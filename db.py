"""Хранилище на SQLite: пользователи, прогресс карточек (интервальное повторение), статистика."""
from __future__ import annotations

import datetime as dt
import random
import logging
from dataclasses import dataclass
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
    created_at TEXT NOT NULL
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

class Database:
    def __init__(self, path: str = DB_PATH):
        self.path = path
        self._db: aiosqlite.Connection | None = None

    async def connect(self) -> None:
        self._db = await aiosqlite.connect(self.path)
        await self._db.executescript(_SCHEMA)
        
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
    async def register_user(self, user_id: int, username: str | None, level: str = "beginner") -> None:
        assert self._db
        await self._db.execute(
            """INSERT INTO users (user_id, username, level, created_at)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(user_id) DO UPDATE SET username = excluded.username""",
            (user_id, username, level, _now().isoformat()),
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
        
        # Локальный словарь как fallback
        local_index = {w: (t, e) for w, t, e in VOCABULARY.get(level, [])}
        
        for word, translation, example, box in rows:
            final_translation = translation or local_index.get(word, ("", ""))[0]
            final_example = example or local_index.get(word, ("", ""))[1]
            
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
            if box == 0 and new_box > 0:
                await self._db.execute(
                    "UPDATE stats SET learned = learned + 1 WHERE user_id = ?", (user_id,)
                )
        else:
            new_box = 0
            
        days = REPETITION_INTERVALS_DAYS[new_box]
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
    def random_word(level: str) -> CardItem:
        words = VOCABULARY.get(level) or VOCABULARY["beginner"]
        w, t, e = random.choice(words)
        return CardItem(w, t, e, 0)

    # ---------------- Статистика ----------------
    async def get_stats(self, user_id: int) -> dict:
        assert self._db
        cur = await self._db.execute(
            "SELECT learned, quiz_best FROM stats WHERE user_id = ?", (user_id,)
        )
        row = await cur.fetchone()
        learned, quiz_best = (row[0], row[1]) if row else (0, 0)
        
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
        return "premium", None  # ВРЕМЕННО: всем выдан Premium
        assert self._db
        cur = await self._db.execute("SELECT tier, expires_at FROM plans WHERE user_id = ?", (user_id,))
        row = await cur.fetchone()
        if not row:
            return "free", None
            
        tier, expires_at = row[0], row[1]
        if tier != "premium" and expires_at:
            if dt.datetime.fromisoformat(expires_at) <= _now():
                await self._db.execute(
                    "UPDATE plans SET tier = 'free', expires_at = NULL WHERE user_id = ?", (user_id,)
                )
                await self._db.commit()
                return "free", None
        return tier, expires_at

    async def set_plan(self, user_id: int, tier: str, days: int) -> None:
        assert self._db
        expires_at = None if tier == "premium" else next_period(days)
        await self._db.execute(
            """INSERT INTO plans (user_id, tier, expires_at) VALUES (?, ?, ?)
               ON CONFLICT(user_id) DO UPDATE SET tier = excluded.tier, expires_at = excluded.expires_at""",
            (user_id, tier, expires_at),
        )
        await self._db.commit()

    async def is_allowed(self, user_id: int, feature: str) -> bool:
        tier, _ = await self.get_plan(user_id)
        if tier == "premium":
            return True
        if feature == "voice":
            return tier == "plus"
        if feature == "topics_all":
            return tier == "plus"
        if feature == "auto_reviews":
            return tier == "plus"
        if feature == "full_dictionary":
            return tier == "plus"
        return False

    # ---------------- Дневные счётчики (лимиты) ----------------
    async def incr_usage(self, user_id: int, kind: str) -> int:
        assert self._db
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
        return True  # ВРЕМЕННО: лимиты отключены
        tier, _ = await self.get_plan(user_id)
        if tier != "free":
            return True
        return await self.get_usage(user_id, kind) < limit

    # ---------------- Авто-повторения ----------------
    async def users_with_due_cards(self, limit: int = 50) -> list[int]:
        assert self._db
        cur = await self._db.execute(
            """SELECT DISTINCT c.user_id FROM cards c
               JOIN plans p ON p.user_id = c.user_id
               WHERE c.next_review <= ? AND p.tier IN ('plus', 'premium')
               LIMIT ?""",
            (_now().isoformat(), limit),
        )
        return [r[0] for r in await cur.fetchall()]
