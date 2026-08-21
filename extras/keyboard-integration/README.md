# SoundType keyboard integration (hold-space dictation)

Voice dictation built into the Lomiri system keyboard on Ubuntu Touch 24.04.

## How it works

- **Hold space (~0.8s, haptic pulse when armed), release without moving** →
  start dictation.
- **Short tap on space while recording** → stop dictation (no space typed).
- **Hold space and move** → cursor-swipe touchpad, exactly like stock.
- **Mic button in the swipe menu** → same toggle, for swipe-menu fans.
- Mic indicator on the left side of the space key (the right side hides
  under your finger during a hold): gray = engine not in memory (first start
  takes ~5s), yellow = loading or transcribing, pulsing red = recording,
  green = engine loaded, instant start.
- The daemon loads the engine lazily and unloads it after 5 idle minutes
  (override with the SOUNDTYPE_IDLE_UNLOAD env var, seconds): tens of MB
  idle instead of a resident ~1GB.
- Recognized phrases are typed character by character ("typewriter") as they
  arrive from the SoundType daemon over D-Bus (`com.n0madd3v0ps.soundtype`).
- The listener lives in `Keyboard.qml` (the keyboard's permanent layer), so
  typing survives opening/closing the swipe menu.

## Files

- `patched/Keyboard.qml` — pyotherside D-Bus listener + typewriter + dictation state
- `patched/SpaceKey.qml` — hold-space gesture + tap-to-stop + mic indicator
- `patched/FloatingActions.qml` — mic button in the swipe menu (uses the shared state)
- `stock/` — pristine noble (24.04, lomiri-keyboard-data) copies for reference/revert
- `install.sh` / `uninstall.sh` — run on the phone as root

## Install

Requires the SoundType click installed and its keyboard daemon running
(`/home/phablet/soundtype/soundtype-dbus.py`).

```sh
adb push extras/keyboard-integration /home/phablet/soundtype/keyboard-integration
adb shell
sudo bash /home/phablet/soundtype/keyboard-integration/install.sh
```

The script backs up the stock files (one-time `.stock` copies), installs the
daemon's systemd user unit and restarts both the daemon and maliit-server —
no manual steps.

An OTA update overwrites `/usr` — re-run `install.sh` after each OTA.
