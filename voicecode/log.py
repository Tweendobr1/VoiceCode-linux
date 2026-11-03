"""Логирование в файл с ротацией."""

from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler

from .paths import LOG_DIR

_configured = False


def setup(level: str = "INFO", debug: bool = False) -> logging.Logger:
    global _configured
    root = logging.getLogger()
    if _configured:
        return root

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    numeric = logging.DEBUG if debug else getattr(logging, str(level).upper(), logging.INFO)

    fmt = logging.Formatter(
        "%(asctime)s %(levelname)-7s %(name)s: %(message)s", "%Y-%m-%d %H:%M:%S"
    )
    file_handler = RotatingFileHandler(
        LOG_DIR / "voicecode.log", maxBytes=1_000_000, backupCount=3, encoding="utf-8"
    )
    file_handler.setFormatter(fmt)
    file_handler.setLevel(numeric)

    console = logging.StreamHandler(sys.stderr)
    console.setFormatter(fmt)
    console.setLevel(numeric)

    root.setLevel(numeric)
    root.addHandler(file_handler)
    root.addHandler(console)

    logging.getLogger("faster_whisper").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("edge_tts").setLevel(logging.WARNING)

    _configured = True
    return root
