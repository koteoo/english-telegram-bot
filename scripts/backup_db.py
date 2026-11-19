#!/usr/bin/env python3
"""Снимок базы через VACUUM INTO — безопасно на работающем боте, без блокировок."""
import sqlite3
from datetime import datetime
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
env = {}
for line in (BASE / ".env").read_text(encoding="utf-8").splitlines():
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip().strip('"').strip("'")

db = BASE / env.get("DB_PATH", "english_bot.db")
out = BASE / "backups"
out.mkdir(exist_ok=True)
target = out / f"english_bot_{datetime.now():%Y-%m-%d_%H%M}.db"

con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
con.execute("VACUUM INTO ?", (str(target),))
con.close()

chk = sqlite3.connect(target)
cards = chk.execute("SELECT COUNT(*) FROM cards").fetchone()[0]
users = chk.execute("SELECT COUNT(*) FROM users").fetchone()[0]
chk.close()

for old in sorted(out.glob("english_bot_*.db"))[:-14]:
    old.unlink()

kept = len(list(out.glob("english_bot_*.db")))
print(f"OK {target.name}: {target.stat().st_size/1024:.0f} KB, cards={cards}, users={users}, copies={kept}")
