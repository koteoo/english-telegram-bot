"""Тесты тарифных планов, лимитов и авто-повторений."""
import asyncio
import datetime as dt
import os
import tempfile

os.environ["DB_PATH"] = tempfile.mktemp(suffix=".db")

from db import Database  # noqa: E402
from plans import LIMITS, next_period  # noqa: E402


async def run() -> None:
    db = Database(os.environ["DB_PATH"])
    await db.connect()

    uid = 111
    await db.register_user(uid, "tester")

    # по умолчанию — free
    assert await db.get_plan(uid) == ("free", None)

    # free не может голос/темы/авто-повторы
    for feat in ("voice", "topics_all", "auto_reviews", "full_dictionary"):
        assert not await db.is_allowed(uid, feat), feat

    # лимиты free: слова
    assert await db.within_limit(uid, "words", LIMITS.free_words_per_day)
    for _ in range(LIMITS.free_words_per_day):
        await db.incr_usage(uid, "words")
    assert not await db.within_limit(uid, "words", LIMITS.free_words_per_day)
    assert await db.get_usage(uid, "words") == LIMITS.free_words_per_day

    # счётчики независимы по kind
    assert await db.within_limit(uid, "quiz", LIMITS.free_quizzes_per_day)

    # активация Plus
    await db.set_plan(uid, "plus", 30)
    tier, exp = await db.get_plan(uid)
    assert tier == "plus" and exp
    assert await db.is_allowed(uid, "voice")
    assert await db.is_allowed(uid, "topics_all")
    # на платном плане дневные лимиты не действуют
    assert await db.within_limit(uid, "words", LIMITS.free_words_per_day)

    # просроченная подписка автоматически становится free
    assert db._db
    await db._db.execute(
        "UPDATE plans SET expires_at = ? WHERE user_id = ?",
        ((dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=1)).isoformat(), uid),
    )
    await db._db.commit()
    assert (await db.get_plan(uid))[0] == "free"

    # Premium бессрочный
    await db.set_plan(uid, "premium", 30)
    tier, exp = await db.get_plan(uid)
    assert tier == "premium" and exp is None
    assert await db.is_allowed(uid, "voice")

    # авто-повторения: только у платных с due-карточками
    uid_plus = 222
    await db.register_user(uid_plus, "payer")
    await db.set_plan(uid_plus, "plus", 30)
    await db.add_word_to_deck(uid_plus, "apple")
    assert uid_plus in await db.users_with_due_cards()

    uid_free = 333
    await db.register_user(uid_free, "freetest")
    await db.add_word_to_deck(uid_free, "apple")
    assert uid_free not in await db.users_with_due_cards()

    assert next_period(30) > dt.datetime.now(dt.timezone.utc).isoformat()

    await db.close()
    print("OK: все тесты тарифов прошли ✅")


if __name__ == "__main__":
    asyncio.run(run())
