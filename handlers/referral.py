"""Приглашения друзей: персональная ссылка и статистика."""
from __future__ import annotations

import os

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message

from db import Database

router = Router()
INVITER_DAYS = int(os.getenv("REFERRAL_INVITER_DAYS", "7"))
INVITEE_DAYS = int(os.getenv("REFERRAL_INVITEE_DAYS", "3"))
MAX_REWARDS = int(os.getenv("REFERRAL_MAX", "10"))

_username: str | None = None


async def _bot_username(message: Message) -> str:
    global _username
    if _username is None:
        me = await message.bot.get_me()
        _username = me.username
    return _username


@router.message(F.text == "👥 Пригласить друга")
@router.message(Command("invite"))
async def invite_screen(message: Message, db: Database) -> None:
    uid = message.from_user.id
    uname = await _bot_username(message)
    link = f"https://t.me/{uname}?start=ref_{uid}"
    st = await db.referral_stats(uid)
    share = (f"https://t.me/share/url?url={link}"
             "&text=Учу%20английский%20с%20ИИ-репетитором%20в%20Telegram.%20Попробуй%20тоже:")
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📤 Отправить другу", url=share)],
    ])
    await message.answer(
        "👥 <b>Пригласить друга</b>\n\n"
        f"Ваша ссылка:\n<code>{link}</code>\n\n"
        f"Друг получает <b>+{INVITEE_DAYS} дня Plus</b> после первого добавленного слова, "
        f"вы — <b>+{INVITER_DAYS} дней Plus</b> за каждого такого друга "
        f"(до {MAX_REWARDS} наград).\n\n"
        f"Приглашено: <b>{st['total']}</b> · дошли до дела: <b>{st['active']}</b> · "
        f"наград получено: <b>{st['rewarded']}</b>",
        parse_mode="HTML", reply_markup=kb,
    )
