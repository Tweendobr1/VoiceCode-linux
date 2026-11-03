#!/usr/bin/env python3
"""Проверка окружения VoiceCode на Arch Linux."""

from __future__ import annotations

import importlib
import os
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from voicecode.audio.speech import edge_reachable  # noqa: E402
from voicecode.config import Config  # noqa: E402
from voicecode.opencode import OpenCodeClient  # noqa: E402
from voicecode.paths import (  # noqa: E402
    APP_DIR,
    CONFIG_HOME,
    CONFIG_PATH,
    LOG_DIR,
    models_dir,
)
from voicecode.stt import Transcriber  # noqa: E402

OK = "✓"
BAD = "✗"
WARN = "!"
problems: list[str] = []


def line(mark: str, label: str, detail: str = "") -> None:
    print(f"  {mark} {label}" + (f" — {detail}" if detail else ""))


def check_import(name: str, required: bool = True) -> bool:
    try:
        module = importlib.import_module(name)
        version = getattr(module, "__version__", "")
        line(OK, f"python: {name}", version)
        return True
    except Exception as exc:
        line(BAD if required else WARN, f"python: {name}", str(exc))
        if required:
            problems.append(f"нет модуля {name}")
        return False


def main() -> int:
    print("\nVoiceCode — проверка окружения\n")
    user_config = CONFIG_HOME / "voicecode" / "config.json"
    cfg = Config.load(user_config if user_config.exists() else CONFIG_PATH)
    print(f"  Конфиг: {cfg.path}")
    print(f"  Проект: {APP_DIR}")
    print(f"  Модели: {models_dir()}")
    print(f"  Логи:   {LOG_DIR}")

    print("\nPython")
    print(f"  {OK} {sys.version.split()[0]} ({sys.executable})")
    for name in ("PySide6", "numpy", "sounddevice", "faster_whisper", "edge_tts", "av"):
        check_import(name)
    check_import("evdev", required=False)
    check_import("pynput", required=False)

    print("\nСессия")
    session = os.environ.get("XDG_SESSION_TYPE") or "не определена"
    desktop = os.environ.get("XDG_CURRENT_DESKTOP") or "не определено"
    print(f"  Session: {session}, desktop: {desktop}")
    if session == "wayland":
        line(WARN, "Wayland", "окна и громкость зависят от композитора")

    print("\nМодель распознавания")
    transcriber = Transcriber(cfg)
    model_path = Path(transcriber.model_name)
    if model_path.exists():
        line(OK, "Whisper", str(model_path))
    else:
        line(WARN, "Whisper", f"{transcriber.model_name} — будет скачана при первом запуске")
        print("     Быстрее заранее: python tools/fetch_model.py --size small")

    print("\nopencode")
    client = OpenCodeClient(cfg)
    if client.cli:
        line(OK, "CLI", f"{client.cli} ({client.version()})")
    else:
        line(BAD, "CLI", "не найден — укажи opencode_cli в config.json")
        problems.append("opencode CLI не найден")

    print("\nГолос")
    for binary in ("ffplay", "mpv", "paplay"):
        found = shutil.which(binary)
        if found:
            line(OK, "плеер", found)
            break
    else:
        line(BAD, "плеер", "нет ffplay/mpv/paplay — установи ffmpeg")
        problems.append("нет аудиоплеера")

    if shutil.which("piper"):
        line(OK, "piper", shutil.which("piper"))
    elif shutil.which("espeak-ng"):
        line(OK, "espeak-ng", "офлайн-фолбэк")
    else:
        line(WARN, "офлайн-синтез", "установи espeak-ng")

    if cfg.edge_check:
        if edge_reachable():
            line(OK, "edge-tts", "speech.platform.bing.com доступен")
        else:
            line(WARN, "edge-tts", "недоступен — будет использован офлайн-синтез")

    print("\nМикрофон")
    try:
        import sounddevice as sd

        devices = sd.query_devices()
        inputs = [d for d in devices if d.get("max_input_channels", 0) > 0]
        if not inputs:
            line(BAD, "входы", "не найдено ни одного микрофона")
            problems.append("нет микрофона")
        for index, device in enumerate(devices):
            if device.get("max_input_channels", 0) > 0:
                line(OK, f"[{index}] {device['name']}", f"{int(device['default_samplerate'])} Гц")
        default = sd.query_devices(kind="input")
        print(f"  По умолчанию: {default['name']}")
    except Exception as exc:
        line(BAD, "sounddevice", str(exc))
        problems.append("sounddevice не работает")

    print("\nСистемные команды")
    for binary in (
        "xdg-open",
        "notify-send",
        "wpctl",
        "pamixer",
        "grim",
        "spectacle",
        "flameshot",
        "scrot",
        "xdotool",
        "hyprctl",
        "swaymsg",
        "loginctl",
        "pkill",
    ):
        found = shutil.which(binary)
        if found:
            print(f"  {OK} {binary}: {found}")

    print("\nГлобальный хоткей")
    events = list(Path("/dev/input").glob("event*"))
    readable = [path for path in events if os.access(path, os.R_OK)]
    if readable:
        line(OK, "evdev", f"доступно устройств: {len(readable)}")
    elif events:
        line(WARN, "evdev", "нет доступа к /dev/input")
        print("     sudo usermod -aG input $USER && перезайди в сессию")
        print("     либо запускайся под X11 — сработает pynput")
    else:
        line(WARN, "evdev", "/dev/input не найден")

    print("\nИтог")
    if problems:
        for problem in problems:
            print(f"  {BAD} {problem}")
        print(
            "\nУстановка зависимостей: ./install.sh\n"
            "Лог: " + str(LOG_DIR / "voicecode.log")
        )
        return 1
    print(f"  {OK} Всё на месте. Запуск: ./run.sh\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
