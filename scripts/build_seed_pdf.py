#!/usr/bin/env python3
"""Render seed/profile-source.md into seed/profile.pdf.

The PDF is committed, so this only runs when the source text changes. It is
deliberately dependency-free: the application only needs a PDF reader at
runtime, and adding a PDF-writing library to requirements.txt for a build-time
artefact would be a poor trade.

Usage:
    python3 scripts/build_seed_pdf.py
    python3 scripts/build_seed_pdf.py --check     # verify the PDF matches the source

The output must satisfy the same reader the application uses, which is
strict-mode pypdf: a malformed xref table or a missing %%EOF fails at ingest
time with PdfReadError, so `--check` exercises that path too.
"""

from __future__ import annotations

import argparse
import io
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "seed" / "profile-source.md"
TARGET = ROOT / "seed" / "profile.pdf"

PAGE_W, PAGE_H = 595.28, 841.89  # A4 portrait, in points
MARGIN_X, MARGIN_TOP, MARGIN_BOTTOM = 56.0, 64.0, 56.0
BODY_SIZE, LEADING = 9.6, 12.4
H1_SIZE, H2_SIZE = 14.0, 11.0
H1_LEADING, H2_LEADING = 17.0, 14.0

# Adobe Helvetica advance widths (1/1000 em) for the printable ASCII range.
# Accurate widths matter: guessing them produces text that overflows the right
# margin, which is invisible in the source but obvious on the rendered page.
_HELV = (
    "278 278 355 556 556 889 667 191 333 333 389 584 278 333 278 278 "
    "556 556 556 556 556 556 556 556 556 556 278 278 584 584 584 556 "
    "1015 667 667 722 722 667 611 778 722 278 500 667 556 833 722 778 "
    "667 778 722 667 611 722 667 944 667 667 611 278 278 278 469 556 "
    "333 556 556 500 556 556 278 556 556 222 222 500 222 833 556 556 "
    "556 556 333 500 278 556 500 722 500 500 500 334 260 334 584"
)
_HELV_BOLD = (
    "278 333 474 556 556 889 722 238 333 333 389 584 278 333 278 278 "
    "556 556 556 556 556 556 556 556 556 556 333 333 584 584 584 611 "
    "975 722 722 722 722 667 611 778 722 278 556 722 611 833 722 778 "
    "667 778 722 667 611 722 667 944 667 667 611 333 278 333 584 556 "
    "333 556 611 556 611 556 333 611 611 278 278 556 278 889 611 611 "
    "611 611 389 556 333 611 556 778 556 556 500 389 280 389 584"
)
HELV_W = tuple(int(x) for x in _HELV.split())
HELV_BOLD_W = tuple(int(x) for x in _HELV_BOLD.split())


def text_width(text: str, size: float, bold: bool) -> float:
    table = HELV_BOLD_W if bold else HELV_W
    total = 0
    for char in text:
        code = ord(char)
        total += table[code - 32] if 32 <= code <= 126 else 556
    return total * size / 1000.0


def wrap(text: str, size: float, bold: bool, max_width: float) -> list[str]:
    lines: list[str] = []
    for paragraph in text.split("\n"):
        words = paragraph.split()
        if not words:
            lines.append("")
            continue
        current = words[0]
        for word in words[1:]:
            candidate = f"{current} {word}"
            if text_width(candidate, size, bold) <= max_width:
                current = candidate
            else:
                lines.append(current)
                current = word
        lines.append(current)
    return lines


def parse_markdown(markdown: str) -> list[tuple[str, str]]:
    blocks: list[tuple[str, str]] = []
    paragraph: list[str] = []

    def flush() -> None:
        if paragraph:
            blocks.append(("body", " ".join(paragraph).strip()))
            paragraph.clear()

    for raw in markdown.split("\n"):
        line = raw.rstrip()
        if line.startswith("## "):
            flush()
            blocks.append(("h1", line[3:].strip()))
        elif line.startswith("### "):
            flush()
            blocks.append(("h2", line[4:].strip()))
        elif line.startswith("# "):
            flush()
            blocks.append(("title", line[2:].strip()))
        elif not line.strip():
            flush()
        else:
            paragraph.append(line.strip())
    flush()
    return blocks


def escape(text: str) -> str:
    return text.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")


def build_pdf(blocks: list[tuple[str, str]]) -> bytes:
    pages: list[list[tuple[float, float, str, bool, float]]] = [[]]
    y = PAGE_H - MARGIN_TOP
    content_width = PAGE_W - 2 * MARGIN_X

    def new_page() -> None:
        nonlocal y
        pages.append([])
        y = PAGE_H - MARGIN_TOP

    for style, text in blocks:
        if style == "title":
            size, bold, leading, before, after = 17.0, True, 20.0, 0.0, 4.0
        elif style == "h1":
            size, bold, leading, before, after = H1_SIZE, True, H1_LEADING, 6.0, 3.0
        elif style == "h2":
            size, bold, leading, before, after = H2_SIZE, True, H2_LEADING, 7.0, 2.0
        else:
            size, bold, leading, before, after = BODY_SIZE, False, LEADING, 0.0, 5.0

        if style != "body":
            y -= before

        for line in wrap(text, size, bold, content_width):
            if y < MARGIN_BOTTOM + leading:
                new_page()
            y -= leading
            font = "/F2" if bold else "/F1"
            # The trailing space is invisible when rendered but load-bearing on
            # extraction: pypdf concatenates separate text-showing operations
            # with no separator, so without it a word wrapped across a line
            # break comes back glued ("...andReact"). The document is chunked
            # from extracted text, so that gluing reaches the RAG pipeline.
            pages[-1].append(
                (MARGIN_X, y, f"{font} {size:.2f} Tf ({escape(line + ' ')}) Tj", False, 0.0)
            )

        if style != "body":
            y -= after

    streams = []
    for page in pages:
        body = "\n".join(item[2] for item in page)
        # cp1252, not latin-1: the source uses typographic characters (em dash,
        # en dash, curly quotes) that latin-1 cannot represent and silently
        # replaces, corrupting the title.
        try:
            streams.append(body.encode("cp1252"))
        except UnicodeEncodeError as error:
            bad = body[error.start : error.end]
            raise SystemExit(
                f"character {bad!r} at offset {error.start} cannot be encoded; "
                "the PDF uses WinAnsiEncoding, so use a cp1252 character instead."
            ) from error

    # Fixed object numbers: 1 catalog, 2 pages, 3/4 fonts, 5+ page/content pairs.
    # Deriving these arithmetically is how /F1 once pointed at the wrong object,
    # which pypdf rejects with a bare KeyError: '/DescendantFonts'.
    FONT_REGULAR_ID, FONT_BOLD_ID = 3, 4
    first_page_id = 5
    page_ids = [first_page_id + 2 * i for i in range(len(pages))]

    objects: list[bytes] = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        f"<< /Type /Pages /Kids [{' '.join(f'{i} 0 R' for i in page_ids)}] "
        f"/Count {len(pages)} >>".encode(),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>",
    ]
    for index, stream in enumerate(streams):
        objects.append(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {PAGE_W:.2f} {PAGE_H:.2f}] "
            f"/Resources << /Font << /F1 {FONT_REGULAR_ID} 0 R /F2 {FONT_BOLD_ID} 0 R >> >> "
            f"/Contents {page_ids[index] + 1} 0 R >>".encode()
        )
        objects.append(
            b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream"
        )

    out = bytearray(b"%PDF-1.4\n")
    offsets: list[int] = []
    for number, payload in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n".encode() + payload + b"\nendobj\n"

    xref_offset = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode()
    out += b"0000000000 65535 f \n"
    for offset in offsets:
        out += f"{offset:010d} 00000 n \n".encode()
    out += (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref_offset}\n%%EOF\n"
    ).encode()
    return bytes(out)


def verify(pdf: bytes) -> None:
    """Parse with the same strict reader the application's ingest path uses."""
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(pdf), strict=True)
    text = "\n".join(page.extract_text() or "" for page in reader.pages)
    if len(text) < 2000:
        raise SystemExit(f"extracted only {len(text)} characters; the PDF is likely broken")
    if "Akin Gungor" not in text:
        raise SystemExit("expected name missing from extracted text")
    print(f"verified: {len(reader.pages)} page(s), {len(text)} characters extractable")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="verify only, do not write")
    args = parser.parse_args()

    blocks = parse_markdown(SOURCE.read_text(encoding="utf-8"))
    pdf = build_pdf(blocks)
    verify(pdf)

    if args.check:
        if not TARGET.exists():
            raise SystemExit(f"{TARGET} does not exist")
        if TARGET.read_bytes() != pdf:
            raise SystemExit(
                f"{TARGET} is stale relative to {SOURCE.name}. "
                f"Run: python3 scripts/build_seed_pdf.py"
            )
        print(f"{TARGET.relative_to(ROOT)} is up to date")
        return 0

    TARGET.write_bytes(pdf)
    print(f"wrote {TARGET.relative_to(ROOT)} ({len(pdf)} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())