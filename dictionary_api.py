"""Модуль для получения данных о словах из внешних API (только надёжные источники)."""
import json
import logging
import urllib.request
import urllib.error
import urllib.parse

logger = logging.getLogger(__name__)

async def fetch_word_details(word: str) -> dict | None:
    """
    Возвращает словарь с ключами: word, translation, example.
    Использует только MyMemory API (надёжный, без блокировок).
    """
    word = word.strip().lower()
    if not word or len(word) > 100:
        return None

    try:
        # Получаем перевод через MyMemory API (работает стабильно)
        encoded_query = urllib.parse.quote(word)
        trans_url = f"https://api.mymemory.translated.net/get?q={encoded_query}&langpair=en|ru"
        
        req = urllib.request.Request(
            trans_url,
            headers={
                "User-Agent": "EnglishBot/1.0 (Telegram Bot)",
                "Accept": "application/json"
            }
        )
        
        with urllib.request.urlopen(req, timeout=5) as response:
            trans_data = json.loads(response.read().decode())
        
        translation = trans_data.get("responseData", {}).get("translatedText", "")
        
        if not translation or translation.lower() == word.lower():
            logger.warning(f"No translation found for '{word}'")
            return None
        
        # Генерируем простой пример использования
        example = f"I'm learning the word '{word}' in English."
        
        return {
            "word": word,
            "translation": translation.capitalize(),
            "example": example
        }
    except urllib.error.HTTPError as e:
        logger.warning(f"API Error fetching '{word}': {e.code}")
        return None
    except Exception as e:
        logger.warning(f"Failed to fetch dictionary data for '{word}': {e}")
        return None
