"""Расширенная словарная база: дополнительные слова для каждого уровня.
Формат: (english, translation, example). Правьте этот файл, не трогая vocabulary.py."""

EXTENDED_BEGINNER = [
    ("breakfast", "завтрак", "I have eggs and toast for breakfast."),
    ("dinner", "ужин", "We usually have dinner at seven."),
    ("kitchen", "кухня", "The kettle is on the kitchen table."),
    ("bedroom", "спальня", "My bedroom is small but cosy."),
    ("window", "окно", "Please open the window to let fresh air in."),
    ("door", "дверь", "He knocked on the door twice."),
    ("table", "стол", "The keys are on the table."),
    ("chair", "стул", "Sit down, please — take this chair."),
    ("phone", "телефон", "My phone battery is almost dead."),
    ("money", "деньги", "I need money to buy a new ticket."),
    ("time", "время", "What time is it now?"),
    ("year", "год", "This year has been very busy."),
    ("week", "неделя", "We start a new week on Monday."),
    ("day", "день", "Have a nice day!"),
    ("hour", "час", "The film lasted two hours."),
    ("person", "человек", "She is a kind person."),
    ("man", "мужчина", "The man next to me was reading a newspaper."),
    ("woman", "женщина", "That woman works at the hospital."),
    ("boy", "мальчик", "The boy rides his bike every evening."),
    ("girl", "девочка", "The girl sings beautifully."),
    ("teacher", "учитель", "Our teacher explains grammar very clearly."),
    ("student", "студент", "He is a hard-working student."),
    ("doctor", "врач", "You should see a doctor about that cough."),
    ("police", "полиция", "Call the police if you feel unsafe."),
    ("city", "город", "London is a huge and noisy city."),
    ("village", "деревня", "My grandparents live in a quiet village."),
    ("country", "страна", "Which country would you like to visit?"),
    ("language", "язык", "English is a global language."),
    ("name", "имя", "May I ask your name?"),
    ("number", "номер, число", "Can you repeat the number, please?"),
    ("colour", "цвет", "Blue is my favourite colour."),
    ("black", "чёрный", "She wore a black dress to the party."),
    ("white", "белый", "The walls of the room are white."),
    ("red", "красный", "The red traffic light means stop."),
    ("green", "зелёный", "Turn left at the green sign."),
    ("hot", "горячий, жаркий", "It is very hot outside today."),
    ("cold", "холодный", "My hands are cold — it's freezing!"),
    ("warm", "тёплый", "The water is warm enough to swim."),
    ("new", "новый", "He bought a new bike last week."),
    ("old", "старый", "This is an old building from 1902."),
    ("good", "хороший", "That's a good question."),
    ("bad", "плохой", "Smoking is bad for your health."),
    ("long", "длинный", "We waited a long time for the bus."),
    ("short", "короткий", "The meeting was short and useful."),
    ("young", "молодой", "Young children learn languages quickly."),
    ("to drink", "пить", "I drink water after sport."),
    ("to go", "идти, ехать", "Let's go to the cinema tonight."),
    ("to come", "приходить", "Come to my place at six."),
    ("to see", "видеть", "Did you see that bird?"),
    ("to hear", "слышать", "I can hear music from the street."),
    ("to give", "давать", "Give me a hand with this box, please."),
    ("to take", "брать", "Take an umbrella — it might rain."),
    ("to help", "помогать", "Can you help me with my homework?"),
    ("to learn", "учить(ся)", "I learn new words every day."),
    ("to teach", "учить (преподавать)", "She teaches maths at school."),
    ("to buy", "покупать", "I want to buy some bread."),
    ("to sell", "продавать", "They sell fruit at the market."),
    ("to pay", "платить", "Who will pay for lunch?"),
    ("to ask", "спрашивать", "Don't be afraid to ask questions."),
    ("to answer", "отвечать", "Please answer my message today."),
    ("to call", "звонить", "I'll call you when I arrive."),
    ("to open", "открывать", "Can you open the door for me?"),
    ("to close", "закрывать", "Close the window, it's cold."),
    ("left", "левый / налево", "Turn left at the corner."),
    ("right", "правый / направо", "The shop is on the right."),
    ("here", "здесь", "Come here, please."),
    ("there", "там", "The files are over there."),
    ("now", "сейчас", "I'm busy right now."),
    ("later", "позже", "Let's talk later, okay?"),
    ("before", "до, раньше", "Wash your hands before eating."),
    ("after", "после", "We went for a walk after dinner."),
    ("again", "снова", "Try again — you can do it!"),
    ("very", "очень", "She is very clever."),
]

# Остальные секции можно дополнять позже по той же схеме:
EXTENDED_INTERMEDIATE = []
EXTENDED_ADVANCED = []
EXTRA_QUIZ_SENTENCES = []

# ----------------------------------------------------------------------------
# Расширение базы из vocab_extra.py добавляется автоматически (без дубликатов).
# Чтобы добавить свои слова — правьте data/vocab_extra.py.
# ----------------------------------------------------------------------------

def _merge_extended() -> None:
    from data.vocab_extra import (
        EXTENDED_BEGINNER, EXTENDED_INTERMEDIATE, EXTENDED_ADVANCED,
        EXTRA_QUIZ_SENTENCES,
    )
    mapping = {
        "beginner": EXTENDED_BEGINNER,
        "intermediate": EXTENDED_INTERMEDIATE,
        "advanced": EXTENDED_ADVANCED,
    }
    for level, extra in mapping.items():
        base = VOCABULARY[level]
        seen = {w.lower() for w, _, _ in base}
        for word, trans, ex in extra:
            if word.lower() not in seen:
                base.append((word, trans, ex))
                seen.add(word.lower())

    existing = {q[0].strip() for q in QUIZ_SENTENCES}
    for q in EXTRA_QUIZ_SENTENCES:
        if q[0].strip() not in existing:
            QUIZ_SENTENCES.append(q)
            existing.add(q[0].strip())


_merge_extended()
