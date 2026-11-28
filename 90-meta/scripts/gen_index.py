#!/usr/bin/env python3
"""Генерация index.md из frontmatter. Руками index.md не правится (G5/G6).

    python3 90-meta/scripts/gen_index.py          # показать diff, ничего не писать
    python3 90-meta/scripts/gen_index.py --write  # перезаписать index.md
    python3 90-meta/scripts/gen_index.py --check  # exit 1, если файл расходится

Правила: одна строка на страницу, «ссылка — имя», не длиннее LINE_MAX символов.
Никаких абзацев: подробности живут в самих заметках.
"""

import argparse
import os
import re
import sys

VAULT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
INDEX = os.path.join(VAULT, "index.md")
HUB = os.path.join(VAULT, "35-courses", "hub.md")
LINE_MAX = 120
NAME_MAX = 90

SKIP_DIRS = ("90-meta/templates", "90-meta/log", "60-travel/trips", "30-journal", "01-raw",
             "00-inbox", ".git", ".obsidian", ".trash", ".wiki-index")
SKIP_NAMES = ("README.md", "log.md", "hub.md", "status.md", "index.md", "AGENTS.md")

ZONES = [
    ("00-inbox", "приёмная: клиппер, быстрые заметки"),
    ("01-raw", "исходники (текст), неизменяемые"),
    ("05-chats", "дампы чатов с LLM (выжимка + сырой лог)"),
    ("10-wiki", "знания: concept/howto/tool/survey"),
    ("15-precedent", "прецедентные тексты: банк цитат, произведения"),
    ("20-people", "люди: карточки"),
    ("25-interactions", "взаимодействия"),
    ("30-journal", "ежедневные заметки"),
    ("35-courses", "курсы: карточка, конспекты модулей, инсайты"),
    ("40-projects", "проекты и доклады"),
    ("42-repos", "GitHub-репозитории: мейнтейнер/контрибьютор"),
    ("50-drafts", "статьи/посты/доклады (аккумуляторы)"),
    ("60-travel", "путешествия: поездки, точки интереса"),
    ("70-personal", "личный лайф-админ"),
    ("90-meta", "шаблоны, скрипты, модель данных"),
]

TYPE_TITLES = {
    "concept": "Концепции и разборы",
    "howto": "Инструкции",
    "tool": "Инструменты",
    "survey": "Обзоры",
    "comparison": "Сравнения",
    "case": "Кейсы",
    "talk": "Доклады и конспекты",
    "company": "Компании",
    "style-guide": "Стиль и редактура",
    "course": "Курсы",
    "course-module": "Конспекты модулей",
    "insight": "Инсайты",
}

# Зона курсов: порядок статусов курса в индексе и хабе.
COURSE_STATUS = {"active": 0, "paused": 1, "planned": 2, "done": 3, "dropped": 4}
INSIGHT_STATUS = {"to-apply": 0, "applied": 1, "promoted": 2, "dropped": 3}
AREA_ORDER = {"work": 0, "1c": 1, "personal": 2, "study": 3}


def frontmatter(text):
    if not text.startswith("---"):
        return None
    end = text.find("\n---", 3)
    if end < 0:
        return None
    fields = {}
    for line in text[3:end].splitlines():
        m = re.match(r"^([A-Za-z_][\w-]*)\s*:\s*(.*)$", line)
        if m:
            fields[m.group(1)] = m.group(2).strip().strip('"').strip("'")
    return fields


def first_line(text):
    """Первая содержательная строка тела: первый абзац после frontmatter."""
    body = text.split("\n---", 1)[-1]
    for line in body.splitlines():
        s = line.strip()
        if not s or s.startswith(("---", "```", "|", ">")):
            continue
        if s.startswith("#"):
            continue
        s = re.sub(r"\[\[([^\]|]+)\|?([^\]]*)\]\]", lambda m: m.group(2) or m.group(1), s)
        s = re.sub(r"[*_`]", "", s)
        return s
    return ""


def collect():
    pages = []
    for root, dirs, files in os.walk(VAULT):
        dirs[:] = [d for d in dirs if d not in (".git", ".obsidian", ".trash")]
        for name in sorted(files):
            if not name.endswith(".md") or name in SKIP_NAMES:
                continue
            abs_path = os.path.join(root, name)
            rel = os.path.relpath(abs_path, VAULT).replace(os.sep, "/")
            if any(rel.startswith(s) for s in SKIP_DIRS):
                continue
            with open(abs_path, encoding="utf-8", errors="replace") as fh:
                text = fh.read()
            fm = frontmatter(text) or {}
            pages.append({
                "rel": rel,
                "slug": rel[:-3],
                "stem": name[:-3],
                "name": fm.get("name") or first_line(text) or name[:-3],
                "type": fm.get("type", ""),
                "updated": fm.get("updated", ""),
                "region": fm.get("region", ""),
                "role": fm.get("role", ""),
                "status": fm.get("status", ""),
                "course": fm.get("course", ""),
                "part": fm.get("part", ""),
                "area": fm.get("area", ""),
                "date": fm.get("date", ""),
                "person": fm.get("person", "").strip("[]\"' "),
                "started": fm.get("started", ""),
                "promoted_to": fm.get("promoted_to", ""),
            })
    return pages


def fmt(entry, indent=0, suffix=""):
    """Строка каталога. `indent` — вложенность, `suffix` — хвост вроде статуса."""
    pad = " " * indent
    label = f"[[{entry['slug']}|{entry['stem']}]]"
    prefix = f"{pad}- {label} — "
    room = LINE_MAX - len(prefix) - len(suffix)
    if room < 20:
        return f"{pad}- {label}{suffix}"
    name = entry["name"].replace("|", "/").strip()
    if len(name) > room:
        name = name[:max(20, room - 1)].rstrip() + "…"
    return prefix + name + suffix


def fmt_folder(entry, indent=0):
    """Строка папки-входа: текстом ссылки служит `name`, путь остаётся в slug.

    У вложенных папок slug длинный (`40-projects/talks/<slug>/README`), и
    вариaнт «slug как текст + описание» не влезает в 120 символов (G6).
    """
    pad = " " * indent
    name = entry["name"].replace("|", "/").replace("]", ")").strip() or entry["stem"]
    suffix = f" · {entry['status']}" if entry.get("status") else ""
    room = LINE_MAX - len(pad) - 7 - len(entry["slug"]) - len(suffix)
    if room < 12:
        return f"{pad}- [[{entry['slug']}|{entry['stem']}]]{suffix}"
    if len(name) > room:
        name = name[:room - 1].rstrip() + "…"
    return f"{pad}- [[{entry['slug']}|{name}]]{suffix}"


def h1(text):
    """Первый заголовок H1: имя папки-входа, у которой нет frontmatter."""
    body = text.split("\n---", 1)[-1]
    for line in body.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return ""


def project_entries():
    """Папки `40-projects`: точка входа — README.md, а он в SKIP_NAMES.

    Поэтому проекты не попадают в `collect()` вообще, и без отдельного обхода
    раздел «Проекты» не может быть наполнен ничем: в папке проекта остаются
    только `status.md`/`log.md` (тоже SKIP_NAMES).
    """
    root = os.path.join(VAULT, "40-projects")
    if not os.path.isdir(root):
        return []
    out = []
    for cur, dirs, files in os.walk(root):
        dirs[:] = sorted(d for d in dirs if not d.startswith("."))
        if "README.md" not in files:
            continue
        rel = os.path.relpath(cur, VAULT).replace(os.sep, "/")
        with open(os.path.join(cur, "README.md"), encoding="utf-8", errors="replace") as fh:
            text = fh.read()
        fm = frontmatter(text) or {}
        out.append({
            "rel": rel,
            "slug": f"{rel}/README",
            "stem": os.path.basename(cur),
            "name": fm.get("name") or h1(text) or os.path.basename(cur),
            "status": fm.get("status", ""),
            "parent": os.path.dirname(rel),
        })
    return out


def course_slug(rel):
    """35-courses/<slug>/... -> <slug>; страница не в папке курса -> ''."""
    parts = rel.split("/")
    return parts[1] if len(parts) > 2 else ""


def course_lines(crs):
    """Секция курсов: по курсу — карточка, модули по номеру, инсайты внутри."""
    by_course = {}
    for p in crs:
        slug = course_slug(p["rel"])
        if slug:
            by_course.setdefault(slug, []).append(p)

    out = []
    order = sorted(by_course.items(),
                   key=lambda kv: (COURSE_STATUS.get(card_status(kv[1]), 9), kv[0]))
    for slug, items in order:
        card = next((p for p in items if p["type"] == "course"), None)
        mods = sorted((p for p in items if p["type"] == "course-module"),
                      key=lambda p: (p["part"], p["slug"]))
        ins = sorted((p for p in items if p["type"] == "insight"),
                     key=lambda p: (INSIGHT_STATUS.get(p["status"], 9),
                                    AREA_ORDER.get(p["area"], 9), p["slug"]))
        open_ins = sum(1 for p in ins if p["status"] == "to-apply")
        head = f"### {slug}"
        meta = []
        st = card_status(items)
        if st:
            meta.append(st)
        meta.append(f"модулей {len(mods)}")
        if ins:
            meta.append(f"инсайтов {len(ins)}, к применению {open_ins}")
        if meta:
            head += f" — {', '.join(meta)}"
        out += [head, ""]
        if card:
            name = card["name"].replace("|", "/").strip()
            out.append(f"- [[{card['slug']}|карточка курса]] — {name}")
        out += [fmt(p) for p in mods]
        out += [fmt(p, suffix=f" ({p['area'] or 'область не указана'}: {p['status']})") for p in ins]
        out.append("")

    pending = [p for p in crs if p["type"] == "insight" and p["status"] == "to-apply"]
    if pending:
        out += ["### Инсайты к применению", ""]
        for p in sorted(pending, key=lambda p: (AREA_ORDER.get(p["area"], 9), p["slug"])):
            out.append(f"{fmt(p)} — {p['area'] or 'область не указана'}")
        out.append("")
    return out


def card_status(items):
    card = next((p for p in items if p["type"] == "course"), None)
    return card["status"] if card else ""


def build_hub(pages):
    """35-courses/hub.md: таблица курсов и очередь инсайтов. Генерируется."""
    crs = [p for p in pages if p["rel"].startswith("35-courses/")]
    by_course = {}
    for p in crs:
        slug = course_slug(p["rel"])
        if slug:
            by_course.setdefault(slug, []).append(p)

    out = ["# Курсы — хаб", "",
           "**Файл генерируется** `90-meta/scripts/gen_index.py` (`make index`). "
           "Руками не править. Контракт зоны — [[35-courses/README]].", ""]

    if not by_course:
        out += ["Курсов пока нет. Заведи карточку по шаблону `90-meta/templates/course.md`.", ""]
        return "\n".join(out)

    out += ["## Курсы", "",
            "| Курс | Статус | Модулей | Инсайтов | К применению | Начат |",
            "|---|---|---|---|---|---|"]
    order = sorted(by_course.items(),
                   key=lambda kv: (COURSE_STATUS.get(card_status(kv[1]), 9), kv[0]))
    for slug, items in order:
        card = next((p for p in items if p["type"] == "course"), None)
        mods = [p for p in items if p["type"] == "course-module"]
        ins = [p for p in items if p["type"] == "insight"]
        pending = sum(1 for p in ins if p["status"] == "to-apply")
        name = f"[[35-courses/{slug}/course|{slug}]]" if card else slug
        started = card["started"] if card else ""
        out.append(f"| {name} | {card_status(items) or '—'} | {len(mods)} | {len(ins)} | "
                   f"{pending} | {started or '—'} |")
    out.append("")

    pending = [p for p in crs if p["type"] == "insight" and p["status"] == "to-apply"]
    out += ["## Инсайты к применению", ""]
    if pending:
        out += ["| Инсайт | Область | Курс | Создан |", "|---|---|---|---|"]
        for p in sorted(pending, key=lambda p: (AREA_ORDER.get(p["area"], 9), p["slug"])):
            rel = p["rel"]
            course = course_slug(rel)
            out.append(f"| [[{p['slug']}|{p['stem']}]] | {p['area'] or '—'} | "
                       f"[[35-courses/{course}/course|{course}]] | {p['updated'] or '—'} |")
    else:
        out.append("Очередь пуста.")
    out += ["", "## Что дальше", "",
            "Порядок: очередь `to-apply` → применить и закрыть (`applied`) → созрело до "
            "переиспользуемого → промоушен в `10-wiki` (`promoted`). Модули без инсайтов — "
            "кандидаты на перечитывание.", ""]
    return "\n".join(out)


def render_projects(pages):
    """Раздел проектов: папка проекта — строка, её страницы — вложенным списком."""
    entries = project_entries()
    proj_pages = [p for p in pages if p["rel"].startswith("40-projects/")]
    if not entries and not proj_pages:
        return []

    by_parent = {}
    for e in entries:
        by_parent.setdefault(e["parent"], []).append(e)

    def docs_of(entry):
        """Страницы папки, не относящиеся к вложенным проектам."""
        kids = {c["rel"] + "/" for c in by_parent.get(entry["rel"], [])}
        out = []
        for p in proj_pages:
            if not p["rel"].startswith(entry["rel"] + "/"):
                continue
            if any(p["rel"].startswith(k) for k in kids):
                continue
            out.append(p)
        return sorted(out, key=lambda p: p["rel"])

    out = []
    seen = set()

    def walk(parent, indent):
        for e in sorted(by_parent.get(parent, []), key=lambda x: x["stem"]):
            out.append(fmt_folder(e, indent))
            seen.add(e["rel"] + "/")
            for p in docs_of(e):
                out.append(fmt(p, indent + 2))
            walk(e["rel"], indent + 2)

    walk("40-projects", 0)

    # Папки без README (например, проект со `spec.md` и `status.md`): в обходе
    # точек входа их нет, но страницы обязаны попасть в каталог.
    rest = [p for p in proj_pages if not any(p["rel"].startswith(s) for s in seen)]
    if rest:
        groups = {}
        for p in rest:
            groups.setdefault(os.path.dirname(p["rel"]), []).append(p)
        for d in sorted(groups):
            out += ["", f"### {d.split('/', 1)[-1]} (без README)", ""]
            out += [fmt(p) for p in sorted(groups[d], key=lambda p: p["stem"])]
            out.append("")

    head = f"## 40-projects — проекты и доклады ({len(entries)})"
    return ["", head, "",
            "Точка входа проекта — его `README.md`, статус — `status.md`.", ""] + out


def build(pages):
    by_zone = {}
    for p in pages:
        by_zone.setdefault(p["rel"].split("/")[0], []).append(p)

    out = ["# Index", "",
           "Каталог vault. **Файл генерируется** `90-meta/scripts/gen_index.py` "
           "(`make index`).", "",
           "Руками не править: правка будет перезаписана, описания берутся "
           "из `name` заметок.", "",
           "Журнал операций — [[log]].", "",
           "## Зоны", ""]
    raw_counts = {}
    for zone, _ in ZONES:
        base = os.path.join(VAULT, zone)
        n = 0
        for root, dirs, files in os.walk(base):
            dirs[:] = [d for d in dirs if d not in (".git", ".obsidian", ".trash")]
            n += sum(1 for f in files if f.endswith(".md") and f not in SKIP_NAMES)
        raw_counts[zone] = n
    for zone, desc in ZONES:
        n = raw_counts.get(zone, 0)
        mark = "" if n else " _(пусто)_"
        out.append(f"- `{zone}` — {desc}{mark}")

    acc = [p for p in by_zone.get("50-drafts", []) if p["rel"].endswith("ideas.md")]
    if acc:
        out += ["", "## Аккумуляторы идей", ""]
        for p in sorted(acc, key=lambda p: p["slug"]):
            slug = p["rel"].split("/")[1]
            name = p["name"].replace("|", "/").strip()
            room = LINE_MAX - len(f"- [[50-drafts/{slug}/ideas|{slug}]] — ")
            if len(name) > room:
                name = name[:max(20, room - 1)].rstrip() + "…"
            out.append(f"- [[50-drafts/{slug}/ideas|{slug}]] — {name}")

    wiki = by_zone.get("10-wiki", [])
    if wiki:
        out += ["", "## 10-wiki — знания", ""]
        groups = {}
        for p in wiki:
            groups.setdefault(p["type"] or "без типа", []).append(p)
        for t, items in sorted(groups.items(), key=lambda kv: (-len(kv[1]), kv[0])):
            out += [f"### {TYPE_TITLES.get(t, t)} ({len(items)})", ""]
            out += [fmt(p) for p in sorted(items, key=lambda p: p["stem"])]
            out.append("")

    crs = by_zone.get("35-courses", [])
    if crs:
        out += ["", "## 35-courses — курсы", "",
                "Хаб: [[35-courses/hub]]. Контракт: [[35-courses/README]].", ""]
        out += course_lines(crs)

    prec_works = by_zone.get("15-precedent", [])
    works = [p for p in prec_works if p["rel"].startswith("15-precedent/works/")]
    bank = [p for p in prec_works if p["rel"].startswith("15-precedent/bank/")]
    if prec_works:
        out += ["", "## 15-precedent — банк цитат", "",
                "Хаб с выборками: [[15-precedent/hub]]. Контракт: [[15-precedent/README]]. "
                "Словарь тем: [[15-precedent/themes]].", ""]
        if works:
            out += [f"### Произведения ({len(works)})", ""] + [fmt(p) for p in sorted(works, key=lambda p: p["stem"])] + [""]
        if bank:
            out += [f"### Цитаты ({len(bank)})", ""] + [fmt(p) for p in sorted(bank, key=lambda p: p["stem"])] + [""]

    repos = by_zone.get("42-repos", [])
    if repos:
        out += ["", "## 42-repos — репозитории", ""]
        order = {"maintainer": 0, "contributor": 1, "fork": 2, "watcher": 3, "archived": 4}
        for p in sorted(repos, key=lambda p: (order.get(p["role"], 9), p["stem"])):
            out.append(fmt(p))

    out += render_projects(pages)

    people = by_zone.get("20-people", [])
    if people:
        out += ["", f"## Люди ({len(people)})", ""]
        out += [f"- [[{p['slug']}]]" for p in sorted(people, key=lambda p: p["stem"])]

    inter = by_zone.get("25-interactions", [])
    if inter:
        out += ["", f"## 25-interactions — взаимодействия ({len(inter)})", "",
                "Зона append-only. Собирается по полю `person:` в карточках людей.", ""]
        for p in sorted(inter, key=lambda p: (p["date"], p["stem"]), reverse=True):
            # Текст ссылки — дата и человек: имя файла целиком не влезает в 120.
            label = f"{p['date']} {p['person']}".strip() or p["stem"]
            line = f"- [[{p['slug']}|{label}]]"
            if len(line) > LINE_MAX:
                # Обрезка `]]` ломает ссылку — тогда жертвуем подписью, не путём.
                line = f"- [[{p['slug']}]]"
            out.append(line)

    poi = [p for p in by_zone.get("60-travel", []) if p["rel"].startswith("60-travel/poi/")]
    if poi:
        regions = {}
        for p in poi:
            regions.setdefault(p["region"] or "регион не указан", []).append(p)
        out += ["", f"## Точки интереса ({len(poi)})", ""]
        out.append("Карта: [[60-travel/poi-map]].")
        out.append("")
        for region, items in sorted(regions.items(), key=lambda kv: (-len(kv[1]), kv[0])):
            out += [f"### {region} ({len(items)})", ""]
            out += [f"- [[{p['slug']}|{p['stem']}]]" for p in sorted(items, key=lambda p: p["stem"])]
            out.append("")

    personal = by_zone.get("70-personal", [])
    if personal:
        out += ["", f"## 70-personal — личный лайф-админ ({len(personal)})", ""]
        groups = {}
        for p in personal:
            parts = os.path.dirname(p["rel"]).split("/", 1)
            groups.setdefault(parts[1] if len(parts) > 1 else "", []).append(p)
        for key in sorted(groups):
            items = groups[key]
            if key:
                out += [f"### {key} ({len(items)})", ""]
            out += [fmt(p) for p in sorted(items, key=lambda p: p["stem"])]
            out.append("")

    drafts = [p for p in by_zone.get("50-drafts", []) if not p["rel"].endswith("ideas.md")]
    if drafts:
        out += ["", "## 50-drafts — черновики", ""]
        out += [fmt(p) for p in sorted(drafts, key=lambda p: p["slug"])]

    chats = by_zone.get("05-chats", [])
    if chats:
        # Каталог показывает только последние 30 дампов: 188 строк утопили бы индекс,
        # полный список читается поиском (`wiki_search.py` + корпус `chats`).
        limit = 30
        head = f"## 05-chats — дампы чатов ({len(chats)}"
        head += f", показаны {limit} последних)" if len(chats) > limit else ")"
        out += ["", head, ""]
        for p in sorted(chats, key=lambda p: p["stem"], reverse=True)[:limit]:
            line = f"- [[{p['slug']}]] — {p['name']}"
            if len(line) > LINE_MAX:
                line = f"- [[{p['slug']}]]"
            out.append(line)

    recent = [p for p in pages if p["updated"]]
    if recent:
        out += ["", "## Последние изменения", ""]
        # Тай-брейк по slug: при равных датах порядок обхода ФС разный на
        # Windows и Linux, и index.md начинает «дрожать» между машинами.
        for p in sorted(recent, key=lambda p: (p["updated"], p["slug"]), reverse=True)[:20]:
            out.append(f"- {p['updated']} [[{p['slug']}|{p['stem']}]]")

    while out and out[-1] == "":
        out.pop()
    return "\n".join(clip(l) for l in out) + "\n"


def clip(line, limit=LINE_MAX):
    """Гарантия G6: строка каталога ≤ `limit` символов.

    Режется только хвост-описание после последнего `]] — `, чтобы не испортить
    wikilink: текст ссылки может само содержать тире.
    """
    if len(line) <= limit:
        return line
    idx = line.rfind("]] — ")
    if idx < 0:
        return line
    head, tail = line[:idx + 2], line[idx + 5:]
    room = limit - len(head) - 3
    if room < 12:
        return head
    return f"{head} — {tail[:room].rstrip()}…"[:limit]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--diff", action="store_true")
    args = ap.parse_args()

    pages = collect()
    new = build(pages)
    new_hub = build_hub(pages)
    old = open(INDEX, encoding="utf-8").read() if os.path.exists(INDEX) else ""
    old_hub = open(HUB, encoding="utf-8").read() if os.path.exists(HUB) else ""

    if args.check:
        bad = False
        if new != old:
            print(f"index.md расходится с frontmatter ({len(old)} -> {len(new)} байт). "
                  f"Запусти gen_index.py --write")
            bad = True
        long = [(i + 1, len(l)) for i, l in enumerate(new.splitlines()) if len(l) > LINE_MAX]
        if long:
            print(f"строк длиннее {LINE_MAX} символов (G6): {len(long)}; первая — "
                  f"строка {long[0][0]}, {long[0][1]} символов")
            bad = True
        if os.path.isdir(os.path.join(VAULT, "35-courses")) and new_hub != old_hub:
            print(f"35-courses/hub.md расходится с frontmatter "
                  f"({len(old_hub)} -> {len(new_hub)} байт). Запусти gen_index.py --write")
            bad = True
        if not bad:
            print("index.md в порядке")
        return 1 if bad else 0
    if args.write:
        with open(INDEX, "w", encoding="utf-8") as fh:
            fh.write(new)
        msg = f"index.md перезаписан: {len(old)} -> {len(new)} байт"
        if os.path.isdir(os.path.dirname(HUB)):
            with open(HUB, "w", encoding="utf-8") as fh:
                fh.write(new_hub)
            msg += f"; hub.md: {len(old_hub)} -> {len(new_hub)} байт"
        print(msg)
        return 0
    import difflib
    sys.stdout.writelines(difflib.unified_diff(
        old.splitlines(True), new.splitlines(True), "index.md (сейчас)", "index.md (новый)"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
