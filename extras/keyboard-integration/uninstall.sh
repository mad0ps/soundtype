#!/bin/bash
# Restore stock Lomiri keyboard files. Run ON THE PHONE as root: sudo bash uninstall.sh
set -euo pipefail

KB=/usr/share/maliit/plugins/lomiri-keyboard

[ "$(id -u)" = 0 ] || { echo "ERROR: run as root (sudo bash uninstall.sh)"; exit 1; }

mount -o remount,rw /

for pair in "$KB/Keyboard.qml" "$KB/keys/SpaceKey.qml" "$KB/FloatingActions.qml"; do
    if [ -f "$pair.stock" ]; then
        mv "$pair.stock" "$pair"
        echo "restored: $pair"
    else
        echo "WARNING: $pair.stock missing — nothing to restore"
    fi
done

sync
mount -o remount,ro / || echo "WARNING: could not remount / read-only (harmless, reboot restores it)"

# restart the keyboard via systemd: after a plain pkill it only respawns on
# input focus, which never comes on the lockscreen — leaving the user unable
# to type the passphrase
sudo -u phablet bash -c "
    export XDG_RUNTIME_DIR=/run/user/\$(id -u)
    systemctl --user restart maliit-server
" || pkill -f maliit-server || true
echo "OK: stock keyboard restored."
