"""Интерактивный чат на английском: выбор темы + офлайн-движок."""
import asyncio
import html
import io
import logging
import os
import re
import time

from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery, BufferedInputFile
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from db import Database
from data.topics import TOPICS, TOPIC_BY_ID, topic_idea
from chat_engine import local_engine, llm_available, chat_reply
from keyboards import chat_menu_kb, main_menu_kb, topics_kb, back_topics_kb
from plans import LIMITS, UPGRADE_HINTS

logger = logging.getLogger(__name__)
router = Router()

EXIT_LABELS = {"🏠 Main menu", "❌ Отмена"}


class ChatStates(StatesGroup):
    in_chat = State()


async def _open_count(db: Database, user_id: int) -> int | None:
    """Сколько тем открыто пользователю; None = все."""
    tier, _ = await db.get_plan(user_id)
    return LIMITS.open_topics_free if tier == "free" else None


def _topic_allowed(topic_id: str, open_count: int | None) -> bool:
    if topic_id == "free":
        return True
    ids = [t["id"] for t in TOPICS]
    if topic_id not in ids:
        return False
    return open_count is None or ids.index(topic_id) < open_count


async def _show_topics(message: Message, db: Database, user_id: int) -> None:
    oc = await _open_count(db, user_id)
    text = "💬 <b>Выбери тему для разговора</b>\n\n"
    if oc is not None:
        text += f"На бесплатном плане открыто {oc} из {len(TOPICS)} тем.\n"
    text += "Можно и без темы — «🆓 Free conversation»."
    await message.answer(text, parse_mode="HTML", reply_markup=topics_kb(oc))


async def _chat_quota(message: Message, db: Database, state: FSMContext) -> bool:
    """Дневной лимит реплик для free. False — лимит исчерпан."""
    uid = message.from_user.id
    tier, _ = await db.get_plan(uid)
    if tier != "free":
        return True
    if await db.within_limit(uid, "chat", LIMITS.free_chat_messages_per_day):
        return True
    used = await db.get_usage(uid, "chat")
    await message.answer(
        f"📭 Лимит сообщений чата на сегодня исчерпан ({used}/{LIMITS.free_chat_messages_per_day}).\n\n"
        + UPGRADE_HINTS["chat"].format(limit=LIMITS.free_chat_messages_per_day),
        reply_markup=main_menu_kb(),
    )
    await state.clear()
    return False


def _fmt(text: str) -> str:
    """Ответ LLM: экранировать HTML и превратить Markdown-акценты в теги."""
    t = html.escape(text)
    t = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", t, flags=re.S)
    t = re.sub(r"\*(.+?)\*", r"<i>\1</i>", t, flags=re.S)
    return t


def _plain(text: str) -> str:
    """Текст для озвучки: без HTML-тегов и Markdown-акцентов."""
    t = re.sub(r"<[^>]+>", "", text)
    t = html.unescape(t)
    return t.replace("*", "").replace("`", "").strip()


async def _chat_kb(state: FSMContext):
    """Клавиатура чата: кнопка озвучки только в режиме toggle."""
    if os.getenv("VOICE_REPLY_ENABLED", "off").lower() != "toggle":
        return chat_menu_kb()
    data = await state.get_data()
    return chat_menu_kb(bool(data.get("voice")))


async def _maybe_voice(message: Message, state: FSMContext, db: Database, text: str) -> None:
    """Озвучить ответ, если режим включён и тариф позволяет."""
    mode = os.getenv("VOICE_REPLY_ENABLED", "off").lower()
    data = await state.get_data()
    if mode == "off" or (mode == "toggle" and not data.get("voice")):
        return
    uid = message.from_user.id
    if not await db.is_allowed(uid, "voice"):
        return
    tier, _ = await db.get_plan(uid)
    if tier == "plus" and not await db.within_limit(uid, "voice_out", LIMITS.plus_voice_replies_per_day):
        return
    import speech
    if not speech.tts_available():
        return
    try:
        res = await asyncio.to_thread(speech.synthesize, text[:500])
    except Exception as exc:
        logger.warning("TTS failed: %s", exc)
        return
    if not res:
        return
    audio, fmt = res
    await db.incr_usage(uid, "voice_out")
    file = BufferedInputFile(audio, filename="reply.ogg" if fmt == "ogg" else "reply.mp3")
    if fmt == "ogg":
        await message.answer_voice(voice=file)
    else:
        await message.answer_audio(audio=file)


async def _respond(message: Message, state: FSMContext, db: Database, user_text: str) -> None:
    """Ответ ученику: LLM, при недоступности — офлайн-движок."""
    data = await state.get_data()
    topic_id = data.get("topic")
    turn = int(data.get("turn") or 0)
    history = list(data.get("history") or [])
    history.append({"role": "user", "content": user_text})
    level = await db.get_level(message.from_user.id)

    answer = await chat_reply(history, topic_id, level)
    if answer:
        history.append({"role": "assistant", "content": answer})
        body = _fmt(answer)
        plain = _plain(answer)
    else:
        offline, turn = local_engine.reply(user_text, topic_id, turn)
        body = offline  # офлайн-движок уже отдаёт HTML
        plain = _plain(offline)

    await state.update_data(turn=turn, history=history[-12:])
    await message.answer(body, parse_mode="HTML", reply_markup=back_topics_kb())
    await _maybe_voice(message, state, db, plain)


async def cmd_chat(message: Message, state: FSMContext, db: Database) -> None:
    """Вход в режим чата."""
    await state.set_state(ChatStates.in_chat)
    await state.update_data(topic=None, turn=0, history=[])
    text = (
        "🗣 <b>Давай попрактикуем английский!</b>\n\n"
        "Пиши мне на английском — я поддержу разговор.\n"
        "Не знаешь, как сказать — напиши по-русски, подскажу.\n\n"
        "Выход — 🏠 Main menu или /cancel"
    )
    if not llm_available():
        text += "\n\n<i>Сейчас я работаю офлайн: задаю вопросы по теме и подсказываю фразы.</i>"
    await message.answer(text, parse_mode="HTML", reply_markup=await _chat_kb(state))
    await _show_topics(message, db, message.from_user.id)


@router.message(Command("chat"))
async def handle_chat_command(message: Message, state: FSMContext, db: Database) -> None:
    await cmd_chat(message, state, db)


@router.message(F.text == "🗣 Chat with me")
async def btn_chat(message: Message, state: FSMContext, db: Database) -> None:
    await state.clear()
    await cmd_chat(message, state, db)


@router.message(F.text == "💬 Topics")
async def btn_topics(message: Message, db: Database) -> None:
    await _show_topics(message, db, message.from_user.id)


@router.callback_query(F.data == "cmd:topics")
async def cb_topics(call: CallbackQuery, db: Database) -> None:
    await call.answer()
    await _show_topics(call.message, db, call.from_user.id)


@router.callback_query(F.data.startswith("topic:"))
async def cb_topic_pick(call: CallbackQuery, db: Database, state: FSMContext) -> None:
    topic_id = call.data.split(":", 1)[1]
    oc = await _open_count(db, call.from_user.id)
    if not _topic_allowed(topic_id, oc):
        await call.answer("🔒 Эта тема откроется на Plus / Premium", show_alert=True)
        return
    topic = TOPIC_BY_ID.get(topic_id)
    tid = topic["id"] if topic else None
    await state.set_state(ChatStates.in_chat)
    await state.update_data(topic=tid, turn=0, history=[])
    await call.answer()
    if topic:
        en, ru = topic["phrases"][0]
        await call.message.answer(
            f"{topic['emoji']} <b>{topic['title']}</b>\n<i>{topic['description']}</i>\n\n"
            f"💡 Idea: <i>{topic_idea(topic, 0)}</i>\n\n"
            f"🎓 Useful phrase:\n<b>{en}</b>\n<i>({ru})</i>",
            parse_mode="HTML", reply_markup=await _chat_kb(state),
        )
    else:
        await call.message.answer(
            "🆓 <b>Free conversation</b>\n\nПиши на английском — я поддержу разговор.",
            parse_mode="HTML", reply_markup=await _chat_kb(state),
        )
    reply, turn = local_engine.reply("hello", tid, 0)
    await state.update_data(turn=turn)
    await call.message.answer(reply, parse_mode="HTML", reply_markup=back_topics_kb())


@router.message(ChatStates.in_chat, F.text == "💬 Change topic")
async def chat_change_topic(message: Message, db: Database) -> None:
    await _show_topics(message, db, message.from_user.id)


@router.message(ChatStates.in_chat, F.text == "🙋 Ask for help")
async def chat_help(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    topic = TOPIC_BY_ID.get(data.get("topic") or "")
    if not topic:
        await message.answer(
            "🙋 Выбери тему через «💬 Change topic» — тогда покажу фразы и идеи.\n"
            "Или напиши по-русски, если не знаешь, как сказать.",
            reply_markup=await _chat_kb(state),
        )
        return
    phrases = "\n".join(f"• <b>{en}</b>\n  <i>{ru}</i>" for en, ru in topic["phrases"])
    ideas = "\n".join(f"• {i}" for i in topic["ideas"])
    await message.answer(
        f"🙋 <b>{topic['emoji']} {topic['title']}</b>\n\n"
        f"🎓 Фразы:\n{phrases}\n\n💡 О чём поговорить:\n{ideas}",
        parse_mode="HTML", reply_markup=await _chat_kb(state),
    )


@router.message(ChatStates.in_chat, F.text.in_({"🎙 Voice reply: on", "🔇 Voice reply: off"}))
async def chat_voice_toggle(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    new = not bool(data.get("voice"))
    await state.update_data(voice=new)
    await message.answer(
        "🎙 Озвучка ответов включена." if new else "🔇 Озвучка ответов выключена.",
        reply_markup=await _chat_kb(state),
    )


@router.message(Command("cancel"), ChatStates.in_chat)
async def chat_cancel(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("✅ Вернулись в главное меню.", reply_markup=main_menu_kb())


@router.message(ChatStates.in_chat, F.text.in_(EXIT_LABELS))
async def exit_chat(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("✅ Вернулись в главное меню.", reply_markup=main_menu_kb())


@router.message(ChatStates.in_chat, F.text & ~F.text.in_(EXIT_LABELS))
async def chat_message(message: Message, state: FSMContext, db: Database) -> None:
    if not await _chat_quota(message, db, state):
        return
    await db.incr_usage(message.from_user.id, "chat")
    await _respond(message, state, db, message.text)


@router.message(ChatStates.in_chat, F.voice)
async def chat_voice(message: Message, state: FSMContext, db: Database, bot: Bot) -> None:
    """Голосовое сообщение в чате: STT -> ответ движка."""
    import speech

    uid = message.from_user.id
    if not await db.is_allowed(uid, "voice"):
        await message.answer(UPGRADE_HINTS["voice"], reply_markup=await _chat_kb(state))
        return
    tier, _ = await db.get_plan(uid)
    if tier == "plus" and not await db.within_limit(uid, "voice_in", LIMITS.plus_voice_inputs_per_day):
        used = await db.get_usage(uid, "voice_in")
        await message.answer(
            f"📭 Лимит голосовых на сегодня исчерпан ({used}/{LIMITS.plus_voice_inputs_per_day}).\n"
            "Без лимита — на 👑 Premium: /premium",
            reply_markup=await _chat_kb(state),
        )
        return
    if not await _chat_quota(message, db, state):
        return
    if not speech.stt_available():
        await message.answer("🎙 Распознавание речи сейчас недоступно.", reply_markup=await _chat_kb(state))
        return
    note = await message.answer("⏳ Распознаю голосовое…")
    t0 = time.monotonic()
    try:
        file = await bot.get_file(message.voice.file_id)
        buf = io.BytesIO()
        await bot.download_file(file.file_path, destination=buf)
        t_dl = time.monotonic() - t0
        text = await asyncio.to_thread(speech.transcribe, buf.getvalue(), "voice.ogg")
        t_stt = time.monotonic() - t0 - t_dl
    except Exception as exc:
        logger.warning("voice failed: %s", exc)
        await note.edit_text("😅 Не удалось обработать голосовое. Попробуйте ещё раз.")
        return
    if not text:
        await note.edit_text("😅 Не разобрал речь. Скажите чуть громче и чётче.")
        return
    await db.incr_usage(uid, "voice_in")
    await db.incr_usage(uid, "chat")
    await note.edit_text(
        f"🎙 <i>Распознано:</i> {html.escape(text)}\n"
        f"<i>⏱ аудио {message.voice.duration} c · загрузка {t_dl:.1f} c · распознавание {t_stt:.1f} c</i>",
        parse_mode="HTML",
    )
    await _respond(message, state, db, text)


@router.message(F.voice)
async def voice_outside_chat(message: Message) -> None:
    await message.answer(
        "🎙 Голосовые работают в режиме разговора — нажмите «🗣 Chat with me».",
        reply_markup=main_menu_kb(),
    )
