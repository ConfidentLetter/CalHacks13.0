"""Ingest every datasheet in knowledge/datasheets/ into the part indexes.

Run:  python -m knowledge.tools.ingest_all [part_id ...]
Mapping is explicit so a part can have several source documents (module datasheet + board guide).
"""
from __future__ import annotations

import sys
import time

from ..ingestion import ingest
from ..paths import DATASHEETS_DIR

SOURCES: dict[str, list[str]] = {
    "bme280": ["bme280.pdf"],
    "bmp280": ["bmp280.pdf"],
    "esp32-devkitc": ["esp32-devkitc-v4.pdf", "esp32-wroom-32.pdf", "esp32.pdf"],
    "arduino-uno": ["arduino-uno.pdf", "arduino-uno-pinout.pdf"],
}


def main(argv: list[str]) -> int:
    wanted = argv or list(SOURCES)
    for part_id in wanted:
        for name in SOURCES[part_id]:
            path = DATASHEETS_DIR / name
            if not path.is_file():
                print(f"skip {part_id}: {name} missing")
                continue
            t0 = time.perf_counter()
            n = ingest(str(path), part_id)
            print(f"{part_id:14s} {name:28s} {n:5d} chunks  {time.perf_counter() - t0:5.1f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
