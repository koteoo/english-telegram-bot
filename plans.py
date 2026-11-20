"""Тарифные планы бота и оплата Telegram Stars.

Free     — словарь только Beginner, 5 карточек/день, квиз 3 вопроса/день,
           4 открытые темы, разговор без голоса (лимит сообщений в день).
Plus     — голосовые сообщения с лимитами (STT/TTS), все словари, квизы,
           авто-повторения слов, расширенные темы.
Premium  — всё включено без ограничений.

Цены указаны в Telegram Stars (1000 ⭐ ≈ $10 для покупателя; вывод — ~$0.78/1000⭐).
Все лимиты можно переопределить переменными окружения.
"""
from __future__ import annotations

import datetime as dt
import os
from dataclasses import dataclass

PLUS_DAYS = int(os.getenv("PLUS_DAYS", "30"))

PLUS_STARS = int(os.getenv("PLUS_STARS", "120"))         # ~$1.2 за 30 дней


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, ""))
    except (TypeError, ValueError):
        return default


@dataclass(frozen=True)
class Limits:
    free_words_per_day: int = 5          # Word of the Day / добавление слов
    free_quizzes_per_day: int = 3        # вопросы квиза
    free_chat_messages_per_day: int = 15 # реплики в разговорном чате
    plus_voice_replies_per_day: int = 10 # озвучка ответов (TTS)
    plus_voice_inputs_per_day: int = 15  # распознавание голосовых (STT)
    free_voice_replies_per_day: int = 5  # озвучка ответов на Free
    free_voice_inputs_per_day: int = 5   # распознавание голосовых на Free
    open_topics_free: int = 4            # сколько тем открыто на бесплатном плане


LIMITS = Limits(
    free_words_per_day=_env_int("FREE_WORDS_PER_DAY", Limits.free_words_per_day),
    free_quizzes_per_day=_env_int("FREE_QUIZZES_PER_DAY", Limits.free_quizzes_per_day),
    free_chat_messages_per_day=_env_int("FREE_CHAT_MESSAGES_PER_DAY", Limits.free_chat_messages_per_day),
    plus_voice_replies_per_day=_env_int("PLUS_VOICE_REPLIES_PER_DAY", Limits.plus_voice_replies_per_day),
    plus_voice_inputs_per_day=_env_int("PLUS_VOICE_INPUTS_PER_DAY", Limits.plus_voice_inputs_per_day),
    free_voice_replies_per_day=_env_int("FREE_VOICE_REPLIES_PER_DAY", Limits.free_voice_replies_per_day),
    free_voice_inputs_per_day=_env_int("FREE_VOICE_INPUTS_PER_DAY", Limits.free_voice_inputs_per_day),
    open_topics_free=_env_int("OPEN_TOPICS_FREE", Limits.open_topics_free),
)

PLAN_NAMES = {"free": "🆓 Free", "plus": "💠 Plus"}

UPGRADE_HINTS = {
    "voice": "На бесплатном плане 5 озвучек и 5 голосовых в день. Без лимитов — 💠 Plus: /premium",
    "topics": "Эта тема откроется на 💠 Plus. Тарифы: /premium",
    "words": "На бесплатном плане доступно {limit} новых слов в день. Больше — на 💠 Plus: /premium",
    "quiz": "На бесплатном плане {limit} вопроса квиза в день. Без лимита — на 💠 Plus: /premium",
    "chat": "На бесплатном плане {limit} сообщений чата в день. Без лимита — на 💠 Plus: /premium",
    "auto_reviews": "Авто-повторения слов доступны на 💠 Plus. /premium",
}


def next_period(days: int) -> str:
    return (dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=days)).isoformat()

# Добровольная поддержка: любая сумма в целых звёздах, тариф не меняет.
DONATE_PRESETS = (50, 100, 250, 500)
DONATE_MIN = int(os.getenv("DONATE_MIN", "1"))
DONATE_MAX = int(os.getenv("DONATE_MAX", "10000"))
