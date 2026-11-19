"""Веб-версия игры «Касса тает»: страница (Telegram Mini App и обычный сайт) + API.
Промпты и ключ нейросети живут только на сервере – страница отправляет переписку и получает ответы."""
import asyncio
import hashlib
import hmac
import json
import logging
import os
import secrets
import time
from collections import defaultdict
from types import SimpleNamespace
from urllib.parse import parse_qsl

from aiohttp import web

import owner as own
from game_data import CLIENTS, DEFAULT_NUMBERS, MAX_TURNS

log = logging.getLogger("kassa.web")
WEB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")
PORT = int(os.environ.get("WEB_PORT", "8090"))
MAX_CALLS = 90           # запросов к нейросети на одну игру
SESSION_TTL = 6 * 3600
SESSIONS: dict[str, dict] = {}
STARTS: dict[str, list] = defaultdict(list)
K = None    # модуль kassa_bot (промпты, нейросеть, расчеты)
BOT = None


def verify_init_data(init_data, token):
    """Проверка подписи Telegram Mini App. Возвращает пользователя или None."""
    try:
        pairs = dict(parse_qsl(init_data, keep_blank_values=True))
        h = pairs.pop("hash", "")
        dcs = "\n".join(f"{k}={pairs[k]}" for k in sorted(pairs))
        secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
        if not hmac.compare_digest(hmac.new(secret, dcs.encode(), hashlib.sha256).hexdigest(), h):
            return None
        if time.time() - int(pairs.get("auth_date", "0")) > 86400:
            return None
        return json.loads(pairs.get("user", "{}")) or None
    except Exception:
        return None


def client_ip(req):
    return req.headers.get("X-Real-IP") or req.remote or "?"


def clean_log(raw):
    out = []
    for m in (raw or [])[:60]:
        if not isinstance(m, dict) or m.get("who") not in ("client", "manager"):
            continue
        out.append(dict(who=m["who"], text=str(m.get("text", ""))[:2000]))
    return out


def session(req, data):
    s = SESSIONS.get(str(data.get("sid", "")))
    if not s:
        raise web.HTTPUnauthorized(text=json.dumps({"error": "session"}), content_type="application/json")
    s["calls"] += 1
    if s["calls"] > MAX_CALLS:
        raise web.HTTPTooManyRequests(text=json.dumps({"error": "limit"}), content_type="application/json")
    return s


def game_of(s, data):
    i = int(data.get("i", -1))
    if not 0 <= i < len(CLIENTS):
        raise web.HTTPBadRequest(text=json.dumps({"error": "client"}), content_type="application/json")
    g = SimpleNamespace(i=i, log=clean_log(data.get("log")), turns=min(MAX_TURNS, max(1, int(data.get("turns", 1)))), nums=s["nums"])
    if not g.log or g.log[0]["who"] != "client":
        g.log.insert(0, dict(who="client", text=CLIENTS[i]["first"]))
    return g


def gc():
    now = time.time()
    for k in [k for k, v in SESSIONS.items() if now - v["created"] > SESSION_TTL]:
        SESSIONS.pop(k, None)


# ---------------- API ----------------
async def api_session(req):
    data = await req.json()
    gc()
    user = verify_init_data(data.get("initData") or "", K.TOKEN) if data.get("initData") else None
    who = f"tg:{user['id']}" if user else f"ip:{client_ip(req)}"
    team_id = (data.get("team") or "").strip()
    t = own.team(team_id) if team_id else None
    if team_id and not t:
        return web.json_response({"error": "team"}, status=404)
    if not t:
        day = time.time() - 86400
        STARTS[who] = [x for x in STARTS[who] if x > day]
        if len(STARTS[who]) >= K.GAMES_PER_DAY and not (user and (user.get("username") or "").lower() in K.ADMINS):
            return web.json_response({"error": "daily", "limit": K.GAMES_PER_DAY}, status=429)
        STARTS[who].append(time.time())
    nums = own.team_nums(t) if t else DEFAULT_NUMBERS
    if not t and isinstance(data.get("nums"), dict):
        try:
            n = {k: float(data["nums"][k]) for k in ("budget", "cpl", "check", "conv")}
            if min(n["budget"], n["cpl"], n["check"]) > 0 and 0 < n["conv"] <= 100:
                nums = n
        except Exception:
            pass
    sid = secrets.token_urlsafe(18)
    s = dict(created=time.time(), who=who, user=user, team=t["id"] if t else None, pid=None, alias="", nums=dict(nums), calls=0,
             results=[None] * len(CLIENTS))
    if t:
        alias = " ".join(str(data.get("alias") or "").split())[:40] or "Менеджер"
        uid = user["id"] if user else -abs(hash(who)) % (10 ** 12)
        s["alias"], s["pid"] = alias, own.start_player(t["id"], uid, alias)
    SESSIONS[sid] = s
    return web.json_response({"sid": sid, "nums": s["nums"], "team": {"title": t["title"]} if t else None,
                              "name": (user or {}).get("first_name", "")})


async def api_team(req):
    t = own.team(req.query.get("team", ""))
    return web.json_response({"title": t["title"], "nums": own.team_nums(t)} if t else {"error": "team"}, status=200 if t else 404)


async def api_client(req):
    data = await req.json()
    s = session(req, data)
    g = game_of(s, data)
    try:
        r = await K.llm_json(K.client_prompt(g), dict, K.MODEL_FAST, temperature=0.7, max_tokens=400)
    except Exception as e:
        log.warning("client: %s", e)
        return web.json_response({"error": "llm"}, status=502)
    return web.json_response({"reply": str(r.get("reply") or "…").strip(), "outcome": str(r.get("outcome") or "continue").lower()})


async def api_review(req):
    data = await req.json()
    s = session(req, data)
    g = game_of(s, data)
    outcome = "meeting" if data.get("outcome") == "meeting" else "lost"
    turns = K.manager_turns(g.log)
    vt = asyncio.create_task(K.llm_json(K.verdict_prompt(g, outcome), dict, K.MODEL_SMART, temperature=0.4, max_tokens=1200))
    st = asyncio.create_task(K.llm_json(K.steps_prompt(g, turns), dict, K.MODEL_SMART, temperature=0.4, max_tokens=2500)) if turns else None
    v = steps = None
    try:
        v = await vt
    except Exception as e:
        log.warning("verdict: %s", e)
    try:
        steps = (await st).get("steps", []) if st else []
    except Exception as e:
        log.warning("steps: %s", e)
    merged = [dict(x, **(steps[k] if steps and k < len(steps) and isinstance(steps[k], dict) else {})) for k, x in enumerate(turns)] if steps is not None else None
    s["results"][g.i] = dict(lost=outcome != "meeting", v=v)
    if s["pid"]:
        try:
            own.save_result(s["pid"], g.i, dict(lost=outcome != "meeting", v=v, steps=steps or [], log=g.log))
        except Exception as e:
            log.warning("save_result: %s", e)
    return web.json_response({"v": v, "steps": merged})


async def api_finish(req):
    data = await req.json()
    s = SESSIONS.get(str(data.get("sid", "")))
    if not s or s.get("finished"):
        return web.json_response({"ok": True})
    s["finished"] = True
    g = SimpleNamespace(results=s["results"])
    K.save_stats(g)
    if s["team"] and s["pid"]:
        own.finish_player(s["pid"])
        t = own.team(s["team"])
        done = [r for r in s["results"] if r]
        lost = sum(1 for r in done if r["lost"])
        tot = K.till(s["nums"])["total"]
        share = lost / len(done) if done else 0
        if t and BOT:
            try:
                await BOT.send_message(t["owner_chat"], f"👤 <b>{K.esc(s['alias'])}</b> – проверка пройдена, отдел «{K.esc(t['title'])}».\n"
                                       f"Встречи – {len(done) - lost} из {len(done)}, потери – около <b>{K.short(share * tot)}</b> в месяц.",
                                       reply_markup=K.InlineKeyboardMarkup(inline_keyboard=[[K.InlineKeyboardButton(text="📊 Отчет по отделу", callback_data=f"r:{t['id']}")]]))
            except Exception as e:
                log.warning("notify owner: %s", e)
    return web.json_response({"ok": True})


async def index(req):
    resp = web.FileResponse(os.path.join(WEB_DIR, "index.html"))
    resp.headers["Cache-Control"] = "no-cache"
    return resp


async def start(bot, kmod):
    global K, BOT
    K, BOT = kmod, bot
    app = web.Application(client_max_size=256 * 1024)
    app.router.add_get("/", index)
    app.router.add_get("/api/team", api_team)
    app.router.add_post("/api/session", api_session)
    app.router.add_post("/api/client", api_client)
    app.router.add_post("/api/review", api_review)
    app.router.add_post("/api/finish", api_finish)
    app.router.add_static("/static/", WEB_DIR)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "127.0.0.1", PORT).start()
    log.info("web on 127.0.0.1:%s", PORT)
    return runner
