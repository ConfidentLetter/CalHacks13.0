"""Tokenizing, boilerplate removal and chunking helpers shared by ingest and search. Pure functions, no I/O."""
from __future__ import annotations

import re
import unicodedata
from collections import Counter

# Keeps hardware tokens whole: 3.6, 0x76, VDDIO, GPIO21, I2C. Lower-cased.
_TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9_.\-]*[a-z0-9]|[a-z0-9]")
_SPLIT_RE = re.compile(r"[a-z]+|[0-9]+(?:\.[0-9]+)?")

# "4.2 Electrical specification", "5.3.1 I2C interface". First group >= 1 (so "0.2 Pa" is not a heading).
_HEADING_RE = re.compile(r"^\s*([1-9]\d?(?:\.\d{1,2}){0,3})\.?\s+([A-Z][^\n|]{2,80})$")
_SPEC_WORDS_RE = re.compile(r"\b(Parameter|Min\.?|Max\.?|Pin|Symbol|Typ\.?)\b")
_PAGE_FOOTER_RE = re.compile(r"^\s*\d{1,3}\s*\|\s*\d{1,3}\s*$")  # "13 | 60"

MAX_CHUNK_CHARS = 800
PARENT_WINDOW_CHARS = 1200
PAGE_OVERLAP_CHARS = 240
_SENTENCE_END_RE = re.compile(r"[.:;!?)\]]\s*$")
BOILERPLATE_MIN_PAGES = 4
BOILERPLATE_PAGE_FRACTION = 0.3


def tokenize(text: str) -> list[str]:
    """Whole tokens first (exact hardware strings), then alnum sub-parts so 'GPIO21' also matches 'GPIO 21'."""
    out: list[str] = []
    # NFKC folds superscripts and ligatures: "I²C" -> "I2C", "ﬁ" -> "fi".
    for tok in _TOKEN_RE.findall(unicodedata.normalize("NFKC", text).lower()):
        tok = tok.strip("._-")
        if not tok:
            continue
        out.append(tok)
        parts = [p for p in _SPLIT_RE.findall(tok) if len(p) >= 2]  # 'i2c' -> no noise tokens i/2/c
        if parts and parts != [tok]:
            out.extend(parts)
    return out


def normalize_line(line: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", line)).strip().lower()


_NUM_PREFIX_RE = re.compile(r"^[\d.]+\s*")


def matches_heading(line: str, titles: set[str]) -> bool:
    """True if the line is one of the (normalized) outline titles, with or without a numeric prefix."""
    norm = normalize_line(line)
    return norm in titles or _NUM_PREFIX_RE.sub("", norm) in titles


def heading_title(line: str) -> str | None:
    """'4.2 Electrical specification' -> that line stripped, else None."""
    m = _HEADING_RE.match(line)
    return line.strip() if m and len(line) <= 90 else None


def looks_like_spec_page(text: str) -> bool:
    return bool(_SPEC_WORDS_RE.search(text))


def boilerplate_lines(page_texts: list[str]) -> set[str]:
    """Normalized lines that repeat on many pages (running headers/footers, document numbers)."""
    if len(page_texts) < BOILERPLATE_MIN_PAGES:
        return set()
    counts: Counter[str] = Counter()
    for text in page_texts:
        for ln in {normalize_line(l) for l in text.splitlines() if l.strip()}:
            counts[ln] += 1
    threshold = max(BOILERPLATE_MIN_PAGES, int(len(page_texts) * BOILERPLATE_PAGE_FRACTION))
    return {ln for ln, n in counts.items() if n >= threshold}


def strip_boilerplate(text: str, boilerplate: set[str]) -> str:
    kept = [l for l in text.splitlines()
            if l.strip() and normalize_line(l) not in boilerplate and not _PAGE_FOOTER_RE.match(l)]
    return "\n".join(kept)


def dedupe_cells(cells: list[str]) -> list[str]:
    """pdfplumber repeats merged cells; drop consecutive duplicates."""
    out: list[str] = []
    for c in cells:
        if not out or out[-1] != c:
            out.append(c)
    return out


def chunk_page(text: str, max_chars: int = MAX_CHUNK_CHARS, initial_section: str = "",
               known_headings: set[str] | None = None) -> list[tuple[str, str]]:
    """Split one page's text into (section, chunk_text) pairs: new chunk at each heading or at max_chars.

    If known_headings (normalized TOC titles) is given, only lines matching one of them start a section;
    otherwise any line that looks like a numbered heading does.
    """
    chunks: list[tuple[str, str]] = []
    section = initial_section
    buf: list[str] = []
    size = 0

    def flush() -> None:
        nonlocal buf, size
        body = "\n".join(buf).strip()
        if body:
            chunks.append((section, body))
        buf, size = [], 0

    def is_section_start(line: str) -> bool:
        if known_headings is not None:
            return matches_heading(line, known_headings)
        return heading_title(line) is not None

    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if is_section_start(line):
            flush()
            section = line
            buf.append(line)
            size = len(line)
            continue
        if size + len(line) + 1 > max_chars and buf:
            flush()
        buf.append(line)
        size += len(line) + 1
    flush()
    return chunks


def parent_window(page_text: str, chunk_text: str, width: int = PARENT_WINDOW_CHARS) -> str:
    """A <= width-char window of the full page text centred on where the chunk starts."""
    page_text = page_text.strip()
    if len(page_text) <= width:
        return page_text
    pos = _locate(page_text, chunk_text)
    if pos < 0:
        return page_text[:width].strip()
    start = max(0, min(pos - width // 4, len(page_text) - width))
    return page_text[start:start + width].strip()


def _locate(page_text: str, chunk_text: str) -> int:
    """Index of the chunk's first words in the page text, tolerant of line breaks and spacing differences."""
    words = chunk_text.split()[:8]
    if not words:
        return -1
    pattern = r"\s+".join(re.escape(w) for w in words)
    m = re.search(pattern, page_text)
    return m.start() if m else page_text.find(" ".join(words[:3]))


def ends_mid_sentence(text: str) -> bool:
    """True when a page's last line has no terminal punctuation (a sentence continues on the next page)."""
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    return bool(lines) and not _SENTENCE_END_RE.search(lines[-1])


def next_page_overlap(next_text: str, width: int = PAGE_OVERLAP_CHARS) -> str:
    """The opening of the next page, cut at a sentence end, to complete a sentence split by a page break."""
    head = " ".join(l.strip() for l in next_text.splitlines() if l.strip())[: width * 2]
    if not head:
        return ""
    for m in re.finditer(r"[.!?]\s", head):
        if m.end() >= min(len(head), width) * 0.3:
            return head[: m.end()].strip()
    return head[:width].strip()
