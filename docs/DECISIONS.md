# Decisions

This file records why things are done the way they are, and what was rejected.
The point is to avoid re-fighting battles that have already been settled — and
to make it visible where a decision rests on measurements and where on gut
feeling.

---

## Recognition engine: Parakeet TDT 0.6B v3 via sherpa-onnx

**Why this one.** A single model covering 25 languages, including Russian and
English, and they can be mixed **within one phrase** — "закоммить в докер" is
recognized as a whole. Ready-made ONNX weights with int8 quantization, 660 MB.
Runs via `sherpa-onnx`, which installs as a wheel for `cp312/aarch64` — **no
compiler and no `torch` needed at all**, which is decisive on a phone.

**What was rejected:**

| Option | Why not |
|---|---|
| **Vosk** (small Russian model) | Noticeably worse accuracy. We started with it and dropped it before the first release |
| **Whisper via cloud** (OpenAI/Groq) | Needs an API key and internet, audio goes to someone else's server. Contradicts the whole point of the app |
| **GigaAM-v3** from Sber | Tempting: WER ~3.3% vs ~8% for Whisper large-v3 on Russian, weights only 428 MB. But: Russian only — language mixing is lost; installs via `pip` and pulls in `torch` (~3 GB), unmanageable on a phone; no sherpa-onnx builds in any release — verified by searching every tag. The path would be a do-it-yourself ONNX export on a desktop with an uncertain outcome |

GigaAM is worth revisiting if a ready sherpa-onnx build appears or if language
mixing turns out to be unnecessary. *(Update 2026-08: community sherpa-onnx
conversions of GigaAM-v3 now exist on HF — tracked as the "pure Russian
profile" item in ROADMAP phase 2.)*

---

## Order of operations: record first, recognize after

Recording and recognition **do not overlap in time**. While recording is in
progress, the microphone read loop does nothing heavy.

**How we got here.** At first it was the other way around — recognition ran on
the fly, right in the read loop:

```python
while not stop:
    pa_simple_read(...)      # 0.256 s of audio
    vad.accept_waveform(...)
    self._drain()            # ← recognition HERE, blocks the loop
```

Every pause in speech triggered transcription, the loop stalled for over a
second, and the PulseAudio buffer overflowed. **Long dictations came back
truncated** — and it wasn't a rare glitch but a systematic loss on every pause.

The intermediate variant — a queue and a separate recognition thread —
eliminated the loss. But we ultimately moved to batch mode: it's simpler, has
no contention for the CPU, and better fits how the app is actually used —
dictate, stop, grab the text.

**Side benefit:** the ceiling for a continuous phrase went up from 18 to 30
seconds, and the audio stays in memory in full — which is what made
re-recognition possible.

---

## Audio: libpulse-simple via ctypes

Not GStreamer and not `arecord`. Inside confinement a direct library call is
more reliable and pulls in no dependencies. The format is exactly what the
model needs from the start — 16 kHz, mono, s16le — nothing to convert.

---

## Clipboard: hidden TextEdit

A confined app has no dedicated API. The text goes into an invisible
`TextEdit`, followed by `selectAll()` and `copy()`.

**A direct D-Bus call does not work.** The `CreatePaste` method of the
`com.lomiri.content.dbus.Service` service returns a refusal when called from a
console — verified both with raw text and with proper `QMimeData`
serialization. The clipboard is tied to the app's graphical surface, and a
console program has none.

---

## Keeping audio for retry: the last 20 recordings

The "retry" button needs saved audio — a transcription cannot be reconstructed
from text.

A minute of speech is about 2 MB. Twenty recordings — tens of megabytes,
acceptable. Old ones are deleted automatically; the history text is kept in full.

**What retry does NOT give you.** The model is deterministic: on intact audio
the result will be the same. Retry helps when the first attempt **failed** —
ran out of memory, the app got backgrounded, recognition died with an error.
It is not "press again, maybe it recognizes better this time".

For retry to produce a **different** result, the conditions have to change:
the phrase segmentation parameters or the model itself. That is a separate task.

---

## Clearing the field when recording starts

The field is cleared when you press the green button. This became safe only
after history appeared: before it, the previous transcription would have been
lost for good.

The order matters: history first, then clearing.

---

## Installation: the com.lomiri.click service, not pkcon

`pkcon install-local` for click packages on Ubuntu Touch **does not work at
all**: the PackageKit backend here is `aptcc`, which is about `.deb`. The
error masquerades as "file not found", which is misleading.

Click packages are installed by the privileged `com.lomiri.click` service —
the same one OpenStore uses. It runs as root, but the D-Bus policy allows any
user to call it — **no password needed**.

---

## Dependencies stay out of git

The model (660 MB) and the wheels (130 MB) are not committed to the
repository — otherwise the clone would become unmanageable.
`scripts/fetch-deps.py` downloads them straight into the app's data directory.

The wheels are unpacked manually via `zipfile`: there is no `pip` on the
device, and a wheel is just a zip.

---

## Open questions

**Model stays in memory (app path).** It takes about 1 GB. Since 0.8.0 the
keyboard daemon loads the engine lazily and unloads it after 5 idle minutes
(`malloc_trim` returns the memory to the OS: tens of MB idle). The GUI app
still keeps the model resident while open — unloading there is an open task.

**OpenStore.** It hosts a ready `.click`, and ours depends on a 660 MB model.
In-app download on first launch was implemented in 0.6, with progress — but
without resume after interruption: a failed download restarts the file from
scratch (`py/downloader.py`). The OpenStore publication itself hasn't happened.

**Auto-retry on failure.** If recognizing a single phrase dies with an
exception, it is currently just lost — the error is logged, and the remaining
phrases keep being processed. An honest auto-retry (failed → try again →
only then report) looks reasonable.

---

## Back to decoding during recording — but not the 0.2 way

In 0.2 recognition was called right from the microphone read loop and dropped
audio; in 0.4 we moved to batch mode. In 0.6 decoding runs during recording
again, but the architecture is different, and the 0.2 pitfalls do not carry over:

* The recording loop runs only lightweight VAD (silero, 512-sample window,
  ~ms per window). Heavy decoding lives in a separate thread behind a
  `queue.Queue`; sherpa-onnx releases the GIL while decoding, so the threads
  are genuinely parallel.
* Measured on the N10 (int8, 4 threads): 84 s of audio → 14.8 s of decoding
  with VAD (~5.7x). Decoding keeps up with recording with room to spare.
* The sherpa-onnx #2918 trap is accounted for: only the current segment is
  decoded, the growing buffer is never re-decoded.
* The architecture reference is FluidAudio/Spokenly (decoding VAD segments in
  the background, only the last phrase on stop). We copy the idea, not the
  code: their streaming model and the Apple Neural Engine are out of our reach.

Spec with measurements: `docs/specs/2026-08-20-streaming-selfdownload-waveform.md`.

**Download atomicity (C1, 0.6.1).** `missing()` decides what to download with
a plain `os.path.exists` check — no checksums, no sizes. This is safe ONLY
because every writer in `py/downloader.py` places its file/directory
atomically: `fetch_silero` downloads to a temporary `*.part` and renames
(`os.replace`) on success; `fetch_wheels`/`fetch_parakeet` unpack into a
temporary directory and move the finished tree as a whole. A new writer that
streams data straight to the final path silently breaks this assumption — an
interruption midway leaves a partially complete file/directory that
`missing()` will count as present.

## Silero VAD stays

We previously discussed dropping VAD for better quality at segment boundaries.
Cancelled: VAD IS the streaming segmentation mechanism. We cut at pauses;
words are not torn apart.

## Backward-only overlap + token-LCS dedupe at VAD junctions (issue #14) — shipped disabled

VAD-cut segments still lose or garble the word right at the cut (edge-word
degradation from missing acoustic context) even with the existing
`PAD_PRE`/`PAD_POST` ring-buffer padding, which only pads with raw audio and
doesn't give the model a running decode to continue from. The plan: have
each phrase's slice re-include the last `OVERLAP` seconds of the *previous*
phrase's audio, decode it as usual, then use a token-level LCS
(`merge_overlap`) to strip whatever got re-transcribed, keeping only the new
words. Overlap direction is backward-only by construction — streaming
cannot wait for audio that hasn't been recorded yet — unlike NVIDIA's
symmetric (left+right) chunking used in offline batch transcription, which
was rejected outright for this reason (not applicable to a live stream).
The alternative of simply widening the static pads without any dedupe was
also rejected: bigger pads just re-decode more of the neighboring phrase's
audio as duplicate text with nothing to remove it.

**Measured effect (2026-08-25 tuning pass,
`eval/reports/boundary-overlap-tuning.md`, local — not committed, contains
corpus transcripts):** the parity baseline (today's prod pipeline, pads on,
`overlap=0`) measures 58 junctions, 24 damaged (41%), aggregate WER 18.08%
on the 42-clip eval corpus. Turning overlap on **made both metrics worse at
every tested width** (0.1, 0.2, 0.5, 1.0 — the plan's default, 1.5
seconds): damaged% ranged 36–81% (worse than parity except at the very
smallest widths, which still failed the WER guard), aggregate WER regressed
+0.58 to +2.12 percentage points (guard was ≤+0.5pp). A follow-up targeted
experiment narrowed `OVERLAP_GAP_MAX` from 2.0s to 0.3s so overlap only
fires on `max_speech`-forced cuts and instant VAD re-opens (where the
"next" phrase is provably a continuation of the same utterance, not a
different mid-sentence fragment) — WER came back clean (18.04%,
-0.04pp), but the one junction in the whole corpus that qualified for this
gate still came out *more* damaged than parity (2/2 vs 1/2 junctions
damaged), the same failure mode reproducing even on a genuine forced-cut
continuation.

**Root cause:** both the live and eval decode paths call
`recognizer.create_stream()` **per phrase** (no decoder state carried
across phrases). The re-included overlap window therefore gets transcribed
twice under different acoustic conditions — once with full left context as
the tail of the previous, longer utterance, once cold as the entire leading
content of a fresh stream — and a transducer model frequently produces
different wording for the second case, up to outright hallucination
(observed: a two-word Russian phrase hallucinated wholesale at a junction,
absent from any reference). When the two transcriptions share no common
token, `merge_overlap`'s LCS has nothing to match, and `join_chunk` appends
the divergent text raw instead of deduping it. No case of the *opposite*
failure (over-aggressive LCS matching deleting genuine repeated words) was
observed in any run, so `LCS_MIN_MATCH` is not a useful lever here — the
problem is decode divergence, not a matching threshold.

**Decision:** ship the infrastructure (`merge_overlap`, `join_chunk`'s
overlap branch, `Segmenter`'s overlap plumbing, the `eval` harness that
proved all of this) but set `OVERLAP = 0.0` by default — the mechanism is
present and unit-tested, reachable via `--overlap` in `eval.run_model` or by
setting `OVERLAP` in `py/streaming.py` for further experimentation, but off
in prod until it can carry decoder state across adjacent phrases (or be
redesigned as a textual stitch that never re-transcribes already-decoded
audio). `PAD_PRE`/`PAD_POST` (unrelated, already in prod) are untouched.
Edge-word degradation at ordinary VAD pauses remains open — issue #14
should stay open past this task pending a redesign, rather than being
closed on infrastructure that measured net-negative.
