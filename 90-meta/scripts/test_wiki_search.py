#!/usr/bin/env python3
"""Тесты BM25-поиска: корпуса, инкрементальность, строгость, свежесть, соседи.

    make test            # или: python 90-meta/scripts/test_wiki_search.py

Каждый тест собирает одноразовый vault во временном каталоге внутри
`.wiki-index/` (он в .gitignore) и гоняет `wiki_search.py` подпроцессом с
WIKI_SEARCH_VAULT, чтобы не трогать настоящий индекс.
"""

import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
VAULT = os.path.dirname(os.path.dirname(HERE))
SCRIPT = os.path.join(HERE, "wiki_search.py")

try:
    import snowballstemmer  # noqa: F401
    HAVE_STEMMER = True
except ImportError:
    HAVE_STEMMER = False


def note(name, body, tags=None, kw=None):
    fm = ["---", "name: " + name]
    if tags:
        fm.append("tags: [" + ", ".join(tags) + "]")
    if kw:
        fm.append("kw: [" + ", ".join(kw) + "]")
    fm.append("---")
    return "\n".join(fm) + "\n\n" + body + "\n"


@unittest.skipUnless(HAVE_STEMMER, "нет snowballstemmer: индекс не собирается")
class SearchTest(unittest.TestCase):
    def setUp(self):
        base = os.environ.get("WIKI_SEARCH_TEST_TMP") or os.path.join(VAULT, ".wiki-index", "test-tmp")
        os.makedirs(base, exist_ok=True)
        self.root = tempfile.mkdtemp(prefix="vault-", dir=base)
        self.addCleanup(shutil.rmtree, self.root, True)

    # --- helpers -------------------------------------------------------
    def write(self, rel, text):
        path = os.path.join(self.root, rel.replace("/", os.sep))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)

    def run_cli(self, *args, expect=0, env=None):
        full_env = dict(os.environ, WIKI_SEARCH_VAULT=self.root, PYTHONIOENCODING="utf-8")
        full_env.pop("WIKI_SEARCH_NO_REFRESH", None)
        if env:
            full_env.update(env)
        proc = subprocess.run([sys.executable, SCRIPT] + list(args),
                              capture_output=True, text=True, encoding="utf-8", env=full_env)
        self.assertEqual(proc.returncode, expect, proc.stdout + proc.stderr)
        return proc

    def db(self):
        return sqlite3.connect(os.path.join(self.root, ".wiki-index", "search.db"))

    # --- корпуса и пропуски --------------------------------------------
    def test_corpora_and_skips(self):
        self.write("10-wiki/alpha.md", note("Альфа", "текст про индексы"))
        self.write("01-raw/raw1.md", note("Сырьё", "текст про индексы"))
        self.write("90-meta/templates/tpl.md", note("Шаблон", "текст"))
        self.write("30-journal/2026-01-01.md", note("Дневник", "текст"))
        self.write("00-inbox/scratch.md", note("Входящее", "текст"))
        self.run_cli("index", "--full")
        con = self.db()
        corpora = dict(con.execute("SELECT corpus, COUNT(*) FROM docs GROUP BY corpus"))
        self.assertEqual(corpora, {"wiki": 1, "raw": 1})
        paths = [row[0] for row in con.execute("SELECT path FROM docs")]
        self.assertTrue(all("\\" not in p for p in paths), paths)
        for bad in ("90-meta/templates", "30-journal", "00-inbox"):
            self.assertFalse([p for p in paths if p.startswith(bad)], paths)

    def test_raw_filtered_by_default(self):
        self.write("10-wiki/alpha.md", note("Альфа", "слово якорь в заметке"))
        self.write("01-raw/raw1.md", note("Сырьё", "слово якорь в транскрипте"))
        self.run_cli("index", "--full")
        out = self.run_cli("якорь", "-n", "5").stdout
        self.assertIn("10-wiki/alpha.md", out)
        self.assertNotIn("01-raw/", out)
        out = self.run_cli("якорь", "-n", "5", "--raw").stdout
        self.assertIn("01-raw/raw1.md", out)
        self.assertIn("[raw]", out)

    # --- инкрементальность ---------------------------------------------
    def test_incremental_add_edit_delete(self):
        self.write("10-wiki/alpha.md", note("Альфа", "первая версия"))
        self.run_cli("index", "--full")
        self.write("10-wiki/beta.md", note("Бета", "банановый маркер"))
        self.assertIn("добавлено 1", self.run_cli("index").stdout)
        self.assertIn("10-wiki/beta.md", self.run_cli("банановый").stdout)
        self.write("10-wiki/beta.md", note("Бета", "банановый маркер и правка"))
        self.assertIn("обновлено 1", self.run_cli("index").stdout)
        os.remove(os.path.join(self.root, "10-wiki", "beta.md"))
        self.assertIn("удалено 1", self.run_cli("index").stdout)
        self.assertIn("ничего не найдено", self.run_cli("банановый").stdout)

    # --- строгость запроса ---------------------------------------------
    def test_strict_modes(self):
        self.write("10-wiki/alpha.md", note("Альфа", "только альфа"))
        self.write("10-wiki/beta.md", note("Бета", "только бета"))
        self.run_cli("index", "--full")
        auto = self.run_cli("альфа бета")
        self.assertIn("частичное совпадение", auto.stderr)
        self.assertIn("10-wiki/", auto.stdout)
        strict = self.run_cli("альфа бета", "--strict")
        self.assertIn("ничего не найдено", strict.stdout)
        self.assertNotIn("частичное", strict.stderr)
        self.assertTrue(self.run_cli("альфа бета", "--any").stdout.strip())

    def test_empty_query_fails(self):
        self.write("10-wiki/alpha.md", note("Альфа", "текст"))
        self.run_cli("index", "--full")
        proc = self.run_cli("!!!", expect=1)
        self.assertIn("пустой запрос", proc.stderr)

    # --- свежесть -------------------------------------------------------
    def test_freshness_without_manual_reindex(self):
        self.write("10-wiki/alpha.md", note("Альфа", "старый текст"))
        self.run_cli("index", "--full")
        self.write("10-wiki/alpha.md", note("Альфа", "старый текст и свежий маркер"))
        # Сначала проверяем именно устаревший индекс: --no-refresh ничего не догоняет.
        stale = self.run_cli("свежий", "--no-refresh")
        self.assertNotIn("10-wiki/alpha.md", stale.stdout)
        self.assertIn("ничего не найдено", stale.stdout)
        # Теперь без флага: запрос сам догоняет индекс и находит правку.
        fresh = self.run_cli("свежий")
        self.assertIn("10-wiki/alpha.md", fresh.stdout)
        self.assertIn("индекс отставал", fresh.stderr)

    def test_first_query_builds_index(self):
        self.write("10-wiki/alpha.md", note("Альфа", "первый запуск"))
        db = os.path.join(self.root, ".wiki-index", "search.db")
        self.assertFalse(os.path.exists(db))
        proc = self.run_cli("первый")
        self.assertIn("собирается впервые", proc.stderr)
        self.assertIn("10-wiki/alpha.md", proc.stdout)
        self.assertTrue(os.path.exists(db))

    def test_stats_reports_drift(self):
        self.write("10-wiki/alpha.md", note("Альфа", "текст"))
        self.run_cli("index", "--full")
        self.assertIn("индекс актуален", self.run_cli("stats").stdout)
        self.write("10-wiki/beta.md", note("Бета", "текст"))
        self.assertIn("отстаёт", self.run_cli("stats").stdout)

    # --- соседи ---------------------------------------------------------
    def test_similar_prefers_links(self):
        self.write("10-wiki/hub.md", note("Хаб", "см. [[related]]", kw=["postgres"]))
        self.write("10-wiki/related.md", note("Родственник", "про то же"))
        self.write("10-wiki/noise.md", note("Шум", "посторонний текст", kw=["postgres"]))
        for i in range(3):
            self.write("10-wiki/filler%d.md" % i, note("Заполнитель %d" % i, "другое", tags=["travel"]))
        self.run_cli("index", "--full")
        out = self.run_cli("similar", "10-wiki/hub").stdout
        self.assertIn("10-wiki/related.md", out)
        self.assertIn("10-wiki/noise.md", out)
        self.assertLess(out.index("10-wiki/related.md"), out.index("10-wiki/noise.md"))

    def test_similar_falls_back_to_tags(self):
        self.write("10-wiki/hub.md", note("Хаб", "без ссылок", tags=["database"], kw=["postgres"]))
        self.write("10-wiki/dbish.md", note("База", "про базу", tags=["database"], kw=["postgres"]))
        self.write("10-wiki/other.md", note("Другое", "про другое", tags=["travel"], kw=["rome"]))
        self.run_cli("index", "--full")
        out = self.run_cli("similar", "10-wiki/hub").stdout
        self.assertIn("10-wiki/dbish.md", out)
        self.assertNotIn("10-wiki/other.md", out)

    def test_similar_unknown_page(self):
        self.write("10-wiki/alpha.md", note("Альфа", "текст"))
        self.run_cli("index", "--full")
        proc = self.run_cli("similar", "10-wiki/nope", expect=1)
        self.assertIn("нет страницы", proc.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
