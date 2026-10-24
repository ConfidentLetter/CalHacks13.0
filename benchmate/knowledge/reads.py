"""Reading history: what the user has read, which part and which page it was.

record_read() appends one JSON line to knowledge/reads.jsonl (called by T5's POST /read, fed by the Chrome
extension in knowledge/extension/). recent_reads() lets T3 say "you read page 8 earlier".

Only argument validation raises (T5 maps ValueError to 422). Part/page resolution never raises: on any
internal failure the read is still logged with part_id/page = None. Page texts and their token sets are
cached per part (keyed on the index files), so a progress post costs milliseconds, not a re-parse.
"""
from __future__ import annotations

import ipaddress
import json
import re
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import unquote, urlparse

from ._telemetry import log, timed
from .paths import DATASHEETS_DIR, READS_FILE
from .profiles_store import list_profiles
from .textutil import tokenize
from .validation import is_valid_part_id

MIN_PAGE_MATCH_SCORE = 0.15      # token-overlap needed before we claim a page was read
MAX_TITLE_CHARS = 120
MAX_TEXT_CHARS = 20_000
MAX_PDF_BYTES = 60 * 1024 * 1024
DOWNLOAD_TIMEOUT_S = 60
FAILED_RETRY_AFTER_S = 15 * 60   # do not re-attempt a failed datasheet download for this long
_PAGE_FRAGMENT_RE = re.compile(r"[#&]page=(\d+)", re.IGNORECASE)
_lock = threading.Lock()
_ingest_lock = threading.Lock()
_ingests_in_flight: set[str] = set()
_failed_ingests: dict[str, float] = {}   # url -> monotonic time of failure
_pages_cache: dict[str, tuple[tuple, dict]] = {}   # part_id -> (index key, {source: {label: (text, tokens)}})


# --------------------------------------------------------------------------- cached knowledge

def _known_sources() -> dict[str, str]:
    """{lowercased URL or file name: part_id} from tools.ingest_all.SOURCES + knowledge/datasheets/SOURCES.md."""
    out: dict[str, str] = {}
    try:
        from .tools.ingest_all import SOURCES
        for part_id, files in SOURCES.items():
            for f in files:
                out[f.lower()] = part_id
    except Exception:
        pass
    sources_md = DATASHEETS_DIR / "SOURCES.md"
    if sources_md.is_file():
        files_to_part = dict(out)
        for line in sources_md.read_text(encoding="utf-8").splitlines():
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if len(cells) >= 3 and cells[0].startswith("`"):
                fname, url = cells[0].strip("`").lower(), cells[2].lower()
                if fname in files_to_part and url.startswith("http"):
                    out[url] = files_to_part[fname]
    return out


def _pages_with_tokens(part_id: str) -> dict[str, dict[str, tuple[str, set[str]]]]:
    """{source_file: {label: (text, token_set)}} for a part, cached on the index files' identity."""
    from .ingestion import load_pages
    from .retrieval import _index_key
    key = _index_key(part_id)
    if key is None:
        return {}
    with _lock:
        hit = _pages_cache.get(part_id)
        if hit and hit[0] == key:
            return hit[1]
    data = {src: {label: (txt, set(tokenize(txt))) for label, txt in texts.items()}
            for src, texts in load_pages(part_id).items()}
    with _lock:
        _pages_cache[part_id] = (key, data)
    return data


# --------------------------------------------------------------------------- resolution

def _squash(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def resolve_part_id(url_or_path: str, text: str | None) -> str | None:
    """Datasheet URL/file name first, then profile aliases in the URL, then alias mentions in the text."""
    low = url_or_path.lower()
    for key, part_id in _known_sources().items():
        if key and key in low:
            return part_id
    profiles = list_profiles()
    squashed_url = _squash(unquote(low))
    for p in profiles:
        for alias in [p["part_id"], *p.get("aliases", [])]:
            if len(_squash(alias)) >= 4 and _squash(alias) in squashed_url:
                return p["part_id"]
    if text:
        best, best_n = None, 0
        for p in profiles:
            names = [a for a in [p["part_id"], *p.get("aliases", [])] if len(a) >= 4]
            n = sum(len(re.findall(re.escape(a), text, flags=re.IGNORECASE)) for a in names)
            if n > best_n:
                best, best_n = p["part_id"], n
        return best
    return None


def _source_for(pages: dict, url_or_path: str) -> str | None:
    """The indexed source_file whose file name appears in the URL/path, else None."""
    low = url_or_path.lower()
    for source in pages:
        if Path(source).name.lower() in low:
            return source
    return None


def _pages_for(pages: dict, source: str | None) -> dict[str, tuple[str, set[str]]]:
    """Page texts to match a read against: the matching source, else the only source, else all merged."""
    if source:
        return pages[source]
    if len(pages) == 1:
        return next(iter(pages.values()))
    merged: dict[str, tuple[str, set[str]]] = {}
    for texts in pages.values():
        for label, item in texts.items():
            merged.setdefault(label, item)
    return merged


def resolve_page(part_id: str | None, url_or_path: str, text: str | None) -> str | None:
    """Page label: from a `#page=N` fragment (viewer index -> label) or by matching text against page texts."""
    if part_id is None or not is_valid_part_id(part_id):
        return None
    pages = _pages_with_tokens(part_id)
    page_items = _pages_for(pages, _source_for(pages, url_or_path))
    m = _PAGE_FRAGMENT_RE.search(url_or_path)
    if m:
        n = int(m.group(1))
        labels = list(page_items)
        return labels[n - 1] if 1 <= n <= len(labels) else str(n)
    if not text or not page_items:
        return None
    read_tokens = set(tokenize(text[:MAX_TEXT_CHARS]))
    if len(read_tokens) < 5:
        return None
    best_label, best_score = None, 0.0
    for label, (_txt, ptoks) in page_items.items():
        if not ptoks:
            continue
        score = len(read_tokens & ptoks) / len(ptoks)   # how much of the page the user's text covers
        if score > best_score:
            best_label, best_score = label, score
    return best_label if best_score >= MIN_PAGE_MATCH_SCORE else None


def _title_for(url_or_path: str, text: str | None) -> str:
    if text:
        for line in text.splitlines():
            if len(line.strip()) >= 4:
                return line.strip()[:MAX_TITLE_CHARS]
    name = Path(unquote(urlparse(url_or_path).path or url_or_path)).name
    return (name or url_or_path)[:MAX_TITLE_CHARS]


# --------------------------------------------------------------------------- background datasheet ingest

def _is_public_http_pdf(url: str) -> bool:
    """Only public http(s) URLs ending in .pdf are fetched: never local files, localhost or private hosts."""
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return False
    if not parsed.path.lower().endswith(".pdf"):
        return False
    host = parsed.hostname.lower()
    if host in ("localhost",) or host.endswith(".local"):
        return False
    try:
        return ipaddress.ip_address(host).is_global
    except ValueError:
        return True  # a DNS name


def _download_pdf(url: str, dest: Path) -> None:
    import urllib.request
    DATASHEETS_DIR.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 BenchMate"})
    with urllib.request.urlopen(req, timeout=DOWNLOAD_TIMEOUT_S) as resp, part.open("wb") as fh:
        total = 0
        while True:
            block = resp.read(1 << 16)
            if not block:
                break
            total += len(block)
            if total > MAX_PDF_BYTES:
                raise ValueError("PDF larger than MAX_PDF_BYTES")
            fh.write(block)
    with part.open("rb") as fh:
        if fh.read(5) != b"%PDF-":
            part.unlink(missing_ok=True)
            raise ValueError("not a PDF")
    part.replace(dest)


def _ingest_pdf_in_background(url: str, part_id: str) -> None:
    """Download and ingest a public datasheet PDF we have not indexed yet. Never raises into the caller."""
    if not _is_public_http_pdf(url) or not is_valid_part_id(part_id):
        return
    with _ingest_lock:
        failed_at = _failed_ingests.get(url)
        if url in _ingests_in_flight or (failed_at and time.monotonic() - failed_at < FAILED_RETRY_AFTER_S):
            return
        _ingests_in_flight.add(url)

    def work() -> None:
        ok = False
        try:
            from .ingestion import ingest
            name = Path(unquote(urlparse(url).path)).name
            dest = DATASHEETS_DIR / re.sub(r"[^A-Za-z0-9._-]", "_", name)
            if not dest.is_file():
                _download_pdf(url, dest)
            ingest(str(dest), part_id)
            ok = True
        except Exception as exc:  # background: log, never crash the server
            log("knowledge.record_read.ingest_failed", 0.0, url=url[:200], error=f"{type(exc).__name__}: {exc}"[:200])
        finally:
            with _ingest_lock:
                _ingests_in_flight.discard(url)
                if ok:
                    _failed_ingests.pop(url, None)
                else:
                    _failed_ingests[url] = time.monotonic()

    threading.Thread(target=work, name="bm-ingest", daemon=True).start()


# --------------------------------------------------------------------------- public API

def _validate(url_or_path, text, seconds_on_page) -> tuple[str, str | None, float]:
    if not isinstance(url_or_path, str) or not url_or_path.strip():
        raise ValueError("url_or_path must be a non-empty string")
    if text is not None and not isinstance(text, str):
        raise ValueError("text must be a string or None")
    if isinstance(seconds_on_page, bool):
        raise ValueError("seconds_on_page must be a number")
    try:
        seconds = float(seconds_on_page)
    except (TypeError, ValueError):
        raise ValueError("seconds_on_page must be a number") from None
    if not seconds >= 0:
        raise ValueError("seconds_on_page must be >= 0")
    return url_or_path.strip()[:4096], (text[:MAX_TEXT_CHARS] if text else None), seconds


def _resolve(url: str, text: str | None) -> tuple[str | None, str | None]:
    """(part_id, page); never raises."""
    try:
        part_id = resolve_part_id(url, text)
    except Exception as exc:
        log("knowledge.record_read.resolve_failed", 0.0, step="part", error=str(exc)[:160])
        return None, None
    try:
        return part_id, resolve_page(part_id, url, text)
    except Exception as exc:
        log("knowledge.record_read.resolve_failed", 0.0, step="page", error=str(exc)[:160])
        return part_id, None


def record_read(url_or_path: str, text: str | None, seconds_on_page: float) -> None:
    """Log that the user read something (called via POST /read from the browser extension)."""
    url, text, seconds = _validate(url_or_path, text, seconds_on_page)
    with timed("record_read"):
        part_id, page = _resolve(url, text)
        try:
            pages = _pages_with_tokens(part_id) if part_id else {}
            if part_id and _is_public_http_pdf(url) and _source_for(pages, url) is None:
                _ingest_pdf_in_background(url, part_id)
        except Exception as exc:
            log("knowledge.record_read.ingest_skipped", 0.0, error=str(exc)[:160])
        entry = {
            "read_at": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "url": url,
            "part_id": part_id,
            "page": page,
            "title": _title_for(url, text),
            "seconds": round(seconds, 1),
        }
        with _lock:
            READS_FILE.parent.mkdir(parents=True, exist_ok=True)
            with READS_FILE.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    log("knowledge.read", 0.0, part_id=part_id, page=page, seconds=seconds)


def _load_reads() -> list[dict]:
    if not READS_FILE.is_file():
        return []
    out = []
    with READS_FILE.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(row, dict):
                out.append(row)
    return out


def _parse_read_at(value) -> datetime | None:
    try:
        dt = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def recent_reads(part_id: str | None = None, hours: int = 24) -> list[dict]:
    """[{part_id, page, title, read_at, seconds}] newest first — lets T3 say 'you read page 7 last night'.
    Repeated reports for the same url+page (the extension posts progress) collapse into one entry (max seconds)."""
    try:
        hours_f = max(0.0, float(hours))
    except (TypeError, ValueError):
        hours_f = 24.0
    since = datetime.now(timezone.utc) - timedelta(hours=hours_f)
    merged: dict[tuple, dict] = {}
    for order, e in enumerate(_load_reads()):
        read_at = _parse_read_at(e.get("read_at"))
        if read_at is None or read_at < since or (part_id is not None and e.get("part_id") != part_id):
            continue
        try:
            seconds = float(e.get("seconds") or 0)
        except (TypeError, ValueError):
            seconds = 0.0
        key = (e.get("url"), e.get("page"))
        cur = merged.get(key)
        if cur is None or read_at > cur["_dt"]:
            merged[key] = {"part_id": e.get("part_id"), "page": e.get("page"), "title": e.get("title"),
                           "read_at": read_at.isoformat(timespec="milliseconds"),
                           "seconds": max(seconds, cur["seconds"] if cur else 0.0), "_dt": read_at, "_order": order}
        else:
            cur["seconds"] = max(cur["seconds"], seconds)
    rows = sorted(merged.values(), key=lambda r: (r["_dt"], r["_order"]), reverse=True)
    return [{k: v for k, v in r.items() if not k.startswith("_")} for r in rows]
