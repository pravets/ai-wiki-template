#!/usr/bin/env python3
"""BM25-поиск по vault на SQLite FTS5. Заменяет чтение index.md глазами (G5).

    python3 90-meta/scripts/wiki_search.py index            # пересобрать (инкрементально)
    python3 90-meta/scripts/wiki_search.py index --full     # пересобрать с нуля
    python3 90-meta/scripts/wiki_search.py "postgres bloat" -n 5
    python3 90-meta/scripts/wiki_search.py "sentry 1c" -n 8
    python3 90-meta/scripts/wiki_search.py "codex" --raw          # и транскрипты 01-raw
    python3 90-meta/scripts/wiki_search.py "sentry 1с" --strict   # без фолбэка на OR
    python3 90-meta/scripts/wiki_search.py similar 10-wiki/1c-postgres-indexes
    python3 90-meta/scripts/wiki_search.py stats

Перед чтением индекс догоняется сам: если файлов на диске больше, чем в базе, или
у них свежее mtime, делается инкрементальная пересборка (0.1 с). Отключается
`--no-refresh` или WIKI_SEARCH_NO_REFRESH=1. `stats` показывает расхождение, но
ничего не пересобирает.

Корпуса: wiki (10-wiki, 15-precedent, 20-people, 25-interactions, 40-projects,
42-repos, 50-drafts, 60-travel, 70-personal, 90-meta), chats (05-chats),
raw (01-raw — отдельно, транскрипты забивают выдачу).

Русская морфология: слова стеммятся snowball'ом (ru) и в документе, и в запросе —
иначе «индексы» не найдёт «индекс». Латиница стеммится только по регистру.

Индекс не коммитится: `.wiki-index/search.db` — производный артефакт.
"""

import argparse
import math
import os
import re
import sqlite3
import sys
import time

# Корень vault можно подменить: так тесты и ручные сборки работают на копии.
VAULT = (os.environ.get("WIKI_SEARCH_VAULT")
         or os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
DB_DIR = os.path.join(VAULT, ".wiki-index")
DB = os.path.join(DB_DIR, "search.db")

WIKI_DIRS = ("10-wiki", "15-precedent", "20-people", "25-interactions", "40-projects",
             "42-repos", "50-drafts", "60-travel", "70-personal", "90-meta")
RAW_DIRS = ("01-raw",)
CHAT_DIRS = ("05-chats",)
SKIP_DIRS = ("90-meta/templates", "90-meta/log", "60-travel/trips", "30-journal", "00-inbox",
             ".git", ".obsidian", ".trash", ".wiki-index")
SKIP_NAMES = ("index.md", "AGENTS.md", "README.md", "log.md", "status.md")

CYR = re.compile(r"[а-яё]")
TOKEN = re.compile(r"[а-яёa-z0-9]+")
LINK = re.compile(r"\[\[([^\]|#]+)")

try:
    import snowballstemmer
    _RU = snowballstemmer.stemmer("russian")
except ImportError:  # деградация без стеммера: точное совпадение слова
    _RU = None


def stem_word(word):
    if _RU is not None and CYR.match(word):
        return _RU.stemWord(word)
    return word


def tokens(text):
    return [stem_word(t) for t in TOKEN.findall(text.lower())]


def frontmatter(text):
    if not text.startswith("---"):
        return None, text
    end = text.find("\n---", 3)
    if end < 0:
        return None, text
    fields = {}
    for line in text[3:end].splitlines():
        m = re.match(r"^([A-Za-z_][\w-]*)\s*:\s*(.*)$", line)
        if m:
            fields[m.group(1)] = m.group(2).strip().strip('"').strip("'")
    return fields, text[end + 4:]


def headings(body):
    return " ".join(re.sub(r"^#+\s*", "", l) for l in body.splitlines()
                    if l.startswith("#"))


def plain(body):
    """Тело без разметки — чтобы индексировать слова, а не синтаксис."""
    body = re.sub(r"```.*?```", " ", body, flags=re.S)
    body = re.sub(r"\[\[([^\]|]+)\|([^\]]+)\]\]", r"\2", body)
    body = re.sub(r"\[\[([^\]]+)\]\]", r"\1", body)
    body = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", body)
    body = re.sub(r"[|>*_`#-]", " ", body)
    return body


def excerpt(body):
    for line in body.splitlines():
        s = line.strip()
        if not s or s.startswith(("---", "```", "#", "|", ">")):
            continue
        s = re.sub(r"\[\[([^\]|]+)\|?([^\]]*)\]\]", lambda m: m.group(2) or m.group(1), s)
        s = re.sub(r"[*_`]", "", s)
        return s[:200]
    return ""


def iter_files(dirs):
    for d in dirs:
        base = os.path.join(VAULT, d)
        if not os.path.isdir(base):
            continue
        for root, sub, files in os.walk(base):
            sub[:] = [x for x in sub if x not in (".git", ".obsidian", ".trash")]
            for name in sorted(files):
                if not name.endswith(".md") or name in SKIP_NAMES:
                    continue
                path = os.path.join(root, name)
                # Пути в индексе всегда posix: иначе на Windows relpath отдаёт
                # обратные слэши, corpus_of/SKIP_DIRS не срабатывают и 01-raw
                # попадает в корпус wiki.
                rel = os.path.relpath(path, VAULT).replace(os.sep, "/")
                if any(rel.startswith(s) for s in SKIP_DIRS):
                    continue
                yield rel, path


def corpus_of(rel):
    zone = rel.split("/")[0]
    if zone in CHAT_DIRS:
        return "chats"
    if zone in RAW_DIRS:
        return "raw"
    return "wiki"


def link_graph():
    """Исходящие и входящие wikilink'и вики-слоя — самые честные соседи.

    Ведро на запрос: 254 файла, ~0.05 с. Читается всегда свежая копия, поэтому
    правка ссылки видна сразу, без пересборки индекса.
    """
    texts = {}
    for rel, path in iter_files(WIKI_DIRS):
        try:
            with open(path, encoding="utf-8", errors="replace") as fh:
                texts[rel] = fh.read()
        except OSError:
            continue
    stem2path = {}
    for rel in texts:
        stem2path.setdefault(os.path.basename(rel)[:-3], []).append(rel)
    out = {rel: set() for rel in texts}
    back = {rel: set() for rel in texts}
    for rel, text in texts.items():
        for target in LINK.findall(text):
            stem = target.strip().rstrip("/").split("/")[-1]
            for other in stem2path.get(stem, ()):
                if other != rel:
                    out[rel].add(other)
                    back[other].add(rel)
    return out, back


def connect():
    os.makedirs(DB_DIR, exist_ok=True)
    con = sqlite3.connect(DB)
    con.execute("PRAGMA journal_mode=WAL")
    # Запрос не должен падать, если хук прямо сейчас пересобирает индекс.
    con.execute("PRAGMA busy_timeout=3000")
    con.executescript("""
        CREATE TABLE IF NOT EXISTS docs(
            id INTEGER PRIMARY KEY,
            path TEXT UNIQUE NOT NULL,
            corpus TEXT NOT NULL,
            name TEXT,
            updated TEXT,
            mtime REAL,
            size INTEGER,
            excerpt TEXT
        );
        CREATE VIRTUAL TABLE IF NOT EXISTS search USING fts5(
            doc_id UNINDEXED,
            name, tags, headings, kw, body,
            tokenize='unicode61 remove_diacritics 2'
        );
        CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT);
    """)
    return con


def rebuild(full=False, allow_no_stem=False, quiet=False):
    if _RU is None and not allow_no_stem:
        # Индекс без стемминга ломает русскую морфологию незаметно для юзера:
        # лучше оставить старый рабочий индекс и сказать об этом вслух.
        print("no snowballstemmer: пересборка отменена, иначе русский поиск деградирует "
              "до точного совпадения слова. Поставь python3-snowballstemmer "
              "(или --no-stem, если деградация осознанная).", file=sys.stderr)
        return 2
    con = connect()
    if full:
        con.executescript("DELETE FROM docs; DELETE FROM search;")
        con.commit()
    known = {row[0]: (row[1], row[2]) for row in
             con.execute("SELECT path, mtime, size FROM docs")}
    seen = set()
    added = updated = 0
    t0 = time.time()

    targets = [(rel, path) for rel, path in iter_files(WIKI_DIRS + CHAT_DIRS + RAW_DIRS)]
    for rel, path in targets:
        try:
            st = os.stat(path)
        except OSError:
            continue
        seen.add(rel)
        prev = known.get(rel)
        if prev and abs(prev[0] - st.st_mtime) < 1 and prev[1] == st.st_size:
            continue
        with open(path, encoding="utf-8", errors="replace") as fh:
            text = fh.read()
        fm, body = frontmatter(text)
        fm = fm or {}
        corpus = corpus_of(rel)
        name = fm.get("name") or os.path.basename(rel)[:-3]
        row = con.execute("SELECT id FROM docs WHERE path=?", (rel,)).fetchone()
        if row:
            doc_id = row[0]
            updated += 1
            con.execute("DELETE FROM search WHERE doc_id=?", (doc_id,))
            con.execute("""UPDATE docs SET corpus=?, name=?, updated=?, mtime=?, size=?, excerpt=?
                           WHERE id=?""",
                        (corpus, name, fm.get("updated", ""), st.st_mtime, st.st_size,
                         excerpt(body), doc_id))
        else:
            added += 1
            cur = con.execute("""INSERT INTO docs(path, corpus, name, updated, mtime, size, excerpt)
                                 VALUES(?,?,?,?,?,?,?)""",
                              (rel, corpus, name, fm.get("updated", ""), st.st_mtime,
                               st.st_size, excerpt(body)))
            doc_id = cur.lastrowid
        con.execute("""INSERT INTO search(doc_id, name, tags, headings, kw, body)
                       VALUES(?,?,?,?,?,?)""",
                    (doc_id,
                     " ".join(tokens(name)),
                     " ".join(tokens(fm.get("tags", "") + " " + fm.get("aliases", ""))),
                     " ".join(tokens(headings(body))),
                     " ".join(tokens(fm.get("kw", ""))),
                     " ".join(tokens(plain(body)))))

    stale = [rel for rel in known if rel not in seen]
    for rel in stale:
        row = con.execute("SELECT id FROM docs WHERE path=?", (rel,)).fetchone()
        if row:
            con.execute("DELETE FROM search WHERE doc_id=?", (row[0],))
            con.execute("DELETE FROM docs WHERE id=?", (row[0],))
    con.execute("INSERT OR REPLACE INTO meta VALUES('built', ?)", (f"{time.time():.3f}",))
    con.commit()
    total = con.execute("SELECT COUNT(*) FROM docs").fetchone()[0]
    if not quiet:
        print(f"проиндексировано: добавлено {added}, обновлено {updated}, "
              f"удалено {len(stale)}, всего {total} — {time.time() - t0:.1f}s")
    return 0


def corpus_state():
    """Сколько файлов вообще индексируемо и самый свежий mtime среди них."""
    files = 0
    newest = 0.0
    for _rel, path in iter_files(WIKI_DIRS + CHAT_DIRS + RAW_DIRS):
        try:
            st = os.stat(path)
        except OSError:
            continue
        files += 1
        if st.st_mtime > newest:
            newest = st.st_mtime
    return files, newest


def stale_info(con):
    """(устарел?, файлов на диске, самый свежий mtime, время сборки)."""
    files, newest = corpus_state()
    row = con.execute("SELECT value FROM meta WHERE key='built'").fetchone()
    # Дробное время сборки: int-секунды давали ложное «отстаёт» на файлах,
    # записанных в ту же секунду.
    built = float(row[0]) if row else 0.0
    indexed = con.execute("SELECT COUNT(*) FROM docs").fetchone()[0]
    stale = files != indexed or newest > built
    return stale, files, newest, built


def ensure_fresh(con, quiet=False):
    """Догоняет индекс перед чтением: правка без коммита не должна теряться.

    Возвращает True, если индекс пришлось пересобрать. Без стеммера пересборку
    не делает (иначе молча теряется русская морфология), только предупреждает.
    """
    if os.environ.get("WIKI_SEARCH_NO_REFRESH"):
        return False
    indexed = con.execute("SELECT COUNT(*) FROM docs").fetchone()[0]
    if not indexed:
        if _RU is None:
            print("no snowballstemmer: индекс не собран, пересборка отменена "
                  "(поставь python3-snowballstemmer)", file=sys.stderr)
            return False
        files, _ = corpus_state()
        if not quiet:
            print(f"индекс собирается впервые: {files} файлов, ~10 с", file=sys.stderr)
        return rebuild(full=True, quiet=True) == 0
    stale, files, _newest, _built = stale_info(con)
    if not stale:
        return False
    if _RU is None:
        print("no snowballstemmer: индекс устарел, но пересборка отменена — "
              "русская морфология сломается; запусти: make search", file=sys.stderr)
        return False
    try:
        rebuild(quiet=True)
    except sqlite3.OperationalError:
        time.sleep(1)
        try:
            rebuild(quiet=True)
        except sqlite3.OperationalError:
            print("индекс занят: поиск идёт по старой копии", file=sys.stderr)
            return False
    if not quiet:
        print(f"индекс отставал ({files} файлов на диске) — обновлён", file=sys.stderr)
    return True


def build_query(terms, op):
    return op.join(f'"{t}"*' for t in terms)


def search(q, limit=10, include_raw=False, mode="auto"):
    con = connect()
    ensure_fresh(con)
    if con.execute("SELECT COUNT(*) FROM docs").fetchone()[0] == 0:
        print("индекс пуст: сначала wiki_search.py index", file=sys.stderr)
        return 1
    terms = tokens(q)
    if not terms:
        print("пустой запрос", file=sys.stderr)
        return 1
    corpus_filter = ""
    if not include_raw:
        corpus_filter = " AND d.corpus != 'raw'"
    sql = f"""
        SELECT d.path, d.name, d.updated, d.corpus, d.excerpt,
               bm25(search, 0.0, 5.0, 3.0, 2.0, 2.0, 1.0) AS score
        FROM search JOIN docs d ON d.id = search.doc_id
        WHERE search MATCH ?{corpus_filter}
        ORDER BY score LIMIT ?"""
    if mode == "strict":
        ops = ("AND",)
    elif mode == "any":
        ops = ("OR",)
    else:
        ops = ("AND", "OR")
    rows = []
    used_or = False
    for op in ops:
        try:
            rows = con.execute(sql, (build_query(terms, op), limit)).fetchall()
        except sqlite3.OperationalError:
            rows = []
        if rows:
            used_or = op == "OR"
            break
    if rows and used_or and mode == "auto":
        print("строгий запрос пуст — показано частичное совпадение (OR); "
              "чтобы отключить: --strict", file=sys.stderr)
    if not rows:
        print(f"ничего не найдено: {q}")
        return 0
    for path, name, updated, corpus, exc, score in rows:
        tag = "" if corpus == "wiki" else f" [{corpus}]"
        print(f"{-score:6.2f}  {path}{tag}")
        print(f"        {name}")
        if exc:
            print(f"        {exc[:140]}")
    return 0


def similar(slug, limit=6):
    con = connect()
    ensure_fresh(con)
    row = con.execute("SELECT id, path, name FROM docs WHERE path LIKE ?",
                      (slug.rstrip("/") + "%",)).fetchone()
    if not row:
        print(f"нет страницы: {slug}", file=sys.stderr)
        return 1
    doc_id, doc_path, doc_name = row
    docs = con.execute("""
        SELECT d.path, d.name, s.tags, s.kw
        FROM docs d JOIN search s ON s.doc_id = d.id
        WHERE d.corpus = 'wiki'""").fetchall()
    by_path = {d[0]: d for d in docs}
    if len(docs) < 2 or doc_path not in by_path:
        return 0
    total = len(docs)
    df_cache = {}

    def df_of(col, stem):
        key = (col, stem)
        if key not in df_cache:
            df_cache[key] = con.execute(
                f"SELECT COUNT(*) FROM search WHERE {col} MATCH ?",
                (f'"{stem}"',)).fetchone()[0]
        return df_cache[key]

    def idf(count):
        return math.log((total + 1) / (count + 1)) if count else 0.0

    def words(text):
        return {w for w in (text or "").split() if len(w) >= 3}

    picked = []
    seen = {doc_path}

    # 1. Wikilink'и: сначала двусторонние, потом исходящие, потом обратные.
    #    Ссылку ставит автор заметки, поэтому это единственный сигнал, который
    #    не путает «конспект доклада» с темой.
    out, back = link_graph()
    for group in (out.get(doc_path, set()) & back.get(doc_path, set()),
                  out.get(doc_path, set()),
                  back.get(doc_path, set())):
        for other in sorted(group):
            if other in seen or other not in by_path:
                continue
            seen.add(other)
            picked.append((other, "[ссылка]"))
            if len(picked) >= limit:
                break
        if len(picked) >= limit:
            break

    # 2. Общие теги и kw с весом idf: тег отвечает за область, kw — за тему.
    if len(picked) < limit:
        src = by_path[doc_path]
        src_tags, src_kw = words(src[2]), words(src[3])
        rest = []
        for path, _name, tags, kw in docs:
            if path in seen:
                continue
            score = 0.0
            for w in src_tags & words(tags):
                score += idf(df_of("tags", w))
            for w in src_kw & words(kw):
                score += 1.3 * idf(df_of("kw", w))
            if score > 0:
                rest.append((score, path))
        rest.sort(reverse=True)
        for _score, path in rest:
            if len(picked) >= limit:
                break
            picked.append((path, "[теги]"))

    if not picked:
        print(f"похожих на {doc_name} не нашлось: ни ссылок, ни общих тегов")
        return 0
    print(f"похожие на {doc_name}:")
    for path, why in picked:
        print(f"  {why:9s} {path} — {by_path[path][1]}")
    return 0


def stats():
    con = connect()
    total = con.execute("SELECT COUNT(*) FROM docs").fetchone()[0]
    per = con.execute("SELECT corpus, COUNT(*) FROM docs GROUP BY corpus").fetchall()
    built = con.execute("SELECT value FROM meta WHERE key='built'").fetchone()
    print(f"документов: {total}")
    for corpus, n in per:
        print(f"  {corpus:8s} {n}")
    print(f"стеммер: {'snowball ru' if _RU is not None else 'НЕТ — морфология не работает'}")
    if built:
        print(f"собран: {time.strftime('%Y-%m-%d %H:%M', time.localtime(int(float(built[0]))))}")
    stale, files, newest, _built = stale_info(con)
    if not total:
        print("индекс: не собран — запусти make search")
    elif stale:
        when = time.strftime('%Y-%m-%d %H:%M', time.localtime(newest)) if newest else "?"
        print(f"индекс отстаёт: файлов на диске {files}, в индексе {total}, "
              f"свежайший {when}")
        print("  догонится сам при следующем запросе или: make search")
    else:
        print("индекс актуален")
    return 0


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd")
    p_index = sub.add_parser("index")
    p_index.add_argument("--full", action="store_true")
    p_index.add_argument("--no-stem", action="store_true",
                         help="разрешить сборку без snowballstemmer (русская морфология ломается)")
    p_q = sub.add_parser("query")
    p_q.add_argument("q")
    p_q.add_argument("-n", type=int, default=8)
    p_q.add_argument("--raw", action="store_true", help="искать и в 01-raw")
    g_q = p_q.add_mutually_exclusive_group()
    g_q.add_argument("--strict", action="store_true",
                     help="только строгое совпадение (AND), без фолбэка на OR")
    g_q.add_argument("--any", action="store_true",
                     help="любое из слов (OR), без строгого прохода")
    p_q.add_argument("--no-refresh", action="store_true",
                     help="не догонять индекс перед поиском")
    p_sim = sub.add_parser("similar")
    p_sim.add_argument("slug")
    p_sim.add_argument("--no-refresh", action="store_true",
                       help="не догонять индекс перед поиском")
    sub.add_parser("stats")

    argv = sys.argv[1:]
    if not argv:
        ap.print_help()
        return 1
    if argv[0] not in ("index", "query", "similar", "stats"):
        argv = ["query"] + argv
    args = ap.parse_args(argv)

    if args.cmd == "index":
        if getattr(args, "no_stem", False):
            print("внимание: --no-stem — русская морфология работать не будет", file=sys.stderr)
        return rebuild(args.full, args.no_stem)
    if args.cmd == "query":
        if args.no_refresh:
            os.environ["WIKI_SEARCH_NO_REFRESH"] = "1"
        mode = "strict" if args.strict else "any" if args.any else "auto"
        return search(args.q, args.n, include_raw=args.raw, mode=mode)
    if args.cmd == "similar":
        if args.no_refresh:
            os.environ["WIKI_SEARCH_NO_REFRESH"] = "1"
        return similar(args.slug)
    return stats()


if __name__ == "__main__":
    sys.exit(main())
