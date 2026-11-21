"""Логика карточек, теста и статистики в чате (с учётом тарифных планов)."""
import random

from aiogram import Router, F
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from db import Database
from data.vocabulary import VOCABULARY, QUIZ_SENTENCES
from data.quiz_bank import QUIZ_BY_LEVEL
from keyboards import main_menu_kb, review_cb, answer_quiz_cb, levels_kb, LEVEL_NAMES, quiz_menu_kb, flashcards_menu_kb, add_word_kb, notify_kb, placement_kb, goals_kb, notify_tz_kb, level_sub_kb
from plans import LIMITS, PLAN_NAMES, UPGRADE_HINTS

router = Router()


class QuizState(StatesGroup):
    in_quiz = State()


class FlashcardsState(StatesGroup):
    add_word = State()
    in_review = State()

# Текущая серия верных ответов квиза (в памяти; рекорд хранится в БД)
_quiz_streak: dict[int, int] = {}

# Последние показанные вопросы, чтобы не повторяться подряд
_quiz_seen: dict[int, list[str]] = {}

# Активный вопрос пользователя: (вопрос, перевод, A, B, ключ)
_quiz_active: dict[int, tuple] = {}

# Все вопросы: нужны для разбора ответа после перезапуска бота
_ALL_QUIZ = list(QUIZ_SENTENCES) + [q for qs in QUIZ_BY_LEVEL.values() for q in qs]

# Показанная карточка: (слово, перевод, пример) и последнее слово для антиповтора
_card_active: dict[int, tuple] = {}
_card_last: dict[int, str] = {}


async def _effective_level(db: Database, user_id: int) -> tuple[str, str]:
    """Словари всех уровней открыты всем тарифам; ограничение — по числу слов в день."""
    level = await db.get_level(user_id)
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
    text = _word_card(item) + ("\n\n➕ Добавлено в твою колоду для повторения!" if added else "") + lock_note
    await message.answer(text, parse_mode="HTML")


async def _send_card(message: Message, db: Database, user_id: int) -> bool:
    """Показать следующую карточку. False — повторять нечего."""
    level = await db.get_level(user_id)
    due = await db.due_cards(user_id, level, limit=10)
    if not due:
        await message.answer(
            "🎉 Повторять пока нечего.",
            reply_markup=main_menu_kb(),
        )
        return False
    last = _card_last.get(user_id)
    pool = [c for c in due if c.word != last] or due
    item = random.choice(pool)
    _card_last[user_id] = item.word
    _card_active[user_id] = (item.word, item.translation, item.example)
    await message.answer(
        _word_card(item, hint_only=True),
        parse_mode="HTML",
        reply_markup=review_cb(level),
    )
    return True


@router.message(F.text == "🃏 Flashcards")
async def flashcards(message: Message, db: Database, state: FSMContext) -> None:
    uid = message.from_user.id
    level = await db.get_level(uid)
    if not await db.due_cards(uid, level, limit=1):
        await state.clear()
        await message.answer(
            "🃏 <b>Режим карточек</b>\n\n🎉 Повторять пока нечего.",
            parse_mode="HTML",
            reply_markup=main_menu_kb(),
        )
        return
    await state.set_state(FlashcardsState.in_review)
    await message.answer(
        "🃏 <b>Режим карточек</b>\n\n"
        "Вспомни перевод, затем нажми «✅ I know it» или «❌ Don't know».\n"
        "После ответа придёт следующая карточка.\n"
        "Выход — 🏠 Main menu или /cancel",
        parse_mode="HTML",
        reply_markup=flashcards_menu_kb(),
    )
    if not await _send_card(message, db, message.from_user.id):
        await state.clear()


@router.message(FlashcardsState.in_review, F.text == "➕ Add word")
async def cards_add_word_start(message: Message, state: FSMContext) -> None:
    await state.set_state(FlashcardsState.add_word)
    await message.answer(
        "Отправь английское слово или фразу — добавлю в колоду.\n"
        "Например: <b>journey</b>, <b>take off</b>",
        parse_mode="HTML",
        reply_markup=add_word_kb(),
    )


@router.message(FlashcardsState.add_word, F.text.in_({"⬅️ Back to cards", "🏠 Main menu"}))
async def cards_add_word_nav(message: Message, db: Database, state: FSMContext) -> None:
    if "Main menu" in (message.text or ""):
        await state.clear()
        await message.answer("✅ Режим карточек завершён.", reply_markup=main_menu_kb())
    else:
        await flashcards(message, db, state)


@router.message(FlashcardsState.add_word, ~F.text.regexp(r"^[A-Za-z][A-Za-z '\-]{1,30}$"))
async def cards_add_word_hint(message: Message, state: FSMContext) -> None:
    await message.answer(
        "Жду английское слово латиницей. Выход — ⬅️ Back to cards.",
        reply_markup=add_word_kb(),
    )


@router.message(Command("cancel"), FlashcardsState.in_review)
async def cards_cancel(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("✅ Режим карточек завершён.", reply_markup=main_menu_kb())


@router.message(FlashcardsState.in_review)
async def cards_text_hint(message: Message, state: FSMContext) -> None:
    text = message.text or ""
    if "Main menu" in text or "Отмена" in text:
        await state.clear()
        await message.answer("✅ Режим карточек завершён.", reply_markup=main_menu_kb())
        return
    await message.answer(
        "Нажмите «✅ I know it» или «❌ Don't know» под карточкой.\n"
        "Выход — 🏠 Main menu или /cancel",
        parse_mode="HTML",
        reply_markup=flashcards_menu_kb(),
    )


def _find_word_info(word: str):
    """Найти (перевод, пример) слова во всех уровнях."""
    for lv_words in VOCABULARY.values():
        for w, t, e in lv_words:
            if w.lower() == word.lower():
                return t, e
    return None, None


@router.callback_query(F.data == "card:start")
async def start_review_from_ping(call: CallbackQuery, db: Database, state: FSMContext) -> None:
    """Запуск повторения из напоминания планировщика."""
    uid = call.from_user.id
    level = await db.get_level(uid)
    await call.answer()
    if not await db.due_cards(uid, level, limit=1):
        await state.clear()
        await call.message.answer(
            "🎉 Повторять пока нечего — всё повторено.", reply_markup=main_menu_kb())
        return
    await state.set_state(FlashcardsState.in_review)
    await call.message.answer(
        "🃏 <b>Режим карточек</b>\n\n"
        "Вспомни перевод, затем нажми «✅ I know it» или «❌ Don't know».\n"
        "Выход — 🏠 Main menu или /cancel",
        parse_mode="HTML", reply_markup=flashcards_menu_kb(),
    )
    if not await _send_card(call.message, db, uid):
        await state.clear()


@router.callback_query(F.data.startswith("rev:"))
async def review_callback(call: CallbackQuery, db: Database, state: FSMContext) -> None:
    _, level, correct_flag = call.data.split(":")
    correct = correct_flag == "1"
    text = call.message.text or ""
    word = None
    for line in text.splitlines():
        if line.startswith("🃏"):
            word = line.replace("🃏", "").strip()
            break
    if not word:
        await call.answer("Не нашёл карточку", show_alert=True)
        return
    new_box = await db.review_card(call.from_user.id, word, correct)
    await db.incr_usage(call.from_user.id, "review")
    active = _card_active.get(call.from_user.id)
    if active and active[0] == word:
        translation, example = active[1], active[2]
    else:
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
    if await state.get_state() == FlashcardsState.in_review.state:
        if not await _send_card(call.message, db, call.from_user.id):
            await state.clear()


def _pick_question(user_id: int, level: str):
    """Выбрать вопрос уровня без повторов и запомнить его активным."""
    pool_all = list(QUIZ_BY_LEVEL.get(level) or QUIZ_SENTENCES)
    if level == "beginner":
        pool_all += list(QUIZ_SENTENCES)
    hist = _quiz_seen.setdefault(user_id, [])
    pool = [q for q in pool_all if q[0] not in hist]
    if not pool:
        hist.clear()
        pool = pool_all
    q = random.choice(pool)
    _quiz_active[user_id] = q
    hist.append(q[0])
    if len(hist) > 5:
        del hist[0]
    return q


async def _send_question(message: Message, db: Database, user_id: int) -> bool:
    """Отправить следующий вопрос. False — дневной лимит исчерпан."""
    if not await db.within_limit(user_id, "quiz", LIMITS.free_quizzes_per_day):
        used = await db.get_usage(user_id, "quiz")
        await message.answer(
            f"📭 Лимит квиза на сегодня исчерпан ({used}/{LIMITS.free_quizzes_per_day} вопросов).\n\n"
            + UPGRADE_HINTS["quiz"].format(limit=LIMITS.free_quizzes_per_day),
            reply_markup=main_menu_kb(),
        )
        return False
    level = await db.get_level(user_id)
    sentence, translation, a, b, _answer = _pick_question(user_id, level)
    body = f"<b>{sentence}</b>"
    if translation:
        body += f"\n<i>({translation})</i>"
    await message.answer(
        f"✍️ <b>Quiz</b> — выбери правильный вариант:\n\n"
        f"{body}\n\n"
        f"A) {a}\nB) {b}",
        parse_mode="HTML",
        reply_markup=answer_quiz_cb(level),
    )
    return True


@router.message(F.text == "✍️ Quiz")
async def quiz_start(message: Message, db: Database, state: FSMContext) -> None:
    await state.set_state(QuizState.in_quiz)
    await message.answer(
        "✍️ <b>Режим квиза</b>\n\n"
        "После каждого ответа придёт следующий вопрос.\n"
        "Выход — 🏠 Main menu или /cancel",
        parse_mode="HTML",
        reply_markup=quiz_menu_kb(),
    )
    if not await _send_question(message, db, message.from_user.id):
        await state.clear()


@router.message(Command("cancel"), QuizState.in_quiz)
async def quiz_cancel(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("✅ Режим квиза завершён.", reply_markup=main_menu_kb())


@router.message(QuizState.in_quiz)
async def quiz_text_hint(message: Message, state: FSMContext) -> None:
    text = message.text or ""
    if "Main menu" in text or "Отмена" in text:
        await state.clear()
        await message.answer("✅ Режим квиза завершён.", reply_markup=main_menu_kb())
        return
    await message.answer(
        "Нажмите кнопку <b>A</b> или <b>B</b> под вопросом.\n"
        "Выход — 🏠 Main menu или /cancel",
        parse_mode="HTML",
        reply_markup=quiz_menu_kb(),
    )


@router.callback_query(F.data.startswith("quiz:"))
async def quiz_answer(call: CallbackQuery, db: Database, state: FSMContext) -> None:
    _, level, choice = call.data.split(":")
    await db.incr_usage(call.from_user.id, "quiz")
    text = call.message.text or ""
    q = _quiz_active.get(call.from_user.id)
    if q and q[0] not in text:
        q = None
    if not q:
        q = next((cand for cand in _ALL_QUIZ if cand[0] in text), None)
    if not q:
        await call.answer("Вопрос не найден", show_alert=True)
        return
    correct = q[4]
    right_word = q[2] if correct == "A" else q[3]
    if choice == correct:
        streak = _quiz_streak.get(call.from_user.id, 0) + 1
        _quiz_streak[call.from_user.id] = streak
        record = await db.update_quiz_result(call.from_user.id, streak)
        await call.message.edit_text(
            f"✅ Верно: <b>{right_word}</b>\n"
            f"🔥 Серия: <b>{streak}</b>"
            + ("\n\n🏆 Новый рекорд квиза!" if record else ""),
            parse_mode="HTML",
        )
    else:
        import html as _html
        chosen = q[2] if choice == "A" else q[3]
        lost = _quiz_streak.pop(call.from_user.id, 0)
        await call.message.edit_text(
            "❌ <b>Неверно</b>\n\n" + _html.escape(text) + "\n\n"
            + f"Ваш ответ: {_html.escape(chosen)}\n"
            + f"Правильный: <b>{_html.escape(right_word)}</b>\n"
            + (f"\nСерия из {lost} прервана." if lost else ""),
            parse_mode="HTML",
        )
    await call.answer()
    if await state.get_state() == QuizState.in_quiz.state:
        if not await _send_question(call.message, db, call.from_user.id):
            await state.clear()


@router.message(F.text == "➕ Add word")
async def add_word_hint(message: Message) -> None:
    await message.answer(
        "Просто отправь мне английское слово (например: <b>journey</b>) — "
        "я добавлю его в твою колоду для повторения.",
        parse_mode="HTML",
        reply_markup=main_menu_kb(),
    )


@router.message(StateFilter(None), F.text.regexp(r"^[A-Za-z][A-Za-z '\-]{1,30}$"))
async def add_user_word(message: Message, db: Database, state: FSMContext) -> None:
    # в режиме разговора обычные сообщения обрабатывает chat-хендлер
    st = await state.get_state()
    if st and st != FlashcardsState.add_word.state:
        return
    kb = add_word_kb() if st == FlashcardsState.add_word.state else main_menu_kb()
    if not await db.within_limit(message.from_user.id, "words", LIMITS.free_words_per_day):
        await message.answer(
            UPGRADE_HINTS["words"].format(limit=LIMITS.free_words_per_day),
            reply_markup=kb,
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
        added = await db.add_word_to_deck(message.from_user.id, w, t, e)
        await db.incr_usage(message.from_user.id, "words")
        await message.answer(
            f"✅ Слово <b>{w}</b> уже в моей базе!\n💡 <i>{t}</i>\n📝 <b>{e}</b>"
            + ("\nДобавлено в твою колоду!" if added else "\nОно уже в твоей колоде."),
            parse_mode="HTML",
            reply_markup=kb,
        )
    else:
        import dictionary
        hit = dictionary.en_ru_lookup(word)
        if not hit:
            from chat_engine import word_card
            card = await word_card(word)
            if card and card["status"] == "ok":
                added = await db.add_word_to_deck(
                    message.from_user.id, card["word"], card["ru"], card["example"]
                )
                await db.incr_usage(message.from_user.id, "words")
                await message.answer(
                    f"✅ <b>{card['word']}</b>\n💡 <i>{card['ru']}</i>\n"
                    f"📝 <b>{card['example']}</b>\n"
                    + ("Добавлено в твою колоду!" if added else "Оно уже в твоей колоде."),
                    parse_mode="HTML",
                    reply_markup=kb,
                )
                return
            if card and card["status"] == "fix":
                await message.answer(
                    f"✏️ Похоже на опечатку. Правильно: <b>{card['word']}</b> — <i>{card['ru']}</i>\n"
                    "Добавить исправленный вариант?",
                    parse_mode="HTML",
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                        InlineKeyboardButton(text=f"➕ {card['word']}",
                                             callback_data=f"addw:{card['word']}")
                    ]]),
                )
                return
            # модель сказала NO или недоступна — офлайн-подсказки
            sugg = dictionary.suggest_en(word)
            if sugg:
                rows = [[InlineKeyboardButton(text=f"➕ {x}", callback_data=f"addw:{x}")]
                        for x in sugg]
                await message.answer(
                    f"❌ Слова «{word}» в словаре нет — в колоду его не добавляю.\n"
                    "Возможно, вы имели в виду:",
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
                )
            else:
                await message.answer(
                    f"❌ Не нашёл перевод для «{word}» — проверьте написание.\n"
                    "В колоду не добавляю: слово без перевода учить нечем.",
                    reply_markup=kb,
                )
            return
        translation = hit[0]
        added = await db.add_word_to_deck(message.from_user.id, word, translation, "")
        await db.incr_usage(message.from_user.id, "words")
        if added:
            await message.answer(
                f"✅ Добавил «{word}» в твою колоду!\n💡 <i>{translation}</i>\n"
                "Завтра попрошу повторить 😉",
                parse_mode="HTML",
                reply_markup=kb,
            )
        else:
            await message.answer("Это слово уже в твоей колоде 👍")


def _topics_line(rows) -> str:
    if not rows:
        return ""
    import topics as T
    parts = []
    for tid, n in rows:
        t = T.get_topic(tid)
        name = t["title"].split(" ", 1)[-1] if t else tid
        parts.append(f"{name} — {n}")
    return "💬 Темы: " + ", ".join(parts) + "\n"


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
    from config import MASTERED_BOX as mastered_box
    pr = await db.get_progress(message.from_user.id)
    boxes = pr["boxes"]
    mastered = sum(n for b, n in boxes.items() if b >= mastered_box)
    fresh = boxes.get(0, 0)
    working = sum(boxes.values()) - mastered - fresh
    fire = "🔥" if pr["streak"] >= 3 else "📅"
    await message.answer(
        f"📊 <b>Твой прогресс</b>\n\n"
        f"🎫 План: {PLAN_NAMES[tier]}\n"
        f"🎯 Уровень: {LEVEL_NAMES[level]}\n\n"
        f"{fire} Серия: <b>{pr['streak']}</b> дн. (лучшая {pr['best_streak']})\n"
        f"🗓 Дней занятий: {pr['days']} · действий: {pr['actions']}\n"
        + (f"⏱ Время практики: ≈ {pr['seconds'] // 60} мин\n" if pr["seconds"] >= 60 else "")
        + _topics_line(pr["topics"]) + "\n"
        f"🃏 Колода: <b>{stats['deck_size']}</b> слов\n"
        f"   ✅ освоено: {mastered}\n"
        f"   📖 в работе: {working}\n"
        f"   🆕 новые: {fresh}\n"
        f"⏰ К повторению сейчас: {pr['due']}\n"
        f"🏆 Рекорд в квизе: {stats['quiz_best']}/10"
        + limits_line,
        parse_mode="HTML",
        reply_markup=main_menu_kb(),
    )


@router.message(F.text == "🎯 Level")
async def choose_level(message: Message, db: Database) -> None:
    import placement
    prof = await db.get_profile(message.from_user.id)
    level = await db.get_level(message.from_user.id)
    cefr = prof["cefr"] or "не определён"
    await message.answer(
        f"🎯 <b>Уровень</b>\n\n"
        f"CEFR: <b>{cefr}</b>\n"
        f"Рабочий уровень: {LEVEL_NAMES[level]}\n\n"
        "Пройдите тест — он поднимается по ступеням A1–C2 и останавливается "
        "там, где начинаются ошибки. Или выберите уровень вручную.",
        parse_mode="HTML",
        reply_markup=level_sub_kb(),
    )


@router.callback_query(F.data.startswith("lvl:"))
async def set_level(call: CallbackQuery, db: Database) -> None:
    level = call.data.split(":")[1]
    await db.set_level(call.from_user.id, level)
    await call.message.edit_text(f"🎯 Теперь твой уровень: {LEVEL_NAMES[level]}")
    await call.answer()


@router.callback_query(F.data.startswith("addw:"))
async def add_suggested_word(cb: CallbackQuery, db: Database) -> None:
    """Добавление слова из подсказки — в колоду идёт проверенный вариант."""
    import dictionary
    word = cb.data.split(":", 1)[1].strip().lower()
    hit = dictionary.en_ru_lookup(word)
    if hit:
        ru, example = hit[0], ""
    else:
        from chat_engine import word_card
        card = await word_card(word)
        if not card or card["status"] != "ok":
            await cb.answer("Перевод не найден", show_alert=True)
            return
        ru, example = card["ru"], card["example"]
    if not await db.within_limit(cb.from_user.id, "words", LIMITS.free_words_per_day):
        await cb.answer("Лимит слов на сегодня исчерпан", show_alert=True)
        return
    added = await db.add_word_to_deck(cb.from_user.id, word, ru, example)
    await db.incr_usage(cb.from_user.id, "words")
    await cb.answer("Добавлено" if added else "Уже в колоде")
    await cb.message.answer(
        f"✅ <b>{word}</b>\n💡 <i>{ru}</i>\n"
        + (f"📝 <b>{example}</b>\n" if example else "")
        + ("Добавлено в твою колоду!" if added else "Оно уже в твоей колоде."),
        parse_mode="HTML",
        reply_markup=main_menu_kb(),
    )


def _notify_text(enabled: bool, hour: int, tz: int = 5) -> str:
    state = f"включены, в {hour:02d}:00" if enabled else "выключены"
    return (
        "🔔 <b>Напоминания о повторении</b>\n"
        f"Сейчас: {state} (ваш пояс UTC{tz:+d}).\n\n"
        "Напомню не чаще раза в день и только если есть слова к повторению. "
        "Если вы уже позанимались — не потревожу."
    )


@router.message(F.text == "🔔 Напоминания")
async def notify_settings(message: Message, db: Database) -> None:
    uid = message.from_user.id
    enabled, hour = await db.get_notify_prefs(uid)
    tz = await db.get_notify_tz(uid)
    await message.answer(
        _notify_text(enabled, hour, tz), parse_mode="HTML",
        reply_markup=notify_kb(enabled, hour, tz),
    )


@router.callback_query(F.data.startswith("notify:"))
async def notify_change(call: CallbackQuery, db: Database) -> None:
    from aiogram.exceptions import TelegramBadRequest
    uid = call.from_user.id
    enabled, hour = await db.get_notify_prefs(uid)
    tz = await db.get_notify_tz(uid)
    action = call.data.split(":", 1)[1]
    if action == "close":
        await call.answer()
        try:
            await call.message.edit_text("Настройки напоминаний сохранены.", reply_markup=None)
        except TelegramBadRequest:
            pass
        return
    if action == "tz":
        await call.answer()
        await call.message.edit_text(
            "🌍 Ваш часовой пояс — напоминание придёт в выбранный час по вашему времени.",
            reply_markup=notify_tz_kb(tz),
        )
        return
    if action == "back":
        await call.answer()
    elif action.startswith("tz") and action[2:].isdigit():
        tz = int(action[2:])
        await db.set_notify_tz(uid, tz)
        await call.answer(f"Пояс UTC{tz:+d}")
    elif action == "toggle":
        enabled = not enabled
        await db.set_notify_prefs(uid, enabled, hour)
        await call.answer("Сохранено")
    elif action.startswith("h") and action[1:].isdigit():
        hour, enabled = int(action[1:]), True
        await db.set_notify_prefs(uid, enabled, hour)
        await call.answer("Сохранено")
    else:
        await call.answer()
        return
    try:
        await call.message.edit_text(
            _notify_text(enabled, hour, tz), parse_mode="HTML",
            reply_markup=notify_kb(enabled, hour, tz),
        )
    except TelegramBadRequest:
        pass  # сообщение не изменилось

class PlacementState(StatesGroup):
    in_test = State()


async def _send_placement_question(msg: Message, state: FSMContext, db: Database, uid: int) -> None:
    import placement
    data = await state.get_data()
    ids, pos, seed = data["ids"], data["pos"], data["seed"]
    if pos >= len(ids):
        answers = [(l, bool(ok)) for l, ok in data["answers"]]
        cefr = placement.score(answers)
        internal = placement.TO_INTERNAL[cefr]
        await db.set_profile(uid, cefr=cefr)
        await db.set_level(uid, internal)
        correct = sum(1 for _, ok in answers if ok)
        await state.clear()
        await msg.answer(
            f"🎓 <b>Ваш уровень: {cefr}</b>\n"
            f"Верных ответов: {correct} из {len(answers)}\n"
            f"Рабочий уровень бота: {LEVEL_NAMES[internal]}\n\n"
            "Слова и карточки подобраны под него. Пройти тест заново — 🎯 Level.",
            parse_mode="HTML",
            reply_markup=main_menu_kb(),
        )
        try:
            import asyncio
            import logging
            import card
            from aiogram.types import (BufferedInputFile, InlineKeyboardButton,
                                       InlineKeyboardMarkup)
            pr = await db.get_progress(uid)
            st = await db.get_stats(uid)
            me = await msg.bot.get_me()
            png = await asyncio.to_thread(
                card.render_level_card, cefr, pr.get("streak", 0),
                st.get("deck_size", 0), me.username)
            link = f"https://t.me/{me.username}?start=ref_{uid}"
            share = ("https://t.me/share/url?url=" + link +
                     "&text=Мой%20уровень%20английского%20—%20" + cefr +
                     ".%20А%20у%20тебя%3F")
            await msg.answer_photo(
                BufferedInputFile(png, filename="level.png"),
                caption=(f"🎓 {cefr} — карточка готова.\n"
                         "Перешлите её другу или отправьте ссылку кнопкой ниже: "
                         "за приглашение вам придут дни Plus."),
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="📤 Поделиться ссылкой", url=share)]]),
            )
        except Exception as exc:  # noqa: BLE001 — картинка не должна ломать результат теста
            import logging
            logging.getLogger(__name__).warning("level card failed: %s", exc)
        return
    q_index = ids[pos]
    _level, text, _opts, _c = placement.QUESTIONS[q_index]
    opts, correct_idx = placement.options_shuffled(q_index, seed)
    await state.update_data(correct=correct_idx)
    await msg.answer(
        f"Вопрос <b>{pos + 1}/{len(ids)}</b>\n\n{text}",
        parse_mode="HTML",
        reply_markup=placement_kb(opts),
    )


@router.callback_query(F.data.startswith("plc:"))
async def _begin_placement(message: Message, state: FSMContext, db: Database,
                           user_id: int, mode: str) -> None:
    """Общий запуск теста: и из подменю, и со старой inline-кнопки."""
    import random
    import placement
    ids = placement.QUICK if mode == "quick" else placement.FULL
    await state.set_state(PlacementState.in_test)
    await state.update_data(ids=list(ids), pos=0, answers=[], seed=random.randint(1, 10**6))
    await _send_placement_question(message, state, db, user_id)


async def placement_start(call: CallbackQuery, state: FSMContext, db: Database) -> None:
    mode = call.data.split(":", 1)[1]
    await call.answer()
    await _begin_placement(call.message, state, db, call.from_user.id, mode)


@router.message(F.text == "🎯 Пройти тест")
async def level_full_test(message: Message, state: FSMContext, db: Database) -> None:
    await _begin_placement(message, state, db, message.from_user.id, "full")


@router.message(F.text == "⚡ Быстрый тест")
async def level_quick_test(message: Message, state: FSMContext, db: Database) -> None:
    await _begin_placement(message, state, db, message.from_user.id, "quick")


@router.message(F.text == "🎓 Выбрать уровень")
async def level_manual(message: Message) -> None:
    await message.answer(
        "🎓 Выберите рабочий уровень вручную. Тест точнее, но выбор тоже работает.",
        reply_markup=levels_kb(),
    )


@router.message(F.text == "🧭 Цель обучения")
async def level_goal(message: Message, db: Database) -> None:
    prof = await db.get_profile(message.from_user.id)
    await message.answer(
        "🧭 Зачем вам английский? Цель влияет на лексику и примеры в разговоре.",
        reply_markup=goals_kb(prof["goal"]),
    )


@router.callback_query(PlacementState.in_test, F.data.startswith("plca:"))
async def placement_answer(call: CallbackQuery, state: FSMContext, db: Database) -> None:
    import placement
    data = await state.get_data()
    ids, pos = data["ids"], data["pos"]
    level = placement.QUESTIONS[ids[pos]][0]
    ok = int(call.data.split(":", 1)[1]) == int(data.get("correct", -1))
    answers = list(data["answers"]) + [[level, ok]]
    await state.update_data(answers=answers, pos=pos + 1)
    await call.answer("Верно ✅" if ok else "Неверно ❌")
    await _send_placement_question(call.message, state, db, call.from_user.id)


@router.message(Command("cancel"), PlacementState.in_test)
async def placement_cancel(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Тест прерван. Уровень не изменён.", reply_markup=main_menu_kb())


@router.callback_query(F.data == "goal:menu")
async def goal_menu(call: CallbackQuery, db: Database) -> None:
    prof = await db.get_profile(call.from_user.id)
    await call.answer()
    await call.message.answer(
        "Зачем вам английский? Подберу темы и лексику под цель.",
        reply_markup=goals_kb(prof["goal"]),
    )


@router.callback_query(F.data.startswith("goal:"))
async def goal_set(call: CallbackQuery, db: Database) -> None:
    from placement import GOALS
    key = call.data.split(":", 1)[1]
    if key not in GOALS:
        await call.answer()
        return
    await db.set_profile(call.from_user.id, goal=key)
    await call.answer("Цель сохранена")
    await call.message.edit_text(
        f"🎯 Цель: <b>{GOALS[key]}</b>\nТемы и лексика будут подбираться под неё.",
        parse_mode="HTML",
        reply_markup=goals_kb(key),
    )


@router.message(Command("export"))
async def export_progress(message: Message, db: Database) -> None:
    """Выгрузка прогресса в JSON — на случай переезда или переделки проекта."""
    import json
    from aiogram.types import BufferedInputFile
    data = await db.export_user(message.from_user.id)
    payload = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
    await message.answer_document(
        BufferedInputFile(payload, filename=f"english-progress-{message.from_user.id}.json"),
        caption=(
            f"📦 Ваш прогресс: {len(data['cards'])} слов, "
            f"{len(data['activity'])} записей активности.\n"
            "Формат JSON — читается любым языком и не зависит от бота."
        ),
    )
