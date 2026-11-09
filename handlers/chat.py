"""Хендлеры для разговорного диалога с ботом."""
import asyncio
import logging
import re
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from db import Database
from chat_engine import _llm_reply, llm_available, local_engine
from data.topics import TOPICS, TOPIC_BY_ID, topic_idea
from keyboards import main_menu_kb, topics_kb, chat_menu_kb, back_topics_kb
from config import VOICE_REPLY_ENABLED, LIMITS, UPGRADE_HINTS
from speech import stt_available, tts_available, transcribe

logger = logging.getLogger(__name__)
router = Router()


class ChatStates(StatesGroup):
    in_chat = State()
    waiting_for_topic = State()


def _strip_html(text: str) -> str:
    return re.sub(r'<[^>]+>', '', text)


# --- Вспомогательные функции ---

async def _get_user_text(message: Message, state: FSMContext, db: Database) -> str | None:
    """Достать текст из текстового или голосового сообщения (через STT)."""
    if message.text:
        return message.text.strip()
    
    if message.voice:
        user_id = message.from_user.id
        tier, _ = await db.get_plan(user_id)
        
        if tier == "free":
            await message.answer(UPGRADE_HINTS["voice"])
            return None
        
        if tier == "plus" and not await db.within_limit(user_id, "stt", LIMITS.plus_voice_inputs_per_day):
            used = await db.get_usage(user_id, "stt")
            await message.answer(
                f"🎙 Лимит голосовых сообщений на сегодня исчерпан "
                f"({used}/{LIMITS.plus_voice_inputs_per_day}). Без лимита — 👑 Premium: /premium"
            )
            return None
        
        if not stt_available():
            await message.answer(
                "🎙 Я пока не умею распознавать голос. Настройте Whisper "
                "(SPEECH_API_KEY/SPEECH_BASE_URL или локальный faster-whisper) — "
                "и можете говорить со мной голосом!"
            )
            return None
        
        tg_file = await message.bot.get_file(message.voice.file_id)
        audio = bytes(await message.bot.download_file(tg_file.file_path))
        loop = asyncio.get_running_loop()
        text = await loop.run_in_executor(None, transcribe, audio, "voice.ogg")
        
        if not text:
            await message.answer("Hmm, I couldn't understand the audio 😅 Try again, please.")
            return None
        
        await db.incr_usage(user_id, "stt")
        await state.update_data(last_transcription=text)
        return text
    
    return None


# --- Хендлеры диалога ---

@router.message(Command("chat"))
async def cmd_chat(message: Message, state: FSMContext):
    await state.set_state(ChatStates.in_chat)
    await message.answer(
        "🗣 <b>Давай попрактикуем английский!</b>\n\n"
        "Просто пиши мне на английском, и я буду поддерживать разговор.\n"
        "Если не знаешь, как сказать что-то — напиши по-русски, я подскажу.\n\n"
        "Чтобы выйти, нажми кнопку <b>🏠 Main menu</b>.",
        parse_mode="HTML"
    )


@router.message(F.text == "🗣 Chat with me")
async def btn_chat(message: Message, state: FSMContext):
    await cmd_chat(message, state)


@router.message(ChatStates.in_chat, F.voice)
async def chat_voice(message: Message, state: FSMContext, db: Database):
    await _handle_chat_input(message, state, db, is_voice=True)


@router.message(ChatStates.in_chat, F.text & ~F.text.in_({"🏠 Main menu", "❌ Отмена", "💬 Change topic", "🙋 Ask for help"}))
async def chat_message(message: Message, state: FSMContext, db: Database):
    await _handle_chat_input(message, state, db, is_voice=False)


async def _handle_chat_input(message: Message, state: FSMContext, db: Database, is_voice: bool) -> None:
    logger.info(f"📩 Chat input received: '{message.text[:50]}...' (is_voice={is_voice})")
    data = await state.get_data()
    topic_id = data.get("chat_topic")
    turn = int(data.get("chat_turn", 0))
    history: list[dict] = list(data.get("chat_history", []))
    level = await db.get_level(message.from_user.id)
    tier, _ = await db.get_plan(message.from_user.id)
    
    if tier == "free" and not await db.within_limit(message.from_user.id, "chat", LIMITS.free_chat_messages_per_day):
        used = await db.get_usage(message.from_user.id, "chat")
        await message.answer(
            f"💬 Лимит разговора на сегодня исчерпан ({used}/{LIMITS.free_chat_messages_per_day} сообщений).\n\n"
            + UPGRADE_HINTS["chat"].format(limit=LIMITS.free_chat_messages_per_day),
        )
        return

    user_text = await _get_user_text(message, state, db)
    if not user_text:
        return
        
    await db.incr_usage(message.from_user.id, "chat")

    voice_on = data.get("voice_reply", VOICE_REPLY_ENABLED == "on")
    kb = chat_menu_kb(voice_on=voice_on if tts_available() else None)

    await message.bot.send_chat_action(chat_id=message.chat.id, action="typing")
    
    reply: str | None = None
    if llm_available():
        history.append({"role": "user", "content": user_text})
        try:
            loop = asyncio.get_running_loop()
            reply = await loop.run_in_executor(None, _llm_reply, history, topic_id, level)
            history.append({"role": "assistant", "content": reply})
        except Exception as exc:
            logger.warning("LLM chat failed, falling back to local engine: %s", exc)
            reply = None

    if reply is None:
        reply, turn = local_engine.reply(user_text, topic_id, turn)

    if is_voice:
        reply = f"🎙 <i>I heard you say:</i> \"{_strip_html(user_text)}\"\n\n{reply}"

    history = history[-20:]
    await state.update_data(chat_turn=turn, chat_history=history)
    logger.info(f"📤 Sending reply: {reply[:50]}...")
    await message.answer(reply, parse_mode="HTML", reply_markup=kb)
    await _maybe_voice_reply(message, state, reply, db=db)


async def _maybe_voice_reply(message: Message, state: FSMContext, text: str, db: Database):
    data = await state.get_data()
    voice_on = data.get("voice_reply", VOICE_REPLY_ENABLED == "on")
    
    if not voice_on or not tts_available():
        return
    
    tier, _ = await db.get_plan(message.from_user.id)
    if tier == "free":
        return
    
    if tier == "plus" and not await db.within_limit(message.from_user.id, "tts", LIMITS.plus_tts_per_day):
        return


# --- Темы для разговора ---

@router.message(Command("topics"))
async def cmd_topics(message: Message, state: FSMContext):
    await state.set_state(ChatStates.waiting_for_topic)
    await message.answer(
        "📚 <b>Выбери тему для разговора:</b>",
        parse_mode="HTML"
    )


@router.message(F.text == "💬 Topics")
async def btn_topics(message: Message, state: FSMContext):
    await cmd_topics(message, state)


@router.callback_query(F.data.startswith("topic:"))
async def cb_select_topic(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    topic_id = callback.data.split(":")[1]
    
    if topic_id == "free":
        await state.set_state(ChatStates.in_chat)
        await state.update_data(chat_topic=None, chat_turn=0, chat_history=[])
        await callback.message.edit_text(
            "🗣 <b>Free conversation mode</b>\n\n"
            "Просто пиши мне на английском о чём угодно!",
            parse_mode="HTML"
        )
        return
    
    topic = TOPIC_BY_ID.get(topic_id)
    if not topic:
        await callback.message.edit_text("❌ Тема не найдена.")
        return
    
    await state.set_state(ChatStates.in_chat)
    await state.update_data(chat_topic=topic_id, chat_turn=0, chat_history=[])
    
    idea = topic_idea(topic, 0)
    first_question = topic["questions"][0]
    
    text = (
        f"📚 <b>Тема: {topic['emoji']} {topic['title']}</b>\n\n"
        f"💡 <i>{idea}</i>\n\n"
        f"❓ {first_question}"
    )
    
    await callback.message.edit_text(text, parse_mode="HTML")


@router.message(ChatStates.in_chat, F.text == "💬 Change topic")
async def btn_change_topic(message: Message, state: FSMContext):
    await cmd_topics(message, state)


@router.message(ChatStates.in_chat, F.text == "🙋 Ask for help")
async def btn_ask_help(message: Message, state: FSMContext):
    await message.answer(
        "🙋 <b>Нужна помощь?</b>\n\n"
        "Напиши по-русски, что хочешь сказать, и я подскажу, как это сказать по-английски!",
        parse_mode="HTML"
    )


# --- Глобальный обработчик кнопки возврата в меню (в самом конце!) ---

@router.message(F.text.in_({"🏠 Main menu", "❌ Отмена"}))
async def cmd_global_menu(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("🏠 Главное меню:")

# Глобальный обработчик кнопки возврата в меню (работает из любого состояния)
@router.message(F.text == "🏠 Main menu")
@router.message(F.text == "❌ Отмена")
async def cmd_global_menu(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("🏠 Главное меню:")

# Глобальный обработчик выхода в меню (используем contains для надежности)
@router.message(F.text.contains("Main menu") | F.text.contains("Отмена"))
async def cmd_global_menu(message: Message, state: FSMContext):
    await state.clear()
    kb = main_menu_kb()
    await message.answer("🏠 Главное меню:", reply_markup=kb)
