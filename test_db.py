"""Смоук-тест логики БД без Telegram (python test_db.py). Временная база."""
import asyncio
import datetime as dt
import os
import tempfile

from config import MASTERED_BOX
from db import Database


async def run() -> None:
    path = os.path.join(tempfile.mkdtemp(), "test.db")
    db = Database(path)
    await db.connect()
    try:
        uid = 123
        await db.register_user(uid, "tester", level="beginner")
        assert await db.get_level(uid) == "beginner"

        assert await db.add_word_to_deck(uid, "apple") is True
        assert await db.add_word_to_deck(uid, "apple") is False
        assert await db.deck_words(uid) == ["apple"]

        due = await db.due_cards(uid, "beginner")
        assert len(due) == 1 and due[0].word == "apple", due

        # одно повторение поднимает коробку, но слово ещё не освоено
        assert await db.review_card(uid, "apple", correct=True) == 1
        stats = await db.get_stats(uid)
        assert stats["learned"] == 0, stats
        assert await db.due_cards(uid, "beginner") == []

        # ошибка возвращает в нулевую коробку, но повтор через 10 минут —
        # иначе карточка зацикливается в одном сеансе
        assert await db.review_card(uid, "apple", correct=False) == 0
        assert await db.due_cards(uid, "beginner") == []
        row = await (await db._db.execute(
            "SELECT next_review FROM cards WHERE user_id=? AND word=?", (uid, "apple"))).fetchone()
        delta = (dt.datetime.fromisoformat(row[0])
                 - dt.datetime.now(dt.timezone.utc)).total_seconds()
        assert 500 < delta <= 600, delta

        # доводим до порога освоения
        box = 0
        for _ in range(MASTERED_BOX):
            box = await db.review_card(uid, "apple", correct=True)
        assert box == MASTERED_BOX, box
        assert (await db.get_stats(uid))["learned"] == 1

        #回归: повторный проход не должен удваивать счётчик
        await db.review_card(uid, "apple", correct=False)
        for _ in range(MASTERED_BOX):
            await db.review_card(uid, "apple", correct=True)
        assert (await db.get_stats(uid))["learned"] == 1, "счётчик освоения задвоился"

        assert await db.update_quiz_result(uid, 5) is True
        assert await db.update_quiz_result(uid, 3) is False
        assert (await db.get_stats(uid))["quiz_best"] == 5

        await db.set_level(uid, "advanced")
        assert await db.get_level(uid) == "advanced"

        item = db.random_word("intermediate")
        assert item.word and item.translation and item.example
        print("OK: тесты базы прошли ✅")
    finally:
        await db.close()


if __name__ == "__main__":
    asyncio.run(run())
