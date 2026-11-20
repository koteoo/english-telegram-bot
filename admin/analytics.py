"""Аналитика БД бота для веб-панели.

ВАЖНО: модуль работает с тем же SQLite-файлом, что и бот, но ТОЛЬКО на чтение
(mode=ro) — код бота не изменяется и не запускается отсюда. Все запросы —
обычные SELECT по схеме из db.py (users, cards, stats, plans, usage_counters,
notify_prefs, user_profile).
"""
from __future__ import annotations

import datetime as dt
import os
import sqlite3
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

try:  # единый порог с ботом; fallback на случай запуска без окружения бота
    from config import MASTERED_BOX
except Exception:  # noqa: BLE001
    MASTERED_BOX = 4


def default_db_path() -> str:
    """Путь к БД: env DB_PATH (как у бота), иначе стандартные места."""
    p = os.getenv("DB_PATH", "")
    if p:
        cand = Path(p)
        if not cand.is_absolute():
            cand = BASE_DIR / p
        return str(cand)
    for cand in (BASE_DIR / "db" / "english_bot.db", BASE_DIR / "english_bot.db"):
        if cand.exists():
            return str(cand)
    return str(BASE_DIR / "db" / "english_bot.db")


def _connect(path: str | None = None) -> sqlite3.Connection:
    path = path or default_db_path()
    uri = f"file:{Path(path).as_posix()}?mode=ro&immutable=0"
    conn = sqlite3.connect(uri, uri=True, timeout=5)
    conn.row_factory = sqlite3.Row
    return conn


def _tables(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    return {r["name"] for r in rows}


# ---------------- Сводка ----------------

def overview(path: str | None = None) -> dict:
    now = dt.datetime.now(dt.timezone.utc)
    today = now.strftime("%Y-%m-%d")
    out: dict = {"db_path": path or default_db_path(), "db_exists": False,
                 "generated_at": now.isoformat(timespec="seconds")}
    try:
        conn = _connect(out["db_path"])
    except sqlite3.Error as e:
        out["error"] = f"БД недоступна: {e}"
        return out
    try:
        tb = _tables(conn)
        out["db_exists"] = True
        def q(sql, *args):
            try:
                return [dict(r) for r in conn.execute(sql, args).fetchall()]
            except sqlite3.Error:
                return []

        def one(sql, *args, default=0):
            try:
                r = conn.execute(sql, args).fetchone()
                return r[0] if r and r[0] is not None else default
            except sqlite3.Error:
                return default
            try:
                r = conn.execute(sql, args).fetchone()
                return r[0] if r and r[0] is not None else default
            except sqlite3.Error:
                return default

        out["users_total"] = one("SELECT COUNT(*) FROM users")
        out["users_today"] = one(
            "SELECT COUNT(*) FROM users WHERE substr(created_at,1,10)=?", today)
        out["users_week"] = one(
            "SELECT COUNT(*) FROM users WHERE created_at >= ?",
            (now - dt.timedelta(days=7)).isoformat())
        out["cards_total"] = one("SELECT COUNT(*) FROM cards")
        out["cards_due"] = one("SELECT COUNT(*) FROM cards WHERE next_review <= ?",
                               now.isoformat())
        out["learned_total"] = one("SELECT COUNT(*) FROM cards WHERE box >= ?", MASTERED_BOX)
        out["active_today"] = one(
            "SELECT COUNT(DISTINCT user_id) FROM usage_counters WHERE day=?", today)
        out["active_week"] = one(
            "SELECT COUNT(DISTINCT user_id) FROM usage_counters "
            "WHERE day >= ?", (now - dt.timedelta(days=7)).strftime("%Y-%m-%d"))
        if "plans" in tb:
            out["plans"] = q("SELECT tier, COUNT(*) n FROM plans GROUP BY tier")
            out["paid_users"] = one(
                "SELECT COUNT(*) FROM plans WHERE tier = 'plus'")
        else:
            out["plans"], out["paid_users"] = [], 0
        if "user_profile" in tb:
            out["cefr"] = q("SELECT COALESCE(cefr,'—') k, COUNT(*) n "
                            "FROM user_profile GROUP BY cefr ORDER BY n DESC")
        else:
            out["cefr"] = []
        # уровни
        if "users" in tb:
            out["levels"] = q("SELECT level, COUNT(*) n FROM users GROUP BY level "
                              "ORDER BY n DESC")
        else:
            out["levels"] = []
        # размер БД
        try:
            out["db_size_kb"] = round(os.path.getsize(out["db_path"]) / 1024, 1)
        except OSError:
            out["db_size_kb"] = None
    finally:
        conn.close()
    return out


# ---------------- Графики ----------------

def growth(days: int = 30, path: str | None = None) -> list[dict]:
    """Рост базы и активность по дням."""
    since = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days)) \
        .strftime("%Y-%m-%d")
    conn = _connect(path)
    try:
        rows = conn.execute(
            """SELECT d.day,
                      (SELECT COUNT(*) FROM users u
                        WHERE substr(u.created_at,1,10)=d.day) AS new_users,
                      (SELECT COUNT(DISTINCT uc.user_id) FROM usage_counters uc
                        WHERE uc.day=d.day) AS active
               FROM (SELECT DISTINCT substr(created_at,1,10) AS day FROM users
                     UNION
                     SELECT DISTINCT day FROM usage_counters) d
               WHERE d.day >= ?
               ORDER BY d.day""", (since,)).fetchall()
        return [dict(r) for r in rows]
    except sqlite3.Error:
        return []
    finally:
        conn.close()


def activity(kind: str = "", days: int = 14, path: str | None = None) -> list[dict]:
    """Дневная разбивка счётчиков usage_counters (words/quiz/chat/review/...)."""
    since = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days)) \
        .strftime("%Y-%m-%d")
    sql = ("SELECT day, kind, SUM(used) n FROM usage_counters WHERE day>=?"
           + (" AND kind=?" if kind else "") + " GROUP BY day, kind ORDER BY day")
    args = (since, kind) if kind else (since,)
    conn = _connect(path)
    try:
        return [dict(r) for r in conn.execute(sql, args).fetchall()]
    except sqlite3.Error:
        return []
    finally:
        conn.close()


def top_words(limit: int = 20, path: str | None = None) -> list[dict]:
    conn = _connect(path)
    try:
        return [dict(r) for r in conn.execute(
            f"""SELECT word, COUNT(*) users,
                      AVG(box) avg_box,
                      SUM(CASE WHEN box>={MASTERED_BOX} THEN 1 ELSE 0 END) learned_by
               FROM cards GROUP BY word ORDER BY users DESC LIMIT ?""",
            (limit,)).fetchall()]
    except sqlite3.Error:
        return []
    finally:
        conn.close()


def retention(path: str | None = None) -> list[dict]:
    """Возраст когорт пользователей (дни с регистрации)."""
    conn = _connect(path)
    try:
        return [dict(r) for r in conn.execute(
            """SELECT CAST(julianday('now') - julianday(created_at) AS INT) age,
                      COUNT(*) n FROM users GROUP BY age ORDER BY age LIMIT 90"""
        ).fetchall()]
    except sqlite3.Error:
        return []
    finally:
        conn.close()


# ---------------- Пользователи ----------------

def users_list(q: str = "", plan: str = "", level: str = "", limit: int = 100,
               offset: int = 0, path: str | None = None) -> dict:
    where, args = ["1=1"], []
    if q:
        where.append("(CAST(u.user_id AS TEXT) LIKE ? OR u.username LIKE ?)")
        args += [f"%{q}%", f"%{q}%"]
    if plan:
        where.append("COALESCE(p.tier,'free')=?")
        args.append(plan)
    if level:
        where.append("u.level=?")
        args.append(level)
    w = " AND ".join(where)
    conn = _connect(path)
    try:
        total = conn.execute(
            f"""SELECT COUNT(*) FROM users u LEFT JOIN plans p ON p.user_id=u.user_id
                WHERE {w}""", args).fetchone()[0]
        rows = conn.execute(
            f"""SELECT u.user_id, u.username, u.level, u.created_at,
                       (SELECT COUNT(*) FROM cards lc
                         WHERE lc.user_id=u.user_id AND lc.box >= {MASTERED_BOX}) learned,
                       (SELECT COALESCE(SUM(stars),0) FROM payments pm
                         WHERE pm.user_id=u.user_id) paid_stars,
                       (SELECT COUNT(*) FROM payments pm
                         WHERE pm.user_id=u.user_id) payments_n,
                       COALESCE(s.quiz_best,0) quiz_best,
                       (SELECT COUNT(*) FROM cards c WHERE c.user_id=u.user_id) deck,
                       COALESCE(p.tier,'free') tier, p.expires_at,
                       (SELECT MAX(day) FROM usage_counters uc
                         WHERE uc.user_id=u.user_id) last_active
                FROM users u
                LEFT JOIN stats s ON s.user_id=u.user_id
                LEFT JOIN plans p ON p.user_id=u.user_id
                WHERE {w}
                ORDER BY u.created_at DESC LIMIT ? OFFSET ?""",
            (*args, limit, offset)).fetchall()
        return {"total": total, "items": [dict(r) for r in rows]}
    except sqlite3.Error as e:
        return {"total": 0, "items": [], "error": str(e)}
    finally:
        conn.close()


def user_detail(user_id: int, path: str | None = None) -> dict:
    conn = _connect(path)
    out: dict = {"user_id": user_id}
    try:
        def row(sql, *a):
            try:
                r = conn.execute(sql, a).fetchone()
                return dict(r) if r else None
            except sqlite3.Error:
                return None

        out["user"] = row("SELECT * FROM users WHERE user_id=?", user_id)
        if not out["user"]:
            return out
        out["stats"] = row("SELECT * FROM stats WHERE user_id=?", user_id)
        out["plan"] = row("SELECT * FROM plans WHERE user_id=?", user_id)
        out["profile"] = row("SELECT * FROM user_profile WHERE user_id=?", user_id)
        out["notify"] = row("SELECT * FROM notify_prefs WHERE user_id=?", user_id)
        try:
            out["payments"] = [dict(r) for r in conn.execute(
                "SELECT tier, stars, days, created_at FROM payments "
                "WHERE user_id=? ORDER BY created_at DESC LIMIT 100", (user_id,)).fetchall()]
        except sqlite3.Error:
            out["payments"] = []
        try:
            out["boxes"] = [dict(r) for r in conn.execute(
                "SELECT box, COUNT(*) n FROM cards WHERE user_id=? GROUP BY box "
                "ORDER BY box", (user_id,)).fetchall()]
        except sqlite3.Error:
            out["boxes"] = []
        try:
            out["usage"] = [dict(r) for r in conn.execute(
                """SELECT day,
                          SUM(CASE WHEN kind='words'  THEN used END) words,
                          SUM(CASE WHEN kind='quiz'   THEN used END) quiz,
                          SUM(CASE WHEN kind='chat'   THEN used END) chat,
                          SUM(CASE WHEN kind='review' THEN used END) review
                   FROM usage_counters WHERE user_id=?
                   GROUP BY day ORDER BY day DESC LIMIT 30""", (user_id,)).fetchall()]
        except sqlite3.Error:
            out["usage"] = []
        try:
            out["cards"] = [dict(r) for r in conn.execute(
                """SELECT word, translation, box, next_review FROM cards
                   WHERE user_id=? ORDER BY box DESC, next_review LIMIT 500""",
                (user_id,)).fetchall()]
        except sqlite3.Error:
            out["cards"] = []
        return out
    finally:
        conn.close()


# ---------------- Схема / SQL / дамп ----------------

def schema(path: str | None = None) -> list[dict]:
    conn = _connect(path)
    try:
        tables = conn.execute(
            "SELECT name, sql FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
        out = []
        for t in tables:
            cnt = conn.execute(f'SELECT COUNT(*) FROM "{t["name"]}"').fetchone()[0]
            cols = [dict(r) for r in conn.execute(
                f'PRAGMA table_info("{t["name"]}")').fetchall()]
            out.append({"name": t["name"], "rows": cnt, "sql": t["sql"],
                        "columns": cols})
        return out
    finally:
        conn.close()


ALLOWED_PREFIXES = ("select", "with", "pragma", "explain")


def run_query(sql: str, limit: int = 500, path: str | None = None) -> dict:
    """Только read-only произвольный SQL (подключении в режиме mode=ro)."""
    s = sql.strip().rstrip(";")
    low = s.lower()
    if not low.startswith(ALLOWED_PREFIXES):
        return {"error": "Разрешены только read-only запросы: SELECT / WITH / PRAGMA / EXPLAIN"}
    if ";" in s:
        return {"error": "Один запрос за раз (точка с запятой внутри запрещена)"}
    conn = _connect(path)
    try:
        cur = conn.execute(s)
        cols = [d[0] for d in cur.description] if cur.description else []
        rows = cur.fetchmany(limit)
        return {"columns": cols,
                "rows": [[None if isinstance(v, bytes) else v for v in r] for r in rows],
                "truncated": len(rows) >= limit}
    except sqlite3.Error as e:
        return {"error": str(e)}
    finally:
        conn.close()


def dump_sql(path: str | None = None) -> str:
    """SQL-дамп всей БД (для резервной копии)."""
    conn = _connect(path)
    try:
        return "\n".join(conn.iterdump()) + "\n"
    finally:
        conn.close()


# ---------------- Бизнес-показатели ----------------

def business(path: str | None = None) -> dict:
    """Аудитория, платящие, выручка и подписки. Учебные метрики не считаются."""
    now = dt.datetime.now(dt.timezone.utc)
    today = now.strftime("%Y-%m-%d")
    d7 = (now - dt.timedelta(days=7)).strftime("%Y-%m-%d")
    d30 = (now - dt.timedelta(days=30)).strftime("%Y-%m-%d")
    out: dict = {"generated_at": now.isoformat(timespec="seconds"),
                 "db_path": path or default_db_path()}
    conn = _connect(path)
    try:
        def one(sql, *a, default=0):
            try:
                r = conn.execute(sql, a).fetchone()
                return r[0] if r and r[0] is not None else default
            except sqlite3.Error:
                return default

        def rows(sql, *a):
            try:
                return [dict(r) for r in conn.execute(sql, a).fetchall()]
            except sqlite3.Error:
                return []

        out["users_total"] = one("SELECT COUNT(*) FROM users")
        out["users_today"] = one(
            "SELECT COUNT(*) FROM users WHERE substr(created_at,1,10)=?", today)
        out["users_week"] = one(
            "SELECT COUNT(*) FROM users WHERE substr(created_at,1,10)>=?", d7)
        out["active_today"] = one(
            "SELECT COUNT(DISTINCT user_id) FROM usage_counters WHERE day=?", today)
        out["active_week"] = one(
            "SELECT COUNT(DISTINCT user_id) FROM usage_counters WHERE day>=?", d7)
        out["active_plus"] = one(
            "SELECT COUNT(*) FROM plans WHERE tier = 'plus' "
            "AND (expires_at IS NULL OR expires_at > ?)", now.isoformat())
        out["paying_now"] = one(
            "SELECT COUNT(DISTINCT p.user_id) FROM plans p "
            "JOIN payments pm ON pm.user_id = p.user_id AND pm.tier != 'donate' "
            "WHERE p.tier = 'plus' AND (p.expires_at IS NULL OR p.expires_at > ?)",
            now.isoformat())
        out["granted_plus"] = max(out["active_plus"] - out["paying_now"], 0)
        out["conversion_pct"] = (
            round(100.0 * out["paying_now"] / out["users_total"], 1)
            if out["users_total"] else 0.0)
        out["payments_count"] = one("SELECT COUNT(*) FROM payments")
        out["revenue_total"] = one("SELECT COALESCE(SUM(stars),0) FROM payments")
        out["revenue_today"] = one(
            "SELECT COALESCE(SUM(stars),0) FROM payments WHERE substr(created_at,1,10)=?", today)
        out["revenue_30d"] = one(
            "SELECT COALESCE(SUM(stars),0) FROM payments WHERE substr(created_at,1,10)>=?", d30)
        out["revenue_subs"] = one(
            "SELECT COALESCE(SUM(stars),0) FROM payments WHERE tier != 'donate'")
        out["revenue_donations"] = one(
            "SELECT COALESCE(SUM(stars),0) FROM payments WHERE tier = 'donate'")
        out["donations_count"] = one("SELECT COUNT(*) FROM payments WHERE tier = 'donate'")
        out["avg_check"] = (round(out["revenue_total"] / out["payments_count"], 1)
                            if out["payments_count"] else 0)
        payers = one("SELECT COUNT(DISTINCT user_id) FROM payments")
        out["payers_ever"] = payers
        out["arpu"] = round(out["revenue_total"] / payers, 1) if payers else 0
        out["accounting_since"] = one("SELECT MIN(created_at) FROM payments", default=None)
        out["plans"] = rows(
            "SELECT COALESCE(p.tier,'free') tier, COUNT(*) n FROM users u "
            "LEFT JOIN plans p ON p.user_id=u.user_id GROUP BY tier ORDER BY n DESC")
        out["revenue_by_tier"] = rows(
            "SELECT tier, SUM(stars) stars, COUNT(*) n FROM payments "
            "GROUP BY tier ORDER BY stars DESC")
        out["expiring"] = rows(
            "SELECT user_id, tier, expires_at FROM plans "
            "WHERE tier = 'plus' AND expires_at IS NOT NULL "
            "AND expires_at > ? AND expires_at <= ? ORDER BY expires_at",
            now.isoformat(), (now + dt.timedelta(days=7)).isoformat())
        out["daily"] = rows(
            "SELECT substr(created_at,1,10) day, SUM(stars) stars, COUNT(*) n "
            "FROM payments WHERE substr(created_at,1,10)>=? GROUP BY day ORDER BY day", d30)
        try:
            out["db_size_kb"] = round(os.path.getsize(out["db_path"]) / 1024, 1)
        except OSError:
            out["db_size_kb"] = None
    finally:
        conn.close()
    return out
