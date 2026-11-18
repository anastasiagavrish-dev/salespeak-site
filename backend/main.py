"""Прием заявок a-gavrish.com + админка.

Один файл, один и тот же код на сервере в России (REGION=ru) и в Казахстане (REGION=kz).
Настройки – в переменных окружения (.env, права 600), см. .env.example.
"""
import base64, csv, hashlib, hmac, html, io, json, os, re, secrets, sqlite3, threading, time, urllib.parse, urllib.request
from datetime import datetime, timedelta, timezone

from fastapi import FastAPI, Request, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

REGION = os.environ.get("REGION", "ru")
DB_PATH = os.environ.get("DB_PATH", os.path.join(os.path.dirname(__file__), "leads.sqlite3"))
SITE_ORIGIN = os.environ.get("SITE_ORIGIN", "https://a-gavrish.com")
ADMIN_BASE = os.environ.get("ADMIN_BASE", "https://a-gavrish.com/admin")
ADMIN_PASSWORD_HASH = os.environ.get("ADMIN_PASSWORD_HASH", "")  # формат scrypt$<salt_b64>$<hash_b64>
SESSION_SECRET = os.environ.get("SESSION_SECRET", "") or secrets.token_hex(32)
TG_BOT_TOKEN = os.environ.get("TG_BOT_TOKEN", "")
TG_CHAT_ID = os.environ.get("TG_CHAT_ID", "")
CONSENT_VERSION = os.environ.get("CONSENT_VERSION", "2026-11-03")
RETENTION_DAYS = int(os.environ.get("RETENTION_DAYS", str(3 * 365)))
COOKIE_SECURE = os.environ.get("COOKIE_SECURE", "1") == "1"
SERVE_STATIC = os.environ.get("SERVE_STATIC", "")  # только для локальной проверки, на сервере статику отдает nginx

STATUSES = {"new": "Новая", "work": "В работе", "closed": "Закрыта"}
REGION_LABEL = {"ru": "Россия", "kz": "Казахстан"}[REGION]

app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
app.add_middleware(CORSMiddleware, allow_origins=[SITE_ORIGIN], allow_methods=["POST"], allow_headers=["Content-Type"])


# ---------- база ----------
def db():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con


def init_db():
    with db() as con:
        con.execute("""CREATE TABLE IF NOT EXISTS leads(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
            name TEXT NOT NULL, contact TEXT NOT NULL, pain TEXT, country TEXT,
            consent_pd INTEGER NOT NULL, consent_ads INTEGER NOT NULL,
            consent_version TEXT NOT NULL, ip TEXT, user_agent TEXT, page TEXT,
            status TEXT NOT NULL DEFAULT 'new')""")
        con.execute("CREATE INDEX IF NOT EXISTS ix_leads_ip_time ON leads(ip, created_at)")


def now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def purge_old():
    """Удаляет заявки старше срока хранения (считая от последнего изменения)."""
    border = (datetime.now(timezone.utc) - timedelta(days=RETENTION_DAYS)).strftime("%Y-%m-%dT%H:%M:%SZ")
    with db() as con:
        con.execute("DELETE FROM leads WHERE updated_at < ?", (border,))


def purge_loop():
    while True:
        try:
            purge_old()
        except Exception:
            pass
        time.sleep(24 * 3600)


@app.on_event("startup")
def startup():
    init_db()
    threading.Thread(target=purge_loop, daemon=True).start()


# ---------- уведомление о заявке (без персональных данных: только номер и ссылка на админку) ----------
NOTIFY_URL = os.environ.get("NOTIFY_URL", "")  # веб-приложение Google Apps Script: шлет письмо и Telegram


def notify(lead_id):
    text = f"Новая заявка №{lead_id} ({REGION_LABEL}). Открыть: {ADMIN_BASE}"
    if NOTIFY_URL:
        try:
            req = urllib.request.Request(NOTIFY_URL, data=json.dumps({"text": text, "id": lead_id}).encode(),
                                         headers={"Content-Type": "application/json"})
            urllib.request.urlopen(req, timeout=20)
        except Exception:
            pass
    if TG_BOT_TOKEN and TG_CHAT_ID:
        data = urllib.parse.urlencode({"chat_id": TG_CHAT_ID, "text": text, "disable_web_page_preview": "true"}).encode()
        try:
            urllib.request.urlopen(f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage", data=data, timeout=10)
        except Exception:
            pass


# ---------- прием заявки ----------
def client_ip(req: Request):
    return req.headers.get("x-real-ip") or (req.client.host if req.client else "")


@app.post("/api/lead")
async def lead(req: Request):
    try:
        d = await req.json()
    except Exception:
        return JSONResponse({"ok": False, "error": "Не удалось прочитать заявку. Обновите страницу и попробуйте еще раз."}, 400)
    if (d.get("website") or "").strip():  # honeypot: поле невидимо для людей
        return {"ok": True, "id": 0}
    name = (d.get("name") or "").strip()[:120]
    contact = (d.get("contact") or "").strip()[:120]
    pain = (d.get("pain") or "").strip()[:2000]
    country = (d.get("country") or "").strip()[:20]
    errors = {}
    if not name:
        errors["name"] = "Напишите, как к вам обращаться"
    digits = re.sub(r"\D", "", contact)
    if not (len(digits) >= 10 or re.fullmatch(r"@?[A-Za-z0-9_]{5,32}", contact)):
        errors["contact"] = "Нужен телефон, например +7 701 123 45 67, или ник в Telegram"
    if d.get("consent_pd") is not True:
        errors["consent_pd"] = "Без согласия заявку отправить нельзя"
    if errors:
        return JSONResponse({"ok": False, "errors": errors}, 422)
    ip = client_ip(req)
    hour_ago = (datetime.now(timezone.utc) - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    with db() as con:
        n = con.execute("SELECT COUNT(*) FROM leads WHERE ip=? AND created_at>?", (ip, hour_ago)).fetchone()[0]
        if n >= 5:
            return JSONResponse({"ok": False, "error": "Слишком много заявок с вашего адреса. Напишите в Telegram или WhatsApp."}, 429)
        t = now()
        cur = con.execute(
            "INSERT INTO leads(created_at,updated_at,name,contact,pain,country,consent_pd,consent_ads,consent_version,ip,user_agent,page)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            (t, t, name, contact, pain, country, 1, 1 if d.get("consent_ads") is True else 0, CONSENT_VERSION, ip,
             (req.headers.get("user-agent") or "")[:300], (d.get("page") or "")[:300]))
        lead_id = cur.lastrowid
    threading.Thread(target=notify, args=(lead_id,), daemon=True).start()
    return {"ok": True, "id": lead_id}


# ---------- вход в админку ----------
def make_hash(password: str) -> str:
    salt = secrets.token_bytes(16)
    h = hashlib.scrypt(password.encode(), salt=salt, n=2 ** 14, r=8, p=1)
    return "scrypt$" + base64.b64encode(salt).decode() + "$" + base64.b64encode(h).decode()


def check_password(password: str) -> bool:
    try:
        _, s, h = ADMIN_PASSWORD_HASH.split("$")
        calc = hashlib.scrypt(password.encode(), salt=base64.b64decode(s), n=2 ** 14, r=8, p=1)
        return hmac.compare_digest(calc, base64.b64decode(h))
    except Exception:
        return False


def sign(value: str) -> str:
    return value + "." + hmac.new(SESSION_SECRET.encode(), value.encode(), hashlib.sha256).hexdigest()


def session_ok(req: Request) -> bool:
    raw = req.cookies.get("sp_admin", "")
    if "." not in raw:
        return False
    value, _ = raw.rsplit(".", 1)
    if not hmac.compare_digest(sign(value), raw):
        return False
    try:
        return float(value.split(":")[0]) > time.time()
    except Exception:
        return False


def csrf_token(req: Request) -> str:
    return hmac.new(SESSION_SECRET.encode(), (req.cookies.get("sp_admin", "") + "csrf").encode(), hashlib.sha256).hexdigest()[:32]


_login_fails = {}


@app.post("/admin/login")
def login(req: Request, password: str = Form("")):
    ip = client_ip(req)
    fails = [t for t in _login_fails.get(ip, []) if t > time.time() - 900]
    if len(fails) >= 5:
        return HTMLResponse(page("Вход", login_form("Слишком много попыток. Подождите 15 минут.")), 429)
    if not check_password(password):
        _login_fails[ip] = fails + [time.time()]
        return HTMLResponse(page("Вход", login_form("Пароль не подошел. Проверьте раскладку и попробуйте еще раз.")), 401)
    value = f"{time.time() + 30 * 24 * 3600:.0f}:{secrets.token_hex(8)}"
    r = RedirectResponse("/admin", 303)
    r.set_cookie("sp_admin", sign(value), max_age=30 * 24 * 3600, httponly=True, secure=COOKIE_SECURE, samesite="strict", path="/admin")
    return r


@app.post("/admin/logout")
def logout():
    r = RedirectResponse("/admin", 303)
    r.delete_cookie("sp_admin", path="/admin")
    return r


# ---------- админка ----------
ADMIN_CSS = """
:root{--bg:#F6F6FB;--card:#FFFFFF;--fg:#17152B;--muted:#5E5C75;--line:#E1DFEE;--violet:#4B3FE1;--lime:#D6F479;--bad:#C2261B;--r:14px}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:500 16px/1.5 Montserrat,system-ui,-apple-system,"Segoe UI",sans-serif}
.wrap{max-width:1100px;margin:0 auto;padding:24px max(16px,env(safe-area-inset-left))}
h1{font:600 26px/1.2 Unbounded,Montserrat,system-ui,sans-serif;margin:0}
.bar{display:flex;flex-wrap:wrap;gap:12px;align-items:center;justify-content:space-between;margin-bottom:20px}
.tabs{display:flex;flex-wrap:wrap;gap:8px}.tabs a{padding:8px 14px;border-radius:999px;text-decoration:none;color:var(--fg);background:var(--card);border:1px solid var(--line);font-size:14px;font-weight:600}
.tabs a.on{background:var(--fg);color:#fff;border-color:var(--fg)}
.btn{display:inline-flex;align-items:center;justify-content:center;min-height:44px;padding:0 18px;border:0;border-radius:12px;background:var(--violet);color:#fff;font:700 15px/1 inherit;font-family:inherit;cursor:pointer;text-decoration:none;transition:transform .2s cubic-bezier(.34,1.56,.64,1)}
.btn:active{transform:scale(.96)}.btn.ghost{background:transparent;color:var(--fg);border:1px solid var(--line)}.btn.danger{background:var(--bad)}
.list{display:grid;gap:12px}.lead{background:var(--card);border-radius:var(--r);padding:18px;display:grid;gap:10px}
.lead-top{display:flex;flex-wrap:wrap;gap:8px 16px;align-items:baseline}.lead-top b{font-size:18px;overflow-wrap:anywhere}
.meta{color:var(--muted);font-size:13px}.pain{white-space:pre-wrap;overflow-wrap:anywhere;background:var(--bg);border-radius:10px;padding:10px 12px;font-size:15px}
.pill{font-size:12px;font-weight:700;padding:3px 10px;border-radius:999px;border:1px solid var(--line)}
.pill.new{background:var(--lime);border-color:var(--lime)}.pill.work{background:#E7E5FF;border-color:#E7E5FF}.pill.closed{background:#EEE;border-color:#EEE;color:var(--muted)}
.acts{display:flex;flex-wrap:wrap;gap:8px;align-items:center}.acts form{margin:0}
details.del summary{cursor:pointer;color:var(--bad);font-size:14px;font-weight:600;list-style:none;padding:10px 4px}
details.del[open] summary{color:var(--muted)}
.empty{background:var(--card);border-radius:var(--r);padding:40px 24px;text-align:center;color:var(--muted)}
.pager{display:flex;gap:8px;margin-top:16px}
.login{max-width:380px;margin:12vh auto;background:var(--card);border-radius:var(--r);padding:28px;display:grid;gap:14px}
.login label{font-weight:600;font-size:15px}.login input{width:100%;min-height:50px;padding:12px 14px;border:1.5px solid var(--line);border-radius:10px;font:inherit}
.err{color:var(--bad);font-size:14px}.copy{font-size:13px;color:var(--muted)}
:focus-visible{outline:3px solid var(--violet);outline-offset:2px}
"""


def page(title, body):
    return f"""<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="robots" content="noindex,nofollow"><title>{html.escape(title)} – заявки a-gavrish.com</title>
<link rel="stylesheet" href="/assets/fonts.css"><style>{ADMIN_CSS}</style></head><body>{body}</body></html>"""


def login_form(err=""):
    e = f'<p class="err" role="alert">{html.escape(err)}</p>' if err else ""
    return f"""<form class="login" method="post" action="/admin/login"><h1>Заявки · {REGION_LABEL}</h1>
<label for="pw">Пароль</label><input id="pw" name="password" type="password" autocomplete="current-password" required autofocus>{e}
<button class="btn" type="submit">Войти</button></form>"""


def fmt_time(t):
    try:
        dt = datetime.strptime(t, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc) + timedelta(hours=5)
        return dt.strftime("%d.%m.%Y %H:%M") + " (Алматы)"
    except Exception:
        return t


@app.get("/admin", response_class=HTMLResponse)
def admin(req: Request, status: str = "all", p: int = 1):
    if not session_ok(req):
        return page("Вход", login_form())
    per = 30
    where, args = ("", []) if status not in STATUSES else ("WHERE status=?", [status])
    with db() as con:
        total = con.execute(f"SELECT COUNT(*) FROM leads {where}", args).fetchone()[0]
        rows = con.execute(f"SELECT * FROM leads {where} ORDER BY id DESC LIMIT ? OFFSET ?", args + [per, (max(p, 1) - 1) * per]).fetchall()
        counts = {k: con.execute("SELECT COUNT(*) FROM leads WHERE status=?", (k,)).fetchone()[0] for k in STATUSES}
    tok = csrf_token(req)
    tabs = [("all", "Все", sum(counts.values()))] + [(k, v, counts[k]) for k, v in STATUSES.items()]
    tabs_html = "".join(f'<a class="{"on" if status == k else ""}" href="/admin?status={k}">{v} · {n}</a>' for k, v, n in tabs)
    items = []
    for r in rows:
        e = {k: html.escape(str(r[k] or "")) for k in r.keys()}
        btns = "".join(
            f'<form method="post" action="/admin/lead/{r["id"]}/status"><input type="hidden" name="csrf" value="{tok}"><input type="hidden" name="to" value="{k}">'
            f'<button class="btn ghost" type="submit">{v}</button></form>' for k, v in STATUSES.items() if k != r["status"])
        items.append(f"""<article class="lead"><div class="lead-top"><b>{e['name']}</b><span>{e['contact']}</span>
<span class="pill {e['status']}">{STATUSES.get(r['status'], r['status'])}</span></div>
{f'<p class="pain">{e["pain"]}</p>' if r['pain'] else ''}
<p class="meta">№{r['id']} · {fmt_time(r['created_at'])} · страна: {e['country'] or 'по номеру'} · рассылка: {'да' if r['consent_ads'] else 'нет'} · согласие {e['consent_version']} · IP {e['ip']}</p>
<div class="acts">{btns}<details class="del"><summary>Удалить</summary>
<form method="post" action="/admin/lead/{r['id']}/delete"><input type="hidden" name="csrf" value="{tok}"><button class="btn danger" type="submit">Удалить заявку №{r['id']} навсегда</button></form></details></div></article>""")
    lst = "".join(items) or '<div class="empty">Заявок пока нет. Как только кто-то заполнит форму на сайте, она появится здесь, а в Telegram придет уведомление.</div>'
    pages = (total + per - 1) // per
    pager = ""
    if pages > 1:
        pager = '<nav class="pager">' + "".join(
            f'<a class="btn {"" if i == p else "ghost"}" href="/admin?status={status}&p={i}">{i}</a>' for i in range(1, pages + 1)) + "</nav>"
    body = f"""<div class="wrap"><div class="bar"><h1>Заявки · {REGION_LABEL}</h1>
<div class="acts"><a class="btn ghost" href="/admin/export.csv">Скачать CSV</a>
<form method="post" action="/admin/logout"><button class="btn ghost" type="submit">Выйти</button></form></div></div>
<nav class="tabs" aria-label="Статусы">{tabs_html}</nav><div class="list" style="margin-top:16px">{lst}</div>{pager}
<p class="copy" style="margin-top:24px">Заявки хранятся {RETENTION_DAYS // 365} года с последнего изменения и удаляются автоматически. Запрос «удалите мои данные» – найдите заявку и нажмите «Удалить».</p></div>"""
    return page("Заявки", body)


def guard(req: Request, csrf: str):
    return session_ok(req) and hmac.compare_digest(csrf or "", csrf_token(req))


@app.post("/admin/lead/{lead_id}/status")
def set_status(req: Request, lead_id: int, to: str = Form(""), csrf: str = Form("")):
    if not guard(req, csrf) or to not in STATUSES:
        return RedirectResponse("/admin", 303)
    with db() as con:
        con.execute("UPDATE leads SET status=?, updated_at=? WHERE id=?", (to, now(), lead_id))
    return RedirectResponse(req.headers.get("referer") or "/admin", 303)


@app.post("/admin/lead/{lead_id}/delete")
def delete(req: Request, lead_id: int, csrf: str = Form("")):
    if guard(req, csrf):
        with db() as con:
            con.execute("DELETE FROM leads WHERE id=?", (lead_id,))
    return RedirectResponse("/admin", 303)


@app.get("/admin/export.csv")
def export(req: Request):
    if not session_ok(req):
        return RedirectResponse("/admin", 303)
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    cols = ["id", "created_at", "name", "contact", "pain", "country", "status", "consent_ads", "consent_version", "ip", "page"]
    w.writerow(cols)
    with db() as con:
        for r in con.execute("SELECT * FROM leads ORDER BY id DESC"):
            w.writerow([r[c] for c in cols])
    return Response("﻿" + buf.getvalue(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="zayavki-{REGION}-{datetime.now():%Y-%m-%d}.csv"'})


if SERVE_STATIC:  # локальная проверка: отдать собранный сайт тем же процессом
    from fastapi.staticfiles import StaticFiles
    app.mount("/", StaticFiles(directory=SERVE_STATIC, html=True), name="site")

if __name__ == "__main__":
    import sys
    if len(sys.argv) > 2 and sys.argv[1] == "hash":
        print(make_hash(sys.argv[2]))
