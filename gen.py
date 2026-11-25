"""Сборка статического сайта a-gavrish.com.

python3 gen.py            → public/   (боевая версия, ссылки вида /uslugi/audit/)
python3 gen.py preview    → preview/  (для превью-артефакта, относительные ссылки на index.html, форма без бэкенда)
"""
import html, json, os, re, shutil, sys
from content import SERVICES, SVC, CASES, CASE, CASE_FULL, FAQ_HOME, TG, WA, PHONE_TXT, GAME_BOT, GAME_WEB

PREVIEW = len(sys.argv) > 1 and sys.argv[1] == "preview"
ROOT = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(ROOT, "preview" if PREVIEW else "public")
SITE = "https://a-gavrish.com"
KZ_API = ""  # адрес приема заявок в Казахстане, когда появится хостинг в РК
METRIKA_ID = "114339872"  # номер счетчика Яндекс Метрики (a-gavrish.com)
YANDEX_VERIFICATION = "d59ad12dec1ec192"  # Яндекс Вебмастер
GOOGLE_VERIFICATION = "AS5q5OC1Cb9ig-yKfKVePH5TA7Dw2NGGUOeTEv4HzgM"  # Google Search Console
VERIFY_META = "".join(f'<meta name="{n}" content="{v}">' for n, v in
                      [("yandex-verification", YANDEX_VERIFICATION), ("google-site-verification", GOOGLE_VERIFICATION)] if v)
CONSENT_VERSION = "2026-11-03"
E = html.escape

_cur = ""  # путь текущей страницы, нужен для относительных ссылок в превью


def u(path):
    """Ссылка на страницу. path – 'uslugi/audit/' или '' для главной, может содержать #якорь."""
    path, _, anchor = path.partition("#")
    anchor = "#" + anchor if anchor else ""
    if not PREVIEW:
        return "/" + path + anchor
    depth = _cur.count("/")
    target = path + ("index.html" if path == "" or path.endswith("/") else "")
    return "../" * depth + target + anchor


def a(path):
    """Ссылка на файл из assets, с меткой версии – браузер берет новый файл после каждого изменения."""
    url = ("../" * _cur.count("/") if PREVIEW else "/") + "assets/" + path
    f = os.path.join(OUT, "assets", path)
    if os.path.isfile(f) and not PREVIEW:
        import hashlib
        url += "?v=" + hashlib.md5(open(f, "rb").read()).hexdigest()[:8]
    return url


NAV = [("uslugi/", "Услуги"), ("metod/", "Метод"), ("cases/", "Кейсы"), ("blog/", "Блог"), ("about/", "Обо мне")]


def header(offer_href):
    items = "".join(f'<a href="{u(p)}"{" aria-current=page" if _cur.startswith(p) else ""}>{t}</a>' for p, t in NAV)
    return f"""<a class="skip" href="#main">К содержанию</a>
<header class="top"><div class="wrap top-in">
<a class="logo" href="{u('')}"><span class="logo-mark" aria-hidden="true">G</span><span class="logo-t"><b>Анастасия Гавриш</b><small>эксперт по продажам</small></span></a>
<nav class="nav" aria-label="Разделы">{items}</nav>
<a class="nav-game" href="{GAME_BOT}" data-game><span class="nav-game-dot" aria-hidden="true"></span><span class="nav-game-long">Игра для менеджеров</span><span class="nav-game-short">Игра</span></a>
<a class="btn btn-sm" href="{offer_href}">Хочу разбор</a>
</div>
<a class="game-strip" href="{GAME_BOT}" data-game><b>Игра для менеджеров «Касса тает»</b> <span>проверьте свои продажи в Telegram</span></a></header>"""


def game_band():
    """Блок игры «Касса тает» – на главной. Основная кнопка ведет в Telegram-бот, запасная – в браузер."""
    return f"""<section class="game-band" id="game"><div class="wrap game-band-in">
<div class="game-band-text"><p class="label">Игра для менеджеров</p><h2>«Касса тает» – проверьте, сколько денег теряется в переписке</h2>
<p>Пять клиентов из вашей ниши по очереди пишут менеджеру – недвижимость, стоматология, спа, турагентство, B2B и другие. Каждый слитый клиент забирает деньги из кассы, а после каждого диалога нейросеть показывает ошибки и как стоило ответить.</p>
<p>Хотите проверить всю команду? В боте есть режим «Проверить мой отдел продаж» – менеджеры проходят игру по вашей ссылке, а результаты каждого приходят вам. Код доступа к нему пришлю по запросу в <a href="{TG}">Telegram</a>.</p></div>
<div class="game-band-cta"><a class="btn" href="{GAME_BOT}" data-game>Играть в Telegram</a><a class="game-band-alt" href="{GAME_WEB}" data-game>Нет Telegram? Играть в браузере</a><p>Бесплатно</p></div>
</div></section>"""


def footer():
    return f"""<footer class="foot"><div class="wrap foot-in">
<div><b>Анастасия Гавриш</b><p>Эксперт по продажам, Алматы</p><p class="foot-small">Telegram <a href="{TG}">@gavrish_anastasiya</a><br>WhatsApp <span class="sel">{PHONE_TXT}</span></p><p class="foot-small">Каналы в Telegram<br><a href="https://t.me/sdelkazasdelkoi">«Сделка за сделкой»</a><br><a href="https://t.me/razborprodaj">«Разборы продаж»</a></p><p class="foot-small">Игра для менеджеров<br><a href="{GAME_BOT}" data-game>«Касса тает» в Telegram</a></p></div>
<nav aria-label="Разделы сайта">{''.join(f'<a href="{u(p)}">{t}</a>' for p, t in NAV)}</nav>
<nav aria-label="Документы"><a href="{u('privacy/')}">Политика конфиденциальности</a><a href="{u('soglasie/')}">Согласие на обработку данных</a><a href="{u('soglasie-reklama/')}">Согласие на рекламные рассылки</a><button class="linklike" type="button" data-cookie-settings>Настройки cookie</button></nav>
</div></footer>
<div class="cookie" id="cookie" hidden role="region" aria-label="Cookie">
<p>Сайт использует cookie и Яндекс Метрику, чтобы понимать, какие страницы полезны. Подробнее в <a href="{u('privacy/')}">политике конфиденциальности</a>.</p>
<div class="cookie-btns"><button class="btn btn-sm" type="button" data-cookie="yes">Принять</button><button class="btn btn-sm btn-ghost" type="button" data-cookie="no">Отклонить</button></div>
</div>"""


def lead_form(fid="lead"):
    return f"""<form class="form" id="{fid}-form" novalidate data-kz-api="{'' if PREVIEW else KZ_API}" data-preview="{'1' if PREVIEW else ''}">
<div class="field"><label for="{fid}-name">Имя</label><input id="{fid}-name" name="name" autocomplete="name" required maxlength="120"><p class="err" hidden></p></div>
<div class="field"><label for="{fid}-contact">Телефон или Telegram</label><input id="{fid}-contact" name="contact" autocomplete="tel" inputmode="text" required maxlength="120" placeholder="+7 … или @ник"><p class="err" hidden></p></div>
<fieldset class="field country" hidden><legend>Где вы находитесь</legend>
<label class="radio"><input type="radio" name="country" value="ru"> Россия</label><label class="radio"><input type="radio" name="country" value="kz"> Казахстан</label><label class="radio"><input type="radio" name="country" value="other"> Другая страна</label><p class="err" hidden></p></fieldset>
<div class="field"><label for="{fid}-pain">Что сейчас не так с продажами <span class="opt">необязательно</span></label><textarea id="{fid}-pain" name="pain" rows="3" maxlength="2000"></textarea></div>
<div class="hp" aria-hidden="true"><label for="{fid}-website">Сайт</label><input id="{fid}-website" name="website" tabindex="-1" autocomplete="off"></div>
<div class="field"><label class="check" for="{fid}-pd"><input type="checkbox" id="{fid}-pd" name="consent_pd"><span>Даю <a href="{u('soglasie/')}">согласие на обработку персональных данных</a> и принимаю <a href="{u('privacy/')}">политику конфиденциальности</a></span></label><p class="err" hidden></p></div>
<label class="check" for="{fid}-ads"><input type="checkbox" id="{fid}-ads" name="consent_ads"><span>Хочу получать полезные материалы и анонсы, <a href="{u('soglasie-reklama/')}">согласие на рассылку</a> <span class="opt">необязательно</span></span></label>
<button class="btn btn-wide" type="submit">Хочу разбор переписок</button>
<p class="form-err" role="alert" hidden></p>
<div class="form-kz" hidden><b>Для заявок из Казахстана пока работает мессенджер</b><p>Напишите мне в <a href="{TG}">Telegram</a> или <a href="{WA}">WhatsApp</a> – отвечу там и договоримся о разборе.</p></div>
<div class="form-ok" hidden tabindex="-1"><b>Заявка принята</b><p>Напишу вам в течение рабочего дня и договоримся о времени созвона.</p></div>
</form>"""


def offer_block():
    return f"""<section class="offer" id="offer"><div class="wrap offer-in">
<div class="offer-text"><p class="label">Бесплатно</p><h2>Разбор переписок вашего отдела продаж</h2>
<ul class="offer-facts"><li><b>Вы присылаете</b> 4–6 переписок или звонков менеджеров</li><li><b>Вы получаете</b> разбор ошибок по этапам продаж и рекомендации, что исправить первым</li><li><b>Формат</b> созвон в Zoom до 1 часа</li></ul>
<p class="offer-msgr">Удобнее в мессенджере? Пишите в <a href="{TG}">Telegram</a> или <a href="{WA}">WhatsApp</a>.</p></div>
{lead_form()}</div></section>"""


def breadcrumbs(items):
    """items – [(path, title)], последний без ссылки."""
    parts = [f'<a href="{u("")}">Главная</a>'] + [f'<a href="{u(p)}">{E(t)}</a>' if i < len(items) - 1 else f'<span aria-current="page">{E(t)}</span>' for i, (p, t) in enumerate(items)]
    ld = {"@context": "https://schema.org", "@type": "BreadcrumbList", "itemListElement": [
        {"@type": "ListItem", "position": i + 1, "name": t, "item": SITE + "/" + p} for i, (p, t) in enumerate([("", "Главная")] + items)]}
    return f'<nav class="crumbs" aria-label="Хлебные крошки"><div class="wrap">{" <span aria-hidden=true>/</span> ".join(parts)}</div></nav>', ld


PERSON = {"@type": "Person", "@id": SITE + "/#person", "name": "Анастасия Гавриш", "jobTitle": "Эксперт по продажам",
          "url": SITE + "/", "sameAs": ["https://www.instagram.com/an.gavrish/", TG, "https://t.me/sdelkazasdelkoi", "https://t.me/razborprodaj"],
          "address": {"@type": "PostalAddress", "addressLocality": "Алматы", "addressCountry": "KZ"},
          "alumniOf": ["МГТУ им. Н. Э. Баумана", "Московская школа кино"],
          "knowsAbout": ["Аудит отдела продаж", "Скрипты продаж", "Построение отдела продаж", "Тренинги по продажам", "Продажи в переписке", "Холодные продажи B2B"]}


def layout(path, title, desc, body, ld=None, noindex=False):
    global _cur
    _cur = path
    lds = ld if isinstance(ld, list) else ([ld] if ld else [])
    ld_html = "".join(f'<script type="application/ld+json">{json.dumps(x, ensure_ascii=False)}</script>' for x in lds)
    canon = SITE + "/" + path
    full_title = title if "Анастасия Гавриш" in title else f"{title} | Анастасия Гавриш"
    page = f"""<!doctype html>
<html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>{E(full_title)}</title><meta name="description" content="{E(desc)}">
<link rel="canonical" href="{canon}">{'<meta name="robots" content="noindex">' if noindex or PREVIEW else ''}
<meta property="og:type" content="website"><meta property="og:locale" content="ru_RU"><meta property="og:title" content="{E(full_title)}"><meta property="og:description" content="{E(desc)}"><meta property="og:url" content="{canon}"><meta property="og:image" content="{SITE}/assets/og.jpg">
<meta name="theme-color" content="#4B3FE1">{VERIFY_META}<link rel="icon" href="{a('favicon.svg')}" type="image/svg+xml">
<link rel="preload" href="{a('fonts/unbounded-cyrillic-600-normal.woff2')}" as="font" type="font/woff2" crossorigin>
<link rel="preload" href="{a('fonts/montserrat-cyrillic-500-normal.woff2')}" as="font" type="font/woff2" crossorigin>
<link rel="stylesheet" href="{a('fonts.css')}"><link rel="stylesheet" href="{a('site.css')}">{ld_html}
</head><body data-metrika="{METRIKA_ID}" data-consent="{CONSENT_VERSION}">
{header("#offer" if 'id="offer"' in body else u("") + "#offer")}
<main id="main">{body}</main>
{footer()}
<script src="{a('site.js')}" defer></script>
</body></html>"""
    page = re.sub(r"<a\b[^>]*>", _external_blank, page)
    dest = os.path.join(OUT, path, "index.html") if path.endswith("/") or path == "" else os.path.join(OUT, path)
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    open(dest, "w").write(page)
    if not noindex:
        SITEMAP.append(path)


def _external_blank(m):
    """Внешние ссылки (Telegram, WhatsApp, другие сайты) открываются в новой вкладке, внутренние – в той же."""
    tag = m.group(0)
    href = re.search(r'href="([^"]*)"', tag)
    if not href or "target=" in tag:
        return tag
    h = href.group(1)
    if h.startswith(("http://", "https://", "//")) and not h.startswith(SITE):
        return tag[:-1] + ' target="_blank" rel="noopener">'
    return tag


SITEMAP = []


def case_card(c):
    tag = "a" if c["full"] else "div"
    href = f' href="{u("cases/" + c["slug"] + "/")}"' if c["full"] else ""
    soon = "" if c["full"] else '<span class="case-soon">Переносим на новый сайт</span>'
    return f"""<{tag} class="case" data-tags="{' '.join(c['tags'])}"{href}><span class="case-niche">{E(c['niche'])}</span><b class="case-num">{E(c['metric'])}</b><span class="case-txt">{E(c['metric_txt'])}</span>{soon}</{tag}>"""


def faq_block(items, head=True):
    if not items:
        return "", None
    det = "".join(f"<details><summary>{E(q)}</summary><p>{E(ans)}</p></details>" for q, ans in items)
    ld = {"@context": "https://schema.org", "@type": "FAQPage", "mainEntity": [
        {"@type": "Question", "name": q, "acceptedAnswer": {"@type": "Answer", "text": ans}} for q, ans in items]}
    return f"""<section class="faq" aria-label="Частые вопросы"><div class="wrap faq-in"><div class="sec-head"><p class="label">Вопросы</p><h2>Частые вопросы</h2></div><div class="faq-list">{det}</div></div></section>""", ld


# ---------------- страницы ----------------

HOME_MORE = {"kontrol-kachestva"}  # услуги, которые на главной идут ссылкой «Еще – …», а не карточкой
PRINCIPLES = "".join(f"<li>{p}</li>" for p in [
    "Экологичные продажи без манипуляций и давления – продаем решение проблемы и только тем, кому можем помочь",
    "Человеческие продажи вместо «Добрый день, интересует?»",
    "Клиент должен покупать легко и с удовольствием, а не продираться через плохие скрипты",
    "В 90% случаев проблема не там, где думает собственник – поэтому сначала разбираю вашу ситуацию, потом предлагаю решение",
    "Плохой продавец обворовывает собственника, но плохих менеджеров нет – есть необученные",
    "В аудите только факты – каждый вывод подтверждаю вашими диалогами и цифрами",
    "Работаю в формате, удобном вашей команде, чтобы внедрение не требовало лишних усилий",
    "Не бросаю на полпути – довожу инструмент до внедрения и проверяю, что он работает",
    "Работаю только с качественными продуктами и часто сама становлюсь клиентом своих клиентов",
    "Берусь за работу, только если уверена в результате"])


def home():
    global _cur
    _cur = ""
    svc = "".join(f"""<article class="svc"><h3><a href="{u('uslugi/' + s['slug'] + '/')}">{E(s['name'])}</a></h3><dl><dt>Кому</dt><dd>{E(s['short_who'])}</dd><dt>Что изменится</dt><dd>{E(s['short_what'])}</dd></dl></article>"""
                  for s in SERVICES if s["slug"] not in HOME_MORE)
    more = ", ".join(f'<a href="{u("uslugi/" + s["slug"] + "/")}">{E(s["name"].lower())}</a>' for s in SERVICES if s["slug"] in HOME_MORE)
    cases = "".join(case_card(CASE[k]) for k in ["africa", "b2b-case", "kpi-za-3-dnya", "cosmetic"])
    faq, faq_ld = faq_block(FAQ_HOME)
    body = f"""
<section class="hero"><div class="wrap hero-in"><div class="hero-text">
<p class="eyebrow">Аудит и построение отделов продаж</p>
<h1>Найду, где ваш отдел продаж <mark>теряет деньги</mark>, и исправлю это</h1>
<p class="lead">Аудит, скрипты, обучение и построение отдела продаж. 16 лет в продажах, работаю с бизнесом в России, Казахстане и везде, где продают на русском.</p>
<div class="hero-cta"><a class="btn" href="#offer">Хочу разбор переписок</a><span class="msgr">или напишите в <a href="{TG}">Telegram</a> и <a href="{WA}">WhatsApp</a></span></div></div>
<figure class="hero-photo"><img src="{a('img/hero.webp')}" width="760" height="950" alt="Анастасия Гавриш, эксперт по продажам" fetchpriority="high"><figcaption><b>Анастасия Гавриш</b><span>эксперт по продажам</span></figcaption></figure>
</div></section>
<section class="facts" aria-label="Цифры"><div class="wrap"><ul class="facts-list">
<li><b>16+</b><span>лет в продажах и маркетинге</span></li><li><b>200 млн ₸</b><span>личных B2B-продаж за 2024 год</span></li><li><b>{len(CASES)}</b><span>проектов, разобранных в кейсах</span></li></ul>
<p class="niches"><span>Ниши клиентов</span> туризм, медицина, бигтех, B2B-дистрибуция, маркетплейсы, ивенты, реклама, детская одежда</p></div></section>
{game_band()}
<section class="sit" id="situations"><div class="wrap"><div class="sec-head"><p class="label">Ваша ситуация</p><h2>С чем ко мне приходят</h2></div><ol class="sit-list">
<li><p class="quote">«Отдела продаж нет, все держится на мне»</p><p class="ans">Соберу отдел с нуля или возьму роль РОПа на время, пока система не заработает без вас.</p><a href="{u('uslugi/otdel-prodazh/')}">Построение отдела продаж</a></li>
<li><p class="quote">«Лиды идут, а продаж мало»</p><p class="ans">Найду, на каком этапе менеджеры теряют клиентов, и дам им скрипт, который ведет до оплаты.</p><a href="{u('uslugi/audit/')}">Аудит отдела продаж</a></li>
<li><p class="quote">«Команда есть, но продает слабо»</p><p class="ans">Обучу на ваших реальных диалогах и буду регулярно разбирать звонки и переписки.</p><a href="{u('uslugi/treningi/')}">Тренинги по продажам</a></li></ol></div></section>
<section class="method" id="method"><div class="wrap"><div class="sec-head"><p class="label">Метод</p><h2>Сначала диагноз, потом инструменты</h2>
<p class="sec-lead">Мы продаем человеку решение его проблемы, а не продукт. Поэтому работа начинается с того, что я смотрю, как ваши менеджеры продают на самом деле.</p></div>
<ol class="steps">
<li><h3>Аудит и тайный покупатель</h3><p>Разбираю 4–6 ваших переписок или звонков и сама пишу менеджерам как клиент, с возражениями «дорого» и «я подумаю».</p></li>
<li><h3>Вердикт по каждому диалогу</h3><p>Что хорошо, что мешает продать, и аналитическая справка о работе всего отдела.</p></li>
<li><h3>Показываю результаты</h3><p>На созвоне называю точки роста и инструменты, которые помогут поднять выручку и конверсию.</p></li>
<li><h3>Внедрение</h3><p>Скрипт в удобном для команды формате – Word, Excel или программа для скриптов. Обучение, регламенты, мотивация, при необходимости найм.</p></li>
<li><h3>Сопровождение</h3><p>Слушаю звонки после внедрения, вношу правки, тренирую команду.</p></li></ol>
<a class="more" href="{u('metod/')}">Подробнее о методе</a></div></section>
<section class="services" id="services"><div class="wrap"><div class="sec-head"><p class="label">Услуги</p><h2>Чем могу помочь</h2></div>
<div class="svc-list">{svc}</div><p class="svc-more">Еще – {more}.</p></div></section>
<section class="cases" id="cases"><div class="wrap"><div class="sec-head"><p class="label">Кейсы</p><h2>Что получилось у клиентов</h2></div>
<div class="case-grid">{cases}</div><a class="more" href="{u('cases/')}">Все кейсы</a></div></section>
{offer_block()}
<section class="about" id="about"><div class="wrap about-in"><div class="about-text"><p class="label">Обо мне</p><h2>Практик, который продает сам</h2>
<p>Я в продажах и маркетинге с 2010 года. До консалтинга 7 лет была кинопродюсером, сняла 4 полнометражных фильма и сериал, продавала фильмы в прокат в 11 стран. Сейчас помогаю собственникам растить компании через отделы продаж и продолжаю продавать сама.</p>
<a class="more" href="{u('about/')}">Подробнее обо мне</a></div>
<ul class="about-facts"><li><b>200 млн ₸</b>личных B2B-продаж за 2024 год</li><li><b>500 млн ₽</b>привлекла в Фонде кино и Минкультуры на производство фильмов</li><li><b>Образование</b>МГТУ им. Баумана и Московская школа кино</li><li><b>Училась продажам у</b>Михаила Уколова, Настасьи Белочкиной, Виталия Говорухина</li></ul></div></section>
<section class="princ" aria-label="Принципы"><div class="wrap"><div class="sec-head"><p class="label">Принципы</p><h2>Как я работаю</h2></div>
<ol class="princ-list">{PRINCIPLES}</ol></div></section>
{faq}
<section class="final"><div class="wrap final-in"><h2>Покажите переписки, а я покажу, где теряются деньги</h2><a class="btn" href="#offer">Хочу разбор переписок</a><p class="msgr">Telegram <a href="{TG}">@gavrish_anastasiya</a>, WhatsApp <span class="sel">{PHONE_TXT}</span></p></div></section>"""
    ld = [{"@context": "https://schema.org", "@graph": [PERSON, {"@type": "ProfessionalService", "@id": SITE + "/#service", "name": "Анастасия Гавриш – консалтинг по продажам", "url": SITE + "/",
           "founder": {"@id": SITE + "/#person"}, "areaServed": ["RU", "KZ"], "address": {"@type": "PostalAddress", "addressLocality": "Алматы", "addressCountry": "KZ"},
           "description": "Аудит отдела продаж, скрипты продаж, тренинги, построение отдела продаж, РОП в аренду."}]}, faq_ld]
    layout("", "Анастасия Гавриш – аудит и построение отделов продаж",
           "Эксперт по продажам Анастасия Гавриш. Аудит отдела продаж, скрипты для звонков и переписки, тренинги, построение отдела продаж и РОП в аренду. Бесплатный разбор переписок.",
           body, ld)


def services_hub():
    global _cur
    _cur = "uslugi/"
    crumbs, cld = breadcrumbs([("uslugi/", "Услуги")])
    rows = "".join(f"""<article class="svc"><h3><a href="{u('uslugi/' + s['slug'] + '/')}">{E(s['name'])}</a></h3><dl><dt>Кому</dt><dd>{E(s['short_who'])}</dd><dt>Что изменится</dt><dd>{E(s['short_what'])}</dd></dl></article>""" for s in SERVICES)
    body = f"""{crumbs}<section class="page-hero"><div class="wrap"><p class="eyebrow">Услуги</p><h1>Чем могу помочь вашему отделу продаж</h1>
<p class="lead">Любая работа начинается с бесплатного разбора переписок. По нему видно, какой инструмент нужен именно вам.</p></div></section>
<section class="services"><div class="wrap"><div class="svc-list svc-list-full">{rows}</div></div></section>{offer_block()}"""
    layout("uslugi/", "Услуги – аудит, скрипты, тренинги, построение отдела продаж",
           "Услуги эксперта по продажам Анастасии Гавриш – аудит отдела продаж, скрипты, тренинги, построение отдела продаж, РОП и тренер в аренду, холодный аутрич в B2B.", body, cld)


def service_page(s):
    global _cur
    path = f"uslugi/{s['slug']}/"
    _cur = path
    crumbs, cld = breadcrumbs([("uslugi/", "Услуги"), (path, s["name"])])
    who = "".join(f"<li>{E(x)}</li>" for x in s["who"])
    steps = "".join(f"<li><h3>{E(t)}</h3><p>{E(d)}</p></li>" for t, d in s["steps"])
    res = "".join(f"<li>{E(x)}</li>" for x in s["result"])
    note = f'<p class="note-line">{E(s["note"])}</p>' if s["note"] else ""
    cases = "".join(case_card(CASE[k]) for k in s["cases"])
    cases_html = f"""<section class="cases"><div class="wrap"><div class="sec-head"><p class="label">Кейсы</p><h2>Как это было у клиентов</h2></div><div class="case-grid">{cases}</div></div></section>""" if cases else ""
    faq, faq_ld = faq_block(s["faq"])
    others = "".join(f'<a href="{u("uslugi/" + o["slug"] + "/")}">{E(o["name"])}</a>' for o in SERVICES if o["slug"] != s["slug"])
    body = f"""{crumbs}<section class="page-hero"><div class="wrap"><p class="eyebrow">Услуга</p><h1>{E(s['name'])}</h1><p class="lead">{E(s['lead'])}</p>
<div class="hero-cta"><a class="btn" href="#offer">Хочу разбор переписок</a><span class="msgr">или напишите в <a href="{TG}">Telegram</a></span></div></div></section>
<section class="sit"><div class="wrap"><div class="sec-head"><p class="label">Кому подходит</p><h2>Узнаете свою ситуацию?</h2></div><ul class="ticks">{who}</ul></div></section>
<section class="method"><div class="wrap"><div class="sec-head"><p class="label">Как проходит</p><h2>Этапы работы</h2></div><ol class="steps">{steps}</ol>{note}</div></section>
<section class="result"><div class="wrap"><div class="sec-head"><p class="label">Результат</p><h2>Что вы получите</h2></div><ul class="ticks ticks-big">{res}</ul></div></section>
{cases_html}{related_posts(s['slug'])}{offer_block()}{faq}
<section class="also"><div class="wrap"><p class="label">Другие услуги</p><nav class="chips" aria-label="Другие услуги">{others}</nav></div></section>"""
    ld = [cld, {"@context": "https://schema.org", "@type": "Service", "name": s["name"], "description": s["desc"], "provider": {"@type": "Person", "name": "Анастасия Гавриш", "url": SITE + "/"},
                "areaServed": ["RU", "KZ"], "url": SITE + "/" + path}] + ([faq_ld] if faq_ld else [])
    layout(path, s["title"], s["desc"], body, ld)


def method_page():
    global _cur
    _cur = "metod/"
    crumbs, cld = breadcrumbs([("metod/", "Метод")])
    body = f"""{crumbs}<section class="page-hero"><div class="wrap"><p class="eyebrow">Метод</p><h1>Сначала диагноз, потом инструменты</h1>
<p class="lead">Сначала анализ – смотрю, как ваши менеджеры продают на самом деле. И только после этого предлагаю то, что подойдет именно вам.</p></div></section>
<section class="prose-sec"><div class="wrap prose">
<h2>Почему начинаем не со скрипта и не с тренинга</h2>
<p>В 90% случаев проблема не там, где думает собственник. Кто-то просит скрипт, но скрипт не поможет, потому что слабая команда. Кому-то вместо тренинга поможет скрипт, кому-то вместо долгой работы хватит одной консультации, а кому-то вместо консультации эффективнее зайти в работу на три месяца.</p>
<p class="result-p"><b>Пример из практики.</b> На аудит пришла стоматология – конверсия 30%, директор хотела 60%. Звонки администратора идеальные – по скрипту, с отработкой возражений и дожимом. А переписки как будто пишет робот. Оказалось, что администратор звонит в одном кабинете с директором, и после каждого звонка они вместе разбирают ошибки. А переписки никто не читает и не контролирует. Я сказала директору, что недостающие 30% лежат в переписках – начните их читать и разбирать с администратором, и даже я вам не понадоблюсь.</p>
<p>Аудит сразу подсвечивает слабые места. Бывает, что клиент кратно поднимает конверсию уже после аудита, просто исправив найденное. Дальше собственник может работать над ошибками сам или вместе со мной.</p>
<h2>Как устроена работа</h2>
<ol class="steps steps-prose">
<li><h3>Аудит и тайный покупатель</h3><p>Вы присылаете 4–6 переписок или звонков менеджеров – этого хватает, чтобы понять, в чем проблема. Для более глубокого анализа можно дать мне доступ к CRM на просмотр, тогда разбираю сделки прямо оттуда. Параллельно пишу вашим менеджерам как обычный клиент со стандартным набором возражений – «дорого», «я подумаю», «пока не надо», исчезнувший клиент. Под вашу нишу добавляю свои вопросы. Так я вижу реальную картину, а не только отобранные переписки.</p>
<p>Беру поровну успешные и неуспешные сделки и сравниваю, чем они отличаются – от первого сообщения клиента до оплаты. Так видно, что уже работает и что можно масштабировать, а где теряется клиент. Читаю и ваши шаблоны для менеджеров – часто ошибки заложены именно в них.</p></li>
<li><h3>Вердикт по каждому диалогу</h3><p>Оцениваю звонки и переписки с позиций «что сейчас хорошо» и «что стоит улучшить». По каждому диалогу отмечаю, почему сделка не состоялась – ошибка менеджера, нецелевой лид или клиент просто узнавал цены. Так видно, где теряет менеджер по продажам, а где маркетинг.</p><p>Итог – аналитическая справка о работе вашего отдела продаж. В ней видно, что мешает продавать и с чего начать изменения.</p></li>
<li><h3>Показываю результаты</h3><p>Показываю результаты работы вашего отдела продаж в Zoom вам и команде. Называю точки роста и инструменты, которые помогут поднять выручку и конверсию.</p></li>
<li><h3>Внедрение</h3><p>Инструмент выбираем под вашу задачу. Это может быть скрипт в удобном для команды формате, разовый тренинг или длительное обучение менеджеров. При необходимости разрабатываю регламенты и систему мотивации, помогаю нанять менеджеров.</p>
<p>Сначала система, потом обучение. Если менеджеры вернутся с тренинга в тот же перегруз и к той же мотивации, новые навыки не приживутся. До разработки знакомлюсь с менеджерами – так внедрение идет легче. После обучения у вас остаются видеозапись и расшифровка, по ним новые менеджеры учатся сами.</p></li>
<li><h3>Сопровождение</h3><p>Скрипт – это набор гипотез, поэтому после внедрения месяц слушаю звонки или читаю переписки и вношу правки. Через месяц-полтора проводим контрольный созвон – смотрим, что внедрено и какие результаты.</p></li></ol>
<h2>Считаем цель в цифрах</h2>
<p>Желаемый рост переводим в число клиентов при вашем среднем чеке и сверяем с базой и потоком заявок. Если цифра нереальна, говорю об этом сразу.</p>
<h2>Иногда скрипт не нужен</h2>
<p>Бывает, что у команды все хорошо, кроме одного – менеджеры не предлагают оформить заказ. Тогда честно говорю, что скрипт не нужен, хватит одной фразы. Сначала ищу самое простое изменение, которое даст эффект.</p>
<h2>Где мои границы</h2>
<p>Я помогаю превращать заявки в продажи, а не привлекать трафик. Если почти все, кто пишет, покупают, проблема не в продажах, и я скажу об этом прямо. Если задача вне моего профиля, порекомендую коллегу, в котором уверена.</p>
<h2>Что нужно от вас</h2>
<p>4–6 переписок или звонков менеджеров и час на созвон. Дальше включаюсь я и говорю, где нужно ваше решение.</p>
</div></section>
<section class="princ" aria-label="Принципы"><div class="wrap"><div class="sec-head"><p class="label">Принципы</p><h2>На чем держится метод</h2></div>
<ol class="princ-list">{PRINCIPLES}</ol></div></section>
{offer_block()}"""
    layout("metod/", "Метод работы с отделом продаж – сначала аудит, потом инструменты",
           "Как Анастасия Гавриш работает с отделами продаж – аудит переписок и звонков, тайный покупатель, аналитическая справка по отделу, внедрение и сопровождение.", body, cld)


def cases_hub():
    global _cur
    _cur = "cases/"
    crumbs, cld = breadcrumbs([("cases/", "Кейсы")])
    used = []
    for c in CASES:
        for t in c["tags"]:
            if t not in used:
                used.append(t)
    chips = '<button type="button" class="chip on" data-filter="all" aria-pressed="true">Все</button>' + "".join(
        f'<button type="button" class="chip" data-filter="{t}" aria-pressed="false">{E(SVC[t]["name"])}</button>' for t in used)
    cards = "".join(f"""<article class="case-row" data-tags="{' '.join(c['tags'])}"><div><p class="case-niche">{E(c['niche'])}</p>
<h2>{f'<a href="{u("cases/" + c["slug"] + "/")}">{E(c["title"])}</a>' if c['full'] else E(c['title'])}</h2><p>{E(c['summary'])}</p>
{'' if c['full'] else '<p class="case-soon">Переносим на новый сайт</p>'}</div><div class="case-metric"><b>{E(c['metric'])}</b><span>{E(c['metric_txt'])}</span></div></article>""" for c in CASES)
    body = f"""{crumbs}<section class="page-hero"><div class="wrap"><p class="eyebrow">Кейсы</p><h1>Кейсы по продажам</h1>
<p class="lead">Описываю работу как истории – что было у клиента, что мы сделали и что из этого взять себе. Имена компаний не называю.</p></div></section>
<section class="cases-cat"><div class="wrap"><div class="chips" role="group" aria-label="Фильтр по услуге">{chips}</div><div class="case-list">{cards}</div>
<p class="empty" hidden>По этой услуге кейсов пока нет.</p></div></section>{offer_block()}"""
    layout("cases/", "Кейсы по продажам – аудит, скрипты, построение отдела продаж",
           "Кейсы Анастасии Гавриш – скрипты продаж, аудит отдела продаж, тендер в B2B, тренинги, мотивация и юнит-экономика.", body, cld)


def case_page(c):
    global _cur
    path = f"cases/{c['slug']}/"
    _cur = path
    f = CASE_FULL[c["slug"]]
    crumbs, cld = breadcrumbs([("cases/", "Кейсы"), (path, c["title"])])
    tiles = "".join(f'<li><b>{E(x)}</b><span>{E(y)}</span></li>' for x, y in f["tiles"])
    sit = "".join(f"<p>{E(p)}</p>" for p in f["situation"])
    probs = "".join(f'<li><p class="pr"><span>Было</span>{E(p)}</p><p class="fx"><span>Сделали</span>{E(x)}</p></li>' for p, x in f["problems"])
    done = "".join(f"<li>{E(d)}</li>" for d in f["done"])
    tk = "".join(f"<li>{E(t)}</li>" for t in f["takeaways"])
    svc_links = "".join(f'<a href="{u("uslugi/" + t + "/")}">{E(SVC[t]["name"])}</a>' for t in c["tags"])
    similar = [x for x in CASES if x["slug"] != c["slug"] and set(x["tags"]) & set(c["tags"])][:2] or [x for x in CASES if x["slug"] != c["slug"]][:2]
    sim = "".join(case_card(x) for x in similar)
    body = f"""{crumbs}<article><header class="page-hero case-hero"><div class="wrap"><p class="eyebrow">Кейс · {E(c['niche'])}</p><h1>{E(f['h1'])}</h1><p class="lead">{E(f['sub'])}</p>
<ul class="tiles">{tiles}</ul></div></header>
<section class="prose-sec"><div class="wrap prose"><h2>Ситуация</h2>{sit}
<h2>Что было не так и что сделали</h2><ol class="pairs">{probs}</ol>
<h2>Как шла работа</h2><ol class="done">{done}</ol>
<h2>Результат</h2><p class="result-p">{E(f['result'])}</p>
<h2>Что взять себе</h2><ul class="ticks">{tk}</ul>
<p class="anon">Имена и название компании не указаны по причине конфиденциальности.</p></div></section></article>
<section class="recog"><div class="wrap recog-in"><h2>Узнали свою ситуацию?</h2><p>Пришлите 4–6 переписок вашего отдела продаж – покажу, где теряются сделки.</p><a class="btn" href="#offer">Хочу разбор переписок</a></div></section>
<section class="also"><div class="wrap"><p class="label">Услуги из этого кейса</p><nav class="chips">{svc_links}</nav></div></section>
<section class="cases"><div class="wrap"><div class="sec-head"><p class="label">Еще кейсы</p><h2>Похожие истории</h2></div><div class="case-grid case-grid-2">{sim}</div></div></section>
{offer_block()}"""
    ld = [cld, {"@context": "https://schema.org", "@type": "Article", "headline": f["h1"], "description": f["sub"], "author": {"@type": "Person", "name": "Анастасия Гавриш", "url": SITE + "/"},
                "inLanguage": "ru", "mainEntityOfPage": SITE + "/" + path}]
    layout(path, f["h1"], f["sub"][:160], body, ld)


def about_page():
    global _cur
    _cur = "about/"
    crumbs, cld = breadcrumbs([("about/", "Обо мне")])
    body = f"""{crumbs}<section class="page-hero"><div class="wrap about-hero"><div><p class="eyebrow">Обо мне</p><h1>Анастасия Гавриш</h1>
<p class="lead">Эксперт по продажам, в маркетинге и продажах с 2010 года. Помогаю собственникам растить компании через обучение отделов продаж и разработку скриптов. Люблю разбирать продажи до костей и находить точки роста.</p>
<div class="hero-cta"><a class="btn" href="#offer">Хочу разбор переписок</a></div></div>
<figure class="hero-photo"><img src="{a('img/hero.webp')}" width="760" height="950" alt="Анастасия Гавриш"></figure></div></section>
<section class="prose-sec"><div class="wrap prose">
<h2>Люблю и умею продавать</h2><p>Только в 2024 году сделала личных продаж в B2B-сегменте больше чем на 200 миллионов тенге. Продаю сама и в холодную – нахожу людей, которые принимают решения в крупных компаниях, и довожу до сделки.</p>
<h2>Карьера в кино</h2><p>7 лет работала кинопродюсером. Сняла 4 полнометражных фильма и 1 сериал, продавала фильмы в прокат в 11 стран, управляла двумя киностудиями в Москве. Привлекла больше 500 миллионов рублей в Фонде кино и Министерстве культуры РФ на производство фильмов своих студий и сторонних продюсеров.</p>
<h2>Образование</h2><p>МГТУ им. Баумана и Московская школа кино. Училась продажам у Михаила Уколова (SOHO MBA), Настасьи Белочкиной и Виталия Говорухина.</p>
<h2>Немного биографии</h2><p>Родилась в Алматы, уехала учиться в Москву и 15 лет прожила там. С 2018 года живу и работаю в Алматы. Помимо продаж у меня есть дизайнерское агентство, которое делает постеры для кино.</p>
<h2>Увлечения</h2><p>Танцую джаз-фанк и хип-хоп, хожу в тренажерный зал, читаю все книги про продажи, до которых могу дотянуться. Люблю покупать недвижимость и путешествовать.</p>
<h2>Мои каналы</h2><p>В Telegram веду два канала – <a href="https://t.me/sdelkazasdelkoi">«Сделка за сделкой»</a> и <a href="https://t.me/razborprodaj">«Разборы продаж»</a>. Подписывайтесь.</p>
</div></section>{offer_block()}"""
    layout("about/", "Обо мне – Анастасия Гавриш, эксперт по продажам",
           "Анастасия Гавриш – эксперт по продажам с 2010 года, 200 млн тенге личных B2B-продаж за 2024 год, 7 лет в кино, МГТУ им. Баумана. Алматы.", body, [cld, {"@context": "https://schema.org", **PERSON}])


# ---------------- блог ----------------

from blog import load_posts, render_post, ru_date, game_block  # статьи – posts/*.md, разметка – blog.py

POSTS = load_posts(ROOT)


def blog_page():
    global _cur
    _cur = "blog/"
    crumbs, cld = breadcrumbs([("blog/", "Блог")])
    if POSTS:
        cards = "".join(f"""<article class="post-card"><p class="post-date">{ru_date(p['date'])}</p><h2><a href="{u('blog/' + p['slug'] + '/')}">{E(p['h1'])}</a></h2><p>{E(p['description'])}</p></article>""" for p in POSTS)
        listing = f'<section class="blog-list"><div class="wrap"><div class="post-list">{cards}</div></div></section>'
    else:
        listing = f"""<section class="blog-empty"><div class="wrap"><div class="empty-card"><h2>Первые статьи готовятся</h2><p>Пока можно почитать <a href="{u('cases/')}">кейсы</a> или подписаться на мои Telegram-каналы <a href="https://t.me/sdelkazasdelkoi">«Сделка за сделкой»</a> и <a href="https://t.me/razborprodaj">«Разборы продаж»</a>.</p></div></div></section>"""
    body = f"""{crumbs}<section class="page-hero"><div class="wrap"><p class="eyebrow">Блог</p><h1>Разборы и статьи о продажах</h1>
<p class="lead">Разборы реальных переписок, ответы на возражения и статьи о том, как устроить отдел продаж.</p></div></section>{listing}
<section class="blog-game"><div class="wrap">{game_block("div")}</div></section>{offer_block()}"""
    layout("blog/", "Блог о продажах", "Статьи и разборы о продажах, скриптах, возражениях и построении отдела продаж от Анастасии Гавриш.", body, cld)


def post_page(p):
    global _cur
    path = f"blog/{p['slug']}/"
    _cur = path
    crumbs, cld = breadcrumbs([("blog/", "Блог"), (path, p["h1"])])
    faq, faq_ld = faq_block(p["faq"])
    svc_links = "".join(f'<a href="{u("uslugi/" + k + "/")}">{E(SVC[k]["name"])}</a>' for k in p["services"] if k in SVC)
    text, side_toc = render_post(p["body"], u)
    body = f"""{crumbs}<article><header class="page-hero post-hero"><div class="wrap"><p class="eyebrow">Статья</p><h1>{E(p['h1'])}</h1>
<p class="post-meta"><span>Анастасия Гавриш, эксперт по продажам</span><span>{ru_date(p['date'])}</span><span>{p['minutes']} мин чтения</span></p></div></header>
<div class="post-sec"><div class="wrap post-layout"><div class="post-body">{text}</div><aside>{side_toc}</aside></div></div></article>
{faq}
<section class="also"><div class="wrap"><p class="label">Услуги по теме</p><nav class="chips" aria-label="Услуги по теме">{svc_links}</nav></div></section>
{offer_block()}"""
    ld = [cld, {"@context": "https://schema.org", "@type": "BlogPosting", "headline": p["h1"], "description": p["description"],
                "datePublished": p["date"], "dateModified": p.get("updated", p["date"]), "inLanguage": "ru",
                "author": {"@type": "Person", "@id": SITE + "/#person", "name": "Анастасия Гавриш", "url": SITE + "/about/"},
                "publisher": {"@type": "Person", "@id": SITE + "/#person", "name": "Анастасия Гавриш"},
                "image": SITE + "/assets/og.jpg", "mainEntityOfPage": SITE + "/" + path}] + ([faq_ld] if faq_ld else [])
    layout(path, p["title"], p["description"], body, ld)


def related_posts(slug):
    """Статьи блога, которые ссылаются на услугу, с анкором из поля services статьи."""
    links = "".join(f'<li><a href="{u("blog/" + p["slug"] + "/")}">{E(p["services"][slug])}</a></li>' for p in POSTS if slug in p["services"])
    return f'<section class="also"><div class="wrap"><p class="label">Статьи по теме</p><ul class="post-links">{links}</ul></div></section>' if links else ""


def doc_page(path, title, desc, html_body):
    global _cur
    _cur = path
    crumbs, cld = breadcrumbs([(path, title)])
    body = f"""{crumbs}<section class="page-hero doc-hero"><div class="wrap"><h1>{E(title)}</h1><p class="lead">Редакция от 3 ноября 2026 года</p></div></section>
<section class="prose-sec"><div class="wrap prose doc">{html_body}</div></section>"""
    layout(path, title, desc, body, cld)


OPERATORS = """<p><b>Оператор по данным посетителей из России и других стран (кроме Казахстана)</b> – Гавриш Анастасия, плательщик налога на профессиональный доход (самозанятая), ИНН 771594633137.</p>
<p><b>Оператор по данным посетителей из Казахстана</b> – индивидуальный предприниматель Гавриш Анастасия, ИП «Unit Pro», ИИН 851024400743, Республика Казахстан, г. Алматы, проспект Достык, 121.</p>
<p>Email для обращений по персональным данным – <span class="sel">anastasia.gavrish@gmail.com</span>.</p>"""


def docs():
    privacy = f"""<h2>1. Кто обрабатывает данные</h2>{OPERATORS}
<p>Политика составлена по требованиям Федерального закона № 152-ФЗ «О персональных данных», Закона Республики Казахстан № 94-V «О персональных данных и их защите» и Общего регламента ЕС по защите данных (GDPR) в части, применимой к посетителям из ЕС.</p>
<h2>2. Какие данные мы получаем</h2><ul><li>Имя, телефон или ник в Telegram, текст в поле «Что сейчас не так с продажами» и страна, если вы ее указали – из формы заявки.</li><li>Дата и время заявки, IP-адрес, тип браузера и версия текста согласия – чтобы подтвердить, что согласие дано.</li><li>Cookie и данные Яндекс Метрики (страницы, источники переходов, устройство) – только если вы нажали «Принять» в баннере cookie.</li></ul>
<h2>3. Зачем</h2><ul><li>Ответить на заявку, договориться о созвоне и провести разбор переписок.</li><li>Заключить и исполнить договор, если вы решите работать.</li><li>Присылать полезные материалы и анонсы – только при отдельном согласии на рассылку.</li><li>Понимать, какие страницы сайта полезны – по данным Метрики, если вы на это согласились.</li></ul>
<h2>4. Основание</h2><p>Ваше согласие, которое вы даете, отмечая галочку в форме. Согласие на рассылку – отдельное и необязательное.</p>
<h2>5. Где и сколько хранятся данные</h2><p>Заявки с казахстанскими номерами записываются в базу на сервере в Республике Казахстан. Остальные заявки записываются в базу на сервере в Российской Федерации. Резервные копии остаются на тех же серверах. Заявки хранятся 3 года с последнего контакта и затем удаляются автоматически, если вы не отозвали согласие раньше.</p>
<p>Оператор просматривает заявки, находясь в Республике Казахстан. Для данных из российской базы это трансграничная передача в Республику Казахстан, о которой оператор уведомил Роскомнадзор.</p>
<h2>6. Кому передаются данные</h2><p>Данные не продаются и не передаются третьим лицам для их целей. Их технически обрабатывают хостинг-провайдеры серверов в России и Казахстане. Уведомления о новых заявках приходят оператору в Telegram и на электронную почту через сервис Google Apps Script – в них только номер заявки, без ваших имени и контактов. Яндекс Метрика получает обезличенные данные о посещении, только если вы приняли cookie.</p>
<h2>7. Ваши права</h2><p>Вы можете узнать, какие данные о вас хранятся, уточнить их, потребовать удалить, отозвать согласие на обработку или на рассылку. Напишите на <span class="sel">anastasia.gavrish@gmail.com</span>, ответим и выполним запрос не позже чем за 10 рабочих дней. От рассылки можно отписаться по ссылке в любом письме. Посетители из ЕС также вправе подать жалобу в надзорный орган по защите данных своей страны.</p>
<h2>8. Как защищаются данные</h2><p>Сайт работает по HTTPS, базы заявок недоступны из интернета, админка закрыта паролем, доступ есть только у оператора.</p>
<h2>9. Cookie</h2><p>Без вашего согласия сайт ставит только технически необходимые cookie, например для запоминания вашего выбора в баннере. Яндекс Метрика загружается только после нажатия «Принять». Изменить выбор можно по ссылке «Настройки cookie» внизу любой страницы.</p>
<h2>10. Изменения политики</h2><p>Актуальная редакция всегда опубликована на этой странице. Дата редакции указана вверху.</p>"""
    consent = f"""<p>Отмечая галочку в форме на сайте a-gavrish.com, я даю согласие оператору на обработку моих персональных данных на следующих условиях.</p>
<h2>Оператор</h2>{OPERATORS}
<h2>Данные</h2><p>Имя, телефон или ник в Telegram, страна, текст сообщения, а также IP-адрес, дата и время отправки формы.</p>
<h2>Цели</h2><p>Обработка заявки, связь со мной для разбора переписок отдела продаж, подготовка и заключение договора.</p>
<h2>Действия с данными</h2><p>Сбор, запись, систематизация, накопление, хранение, уточнение, использование, удаление, а также трансграничная передача в Республику Казахстан для просмотра заявок оператором. Обработка автоматизированная.</p>
<h2>Срок</h2><p>3 года с последнего контакта или до отзыва согласия.</p>
<h2>Отзыв согласия</h2><p>Письмо на <span class="sel">anastasia.gavrish@gmail.com</span>. После отзыва данные удаляются в течение 10 рабочих дней.</p>"""
    ads = f"""<p>Отмечая галочку «Хочу получать полезные материалы и анонсы», я даю согласие оператору на получение информационных и рекламных сообщений.</p>
<h2>Оператор</h2>{OPERATORS}
<h2>Что будет приходить</h2><p>Полезные материалы о продажах, анонсы вебинаров, курсов и услуг Анастасии Гавриш.</p>
<h2>Каналы</h2><p>Telegram, WhatsApp, SMS или звонок по указанному контакту.</p>
<h2>Данные</h2><p>Имя и контакт, указанные в форме.</p>
<h2>Срок и отзыв</h2><p>До отзыва согласия. Отказаться можно в любой момент – ответьте «стоп» на любое сообщение или напишите на <span class="sel">anastasia.gavrish@gmail.com</span>. Согласие на рассылку не влияет на обработку заявки.</p>"""
    doc_page("privacy/", "Политика конфиденциальности", "Политика обработки персональных данных на сайте a-gavrish.com.", privacy)
    doc_page("soglasie/", "Согласие на обработку персональных данных", "Текст согласия на обработку персональных данных на сайте a-gavrish.com.", consent)
    doc_page("soglasie-reklama/", "Согласие на рекламные рассылки", "Текст согласия на получение информационных и рекламных сообщений.", ads)


def not_found():
    global _cur
    _cur = "404.html"
    body = f"""<section class="page-hero"><div class="wrap"><p class="eyebrow">Ошибка 404</p><h1>Такой страницы нет</h1><p class="lead">Возможно, она переехала, пока мы обновляли сайт.</p>
<div class="hero-cta"><a class="btn" href="{u('')}">На главную</a><a class="more" href="{u('cases/')}">Посмотреть кейсы</a></div></div></section>"""
    layout("404.html", "Страница не найдена", "Страница не найдена.", body, noindex=True)


# ---------------- assets ----------------

def build_assets():
    ad = os.path.join(OUT, "assets")
    os.makedirs(os.path.join(ad, "fonts"), exist_ok=True)
    os.makedirs(os.path.join(ad, "img"), exist_ok=True)
    F = os.environ.get("FONTSOURCE", os.path.join(ROOT, "node_modules/@fontsource/"))
    ranges = {"cyrillic": "U+0301,U+0400-045F,U+0490-0491,U+04B0-04B1,U+2116",
              "latin": "U+0000-00FF,U+0131,U+0152-0153,U+02BB-02BC,U+02C6,U+02DA,U+02DC,U+0304,U+0308,U+0329,U+2000-206F,U+20AC,U+2122,U+2191,U+2193,U+2212,U+2215,U+FEFF,U+FFFD,U+20B8"}
    css = []
    for fam, d, ws in [("Montserrat", "montserrat", [400, 500, 600, 700]), ("Unbounded", "unbounded", [500, 600])]:
        for w in ws:
            for sub, rng in ranges.items():
                fn = f"{d}-{sub}-{w}-normal.woff2"
                shutil.copy(os.path.join(ROOT, "src", "fonts", fn), os.path.join(ad, "fonts", fn))
                css.append(f'@font-face{{font-family:"{fam}";font-style:normal;font-weight:{w};font-display:swap;src:url(fonts/{fn}) format("woff2");unicode-range:{rng}}}')
    open(os.path.join(ad, "fonts.css"), "w").write("\n".join(css))
    shutil.copy(os.path.join(ROOT, "src", "site.css"), os.path.join(ad, "site.css"))
    shutil.copy(os.path.join(ROOT, "src", "site.js"), os.path.join(ad, "site.js"))
    shutil.copy(os.path.join(ROOT, "src", "hero.webp"), os.path.join(ad, "img", "hero.webp"))
    shutil.copy(os.path.join(ROOT, "src", "og.jpg"), os.path.join(ad, "og.jpg"))
    open(os.path.join(ad, "favicon.svg"), "w").write('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"><circle cx="32" cy="32" r="32" fill="#D6F479"/><text x="32" y="44" text-anchor="middle" font-family="Arial,sans-serif" font-weight="800" font-size="34" fill="#17152B">G</text></svg>')


def main():
    # Сборка идет во временную папку и подменяет готовый сайт только целиком и после проверки.
    # Если сборка упадет, на сервере останется предыдущая рабочая версия со всеми файлами.
    global OUT
    final = OUT
    OUT = final + ".new"
    if os.path.exists(OUT):
        shutil.rmtree(OUT)
    os.makedirs(OUT)
    build(final)


def build(final):
    build_assets()
    if not PREVIEW:
        shutil.copytree(os.path.join(ROOT, 'php'), OUT, dirs_exist_ok=True)
    home(); services_hub()
    for s in SERVICES:
        service_page(s)
    method_page(); cases_hub()
    for c in CASES:
        if c["full"]:
            case_page(c)
    about_page(); blog_page()
    for p in POSTS:
        post_page(p)
    docs(); not_found()
    if not PREVIEW:
        urls = "".join(f"<url><loc>{SITE}/{p}</loc></url>" for p in SITEMAP)
        open(os.path.join(OUT, "sitemap.xml"), "w").write(f'<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{urls}</urlset>')
        import datetime
        open(os.path.join(OUT, "build.txt"), "w").write(datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") + "\n")
        open(os.path.join(OUT, "robots.txt"), "w").write(f"User-agent: *\nDisallow: /admin\nDisallow: /api/\nSitemap: {SITE}/sitemap.xml\n")
        check(OUT)
    old = final + ".old"
    if os.path.exists(old):
        shutil.rmtree(old)
    if os.path.exists(final):
        os.rename(final, old)
    os.rename(OUT, final)
    if os.path.exists(old):
        shutil.rmtree(old)
    print("pages:", len(SITEMAP), "→", final)


def check(out):
    """Перед выкладкой: служебные файлы на месте, в карте сайта все страницы и нет закрытых разделов."""
    must = ["index.html", "404.html", "sitemap.xml", "robots.txt", "uslugi/skripty/index.html", "uslugi/treningi/index.html"]
    missing = [f for f in must if not os.path.isfile(os.path.join(out, f))]
    if missing:
        sys.exit("Сборка остановлена, нет файлов: " + ", ".join(missing))
    pages = sorted(os.path.relpath(os.path.join(d, "index.html"), out).replace("index.html", "").replace(os.sep, "/")
                   for d, _, fs in os.walk(out) if "index.html" in fs)
    pages = [p.replace("./", "") for p in pages]
    lost = [p for p in pages if p not in SITEMAP]
    if lost or not SITEMAP:
        sys.exit("Сборка остановлена, страниц нет в sitemap.xml: " + (", ".join(lost) or "карта пустая"))
    bad = [p for p in SITEMAP if p.startswith(("admin", "api", "_app", "assets"))]
    if bad:
        sys.exit("Сборка остановлена, в sitemap.xml попали служебные адреса: " + ", ".join(bad))


if __name__ == "__main__":
    main()
