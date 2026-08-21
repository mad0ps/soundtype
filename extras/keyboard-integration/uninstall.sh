#!/bin/bash
set -e

echo "Uninstalling SoundType Keyboard Integration..."

echo "1. Stopping and disabling systemd user service..."
systemctl --user disable --now soundtype-daemon.service || true
rm -f ~/.config/systemd/user/soundtype-daemon.service
systemctl --user daemon-reload

echo "2. Restoring original FloatingActions.qml (requires sudo)..."
sudo mount -o remount,rw /
if [ -f "/usr/share/maliit/plugins/lomiri-keyboard/FloatingActions.qml.bak" ]; then
    sudo cp /usr/share/maliit/plugins/lomiri-keyboard/FloatingActions.qml.bak /usr/share/maliit/plugins/lomiri-keyboard/FloatingActions.qml
else
    echo "Warning: Backup file not found!"
fi

echo "3. Restarting Maliit Keyboard server..."
systemctl --user restart maliit-server

echo "Uninstallation complete!"
