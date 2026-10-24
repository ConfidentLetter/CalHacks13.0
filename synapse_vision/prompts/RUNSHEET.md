# Henry's run sheet — Synapse Vision

## 1. Setup (10 minutes)
```bash
unzip synapse_vision.zip && cd synapse_vision
python3.11 -m venv .venv && source .venv/bin/activate
pip install -U pip pytest jsonschema pyyaml anthropic opencv-python fastapi uvicorn
cp env.example.sh env.sh      # put your API key in env.sh
source env.sh
python main.py --mock         # prints 4 lines; L1 is the deliberate product-rule mistake
git init && git add -A && git commit -m "scaffold"
```
Open four terminal windows. In each: `cd synapse_vision && source .venv/bin/activate && source env.sh && claude`.
In your tool's permission settings, allow `pytest`, `pip install`, `python` and file edits before launching, or the terminals will mostly wait on you.

## 2. Launch (paste one block per terminal, in this order)

**T4 — App & Eval** (first: everyone imports its config and telemetry)
```
You are T4 (App & Eval) in the Synapse Vision project. Read AGENTS.md, README.md, everything in contracts/, config/vision.yaml, mocks/, and then prompts/T4_app_eval.md in full. Follow prompts/T4_app_eval.md exactly, starting with Step 1. Write only inside app/, eval/ and NOTES_T4.md. After each step, run its tests, update NOTES_T4.md, and continue without waiting for me unless you are blocked.
```

**T1 — Capture**
```
You are T1 (Capture) in the Synapse Vision project. Read AGENTS.md, README.md, everything in contracts/, config/vision.yaml, mocks/, hardware/, and then prompts/T1_capture.md in full. Follow prompts/T1_capture.md exactly, starting with Step 1. Write only inside capture/, hardware/ and NOTES_T1.md. After each step, run its tests, update NOTES_T1.md, and continue without waiting for me unless you are blocked. Use your synthetic test bench until real photos appear in eval/calibration/.
```

**T2 — Layout**
```
You are T2 (Layout) in the Synapse Vision project. Read AGENTS.md, README.md, everything in contracts/, config/vision.yaml, mocks/, and then prompts/T2_layout.md in full. Follow prompts/T2_layout.md exactly, starting with Step 1. Write only inside layout/ and NOTES_T2.md. After each step, run its tests, update NOTES_T2.md, and continue without waiting for me unless you are blocked. Use synthetic pages until real ones appear in eval/testset/.
```

**T3 — Transcribe**
```
You are T3 (Transcribe) in the Synapse Vision project. Read AGENTS.md, README.md, everything in contracts/, config/vision.yaml, mocks/, and then prompts/T3_transcribe.md in full. Follow prompts/T3_transcribe.md exactly, starting with Step 1. Write only inside transcribe/ and NOTES_T3.md. After each step, run its tests, update NOTES_T3.md, and continue without waiting for me unless you are blocked. Never correct the student's mathematics.
```

## 3. Your physical work while they build

| When | Do |
|---|---|
| H+0 | Mount the camera (`hardware/README.md`): Pi camera or phone, 35–45 cm above the desk, dark mat, lamp angled so no glare. |
| H+0.5 | Pi: run `hardware/pi_snapshot_server.py`, open `/snapshot.jpg` from the laptop, set `capture.pi_url` in `config/vision.yaml`. |
| H+1 | Tell the Tutor team the mock API is up at `http://<laptop-ip>:8000` (`app/API.md`) once T4 says so. |
| H+1 → H+4 | Write 15–20 test pages by hand (calculus/algebra derivations), **each with at least one deliberate mistake** (product rule, chain rule, sign, distribution), plus: one with crossed-out lines, one fraction-heavy, one in pencil. Photograph each from the mount into `eval/testset/<n>.jpg`. Put 10 extra plain shots in `eval/calibration/` for T1. |
| H+4 → H+6 | Correct the pre-labels at `http://localhost:8000/label` (about a minute per page), ticking `planted_error` on each deliberate mistake. |
| H+6 | Write the demo page: `f(x) = x^2 sin x`, `f'(x) = 2x · cos x`, a crossed-out line, a next line. Practise writing it the same way each time. |

## 4. Every 30–60 minutes
1. Answer any terminal that is waiting.
2. `head -4 NOTES_T*.md` and `grep -A5 "For other terminals" NOTES_T*.md`; relay by pasting into the target terminal: `Message from T2 (via Henry): <item>. Adapt, then continue.`
3. `pytest -q` from the root; paste failures into the owning terminal.
4. `git add -A && git commit -m "checkpoint H+N"`.
5. After H+8: ask T4 to run `eval/run_eval.py`; read planted-error preservation first. Anything below 100 % on the demo page goes to T3 immediately.
6. Read `runtime/debug/verbatim_guard.jsonl` — every line where the system had to choose between a "correct" and a "verbatim" reading.

## 5. Tuning cheatsheet (edit `config/vision.yaml`, no restart needed)
- Lines merged or split wrongly → `layout.min_line_height_px`.
- Too many false "blur" flags → lower `page.blur_threshold`.
- Too many re-reads (slow) → lower `transcribe.agreement_threshold` slightly; too many wrong confident lines → raise it.
- Analyses starting while your hand is still on the page → raise `capture.stable_seconds`.
