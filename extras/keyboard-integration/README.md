# SoundType keyboard integration (hold-space dictation)

Voice dictation built into the Lomiri system keyboard on Ubuntu Touch 24.04.

## How it works

- **Hold space, don't move, release** → toggle dictation (start/stop).
- **Hold space and move** → cursor-swipe touchpad, exactly like stock.
- Mic indicator next to the language label on the space key:
  gray = ready, pulsing red = recording, orange = transcribing.
- Recognized phrases are typed character by character ("typewriter") as they
  arrive from the SoundType daemon over D-Bus (`com.n0madd3v0ps.soundtype`).
- The listener lives in `Keyboard.qml` (the keyboard's permanent layer), so
  typing survives opening/closing the swipe menu.

## Files

- `patched/Keyboard.qml` — pyotherside D-Bus listener + typewriter + dictation state
- `patched/SpaceKey.qml` — hold-space gesture + mic indicator
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

An OTA update overwrites `/usr` — re-run `install.sh` after each OTA.
