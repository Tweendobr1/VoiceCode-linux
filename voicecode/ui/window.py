"""Главное окно: состояние, hotkeys, трей и связка всех частей."""

from __future__ import annotations

import logging
import os
import re
import threading
import time

from PySide6.QtCore import QPoint, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import (
    QColor,
    QIcon,
    QKeySequence,
    QLinearGradient,
    QPainter,
    QPixmap,
    QShortcut,
)
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
)

from ..apps import AppIndex
from ..audio.recorder import Recorder
from ..audio.speech import Speaker
from ..config import Config
from ..hotkey import HotkeyListener
from ..intents import Router
from ..opencode import OpenCodeClient
from ..stt import Transcriber
from ..system import SystemActions
from . import theme
from .widgets import Card, HoldButton, Logo, Orb

log = logging.getLogger(__name__)

IDLE = "idle"
LISTENING = "listening"
THINKING = "thinking"
SPEAKING = "speaking"

_SENTENCE_END = re.compile(r"(?<=[.!?…])\s+")


def _take_sentences(buffer: str, force: bool = False) -> tuple[list[str], str]:
    parts: list[str] = []
    while True:
        match = _SENTENCE_END.search(buffer)
        if not match:
            break
        sentence = buffer[: match.end()].strip()
        buffer = buffer[match.end() :]
        if sentence:
            parts.append(sentence)
    if len(buffer) > 220:
        cut = max(buffer.rfind(" ", 0, 200), buffer.rfind("\n", 0, 200))
        if cut > 60:
            parts.append(buffer[:cut].strip())
            buffer = buffer[cut + 1 :]
    if force and buffer.strip():
        parts.append(buffer.strip())
        buffer = ""
    return parts, buffer


class VoiceWindow(QWidget):
    hotkey_pressed = Signal()
    hotkey_released = Signal()
    sig_status = Signal(str)
    sig_state = Signal(str)
    sig_transcript = Signal(str)
    sig_answer = Signal(str)
    sig_ready = Signal(bool, str)
    sig_control = Signal(str)
    sig_error = Signal(str)

    def __init__(self, cfg: Config) -> None:
        super().__init__()
        self.cfg = cfg
        self.speaker: Speaker | None = None
        self.recorder: Recorder | None = None
        self.transcriber: Transcriber | None = None
        self.client = OpenCodeClient(cfg)
        self.apps = AppIndex()
        self.system = SystemActions(cfg, self.apps)
        self.router = Router(cfg, self.apps, self.system)

        self._ready = False
        self._talking = False
        self._state = IDLE
        self._request_id = 0
        self._cancel = threading.Event()
        self._history: list[tuple[str, str]] = []
        self._last_answer = ""
        self._closing = False
        self._hotkey: HotkeyListener | None = None
        self._hotkey_desc = ""
        self._drag_offset: QPoint | None = None

        self.setWindowTitle("VoiceCode")
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Window)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFixedSize(540, 444)
        self.setStyleSheet(theme.stylesheet())

        self._build_ui()
        self._build_tray()
        self._wire()

        self._tick_timer = QTimer(self)
        self._tick_timer.timeout.connect(self._tick)
        self._tick_timer.start(120)

        self._start_hotkey()
        self.sig_status.emit("Загружаюсь…")
        threading.Thread(target=self._init_worker, name="init", daemon=True).start()

    # ------------------------------------------------------------------ UI
    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        self.card = Card(self)
        outer.addWidget(self.card)

        layout = QVBoxLayout(self.card)
        layout.setContentsMargins(24, 18, 24, 16)
        layout.setSpacing(8)

        top = QHBoxLayout()
        top.setSpacing(6)
        top.addWidget(Logo())
        top.addStretch(1)
        self.min_button = QPushButton("—")
        self.min_button.setObjectName("IconButton")
        self.min_button.setFixedSize(26, 26)
        self.min_button.setCursor(Qt.PointingHandCursor)
        self.min_button.setFocusPolicy(Qt.NoFocus)
        self.min_button.setToolTip("Свернуть в трей")
        top.addWidget(self.min_button)
        self.close_button = QPushButton("×")
        self.close_button.setObjectName("IconButton")
        self.close_button.setFixedSize(26, 26)
        self.close_button.setCursor(Qt.PointingHandCursor)
        self.close_button.setFocusPolicy(Qt.NoFocus)
        self.close_button.setToolTip("Закрыть")
        top.addWidget(self.close_button)
        layout.addLayout(top)

        self.orb = Orb()
        holder = QHBoxLayout()
        holder.addStretch(1)
        holder.addWidget(self.orb)
        holder.addStretch(1)
        layout.addLayout(holder)

        self.status_label = QLabel("ЗАГРУЖАЮСЬ")
        self.status_label.setObjectName("StatusLabel")
        self.status_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.status_label)

        self.caption_label = QLabel("")
        self.caption_label.setObjectName("CaptionLabel")
        self.caption_label.setAlignment(Qt.AlignCenter)
        self.caption_label.setWordWrap(True)
        self.caption_label.setMinimumHeight(18)
        self.caption_label.setMaximumHeight(40)
        self.caption_label.setTextInteractionFlags(Qt.NoTextInteraction)
        layout.addWidget(self.caption_label)

        self.answer_label = QLabel("")
        self.answer_label.setObjectName("AnswerLabel")
        self.answer_label.setAlignment(Qt.AlignCenter)
        self.answer_label.setWordWrap(True)
        self.answer_label.setMinimumHeight(44)
        self.answer_label.setMaximumHeight(78)
        layout.addWidget(self.answer_label)

        layout.addSpacing(2)
        self.talk_button = HoldButton("Держи и говори")
        layout.addWidget(self.talk_button)

        self.hint_label = QLabel("F8 — говорить · Esc — стоп · Ctrl+R — повторить · Ctrl+Q — выход")
        self.hint_label.setObjectName("HintLabel")
        self.hint_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.hint_label)

    def _build_tray(self) -> None:
        self.tray_available = QSystemTrayIcon.isSystemTrayAvailable()
        self.tray: QSystemTrayIcon | None = None
        if not self.tray_available:
            log.warning("Системный трей недоступен")
            return
        self.tray = QSystemTrayIcon(self._make_icon(), self)
        self.tray.setToolTip("VoiceCode")
        menu = QMenu()
        show_action = menu.addAction("Показать")
        show_action.triggered.connect(self.show_window)
        repeat_action = menu.addAction("Повторить ответ")
        repeat_action.triggered.connect(lambda: self._on_control("repeat"))
        menu.addSeparator()
        quit_action = menu.addAction("Выход")
        quit_action.triggered.connect(self.quit_app)
        self.tray.setContextMenu(menu)
        self.tray_menu = menu
        self.tray.activated.connect(self._tray_activated)
        self.tray.show()

    @staticmethod
    def _make_icon() -> QIcon:
        pixmap = QPixmap(64, 64)
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing)
        gradient = QLinearGradient(8, 8, 56, 56)
        gradient.setColorAt(0.0, QColor(theme.ACCENT))
        gradient.setColorAt(1.0, QColor(theme.ACCENT_2))
        painter.setPen(Qt.NoPen)
        painter.setBrush(gradient)
        painter.drawRoundedRect(QRectF(8, 8, 48, 48), 15, 15)
        painter.setPen(QColor(theme.BG))
        font = painter.font()
        font.setPointSize(24)
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(QRectF(8, 6, 48, 48), Qt.AlignCenter, ">")
        painter.end()
        return QIcon(pixmap)

    def _wire(self) -> None:
        self.talk_button.pressed.connect(self._begin_talk)
        self.talk_button.released.connect(self._end_talk)
        self.min_button.clicked.connect(self.hide_to_tray)
        self.close_button.clicked.connect(self._close_clicked)
        self.hotkey_pressed.connect(self._begin_talk)
        self.hotkey_released.connect(self._end_talk)
        self.sig_status.connect(self._set_status)
        self.sig_state.connect(self._set_state)
        self.sig_transcript.connect(self._show_transcript)
        self.sig_answer.connect(self._show_answer)
        self.sig_ready.connect(self._on_ready)
        self.sig_control.connect(self._on_control)
        self.sig_error.connect(self._show_error)

        self.shortcuts: list[QShortcut] = []
        for sequence, callback in (
            ("Ctrl+Q", self.quit_app),
            ("Ctrl+R", lambda: self._on_control("repeat")),
            ("Escape", lambda: self._on_control("stop")),
        ):
            shortcut = QShortcut(QKeySequence(sequence), self)
            shortcut.activated.connect(callback)
            self.shortcuts.append(shortcut)

    # --------------------------------------------------------------- lifecycle
    def _start_hotkey(self) -> None:
        self._hotkey = HotkeyListener(
            self.cfg, self.hotkey_pressed.emit, self.hotkey_released.emit
        )
        self._hotkey_desc = self._hotkey.start()
        log.info("Хоткей: %s", self._hotkey_desc)
        if "не работает" in self._hotkey_desc:
            self.hint_label.setText(
                "Space — говорить · Esc — стоп · Ctrl+R — повторить · Ctrl+Q — выход"
            )
            self.hint_label.setToolTip(self._hotkey_desc)
            self._set_status("F8 недоступен — добавь себя в группу input")

    def _init_worker(self) -> None:
        try:
            self.sig_status.emit("Открываю микрофон…")
            recorder = Recorder(self.cfg)
            recorder.open()
            self.recorder = recorder

            self.sig_status.emit("Загружаю модель распознавания…")
            transcriber = Transcriber(self.cfg)
            transcriber.load()
            self.transcriber = transcriber

            self.sig_status.emit("Проверяю голос…")
            speaker = Speaker(self.cfg)
            self.speaker = speaker
            speaker.prepare()

            self.sig_status.emit("Прогреваю распознавание…")
            transcriber.warmup()

            self.sig_status.emit("Читаю приложения…")
            self.apps.load()

            cli = self.client.cli or "не найден"
            message = (
                f"Готово. opencode: {self.client.version() if self.client.cli else cli}. "
                f"Голос: {speaker.engine}. Хоткей: {self._hotkey_desc}."
            )
            self.sig_ready.emit(True, message)
        except Exception as exc:
            log.exception("Ошибка инициализации")
            self.sig_ready.emit(False, str(exc))

    def _on_ready(self, ok: bool, message: str) -> None:
        if ok:
            self._ready = True
            log.info(message)
            self._set_status("ГОТОВ")
            self.orb.set_state("idle")
            if self.cfg.greeting and self.speaker is not None:
                self.speaker.enqueue("Голосовой помощник готов")
                self._set_state(SPEAKING)
        else:
            log.error("Инициализация не удалась: %s", message)
            self._set_status("ОШИБКА")
            self._show_answer(message)
            if self.speaker is not None:
                self.speaker.enqueue("Не удалось запуститься. Подробности в окне и в логе.")
                self._set_state(SPEAKING)

    # ---------------------------------------------------------------- talking
    def _begin_talk(self) -> None:
        if self._closing:
            return
        if not self._ready:
            self._set_status("ЕЩЁ ЗАГРУЖАЮСЬ")
            return
        if self._state == LISTENING or self.recorder is None:
            return

        self._cancel_current()
        self._cancel = threading.Event()
        try:
            self.recorder.start()
        except Exception as exc:
            log.exception("Не удалось начать запись")
            self._show_error(str(exc))
            self.speaker and self.speaker.enqueue("Микрофон недоступен")
            return

        self._talking = True
        self.talk_button.set_listening(True)
        self._show_transcript("")
        self._show_answer("")
        self._set_state(LISTENING)

    def _end_talk(self) -> None:
        if not self._talking or self._state != LISTENING or self.recorder is None:
            return
        self._talking = False
        self.talk_button.set_listening(False)
        audio = self.recorder.stop()
        duration = len(audio) / float(self.cfg.sample_rate)
        if duration < 0.3:
            self._set_state(IDLE)
            return
        self._set_state(THINKING)
        self._set_status("РАСПОЗНАЮ…")
        request_id = self._request_id
        threading.Thread(
            target=self._process,
            args=(audio, request_id),
            name="process",
            daemon=True,
        ).start()

    def _cancel_current(self) -> None:
        self._talking = False
        self.talk_button.set_listening(False)
        if self.recorder is not None and self.recorder.is_recording:
            self.recorder.stop()
        self._request_id += 1
        self._cancel.set()
        if self.speaker is not None:
            self.speaker.stop()
        self._set_state(IDLE)

    # --------------------------------------------------------------- processing
    def _process(self, audio, request_id: int) -> None:
        try:
            assert self.transcriber is not None
            text = self.transcriber.transcribe(audio)
        except Exception as exc:
            log.exception("Ошибка распознавания")
            self.sig_error.emit(f"Не удалось распознать речь: {exc}")
            return
        if request_id != self._request_id:
            return

        log.info("Распознано: %s", text)
        self.sig_transcript.emit(text)
        if not text:
            if request_id == self._request_id and not self._cancel.is_set():
                self._speak("Не расслышал")
            return

        try:
            intent = self.router.route(text)
            log.info("Маршрут: %s %s %s", intent.kind, intent.name, intent.target)

            if intent.kind in {"stop", "repeat", "hide", "quit"}:
                self.sig_control.emit(intent.kind)
                return
            if intent.kind == "opencode":
                self._ask_opencode(text, request_id)
                return

            ok, reply = self.router.execute(intent)
        except Exception as exc:
            if request_id == self._request_id:
                log.exception("Ошибка локальной команды")
                self.sig_error.emit(f"Ошибка команды: {exc}")
            return

        if request_id != self._request_id:
            return
        log.info("Локальная команда: %s → %s", reply, ok)
        self.sig_answer.emit(reply)
        self._speak(reply, state=SPEAKING if self.speaker else IDLE)

    def _ask_opencode(self, question: str, request_id: int) -> None:
        if self._cancel.is_set() or request_id != self._request_id:
            return
        self.sig_state.emit(THINKING)
        self.sig_status.emit("ДУМАЮ…")
        prompt = self.client.build_prompt(question, self._history)
        buffer = ""
        answer = ""
        spoke = False
        started = time.monotonic()
        try:
            for delta in self.client.stream(prompt, self._cancel):
                if self._cancel.is_set() or request_id != self._request_id:
                    return
                answer += delta
                buffer += delta
                self.sig_answer.emit(answer)
                sentences, buffer = _take_sentences(buffer)
                for sentence in sentences:
                    if self.speaker is not None:
                        self.speaker.enqueue(sentence)
                        if not spoke:
                            spoke = True
                            self.sig_state.emit(SPEAKING)
            if self._cancel.is_set() or request_id != self._request_id:
                return
            final, _ = _take_sentences(buffer, force=True)
            for sentence in final:
                if self.speaker is not None:
                    self.speaker.enqueue(sentence)
                    if not spoke:
                        spoke = True
                        self.sig_state.emit(SPEAKING)
            if not answer.strip():
                raise RuntimeError("opencode ничего не ответил")
            self._last_answer = answer.strip()
            if self.cfg.keep_context:
                self._history.append((question, answer.strip()))
                limit = max(1, int(self.cfg.max_context_turns))
                self._history = self._history[-limit:]
            log.info(
                "opencode ответил за %.1f с (%d символов)",
                time.monotonic() - started,
                len(answer),
            )
            if not spoke:
                self.sig_state.emit(IDLE)
        except Exception as exc:
            if self._cancel.is_set() or request_id != self._request_id:
                return
            log.exception("Ошибка opencode")
            self.sig_answer.emit(f"Ошибка opencode: {exc}")
            self._speak(
                "Не получилось получить ответ. Проверь opencode и лог.",
                state=SPEAKING if self.speaker else IDLE,
            )

    def _speak(self, text: str, state: str = SPEAKING) -> None:
        if self.speaker is not None and text:
            self.speaker.enqueue(text)
        self.sig_state.emit(state)

    # ------------------------------------------------------------------- slots
    def _tick(self) -> None:
        if self._state == LISTENING and self.recorder is not None:
            self.orb.set_level(self.recorder.level)
        if self.speaker is not None:
            if self.speaker.busy and self._state in {IDLE, THINKING}:
                self._set_state(SPEAKING)
            elif not self.speaker.busy and self._state == SPEAKING:
                self._set_state(IDLE)

    def _set_state(self, state: str) -> None:
        self._state = state
        self.orb.set_state(state)
        labels = {
            IDLE: "ГОТОВ",
            LISTENING: "СЛУШАЮ…",
            THINKING: "ДУМАЮ…",
            SPEAKING: "ГОВОРЮ…",
        }
        self._set_status(labels.get(state, "ГОТОВ"))

    def _set_status(self, text: str) -> None:
        self.status_label.setText(str(text).upper())

    def _show_transcript(self, text: str) -> None:
        if not self.cfg.show_caption:
            return
        value = " ".join(str(text).split())
        if len(value) > 180:
            value = value[:177].rstrip() + "…"
        self.caption_label.setText(value)

    def _show_answer(self, text: str) -> None:
        value = " ".join(str(text).split())
        if len(value) > 420:
            value = value[:417].rstrip() + "…"
        self.answer_label.setText(value)

    def _show_error(self, message: str) -> None:
        log.error("%s", message)
        self._set_status("ОШИБКА")
        self._show_answer(message)
        if self.speaker is not None:
            self.speaker.enqueue("Произошла ошибка. Подробности в логе.")
            self._set_state(SPEAKING)
        else:
            self._set_state(IDLE)

    def _on_control(self, kind: str) -> None:
        if kind == "stop":
            self._cancel_current()
            self._set_status("ГОТОВ")
        elif kind == "repeat":
            if self._last_answer:
                self._show_answer(self._last_answer)
                self._speak(self._last_answer)
        elif kind == "hide":
            self.hide_to_tray()
        elif kind == "quit":
            self.quit_app()

    # -------------------------------------------------------------------- tray
    def _tray_activated(self, reason) -> None:
        if reason == QSystemTrayIcon.Trigger:
            self.show_window()

    def show_window(self) -> None:
        self.show()
        self.raise_()
        self.activateWindow()

    def hide_to_tray(self) -> None:
        if self.tray_available:
            self.hide()
        else:
            self.showMinimized()

    def _close_clicked(self) -> None:
        if self.cfg.minimize_to_tray and self.tray_available:
            self.hide_to_tray()
        else:
            self.quit_app()

    def closeEvent(self, event) -> None:
        if self.cfg.minimize_to_tray and self.tray_available and not self._closing:
            event.ignore()
            self.hide_to_tray()
            return
        event.accept()
        if not self._closing:
            self.quit_app()

    def quit_app(self) -> None:
        if self._closing:
            return
        self._closing = True
        log.info("Завершение работы")
        if self._hotkey is not None:
            self._hotkey.stop()
        self._cancel_current()
        if self.speaker is not None:
            self.speaker.stop()
        if self.recorder is not None:
            self.recorder.close()
        if self.tray is not None:
            self.tray.hide()
        QApplication.instance().quit()

    # ------------------------------------------------------------------- mouse
    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            child = self.childAt(event.position().toPoint())
            if not isinstance(child, QPushButton):
                # На Wayland позицией окна управляет композитор.
                if os.environ.get("WAYLAND_DISPLAY") and self.windowHandle() is not None:
                    try:
                        if self.windowHandle().startSystemMove():
                            super().mousePressEvent(event)
                            return
                    except (AttributeError, RuntimeError):
                        pass
                self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._drag_offset is not None and event.buttons() & Qt.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_offset)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        self._drag_offset = None
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key_Space and not event.isAutoRepeat():
            self._begin_talk()
            event.accept()
            return
        if event.key() == Qt.Key_Escape:
            self._on_control("stop")
            event.accept()
            return
        super().keyPressEvent(event)

    def keyReleaseEvent(self, event) -> None:
        if event.key() == Qt.Key_Space and not event.isAutoRepeat():
            self._end_talk()
            event.accept()
            return
        super().keyReleaseEvent(event)
