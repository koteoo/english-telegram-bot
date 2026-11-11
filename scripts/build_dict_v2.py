import re
import json
from pathlib import Path
from collections import defaultdict
import pymorphy3

MORPH = pymorphy3.MorphAnalyzer()

def normalize_ru(word):
    word = word.lower().strip()
    word = re.sub(r'^[\W_]+|[\W_]+$', '', word)
    if not word or len(word) < 2:
        return ""
    
    parsed = MORPH.parse(word)
    if parsed:
        lemma = parsed[0].normal_form
        if re.match(r'^[а-яёa-z\-]+$', lemma):
            return lemma
    return ""

def is_valid_en_word(word):
    word = word.lower().strip()
    if not re.match(r"^[a-z][a-z'’\-]{0,63}$", word):
        return False
    if len(word) > 64:
        return False
    return True

raw_path = Path("/opt/english-bot/data/dicts/mueller-base.raw")
if not raw_path.exists():
    raise SystemExit("mueller-base.raw not found")

print("Loading Mueller dictionary...")
raw = raw_path.read_text(encoding="utf-8", errors="replace")
blocks = re.split(r"^_{3,}\s*$", raw, flags=re.M)

phonetic_re = re.compile(r"\[[^\]]*\]")
paren_re = re.compile(r"\([^)]*\)")
marker_re = re.compile(r"(?:^|\s)_[A-Za-zА-Яа-яЁё]+\.?(?=\s|$)")
numbering_re = re.compile(r"^\d+[.)]\s*")

en_to_rus_ordered = {} 

for block in blocks:
    lines = [ln.strip() for ln in block.splitlines() if ln.strip()]
    if len(lines) < 2:
        continue

    head = lines[0].strip()
    definition = " ".join(lines[1:])

    if not is_valid_en_word(head):
        continue
    
    en = head.lower()

    def_clean = phonetic_re.sub(" ", definition)
    def_clean = paren_re.sub(" ", def_clean)
    def_clean = marker_re.sub(" ", def_clean)
    def_clean = marker_re.sub(" ", def_clean)
    
    main_part, _, example_part = def_clean.partition(":")
    target_text = main_part if re.search(r"[А-Яа-яЁё]", main_part) else example_part
    
    raw_meanings = re.split(r"[;,]", target_text)
    
    valid_meanings = []
    for m in raw_meanings:
        m = m.strip()
        if not m:
            continue
        
        m = numbering_re.sub("", m).strip()
        m = re.sub(r'\s+', ' ', m)
        m = re.sub(r'^[\W_]+|[\W_]+$', '', m)
        
        words_in_m = m.split()
        if len(words_in_m) == 0 or len(words_in_m) > 3:
            continue
            
        has_cyr = bool(re.search(r"[А-Яа-яЁё]", m))
        cyr_count = len(re.findall(r"[А-Яа-яЁё]", m))
        lat_count = len(re.findall(r"[A-Za-z]", m))
        
        if lat_count > 0 and cyr_count < lat_count * 2:
            continue
            
        if not has_cyr:
            continue
            
        valid_meanings.append(m.lower())

    if valid_meanings:
        en_to_rus_ordered.setdefault(en, []).extend(valid_meanings)

print(f"Collected unique English words: {len(en_to_rus_ordered)}")
