"""Конфигурация бота. Токен берётся из переменной окружения BOT_TOKEN."""
import os

BOT_TOKEN = os.getenv("BOT_TOKEN", "")

DB_PATH = os.getenv("DB_PATH", "db/english_bot.db")

# Интервалы повторения карточек (метод интервального повторения), в днях
REPETITION_INTERVALS_DAYS = [0, 1, 3, 7, 14, 30]

# --- Опционально: интеллектуальный диалог через LLM ---
# Цепочка провайдеров (failover) настроена в chat_engine.py:
#   Groq (GROQ_API_KEY) → Ollama (OLLAMA_ENABLED=on) → офлайн rule-based движок.
DEFAULT_GROQ_BASE_URL = "https://api.groq.com/openai/v1"

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", os.getenv("GROQ_API_KEY", ""))
OPENAI_BASE_URL = os.getenv(
    "OPENAI_BASE_URL",
    DEFAULT_GROQ_BASE_URL if os.getenv("GROQ_API_KEY") else "https://api.openai.com/v1",
)
OPENAI_MODEL = os.getenv(
    "OPENAI_MODEL",
    "llama-3.3-70b-versatile" if os.getenv("GROQ_API_KEY") else "gpt-4o-mini",
)

# Локальный резервный LLM-движок (Ollama). Модель скачивается install-bot.sh
# при установке контейнера; включается строкой OLLAMA_ENABLED=on в .env.
OLLAMA_ENABLED = os.getenv("OLLAMA_ENABLED", "").lower() in ("1", "on", "true", "yes")
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:7b-instruct-q4_K_M")

# --- Голос: распознавание (STT) и синтез ответов (TTS) ---
# SPEECH_* — любой OpenAI-совместимый эндпоинт с /audio/transcriptions и /audio/speech
# (Select AI Selectel, Cloud.ru, локальный сервер). Если не задан — используется
# локальный faster-whisper для STT и Piper для TTS (ставятся install-bot.sh).
SPEECH_API_KEY = os.getenv("SPEECH_API_KEY", "")
SPEECH_BASE_URL = os.getenv("SPEECH_BASE_URL", "")
VOICE_REPLY_ENABLED = os.getenv("VOICE_REPLY_ENABLED", "off")  # off | on | toggle

from pathlib import Path
BASE_DIR = Path(__file__).parent

# === Константы для лимитов и подсказок (добавлено для совместимости) ===
class LIMITS:
    free_chat_messages_per_day = 15
    plus_voice_inputs_per_day = 15
    plus_tts_per_day = 10

UPGRADE_HINTS = {
    "voice": "🎙 Голосовые сообщения доступны только на тарифах Plus и Premium. /premium",
    "chat": "💬 Лимит разговора исчерпан. Без лимита — 👑 Premium: /premium"
}
