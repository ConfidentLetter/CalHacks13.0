# T4 — Knowledge: datasheets, profiles, and what the user has read

**How to use:** paste this whole file as the first message in the T4 terminal.

## Project context (identical in all five prompts)

We are building **BenchMate** at Cal Hacks (a weekend hackathon): "a stack trace for your breadboard". A phone camera on a fixed mount looks straight down at a solderless breadboard. BenchMate turns the image into a structured *circuit twin* (which component pin and which wire sits in which hole, and which holes are electrically connected), checks it against component profiles built from datasheets, reads the microcontroller's serial output, and tells the user what is wrong, how to fix it, and which datasheet page says so.

The whole build serves two live demo scenarios:
1. **Prevention** — a 3.3 V-only I2C sensor's VIN is wired to the 5 V pin. Before anyone asks, BenchMate raises an error card citing the datasheet's maximum supply voltage page.
2. **Debug** — the sensor's SDA and SCL wires are swapped. Serial prints "no I2C devices found". The user asks "why isn't the sensor reading?" BenchMate answers "SDA and SCL are swapped — move the yellow wire from I18 to I15" with the datasheet page. The user swaps the wires and readings appear.

One person (Henry, the integrator) runs five AI terminals in parallel. **All five work in the same project folder at the same time**, so every file another terminal writes is visible to you immediately:

| Terminal | Folder | Owns |
|---|---|---|
| T1 Geometry | `perception_geometry/` | calibration, hole mapping, tiling, wire detection, nets |
| T2 Detection | `perception_detect/`, `eval/` | components, part identification, twin assembly, test set, accuracy chart |
| T3 Reasoning | `reasoning/` | rule checks, vision-model answers, self-correction |
| T4 Knowledge | `knowledge/` | datasheets, retrieval, profiles, reading history |
| T5 Shell | `app/` | camera, serial, server, UI, telemetry |

Before writing any code, read: `README.md`, `AGENTS.md`, `HARDWARE.md`, every file in `contracts/`, and the files in `mocks/` (run `python mocks/make_mocks.py` to see how the mock twins are built). The contracts are frozen; if one blocks you, write the problem at the top of `NOTES_<terminal>.md` and continue with a workaround. Never edit another terminal's folder, `contracts/` or `mocks/`.

Working rules:
- Every function in `contracts/interfaces.md` for your folder must exist with that exact signature from your first step, returning mock data if the real version is not ready. Other terminals import it immediately.
- Everything you return that has a schema must validate against it; each of your test files includes a schema-validation test.
- Time every stage with `app.telemetry.log(stage, ms, **extra)`. If `app/telemetry.py` does not exist yet, use `try: from app.telemetry import log except ImportError: log = lambda *a, **k: None`.
- Dependencies go in `requirements/<folder>.txt`. Python 3.11. Tests with `pytest` under `<folder>/tests/`.
- Model name from env `BM_MODEL` (default `claude-sonnet-5-5`), key from `ANTHROPIC_API_KEY`. Never hard-code keys.
- Never run git commands (no commit, branch, checkout, stash, reset); Henry takes snapshots. Only T5 starts the server on port 8000; everyone else tests with `pytest` and plain imports. Install packages with `pip install` into the shared environment and add them to your requirements file. At each checkpoint (H+1, H+4, H+8, H+16, H+22) update the 3-line status block at the top of `NOTES_<terminal>.md`: Done / Next / Blocked.
- Prefer boring, deterministic code. A demo that works every time beats a clever one that works most of the time.
- When you finish a step, run its tests, update your NOTES status block, then move to the next step without waiting for confirmation. Ask the human only when a decision changes another terminal's work.
- Staying in sync: before each new step, re-read `contracts/CHANGELOG.md` and the status block at the top of every other `NOTES_T*.md`. You may READ any file in the repo at any time (other terminals' code included) to integrate correctly; you may only WRITE inside your own folder and your own `NOTES_<terminal>.md`. If another terminal must know something (wrong pin order, contract problem, hardware surprise), add it under `## For other terminals` in your NOTES and say it in your reply so Henry sees it.

---

## Your role

You are T4. You own `knowledge/`. BenchMate's answers are only as trustworthy as the page they cite. You make it possible to say "the datasheet says 3.6 V max, page N" and "you read that page earlier". You also write the component profiles every other terminal runs on, so your profiles are the most load-bearing files in the repo after the contracts.

## Build in this order

### Step 1 (by H+1): stubs and draft profiles
- Every T4 function from `contracts/interfaces.md`, exact signatures. `search` returns `mocks/search_bme280_supply.json`; `get_profile` / `list_profiles` load the two YAML documents in `contracts/profile.example.yaml`; `recent_reads` returns `[]`.
- Copy the two example profiles into `knowledge/profiles/bme280.yaml` and `knowledge/profiles/esp32-devkitc.yaml`. T2 and T3 now read real files from you.

### Step 2 (by H+3): get the real parts and the real datasheets
- Ask the integrator for close-up photos of the exact modules the team borrowed (top and bottom). Identify each one. Write the findings in `NOTES_T4.md`.
- Decide the sensor's real `max_v`: a bare BME280/BMP280 breakout is 3.3 V-only; a module with an onboard regulator (a small 3- or 5-pin chip near VIN, e.g. marked `662K`) accepts 5 V. If the team's sensor tolerates 5 V, scenario 1 does not work — tell the integrator immediately so they find a 3.3 V-only part.
- Verify the ESP32 board's pin order from its silkscreen photo and fix `footprint.rows` in the profile. If the team has an Arduino Uno instead, write `knowledge/profiles/arduino-uno.yaml` (`role: mcu`, roles `i2c_sda: A4`, `i2c_scl: A5`, `gnd: GND`, sources `3.3V: 3.3`, `5V: 5.0`, footprint from its headers) and tell T2/T3.
- Download each part's official datasheet PDF (manufacturer site) into `knowledge/datasheets/`. Also save the board's pinout document. Record source URLs in `knowledge/datasheets/SOURCES.md`.

### Step 3 (by H+6): ingestion — `ingest(pdf_path, part_id)` (pipeline from the Wiwynn poster)
1. Per page with PyMuPDF (`fitz`): text, plus the **page label** (`page.get_label()`, falling back to index+1). Citations always use what a human sees in a PDF viewer.
2. OCR (pytesseract) only for pages with almost no extractable text.
3. Tables: `pdfplumber` on pages whose text contains words like "Parameter", "Min", "Max", "Pin". Turn each table row into a line like `VDD | supply voltage | min 1.71 | max 3.6 | V` so keyword search can hit it.
4. Chunks: split by section headings (lines that look like `4.2 Electrical specification`), max ~800 characters, each chunk keeps `{part_id, page, section, source_file, text}`.
5. Store in `knowledge/index/<part_id>.jsonl` plus embeddings in `knowledge/index/<part_id>.npy`. Idempotent: re-ingesting the same file replaces its chunks.

### Step 4 (by H+8): retrieval — `search(part_id, query, k)`
- Keyword: BM25 (`rank_bm25`) over chunk text, with a tokenizer that keeps tokens like `3.6`, `0x76`, `VDDIO`, `GPIO21` intact. Exact strings decide hardware answers, which is why keyword search is mandatory.
- Vector: `sentence-transformers/all-MiniLM-L6-v2` locally (no API cost, fast on CPU).
- Merge with reciprocal rank fusion (k=60). Optional: cross-encoder rerank of the top 10 if latency allows (`cross-encoder/ms-marco-MiniLM-L-6-v2`).
- **Parent-page retrieval**: for each hit, return a window of the full page text around the chunk, ≤ 1200 characters, so the caller has context for the citation.
- Target ≤ 150 ms per search after warm-up. Load models once at import.
- Tests — these are your acceptance criteria, using the real datasheets:
  - `search("bme280", "maximum supply voltage")` top hit contains the supply-voltage spec and its page label is correct (check by opening the PDF).
  - `search("bme280", "I2C address")` top hit mentions `0x76`/`0x77`.
  - `search("esp32-devkitc", "default I2C pins")` returns the page that maps the pins (or record in NOTES that the doc doesn't say, and that the profile's `roles` come from the Arduino-ESP32 default `Wire` pins).

### Step 5 (by H+10): finish the profiles
- Fill every `datasheet_page` from your own search results.
- For every check, make sure `search_query` actually retrieves the right page as top hit; tune the query string, not the search code, when it doesn't.
- Validate: every `pin` in `checks` and every pin in `roles` / `sources` appears in `footprint.rows`. Write `knowledge/tests/test_profiles.py` for this — a typo here silently breaks T2 and T3.

### Step 6 (H+10 → H+16): reading history and the browser extension
- `record_read(url_or_path, text, seconds_on_page)`: append to `knowledge/reads.jsonl`. Resolve `part_id` by matching the URL or text against profile aliases and datasheet sources. If the URL is a PDF datasheet not yet ingested, download and `ingest` it in a background thread. Resolve the page: for PDFs opened in the browser, the extension can send the `#page=N` fragment if present; otherwise match the text against page texts.
- `recent_reads(part_id, hours)`: newest first.
- Chrome extension (Manifest V3) in `knowledge/extension/`:
  - A popup toggle "Study mode" (off by default). Allow-list of domains in the extension options (manufacturer sites, docs sites, Wikipedia).
  - Content script: when study mode is on and the page is on the allow-list, measure visible time; after 30 s, `POST http://localhost:8000/read` with `{url, text (first 20k chars of document.body.innerText), seconds}`. T5's server forwards it to `record_read`.
  - Chrome's built-in PDF viewer does not expose text to content scripts; send `{url, text: null, seconds}` and let `record_read` fetch the PDF itself.
  - Privacy: nothing is sent anywhere except localhost; say so in the popup.

## Pitfalls to design around
- PDF page index ≠ printed page number. Always cite the label.
- Datasheets repeat numbers in many tables (absolute maximum ratings vs operating conditions). For "can I connect 5 V", the operating range is what matters, but the absolute maximum is the "will it break" number. Make the BME280 supply check's `search_query` target the one the team wants to quote, and put both pages in the profile if useful.
- Do not paste large blocks of datasheet text into the UI; quotes are ≤ 200 characters.

## Done when
- Real datasheets for every part on the demo board are ingested and their acceptance searches pass.
- Profiles match the actual hardware and pass `test_profiles.py`.
- The extension records a read, and `recent_reads("bme280")` returns it with the right page.

## Report at every checkpoint
Top of `NOTES_T4.md`: Done / Next / Blocked, plus anything about the real hardware that other terminals must know.
