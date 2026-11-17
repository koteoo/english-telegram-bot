"""Логика карточек, теста и статистики в чате (с учётом тарифных планов)."""
import random

from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery

from db import Database
from data.vocabulary import VOCABULARY, QUIZ_SENTENCES
from data.quiz_bank import QUIZ_BY_LEVEL
from keyboards import main_menu_kb, level_select_cb, answer_quiz_cb, levels_kb, LEVEL_NAMES
from plans import LIMITS, PLAN_NAMES, UPGRADE_HINTS

router = Router()

# Текущая серия верных ответов квиза (в памяти; рекорд хранится в БД)
_quiz_streak: dict[int, int] = {}

# Последние показанные вопросы, чтобы не повторяться подряд
_quiz_seen: dict[int, list[str]] = {}

# Активный вопрос пользователя: (вопрос, перевод, A, B, ключ)
_quiz_active: dict[int, tuple] = {}

# Все вопросы: нужны для разбора ответа после перезапуска бота
_ALL_QUIZ = list(QUIZ_SENTENCES) + [q for qs in QUIZ_BY_LEVEL.values() for q in qs]


async def _effective_level(db: Database, user_id: int) -> tuple[str, str]:
    """Уровень для выдачи слов: на бесплатном плане словарь ограничен Beginner."""
    level = await db.get_level(user_id)
    tier, _ = await db.get_plan(user_id)
    if tier == "free" and level != "beginner":
        return "beginner", level
    return level, level


def _word_card(item, hint_only: bool = False) -> str:
    if hint_only:
        return (
            f"🃏 <b>{item.word}</b>\n\n"
            f"Как переводится? Подумай и нажми кнопку 👇"
        )
    return (
        f"🃏 <b>{item.word}</b>\n"
        f"💡 Перевод: <i>{item.translation}</i>\n\n"
        f"📝 Пример: <b>{item.example}</b>"
    )


@router.message(F.text == "📚 Word of the Day")
async def word_of_day(message: Message, db: Database) -> None:
    eff_level, real_level = await _effective_level(db, message.from_user.id)
    # лимит новых слов на бесплатном плане
    if not await db.within_limit(message.from_user.id, "words", LIMITS.free_words_per_day):
        used = await db.get_usage(message.from_user.id, "words")
        await message.answer(
            f"📭 На сегодня лимит исчерпан ({used}/{LIMITS.free_words_per_day} слов).\n\n"
            + UPGRADE_HINTS["words"].format(limit=LIMITS.free_words_per_day),
            reply_markup=main_menu_kb(),
        )
        return
    seen = {w.lower() for w in await db.deck_words(message.from_user.id)}
    item = db.random_word(eff_level, exclude=seen)
    added = await db.add_word_to_deck(
        message.from_user.id, item.word, item.translation, item.example
    )
    await db.incr_usage(message.from_user.id, "words")
    lock_note = ""
    if eff_level != real_level:
        lock_note = "\n🔒 На бесплатном плане доступен только словарь Beginner. Полный словарь — 💠 Plus: /premium"
    text = _word_card(item) + ("\n\n➕ Добавлено в твою колоду для повторения!" if added else "") + lock_note
    await message.answer(text, parse_mode="HTML")


@router.message(F.text == "🃏 Flashcards")
async def flashcards(message: Message, db: Database) -> None:
    level = await db.get_level(message.from_user.id)
    due = await db.due_cards(message.from_user.id, level, limit=10)
    if not due:
        await message.answer(
            "🎉 Повторять пока нечего! Выучи новое слово через «📚 Word of the Day» "
            "или добавь своё через «➕ Add word».",
            reply_markup=main_menu_kb(),
        )
        return
    item = random.choice(due)
    await message.answer(
        _word_card(item, hint_only=True),
        parse_mode="HTML",
        reply_markup=level_select_cb(level),
    )


def _find_word_info(word: str):
    """Найти (перевод, пример) слова во всех уровнях."""
    for lv_words in VOCABULARY.values():
        for w, t, e in lv_words:
            if w.lower() == word.lower():
                return t, e
    return None, None


@router.callback_query(F.data.startswith("rev:"))
async def review_callback(call: CallbackQuery, db: Database) -> None:
    _, level, correct_flag = call.data.split(":")
    correct = correct_flag == "1"
    text = call.message.text or ""
    word = None
    for line in text.splitlines():
        if line.startswith("🃏"):
            word = line.replace("🃏", "").strip()
            break
    if not word:
        await call.answer("Не нашёл карточку 😅", show_alert=True)
        return
    new_box = await db.review_card(call.from_user.id, word, correct)
    translation, example = _find_word_info(word)
    extra = f"\n💡 <i>{translation}</i>\n📝 <b>{example}</b>" if translation else ""
    if correct:
        await call.message.edit_text(
            f"✅ Отлично! Слово «{word}» переходит на уровень повторения {new_box + 1}." + extra,
            parse_mode="HTML",
        )
    else:
        await call.message.edit_text(
            f"❌ Ничего страшного — повторим «{word}» поскорее.{extra}",
            parse_mode="HTML",
        )
    await call.answer()


@router.message(F.text == "✍️ Quiz")
async def quiz_start(message: Message, db: Database) -> None:
    # квиз доступен всем; на бесплатном плане — лимит вопросов в день
    if not await db.within_limit(message.from_user.id, "quiz", LIMITS.free_quizzes_per_day):
        used = await db.get_usage(message.from_user.id, "quiz")
        await message.answer(
            f"📭 Лимит квиза на сегодня исчерпан ({used}/{LIMITS.free_quizzes_per_day} вопросов).\n\n"
            + UPGRADE_HINTS["quiz"].format(limit=LIMITS.free_quizzes_per_day),
            reply_markup=main_menu_kb(),
        )
        return
    level = await db.get_level(message.from_user.id)
    pool_all = list(QUIZ_BY_LEVEL.get(level) or QUIZ_SENTENCES)
    if level == "beginner":
        pool_all += list(QUIZ_SENTENCES)
    hist = _quiz_seen.setdefault(message.from_user.id, [])
    pool = [q for q in pool_all if q[0] not in hist]
    if not pool:
        hist.clear()
        pool = pool_all
    question = random.choice(pool)
    _quiz_active[message.from_user.id] = question
    hist.append(question[0])
    if len(hist) > 5:
        del hist[0]
    sentence, translation, a, b, _answer = question
    body = f"<b>{sentence}</b>"
    if translation:
        body += f"\n<i>({translation})</i>"
    await message.answer(
        f"✍️ <b>Quiz time!</b> Выбери правильный вариант:\n\n"
        f"{body}\n\n"
        f"A) {a}\nB) {b}",
        parse_mode="HTML",
        reply_markup=answer_quiz_cb(level),
    )


@router.callback_query(F.data.startswith("quiz:"))
async def quiz_answer(call: CallbackQuery, db: Database) -> None:
    _, level, choice = call.data.split(":")
    await db.incr_usage(call.from_user.id, "quiz")
    text = call.message.text or ""
    q = _quiz_active.get(call.from_user.id)
    if q and q[0] not in text:
        q = None
    if not q:
        q = next((cand for cand in _ALL_QUIZ if cand[0] in text), None)
    if not q:
        await call.answer("Вопрос не найден 😅", show_alert=True)
        return
    correct = q[4]
    right_word = q[2] if correct == "A" else q[3]
    if choice == correct:
        streak = _quiz_streak.get(call.from_user.id, 0) + 1
        _quiz_streak[call.from_user.id] = streak
        record = await db.update_quiz_result(call.from_user.id, streak)
        await call.message.edit_text(
            f"🎉 Правильно! Ответ: <b>{right_word}</b>.\n"
            f"🔥 Серия: <b>{streak}</b>"
            + ("\n\n🏆 Новый рекорд квиза!" if record else ""),
            parse_mode="HTML",
        )
    else:
        lost = _quiz_streak.pop(call.from_user.id, 0)
        await call.message.edit_text(
            f"😅 Неверно. Правильный ответ: <b>{right_word}</b>.\n"
            + (f"Серия из {lost} прервана.\n" if lost else "")
            + "Нажми «✍️ Quiz», чтобы попробовать ещё раз.",
            parse_mode="HTML",
        )
    await call.answer()


@router.message(F.text == "➕ Add word")
async def add_word_hint(message: Message) -> None:
    await message.answer(
        "Просто отправь мне английское слово (например: <b>journey</b>) — "
        "я добавлю его в твою колоду для повторения.",
        parse_mode="HTML",
        reply_markup=main_menu_kb(),
    )


@router.message(F.text.Regexp(r"^[A-Za-z][A-Za-z '\-]{1,30}$"))
async def add_user_word(message: Message, db: Database, state: FSMContext) -> None:
    # в режиме разговора обычные сообщения обрабатывает chat-хендлер
    if await state.get_state():
        return
    if not await db.within_limit(message.from_user.id, "words", LIMITS.free_words_per_day):
        await message.answer(
            UPGRADE_HINTS["words"].format(limit=LIMITS.free_words_per_day),
            reply_markup=main_menu_kb(),
        )
        return
    word = message.text.strip().lower()
    # ищем слово во всех уровнях словарной базы
    found = None
    for lv in VOCABULARY.values():
        for w, t, e in lv:
            if w.lower() == word:
                found = (w, t, e)
                break
    if found:
        w, t, e = found
        added = await db.add_word_to_deck(message.from_user.id, w)
        await db.incr_usage(message.from_user.id, "words")
        await message.answer(
            f"✅ Слово <b>{w}</b> уже в моей базе!\n💡 <i>{t}</i>\n📝 <b>{e}</b>"
            + ("\nДобавлено в твою колоду!" if added else "\nОно уже в твоей колоде."),
            parse_mode="HTML",
            reply_markup=main_menu_kb(),
        )
    else:
        added = await db.add_word_to_deck(message.from_user.id, word)
        await db.incr_usage(message.from_user.id, "words")
        if added:
            await message.answer(
                f"✅ Добавил «{word}» в твою колоду! Завтра попрошу повторить 😉",
                reply_markup=main_menu_kb(),
            )
        else:
            await message.answer("Это слово уже в твоей колоде 👍")


@router.message(F.text == "📊 Progress")
async def progress(message: Message, db: Database) -> None:
    stats = await db.get_stats(message.from_user.id)
    level = await db.get_level(message.from_user.id)
    tier, expires_at = await db.get_plan(message.from_user.id)
    words_used = await db.get_usage(message.from_user.id, "words")
    quiz_used = await db.get_usage(message.from_user.id, "quiz")
    limits_line = ""
    if tier == "free":
        limits_line = (
            f"\n⏳ Лимиты сегодня: слов {words_used}/{LIMITS.free_words_per_day}, "
            f"квиз {quiz_used}/{LIMITS.free_quizzes_per_day}"
        )
    await message.answer(
        f"📊 <b>Твой прогресс</b>\n\n"
        f"🎫 План: {PLAN_NAMES[tier]}\n"
        f"🎯 Уровень: {LEVEL_NAMES[level]}\n"
        f"🧠 Выучено слов: {stats['learned']}\n"
        f"🃏 В колоде на повторение: {stats['deck_size']}\n"
        f"🏆 Рекорд в квизе: {stats['quiz_best']}/10"
        + limits_line,
        parse_mode="HTML",
        reply_markup=main_menu_kb(),
    )


@router.message(F.text == "🎯 Level")
async def choose_level(message: Message, db: Database) -> None:
    await message.answer("Выбери уровень:", reply_markup=levels_kb())


@router.callback_query(F.data.startswith("lvl:"))
async def set_level(call: CallbackQuery, db: Database) -> None:
    level = call.data.split(":")[1]
    await db.set_level(call.from_user.id, level)
    await call.message.edit_text(f"🎯 Теперь твой уровень: {LEVEL_NAMES[level]}")
    await call.answer()
