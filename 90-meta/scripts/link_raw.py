#!/usr/bin/env python3
"""Привязка страниц 10-wiki к исходникам 01-raw полем `raw:` (G8).

    python3 90-meta/scripts/link_raw.py             # отчёт: пары и кандидаты
    python3 90-meta/scripts/link_raw.py --write     # проставить точные совпадения
    python3 90-meta/scripts/link_raw.py --orphans   # raw без потребителя

Точное совпадение (точность: exact) — слаг страницы целиком содержится в имени
raw-файла после отбрасывания даты и суффикса типа (-transcript, -article, ...).
Остальное — кандидаты с оценкой, решение за владельцем: скрипт их не пишет.
"""

import argparse
import os
import re
import sys

VAULT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lint_frontmatter import SKIP_DIRS, SKIP_NAMES  # noqa: E402

RAW = os.path.join(VAULT, "01-raw")
WIKI = os.path.join(VAULT, "10-wiki")
SUFFIX = re.compile(r"-(transcript|article|post|video|summary|faq|tekst|text)$")
DATE = re.compile(r"^\d{4}-\d{2}-\d{2}-")
STOP = {"the", "and", "for", "with", "без", "как", "для", "про", "или"}


def raw_name(filename):
    stem = filename[:-3]
    stem = DATE.sub("", stem)
    stem = SUFFIX.sub("", stem)
    return stem


def tokens(text):
    return {t for t in re.split(r"[^a-zа-яё0-9]+", text.lower()) if t and t not in STOP}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--orphans", action="store_true")
    args = ap.parse_args()

    raws = [f for f in sorted(os.listdir(RAW)) if f.endswith(".md")]
    raw_tokens = {f: tokens(raw_name(f)) for f in raws}

    pages = []
    for name in sorted(os.listdir(WIKI)):
        if not name.endswith(".md") or name in SKIP_NAMES:
            continue
        pages.append(name)

    used = set()
    exact, fuzzy, present = [], [], []
    for name in pages:
        path = os.path.join(WIKI, name)
        text = open(path, encoding="utf-8", errors="replace").read()
        slug = name[:-3]
        m = re.search(r"^raw:\s*(.+)$", text, re.M)
        if m:
            present.append((slug, m.group(1).strip()))
            used.add(m.group(1).strip())
            continue

        slug_tokens = tokens(slug)
        best = None
        for raw in raws:
            if raw in used:
                continue
            rt = raw_tokens[raw]
            if not rt:
                continue
            common = slug_tokens & rt
            if not common:
                continue
            score = len(common) / max(1, len(slug_tokens | rt))
            exact_hit = slug in raw_name(raw).lower() or raw_name(raw).lower() in slug
            cand = (score, raw, exact_hit, sorted(common))
            if best is None or cand[0] > best[0]:
                best = cand
        if not best:
            continue
        score, raw, exact_hit, common = best
        if exact_hit and score >= 0.4:
            exact.append((slug, raw, common))
        elif score >= 0.35:
            fuzzy.append((slug, raw, round(score, 2), common))

    print(f"страниц 10-wiki: {len(pages)}")
    print(f"уже с полем raw:  {len(present)}")
    print(f"точных совпадений: {len(exact)}")
    print(f"кандидатов для решения: {len(fuzzy)}")
    for slug, raw, common in exact:
        print(f"  EXACT {slug} -> {raw}  ({', '.join(common[:4])})")
    for slug, raw, score, common in fuzzy:
        print(f"  ~{score:.2f} {slug} -> {raw}  ({', '.join(common[:4])})")

    if args.orphans:
        orphans = [f for f in raws if f not in used]
        print(f"\nraw без потребителя: {len(orphans)}")
        for f in orphans[:40]:
            print(f"  {f}")
        if len(orphans) > 40:
            print(f"  … и ещё {len(orphans) - 40}")

    if args.write:
        for slug, raw, _ in exact:
            path = os.path.join(WIKI, slug + ".md")
            text = open(path, encoding="utf-8").read()
            m = re.match(r"\A---\n(.*?)\n---\n", text, re.S)
            if not m:
                continue
            raw_fm = m.group(1)
            anchor = re.search(r"^sources:.*$", raw_fm, re.M)
            line = f"raw: {raw}"
            if anchor:
                raw_fm = raw_fm[:anchor.start()] + line + "\n" + raw_fm[anchor.start():]
            else:
                raw_fm = raw_fm.rstrip() + "\n" + line
            open(path, "w", encoding="utf-8").write(
                "---\n" + raw_fm + "\n---\n" + text[m.end():])
        print(f"проставлено raw: {len(exact)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
