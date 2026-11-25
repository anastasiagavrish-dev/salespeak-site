"""Статьи блога: чтение posts/*.md и разметка текста статьи в html.

Формат файла статьи – шапка «ключ: значение», строка ---, текст.
В тексте:
  ## Шаг 1. Заголовок        – заголовок шага (номер выводится отдельной меткой)
  ## Заголовок               – обычный заголовок раздела
  абзацы, списки «1.» и «-», **жирный**, [текст](ссылка)
  > фраза                    – выделенная цитата
  [[toc]]                    – содержание статьи по заголовкам
  ::: story Подпись ... :::  – врезка-история из практики
  ::: note Подпись ... :::   – врезка-пояснение
  ::: key ... :::            – главный вывод крупно
  ::: cards ... :::          – список «1. **Название.** текст» карточками
  ::: tiles ... :::          – цифры «- **цифра** пояснение» плитками
  ::: tools ... :::          – инструменты «- **[Название](ссылка)** – текст» карточками
  ::: cta Заголовок ... :::  – фиолетовый блок с кнопкой на форму
  ?? Вопрос + строки ответа  – частые вопросы (в конце файла)
"""
import html, os, re

E = html.escape
SITE = "https://a-gavrish.com"
MONTHS = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа", "сентября", "октября", "ноября", "декабря"]
TRANSLIT = dict(zip("абвгдеёжзийклмнопрстуфхцчшщъыьэюя", ["a", "b", "v", "g", "d", "e", "e", "zh", "z", "i", "y", "k", "l", "m", "n", "o", "p", "r", "s", "t", "u", "f", "h", "c", "ch", "sh", "sch", "", "y", "", "e", "yu", "ya"]))


def ru_date(d):
    y, m, dd = d.split("-")
    return f"{int(dd)} {MONTHS[int(m) - 1]} {y}"


def slugify(t):
    t = "".join(TRANSLIT.get(c, c) for c in t.lower())
    return re.sub(r"[^a-z0-9]+", "-", t).strip("-")[:60]


def load_posts(root):
    posts = []
    d = os.path.join(root, "posts")
    for fn in sorted(os.listdir(d)) if os.path.isdir(d) else []:
        if not fn.endswith(".md"):
            continue
        raw = open(os.path.join(d, fn), encoding="utf-8").read()
        head, _, body = raw.partition("\n---\n")
        meta = dict(l.split(": ", 1) for l in head.splitlines() if ": " in l)
        faq, text = [], []
        lines = body.strip().splitlines()
        i = 0
        while i < len(lines):
            if lines[i].startswith("?? "):
                q, i, ans = lines[i][3:].strip(), i + 1, []
                while i < len(lines) and lines[i].strip() and not lines[i].startswith("?? "):
                    ans.append(lines[i].strip())
                    i += 1
                faq.append((q, " ".join(ans)))
            else:
                text.append(lines[i])
                i += 1
        meta["services"] = dict(x.strip().split("=", 1) for x in meta.get("services", "").split(";") if "=" in x)
        meta["body"], meta["faq"] = "\n".join(text), faq
        words = len(re.findall(r"\w+", meta["body"]))
        meta["minutes"] = max(1, round(words / 180))
        posts.append(meta)
    return sorted(posts, key=lambda p: p["date"], reverse=True)


class Render:
    """Текст статьи → html. u – функция генератора сайта для внутренних ссылок."""

    def __init__(self, u):
        self.u = u
        self.toc = []

    def inline(self, t):
        t = E(t, quote=False)

        def link(m):
            href = m.group(2)
            if href.startswith(SITE):
                href = self.u(href[len(SITE) + 1:])
            return f'<a href="{href}">{m.group(1)}</a>'
        t = re.sub(r"\[([^\]]+)\]\(([^)\s]+)\)", link, t)
        return re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", t)

    def heading(self, t):
        m = re.match(r"Шаг (\d+)\.\s*(.*)", t)
        if m:
            hid = "shag-" + m.group(1)
            self.toc.append((hid, m.group(2)))
            return f'<h2 id="{hid}" class="p-step"><span class="p-num">Шаг {m.group(1)}</span> {self.inline(m.group(2))}</h2>'
        hid = slugify(t)
        self.toc.append((hid, t))
        return f'<h2 id="{hid}">{self.inline(t)}</h2>'

    def items(self, lines):
        """Строки списка → пункты (продолжение пункта без маркера приклеивается к нему)."""
        out = []
        for l in lines:
            m = re.match(r"^(?:\d+\.|-)\s+(.*)", l)
            if m:
                out.append(m.group(1))
            elif l.strip() and out:
                out[-1] += " " + l.strip()
        return out

    def lead_split(self, item):
        """«**Название.** текст» → (Название, текст); ссылка в названии сохраняется."""
        m = re.match(r"^\*\*(.+?)\*\*\s*[–-]?\s*(.*)", item)
        if not m:
            return "", item
        rest = m.group(2)
        return m.group(1).rstrip("."), rest[:1].upper() + rest[1:]

    def block(self, kind, label, lines):
        if kind == "cards":
            cards = []
            for n, it in enumerate(self.items(lines), 1):
                t, rest = self.lead_split(it)
                cards.append(f'<li><span class="p-card-n">{n:02d}</span><div><h3>{self.inline(t)}</h3><p>{self.inline(rest)}</p></div></li>')
            return f'<ol class="p-cards">{"".join(cards)}</ol>'
        if kind == "tiles":
            tiles = []
            for it in self.items(lines):
                t, rest = self.lead_split(it)
                tiles.append(f"<li><b>{self.inline(t)}</b><span>{self.inline(rest)}</span></li>")
            return f'<ul class="p-tiles">{"".join(tiles)}</ul>'
        if kind == "tools":
            tools = []
            for it in self.items(lines):
                t, rest = self.lead_split(it)
                tools.append(f'<li><h3>{self.inline(t)}</h3><p>{self.inline(rest)}</p></li>')
            return f'<ul class="p-tools">{"".join(tools)}</ul>'
        inner = self.render(lines)
        if kind == "story":
            return f'<aside class="p-story"><p class="p-label">{E(label)}</p>{inner}</aside>'
        if kind == "note":
            return f'<aside class="p-note"><p class="p-label">{E(label)}</p>{inner}</aside>'
        if kind == "key":
            return f'<div class="p-key">{inner}</div>'
        if kind == "cta":
            hid = slugify(label)
            self.toc.append((hid, label))
            return f'<section class="p-cta"><h2 id="{hid}">{E(label)}</h2>{inner}<a class="btn" href="#offer">Хочу разбор переписок</a></section>'
        return inner

    def render(self, lines):
        out, buf, lst = [], [], None

        def flush():
            nonlocal buf, lst
            if buf:
                out.append("<p>" + self.inline(" ".join(buf)) + "</p>")
                buf = []
            if lst:
                tag, its = lst
                out.append(f"<{tag}>" + "".join(f"<li>{self.inline(i)}</li>" for i in its) + f"</{tag}>")
                lst = None
        i = 0
        while i < len(lines):
            line = lines[i].rstrip()
            m_blk = re.match(r"^:::\s*(\w+)\s*(.*)$", line)
            mo, mu = re.match(r"^\d+\.\s+(.*)", line), re.match(r"^-\s+(.*)", line)
            if m_blk:
                flush()
                kind, label, inner = m_blk.group(1), m_blk.group(2).strip(), []
                i += 1
                while i < len(lines) and lines[i].strip() != ":::":
                    inner.append(lines[i])
                    i += 1
                out.append(self.block(kind, label, inner))
            elif not line:
                flush()
            elif line == "[[toc]]":
                flush()
                out.append("<!--TOC-->")
            elif line.startswith("## "):
                flush()
                out.append(self.heading(line[3:]))
            elif line.startswith("> "):
                flush()
                out.append(f'<blockquote class="p-quote"><p>{self.inline(line[2:])}</p></blockquote>')
            elif mo or mu:
                tag = "ol" if mo else "ul"
                if buf or (lst and lst[0] != tag):
                    flush()
                lst = lst or (tag, [])
                lst[1].append((mo or mu).group(1))
            else:
                if lst:
                    flush()
                buf.append(line)
            i += 1
        flush()
        return "\n".join(out)


def toc_html(toc, cls):
    items = "".join(f'<li><a href="#{i}">{E(t)}</a></li>' for i, t in toc)
    return f'<nav class="{cls}" aria-label="Содержание"><p class="p-label">Содержание</p><ol>{items}</ol></nav>'


def render_post(body, u):
    """Текст статьи → (html, содержание для боковой колонки). Содержание в тексте видно только на узких экранах."""
    r = Render(u)
    h = r.render(body.splitlines())
    return h.replace("<!--TOC-->", toc_html(r.toc, "p-toc")), toc_html(r.toc, "p-toc-side")


if __name__ == "__main__":
    import sys
    root = sys.argv[1] if len(sys.argv) > 1 else os.path.dirname(os.path.abspath(__file__))
    for p in load_posts(root):
        h, toc = render_post(p["body"], lambda x: "/" + x)
        print(p["slug"], p["minutes"], "мин;", toc.count("<li>"), "разделов;", h.count("<aside"), "врезок;", len(p["faq"]), "вопросов")
        if len(sys.argv) > 2:
            open(sys.argv[2], "w").write(h)
