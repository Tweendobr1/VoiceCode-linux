"""Чтение и валидация config.json."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from .paths import CONFIG_PATH

log = logging.getLogger(__name__)

DEFAULTS: dict[str, Any] = {
    "language": "ru",
    "whisper_model": "models/faster-whisper-small",
    "whisper_compute": "int8",
    "whisper_threads": 0,
    "tts_engine": "edge",
    "voice": "ru-RU-DmitryNeural",
    "tts_rate": "+8%",
    "tts_volume": "+0%",
    "system_tts": "auto",
    "piper_model": "",
    "edge_check": True,
    "opencode_cli": "",
    "model": "opencode/deepseek-v4.1-flash-free",
    "agent": "build",
    "workspace": "agent",
    "auto_approve": False,
    "keep_context": True,
    "max_context_turns": 6,
    "timeout_sec": 150,
    "microphone": "",
    "sample_rate": 16000,
    "max_record_sec": 30,
    "global_hotkey": "f8",
    "hotkey_grab": False,
    "compositor": "auto",
    "greeting": True,
    "minimize_to_tray": True,
    "start_minimized": False,
    "search_url": "https://yandex.ru/search/?text={query}",
    "show_caption": True,
    "volume_step": 5,
    "screenshot_dir": "",
    "notifications": True,
    "log_level": "INFO",
}


class Config:
    """Настройки с доступом через атрибуты: cfg.model, cfg.voice и т.д."""

    def __init__(self, data: dict[str, Any] | None = None) -> None:
        object.__setattr__(self, "_data", {**DEFAULTS, **(data or {})})
        object.__setattr__(self, "path", CONFIG_PATH)

    @classmethod
    def load(cls, path: str | Path | None = None) -> "Config":
        target = Path(path).expanduser() if path else CONFIG_PATH
        data: dict[str, Any] = {}
        if target.exists():
            try:
                loaded = json.loads(target.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    data = loaded
                else:
                    log.warning("%s: ожидался объект JSON", target)
            except (OSError, json.JSONDecodeError) as exc:
                log.error("Не удалось прочитать %s: %s", target, exc)
        else:
            log.warning("Файл настроек не найден: %s (использую значения по умолчанию)", target)
        cfg = cls(data)
        object.__setattr__(cfg, "path", target)
        return cfg

    def __getattr__(self, name: str) -> Any:
        if name.startswith("_"):
            raise AttributeError(name)
        try:
            return self._data[name]
        except KeyError as exc:  # pragma: no cover - защита от опечаток
            raise AttributeError(name) from exc

    def __setattr__(self, name: str, value: Any) -> None:
        if name == "_data":
            object.__setattr__(self, name, value)
        else:
            self._data[name] = value

    def get(self, name: str, default: Any = None) -> Any:
        return self._data.get(name, default)

    def as_dict(self) -> dict[str, Any]:
        return dict(self._data)

    def save(self) -> None:
        self.path.write_text(
            json.dumps(self._data, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    def resolved_threads(self) -> int:
        import os

        value = int(self.whisper_threads or 0)
        if value > 0:
            return value
        return max(1, (os.cpu_count() or 4) - 2)
