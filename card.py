"""Карточка результата CEFR — картинка, которой делятся в чатах и сторис."""
from __future__ import annotations

import io
import os

from PIL import Image, ImageDraw, ImageFont

W, H = 800, 420
BG = (15, 23, 32)
ACCENT = (126, 231, 135)
TEXT = (201, 209, 217)
MUTED = (139, 148, 158)

_REG = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"

LABELS = {
    "A1": "Начальный", "A2": "Элементарный",
    "B1": "Средний", "B2": "Выше среднего",
    "C1": "Продвинутый", "C2": "Свободное владение",
}


def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    path = _BOLD if bold and os.path.exists(_BOLD) else _REG
    return ImageFont.truetype(path, size)


def render_level_card(cefr: str, streak: int, words: int, bot_username: str) -> bytes:
    """Эмодзи в картинке не рисуем: в DejaVu нет этих глифов, будут квадраты."""
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, W - 1, H - 1], outline=(48, 54, 61), width=2)

    d.text((48, 38), "МОЙ УРОВЕНЬ АНГЛИЙСКОГО", font=_font(26, True), fill=MUTED)

    big = _font(132, True)
    d.text((44, 78), cefr, font=big, fill=ACCENT)
    cw = d.textlength(cefr, font=big)
    d.text((44 + cw + 28, 150), LABELS.get(cefr, ""), font=_font(34), fill=TEXT)

    d.line([(48, 262), (W - 48, 262)], fill=(48, 54, 61), width=2)

    d.text((48, 288), f"Серия: {streak} дн.", font=_font(30, True), fill=TEXT)
    d.text((330, 288), f"Слов в колоде: {words}", font=_font(30, True), fill=TEXT)

    d.text((48, 352), f"t.me/{bot_username} — английский с ИИ-репетитором",
           font=_font(26), fill=MUTED)

    buf = io.BytesIO()
    img.save(buf, "PNG", optimize=True)
    return buf.getvalue()
