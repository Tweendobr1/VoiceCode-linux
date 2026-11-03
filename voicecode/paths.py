"""Пути проекта и XDG-каталоги."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent.parent


def _home() -> Path:
    return Path.home()


def _xdg(env: str, default: str) -> Path:
    value = os.environ.get(env)
    return Path(value).expanduser() if value else _home() / default


DATA_HOME = _xdg("XDG_DATA_HOME", ".local/share")
CONFIG_HOME = _xdg("XDG_CONFIG_HOME", ".config")
STATE_HOME = _xdg("XDG_STATE_HOME", ".local/state")
CACHE_HOME = _xdg("XDG_CACHE_HOME", ".cache")
LOG_DIR = STATE_HOME / "voicecode" / "logs"
CACHE_DIR = CACHE_HOME / "voicecode"

_uid = getattr(os, "getuid", lambda: 0)()
RUNTIME_DIR = Path(os.environ.get("XDG_RUNTIME_DIR") or "/tmp") / f"voicecode-{_uid}"
LOCK_PATH = RUNTIME_DIR / "voicecode.lock"

CONFIG_PATH = APP_DIR / "config.json"
MODELS_DIR = APP_DIR / "models"
USER_MODELS_DIR = DATA_HOME / "voicecode" / "models"
AGENT_DIR = APP_DIR / "agent"
DEFAULT_SYSTEM_PROMPT = (
    "Ты голосовой помощник. Отвечай по-русски, коротко и разговорно. "
    "Не используй markdown, списки, таблицы и блоки кода: ответ читают вслух."
)


def models_dir() -> Path:
    """Каталог моделей: рядом с проектом, если он доступен на запись."""
    if os.access(APP_DIR, os.W_OK):
        return MODELS_DIR
    return USER_MODELS_DIR


def agent_dir() -> Path:
    """Рабочая папка opencode; для /opt/voicecode — в пользовательских данных."""
    if os.access(APP_DIR, os.W_OK):
        return AGENT_DIR
    target = DATA_HOME / "voicecode" / "agent"
    target.mkdir(parents=True, exist_ok=True)
    source = AGENT_DIR / "AGENTS.md"
    if source.exists() and not (target / "AGENTS.md").exists():
        shutil.copy2(source, target / "AGENTS.md")
    return target


def ensure_dirs() -> None:
    for path in (LOG_DIR, CACHE_DIR, RUNTIME_DIR, models_dir(), agent_dir()):
        path.mkdir(parents=True, exist_ok=True)


def pictures_dir() -> Path:
    """Каталог изображений пользователя (XDG_PICTURES_DIR)."""
    configured = os.environ.get("XDG_PICTURES_DIR")
    if configured:
        return Path(configured).expanduser()

    tool = shutil.which("xdg-user-dir")
    if tool:
        try:
            out = subprocess.run(
                [tool, "PICTURES"], capture_output=True, text=True, timeout=3
            )
            value = out.stdout.strip()
            if value and Path(value) != _home():
                return Path(value)
        except (OSError, subprocess.SubprocessError):
            pass
    return _home() / "Pictures"


def resolve(path: str | Path, base: Path = APP_DIR) -> Path:
    """Разворачивает ~ и относительные пути от каталога приложения."""
    result = Path(path).expanduser()
    if not result.is_absolute():
        result = base / result
    return result
