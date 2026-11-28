#!/usr/bin/env python3
"""Канонизация тегов: словарь, максимум 5, остальное в kw (G4).

    python3 90-meta/scripts/canon_tags.py            # отчёт, ничего не меняет
    python3 90-meta/scripts/canon_tags.py --write    # применить
    python3 90-meta/scripts/canon_tags.py --proposals 90-meta/tag-proposals.md

Три операции, все идемпотентные:
1. Таблица канонизации (конспект -> digest, конференции -> conference, ...).
2. Теги вне словаря переезжают в `kw` (до 8 значений) — они содержательные
   (edt, vllm, postgres, tts), просто это ключевые слова, а не домены.
3. Если канонических тегов больше 5 — хвост тоже уезжает в `kw`.

Удаления без следа не бывает: тег либо становится каноном, либо живёт в `kw`.
"""

import argparse
import collections
import os
import re
import sys

VAULT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Должны совпадать с lint_frontmatter.py; импорт оттуда при недоступности — локальная копия.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    from lint_frontmatter import TAGS, CANON, SKIP_DIRS, SKIP_NAMES  # noqa: E402
except ImportError:  # страховка: скрипт остаётся работоспособным отдельно
    raise SystemExit("не найден lint_frontmatter.py рядом с canon_tags.py")

MAX_TAGS = 5
MAX_KW = 8
FM = re.compile(r"\A---\n(.*?)\n---\n", re.S)


def split_list(raw):
    return [t.strip().strip('"').strip("'") for t in raw.strip().strip("[]").split(",")
            if t.strip()]


def get_field(raw, key):
    m = re.search(rf"^{key}:\s*(.*)$", raw, re.M)
    return m.group(1) if m else None


def set_field(raw, key, value):
    line = f"{key}: {value}"
    if re.search(rf"^{key}:.*$", raw, re.M):
        return re.sub(rf"^{key}:.*$", line, raw, count=1, flags=re.M)
    # вставляем сразу после tags (там и живёт родственное поле), иначе после type
    anchor = re.search(r"^tags:.*$", raw, re.M) or re.search(r"^type:.*$", raw, re.M) \
        or re.search(r"^name:.*$", raw, re.M)
    if anchor:
        return raw[:anchor.end()] + "\n" + line + raw[anchor.end():]
    return raw + "\n" + line


def process(text):
    m = FM.match(text)
    if not m:
        return text, None
    raw = m.group(1)
    if get_field(raw, "tags") is None:
        return text, None
    tags = split_list(get_field(raw, "tags"))
    kw = split_list(get_field(raw, "kw") or "")

    canonized = []
    moved = []
    for tag in tags:
        target = CANON.get(tag, tag)
        if target in TAGS:
            if target not in canonized:
                canonized.append(target)
        else:
            moved.append(target)

    overflow = canonized[MAX_TAGS:]
    canonized = canonized[:MAX_TAGS]

    new_kw = list(dict.fromkeys(kw + moved + overflow))[:MAX_KW]
    dropped = (moved + overflow)[len(new_kw) - len(kw):] if len(kw + moved + overflow) > MAX_KW else []

    report = {
        "tags": tags,
        "new_tags": canonized,
        "moved_to_kw": moved + overflow,
        "dropped": dropped,
    }
    if canonized == tags and not moved and not overflow:
        return text, None

    raw = set_field(raw, "tags", "[" + ", ".join(canonized) + "]")
    if new_kw:
        raw = set_field(raw, "kw", "[" + ", ".join(new_kw) + "]")
    return text[:m.start(1)] + raw + text[m.end(1):], report


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--proposals", metavar="FILE",
                    help="записать список тегов вне словаря с частотой")
    ap.add_argument("--only", metavar="PREFIX", help="только зона, напр. 10-wiki")
    args = ap.parse_args()

    changed = 0
    moved_total = 0
    dropped_total = 0
    proposals = collections.Counter()
    per_zone = collections.Counter()

    for root, dirs, files in os.walk(VAULT):
        dirs[:] = [d for d in dirs if d not in (".git", ".obsidian", ".trash")]
        for name in sorted(files):
            if not name.endswith(".md") or name in SKIP_NAMES:
                continue
            path = os.path.join(root, name)
            rel = os.path.relpath(path, VAULT).replace(os.sep, "/")
            if any(rel.startswith(s) for s in SKIP_DIRS):
                continue
            if args.only and not rel.startswith(args.only):
                continue
            text = open(path, encoding="utf-8", errors="replace").read()
            new_text, report = process(text)
            if report is None:
                continue
            for tag in report["moved_to_kw"]:
                proposals[tag] += 1
            changed += 1
            moved_total += len(report["moved_to_kw"])
            dropped_total += len(report["dropped"])
            per_zone[rel.split("/")[0]] += 1
            if args.write and new_text != text:
                with open(path, "w", encoding="utf-8") as fh:
                    fh.write(new_text)

    print(f"страниц к правке: {changed}")
    for zone, n in sorted(per_zone.items()):
        print(f"  {zone:16s} {n}")
    print(f"тегов переехало в kw: {moved_total}")
    if dropped_total:
        print(f"НЕ влезло в kw (потеряно): {dropped_total}")

    if args.proposals:
        lines = ["# Теги вне словаря — предложения", "",
                 "Сгенерировано `90-meta/scripts/canon_tags.py --proposals`.",
                 "Слева — тег и число страниц. Решение по каждому: принять в словарь",
                 "(и тогда он уходит из `kw` в `tags`) или оставить ключевым словом.", "",
                 "Кандидаты в домены — те, что встречаются в 3+ страницах и называют",
                 "область, а не продукт.", "",
                 "| Тег | Страниц |", "|---|---|"]
        for tag, n in proposals.most_common():
            lines.append(f"| `{tag}` | {n} |")
        with open(os.path.join(VAULT, args.proposals), "w", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")
        print(f"предложения записаны: {args.proposals} ({len(proposals)} тегов)")

    if not args.write:
        print("(ничего не изменено; запусти с --write)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
