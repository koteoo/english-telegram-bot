"""Движок разговорного диалога: цепочка LLM-провайдеров + офлайн fallback.

LLM-цепочка (failover): Groq → Ollama (локально) → rule-based движок.
Провайдеры настраиваются через env-переменные (см. .env.example):
  • GROQ_API_KEY                — бесплатный Groq API (основной, работает из РФ)
  • OLLAMA_ENABLED=on           — локальная модель через Ollama (модель скачивается
                                  install-bot.sh при установке; резервный вариант)
При исчерпании лимитов Groq (HTTP 429 / rate limit) провайдер уходит в кулдаун
(LLM_COOLDOWN_SEC, по умолчанию 15 минут) и запрос автоматически идёт в Ollama;
если недоступны оба — отвечает офлайн rule-based движок. Кулдаун общий для всех
пользователей, поэтому дневные лимиты Groq растягиваются на весь бот.
"""
from __future__ import annotations

import json
import logging
import os
import random
import re
import time
import urllib.error
import urllib.request

from data.topics import TOPIC_BY_ID, topic_idea

logger = logging.getLogger(__name__)

GREETINGS = {"hi", "hello", "hey", "good morning", "good afternoon", "good evening"}
FAREWELLS = {"bye", "goodbye", "see you", "that's all", "stop", "end"}
THANKS = {"thanks", "thank you", "ok", "okay", "great", "cool", "nice"}


# ------------------------- LLM-режим: цепочка провайдеров -------------------------

class Provider:
    """Один OpenAI-совместимый LLM-эндпоинт с кулдауном при ошибках."""

    def __init__(self, name: str, base_url: str, api_key: str, model: str):
        self.name = name
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.disabled_until = 0.0  # unix ts, до которого провайдер в кулдауне

    @property
    def configured(self) -> bool:
        return bool(self.base_url and self.api_key and self.model)

    def available(self) -> bool:
        return self.configured and time.time() >= self.disabled_until

    def cooldown(self, seconds: float) -> None:
        self.disabled_until = max(self.disabled_until, time.time() + seconds)
        logger.warning("Provider %s: кулдаун %.0f сек (%.0f мин)",
                       self.name, seconds, seconds / 60)

    def reply(self, history: list[dict], topic_id: str | None, level: str) -> str:
        topic_name = TOPIC_BY_ID[topic_id]["title"] if topic_id in TOPIC_BY_ID else "free conversation"
        system = (
            "You are a friendly English tutor chatting with a learner on Telegram. "
            f"The learner's level is {level}. Current topic: {topic_name}. "
            "Keep replies short (2-4 sentences), always in English, ask a follow-up question, "
            "gently correct mistakes, and occasionally suggest one useful phrase for the topic."
        )
        
        # --- Динамическое окно контекста ---
        MAX_CONTEXT_CHARS = 2500
        context_messages = []
        current_length = len(system)
        
        for msg in reversed(history):
            msg_len = len(msg.get("content", ""))
            if current_length + msg_len > MAX_CONTEXT_CHARS:
                context_messages.insert(0, {
                    "role": "system",
                    "content": "[Previous context truncated]"
                })
                break
            context_messages.insert(0, msg)
            current_length += msg_len
        # ------------------------------------------

        messages = [{"role": "system", "content": system}] + context_messages
        
        payload = json.dumps({"model": self.model, "messages": messages, "temperature": 0.7})
        req = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=payload.encode(),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
        )
        timeout = int(os.getenv("OLLAMA_TIMEOUT" if self.name == "ollama" else "LLM_TIMEOUT", "60"))
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode())
            return data["choices"][0]["message"]["content"].strip()


COOLDOWN_SEC = int(os.getenv("LLM_COOLDOWN_SEC", "900"))  # 15 минут

_groq_key = os.getenv("GROQ_API_KEY", "")
_providers: list[Provider] = [
    Provider(
        "groq",
        os.getenv("GROQ_BASE_URL", "https://api.groq.com/openai/v1"),
        _groq_key or os.getenv("OPENAI_API_KEY", ""),
        os.getenv("OPENAI_MODEL", "llama-3.3-70b-versatile" if _groq_key else "gpt-4o-mini"),
    ),
    Provider(
        "ollama",
        os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1"),
        os.getenv("OLLAMA_API_KEY", "ollama" if os.getenv("OLLAMA_ENABLED", "").lower() in ("1", "on", "true", "yes") else ""),
        os.getenv("OLLAMA_MODEL", "qwen2.5:7b-instruct-q4_K_M"),
    ),
]

# Ключевые слова ответов об исчерпании лимита (Groq/OpenAI/аналоги)
_LIMIT_MARKERS = ("rate limit", "ratelimit", "too many requests", "quota",
                  "tokens per day", "requests per minute")


def _is_limit_error(exc: Exception) -> bool:
    if isinstance(exc, urllib.error.HTTPError) and exc.code == 429:
        return True
    text = str(exc).lower()
    return any(m in text for m in _LIMIT_MARKERS)


def llm_available() -> bool:
    """Есть ли хотя бы один настроенный LLM-провайдер (для отображения режима)."""
    return any(p.configured for p in _providers)


def active_provider_name() -> str | None:
    for p in _providers:
        if p.available():
            return p.name
    return None


def _llm_reply(history: list[dict], topic_id: str | None, level: str) -> str:
    """Синхронный вызов LLM с failover по цепочке (запускается в executor).

    Поднимает RuntimeError, если ни один провайдер не ответил, —
    вызывающий код тогда использует офлайн-движок.
    """
    errors: list[str] = []
    for p in _providers:
        if not p.available():
            continue
        try:
            return p.reply(history, topic_id, level)
        except Exception as exc:  # noqa: BLE001
            if _is_limit_error(exc):
                p.cooldown(COOLDOWN_SEC)
                errors.append(f"{p.name}: лимит исчерпан, пауза {COOLDOWN_SEC // 60} мин")
            else:
                # сетевые/5xx ошибки — короткий кулдаун, чтобы не долбить упавший сервис
                p.cooldown(60)
                errors.append(f"{p.name}: {exc}")
    raise RuntimeError("; ".join(errors) or "no LLM provider configured")


# ------------------------- Локальный rule-based режим -------------------------

def _clean(text: str) -> str:
    return re.sub(r"[^\w\s']", " ", text.lower()).strip()


def _word_count(text: str) -> int:
    return len([w for w in _clean(text).split() if w])


class LocalChatEngine:
    """Поддерживает диалог по теме без внешних API."""

    reactions = [
        "That's interesting! Tell me more about it.",
        "Nice! Why do you think so?",
        "I see 👍 What happened next?",
        "Good answer! Can you give me an example?",
        "Wow, sounds great! How did that make you feel?",
    ]
    praise_long = [
        "Excellent! That was a detailed answer 💪",
        "Great job — you explained it really well!",
        "Impressive! Your English is getting stronger.",
    ]
    encourage_short = [
        "Good start! Try to add one more detail next time 🙂",
        "Nice! Now tell me a bit more — why? when? with whom?",
        "OK! Imagine you're telling a friend — add some details.",
    ]
    corrections_hint = [
        "Small tip: after 'I' use 'am', and don't forget articles (a / the).",
        "Tip: for past events use Past Simple: 'I went', 'we saw', 'it was'.",
        "Tip: 'very much' goes at the end: 'I like it very much.'",
    ]

    def reply(self, user_text: str, topic_id: str | None, turn: int) -> tuple[str, int]:
        """Вернуть (ответ_боту, новый_номер_хода)."""
        clean = _clean(user_text)
        words = _word_count(user_text)

        if any(g in clean for g in FAREWELLS):
            return ("See you soon! 👋 Come back whenever you want to practise English.", turn)

        topic = TOPIC_BY_ID.get(topic_id or "")

        # первое сообщение в теме — реагируем на приветствие и задаём первый вопрос
        if turn == 0 or any(g in clean for g in GREETINGS):
            if topic:
                q = topic["questions"][0]
                idea = topic_idea(topic, 0)
                return (
                    f"Hi! 😊 Let's chat about <b>{topic['emoji']} {topic['title']}</b>.\n\n"
                    f"💡 Today's idea: <i>{idea}</i>\n\nHere is my first question for you:\n"
                    f"<b>{q}</b>",
                    turn + 1,
                )
            return (
                "Hi! 😊 Choose a topic and we'll have a nice chat in English. "
                "What would you like to talk about?",
                turn + 1,
            )

        if any(t in clean for t in THANKS) and words <= 3:
            hint = random.choice(self.corrections_hint)
            return (f"You're welcome! 🙌 {hint} Ready for another question?", turn + 1)

        feedback = ""
        if words >= 12:
            feedback = random.choice(self.praise_long) + "\n\n"
        elif words <= 4:
            feedback = random.choice(self.encourage_short) + "\n\n"

        if topic:
            q_index = min(1 + ((turn - 1) % (len(topic["questions"]) - 1)), len(topic["questions"]) - 1)
            question = topic["questions"][q_index]
            idea_idx = (turn - 1) // len(topic["questions"])
            idea_line = ""
            if idea_idx > 0 and idea_idx % 2 == 0:
                idea_line = f"\n💡 New idea: <i>{topic_idea(topic, idea_idx)}</i>\n"
            reaction = random.choice(self.reactions)
            phrase_en, phrase_ru = random.choice(topic["phrases"])
            return (
                f"{feedback}{reaction}\n\n"
                f"🎓 Useful phrase: <b>{phrase_en}</b>\n<i>({phrase_ru})</i>\n"
                f"{idea_line}\nMy next question:\n<b>{question}</b>",
                turn + 1,
            )

        question = random.choice(
            ["How are you today?", "What did you do yesterday?", "Tell me about your day!"]
        )
        return (f"{feedback}{random.choice(self.reactions)}\n\nAnd a quick question: <b>{question}</b>", turn + 1)


local_engine = LocalChatEngine()

# === Заглушка для совместимости со старым dictionary.py ===
async def ask_llm(messages: list, temperature: float = 0.7, max_tokens: int = 100) -> str | None:
    """Временная заглушка, чтобы старый dictionary.py не падал при импорте."""
    return None
