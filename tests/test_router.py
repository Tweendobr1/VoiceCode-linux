"""Быстрые тесты роутера и разбора текста (без Linux-зависимостей)."""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from voicecode.apps import AppIndex, DesktopApp, find_site, normalize  # noqa: E402
from voicecode.audio.speech import clean_for_speech, split_sentences  # noqa: E402
from voicecode.config import Config  # noqa: E402
from voicecode.intents import Router  # noqa: E402
from voicecode.opencode import OpenCodeClient, TextAccumulator, extract_text  # noqa: E402
from voicecode.system import SystemActions  # noqa: E402


def make_router() -> Router:
    apps = AppIndex()
    apps._apps = {
        "org.telegram.desktop": DesktopApp(
            "org.telegram.desktop",
            "Telegram Desktop",
            "Телеграм",
            "telegram-desktop %U",
            Path("/usr/share/applications/org.telegram.desktop"),
        ),
        "org.kde.kate": DesktopApp(
            "org.kde.kate", "Kate", "", "kate %F", Path("/usr/share/applications/org.kde.kate")
        ),
        "org.kde.kcalc": DesktopApp(
            "org.kde.kcalc",
            "KCalc",
            "Калькулятор",
            "kcalc",
            Path("/usr/share/applications/org.kde.kcalc"),
        ),
    }
    apps._loaded = True
    cfg = Config()
    return Router(cfg, apps, SystemActions(cfg, apps))


class RouterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.router = make_router()

    def assert_route(self, phrase: str, kind: str, name: str = "", target: str = "") -> None:
        intent = self.router.route(phrase)
        self.assertEqual((intent.kind, intent.name, intent.target), (kind, name, target), phrase)

    def test_open_app(self) -> None:
        self.assert_route("открой телеграм", "action", "open_app", "телеграм")
        self.assert_route("запусти калькулятор, пожалуйста", "action", "open_app", "калькулятор")

    def test_open_site(self) -> None:
        self.assert_route("открой ютуб", "action", "open_site", "ютуб")
        self.assert_route("открой сайт гитхаб", "action", "open_site", "гитхаб")
        self.assert_route("открой github.com", "action", "open_site", "github.com")

    def test_search(self) -> None:
        self.assert_route(
            "найди в интернете погоду на завтра", "action", "search", "погоду на завтра"
        )
        self.assert_route("погугли новости", "action", "search", "новости")

    def test_local_actions(self) -> None:
        self.assert_route("который час", "action", "time")
        self.assert_route("какое сегодня число", "action", "date")
        self.assert_route("сделай скриншот", "action", "screenshot")
        self.assert_route("громче", "action", "volume_up")
        self.assert_route("тише", "action", "volume_down")
        self.assert_route("выключи звук", "action", "volume_mute")
        self.assert_route("включи звук", "action", "volume_unmute")
        self.assert_route("заблокируй компьютер", "action", "lock")
        self.assert_route("сверни окно", "action", "minimize_window")
        self.assert_route("покажи рабочий стол", "action", "minimize_all")
        self.assert_route("закрой окно", "action", "close_window")
        self.assert_route("переключи окно", "action", "switch_window")
        self.assert_route("закрой телеграм", "action", "close_app", "телеграм")
        self.assert_route("что ты умеешь", "action", "capabilities")

    def test_service(self) -> None:
        self.assert_route("стоп", "stop")
        self.assert_route("повтори последнее", "repeat")
        self.assert_route("скройся", "hide")
        self.assert_route("выключись", "quit")
        self.assert_route("спасибо", "say")

    def test_opencode(self) -> None:
        for phrase in (
            "объясни, что такое квантовая запутанность",
            "напиши функцию на Python",
            "какая погода в Москве",
        ):
            self.assert_route(phrase, "opencode")

    def test_politeness_does_not_break_quit(self) -> None:
        self.assert_route("покажи рабочий стол, пожалуйста", "action", "minimize_all")
        self.assert_route("ну пока", "quit")


class TextTests(unittest.TestCase):
    def test_normalize_keeps_domains(self) -> None:
        self.assertEqual(normalize("Открой GitHub.com!"), "открой github.com")

    def test_find_site(self) -> None:
        self.assertEqual(find_site("ютуб")[1], "https://www.youtube.com")
        self.assertEqual(find_site("github.com")[1], "https://github.com")

    def test_clean_and_split(self) -> None:
        cleaned = clean_for_speech("**Привет** `код` https://ya.ru 😀")
        self.assertEqual(cleaned, "Привет код ссылка")
        self.assertEqual(
            split_sentences("Первое. Второе! Третье?"),
            ["Первое.", "Второе!", "Третье?"],
        )

    def test_accumulator(self) -> None:
        accumulator = TextAccumulator()
        self.assertEqual(accumulator.feed("При"), "При")
        self.assertEqual(accumulator.feed("Привет"), "вет")
        self.assertEqual(accumulator.feed("Привет, мир"), ", мир")
        self.assertEqual(accumulator.text, "Привет, мир")

    def test_plain_lines_keep_separator(self) -> None:
        accumulator = TextAccumulator()
        OpenCodeClient._parse_line("Первая строка\n", accumulator)
        OpenCodeClient._parse_line("вторая строка\n", accumulator)
        self.assertEqual(accumulator.text, "Первая строка\nвторая строка\n")

    def test_extract_text(self) -> None:
        self.assertEqual(extract_text({"type": "text", "text": "ответ"}), "ответ")
        self.assertEqual(extract_text({"type": "reasoning", "text": "секрет"}), "")
        event = {
            "type": "message.part.updated",
            "properties": {"part": {"type": "text", "text": "привет"}},
        }
        self.assertEqual(extract_text(event), "привет")
        nested = {
            "type": "text",
            "part": {"type": "text", "text": "вложенный"},
        }
        self.assertEqual(extract_text(nested), "вложенный")
        tool = {
            "type": "message.part.updated",
            "properties": {"part": {"type": "tool", "text": "вывод инструмента"}},
        }
        self.assertEqual(extract_text(tool), "")


class StreamTests(unittest.TestCase):
    @staticmethod
    def _fake_proc(code: str) -> subprocess.Popen:
        return subprocess.Popen(
            [sys.executable, "-u", "-c", code],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            bufsize=1,
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        )

    def test_read_stdout_keeps_all_lines(self) -> None:
        code = (
            "import json\n"
            "for word in ('раз', 'два', 'три'):\n"
            "    print(json.dumps({'type': 'text', 'text': word}), flush=True)\n"
        )
        proc = self._fake_proc(code)
        client = OpenCodeClient.__new__(OpenCodeClient)
        accumulator = TextAccumulator()
        deltas = list(
            client._read_stdout(
                proc, accumulator, threading.Event(), time.monotonic() + 10
            )
        )
        self.assertEqual("".join(deltas), "раздватри")
        self.assertIsNotNone(proc.poll())
        if proc.stderr is not None:
            proc.stderr.close()

    def test_stream_with_fake_cli(self) -> None:
        code = (
            "import json\n"
            "for word in ('Привет', ' мир'):\n"
            "    print(json.dumps({'type': 'text', 'text': word}), flush=True)\n"
        )
        client = OpenCodeClient.__new__(OpenCodeClient)
        client.cfg = Config()
        client.cli = "fake"
        client._spawn = lambda prompt, with_json: self._fake_proc(code)
        deltas = list(client.stream("привет", threading.Event()))
        self.assertEqual("".join(deltas), "Привет мир")

    def test_stream_retries_without_json(self) -> None:
        attempts = []

        def spawn(prompt, with_json):
            attempts.append(with_json)
            if with_json:
                code = (
                    "import sys\n"
                    "print('unknown option: --format', file=sys.stderr)\n"
                    "sys.exit(2)\n"
                )
            else:
                code = "print('Ответ без JSON', flush=True)\n"
            return self._fake_proc(code)

        client = OpenCodeClient.__new__(OpenCodeClient)
        client.cfg = Config()
        client.cli = "fake"
        client._spawn = spawn
        deltas = list(client.stream("вопрос", threading.Event()))
        self.assertEqual(attempts, [True, False])
        self.assertEqual("".join(deltas), "Ответ без JSON\n")


if __name__ == "__main__":
    unittest.main()
