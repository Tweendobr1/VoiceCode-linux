"""Русский локальный роутер команд."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from .apps import AppIndex, find_site, normalize
from .config import Config
from .system import SystemActions, date_reply, time_reply

log = logging.getLogger(__name__)

_LEAD = re.compile(
    r"^(?:пожалуйста|слушай|эй|окей|voicecode|можешь|можешь пожалуйста|"
    r"будь добр|давай|ну)\s+",
    re.IGNORECASE,
)
_TAIL = re.compile(r"\s+(?:пожалуйста|сейчас|быстро|пожалуй)$", re.IGNORECASE)


def strip_request(text: str) -> str:
    text = normalize(text)
    previous = None
    while previous != text:
        previous = text
        text = _LEAD.sub("", text).strip(" .")
        text = _TAIL.sub("", text).strip(" .")
    return text


@dataclass
class Intent:
    kind: str
    name: str = ""
    target: str = ""
    reply: str = ""


_OPEN_VERBS = r"(?:открой|открыть|запусти|запустить|вруби|включи|стартуй|подними)"
_SEARCH_PATTERNS = [
    re.compile(r"^(?:найди|поищи|ищи)\s+в\s+(?:интернете|сети|гугле)\s+(.+)$"),
    re.compile(r"^(?:погугли|загугли|погуглить)\s+(.+)$"),
    re.compile(r"^(?:поиск|найди)\s+(.+)$"),
]
_TIME_RE = re.compile(r"(который\s+час|сколько\s+времени|текущее\s+время|скажи\s+время|время\s+сейчас)")
_DATE_RE = re.compile(
    r"(какое\s+(?:сегодня\s+)?число|какая\s+(?:сегодня\s+)?дата|"
    r"сегодняшн\w*\s+дата|какой\s+сегодня\s+день)"
)


class Router:
    def __init__(self, cfg: Config, apps: AppIndex, system: SystemActions) -> None:
        self.cfg = cfg
        self.apps = apps
        self.system = system

    # ------------------------------------------------------------------ routing
    def route(self, text: str) -> Intent:
        normalized = strip_request(text)
        if not normalized:
            return Intent("say", reply="Не расслышал")

        if re.fullmatch(r"(стоп|остановись|замолчи|отмена|хватит|перестань|стоп стоп)", normalized):
            return Intent("stop")
        if re.fullmatch(r"(повтори|повтори последнее|что ты сказал|скажи еще раз|еще раз)", normalized):
            return Intent("repeat")
        if re.search(r"(скройся|спрячься|свернись в трей|убери окно|скрой окно)", normalized):
            return Intent("hide")
        if re.search(
            r"(выключись|заверши работу|закройся совсем|\bвыходи\b|(?:^|\s)пока(?:\s|$))",
            normalized,
        ):
            return Intent("quit")
        if re.fullmatch(r"(спасибо|благодарю|спс|спасибо большое)", normalized):
            return Intent("say", reply="Пожалуйста")
        if re.search(r"(что ты умеешь|твои возможности|что ты можешь|чем ты можешь|помощь)", normalized):
            return Intent("action", name="capabilities")

        if _TIME_RE.search(normalized):
            return Intent("action", name="time")
        if _DATE_RE.search(normalized):
            return Intent("action", name="date")
        if re.search(r"(скриншот|снимок экрана|сделай скрин|скрин экрана)", normalized):
            return Intent("action", name="screenshot")

        if re.search(r"(выключи|отключи|убери)\s+звук|без звука|заглуши", normalized):
            return Intent("action", name="volume_mute")
        if re.search(r"(включи|верни)\s+звук|со звуком", normalized):
            return Intent("action", name="volume_unmute")
        if re.search(r"(громче|прибавь звук|прибавь громкость|увеличь (?:звук|громкость)|сделай громче)", normalized):
            return Intent("action", name="volume_up")
        if re.search(r"(тише|убавь звук|убавь громкость|уменьши (?:звук|громкость)|сделай тише)", normalized):
            return Intent("action", name="volume_down")

        if re.search(r"(заблокируй|заблокировать|поставь на блокировку)", normalized):
            return Intent("action", name="lock")
        if re.search(r"(сверни все|сверни всё|покажи рабочий стол|рабочий стол)", normalized):
            return Intent("action", name="minimize_all")
        if re.search(r"(закрой все окна|закрой все окна нафиг)", normalized):
            return Intent("say", reply="Закрывать все окна сразу я не умею")
        if re.search(r"(закрой|закрыть)\s+(?:текущее\s+)?окно", normalized):
            return Intent("action", name="close_window")
        if re.search(r"(переключи|следующее)\s+окно|переключись", normalized):
            return Intent("action", name="switch_window")
        if re.search(r"(сверни|минимизируй)\s+(?:текущее\s+)?окно", normalized) or normalized == "сверни":
            return Intent("action", name="minimize_window")

        search_target = self._match_search(normalized)
        if search_target is not None:
            return Intent("action", name="search", target=search_target)

        open_target = self._match_open(normalized)
        if open_target is not None:
            if find_site(open_target) is not None:
                return Intent("action", name="open_site", target=open_target)
            return Intent("action", name="open_app", target=open_target)

        close_target = self._match_close(normalized)
        if close_target is not None:
            return Intent("action", name="close_app", target=close_target)

        return Intent("opencode")

    @staticmethod
    def _match_search(text: str) -> str | None:
        for pattern in _SEARCH_PATTERNS:
            match = pattern.match(text)
            if match:
                target = match.group(1).strip()
                if target:
                    return target
        return None

    @staticmethod
    def _match_open(text: str) -> str | None:
        match = re.match(_OPEN_VERBS + r"\s+(?:сайт|страницу|вкладку)?\s*(.+)$", text)
        if not match:
            return None
        target = match.group(1).strip()
        target = re.sub(r"^(?:сайт|страницу|вкладку)\s+", "", target)
        return target or None

    @staticmethod
    def _match_close(text: str) -> str | None:
        match = re.match(r"(?:закрой|закрыть|выключи|убей|прибей)\s+(.+)$", text)
        if not match:
            return None
        target = match.group(1).strip()
        if target.startswith(("окно", "все окна", "игру")):
            return None
        return target or None

    # ---------------------------------------------------------------- execution
    def execute(self, intent: Intent) -> tuple[bool, str]:
        if intent.kind == "say":
            return True, intent.reply

        name = intent.name
        if name == "time":
            return True, time_reply()
        if name == "date":
            return True, date_reply()
        if name == "capabilities":
            return True, self.system.capabilities()
        if name == "screenshot":
            return self.system.screenshot()
        if name == "volume_up":
            return self.system.volume("up")
        if name == "volume_down":
            return self.system.volume("down")
        if name == "volume_mute":
            return self.system.volume("mute")
        if name == "volume_unmute":
            return self.system.volume("unmute")
        if name == "lock":
            return self.system.lock()
        if name == "minimize_window":
            return self.system.minimize_window()
        if name == "minimize_all":
            return self.system.minimize_all()
        if name == "close_window":
            return self.system.close_window()
        if name == "switch_window":
            return self.system.switch_window()
        if name == "open_app":
            return self.system.open_app(intent.target)
        if name == "open_site":
            return self.system.open_site(intent.target)
        if name == "search":
            return self.system.search(intent.target)
        if name == "close_app":
            return self.system.close_app(intent.target)
        return False, "Не понял команду"
