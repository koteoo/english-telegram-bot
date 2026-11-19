"""Определение уровня CEFR: банк вопросов и лестничная оценка.

Вопросы идут по ступеням A1..C2. Оценка поднимается вверх, пока на ступени
верно не меньше половины ответов; на первом провале останавливается.
"""
from __future__ import annotations

CEFR = ["A1", "A2", "B1", "B2", "C1", "C2"]

# (ступень, вопрос, варианты, индекс верного)
QUESTIONS: list[tuple[str, str, list[str], int]] = [
    ("A1", "She ___ a teacher.", ["is", "are", "am", "be"], 0),
    ("A1", "I ___ two brothers.", ["have", "has", "am", "having"], 0),
    ("A1", "___ you like coffee?", ["Do", "Does", "Are", "Is"], 0),
    ("A2", "Yesterday I ___ to the cinema.", ["went", "go", "gone", "going"], 0),
    ("A2", "This book is ___ than that one.", ["more interesting", "interestinger", "most interesting", "the most interesting"], 0),
    ("A2", "There isn't ___ milk in the fridge.", ["much", "many", "a few", "few"], 0),
    ("B1", "I've lived here ___ 2015.", ["since", "for", "from", "during"], 0),
    ("B1", "If it rains, we ___ at home.", ["will stay", "stay", "would stay", "stayed"], 0),
    ("B1", "She asked me where I ___.", ["lived", "live", "am living", "have lived"], 0),
    ("B1", "You ___ smoke here — it's forbidden.", ["mustn't", "don't have to", "needn't", "shouldn't have"], 0),
    ("B2", "By the time we arrived, the film ___.", ["had already started", "already started", "has already started", "was already starting"], 0),
    ("B2", "I wish I ___ more time to travel.", ["had", "have", "will have", "would have"], 0),
    ("B2", "The report ___ by the manager yesterday.", ["was written", "wrote", "has written", "is writing"], 0),
    ("B2", "He's used to ___ early.", ["getting up", "get up", "got up", "be getting up"], 0),
    ("C1", "Hardly ___ the door when the phone rang.", ["had I opened", "I had opened", "did I open", "I opened"], 0),
    ("C1", "The proposal was rejected ___ its cost.", ["on the grounds of", "in spite", "due", "because"], 0),
    ("C1", "She would rather we ___ earlier.", ["arrived", "arrive", "will arrive", "would arrive"], 0),
    ("C2", "His argument, ___ persuasive, was ultimately unconvincing.", ["albeit", "despite", "although of", "however"], 0),
    ("C2", "Such was the ___ of the evidence that the case was dismissed.", ["paucity", "plethora", "abundance", "surplus"], 0),
    ("C2", "The findings ___ the earlier assumption.", ["belie", "believe", "belies of", "are belie"], 0),
]

QUICK = [0, 3, 6, 8, 10, 12, 14, 17]      # 8 вопросов, по ступеням
FULL = list(range(len(QUESTIONS)))         # 20 вопросов

TO_INTERNAL = {"A1": "beginner", "A2": "beginner",
               "B1": "intermediate", "B2": "intermediate",
               "C1": "advanced", "C2": "advanced"}


def options_shuffled(q_index: int, seed: int) -> tuple[list[str], int]:
    """Варианты в перемешанном виде + новый индекс верного (чтобы не всегда первый)."""
    import random
    level, text, opts, correct = QUESTIONS[q_index]
    order = list(range(len(opts)))
    random.Random(seed + q_index).shuffle(order)
    new_opts = [opts[i] for i in order]
    return new_opts, order.index(correct)


def score(answers: list[tuple[str, bool]]) -> str:
    """answers: [(ступень, верно)]. Возвращает достигнутую ступень CEFR."""
    reached = "A1"
    for lvl in CEFR:
        rows = [ok for l, ok in answers if l == lvl]
        if not rows:
            continue
        if sum(rows) / len(rows) >= 0.5:
            reached = lvl
        else:
            break
    return reached
