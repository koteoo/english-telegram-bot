"""Клавиатуры бота."""
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton

LEVEL_NAMES = {
    "beginner": "🌱 Beginner",
    "intermediate": "🌿 Intermediate",
    "advanced": "🌳 Advanced",
}


def main_menu_kb() -> ReplyKeyboardMarkup:
    kb = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📚 Word of the Day"), KeyboardButton(text="🃏 Flashcards")],
            [KeyboardButton(text="✍️ Quiz"), KeyboardButton(text="➕ Add word")],
            [KeyboardButton(text="📊 Progress"), KeyboardButton(text="🎯 Level")],
            [KeyboardButton(text="💬 Topics"), KeyboardButton(text="🗣 Chat with me")],
            [KeyboardButton(text="💎 Premium"), KeyboardButton(text="❓ Help")],
        ],
        resize_keyboard=True,
        input_field_placeholder="Choose an action…",
    )
    return kb


def premium_kb() -> InlineKeyboardMarkup:
    from plans import PLUS_STARS, PREMIUM_STARS
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=f"💠 Plus — {PLUS_STARS} ⭐", callback_data="buy:plus")],
            [InlineKeyboardButton(text=f"👑 Premium — {PREMIUM_STARS} ⭐", callback_data="buy:premium")],
        ]
    )


def level_select_cb(level: str) -> InlineKeyboardMarkup:
    """Кнопки под сообщением с карточкой: знаю / не знаю."""
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ I know it", callback_data=f"rev:{level}:1"),
                InlineKeyboardButton(text="❌ Don't know", callback_data=f"rev:{level}:0"),
            ]
        ]
    )
    return kb


def answer_quiz_cb(level: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="A", callback_data=f"quiz:{level}:A"),
                InlineKeyboardButton(text="B", callback_data=f"quiz:{level}:B"),
            ]
        ]
    )
    return kb


def levels_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=name, callback_data=f"lvl:{code}") for code, name in LEVEL_NAMES.items()]
        ]
    )
    return kb


def topics_kb(open_count: int | None = None) -> InlineKeyboardMarkup:
    """Список тем для изучения (по 2 в ряду).

    open_count — сколько тем открыто на текущем плане; остальные помечаются 🔒.
    None = открыты все.
    """
    from data.topics import TOPICS
    rows = []
    for i in range(0, len(TOPICS), 2):
        row = []
        for idx, t in enumerate(TOPICS[i:i + 2]):
            locked = open_count is not None and (i + idx) >= open_count
            prefix = "🔒 " if locked else ""
            row.append(InlineKeyboardButton(
                text=f"{t['emoji']} {prefix}{t['title']}", callback_data=f"topic:{t['id']}"
            ))
        rows.append(row)
    rows.append([InlineKeyboardButton(text="🆓 Free conversation", callback_data="topic:free")])
    if open_count is not None:
        rows.append([InlineKeyboardButton(text="💎 Unlock all topics", callback_data="buy:plus")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def chat_menu_kb(voice_on: bool | None = None) -> ReplyKeyboardMarkup:
    rows = [
        [KeyboardButton(text="💬 Change topic"), KeyboardButton(text="🙋 Ask for help")],
        [KeyboardButton(text="🏠 Main menu")],
    ]
    if voice_on is not None:
        label = "🔇 Voice reply: off" if voice_on else "🎙 Voice reply: on"
        rows.insert(1, [KeyboardButton(text=label)])
    kb = ReplyKeyboardMarkup(
        keyboard=rows,
        resize_keyboard=True,
        input_field_placeholder="Write or send a voice message in English…",
    )
    return kb


def back_topics_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="← Other topics", callback_data="cmd:topics")]]
    )
