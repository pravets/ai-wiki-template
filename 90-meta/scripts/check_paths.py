#!/usr/bin/env python3
"""Проверка: все пути вида `path/to/file.py` из *.md существуют.

    python3 90-meta/scripts/check_paths.py            # отчёт, exit 1 при находках
    python3 90-meta/scripts/check_paths.py --quiet    # только счётчик

Ловит ровно тот класс дефекта, ради которого шаблон ремонтируется: дока
обещает файл, файла нет. Проверяются только пути, оканчивающиеся на .py/.sh/.json,
и только те, что начинаются с известного корня.
"""

import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ROOTS = ("90-meta/", "skills/", "42-repos/", "40-projects/", "15-precedent/",
         "60-travel/", "70-personal/", "10-wiki/")
# Шаблоны с плейсхолдерами (owner/name, <slug>) и примеры «в вашем vault'е».
SKIP_MARKERS = ("<", ">", "{", "}", "*", "$", "…", "vault'е", "PATH")
# Путь ищем в любом месте строки — внутри бэктиков, в код-фенсах, посреди
# предложения. Иначе `python3 90-meta/scripts/x.py "q"` в одном бэктике
# проскакивает мимо детектора.
PATH_RE = re.compile(
    r"(?<![\w/.-])((?:90-meta|skills|42-repos|40-projects|15-precedent|60-travel"
    r"|70-personal|10-wiki)/[A-Za-z0-9_./-]*\.(?:py|sh|json))")


def scan():
    missing = []
    for root, dirs, files in os.walk(ROOT):
        dirs[:] = [d for d in dirs if d not in (".git", ".obsidian", ".trash",
                                                ".wiki-index", "node_modules")]
        for name in files:
            if not name.endswith(".md"):
                continue
            path = os.path.join(root, name)
            rel_doc = os.path.relpath(path, ROOT).replace(os.sep, "/")
            with open(path, encoding="utf-8", errors="replace") as fh:
                text = fh.read()
            for line_no, line in enumerate(text.splitlines(), 1):
                for cand in PATH_RE.findall(line):
                    if any(m in cand for m in SKIP_MARKERS):
                        continue
                    if not cand.startswith(ROOTS):
                        continue
                    if not os.path.exists(os.path.join(ROOT, cand)):
                        missing.append((rel_doc, line_no, cand))
    return missing


def main():
    quiet = "--quiet" in sys.argv
    missing = scan()
    if not quiet:
        for doc, line_no, cand in missing:
            print(f"{doc}:{line_no}: нет файла {cand}")
    print(f"висячих путей: {len(missing)}")
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
