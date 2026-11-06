"""Быстрый смоук-тест логики БД без Telegram (python test_db.py)."""
import asyncio
import datetime as dt
import os
import tempfile

from db import Database


async def run() -> None:
    path = os.path.join(tempfile.mkdtemp(), "test.db")
    db = Database(path)
    await db.connect()

    uid = 123
    await db.register_user(uid, "tester", level="beginner")
    assert await db.get_level(uid) == "beginner"

    # добавление слова в колоду
    assert await db.add_word_to_deck(uid, "apple") is True
    assert await db.add_word_to_deck(uid, "apple") is False
    assert await db.deck_words(uid) == ["apple"]

    # карточка сразу "due"
    due = await db.due_cards(uid, "beginner")
    assert len(due) == 1 and due[0].word == "apple", due

    # успешное повторение: box 0 -> 1, learned +1
    box = await db.review_card(uid, "apple", correct=True)
    assert box == 1
    stats = await db.get_stats(uid)
    assert stats["learned"] == 1, stats

    # после успешного повторения карточка не due (next_review через 1 день)
    assert await db.due_cards(uid, "beginner") == []

    # неверный ответ возвращает в box 0 и делает due снова
    # сначала сдвинем время: просто проверим review_card(False) напрямую
    box = await db.review_card(uid, "apple", correct=False)
    assert box == 0
    assert len(await db.due_cards(uid, "beginner")) == 1

    # квиз-рекорд
    assert await db.update_quiz_result(uid, 5) is True
    assert await db.update_quiz_result(uid, 3) is False
    assert (await db.get_stats(uid))["quiz_best"] == 5

    # уровень
    await db.set_level(uid, "advanced")
    assert await db.get_level(uid) == "advanced"

    # случайное слово возвращается корректно
    item = db.random_word("intermediate")
    assert item.word and item.translation and item.example

    await db.close()
    print("OK: все тесты базы данных прошли ✅")


if __name__ == "__main__":
    asyncio.run(run())
