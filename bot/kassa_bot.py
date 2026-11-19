"""Telegram-бот «Касса тает» – тренажер-диагностика переписки отдела продаж.
Клиентов и разбор играет нейросеть (по умолчанию DeepSeek). Настройки – в переменных окружения (см. deploy/kassa-bot.sh)."""
import asyncio
import html
import json
import logging
import os
import re
import sys
from types import SimpleNamespace
import time
from collections import defaultdict

import httpx
from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ChatAction, ParseMode
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import (BufferedInputFile, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, Message,
                           MenuButtonWebApp, ReplyKeyboardMarkup, ReplyKeyboardRemove, WebAppInfo)

import owner as own
from game_data import CLIENTS, DEFAULT_NUMBERS, FILES, MAX_TURNS, PROJECT, PROJECT_TEXT, RULES, STAGES

TOKEN = os.environ.get("TG_BOT_TOKEN", "")
# Любая нейросеть с OpenAI-совместимым API. По умолчанию DeepSeek.
LLM_KEY = os.environ.get("LLM_API_KEY", "")
LLM_BASE = os.environ.get("LLM_BASE", "https://api.deepseek.com").rstrip("/")
MODEL_FAST = os.environ.get("LLM_MODEL_FAST", "deepseek-flash")    # реплики клиентов
MODEL_SMART = os.environ.get("LLM_MODEL_SMART", "deepseek-v4-pro")  # разборы
GAMES_PER_DAY = int(os.environ.get("GAMES_PER_DAY", "3"))
DATA_DIR = os.environ.get("BOT_DATA", "/var/lib/kassa-bot")
CONTACT = os.environ.get("CONTACT", "gavrish_anastasiya")
ADMINS = {x.strip().lstrip("@").lower() for x in os.environ.get("ADMIN_USERNAMES", "gavrish_anastasiya").split(",") if x.strip()}
BOT_NAME = {"v": ""}
WEBAPP_URL = os.environ.get("WEBAPP_URL", "").rstrip("/")  # если задан – игра открывается мини-приложением

log = logging.getLogger("kassa")
router = Router()

BTN_FILE, BTN_REF, BTN_LEFT = "📎 Отправить файл", "📋 Шпаргалка", "🚪 Клиент ушел"
CHAT_KB = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text=BTN_FILE), KeyboardButton(text=BTN_REF)], [KeyboardButton(text=BTN_LEFT)]],
                              resize_keyboard=True, input_field_placeholder="Ваш ответ клиенту…")


# ---------------- деньги ----------------
def money(n):
    return f"{round(n):,}".replace(",", " ") + " ₸"


def short(n):
    if n >= 1e9:
        return f"{n / 1e9:.1f}".replace(".", ",") + " млрд ₸"
    if n >= 1e6:
        return f"{round(n / 1e6)} млн ₸"
    return money(n)


def till(nums):
    leads = nums["budget"] / max(1, nums["cpl"])
    deals = leads * nums["conv"] / 100
    return dict(leads=leads, deals=deals, total=deals * nums["check"])


def esc(s):
    return html.escape(str(s or ""), quote=False)


# ---------------- нейросеть ----------------
async def llm(prompt, model, temperature=0.6, max_tokens=1500):
    async with httpx.AsyncClient(timeout=120) as c:
        r = await c.post(f"{LLM_BASE}/chat/completions",
                         headers={"Authorization": f"Bearer {LLM_KEY}"},
                         json={"model": model, "temperature": temperature, "max_tokens": max_tokens,
                               "response_format": {"type": "json_object"},
                               "messages": [{"role": "user", "content": prompt}]})
        if r.status_code >= 400:
            log.warning("LLM %s %s: %s", model, r.status_code, r.text[:300])
        r.raise_for_status()
        msg = r.json()["choices"][0]
        text = msg["message"].get("content") or ""
        if not text.strip():
            log.warning("LLM %s: пустой ответ, finish_reason=%s", model, msg.get("finish_reason"))
        return text


def parse_json(text, want):
    t = re.sub(r"```(?:json)?", "", text or "").strip()
    try:
        v = json.loads(t)
        if isinstance(v, want):
            return v
    except Exception:
        pass
    o, c = ("[", "]") if want is list else ("{", "}")
    a, b = t.find(o), t.rfind(c)
    if a >= 0 and b > a:
        try:
            v = json.loads(t[a:b + 1])
            if isinstance(v, want):
                return v
        except Exception:
            pass
    return None


async def llm_json(prompt, want, model, temperature=0.6, max_tokens=1500, tries=2):
    last = None
    for k in range(tries):
        try:
            v = parse_json(await llm(prompt, model, temperature, max_tokens), want)
            if v is not None:
                return v
            last = ValueError("ответ не в формате JSON")
        except Exception as e:  # сеть, лимиты, ошибки API
            last = e
            log.warning("LLM: %s", e)
        await asyncio.sleep(1.5)
    if model != MODEL_FAST:
        # запасной вариант – быстрая модель, чтобы разбор все равно пришел
        try:
            v = parse_json(await llm(prompt, MODEL_FAST, temperature, max_tokens), want)
            if v is not None:
                log.warning("LLM: %s не ответила, разбор сделала %s", model, MODEL_FAST)
                return v
        except Exception as e:
            last = e
            log.warning("LLM fallback: %s", e)
    raise last or RuntimeError("нет ответа")


# ---------------- состояние ----------------
class Game:
    def __init__(self, nums):
        self.nums = dict(nums)
        self.i = -1
        self.log = []
        self.turns = 0
        self.results = [None] * len(CLIENTS)
        self.busy = False
        self.closing = False
        self.team = None   # id отдела, если менеджер играет по ссылке собственника
        self.pid = None
        self.alias = ""


GAMES: dict[int, Game] = {}
NUMS: dict[int, dict] = {}
WAIT_NUMS: set[int] = set()
WAIT_CODE: set[int] = set()
WAIT_TITLE: dict[int, str] = {}
WAIT_ALIAS: dict[int, str] = {}
PLAYS: dict[int, list] = defaultdict(list)


def transcript(lg):
    return "\n".join(("КЛИЕНТ: " if m["who"] == "client" else "МЕНЕДЖЕР: ") + m["text"] for m in lg)


def manager_turns(lg):
    out, last = [], ""
    for m in lg:
        if m["who"] == "client":
            last = m["text"]
        else:
            out.append(dict(client=last, manager=m["text"]))
    return out


# ---------------- промпты ----------------
def client_prompt(g):
    c = CLIENTS[g.i]
    return f"""Ты играешь клиента в тренажере продаж. Тебе пишет менеджер застройщика в WhatsApp. Ты не помощник и не продавец – ты обычный человек, который ищет квартиру в Алматы.

Кто ты (скрытые детали раскрывай только если менеджер прямо и уместно спросит):
{c['brief']}

Менеджер продает вот что (ты этого заранее не знаешь, узнаешь только из его сообщений): {PROJECT_TEXT}
Менеджер может присылать файлы – в переписке они выглядят как [Файл: название – описание]. Считай, что ты получил картинку или PDF и посмотрел их. Планировка или карточка квартиры прямо в чате – это удобно. Ссылка на сайт вместо файла – неудобно.

Как себя вести:
- Отвечай как живой человек в мессенджере: коротко, 1–3 предложения, на русском, без эмодзи или с одним.
- Не подсказывай менеджеру, что делать, и не облегчай ему работу.
- Реагируй на ошибки, которые раздражают клиентов: «чем могу помочь» после конкретного запроса, ссылки на сайт вместо картинок в чате, простыни текста, «примерно», путаница в цифрах, вопросы-допросы без пояснения, неграмотность, давление. Раздражение показывай сдержанно, как реальный человек.
- Если менеджер выявил твои потребности и предложил понятный следующий шаг, который тебе подходит (онлайн-встреча или визит с понятной пользой, в удобное время) – соглашайся. Это outcome "meeting".
- Если менеджер грубит, игнорирует твои вопросы, дважды не дает того, что ты просишь, или явно не ведет к следующему шагу – теряй интерес. Можешь вежливо закончить («спасибо, подумаю») – это outcome "lost".
- Если ты прощаешься, пишешь «спасибо, подумаю», «посмотрю у других», «не актуально» или перестаешь интересоваться – это всегда outcome "lost".
- Иначе продолжай диалог – outcome "continue".
- Сейчас ответ номер {g.turns} менеджера из {MAX_TURNS}. Если это последний ответ и встреча не назначена – заверши разговор, outcome "lost".

Переписка до сих пор:
{transcript(g.log)}

Ответь строго JSON без пояснений и без markdown: {{"reply":"твое сообщение менеджеру","outcome":"continue|meeting|lost"}}"""


STYLE = "Пиши живо, прямо и по-человечески, от первого лица, как в голосовых разборах. Без буквы «ё», тире короткое «–», без канцелярита, минимум двоеточий."


def verdict_prompt(g, outcome):
    c = CLIENTS[g.i]
    return f"""Ты – Анастасия Гавриш, эксперт по продажам. Ты разбираешь переписку менеджера застройщика с клиентом для собственника бизнеса. {STYLE} Честно называй ошибки, отмечай, что получилось хорошо.

{RULES}

Клиент: {c['name']}, {c['sub']}. Что о клиенте было скрыто: {c['brief']}
Что было у менеджера в продаже: {PROJECT_TEXT}
Сообщения вида [Файл: …] – файлы, которые менеджер отправил прямо в чат. Планировки и карточки в чате – плюс, ссылка на сайт – минус.

Итог переписки: {'клиент согласился на встречу' if outcome == 'meeting' else 'клиент слит'}.

Переписка:
{transcript(g.log)}

Верни строго JSON без markdown:
{{"stage": одно из {json.dumps(STAGES, ensure_ascii=False)} – последний этап, который менеджер реально прошел,
 "summary": "2–3 предложения – что произошло и почему клиент {'согласился' if outcome == 'meeting' else 'ушел'}",
 "good": ["что менеджер сделал хорошо"] (0–3 пункта),
 "errors": ["конкретная ошибка с цитатой менеджера"] (1–4 пункта),
 "hidden": "что важное о клиенте менеджер так и не узнал (одна фраза или пустая строка)",
 "phrase": "вывод одной фразой, который хочется переслать"}}"""


def steps_prompt(g, t):
    c = CLIENTS[g.i]
    lines = "\n".join(f"{k + 1}. Клиент написал: «{x['client']}»\n   Менеджер ответил: «{x['manager']}»" for k, x in enumerate(t))
    return f"""Ты – Анастасия Гавриш, эксперт по продажам. Разбери переписку менеджера застройщика по шагам – каждый ответ менеджера отдельно. {STYLE}

{RULES}

Клиент: {c['name']}, {c['sub']}. Что о клиенте было скрыто: {c['brief']}
Что было у менеджера в продаже: {PROJECT_TEXT}
Сообщения вида [Файл: …] – файлы, которые менеджер отправил прямо в чат.

Полная переписка для контекста:
{transcript(g.log)}

Ответы менеджера по шагам:
{lines}

Для каждого шага оцени ответ менеджера и напиши, как ответить правильно, чтобы клиент не слился и пошел к встрече. Готовый ответ пиши так, как менеджер отправил бы его клиенту в мессенджер, коротко и по-человечески, с вопросом или следующим шагом в конце.
Верни строго JSON без markdown – объект с полем steps, в нем массив ровно из {len(t)} элементов в том же порядке:
{{"steps": [{{"ok": true или false, "comment": "1–2 предложения – что хорошо или где ошибка и почему клиенту это не понравится", "better": "как стоило ответить – готовое сообщение клиенту; если ответ был хорош, можно оставить пустую строку"}}]}}"""


# ---------------- тексты ----------------
def ref_text():
    lots = "\n".join(f"• {l['t']} {l['m']}, {l['f']}, {l['q']} – {l['p']}" for l in PROJECT["lots"])
    return (f"📋 <b>Шпаргалка менеджера – {esc(PROJECT['name'])}</b>\n\n{esc(PROJECT['about'])}\n\n<b>Квартиры</b>\n{esc(lots)}\n\n"
            f"<b>Сроки.</b> {esc(PROJECT['queues'])}\n<b>Цена.</b> {esc(PROJECT['price'])}\n<b>Оплата.</b> {esc(PROJECT['pay'])}\n"
            f"<b>Встреча.</b> {esc(PROJECT['meet'])}\n\nФайлы отправляются кнопкой «{BTN_FILE}». Клиент видит их так, как будто вы прислали картинку или PDF.")


def cash_text(g):
    t = till(g.nums)
    share = t["total"] / len(CLIENTS)
    lost = sum(1 for r in g.results if r and r["lost"])
    marks = " ".join("⚪" if not r else ("🔴" if r["lost"] else "🟢") for r in g.results)
    return (f"💰 <b>Касса месяца – {short(t['total'] - lost * share)}</b> из {short(t['total'])}\n"
            f"Потеряно – {short(lost * share)}\n{marks}")


START_TEXT = ("<b>Сколько ваш отдел теряет в переписке</b>\n\n"
              "Вы – менеджер застройщика в Алматы. Пять клиентов пишут вам в мессенджер. Отвечайте так, как отвечаете в работе.\n\n"
              "Задача – не продать квартиру за 10 минут, а довести клиента до встречи, онлайн или в офисе, где подбирают квартиру по шахматке и считают оплату.\n\n"
              "Каждый слитый клиент забирает пятую часть кассы. После каждой переписки – разбор по шагам от Анастасии Гавриш, как ответить, чтобы клиент не слился.")


def start_kb():
    if WEBAPP_URL:
        return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="▶️ Играть", web_app=WebAppInfo(url=WEBAPP_URL + "/"))],
                                                     [InlineKeyboardButton(text="👔 Проверить мой отдел продаж", callback_data="own")]])
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="▶️ Начать игру", callback_data="go")],
                                                 [InlineKeyboardButton(text="🔢 Подставить свои цифры", callback_data="nums")],
                                                 [InlineKeyboardButton(text="👔 Проверить мой отдел продаж", callback_data="own")]])


def nums_text(n):
    t = till(n)
    return (f"Цифры для кассы – реклама {money(n['budget'])} в месяц, лид {money(n['cpl'])}, средняя квартира {money(n['check'])}, "
            f"норма лид → сделка {('%g' % n['conv']).replace('.', ',')}%.\nЭто {round(t['leads'])} лидов и {t['deals']:.1f} сделок в месяц – "
            f"касса {short(t['total'])}.".replace(".0 сделок", " сделок"))


# ---------------- игра ----------------
async def typing_loop(bot, chat_id, stop: asyncio.Event):
    while not stop.is_set():
        try:
            await bot.send_chat_action(chat_id, ChatAction.TYPING)
        except Exception:
            pass
        try:
            await asyncio.wait_for(stop.wait(), 4.5)
        except asyncio.TimeoutError:
            pass


async def open_client(bot, chat_id, g, i):
    c = CLIENTS[i]
    g.i, g.log, g.turns, g.closing = i, [dict(who="client", text=c["first"])], 0, False
    await bot.send_message(chat_id, f"<i>Клиент {i + 1} из {len(CLIENTS)} · {esc(c['name'])}, {esc(c['sub'])}. Заявка пришла с рекламы в Instagram.</i>",
                           reply_markup=CHAT_KB)
    await bot.send_message(chat_id, f"💬 <b>{esc(c['name'])}</b>\n{esc(c['first'])}")


async def client_turn(bot, chat_id, g):
    g.turns += 1
    g.busy = True
    stop = asyncio.Event()
    tl = asyncio.create_task(typing_loop(bot, chat_id, stop))
    try:
        r = await llm_json(client_prompt(g), dict, MODEL_FAST, temperature=0.7, max_tokens=400)
    except Exception as e:
        log.warning("client reply failed: %s", e)
        g.turns -= 1
        await bot.send_message(chat_id, "Клиент не ответил – сбой связи с нейросетью. Отправьте сообщение еще раз.")
        return
    finally:
        stop.set()
        await tl
        g.busy = False
    reply = str(r.get("reply") or "…").strip()
    g.log.append(dict(who="client", text=reply))
    await bot.send_message(chat_id, f"💬 <b>{esc(CLIENTS[g.i]['name'])}</b>\n{esc(reply)}")
    out = str(r.get("outcome") or "").lower()
    if "meet" in out or "lost" in out or g.turns >= MAX_TURNS:
        await close_client(bot, chat_id, g, "meeting" if "meet" in out else "lost")
    elif g.turns >= MAX_TURNS - 2:
        await bot.send_message(chat_id, f"<i>Ответов {g.turns} из {MAX_TURNS}</i>")


async def close_client(bot, chat_id, g, outcome):
    if g.closing:
        return
    g.closing = True
    t = till(g.nums)
    share = t["total"] / len(CLIENTS)
    g.results[g.i] = dict(lost=outcome != "meeting")
    head = "🟢 <b>Встреча назначена.</b> Клиент остается в кассе." if outcome == "meeting" else f"🔴 <b>Клиент ушел.</b> Из кассы −{short(share)}."
    await bot.send_message(chat_id, head + "\n\n" + cash_text(g), reply_markup=ReplyKeyboardRemove())
    await bot.send_message(chat_id, "<i>Анастасия читает переписку… обычно это занимает до минуты</i>")
    stop = asyncio.Event()
    tl = asyncio.create_task(typing_loop(bot, chat_id, stop))
    turns = manager_turns(g.log)
    vt = asyncio.create_task(llm_json(verdict_prompt(g, outcome), dict, MODEL_SMART, temperature=0.4, max_tokens=2500))
    st = asyncio.create_task(llm_json(steps_prompt(g, turns), dict, MODEL_SMART, temperature=0.4, max_tokens=5000)) if turns else None
    v = s = None
    try:
        v = await vt
    except Exception as e:
        log.warning("verdict failed: %s", e)
    try:
        s = (await st).get("steps", []) if st else []
    except Exception as e:
        log.warning("steps failed: %s", e)
    stop.set()
    await tl
    g.results[g.i]["v"] = v
    if g.pid:
        try:
            own.save_result(g.pid, g.i, dict(lost=outcome != "meeting", v=v, steps=s or [], log=g.log))
        except Exception as e:
            log.warning("save_result: %s", e)
    c = CLIENTS[g.i]
    if v:
        parts = [f"🧾 <b>Разбор · {esc(c['name'])}</b>"]
        if v.get("stage"):
            parts.append(f"<i>Дошли до этапа «{esc(v['stage'])}»</i>")
        if v.get("phrase"):
            parts.append(f"<b>{esc(v['phrase'])}</b>")
        if v.get("summary"):
            parts.append(esc(v["summary"]))
        if v.get("good"):
            parts.append("<b>Что получилось</b>\n" + "\n".join(f"• {esc(x)}" for x in v["good"]))
        if v.get("errors"):
            parts.append("<b>Где слили</b>\n" + "\n".join(f"• {esc(x)}" for x in v["errors"]))
        if v.get("hidden"):
            parts.append(f"<b>Что не узнали о клиенте.</b> {esc(v['hidden'])}")
        await send_long(bot, chat_id, "\n\n".join(parts))
    else:
        await bot.send_message(chat_id, f"🧾 Общий разбор по {esc(c['name'])} не загрузился – нейросеть не ответила.")
    if s:
        await bot.send_message(chat_id, "<b>Разбор по шагам – как ответить, чтобы клиент не слился</b>")
        for k, x in enumerate(turns):
            y = s[k] if k < len(s) and isinstance(s[k], dict) else {}
            mark = "✅ хорошо" if y.get("ok") else "❌ ошибка"
            txt = (f"<b>Шаг {k + 1} · {mark}</b>\n<i>Клиент:</i> «{esc(x['client'])}»\n<i>Вы:</i> {esc(x['manager'])}")
            if y.get("comment"):
                txt += f"\n\n{esc(y['comment'])}"
            if y.get("better"):
                txt += f"\n\n<b>Как лучше:</b>\n<blockquote>{esc(y['better'])}</blockquote>"
            await send_long(bot, chat_id, txt)
    elif turns:
        await bot.send_message(chat_id, "Разбор по шагам не загрузился – нейросеть не ответила.")
    last = g.i >= len(CLIENTS) - 1
    kb = [[InlineKeyboardButton(text="📊 Итог по отделу" if last else f"➡️ Следующий клиент – {CLIENTS[g.i + 1]['name']}",
                                callback_data="final" if last else "next")]]
    if not last:
        kb.append([InlineKeyboardButton(text="📊 Закончить и получить итог", callback_data="final")])
    await bot.send_message(chat_id, "Что дальше?", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))


async def send_long(bot, chat_id, text):
    while text:
        if len(text) <= 4000:
            await bot.send_message(chat_id, text)
            return
        cut = text.rfind("\n", 0, 4000)
        cut = cut if cut > 1000 else 4000
        await bot.send_message(chat_id, text[:cut])
        text = text[cut:].lstrip()


async def finale(bot, chat_id, g):
    if g.team:
        return await team_finale(bot, chat_id, g)
    t = till(g.nums)
    done = [r for r in g.results if r]
    lost = sum(1 for r in done if r["lost"])
    share = lost / len(done) if done else 0
    errs = [e for r in done for e in ((r.get("v") or {}).get("errors") or [])][:6]
    txt = (f"📊 <b>Итог по отделу</b>\n\n<b>−{short(share * t['total'])} в месяц</b>\n\n"
           f"Пройдено клиентов – {len(done)} из {len(CLIENTS)}, до встречи дошли {len(done) - lost}. Если ваш менеджер так отвечает всем, "
           f"при ваших цифрах отдел недополучает около <b>{short(share * t['total'])}</b> в месяц и <b>{short(share * t['total'] * 12)}</b> в год.")
    if errs:
        txt += "\n\n<b>Ошибки, которые повторялись</b>\n" + "\n".join(f"• {esc(e)}" for e in errs)
    txt += ("\n\n<b>Реклама может приводить 100% целевых клиентов, но если менеджер сливает их в переписке, чем больше вы тратите на трафик, "
            "тем больше теряете.</b>\n\nХотите разобрать настоящие переписки вашего отдела? Напишите Анастасии – "
            f"@{CONTACT}")
    await send_long(bot, chat_id, txt)
    await bot.send_message(chat_id, "Сыграть еще раз?", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔁 Пройти еще раз", callback_data="go")],
        [InlineKeyboardButton(text="✉️ Написать Анастасии", url=f"https://t.me/{CONTACT}")]]))
    save_stats(g)


async def team_finale(bot, chat_id, g):
    t = own.team(g.team)
    tot = till(g.nums)["total"]
    done = [r for r in g.results if r]
    lost = sum(1 for r in done if r["lost"])
    share = lost / len(done) if done else 0
    own.finish_player(g.pid)
    save_stats(g)
    await bot.send_message(chat_id, f"📊 <b>Готово!</b>\n\nДо встречи дошли {len(done) - lost} из {len(done)} клиентов. "
                           f"Результат и разборы отправлены руководителю. Спасибо, что прошли проверку!")
    if t:
        try:
            await bot.send_message(t["owner_chat"], f"👤 <b>{esc(g.alias)}</b> – проверка пройдена, отдел «{esc(t['title'])}».\n"
                                   f"Встречи – {len(done) - lost} из {len(done)}, потери – около <b>{short(share * tot)}</b> в месяц.",
                                   reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="📊 Отчет по отделу", callback_data=f"r:{t['id']}")]]))
        except Exception as e:
            log.warning("notify owner: %s", e)


async def bot_name(bot):
    if not BOT_NAME["v"]:
        BOT_NAME["v"] = (await bot.get_me()).username
    return BOT_NAME["v"]


def team_link(name, tid):
    return f"https://t.me/{name}?start=t_{tid}"


def invite_text(t, link):
    web_link = f"\n\nБез Telegram – на сайте: {WEBAPP_URL}/?team={t['id']}" if WEBAPP_URL else ""
    return (f"Коллеги, пройдите, пожалуйста, короткую проверку переписки – это игра в Telegram. Пять клиентов застройщика пишут вам в мессенджер, "
            f"ваша задача – довести их до встречи. Займет 20–30 минут. Отвечайте так же, как в работе.\n\n{link}{web_link}")


def is_admin(u):
    return (u.username or "").lower() in ADMINS


async def owner_menu(m_or_q, uid):
    ts = own.owner_teams(uid)
    msg = m_or_q.message if isinstance(m_or_q, CallbackQuery) else m_or_q
    if not ts:
        WAIT_CODE.add(uid)
        await msg.answer("<b>Проверка отдела продаж</b>\n\nВы получите ссылку для менеджеров. Каждый пройдет тех же 5 клиентов, "
                         "а вам придет отчет по отделу – кто где сливает клиентов, сколько это стоит в деньгах и что исправить.\n\n"
                         f"Чтобы открыть доступ, пришлите код. Код можно получить у Анастасии – @{CONTACT}")
        return
    kb = [[InlineKeyboardButton(text=f"📊 {t['title']} – отчет", callback_data=f"r:{t['id']}"),
           InlineKeyboardButton(text="🔗 Ссылка", callback_data=f"l:{t['id']}")] for t in ts[:8]]
    kb.append([InlineKeyboardButton(text="➕ Новый отдел по коду", callback_data="own_new")])
    await msg.answer("<b>Ваши отделы</b>", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))


async def review_one(g, outcome):
    turns = manager_turns(g.log)
    v = steps = None
    vt = asyncio.create_task(llm_json(verdict_prompt(g, outcome), dict, MODEL_SMART, temperature=0.4, max_tokens=2500))
    st = asyncio.create_task(llm_json(steps_prompt(g, turns), dict, MODEL_SMART, temperature=0.4, max_tokens=5000)) if turns else None
    try:
        v = await vt
    except Exception as e:
        log.warning("verdict: %s", e)
    try:
        steps = (await st).get("steps", []) if st else []
    except Exception as e:
        log.warning("steps: %s", e)
    return v, steps


async def fill_missing_reviews(ps, nums):
    """Если разбор переписки не сохранился (сбой нейросети), делаем его заново перед отчетом."""
    sem = asyncio.Semaphore(3)

    async def one(p, k, r):
        async with sem:
            g = SimpleNamespace(i=k, log=r.get("log") or [], turns=len(manager_turns(r.get("log") or [])), nums=nums)
            v, steps = await review_one(g, "lost" if r.get("lost") else "meeting")
            if v or steps:
                r["v"] = r.get("v") or v
                r["steps"] = r.get("steps") or steps or []
                own.save_result(p["id"], k, r)

    jobs = [one(p, k, r) for p in ps for k, r in enumerate(p["results"])
            if r and r.get("log") and (not r.get("v") or not r.get("steps"))]
    if jobs:
        await asyncio.gather(*jobs, return_exceptions=True)


async def send_report(bot, chat_id, tid, uid):
    t = own.team(tid)
    if not t or t["owner_id"] != uid:
        await bot.send_message(chat_id, "Отчет доступен только владельцу отдела.")
        return
    ps = own.players(tid)
    if not any(any(r for r in p["results"]) for p in ps):
        name = await bot_name(bot)
        await bot.send_message(chat_id, "Пока никто из менеджеров не прошел ни одного клиента. Ссылка для команды:\n" + team_link(name, tid))
        return
    tot = till(own.team_nums(t))["total"]
    await bot.send_message(chat_id, "<i>Анастасия собирает отчет по отделу… это занимает до минуты</i>")
    await fill_missing_reviews(ps, own.team_nums(t))
    summary = None
    try:
        summary = await llm_json(own.team_summary_prompt(t, ps, STYLE, RULES), dict, MODEL_SMART, temperature=0.4, max_tokens=2500)
    except Exception as e:
        log.warning("team summary: %s", e)
    lines = [f"📊 <b>Отчет по отделу «{esc(t['title'])}»</b>", f"Менеджеров – {len(ps)}, закончили – {sum(1 for p in ps if p['finished'])}"]
    for p in sorted(ps, key=lambda p: -own.player_stats(p, tot)["meetings"]):
        st = own.player_stats(p, tot)
        lines.append(f"• <b>{esc(p['alias'])}</b> – встречи {st['meetings']} из {st['done']}, потери ~{short(st['loss'])}/мес")
    if summary:
        if summary.get("headline"):
            lines.append(f"\n<b>{esc(summary['headline'])}</b>")
        if summary.get("patterns"):
            lines.append("<b>Повторяющиеся ошибки</b>\n" + "\n".join(f"• {esc(x)}" for x in summary["patterns"]))
        if summary.get("growth"):
            lines.append("<b>Точки роста</b>\n" + "\n".join(f"• {esc(x)}" for x in summary["growth"]))
    lines.append("\nПолный отчет с перепиской и разбором каждого менеджера – в файле ниже. Откройте его в браузере.")
    await send_long(bot, chat_id, "\n".join(lines))
    data = own.report_html(t, ps, tot, summary).encode("utf-8")
    await bot.send_document(chat_id, BufferedInputFile(data, filename=f"otchet-{tid}.html"))
    await bot.send_message(chat_id, f"Хотите разобрать настоящие переписки вашего отдела? Напишите Анастасии – @{CONTACT}")


async def start_team_game(bot, chat_id, uid, tid, alias):
    t = own.team(tid)
    g = Game(own.team_nums(t))
    g.team, g.alias = tid, alias
    g.pid = own.start_player(tid, uid, alias)
    GAMES[uid] = g
    await bot.send_message(chat_id, ref_text())
    await open_client(bot, chat_id, g, 0)


def save_stats(g):
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(os.path.join(DATA_DIR, "games.jsonl"), "a", encoding="utf-8") as f:
            f.write(json.dumps(dict(ts=int(time.time()), results=[None if r is None else ("lost" if r["lost"] else "meeting") for r in g.results]),
                               ensure_ascii=False) + "\n")
    except Exception as e:
        log.warning("stats: %s", e)


# ---------------- обработчики ----------------
@router.message(CommandStart())
async def cmd_start(m: Message, command: CommandObject):
    uid = m.from_user.id
    GAMES.pop(uid, None)
    WAIT_NUMS.discard(uid)
    WAIT_CODE.discard(uid)
    WAIT_TITLE.pop(uid, None)
    WAIT_ALIAS.pop(uid, None)
    arg = (command.args or "").strip()
    if arg.startswith("t_"):
        t = own.team(arg[2:])
        if not t:
            await m.answer("Ссылка устарела или неверная. Попросите руководителя прислать новую.")
            return
        if own.player_done(t["id"], uid):
            await m.answer("Вы уже прошли эту проверку – результат у руководителя. Спасибо!")
            return
        if WEBAPP_URL:
            await m.answer(f"<b>Проверка переписки – {esc(t['title'])}</b>\n\n"
                           "Вы – менеджер застройщика в Алматы. Пять клиентов по очереди пишут вам в мессенджер. Задача – довести каждого до встречи, "
                           "онлайн или в офисе. Отвечайте так же, как в работе. После каждого клиента вы увидите разбор, а итог получит ваш руководитель.",
                           reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(
                               text="▶️ Начать проверку", web_app=WebAppInfo(url=f"{WEBAPP_URL}/?team={t['id']}"))]]))
            return
        WAIT_ALIAS[uid] = t["id"]
        await m.answer(f"<b>Проверка переписки – {esc(t['title'])}</b>\n\n"
                       "Вы – менеджер застройщика в Алматы. Пять клиентов по очереди пишут вам в мессенджер. Задача – довести каждого до встречи, "
                       "онлайн или в офисе. Отвечайте так же, как в работе. После каждого клиента вы увидите разбор, а итог получит ваш руководитель.\n\n"
                       "Как подписать вас в отчете? Напишите имя или любой псевдоним.", reply_markup=ReplyKeyboardRemove())
        return
    await m.answer(START_TEXT, reply_markup=ReplyKeyboardRemove())
    if WEBAPP_URL:
        await m.answer("Игра откроется прямо здесь, в Telegram. Свои цифры кассы можно подставить на первом экране.", reply_markup=start_kb())
        return
    await m.answer(nums_text(NUMS.get(m.from_user.id, DEFAULT_NUMBERS)), reply_markup=start_kb())


@router.message(Command("help"))
async def cmd_help(m: Message):
    await m.answer("Пишите клиенту обычными сообщениями. Кнопки внизу – отправить файл, открыть шпаргалку или закончить переписку, если клиент ушел.\n"
                   "/start – начать заново")


@router.callback_query(F.data == "nums")
async def cb_nums(q: CallbackQuery):
    WAIT_NUMS.add(q.from_user.id)
    await q.message.answer("Пришлите четыре числа через пробел – рекламный бюджет в месяц, стоимость лида, среднюю стоимость квартиры и норму "
                           "конверсии лид → сделка в процентах.\n\nНапример: <code>3000000 6000 45000000 2</code>")
    await q.answer()


@router.callback_query(F.data == "go")
async def cb_go(q: CallbackQuery):
    uid = q.from_user.id
    day = time.time() - 86400
    PLAYS[uid] = [x for x in PLAYS[uid] if x > day]
    if len(PLAYS[uid]) >= GAMES_PER_DAY:
        await q.answer()
        await q.message.answer(f"На сегодня лимит – {GAMES_PER_DAY} игры. Возвращайтесь завтра или напишите Анастасии – @{CONTACT}")
        return
    PLAYS[uid].append(time.time())
    g = Game(NUMS.get(uid, DEFAULT_NUMBERS))
    GAMES[uid] = g
    await q.answer()
    await q.message.answer(cash_text(g) + "\n\n<i>Каждый клиент – пятая часть вашего потока заявок.</i>")
    await q.message.answer(ref_text())
    await open_client(q.bot, q.message.chat.id, g, 0)


@router.callback_query(F.data == "next")
async def cb_next(q: CallbackQuery):
    g = GAMES.get(q.from_user.id)
    await q.answer()
    if not g or g.i < 0 or not g.closing or g.i >= len(CLIENTS) - 1:
        return
    await q.message.edit_reply_markup(reply_markup=None)
    await open_client(q.bot, q.message.chat.id, g, g.i + 1)


@router.callback_query(F.data == "final")
async def cb_final(q: CallbackQuery):
    g = GAMES.pop(q.from_user.id, None)
    await q.answer()
    if not g:
        return
    await q.message.edit_reply_markup(reply_markup=None)
    await finale(q.bot, q.message.chat.id, g)


@router.callback_query(F.data.startswith("f:"))
async def cb_file(q: CallbackQuery):
    g = GAMES.get(q.from_user.id)
    await q.answer()
    if not g or g.closing or g.busy:
        return
    f = FILES[int(q.data[2:])]
    g.log.append(dict(who="manager", text=f"[Файл: {f['title']} – {f['desc']}]"))
    await q.message.edit_text(f"📎 Отправлено клиенту – <b>{esc(f['title'])}</b>\n<i>{esc(f['desc'])}</i>",
                              reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⏳ Без текста – ждать ответа клиента", callback_data="wait")]]))


@router.callback_query(F.data == "wait")
async def cb_wait(q: CallbackQuery):
    g = GAMES.get(q.from_user.id)
    await q.answer()
    if not g or g.closing or g.busy or not g.log or g.log[-1]["who"] != "manager":
        return
    await q.message.edit_reply_markup(reply_markup=None)
    await client_turn(q.bot, q.message.chat.id, g)


@router.message(F.text == BTN_FILE)
async def btn_file(m: Message):
    g = GAMES.get(m.from_user.id)
    if not g or g.closing:
        return
    kb = [[InlineKeyboardButton(text=f["title"][:60], callback_data=f"f:{k}")] for k, f in enumerate(FILES)]
    await m.answer("Что отправить клиенту?", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))


@router.message(F.text == BTN_REF)
async def btn_ref(m: Message):
    await m.answer(ref_text())


@router.message(F.text == BTN_LEFT)
async def btn_left(m: Message):
    g = GAMES.get(m.from_user.id)
    if not g or g.closing or g.busy:
        return
    await close_client(m.bot, m.chat.id, g, "lost")


@router.callback_query(F.data.in_({"own", "own_new"}))
async def cb_own(q: CallbackQuery):
    await q.answer()
    if q.data == "own_new":
        WAIT_CODE.add(q.from_user.id)
        await q.message.answer("Пришлите код доступа для нового отдела.")
        return
    await owner_menu(q, q.from_user.id)


@router.message(Command("team"))
async def cmd_team(m: Message):
    await owner_menu(m, m.from_user.id)


@router.callback_query(F.data.startswith("r:"))
async def cb_report(q: CallbackQuery):
    await q.answer()
    await send_report(q.bot, q.message.chat.id, q.data[2:], q.from_user.id)


@router.callback_query(F.data.startswith("l:"))
async def cb_link(q: CallbackQuery):
    await q.answer()
    t = own.team(q.data[2:])
    if not t or t["owner_id"] != q.from_user.id:
        return
    link = team_link(await bot_name(q.bot), t["id"])
    await q.message.answer("Перешлите это сообщение менеджерам:")
    await q.message.answer(invite_text(t, link), disable_web_page_preview=True)


@router.message(Command("code"))
async def cmd_code(m: Message, command: CommandObject):
    if not is_admin(m.from_user):
        return
    code = own.new_code(command.args or "")
    await m.answer(f"Новый код доступа для собственника:\n<code>{code}</code>\n\nОн открывает режим «Проверить мой отдел продаж» для одного отдела.")


@router.message(Command("codes"))
async def cmd_codes(m: Message):
    if not is_admin(m.from_user):
        return
    rows = own.list_codes()
    if not rows:
        await m.answer("Кодов пока нет. Создать – /code")
        return
    await m.answer("<b>Коды доступа</b>\n" + "\n".join(f"<code>{r['code']}</code> – {'использован' if r['used_by'] else 'свободен'}"
                                                         + (f" · {esc(r['note'])}" if r['note'] else "") for r in rows))


@router.message(Command("stats"))
async def cmd_stats(m: Message):
    if not is_admin(m.from_user):
        return
    games, week = 0, 0
    try:
        with open(os.path.join(DATA_DIR, "games.jsonl"), encoding="utf-8") as f:
            for line in f:
                games += 1
                if json.loads(line).get("ts", 0) > time.time() - 7 * 86400:
                    week += 1
    except FileNotFoundError:
        pass
    teams = own.db().execute("SELECT COUNT(*) FROM teams").fetchone()[0]
    pl = own.db().execute("SELECT COUNT(*) FROM players").fetchone()[0]
    await m.answer(f"<b>Статистика</b>\nЗаконченных игр – {games}, за 7 дней – {week}\nОтделов – {teams}, менеджеров в отделах – {pl}\n"
                   f"Оценка затрат на нейросеть – около ${games * 0.07:.2f} за все время (≈$0,07 за игру). Точные траты – platform.deepseek.com → Usage.")


@router.message(F.text)
async def on_text(m: Message):
    uid = m.from_user.id
    if uid in WAIT_ALIAS:
        alias = re.sub(r"\s+", " ", m.text).strip()[:40]
        if not alias or alias.startswith("/"):
            await m.answer("Напишите имя или псевдоним одним сообщением.")
            return
        tid = WAIT_ALIAS.pop(uid)
        await start_team_game(m.bot, m.chat.id, uid, tid, alias)
        return
    if uid in WAIT_CODE:
        code, err = own.use_code(m.text, uid)
        if not code:
            await m.answer(err + " Или нажмите /start, чтобы выйти.")
            return
        WAIT_CODE.discard(uid)
        WAIT_TITLE[uid] = code
        await m.answer("Код принят. Как назвать отдел в отчете? Например «Отдел продаж ЖК Тау».")
        return
    if uid in WAIT_TITLE:
        title = re.sub(r"\s+", " ", m.text).strip()[:60] or "Отдел продаж"
        code = WAIT_TITLE.pop(uid)
        tid = own.create_team(uid, m.chat.id, title, code, NUMS.get(uid, DEFAULT_NUMBERS))
        t = own.team(tid)
        link = team_link(await bot_name(m.bot), tid)
        await m.answer(f"Отдел «{esc(title)}» создан. Касса считается по вашим цифрам: {nums_text(own.team_nums(t))}\n\n"
                       "Перешлите менеджерам сообщение ниже. Когда каждый закончит, я пришлю вам уведомление, а отчет по отделу можно открыть в любой момент – /team")
        await m.answer(invite_text(t, link), disable_web_page_preview=True)
        return
    if uid in WAIT_NUMS:
        nums = [float(x.replace(",", ".")) for x in re.findall(r"\d+(?:[.,]\d+)?", m.text)]
        if len(nums) < 4 or min(nums[:3]) <= 0:
            await m.answer("Нужно четыре числа через пробел, например <code>3000000 6000 45000000 2</code>")
            return
        WAIT_NUMS.discard(uid)
        NUMS[uid] = dict(budget=nums[0], cpl=nums[1], check=nums[2], conv=nums[3])
        await m.answer(nums_text(NUMS[uid]), reply_markup=start_kb())
        return
    g = GAMES.get(uid)
    if not g or g.i < 0:
        await m.answer("Чтобы начать игру, нажмите /start")
        return
    if g.closing:
        await m.answer("Эта переписка уже закончилась – нажмите кнопку под разбором, чтобы перейти дальше.")
        return
    if g.busy:
        await m.answer("<i>Клиент еще печатает…</i>")
        return
    g.log.append(dict(who="manager", text=m.text.strip()))
    await client_turn(m.bot, m.chat.id, g)


async def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if not (TOKEN and LLM_KEY):
        raise SystemExit("Не заданы TG_BOT_TOKEN или LLM_API_KEY")
    bot = Bot(TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()
    dp.include_router(router)
    await bot.delete_webhook(drop_pending_updates=True)
    import webapp
    await webapp.start(bot, sys.modules[__name__])
    if WEBAPP_URL:
        try:
            await bot.set_chat_menu_button(menu_button=MenuButtonWebApp(text="Играть", web_app=WebAppInfo(url=WEBAPP_URL + "/")))
        except Exception as e:
            log.warning("menu button: %s", e)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
