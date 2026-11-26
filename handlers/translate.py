"""Хендлер для перевода слов через меню или команду /tr."""
import logging
from aiogram import Router, F
from aiogram.types import Message
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
import dictionary_api
import dictionary
from data.vocabulary import VOCABULARY
from keyboards import main_menu_kb, translate_menu_kb
from db import Database
from plans import LIMITS

logger = logging.getLogger(__name__)
router = Router()


class TranslateState(StatesGroup):
    waiting_for_text = State()


# 1. Обработка нажатия кнопки "🔄 Translate" в меню
@router.message(F.text == "🔄 Translate")
async def cmd_translate_menu(message: Message, state: FSMContext):
    await state.set_state(TranslateState.waiting_for_text)
    await message.answer(
        "🔄 <b>Режим перевода активен</b>\n\n"
        "✍️ Пришлите слово, фразу или целое предложение.\n"
        "Можете переводить несколько слов подряд!\n\n"
        "Для выхода нажмите 🏠 Main menu или /cancel",
        parse_mode="HTML",
        reply_markup=translate_menu_kb()
    )


# 2. Обработка текста ТОЛЬКО когда пользователь находится в режиме перевода
@router.message(TranslateState.waiting_for_text)
async def process_translate_input(message: Message, state: FSMContext, db: Database):
    # Если пользователь нажал кнопку выхода, пропускаем (обработает start.py)
    if "Main menu" in message.text or "Отмена" in message.text:
        return
        
    text = message.text.strip()
    await process_translation(message, text, db)


# 3. Ручная команда /tr (работает из любого состояния)
@router.message(Command("tr"))
async def cmd_translate_manual(message: Message, state: FSMContext, db: Database):
    text = message.text.replace("/tr", "", 1).strip()
    if not text:
        await state.set_state(TranslateState.waiting_for_text)
        await message.answer(
            "🔄 <b>Режим перевода активен</b>\n\n"
            "✍️ Пришлите слово, фразу или целое предложение.\n"
            "Можете переводить несколько слов подряд!\n\n"
            "Для выхода нажмите 🏠 Main menu или /cancel",
            parse_mode="HTML",
            reply_markup=translate_menu_kb()
        )
        return
    
    await state.clear()
    await process_translation(message, text, db)


# 4. Команда /cancel для выхода из режима перевода
@router.message(Command("cancel"), TranslateState.waiting_for_text)
async def cmd_cancel_translate(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "✅ Режим перевода завершён.",
        reply_markup=main_menu_kb()
    )



def _classify_input(text: str) -> str:
    """Возвращает: 'word' | 'short' | 'long'."""
    t = text.strip()
    words = t.split()
    n = len(words)
    length = len(t)
    if n > 15 or length > 150:
        return "long"
    if n == 1 and not any(c in t for c in ".!?;:,"):
        return "word"
    return "short"

async def process_translation(message: Message, text: str, db: Database):
    uid = message.from_user.id
    tier, _ = await db.get_plan(uid)
    if tier != "plus" and not await db.within_limit(uid, "translate", LIMITS.free_translate_per_day):
        used = await db.get_usage(uid, "translate")
        await message.answer(
            f"📭 Лимит переводов на сегодня исчерпан ({used}/{LIMITS.free_translate_per_day}).\n"
            "Без лимита — 💠 Plus: /premium",
            reply_markup=main_menu_kb(),
        )
        return
    await db.incr_usage(uid, "translate")

    import html as _html
    has_cyr = any(ch in "абвгдеёжзийклмнопрстуфхцчшщъыьэюя" for ch in text.lower())
    direction = "ru-en" if has_cyr else "en-ru"

    kind = _classify_input(text)

    if kind == "long":
        await message.answer(
            "📏 Текст довольно длинный.\n\n"
            "Для перевода предложений и текстов лучше перейти в режим разговора:\n"
            "нажми «🗣 Chat with me» — там бот переведёт и поддержит беседу.",
            reply_markup=translate_menu_kb(),
        )
        return

    if kind == "word":
        if direction == "ru-en":
            result_tuple = dictionary.ru_en_multi(text)
        else:
            result_tuple = dictionary.en_ru_lookup(text)

        if result_tuple:
            translation_str, source_str = result_tuple
            translated = translation_str[:1].upper() + translation_str[1:]
            response = f"<b>{_html.escape(text)}</b> → {translated}"
            if source_str == "RuEnDict":
                response += "\n<i>(из словаря Мюллера)</i>"
            response += "\n\n<i>➡️ Введите следующее слово или нажмите 🏠 Main menu</i>"
            await message.answer(response, parse_mode="HTML", reply_markup=translate_menu_kb())
            return

        tr, src, extra = await dictionary.translate(text, direction)
        if src == "none":
            free = await dictionary.translate_text(text, direction)
            if free:
                tr, src = free, "llm"
        if src != "none":
            note = "\n<i>(машинный перевод)</i>" if src == "llm" else ""
            await message.answer(
                f"<b>{_html.escape(text)}</b> → {_html.escape(tr)}{note}\n\n"
                f"<i>➡️ Введите следующее слово или нажмите 🏠 Main menu</i>",
                parse_mode="HTML", reply_markup=translate_menu_kb())
            return

        await message.answer(
            f"❌ Не удалось найти перевод для '{_html.escape(text)}'.\n"
            "Проверьте написание.\n\n"
            "<i>➡️ Попробуйте другое слово или нажмите 🏠 Main menu</i>",
            parse_mode="HTML", reply_markup=translate_menu_kb())
        return

    # short phrase / sentence
    res = await dictionary.translate_text(text, direction)
    if res:
        flag = "🇬🇧" if direction == "ru-en" else "🇷🇺"
        await message.answer(
            f"{flag} {_html.escape(res)}\n\n"
            f"<i>➡️ Пришлите следующий текст или нажмите 🏠 Main menu</i>",
            parse_mode="HTML", reply_markup=translate_menu_kb())
        return

    await message.answer(
        "😅 Перевод сейчас недоступен. Попробуйте через минуту.",
        reply_markup=translate_menu_kb())
