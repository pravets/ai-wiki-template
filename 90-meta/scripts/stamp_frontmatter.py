#!/usr/bin/env python3
"""Даты и пустые обязательные поля: created/updated из git, tags по умолчанию.

    python3 90-meta/scripts/stamp_frontmatter.py            # отчёт
    python3 90-meta/scripts/stamp_frontmatter.py --write    # применить

created = дата первого коммита файла, updated = дата последнего коммита
(для файлов без истории — дата изменения на диске). values вручную не выдумываются:
чего нет, то `[]`, а не догадка.
"""

import argparse
import os
import re
import subprocess
import sys
from datetime import date

VAULT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lint_frontmatter import SKIP_DIRS, SKIP_NAMES  # noqa: E402

FM = re.compile(r"\A---\n(.*?)\n---\n", re.S)


def git_date(rel, first=False):
    args = ["git", "log"] + (["--diff-filter=A"] if first else ["-1"]) + \
           ["--format=%ad", "--date=short", "--", rel]
    try:
        out = subprocess.run(args, cwd=VAULT, capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    lines = [l for l in out.stdout.strip().splitlines() if l]
    if not lines:
        return None
    return lines[-1] if first else lines[0]


def insert_after(raw, key, line):
    anchor = re.search(rf"^{key}:.*$", raw, re.M)
    if anchor:
        return raw[:anchor.end()] + "\n" + line + raw[anchor.end():]
    return raw.rstrip() + "\n" + line


def process(path, rel):
    text = open(path, encoding="utf-8", errors="replace").read()
    m = FM.match(text)
    if not m:
        return text, []
    raw = m.group(1)
    changed = []

    if not re.search(r"^created:", raw, re.M):
        created = git_date(rel, first=True) or git_date(rel) or date.today().isoformat()
        raw = insert_after(raw, "name", f"created: {created}")
        changed.append("created")

    # G3: не только дописать недостающее, но и поднять отставшее — линт считает
    # `updated` старше git-даты последнего коммита предупреждением (updated-stale).
    if re.search(r"^updated:", raw, re.M):
        git_last = git_date(rel)
        if git_last:
            m_u = re.search(r"^updated:\s*(\S+)", raw, re.M)
            if m_u and m_u.group(1) < git_last:
                raw = raw[:m_u.start(1)] + git_last + raw[m_u.end(1):]
                changed.append(f"updated {m_u.group(1)} -> {git_last}")
    else:
        updated = git_date(rel) or date.today().isoformat()
        raw = insert_after(raw, "created", f"updated: {updated}")
        changed.append("updated")
    if not re.search(r"^tags:", raw, re.M):
        raw = insert_after(raw, "updated", "tags: []")
        changed.append("tags")

    if not changed:
        return text, []
    return text[:m.start(1)] + raw + text[m.end(1):], changed


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--only", metavar="PREFIX")
    args = ap.parse_args()

    touched = 0
    counts = {}
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
            new_text, changed = process(path, rel)
            if not changed:
                continue
            touched += 1
            for c in changed:
                counts[c] = counts.get(c, 0) + 1
            if args.write:
                with open(path, "w", encoding="utf-8") as fh:
                    fh.write(new_text)

    print(f"страниц к правке: {touched}")
    for c, n in sorted(counts.items()):
        print(f"  дописано {c}: {n}")
    if not args.write:
        print("(ничего не изменено; запусти с --write)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
