"""Режим собственника: отделы, коды доступа, результаты менеджеров и отчет.
Имен менеджеров бот не спрашивает – только псевдоним, который менеджер вводит сам."""
import html
import json
import random
import os
import secrets
import sqlite3
import string
import time

from game_data import niche

DB = None


def db():
    global DB
    if DB is None:
        d = os.environ.get("BOT_DATA", "/var/lib/kassa-bot")
        os.makedirs(d, exist_ok=True)
        DB = sqlite3.connect(os.path.join(d, "kassa.db"), check_same_thread=False)
        DB.row_factory = sqlite3.Row
        DB.executescript("""
        CREATE TABLE IF NOT EXISTS codes(code TEXT PRIMARY KEY, created INT, note TEXT, used_by INT, used_at INT);
        CREATE TABLE IF NOT EXISTS teams(id TEXT PRIMARY KEY, owner_id INT, owner_chat INT, title TEXT, code TEXT, nums TEXT, created INT);
        CREATE TABLE IF NOT EXISTS players(id INTEGER PRIMARY KEY AUTOINCREMENT, team_id TEXT, tg_id INT, alias TEXT,
                                           started INT, finished INT, results TEXT);
        CREATE INDEX IF NOT EXISTS players_team ON players(team_id);
        CREATE TABLE IF NOT EXISTS vip(key TEXT PRIMARY KEY, note TEXT, created INT);
        """)
        # ниша игры (недвижимость, пептиды…) – у кода и у отдела
        for tbl in ("codes", "teams"):
            if "niche" not in [r[1] for r in DB.execute(f"PRAGMA table_info({tbl})")]:
                DB.execute(f"ALTER TABLE {tbl} ADD COLUMN niche TEXT DEFAULT 'realestate'")
        # какие клиенты из ниши достались отделу – у всех менеджеров одни и те же, чтобы сравнивать
        if "pick" not in [r[1] for r in DB.execute("PRAGMA table_info(teams)")]:
            DB.execute("ALTER TABLE teams ADD COLUMN pick TEXT")
        DB.commit()
    return DB


def _rand(n, alphabet=string.ascii_uppercase + string.digits):
    return "".join(secrets.choice(alphabet) for _ in range(n))


# ---------------- безлимитные ключи (игра без дневного лимита) ----------------
def new_vip(note=""):
    key = _rand(16, string.ascii_letters + string.digits)
    db().execute("INSERT INTO vip(key, note, created) VALUES(?,?,?)", (key, note, int(time.time())))
    db().commit()
    return key


def vip_ok(key):
    key = str(key or "").strip()
    return bool(key) and db().execute("SELECT 1 FROM vip WHERE key=?", (key,)).fetchone() is not None


# ---------------- коды доступа ----------------
def new_code(note="", niche_id="realestate"):
    code = "KT-" + _rand(6, "ABCDEFGHJKLMNPQRSTUVWXYZ23456789")
    db().execute("INSERT INTO codes(code, created, note, niche) VALUES(?,?,?,?)", (code, int(time.time()), note, niche_id))
    db().commit()
    return code


def list_codes(limit=20):
    return db().execute("SELECT * FROM codes ORDER BY created DESC LIMIT ?", (limit,)).fetchall()


def use_code(code, owner_id):
    code = code.strip().upper()
    r = db().execute("SELECT * FROM codes WHERE code=?", (code,)).fetchone()
    if not r:
        return None, "Такого кода нет. Проверьте, что скопировали его целиком."
    if r["used_by"] and r["used_by"] != owner_id:
        return None, "Этот код уже использован."
    db().execute("UPDATE codes SET used_by=?, used_at=? WHERE code=?", (owner_id, int(time.time()), code))
    db().commit()
    return code, ""


def code_niche(code):
    r = db().execute("SELECT niche FROM codes WHERE code=?", (code,)).fetchone()
    return (r and r["niche"]) or "realestate"


# ---------------- отделы ----------------
def create_team(owner_id, owner_chat, title, code, nums, niche_id="realestate"):
    tid = _rand(8, string.ascii_lowercase + string.digits)
    db().execute("INSERT INTO teams(id, owner_id, owner_chat, title, code, nums, created, niche) VALUES(?,?,?,?,?,?,?,?)",
                 (tid, owner_id, owner_chat, title, code, json.dumps(nums), int(time.time()), niche_id))
    db().commit()
    return tid


def team(tid):
    return db().execute("SELECT * FROM teams WHERE id=?", (tid,)).fetchone()


def owner_teams(owner_id):
    return db().execute("SELECT * FROM teams WHERE owner_id=? ORDER BY created DESC", (owner_id,)).fetchall()


def team_nums(t):
    return json.loads(t["nums"])


def team_niche(t):
    return niche(t["niche"] if t and "niche" in t.keys() else None)


def pick_clients(n):
    """Случайные клиенты на одну игру: в нише может быть больше профилей, чем клиентов в игре."""
    k = min(n.get("per_game", 5), len(n["clients"]))
    return random.sample(range(len(n["clients"])), k) if k < len(n["clients"]) else list(range(k))


def team_pick(t):
    n = team_niche(t)
    if t["pick"] if "pick" in t.keys() else None:
        p = [i for i in json.loads(t["pick"]) if 0 <= i < len(n["clients"])]
        if p:
            return p
    p = pick_clients(n)
    db().execute("UPDATE teams SET pick=? WHERE id=?", (json.dumps(p), t["id"]))
    db().commit()
    return p


# ---------------- менеджеры ----------------
def start_player(tid, tg_id, alias):
    old = db().execute("SELECT * FROM players WHERE team_id=? AND tg_id=?", (tid, tg_id)).fetchone()
    empty = json.dumps([None] * len(team_niche(team(tid))["clients"]))
    if old:
        db().execute("UPDATE players SET alias=?, started=?, finished=NULL, results=? WHERE id=?", (alias, int(time.time()), empty, old["id"]))
        db().commit()
        return old["id"]
    cur = db().execute("INSERT INTO players(team_id, tg_id, alias, started, results) VALUES(?,?,?,?,?)", (tid, tg_id, alias, int(time.time()), empty))
    db().commit()
    return cur.lastrowid


def player_done(tid, tg_id):
    r = db().execute("SELECT finished FROM players WHERE team_id=? AND tg_id=?", (tid, tg_id)).fetchone()
    return bool(r and r["finished"])


def save_result(pid, i, res):
    r = db().execute("SELECT results FROM players WHERE id=?", (pid,)).fetchone()
    results = json.loads(r["results"])
    results[i] = res
    db().execute("UPDATE players SET results=? WHERE id=?", (json.dumps(results, ensure_ascii=False), pid))
    db().commit()


def finish_player(pid):
    db().execute("UPDATE players SET finished=? WHERE id=?", (int(time.time()), pid))
    db().commit()


def player(pid):
    return db().execute("SELECT * FROM players WHERE id=?", (pid,)).fetchone()


def players(tid):
    rows = db().execute("SELECT * FROM players WHERE team_id=? ORDER BY started", (tid,)).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["results"] = json.loads(r["results"] or "[]")
        out.append(d)
    return out


# ---------------- расчеты ----------------
def player_stats(p, total):
    done = [r for r in p["results"] if r]
    lost = sum(1 for r in done if r.get("lost"))
    share = lost / len(done) if done else 0
    return dict(done=len(done), meetings=len(done) - lost, lost=lost, loss=share * total)


def team_errors(ps, limit=40):
    out = []
    for p in ps:
        for r in p["results"]:
            if r and r.get("v"):
                out += [e for e in (r["v"].get("errors") or [])]
    return out[:limit]


def team_summary_prompt(t, ps, style, voice=""):
    n = team_niche(t)
    lines = []
    for p in ps:
        for k, r in enumerate(p["results"]):
            if r and r.get("v"):
                v = r["v"]
                lines.append(f"{p['alias']} · {n['clients'][k]['name']} · {n['win'] if not r.get('lost') else 'слит'} · этап «{v.get('stage', '')}» · ошибки: "
                             + "; ".join(v.get("errors") or []))
    return f"""Ты – Анастасия Гавриш, эксперт по продажам. Собственник проверил свой отдел продаж в тренажере ({n['project_name']}) – менеджеры переписывались с одними и теми же 5 клиентами, задача – {n['goal']}. Ниже результаты по каждой переписке. {style}

{voice}

{n['rules']}

Результаты:
{chr(10).join(lines)}

Напиши выводы для собственника. Верни строго JSON без markdown:
{{"headline": "главный вывод одной фразой",
 "patterns": ["ошибка, которая повторяется у нескольких менеджеров, и что она стоит отделу"] (2–4 пункта),
 "growth": ["точка роста – что внедрить в отделе, чтобы перестать сливать клиентов"] (2–4 пункта),
 "audit": "одно-два предложения, что стоит проверить на настоящих переписках отдела"}}"""


# ---------------- HTML-отчет ----------------
def _e(s):
    return html.escape(str(s or ""))


def _short(n, cur="₸"):
    if n >= 1e9:
        return f"{n / 1e9:.1f}".replace(".", ",") + " млрд " + cur
    if n >= 1e6:
        return f"{round(n / 1e6)} млн " + cur
    return f"{round(n):,}".replace(",", " ") + " " + cur


def report_html(t, ps, total, summary=None):
    n = team_niche(t)
    CLIENTS = n["clients"]
    pick = team_pick(t)
    rows, details = [], []
    ranked = sorted(ps, key=lambda p: (-player_stats(p, total)["meetings"], player_stats(p, total)["loss"]))
    for p in ranked:
        s = player_stats(p, total)
        marks = "".join("<span class='m n'>–</span>" if not r else (f"<span class='m bad' title='{_e(CLIENTS[k]['name'])}'>✕</span>" if r.get("lost")
                        else f"<span class='m ok' title='{_e(CLIENTS[k]['name'])}'>✓</span>") for k, r in ((k, p["results"][k] if k < len(p["results"]) else None) for k in pick))
        rows.append(f"<tr><td><b>{_e(p['alias'])}</b>{'' if p['finished'] else ' <i>(не закончил)</i>'}</td><td>{marks}</td>"
                    f"<td>{s['meetings']} из {s['done']}</td><td class='loss'>−{_short(s['loss'], n['cur'])}</td></tr>")
        blocks = []
        for k, r in enumerate(p["results"]):
            if not r:
                continue
            v = r.get("v") or {}
            chat = "".join(f"<div class='msg {'c' if m['who'] == 'client' else 'me'}'>{_e(m['text'])}</div>" for m in r.get("log", []))
            steps = "".join(f"<li class='{'ok' if (x or {}).get('ok') else 'bad'}'><b>Шаг {n + 1} · {'хорошо' if (x or {}).get('ok') else 'ошибка'}</b>"
                            f"<p>{_e((x or {}).get('comment'))}</p>"
                            + (f"<blockquote>{_e((x or {}).get('better'))}</blockquote>" if (x or {}).get('better') else "") + "</li>"
                            for n, x in enumerate(r.get("steps") or []))
            verdict_html = (('<p class="phrase">' + _e(v.get('phrase')) + '</p>') if v.get('phrase') else '') \
                + (('<p>' + _e(v.get('summary')) + '</p>') if v.get('summary') else '') \
                + (('<p><b>Что получилось</b></p><ul>' + ''.join('<li>' + _e(x) + '</li>' for x in v.get('good') or []) + '</ul>') if v.get('good') else '') \
                + (('<p><b>Где слили</b></p><ul>' + ''.join('<li>' + _e(x) + '</li>' for x in v.get('errors') or []) + '</ul>') if v.get('errors') else '') \
                + (('<p><b>Что не узнали о клиенте.</b> ' + _e(v.get('hidden')) + '</p>') if v.get('hidden') else '')
            if not verdict_html:
                verdict_html = "<p class='muted'>Разбор этой переписки не загрузился – нейросеть не ответила. Он появится при следующем запросе отчета.</p>"
            blocks.append(f"""<div class='client'><h4>{_e(CLIENTS[k]['name'])} – <span class='{'okc' if not r.get('lost') else 'badc'}'>{n['win'] if not r.get('lost') else 'слит'}</span>{(' · этап «' + _e(v.get('stage')) + '»') if v.get('stage') else ''}</h4>
              {verdict_html}
              {('<p><b>Разбор по шагам – как надо было ответить</b></p><ol class="steps">' + steps + '</ol>') if steps else ''}
              <details><summary>Показать переписку</summary><div class='chat'>{chat}</div></details>
            </div>""")
        details.append(f"<section><h3>{_e(p['alias'])}</h3>{''.join(blocks) or '<p>Нет законченных переписок.</p>'}</section>")
    tot_loss = sum(player_stats(p, total)["loss"] for p in ps) / max(1, len(ps))
    sm = ""
    if not summary:
        errs = team_errors(ps, 8)
        if errs:
            summary = {"headline": "Где отдел теряет клиентов", "patterns": errs}
    if summary:
        sm = (f"<div class='card'><p class='phrase'>{_e(summary.get('headline'))}</p>"
              + ("<p><b>Ошибки, которые повторяются в отделе</b></p><ul>" + "".join(f"<li>{_e(x)}</li>" for x in summary.get("patterns") or []) + "</ul>" if summary.get("patterns") else "")
              + ("<p><b>Точки роста</b></p><ul>" + "".join(f"<li>{_e(x)}</li>" for x in summary.get("growth") or []) + "</ul>" if summary.get("growth") else "")
              + (f"<p><b>Что проверить на настоящих переписках.</b> {_e(summary.get('audit'))}</p>" if summary.get("audit") else "") + "</div>")
    return f"""<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Отчет по отделу – {_e(t['title'])}</title><style>
body{{font:16px/1.55 -apple-system,Segoe UI,Roboto,sans-serif;color:#1d1d1f;background:#f6f5f2;margin:0}}
.wrap{{max-width:860px;margin:0 auto;padding:32px 16px 64px}} h1{{font-size:28px;margin:0 0 4px}} h2{{margin-top:40px}}
.sub{{color:#6e6e73;margin:0 0 24px}} .big{{font-size:40px;font-weight:700;color:#c0392b;margin:8px 0}}
.card{{background:#fff;border-radius:16px;padding:20px 24px;margin:16px 0;box-shadow:0 1px 3px rgba(0,0,0,.06)}}
table{{width:100%;border-collapse:collapse;background:#fff;border-radius:16px;overflow:hidden}} td,th{{padding:12px 14px;border-bottom:1px solid #eee;text-align:left}}
th{{font-size:13px;color:#6e6e73;font-weight:600}} .loss{{color:#c0392b;font-weight:600;white-space:nowrap}}
.m{{display:inline-block;width:24px;height:24px;border-radius:50%;text-align:center;line-height:24px;margin-right:4px;font-size:13px}}
.m.ok{{background:#e3f4e8;color:#1e7b3a}} .m.bad{{background:#fbe5e2;color:#c0392b}} .m.n{{background:#eee;color:#999}}
details{{background:#fff;border-radius:14px;padding:14px 18px;margin:10px 0}} summary{{cursor:pointer;font-weight:600}}
.phrase{{font-weight:700;font-size:18px}} .chat{{display:grid;gap:6px;margin:12px 0}}
.msg{{padding:8px 12px;border-radius:12px;max-width:80%;white-space:pre-wrap}} .msg.c{{background:#f1f1f1}} .msg.me{{background:#dcf3d6;justify-self:end}}
.steps li{{margin:10px 0}} .client{{background:#fff;border-radius:14px;padding:16px 20px;margin:12px 0}} .client h4{{margin:0 0 8px;font-size:17px}}
.okc{{color:#1e7b3a}} .badc{{color:#c0392b}} .muted{{color:#6e6e73}} details summary{{font-weight:500;color:#4B3FE1}} .steps li.bad b{{color:#c0392b}} .steps li.ok b{{color:#1e7b3a}}
blockquote{{margin:6px 0;padding:8px 12px;border-left:3px solid #1e7b3a;background:#f3faf1;border-radius:0 8px 8px 0}}
footer{{margin-top:48px;color:#6e6e73;font-size:14px}}
</style></head><body><div class="wrap">
<h1>Отчет по отделу – {_e(t['title'])}</h1>
<p class="sub">Тренажер «Касса тает» · {_e(n['project_name'])} · менеджеров – {len(ps)} · {time.strftime('%d.%m.%Y')}</p>
<div class="card"><p>Если отдел отвечает так всем заявкам, при ваших цифрах он недополучает в среднем</p>
<p class="big">−{_short(tot_loss, n['cur'])} в месяц</p><p>Это −{_short(tot_loss * 12, n['cur'])} в год.</p></div>
{sm}
<h2>Менеджеры</h2>
<table><tr><th>Менеджер</th><th>Клиенты</th><th>{n['wins'].capitalize()}</th><th>Потери в месяц</th></tr>{''.join(rows)}</table>
<h2>Переписки и разборы</h2>{''.join(details)}
<footer>Разбор подготовлен по методу Анастасии Гавриш. В игре клиенты учебные. Как ваши менеджеры отвечают настоящим клиентам, видно по живым перепискам – пришлите 4–6 диалогов, и Анастасия бесплатно разберет их: <a href="https://a-gavrish.com/uslugi/audit/?from=report#offer">заявка на разбор</a> или <a href="https://t.me/gavrish_anastasiya">@gavrish_anastasiya</a> в Telegram.</footer>
</div></body></html>"""
