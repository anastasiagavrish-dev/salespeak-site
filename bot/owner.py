"""Режим собственника: отделы, коды доступа, результаты менеджеров и отчет.
Имен менеджеров бот не спрашивает – только псевдоним, который менеджер вводит сам."""
import html
import json
import os
import secrets
import sqlite3
import string
import time

from game_data import CLIENTS, PROJECT

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
        """)
    return DB


def _rand(n, alphabet=string.ascii_uppercase + string.digits):
    return "".join(secrets.choice(alphabet) for _ in range(n))


# ---------------- коды доступа ----------------
def new_code(note=""):
    code = "KT-" + _rand(6, "ABCDEFGHJKLMNPQRSTUVWXYZ23456789")
    db().execute("INSERT INTO codes(code, created, note) VALUES(?,?,?)", (code, int(time.time()), note))
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


# ---------------- отделы ----------------
def create_team(owner_id, owner_chat, title, code, nums):
    tid = _rand(8, string.ascii_lowercase + string.digits)
    db().execute("INSERT INTO teams VALUES(?,?,?,?,?,?,?)", (tid, owner_id, owner_chat, title, code, json.dumps(nums), int(time.time())))
    db().commit()
    return tid


def team(tid):
    return db().execute("SELECT * FROM teams WHERE id=?", (tid,)).fetchone()


def owner_teams(owner_id):
    return db().execute("SELECT * FROM teams WHERE owner_id=? ORDER BY created DESC", (owner_id,)).fetchall()


def team_nums(t):
    return json.loads(t["nums"])


# ---------------- менеджеры ----------------
def start_player(tid, tg_id, alias):
    old = db().execute("SELECT * FROM players WHERE team_id=? AND tg_id=?", (tid, tg_id)).fetchone()
    empty = json.dumps([None] * len(CLIENTS))
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


def team_summary_prompt(t, ps, style, rules):
    lines = []
    for p in ps:
        for k, r in enumerate(p["results"]):
            if r and r.get("v"):
                v = r["v"]
                lines.append(f"{p['alias']} · {CLIENTS[k]['name']} · {'встреча' if not r.get('lost') else 'слит'} · этап «{v.get('stage', '')}» · ошибки: "
                             + "; ".join(v.get("errors") or []))
    return f"""Ты – Анастасия Гавриш, эксперт по продажам. Собственник застройщика проверил свой отдел продаж в тренажере – менеджеры переписывались с одними и теми же 5 клиентами. Ниже результаты по каждой переписке. {style}

{rules}

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


def _short(n):
    if n >= 1e9:
        return f"{n / 1e9:.1f}".replace(".", ",") + " млрд ₸"
    if n >= 1e6:
        return f"{round(n / 1e6)} млн ₸"
    return f"{round(n):,}".replace(",", " ") + " ₸"


def report_html(t, ps, total, summary=None):
    rows, details = [], []
    ranked = sorted(ps, key=lambda p: (-player_stats(p, total)["meetings"], player_stats(p, total)["loss"]))
    for p in ranked:
        s = player_stats(p, total)
        marks = "".join("<span class='m n'>–</span>" if not r else (f"<span class='m bad' title='{_e(CLIENTS[k]['name'])}'>✕</span>" if r.get("lost")
                        else f"<span class='m ok' title='{_e(CLIENTS[k]['name'])}'>✓</span>") for k, r in enumerate(p["results"]))
        rows.append(f"<tr><td><b>{_e(p['alias'])}</b>{'' if p['finished'] else ' <i>(не закончил)</i>'}</td><td>{marks}</td>"
                    f"<td>{s['meetings']} из {s['done']}</td><td class='loss'>−{_short(s['loss'])}</td></tr>")
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
            blocks.append(f"""<details><summary>{_e(CLIENTS[k]['name'])} – {'встреча' if not r.get('lost') else 'слит'}{(' · этап «' + _e(v.get('stage')) + '»') if v.get('stage') else ''}</summary>
              {('<p class="phrase">' + _e(v.get('phrase')) + '</p>') if v.get('phrase') else ''}
              {('<p>' + _e(v.get('summary')) + '</p>') if v.get('summary') else ''}
              {('<p><b>Где слили</b></p><ul>' + ''.join('<li>' + _e(x) + '</li>' for x in v.get('errors') or []) + '</ul>') if v.get('errors') else ''}
              <div class='chat'>{chat}</div>
              {('<p><b>Разбор по шагам</b></p><ol class="steps">' + steps + '</ol>') if steps else ''}
            </details>""")
        details.append(f"<section><h3>{_e(p['alias'])}</h3>{''.join(blocks) or '<p>Нет законченных переписок.</p>'}</section>")
    tot_loss = sum(player_stats(p, total)["loss"] for p in ps) / max(1, len(ps))
    sm = ""
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
.steps li{{margin:10px 0}} .steps li.bad b{{color:#c0392b}} .steps li.ok b{{color:#1e7b3a}}
blockquote{{margin:6px 0;padding:8px 12px;border-left:3px solid #1e7b3a;background:#f3faf1;border-radius:0 8px 8px 0}}
footer{{margin-top:48px;color:#6e6e73;font-size:14px}}
</style></head><body><div class="wrap">
<h1>Отчет по отделу – {_e(t['title'])}</h1>
<p class="sub">Тренажер «Касса тает» · {_e(PROJECT['name'])} (учебный ЖК) · менеджеров – {len(ps)} · {time.strftime('%d.%m.%Y')}</p>
<div class="card"><p>Если отдел отвечает так всем заявкам, при ваших цифрах он недополучает в среднем</p>
<p class="big">−{_short(tot_loss)} в месяц</p><p>Это −{_short(tot_loss * 12)} в год.</p></div>
{sm}
<h2>Менеджеры</h2>
<table><tr><th>Менеджер</th><th>Клиенты</th><th>Встречи</th><th>Потери в месяц</th></tr>{''.join(rows)}</table>
<h2>Переписки и разборы</h2>{''.join(details)}
<footer>Разбор подготовлен по методу Анастасии Гавриш. Хотите разобрать настоящие переписки вашего отдела – напишите <a href="https://t.me/gavrish_anastasiya">@gavrish_anastasiya</a>.</footer>
</div></body></html>"""
