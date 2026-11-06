"""Хендлеры: выбор темы изучения и интерактивный разговор с ботом.

Режимы диалога:
  • Если задан OPENAI_API_KEY / GROQ_API_KEY — «живой» разговор через бесплатную LLM
    (Groq по умолчанию; можно переключить на Selectel/Cloud.ru/YandexGPT/Ollama).
  • Иначе — локальный rule-based движок: вопросы, реакции и лексика по выбранной теме.

Голос:
  • Пользователь может присылать голосовые сообщения — они распознаются (Whisper API
    или локальный faster-whisper) и обрабатываются как обычный текст.
  • Кнопка 🎙 Voice reply включает/выключает озвучку ответов бота (Yandex SpeechKit /
    OpenAI-совместимый TTS / Piper), если TTS настроен.

Состояние диалога хранится в FSMContext aiogram (storage по умолчанию — в памяти).
"""
from __future__ import annotations

import asyncio
import logging
import re

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import BufferedInputFile, CallbackQuery, Message

from chat_engine import _llm_reply, llm_available, local_engine
from config import VOICE_REPLY_ENABLED
from data.topics import TOPICS, TOPIC_BY_ID
from db import Database
from keyboards import chat_menu_kb, main_menu_kb, topics_kb
from plans import LIMITS, UPGRADE_HINTS
from speech import stt_available, synthesize, transcribe, tts_available

logger = logging.getLogger(__name__)

router = Router()


class ChatStates(StatesGroup):
    in_chat = State()          # пользователь в режиме разговора
    waiting_help = State()     # задал вопрос «как сказать…?»


def _strip_html(text: str) -> str:
    """Убрать HTML-теги из ответа перед озвучкой."""
    return re.sub(r"<[^>]+>", "", text)


async def _send_voice(bot, chat_id: int, text: str) -> bool:
    """Озвучить ответ бота голосовым сообщением. True, если успешно."""
    if not tts_available():
        return False
    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(None, synthesize, _strip_html(text))
    if not result:
        return False
    audio, fmt = result
    filename = f"reply.{fmt}"
    try:
        if fmt == "mp3":
            await bot.send_audio(chat_id, BufferedInputFile(audio, filename=filename))
        else:
            await bot.send_voice(chat_id, BufferedInputFile(audio, filename=filename))
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("Sending voice failed: %s", exc)
        return False


async def _maybe_voice_reply(message: Message, state: FSMContext, reply_text: str,
                             db: Database | None = None) -> None:
    """Отправить голосовую дублировку, если пользователь включил режим озвучки.

    Озвучка доступна только на Plus/Premium; на Plus — с дневным лимитом.
    """
    data = await state.get_data()
    voice_on = data.get("voice_reply")
    if voice_on is None:
        voice_on = VOICE_REPLY_ENABLED == "on"
    if not (voice_on and message.chat.type == "private"):
        return
    if db is not None:
        user_id = message.from_user.id
        tier, _ = await db.get_plan(user_id)
        if tier == "free":
            return
        if tier == "plus" and not await db.within_limit(user_id, "tts", LIMITS.plus_voice_replies_per_day):
            await message.answer(
                f"🔊 Дневной лимит озвучки исчерпан ({LIMITS.plus_voice_replies_per_day}/день). "
                "Без лимита — 👑 Premium: /premium"
            )
            return
        await db.incr_usage(user_id, "tts")
    await _send_voice(message.bot, message.chat.id, reply_text)


# --------------------------- Меню тем ---------------------------

def _topics_overview_text() -> str:
    lines = ["📚 <b>Topics to study</b> — выбери тему, и мы:",
             "• разберём идеи, что можно обсуждать по теме;",
             "• выучим полезные фразы;",
             "• потренируем живой диалог на английском.\n"]
    for t in TOPICS:
        lines.append(f"{t['emoji']} <b>{t['title']}</b> — {t['description']}")
    lines.append("\nНажми на любую тему 👇 или напиши /chat, чтобы начать разговор.")
    return "\n".join(lines)


@router.message(F.text == "💬 Topics")
@router.message(Command("topics"))
async def show_topics(message: Message, db: Database) -> None:
    open_count = None if await db.is_allowed(message.from_user.id, "topics_all") else LIMITS.open_topics_free
    extra = ""
    if open_count is not None:
        extra = (f"\n🔒 На бесплатном плане открыто {open_count} из {len(TOPICS)} тем. "
                 "Все темы — на 💠 Plus: /premium")
    await message.answer(_topics_overview_text() + extra, parse_mode="HTML", reply_markup=topics_kb(open_count))


@router.callback_query(F.data.startswith("topic:"))
async def choose_topic(call: CallbackQuery, state: FSMContext, db: Database) -> None:
    topic_id = call.data.split(":", 1)[1]

    # платная стена: закрытые темы на бесплатном плане
    if topic_id != "free" and not await db.is_allowed(call.from_user.id, "topics_all"):
        index = next((i for i, t in enumerate(TOPICS) if t["id"] == topic_id), None)
        if index is not None and index >= LIMITS.open_topics_free:
            t = TOPICS[index]
            await call.message.answer(
                f"🔒 Тема «{t['emoji']} {t['title']}» входит в расширенный набор.\n\n"
                + UPGRADE_HINTS["topics"],
                reply_markup=topics_kb(LIMITS.open_topics_free),
            )
            await call.answer()
            return

    tier, _ = await db.get_plan(call.from_user.id)
    await state.update_data(chat_topic=topic_id, chat_turn=0, chat_history=[], chat_tier=tier)
    await state.set_state(ChatStates.in_chat)

    mode_lines = [f"Режим диалога: {'LLM 🤖' if llm_available() else 'practice questions 📝'}"]
    if stt_available():
        if tier == "free":
            mode_lines.append("🎙 Голосовые сообщения — на планах 💠 Plus / 👑 Premium (/premium)")
        else:
            mode_lines.append("🎙 Голос: можешь присылать мне голосовые сообщения")
    if tts_available():
        mode_lines.append("🔊 Озвучка ответов доступна (кнопка Voice reply)")
    voice_hint = "\nПросто пришли голосовое сообщение — я распознаю речь. 🎙" if (stt_available() and tier != "free") else ""
    if topic_id == "free":
        intro = (
            "🆓 <b>Free conversation</b> mode!\n\n"
            "Просто пиши мне на английском о чём угодно — я поддержу разговор, "
            "буду задавать вопросы и мягко исправлять ошибки." + voice_hint + "\n\n"
            + "\n".join(f"<i>{line}</i>" for line in mode_lines)
        )
    else:
        t = TOPIC_BY_ID[topic_id]
        ideas = "\n".join(f"  {i + 1}. {idea}" for i, idea in enumerate(t["ideas"]))
        phrases = "\n".join(f"  • <b>{en}</b> — <i>{ru}</i>" for en, ru in t["phrases"])
        intro = (
            f"{t['emoji']} <b>{t['title']}</b>\n{t['description']}\n\n"
            f"💡 <b>Ideas to discuss:</b>\n{ideas}\n\n"
            f"🎓 <b>Useful phrases:</b>\n{phrases}\n\n"
            "Let's start! Write me anything in English — I'll ask you questions. "
            "Напиши любое сообщение по-английски 👇" + voice_hint + "\n\n"
            + "\n".join(f"<i>{line}</i>" for line in mode_lines)
        )
    voice_on = (await state.get_data()).get("voice_reply", VOICE_REPLY_ENABLED == "on")
    await call.message.answer(
        intro, parse_mode="HTML",
        reply_markup=chat_menu_kb(voice_on=voice_on if tts_available() else None),
    )
    await call.answer()


# --------------------------- Вход в чат ---------------------------

@router.message(F.text == "🗣 Chat with me")
@router.message(Command("chat"))
async def start_chat(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    voice_on = data.get("voice_reply", VOICE_REPLY_ENABLED == "on")
    kb = chat_menu_kb(voice_on=voice_on if tts_available() else None)
    if data.get("chat_topic"):
        await state.set_state(ChatStates.in_chat)
        extra = "\nМожешь писать текстом или присылать голосовые 🎙" if stt_available() else ""
        await message.answer(
            f"🗣 Let's continue our conversation! Write in English 👇{extra}",
            reply_markup=kb,
        )
    else:
        await message.answer(
            "Сначала выбери тему для разговора 👇", reply_markup=topics_kb()
        )


@router.message(ChatStates.in_chat, F.text == "💬 Change topic")
async def change_topic(message: Message, state: FSMContext, db: Database) -> None:
    await state.clear()
    open_count = None if await db.is_allowed(message.from_user.id, "topics_all") else LIMITS.open_topics_free
    await message.answer("Выбери новую тему:", reply_markup=topics_kb(open_count))


@router.message(F.text == "🏠 Main menu")
@router.message(Command("menu"))
async def back_to_menu(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Главное меню 👇", reply_markup=main_menu_kb())


# --------------------------- Помощь с переводом ---------------------------

HELP_PROMPTS = [
    "Как сказать по-английски? Напиши фразу по-русски (например: «Мне нужно поторговаться»)",
]


@router.message(ChatStates.in_chat, F.text == "🙋 Ask for help")
async def ask_help(message: Message, state: FSMContext) -> None:
    await state.set_state(ChatStates.waiting_help)
    await message.answer(
        "🙋 Напиши по-русски, что ты хочешь сказать, а я подскажу фразу на английском "
        f"(по теме, которую ты выбрал).\n\n{HELP_PROMPTS[0]}"
    )


@router.message(ChatStates.waiting_help, F.text)
async def answer_help(message: Message, state: FSMContext) -> None:
    await state.set_state(ChatStates.in_chat)
    request = message.text.strip()
    topic_id = (await state.get_data()).get("chat_topic")
    topic = TOPIC_BY_ID.get(topic_id or "")

    suggestion = None
    if llm_available():
        try:
            history = [
                {"role": "user", "content":
                    f"The learner wants to say this in English (topic: "
                    f"{topic['title'] if topic else 'general'}): «{request}». "
                    "Give ONLY the natural English sentence plus a short Russian translation."}
            ]
            loop = asyncio.get_running_loop()
            suggestion = await loop.run_in_executor(None, _llm_reply, history, topic_id, "intermediate")
        except Exception as exc:  # noqa: BLE001
            logger.warning("LLM help failed: %s", exc)

    if not suggestion:
        # офлайн-подсказка: подбираем близкую полезную фразу из темы
        if topic:
            en, ru = topic["phrases"][hash(request) % len(topic["phrases"])]
            suggestion = (
                f"Попробуй так: <b>{en}</b>\n<i>({ru})</i>\n\n"
                "Это полезная фраза из твоей темы — подставь свои слова!"
            )
        else:
            suggestion = (
                "Подсказка: строй фразу по схеме <b>I'd like to …</b> / "
                "<b>Could I … ?</b> — это звучит вежливо и естественно."
            )
    await message.answer(suggestion, parse_mode="HTML")


# --------------------------- Основной цикл диалога ---------------------------

async def _get_user_text(message: Message, state: FSMContext, db: Database) -> str | None:
    """Достать текст из текстового или голосового сообщения (через STT).

    Голосовые сообщения доступны только на планах Plus/Premium; на Plus — с дневным лимитом.
    """
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


@router.message(ChatStates.in_chat, F.voice)
async def chat_voice(message: Message, state: FSMContext, db: Database) -> None:
    await _handle_chat_input(message, state, db, is_voice=True)


@router.message(ChatStates.in_chat, F.text)
async def chat_message(message: Message, state: FSMContext, db: Database) -> None:
    await _handle_chat_input(message, state, db, is_voice=False)


async def _handle_chat_input(message: Message, state: FSMContext, db: Database,
                             is_voice: bool) -> None:
    data = await state.get_data()
    topic_id = data.get("chat_topic")
    turn = int(data.get("chat_turn", 0))
    history: list[dict] = list(data.get("chat_history", []))
    level = await db.get_level(message.from_user.id)
    tier, _ = await db.get_plan(message.from_user.id)

    # лимит сообщений разговорного чата на бесплатном плане
    if tier == "free" and not await db.within_limit(message.from_user.id, "chat", LIMITS.free_chat_messages_per_day):
        used = await db.get_usage(message.from_user.id, "chat")
        await message.answer(
            f"💬 Лимит разговора на сегодня исчерпан ({used}/{LIMITS.free_chat_messages_per_day} сообщений).\n\n"
            + UPGRADE_HINTS["chat"].format(limit=LIMITS.free_chat_messages_per_day),
            reply_markup=main_menu_kb(),
        )
        return

    user_text = await _get_user_text(message, state, db)
    if not user_text:
        return
    await db.incr_usage(message.from_user.id, "chat")

    voice_on = data.get("voice_reply", VOICE_REPLY_ENABLED == "on")
    kb = chat_menu_kb(voice_on=voice_on if tts_available() else None)

    async with message.chat.typing():
        reply: str | None = None
        if llm_available():
            history.append({"role": "user", "content": user_text})
            try:
                loop = asyncio.get_running_loop()
                reply = await loop.run_in_executor(None, _llm_reply, history, topic_id, level)
                history.append({"role": "assistant", "content": reply})
            except Exception as exc:  # noqa: BLE001
                logger.warning("LLM chat failed, falling back to local engine: %s", exc)
                reply = None

        if reply is None:
            reply, turn = local_engine.reply(user_text, topic_id, turn)

        if is_voice:
            reply = f"🎙 <i>I heard you say:</i> “{_strip_html(user_text)}”\n\n{reply}"

        # история не должна расти бесконечно
        history = history[-20:]
        await state.update_data(chat_turn=turn, chat_history=history)
        await message.answer(reply, parse_mode="HTML", reply_markup=kb)
        await _maybe_voice_reply(message, state, reply, db=db)


# --------------------------- Переключатель озвучки ---------------------------

@router.message(ChatStates.in_chat, F.text.in_({"🎙 Voice reply: on", "🔇 Voice reply: off"}))
async def toggle_voice_reply(message: Message, state: FSMContext, db: Database) -> None:
    data = await state.get_data()
    current = data.get("voice_reply", VOICE_REPLY_ENABLED == "on")
    new_state = not current
    if new_state and not await db.is_allowed(message.from_user.id, "voice"):
        await message.answer(UPGRADE_HINTS["voice"])
        new_state = False
    await state.update_data(voice_reply=new_state)
    if new_state and not tts_available():
        await message.answer(
            "Озвучка пока недоступна: настройте TTS (Yandex SpeechKit / "
            "OpenAI-совместимый /audio/speech / Piper). Режим выключен."
        )
        new_state = False
        await state.update_data(voice_reply=False)
    hint = (
        "🎙 Теперь я буду дублировать ответы голосом."
        if new_state else "🔇 Озвучка выключена, отвечаю только текстом."
    )
    await message.answer(hint, reply_markup=chat_menu_kb(voice_on=new_state))


@router.callback_query(F.data == "cmd:topics")
async def topics_from_inline(call: CallbackQuery) -> None:
    await call.message.answer(_topics_overview_text(), parse_mode="HTML", reply_markup=topics_kb())
    await call.answer()
