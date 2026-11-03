#!/usr/bin/env python3
"""VoiceCode для Arch Linux: голосовой компаньон opencode."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from voicecode import __version__  # noqa: E402
from voicecode.config import Config  # noqa: E402
from voicecode.log import setup as setup_logging  # noqa: E402


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="voicecode",
        description="Голосовой помощник opencode для Linux (push-to-talk).",
    )
    parser.add_argument("--version", action="version", version=f"VoiceCode {__version__}")
    parser.add_argument("--config", help="путь к config.json")
    parser.add_argument("--debug", action="store_true", help="подробный лог")
    parser.add_argument(
        "--say",
        metavar="ТЕКСТ",
        help="озвучить текст и выйти (проверка голоса)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    cfg = Config.load(args.config)
    setup_logging(cfg.log_level, args.debug)

    if args.say:
        from voicecode.audio.speech import Speaker

        speaker = Speaker(cfg)
        try:
            print(f"Движок: {speaker.prepare()}")
            speaker.say_blocking(args.say, timeout=120)
        finally:
            speaker.close()
        return 0

    from voicecode.app import run

    try:
        return run(cfg)
    except KeyboardInterrupt:
        return 130
    except Exception as exc:  # pragma: no cover - верхний уровень
        import logging

        logging.getLogger(__name__).exception("Фатальная ошибка")
        print(f"Не удалось запустить VoiceCode: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
