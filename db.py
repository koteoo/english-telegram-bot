"""Хранилище на SQLite: пользователи, прогресс карточек (интервальное повторение), статистика."""
from __future__ import annotations

import datetime as dt
import random
import logging
from dataclasses import dataclass
import os

import aiosqlite

from config import DB_PATH, REPETITION_INTERVALS_DAYS
from data.vocabulary import VOCABULARY
from plans import next_period

logger = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    username TEXT,
    level TEXT NOT NULL DEFAULT 'beginner',
    created_at TEXT NOT NULL,
    start_source TEXT
);
CREATE TABLE IF NOT EXISTS cards (
    user_id INTEGER NOT NULL,
    word TEXT NOT NULL,
    translation TEXT,
    example TEXT,
    box INTEGER NOT NULL DEFAULT 0,
    next_review TEXT NOT NULL,
    PRIMARY KEY (user_id, word)
);
CREATE TABLE IF NOT EXISTS stats (
    user_id INTEGER PRIMARY KEY,
    learned INTEGER NOT NULL DEFAULT 0,
    quiz_best INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS plans (
    user_id INTEGER PRIMARY KEY,
    tier TEXT NOT NULL DEFAULT 'free',
    expires_at TEXT
);
CREATE TABLE IF NOT EXISTS usage_counters (
    user_id INTEGER NOT NULL,
    kind TEXT NOT NULL,
    day TEXT NOT NULL,
    used INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (user_id, kind, day)
);
"""

def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)

@dataclass
class CardItem:
    word: str
    translation: str
    example: str
    box: int

_DEFAULT_TZ = int(os.getenv("NOTIFY_TZ_OFFSET", "5"))

_NOTIFY_SCHEMA = """
CREATE TABLE IF NOT EXISTS notify_prefs (
    user_id INTEGER PRIMARY KEY,
    enabled INTEGER NOT NULL DEFAULT 1,
    hour    INTEGER NOT NULL DEFAULT 19,
    tz_offset INTEGER NOT NULL DEFAULT 5
);
"""


_LAST_ACTION: dict[int, object] = {}


_PROFILE_SCHEMA = """
CREATE TABLE IF NOT EXISTS user_profile (
    user_id    INTEGER PRIMARY KEY,
    cefr       TEXT,
    goal       TEXT,
    updated_at TEXT
);
"""


_PAYMENTS_SCHEMA = """
CREATE TABLE IF NOT EXISTS payments (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL,
    tier       TEXT NOT NULL,
    stars      INTEGER NOT NULL,
    days       INTEGER NOT NULL,
    charge_id  TEXT UNIQUE,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_payments_created ON payments(created_at);
"""


_FEEDBACK_SCHEMA = """
CREATE TABLE IF NOT EXISTS feedback (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL,
    kind       TEXT NOT NULL,
    text       TEXT NOT NULL,
    tier       TEXT,
    status     TEXT NOT NULL DEFAULT 'new',
    created_at TEXT NOT NULL,
    handled_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_feedback_status ON feedback(status, created_at);
"""


_REFERRAL_SCHEMA = """
CREATE TABLE IF NOT EXISTS referrals (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    inviter_id   INTEGER NOT NULL,
    invitee_id   INTEGER NOT NULL UNIQUE,
    created_at   TEXT NOT NULL,
    activated_at TEXT,
    rewarded_at  TEXT,
    notified_at  TEXT
);
CREATE INDEX IF NOT EXISTS idx_ref_inviter ON referrals(inviter_id);
"""


_CHAT_SCHEMA = """
CREATE TABLE IF NOT EXISTS chat_state (
    user_id    INTEGER PRIMARY KEY,
    topic      TEXT,
    turn       INTEGER NOT NULL DEFAULT 0,
    history    TEXT NOT NULL DEFAULT '[]',
    voice      INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT
);
"""


class Database:
    def __init__(self, path: str = DB_PATH):
        self.path = path
        self._db: aiosqlite.Connection | None = None

    async def connect(self) -> None:
        self._db = await aiosqlite.connect(self.path)
        await self._db.executescript(_SCHEMA)
        await self._db.executescript(_NOTIFY_SCHEMA)
        await self._db.executescript(_PROFILE_SCHEMA)
        await self._db.executescript(_PAYMENTS_SCHEMA)
        await self._db.executescript(_FEEDBACK_SCHEMA)
        await self._db.executescript(_REFERRAL_SCHEMA)
        await self._db.executescript(_CHAT_SCHEMA)
        # миграция: источник прихода (для уже существующих — direct)
        cur = await self._db.execute("PRAGMA table_info(referrals)")
        rcols = {r[1] for r in await cur.fetchall()}
        if rcols and "notified_at" not in rcols:
            await self._db.execute("ALTER TABLE referrals ADD COLUMN notified_at TEXT")
            await self._db.commit()
        cur = await self._db.execute("PRAGMA table_info(users)")
        cols = {r[1] for r in await cur.fetchall()}
        if "start_source" not in cols:
            await self._db.execute("ALTER TABLE users ADD COLUMN start_source TEXT")
            await self._db.execute(
                "UPDATE users SET start_source='direct' WHERE start_source IS NULL")
            await self._db.commit()
        # миграция: пояс для существующих строк
        try:
            await self._db.execute(
                "ALTER TABLE notify_prefs ADD COLUMN tz_offset INTEGER NOT NULL DEFAULT 5")
            await self._db.commit()
        except aiosqlite.OperationalError:
            pass  # колонка уже есть
        
        # Безопасная миграция: добавляем колонки, если их нет (для старых баз)
        try:
            await self._db.execute("ALTER TABLE cards ADD COLUMN translation TEXT")
            await self._db.execute("ALTER TABLE cards ADD COLUMN example TEXT")
            await self._db.commit()
        except aiosqlite.OperationalError:
            # Колонки уже существуют, это нормально
            pass
            
        await self._db.commit()

    async def close(self) -> None:
        if self._db:
            await self._db.close()
            self._db = None

    # ---------------- Пользователи ----------------
    async def register_user(self, user_id: int, username: str | None,
                            level: str = "beginner", source: str | None = None) -> None:
        """Источник фиксируется только при первом /start — первое касание."""
        assert self._db
        await self._db.execute(
            """INSERT INTO users (user_id, username, level, created_at, start_source)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(user_id) DO UPDATE SET username = excluded.username""",
            (user_id, username, level, _now().isoformat(), source or "direct"),
        )
        await self._db.execute("INSERT OR IGNORE INTO stats (user_id) VALUES (?)", (user_id,))
        await self._db.commit()

    async def get_level(self, user_id: int) -> str:
        assert self._db
        cur = await self._db.execute("SELECT level FROM users WHERE user_id = ?", (user_id,))
        row = await cur.fetchone()
        return row[0] if row else "beginner"

    async def set_level(self, user_id: int, level: str) -> None:
        assert self._db
        await self._db.execute("UPDATE users SET level = ? WHERE user_id = ?", (level, user_id))
        await self._db.commit()

    # ---------------- Карточки ----------------
    async def add_word_to_deck(self, user_id: int, word: str, translation: str = "", example: str = "") -> bool:
        """Добавить слово в колоду пользователя. Возвращает True, если слово новое."""
        assert self._db
        cur = await self._db.execute(
            "SELECT 1 FROM cards WHERE user_id = ? AND word = ?", (user_id, word)
        )
        if await cur.fetchone():
            return False
            
        await self._db.execute(
            """INSERT INTO cards (user_id, word, translation, example, box, next_review) 
               VALUES (?, ?, ?, ?, 0, ?)""",
            (user_id, word, translation, example, _now().isoformat()),
        )
        await self._db.commit()
        # единственная точка входа для всех пяти сценариев добавления слова
        try:
            await self.activate_referral(user_id)
        except Exception:  # noqa: BLE001 — награда не должна ломать добавление слова
            pass
        return True

    async def due_cards(self, user_id: int, level: str, limit: int = 10) -> list[CardItem]:
        """Карточки, которые пора повторить (next_review <= сейчас)."""
        assert self._db
        cur = await self._db.execute(
            """SELECT word, translation, example, box FROM cards 
               WHERE user_id = ? AND next_review <= ? 
               ORDER BY next_review LIMIT ?""",
            (user_id, _now().isoformat(), limit),
        )
        rows = await cur.fetchall()
        result = []
        
        # Fallback по ВСЕМ уровням: слово не зависит от текущего уровня
        local_index = {w.lower(): (t, e) for ws in VOCABULARY.values() for w, t, e in ws}

        for word, translation, example, box in rows:
            fb_t, fb_e = local_index.get(word.lower(), ("", ""))
            final_translation = translation or fb_t
            final_example = example or fb_e

            if not final_translation:
                # последний шанс — словарь Мюллера; при сбое остаётся заглушка
                try:
                    import dictionary
                    hit = dictionary.en_ru_lookup(word)
                    if hit:
                        final_translation = hit[0]
                except Exception:
                    pass
            if not final_translation:
                final_translation = "Translation not found"
            if not final_example:
                final_example = f"Try to make a sentence with '{word}'."
                
            result.append(CardItem(word, final_translation, final_example, box))
            
        return result

    async def review_card(self, user_id: int, word: str, correct: bool) -> int:
        """Обновить интервал карточки. Возвращает новую «коробку»."""
        assert self._db
        cur = await self._db.execute(
            "SELECT box FROM cards WHERE user_id = ? AND word = ?", (user_id, word)
        )
        row = await cur.fetchone()
        if not row:
            return 0
            
        box = row[0]
        if correct:
            new_box = min(box + 1, len(REPETITION_INTERVALS_DAYS) - 1)
            # счётчик stats.learned больше не ведём: он дважды считал одно слово
            # при возврате в нулевую коробку. Освоение считается из cards.box.
        else:
            new_box = 0
            
        days = REPETITION_INTERVALS_DAYS[new_box]
        if days <= 0:
            # «не знаю» — повтор через 10 минут, иначе карточка зацикливается
            next_review = _now() + dt.timedelta(minutes=10)
        else:
            next_review = _now() + dt.timedelta(days=days)
        
        await self._db.execute(
            "UPDATE cards SET box = ?, next_review = ? WHERE user_id = ? AND word = ?",
            (new_box, next_review.isoformat(), user_id, word),
        )
        await self._db.commit()
        return new_box

    async def deck_words(self, user_id: int) -> list[str]:
        assert self._db
        cur = await self._db.execute("SELECT word FROM cards WHERE user_id = ?", (user_id,))
        return [r[0] for r in await cur.fetchall()]

    # ---------------- Случайные слова уровня ----------------
    @staticmethod
    def random_word(level: str, exclude: set[str] | None = None) -> CardItem:
        words = VOCABULARY.get(level) or VOCABULARY["beginner"]
        pool = [w for w in words if not exclude or w[0].lower() not in exclude]
        if not pool:
            pool = words
        w, t, e = random.choice(pool)
        return CardItem(w, t, e, 0)

    # ---------------- Статистика ----------------
    async def get_stats(self, user_id: int) -> dict:
        assert self._db
        cur = await self._db.execute(
            "SELECT learned, quiz_best FROM stats WHERE user_id = ?", (user_id,)
        )
        row = await cur.fetchone()
        _legacy_learned, quiz_best = (row[0], row[1]) if row else (0, 0)
        from config import MASTERED_BOX
        cur3 = await self._db.execute(
            "SELECT COUNT(*) FROM cards WHERE user_id = ? AND box >= ?",
            (user_id, MASTERED_BOX),
        )
        learned = int((await cur3.fetchone())[0])
        
        cur2 = await self._db.execute("SELECT COUNT(*) FROM cards WHERE user_id = ?", (user_id,))
        deck_size = (await cur2.fetchone())[0]
        
        return {"learned": learned, "quiz_best": quiz_best, "deck_size": deck_size}

    async def update_quiz_result(self, user_id: int, score: int) -> bool:
        assert self._db
        cur = await self._db.execute("SELECT quiz_best FROM stats WHERE user_id = ?", (user_id,))
        row = await cur.fetchone()
        best = row[0] if row else 0
        
        if score > best:
            await self._db.execute("UPDATE stats SET quiz_best = ? WHERE user_id = ?", (score, user_id))
            await self._db.commit()
            return True
        return False

    # ---------------- Тарифные планы ----------------
    async def get_plan(self, user_id: int) -> tuple[str, str | None]:
        assert self._db
        cur = await self._db.execute("SELECT tier, expires_at FROM plans WHERE user_id = ?", (user_id,))
        row = await cur.fetchone()
        if not row:
            return "free", None
            
        tier, expires_at = row[0], row[1]
        if expires_at:
            if dt.datetime.fromisoformat(expires_at) <= _now():
                await self._db.execute(
                    "UPDATE plans SET tier = 'free', expires_at = NULL WHERE user_id = ?", (user_id,)
                )
                await self._db.commit()
                return "free", None
        return tier, expires_at

    async def set_plan(self, user_id: int, tier: str, days: int | None) -> None:
        """days=None — бессрочный доступ (для владельца)."""
        assert self._db
        expires_at = None if days is None else next_period(days)
        await self._db.execute(
            """INSERT INTO plans (user_id, tier, expires_at) VALUES (?, ?, ?)
               ON CONFLICT(user_id) DO UPDATE SET tier = excluded.tier, expires_at = excluded.expires_at""",
            (user_id, tier, expires_at),
        )
        await self._db.commit()

    async def is_allowed(self, user_id: int, feature: str) -> bool:
        tier, _ = await self.get_plan(user_id)
        if feature == "voice":
            return True   # голос доступен всем, объём задаётся лимитами тарифа
        if feature == "topics_all":
            return tier == "plus"
        if feature == "auto_reviews":
            return True   # Free: 2 слова в день
        if feature == "full_dictionary":
            return True   # словари всех уровней открыты
        return False

    # ---------------- Дневные счётчики (лимиты) ----------------
    async def incr_usage(self, user_id: int, kind: str) -> int:
        assert self._db
        await self._touch_practice(user_id, kind)
        day = _now().strftime("%Y-%m-%d")
        await self._db.execute(
            """INSERT INTO usage_counters (user_id, kind, day, used) VALUES (?, ?, ?, 1)
               ON CONFLICT(user_id, kind, day) DO UPDATE SET used = used + 1""",
            (user_id, kind, day),
        )
        await self._db.commit()
        cur = await self._db.execute(
            "SELECT used FROM usage_counters WHERE user_id = ? AND kind = ? AND day = ?",
            (user_id, kind, day),
        )
        row = await cur.fetchone()
        return row[0] if row else 1

    async def get_usage(self, user_id: int, kind: str) -> int:
        assert self._db
        day = _now().strftime("%Y-%m-%d")
        cur = await self._db.execute(
            "SELECT used FROM usage_counters WHERE user_id = ? AND kind = ? AND day = ?",
            (user_id, kind, day),
        )
        row = await cur.fetchone()
        return row[0] if row else 0

    async def within_limit(self, user_id: int, kind: str, limit: int) -> bool:
        """Free ограничен суточными лимитами, Plus — без ограничений."""
        assert self._db
        tier, _ = await self.get_plan(user_id)
        if tier != "free":
            return True
        return await self.get_usage(user_id, kind) < limit

    # ---------------- Авто-повторения ----------------
    async def users_with_due_cards(self, limit: int = 50) -> list[int]:
        assert self._db
        cur = await self._db.execute(
            """SELECT DISTINCT c.user_id FROM cards c
               WHERE c.next_review <= ?
               LIMIT ?""",
            (_now().isoformat(), limit),
        )
        return [r[0] for r in await cur.fetchall()]

    # ---------------- Напоминания ----------------
    async def get_notify_prefs(self, user_id: int) -> tuple[bool, int]:
        """(включены, час местного времени). По умолчанию включены в 19:00."""
        assert self._db
        cur = await self._db.execute(
            "SELECT enabled, hour FROM notify_prefs WHERE user_id = ?", (user_id,)
        )
        row = await cur.fetchone()
        return (bool(row[0]), int(row[1])) if row else (True, 19)

    async def set_notify_prefs(self, user_id: int, enabled: bool, hour: int) -> None:
        assert self._db
        await self._db.execute(
            """INSERT INTO notify_prefs (user_id, enabled, hour) VALUES (?, ?, ?)
               ON CONFLICT(user_id) DO UPDATE SET
                 enabled = excluded.enabled, hour = excluded.hour""",
            (user_id, int(enabled), int(hour)),
        )
        await self._db.commit()

    async def get_progress(self, user_id: int) -> dict:
        """Коробки колоды, срок повторения, серия дней и число действий."""
        from datetime import date, timedelta
        assert self._db
        cur = await self._db.execute(
            "SELECT box, COUNT(*) FROM cards WHERE user_id = ? GROUP BY box", (user_id,)
        )
        boxes = {int(b): int(n) for b, n in await cur.fetchall()}
        cur = await self._db.execute(
            "SELECT COUNT(*) FROM cards WHERE user_id = ? AND next_review <= ?",
            (user_id, _now().isoformat()),
        )
        due = int((await cur.fetchone())[0])
        kinds = ('words', 'quiz', 'chat', 'review')
        cur = await self._db.execute(
            """SELECT DISTINCT day FROM usage_counters
               WHERE user_id = ? AND kind IN ('words','quiz','chat','review')
               ORDER BY day DESC""", (user_id,)
        )
        days = {r[0] for r in await cur.fetchall()}
        cur = await self._db.execute(
            """SELECT COALESCE(SUM(used), 0) FROM usage_counters
               WHERE user_id = ? AND kind IN ('words','quiz','chat','review')""", (user_id,)
        )
        actions = int((await cur.fetchone())[0])
        today = _now().date()
        d = today if today.isoformat() in days else today - timedelta(days=1)
        streak = 0
        while d.isoformat() in days:
            streak += 1
            d -= timedelta(days=1)
        best = run = 0
        prev = None
        for day in sorted(days):
            dd = date.fromisoformat(day)
            run = run + 1 if prev and (dd - prev).days == 1 else 1
            best = max(best, run)
            prev = dd
        cur = await self._db.execute(
            "SELECT COALESCE(SUM(used), 0) FROM usage_counters "
            "WHERE user_id = ? AND kind = 'practice_sec'", (user_id,)
        )
        seconds = int((await cur.fetchone())[0])
        cur = await self._db.execute(
            """SELECT kind, SUM(used) AS n FROM usage_counters
               WHERE user_id = ? AND kind LIKE 'topic:%'
               GROUP BY kind ORDER BY n DESC LIMIT 3""", (user_id,)
        )
        topic_rows = [(r[0].split(":", 1)[1], int(r[1])) for r in await cur.fetchall()]
        return {"boxes": boxes, "due": due, "days": len(days),
                "streak": streak, "best_streak": best, "actions": actions,
                "seconds": seconds, "topics": topic_rows}

    async def add_usage(self, user_id: int, kind: str, amount: int) -> None:
        """Прибавить произвольное значение к дневному счётчику."""
        assert self._db
        if amount <= 0:
            return
        day = _now().strftime("%Y-%m-%d")
        await self._db.execute(
            """INSERT INTO usage_counters (user_id, kind, day, used) VALUES (?, ?, ?, ?)
               ON CONFLICT(user_id, kind, day) DO UPDATE SET used = used + ?""",
            (user_id, kind, day, amount, amount),
        )
        await self._db.commit()

    async def _touch_practice(self, user_id: int, kind: str) -> None:
        """Оценка времени практики: складываем интервалы между близкими действиями."""
        if kind not in ("words", "quiz", "chat", "review"):
            return
        now = _now()
        prev = _LAST_ACTION.get(user_id)
        _LAST_ACTION[user_id] = now
        if prev is None:
            return
        gap = (now - prev).total_seconds()
        if 0 < gap <= 300:
            await self.add_usage(user_id, "practice_sec", int(gap))

    # ---------------- Профиль: CEFR и цель ----------------
    async def get_chat_state(self, user_id: int) -> dict:
        """Состояние разговора между сессиями: тема, ход, история, озвучка."""
        assert self._db
        import json as _json
        cur = await self._db.execute(
            "SELECT topic, turn, history, voice FROM chat_state WHERE user_id = ?",
            (user_id,),
        )
        row = await cur.fetchone()
        if not row:
            return {"topic": None, "turn": 0, "history": [], "voice": False}
        try:
            hist = _json.loads(row[2] or "[]")
        except Exception:
            hist = []
        return {"topic": row[0], "turn": row[1] or 0,
                "history": hist[-12:], "voice": bool(row[3])}

    async def save_chat_state(self, user_id: int, topic, turn: int,
                              history: list, voice: bool) -> None:
        assert self._db
        import json as _json
        await self._db.execute(
            """INSERT INTO chat_state (user_id, topic, turn, history, voice, updated_at)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(user_id) DO UPDATE SET
                 topic = excluded.topic, turn = excluded.turn,
                 history = excluded.history, voice = excluded.voice,
                 updated_at = excluded.updated_at""",
            (user_id, topic, int(turn),
             _json.dumps(history[-12:], ensure_ascii=False),
             1 if voice else 0, _now().isoformat()),
        )
        await self._db.commit()

    async def get_profile(self, user_id: int) -> dict:
        assert self._db
        cur = await self._db.execute(
            "SELECT cefr, goal FROM user_profile WHERE user_id = ?", (user_id,)
        )
        row = await cur.fetchone()
        return {"cefr": row[0], "goal": row[1]} if row else {"cefr": None, "goal": None}

    async def set_profile(self, user_id: int, cefr: str | None = None,
                          goal: str | None = None) -> None:
        """Меняет только переданные поля, остальные сохраняет."""
        assert self._db
        cur = await self.get_profile(user_id)
        new_cefr = cefr if cefr is not None else cur["cefr"]
        new_goal = goal if goal is not None else cur["goal"]
        await self._db.execute(
            """INSERT INTO user_profile (user_id, cefr, goal, updated_at) VALUES (?, ?, ?, ?)
               ON CONFLICT(user_id) DO UPDATE SET
                 cefr = excluded.cefr, goal = excluded.goal, updated_at = excluded.updated_at""",
            (user_id, new_cefr, new_goal, _now().isoformat()),
        )
        await self._db.commit()

    async def export_user(self, user_id: int) -> dict:
        """Полная выгрузка прогресса в переносимый вид (не зависит от схемы бота)."""
        assert self._db
        out = {"user_id": user_id, "exported_at": _now().isoformat()}
        cur = await self._db.execute("SELECT level FROM users WHERE user_id = ?", (user_id,))
        row = await cur.fetchone()
        out["level"] = row[0] if row else None
        out["profile"] = await self.get_profile(user_id)
        out["stats"] = await self.get_stats(user_id)
        cur = await self._db.execute(
            "SELECT word, box, next_review, translation, example FROM cards "
            "WHERE user_id = ? ORDER BY word", (user_id,)
        )
        cols = ("word", "box", "next_review", "translation", "example")
        out["cards"] = [dict(zip(cols, r)) for r in await cur.fetchall()]
        cur = await self._db.execute(
            "SELECT day, kind, used FROM usage_counters WHERE user_id = ? ORDER BY day, kind",
            (user_id,)
        )
        out["activity"] = [dict(zip(("day", "kind", "used"), r)) for r in await cur.fetchall()]
        return out

    async def get_notify_tz(self, user_id: int) -> int:
        """Смещение от UTC для напоминаний; по умолчанию из NOTIFY_TZ_OFFSET."""
        assert self._db
        cur = await self._db.execute(
            "SELECT tz_offset FROM notify_prefs WHERE user_id = ?", (user_id,)
        )
        row = await cur.fetchone()
        return int(row[0]) if row and row[0] is not None else _DEFAULT_TZ

    async def set_notify_tz(self, user_id: int, offset: int) -> None:
        assert self._db
        offset = max(-12, min(14, int(offset)))
        await self._db.execute(
            """INSERT INTO notify_prefs (user_id, tz_offset) VALUES (?, ?)
               ON CONFLICT(user_id) DO UPDATE SET tz_offset = excluded.tz_offset""",
            (user_id, offset),
        )
        await self._db.commit()

    # ---------------- Платежи ----------------
    async def add_payment(self, user_id: int, tier: str, stars: int, days: int,
                          charge_id: str | None = None) -> bool:
        """Записать оплату. UNIQUE по charge_id защищает от двойного учёта."""
        assert self._db
        cur = await self._db.execute(
            """INSERT OR IGNORE INTO payments
               (user_id, tier, stars, days, charge_id, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (user_id, tier, int(stars), int(days), charge_id, _now().isoformat()),
        )
        await self._db.commit()
        return cur.rowcount > 0

    # ---------------- Обращения пользователей ----------------
    async def add_feedback(self, user_id: int, kind: str, text: str, tier: str) -> int:
        """Сохранить обращение, вернуть его номер."""
        assert self._db
        cur = await self._db.execute(
            """INSERT INTO feedback (user_id, kind, text, tier, status, created_at)
               VALUES (?, ?, ?, ?, 'new', ?)""",
            (user_id, kind, text, tier, _now().isoformat()),
        )
        await self._db.commit()
        return int(cur.lastrowid)

    # ---------------- Приглашения ----------------
    async def user_exists(self, user_id: int) -> bool:
        assert self._db
        cur = await self._db.execute("SELECT 1 FROM users WHERE user_id = ?", (user_id,))
        return await cur.fetchone() is not None

    async def add_referral(self, inviter_id: int, invitee_id: int) -> bool:
        """Приглашение учитывается только для нового человека и не самому себе."""
        assert self._db
        if inviter_id == invitee_id:
            return False
        cur = await self._db.execute(
            """INSERT OR IGNORE INTO referrals (inviter_id, invitee_id, created_at)
               VALUES (?, ?, ?)""",
            (inviter_id, invitee_id, _now().isoformat()),
        )
        await self._db.commit()
        return cur.rowcount > 0

    async def referral_stats(self, user_id: int) -> dict:
        assert self._db
        cur = await self._db.execute(
            """SELECT COUNT(*) total,
                      SUM(CASE WHEN activated_at IS NOT NULL THEN 1 ELSE 0 END) active,
                      SUM(CASE WHEN rewarded_at IS NOT NULL THEN 1 ELSE 0 END) rewarded
               FROM referrals WHERE inviter_id = ?""", (user_id,))
        row = await cur.fetchone()
        return {"total": row[0] or 0, "active": row[1] or 0, "rewarded": row[2] or 0}

    async def extend_plan(self, user_id: int, days: int) -> str | None:
        """Продлить Plus. Бессрочный доступ остаётся бессрочным."""
        assert self._db
        tier, exp = await self.get_plan(user_id)
        if tier == "plus" and exp is None:
            return None
        base = _now()
        if tier == "plus" and exp:
            try:
                cur_exp = dt.datetime.fromisoformat(exp)
                if cur_exp > base:
                    base = cur_exp
            except ValueError:
                pass
        new_exp = (base + dt.timedelta(days=days)).isoformat()
        await self._db.execute(
            """INSERT INTO plans (user_id, tier, expires_at) VALUES (?, 'plus', ?)
               ON CONFLICT(user_id) DO UPDATE SET tier='plus', expires_at=excluded.expires_at""",
            (user_id, new_exp))
        await self._db.commit()
        return new_exp

    async def activate_referral(self, invitee_id: int, inviter_days: int = 7,
                                invitee_days: int = 3, max_rewards: int = 10) -> dict | None:
        """Провести приглашение по факту первого слова. Повторный вызов ничего не даёт."""
        assert self._db
        cur = await self._db.execute(
            "SELECT id, inviter_id FROM referrals WHERE invitee_id=? AND activated_at IS NULL",
            (invitee_id,))
        row = await cur.fetchone()
        if not row:
            return None
        rid, inviter = row[0], row[1]
        now = _now().isoformat()
        await self._db.execute("UPDATE referrals SET activated_at=? WHERE id=?", (now, rid))
        cur = await self._db.execute(
            "SELECT COUNT(*) FROM referrals WHERE inviter_id=? AND rewarded_at IS NOT NULL",
            (inviter,))
        used = (await cur.fetchone())[0]
        rewarded = used < max_rewards
        if rewarded:
            await self._db.execute("UPDATE referrals SET rewarded_at=? WHERE id=?", (now, rid))
        await self._db.commit()
        await self.extend_plan(invitee_id, invitee_days)
        if rewarded:
            await self.extend_plan(inviter, inviter_days)
        return {"id": rid, "inviter": inviter, "rewarded": rewarded,
                "inviter_days": inviter_days if rewarded else 0, "invitee_days": invitee_days}

    async def pending_referral_notifications(self, limit: int = 20) -> list[dict]:
        assert self._db
        cur = await self._db.execute(
            """SELECT id, inviter_id, invitee_id, rewarded_at FROM referrals
               WHERE activated_at IS NOT NULL AND notified_at IS NULL LIMIT ?""", (limit,))
        return [{"id": r[0], "inviter": r[1], "invitee": r[2], "rewarded": r[3] is not None}
                for r in await cur.fetchall()]

    async def mark_referral_notified(self, rid: int) -> None:
        assert self._db
        await self._db.execute("UPDATE referrals SET notified_at=? WHERE id=?",
                               (_now().isoformat(), rid))
        await self._db.commit()
