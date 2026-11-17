"""Интерактивный чат на английском: выбор темы + офлайн-движок."""
import logging

from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from db import Database
from data.topics import TOPICS, TOPIC_BY_ID, topic_idea
from chat_engine import local_engine, llm_available
from keyboards import chat_menu_kb, main_menu_kb, topics_kb, back_topics_kb
from plans import LIMITS

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


async def cmd_chat(message: Message, state: FSMContext, db: Database) -> None:
    """Вход в режим чата."""
    await state.set_state(ChatStates.in_chat)
    await state.update_data(topic=None, turn=0)
    text = (
        "🗣 <b>Давай попрактикуем английский!</b>\n\n"
        "Пиши мне на английском — я поддержу разговор.\n"
        "Не знаешь, как сказать — напиши по-русски, подскажу.\n\n"
        "Выход — 🏠 Main menu или /cancel"
    )
    if not llm_available():
        text += "\n\n<i>Сейчас я работаю офлайн: задаю вопросы по теме и подсказываю фразы.</i>"
    await message.answer(text, parse_mode="HTML", reply_markup=chat_menu_kb())
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
    await state.update_data(topic=tid, turn=0)
    await call.answer()
    if topic:
        en, ru = topic["phrases"][0]
        await call.message.answer(
            f"{topic['emoji']} <b>{topic['title']}</b>\n<i>{topic['description']}</i>\n\n"
            f"💡 Idea: <i>{topic_idea(topic, 0)}</i>\n\n"
            f"🎓 Useful phrase:\n<b>{en}</b>\n<i>({ru})</i>",
            parse_mode="HTML", reply_markup=chat_menu_kb(),
        )
    else:
        await call.message.answer(
            "🆓 <b>Free conversation</b>\n\nПиши на английском — я поддержу разговор.",
            parse_mode="HTML", reply_markup=chat_menu_kb(),
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
            reply_markup=chat_menu_kb(),
        )
        return
    phrases = "\n".join(f"• <b>{en}</b>\n  <i>{ru}</i>" for en, ru in topic["phrases"])
    ideas = "\n".join(f"• {i}" for i in topic["ideas"])
    await message.answer(
        f"🙋 <b>{topic['emoji']} {topic['title']}</b>\n\n"
        f"🎓 Фразы:\n{phrases}\n\n💡 О чём поговорить:\n{ideas}",
        parse_mode="HTML", reply_markup=chat_menu_kb(),
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
async def chat_message(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    topic_id = data.get("topic")
    turn = int(data.get("turn") or 0)
    reply, new_turn = local_engine.reply(message.text, topic_id, turn)
    await state.update_data(turn=new_turn)
    await message.answer(reply, parse_mode="HTML", reply_markup=back_topics_kb())
