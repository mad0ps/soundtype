# Changelog

## Unreleased

* Overlap+LCS merge infrastructure at VAD segment boundaries (issue #14):
  `Segmenter` can re-include backward audio context from the previous
  phrase at a junction, and `merge_overlap`/`join_chunk` dedupe the
  re-transcribed overlap via token-LCS. Measured on the 42-clip eval corpus:
  shipped **disabled by default** (`OVERLAP = 0.0`) — every tested width
  (0.1–1.5s) and gate made junction damage and/or aggregate WER worse than
  today's padding-only baseline (root cause: each phrase decodes from a
  cold stream, so the re-included window can be transcribed differently
  the second time and the mismatch gets appended raw instead of deduped).
  See `docs/DECISIONS.md` for the full measurement and rationale; the eval
  harness's `vad` mode now mirrors the prod pipeline (pads, `max_speech`,
  `join_chunk`) and a new `eval.boundary` CLI measures junction damage.
  Also fixes a `Segmenter.feed()` bug (buffer trimmed before early segments
  were drained on large single-call feeds) that only eval's whole-clip
  feeding pattern could trigger.

## 0.9.0 — selectable model profiles

* **Model picker in app settings**: "Multilingual (Parakeet v3)" (default) or
  "Russian (GigaAM-v3 e2e)". The choice persists in `settings.json` and is
  shared by the app and the keyboard daemon.
* **GigaAM-v3 e2e int8** (~330 MB, downloaded on demand from Hugging Face):
  a Russian-specialized model with native punctuation, capitalization and
  «ё» straight from the decoder. On our own dictation corpus it produces
  noticeably more coherent Russian than the multilingual profile
  (see issue #12 for the evaluation data).
* The keyboard daemon picks up a profile switch on the next dictation start
  (or after its idle unload); if the newly selected model is not downloaded
  yet, the keyboard shows the gray indicator instead of hanging busy, and
  the app offers the download.
* The engine announces the actually loaded model in the `ready` event.

## 0.8.0 — dictation in the system keyboard (hold-space)

* **Hold-space gesture**: press and hold the space bar (~0.8 s, haptic
  feedback when ready) and release without moving your finger — recording
  starts; a short tap on space stops it (no space is typed); press and slide
  your finger — the stock touchpad cursor, same as before.
* **Indicator on the space bar** (on the left, where your finger doesn't
  cover it): gray — engine not in memory, yellow — loading or transcribing,
  pulsing red — recording, green — engine in memory, instant start.
* The microphone button in the swipe menu stays — a thin trigger of the same
  shared state, with no logic of its own.
* **Dictation logic moved to the keyboard's persistent layer**
  (`Keyboard.qml`): typing no longer dies when the swipe menu is opened or
  closed.
* **Lazy engine in the daemon + unload after 5 minutes idle**: when idle the
  daemon takes tens of MB instead of ~1 GB resident; after an unload the
  first dictation waits ~5 s for loading (yellow indicator), instant after
  that. `malloc_trim` returns the freed memory to the OS.
* **`extras/keyboard-integration/`** — one-command install: backups of the
  stock files, a systemd unit for the daemon, keyboard restart. `uninstall.sh`
  rolls it back. The patch is wiped by an OTA update — reinstall with the
  same command.
* Based on PR #1 by twicros (the daemon, the D-Bus bridge, the integration
  idea itself) + our gesture, indicator, and unload polish.

## 0.7.0 — Ubuntu Touch 24.04

* Port to UT 24.04 (noble): python wheels for Python 3.12 (numpy 1.26.4,
  sherpa-onnx cp312), framework `ubuntu-touch-24.04-1.x`.
* Experimental system keyboard integration (see PR #1 by twicros + the
  feat/noble-port branch): voice input from the swipe menu, phrases are typed
  character by character as you speak (typewriter effect), the swipe menu
  stays open during dictation. Installed separately, patches the system
  partition, wiped by an OTA update.

## 0.6.0 — streaming transcription

* **Text appears as you record.** VAD splits speech into phrases right in the
  recording loop; a separate thread decodes each phrase immediately while the
  next one is being spoken. After "stop" only the last phrase is left to
  finish — the final result takes seconds instead of 15–21 s on a long
  recording.
* **The app downloads the model itself.** On first launch — a screen with a
  "Download" button (~500 MB, Wi-Fi recommended) and a progress bar. The
  manual `scripts/fetch-deps.py` remains as a wrapper around the same logic.
* **Voice waves** during recording: a ribbon of bars, height = loudness.
* `networking` added to apparmor — solely for the model download; after that
  the app is fully offline, no audio leaves the device.
* "Retry" from history can no longer be started during recording — they
  share a single silence detector.

## 0.5.0

* **"Retry" button** on history entries. Re-asks the model using the saved
  audio; the new text replaces the old one and goes to the clipboard.
* **Audio is kept** for the last 20 recordings (`audio/<ts>.wav`), older
  ones are deleted automatically. Without this there would be nothing to
  retry: history stored only text.
* Entries without audio have no button and are labeled to say there is
  nothing to re-ask with.
* Clearing the history now also deletes the saved recordings.

## 0.4.0 — batch mode

Reworked flow: **recording and recognition no longer overlap**.

* No recognition runs during recording — the microphone reading thread only
  accumulates bytes. Nothing left to lose on pauses.
* All transcription happens after "stop", with "3 of 7" progress.
* The finished text goes **straight to the clipboard** — you can switch to
  another app and paste.
* Recording timer in the header.
* The button is locked while transcribing.
* If nothing was recognized, it says so instead of putting an empty string
  on the clipboard.
* Recording limit of 10 minutes; stops on its own when reached.

## 0.3.0 — history and thread separation

* **Capture and recognition split into separate threads** via a queue. This
  eliminated audio loss: previously recognition was called straight from the
  microphone reading loop, the loop froze on every pause, the PulseAudio
  buffer overflowed, and long dictations came back truncated.
* **Transcription history** in `history.jsonl` with timestamps, a separate
  screen, tapping an entry copies it.
* The field is cleared when the green button is pressed — safe only now that
  the previous text stays in history.
* Continuous phrase ceiling raised from 18 to 40 seconds, detector buffer
  from 60 to 240 seconds.
* Auto-copy after stopping waits for the queue to drain, otherwise truncated
  text ended up on the clipboard.

## 0.2.0 — switch to Parakeet

* Engine switched from Vosk to **Parakeet TDT 0.6B v3** via `sherpa-onnx`.
  Noticeably higher accuracy, 25 languages, Russian and English can be mixed
  in one phrase.
* **The model moved out of the package** into the app's data directory. The
  package slimmed from 49 MB to 10 KB; the model is installed separately by
  a script and survives reinstalls.
* Phrase segmentation by the silero VAD silence detector.
* Result copied to the clipboard.

## 0.1.0 — first working version

* Recognition with **Vosk** (small Russian model), the weights lived right
  inside the click package — hence its 49 MB size.
* Recording via `libpulse-simple` directly through `ctypes`.
* Dropped Vosk over accuracy before this version was published anywhere.
