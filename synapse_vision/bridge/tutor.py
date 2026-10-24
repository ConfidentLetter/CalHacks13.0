"""The only place in the repo that judges the student's work. It receives the verbatim page twin and must
quote it; it never changes a label. Transcription stays T3's business.

    judge_twin(twin)                 -> {summary, topics, steps[{id,label,status,note}], hints}
    respond(message, history, ...)   -> {reply, petExpression}
    sessions                         -> per-sessionId history for /api/tutor/*
"""
from __future__ import annotations

import threading
from collections import deque
from typing import Any

from bridge import llm
from bridge.compat import cfg, now_iso

STEP_STATUSES = ("correct", "error", "unclear")
PET_EXPRESSIONS = ("neutral", "encouraging", "curious", "celebrating", "thinking")
DEFAULT_LOW_CONFIDENCE = 0.6
MAX_HISTORY_TURNS = 20
MAX_READING_ITEMS = 10
MAX_READING_TEXT_CHARS = 1500
MAX_NOTE_CHARS = 200

JUDGE_SYSTEM = """You are a patient math tutor reviewing ONE page of a student's handwritten work.

You do not see the page. You receive its lines exactly as a transcriber read them, in reading order, with for each
line: id, the verbatim LaTeX, a plain-text rendering, the line's status (active | crossed_out | illegible), the
transcriber's confidence (0-1) and any uncertain spans with alternative readings.

Your job: for each ACTIVE line decide whether the mathematics written on that line is correct, an error, or unclear.
Rules:
- Judge only what is written. Never rewrite, complete or "fix" a line; the label is fixed and not yours to change.
- "error" only when you are confident the written mathematics is wrong given the lines above it.
- "unclear" when the line could be a misread (low confidence, uncertain spans whose alternatives would change the
  meaning), when it is a problem statement or definition rather than a claim, or when you cannot tell.
- crossed_out and illegible lines are already handled: you may skip them or return them as unclear.
- Notes are short (one sentence, at most 200 characters), concrete, and encouraging. Point at what to re-check;
  do not give the full corrected answer.
- summary: two sentences at most, naming the topic and the key issue (or confirming the work is right).
- topics: 1-3 short topic names. hints: at most 3 short next-step hints the student can act on.
Output strict JSON only."""

JUDGE_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "topics": {"type": "array", "items": {"type": "string"}},
        "steps": {"type": "array", "items": {"type": "object", "properties": {
            "id": {"type": "string"},
            "status": {"type": "string", "enum": list(STEP_STATUSES)},
            "note": {"type": "string"}}, "required": ["id", "status", "note"]}},
        "hints": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["summary", "topics", "steps", "hints"],
}

CHAT_SYSTEM = """You are Pip, a warm, concise study tutor inside the Synapse dashboard. You help a student with their
OWN work: a verbatim transcription of their latest handwritten notebook page (if provided) and the titles of web pages
they recently read (and their text only if the student consented and it is included).

Rules:
- Quote the student's lines exactly as transcribed when you refer to them (they are verbatim; do not clean them up).
- The notebook snapshot is ONE still photo taken when the student asked; say "in the photo from <time>" rather than
  claiming to watch them.
- Be Socratic and brief: 2-5 short paragraphs or fewer, plain text, blank line between paragraphs. Prefer a pointed
  question or a check the student can do over handing over the full answer, unless they explicitly ask for it.
- If a line looks wrong, say which line and why; if a line may be a transcription misread (low confidence), say so.
- If no notebook or reading context is available, say so honestly and still help with the question.
- petExpression: celebrating when the work is right, encouraging when there is a fixable mistake, curious when you ask
  a question, thinking when you reason through something, neutral otherwise.
Output strict JSON only: {"reply": "...", "petExpression": "..."}."""

CHAT_SCHEMA = {
    "type": "object",
    "properties": {"reply": {"type": "string"}, "petExpression": {"type": "string", "enum": list(PET_EXPRESSIONS)}},
    "required": ["reply", "petExpression"],
}


# ---------------------------------------------------------------------- twin → prompt lines

def twin_lines(twin: dict | None) -> list[dict]:
    """Lines in reading order: the fields the judge needs (verbatim latex/text untouched) plus T3's
    recognition extras (bbox, crops, both readings) that the UI's inspector shows per step."""
    if not twin:
        return []
    lines = sorted(twin.get("lines") or [], key=lambda l: (int(l.get("order", 0)), str(l.get("id"))))
    return [{"id": str(l.get("id")), "latex": l.get("latex") or "", "text": l.get("text") or "",
             "status": l.get("status") or "active", "confidence": float(l.get("confidence") or 0.0),
             "uncertain_spans": list(l.get("uncertain_spans") or []), "parse_ok": bool(l.get("parse_ok", True)),
             "bbox": _bbox(l.get("bbox")), "crop_path": l.get("crop_path"), "context_crop_path": l.get("context_crop_path"),
             "readings": _readings(l)}
            for l in lines]


def label_of(line: dict) -> str:
    return line.get("latex") or line.get("text") or ""


def _bbox(value: Any) -> list[float] | None:
    try:
        box = [float(v) for v in value]
    except (TypeError, ValueError):
        return None
    return box if len(box) == 4 else None


def _reading_text(reading: Any) -> str | None:
    """One reading as the string the UI shows: verbatim latex, else verbatim text; None when absent."""
    if not isinstance(reading, dict):
        return None
    if reading.get("illegible") and not (reading.get("latex") or reading.get("text")):
        return ""
    return reading.get("latex") or reading.get("text") or ""


def _readings(line: dict) -> dict:
    """{page, line, reread, agree} from T3's per-line `readings` ({line, page, reread, notes, cached})."""
    raw = line.get("readings") if isinstance(line.get("readings"), dict) else {}
    line_r, page_r, reread_r = raw.get("line"), raw.get("page"), raw.get("reread")
    if reread_r is None and isinstance(line.get("reread"), dict):
        reread_r = line["reread"].get("result") if isinstance(line["reread"].get("result"), dict) else None
    notes = [str(n) for n in (raw.get("notes") or [])]
    if isinstance(line_r, dict) and isinstance(page_r, dict):
        agree = _readings_agree(line_r, page_r) and not any(n in ("disagree", "near_disagree") for n in notes)
    else:
        agree = False
    return {"page": _reading_text(page_r), "line": _reading_text(line_r) if line_r is not None else (line.get("latex") or line.get("text") or None),
            "reread": _reading_text(reread_r), "agree": bool(agree), "notes": notes}


def _readings_agree(a: dict, b: dict) -> bool:
    try:
        from transcribe.compare import readings_agree  # T3's own agreement rule (normalized latex identical)

        return bool(readings_agree(a, b))
    except Exception:  # noqa: BLE001 - T3 helper missing or changed: plain comparison
        return (a.get("latex") or a.get("text") or "") == (b.get("latex") or b.get("text") or "")


def step_base(line: dict) -> dict:
    """The recognition half of a step (everything except status/note), from a `twin_lines` entry."""
    from bridge.compat import file_url

    return {"id": line["id"], "label": label_of(line), "confidence": line["confidence"], "lineStatus": line["status"],
            "bbox": line.get("bbox"), "cropUrl": file_url(line.get("crop_path")),
            "contextCropUrl": file_url(line.get("context_crop_path")), "readings": line.get("readings") or
            {"page": None, "line": None, "reread": None, "agree": False, "notes": []},
            "uncertainSpans": list(line.get("uncertain_spans") or [])}


def prefilled(line: dict) -> tuple[str, str] | None:
    """Status the bridge decides before any model sees the line (never overridden by the model)."""
    low = float(cfg("transcribe.low_confidence", DEFAULT_LOW_CONFIDENCE))
    if line["status"] == "crossed_out":
        return "unclear", "crossed out"
    if line["status"] == "illegible":
        return "unclear", "illegible in the photo"
    if line["confidence"] < low:
        return "unclear", f"low transcription confidence ({line['confidence']:.2f}); may be a misread"
    return None


def _lines_block(lines: list[dict]) -> str:
    rows = []
    for l in lines:
        spans = "; ".join(f"{s.get('start')}-{s.get('end')} alt={s.get('alternatives')}" for s in l["uncertain_spans"])
        rows.append(f"- id={l['id']} status={l['status']} confidence={l['confidence']:.2f}"
                    f"{' uncertain=[' + spans + ']' if spans else ''}\n  latex: {l['latex']}\n  text: {l['text']}")
    return "\n".join(rows) if rows else "(no lines were read on this page)"


# ---------------------------------------------------------------------- judge

def judge_twin(twin: dict) -> dict:
    """ONE model call over the verbatim lines → analysis body. Labels come from the twin, never from the model."""
    lines = twin_lines(twin)
    base = {"summary": "", "topics": [], "steps": [], "hints": []}
    if not lines:
        why = twin.get("_error") or ("quality issues: " + ", ".join(twin.get("quality", {}).get("issues") or []) or "no lines found")
        return {**base, "summary": f"No handwriting could be read on this page ({why}). Try a sharper, flatter photo.",
                "steps": []}
    fixed = {l["id"]: prefilled(l) for l in lines}
    to_judge = [l for l in lines if fixed[l["id"]] is None]
    verdicts: dict[str, dict] = {}
    try:
        user = ("Here is the page, top to bottom:\n\n" + _lines_block(lines)
                + "\n\nReturn one step per line id listed above (crossed_out/illegible may be omitted).")
        judged = llm.ask_json(JUDGE_SYSTEM, [{"role": "user", "content": user}], JUDGE_SCHEMA, stage="bridge.judge",
                              timeout_s=float(cfg("bridge.judge_timeout_s", 40.0)))
        verdicts = {str(s["id"]): s for s in judged.get("steps", []) if isinstance(s, dict)}
        result = {**base, "summary": str(judged.get("summary") or "").strip(),
                  "topics": [str(t) for t in judged.get("topics", [])][:3],
                  "hints": [str(h) for h in judged.get("hints", [])][:3]}
    except llm.LLMError as exc:
        result = {**base, "summary": f"Analysis failed ({exc}); the lines below are shown as transcribed, unjudged.",
                  "analysisFailed": True}
        to_judge = []
    steps = []
    for l in lines:
        pre = fixed[l["id"]]
        if pre is not None:
            status, note = pre
        elif l in to_judge and l["id"] in verdicts:
            status = verdicts[l["id"]].get("status") if verdicts[l["id"]].get("status") in STEP_STATUSES else "unclear"
            note = str(verdicts[l["id"]].get("note") or "")[:MAX_NOTE_CHARS]
        else:
            status, note = "unclear", "" if result.get("analysisFailed") else "not judged"
        steps.append({**step_base(l), "status": status, "note": note})
    return {**result, "steps": steps}


# ---------------------------------------------------------------------- chat / tutor

def notebook_context(twin: dict | None) -> str:
    lines = twin_lines(twin)
    if not twin or not lines:
        return "NOTEBOOK: no readable page available."
    return (f"NOTEBOOK (one photo taken {twin.get('captured_at', 'recently')}, transcribed verbatim, reading order):\n"
            + _lines_block(lines))


def reading_context(readings: list[dict], include_text: bool) -> str:
    if not readings:
        return "READING: no recent pages."
    rows = []
    for r in readings[:MAX_READING_ITEMS]:
        row = f"- {r.get('title') or r.get('url')} ({r.get('url')}; {int(r.get('durationSec') or 0)} s)"
        text = (r.get("text") or r.get("excerpt") or "") if include_text else ""
        if text:
            row += f"\n  text: {text[:MAX_READING_TEXT_CHARS]}"
        rows.append(row)
    return "READING (recent pages" + (", text shared with consent" if include_text else ", titles only") + "):\n" + "\n".join(rows)


def _clean_history(history: Any) -> list[dict]:
    out = []
    for turn in history or []:
        if not isinstance(turn, dict):
            continue
        role, content = turn.get("role"), turn.get("content")
        if role in ("user", "assistant") and isinstance(content, str) and content.strip():
            out.append({"role": role, "content": content.strip()})
    # Anthropic wants alternating roles starting with user; drop leading assistant turns and merge duplicates.
    merged: list[dict] = []
    for t in out[-MAX_HISTORY_TURNS:]:
        if not merged and t["role"] == "assistant":
            continue
        if merged and merged[-1]["role"] == t["role"]:
            merged[-1] = {"role": t["role"], "content": merged[-1]["content"] + "\n\n" + t["content"]}
        else:
            merged.append(t)
    return merged


def respond(message: str, history: Any, *, twin: dict | None, readings: list[dict], include_text: bool,
            context_notes: list[str] | None = None, timeout_s: float | None = None) -> dict:
    """One model call → {reply, petExpression}. Raises llm.LLMError."""
    context = "\n\n".join([notebook_context(twin), reading_context(readings, include_text), *(context_notes or [])])
    turns = _clean_history(history)
    user = f"{context}\n\nSTUDENT ({now_iso()}): {message.strip()}"
    messages = turns + [{"role": "user", "content": user}]
    out = llm.ask_json(CHAT_SYSTEM, messages, CHAT_SCHEMA, stage="bridge.chat",
                       timeout_s=timeout_s or float(cfg("bridge.chat_timeout_s", 40.0)))
    pet = out.get("petExpression") if out.get("petExpression") in PET_EXPRESSIONS else "neutral"
    return {"reply": str(out.get("reply") or "").strip(), "petExpression": pet}


def sources_for(twin: dict | None, readings: list[dict]) -> list[dict]:
    from bridge.compat import file_url

    out: list[dict] = []
    if twin and twin.get("lines"):
        image = twin.get("image") or {}
        out.append({"type": "notebook", "id": twin.get("snapshot_id"), "title": "Notebook snapshot",
                    "capturedAt": twin.get("captured_at"),
                    "imageUrl": file_url(image.get("dewarped_path") or image.get("original_path"))})
    for r in readings[:MAX_READING_ITEMS]:
        out.append({"type": "reading", "id": r.get("id"), "title": r.get("title") or r.get("url"), "url": r.get("url")})
    return out


class Sessions:
    """In-memory conversation history per Pip sessionId (anonymous per-tab id)."""

    def __init__(self, turns: int = MAX_HISTORY_TURNS) -> None:
        self._lock = threading.Lock()
        self._data: dict[str, deque] = {}
        self._turns = turns

    def history(self, session_id: str) -> list[dict]:
        with self._lock:
            return list(self._data.get(session_id, ()))

    def record(self, session_id: str, user: str, assistant: str) -> None:
        if not session_id:
            return
        with self._lock:
            q = self._data.setdefault(session_id, deque(maxlen=self._turns))
            q.append({"role": "user", "content": user})
            q.append({"role": "assistant", "content": assistant})

    def clear(self) -> None:
        with self._lock:
            self._data.clear()


sessions = Sessions()
