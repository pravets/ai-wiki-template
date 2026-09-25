#!/usr/bin/env python3
"""Build PDF fixtures for the pdf_layer_check self-test.

Hand-rolled minimal PDF writer: no PDF library required. Three fixtures:

  A_digital.pdf - 2 pages with a real text layer (no images)
  B_scan.pdf    - 2 pages that are full-page raster images (no text layer)
  C_mixed.pdf   - page 1 digital text, page 2 full-page scan

The scan fixtures need Pillow (to rasterize the page image); the digital
fixture needs nothing but the standard library.

Used by self_test.py; can also be run directly to get the files:

    python3 make_fixtures.py [outdir]
"""
import io
import os
import sys

A4_W, A4_H = 595, 842
FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "C:/Windows/Fonts/arial.ttf",
]

# Digital page: 'OOO' is deliberate — tesseract reads it as '000', which is the
# asymmetry stage 0 exists to avoid. The text layer keeps it exact.
TEXT_LINES = [
    "INVOICE 2026-0042",
    "Total: 1234.56 EUR",
    "VAT: 205.76 EUR",
    "Supplier: OOO Tekhnomarin",
    "Payment due: 2026-10-01",
]

# Scanned page: Cyrillic, so the OCR bridge has real work to do.
SCAN_LINES = [
    "СЧЁТ-ФАКТУРА 2026-0042",
    "Итого: 1234.56 руб.",
    "НДС: 205.76 руб.",
    "Поставщик: ООО Техномарин",
]


def _esc(s):
    return s.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")


def _text_stream(lines, y0=780, step=22):
    body = ["BT", "/F1 14 Tf", f"50 {y0} Td", f"{step} TL"]
    for ln in lines:
        body.append(f"({_esc(ln)}) Tj T*")
    body.append("ET")
    return "\n".join(body).encode("latin-1")


def _font_path():
    for p in FONT_CANDIDATES:
        if os.path.exists(p):
            return p
    raise RuntimeError(
        "не найден шрифт с кириллицей для фикстуры (пробовали: "
        + ", ".join(FONT_CANDIDATES)
        + ")"
    )


def scan_image(lines, width=1240, height=1754):
    """Render lines into a raster page image; returns (jpeg_bytes, w, h)."""
    from PIL import Image, ImageDraw, ImageFont  # imported here: only scans need it
    img = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(img)
    font = ImageFont.truetype(_font_path(), 40)
    y = 120
    for ln in lines:
        draw.text((120, y), ln, fill="black", font=font)
        y += 80
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    return buf.getvalue(), width, height


def build_pdf(pages):
    """pages: list of ('text', lines) or ('image', jpeg, w, h) -> PDF bytes."""
    objs = {}
    kids = []
    n = 3  # 1 = catalog, 2 = pages
    font_id = None

    for page in pages:
        if page[0] == "text":
            if font_id is None:
                font_id = 100
                objs[font_id] = (
                    b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica "
                    b"/Encoding /WinAnsiEncoding >>"
                )
            stream = _text_stream(page[1])
            content_id = n
            objs[content_id] = b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream"
            page_id = n + 1
            objs[page_id] = (
                b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 %d %d] "
                b"/Resources << /Font << /F1 %d 0 R >> >> /Contents %d 0 R >>"
                % (A4_W, A4_H, font_id, content_id)
            )
            n += 2
        else:
            _, jpeg, w, h = page
            img_id = n
            objs[img_id] = (
                b"<< /Type /XObject /Subtype /Image /Width %d /Height %d "
                b"/ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /DCTDecode "
                b"/Length %d >>\nstream\n" % (w, h, len(jpeg)) + jpeg + b"\nendstream"
            )
            content_id = n + 1
            stream = ("q %d 0 0 %d 0 0 cm /Im1 Do Q" % (A4_W, A4_H)).encode()
            objs[content_id] = b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream"
            page_id = n + 2
            objs[page_id] = (
                b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 %d %d] "
                b"/Resources << /XObject << /Im1 %d 0 R >> >> /Contents %d 0 R >>"
                % (A4_W, A4_H, img_id, content_id)
            )
            n += 3
        kids.append(page_id)

    objs[1] = b"<< /Type /Catalog /Pages 2 0 R >>"
    objs[2] = (
        b"<< /Type /Pages /Kids ["
        + b" ".join(b"%d 0 R" % k for k in kids)
        + b"] /Count %d >>" % len(kids)
    )

    out = bytearray(b"%PDF-1.4\n")
    offsets = {}
    for num in sorted(objs):
        offsets[num] = len(out)
        out += b"%d 0 obj\n" % num + objs[num] + b"\nendobj\n"
    xref_at = len(out)
    size = max(objs) + 1
    out += b"xref\n0 %d\n" % size + b"0000000000 65535 f \n"
    for num in range(1, size):
        out += b"%010d 00000 n \n" % offsets.get(num, 0)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (size, xref_at)
    return bytes(out)


def build_fixtures(outdir, with_scans=True):
    """Write the fixture PDFs into outdir. Returns {name: path}.

    with_scans=False builds only the digital fixture (no Pillow needed).
    """
    os.makedirs(outdir, exist_ok=True)
    files = {}
    files["A_digital"] = os.path.join(outdir, "A_digital.pdf")
    with open(files["A_digital"], "wb") as f:
        f.write(build_pdf([("text", TEXT_LINES), ("text", TEXT_LINES)]))

    if not with_scans:
        return files

    img, w, h = scan_image(SCAN_LINES)
    files["B_scan"] = os.path.join(outdir, "B_scan.pdf")
    with open(files["B_scan"], "wb") as f:
        f.write(build_pdf([("image", img, w, h), ("image", img, w, h)]))

    files["C_mixed"] = os.path.join(outdir, "C_mixed.pdf")
    with open(files["C_mixed"], "wb") as f:
        f.write(build_pdf([("text", TEXT_LINES), ("image", img, w, h)]))
    return files


def main():
    outdir = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.getcwd(), "pdf_fixtures")
    try:
        files = build_fixtures(outdir)
    except RuntimeError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    for name, path in sorted(files.items()):
        print(f"{name}: {path} ({os.path.getsize(path)} байт)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
