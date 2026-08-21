#!/bin/bash
set -e

# Get the absolute path of the directory where this script is located
SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" &> /dev/null && pwd)
REPO_ROOT=$(dirname $(dirname "$SCRIPT_DIR"))
SOUNDTYPE_PY_PATH="$REPO_ROOT/py"
SOUNDTYPE_DAEMON_EXEC="$SCRIPT_DIR/soundtype-dbus.py"

echo "Installing SoundType Keyboard Integration..."

echo "1. Patching FloatingActions.qml with dynamic path..."
sed "s|SOUNDTYPE_PY_PATH|$SOUNDTYPE_PY_PATH|g" "$SCRIPT_DIR/FloatingActions.qml.template" > "$SCRIPT_DIR/FloatingActions.qml"

echo "2. Patching soundtype-daemon.service with dynamic path..."
sed "s|SOUNDTYPE_DAEMON_EXEC|$SOUNDTYPE_DAEMON_EXEC|g" "$SCRIPT_DIR/soundtype-daemon.service.template" > "$SCRIPT_DIR/soundtype-daemon.service"

echo "3. Backing up original FloatingActions.qml (requires sudo)..."
sudo mount -o remount,rw /
if [ ! -f "/usr/share/maliit/plugins/lomiri-keyboard/FloatingActions.qml.bak" ]; then
    sudo cp /usr/share/maliit/plugins/lomiri-keyboard/FloatingActions.qml /usr/share/maliit/plugins/lomiri-keyboard/FloatingActions.qml.bak
fi

echo "4. Installing patched FloatingActions.qml..."
sudo cp "$SCRIPT_DIR/FloatingActions.qml" /usr/share/maliit/plugins/lomiri-keyboard/FloatingActions.qml

echo "5. Moving listener script to $SOUNDTYPE_PY_PATH..."
cp "$SCRIPT_DIR/soundtype_dbus_listener.py" "$SOUNDTYPE_PY_PATH/"

echo "6. Enabling and starting systemd user service..."
mkdir -p ~/.config/systemd/user/
cp "$SCRIPT_DIR/soundtype-daemon.service" ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now soundtype-daemon.service

echo "7. Restarting Maliit Keyboard server..."
systemctl --user restart maliit-server

echo "Installation complete! NOTE: OTA updates overwrite the system partition. You will need to re-run this script after any OS update."
