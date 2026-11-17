"""
Универсальный переводчик слов EN <-> RU.

Цепочка: локальная база -> SQLite-кэш -> RuEnDict -> LLM (Groq/Ollama) -> офлайн-подсказка.
"""
import asyncio
from collections import defaultdict
import json
import logging
import os
import re
import sqlite3
import threading

try:
    import pymorphy3 as _morph_lib
    _MORPH = _morph_lib.MorphAnalyzer()
except ImportError:
    try:
        import pymorphy2 as _morph_lib
        _MORPH = _morph_lib.MorphAnalyzer()
    except ImportError:
        _MORPH = None

def _normalize_ru(word: str) -> str:
    if not _MORPH:
        return word.lower().strip()
    parsed = _MORPH.parse(word.lower().strip())
    if parsed:
        return parsed[0].normal_form
    return word.lower().strip()

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

MUELLER_RAW_PATH = BASE_DIR / "data" / "dicts" / "mueller-base.raw"

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
    load_full_en_ru_index()
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




def load_full_en_ru_index():
    """Читает mueller-base.raw напрямую и строит ЧИСТЫЙ индекс EN -> [List of RU]."""
    if not MUELLER_RAW_PATH.exists():
        log.warning("Mueller raw file not found at %s", MUELLER_RAW_PATH)
        return
    
    try:
        raw = MUELLER_RAW_PATH.read_text(encoding="utf-8", errors="replace")
        blocks = re.split(r"^_{3,}\s*$", raw, flags=re.M)
        
        # Регулярки для очистки
        phonetic_re = re.compile(r"\[[^\]]*\]")
        paren_re = re.compile(r"\([^)]*\)")
        marker_re = re.compile(r"(?:^|\s)_[A-Za-zА-Яа-яЁё]+\.?(?=\s|$)")
        numbering_re = re.compile(r"^\d+[.)]\s*")
        example_sep_re = re.compile(r":\s+") # Разделитель между переводом и примером
        
        temp_en_to_rus = defaultdict(list)
        
        for block in blocks:
            lines = [ln.strip() for ln in block.splitlines() if ln.strip()]
            if len(lines) < 2: continue
            
            head = lines[0].strip().lower()
            # Фильтр головы: только буквы/дефисы/апострофы, длина до 64
            if not re.match(r"^[a-z][a-z'’\-]{0,63}$", head): continue
            
            definition = " ".join(lines[1:])
            
            # 1. Удаляем фонетическую транскрипцию [...]
            def_clean = phonetic_re.sub(" ", definition)
            # 2. Удаляем содержимое в скобках (...)
            def_clean = paren_re.sub(" ", def_clean)
            # 3. Удаляем маркеры частей речи (_n., _v.t. и т.д.)
            def_clean = marker_re.sub(" ", def_clean)
            def_clean = marker_re.sub(" ", def_clean) # Второй проход
            # Отрезаем секцию идиом/примеров (начинается с "*)")
            def_clean = def_clean.split("*)")[0]
            
            # 4. Отделяем основное значение от примеров (обычно после двоеточия)
            # В Мюллере формат: "значение1, значение2 : пример1; пример2"
            # Мы берем ТОЛЬКО часть ДО первого двоеточия, если там есть кириллица
            main_part, _, example_part = def_clean.partition(":")
            
            target_text = main_part
            # Если в основной части нет кириллицы, пробуем взять из примеров (редкий случай)
            if not re.search(r"[А-Яа-яЁё]", target_text):
                target_text = example_part
                
            # Разбиваем на значения по запятым и точкам с запятой
            raw_meanings = re.split(r"\d+[.)]\s*|[;,]", target_text)
            
            valid_meanings = []
            for m in raw_meanings:
                m = m.strip()
                if not m: continue
                
                # Удаляем нумерацию вида "1)", "2."
                m = numbering_re.sub('', m).strip()
                
                # Схлопываем пробелы
                m = re.sub(r'\s+', ' ', m)
                
                # Удаляем пунктуацию по краям
                m = re.sub(r'^[\W_]+|[\W_]+$', '', m)
                
                # ФИНАЛЬНАЯ ОЧИСТКА МУСОРА:
                # 1. Если осталось латиница — пропускаем (это пример типа "in the morning")
                if re.search(r"[A-Za-z]", m):
                    continue
                    
                # 2. Если слишком длинно (>4 слов) — пропускаем (фраза/предложение)
                words_in_m = m.split()
                if len(words_in_m) == 0 or len(words_in_m) > 4:
                    continue
                    
                # 3. Если начинается не с русской буквы — пропускаем
                if not m[0].isalpha() or not ('а' <= m[0] <= 'я' or m[0] == 'ё'):
                    continue
                
                # 4. Убираем повторяющиеся слова в фразе (артефакты парсинга)
                # Например: "лёгкий лёгкий" -> "лёгкий"
                seen_words = set()
                clean_words = []
                for w in words_in_m:
                    if w not in seen_words:
                        clean_words.append(w)
                        seen_words.add(w)
                m = " ".join(clean_words)
                
                valid_meanings.append(m.lower())

            if valid_meanings:
                # Уникализируем список значений для этого английского слова
                unique_vals = list(dict.fromkeys(valid_meanings))[:5]
                temp_en_to_rus[head].extend(unique_vals)
        
        # Заменяем глобальный словарь
        global _ruen_en_ru
        _ruen_en_ru.clear()
        for en, rus_list in temp_en_to_rus.items():
            # Финальная проверка: оставляем только непустые списки
            if rus_list:
                _ruen_en_ru[en] = rus_list
                
        log.info("Full CLEAN EN->RU index loaded from Mueller: %d words", len(_ruen_en_ru))
        
    except Exception as e:
        log.error("Failed to load full EN->RU index: %s", e, exc_info=True)


async def preload() -> None:
    await asyncio.to_thread(_load_ruedict_sync)
    await asyncio.to_thread(_build_ru_multi)
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
    # Жесткая нормализация ввода: lower, strip, удаление пунктуации по краям
    w = word.lower().strip().strip(".!,;:? ")
    
    if not w:
        return None

    if direction == "en-ru":
        # 1. Проверка учебной базы (высокий приоритет)
        if w in _en_ru:
            val = _en_ru[w]
            # Если это список, берем первые 3 уникальных
            if isinstance(val, list):
                unique_vals = list(dict.fromkeys([str(v).strip() for v in val]))[:3]
                return ", ".join(unique_vals), "учебная база"
            else:
                return str(val).strip(), "учебная база"
        
        # 2. Поиск в индексе Мюллера (_ruen_en_ru)
        rus_list = _ruen_en_ru.get(w)
        if rus_list:
            clean_vals = []
            for raw_val in rus_list:
                val_str = str(raw_val).strip().lower()
                
                # ФИЛЬТРЫ ОТ МУСОРА:
                # 1. Пустое
                if not val_str: continue
                
                # 2. Содержит латинские буквы (примеры типа "in the morning")
                if re.search(r"[A-Za-z]", val_str): continue
                
                # 3. Содержит скобки или нумерацию ("б)", "1.", "(см.)")
                if any(char in val_str for char in "()[]{}"): continue
                if re.search(r"\d+[.)]", val_str): continue
                if re.search(r"[абвгдеёжзийклмнопрстуфхцчшщъыьэюя]\)", val_str): continue # Cyrillic letter followed by )
                
                # 4. Слишком длинно (>4 слов - скорее всего фраза/предложение)
                words = val_str.split()
                if len(words) == 0 or len(words) > 4: continue
                
                # 5. Начинается не с буквы
                if not val_str[0].isalpha(): continue
                
                # 6. Дубликаты внутри фразы (артефакты парсинга "лёгкий лёгкий")
                seen_words = set()
                deduped_words = []
                is_dup = False
                for wd in words:
                    if wd in seen_words:
                        is_dup = True
                        break
                    seen_words.add(wd)
                    deduped_words.append(wd)
                if is_dup and len(deduped_words) < len(words):
                    val_str = " ".join(deduped_words)
                
                clean_vals.append(val_str)
            
            if clean_vals:
                # Уникализируем весь список значений
                unique_final = list(dict.fromkeys(clean_vals))[:5]
                combined = ", ".join(unique_final)
                return combined, "RuEnDict"
                
    else:
        # Направление RU -> EN
        # 1. Прямое совпадение в старой базе
        if w in _ru_en:
            vals = _ru_en[w]
            if isinstance(vals, list):
                return ", ".join(str(v).strip() for v in vals[:3]), "учебная база"
            else:
                return str(vals).strip(), "учебная база"
        
        # 2. Нормализация русского слова (род, падеж, число)
        normalized_w = _normalize_ru(w)
        
        # 3. Поиск в новом индексе RuEnDict (ключи уже нормализованы при генерации ruendict.json)
        en = _ruen_ru_en.get(normalized_w)
        if en:
            return en, "RuEnDict (norm)"
            
        # 4. Fallback: поиск по оригинальному слову
        en_orig = _ruen_ru_en.get(w)
        if en_orig:
            return en_orig, "RuEnDict"
            
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



# --- Обратный индекс RU -> EN (несколько вариантов) ---
_ru_multi: dict[str, list[str]] = {}


def _build_ru_multi() -> None:
    """RU -> [EN, ...] из полного индекса Мюллера. Кэшируется на диск."""
    global _ru_multi
    if _ru_multi:
        return
    import pickle
    cache_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ru_multi_cache.pkl")
    if os.path.exists(cache_path):
        try:
            with open(cache_path, "rb") as fh:
                _ru_multi = pickle.load(fh)
            log.info("Обратный индекс RU->EN из кэша: %d ключей", len(_ru_multi))
            return
        except Exception:
            _ru_multi = {}
    if not _ruen_en_ru:
        return

    stop = {"и", "в", "во", "на", "с", "со", "по", "от", "до", "из", "к", "ко",
            "у", "о", "об", "за", "под", "над", "при", "для", "без", "через",
            "а", "но", "или", "не", "как", "что", "это", "то", "же", "бы"}
    memo = {}

    def norm(x):
        got = memo.get(x)
        if got is None:
            got = _normalize_ru(x) or x
            memo[x] = got
        return got

    scores = {}
    for en, ru_list in _ruen_en_ru.items():
        if not isinstance(ru_list, list) or " " in en:
            continue
        if not re.fullmatch(r"[a-z][a-z'\-]{1,24}", en):
            continue
        bonus = min(len(ru_list), 15)
        if en in _en_ru:
            bonus += 25
        for pos, raw in enumerate(ru_list[:10]):
            val = str(raw).strip().lower()
            if not val or re.search(r"[a-z]", val):
                continue
            if any(ch in val for ch in "()[]{}"):
                continue
            words = val.split()
            if not words or len(words) > 3:
                continue
            variants = [(norm(val), pos)]
            if len(words) > 1:
                for wd in words:
                    if len(wd) > 2 and wd not in stop:
                        variants.append((norm(wd), pos + 4))
            for key, pos_sc in variants:
                if not key:
                    continue
                sc = pos_sc - bonus
                bucket = scores.setdefault(key, {})
                if en not in bucket or sc < bucket[en]:
                    bucket[en] = sc
    _ru_multi = {
        key: sorted(bucket, key=lambda e: (bucket[e], len(e), e))[:8]
        for key, bucket in scores.items()
    }
    log.info("Обратный индекс RU->EN построен: %d ключей", len(_ru_multi))
    try:
        with open(cache_path, "wb") as fh:
            pickle.dump(_ru_multi, fh, protocol=4)
    except Exception:
        pass


_EN_PLURAL_IRREGULAR = {
    "man": "men", "woman": "women", "child": "children", "foot": "feet",
    "tooth": "teeth", "mouse": "mice", "goose": "geese", "person": "people",
    "ox": "oxen", "life": "lives", "knife": "knives", "wife": "wives",
    "leaf": "leaves", "wolf": "wolves", "half": "halves", "shelf": "shelves",
    "calf": "calves", "thief": "thieves", "loaf": "loaves", "self": "selves",
    "datum": "data", "criterion": "criteria", "phenomenon": "phenomena",
    "analysis": "analyses", "basis": "bases", "crisis": "crises",
    "thesis": "theses", "axis": "axes", "matrix": "matrices",
}

_EN_NO_PLURAL = {"news", "series", "species", "information", "advice",
                 "money", "music", "furniture", "equipment", "knowledge",
                 "progress", "traffic", "weather", "fun", "luck"}

_EN_ES_O = {"potato", "tomato", "hero", "echo", "veto", "torpedo", "embargo"}

_EN_NEEDS_ES = {"lens", "gas", "atlas", "bias", "canvas", "alias"}


def _ru_is_plural(word: str) -> bool:
    """True, если слово - именительный множественного: собаки, окна, очки."""
    m = _get_morph()
    if not m:
        return False
    for p in m.parse(word):
        if p.tag.POS != "NOUN" or "Sgtm" in p.tag:
            continue
        f = p.inflect({"plur", "nomn"})
        if f and f.word == word:
            return True
    return False


def _en_plural(word: str) -> str:
    """'dog' -> 'dogs', 'city' -> 'cities', 'wolf' -> 'wolves'."""
    if not word:
        return word
    parts = word.split()
    if len(parts) > 3:
        return word
    low = parts[-1].lower()
    if low in _EN_NO_PLURAL:
        return word
    # уже множественное: spectacles, specs
    if low.endswith("s") and not low.endswith(("ss", "us", "is")) and low not in _EN_NEEDS_ES:
        return word
    # прилагательные/причастия: spectacled, goggled
    if low.endswith("ed") and len(low) >= 6:
        return word
    if low in _EN_PLURAL_IRREGULAR:
        new = _EN_PLURAL_IRREGULAR[low]
    elif len(low) > 2 and low.endswith("y") and low[-2] not in "aeiou":
        new = low[:-1] + "ies"
    elif low.endswith(("s", "x", "z", "ch", "sh")):
        new = low + "es"
    elif low in _EN_ES_O:
        new = low + "es"
    else:
        new = low + "s"
    parts[-1] = new
    return " ".join(parts)


def ru_en_multi(word: str) -> tuple[str, str] | None:
    """RU -> EN: несколько вариантов вместо одного."""
    _load_ruedict_sync()
    w = word.lower().strip().strip(".!,;:? ")
    if not w:
        return None
    nw = _normalize_ru(w)
    results = []

    vals = _ru_en.get(w) or _ru_en.get(nw)
    if vals:
        if isinstance(vals, list):
            results.extend(str(v).strip() for v in vals)
        else:
            results.append(str(vals).strip())

    _build_ru_multi()
    results.extend(_ru_multi.get(nw) or _ru_multi.get(w) or [])

    old = _ruen_ru_en.get(nw) or _ruen_ru_en.get(w)
    if old:
        results.append(str(old).strip())

    uniq = [x for x in dict.fromkeys(results) if x]
    if not uniq:
        return None
    if _ru_is_plural(w):
        uniq = list(dict.fromkeys(_en_plural(v) for v in uniq))
    return ", ".join(uniq[:5]), "RuEnDict"


# --- Английская морфология: формы слова -> начальная форма ---
_EN_IRREGULAR = {
    "children": "child", "men": "man", "women": "woman", "feet": "foot",
    "teeth": "tooth", "mice": "mouse", "geese": "goose", "people": "person",
    "oxen": "ox", "lives": "life", "knives": "knife", "wives": "wife",
    "leaves": "leaf", "wolves": "wolf", "halves": "half", "shelves": "shelf",
    "went": "go", "gone": "go", "was": "be", "were": "be", "been": "be",
    "had": "have", "did": "do", "done": "do", "made": "make", "said": "say",
    "took": "take", "taken": "take", "got": "get", "gave": "give",
    "given": "give", "came": "come", "saw": "see", "seen": "see",
    "knew": "know", "known": "know", "better": "good", "best": "good",
    "worse": "bad", "worst": "bad", "further": "far", "farther": "far",
}


def _en_lemmas(w: str) -> list[str]:
    """Кандидаты на начальную форму английского слова."""
    out = []
    irr = _EN_IRREGULAR.get(w)
    if irr:
        out.append(irr)
    if len(w) > 3:
        if w.endswith("ies"):
            out.append(w[:-3] + "y")
        if w.endswith("ves"):
            out.append(w[:-3] + "f")
            out.append(w[:-3] + "fe")
        if w.endswith(("ches", "shes", "sses", "xes", "zes", "ses")):
            out.append(w[:-2])
        if w.endswith("s") and not w.endswith(("ss", "us", "is", "ous")):
            out.append(w[:-1])
        for suf in ("ing", "ed", "er", "est"):
            if w.endswith(suf):
                base = w[:-len(suf)]
                if len(base) > 2 and base[-1] == base[-2]:
                    out.append(base[:-1])
                out.append(base + "e")
                out.append(base)
    seen = set()
    res = []
    for c in out:
        if c and c != w and c not in seen and len(c) > 1:
            seen.add(c)
            res.append(c)
    return res


_EN_PLURAL_IRREG = {"children", "men", "women", "feet", "teeth", "mice",
                    "geese", "oxen", "people", "lives", "knives", "wives",
                    "leaves", "wolves", "halves", "shelves"}

_morph = None


def _get_morph():
    """Ленивая инициализация морфоанализатора: pymorphy3, затем pymorphy2."""
    global _morph
    if _morph is None:
        _morph = False
        try:
            import pymorphy3
            _morph = pymorphy3.MorphAnalyzer()
        except Exception as exc:
            log.warning("pymorphy3 недоступен: %s", exc)
            try:
                import inspect
                if not hasattr(inspect, "getargspec"):
                    inspect.getargspec = inspect.getfullargspec
                import pymorphy2
                _morph = pymorphy2.MorphAnalyzer()
            except Exception as exc2:
                log.warning("pymorphy2 недоступен: %s", exc2)
    return _morph or None


def _ru_head_noun(phrase: str) -> str | None:
    """'старинный город' -> 'город'; 'бороться с нищетой' -> None."""
    m = _get_morph()
    if not m:
        return None
    words = phrase.split()
    if len(words) < 2 or len(words) > 3:
        return None
    last = m.parse(words[-1])[0]
    if last.tag.POS != "NOUN" or last.tag.case not in ("nomn", "accs"):
        return None
    for wd in words[:-1]:
        p = m.parse(wd)[0]
        if p.tag.POS not in ("ADJF", "PRTF"):
            return None
        if p.tag.case != last.tag.case or p.tag.number != last.tag.number:
            return None
    return words[-1]


def _ru_plural(word: str) -> str | None:
    """'собака' -> 'собаки', 'злой человек' -> 'злые люди'.

    Обороты согласуем целиком; несчитаемые и глагольные значения не трогаем.
    """
    m = _get_morph()
    if not m:
        return None
    words = word.split()
    if not words or len(words) > 3:
        return None

    # Берём разбор, где слово - существительное/прилагательное в им./вин. падеже
    parses = []
    for wd in words:
        cands = m.parse(wd)
        best = cands[0]
        for p in cands:
            if p.tag.POS in ("NOUN", "ADJF", "PRTF") and p.tag.case in ("nomn", "accs"):
                best = p
                break
        parses.append(best)

    if not any(p.tag.POS == "NOUN" for p in parses):
        if len(words) == 1 and parses[0].tag.POS in ("ADJF", "PRTF"):
            f = parses[0].inflect({"plur", "nomn"})
            return f.word if f else None
        return None

    head = next(p for p in parses if p.tag.POS == "NOUN")
    if head.tag.case not in ("nomn", "accs") or head.tag.number != "sing":
        return None

    for p in parses:
        if p.tag.POS not in ("NOUN", "ADJF", "PRTF"):
            return None
        if "Sgtm" in p.tag or "Pltm" in p.tag or p.normal_form in _RU_MASS:
            return None

    out = []
    for p in parses:
        # зависимое существительное сохраняет свой падеж, остальныеagree с головным
        case = "nomn" if (p is head or p.tag.POS != "NOUN") else (p.tag.case or "nomn")
        f = p.inflect({"plur", case})
        if not f:
            return None
        out.append(f.word)
    return " ".join(out)


_RU_MASS = {"посуда", "мебель", "одежда", "обувь", "листва", "детвора",
            "молодёжь", "бельё", "утварь", "древесина"}


def _mueller_ru(en: str) -> list[str]:
    """Отфильтрованные русские значения статьи Мюллера для английского слова."""
    out = []
    for raw in _ruen_en_ru.get(en, []):
        v = str(raw).strip().lower()
        if not v or re.search(r"[a-z]", v):
            continue
        if any(ch in v for ch in "()[]{}"):
            continue
        if re.search(r"\d+[.)]", v) or re.search(r"[а-яё]\)", v):
            continue
        words = v.split()
        if not words or len(words) > 4:
            continue
        if not ("а" <= v[0] <= "я" or v[0] == "ё"):
            continue
        out.append(" ".join(dict.fromkeys(words)))
    return list(dict.fromkeys(out))


def en_ru_lookup(word: str) -> tuple[str, str] | None:
    """EN -> RU: формы слова, головное существительное, согласование числа."""
    w = word.lower().strip().strip(".!,;:? ")
    if not w:
        return None
    lemma = w
    hit = local_lookup(w, "en-ru")
    plural = False
    if not hit:
        for cand in _en_lemmas(w):
            hit = local_lookup(cand, "en-ru")
            if hit:
                lemma = cand
                plural = w in _EN_PLURAL_IRREG or (
                    len(cand) < len(w) and w.endswith("s")
                    and not w.endswith(("ing", "ed", "er", "est"))
                )
                break
    if not hit:
        return None

    values = [v.strip() for v in hit[0].split(",") if v.strip()]
    source = hit[1]
    if len(values) < 5:
        for extra in _mueller_ru(lemma):
            if extra not in values:
                values.append(extra)
                source = "RuEnDict"

    m = _get_morph()
    has_single_noun = False
    if m:
        for v in values:
            if " " not in v and m.parse(v)[0].tag.POS == "NOUN":
                has_single_noun = True
                break
    if m and not has_single_noun:
        heads = [h for h in (_ru_head_noun(v) for v in values) if h]
        if heads:
            kept = []
            for v in values:
                if " " not in v and m.parse(v)[0].tag.POS == "ADJF":
                    continue
                kept.append(v)
            values = heads + kept

    if plural:
        values = [_ru_plural(v) or v for v in values]

    uniq = [x for x in dict.fromkeys(values) if x][:5]
    if not uniq:
        return None
    return ", ".join(uniq), source
