"""Язык интерфейса по уровню ученика.

beginner — по-русски, intermediate и advanced — по-английски.
Перевод слова на карточке остаётся русским всегда: это учебное содержание.
"""


def ui_ru(level: str | None) -> bool:
    return (level or "beginner") == "beginner"
