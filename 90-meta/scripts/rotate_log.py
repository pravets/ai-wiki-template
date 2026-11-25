#!/usr/bin/env python3
"""Порядок и ротация log.md (G7). Журнал append-only, но хронологически.

    python3 90-meta/scripts/rotate_log.py            # отчёт: что не так, что уедет
    python3 90-meta/scripts/rotate_log.py --write    # отсортировать и разложить

Правило: активный log.md держит хвост записей не тяжелее MAX_BYTES (и не длиннее
MAX_ENTRIES) в порядке возрастания даты; всё старше уезжает в 90-meta/log/<год>.md
(тоже по датам). Содержимое записей не меняется — только порядок блоков и место
хранения.
"""

import argparse
import os
import re
import sys

VAULT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
LOG = os.path.join(VAULT, "log.md")
ARCHIVE_DIR = os.path.join(VAULT, "90-meta", "log")
MAX_ENTRIES = 300
MAX_BYTES = 100 * 1024  # порог навигации: ориентация читает log.md каждую сессию

ARCHIVE_POINTER = "Архив старых записей — `90-meta/log/` (по годам, ротация: `make log`)."

ENTRY = re.compile(r"^## \[(\d{4}-\d{2}-\d{2})\](.*)$", re.M)

ARCHIVE_HEADER = """# Журнал операций — {year}

Архив `log.md`: записи за {year}. Активный журнал — [[log]]. Порядок — по дате.

"""


def parse(path):
    text = open(path, encoding="utf-8").read() if os.path.exists(path) else ""
    matches = list(ENTRY.finditer(text))
    header = text[:matches[0].start()].rstrip() + "\n" if matches else text
    entries = []
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[m.start():end].rstrip() + "\n"
        entries.append((m.group(1), m.group(2), body))
    return header, entries


def sort_entries(entries):
    """Стабильная сортировка по дате: внутри дня сохраняется исходный порядок."""
    return sorted(entries, key=lambda e: e[0])


def check(entries):
    problems = []
    for i in range(1, len(entries)):
        if entries[i][0] < entries[i - 1][0]:
            problems.append(f"{entries[i][0]} стоит после {entries[i - 1][0]}")
    return problems


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--max", type=int, default=MAX_ENTRIES)
    ap.add_argument("--max-bytes", type=int, default=MAX_BYTES)
    args = ap.parse_args()

    header, entries = parse(LOG)
    problems = check(entries)
    print(f"записей в log.md: {len(entries)}")
    if problems:
        print(f"нарушений порядка: {len(problems)}")
        for p in problems[:5]:
            print(f"  {p}")
        if len(problems) > 5:
            print(f"  … и ещё {len(problems) - 5}")

    ordered = sort_entries(entries)
    # Хвост ограничен и числом записей, и байтами: берём с конца, пока влезаем.
    header_bytes = len(header.rstrip().encode("utf-8")) + 2
    active, used = [], header_bytes
    for entry in reversed(ordered):
        size = len(entry[2].rstrip().encode("utf-8")) + 2
        if active and (len(active) >= args.max or used + size > args.max_bytes):
            break
        active.append(entry)
        used += size
    active.reverse()
    overflow = ordered[:len(ordered) - len(active)]

    print(f"уедет в архив: {len(overflow)}")
    if not args.write:
        print("(ничего не изменено; запусти с --write)")
        return 0

    if overflow:
        os.makedirs(ARCHIVE_DIR, exist_ok=True)
        by_year = {}
        for entry in overflow:
            by_year.setdefault(entry[0][:4], []).append(entry)
        for year, items in sorted(by_year.items()):
            path = os.path.join(ARCHIVE_DIR, f"{year}.md")
            old_header, old_entries = parse(path) if os.path.exists(path) else ("", [])
            if not old_entries:
                old_header = ARCHIVE_HEADER.format(year=year)
            merged = sort_entries(old_entries + items)
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(old_header.rstrip() + "\n\n")
                fh.write("\n".join(e[2].rstrip() + "\n" for e in merged))
            print(f"  {os.path.relpath(path, VAULT)}: {len(merged)} записей")

    if ARCHIVE_POINTER not in header:
        header = header.rstrip() + "\n\n" + ARCHIVE_POINTER + "\n"
    with open(LOG, "w", encoding="utf-8") as fh:
        fh.write(header.rstrip() + "\n\n")
        fh.write("\n".join(e[2].rstrip() + "\n" for e in active))
    print(f"log.md перезаписан: {len(active)} активных записей")
    return 0


if __name__ == "__main__":
    sys.exit(main())
