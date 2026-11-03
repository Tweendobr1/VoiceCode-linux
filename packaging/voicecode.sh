#!/bin/sh
# Запуск установленного пакета: конфиг живёт в ~/.config/voicecode.
set -eu

CONFIG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/voicecode"
CONFIG="$CONFIG_DIR/config.json"
if [ ! -f "$CONFIG" ]; then
  mkdir -p "$CONFIG_DIR"
  cp /usr/share/voicecode/config.json "$CONFIG"
fi

exec /usr/bin/python3 /opt/voicecode/main.py --config "$CONFIG" "$@"
