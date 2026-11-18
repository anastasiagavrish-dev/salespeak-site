"""Telegram-бот «Касса тает» – тренажер-диагностика переписки отдела продаж.
Клиентов и разбор играет YandexGPT. Настройки – в переменных окружения (см. deploy/kassa-bot.sh)."""
import asyncio
import html
import json
import logging
import os
import re
import time
from collections import defaultdict

import httpx
from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ChatAction, ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.types import (CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, Message,
                           ReplyKeyboardMarkup, ReplyKeyboardRemove)

from game_data import CLIENTS, DEFAULT_NUMBERS, FILES, MAX_TURNS, PROJECT, PROJECT_TEXT, RULES, STAGES

TOKEN = os.environ.get("TG_BOT_TOKEN", "")
YC_KEY = os.environ.get("YC_API_KEY", "")
YC_FOLDER = os.environ.get("YC_FOLDER_ID", "")
YC_MODEL = os.environ.get("YC_MODEL", "yandexgpt/latest")
GAMES_PER_DAY = int(os.environ.get("GAMES_PER_DAY", "3"))
DATA_DIR = os.environ.get("BOT_DATA", "/var/lib/kassa-bot")
CONTACT = os.environ.get("CONTACT", "gavrish_anastasiya")

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


# ---------------- YandexGPT ----------------
async def llm(prompt, temperature=0.6, max_tokens=1500):
    async with httpx.AsyncClient(timeout=120) as c:
        r = await c.post("https://ai.api.cloud.yandex.net/v1/chat/completions",
                         headers={"Authorization": f"Api-Key {YC_KEY}", "OpenAI-Project": YC_FOLDER},
                         json={"model": f"gpt://{YC_FOLDER}/{YC_MODEL}", "temperature": temperature, "max_tokens": max_tokens,
                               "messages": [{"role": "user", "content": prompt}]})
        if r.status_code in (404, 405, 501):
            # запасной вариант – классический API Foundation Models
            r = await c.post("https://llm.api.cloud.yandex.net/foundationModels/v1/completion",
                             headers={"Authorization": f"Api-Key {YC_KEY}", "x-folder-id": YC_FOLDER},
                             json={"modelUri": f"gpt://{YC_FOLDER}/{YC_MODEL}",
                                   "completionOptions": {"stream": False, "temperature": temperature, "maxTokens": str(max_tokens)},
                                   "messages": [{"role": "user", "text": prompt}]})
            r.raise_for_status()
            return r.json()["result"]["alternatives"][0]["message"]["text"]
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]


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


async def llm_json(prompt, want, temperature=0.6, max_tokens=1500, tries=2):
    last = None
    for k in range(tries):
        try:
            v = parse_json(await llm(prompt, temperature, max_tokens), want)
            if v is not None:
                return v
            last = ValueError("ответ не в формате JSON")
        except Exception as e:  # сеть, лимиты, ошибки API
            last = e
            log.warning("YandexGPT: %s", e)
        await asyncio.sleep(1.5)
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


GAMES: dict[int, Game] = {}
NUMS: dict[int, dict] = {}
WAIT_NUMS: set[int] = set()
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
Верни строго JSON без markdown – массив ровно из {len(t)} элементов в том же порядке:
[{{"ok": true или false, "comment": "1–2 предложения – что хорошо или где ошибка и почему клиенту это не понравится", "better": "как стоило ответить – готовое сообщение клиенту; если ответ был хорош, можно оставить пустую строку"}}]"""


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
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="▶️ Начать игру", callback_data="go")],
                                                 [InlineKeyboardButton(text="🔢 Подставить свои цифры", callback_data="nums")]])


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
        r = await llm_json(client_prompt(g), dict, temperature=0.7, max_tokens=400)
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
    vt = asyncio.create_task(llm_json(verdict_prompt(g, outcome), dict, temperature=0.4, max_tokens=1200))
    st = asyncio.create_task(llm_json(steps_prompt(g, turns), list, temperature=0.4, max_tokens=2500)) if turns else None
    v = s = None
    try:
        v = await vt
    except Exception as e:
        log.warning("verdict failed: %s", e)
    try:
        s = await st if st else []
    except Exception as e:
        log.warning("steps failed: %s", e)
    stop.set()
    await tl
    g.results[g.i]["v"] = v
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
async def cmd_start(m: Message):
    GAMES.pop(m.from_user.id, None)
    WAIT_NUMS.discard(m.from_user.id)
    await m.answer(START_TEXT, reply_markup=ReplyKeyboardRemove())
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


@router.message(F.text)
async def on_text(m: Message):
    uid = m.from_user.id
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
    if not (TOKEN and YC_KEY and YC_FOLDER):
        raise SystemExit("Не заданы TG_BOT_TOKEN, YC_API_KEY или YC_FOLDER_ID")
    bot = Bot(TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()
    dp.include_router(router)
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
