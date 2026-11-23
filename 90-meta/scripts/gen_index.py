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
LINE_MAX = 120
NAME_MAX = 90

SKIP_DIRS = ("90-meta/templates", "60-travel/trips", "30-journal", "01-raw",
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
}


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
    """Первая содержательная строка тела: H1, иначе первый абзац."""
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
            })
    return pages


def fmt(entry):
    name = entry["name"].replace("|", "/").strip()
    prefix = f"- [[{entry['slug']}|{entry['stem']}]] — "
    room = LINE_MAX - len(prefix)
    if room < 20:
        return prefix.rstrip(" —")
    if len(name) > room:
        name = name[:max(20, room - 1)].rstrip() + "…"
    return prefix + name


def build(pages):
    by_zone = {}
    for p in pages:
        by_zone.setdefault(p["rel"].split("/")[0], []).append(p)

    out = ["# Index", "",
           "Каталог vault. **Файл генерируется** `90-meta/scripts/gen_index.py` "
           "(`make index`). Руками не править: правка будет перезаписана, "
           "описания берутся из `name` заметок.", "",
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

    proj = [p for p in by_zone.get("40-projects", []) if p["rel"].count("/") == 1]
    if proj:
        out += ["", "## Проекты и доклады", ""]
        out += [fmt(p) for p in sorted(proj, key=lambda p: p["stem"])]

    people = by_zone.get("20-people", [])
    if people:
        out += ["", f"## Люди ({len(people)})", ""]
        out += [f"- [[{p['slug']}]]" for p in sorted(people, key=lambda p: p["stem"])]

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

    drafts = [p for p in by_zone.get("50-drafts", []) if not p["rel"].endswith("ideas.md")]
    if drafts:
        out += ["", "## 50-drafts — черновики", ""]
        out += [fmt(p) for p in sorted(drafts, key=lambda p: p["slug"])]

    chats = by_zone.get("05-chats", [])
    if chats:
        out += ["", f"## 05-chats — дампы чатов ({len(chats)})", ""]
        out += [f"- [[{p['slug']}]] — {p['name']}" for p in sorted(chats, key=lambda p: p["stem"], reverse=True)[:30]]

    recent = [p for p in pages if p["updated"]]
    if recent:
        out += ["", "## Последние изменения", ""]
        # Тай-брейк по slug: при равных датах порядок обхода ФС разный на
        # Windows и Linux, и index.md начинает «дрожать» между машинами.
        for p in sorted(recent, key=lambda p: (p["updated"], p["slug"]), reverse=True)[:20]:
            out.append(f"- {p['updated']} [[{p['slug']}|{p['stem']}]]")

    while out and out[-1] == "":
        out.pop()
    return "\n".join(out) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--diff", action="store_true")
    args = ap.parse_args()

    new = build(collect())
    old = open(INDEX, encoding="utf-8").read() if os.path.exists(INDEX) else ""

    if args.check:
        if new != old:
            print(f"index.md расходится с frontmatter ({len(old)} -> {len(new)} байт). "
                  f"Запусти gen_index.py --write")
            return 1
        print("index.md в порядке")
        return 0
    if args.write:
        with open(INDEX, "w", encoding="utf-8") as fh:
            fh.write(new)
        print(f"index.md перезаписан: {len(old)} -> {len(new)} байт")
        return 0
    import difflib
    sys.stdout.writelines(difflib.unified_diff(
        old.splitlines(True), new.splitlines(True), "index.md (сейчас)", "index.md (новый)"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
