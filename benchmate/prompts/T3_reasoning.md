# T3 — Reasoning: what is wrong, how to fix it, and proof

**How to use:** paste this whole file as the first message in the T3 terminal.

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

You are T3. You own `reasoning/`. Given a circuit twin, recent serial lines and the datasheets, you produce a diagnosis that is correct, specific, actionable and cited. Judges will remember one sentence from the demo, and it comes from you, so being right matters more than being clever.

## Core principle: rules first, model second

The twin is structured data, so most checks are plain code (the "reason over a structured twin, not raw pixels" idea from the JHU digital-twin poster). The vision-language model only fills gaps: open-ended questions, low-confidence wires, components without a profile. This gives you instant, deterministic answers for both demo scenarios even with the network down.

## Build in this order

### Step 1 (by H+1): stubs
`run_checks` and `answer` with exact signatures, returning `mocks/diagnosis_sda_swapped.json` adapted to the input's `frame_id` and mode. Also export `refine` (stub: returns `rule_diagnosis` unchanged).

### Step 2 (by H+4): the rule engine — `reasoning/rules.py`
Profiles follow `contracts/profile.example.yaml` (until T4's real profiles land, load the two YAML documents in that file). Implement each check `kind` as a pure function over the twin:

- Resolve components: the MCU is the component whose profile has `role: mcu`. Peripherals are components with a profile and `role: peripheral`. A component without a profile is reported once as an `info` finding ("Unknown part — register it to check it").
- Helper `net_of(component_id, pin)` → the net containing `"<component_id>.<pin>"`, or `None`.
- `same_net`: pass if `net_of(peripheral, pin)` contains `"<mcu_id>.<mcu_profile.roles[target_role]>"`.
- `max_supply`: collect every member of `net_of(peripheral, pin)` that is an MCU source pin (`mcu_profile.sources`); fail if any source voltage > `supply.max_v`; also fail (`warning`) if no source is on the net ("VIN is not powered").
- **Pattern detection on top of single checks** — this is what makes answers sound expert:
  - If `i2c_sda` and `i2c_scl` both fail and SDA's net contains the MCU's SCL pin and SCL's net contains the MCU's SDA pin → replace the two findings with one: id `i2c_swapped`, title "SDA and SCL are swapped".
  - If a peripheral pin's net contains two different MCU source pins → `error` "3V3 and 5V are shorted together".
- Every finding gets a concrete `fix` computed from the twin: which wire (by color and id) to move, from which hole to which hole. For the swap: "Swap the yellow wire (I18) and the green wire (I15)". Derive target holes from the MCU pin's hole on the correct net.
- Evidence: the wire ids and component ids involved.
- Confidence: the minimum confidence of the wires and components the finding depends on.
- Tests (no network): `mocks/twin_sda_swapped.json` → exactly one error, id `i2c_swapped`, fix mentions both wire ids; `mocks/twin_5v.json` → exactly one error, id `supply_voltage`; `mocks/twin_ok.json` → no errors. Plus: a twin with an unknown part, a twin with a wire of confidence 0.4 on the SDA net.

### Step 3 (by H+6): `run_checks(twin, serial)`
1. Run the rule engine.
2. Serial evidence: regex table in config, e.g. `no I2C devices` / `not found at 0x` → attach to every I2C finding; a successful reading line (`T=` / `found at 0x`) → if no errors, add an `ok` finding "Sensor responding" with that line as evidence.
3. Datasheet citation: for each finding, call `knowledge.search(part_id, check.search_query, k=3)`; attach the top hit's `page` and a quote of at most 200 characters, trimmed to the sentence containing the key number (e.g. "3.6"). If search fails, return the finding without a citation rather than failing.
4. Reading history: if `knowledge.recent_reads(part_id)` includes the cited page, append to the explanation: "You read this page earlier today."
5. Low confidence: if a finding depends on anything with confidence < 0.6, do NOT assert it. Put `{element_id, prompt}` in `needs_user_confirmation` instead ("Is the yellow wire in I18?").
6. Validate against `diagnosis.schema.json`; log ms. Target < 300 ms, no API calls.

### Step 4 (H+6 → H+12): `answer(question, twin, serial, frame_path)` — two-phase
Phase 1, immediately: run `run_checks`, set `mode="answer"`, `question`, and return it to T5 so a card appears within ~300 ms. (T5 sends it as the first `diagnosis` message.)

Phase 2, refine with the model. Provide `refine(question, twin, serial, frame_path, rule_diagnosis) -> dict` exported from `reasoning/__init__.py` (see `contracts/interfaces.md`); T5 calls it right after and sends its result as a second `diagnosis` message with the same `frame_id`.

Build the request (Anthropic Messages API, `anthropic` Python SDK, model from `BM_MODEL`):
- **Stable prefix, cached** (`cache_control: {"type": "ephemeral"}` on the last prefix block):
  1. System prompt: you are a hardware debugging assistant; only state what the evidence supports; when evidence conflicts, trust the rule findings and serial output over the image; prefer one specific fix over a list; output JSON only, matching the schema below.
  2. The JSON schema of the diagnosis.
  3. Profiles of the parts on the board.
  4. The few-shot example bank (Step 5).
- **Variable part:**
  5. The twin rendered as readable lines ("bme280_1.SDA ↔ esp32_1.GPIO22 via w_yellow_1 (conf 0.86)").
  6. Rule findings from Phase 1.
  7. Last 20 serial lines.
  8. Datasheet hits for the question (call `knowledge.search` with the question for each part on the board, k=2).
  9. The image: the full frame downscaled to ≤ 1568 px on the long side, plus close-up tiles only around elements with confidence < 0.6.
  10. The question.
- Use the check `question` fields from the profiles as targeted sub-questions inside the prompt when a related wire is low-confidence (the "dynamic queries" idea from the Recon poster): "Look at the tile: which ESP32 pin does the yellow wire end at?"
- Stream the response; parse JSON when complete.

### Step 5 (by H+10): few-shot example bank — `reasoning/examples/`
5–10 cases, each: a small photo (or tile), its twin summary lines, the serial lines, and the correct diagnosis JSON. Cover: OK board, swap, 5V, missing ground, unknown part, low-confidence wire. Taken from T2's test set once it exists; start with the three mocks as text-only examples. (The curated example-bank idea from the AI Planner poster.)

### Step 6 (by H+12): self-correction — `reasoning/verify.py`
Run on every model output before returning:
1. Schema validation. On failure, retry once, sending the validation error back. On second failure, return the Phase 1 rule diagnosis unchanged.
2. Grounding check (deterministic): every wire id, component id and pin name mentioned must exist in the twin or the MCU profile; every cited page must come from a search hit you provided; every hole id in `fix` must be a valid hole. Remove any finding that fails and log it.
3. Consistency with rules: if the model contradicts a rule finding with confidence ≥ 0.8 (e.g. says the wiring is fine while the rule says swapped), keep the rule finding.
4. Optional, only if time remains: a second, short model call that critiques each finding against its evidence (the reflection-agent idea from the TTYSC poster).

## Latency budget
First card on screen ≤ 300 ms (Phase 1). Refined answer first token ≤ 2 s. Log `rules_ms`, `search_ms`, `model_first_token_ms`, `model_total_ms`.

## Pitfalls to design around
- The model will happily invent pins. The grounding check is not optional.
- Never let a model failure remove the rule answer from the screen.
- Keep the wording plain: title ≤ 8 words, fix ≤ 20 words, one action.

## Done when
- The three mock twins give correct diagnoses with no network access.
- On the real demo boards, the Phase 1 card is right in both scenarios, and the refined answer cites a real datasheet page.
- Grounding-check tests exist with deliberately hallucinated model outputs.

## Report at every checkpoint
Top of `NOTES_T3.md`: Done / Next / Blocked, plus measured latencies.
