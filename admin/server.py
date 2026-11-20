#!/usr/bin/env python3
"""Веб-панель мониторинга бота (отдельный сервис, код бота не трогает).

Запуск (внутри LXC-контейнера или где угодно рядом с проектом):
    python3 admin/server.py [--port 8080] [--host 0.0.0.0]

Переменные окружения:
    ADMIN_USER / ADMIN_PASSWORD  — вход (по умолчанию admin / changeme)
    ADMIN_TOKEN                  — токен для API-запросов (?token=... / Bearer)
                                   (по умолчанию = ADMIN_PASSWORD)
    DB_PATH                      — путь к БД бота (как у самого бота)
    BOT_SERVICE                  — имя systemd-юнита бота (english-bot)
    PROJECT_DIR                  — папка проекта (для редактора кода; только чтение,
                                   если PROJECT_WRITE != on)
    PROJECT_WRITE                — on|off: разрешить ли сохранение файлов из панели
    JOURNAL_CMD                  — команда чтения логов (по умолчанию journalctl -u …)

Без внешних зависимостей — только стандартная библиотека Python.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import hmac
import http.cookies
import json
import os
import re
import secrets
import subprocess
import sys
import threading
import time
from pathlib import Path
from urllib.parse import parse_qs, urlparse

# делаем импорты модуля аналитики возможными при запуске из любой папки
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from admin import analytics  # noqa: E402

try:
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
except ImportError:  # pragma: no cover
    from http.server import BaseHTTPRequestHandler, HTTPServer as ThreadingHTTPServer

ADMIN_USER = os.getenv("ADMIN_USER", "admin")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "changeme")
API_TOKEN = os.getenv("ADMIN_TOKEN", ADMIN_PASSWORD)
BOT_SERVICE = os.getenv("BOT_SERVICE", "english-bot")
PROJECT_WRITE = os.getenv("PROJECT_WRITE", "off").lower() in ("1", "on", "true", "yes")
JOURNAL_CMD = os.getenv("JOURNAL_CMD", f"journalctl -u {BOT_SERVICE} --no-pager -n 500")
SESSIONS: dict[str, float] = {}
SESSION_TTL = 12 * 3600

CODE_EXTS = {".py", ".txt", ".md", ".sh", ".service", ".yml", ".yaml", ".json",
             ".env.example", ".cfg", ".ini", ".toml"}
EDITABLE_ROOT = BASE_DIR
SKIP_DIRS = {".git", "__pycache__", "venv", "node_modules", "models_cache",
             "ollama_models", "db", ".idea", ".vscode"}


# ---------------- helpers ----------------

def _systemd(action: str) -> dict:
    """Действие над systemd-сервисом бота (status/restart/stop/start)."""
    if action == "status":
        cmd = ["systemctl", "is-active", BOT_SERVICE]
    else:
        cmd = ["systemctl", action, BOT_SERVICE]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        return {"ok": p.returncode == 0, "out": (p.stdout + p.stderr).strip(),
                "value": p.stdout.strip()}
    except FileNotFoundError:
        return {"ok": False, "out": "systemctl недоступен (не systemd?)", "value": "?"}
    except subprocess.TimeoutExpired:
        return {"ok": False, "out": "timeout", "value": "?"}


def bot_status() -> dict:
    st = _systemd("status")
    state = st.get("value", "?")
    up = state == "active"
    out = {"bot_service": BOT_SERVICE, "bot_state": state, "bot_up": up}
    # время работы и потребление — через systemctl show
    try:
        p = subprocess.run(["systemctl", "show", BOT_SERVICE,
                            "--property=ActiveEnterTimestamp,MainPID,MemoryCurrent",
                            "--value"], capture_output=True, text=True, timeout=10)
        lines = p.stdout.strip().splitlines()
        if len(lines) >= 1:
            out["since"] = lines[0]
        if len(lines) >= 3:
            mem = lines[2].strip()
            if mem.isdigit():
                out["mem_mb"] = round(int(mem) / 1024 / 1024, 1)
    except Exception:
        pass
    # health Telegram API
    try:
        import urllib.request
        tok = ""
        envf = EDITABLE_ROOT / ".env"
        if envf.exists():
            m = re.search(r"^BOT_TOKEN=(\S+)", envf.read_text(errors="ignore"), re.M)
            if m:
                tok = m.group(1)
        if not tok:
            tok = os.getenv("BOT_TOKEN", "")
        if tok:
            with urllib.request.urlopen(
                    f"https://api.telegram.org/bot{tok}/getMe", timeout=8) as r:
                j = json.loads(r.read())
                out["telegram_ok"] = bool(j.get("ok"))
                out["bot_username"] = j.get("result", {}).get("username")
        else:
            out["telegram_ok"] = None
    except Exception as e:
        out["telegram_ok"] = False
        out["telegram_error"] = str(e)[:120]
    return out


def logs_tail(n: int = 300) -> str:
    try:
        p = subprocess.run(JOURNAL_CMD.split() + ["-n", str(n)],
                           capture_output=True, text=True, timeout=20)
        return p.stdout[-400_000:] or p.stderr[:5000]
    except FileNotFoundError:
        return "journalctl не найден — задайте JOURNAL_CMD (например: tail -n 500 /var/log/english-bot.log)"
    except Exception as e:
        return f"Ошибка чтения логов: {e}"


def files_tree(root: Path, rel: str = "") -> list[dict]:
    out = []
    d = root / rel if rel else root
    try:
        entries = sorted(d.iterdir(), key=lambda x: (x.is_file(), x.name.lower()))
    except OSError:
        return out
    for e in entries:
        if e.name in SKIP_DIRS or e.name.endswith((".pyc", ".db", ".log")):
            continue
        if e.is_dir():
            out.append({"name": e.name, "path": str((Path(rel) / e.name)),
                        "type": "dir"})
        elif e.suffix in CODE_EXTS or e.name in (".env.example", "Dockerfile"):
            out.append({"name": e.name, "path": str((Path(rel) / e.name)),
                        "type": "file", "size": e.stat().st_size})
    return out


SECRET_FILES = {".env", ".env.admin", ".env.bak"}


def safe_project_path(rel: str) -> Path | None:
    rel = (rel or "").strip().lstrip("/")
    p = (EDITABLE_ROOT / rel).resolve()
    if not p.is_relative_to(EDITABLE_ROOT.resolve()):
        return None
    if p.name in SECRET_FILES or p.name.startswith(".env."):
        return None
    return p


# ---------------- auth ----------------

def make_session() -> str:
    sid = secrets.token_urlsafe(32)
    SESSIONS[sid] = time.time() + SESSION_TTL
    return sid


def authed(handler) -> bool:
    # 1) API-токен
    qs = parse_qs(urlparse(handler.path).query)
    if "token" in qs and hmac.compare_digest(qs["token"][0], API_TOKEN):
        return True
    hdr = handler.headers.get("Authorization", "")
    if hdr.startswith("Bearer ") and hmac.compare_digest(hdr[7:], API_TOKEN):
        return True
    # 2) cookie-сессия
    c = http.cookies.SimpleCookie(handler.headers.get("Cookie", ""))
    sid = c["adm_sid"].value if "adm_sid" in c else ""
    exp = SESSIONS.get(sid, 0)
    if sid and exp > time.time():
        return True
    # basic auth
    ah = handler.headers.get("Authorization", "")
    if ah.startswith("Basic "):
        import base64
        try:
            u, _, p = base64.b64decode(ah[6:]).decode().partition(":")
            if (hmac.compare_digest(u, ADMIN_USER) and
                    hmac.compare_digest(p, ADMIN_PASSWORD)):
                return True
        except Exception:
            pass
    return False


# ---------------- HTML ----------------

INDEX_HTML = """<!doctype html><html lang="ru"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>English Bot — админ-панель</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
<style>
:root{--bg:#0f1420;--card:#182032;--line:#2a3550;--tx:#dbe4f5;--mut:#8493ad;--acc:#4f8cff;--ok:#3ecf8e;--bad:#ff6b6b;--warn:#ffb454}
*{box-sizing:border-box}body{margin:0;font:14px/1.5 system-ui,sans-serif;background:var(--bg);color:var(--tx)}
header{display:flex;gap:12px;align-items:center;padding:10px 18px;background:var(--card);border-bottom:1px solid var(--line);position:sticky;top:0;z-index:5;flex-wrap:wrap}
header h1{font-size:16px;margin:0 auto 0 0}nav{display:flex;gap:4px;flex-wrap:wrap}
nav a{color:var(--mut);text-decoration:none;padding:6px 12px;border-radius:8px}nav a.on,nav a:hover{background:var(--line);color:var(--tx)}
main{padding:18px;max-width:1280px;margin:0 auto}
.grid{display:grid;gap:14px}.g6{grid-template-columns:repeat(auto-fit,minmax(160px,1fr))}.g2{grid-template-columns:repeat(auto-fit,minmax(380px,1fr))}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:16px}
.kpi b{font-size:26px;display:block}.kpi span{color:var(--mut);font-size:12px;text-transform:uppercase;letter-spacing:.04em}
.dot{width:10px;height:10px;border-radius:50%;display:inline-block;margin-right:6px}
.ok{color:var(--ok)}.bad{color:var(--bad)}.warn{color:var(--warn)}.mut{color:var(--mut)}
table{width:100%;border-collapse:collapse}th,td{padding:7px 9px;border-bottom:1px solid var(--line);text-align:left;font-size:13px}
th{color:var(--mut);font-weight:600}tr:hover td{background:#1d2740}
button,.btn{background:var(--acc);border:0;color:#fff;padding:8px 14px;border-radius:8px;cursor:pointer;font-size:13px}
button.sec{background:var(--line)}input,select,textarea{background:#0d1220;border:1px solid var(--line);color:var(--tx);padding:8px 10px;border-radius:8px;font-size:13px}
textarea.code{width:100%;height:70vh;font:13px/1.45 ui-monospace,monospace;white-space:pre;resize:vertical}
pre.log{background:#0b0f18;border:1px solid var(--line);border-radius:8px;padding:12px;overflow:auto;max-height:70vh;font:12px/1.4 ui-monospace,monospace;white-space:pre-wrap}
.pill{padding:2px 8px;border-radius:99px;font-size:11px;border:1px solid var(--line)}
.row{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-bottom:12px}
canvas{max-height:260px}h2{font-size:15px;margin:0 0 12px}a.tx{color:var(--acc)}
#toast{position:fixed;bottom:18px;right:18px;background:var(--card);border:1px solid var(--line);padding:10px 16px;border-radius:10px;display:none}
.login{max-width:340px;margin:15vh auto}.login input{width:100%;margin:8px 0}
</style></head><body>
<div id="app"></div><div id="toast"></div>
<script>
const $=s=>document.querySelector(s);
async function api(p,opt={}){const r=await fetch(p,opt);if(r.status===401){location='/login';throw 0}
 const t=r.headers.get('content-type')||'';return t.includes('json')?r.json():r.text();}
function toast(m){const t=$('#toast');t.textContent=m;t.style.display='block';setTimeout(()=>t.style.display='none',2500)}
async function post(p,d){return await api(p,{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify(d||{})})}
const NAV=[['dash','📊 Обзор'],['users','👥 Люди'],['charts','📈 Графики'],['sql','🧪 SQL'],['files','🛠 Код'],['logs','📜 Логи'],['sys','⚙️ Сервис']];
let charts={};
function shell(active){$('#app').innerHTML=`<header><h1>🤖 English Bot · Admin</h1>
<nav>${NAV.map(([k,l])=>`<a href='#${k}' class="${k==active?'on':''}" onclick="route('${k}')">${l}</a>`).join('')}</nav>
<span id="botstate" class="pill"></span></header><main id="m"></main>`;}
function setDot(s){$('#botstate').innerHTML=s.bot_up?`<span class="dot" style="background:var(--ok)"></span>${s.bot_state} · ${s.bot_service}`:`<span class="dot" style="background:var(--bad)"></span>${s.bot_state||'?'}`}
async function route(k){shell(k);({dash,users,chartsPage,sql,files,logs,sys})[k]?.();
 try{setDot(await api('/api/status'))}catch(e){}}
// ---- Дашборд
async function dash(){const o=await api('/api/business');
 $('#m').innerHTML=`<div class="grid g6">
 ${kpi('Пользователей',o.users_total,'+'+(o.users_today||0)+' сегодня · +'+(o.users_week||0)+' за 7 дней')}
 ${kpi('Активны сегодня',o.active_today,(o.active_week||0)+' за 7 дней')}
 ${kpi('Платящих сейчас',o.paying_now,'конверсия '+(o.conversion_pct||0)+'%')}
 ${kpi('Выручка всего',(o.revenue_total||0)+' ⭐',(o.payments_count||0)+' оплат')}
 ${kpi('За 30 дней',(o.revenue_30d||0)+' ⭐','сегодня '+(o.revenue_today||0)+' ⭐')}
 ${kpi('Средний чек',(o.avg_check||0)+' ⭐','ARPU '+(o.arpu||0)+' ⭐')}
 ${kpi('Донаты',(o.revenue_donations||0)+' ⭐',(o.donations_count||0)+' поддержек')}
 </div>
 <div class="grid g2" style="margin-top:14px">
 <div class="card"><h2>Тарифы</h2>${bars(o.plans||[],'tier','n')}</div>
 <div class="card"><h2>Выручка по тарифам</h2>${bars(o.revenue_by_tier||[],'tier','stars')}</div>
 <div class="card"><h2>Подписки истекают за 7 дней</h2>${(o.expiring||[]).length?
 `<table><tr><th>ID</th><th>тариф</th><th>до</th></tr>${o.expiring.map(e=>
 `<tr><td>${e.user_id}</td><td>${tierPill(e.tier)}</td><td class="mut">${(e.expires_at||'').slice(0,10)}</td></tr>`).join('')}</table>`
 :'<p class="mut">нет истекающих</p>'}</div>
 <div class="card"><h2>База данных</h2><p class="mut">${o.db_path||''}<br>размер: ${o.db_size_kb??'?'} КБ · снимок: ${o.generated_at||''} UTC</p>
 <a class="btn" href="/api/export.sql">💾 Скачать .sql дамп</a></div></div>
 ${o.accounting_since?`<p class="mut">Учёт платежей ведётся с ${String(o.accounting_since).slice(0,10)}. Более ранние оплаты в базе не сохранялись.</p>`
 :'<p class="warn">Оплат пока не записано: журнал начали вести только что, прошлые платежи в базе отсутствуют.</p>'}`;}

function kpi(t,v,s){return `<div class="card kpi"><span>${t}</span><b>${v??'—'}</b><small class="mut">${s||''}</small></div>`}
function bars(arr,k,v){if(!arr.length)return '<p class="mut">нет данных</p>';
 const mx=Math.max(...arr.map(a=>a[v]))||1;
 return arr.map(a=>`<div class="row"><span style="min-width:110px">${a[k]??'—'}</span>
 <div style="flex:1;background:#0d1220;border-radius:6px"><div style="width:${100*a[v]/mx}%;background:var(--acc);height:14px;border-radius:6px"></div></div>
 <b>${a[v]}</b></div>`).join('')}
// ---- Люди
async function users(page=0){const f=new URLSearchParams({q:$('#uq')?.value||'',plan:$('#up')?.value||'',p:String(page)});
 const d=await api('/api/users?'+f);const rows=d.items.map(u=>`<tr>
 <td><a class="tx" href="#" onclick="userCard(${u.user_id});return false">${u.user_id}</a></td>
 <td>${u.username||''}</td><td>${tierPill(u.tier)}</td>
 <td>${u.paid_stars||0} ⭐</td><td>${u.payments_n||0}</td>
 <td class="mut">${(u.expires_at||'—').slice(0,10)}</td>
 <td>${(u.last_active||'—')}</td><td class="mut">${(u.created_at||'').slice(0,10)}</td></tr>`).join('');
 $('#m').innerHTML=`<div class="card"><div class="row">
 <input id="uq" placeholder="ID или @username" value="${$('#uq')?.value||''}">
 <select id="up"><option value="">все тарифы</option>${['free','plus'].map(x=>`<option ${$('#up')?.value==x?'selected':''}>${x}</option>`).join('')}</select>
 <button onclick="users(0)">Найти</button><span class="mut">всего: ${d.total}</span></div>
 <div style="overflow:auto"><table><tr><th>ID</th><th>Username</th><th>Тариф</th><th>Оплачено</th><th>Платежей</th><th>Подписка до</th><th>Активен</th><th>Регистрация</th></tr>${rows||'<tr><td colspan=8 class="mut">пусто</td></tr>'}</table></div>
 <div class="row" style="margin-top:10px">${page>0?'<button class="sec" onclick="users('+(page-1)+')">← назад</button>':''}
 ${d.total>(page+1)*100?'<button class="sec" onclick="users('+(page+1)+')">вперёд →</button>':''}</div></div>
 <div id="detail"></div>`;}

function tierPill(t){const c={free:'mut',plus:'ok',donate:'warn'}[t]||'mut';return `<span class="pill ${c}">${t||'free'}</span>`}
async function userCard(id){const d=await api('/api/user/'+id);
 const pays=(d.payments||[]);
 $('#detail').innerHTML=`<div class="card" style="margin-top:14px"><h2>Пользователь ${id} · ${d.user?.username||''} ${tierPill(d.plan?.tier||'free')}</h2>
 <div class="grid g2"><div><h2>Платежи</h2>${pays.length?
 `<table><tr><th>дата</th><th>тариф</th><th>звёзды</th><th>дней</th></tr>${pays.map(p=>
 `<tr><td class="mut">${(p.created_at||'').slice(0,10)}</td><td>${p.tier}</td><td>${p.stars} ⭐</td><td>${p.days}</td></tr>`).join('')}</table>`
 :'<p class="mut">оплат не записано</p>'}</div>
 <div><h2>Активность по дням</h2><table><tr><th>день</th><th>слов</th><th>квиз</th><th>чат</th><th>повторы</th></tr>
 ${(d.usage||[]).slice(0,14).map(u=>`<tr><td>${u.day}</td><td>${u.words??''}</td><td>${u.quiz??''}</td><td>${u.chat??''}</td><td>${u.review??''}</td></tr>`).join('')||'<tr><td colspan=5 class="mut">нет</td></tr>'}</table></div></div></div>`;}

// ---- Графики
async function chartsPage(){const g=await api('/api/growth?days=30'),a=await api('/api/activity?days=14'),b=await api('/api/business');
 $('#m').innerHTML=`<div class="grid g2"><div class="card"><h2>Рост базы и DAU (30 дней)</h2><canvas id="cg"></canvas></div>
 <div class="card"><h2>Выручка по дням (30 дней)</h2><canvas id="cr"></canvas></div>
 <div class="card"><h2>Активность по типам (14 дней)</h2><canvas id="ca"></canvas></div></div>`;
 mkChart('cg',g.map(r=>r.day),[{l:'новые',d:g.map(r=>r.new_users)},{l:'активные',d:g.map(r=>r.active)}]);
 const rd=(b.daily||[]);
 mkChart('cr',rd.map(r=>r.day),[{l:'звёзды',d:rd.map(r=>r.stars)},{l:'оплат',d:rd.map(r=>r.n)}]);
 const kinds=[...new Set(a.map(r=>r.kind))].filter(k=>['words','quiz','chat','review'].includes(k));
 const adays=[...new Set(a.map(r=>r.day))].sort();
 mkChart('ca',adays,kinds.map(k=>({l:k,d:adays.map(dy=>a.find(r=>r.day==dy&&r.kind==k)?.n||0)})));}

function mkChart(id,labels,series){if(charts[id])charts[id].destroy();if(!window.Chart)return;
 charts[id]=new Chart($('#'+id),{type:'line',data:{labels,datasets:series.map((s,i)=>({label:s.l,data:s.d,borderColor:['#4f8cff','#3ecf8e','#ffb454','#ff6b6b','#b48cff','#5fd4d4'][i%6],tension:.3,pointRadius:2}))},options:{plugins:{legend:{labels:{color:'#dbe4f5'}}},scales:{x:{ticks:{color:'#8493ad'}},y:{ticks:{color:'#8493ad'},grid:{color:'#2a3550'}}}}});}
// ---- SQL
async function sql(){const sc=await api('/api/schema');
 $('#m').innerHTML=`<div class="card"><div class="row"><textarea id="qs" style="flex:1;min-width:300px;height:90px;font-family:monospace">SELECT level, COUNT(*) n FROM users GROUP BY level;</textarea>
 <div><button onclick="runSql()">▶ Выполнить</button><p class="mut">только read-only<br>(SELECT / WITH / PRAGMA)</p></div></div>
 <div id="qr"></div></div>
 <div class="card" style="margin-top:14px"><h2>Схема БД</h2>${sc.map(t=>`<details><summary><b>${t.name}</b> <span class="mut">${t.rows} строк · ${t.columns.map(c=>c.name).join(', ')}</span></summary><pre>${t.sql}</pre></details>`).join('')}</div>`;}
async function runSql(){const r=await post('/api/query',{sql:$('#qs').value});
 $('#qr').innerHTML=r.error?`<p class="bad">${r.error}</p>`:
 `<table><tr>${r.columns.map(c=>`<th>${c}</th>`).join('')}</tr>${r.rows.map(row=>`<tr>${row.map(v=>`<td>${v??'NULL'}</td>`).join('')}</tr>`).join('')}</table>${r.truncated?'<p class="mut">…обрезано до 500 строк</p>':''}`;}
// ---- Код
let curFile='';
async function files(path=''){const t=await api('/api/files?path='+encodeURIComponent(path));
 $('#m').innerHTML=`<div class="grid g2"><div class="card"><h2>🛠 Проект (модернизация бота отсюда)</h2>
 <div class="row"><button class="sec" onclick="files('${path.split('/').slice(0,-1).join('/')}')">↑ вверх</button>
 <span class="mut">${path||'/'}</span></div>
 <table>${t.map(f=>`<tr><td>${f.type=='dir'?'📁':'📄'}</td><td><a class="tx" href="#" onclick="${f.type=='dir'?`files('${f.path}')`:`openFile('${f.path}')`};return false">${f.name}</a></td><td class="mut">${f.size?(f.size/1024).toFixed(1)+' КБ':''}</td></tr>`).join('')}</table>
 <p class="mut">Сохранение ${''/*placeholder*/}</p></div>
 <div class="card"><h2>Файл</h2><div class="row"><b id="fn" class="mut">не выбран</b>
 <button id="save" style="display:none" onclick="saveFile()">💾 Сохранить</button>
 <a class="tx" id="dl" style="display:none" href="#">raw</a></div>
 <textarea id="ed" class="code" spellcheck="false"></textarea></div></div>`;
 $('#m').querySelector('.mut:last-of-type').textContent=window.canWrite?'режим записи: ВКЛ (PROJECT_WRITE=on)':'режим записи: выкл (только просмотр)';}
async function openFile(p){curFile=p;const d=await api('/api/file?path='+encodeURIComponent(p));
 if(d.error)return toast(d.error);$('#fn').textContent=p;$('#ed').value=d.content;$('#save').style.display='inline-block';
 const dl=$('#dl');dl.style.display='inline';dl.href='/api/file.raw?path='+encodeURIComponent(p);}
async function saveFile(){const r=await post('/api/file',{path:curFile,content:$('#ed').value});
 toast(r.ok?'✅ Сохранено: '+curFile+(r.restart_hint?' — перезапустите сервис во вкладке «Сервис»':''):'❌ '+(r.error||'ошибка'));}
// ---- Логи
async function logs(){const t=await api('/api/logs');
 $('#m').innerHTML=`<div class="card"><div class="row"><h2 style="margin:0">Логи сервиса ${''/*x*/}</h2><button class="sec" onclick="route('logs')">⟳ Обновить</button>
 <label><input type="checkbox" id="auto" checked> автообновление 10с</label></div><pre class="log">${esc(t)}</pre></div>`;
 clearInterval(window._lt);window._lt=setInterval(async()=>{if($('#auto')?.checked){const x=await api('/api/logs');const p=$('#m pre');if(p){p.textContent=x;p.scrollTop=p.scrollHeight}}},10000);}
function esc(s){return (s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;')}
// ---- Сервис
async function sys(){const s=await api('/api/status');
 $('#m').innerHTML=`<div class="card"><h2>Состояние бота</h2><table>
 <tr><td>systemd-сервис</td><td>${s.bot_service}</td></tr>
 <tr><td>состояние</td><td class="${s.bot_up?'ok':'bad'}">${s.bot_state}</td></tr>
 <tr><td>запущен с</td><td>${s.since||'?'}</td></tr>
 <tr><td>память процесса</td><td>${s.mem_mb??'?'} МБ</td></tr>
 <tr><td>Telegram API (getMe)</td><td class="${s.telegram_ok?'ok':(s.telegram_ok===false?'bad':'mut')}">${s.telegram_ok===true?'✅ доступен ('+(s.bot_username||'')+')':(s.telegram_ok===false?'❌ '+(s.telegram_error||''): '? — BOT_TOKEN не найден')}</td></tr></table>
 <div class="row" style="margin-top:14px">
 <button onclick="svc('restart')">🔄 Перезапустить бота</button>
 <button class="sec" onclick="svc('stop')">⏹ Остановить</button>
 <button class="sec" onclick="svc('start')">▶ Запустить</button></div>
 <p class="mut">Примечание: панель работает с БД только на чтение; изменения кода применяются после перезапуска сервиса.</p></div>`;}
async function svc(a){if(a!=='start'&&!confirm(`${a} сервис ${'BOT_SERVICE'}`))return;
 const r=await post('/api/service',{action:a});toast(r.ok?`✅ ${a}: ${r.out||'ok'}`:`❌ ${a}: ${r.out}`);sys();}
window.addEventListener('hashchange',()=>route(location.hash.slice(1)||'dash'));
window.canWrite=%CW%;route(location.hash.slice(1)||'dash');
</script></body></html>"""

LOGIN_HTML = """<!doctype html><html><head><meta charset="utf-8"><title>Вход — админ-панель</title>
<style>body{font:15px system-ui;background:#0f1420;color:#dbe4f5;display:grid;place-items:center;height:100vh;margin:0}
form{background:#182032;border:1px solid #2a3550;border-radius:14px;padding:28px;width:320px}
input{width:100%;padding:10px;margin:8px 0;border-radius:8px;border:1px solid #2a3550;background:#0d1220;color:#dbe4f5}
button{width:100%;padding:10px;background:#4f8cff;color:#fff;border:0;border-radius:8px;font-size:15px}</style></head>
<body><form method="post" action="/login"><h2 style="margin:0 0 10px">🤖 Админ-панель бота</h2>
<input name="user" placeholder="логин" autocomplete="username">
<input name="pass" type="password" placeholder="пароль" autocomplete="current-password">
<button>Войти</button>%ERR%</form></body></html>"""


# ---------------- server ----------------

class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):  # тише
        pass

    # --- низкоуровневое ---
    def _send(self, code: int, body: bytes, ctype="text/html; charset=utf-8",
              extra=None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code=200):
        self._send(code, json.dumps(obj, ensure_ascii=False, default=str).encode(),
                   "application/json; charset=utf-8")

    def _body(self) -> dict:
        n = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(n) if n else b""
        try:
            return json.loads(raw or b"{}")
        except json.JSONDecodeError:
            return {}

    # --- маршрутизация ---
    def do_GET(self):
        url = urlparse(self.path)
        p, qs = url.path, parse_qs(url.query)
        if p == "/login":
            return self._send(200, LOGIN_HTML.replace("%ERR%", "").encode())
        if p in ("/", "/index.html"):
            if not authed(self):
                return self.redirect("/login")
            html = INDEX_HTML.replace("%CW%", "true" if PROJECT_WRITE else "false")
            return self._send(200, html.encode())
        if p.startswith("/api/"):
            if not authed(self):
                return self._json({"error": "unauthorized"}, 401)
            return self._api(p, qs)
        return self._send(404, b"not found", "text/plain")

    def do_POST(self):
        url = urlparse(self.path)
        p = url.path
        if p == "/login":
            n = int(self.headers.get("Content-Length") or 0)
            form = parse_qs(self.rfile.read(n).decode())
            u = (form.get("user") or [""])[0]
            pw = (form.get("pass") or [""])[0]
            ok = (hmac.compare_digest(u, ADMIN_USER) and
                  hmac.compare_digest(pw, ADMIN_PASSWORD))
            if ok:
                sid = make_session()
                return self._send(302, b"", "text/plain", {
                    "Location": "/",
                    "Set-Cookie": f"adm_sid={sid}; HttpOnly; Path=/; Max-Age={SESSION_TTL}; SameSite=Lax"})
            return self._send(200, LOGIN_HTML.replace(
                "%ERR%", '<p style="color:#ff6b6b">Неверный логин/пароль</p>').encode())
        if p.startswith("/api/"):
            if not authed(self):
                return self._json({"error": "unauthorized"}, 401)
            return self._api_post(p, self._body())
        return self._send(404, b"not found", "text/plain")

    def redirect(self, to):
        self._send(302, b"", "text/plain", {"Location": to})

    # --- API GET ---
    def _api(self, p: str, qs: dict):
        try:
            if p == "/api/business":
                return self._json(analytics.business())
            if p == "/api/overview":
                return self._json(analytics.overview())
            if p == "/api/status":
                return self._json(bot_status())
            if p == "/api/growth":
                return self._json(analytics.growth(int((qs.get("days") or [30])[0])))
            if p == "/api/activity":
                return self._json(analytics.activity(
                    (qs.get("kind") or [""])[0], int((qs.get("days") or [14])[0])))
            if p == "/api/top_words":
                return self._json(analytics.top_words())
            if p == "/api/retention":
                return self._json(analytics.retention())
            if p == "/api/users":
                return self._json(analytics.users_list(
                    q=(qs.get("q") or [""])[0], plan=(qs.get("plan") or [""])[0],
                    level=(qs.get("level") or [""])[0],
                    offset=int((qs.get("p") or ["0"])[0]) * 100))
            if p.startswith("/api/user/"):
                uid = int(re.sub(r"\D", "", p.split("/")[-1]) or 0)
                return self._json(analytics.user_detail(uid))
            if p == "/api/schema":
                return self._json(analytics.schema())
            if p == "/api/logs":
                return self._send(200, logs_tail(500).encode(), "text/plain; charset=utf-8")
            if p == "/api/files":
                return self._json(files_tree(EDITABLE_ROOT, (qs.get("path") or [""])[0]))
            if p == "/api/file":
                f = safe_project_path((qs.get("path") or [""])[0])
                if not f or not f.is_file():
                    return self._json({"error": "файл не найден"}, 404)
                return self._json({"path": str(f.relative_to(EDITABLE_ROOT)),
                                   "content": f.read_text(errors="replace")[:2_000_000]})
            if p == "/api/file.raw":
                f = safe_project_path((qs.get("path") or [""])[0])
                if not f or not f.is_file():
                    return self._send(404, b"not found", "text/plain")
                return self._send(200, f.read_bytes(), "text/plain; charset=utf-8")
            if p == "/api/export.sql":
                dump = analytics.dump_sql().encode()
                return self._send(200, dump, "application/sql", {
                    "Content-Disposition":
                        f'attachment; filename="bot_backup_{dt.date.today()}.sql"'})
        except Exception as e:
            return self._json({"error": f"{type(e).__name__}: {e}"}, 500)
        return self._json({"error": "unknown endpoint"}, 404)

    # --- API POST ---
    def _api_post(self, p: str, body: dict):
        try:
            if p == "/api/query":
                return self._json(analytics.run_query(body.get("sql", "")))
            if p == "/api/service":
                act = body.get("action", "status")
                if act not in ("start", "stop", "restart", "status"):
                    return self._json({"error": "bad action"}, 400)
                return self._json(_systemd(act))
            if p == "/api/file":
                if not PROJECT_WRITE:
                    return self._json({"ok": False, "error": "запись запрещена (PROJECT_WRITE=off)"}, 403)
                f = safe_project_path(body.get("path", ""))
                if not f:
                    return self._json({"ok": False, "error": "путь вне проекта"}, 400)
                content = body.get("content", "")
                if f.name == ".env" or content is None:
                    pass
                backup = None
                if f.exists():
                    backup = f.with_name(f.name + f".bak.{dt.datetime.now():%Y%m%d_%H%M%S}")
                    backup.write_bytes(f.read_bytes())
                f.parent.mkdir(parents=True, exist_ok=True)
                f.write_text(content)
                if f.suffix == ".py":
                    import py_compile
                    try:
                        py_compile.compile(str(f), doraise=True)
                    except py_compile.PyCompileError as e:
                        if backup:
                            f.write_bytes(backup.read_bytes())
                        return self._json({"ok": False, "error": f"синтаксис: {e}"})
                return self._json({"ok": True, "backup": backup.name if backup else None,
                                   "restart_hint": True})
        except Exception as e:
            return self._json({"error": f"{type(e).__name__}: {e}"}, 500)
        return self._json({"error": "unknown endpoint"}, 404)


def main():
    ap = argparse.ArgumentParser(description="Админ-панель мониторинга бота")
    ap.add_argument("--host", default=os.getenv("ADMIN_HOST", "127.0.0.1"))
    ap.add_argument("--port", type=int, default=int(os.getenv("ADMIN_PORT", "8080")))
    args = ap.parse_args()
    print(f"[admin] панель: http://{args.host}:{args.port}  (user={ADMIN_USER})")
    print(f"[admin] БД: {analytics.default_db_path()}")
    if ADMIN_PASSWORD == "changeme":
        print("[admin] ⚠ пароль по умолчанию 'changeme' — задайте ADMIN_PASSWORD!")
    ThreadingHTTPServer((args.host, args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
