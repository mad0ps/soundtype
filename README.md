[🇬🇧 English](README.md) | [🇷🇺 Русский](README.ru.md)

# SoundType

Offline dictation for Ubuntu Touch. Speak — and the text lands straight in the input field through the system keyboard!

Recognition happens entirely on the phone: not a single byte leaves the device — no clouds, no API keys, no internet. Works in airplane mode.

**Status:** working release 0.8.0 for Ubuntu Touch 24.04 (noble); for UT 20.04 use [release 0.6.0](https://github.com/mad0ps/soundtype/releases/tag/v0.6.0). Not in the OpenStore yet — installed from source, see [Installation](#installation).

---

## How you use it

### Way 1: The system keyboard (recommended)

Once the integration is installed (see below), dictation lives right in the keyboard:

1. **Hold the space bar** (~0.8 s) without moving your finger — a short
   vibration says "armed". Release — recording starts: the mic on the left
   side of the space bar comes alive, and recognized phrases are **typed into
   the field as you speak**.
2. **A short tap on space** stops the recording (no space character is
   typed). A yellow mic means the tail is still being transcribed.
3. The mic button in the swipe menu (swipe up on the keyboard) does the same.

Mic colors: **gray** — engine not in memory (the first start takes ~5 s),
**yellow** — loading or transcribing, **pulsing red** — recording,
**green** — engine loaded, instant start. After 5 idle minutes the engine
unloads itself from memory.

The stock cursor touchpad still works: hold space and **move your finger**
to drive the cursor, exactly like the stock UT keyboard.

### Way 2: The app
1. Tap the green button — recording starts.
2. Speak as long as you like. Tap the red button — the text is copied to the
   clipboard.
3. Switch to any app and paste.

Transcription takes roughly a quarter of the recording length: a minute of
speech decodes in about fifteen seconds (Snapdragon 690, four threads).

### Why decoding lives in a separate thread

This is the core architectural decision, and it is not cosmetic. The
microphone loop only runs a light VAD (splits speech into phrases) and stores
bytes in memory — the heavy Parakeet decode runs in a separate thread over
finished phrases, in parallel with the recording, never inside the loop.

An early version did it the other way: recognition was called from the read
loop on every pause. The loop froze for over a second, the PulseAudio buffer
overflowed, and live speech **was lost**. Long messages arrived truncated.
That lesson still shapes the architecture: heavy work never blocks the read
loop. Details in `docs/DECISIONS.md`.

### History

Every transcription is saved to `history.jsonl` with a timestamp. Tapping an
entry copies it again.

For the last 20 recordings the audio is kept too — those entries get a
re-transcribe button. Useful when the first attempt failed: out of memory,
app minimized, recognition interrupted. The model is deterministic, so on
healthy audio a retry gives the same result — it is not "try again for luck".

A minute of speech takes about 2 MB; old recordings are deleted
automatically.

---

## Requirements

| | |
|---|---|
| System | Ubuntu Touch 24.04 (noble), arm64 — for 20.04 use [v0.6.0](https://github.com/mad0ps/soundtype/releases/tag/v0.6.0) |
| Disk | ~1.5 GB: 660 MB model, 130 MB libraries |
| Memory | ~1.1 GB with the engine loaded; the keyboard daemon idles at tens of MB (the engine unloads after 5 minutes) |
| Compiler | **not needed** — both the model and the libraries ship as prebuilt binaries |

## Installation

```sh
git clone https://github.com/mad0ps/soundtype.git
cd soundtype

./scripts/build.sh              # builds the click package
./scripts/install.sh            # installs it into the system
```

On first launch the app offers to download the model (~500 MB, Wi-Fi
recommended). `python3 scripts/fetch-deps.py` does the same thing manually.
The `networking` apparmor permission exists only for this download —
recognition is fully offline, audio never leaves the device.

> `pkcon install-local` cannot work here in principle — the PackageKit
> backend on Ubuntu Touch is `aptcc`, which only understands `.deb`. Click
> packages are installed by the `com.lomiri.click` service, which is exactly
> what `install.sh` calls.

---

## Native keyboard integration (daemon mode)

SoundType embeds into the Maliit system keyboard: the hold-space gesture,
a mic button in the swipe menu, and a live indicator on the space bar.

### How it works:
1. **The D-Bus daemon** `soundtype-dbus.py` is a systemd user service
   listening on `com.n0madd3v0ps.soundtype`. It loads the engine lazily and
   unloads it after 5 idle minutes (threshold: the `SOUNDTYPE_IDLE_UNLOAD`
   env var, in seconds).
2. **The QML bridge**: `py/soundtype_dbus_listener.py` runs inside the
   keyboard via `io.thp.pyotherside` and relays daemon signals into QML.
3. **Keyboard patches** (`Keyboard.qml`, `keys/SpaceKey.qml`,
   `FloatingActions.qml`): the gesture, the "typewriter" (character-by-
   character insertion through `event_handler.onKeyReleased`), the
   voice-reactive indicator, the swipe-menu button.

### Installing:

**Warning: this patches the system partition — use at your own risk. An OTA
update overwrites the patch: just re-run install.sh after each OTA.**

One command on the phone (stock-file backups, the daemon's systemd unit and
keyboard restarts are all handled by the script):

```sh
sudo bash extras/keyboard-integration/install.sh
```

Rollback: `sudo bash extras/keyboard-integration/uninstall.sh` (restores
stock files from backups).

Details and the file list:
[`extras/keyboard-integration/README.md`](extras/keyboard-integration/README.md).

---

## Development

Edit `qml/Main.qml` or `py/backend.py`, then:

```sh
./scripts/build.sh && ./scripts/install.sh
```

Close the app before installing, otherwise the old version keeps running.
Watching the logs:

```sh
journalctl -f | grep -i soundtype
```

### From a laptop, deploying to the phone

You can build off-device too. The phone connects over USB, `adb` from the
Android SDK:

```sh
# build the package locally (click is only needed for building)
./scripts/build.sh

# deliver and install
adb push build/*.click /home/phablet/
adb shell "gdbus call --system --dest com.lomiri.click \
    --object-path /com/lomiri/click --method com.lomiri.click.Install \
    /home/phablet/$(basename build/*.click)"
```

The model and libraries must live on the **phone** — `fetch-deps.py` runs
there, once.

The standard Ubuntu Touch development tool is `clickable`: it builds in
Docker and deploys over USB. Our scripts don't conflict with it — they just
build on the device itself.

### Documentation

* [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — internals, QML↔Python
  interchange, what lives where on disk
* [`docs/DECISIONS.md`](docs/DECISIONS.md) — why it is built this way: the
  model, the processing order, storage. With rejected alternatives
* [`docs/ROADMAP.md`](docs/ROADMAP.md) — the development plan (also tracked
  as [issues](https://github.com/mad0ps/soundtype/issues) and
  [milestones](https://github.com/mad0ps/soundtype/milestones))
* [`CHANGELOG.md`](CHANGELOG.md) — what changed between versions

---

## Known limitations

* **In the app** the model stays in memory while the app is open (~1 GB).
  The keyboard daemon unloads it after 5 idle minutes; the app does not yet.
* **AppArmor blocks `onnxruntime`** from `/sys/devices/system/cpu/*`, so it
  cannot detect CPU capabilities and decodes slower than it could. In the
  log this shows as `Unknown CPU vendor`.
* **No automatic retry** when a single phrase fails to decode — it is
  dropped and an error is logged.
* **Not in the OpenStore.** The model size is not a problem there — the app
  downloads it on first launch. But an interrupted download restarts from
  scratch, and the store submission itself has not been done yet.

## License

GPL-3.0, see [LICENSE](LICENSE).

`extras/` also contains things unrelated to the app: patches for
`terminal.ubports` that came up along the way. Details in the files
themselves.
