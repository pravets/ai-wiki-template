#!/usr/bin/env python3
"""Проверка банка прецедентных текстов (15-precedent/).

Без внешних зависимостей: frontmatter разбирается вручную (плоские пары key: value
и YAML-списки в [..] или блоках "  - item"). Если установлен PyYAML — используется он.

Что проверяется:
  - обязательные поля: type, text, author, attribution, sources
  - attribution из допустимого набора
  - theme/device — из словаря themes.md
  - sources не пуст
  - дубли по нормализованному text (нижний регистр, без пунктуации/пробелов)

Использование:
  python3 precedent_check.py <vault-root-or-15-precedent-dir>
Код возврата 1, если есть ошибки (дубли и нарушения контракта).
"""
import os
import re
import sys
import unicodedata

REQUIRED = ("type", "text", "author", "attribution", "sources")
ATTRIBUTION = {"primary", "secondary", "misattributed", "unverified"}


def norm(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).lower()
    text = re.sub(r"[\W_]+", "", text)
    return text


def parse_frontmatter(raw: str) -> dict:
    m = re.match(r"^---\r?\n(.*?)\r?\n---", raw, re.S)
    if not m:
        return {}
    body = m.group(1)
    try:
        import yaml  # type: ignore
        return yaml.safe_load(body) or {}
    except Exception:
        pass
    data, key = {}, None
    for line in body.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if re.match(r"^\s+-\s", line) and key:
            val = line.split("-", 1)[1].strip().strip('"').strip("'")
            if not isinstance(data.get(key), list):
                data[key] = []
            data[key].append(val)
            continue
        if ":" in line:
            k, v = line.split(":", 1)
            key = k.strip()
            v = v.strip()
            if v.startswith("[") and v.endswith("]"):
                inner = v[1:-1].strip()
                data[key] = [x.strip().strip('"').strip("'") for x in inner.split(",") if x.strip()]
            elif v == "":
                data[key] = []
            else:
                data[key] = v.strip('"').strip("'")
    return data


def load_vocab(path: str):
    """Строки таблиц в themes.md: | `значение` | ... | — берём первый столбец в бэктиках."""
    themes, devices = set(), set()
    if not os.path.exists(path):
        return themes, devices
    section = None
    for line in open(path, encoding="utf-8"):
        if line.startswith("## "):
            if "Темы" in line:
                section = "theme"
            elif "Приёмы" in line:
                section = "device"
            else:
                section = None
        m = re.match(r"^\|\s*`([^`]+)`\s*\|", line)
        if m and section:
            (themes if section == "theme" else devices).add(m.group(1))
    return themes, devices


def main(argv):
    if len(argv) != 2:
        print(__doc__)
        return 2
    root = argv[1]
    base = root if os.path.basename(root.rstrip("/")) == "15-precedent" else os.path.join(root, "15-precedent")
    bank = os.path.join(base, "bank")
    if not os.path.isdir(bank):
        print(f"нет каталога {bank}")
        return 2
    themes, devices = load_vocab(os.path.join(base, "themes.md"))
    errors, seen = [], {}
    for name in sorted(os.listdir(bank)):
        if not name.endswith(".md"):
            continue
        path = os.path.join(bank, name)
        data = parse_frontmatter(open(path, encoding="utf-8").read())
        if not data:
            errors.append(f"{name}: нет frontmatter")
            continue
        for field in REQUIRED:
            if not data.get(field):
                errors.append(f"{name}: пустое обязательное поле {field}")
        att = data.get("attribution")
        if att and att not in ATTRIBUTION:
            errors.append(f"{name}: attribution={att!r} вне {sorted(ATTRIBUTION)}")
        for field, vocab in (("theme", themes), ("device", devices)):
            vals = data.get(field) or []
            if isinstance(vals, str):
                vals = [vals]
            for v in vals:
                if vocab and v not in vocab:
                    errors.append(f"{name}: {field}={v!r} нет в themes.md")
        text = data.get("text") or ""
        if text:
            key = norm(text)
            if key in seen:
                errors.append(f"{name}: дубль текста с {seen[key]}")
            else:
                seen[key] = name
    cards = len(seen)
    print(f"карточек: {cards}; тем в словаре: {len(themes)}; приёмов: {len(devices)}")
    for e in errors:
        print("  !", e)
    print("ОК" if not errors else f"ошибок: {len(errors)}")
    return 0 if not errors else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
