#!/bin/sh
# Собирает click-пакет из исходников репозитория.
set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="$ROOT/build"
STAGE="$OUT/soundtype"

rm -rf "$STAGE"
mkdir -p "$STAGE"

cp -r "$ROOT/qml" "$ROOT/py" "$ROOT/assets" "$STAGE/"
cp "$ROOT/manifest.json" "$ROOT/soundtype.apparmor" "$ROOT/soundtype.desktop" "$STAGE/"
find "$STAGE" -name '__pycache__' -type d -exec rm -rf {} + 2>/dev/null || true

cd "$OUT"
click build soundtype
echo
echo "Готово. Установить:  ./scripts/install.sh"
