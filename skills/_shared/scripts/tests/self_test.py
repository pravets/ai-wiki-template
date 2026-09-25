#!/usr/bin/env python3
"""Self-test for pdf_layer_check.py — run it to prove the helper works here.

Checks three layers:
  1. detector branches  - quality metrics and verdicts on synthetic text
  2. PDF fixtures       - digital / scan / mixed files, end-to-end via the CLI
  3. OCR bridge         - rasterize a scanned page and read it with tesseract

Requirements: poppler (pdfinfo, pdftotext, pdfimages, pdftoppm) — hard requirement.
Optional: Pillow (for scan fixtures), tesseract with the `rus` language pack
(for the bridge check). Missing optional pieces are reported as SKIP, not failure.

Usage:
    python3 self_test.py
    python3 self_test.py -v

Exit codes: 0 = all checks passed, 1 = a check failed, 2 = environment unusable.
"""
import argparse
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
HELPER = os.path.join(os.path.dirname(HERE), "pdf_layer_check.py")

CLEAN_TEXT = (
    "Поставщик ООО Техномарин итого сумма рублей по документу за период "
    "подпись печать расшифровка "
) * 2


class Runner:
    def __init__(self, verbose=False):
        self.verbose = verbose
        self.passed = 0
        self.failed = 0
        self.skipped = 0

    def check(self, name, ok, detail=""):
        if ok:
            self.passed += 1
            print(f"  ✔ {name}")
        else:
            self.failed += 1
            print(f"  ✘ {name}" + (f"\n      {detail}" if detail else ""))
        if self.verbose and ok and detail:
            print(f"      {detail}")

    def skip(self, name, why):
        self.skipped += 1
        print(f"  – {name} (пропущено: {why})")

    def summary(self):
        print(f"\nитог: успешно {self.passed}, провалено {self.failed}, пропущено {self.skipped}")
        if self.failed:
            print("ЕСТЬ ПРОВАЛЫ — хелпер ведёт себя не так, как заявлено.")
        elif self.skipped:
            print("Частичный прогон: часть проверок пропущена (см. выше).")
        else:
            print("Все проверки пройдены.")
        return 0 if self.failed == 0 else 1


def load_helper():
    spec = importlib.util.spec_from_file_location("pdf_layer_check", HELPER)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"не удалось загрузить хелпер: {HELPER}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def run(cmd):
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return p.stdout or ""


def poppler_ready():
    return all(shutil.which(t) for t in ("pdfinfo", "pdftotext", "pdfimages", "pdftoppm"))


def check_detector(r, mod):
    print("\n1. Ветки детектора (синтетика)")
    cases = [
        # name, text, has_full_page_image, expected verdict
        ("чистый текст", CLEAN_TEXT, False, "text-layer"),
        ("битые глифы U+FFFD", "\ufffd" * 60, False, "needs-ocr"),
        ("cid-плейсхолдеры (шрифт без Unicode)", "(cid:12)" * 8, False, "needs-ocr"),
        ("согласный мусор (мусорный OCR-слой)", "прстклмн встрджк нклмнт сртдкм " * 3, False, "ambiguous"),
        ("водяной знак (повторы)", "КОПИЯ\n" * 20, False, "ambiguous"),
        ("пустая страница", "", False, "needs-ocr"),
        ("чистый текст поверх картинки (скан со слоем)", CLEAN_TEXT, True, "text-layer"),
    ]
    for name, text, has_img, expected in cases:
        metrics = mod.analyse(text)
        verdict, notes = mod.verdict(metrics, has_img, 40)
        r.check(
            f"{name} → {expected}",
            verdict == expected,
            f"получено {verdict}; метрики: мусор={metrics['garbage_ratio']}, "
            f"подозр={metrics['suspicious_token_ratio']}, повтор={metrics['repeated_line_ratio']}",
        )

    # regression guard: pdftotext ends each page with a form feed; it is a page
    # separator, not garbage, and must not inflate the garbage ratio
    m = mod.analyse("Итого: 1234.56 руб.\n\f")
    r.check("form feed не считается мусором (регресс)", m["garbage_ratio"] == 0.0,
            f"мусор={m['garbage_ratio']}")


def check_fixture_properties(r, files):
    """Verify independently (poppler) that each fixture is what it claims to be."""
    a, c = files.get("A_digital"), files.get("C_mixed")
    b = files.get("B_scan")

    text1 = run(["pdftotext", "-f", "1", "-l", "1", "-layout", "-enc", "UTF-8", a, "-"]).strip()
    r.check("фикстура A: на стр.1 есть текстовый слой", len(text1) > 40, f"получено {len(text1)} симв.")
    r.check("фикстура A: слой точен (OOO остаётся буквами)", "OOO Tekhnomarin" in text1, text1[:80])
    imgs_a = [ln for ln in run(["pdfimages", "-list", a]).splitlines()[2:] if ln.strip()]
    r.check("фикстура A: картинок нет", not imgs_a, f"найдено {len(imgs_a)}")

    if b:
        text_b = run(["pdftotext", "-f", "1", "-l", "1", b, "-"]).strip()
        r.check("фикстура B: текстового слоя нет", len(text_b) == 0, f"получено {len(text_b)} симв.")
        imgs_b = [ln for ln in run(["pdfimages", "-list", b]).splitlines()[2:] if ln.strip()]
        r.check("фикстура B: страницы — полноразмерные картинки", len(imgs_b) == 2, f"картинок {len(imgs_b)}")

    if c:
        c1 = run(["pdftotext", "-f", "1", "-l", "1", c, "-"]).strip()
        c2 = run(["pdftotext", "-f", "2", "-l", "2", c, "-"]).strip()
        r.check("фикстура C: стр.1 цифровая", len(c1) > 40, f"{len(c1)} симв.")
        r.check("фикстура C: стр.2 без слоя (скан)", len(c2) == 0, f"{len(c2)} симв.")


def check_cli(r, files, expected):
    """Run the real CLI with --json and compare per-page verdicts."""
    for name, path in sorted(files.items()):
        out = run([sys.executable, HELPER, path, "--json"])
        try:
            data = json.loads(out)
        except json.JSONDecodeError:
            r.check(f"CLI {name}: валидный JSON", False, out[:200])
            continue
        got = [p["verdict"] for p in data["pages"]]
        r.check(f"CLI {name}: вердикты {expected[name]}", got == expected[name], f"получено {got}")


def check_bridge(r, files, workdir):
    """Rasterize the scanned page of the mixed fixture and read it with tesseract."""
    mixed = files.get("C_mixed")
    if not mixed:
        r.skip("мост растеризация → tesseract", "нет фикстуры со сканом (нужен Pillow)")
        return
    if not shutil.which("tesseract"):
        r.skip("мост растеризация → tesseract", "tesseract не установлен")
        return
    langs = run(["tesseract", "--list-langs"]).split()
    if "rus" not in langs:
        r.skip("мост растеризация → tesseract", "нет языкового пакета rus")
        return

    prefix = os.path.join(workdir, "page2")
    subprocess.run(["pdftoppm", "-r", "300", "-f", "2", "-l", "2", "-png", mixed, prefix],
                   capture_output=True, timeout=180)
    produced = [f for f in os.listdir(workdir) if f.startswith("page2") and f.endswith(".png")]
    if not produced:
        r.check("мост: страница растеризована", False, "pdftoppm не создал PNG")
        return
    r.check("мост: страница растеризована", True, f"{len(produced)} файл(ов)")

    png = os.path.join(workdir, sorted(produced)[0])
    ocr = run(["tesseract", png, "-", "-l", "rus+eng"]).strip()
    r.check("мост: tesseract прочитал скан", "1234.56" in ocr and "2026-0042" in ocr,
            f"распознано: {ocr[:120]}")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-v", "--verbose", action="store_true")
    a = ap.parse_args()

    print("Самопроверка pdf_layer_check.py", flush=True)
    if not poppler_ready():
        print("error: нужны инструменты poppler (pdfinfo, pdftotext, pdfimages, pdftoppm).\n"
              "  Debian/Ubuntu: sudo apt-get install -y poppler-utils", file=sys.stderr)
        return 2

    r = Runner(a.verbose)
    mod = load_helper()

    check_detector(r, mod)

    print("\n2. Фикстуры и сквозная проверка")
    with tempfile.TemporaryDirectory(prefix="pdf_layer_selftest_") as tmp:
        try:
            import PIL  # noqa: F401
            have_pil = True
        except ImportError:
            have_pil = False
            print("  – фикстуры со сканами (пропущено: Pillow не установлен)")

        sys.path.insert(0, HERE)
        import make_fixtures
        files = make_fixtures.build_fixtures(tmp, with_scans=have_pil)
        print(f"  собраны: {', '.join(sorted(os.path.basename(p) for p in files.values()))}")

        check_fixture_properties(r, files)

        expected = {"A_digital": ["text-layer", "text-layer"]}
        if have_pil:
            expected["B_scan"] = ["needs-ocr", "needs-ocr"]
            expected["C_mixed"] = ["text-layer", "needs-ocr"]
        check_cli(r, files, expected)

        print("\n3. Мост растеризация → OCR")
        check_bridge(r, files, tmp)

    return r.summary()


if __name__ == "__main__":
    sys.exit(main())
