#!/usr/bin/env python3
"""Показывает, какие фразы VoiceCode выполняет локально, а какие отдаёт opencode."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from voicecode.apps import AppIndex  # noqa: E402
from voicecode.config import Config  # noqa: E402
from voicecode.intents import Router  # noqa: E402
from voicecode.system import SystemActions  # noqa: E402

PHRASES = [
    "открой телеграм",
    "запусти калькулятор",
    "вруби блокнот",
    "открой ютуб",
    "открой сайт гитхаб",
    "открой github.com",
    "найди в интернете погоду на завтра",
    "погугли новости",
    "который час",
    "какое сегодня число",
    "сделай скриншот",
    "громче",
    "тише",
    "выключи звук",
    "включи звук",
    "сверни окно",
    "покажи рабочий стол",
    "закрой окно",
    "переключи окно",
    "закрой телеграм",
    "заблокируй компьютер",
    "скройся",
    "выключись",
    "повтори",
    "стоп",
    "спасибо",
    "что ты умеешь",
    "объясни, что такое квантовая запутанность",
    "напиши функцию на Python",
    "какая погода в Москве",
]


def main() -> int:
    cfg = Config.load()
    apps = AppIndex()
    apps.load()
    router = Router(cfg, apps, SystemActions(cfg, apps))
    print(f"Приложений в индексе: {len(apps)}\n")
    print(f"{'фраза':<48} {'маршрут':<12} детали")
    print("-" * 96)
    for phrase in PHRASES:
        intent = router.route(phrase)
        details = intent.name
        if intent.target:
            details += f" «{intent.target}»"
        if intent.reply:
            details += f" -> {intent.reply}"
        print(f"{phrase:<48} {intent.kind:<12} {details}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
