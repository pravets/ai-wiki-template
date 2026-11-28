#!/usr/bin/env python3
"""Линт frontmatter вики-слоя vault по контракту AGENTS.md («Frontmatter и теги»).

Использование:
    python3 90-meta/scripts/lint_frontmatter.py                  # отчёт по всему vault
    python3 90-meta/scripts/lint_frontmatter.py --files          # + список нарушителей
    python3 90-meta/scripts/lint_frontmatter.py --json           # машиночитаемый отчёт
    python3 90-meta/scripts/lint_frontmatter.py --write-baseline 90-meta/lint-baseline.json
    python3 90-meta/scripts/lint_frontmatter.py --baseline 90-meta/lint-baseline.json --strict
    python3 90-meta/scripts/lint_frontmatter.py --git-dates      # сверить updated с git
    python3 90-meta/scripts/lint_frontmatter.py --changed A.md B.md   # режим хука

Смысл baseline: старые страницы нормализуются партиями (grandfathering), поэтому
список известных нарушений хранится в файле. --strict падает только на НОВЫХ
нарушениях: путь, которого нет в baseline, или новый код нарушения на известном
пути. Убрать нарушение из baseline можно и нужно — скрипт сам подсказывает
устаревшие записи (--prune-baseline).
"""

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import date

VAULT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

COMMON = ("name", "type", "created", "updated", "tags")
# Зоны, где `tags` — исключение из общего правила: у дампа чата тема появляется
# только в выжимке, до разбора тегировать нечего.
TAGS_OPTIONAL = ("05-chats",)
DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# Правила по подпути: сначала самые длинные префиксы.
# (prefix, допустимые type, доп. обязательные поля, обязательные непустые)
ZONE_RULES = [
    ("15-precedent/bank", ("precedent",),
     ("text", "kind", "author", "theme", "device", "attribution", "sources"), ()),
    ("15-precedent/works", ("work",), ("author", "year", "kind", "sources"), ()),
    ("42-repos", ("repo",), ("repo", "role", "status", "sources"), ()),
    ("60-travel/poi", ("church", "abandoned", "nature", "urban", "fortress", "route", "other"),
     ("region", "status", "coords", "location", "sources"), ()),
    ("10-wiki", ("concept", "howto", "tool", "survey", "comparison", "case", "talk",
                 "company", "style-guide"), ("sources",), ()),
    ("35-courses", ("course", "course-module", "insight"), ("sources",), ("sources",)),
    ("15-precedent", ("precedent",), ("sources",), ()),
    ("20-people", ("work", "client", "contractor", "community", "personal", "travel"),
     ("org", "role", "contact", "status", "first_met"), ()),
    ("25-interactions", ("meeting", "call", "chat", "email"), ("date", "person"), ()),
    # Дамп чата: session — ключ склейки частей, part есть только у многочастных.
    # tags опциональны: у сырца темы ещё нет, она появляется в выжимке.
    ("05-chats", ("chat",), ("project", "model", "session", "messages"), ()),
    ("40-projects", ("project", "talk", "spec", "status", "plan", "masterclass"),
     ("project", "status"), ()),
    ("50-drafts", ("ideas", "draft", "outline", "slides", "plan", "post"), ("status",), ()),
    ("60-travel", ("church", "abandoned", "nature", "urban", "fortress", "route", "other"),
     ("region", "status", "coords", "location", "sources"), ()),
    ("70-personal", ("lifeadmin-profile", "lifeadmin-provider", "lifeadmin-month",
                     "lifeadmin-report"), (), ()),
    ("90-meta", ("template", "accumulator", "script"), (), ()),
]

# Поля, обязательные только для конкретного типа внутри зоны: формат ZONE_RULES
# даёт один набор на префикс, а у курсов типы различаются полями.
# (prefix, type) -> доп. обязательные поля сверх правила зоны
TYPE_REQUIRED = {
    ("35-courses", "course"): ("platform", "author", "status"),
    ("35-courses", "course-module"): ("course", "part"),
    ("35-courses", "insight"): ("course", "source", "area", "status"),
}

# (prefix, type) -> поле -> допустимые значения
TYPE_ENUM = {
    ("35-courses", "course"): {
        "status": ("planned", "active", "paused", "done", "dropped"),
    },
    ("35-courses", "insight"): {
        "status": ("to-apply", "applied", "dropped", "promoted"),
        "area": ("work", "1c", "personal", "study"),
    },
}

# Условно обязательные поля: (prefix, type, поле) -> при каких значениях другого
# поля оно требуется. Дата старта нужна курсу в работе, но не запланированному.
TYPE_CONDITIONAL = {
    ("35-courses", "course", "started"): ("status", ("active", "paused", "done")),
    ("35-courses", "insight", "promoted_to"): ("status", ("promoted",)),
}

# Закрытый словарь тегов (AGENTS.md, «Словарь тегов»). 47 значений.
TAGS = {
    # домен и технологии
    "1c", "ai", "llm", "local-models", "agents", "mcp", "devops", "ci-cd", "monitoring",
    "git", "linux", "windows", "macos", "networking", "security", "database", "testing",
    "docker", "kubernetes", "self-hosted", "cloud", "gpu", "audio", "video", "media",
    "design", "content", "product", "management", "gaming", "tools",
    "api", "integrations", "ocr",
    # люди и сообщество
    "conference", "speaker", "community", "blogger", "analytics", "hr",
    # предметные
    "travel", "finance", "personal", "health", "learning", "household",
    # стартовый набор 90-meta/schema.md (уточняется в блоке инициализации)
    "people", "project", "talk", "transcription", "research", "meta",
    # форма подачи
    "digest",
    # обезличенные примеры шаблона (70-personal/example/)
    "example",
}

# Механическая канонизация: как встречается -> канон.
CANON = {
    "selfhost": "self-hosted", "selfhosted": "self-hosted", "self-hosting": "self-hosted",
    "agent": "agents", "ai-agents": "agents", "агенты": "agents",
    "локальные-модели": "local-models", "local-ai-models": "local-models",
    "тестирование": "testing", "unit-тесты": "testing",
    "мониторинг": "monitoring", "observability": "monitoring",
    "аналитика": "analytics", "конспект": "digest",
    "конференции": "conference", "спикер": "speaker",
    "интеграции": "integrations",
}

# Лимиты размера (G11), байты. Медиана 10-wiki — 7.7 КБ; порог 26 КБ отсекает
# верхние 6% (каталоги и разросшиеся конспекты), которые пора делить по подтемам.
SIZE_LIMITS = [
    ("10-wiki", 26 * 1024),
    ("35-courses", 26 * 1024),
    ("15-precedent/bank", 4 * 1024),
    ("20-people", 8 * 1024),
    ("42-repos", 12 * 1024),
    ("05-chats", 100 * 1024),
]
DEFAULT_SIZE_LIMIT = 60 * 1024

SKIP_DIRS = ("90-meta/templates", "90-meta/log", "60-travel/trips", "30-journal", "01-raw",
             "00-inbox", ".git", ".obsidian", ".trash", ".wiki-index")
# Служебные и генерируемые файлы: контракт frontmatter на них не действует.
SKIP_NAMES = ("README.md", "log.md", "status.md", "index.md", "AGENTS.md",
              "hub.md", "themes.md", "poi-map.md", "tag-proposals.md",
              "schema.md", "known-concepts.md")


# Предупреждения: показываются, но не блокируют коммит. updated-stale не должен
# ломать автокоммиттер владельца — контракт требует поднимать updated, но гейт
# обязан оставаться включённым и для ручных правок из Obsidian.
WARN_PREFIXES = ("updated-stale",)


def is_warn(code):
    return code.startswith(WARN_PREFIXES)


def split_codes(problems):
    blocking = [p for p in problems if not is_warn(p)]
    warnings = [p for p in problems if is_warn(p)]
    return blocking, warnings


def frontmatter(text):
    if not text.startswith("---"):
        return None
    end = text.find("\n---", 3)
    if end < 0:
        return None
    fields = {}
    last = None
    for line in text[3:end].splitlines():
        item = re.match(r"^\s+-\s+(.*)$", line)
        if item and last:
            prev = fields.get(last, "")
            fields[last] = (prev + ", " + item.group(1).strip().strip('"').strip("'")).strip(", ")
            continue
        m = re.match(r"^([A-Za-z_][\w-]*)\s*:\s*(.*)$", line)
        if m:
            last = m.group(1)
            fields[last] = m.group(2).strip().strip('"').strip("'")
    return fields


def tag_list(raw):
    return [t.strip().strip('"').strip("'") for t in raw.strip().strip("[]").split(",")
            if t.strip()]


def rule_for(rel):
    best = None
    for prefix, types, extra, nonempty in ZONE_RULES:
        if rel == prefix or rel.startswith(prefix + "/"):
            if best is None or len(prefix) > len(best[0]):
                best = (prefix, types, extra, nonempty)
    return best


def git_date(rel):
    try:
        out = subprocess.run(
            ["git", "log", "-1", "--format=%ad", "--date=short", "--", rel],
            cwd=VAULT, capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    lines = [l for l in out.stdout.strip().splitlines() if l]
    if not lines:
        return None
    return lines[0]


def check(rel, text, abs_path, check_git=False):
    """Возвращает список кодов нарушений (стабильных, без свободного текста)."""
    problems = []
    rule = rule_for(rel)
    if rule is None:
        return problems
    prefix, types, extra, nonempty = rule
    fm = frontmatter(text)
    if fm is None:
        return ["no-frontmatter"]

    extra = tuple(extra) + tuple(TYPE_REQUIRED.get((prefix, fm.get("type")), ()))

    for key in COMMON + extra:
        if key == "name" and rel.endswith("/slides.md"):
            # Slidev читает title из своего frontmatter; дублировать его в name бессмысленно
            if "name" not in fm and "title" not in fm:
                problems.append("missing:name")
            continue
        if key == "tags" and prefix in TAGS_OPTIONAL:
            continue
        if key not in fm:
            problems.append(f"missing:{key}")
        elif key in nonempty and fm[key] in ("", "[]"):
            problems.append(f"empty:{key}")
    if fm.get("sources") in ("", "[]") and "sources" in extra:
        problems.append("empty:sources")
    if "title" in fm and not rel.endswith("/slides.md"):
        problems.append("title-duplicate")
    if fm.get("type") and fm["type"] not in types:
        problems.append("type-not-in-enum")

    for (p_prefix, p_type), fields in TYPE_ENUM.items():
        if prefix != p_prefix or str(fm.get("type") or "") != p_type:
            continue
        for field, allowed in fields.items():
            val = fm.get(field)
            if val and val not in allowed:
                problems.append(f"{field}-not-in-enum")

    for (p_prefix, p_type, field), (other, values) in TYPE_CONDITIONAL.items():
        if prefix != p_prefix or str(fm.get("type") or "") != p_type:
            continue
        if fm.get(other) in values and not fm.get(field):
            problems.append(f"missing:{field}")

    for key in ("created", "updated"):
        val = fm.get(key)
        if val and not DATE.match(val):
            problems.append(f"{key}-not-iso")
    if (fm.get("created") and fm.get("updated")
            and DATE.match(fm["created"]) and DATE.match(fm["updated"])
            and fm["updated"] < fm["created"]):
        problems.append("updated-before-created")

    tags = tag_list(fm.get("tags", ""))
    if len(tags) > 5:
        problems.append("too-many-tags")
    for t in tags:
        if t in CANON:
            problems.append(f"tag-canonicalize:{t}")
        elif t not in TAGS:
            problems.append(f"tag-outside:{t}")
    if len(tag_list(fm.get("kw", ""))) > 8:
        problems.append("too-many-kw")

    # G8: поле raw: должно указывать на существующий файл в 01-raw
    if fm.get("raw"):
        raw_val = fm["raw"].strip().strip('"')
        if raw_val and not os.path.exists(os.path.join(VAULT, "01-raw", raw_val)):
            problems.append("raw-missing-file")

    # G11: размер
    limit = DEFAULT_SIZE_LIMIT
    for prefix, lim in SIZE_LIMITS:
        if rel.startswith(prefix):
            limit = lim
            break
    try:
        if os.path.getsize(abs_path) > limit:
            problems.append(f"too-large:{limit // 1024}k")
    except OSError:
        pass

    # G3: updated не отстаёт от последнего коммита файла
    if check_git and fm.get("updated") and DATE.match(fm["updated"]):
        last = git_date(rel)
        if last and last > fm["updated"]:
            problems.append("updated-stale")

    return problems


def check_log():
    """G7: даты в log.md идут по возрастанию (журнал дописывается в конец)."""
    path = os.path.join(VAULT, "log.md")
    if not os.path.exists(path):
        return []
    dates = re.findall(r"^## \[(\d{4}-\d{2}-\d{2})\]", open(path, encoding="utf-8").read(),
                       re.M)
    bad = []
    for i in range(1, len(dates)):
        if dates[i] < dates[i - 1]:
            bad.append(f"log-order:{dates[i]} после {dates[i - 1]}")
    return bad


def collect(paths=None, check_git=False):
    violations = {}
    total = 0
    if paths is not None:
        candidates = [(p, os.path.join(VAULT, p)) for p in paths
                      if os.path.basename(p) not in SKIP_NAMES]
    else:
        candidates = []
        for root, dirs, files in os.walk(VAULT):
            dirs[:] = [d for d in dirs if d not in (".git", ".obsidian", ".trash")]
            for name in sorted(files):
                if not name.endswith(".md") or name in SKIP_NAMES:
                    continue
                abs_path = os.path.join(root, name)
                candidates.append((os.path.relpath(abs_path, VAULT).replace(os.sep, "/"),
                                   abs_path))
    for rel, abs_path in candidates:
        if any(rel.startswith(s) for s in SKIP_DIRS):
            continue
        if not os.path.exists(abs_path):
            continue
        total += 1
        with open(abs_path, encoding="utf-8", errors="replace") as fh:
            problems = check(rel, fh.read(), abs_path, check_git)
        if problems:
            violations[rel] = sorted(set(problems))
    return total, violations


def load_baseline(path):
    if not path or not os.path.exists(path):
        return {"violations": {}}
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--files", action="store_true", help="печатать нарушителей")
    ap.add_argument("--json", action="store_true", help="отчёт в JSON")
    ap.add_argument("--strict", action="store_true",
                    help="exit 1 только на нарушениях вне baseline")
    ap.add_argument("--baseline", metavar="FILE", help="файл известных нарушений")
    ap.add_argument("--write-baseline", metavar="FILE", help="записать текущее состояние")
    ap.add_argument("--prune-baseline", action="store_true",
                    help="убрать из baseline исправленные записи")
    ap.add_argument("--git-dates", action="store_true", help="сверить updated с git")
    ap.add_argument("--changed", nargs="*", metavar="FILE", help="проверить только эти файлы")
    args = ap.parse_args()

    changed = args.changed
    if changed == ["-"]:
        changed = [line.strip() for line in sys.stdin if line.strip()]

    total, violations = collect(changed if changed else None, args.git_dates)
    log_problems = check_log() if not args.changed else []

    if args.write_baseline:
        payload = {
            "version": 1,
            "generated": date.today().isoformat(),
            "count": len(violations),
            "violations": violations,
        }
        with open(args.write_baseline, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=1, sort_keys=True)
            fh.write("\n")
        print(f"baseline записан: {args.write_baseline} ({len(violations)} страниц)")
        return 0

    baseline = load_baseline(args.baseline)
    known = baseline.get("violations", {})

    new_violations = {}
    warn_violations = {}
    if known:
        for rel, problems in violations.items():
            blocking, warnings = split_codes(problems)
            if warnings:
                warn_violations[rel] = warnings
            allowed = set(known.get(rel, []))
            fresh = [p for p in blocking if p not in allowed]
            if fresh:
                new_violations[rel] = fresh
    else:
        for rel, problems in violations.items():
            blocking, warnings = split_codes(problems)
            if warnings:
                warn_violations[rel] = warnings
            if blocking:
                new_violations[rel] = blocking

    fixed = [rel for rel in known if rel not in violations]
    improved = [rel for rel, problems in violations.items()
                if rel in known and set(problems) < set(known[rel])]

    if args.prune_baseline and args.baseline:
        cleaned = {rel: sorted(problems) for rel, problems in violations.items()}
        payload = {"version": 1, "generated": date.today().isoformat(),
                   "count": len(cleaned), "violations": cleaned}
        with open(args.baseline, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=1, sort_keys=True)
            fh.write("\n")
        print(f"baseline подрезан: было {len(known)}, стало {len(cleaned)}")
        return 0

    if args.json:
        per_zone = {}
        for rel, probs in violations.items():
            if split_codes(probs)[0]:
                zone = rel.split("/")[0]
                per_zone[zone] = per_zone.get(zone, 0) + 1
        print(json.dumps({
            "total": total,
            "violations": sum(1 for p in violations.values() if split_codes(p)[0]),
            "warnings": sum(1 for p in violations.values() if split_codes(p)[1]),
            "per_zone": per_zone,
            "new": new_violations,
            "fixed_since_baseline": fixed,
            "improved_since_baseline": improved,
            "log": log_problems,
            "details": violations,
        }, ensure_ascii=False, indent=1))
    else:
        per_zone = {}
        blocking_count = 0
        for rel, probs in violations.items():
            if split_codes(probs)[0]:
                blocking_count += 1
                zone = rel.split("/")[0]
                per_zone[zone] = per_zone.get(zone, 0) + 1
        print(f"страниц проверено: {total}")
        print(f"с нарушениями:     {blocking_count}")
        for zone, n in sorted(per_zone.items()):
            print(f"  {zone:16s} {n}")
        if known:
            print(f"новых сверх baseline: {len(new_violations)}")
            for rel, problems in sorted(new_violations.items()):
                print(f"  NEW {rel}: {', '.join(problems)}")
            if fixed and not args.changed:
                print(f"исправлено с прошлого прогона: {len(fixed)} (запусти --prune-baseline)")
        if warn_violations:
            print(f"предупреждений: {len(warn_violations)}")
        if log_problems:
            print("журнал:")
            for p in log_problems[:10]:
                print(f"  {p}")
        if args.files:
            print()
            for rel, problems in sorted(violations.items()):
                print(f"{rel}: {', '.join(problems)}")

    if args.strict:
        if new_violations or log_problems:
            return 1
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
