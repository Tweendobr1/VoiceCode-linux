"""Палитра и стили в духе opencode."""

from __future__ import annotations

BG = "#0a0c10"
CARD = "#101319"
CARD_BORDER = "#222835"
TEXT = "#e8ecf4"
MUTED = "#8b95a9"
DIM = "#5d6678"
ACCENT = "#f5a97f"
ACCENT_2 = "#f08c5a"
DANGER = "#ef7d7d"
BUTTON = "#1a202b"
BUTTON_HOVER = "#222a38"


def stylesheet() -> str:
    return f"""
    * {{
        font-family: "Inter", "Noto Sans", "DejaVu Sans", sans-serif;
        outline: none;
    }}
    #Card {{
        background-color: {CARD};
        border: 1px solid {CARD_BORDER};
        border-radius: 26px;
    }}
    #StatusLabel {{
        color: {MUTED};
        font-size: 11px;
        letter-spacing: 2px;
        font-weight: 600;
    }}
    #CaptionLabel {{
        color: {MUTED};
        font-size: 13px;
    }}
    #AnswerLabel {{
        color: {TEXT};
        font-size: 15px;
    }}
    #HintLabel {{
        color: {DIM};
        font-size: 11px;
    }}
    #IconButton {{
        background: transparent;
        color: {MUTED};
        border: none;
        border-radius: 11px;
        font-size: 17px;
        padding: 0px;
    }}
    #IconButton:hover {{
        background: {BUTTON_HOVER};
        color: {TEXT};
    }}
    QPushButton#TalkButton {{
        background: {BUTTON};
        color: {TEXT};
        border: 1px solid #2a3140;
        border-radius: 16px;
        font-size: 14px;
        font-weight: 600;
        padding: 0 18px;
    }}
    QPushButton#TalkButton:hover {{
        background: {BUTTON_HOVER};
        border-color: #394253;
    }}
    QPushButton#TalkButton:pressed,
    QPushButton#TalkButton[listening="true"] {{
        background: {ACCENT};
        border-color: {ACCENT};
        color: {BG};
    }}
    QMenu {{
        background: {CARD};
        color: {TEXT};
        border: 1px solid {CARD_BORDER};
        border-radius: 10px;
        padding: 6px;
    }}
    QMenu::item {{
        padding: 6px 22px 6px 12px;
        border-radius: 6px;
    }}
    QMenu::item:selected {{
        background: {BUTTON_HOVER};
    }}
    """
