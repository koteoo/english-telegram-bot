"""Темы для изучения английского: идеи, лексика и вопросы для разговорной практики.

Каждая тема:
  title        — название в меню
  emoji        — иконка
  description  — краткое описание (RU)
  ideas        — идеи/подтемы, что обсуждать и учить по теме
  phrases      — полезные выражения EN + перевод RU
  questions    — разговорные вопросы для практики speaking/writing
"""

TOPICS = [
    {
        "id": "travel",
        "title": "Travel & Holidays",
        "emoji": "✈️",
        "description": "Путешествия, аэропорт, отель, планы на отпуск",
        "ideas": [
            "Describe your last trip: where, with whom, what you saw",
            "Dream destination: why do you want to visit it?",
            "At the airport / hotel check-in: role-play a dialogue",
            "Pack a suitcase: what do you take and why?",
            "Travel problems: lost luggage, delayed flights — what do you do?",
        ],
        "phrases": [
            ("I'd like to book a room for two nights.", "Я хотел бы забронировать номер на две ночи."),
            ("Where is the nearest subway station?", "Где ближайшая станция метро?"),
            ("Could I see the menu, please?", "Можно мне меню, пожалуйста?"),
            ("My flight was delayed by three hours.", "Мой рейс задержали на три часа."),
            ("I'm just here for the sights.", "Я здесь только ради достопримечательностей."),
        ],
        "questions": [
            "What is the most beautiful place you have ever visited?",
            "Do you prefer beach holidays or city trips? Why?",
            "Have you ever travelled alone? What was it like?",
            "What three things would you pack for a week-long trip?",
            "If you could live in another country, which one would you choose?",
        ],
    },
    {
        "id": "food",
        "title": "Food & Cooking",
        "emoji": "🍕",
        "description": "Еда, рестораны, рецепты, вкусы и привычки",
        "ideas": [
            "Talk about your favourite dish and how it's made",
            "Order food in a café: role-play with the waiter",
            "Healthy eating: is fast food really that bad?",
            "National cuisine of your country — explain it to a foreigner",
            "Cooking show: describe a recipe step by step",
        ],
        "phrases": [
            ("Could I have the bill, please?", "Можно счёт, пожалуйста?"),
            ("I'm allergic to nuts.", "У меня аллергия на орехи."),
            ("It tastes delicious / salty / spicy.", "На вкус очень вкусно / солоно / остро."),
            ("I usually have cereal for breakfast.", "Обычно я ем хлопья на завтрак."),
            ("Would you like something to drink?", "Хотите что-нибудь выпить?"),
        ],
        "questions": [
            "What did you eat yesterday? Describe it in detail.",
            "Can you cook? What is your signature dish?",
            "Is it better to eat at home or in a restaurant?",
            "What food from your country should everyone try?",
            "Do you like trying exotic food? What is the strangest thing you've eaten?",
        ],
    },
    {
        "id": "work",
        "title": "Work & Career",
        "emoji": "💼",
        "description": "Работа, профессия, собеседование, карьера",
        "ideas": [
            "Mock job interview: strengths, weaknesses, goals",
            "Describe a typical working day",
            "Remote work vs office: pros and cons",
            "Dream job: what would you do if money didn't matter?",
            "Write a short formal email to your manager",
        ],
        "phrases": [
            ("I work as a software engineer.", "Я работаю инженером-программистом."),
            ("I'm responsible for customer support.", "Я отвечаю за поддержку клиентов."),
            ("Could we reschedule the meeting?", "Можем перенести встречу?"),
            ("I'll get back to you by Friday.", "Отвечу вам до пятницы."),
            ("I'm looking for a new challenge.", "Я ищу новый вызов себе."),
        ],
        "questions": [
            "What do you do for a living? Do you enjoy it?",
            "What was your first job like?",
            "Is work-life balance important to you?",
            "Would you rather have a high salary or an interesting job?",
            "How do you think AI will change jobs in the future?",
        ],
    },
    {
        "id": "hobbies",
        "title": "Hobbies & Free Time",
        "emoji": "🎸",
        "description": "Хобби, спорт, музыка, кино, отдых",
        "ideas": [
            "Present your favourite hobby and why you love it",
            "Recommend a film / series / book to me",
            "Sports: do you play or watch? Talk about a match",
            "Weekend plans: what makes you relax?",
            "Learn something new: what skill would you like to pick up?",
        ],
        "phrases": [
            ("I'm really into photography.", "Я увлекаюсь фотографией."),
            ("I play the guitar in my free time.", "В свободное время я играю на гитаре."),
            ("It helps me unwind after work.", "Это помогает мне расслабиться после работы."),
            ("Let's hang out this weekend!", "Давай проведем вместе выходные!"),
            ("I can't stop binge-watching that series.", "Не могу перестать запоем смотреть тот сериал."),
        ],
        "questions": [
            "What do you usually do on weekends?",
            "Have you got any hidden talents?",
            "What kind of music do you listen to?",
            "Is it better to have many hobbies or one passion?",
            "What's the last film or book that impressed you?",
        ],
    },
    {
        "id": "family",
        "title": "Family & Friends",
        "emoji": "👨‍👩‍👧",
        "description": "Семья, друзья, отношения, знакомства",
        "ideas": [
            "Describe your family: names, ages, personalities",
            "A best friend: how you met and why you're close",
            "Big family vs small family: advantages",
            "Traditions: what does your family celebrate together?",
            "Making friends as an adult — is it hard?",
        ],
        "phrases": [
            ("I've got two older brothers.", "У меня два старших брата."),
            ("We're very close.", "Мы очень близки."),
            ("He takes after his father.", "Он похож на отца (характером)."),
            ("She's my flatmate.", "Она моя соседка по квартире."),
            ("We've known each other since school.", "Мы знакомы со школы."),
        ],
        "questions": [
            "Tell me about your family. Who are you closest to?",
            "What qualities make a good friend?",
            "Do you prefer big family gatherings or quiet evenings?",
            "What tradition would you like to start in your family?",
            "Is it easier to make friends in childhood or adulthood?",
        ],
    },
    {
        "id": "health",
        "title": "Health & Lifestyle",
        "emoji": "🏃",
        "description": "Здоровье, спорт, сон, привычки",
        "ideas": [
            "Visit the doctor: role-play symptoms and advice",
            "Healthy habits: what do you already do?",
            "Sleep: how many hours do you need and why?",
            "Stress management: your personal techniques",
            "Give me advice: I want to start running",
        ],
        "phrases": [
            ("I've got a headache / sore throat.", "У меня болит голова / горло."),
            ("You should get some rest.", "Тебе стоит отдохнуть."),
            ("I try to stay in shape.", "Я стараюсь поддерживать форму."),
            ("Take this medicine twice a day.", "Принимайте это лекарство дважды в день."),
            ("I feel much better today.", "Сегодня я чувствую себя гораздо лучше."),
        ],
        "questions": [
            "What do you do to stay healthy?",
            "How many hours do you sleep? Is it enough?",
            "Do you exercise regularly? What suits you best?",
            "What is the hardest habit to break?",
            "Is modern medicine making us healthier or lazier?",
        ],
    },
    {
        "id": "technology",
        "title": "Technology & Internet",
        "emoji": "🤖",
        "description": "Технологии, соцсети, AI, гаджеты",
        "ideas": [
            "Smartphone addiction: is it a real problem?",
            "Explain your favourite app to someone who never used it",
            "AI: helper or threat? Share your opinion",
            "Social media: how much time do you spend there?",
            "Life without internet for a week — could you?",
        ],
        "phrases": [
            ("My phone battery has run out.", "У моего телефона села батарея."),
            ("The connection keeps dropping.", "Связь постоянно обрывается."),
            ("It's user-friendly and intuitive.", "Это удобно и интуитивно понятно."),
            ("I can't live without Wi-Fi.", "Я не могу жить без Wi-Fi."),
            ("Let's chat online later.", "Давай поболтаем онлайн позже."),
        ],
        "questions": [
            "How has technology changed your daily life?",
            "Do you trust artificial intelligence?",
            "Which gadget could you not live without?",
            "Should children have smartphones? At what age?",
            "Will paper books disappear in the future?",
        ],
    },
    {
        "id": "movies",
        "title": "Movies & Music",
        "emoji": "🎬",
        "description": "Кино, сериалы, музыка, звёзды",
        "ideas": [
            "Review the last film you watched: plot + verdict",
            "Genres: comedy, thriller, sci-fi — pick one and defend it",
            "Soundtrack: how music changes a scene",
            "Remakes: necessary or lazy?",
            "Convince me to watch/listen to something",
        ],
        "phrases": [
            ("The plot twist blew my mind.", "Сюжетный поворот поразил меня."),
            ("It's a must-see!", "Это обязательно к просмотру!"),
            ("The acting was superb.", "Актёрская игра была великолепна."),
            ("I'm a big fan of rock music.", "Я большой поклонник рок-музыки."),
            ("That song is stuck in my head.", "Эта песня застряла у меня в голове."),
        ],
        "questions": [
            "What is your all-time favourite film and why?",
            "Who is your favourite actor or singer?",
            "Do you prefer cinemas or streaming at home?",
            "If your life were a film, what genre would it be?",
            "Does music help you concentrate or distract you?",
        ],
    },
    {
        "id": "culture",
        "title": "Culture & Travel Abroad",
        "emoji": "🌍",
        "description": "Культуры, традиции, менталитет, языки",
        "ideas": [
            "Cultural differences you know or have experienced",
            "Etiquette: table manners in different countries",
            "Stereotypes: funny or harmful?",
            "Why learn foreign languages? Your reasons",
            "Introduce your country to a tourist in 5 sentences",
        ],
        "phrases": [
            ("Every culture has its own customs.", "У каждой культуры свои обычаи."),
            ("It's considered rude to...", "Это считается невежливым..."),
            ("When in Rome, do as the Romans do.", "В Риме — как римляне."),
            ("I come from a multicultural background.", "Я из мультикультурной среды."),
            ("Language opens doors.", "Язык открывает двери."),
        ],
        "questions": [
            "What custom from another country do you find fascinating?",
            "Have you ever experienced a culture shock?",
            "How many languages do you speak? Which was hardest?",
            "Is it important to keep traditions alive?",
            "What should foreigners know about your country?",
        ],
    },
    {
        "id": "daily",
        "title": "Daily Routine",
        "emoji": "⏰",
        "description": "Распорядок дня, утро, быт — тема для новичков",
        "ideas": [
            "Describe your day from morning to night",
            "Morning person or night owl? Prove your side",
            "Chores: who cooks, cleans, shops in your home?",
            "Perfect day off: plan it hour by hour",
            "Compare your weekday and weekend routines",
        ],
        "phrases": [
            ("I wake up at seven o'clock.", "Я просыпаюсь в семь часов."),
            ("First thing in the morning, I check my phone.", "Первым делом утром я смотрю телефон."),
            ("I usually grab a coffee on the way.", "Обычно я беру кофе по дороге."),
            ("I stay up late watching series.", "Я сижу допоздна, смотря сериалы."),
            ("It takes me an hour to get to work.", "Дорога до работы занимает час."),
        ],
        "questions": [
            "Walk me through your typical day.",
            "Are you a morning or an evening person?",
            "What household chores do you hate?",
            "What would your perfect day look like?",
            "Has your routine changed recently?",
        ],
    },
    {
        "id": "shopping",
        "title": "Shopping & Money",
        "emoji": "🛒",
        "description": "Магазины, покупки, деньги, шопинг онлайн",
        "ideas": [
            "Buy clothes in a shop: sizes, fitting rooms, returns",
            "Online shopping vs in-store: role-play a complaint",
            "Budgeting: how do you save money?",
            "Impulse buys: tell me about your last one",
            "Bargaining: try to get a discount from me 😉",
        ],
        "phrases": [
            ("How much does it cost?", "Сколько это стоит?"),
            ("Do you accept credit cards?", "Вы принимаете кредитные карты?"),
            ("It's too expensive — have you got anything cheaper?", "Слишком дорого, есть что-то подешевле?"),
            ("I'm just browsing, thanks.", "Я просто смотрю, спасибо."),
            ("Can I get a refund?", "Могут ли мне вернуть деньги?"),
        ],
        "questions": [
            "Do you enjoy shopping or find it tiring?",
            "Are you a saver or a spender?",
            "What was the best purchase you made this year?",
            "Is it easy to return goods in your country?",
            "Would you buy a house or rent? Why?",
        ],
    },
    {
        "id": "education",
        "title": "Education & Learning",
        "emoji": "🎓",
        "description": "Школа, университет, учёба, языки",
        "ideas": [
            "School memories: favourite and worst subjects",
            "How should English be taught better?",
            "University: worth the money? Debate with me",
            "Learning styles: apps, books, teachers, immersion",
            "Teach me something you're good at (in English!)",
        ],
        "phrases": [
            ("I'm studying to become a designer.", "Я учусь, чтобы стать дизайнером."),
            ("I attend evening classes.", "Я хожу на вечерние курсы."),
            ("Could you explain that again, please?", "Не могли бы вы объяснить ещё раз?"),
            ("I'm preparing for an exam.", "Я готовлюсь к экзамену."),
            ("Learning by doing works best for me.", "Мне лучше всего учится на практике."),
        ],
        "questions": [
            "What subject was your favourite at school?",
            "Do you think exams are a fair way to test knowledge?",
            "What is the best way to learn a language?",
            "Would you study abroad? Where?",
            "Is self-education possible without a teacher?",
        ],
    },
]

TOPIC_BY_ID = {t["id"]: t for t in TOPICS}


def topic_idea(topic: dict, index: int) -> str:
    """Вернуть идею темы по индексу (циклически)."""
    return topic["ideas"][index % len(topic["ideas"])]
