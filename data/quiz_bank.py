"""Банк грамматических вопросов квиза по уровням.

Формат записи: (предложение с ___, перевод, ВЕРНЫЙ ответ, типичная ошибка).
Порядок A/B назначается детерминированно по хешу предложения,
поэтому ключ верен по построению и стабилен между перезапусками.
"""
import hashlib

BEGINNER = [
    ("She ___ a teacher.", "Она учительница.", "is", "are"),
    ("I ___ two brothers.", "У меня два брата.", "have", "has"),
    ("There ___ many books on the shelf.", "На полке много книг.", "are", "is"),
    ("He ___ to school every day.", "Он ходит в школу каждый день.", "goes", "go"),
    ("Look! It ___.", "Смотри! Идёт дождь.", "is raining", "rains"),
    ("I saw ___ elephant at the zoo.", "Я видел слона в зоопарке.", "an", "a"),
    ("These ___ my friends.", "Это мои друзья.", "are", "is"),
    ("How ___ apples do you need?", "Сколько яблок тебе нужно?", "many", "much"),
    ("How ___ water do you drink?", "Сколько воды ты пьёшь?", "much", "many"),
    ("Yesterday I ___ a film.", "Вчера я посмотрел фильм.", "watched", "watch"),
    ("She ___ like coffee.", "Она не любит кофе.", "doesn't", "don't"),
    ("___ you speak English?", "Ты говоришь по-английски?", "Do", "Does"),
    ("The cat is ___ the table.", "Кот под столом.", "under", "on"),
    ("I get up ___ seven o'clock.", "Я встаю в семь часов.", "at", "on"),
    ("My birthday is ___ May.", "Мой день рождения в мае.", "in", "on"),
    ("We went there ___ Monday.", "Мы ходили туда в понедельник.", "on", "in"),
    ("This is ___ book.", "Это моя книга.", "my", "mine"),
    ("The plural of 'child' is ___.", "Множественное число от child.", "children", "childs"),
    ("I have three ___.", "У меня три коробки.", "boxes", "boxs"),
    ("She can ___ very well.", "Она умеет хорошо петь.", "sing", "sings"),
    ("___ is your name?", "Как тебя зовут?", "What", "How"),
    ("They ___ at home last night.", "Вчера вечером они были дома.", "were", "was"),
    ("I ___ hungry now.", "Я сейчас голоден.", "am", "is"),
    ("He didn't ___ the answer.", "Он не знал ответа.", "know", "knew"),
    ("There isn't ___ milk in the fridge.", "В холодильнике нет молока.", "any", "some"),
    ("This bag is ___ than that one.", "Эта сумка тяжелее той.", "heavier", "more heavy"),
    ("I ___ my homework yesterday.", "Я сделал домашнюю работу вчера.", "did", "done"),
    ("We ___ TV when he came.", "Мы смотрели телевизор, когда он пришёл.", "were watching", "watched"),
    ("___ apple a day is good for you.", "Одно яблоко в день полезно.", "An", "A"),
    ("She ___ got a new phone.", "У неё новый телефон.", "has", "have"),
]

INTERMEDIATE = [
    ("I ___ here since 2015.", "Я здесь с 2015 года.", "have lived", "live"),
    ("She ___ to Paris last year.", "Она ездила в Париж в прошлом году.", "went", "has gone"),
    ("If it rains, we ___ at home.", "Если пойдёт дождь, останемся дома.", "will stay", "would stay"),
    ("If I ___ you, I would apologise.", "На твоём месте я бы извинился.", "were", "was"),
    ("This is the ___ film I've ever seen.", "Это лучший фильм, что я видел.", "best", "better"),
    ("The letter ___ yesterday.", "Письмо отправили вчера.", "was sent", "was send"),
    ("I enjoy ___ books.", "Мне нравится читать книги.", "reading", "read"),
    ("She decided ___ abroad.", "Она решила учиться за границей.", "to study", "study"),
    ("You ___ smoke here — it's forbidden.", "Здесь нельзя курить.", "mustn't", "don't have to"),
    ("I've been working here ___ five years.", "Я работаю здесь пять лет.", "for", "since"),
    ("He said he ___ tired.", "Он сказал, что устал.", "was", "is"),
    ("I ___ get up early, but now I don't.", "Раньше я вставал рано, а теперь нет.", "used to", "use to"),
    ("The man ___ lives next door is a doctor.", "Мужчина, который живёт рядом, врач.", "who", "which"),
    ("There's ___ traffic today.", "Сегодня мало машин.", "little", "few"),
    ("Only a ___ people came.", "Пришло мало людей.", "few", "little"),
    ("She's ___ than her sister.", "Она внимательнее сестры.", "more careful", "carefuller"),
    ("She avoided ___ the question.", "Она избегала ответа на вопрос.", "answering", "to answer"),
    ("By the time we arrived, the film ___.", "К нашему приходу фильм начался.", "had started", "started"),
    ("You ___ tell anyone — it's a secret.", "Не говори никому, это секрет.", "mustn't", "needn't"),
    ("I'm not used to ___ so early.", "Я не привык вставать так рано.", "getting up", "get up"),
    ("He asked me where I ___.", "Он спросил, где я живу.", "lived", "live"),
    ("This house ___ in 1900.", "Этот дом построили в 1900 году.", "was built", "built"),
    ("She has ___ finished her work.", "Она только что закончила работу.", "just", "yet"),
    ("I haven't finished ___.", "Я ещё не закончил.", "yet", "already"),
    ("I'd rather ___ at home tonight.", "Я бы предпочёл остаться дома.", "stay", "to stay"),
    ("Each of the students ___ a book.", "У каждого студента есть книга.", "has", "have"),
    ("The news ___ surprising.", "Новости удивительные.", "was", "were"),
    ("He stopped ___ two years ago.", "Он бросил курить два года назад.", "smoking", "to smoke"),
    ("I'll call you as soon as I ___.", "Позвоню, как только приеду.", "arrive", "will arrive"),
    ("She speaks English ___ than I do.", "Она говорит по-английски свободнее меня.", "more fluently", "fluenter"),
]

ADVANCED = [
    ("If I ___ harder, I would have passed.", "Если бы я старался больше, я бы сдал.", "had studied", "studied"),
    ("Had I known, I ___ you.", "Знай я раньше, я бы помог тебе.", "would have helped", "would help"),
    ("Not only ___ late, but he also forgot the keys.", "Он не только опоздал, но и забыл ключи.", "was he", "he was"),
    ("I wish I ___ that yesterday.", "Жаль, что я сказал это вчера.", "hadn't said", "didn't say"),
    ("You ___ have told me earlier!", "Ты мог бы сказать мне раньше!", "could", "should"),
    ("She ___ have left already — her car is gone.", "Должно быть, она уже уехала.", "must", "should"),
    ("He ___ have seen me — I was hidden.", "Он не мог меня видеть.", "can't", "mustn't"),
    ("I had my car ___ yesterday.", "Мне починили машину вчера.", "repaired", "repair"),
    ("___ the rain, the match continued.", "Несмотря на дождь, матч продолжался.", "Despite", "Although"),
    ("___ it was raining, the match continued.", "Хотя шёл дождь, матч продолжался.", "Although", "Despite"),
    ("The committee insisted that he ___ present.", "Комитет настоял, чтобы он присутствовал.", "be", "is"),
    ("Scarcely ___ the door when the phone rang.", "Едва я открыл дверь, как зазвонил телефон.", "had I opened", "I had opened"),
    ("It's high time you ___ a decision.", "Давно пора принять решение.", "made", "make"),
    ("___ having studied for hours, he failed.", "Несмотря на многочасовую подготовку, он провалился.", "Despite", "However"),
    ("The results, ___ were published yesterday, surprised everyone.", "Результаты, опубликованные вчера, всех удивили.", "which", "that"),
    ("He is said ___ a fortune.", "Говорят, он сколотил состояние.", "to have made", "to make"),
    ("I'd sooner you ___ me the truth.", "Я бы предпочёл, чтобы ты сказал правду.", "told", "tell"),
    ("No sooner had he arrived ___ it started to rain.", "Едва он приехал, как пошёл дождь.", "than", "when"),
    ("She objected to ___ treated like a child.", "Она возражала, когда с ней обращались как с ребёнком.", "being", "be"),
    ("Little ___ that he was being watched.", "Он и не подозревал, что за ним следят.", "did he know", "he knew"),
    ("The proposal is worth ___.", "Это предложение стоит рассмотреть.", "considering", "to consider"),
    ("Had it not been for your help, I ___ failed.", "Если бы не твоя помощь, я бы провалился.", "would have", "would had"),
    ("He denied ___ the money.", "Он отрицал, что взял деньги.", "having taken", "to take"),
    ("By next June I ___ here for ten years.", "К следующему июню я буду работать здесь десять лет.", "will have been working", "will work"),
    ("The more you practise, the ___ you become.", "Чем больше практикуешься, тем лучше становишься.", "better", "more good"),
    ("Hardly anyone ___ to the invitation.", "Почти никто не ответил на приглашение.", "responded", "were responding"),
    ("She would rather ___ than apologise.", "Она скорее уйдёт, чем извинится.", "leave", "to leave"),
    ("Not until midnight ___ to sleep.", "Только в полночь он лёг спать.", "did he go", "he went"),
    ("The book, ___ author is unknown, became a bestseller.", "Книга, автор которой неизвестен, стала бестселлером.", "whose", "which"),
    ("I regret ___ you that your application was rejected.", "С сожалением сообщаю, что заявка отклонена.", "to inform", "informing"),
]


def _build(items):
    # Детерминированный порядок по хешу, затем чередование A/B:
    # ключи сбалансированы поровну и стабильны между перезапусками.
    order = sorted(items, key=lambda it: hashlib.md5(it[0].encode("utf-8")).hexdigest())
    key_of = {it[0]: ("A" if i % 2 == 0 else "B") for i, it in enumerate(order)}
    out = []
    for s, ru, ok, bad in items:
        if key_of[s] == "A":
            out.append((s, ru, ok, bad, "A"))
        else:
            out.append((s, ru, bad, ok, "B"))
    return out


QUIZ_BY_LEVEL = {
    "beginner": _build(BEGINNER),
    "intermediate": _build(INTERMEDIATE),
    "advanced": _build(ADVANCED),
}
