#!/usr/bin/env bash
# Удаляет ярлык и (по желанию) окружение VoiceCode.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PURGE=0
[[ "${1:-}" == "--purge" ]] && PURGE=1

rm -f "$HOME/.local/share/applications/voicecode.desktop"
rm -f "$HOME/.local/share/icons/hicolor/scalable/apps/voicecode.svg"
rm -f "$HOME/.config/autostart/voicecode.desktop"

if [[ "$PURGE" -eq 1 ]]; then
  rm -rf "$ROOT/.venv" "$ROOT/models"
  rm -rf "${XDG_DATA_HOME:-$HOME/.local/share}/voicecode"
  rm -rf "${XDG_STATE_HOME:-$HOME/.local/state}/voicecode"
  rm -rf "${XDG_CACHE_HOME:-$HOME/.cache}/voicecode"
  echo "Удалены окружение, модели, данные агента, логи и кэш."
  echo "Настройки в ~/.config/voicecode оставлены."
else
  echo "Ярлыки удалены. Окружение и модели оставлены (--purge удалит и их)."
fi
