"""Точка сборки Qt-приложения и защита от второго экземпляра."""

from __future__ import annotations

import logging
import os
import sys

from .config import Config
from .paths import LOCK_PATH, RUNTIME_DIR

log = logging.getLogger(__name__)
_lock_file = None


def _acquire_lock():
    """Эксклюзивная блокировка через flock; None — уже запущено."""
    global _lock_file
    try:
        import fcntl
    except ImportError:  # не Linux — просто не блокируем
        return object()
    try:
        RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
        handle = open(LOCK_PATH, "a+", encoding="utf-8")
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        handle.seek(0)
        handle.truncate()
        handle.write(str(os.getpid()))
        handle.flush()
        _lock_file = handle
        return handle
    except (BlockingIOError, OSError):
        return None


def run(cfg: Config) -> int:
    from PySide6.QtWidgets import QApplication

    from .ui.window import VoiceWindow

    lock = _acquire_lock()
    if lock is None:
        print("VoiceCode уже запущен.", file=sys.stderr)
        return 1

    app = QApplication([sys.argv[0]])
    app.setApplicationName("VoiceCode")
    app.setApplicationDisplayName("VoiceCode")
    app.setOrganizationName("VoiceCode")
    app.setDesktopFileName("voicecode")
    app.setQuitOnLastWindowClosed(False)

    window = VoiceWindow(cfg)
    app.setWindowIcon(window._make_icon())
    if cfg.start_minimized and window.tray_available:
        window.hide()
    else:
        window.show()
    return int(app.exec())
