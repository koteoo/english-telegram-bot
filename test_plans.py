"""Смоук-тест тарифов и лимитов. Временная база, реальную не трогает."""
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
    try:
        uid = 111
        await db.register_user(uid, "tester")
        assert await db.get_plan(uid) == ("free", None)

        # Free: голос, словари и авто-повторы открыты, все темы — нет
        for feat in ("voice", "auto_reviews", "full_dictionary"):
            assert await db.is_allowed(uid, feat), feat
        assert not await db.is_allowed(uid, "topics_all")

        # лимиты Free по каждому счётчику
        for kind, cap in (("words", LIMITS.free_words_per_day),
                          ("quiz", LIMITS.free_quizzes_per_day),
                          ("translate", LIMITS.free_translate_per_day),
                          ("voice_in", LIMITS.free_voice_inputs_per_day)):
            assert await db.within_limit(uid, kind, cap), kind
            for _ in range(cap):
                await db.incr_usage(uid, kind)
            assert not await db.within_limit(uid, kind, cap), kind
            assert await db.get_usage(uid, kind) == cap, kind

        # Plus: без ограничений
        await db.set_plan(uid, "plus", 30)
        tier, exp = await db.get_plan(uid)
        assert tier == "plus" and exp
        for feat in ("voice", "topics_all", "auto_reviews", "full_dictionary"):
            assert await db.is_allowed(uid, feat), feat
        assert await db.within_limit(uid, "words", 1)

        # просрочка возвращает в Free
        assert db._db
        await db._db.execute(
            "UPDATE plans SET expires_at = ? WHERE user_id = ?",
            ((dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=1)).isoformat(), uid))
        await db._db.commit()
        assert (await db.get_plan(uid))[0] == "free"

        # бессрочный Plus
        await db.set_plan(uid, "plus", None)
        tier, exp = await db.get_plan(uid)
        assert tier == "plus" and exp is None, (tier, exp)

        # напоминания получают все, у кого есть due-карточки
        for u, name in ((222, "payer"), (333, "freetest")):
            await db.register_user(u, name)
            await db.add_word_to_deck(u, "apple")
        await db.set_plan(222, "plus", 30)
        recipients = await db.users_with_due_cards()
        assert 222 in recipients and 333 in recipients, recipients

        assert next_period(30) > dt.datetime.now(dt.timezone.utc).isoformat()
        print("OK: тесты тарифов прошли ✅")
    finally:
        await db.close()


if __name__ == "__main__":
    asyncio.run(run())
