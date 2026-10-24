# NOTES_T4 — Knowledge

**Done:** Steps 1, 3, 4, 5, 6 — real datasheets ingested for bme280, bmp280, esp32-devkitc, arduino-uno (`knowledge/index/`); hybrid BM25+MiniLM search at ~5 ms/query with correct PDF-viewer page labels; profiles filled and validated; `record_read`/`recent_reads` real (part + page resolution, background PDF ingest); Chrome extension in `knowledge/extension/`. 75 tests pass (`pytest knowledge/tests -q`); whole repo passes.
**Next:** Step 2 verification as soon as Henry's module photos land (sensor regulator check, ESP32 board variant → pick profile); then load the extension in Chrome and do one real read → `recent_reads("bme280")`.
**Blocked:** Not blocked. Waiting on module photos from Henry (Step 2).

## For other terminals

- **T3 / T5:** `knowledge.search()` hits: `{text, page, section, score, source_file}`. `page` is a **string** PDF-viewer label (e.g. `"8"`), never an int. `text` ≤ 1200 chars (parent-page window). One hit per page. Example demo facts: BME280 supply max 3.6 V operating → page `"8"`; absolute max 4.25 V → page `"13"`; I2C address 0x76/0x77 → page `"32"`; SDA/SCL pin names (SDI/SCK) → page `"33"`.
- **T3:** every check in `knowledge/profiles/bme280.yaml` now carries `datasheet_page` (tested: its `search_query` returns that page as top hit), and `supply` has extra keys `absolute_max_v: 4.25`, `absolute_max_page: "13"`; `i2c_address_page: "32"` at top level. Extra keys only — nothing from the contract example was removed or renamed.
- **T2:** profiles now also have `pin_aliases` (silkscreen variants → canonical pin, e.g. `IO21 -> GPIO21`, `D21 -> GPIO21` on DevKitC; `VIN -> 5V`). Use `knowledge.list_profiles()` for aliases; there are now 5 profiles: bme280, bmp280-less (bmp280 has an index but no profile yet), esp32-devkitc (38-pin DevKitC V4), esp32-devkit-v1 (30-pin DOIT clone, DIFFERENT pin order), arduino-uno. Which ESP32 profile is real depends on Henry's photo — until then treat `esp32-devkitc` as the default.
- **T5:** `import knowledge` is now cheap (50 ms, no torch). Please add `knowledge.warmup()` to `app/modules.warmup()` (it is exported at package level, idempotent, ~2 s cold: loads MiniLM + BM25 indexes from the local cache). Nothing in knowledge/ downloads from the network at request time — the embedding model is loaded with `local_files_only=True` first.
- **T5:** your `/read` → `modules.record_read` wiring is exactly what my extension expects (`{url, text, seconds}`, `text: null` for PDFs). No CORS change needed: the extension posts from its service worker with `host_permissions` for localhost:8000.
- **T3:** `recent_reads(part_id)` returns `page` as a string label matching `search()` hits, newest first, progress reports for one URL collapsed into one row. The supply query in my bme280 profile (`checks[0].search_query`) returns the operating-range page `"8"` (1.71–3.6 V) as top hit, with p13 (abs. max 4.25 V) second — quote `supply.datasheet_page` for the 3.6 V claim and `supply.absolute_max_page` for "5 V will damage it".
- **Everyone:** `search()` and `record_read()` never raise into the server (only `record_read` argument validation raises `ValueError`, which T5 already maps to 422 via pydantic); failures are logged to telemetry as `knowledge.search_failed` / `knowledge.search_degraded` and degrade to BM25-only or `[]`. The day-one mock hit for bme280 is now returned ONLY when `BM_MOCK=1` and no index exists (so a broken index cannot masquerade as datasheet text).
- **Everyone:** `import knowledge` is cheap (no model load). Submodules are `knowledge.retrieval`, `knowledge.ingestion`, `knowledge.profiles_store`, `knowledge.reads` (names chosen so they don't shadow the exported functions).

## Step 2 — real hardware (OPEN: needs photos)

Henry, please photograph top + bottom of each borrowed module into `eval/modules/` and tell me. I will then confirm:
1. **Sensor:** BME280 vs BMP280 (both indexed). Pin order on the breakout silkscreen (draft: `VIN, GND, SCL, SDA`). **Regulator check:** a small 3- or 5-pin chip near VIN (marked `662K`, `XC6206`, `LM6206` or similar) means the module accepts 5 V and **scenario 1 will not work** with it — then we need a bare 3.3 V-only breakout. The Bosch die itself is 3.6 V max (p8) / 4.25 V absolute (p13).
2. **MCU:** 38-pin ESP32-DevKitC V4 (profile `esp32-devkitc`, order verified against Espressif's user guide) vs 30-pin DOIT "ESP32 DEVKIT V1" (profile `esp32-devkit-v1`, written from the DOIT silkscreen, VERIFY) vs Arduino Uno (profile `arduino-uno`: SDA=A4, SCL=A5). Note the contract example listed "ESP32 DEVKIT V1" as an alias of the 38-pin board; that is wrong for the DOIT board, so I moved that alias to the 30-pin profile.

## Step log

### Step 1 — stubs + draft profiles (done)
- Exact signatures for all six functions; `get_profile` raises `KeyError`, returns deep copies; `list_profiles` sorted by part_id.

### Step 3 — ingestion (done)
- `knowledge/ingestion.py`: PyMuPDF text + `page.get_label()` (fallback index+1 — correct for Bosch/Espressif/Arduino PDFs, verified against printed footers), OCR only for near-empty pages (pytesseract, tesseract binary present), pdfplumber tables → `a | b | c` rows on spec-looking pages, repeated header/footer lines stripped, sections from the PDF outline (TOC) with regex fallback, chunks ≤ 800 chars, page-break sentence overlap. Index: `knowledge/index/<part>.jsonl` + `.pages.json` + `.npy`. Idempotent per (part_id, source_file); a part can have several sources.
- Datasheets + URLs: `knowledge/datasheets/SOURCES.md`. DevKitC V4 chapter carved out of Espressif's 33 MB dev-kits manual with labels preserved (`knowledge/tools/extract_devkitc_chapter.py`). Re-ingest everything: `python -m knowledge.tools.ingest_all`.

### Step 4 — retrieval (done)
- BM25 (tokenizer keeps `3.6`, `0x76`, `VDDIO`, `GPIO21`, folds `I²C`→`i2c`) + all-MiniLM-L6-v2 vectors, RRF k=60, parent-page window, one hit per page. ~3-10 ms per query after warm-up. Cross-encoder rerank (`knowledge/rerank.py`, ms-marco-MiniLM-L-6-v2) is downloaded and cached but OFF by default: measured ~1 s/query on this laptop (budget 150 ms) and it ranked the "I2C address" query worse (code-sample page first). `BM_RERANK=1` enables it.
- Acceptance: "maximum supply voltage" → p13 (abs. max) then p8 (operating); "I2C address" → p33/p32 (the sentence straddles the page break; hex literals are on p32, in the top 3); "default I2C pins" on esp32-devkitc → esp32.pdf 4.8.4 "I2C Interface" — **no Espressif document calls GPIO21/22 the default; that is the Arduino-ESP32 `Wire` default**, recorded in the profile comment.

### Step 6 — reading history + extension (done)
- `knowledge/reads.py`: `record_read` validates input, resolves `part_id` (datasheet URL/file → profile aliases in URL → alias mentions in text), resolves `page` (`#page=N` viewer index → label, else token-overlap against the part's page texts, threshold 0.15), appends to `knowledge/reads.jsonl`; a datasheet PDF URL not yet indexed is downloaded + ingested in a daemon thread. `recent_reads` filters by part/hours, merges progress reports per (url, page), newest first.
- `knowledge/extension/` (MV3): popup toggle "Study mode" (off by default) + privacy note, options page with domain allow-list, service worker measures active-tab time (pauses when the window loses focus / tab hidden) and POSTs after 30 s, then every minute and on leave; PDFs sent with `text: null`. Endpoint forced to localhost. Load unpacked from `chrome://extensions`. Not yet exercised in a real Chrome session (needs T5's server up).

### Code review pass (done)
- Independent review of `knowledge/` → fixed: no network in the request path (models load `local_files_only`), `search()` wrapped and degrading, per-part ingest lock + atomic writes ordered `.npy` → `.pages.json` → `.jsonl`, cache keyed on all three index files with single-flight build, shared `part_id` validation, `record_read` resolution never raises, background PDF ingest only for public http(s) `.pdf` URLs with size cap + `%PDF` check + 15-min negative cache, page texts/token sets cached per part, tolerant `recent_reads` parsing, `list_profiles` skips malformed files. 75 tests.

### Step 5 — profiles (done)
- `knowledge/tests/test_profiles.py`: every check/role/source/pin_alias pin exists in `footprint.rows`; roles needed by peripherals exist on every MCU; aliases unique; each check's `search_query` returns its `datasheet_page` as top hit.
