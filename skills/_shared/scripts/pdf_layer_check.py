#!/usr/bin/env python3
"""Per-page verdict on a PDF's text layer: usable, needs OCR, or ambiguous.

Why: the cheapest and most accurate OCR pass is the one you do not run. A digital
PDF already carries its text, exactly and without recognition errors. But a text
layer can also be garbage (a scan with a badly embedded OCR layer, fonts without
Unicode mapping, watermark-only text), and deciding for the whole file is wrong —
mixed documents exist, where some pages are digital and some are scans.

Uses poppler tools only (pdfinfo, pdftotext, pdfimages): no Python dependencies.

Usage:
    pdf_layer_check.py doc.pdf
    pdf_layer_check.py doc.pdf --json
    pdf_layer_check.py doc.pdf --min-chars 60

Verdicts per page:
    text-layer  - usable layer; do NOT run OCR on this page
    needs-ocr   - no usable text (scan or broken layer); rasterize + OCR
    ambiguous   - text present but questionable; inspect before trusting

Exit code: 0 (informational), 2 on unusable input.
"""
import argparse
import json
import re
import shutil
import subprocess
import sys

VOWELS = set("аеёиоуыэюяaeiouy")
# Artifacts of a broken layer: replacement char, private use area, box glyphs,
# CID placeholders that pdftotext emits when a font lacks a Unicode mapping.
GARBAGE_CHARS = set("\ufffd\u25a1\u25a0\u25af")
CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
CID_RE = re.compile(r"\(cid:\d+\)")


def run(cmd):
    """Run a poppler command, return stdout ('' on failure)."""
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return p.stdout or ""


def need_tools():
    missing = [t for t in ("pdfinfo", "pdftotext") if not shutil.which(t)]
    if missing:
        print(
            "error: не найдены инструменты poppler: "
            + ", ".join(missing)
            + " (нужен пакет poppler-utils)",
            file=sys.stderr,
        )
        sys.exit(2)


def page_count(path):
    out = run(["pdfinfo", path])
    m = re.search(r"^Pages:\s+(\d+)", out, re.M)
    return int(m.group(1)) if m else 0


def page_sizes(path, pages):
    """{page_no: (width_pt, height_pt)} from pdfinfo -f/-l."""
    out = run(["pdfinfo", "-f", "1", "-l", str(pages), path])
    sizes = {}
    for m in re.finditer(r"^Page\s+(\d+)\s+size:\s+([\d.]+)\s+x\s+([\d.]+)", out, re.M):
        sizes[int(m.group(1))] = (float(m.group(2)), float(m.group(3)))
    return sizes


def page_images(path):
    """{page_no: [(w_px, h_px), ...]} from pdfimages -list (empty if tool missing)."""
    if not shutil.which("pdfimages"):
        return {}
    images = {}
    for line in run(["pdfimages", "-list", path]).splitlines()[2:]:
        parts = line.split()
        if len(parts) < 5 or not parts[0].isdigit():
            continue
        try:
            page, width, height = int(parts[0]), int(parts[3]), int(parts[4])
        except ValueError:
            continue
        images.setdefault(page, []).append((width, height))
    return images


def page_text(path, page):
    """Text of one page, layout-preserving (keeps columns from being reflowed)."""
    return run(["pdftotext", "-f", str(page), "-l", str(page), "-layout", "-enc", "UTF-8", path, "-"])


def analyse(text):
    """Quality metrics for a page's extracted text."""
    # pdftotext terminates each page with a form feed (and may emit vertical tab):
    # these are page separators, not garbage — strip before measuring quality.
    text = text.replace("\f", "").replace("\x0b", "")
    stripped = text.strip()
    chars = len(re.sub(r"\s", "", stripped))
    # A (cid:NNN) placeholder means a glyph with no Unicode mapping: count the
    # characters such a placeholder occupies, since none of them carry content.
    cid_chars = sum(len(m) for m in CID_RE.findall(text))
    cids = len(CID_RE.findall(text))
    bad_chars = sum(1 for ch in text if ch in GARBAGE_CHARS or CONTROL_RE.match(ch))
    garbage_ratio = (bad_chars + cid_chars) / chars if chars else 0.0

    tokens = stripped.split()
    suspicious = sum(
        1
        for t in tokens
        if (len(t) >= 3 and not (set(t.lower()) & VOWELS) and t.isalpha())
        or (len(t) == 1 and not t.isalnum())
    )
    suspicious_ratio = suspicious / len(tokens) if tokens else 0.0

    lines = [ln.strip() for ln in stripped.splitlines() if ln.strip()]
    repeated_ratio = 0.0
    if len(lines) > 3:
        repeated_ratio = 1 - (len(set(lines)) / len(lines))

    lengths = sorted(len(ln) for ln in lines)
    median_len = lengths[len(lengths) // 2] if lengths else 0

    return {
        "chars": chars,
        "lines": len(lines),
        "tokens": len(tokens),
        "cid_placeholders": cids,
        "garbage_ratio": round(garbage_ratio, 3),
        "suspicious_token_ratio": round(suspicious_ratio, 3),
        "repeated_line_ratio": round(repeated_ratio, 3),
        "median_line_len": median_len,
    }


def verdict(metrics, has_full_page_image, min_chars):
    """Decide what to do with this page. Returns (verdict, notes)."""
    notes = []
    if metrics["chars"] < min_chars:
        notes.append("текста меньше порога" + (" (страница-скан)" if has_full_page_image else ""))
        return "needs-ocr", notes
    if metrics["garbage_ratio"] > 0.15:
        notes.append(f"много битых глифов (garbage={metrics['garbage_ratio']})")
        return "needs-ocr", notes
    if metrics["suspicious_token_ratio"] > 0.35:
        notes.append(f"подозрительные токены ({metrics['suspicious_token_ratio']}) — похоже на мусорный слой")
        return "ambiguous", notes
    if metrics["repeated_line_ratio"] >= 0.5:
        notes.append("много повторяющихся строк — возможен водяной знак вместо контента")
        return "ambiguous", notes
    if has_full_page_image:
        notes.append("слой поверх полноразмерной картинки: скан со вшитым слоем — выборочно проверить качество")
    if metrics["lines"] > 20 and metrics["median_line_len"] < 25:
        notes.append("короткие строки при большой высоте — возможна многоколоночная вёрстка, проверить порядок чтения")
    return "text-layer", notes


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("pdf", help="path to the PDF")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    ap.add_argument("--min-chars", type=int, default=40, help="min non-space chars per page (default 40)")
    a = ap.parse_args()

    need_tools()

    pages = page_count(a.pdf)
    if not pages:
        print(f"error: не удалось прочитать PDF или в нём нет страниц: {a.pdf}", file=sys.stderr)
        return 2

    sizes = page_sizes(a.pdf, pages)
    images = page_images(a.pdf)

    report = []
    for page in range(1, pages + 1):
        text = page_text(a.pdf, page)
        metrics = analyse(text)
        page_imgs = images.get(page, [])
        pw, ph = sizes.get(page, (0.0, 0.0))
        has_full = any(w >= pw and h >= ph for w, h in page_imgs) if pw and ph else bool(page_imgs)
        v, notes = verdict(metrics, has_full, a.min_chars)
        report.append(
            {
                "page": page,
                "verdict": v,
                "notes": notes,
                "images": len(page_imgs),
                "full_page_image": has_full,
                **metrics,
            }
        )

    if a.json:
        print(json.dumps({"file": a.pdf, "pages": report}, ensure_ascii=False, indent=2))
    else:
        print(f"файл: {a.pdf}  ({pages} стр., порог текста {a.min_chars} симв.)\n")
        for r in report:
            icon = {"text-layer": "OK ", "needs-ocr": "OCR", "ambiguous": "?? "}[r["verdict"]]
            print(
                f"[{icon}] стр. {r['page']}: {r['verdict']}  "
                f"(символов {r['chars']}, мусор {r['garbage_ratio']}, "
                f"подозр. токены {r['suspicious_token_ratio']}, картинок {r['images']})"
            )
            for n in r["notes"]:
                print(f"        · {n}")
        counts = {v: sum(1 for r in report if r["verdict"] == v) for v in ("text-layer", "needs-ocr", "ambiguous")}
        print(
            f"\nитог: текстовый слой — {counts['text-layer']}, требует OCR — {counts['needs-ocr']}, "
            f"спорных — {counts['ambiguous']}"
        )
        if counts["needs-ocr"]:
            print("Дальше: растеризовать только эти страницы (pdftoppm -r 300 -f N -l N) и прогнать OCR.")
        if counts["text-layer"]:
            print("Для страниц с пригодным слоем OCR не запускать — слой точнее любого распознавания.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
