"""Datasheet ingestion (pipeline per prompts/T4_knowledge.md Step 3).

Per page: PyMuPDF text + page LABEL; OCR (pytesseract) only when a page has almost no text; pdfplumber
tables on spec-looking pages (rows become `a | b | c` lines); headers/footers stripped; sections from the
PDF outline; heading-based chunks <= 800 chars; a sentence split by a page break is completed from the
next page. Output: knowledge/index/<part_id>.jsonl (chunks), <part_id>.pages.json (full page texts),
<part_id>.npy (embeddings, same row order as the jsonl). Idempotent per (part_id, source_file).

Writes are atomic per file (temp + replace), ordered .npy -> .pages.json -> .jsonl, and serialised per part.
"""
from __future__ import annotations

import json
import os
import re
import threading
from pathlib import Path

import numpy as np

from . import embeddings as _emb
from ._telemetry import log, timed
from .paths import INDEX_DIR, REPO_ROOT
from .textutil import (boilerplate_lines, chunk_page, dedupe_cells, ends_mid_sentence, looks_like_spec_page,
                       next_page_overlap, normalize_line, strip_boilerplate)
from .validation import require_part_id

MIN_TEXT_CHARS_BEFORE_OCR = 40
OCR_ZOOM = 2.0
_ROW_SEP = " | "
_part_locks: dict[str, threading.Lock] = {}
_part_locks_guard = threading.Lock()


def _part_lock(part_id: str) -> threading.Lock:
    with _part_locks_guard:
        return _part_locks.setdefault(part_id, threading.Lock())


# --------------------------------------------------------------------------- extraction

def _page_label(page, index: int) -> str:
    try:
        label = (page.get_label() or "").strip()
    except Exception:
        label = ""
    return label or str(index + 1)


def _ocr_page(page) -> str:
    try:
        import pymupdf
        import pytesseract
        from PIL import Image
        pix = page.get_pixmap(matrix=pymupdf.Matrix(OCR_ZOOM, OCR_ZOOM))
        img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
        return pytesseract.image_to_string(img) or ""
    except Exception:  # package or tesseract binary missing, etc.
        return ""


def _clean_cell(cell) -> str:
    return re.sub(r"\s+", " ", str(cell or "")).strip()


def _table_lines(pdf_path: Path, page_indices: list[int]) -> dict[int, list[str]]:
    """pdfplumber tables for the given 0-based pages -> {page_index: ['VDD | supply voltage | 1.71 | 3.6 | V', ...]}."""
    out: dict[int, list[str]] = {}
    if not page_indices:
        return out
    try:
        import pdfplumber
        with pdfplumber.open(str(pdf_path)) as pdf:
            for idx in page_indices:
                if idx >= len(pdf.pages):
                    continue
                lines: list[str] = []
                try:
                    tables = pdf.pages[idx].extract_tables() or []
                except Exception:
                    tables = []
                for table in tables:
                    for row in table:
                        cells = dedupe_cells([_clean_cell(c) for c in row if _clean_cell(c)])
                        if len(cells) >= 2:
                            lines.append(_ROW_SEP.join(cells))
                if lines:
                    out[idx] = lines
    except Exception:
        return out
    return out


def _toc_sections(toc: list, n_pages: int) -> tuple[list[str], set[str]]:
    """Per-page section in effect at the TOP of each page (last outline heading that started on an earlier
    page; headings starting on the page itself are picked up line by line while chunking) + normalized titles."""
    last_on_page: dict[int, str] = {}
    titles: set[str] = set()
    for _level, title, page_no in toc:
        title = re.sub(r"\s+", " ", str(title)).strip()
        if not title or not (1 <= int(page_no) <= n_pages):
            continue
        titles.add(normalize_line(title))
        last_on_page[int(page_no) - 1] = title
    per_page: list[str] = []
    current = ""
    for idx in range(n_pages):
        per_page.append(current)
        current = last_on_page.get(idx, current)
    return per_page, titles


def extract_pages(pdf_path: Path) -> tuple[list[dict], set[str] | None]:
    """([{index, label, text, section, ocr}], toc_titles). Text has headers/footers removed and
    pdfplumber table rows appended as `a | b | c` lines. toc_titles is None when the PDF has no outline."""
    import pymupdf

    pages: list[dict] = []
    with pymupdf.open(str(pdf_path)) as doc:
        toc = doc.get_toc() or []
        sections, titles = _toc_sections(toc, len(doc))
        for idx, page in enumerate(doc):
            text = page.get_text("text") or ""
            used_ocr = False
            if len(text.strip()) < MIN_TEXT_CHARS_BEFORE_OCR:
                ocr = _ocr_page(page)
                if ocr.strip():
                    text, used_ocr = ocr, True
            pages.append({"index": idx, "label": _page_label(page, idx), "text": text,
                          "section": sections[idx], "ocr": used_ocr})
    boiler = boilerplate_lines([p["text"] for p in pages])
    pages = [{**p, "text": strip_boilerplate(p["text"], boiler)} for p in pages]
    spec_pages = [p["index"] for p in pages if looks_like_spec_page(p["text"])]
    tables = _table_lines(pdf_path, spec_pages)
    pages = [
        {**p, "text": p["text"] + ("\n" + "\n".join(tables[p["index"]]) if p["index"] in tables else "")}
        for p in pages
    ]
    return pages, (titles if toc else None)


def _chunk_pages(pages: list[dict], toc_titles: set[str] | None, part_id: str, source: str) -> list[dict]:
    chunks: list[dict] = []
    section = ""
    for i, p in enumerate(pages):
        start = p["section"] if toc_titles is not None else section
        page_chunks = chunk_page(p["text"], initial_section=start, known_headings=toc_titles)
        if page_chunks and i + 1 < len(pages) and ends_mid_sentence(p["text"]):
            # A sentence split by the page break: let the page's last chunk see how it ends. The fact is
            # still cited to THIS page; the parent window (full page text) is unchanged.
            tail = next_page_overlap(pages[i + 1]["text"])
            if tail:
                sec, body = page_chunks[-1]
                page_chunks[-1] = (sec, body + " " + tail)
        for sec, body in page_chunks:
            section = sec
            chunks.append({"part_id": part_id, "page": p["label"], "page_index": p["index"],
                           "section": sec, "source_file": source, "text": body})
    return chunks


# --------------------------------------------------------------------------- storage

def index_paths(part_id: str) -> tuple[Path, Path, Path]:
    """(chunks.jsonl, pages.json, embeddings.npy) for a part."""
    return INDEX_DIR / f"{part_id}.jsonl", INDEX_DIR / f"{part_id}.pages.json", INDEX_DIR / f"{part_id}.npy"


def _relative_source(pdf_path: Path) -> str:
    try:
        return pdf_path.resolve().relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return pdf_path.name


def load_chunks(part_id: str) -> list[dict]:
    jsonl, _, _ = index_paths(part_id)
    if not jsonl.is_file():
        return []
    with jsonl.open("r", encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def load_pages(part_id: str) -> dict[str, dict[str, str]]:
    """{source_file: {page_label: full_text}}"""
    _, pages_file, _ = index_paths(part_id)
    if not pages_file.is_file():
        return {}
    return json.loads(pages_file.read_text(encoding="utf-8"))


def load_embeddings(part_id: str) -> np.ndarray | None:
    _, _, npy = index_paths(part_id)
    if not npy.is_file():
        return None
    arr = np.load(npy)
    return arr if arr.ndim == 2 and len(arr) else None


def _atomic_write_text(path: Path, text: str) -> None:
    tmp = path.with_name(path.name + f".{os.getpid()}.tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def _atomic_write_npy(path: Path, arr: np.ndarray) -> None:
    tmp = path.with_name(path.name + f".{os.getpid()}.tmp.npy")
    np.save(tmp, arr.astype(np.float32))
    tmp.replace(path)


def _write_index(part_id: str, chunks: list[dict], pages: dict, emb: np.ndarray | None) -> None:
    """Write .npy, then .pages.json, then .jsonl (the cache key), each atomically."""
    INDEX_DIR.mkdir(parents=True, exist_ok=True)
    jsonl, pages_file, npy = index_paths(part_id)
    if emb is not None and len(emb) == len(chunks):
        _atomic_write_npy(npy, emb)
    elif npy.exists():
        npy.unlink()
    _atomic_write_text(pages_file, json.dumps(pages, ensure_ascii=False))
    _atomic_write_text(jsonl, "".join(json.dumps(c, ensure_ascii=False) + "\n" for c in chunks))


def _merge_embeddings(kept_chunks: list[dict], kept_emb: np.ndarray | None,
                      new_chunks: list[dict], new_emb: np.ndarray | None) -> np.ndarray | None:
    """Embeddings for kept + new chunks, re-embedding kept ones if they were indexed without a model."""
    if new_chunks and new_emb is None:
        return None  # model unavailable now -> BM25-only for the whole part until re-ingested
    if kept_chunks and (kept_emb is None or (new_emb is not None and kept_emb.shape[1] != new_emb.shape[1])):
        kept_emb = _emb.encode([c["text"] for c in kept_chunks])
        if kept_emb is None:
            return None
    parts = [e for e in (kept_emb, new_emb) if e is not None and len(e)]
    return np.vstack(parts) if parts else None


# --------------------------------------------------------------------------- public API

def ingest(pdf_path: str, part_id: str) -> int:
    """Extract, chunk, index a datasheet. Returns number of chunks. Idempotent."""
    path = Path(pdf_path)
    if not path.is_file():
        raise FileNotFoundError(pdf_path)
    require_part_id(part_id)
    source = _relative_source(path)

    with timed("ingest.extract", part_id=part_id, source_file=source):
        pages, toc_titles = extract_pages(path)
    new_chunks = _chunk_pages(pages, toc_titles, part_id, source)
    with timed("ingest.embed", part_id=part_id, n=len(new_chunks)):
        new_emb = _emb.encode([c["text"] for c in new_chunks]) if new_chunks else None

    with _part_lock(part_id):
        # Idempotent merge: drop this source's old chunks (and their embedding rows), keep other sources.
        old_chunks = load_chunks(part_id)
        old_emb = load_embeddings(part_id)
        if old_emb is not None and len(old_emb) != len(old_chunks):
            old_emb = None
        keep_idx = [i for i, c in enumerate(old_chunks) if c.get("source_file") != source]
        kept_chunks = [old_chunks[i] for i in keep_idx]
        kept_emb = old_emb[keep_idx] if old_emb is not None and keep_idx else None
        emb = _merge_embeddings(kept_chunks, kept_emb, new_chunks, new_emb)

        all_pages = load_pages(part_id)
        all_pages[source] = {p["label"]: p["text"] for p in pages}
        _write_index(part_id, kept_chunks + new_chunks, all_pages, emb)

    from .retrieval import invalidate  # local import avoids a cycle
    invalidate(part_id)
    log("knowledge.ingest", 0.0, part_id=part_id, source_file=source, chunks=len(new_chunks),
        pages=len(pages), ocr_pages=sum(p["ocr"] for p in pages), embedded=emb is not None)
    return len(new_chunks)
