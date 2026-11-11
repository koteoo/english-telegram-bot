import re
import json
from pathlib import Path
from collections import defaultdict
import pymorphy3

MORPH = pymorphy3.MorphAnalyzer()

def normalize_ru(word):
    word = word.lower().strip()
    if not word or len(word) < 2:
        return ''
    parsed = MORPH.parse(word)
    if parsed:
        lemma = parsed[0].normal_form
        if re.match(r'^[а-яёa-z\-]+$', lemma):
            return lemma
    return ''

def is_valid_en_word(word):
    word = word.lower().strip()
    if not re.match(r"^[a-z][a-z'’\-]{0,63}$", word):
        return False
    return True

raw_path = Path('/opt/english-bot/data/dicts/mueller-base.raw')
if not raw_path.exists():
    raise SystemExit('mueller-base.raw not found')

print('Loading Mueller dictionary...')
raw = raw_path.read_text(encoding='utf-8', errors='replace')
blocks = re.split(r'^_{3,}\s*$', raw, flags=re.M)

# Регулярки для очистки
phonetic_re = re.compile(r'\[[^\]]*\]')
paren_re = re.compile(r'\([^)]*\)')
marker_re = re.compile(r'(?:^|\s)_[A-Za-zА-Яа-яЁё]+\.?(?=\s|$)')
numbering_re = re.compile(r'^\d+[.)]\s*')

en_to_rus_ordered = {}

for block in blocks:
    lines = [ln.strip() for ln in block.splitlines() if ln.strip()]
    if len(lines) < 2:
        continue

    head = lines[0].strip()
    definition = ' '.join(lines[1:])

    if not is_valid_en_word(head):
        continue
    en = head.lower()

    def_clean = phonetic_re.sub(' ', definition)
    def_clean = paren_re.sub(' ', def_clean)
    def_clean = marker_re.sub(' ', def_clean)
    def_clean = marker_re.sub(' ', def_clean)

    main_part, _, example_part = def_clean.partition(':')
    target_text = main_part if re.search(r'[А-Яа-яЁё]', main_part) else example_part

    raw_meanings = re.split(r'[;,]', target_text)
    valid_meanings = []

    for m in raw_meanings:
        m = m.strip()
        if not m:
            continue
        m = numbering_re.sub('', m).strip()
        m = re.sub(r'\s+', ' ', m)
        m = re.sub(r'^[\W_]+|[\W_]+$', '', m)

        words_in_m = m.split()
        if len(words_in_m) == 0 or len(words_in_m) > 3:
            continue

        has_cyr = bool(re.search(r'[А-Яа-яЁё]', m))
        cyr_count = len(re.findall(r'[А-Яа-яЁё]', m))
        lat_count = len(re.findall(r'[A-Za-z]', m))

        if lat_count > 0 and cyr_count < lat_count * 2:
            continue
        if not has_cyr:
            continue

        valid_meanings.append(m.lower())

    if valid_meanings:
        en_to_rus_ordered.setdefault(en, []).extend(valid_meanings)

print(f'Collected unique English words: {len(en_to_rus_ordered)}')

# Инвертируем в RU -> EN с нормализацией
rus_normalized_to_en_candidates = defaultdict(set)

for en, rus_list in en_to_rus_ordered.items():
    for ru_phrase in rus_list:
        words = ru_phrase.split()
        normalized_words = []
        for w in words:
            norm_w = normalize_ru(w)
            if norm_w:
                normalized_words.append(norm_w)
        
        if not normalized_words:
            continue
            
        norm_ru_phrase = ' '.join(normalized_words)
        rus_normalized_to_en_candidates[norm_ru_phrase].add(en)

final_ru_norm_to_en = {}

# Создаем карту приоритетов: какое место занимает русское слово в списке значений для данного EN
en_priority_map = {}
for en, rus_list in en_to_rus_ordered.items():
    for idx, ru in enumerate(rus_list):
        # Нормализуем ру для сопоставления с ключами в rus_normalized_to_en_candidates
        words = ru.split()
        normalized_words = []
        for w in words:
            norm_w = normalize_ru(w)
            if norm_w:
                normalized_words.append(norm_w)
        if not normalized_words:
            continue
        norm_ru_phrase = ' '.join(normalized_words)
        
        # Сохраняем индекс появления этого RU значения для конкретного EN
        # Чем меньше индекс, тем выше приоритет (это первое значение в статье)
        current_min_idx = en_priority_map.get((norm_ru_phrase, en), float('inf'))
        if idx < current_min_idx:
            en_priority_map[(norm_ru_phrase, en)] = idx

for ru_norm, ens in rus_normalized_to_en_candidates.items():
    best_en = None
    min_priority = float('inf')
    
    for en in ens:
        priority = en_priority_map.get((ru_norm, en), float('inf'))
        # Если приоритеты равны, выбираем более короткое слово или лексикографически меньшее
        if priority < min_priority or (priority == min_priority and (best_en is None or len(en) < len(best_en))):
            min_priority = priority
            best_en = en
            
    if best_en:
        final_ru_norm_to_en[ru_norm] = best_en

print(f'Final RU->EN pairs: {len(final_ru_norm_to_en)}')

# Тестирование
test_words = ['тяжелая', 'дома', 'книги', 'друг', 'вода', 'семья']
print('\n=== Test normalization ===')
for w in test_words:
    norm_user = normalize_ru(w)
    en = final_ru_norm_to_en.get(norm_user, 'NOT FOUND')
    print(f'{w} -> (norm: {norm_user}) -> {en}')

# Сохраняем результат
output_path = Path('/opt/english-bot/db/ruendict.json')
output_path.parent.mkdir(parents=True, exist_ok=True)

json_data = final_ru_norm_to_en
output_path.write_text(
    json.dumps(json_data, ensure_ascii=False, separators=(',', ':')),
    encoding='utf-8'
)

size_mb = output_path.stat().st_size / (1024 * 1024)
print(f'\nSaved to: {output_path}')
print(f'Size: {size_mb:.2f} MB')
