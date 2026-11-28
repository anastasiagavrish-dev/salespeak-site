"""Статистика игр «Касса тает» и переписки игроков – для Анастасии (/stats, /games, /export в боте).
Пишется из веб-версии игры (Telegram Mini App и браузер). Храним 180 дней."""
import html
import json
import time
from collections import Counter

import owner as own
from game_data import COUNTRIES, niche

KEEP_DAYS = 180
_ready = False


def db():
    global _ready
    d = own.db()
    if not _ready:
        d.executescript("""
        CREATE TABLE IF NOT EXISTS play_games(sid TEXT PRIMARY KEY, created INT, last INT, who TEXT, tg_id INT, username TEXT, first_name TEXT,
                                              source TEXT, team TEXT, alias TEXT, niche TEXT, n_clients INT, reached INT DEFAULT 0,
                                              done INT DEFAULT 0, meetings INT DEFAULT 0, finished INT);
        CREATE INDEX IF NOT EXISTS play_games_created ON play_games(created);
        CREATE TABLE IF NOT EXISTS play_dialogs(sid TEXT, pos INT, client TEXT, outcome TEXT, stage TEXT, turns INT, log TEXT, ts INT,
                                                PRIMARY KEY(sid, pos));
        """)
        cut = int(time.time()) - KEEP_DAYS * 86400
        d.execute("DELETE FROM play_dialogs WHERE sid IN (SELECT sid FROM play_games WHERE created < ?)", (cut,))
        d.execute("DELETE FROM play_games WHERE created < ?", (cut,))
        d.commit()
        _ready = True
    return d


def _safe(fn):
    """Статистика не должна ломать игру – любые ошибки только в лог."""
    def wrap(*a, **kw):
        try:
            return fn(*a, **kw)
        except Exception as e:
            import logging
            logging.getLogger("kassa.stats").warning("%s: %s", fn.__name__, e)
    return wrap


@_safe
def start(sid, s):
    u = s.get("user") or {}
    db().execute("INSERT OR REPLACE INTO play_games(sid, created, last, who, tg_id, username, first_name, source, team, alias, niche, n_clients) "
                 "VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                 (sid, int(s["created"]), int(time.time()), s["who"], u.get("id"), u.get("username") or "", u.get("first_name") or "",
                  "tg" if u else "web", s.get("team"), s.get("alias") or "", s["niche"], len(s["pick"])))
    db().commit()


@_safe
def touch(sid, pos, client, log):
    """Игрок пишет клиенту номер pos (с нуля) – дошел до него. Незаконченную переписку тоже сохраняем, чтобы видеть, где бросили."""
    now = int(time.time())
    db().execute("UPDATE play_games SET last=?, reached=MAX(reached, ?) WHERE sid=?", (now, pos + 1, sid))
    db().execute("INSERT INTO play_dialogs(sid, pos, client, outcome, stage, turns, log, ts) VALUES(?,?,?,'open','',?,?,?) "
                 "ON CONFLICT(sid, pos) DO UPDATE SET log=excluded.log, turns=excluded.turns, ts=excluded.ts WHERE play_dialogs.outcome='open'",
                 (sid, pos, client, sum(1 for m in log if m.get("who") == "manager"), json.dumps(log, ensure_ascii=False), now))
    db().commit()


@_safe
def dialog(sid, pos, client, outcome, verdict, log):
    turns = sum(1 for m in log if m.get("who") == "manager")
    stage = ((verdict or {}).get("stage") or "").strip()
    db().execute("INSERT OR REPLACE INTO play_dialogs(sid, pos, client, outcome, stage, turns, log, ts) VALUES(?,?,?,?,?,?,?,?)",
                 (sid, pos, client, outcome, stage, turns, json.dumps(log, ensure_ascii=False), int(time.time())))
    r = db().execute("SELECT COUNT(*) n, SUM(outcome='meeting') m FROM play_dialogs WHERE sid=? AND outcome!='open'", (sid,)).fetchone()
    db().execute("UPDATE play_games SET last=?, reached=MAX(reached, ?), done=?, meetings=? WHERE sid=?",
                 (int(time.time()), pos + 1, r["n"], r["m"] or 0, sid))
    db().commit()


@_safe
def finish(sid):
    db().execute("UPDATE play_games SET finished=?, last=? WHERE sid=?", (int(time.time()), int(time.time()), sid))
    db().commit()


# ---------------- отчеты ----------------
def niche_title(nid):
    n = niche(nid)
    c = COUNTRIES.get(n.get("country", ""), "")
    return n["title"] + (f" ({c})" if c else "")


def pct(a, b):
    return f"{round(100 * a / b)}%" if b else "–"


def summary(days):
    """Текст для /stats: воронка игры, где бросают, ниши, где сливают клиентов."""
    since = int(time.time()) - days * 86400
    g = db().execute("SELECT * FROM play_games WHERE created >= ?", (since,)).fetchall()
    if not g:
        return f"За {days} дн. игр нет."
    fin = [x for x in g if x["finished"]]
    players = len({x["who"] for x in g})
    tg = sum(1 for x in g if x["source"] == "tg")
    team = sum(1 for x in g if x["team"])
    lines = [f"<b>Игра за {days} дн.</b>",
             f"Начали – {len(g)}, уникальных игроков – {players}",
             f"Из Telegram – {tg}, из браузера – {len(g) - tg}" + (f", по ссылкам отделов – {team}" if team else ""),
             f"Дошли до итога – {len(fin)} ({pct(len(fin), len(g))})"]
    # докуда доходят: последний клиент, которому игрок написал
    gone = [x for x in g if not x["finished"]]
    if gone:
        cnt = Counter(x["reached"] for x in gone)
        parts = [f"не начали переписку – {cnt[0]}"] if cnt[0] else []
        parts += [f"на {k}-м клиенте – {cnt[k]}" for k in sorted(cnt) if k]
        lines.append("\n<b>Где бросили</b> (" + str(len(gone)) + ")\n" + "\n".join("• " + p for p in parts))
    if fin:
        avg = sum(x["meetings"] for x in fin) / len(fin)
        full = sum(1 for x in fin if x["done"] and x["meetings"] == x["done"])
        lines.append(f"\n<b>Результат у дошедших до итога</b>\nВ среднем довели до цели {str(round(avg, 1)).replace('.', ',')} клиента из {round(sum(x['n_clients'] for x in fin) / len(fin))}, "
                     f"никого не слили – {full}")
    nc = Counter(x["niche"] for x in g)
    lines.append("\n<b>Ниши</b>\n" + "\n".join(f"• {niche_title(k)} – {v}" for k, v in nc.most_common(8)))
    d = db().execute("SELECT d.outcome, d.stage FROM play_dialogs d JOIN play_games p ON p.sid=d.sid WHERE p.created >= ? AND d.outcome!='open'", (since,)).fetchall()
    if d:
        lost = [x for x in d if x["outcome"] != "meeting"]
        lines.append(f"\n<b>Переписки</b>\nВсего – {len(d)}, до цели – {len(d) - len(lost)} ({pct(len(d) - len(lost), len(d))}), слито – {len(lost)}")
        st = Counter(x["stage"] for x in lost if x["stage"])
        if st:
            lines.append("<b>На каком этапе сливают</b>\n" + "\n".join(f"• {html.escape(k)} – {v}" for k, v in st.most_common(6)))
    return "\n".join(lines)


def who_line(x):
    if x["team"]:
        name = f"{x['alias'] or 'менеджер'} (отдел)"
    elif x["username"]:
        name = "@" + x["username"]
    elif x["first_name"]:
        name = x["first_name"]
    else:
        name = "браузер"
    return name


def recent(offset=0, limit=10):
    return db().execute("SELECT * FROM play_games WHERE reached > 0 ORDER BY created DESC LIMIT ? OFFSET ?", (limit, offset)).fetchall()


def button_text(x):
    t = time.strftime("%d.%m %H:%M", time.localtime(x["created"]))
    res = f"{x['meetings']}/{x['done']}" if x["done"] else "0"
    end = "✅" if x["finished"] else f"⏸ {x['reached']}-й"
    return f"{t} · {niche(x['niche'])['title']} · {who_line(x)} · {res} {end}"[:64]


def game(sid):
    return db().execute("SELECT * FROM play_games WHERE sid=?", (sid,)).fetchone()


def dialogs(sid):
    return db().execute("SELECT * FROM play_dialogs WHERE sid=? ORDER BY pos", (sid,)).fetchall()


def transcript_parts(x):
    """Переписки одной игры для Telegram – список сообщений (HTML)."""
    e = html.escape
    head = (f"<b>{e(niche_title(x['niche']))}</b> · {e(who_line(x))}\n"
            f"{time.strftime('%d.%m.%Y %H:%M', time.localtime(x['created']))} · {'из Telegram' if x['source'] == 'tg' else 'из браузера'}\n"
            f"Дошел до клиента {x['reached']} из {x['n_clients']}, {'игра закончена' if x['finished'] else 'итог не открыл'}. "
            f"До цели – {x['meetings']} из {x['done']} законченных переписок.")
    out = [head]
    for d in dialogs(x["sid"]):
        mark = {"meeting": "🟢 до цели", "lost": "🔴 слит"}.get(d["outcome"], "⏸ не закончена")
        body = [f"<b>{d['pos'] + 1}. {e(d['client'])}</b> – {mark}" + (f", этап «{e(d['stage'])}»" if d["stage"] else "")]
        for m in json.loads(d["log"]):
            if m["who"] == "pause":
                body.append("<i>…клиент молчит сутки</i>")
            else:
                body.append(f"<i>{'Клиент' if m['who'] == 'client' else 'Менеджер'}:</i> {e(m['text'])}")
        out.append("\n".join(body))
    return out


def export_html(days):
    """Все игры за период одним HTML-файлом – удобно читать с телефона."""
    e = html.escape
    since = int(time.time()) - days * 86400
    rows = db().execute("SELECT * FROM play_games WHERE created >= ? AND reached > 0 ORDER BY created DESC", (since,)).fetchall()
    parts = [f"<!doctype html><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'><title>Касса тает – переписки</title>"
             "<style>body{font:15px/1.5 system-ui,sans-serif;max-width:760px;margin:0 auto;padding:16px;color:#17152b}"
             "h2{font-size:17px;margin:32px 0 4px;border-top:2px solid #4b3fe1;padding-top:12px}h3{font-size:15px;margin:18px 0 6px}"
             ".m{margin:4px 0;padding:6px 10px;border-radius:10px;background:#f1f0fb}.mg{background:#e9f7d0}.meta{color:#666;font-size:13px}</style>",
             f"<h1>Касса тает – переписки за {days} дн.</h1><p class=meta>Игр с перепиской – {len(rows)}. Выгружено {time.strftime('%d.%m.%Y %H:%M')}</p>"]
    for x in rows:
        parts.append(f"<h2>{e(niche_title(x['niche']))} · {e(who_line(x))}</h2><p class=meta>{time.strftime('%d.%m.%Y %H:%M', time.localtime(x['created']))} · "
                     f"{'Telegram' if x['source'] == 'tg' else 'браузер'} · дошел до клиента {x['reached']} из {x['n_clients']} · "
                     f"{'закончил' if x['finished'] else 'не закончил'} · до цели {x['meetings']} из {x['done']}</p>")
        for d in dialogs(x["sid"]):
            parts.append(f"<h3>{d['pos'] + 1}. {e(d['client'])} – {dict(meeting='🟢 до цели', lost='🔴 слит').get(d['outcome'], '⏸ не закончена')}"
                         f"{' · этап «' + e(d['stage']) + '»' if d['stage'] else ''}</h3>")
            for m in json.loads(d["log"]):
                if m["who"] == "pause":
                    parts.append("<p class=meta>…клиент молчит сутки</p>")
                else:
                    parts.append(f"<p class='m{' mg' if m['who'] == 'manager' else ''}'><b>{'Клиент' if m['who'] == 'client' else 'Менеджер'}:</b> {e(m['text'])}</p>")
    return "\n".join(parts), len(rows)
