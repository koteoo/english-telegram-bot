import re
import json
from pathlib import Path
from collections import defaultdict
import pymorphy3

MORPH = pymorphy3.MorphAnalyzer()

def normalize_ru(word):
    parsed = MORPH.parse(word.lower().strip())
    return parsed[0].normal_form if parsed else word.lower().strip()

raw_path = Path("/opt/english-bot/data/dicts/mueller-base.raw")
if not raw_path.exists():
    raise SystemExit("mueller-base.raw not found")

raw = raw_path.read_text(encoding="utf-8", errors="replace")
blocks = re.split(r"^_{3,}\s*$", raw, flags=re.M)

head_re = re.compile(r"^[A-Za-z][A-Za-z''\-]{0,63}$")
cyr_re = re.compile(r"[А-Яа-яЁё]")
latin_re = re.compile(r"[A-Za-z]")
phonetic_re = re.compile(r"\[[^\]]*\]")
paren_re = re.compile(r"\([^)]*\)")
marker_re = re.compile(r"(?:^|\s)_[A-Za-zА-Яа-яЁё]+\.?(?=\s|$)")

def clean_text(s):
    s = str(s or "").strip()
    s = re.sub(r"\s+", " ", s)

def has_cyr(s):
    return bool(cyr_re.search(s or ""))

en_to_rus_ordered = {} 

for block in blocks:
    lines = [ln.strip() for ln in block.splitlines() if ln.strip()]
    if len(lines) < 2:
        continue

    head = clean_text(lines[0])
    definition = " ".join(lines[1:])

    if not head_re.match(head):
        continue
    
    definition = phonetic_re.sub(" ", definition)
    definition = paren_re.sub(" ", definition)
    definition = marker_re.sub(" ", definition)
    definition = marker_re.sub(" ", definition)
    
    main_part, sep, example_part = definition.partition(":")
    target_text = main_part if has_cyr(main_part) else example_part
    
    raw_meanings = re.split(r"[;,]", target_text)
    meanings = []
    
    for m in raw_meanings:
        m = clean_text(m)
        if not m or not has_cyr(m):
            continue
        
        latin_count = len(latin_re.findall(m))
        cyr_count = len(cyr_re.findall(m))
        if latin_count > max(3, cyr_count // 2):
            continue
            
        m_clean = re.sub(r"^\d+[.)]\s*", "", m).strip()
        
        if len(m_clean) >= 2 and len(m_clean) <= 50:
            meanings.append(m_clean.lower())

    if meanings:
        en = head.lower()
        en_to_rus_ordered.setdefault(en, []).extend(meanings)

print(f"Sobrano angliyskih slov: {len(en_to_rus_ordered)}")

rus_normalized_to_en_candidates = defaultdict(set)

for en, rus_list in en_to_rus_ordered.items():
    for ru in rus_list:
        norm_ru = normalize_ru(ru)
        if norm_ru:
            rus_normalized_to_en_candidates[norm_ru].add(en)

final_ru_norm_to_en = {}
for ru_norm, ens in rus_normalized_to_en_candidates.items():
    sorted_ens = sorted(ens, key=lambda x: (len(x), '-' in x, "'" in x))
    final_ru_norm_to_en[ru_norm] = sorted_ens[0]

print(f"Final RU->EN pairs: {len(final_ru_norm_to_en)}")

test_words = ["тяжелая", "дома", "книги", "друг", "вода"]
print("
=== Test normalization ===")
for w in test_words:
    norm = normalize_ru(w)
    en = final_ru_norm_to_en.get(norm, "NOT FOUND")
    print(f"{w} -> (norm: {norm}) -> {en}")

output_path = Path("/opt/english-bot/db/ruendict.json")
output_path.parent.mkdir(parents=True, exist_ok=True)

json_data = final_ru_norm_to_en
output_path.write_text(
    json.dumps(json_data, ensure_ascii=False, separators=(",", ":")),
    encoding="utf-8"
)

size_mb = output_path.stat().st_size / (1024 * 1024)
print(f"
Saved to: {output_path}")
print(f"Size: {size_mb:.2f} MB")
