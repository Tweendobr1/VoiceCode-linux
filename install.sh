#!/usr/bin/env bash
# Установка VoiceCode на Arch Linux (venv + зависимости pacman).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

SKIP_DEPS=0
SKIP_MODEL=0
AUTOSTART=0
for argument in "$@"; do
  case "$argument" in
    --skip-deps) SKIP_DEPS=1 ;;
    --skip-model) SKIP_MODEL=1 ;;
    --autostart) AUTOSTART=1 ;;
    -h|--help)
      echo "Использование: ./install.sh [--skip-deps] [--skip-model] [--autostart]"
      exit 0
      ;;
    *) echo "Неизвестный аргумент: $argument" >&2; exit 2 ;;
  esac
done

if ! command -v pacman >/dev/null 2>&1; then
  echo "Этот установщик рассчитан на Arch Linux (pacman не найден)." >&2
  exit 1
fi

if ! command -v python >/dev/null 2>&1; then
  echo "Не найден python. Установи: sudo pacman -S python" >&2
  exit 1
fi

if [[ "$SKIP_DEPS" -eq 0 ]]; then
  echo "==> Системные пакеты"
  PACKAGES=(
    python python-pip pyside6 python-numpy python-av
    python-evdev portaudio ffmpeg espeak-ng
    xdg-utils libnotify procps-ng
    grim xdotool
  )
  sudo pacman -S --needed --noconfirm "${PACKAGES[@]}"
fi

echo "==> Виртуальное окружение .venv"
python -m venv --system-site-packages .venv
.venv/bin/python -m pip install --upgrade pip wheel >/dev/null
.venv/bin/python -m pip install -r requirements.txt

if [[ "$SKIP_MODEL" -eq 0 ]]; then
  if [[ ! -f models/faster-whisper-small/model.bin ]]; then
    echo "==> Модель Whisper small (~250 МБ)"
    .venv/bin/python tools/fetch_model.py --size small || {
      echo "Модель не скачалась — VoiceCode попробует скачать её при первом запуске." >&2
    }
  else
    echo "==> Модель Whisper уже на месте"
  fi
fi

echo "==> Ярлык и иконка"
chmod +x "$ROOT/run.sh" "$ROOT/run-debug.sh" "$ROOT/uninstall.sh"
APPLICATIONS="$HOME/.local/share/applications"
ICONS="$HOME/.local/share/icons/hicolor/scalable/apps"
mkdir -p "$APPLICATIONS" "$ICONS"
cp packaging/voicecode.svg "$ICONS/voicecode.svg"
sed -e "s|@EXEC@|$ROOT/run.sh|g" -e "s|@ICON@|$ICONS/voicecode.svg|g" \
  packaging/voicecode.desktop.in > "$APPLICATIONS/voicecode.desktop"
command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database "$APPLICATIONS" >/dev/null 2>&1 || true

if [[ "$AUTOSTART" -eq 1 ]]; then
  mkdir -p "$HOME/.config/autostart"
  cp "$APPLICATIONS/voicecode.desktop" "$HOME/.config/autostart/voicecode.desktop"
  echo "==> Автозапуск добавлен"
fi

if ! id -nG "$USER" | tr ' ' '\n' | grep -qx input; then
  echo
  echo "Глобальная клавиша F8 на Wayland требует доступа к /dev/input:"
  echo "    sudo usermod -aG input $USER"
  echo "После этого перезайди в сессию. На X11 F8 работает и без этого (pynput)."
fi

echo
echo "Готово. Проверка: bash run.sh --debug"
echo "Диагностика:  .venv/bin/python tools/warmup.py"
echo "Запуск:       bash run.sh  (или ярлык VoiceCode в меню)"
