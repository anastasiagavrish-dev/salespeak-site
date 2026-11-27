"""Telegram-бот «Разбор переписки» – принимает заявки на бесплатный разбор переписки для Анастасии.

Человек присылает скрины и одной строкой пишет, что продает, отвечает, можно ли показать разбор в блоге без имен.
Заявка приходит Анастасии в Telegram. Она отвечает реплаем на сообщение с заявкой – бот передает ответ человеку.
Настройки – в /etc/razbor-bot.env (см. deploy/razbor-bot.sh)."""
import asyncio
import html
import json
import logging
import os
import time
from datetime import datetime, timezone, timedelta

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.types import (CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto, KeyboardButton, Message,
                           ReplyKeyboardMarkup, ReplyKeyboardRemove)

TOKEN = os.environ.get("RAZBOR_BOT_TOKEN", "")
DATA_DIR = os.environ.get("BOT_DATA", "/var/lib/razbor-bot")
ADMINS = {x.strip().lstrip("@").lower() for x in os.environ.get("ADMIN_USERNAMES", "gavrish_anastasiya").split(",") if x.strip()}
DAYS = os.environ.get("ANSWER_DAYS", "3–5 дней")
MAX_SHOTS = 20
PER_DAY = 3
TZ = timezone(timedelta(hours=5))  # Алматы

log = logging.getLogger("razbor")
router = Router()

BTN_SEND = "✅ Отправить на разбор"
SEND_KB = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text=BTN_SEND)]], resize_keyboard=True,
                              input_field_placeholder="Что вы продаете?")
CONSENT_KB = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text="Да, можно без имен", callback_data="c:yes")],
    [InlineKeyboardButton(text="Нет, только для меня", callback_data="c:no")]])

START_TEXT = (
    "Здравствуйте! Это бот Анастасии Гавриш для бесплатного разбора переписки.\n\n"
    "Пришлите сюда скрины переписки, где клиент замолчал или пропал после цены, и одной строкой напишите, что вы продаете. "
    f"Можно до {MAX_SHOTS} скринов.\n\n"
    "Перед отправкой закрасьте имена и телефоны ваших клиентов – для разбора они не нужны.\n\n"
    f"Когда все пришлете, нажмите «{BTN_SEND[2:]}». Анастасия разберет переписку в течение {DAYS} и пришлет ответ сюда, в этот чат.")


# ---------------- хранилище ----------------
def _path(name):
    return os.path.join(DATA_DIR, name)


def load(name, default):
    try:
        with open(_path(name), encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def save(name, data):
    os.makedirs(DATA_DIR, exist_ok=True)
    tmp = _path(name + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.replace(tmp, _path(name))


REQS = load("requests.json", [])          # заявки
ADMIN_CHATS = load("admins.json", {})     # username -> chat_id
LINKS = load("links.json", {})            # "chat:msg" у Анастасии -> номер заявки
DRAFTS = {}                               # uid -> черновик заявки


def link_key(chat_id, msg_id):
    return f"{chat_id}:{msg_id}"


def remember(chat_id, msg_id, num):
    LINKS[link_key(chat_id, msg_id)] = num
    if len(LINKS) > 5000:  # не даем файлу расти бесконечно
        for k in list(LINKS)[:1000]:
            LINKS.pop(k, None)
    save("links.json", LINKS)


def req(num):
    return next((r for r in REQS if r["num"] == num), None)


def esc(s):
    return html.escape(s or "")


def now_text(ts):
    return datetime.fromtimestamp(ts, TZ).strftime("%d.%m %H:%M")


def is_admin(u):
    return bool(u and u.username and u.username.lower() in ADMINS)


def who(u):
    name = esc(" ".join(x for x in [u.get("first"), u.get("last")] if x)) or "без имени"
    return f"{name} (@{esc(u['username'])})" if u.get("username") else f"{name}, id {u['id']}"


def draft(uid):
    return DRAFTS.setdefault(uid, {"photos": [], "docs": [], "text": []})


# ---------------- Анастасия ----------------
async def notify(bot, r):
    if not ADMIN_CHATS:
        log.warning("Заявка №%s сохранена, но Анастасия еще не нажала /start в боте", r["num"])
        return
    head = (f"📩 <b>Заявка №{r['num']} на разбор</b>\n"
            f"От: {who(r['user'])}\n"
            f"Что продает: {esc(r['text']) or '—'}\n"
            f"Показать в блоге без имен: {'да' if r['consent'] else 'нет'}\n"
            f"Скринов: {len(r['photos']) + len(r['docs'])}\n\n"
            "Чтобы ответить человеку, ответьте на это сообщение (Reply) текстом, голосовым или файлом.")
    for chat in ADMIN_CHATS.values():
        try:
            await send_request(bot, chat, r, head)
        except Exception as e:
            log.warning("не удалось отправить заявку №%s в %s: %s", r["num"], chat, e)


async def send_request(bot, chat, r, head):
    m = await bot.send_message(chat, head)
    remember(chat, m.message_id, r["num"])
    for i in range(0, len(r["photos"]), 10):
        group = [InputMediaPhoto(media=f) for f in r["photos"][i:i + 10]]
        for sent in await bot.send_media_group(chat, group):
            remember(chat, sent.message_id, r["num"])
    for d in r["docs"]:
        sent = await bot.send_document(chat, d)
        remember(chat, sent.message_id, r["num"])


@router.message(Command("zayavki"), F.func(lambda m: is_admin(m.from_user)))
async def cmd_list(m: Message):
    if not REQS:
        await m.answer("Заявок пока нет.")
        return
    lines = []
    for r in REQS[-15:][::-1]:
        st = "✅ отвечено" if r.get("answered") else "⏳ ждет"
        lines.append(f"№{r['num']} · {now_text(r['ts'])} · {who(r['user'])} · {st}\n{esc(r['text'][:80])}")
    await m.answer("Последние заявки:\n\n" + "\n\n".join(lines) + "\n\nОткрыть заявку целиком – /z номер, например /z 3")


@router.message(Command("z"), F.func(lambda m: is_admin(m.from_user)))
async def cmd_one(m: Message):
    parts = (m.text or "").split()
    r = req(int(parts[1])) if len(parts) > 1 and parts[1].isdigit() else None
    if not r:
        await m.answer("Такой заявки нет. Список – /zayavki")
        return
    head = (f"📩 <b>Заявка №{r['num']}</b> от {now_text(r['ts'])}\nОт: {who(r['user'])}\n"
            f"Что продает: {esc(r['text']) or '—'}\nПоказать в блоге без имен: {'да' if r['consent'] else 'нет'}\n"
            f"Статус: {'отвечено' if r.get('answered') else 'ждет ответа'}\n\nОтветить – Reply на это сообщение.")
    await send_request(m.bot, m.chat.id, r, head)


@router.message(F.func(lambda m: is_admin(m.from_user)) & F.reply_to_message)
async def admin_reply(m: Message):
    num = LINKS.get(link_key(m.chat.id, m.reply_to_message.message_id))
    r = req(num) if num else None
    if not r:
        await m.answer("Не найдено, к какой заявке этот ответ. Ответьте (Reply) на сообщение с заявкой или на один из ее скринов.")
        return
    try:
        await m.bot.send_message(r["user"]["chat"], f"Ответ Анастасии по заявке №{r['num']}:")
        await m.copy_to(r["user"]["chat"])
    except Exception as e:
        await m.answer(f"Не получилось отправить: {esc(str(e))}. Возможно, человек заблокировал бота.")
        return
    r["answered"] = True
    save("requests.json", REQS)
    await m.answer(f"Отправлено в заявку №{r['num']}.")


# ---------------- человек ----------------
@router.message(CommandStart())
async def cmd_start(m: Message):
    if is_admin(m.from_user):
        ADMIN_CHATS[m.from_user.username.lower()] = m.chat.id
        save("admins.json", ADMIN_CHATS)
        waiting = sum(1 for r in REQS if not r.get("answered"))
        await m.answer("Готово – заявки на разбор будут приходить сюда.\n\n"
                       "Чтобы ответить человеку, ответьте (Reply) на сообщение с заявкой – текстом, голосовым или файлом, "
                       "бот передаст ответ.\n/zayavki – последние заявки, /z номер – открыть заявку."
                       + (f"\n\nЖдут ответа: {waiting}." if waiting else ""), reply_markup=ReplyKeyboardRemove())
        return
    DRAFTS.pop(m.from_user.id, None)
    await m.answer(START_TEXT, reply_markup=ReplyKeyboardRemove())


def too_many(uid):
    day_ago = time.time() - 86400
    return sum(1 for r in REQS if r["user"]["id"] == uid and r["ts"] > day_ago) >= PER_DAY


async def got_shot(m: Message, kind, file_id):
    d = draft(m.from_user.id)
    if len(d["photos"]) + len(d["docs"]) >= MAX_SHOTS:
        await m.answer(f"Больше {MAX_SHOTS} скринов не нужно – этого хватит для разбора. Нажмите «{BTN_SEND[2:]}».",
                       reply_markup=SEND_KB)
        return
    d[kind].append(file_id)
    if m.caption:
        d["text"].append(m.caption.strip())
    if m.media_group_id:  # альбом приходит пачкой – отвечаем один раз
        if d.get("album") == m.media_group_id:
            return
        d["album"] = m.media_group_id
        await asyncio.sleep(1.5)
    n = len(d["photos"]) + len(d["docs"])
    tip = "Пришлите еще или нажмите кнопку." if d["text"] else "Пришлите еще скрины или напишите одной строкой, что вы продаете."
    await m.answer(f"Скринов получено: {n}. {tip}", reply_markup=SEND_KB)


@router.message(F.photo)
async def on_photo(m: Message):
    await got_shot(m, "photos", m.photo[-1].file_id)


@router.message(F.document)
async def on_doc(m: Message):
    mime = m.document.mime_type or ""
    if not (mime.startswith("image/") or mime == "application/pdf"):
        await m.answer("Пришлите, пожалуйста, скрины переписки – картинками или файлами-изображениями.")
        return
    await got_shot(m, "docs", m.document.file_id)


@router.message(F.text == BTN_SEND)
async def on_send(m: Message):
    d = DRAFTS.get(m.from_user.id)
    if not d or not (d["photos"] or d["docs"]):
        await m.answer("Сначала пришлите хотя бы один скрин переписки.")
        return
    if not d["text"]:
        await m.answer("Напишите одной строкой, что вы продаете, – так разбор будет точнее. Потом снова нажмите кнопку.",
                       reply_markup=SEND_KB)
        return
    if too_many(m.from_user.id):
        await m.answer("За сутки можно отправить до трех переписок. Остальные пришлите завтра – черновик сохранится.")
        return
    await m.answer("Последний вопрос. Можно ли без имен и контактов показать вашу переписку в разборе для блога Анастасии? "
                   "На сам разбор это не влияет.", reply_markup=ReplyKeyboardRemove())
    await m.answer("Выберите вариант:", reply_markup=CONSENT_KB)


@router.callback_query(F.data.startswith("c:"))
async def on_consent(q: CallbackQuery):
    uid = q.from_user.id
    d = DRAFTS.pop(uid, None)
    await q.answer()
    if not d or not (d["photos"] or d["docs"]):
        await q.message.edit_text("Эта заявка уже отправлена. Чтобы прислать новую переписку, просто отправьте скрины.")
        return
    u = q.from_user
    r = dict(num=(REQS[-1]["num"] + 1 if REQS else 1), ts=time.time(),
             user=dict(id=u.id, chat=q.message.chat.id, username=u.username, first=u.first_name, last=u.last_name),
             text=" / ".join(d["text"])[:1500], photos=d["photos"], docs=d["docs"], consent=q.data == "c:yes", answered=False)
    REQS.append(r)
    save("requests.json", REQS)
    await q.message.edit_text(f"Готово, заявка №{r['num']} принята. Анастасия разберет переписку в течение {DAYS} "
                              "и пришлет ответ сюда, в этот чат.\n\nЧтобы прислать еще одну переписку, просто отправьте новые скрины.")
    await notify(q.bot, r)


@router.message(F.text)
async def on_text(m: Message):
    if is_admin(m.from_user):
        await m.answer("Чтобы ответить человеку, ответьте (Reply) на сообщение с заявкой. /zayavki – список заявок.")
        return
    uid = m.from_user.id
    d = DRAFTS.get(uid)
    earlier = [r for r in REQS if r["user"]["id"] == uid]
    if not d and earlier:  # пишет после заявки – передаем Анастасии
        r = earlier[-1]
        for chat in ADMIN_CHATS.values():
            try:
                s = await m.bot.send_message(chat, f"💬 Сообщение по заявке №{r['num']} от {who(r['user'])}:\n\n{esc(m.text)}")
                remember(chat, s.message_id, r["num"])
            except Exception as e:
                log.warning("не удалось переслать сообщение: %s", e)
        await m.answer("Передано Анастасии. Чтобы прислать новую переписку на разбор, отправьте скрины.")
        return
    d = draft(uid)
    d["text"].append(m.text.strip())
    if d["photos"] or d["docs"]:
        await m.answer(f"Записано. Если все готово – нажмите «{BTN_SEND[2:]}».", reply_markup=SEND_KB)
    else:
        await m.answer("Записано. Теперь пришлите скрины переписки, где клиент замолчал или пропал после цены.")


@router.message()
async def other(m: Message):
    await m.answer("Пришлите, пожалуйста, скрины переписки и одной строкой напишите, что вы продаете.")


async def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if not TOKEN:
        raise SystemExit("Не задан RAZBOR_BOT_TOKEN")
    bot = Bot(TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()
    dp.include_router(router)
    await bot.delete_webhook(drop_pending_updates=False)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
