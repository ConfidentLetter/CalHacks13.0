"""Carve the ESP32-DevKitC V4 chapter out of Espressif's esp-dev-kits manual, keeping the printed page labels.

Run:  python -m knowledge.tools.extract_devkitc_chapter
Input : knowledge/datasheets/esp32-devkitc.pdf  (full esp-dev-kits-en-master-esp32.pdf, 130 pages)
Output: knowledge/datasheets/esp32-devkitc-v4.pdf (the DevKitC V4 chapter only, labels preserved)
"""
from __future__ import annotations

import sys

import pymupdf

from ..paths import DATASHEETS_DIR

SRC = DATASHEETS_DIR / "esp32-devkitc.pdf"
DST = DATASHEETS_DIR / "esp32-devkitc-v4.pdf"
CHAPTER_TITLE = "ESP32-DevKitC V4"


def chapter_page_range(doc) -> tuple[int, int]:
    """0-based [start, end) of the chapter named CHAPTER_TITLE, from the outline."""
    toc = doc.get_toc()
    starts = [(i, pg - 1) for i, (lvl, title, pg) in enumerate(toc) if lvl == 2]
    for i, (idx, pg) in enumerate(starts):
        if toc[idx][1].strip() == CHAPTER_TITLE:
            end = starts[i + 1][1] if i + 1 < len(starts) else len(doc)
            return pg, end
    raise SystemExit(f"chapter {CHAPTER_TITLE!r} not found in outline")


def main() -> int:
    doc = pymupdf.open(str(SRC))
    start, end = chapter_page_range(doc)
    labels = [doc[i].get_label() for i in range(start, end)]
    doc.select(list(range(start, end)))
    if labels[0].isdigit():
        doc.set_page_labels([{"startpage": 0, "prefix": "", "style": "D", "firstpagenum": int(labels[0])}])
    doc.set_metadata({**doc.metadata, "title": f"{CHAPTER_TITLE} User Guide (excerpt of esp-dev-kits manual)"})
    doc.save(str(DST), garbage=3, deflate=True)
    out = pymupdf.open(str(DST))
    print(f"wrote {DST.name}: pages {start + 1}-{end} of source, labels {[p.get_label() for p in out]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
