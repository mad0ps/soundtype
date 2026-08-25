# How it works

The app consists of two halves: the UI in QML and all audio work in Python.
Between them sits [pyotherside](https://github.com/thp/pyotherside), a QML
plugin that can call Python functions and receive events back.

```
  Main.qml  ──calls──▶  backend.py  ──ctypes──▶  libpulse-simple  (microphone)
     ▲                        │
     └──────events────────────┤──────────────────▶  silero VAD     (segmentation)
                              └──────────────────▶  Parakeet       (recognition)
                                                    via sherpa-onnx
```

No `torch`, no compiler: `sherpa-onnx` installs as a prebuilt wheel for
`cp312/aarch64` (noble; the 20.04 branch used cp38), and the model already
comes in ONNX format with int8 quantization.

---

## QML ↔ Python communication

**QML calls Python** (`py.call("backend.<name>", [args], handler)`):

| Function | What it does |
|---|---|
| `init()` | Loads the model in a background thread |
| `start()` | Starts recording |
| `stop()` | Stops recording and kicks off transcription |
| `retry(ts)` | Re-runs the model on the saved audio of recording `ts` |
| `history_list()` | Returns the history, newest entries first |
| `history_clear()` | Wipes the history along with the audio |
| `fetch_deps()` | Downloads the model and libraries, reporting progress |

**Python sends events** (`pyotherside.send(...)`), QML catches them via
`setHandler`:

| Event | Arguments | When |
|---|---|---|
| `status` | — | Model loading has started |
| `ready` | model name | Model loaded, the button comes alive |
| `recording` | `bool` | Recording started / stopped |
| `elapsed` | seconds | Timer tick while recording |
| `level` | 0…1 | Volume, for the ring around the button |
| `transcribing` | `bool` | Transcription started / finished |
| `progress` | index, total | Processing the next phrase |
| `final` | text, `ts` | Finished transcription |
| `done` | text | Everything done — QML puts the text on the clipboard |
| `retried` | `ts`, text | Result of re-recognition |
| `error` | message | Any error |
| `partial` | index, text | Phrase recognized mid-recording |
| `deps-missing` | list | Model/libraries missing — download screen needed |
| `download-progress` | stage, % | Download progress (−1 — size unknown) |
| `download-done` | — | Everything downloaded, engine loads next |
| `download-error` | message | Download failed, can be retried |

All sixteen events must have a counterpart in `Main.qml`. If you add a new
one — don't forget the `setHandler`, or it will simply get lost without warning.

---

## Recording

The recording thread does nothing but read the microphone. This is a hard
rule: any heavy work in this loop overflows the PulseAudio buffer and drops
live speech.

```
libpulse-simple (ctypes)
    format   s16le, 16 kHz, mono
    reads    4096 bytes = 2048 samples = 0.128 s at a time
    accumulates chunks in a list, joined at the end
    limit    MAX_RECORD_SECONDS = 600 (about 38 MB in memory)
```

PulseAudio is accessed directly via `ctypes`, not through GStreamer — inside
confinement this is more reliable and avoids extra dependencies.

Since 0.6 the read loop additionally runs VAD (512-sample windows): completed
phrases go through a queue to the decode thread (`py/streaming.py`). The loop
still does no heavy work — decoding runs in another thread, and sherpa-onnx
releases the GIL. Reads are 4096 bytes = 2048 samples = 0.128 s.

## Transcription

Since 0.6 it happens while recording: VAD slices the accumulated audio into
phrases right in the microphone read loop, and each completed phrase goes
straight into a queue and is recognized by a background thread, without
waiting for recording to stop. On stop, only the last, still-open phrase is
finished off. The batch path (`Dictation._transcribe`) remains for "retry"
from history — there the audio already sits on disk, and slicing/recognizing
it whole in one pass is cheaper than setting up a stream.

```
1. Phrase segmentation  silero VAD, 512-sample windows
                        threshold 0.5, silence 1.0 s, speech from 0.25 s
                        max phrase length MAX_SPEECH = 30 s
                        detector buffer VAD_BUFFER_SECONDS = 120 s
                        ring-buffer padding around segments: 0.4 s before,
                        0.25 s after (sherpa-onnx clips edges otherwise)

2. Recognition          Parakeet TDT 0.6B v3 (int8), 4 threads
                        each phrase in a separate call
                        phrases shorter than 0.2 s are skipped

3. Joining              sentence-aware glue: the first phrase and phrases
                        after sentence-final punctuation are capitalized;
                        a pause ≥1.5 s with no model punctuation inserts
                        ". "; otherwise a plain space
```

Backward overlap + token-LCS dedupe at junctions (issue #14): `Segmenter`
can optionally re-include the last `OVERLAP` seconds of audio from the
*previous* phrase at the start of the next phrase's slice (only when the
gap between them is ≤ `OVERLAP_GAP_MAX`), so the next phrase's decode has
left acoustic context instead of starting cold at a hard VAD cut.
`merge_overlap` then looks for a run of ≥ `LCS_MIN_MATCH` matching
normalized tokens between the end of the already-accepted text and the
start of the new phrase's text, and strips the duplicate; `join_chunk` is
the single call site both the live and batch paths use. Overlap only looks
backward — a live stream cannot wait for audio that hasn't arrived yet, so
unlike offline chunking schemes (e.g. NVIDIA's symmetric left+right
overlap) this only ever reaches into the past.

As of the 2026-08-25 tuning pass (`eval/reports/boundary-overlap-tuning.md`,
local) **`OVERLAP` defaults to `0.0` — the mechanism is disabled**. Each
phrase is decoded from a cold offline-recognizer stream (no state carried
between phrases), so the re-included overlap window gets transcribed twice
under different conditions and can come out worded differently each time;
when the two transcriptions share no common tokens `merge_overlap` can't
dedupe them and the divergent text is appended raw, which measured *worse*
junction damage and WER than leaving it off across every width (0.1–1.5s)
and gate (`OVERLAP_GAP_MAX`) tested. The code, and its unit tests, stay in
place — `--overlap` in `eval.run_model` and manually setting `OVERLAP` in
`py/streaming.py` remain the way to experiment with it — but it needs
decoder-state continuity across phrases (or a non-re-decoding textual
stitch) before it can ship on by default.

If the detector finds no boundaries at all, the whole recording goes to the
model in one piece — better that than silently returning nothing.

Speed: about 0.27 seconds of compute per second of audio. Model load at
startup — roughly 5 seconds.

The batch path (`_split` → `_decode` in sequence) remains for "retry" from
history; the segmentation is the same — `streaming.Segmenter`.

---

## What lives where

```
~/.local/share/soundtype.n0madd3v0ps/
├── models/
│   ├── parakeet/
│   │   ├── encoder.int8.onnx     652 MB
│   │   ├── decoder.int8.onnx      12 MB
│   │   ├── joiner.int8.onnx        6 MB
│   │   └── tokens.txt             vocabulary
│   └── silero_vad.onnx           644 KB
├── runtime/pylibs/               numpy + sherpa_onnx, unpacked wheels
├── history.jsonl                 one JSON line per transcription: ts, text
└── audio/<ts>.wav                audio of the last AUDIO_KEEP = 20 recordings
```

`history.jsonl` is appended line by line, and rewritten in full only on
re-recognition — when the text of a single entry has to be replaced.
The `HISTORY_LIMIT = 500` cap is applied at read time; the file is not truncated.

The `runtime/pylibs` directory is added to `sys.path` on the first line of
`backend.py` — before `numpy` and `sherpa_onnx` are imported.

---

## Clipboard

A confined app has no dedicated clipboard API. A workaround is used: a hidden
`TextEdit` — the text is put into it, followed by `selectAll()` and `copy()`.

It looks like a hack, but it is the working path: the journal shows the
`com.lomiri.content.dbus.Service` service accepting `CreatePaste` from the app.
Calling `CreatePaste` directly over D-Bus from a console does not go through —
the clipboard is tied to a graphical surface, and a console program has none.

## Permissions

`soundtype.apparmor` requests three policy groups:

```json
["microphone", "audio", "keep-display-on", "networking"]
```

`content_exchange` is not needed: copying via `TextEdit` works without it.
`networking` exists solely for the model self-download (0.6.0+).

At startup the journal will always show AppArmor denials on
`/sys/devices/system/cpu/*` — that's `onnxruntime` trying to identify the CPU.
Not an error, but because of them it can't see the CPU's capabilities and
computes slower.

---

## Build

`click build` requires that only the app's files sit next to `manifest.json`.
So `scripts/build.sh` assembles the contents into `build/soundtype/` and
packages from there, not from the repository root.

The model and libraries are **not included** in the package — they live in the
data directory and survive app reinstalls.
