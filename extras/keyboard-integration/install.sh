#!/bin/bash
# SoundType keyboard integration — hold-space dictation for Lomiri keyboard.
# Run ON THE PHONE as root:  sudo bash install.sh
# NOTE: patches system files under /usr — an OTA update will overwrite them;
# just re-run this script after each OTA.
set -euo pipefail

KB=/usr/share/maliit/plugins/lomiri-keyboard
DIR="$(cd "$(dirname "$0")" && pwd)"

[ "$(id -u)" = 0 ] || { echo "ERROR: run as root (sudo bash install.sh)"; exit 1; }
[ -f "$DIR/patched/Keyboard.qml" ] || { echo "ERROR: patched/ not found next to install.sh"; exit 1; }
[ -f /home/phablet/soundtype/py/soundtype_dbus_listener.py ] \
    || echo "WARNING: /home/phablet/soundtype/py/soundtype_dbus_listener.py missing — install the SoundType click first"

mount -o remount,rw /

# one-time stock backups (never overwritten on re-install)
[ -f "$KB/Keyboard.qml.stock" ] || cp "$KB/Keyboard.qml" "$KB/Keyboard.qml.stock"
[ -f "$KB/keys/SpaceKey.qml.stock" ] || cp "$KB/keys/SpaceKey.qml" "$KB/keys/SpaceKey.qml.stock"

install -m 644 "$DIR/patched/Keyboard.qml" "$KB/Keyboard.qml"
install -m 644 "$DIR/patched/SpaceKey.qml" "$KB/keys/SpaceKey.qml"

[ -f "$KB/FloatingActions.qml.stock" ] || cp "$KB/FloatingActions.qml" "$KB/FloatingActions.qml.stock"
install -m 644 "$DIR/patched/FloatingActions.qml" "$KB/FloatingActions.qml"
rm -f "$KB/FloatingActions.qml.bak"

sync
mount -o remount,ro / || echo "WARNING: could not remount / read-only (harmless, reboot restores it)"

# systemd user unit for the daemon; the unit file location depends on how
# this directory was deployed: full repo checkout vs extras/ pushed into
# /home/phablet/soundtype/ (README flow)
SVC=""
for cand in "$DIR/../../soundtype-daemon.service" /home/phablet/soundtype/soundtype-daemon.service; do
    if [ -f "$cand" ]; then SVC="$cand"; break; fi
done
if [ -n "$SVC" ]; then
    echo "Installing and restarting soundtype-daemon.service for user phablet..."
    sudo -u phablet bash -c "
        mkdir -p ~/.config/systemd/user/
        cp '$SVC' ~/.config/systemd/user/
        export XDG_RUNTIME_DIR=/run/user/\$(id -u)
        systemctl --user daemon-reload
        systemctl --user enable soundtype-daemon.service
        systemctl --user restart soundtype-daemon.service
    " || echo "WARNING: daemon service install failed — start soundtype-dbus.py manually"
else
    echo "WARNING: soundtype-daemon.service not found — daemon service not installed"
fi

pkill -f maliit-server || true
echo "OK: installed. The keyboard restarts on next focus; hold space (no movement) toggles dictation."
