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
from game_data import COUNTRIES, NICHES, niche

log = logging.getLogger("kassa.web")
WEB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")
PORT = int(os.environ.get("WEB_PORT", "8090"))
MAX_CALLS = 90           # запросов к нейросети на одну игру
SESSION_TTL = 6 * 3600
SESSIONS: dict[str, dict] = {}
STARTS: dict[str, list] = defaultdict(list)
K = None    # модуль kassa_bot (промпты, нейросеть, расчеты)
BOT = None


def _store_path():
    return os.path.join(os.environ.get("BOT_DATA", "/var/lib/kassa-bot"), "web_sessions.json")


def save_sessions():
    """Игры в процессе хранятся на диске, чтобы обновление сервера не обрывало их."""
    try:
        p = _store_path()
        with open(p + ".tmp", "w") as f:
            json.dump(dict(sessions=SESSIONS, starts=STARTS), f, ensure_ascii=False)
        os.replace(p + ".tmp", p)
    except Exception as e:
        log.warning("save sessions: %s", e)


def load_sessions():
    try:
        with open(_store_path()) as f:
            d = json.load(f)
        SESSIONS.update(d.get("sessions", {}))
        STARTS.update({k: list(v) for k, v in d.get("starts", {}).items()})
        gc()
        log.info("restored %s web sessions", len(SESSIONS))
    except FileNotFoundError:
        pass
    except Exception as e:
        log.warning("load sessions: %s", e)


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
        if not isinstance(m, dict) or m.get("who") not in ("client", "manager", "pause"):
            continue
        out.append(dict(who=m["who"], text="" if m["who"] == "pause" else str(m.get("text", ""))[:2000]))
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
    n = niche(s["niche"])
    pos = int(data.get("i", -1))   # номер клиента в этой игре, у сервера – номер профиля в нише
    if not 0 <= pos < len(s["pick"]):
        raise web.HTTPBadRequest(text=json.dumps({"error": "client"}), content_type="application/json")
    i = s["pick"][pos]
    tr = (s.get("traits") or [None] * len(s["pick"]))[pos] or {}
    g = SimpleNamespace(i=i, log=clean_log(data.get("log")), turns=min(n["max_turns"], max(1, int(data.get("turns", 1)))), nums=s["nums"],
                        niche=n["id"], temper=tr.get("temper"), ghost=bool(tr.get("ghost")))
    if not g.log or g.log[0]["who"] != "client":
        g.log.insert(0, dict(who="client", text=n["clients"][i]["first"]))
    return g


def public_client(c):
    return dict(name=c["name"], short=c["name"][:2] if c["name"].startswith("Ай") else c["name"][0], sub=c["sub"], first=c["first"],
                source=c.get("source", ""))


def public_niche(n):
    """Что видит страница: без скрытых деталей клиентов и без правил разбора. Клиентов игры страница получает при старте."""
    per = min(n.get("per_game", 5), len(n["clients"]))
    random_pick = per < len(n["clients"])
    return dict(id=n["id"], title=n["title"], project_name=n["project_name"], max_turns=n["max_turns"], nums=n["nums"], page=n["page"],
                win=n["win"], win_sys=n["win_sys"], wins=n["wins"], reach=n["reach"], files=n["files"], random=random_pick,
                country=n.get("country", "kz"), country_name=COUNTRIES.get(n.get("country", "kz"), ""), cur=n.get("cur", "₸"),
                public=bool(n.get("public")), card=n.get("card", ""), stages=n.get("stages", []), source=n.get("source", ""),
                clients=[dict(name=f"Клиент {k + 1}", short=str(k + 1), sub="откроется в игре", first="") for k in range(per)] if random_pick
                else [public_client(c) for c in n["clients"]])


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
        want = data.get("niche") if data.get("niche") in NICHES else "realestate"
        # закрытые ниши клиентов (ProPeptides) – подарок компании, без дневного лимита
        unlimited = (user and (user.get("username") or "").lower() in K.ADMINS) or own.vip_ok(data.get("vip")) or not NICHES[want].get("public")
        if len(STARTS[who]) >= K.GAMES_PER_DAY and not unlimited:
            return web.json_response({"error": "daily", "limit": K.GAMES_PER_DAY}, status=429)
        if not unlimited:
            STARTS[who].append(time.time())
    nid = own.team_niche(t)["id"] if t else (data.get("niche") if data.get("niche") in NICHES else "realestate")
    nc = niche(nid)
    nums = own.team_nums(t) if t else nc["nums"]
    if not t and isinstance(data.get("nums"), dict):
        try:
            n = {k: float(data["nums"][k]) for k in ("budget", "cpl", "check", "conv")}
            if min(n["budget"], n["cpl"], n["check"]) > 0 and 0 < n["conv"] <= 100:
                nums = n
        except Exception:
            pass
    sid = secrets.token_urlsafe(18)
    s = dict(created=time.time(), who=who, user=user, team=t["id"] if t else None, pid=None, alias="", nums=dict(nums), calls=0,
             niche=nid, results=[None] * len(nc["clients"]), pick=own.team_pick(t) if t else own.pick_clients(nc))
    s["traits"] = K.roll_traits(len(s["pick"]), seed=("team:" + t["id"]) if t else None)   # у отдела характеры одинаковые для всех
    if t:
        alias = " ".join(str(data.get("alias") or "").split())[:40] or "Менеджер"
        # вне Telegram менеджеров различаем по метке браузера, а не по IP – в офисе IP у всех один
        dev = str(data.get("dev") or "")[:64] or secrets.token_hex(8)
        uid = user["id"] if user else -(int(hashlib.sha256(dev.encode()).hexdigest()[:12], 16))
        s["alias"], s["pid"] = alias, own.start_player(t["id"], uid, alias)
    SESSIONS[sid] = s
    save_sessions()
    return web.json_response({"sid": sid, "nums": s["nums"], "niche": nid, "clients": [public_client(nc["clients"][i]) for i in s["pick"]], "team": {"title": t["title"]} if t else None,
                              "name": (user or {}).get("first_name", "")})


async def api_team(req):
    t = own.team(req.query.get("team", ""))
    return web.json_response({"title": t["title"], "nums": own.team_nums(t), "niche": own.team_niche(t)["id"]} if t else {"error": "team"},
                             status=200 if t else 404)


# ниши, которые готовим следующими – показываем на экране выбора с пометкой «скоро»
SOON = []


async def api_niches(req):
    lst = [dict(id=n["id"], title=n["title"], country=n.get("country", "kz"), card=n.get("card", "")) for n in NICHES.values() if n.get("public")]
    return web.json_response(dict(countries=COUNTRIES, niches=lst, soon=SOON), headers={"Cache-Control": "no-cache"})


async def api_niche(req):
    return web.json_response(public_niche(niche(req.query.get("n"))), headers={"Cache-Control": "no-cache"})


async def api_client(req):
    data = await req.json()
    s = session(req, data)
    g = game_of(s, data)
    try:
        r = await K.llm_json(K.client_prompt(g), dict, K.MODEL_FAST, temperature=0.7, max_tokens=400)
    except Exception as e:
        log.warning("client: %s", e)
        return web.json_response({"error": "llm"}, status=502)
    outcome = str(r.get("outcome") or "continue").lower()
    reply = str(r.get("reply") or "").strip()
    if "silent" in outcome:
        pauses = sum(1 for m in g.log if m["who"] == "pause")
        if not g.ghost or g.turns < 3:          # пропадать можно только «призракам» и не в самом начале
            outcome = "continue"
        elif pauses >= 2:                       # уже дважды пропадал – дальше уходит совсем
            outcome, reply = "lost", ""
        else:
            return web.json_response({"reply": "", "outcome": "silent"})
    return web.json_response({"reply": reply or "…", "outcome": outcome})


async def api_review(req):
    data = await req.json()
    s = session(req, data)
    g = game_of(s, data)
    outcome = "meeting" if data.get("outcome") == "meeting" else "lost"
    turns = K.manager_turns(g.log)
    vt = asyncio.create_task(K.get_verdict(g, outcome))
    st = asyncio.create_task(K.llm_json(K.steps_prompt(g, turns), dict, K.MODEL_SMART, temperature=0.4, max_tokens=5000)) if turns else None
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
    save_sessions()
    if s["pid"]:
        try:
            own.save_result(s["pid"], g.i, dict(lost=outcome != "meeting", v=v, steps=merged or [], log=g.log))
        except Exception as e:
            log.warning("save_result: %s", e)
        if not s.get("start_sent"):
            s["start_sent"] = True
            await notify_owner(s, f"👤 <b>{K.esc(s['alias'])}</b> проходит проверку, отдел «{{team}}». Первый клиент – "
                                  f"{niche(s['niche'])['win_done'] if outcome == 'meeting' else 'слит'}. Итог пришлю, когда закончит.")
    return web.json_response({"v": v, "steps": merged})


async def notify_owner(s, text):
    t = own.team(s["team"]) if s.get("team") else None
    if not t or not BOT:
        return
    try:
        await BOT.send_message(t["owner_chat"], text.replace("{team}", K.esc(t["title"])),
                               reply_markup=K.InlineKeyboardMarkup(inline_keyboard=[[K.InlineKeyboardButton(text="📊 Отчет по отделу", callback_data=f"r:{t['id']}")]]))
    except Exception as e:
        log.warning("notify owner: %s", e)


def score(s):
    done = [r for r in s["results"] if r]
    lost = sum(1 for r in done if r["lost"])
    tot = K.till(s["nums"])["total"]
    return done, lost, (lost / len(done) if done else 0) * tot


async def api_ping(req):
    """Жива ли игра на сервере – страница восстанавливает переписку после перезагрузки или сворачивания."""
    try:
        data = await req.json()
    except Exception:
        data = {}
    s = SESSIONS.get(str(data.get("sid", "")))
    return web.json_response({"ok": bool(s and not s.get("finished"))})


async def partial_later(sid, calls, delay=1800):
    await asyncio.sleep(delay)
    s = SESSIONS.get(sid)
    if not s:
        return
    s["partial_wait"] = False
    if s.get("finished") or s.get("partial_sent") or s["calls"] != calls:
        return
    done, lost, loss = score(s)
    n = niche(s["niche"])
    s["partial_sent"] = True
    save_sessions()
    await notify_owner(s, f"👤 <b>{K.esc(s['alias'])}</b> вышел из игры, не дойдя до конца, отдел «{{team}}».\n"
                          f"Пока пройдено клиентов – {len(done)} из {len(s['pick'])}, {n['wins']} – {len(done) - lost}, потери – около <b>{K.short(loss, n['cur'])}</b> в месяц. "
                          "Все пройденное уже есть в отчете. Если вернется и закончит, пришлю итог.")


async def api_finish(req):
    # sendBeacon присылает text/plain – читаем тело как JSON вручную
    try:
        data = json.loads(await req.text() or "{}")
    except Exception:
        data = {}
    s = SESSIONS.get(str(data.get("sid", "")))
    if not s or s.get("finished"):
        return web.json_response({"ok": True})
    done, lost, loss = score(s)
    n = niche(s["niche"])
    if data.get("partial"):
        # менеджер закрыл игру, не дойдя до конца
        # свернуть приложение – еще не уйти: сообщаем собственнику, только если 30 минут не было ни одного действия
        if s["team"] and done and not s.get("partial_sent") and not s.get("partial_wait"):
            s["partial_wait"] = True
            asyncio.create_task(partial_later(str(data.get("sid", "")), s["calls"]))
        return web.json_response({"ok": True})
    s["finished"] = True
    save_sessions()
    K.save_stats(SimpleNamespace(results=s["results"]))
    if s["team"] and s["pid"]:
        own.finish_player(s["pid"])
        await notify_owner(s, f"👤 <b>{K.esc(s['alias'])}</b> – проверка пройдена, отдел «{{team}}».\n"
                              f"{n['wins'].capitalize()} – {len(done) - lost} из {len(done)}, потери – около <b>{K.short(loss, n['cur'])}</b> в месяц.")
    return web.json_response({"ok": True})


async def index(req):
    resp = web.FileResponse(os.path.join(WEB_DIR, "index.html"))
    resp.headers["Cache-Control"] = "no-cache"
    return resp


async def start(bot, kmod):
    global K, BOT
    K, BOT = kmod, bot
    load_sessions()
    app = web.Application(client_max_size=256 * 1024)
    app.router.add_get("/", index)
    app.router.add_get("/favicon.ico", lambda req: web.FileResponse(os.path.join(WEB_DIR, "icon-180.png")))
    app.router.add_get("/api/team", api_team)
    app.router.add_get("/api/niche", api_niche)
    app.router.add_get("/api/niches", api_niches)
    app.router.add_post("/api/session", api_session)
    app.router.add_post("/api/client", api_client)
    app.router.add_post("/api/review", api_review)
    app.router.add_post("/api/finish", api_finish)
    app.router.add_post("/api/ping", api_ping)
    app.router.add_static("/static/", WEB_DIR)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "127.0.0.1", PORT).start()
    log.info("web on 127.0.0.1:%s", PORT)
    return runner
