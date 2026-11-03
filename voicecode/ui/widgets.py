"""Кастомные виджеты: логотип, орб, кнопка разговора."""

from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, QTimer
from PySide6.QtGui import (
    QColor,
    QFont,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QRadialGradient,
)
from PySide6.QtWidgets import QPushButton, QWidget

from . import theme


class Logo(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedHeight(30)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self._font = QFont("Inter", 12)
        self._font.setWeight(QFont.DemiBold)
        self._mark_font = QFont("DejaVu Sans Mono", 13)
        self._mark_font.setWeight(QFont.Bold)

    def sizeHint(self) -> QSize:
        return QSize(170, 30)

    def paintEvent(self, event) -> None:  # noqa: ARG002
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.TextAntialiasing)

        mark = QRectF(0, 4, 22, 22)
        gradient = QLinearGradient(mark.topLeft(), mark.bottomRight())
        gradient.setColorAt(0.0, QColor(theme.ACCENT))
        gradient.setColorAt(1.0, QColor(theme.ACCENT_2))
        painter.setPen(Qt.NoPen)
        painter.setBrush(gradient)
        painter.drawRoundedRect(mark, 7, 7)

        painter.setPen(QColor(theme.BG))
        painter.setFont(self._mark_font)
        painter.drawText(mark, Qt.AlignCenter, ">")

        painter.setPen(QColor(theme.TEXT))
        painter.setFont(self._font)
        painter.drawText(QRectF(30, 0, self.width() - 30, 30), Qt.AlignVCenter, "voicecode")


class Orb(QWidget):
    """Анимированный индикатор: покой, запись, размышление, речь."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedSize(122, 122)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self._state = "idle"
        self._level = 0.0
        self._phase = 0.0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(33)

    def set_state(self, state: str) -> None:
        if state != self._state:
            self._state = state
            self.update()

    def set_level(self, level: float) -> None:
        self._level = max(0.0, min(1.0, level))

    def _tick(self) -> None:
        speed = {"listening": 0.16, "thinking": 0.09, "speaking": 0.12}.get(self._state, 0.035)
        self._phase = (self._phase + speed) % (math.tau * 8)
        if self.isVisible():
            self.update()

    def paintEvent(self, event) -> None:  # noqa: ARG002
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        center = QPointF(self.width() / 2, self.height() / 2)
        base = 32.0
        accent = QColor(theme.ACCENT)

        pulse = 0.0
        if self._state == "listening":
            pulse = 6 + 13 * self._level + 2.5 * math.sin(self._phase * 3)
        elif self._state == "speaking":
            pulse = 4 + 3 * math.sin(self._phase * 2)
        elif self._state == "thinking":
            pulse = 3

        # Мягкое свечение.
        glow_radius = base + 28 + pulse
        glow = QRadialGradient(center, glow_radius)
        glow_color = QColor(accent)
        glow_color.setAlpha(60 if self._state != "idle" else 32)
        glow.setColorAt(0.0, glow_color)
        glow.setColorAt(0.55, QColor(accent.red(), accent.green(), accent.blue(), 22))
        glow.setColorAt(1.0, QColor(accent.red(), accent.green(), accent.blue(), 0))
        painter.setPen(Qt.NoPen)
        painter.setBrush(glow)
        painter.drawEllipse(center, glow_radius, glow_radius)

        # Кольца.
        if self._state in {"listening", "thinking"}:
            for index in range(2):
                progress = (self._phase * 0.28 + index * 0.5) % 1.0
                radius = base + 6 + progress * 24
                ring = QColor(accent)
                ring.setAlpha(int(95 * (1.0 - progress)))
                painter.setPen(QPen(ring, 1.4))
                painter.setBrush(Qt.NoBrush)
                painter.drawEllipse(center, radius, radius)

        # Ядро.
        core_radius = base + pulse * 0.35
        core = QRadialGradient(center - QPointF(9, 11), core_radius * 1.6)
        core.setColorAt(0.0, QColor("#ffc7a3"))
        core.setColorAt(0.45, QColor(theme.ACCENT))
        core.setColorAt(1.0, QColor("#c86a3f"))
        painter.setPen(Qt.NoPen)
        painter.setBrush(core)
        painter.drawEllipse(center, core_radius, core_radius)

        # Блик.
        highlight = QRadialGradient(center - QPointF(11, 13), core_radius * 0.55)
        highlight.setColorAt(0.0, QColor(255, 255, 255, 120))
        highlight.setColorAt(1.0, QColor(255, 255, 255, 0))
        painter.setBrush(highlight)
        painter.drawEllipse(center - QPointF(11, 13), core_radius * 0.55, core_radius * 0.55)

        if self._state == "thinking":
            arc_rect = QRectF(
                center.x() - core_radius - 8,
                center.y() - core_radius - 8,
                (core_radius + 8) * 2,
                (core_radius + 8) * 2,
            )
            pen = QPen(QColor(theme.BG), 3.0, Qt.SolidLine, Qt.RoundCap)
            painter.setPen(pen)
            painter.setBrush(Qt.NoBrush)
            start = int(self._phase * 120) % 360
            painter.drawArc(arc_rect, start * 16, 100 * 16)

        if self._state == "speaking":
            for index in range(3):
                radius = core_radius + 8 + index * 5
                alpha = int(70 - index * 18 + 20 * math.sin(self._phase * 2 + index))
                wave = QColor(accent)
                wave.setAlpha(max(0, alpha))
                painter.setPen(QPen(wave, 1.6))
                painter.setBrush(Qt.NoBrush)
                painter.drawEllipse(center, radius, radius)


class HoldButton(QPushButton):
    def __init__(self, text: str, parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.setObjectName("TalkButton")
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.NoFocus)
        self.setFixedHeight(46)
        self._base_text = text
        self._listening = False
        self.setProperty("listening", "false")

    def set_listening(self, listening: bool) -> None:
        if listening == self._listening:
            return
        self._listening = listening
        self.setText("Отпусти, когда закончишь" if listening else self._base_text)
        self.setProperty("listening", "true" if listening else "false")
        self.style().unpolish(self)
        self.style().polish(self)


class Card(QWidget):
    """Контейнер с мягкой тенью (рисуется вручную, без QGraphicsEffect)."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("Card")

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        path = QPainterPath()
        path.addRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), 26, 26)
        painter.fillPath(path, QColor(theme.CARD))
        painter.setPen(QPen(QColor(theme.CARD_BORDER), 1))
        painter.drawPath(path)
