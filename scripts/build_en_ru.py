import re, json
from pathlib import Path
from collections import defaultdict

raw = Path("/opt/english-bot/data/dicts/mueller-base.raw").read_text(encoding="utf-8", errors="replace")
blocks = re.split(r"^_{3,}\s*$", raw, flags=re.M)

phonetic_re = re.compile(r"\[[^\]]*\]")
paren_re = re.compile(r"\([^)]*\)")
marker_re = re.compile(r"(?:^|\s)_[A-Za-zА-Яа-яЁё]+\.?(?=\s|$)")
numbering_re = re.compile(r"^\d+[.)]\s*")

en_to_rus_list = defaultdict(list)

for block in blocks:
    lines = [ln.strip() for ln in block.splitlines() if ln.strip()]
    if len(lines) < 2: continue
    
    head = lines[0].strip().lower()
    if not re.match(r"^[a-z][a-z'’\-]{0,63}$", head): continue
    
    definition = " ".join(lines[1:])
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
        if not m: continue
        
        m = numbering_re.sub('', m).strip()
        m = re.sub(r'\s+', ' ', m)
        m = re.sub(r'^[\W_]+|[\W_]+$', '', m)
        
        words_in_m = m.split()
        if len(words_in_m) == 0 or len(words_in_m) > 4: continue
        
        has_cyr = bool(re.search(r'[А-Яа-яЁё]', m))
        if not has_cyr: continue
        
        cyr_count = len(re.findall(r'[А-Яа-яЁё]', m))
        lat_count = len(re.findall(r'[A-Za-z]', m))
        
        if lat_count > 0 and cyr_count < lat_count: continue
            
        valid_meanings.append(m.lower())

    if valid_meanings:
        unique_vals = list(dict.fromkeys(valid_meanings))[:5]
        en_to_rus_list[head].extend(unique_vals)

output_path = Path("/opt/english-bot/data/en_ru_full.json")
output_path.parent.mkdir(parents=True, exist_ok=True)
json_data = {k: v for k, v in en_to_rus_list.items()}
output_path.write_text(json.dumps(json_data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
print(f"Saved {len(json_data)} words to {output_path}")
