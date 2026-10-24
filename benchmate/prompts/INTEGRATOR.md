# Henry's run sheet — one operator, five AI terminals

All five terminals work in the same `benchmate/` folder at the same time. Each writes only to its own folder, so they don't collide, and each can read the others' files live — no branches, no merging. Your jobs: launch them, relay messages between them, do the physical work, take snapshots, run the demo.

## 1. Setup (10 minutes, one time)

```bash
unzip benchmate.zip && cd benchmate
python3.11 -m venv .venv && source .venv/bin/activate
pip install -U pip pytest jsonschema pyyaml anthropic
cp env.example.sh env.sh        # then put your real API key in env.sh
source env.sh
python mocks/make_mocks.py && python main.py --mock sda_swapped    # should print "SDA and SCL are swapped"
git init && git add -A && git commit -m "scaffold"
```

Open five terminal windows (or tabs). In each one:

```bash
cd benchmate && source .venv/bin/activate && source env.sh
claude        # or open the folder in Cursor's agent
```

Approvals: five agents will each stop to ask permission for commands. Before launching, allow the routine ones (`pytest`, `pip install`, `python`) and file edits in your tool's permission settings, otherwise the terminals spend most of their time waiting for you.

## 2. Launch order and first messages (5 minutes)

Paste each block as the first message in its own terminal, in this order. T5 goes first because everyone imports its telemetry module.

**Terminal 5 — Shell**
```
You are T5 (Shell) in the BenchMate project. Read AGENTS.md, README.md, HARDWARE.md, everything in contracts/, and then prompts/T5_shell.md in full. Follow prompts/T5_shell.md exactly, starting with Step 1. Write only inside app/ and NOTES_T5.md. After each step, run its tests, update NOTES_T5.md, and continue to the next step without waiting for me unless you are blocked.
```

**Terminal 4 — Knowledge**
```
You are T4 (Knowledge) in the BenchMate project. Read AGENTS.md, README.md, HARDWARE.md, everything in contracts/, and then prompts/T4_knowledge.md in full. Follow prompts/T4_knowledge.md exactly, starting with Step 1. Write only inside knowledge/ and NOTES_T4.md. After each step, run its tests, update NOTES_T4.md, and continue to the next step without waiting for me unless you are blocked. In Step 2 you will need photos of the real modules from me; ask for them and keep working on Step 3 with the datasheets meanwhile.
```

**Terminal 1 — Geometry**
```
You are T1 (Geometry) in the BenchMate project. Read AGENTS.md, README.md, HARDWARE.md, everything in contracts/, and then prompts/T1_geometry.md in full. Follow prompts/T1_geometry.md exactly, starting with Step 1. Write only inside perception_geometry/ and NOTES_T1.md. After each step, run its tests, update NOTES_T1.md, and continue to the next step without waiting for me unless you are blocked. Use the synthetic test bench until real photos appear in eval/calibration/.
```

**Terminal 3 — Reasoning**
```
You are T3 (Reasoning) in the BenchMate project. Read AGENTS.md, README.md, HARDWARE.md, everything in contracts/, and then prompts/T3_reasoning.md in full. Follow prompts/T3_reasoning.md exactly, starting with Step 1. Write only inside reasoning/ and NOTES_T3.md. After each step, run its tests, update NOTES_T3.md, and continue to the next step without waiting for me unless you are blocked.
```

**Terminal 2 — Detection**
```
You are T2 (Detection) in the BenchMate project. Read AGENTS.md, README.md, HARDWARE.md, everything in contracts/, and then prompts/T2_detection.md in full. Follow prompts/T2_detection.md exactly, starting with Step 1. Write only inside perception_detect/, eval/ and NOTES_T2.md. After each step, run its tests, update NOTES_T2.md, and continue to the next step without waiting for me unless you are blocked. Real photos will appear in eval/testset/ as I take them; work with mocks until then.
```

## 3. Your physical work, in parallel with the agents

| When | Do |
|---|---|
| H+0 | Hardware lending area: breadboard, ESP32 or Arduino Uno, USB data cable, a 3.3 V-only I2C sensor, jumpers in red/yellow/green/blue/orange. Lamp and phone clamp if available. |
| H+0.5 | Photograph each module top and bottom, save to `eval/modules/`, tell T4. |
| H+1 | Print `markers/aruco_sheet_print_me.png`, tape markers outside the board corners (0 TL, 1 TR, 2 BR, 3 BL). Mount the phone 30–40 cm above, lamp in front. Never move the mount again. |
| H+1.5 | Flash the microcontroller with the I2C-scan sketch (prints the reading or `no I2C devices found` every 2 s at 115200 baud). Wire the OK circuit. |
| H+2 | 4 calibration photos → `eval/calibration/`. Tell T1. |
| H+2 → H+6 | 20 test photos → `eval/testset/` (OK, 5V, swapped; vary lamp and wire positions; one with a hand in frame). Tell T2. |

## 4. Every 30–60 minutes: the loop

1. Glance at each terminal. Answer any question it is waiting on.
2. `head -4 NOTES_T*.md` — read every Done / Next / Blocked.
3. `grep -A5 "For other terminals" NOTES_T*.md` — relay each item by pasting into the target terminal:
   `Message from T4 (via Henry): <the item>. Adapt your work accordingly, then continue.`
4. `pytest -q` from the project root; if something broke, paste the failure into the owning terminal.
5. `git add -A && git commit -m "checkpoint H+N"` — your rollback point if an agent breaks something.

## 5. Checkpoints

| Time | What must be true | Check with |
|---|---|---|
| H+1 | All stubs exist; telemetry exists | `python main.py --mock sda_swapped`; `pytest -q` |
| H+4 | Each module works on mocks; mock-mode UI plays keys 1–3 | `BM_MOCK=1 uvicorn app.server:app --port 8000`, open http://localhost:8000 |
| H+8 | Integration 1: real camera → twin → rule cards in the UI | Server without `BM_MOCK`; move a wire, watch the overlay |
| H+16 | Integration 2: both demo scenarios correct on the real board | Run each scenario 5 times; ask T2 to run `eval/run_eval.py` |
| H+22 | Refined answers cite real pages; accuracy chart exists | `eval/accuracy_journey.png` |
| H+26 | Feature freeze | Tell every terminal: "Feature freeze. Only fix bugs I report." |

If you hit usage limits with five sessions running, pause T4 and T5 first (their remaining work is polish) and keep T1, T2, T3 going.

## 6. Demo hardening (from H+22)
- Two pre-wired backup boards: one in the 5V state, one swapped.
- Test mock mode with Wi-Fi off. Keys: 1 OK, 2 5V, 3 swapped.
- Rehearse the 3-minute script at least 5 times with a timer.

## 7. Pitch (3 minutes)
1. Problem (20 s): software has stack traces; hardware has "it doesn't work".
2. Live demo (100 s): scenario 1 caught before power-on with the datasheet page; scenario 2 asked by voice → swap → readings appear.
3. How it works (30 s): one architecture slide crediting the industrial designs it draws on — two-stage recognition with targeted queries (Recon), a structured digital twin reasoned over by code (JHU), hybrid retrieval with page citations (Wiwynn), rule checks and self-correction (AI Planner, TTYSC).
4. Proof (20 s): the accuracy-journey chart.
5. Next (10 s): every lab bench with a camera; TAs see where a class is stuck.

## 8. Notability track
Log the process live in Notability: first sketch, mount photos, debug-overlay screenshots at each checkpoint, the accuracy chart, each decision and why. The NOTES status blocks are your raw material.
