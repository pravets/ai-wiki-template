#!/usr/bin/env python3
"""Сверка зоны `42-repos` с живым GitHub: карточки, роли, расхождения.

    python3 skills/_shared/scripts/gh_repos_sync.py               # отчёт
    python3 skills/_shared/scripts/gh_repos_sync.py --write       # создать недостающие карточки
    python3 skills/_shared/scripts/gh_repos_sync.py --forks       # включить форки (по умолчанию мимо)
    python3 skills/_shared/scripts/gh_repos_sync.py --stale 365   # порог «заброшено», дней
    python3 skills/_shared/scripts/gh_repos_sync.py --hub         # перегенерировать README хаба
    python3 skills/_shared/scripts/gh_repos_sync.py --json

Где vault: `--vault PATH`, иначе `$VAULT_ROOT`, иначе поиск вверх от cwd каталога
с `90-meta/`.

Роль берётся только из прав GitHub, не из головы:
    admin | maintain            -> maintainer
    push | triage (без admin)   -> contributor
    pull только                 -> watcher
    fork (не считается работой) -> пропускается, если не --forks

Карточка — суждение владельца (роль, состояние, заметки). Скрипт создаёт
недостающие и сообщает о расхождениях, но никогда не переписывает существующие:
иначе ручные заметки затираются молча.
"""

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import date, datetime, timezone

ROLE_BY_PERM = ("admin", "maintain", "push", "triage", "pull")
TYPE_MAP = {
    "1C Enterprise": "1c", "Python": "python", "JavaScript": "javascript",
    "TypeScript": "typescript", "Java": "java", "Shell": "shell", "Go": "go",
    "Rust": "rust", "C": "c", "C++": "cpp", "HTML": "html", "CSS": "css",
    "Jinja": "jinja", "Dockerfile": "docker", "HCL": "terraform", "Lua": "lua",
    "Kotlin": "kotlin", "PHP": "php", "Ruby": "ruby", "Vue": "vue",
}


def find_vault(explicit):
    if explicit:
        return os.path.abspath(os.path.expanduser(explicit))
    env = os.environ.get("VAULT_ROOT")
    if env:
        return os.path.abspath(os.path.expanduser(env))
    cur = os.path.abspath(os.getcwd())
    while True:
        if os.path.isdir(os.path.join(cur, "90-meta")):
            return cur
        parent = os.path.dirname(cur)
        if parent == cur:
            return os.getcwd()
        cur = parent


def gh(args):
    try:
        out = subprocess.run(["gh"] + args, capture_output=True, text=True, timeout=120)
    except FileNotFoundError:
        raise SystemExit("нужен gh CLI: github.com/cli/cli")
    except subprocess.TimeoutExpired:
        raise SystemExit("gh не ответил за 120 с")
    if out.returncode != 0:
        raise SystemExit(f"gh {' '.join(args)}: {out.stderr.strip()}")
    return out.stdout


def fetch_repos(include_forks, check_forks=True):
    repos = []
    page = 1
    me = gh(["api", "user", "--jq", ".login"]).strip()
    while True:
        chunk = json.loads(gh([
            "api",
            f"user/repos?per_page=100&page={page}&affiliation=owner,collaborator,organization_member&sort=pushed",
        ]))
        if not chunk:
            break
        repos.extend(chunk)
        if len(chunk) < 100:
            break
        page += 1
    result = []
    for r in repos:
        perms = r.get("permissions") or {}
        if perms.get("admin") or perms.get("maintain"):
            role = "maintainer"
        elif perms.get("push") or perms.get("triage"):
            role = "contributor"
        else:
            role = "watcher"
        if r.get("archived"):
            role = "archived"
        parent = (r.get("parent") or {}).get("full_name") or ""
        parent_branch = (r.get("parent") or {}).get("default_branch") or "main"
        ahead = 0
        if r.get("fork") and check_forks:
            if not parent:
                parent, parent_branch = fork_info(r["full_name"])
            if parent:
                ahead = fork_ahead(r["full_name"], parent_branch,
                                   r.get("default_branch") or "main")
            if ahead == 0 and not include_forks:
                continue
            role = "fork" if ahead else "watcher"
        elif r.get("fork") and not include_forks:
            continue
        result.append({
            "full_name": r["full_name"],
            "owner": r["owner"]["login"],
            "name": r["name"],
            "slug": r["full_name"].lower().replace("/", "-").replace("_", "-").replace(".", "-"),
            "role": role,
            "fork": bool(r.get("fork")),
            "ahead": ahead,
            "archived": bool(r.get("archived")),
            "private": bool(r.get("private")),
            "description": (r.get("description") or "").strip(),
            "stack": TYPE_MAP.get(r.get("language") or "", (r.get("language") or "").lower()),
            "language": r.get("language") or "",
            "stars": r.get("stargazers_count", 0),
            "open_issues": r.get("open_issues_count", 0),
            "pushed_at": (r.get("pushed_at") or "")[:10],
            "created_at": (r.get("created_at") or "")[:10],
            "default_branch": r.get("default_branch") or "main",
            "html_url": r.get("html_url") or "",
            "topics": r.get("topics") or [],
            "license": ((r.get("license") or {}).get("spdx_id") or ""),
            "parent": parent,
        })
    return me, result


def fork_info(full_name):
    """parent (owner/name) и его default_branch: в списочном ответе их нет."""
    try:
        out = subprocess.run(["gh", "api", f"repos/{full_name}", "--jq",
                              '[.parent.full_name // "", .parent.default_branch // "main"] | @tsv'],
                             capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return "", "main"
    if out.returncode != 0:
        return "", "main"
    parts = out.stdout.strip().split("\t")
    return (parts[0] if parts else ""), (parts[1] if len(parts) > 1 else "main")


def fork_ahead(full_name, parent_branch, my_branch):
    """Сколько моих коммитов в форке сверх upstream. 0 — зеркало, не проект."""
    for base in dict.fromkeys([parent_branch, "main", "master"]):
        try:
            out = subprocess.run(
                ["gh", "api", f"repos/{full_name}/compare/{base}...{my_branch}",
                 "--jq", ".ahead_by"],
                capture_output=True, text=True, timeout=60)
        except (OSError, subprocess.SubprocessError):
            continue
        if out.returncode != 0:
            continue
        try:
            return int(out.stdout.strip() or 0)
        except ValueError:
            continue
    return 0


def parse_card(text):
    m = re.match(r"\A---\n(.*?)\n---\n", text, re.S)
    if not m:
        return {}, text
    fm = {}
    for line in m.group(1).splitlines():
        k = re.match(r"^([A-Za-z_][\w-]*)\s*:\s*(.*)$", line)
        if k:
            fm[k.group(1)] = k.group(2).strip().strip('"').strip("'")
    return fm, text[m.end():]


def existing_cards(vault):
    zone = os.path.join(vault, "42-repos")
    cards = {}
    if not os.path.isdir(zone):
        return cards
    for name in sorted(os.listdir(zone)):
        if not name.endswith(".md") or name in ("README.md", "log.md"):
            continue
        path = os.path.join(zone, name)
        fm, _ = parse_card(open(path, encoding="utf-8", errors="replace").read())
        if fm.get("repo"):
            cards[fm["repo"]] = (name, fm)
    return cards


CARD = """---
name: {name}
type: repo
created: {created}
updated: {created}
tags: [{tags}]
repo: {full_name}
role: {role}
status: {status}
stack: [{stack}]
{extra}sources:
  - {html_url}
---
## Что это

{description}

## Моя роль

{role_note}

## Журнал

События (PR, релизы, разборы) — append-only в `42-repos/log.md`, строками
`## [YYYY-MM-DD] {full_name} | суть`. Здесь — только устойчивое: зачем репозиторий
в базе и что в нём важно.

## Ссылки

- Репозиторий: {html_url}
"""

ROLE_NOTE = {
    "maintainer": "Мейнтейнер: права admin/maintain. Решения по PR и релизам — мои.",
    "contributor": "Контрибьютор: права push/triage без admin. Мои изменения идут через PR к чужому мейнтейнеру.",
    "fork": "Свой форк с собственными коммитами сверх upstream: правлю под себя, upstream тяну по необходимости.",
    "watcher": "Только чтение: права pull. Слежу, не участвую.",
    "archived": "Репозиторий заархивирован: не развивается, карточка хранится как история.",
}


def _days_since(iso_date):
    pushed = datetime.strptime(iso_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - pushed).days


def status_for(repo, stale_days):
    if repo["archived"]:
        return "archived"
    if not repo["pushed_at"]:
        return "unknown"
    age = _days_since(repo["pushed_at"])
    if age <= 90:
        return "active"
    if age <= stale_days:
        return "on-demand"
    return "paused"


def build_card(repo, stale_days):
    # tags — домен из общего словаря; язык живёт в `stack`, в теги его не тащим
    if repo["stack"] == "1c":
        tags = ["1c", "tools"]
    elif repo["role"] == "maintainer":
        tags = ["tools"]
    else:
        tags = []
    tags = tags[:2]
    extra = ""
    if repo["fork"] and repo["parent"]:
        extra = f"upstream: {repo['parent']}\n"
    desc = repo["description"] or "_Описание в GitHub не задано._"
    return CARD.format(
        name=repo["name"],
        created=date.today().isoformat(),
        tags=", ".join(tags),
        full_name=repo["full_name"],
        role=repo["role"],
        status=status_for(repo, stale_days),
        stack=", ".join(filter(None, [repo["stack"]])),
        extra=extra,
        html_url=repo["html_url"],
        description=desc,
        role_note=ROLE_NOTE[repo["role"]],
    )


def hub_markdown(repos, cards):
    lines = [
        "# 42-repos — хаб",
        "",
        "Репозитории, где я мейнтейнер, контрибьютор или веду свой форк. **Таблица "
        "генерируется** `gh_repos_sync.py --hub` из GitHub + frontmatter карточек; "
        "руками не править — правка будет перезаписана.",
        "",
        f"_Сгенерировано {date.today().isoformat()}. Контракт зоны — [[42-repos/README]], "
        "журнал событий — [[42-repos/log]]._",
        "",
        "## Мейнтейнер",
        "",
        "| Репозиторий | Карточка | Стек | Состояние | Push | ⭐ |",
        "|---|---|---|---|---|---|",
    ]
    for group, title in (("maintainer", "## Мейнтейнер"), ("contributor", "## Контрибьютор"),
                         ("fork", "## Свои форки"), ("watcher", "## Наблюдаю"),
                         ("archived", "## Архив")):
        rows = [r for r in repos if r["role"] == group]
        if not rows:
            continue
        if group != "maintainer":
            lines += ["", title, "",
                      "| Репозиторий | Карточка | Стек | Состояние | Push | ⭐ |",
                      "|---|---|---|---|---|---|"]
        for r in sorted(rows, key=lambda x: x["pushed_at"], reverse=True):
            card = cards.get(r["full_name"])
            link = f"[[42-repos/{card[0][:-3]}]]" if card else "_нет_"
            status = (card[1].get("status") if card else "") or status_for(r, 365)
            lines.append(f"| [{r['full_name']}]({r['html_url']}) | {link} | "
                         f"{r['language'] or '—'} | {status} | {r['pushed_at']} | {r['stars']} |")
    return "\n".join(lines) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--vault")
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--hub", action="store_true", help="перегенерировать README хаба зоны")
    ap.add_argument("--forks", action="store_true", help="включить все форки, даже зеркала")
    ap.add_argument("--no-fork-check", action="store_true",
                    help="не проверять форки через compare (быстрее, но пропустит свои форки)")
    ap.add_argument("--stale", type=int, default=180, help="дней до status: paused")
    ap.add_argument("--max-age", type=int, default=365,
                    help="карточки только для репозиториев с push за N дней; 0 — все")
    ap.add_argument("--all", action="store_true", help="карточки на все репозитории")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    vault = find_vault(args.vault)
    zone = os.path.join(vault, "42-repos")
    me, repos = fetch_repos(args.forks, check_forks=not args.no_fork_check)
    cards = existing_cards(vault)

    missing = [r for r in repos if r["full_name"] not in cards]
    fresh = [r for r in missing if args.all or not args.max_age
             or (r["pushed_at"] and _days_since(r["pushed_at"]) <= args.max_age)]
    drift = [(r, cards[r["full_name"]]) for r in repos
             if r["full_name"] in cards and cards[r["full_name"]][1].get("role") not in (r["role"], None, "")]
    gone = [name for name, (fname, fm) in cards.items()
            if fm.get("repo") and name not in {r["full_name"] for r in repos}]

    if args.json:
        print(json.dumps({
            "account": me, "vault": vault, "repos": len(repos),
            "cards": len(cards), "missing": [r["full_name"] for r in missing],
            "role_drift": [{"repo": r["full_name"], "github": r["role"],
                            "card": c[1].get("role")} for r, c in drift],
            "cards_without_repo": gone,
            "by_role": {role: sum(1 for r in repos if r["role"] == role)
                        for role in ("maintainer", "contributor", "fork", "watcher", "archived")},
        }, ensure_ascii=False, indent=1))
        return 0

    print(f"аккаунт: {me}")
    print(f"vault:   {vault}")
    print(f"репозиториев (без форков): {len(repos)}")
    for role in ("maintainer", "contributor", "fork", "watcher", "archived"):
        n = sum(1 for r in repos if r["role"] == role)
        print(f"  {role:12s} {n}")
    print(f"карточек в 42-repos: {len(cards)}")
    print(f"без карточки:        {len(missing)} (к созданию: {len(fresh)}, "
          f"старше {args.max_age} дн. — только строка в хабе)")
    for r in fresh[:40]:
        print(f"  NEW {r['full_name']} ({r['role']}, {r['pushed_at']})")
    if len(fresh) > 40:
        print(f"  … и ещё {len(fresh) - 40}")
    if drift:
        print(f"роль разошлась с GitHub: {len(drift)}")
        for r, c in drift:
            print(f"  DRIFT {r['full_name']}: карточка {c[1].get('role')}, GitHub {r['role']}")
    if gone:
        print(f"карточки без репозитория: {len(gone)}")
        for name in gone:
            print(f"  GONE {name}")

    if args.write:
        if not os.path.isdir(zone):
            os.makedirs(zone, exist_ok=True)
        created = 0
        for r in fresh:
            path = os.path.join(zone, r["slug"] + ".md")
            if os.path.exists(path):
                print(f"  пропуск (файл занят): {path}")
                continue
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(build_card(r, args.stale))
            created += 1
        print(f"создано карточек: {created}")
        cards = existing_cards(vault)

    if args.hub:
        path = os.path.join(zone, "hub.md")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(hub_markdown(repos, cards))
        print(f"хаб перегенерирован: {os.path.relpath(path, vault)}")

    if not args.write and not args.hub:
        print("(ничего не изменено; --write — карточки, --hub — таблица)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
