"""Голосовой движок бота: распознавание (STT) и синтез (TTS).

Бесплатные варианты, доступные из РФ (проверяйте актуальность тарифов):

STT (распознавание голосовых сообщений):
  • OpenAI-совместимый Whisper через Selectel / Cloud.ru / YandexGPT API
    (задайте SPEECH_BASE_URL + SPEECH_API_KEY).
  • Локальный faster-whisper — полностью бесплатно и без интернета
    (установите: pip install faster-whisper).

TTS (озвучка ответов бота):
  • Yandex SpeechKit (бесплатный пакет ~2000 символов/сутки, из РФ работает стабильно;
    задайте YANDEX_SPEECHKIT_API_KEY и YANDEX_SPEECHKIT_FOLDER_ID).
  • Локальный Piper — бесплатно, офлайн (pip install piper-tts).
  • Если ничего не настроено — бот отвечает текстом (голос опционален).

Все сетевые вызовы синхронные — вызываются через asyncio.to_thread.
"""
from __future__ import annotations

import io
import json
import logging
import os
import urllib.request
import wave

from config import OPENAI_API_KEY, OPENAI_BASE_URL, SPEECH_API_KEY, SPEECH_BASE_URL

logger = logging.getLogger(__name__)

YANDEX_SPEECHKIT_API_KEY = os.getenv("YANDEX_SPEECHKIT_API_KEY", "")
YANDEX_SPEECHKIT_FOLDER_ID = os.getenv("YANDEX_SPEECHKIT_FOLDER_ID", "")


# ----------------------------- STT: Whisper -----------------------------

_whisper_model = None  # ленивая загрузка локальной модели


def _stt_openai_compatible(audio_bytes: bytes, filename: str = "voice.ogg") -> str | None:
    """Распознавание через любой OpenAI-совместимый /audio/transcriptions эндпоинт."""
    if not SPEECH_BASE_URL or not SPEECH_API_KEY:
        return None
    boundary = "----englishbotboundary"
    body = io.BytesIO()
    body.write(f"--{boundary}\r\n".encode())
    body.write(
        b'Content-Disposition: form-data; name="model"\r\n\r\nwhisper-1\r\n'.replace(
            b"whisper-1", os.getenv("WHISPER_MODEL", "whisper-1").encode()
        )
    )
    body.write(f"--{boundary}\r\n".encode())
    body.write(
        f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
        f"Content-Type: audio/ogg\r\n\r\n".encode()
    )
    body.write(audio_bytes)
    body.write(f"\r\n--{boundary}--\r\n".encode())

    req = urllib.request.Request(
        f"{SPEECH_BASE_URL.rstrip('/')}/audio/transcriptions",
        data=body.getvalue(),
        headers={
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "Authorization": f"Bearer {SPEECH_API_KEY}",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read().decode())
        return data.get("text")
    except Exception as exc:  # noqa: BLE001
        logger.warning("Whisper API STT failed: %s", exc)
        return None


def _stt_faster_whisper(audio_bytes: bytes) -> str | None:
    """Локальное бесплатное распознавание через faster-whisper (ogg/wav)."""
    global _whisper_model
    try:
        from faster_whisper import WhisperModel  # импорт здесь — зависимость опциональна
    except ImportError:
        return None
    try:
        if _whisper_model is None:
            model_size = os.getenv("WHISPER_LOCAL_MODEL", "base")
            _whisper_model = WhisperModel(model_size, device="cpu", compute_type="int8")
        segments, _info = _whisper_model.transcribe(
            io.BytesIO(audio_bytes), language="en", beam_size=1
        )
        text = " ".join(seg.text.strip() for seg in segments)
        return text or None
    except Exception as exc:  # noqa: BLE001
        logger.warning("faster-whisper STT failed: %s", exc)
        return None


def stt_available() -> bool:
    if SPEECH_BASE_URL and SPEECH_API_KEY:
        return True
    try:
        import faster_whisper  # noqa: F401
        return True
    except ImportError:
        return False


def transcribe(audio_bytes: bytes, filename: str = "voice.ogg") -> str | None:
    """Синхронная функция (запускать в executor/to_thread)."""
    text = _stt_openai_compatible(audio_bytes, filename)
    if text:
        return text
    return _stt_faster_whisper(audio_bytes)


# ----------------------------- TTS: озвучка -----------------------------

def _tts_yandex(text: str) -> bytes | None:
    """Yandex SpeechKit — бесплатный пакет, работает из РФ без прокси."""
    if not (YANDEX_SPEECHKIT_API_KEY and YANDEX_SPEECHKIT_FOLDER_ID):
        return None
    payload = json.dumps({
        "text": text[:200],  # лимит бесплатного пакета на запрос
        "voice": os.getenv("YANDEX_TTS_VOICE", "albina"),
        "lang": "en-US",
        "format": "mp3",
    }).encode()
    req = urllib.request.Request(
        "https://tts.api.cloud.yandex.net/speech/v1/tts:synthesize",
        data=payload,
        headers={
            "Authorization": f"Api-Key {YANDEX_SPEECHKIT_API_KEY}",
            "FolderId": YANDEX_SPEECHKIT_FOLDER_ID,
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.read()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Yandex TTS failed: %s", exc)
        return None


def _tts_openai_compatible(text: str) -> bytes | None:
    """OpenAI-совместимый /audio/speech (Selectel, Cloud.ru, локальный faster-piper и т.п.)."""
    if not (SPEECH_BASE_URL and SPEECH_API_KEY):
        return None
    payload = json.dumps({
        "model": os.getenv("TTS_MODEL", "tts-1"),
        "input": text[:500],
        "voice": os.getenv("TTS_VOICE", "alloy"),
        "response_format": "mp3",
    }).encode()
    req = urllib.request.Request(
        f"{SPEECH_BASE_URL.rstrip('/')}/audio/speech",
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {SPEECH_API_KEY}",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.read()
    except Exception as exc:  # noqa: BLE001
        logger.warning("TTS API failed: %s", exc)
        return None


_piper_voice = None
_piper_voice_path = ""


def _tts_piper(text: str) -> bytes | None:
    """Локальный Piper — бесплатно и офлайн (pip install piper-tts)."""
    global _piper_voice, _piper_voice_path
    try:
        from piper import PiperVoice
    except ImportError:
        return None
    try:
        model_path = os.getenv("PIPER_MODEL_PATH", "")
        if not model_path or not os.path.exists(model_path):
            return None
        if _piper_voice is None or _piper_voice_path != model_path:
            _piper_voice = PiperVoice.load(model_path)
            _piper_voice_path = model_path
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wav_file:
            # synthesize_wav пишет весь текст в один wav-файл (API piper-tts >= 1.3)
            _piper_voice.synthesize_wav(text[:500], wav_file)
        return _wav_to_ogg(buf.getvalue())
    except Exception as exc:  # noqa: BLE001
        logger.warning("Piper TTS failed: %s", exc)
        return None


def _wav_to_ogg(wav_bytes: bytes) -> bytes | None:
    """Конвертировать wav в ogg/opus — формат голосовых сообщений Telegram."""
    import subprocess
    try:
        proc = subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", "pipe:0",
             "-c:a", "libopus", "-b:a", "32k", "-ar", "48000", "-ac", "1",
             "-f", "ogg", "pipe:1"],
            input=wav_bytes, capture_output=True, timeout=30,
        )
        return proc.stdout if proc.returncode == 0 and proc.stdout else None
    except Exception:  # noqa: BLE001
        return None


def tts_available() -> bool:
    if YANDEX_SPEECHKIT_API_KEY or (SPEECH_BASE_URL and SPEECH_API_KEY):
        return True
    try:
        import piper  # noqa: F401
        path = os.getenv("PIPER_MODEL_PATH", "")
        return bool(path and os.path.exists(path))
    except ImportError:
        return False


def synthesize(text: str) -> tuple[bytes, str] | None:
    """Вернуть (аудио_байты, 'mp3'|'ogg') или None, если TTS не настроен."""
    data = _tts_yandex(text)
    if data:
        return data, "mp3"
    data = _tts_openai_compatible(text)
    if data:
        return data, "mp3"
    data = _tts_piper(text)
    if data:
        return data, "ogg"
    return None
