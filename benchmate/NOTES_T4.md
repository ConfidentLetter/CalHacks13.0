# NOTES_T4 — Knowledge

**Done:** Step 1 — all six T4 functions exist with exact signatures (`knowledge/__init__.py`); `search` returns the mock hit; `get_profile`/`list_profiles` read `knowledge/profiles/{bme280,esp32-devkitc}.yaml` (copied from the contract example); 15 tests pass (`pytest knowledge/tests -q`).
**Next:** Step 2 (identify real modules — need photos from Henry) in parallel with Step 3 (download datasheets, PyMuPDF/pdfplumber ingestion).
**Blocked:** Nothing hard. Waiting on module photos for Step 2 (continuing with Step 3 meanwhile).

## For other terminals

- **T3 / T5:** `search()` hits return `page` as a **string** page label (what a PDF viewer shows, e.g. `"22"`), never an int. The mock file has `page: 0` (int); my stub already coerces it to `"0"`. Treat `page` as `str`.
- **T2 / T3:** profiles are in `knowledge/profiles/<part_id>.yaml`; use `knowledge.get_profile(part_id)` / `knowledge.list_profiles()` rather than reading the YAML yourselves so the path can move. Both are DRAFTS copied from the contract example until I see the real modules (Step 2) — pin order and `supply.max_v` may change.

## Step log

### Step 1 (stubs + draft profiles)
- Package layout: `_telemetry.py` (falls back to a no-op if `app.telemetry` is missing; TODO remove fallback), `paths.py`, `profiles_store.py`, `search.py`, `ingest.py`, `reads.py`.
- `get_profile` raises `KeyError` for missing/odd ids and returns a deep copy (callers can't mutate the cache).
- Dependencies so far: `requirements/knowledge.txt` → pyyaml.

### Step 2 (real hardware) — IN PROGRESS
- Henry: please photograph each borrowed module top + bottom (sensor breakout, MCU board) into `eval/modules/` and tell me. I need: the sensor's silkscreen pin labels in order, whether there is a small regulator chip near VIN (e.g. marked `662K`, `XC6206`), and the MCU board's full header silkscreen.

### Step 3 (ingestion) — IN PROGRESS
