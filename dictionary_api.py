"""Надежный модуль перевода с автоопределением языка и реальными примерами."""
import json
import logging
import urllib.request
import urllib.error
import urllib.parse
import re

logger = logging.getLogger(__name__)

def _is_cyrillic(text: str) -> bool:
    """Проверяет, содержит ли текст кириллицу."""
    return bool(re.search('[а-яА-ЯёЁ]', text))

async def fetch_word_details(word: str) -> dict | None:
    """
    Возвращает перевод и (опционально) реальный пример.
    Поддерживает EN->RU и RU->EN.
    """
    word = word.strip()
    if not word or len(word) > 100:
        return None

    is_ru = _is_cyrillic(word)
    langpair = "ru|en" if is_ru else "en|ru"

    try:
        # 1. Основной перевод через MyMemory (параметр de=bot@example.com повышает лимит запросов)
        encoded_query = urllib.parse.quote(word)
        url = f"https://api.mymemory.translated.net/get?q={encoded_query}&langpair={langpair}&de=bot@example.com"
        
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        )
        
        with urllib.request.urlopen(req, timeout=5) as response:
            data = json.loads(response.read().decode())
        
        translation = data.get("responseData", {}).get("translatedText", "").strip()
        
        # Если API вернул то же самое слово или пустоту, считаем, что перевод не найден
        if not translation or translation.lower() == word.lower():
            return None

        # 2. Попытка найти РЕАЛЬНЫЙ пример использования (только для английских слов)
        example = ""
        if not is_ru:
            try:
                dict_url = f"https://api.dictionaryapi.dev/api/v2/entries/en/{urllib.parse.quote(word)}"
                dict_req = urllib.request.Request(
                    dict_url,
                    headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"}
                )
                with urllib.request.urlopen(dict_req, timeout=3) as dict_resp:
                    dict_data = json.loads(dict_resp.read().decode())
                    meaning = dict_data[0]["meanings"][0]
                    example = meaning["definitions"][0].get("example", "")
            except Exception:
                pass # Если пример не найден или API заблокирован, просто игнорируем и продолжаем

        # Формируем чистый ответ
        if is_ru:
            display_word = word
            display_trans = translation.capitalize()
            flag_base = "🇷🇺"
            flag_target = "🇬🇧"
        else:
            display_word = word.capitalize()
            display_trans = translation.capitalize()
            flag_base = "🇬🇧"
            flag_target = "🇷🇺"

        result = {
            "word": display_word,
            "translation": f"{flag_base} **{display_word}**\n\n{flag_target} {display_trans}",
            "example": example.capitalize() if example else ""
        }
        return result

    except urllib.error.HTTPError as e:
        logger.warning(f"API Error fetching '{word}': {e.code}")
        return None
    except Exception as e:
        logger.warning(f"Failed to fetch data for '{word}': {e}")
        return None
