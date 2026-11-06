"""
Универсальный переводчик слов EN <-> RU.

Цепочка: локальная база -> SQLite-кэш -> RuEnDict -> LLM (Groq/Ollama) -> офлайн-подсказка.
"""
import asyncio
import json
import logging
import os
import re
import sqlite3
import threading
import urllib.request
from pathlib import Path

from config import BASE_DIR
from data.vocabulary import VOCABULARY

log = logging.getLogger("dictionary")

RUEDICT_URLS = [
    u for u in os.getenv(
        "RUEDICT_URL",
        "https://raw.githubusercontent.com/KristinaOpenSource/RuEnDict/master/RuEnDic.txt,"
        "https://cdn.jsdelivr.net/gh/KristinaOpenSource/RuEnDict@master/RuEnDic.txt",
    ).split(",") if u.strip()
]
CACHE_PATH = BASE_DIR / "db" / "translations.db"
RUEDICT_PATH = Path(os.getenv("RUEDICT_LOCAL_PATH") or (BASE_DIR / "db" / "ruendict.json"))

_word_re = re.compile(r"[A-Za-z][A-Za-z'’\-]{0,63}")
_cyr_re = re.compile(r"[А-Яа-яЁё][А-Яа-яЁё'’\-\s]{0,63}")

_en_ru: dict[str, str] = {}
_ru_en: dict[str, list[str]] = {}


def _index_local() -> None:
    """Индексация учебной базы. Формат записей — кортеж (en, ru, example)."""
    for words in VOCABULARY.values():
        for w in words:
            if isinstance(w, dict):
                en, ru = w.get("en", ""), w.get("ru", "")
            else:
                en, ru = w[0], w[1]
            key = en.lower().strip()
            if not key or not ru:
                continue
            _en_ru.setdefault(key, ru)
            for part in re.split(r",\s*", ru.lower()):
                part = part.strip()
                if not part:
                    continue
                _ru_en.setdefault(part, [])
                if key not in _ru_en[part]:
                    _ru_en[part].append(key)


_index_local()

_db_lock = threading.Lock()
_conn: sqlite3.Connection | None = None


def _conn_get() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        _conn = sqlite3.connect(CACHE_PATH, check_same_thread=False)
        _conn.execute("CREATE TABLE IF NOT EXISTS translations (src TEXT PRIMARY KEY, dst TEXT)")
    return _conn


def _cache_lookup(src: str) -> str | None:
    with _db_lock:
        row = _conn_get().execute("SELECT dst FROM translations WHERE src=?", (src,)).fetchone()
    return row[0] if row else None


def _cache_store(src: str, dst: str) -> None:
    with _db_lock:
        c = _conn_get()
        c.execute("INSERT OR REPLACE INTO translations VALUES (?,?)", (src, dst))
        c.commit()


_ruen_ru_en: dict[str, str] = {}
_ruen_en_ru: dict[str, list[str]] = {}
_ruen_loaded = False


def _parse_ruedict(raw: str) -> dict[str, str]:
    raw = raw.strip()
    if raw.startswith("{"):
        return json.loads(raw)
    pairs: dict[str, str] = {}
    for line in raw.splitlines():
        if ";" in line:
            ru, _, en = line.partition(";")
            ru, en = ru.strip().lower(), en.strip().lower()
            if ru and en:
                pairs.setdefault(ru, en)
    return pairs


def _load_ruedict_sync() -> bool:
    global _ruen_ru_en, _ruen_en_ru, _ruen_loaded
    if _ruen_loaded:
        return bool(_ruen_ru_en)
    path = RUEDICT_PATH
    try:
        if not path.exists() or path.stat().st_size < 1024:
            last_err: Exception | None = None
            for url in RUEDICT_URLS:
                try:
                    log.info("Скачиваем RuEnDict (%s)...", url[:60])
                    req = urllib.request.Request(url.strip(), headers={"User-Agent": "Mozilla/5.0"})
                    with urllib.request.urlopen(req, timeout=90) as r:
                        raw = r.read().decode("utf-8", errors="replace")
                    pairs = _parse_ruedict(raw)
                    if len(pairs) < 1000:
                        raise ValueError(f"слишком мало пар: {len(pairs)}")
                    tmp = path.with_suffix(".tmp")
                    tmp.write_text(json.dumps(pairs, ensure_ascii=False), encoding="utf-8")
                    tmp.rename(path)
                    break
                except Exception as e:
                    last_err = e
                    log.warning("Зеркало не сработало: %s", e)
            else:
                raise RuntimeError(f"все зеркала недоступны: {last_err}")
        pairs = json.loads(path.read_text(encoding="utf-8"))
        for ru, en in pairs.items():
            ru_l = ru.lower().strip()
            en_l = str(en).lower().strip()
            _ruen_ru_en.setdefault(ru_l, en_l)
            _ruen_en_ru.setdefault(en_l, []).append(ru_l)
        _ruen_loaded = True
        log.info("RuEnDict загружен: %d пар", len(_ruen_ru_en))
        return True
    except Exception as e:
        log.warning("RuEnDict недоступен (%s) — пропускаем уровень", e)
        _ruen_loaded = True
        return False


async def preload() -> None:
    await asyncio.to_thread(_load_ruedict_sync)
    try:
        from speech import stt_available, warmup_stt
        if stt_available():
            await asyncio.to_thread(warmup_stt)
    except Exception as e:
        log.debug("Whisper warmup skipped: %s", e)


_LLM_PROMPT = (
    "You are a compact English-Russian dictionary. Reply with EXACTLY one line:\n"
    "word|translation|pos|example_sentence\n"
    "where translation is in Russian (main meaning), pos is the part of speech "
    "(noun/verb/adj/adv/phrase), and example is a short natural English sentence "
    "using the word. No other text.\nQuery ({direction}): {query}"
)


async def _llm_translate(query: str, direction: str) -> tuple[str, str] | None:
    from chat_engine import ask_llm  # ленивый импорт против цикла

    prompt = _LLM_PROMPT.format(direction=direction, query=query)
    messages = [{"role": "user", "content": prompt}]
    reply = await ask_llm(messages, temperature=0.0, max_tokens=90)
    if not reply or reply.startswith("__"):
        return None
    parts = [p.strip() for p in reply.splitlines()[0].split("|")]
    if len(parts) >= 2 and parts[1]:
        note = parts[2] if len(parts) > 2 and parts[2] else ""
        example = parts[3] if len(parts) > 3 else ""
        extra = "; ".join(x for x in (note, example) if x)
        return parts[1], extra
    return None


def local_lookup(word: str, direction: str) -> tuple[str, str] | None:
    _load_ruedict_sync()
    w = word.lower().strip()
    if direction == "en-ru":
        if w in _en_ru:
            return _en_ru[w], "из учебной базы"
        rus = _ruen_en_ru.get(w)
        if rus:
            return rus[0], "RuEnDict"
    else:
        if w in _ru_en:
            return ", ".join(_ru_en[w][:3]), "из учебной базы"
        en = _ruen_ru_en.get(w)
        if en:
            return en, "RuEnDict"
    return None


async def translate(word: str, direction: str) -> tuple[str, str, str]:
    """Возвращает (перевод, источник, доп.строка). Всегда даёт ответ."""
    w = word.strip().lower()
    hit = local_lookup(w, direction)
    if hit:
        return hit[0], "local", hit[1]

    cached = _cache_lookup(f"{direction}:{w}")
    if cached:
        return cached, "cache", "ранее переведено"

    llm = await _llm_translate(w, direction)
    if llm:
        _cache_store(f"{direction}:{w}", llm[0])
        return llm[0], "llm", llm[1]

    fallback = ("Не удалось перевести сейчас (нет соединения со словарями и ИИ). "
                "Попробуйте ещё раз через минуту.")
    return fallback, "none", ""


def extract_word(text: str) -> str | None:
    """Одно слово из сообщения (EN или RU). None — если это не одно слово."""
    t = text.strip()
    if len(t) > 64:
        return None
    if _word_re.fullmatch(t):
        return t
    if _cyr_re.fullmatch(t):
        return t
    return None
