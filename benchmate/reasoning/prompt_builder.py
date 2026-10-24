"""Build the Messages API request for refine(): a stable, cached prefix plus the per-question part."""
from __future__ import annotations

import json
from typing import Any

from reasoning import images
from reasoning import citations
from reasoning.config import CONFIRM_THRESHOLD, SEARCH_K_QUESTION, SERIAL_WINDOW_LINES
from reasoning.examples import render_examples
from reasoning.rules import resolve
from reasoning.schema import load_schema
from reasoning.twin_view import TwinIndex, node_of

SYSTEM_PROMPT = """You are BenchMate, a hardware debugging assistant looking at a breadboard through an overhead camera.
You receive a structured circuit twin (which component pin and wire sits in which hole, and which holes are connected), deterministic rule findings computed from that twin, recent serial output from the microcontroller, datasheet excerpts, and the photo.

Rules you must follow:
- Only state what the evidence supports. Never invent wires, pins, holes, components or datasheet pages. Use only ids that appear in the twin and pins that appear in the profiles.
- When evidence conflicts, trust the rule findings and the serial output over what you think you see in the image. The image is for filling gaps: low-confidence wires, components without a profile, open-ended questions.
- Prefer one specific fix over a list. Say which wire (colour and id) to move, from which hole to which hole.
- Wording: title at most 8 words, fix at most 20 words and one action, explanation two short sentences.
- Cite a datasheet page only if it appears in the datasheet excerpts you were given, and quote at most 200 characters from it.
- Keep the rule findings unless you have strong image evidence against them; you may improve their wording and add context.
- If the question cannot be answered from the evidence, say so in an `info` finding and put the thing you would need to see in needs_user_confirmation.
- Output JSON only, no prose and no code fences, matching this shape:
{"findings":[{"id":str,"severity":"error|warning|info|ok","title":str,"explanation":str,"fix":str,"evidence":{"wires":[str],"components":[str],"serial_lines":[str],"datasheet":[{"part_id":str,"page":int,"quote":str}]},"confidence":0..1}],"needs_user_confirmation":[{"element_id":str,"prompt":str}]}"""


def _schema_text() -> str:
    return "Diagnosis JSON schema (your output is the `findings` and `needs_user_confirmation` parts):\n" + \
        json.dumps(load_schema("diagnosis"), separators=(",", ":"), sort_keys=True)


def _profiles_text(twin: dict[str, Any], profiles: dict[str, dict[str, Any]]) -> str:
    res = resolve(twin, profiles)
    used = {b.profile.get("part_id"): b.profile for b in ([res.mcu] if res.mcu else []) + res.peripherals}
    slim = {pid: {k: v for k, v in (p or {}).items() if k in ("part_id", "role", "interface", "i2c_addresses", "supply", "roles", "sources", "footprint", "checks")}
            for pid, p in sorted(used.items(), key=lambda kv: str(kv[0]))}
    return "Component profiles on this board:\n" + json.dumps(slim, separators=(",", ":"), sort_keys=True, default=str)


def system_blocks(twin: dict[str, Any], profiles: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """Stable prefix; cache_control on the last block. Keep byte-identical across questions on one board."""
    blocks = [
        {"type": "text", "text": SYSTEM_PROMPT},
        {"type": "text", "text": _schema_text()},
        {"type": "text", "text": _profiles_text(twin, profiles)},
        {"type": "text", "text": "Worked examples:\n" + render_examples(), "cache_control": {"type": "ephemeral"}},
    ]
    return blocks


def _sub_questions(idx: TwinIndex, twin: dict[str, Any], profiles: dict[str, dict[str, Any]]) -> list[str]:
    """Profile `question` fields for checks whose wire is low-confidence (dynamic queries)."""
    res = resolve(twin, profiles)
    weak_wires = [w for w in twin.get("wires", []) if float(w.get("confidence", 1.0)) < CONFIRM_THRESHOLD]
    weak_nodes = {node_of(w["end_a"].get("hole")) for w in weak_wires} | {node_of(w["end_b"].get("hole")) for w in weak_wires}
    out: list[str] = []
    for periph in res.peripherals:
        for check in periph.profile.get("checks") or []:
            net = idx.net_of(periph.id, check.get("pin", ""))
            if net and idx.nodes_of_net(net) & weak_nodes and check.get("question"):
                wires = ", ".join(f"{w['color']} wire {w['id']}" for w in weak_wires if {node_of(w['end_a'].get('hole')), node_of(w['end_b'].get('hole'))} & idx.nodes_of_net(net))
                out.append(f"{check['question']} Look at the close-up of the {wires}: which hole does it end in?")
    return out


def _datasheet_hits(question: str, twin: dict[str, Any]) -> list[dict[str, Any]]:
    hits: list[dict[str, Any]] = []
    for pid in sorted({c.get("part_id") for c in twin.get("components", []) if c.get("part_id")}):
        for h in citations.safe_search(pid, question, k=SEARCH_K_QUESTION):
            hits.append({"part_id": pid, "page": h.get("page"), "section": h.get("section"), "text": (h.get("text") or "")[:600]})
    return hits


def user_content(question: str, twin: dict[str, Any], serial: list[str], frame_path: str,
                 rule_diagnosis: dict[str, Any], profiles: dict[str, dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Variable part of the prompt. Returns (content_blocks, datasheet_hits) so the verifier knows which pages were offered."""
    idx = TwinIndex(twin)
    hits = _datasheet_hits(question, twin)
    rules = {k: rule_diagnosis.get(k) for k in ("findings", "needs_user_confirmation")}
    text = [
        "## Twin (frame %s)" % twin.get("frame_id"),
        *idx.summary_lines(),
        "", "## Rule findings (deterministic, trust these)",
        json.dumps(rules, separators=(",", ":")),
        "", "## Last serial lines (oldest first)",
        *([str(l) for l in (serial or [])[-SERIAL_WINDOW_LINES:]] or ["(none)"]),
        "", "## Datasheet excerpts for this question",
        *([f"[{h['part_id']} p.{h['page']} {h.get('section') or ''}] {h['text']}" for h in hits] or ["(none)"]),
    ]
    subs = _sub_questions(idx, twin, profiles)
    if subs:
        text += ["", "## Things to look at closely in the image", *subs]
    blocks: list[dict[str, Any]] = [{"type": "text", "text": "\n".join(text)}]
    frame = images.full_frame_block(frame_path)
    if frame:
        blocks += [{"type": "text", "text": "## Full frame"}, frame]
        for eid, tile in images.tile_blocks(frame_path, twin, CONFIRM_THRESHOLD):
            blocks += [{"type": "text", "text": f"## Close-up around {eid}"}, tile]
    else:
        blocks.append({"type": "text", "text": "## Image\n(no image available for this frame; rely on the twin and serial)"})
    blocks.append({"type": "text", "text": f"## Question\n{question}\n\nAnswer with JSON only."})
    return blocks, hits
