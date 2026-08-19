#!/bin/sh
# Ставит собранный click через привилегированный сервис Lomiri.
#
# pkcon здесь не годится: бэкенд PackageKit на Ubuntu Touch — aptcc,
# он умеет только .deb и наш .click не понимает. Установкой click-пакетов
# занимается com.lomiri.click, тот же сервис использует OpenStore.
set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

CLICK=$(ls -t "$ROOT/build"/*.click 2>/dev/null | head -1)
if [ -z "$CLICK" ]; then
    echo "Пакет не найден. Сначала собери:  ./scripts/build.sh" >&2
    exit 1
fi

# Сервис работает от root и должен видеть файл, поэтому кладём его
# в домашний каталог с правами на чтение всем.
TMP="$HOME/$(basename "$CLICK")"
cp "$CLICK" "$TMP"
chmod 644 "$TMP"

echo "Ставлю $(basename "$CLICK")…"
gdbus call --system --dest com.lomiri.click \
    --object-path /com/lomiri/click \
    --method com.lomiri.click.Install "$TMP"

sleep 3
click list | grep -i soundtype || echo "Не появилось в списке — посмотри журнал: journalctl -f"
