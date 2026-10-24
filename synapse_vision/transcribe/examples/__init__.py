"""The few-shot example bank: (crop image, exact JSON) pairs, assembled into a cacheable prefix.

Default layout (text examples — measured H+7: the 8 example *images* in the history cost 8–35 s per call
even on cache hits, text examples cost nothing):
    system      = [SYSTEM_PROMPT, EXAMPLES_AS_TEXT (cache_control)]
    messages    = [<the real request>]
Opt-in (`transcribe.image_examples: true`): the images as user/assistant turns before the request.
"""
from __future__ import annotations

import base64
import json
from functools import lru_cache
from pathlib import Path

from transcribe.compat import cfg
from transcribe.prompts import LINE_PASS_PROMPT_NO_CONTEXT, SYSTEM_PROMPT

HERE = Path(__file__).resolve().parent
BANK_PATH = HERE / "bank.json"
CACHE_CONTROL = {"type": "ephemeral"}


MAX_IMAGE_SIDE = 2000  # the API downsizes above ~1568 px anyway; stay well under its hard size limit
MAX_IMAGE_BYTES = 4_500_000


def image_block(path: str | Path) -> dict:
    p = Path(path)
    media = "image/png" if p.suffix.lower() == ".png" else "image/jpeg"
    raw = p.read_bytes()
    shrunk = _shrink_if_needed(p, raw)
    if shrunk is not None:
        raw, media = shrunk, "image/jpeg"
    data = base64.standard_b64encode(raw).decode("ascii")
    return {"type": "image", "source": {"type": "base64", "media_type": media, "data": data}}


def _shrink_if_needed(p: Path, raw: bytes) -> bytes | None:
    """JPEG re-encode, long side ≤ MAX_IMAGE_SIDE, when the file is too large for one request."""
    import cv2

    img = cv2.imread(str(p), cv2.IMREAD_COLOR)
    if img is None:
        return None
    h, w = img.shape[:2]
    if max(h, w) <= MAX_IMAGE_SIDE and len(raw) <= MAX_IMAGE_BYTES:
        return None
    f = min(1.0, MAX_IMAGE_SIDE / max(h, w))
    if f < 1.0:
        img = cv2.resize(img, None, fx=f, fy=f, interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 90])
    return buf.tobytes() if ok else None


@lru_cache(maxsize=1)
def load_bank() -> tuple[dict, ...]:
    bank = json.loads(BANK_PATH.read_text(encoding="utf-8"))
    return tuple({**ex, "image_path": str(HERE / ex["image"])} for ex in bank)


def dumps_stable(obj) -> str:
    """Deterministic JSON so the cached prefix never changes byte-for-byte between calls."""
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


@lru_cache(maxsize=1)
def examples_text() -> str:
    """The bank as text: what the handwriting shows → the exact JSON. Same verbatim-examples idea, zero image cost."""
    parts = ["Examples of correct output (each shows what the handwriting literally says, then the exact JSON):"]
    for i, ex in enumerate(load_bank(), 1):
        parts.append(f"{i}. Handwriting shows: {ex['shows']}\n   Output: {dumps_stable(ex['output'])}")
    return "\n".join(parts)


@lru_cache(maxsize=1)
def system_blocks() -> tuple[dict, ...]:
    """SYSTEM_PROMPT + text examples; cache_control on the last block (the whole system is the stable prefix)."""
    return ({"type": "text", "text": SYSTEM_PROMPT},
            {"type": "text", "text": examples_text(), "cache_control": CACHE_CONTROL})


@lru_cache(maxsize=1)
def system_blocks_for_image_mode() -> tuple[dict, ...]:
    return ({"type": "text", "text": SYSTEM_PROMPT, "cache_control": CACHE_CONTROL},)


@lru_cache(maxsize=1)
def example_messages() -> tuple[dict, ...]:
    """User/assistant turns for every bank entry; the last assistant block carries cache_control."""
    msgs: list[dict] = []
    bank = load_bank()
    for i, ex in enumerate(bank):
        msgs.append({"role": "user", "content": [image_block(ex["image_path"]),
                                                  {"type": "text", "text": LINE_PASS_PROMPT_NO_CONTEXT}]})
        block = {"type": "text", "text": dumps_stable(ex["output"])}
        if i == len(bank) - 1:
            block["cache_control"] = CACHE_CONTROL
        msgs.append({"role": "assistant", "content": [block]})
    return tuple(msgs)


def prefix() -> tuple[list[dict], list[dict]]:
    """(system, messages) to prepend to every call. Fresh lists so callers may extend them."""
    if cfg("transcribe.image_examples", False):
        return [dict(b) for b in system_blocks_for_image_mode()], [dict(m) for m in example_messages()]
    return [dict(b) for b in system_blocks()], []
