"""transcribe_page: two independent readings per line, alignment, agreement, re-read, verbatim guard.

Phases (model calls run in a thread pool of `transcribe.max_parallel`):
  0. prep: ink density / crop hash per T2 line; empty crops never reach the model;
     unchanged crops (hash seen in previous_twin) reuse the previous reading.
  1. page pass (T1 tiles, context) ∥ line pass per line (context crop, detail).
  2. align page-pass lines to T2 lines (DP); plan per line.
  3. re-reads (3× zoom, both candidates) ∥ crossed-out yes/no for status_hint == 'unsure'.
  4. finalize: confidence, uncertain spans, verbatim guard, status.
"""
from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from statistics import median

from transcribe import decide
from transcribe.align import align
from transcribe.compat import Timer, cfg, log
from transcribe.ink import crop_hash, ink_density, is_empty
from transcribe.lines import make_line
from transcribe.matching import iou
from transcribe.readings import ask_crossed_out, get_tiles, line_pass, page_pass, reread

QUALITY_BAD_CAP = 0.4
PAGE_PASS_SKIP_BELOW = 2  # incremental update touching ≤ this many lines: context crops suffice, skip the page pass
CACHE_MIN_IOU = 0.3
TALL_FACTOR = 1.5
SMALL_FACTOR = 1.5


@dataclass
class Prepped:
    i: int
    line: dict
    density: float
    empty: bool
    hash: str
    tall: bool
    small: bool
    cached: dict | None = None


def _clean(line: dict, i: int) -> dict:
    """Never trust another terminal's record blindly: fill what is missing so nothing downstream raises."""
    bbox = line.get("bbox") if isinstance(line.get("bbox"), (list, tuple)) and len(line.get("bbox") or []) == 4 else [0, 0, 0, 0]
    order = line.get("order")
    return {**line, "bbox": [float(v) for v in bbox], "order": int(order) if isinstance(order, (int, float)) else i,
            "crop_path": line.get("crop_path") or "", "context_crop_path": line.get("context_crop_path") or ""}


def _prep(lines: list[dict], min_h: float) -> list[Prepped]:
    cleaned = sorted((_clean(l, i) for i, l in enumerate(lines)), key=lambda l: (l["order"], l["bbox"][1]))
    heights = [l["bbox"][3] for l in cleaned if l["bbox"][3] > 0] or [min_h]
    med = median(heights)
    out = []
    for i, l in enumerate(cleaned):
        density = float(l["ink_density"]) if l.get("ink_density") is not None else ink_density(l["crop_path"])
        h = l["bbox"][3]
        out.append(Prepped(i, l, density, is_empty(density), crop_hash(l["crop_path"]),
                           tall=h > TALL_FACTOR * med, small=h < SMALL_FACTOR * min_h))
    return out


def _reusable(prev: dict) -> bool:
    """Only readings that actually came from the model are worth caching: never a failed call."""
    notes = (prev.get("readings") or {}).get("notes") or []
    return prev.get("crop_hash") not in (None, "empty", "blank") and prev.get("confidence", 0) > 0 \
        and "no_reading" not in notes


def _attach_cache(prepped: list[Prepped], previous_twin: dict | None) -> None:
    if not previous_twin:
        return
    prev = [p for p in previous_twin.get("lines", []) if _reusable(p)]
    for p in prepped:
        if p.empty or p.hash in ("empty", "blank"):
            continue
        p.cached = next((q for q in prev if q["crop_hash"] == p.hash and iou(q["bbox"], p.line["bbox"]) >= CACHE_MIN_IOU), None)


def _timed(fn, *args):
    """Run fn(*args) and return (result, elapsed_ms) — per-call latency for the viewer's detail panel."""
    t0 = time.perf_counter()
    return fn(*args), round((time.perf_counter() - t0) * 1000.0, 1)


def _region_for(line: dict, regions: list[dict]) -> str:
    if line.get("region_id"):
        return str(line["region_id"])
    x, y, w, h = line["bbox"]
    cx, cy = x + w / 2, y + h / 2
    for r in regions:
        rx, ry, rw, rh = r["bbox"]
        if rx <= cx <= rx + rw and ry <= cy <= ry + rh:
            return str(r["id"])
    return str(regions[0]["id"]) if regions else "R0"


def _status(hint: str, crossed_answer: bool | None, illegible: bool) -> str:
    if illegible:
        return "illegible"
    if hint == "crossed_out" or (hint == "unsure" and crossed_answer is True):
        return "crossed_out"
    return "active"


def transcribe_page(dewarped_path: str, layout: dict, previous_twin: dict | None = None) -> list[dict]:
    """Lines per page_twin.schema.json#/properties/lines (without first_seen/last_changed — build_page_twin sets those).
    Only re-transcribes lines whose crop changed since previous_twin (crop hash cache)."""
    with Timer("transcribe.page") as timer:
        lines = [l for l in (layout.get("lines") or []) if isinstance(l, dict)]
        regions = list(layout.get("regions") or [])
        quality = layout.get("quality") or {}
        issues = len(quality.get("issues") or [])
        threshold = float(cfg("transcribe.agreement_threshold", 0.92))
        max_parallel = max(1, int(cfg("transcribe.max_parallel", 6)))
        min_h = float(cfg("layout.min_line_height_px", 28))

        prepped = _prep(lines, min_h)
        _attach_cache(prepped, previous_twin)
        to_model = [p for p in prepped if not p.empty and p.cached is None]
        unsure = [p for p in prepped if p.line.get("status_hint") == "unsure" and not p.empty and p.cached is None]

        skip_page = bool(previous_twin) and len(to_model) <= int(cfg("transcribe.page_pass_skip_below", PAGE_PASS_SKIP_BELOW))
        with ThreadPoolExecutor(max_workers=max_parallel) as ex:
            page_future = ex.submit(_timed, page_pass, get_tiles(dewarped_path)) if to_model and not skip_page else None
            line_futures = {p.i: ex.submit(_timed, line_pass, p.line) for p in to_model}
            crossed_futures = {p.i: ex.submit(_timed, ask_crossed_out, p.line["crop_path"]) for p in unsure}
            page_readings, page_ms = page_future.result() if page_future else (None, 0.0)
            page_readings = page_readings or []
            timings: dict[int, dict] = {p.i: {"page_pass": page_ms} for p in to_model}
            line_readings = {}
            for i, f in line_futures.items():
                line_readings[i], timings[i]["line_pass"] = f.result()

            ordered = [p.i for p in to_model]
            alignment = align(page_readings, [line_readings[i] or {} for i in ordered])
            page_for = {i: (page_readings[k] if k is not None else None)
                        for i, k in zip(ordered, alignment.page_index_for_line)}
            plans = {i: decide.plan(line_readings[i], page_for[i], threshold=threshold,
                                    tall=next(p.tall for p in to_model if p.i == i)) for i in ordered}
            reread_futures = {i: ex.submit(_timed, reread, prepped[i].line["crop_path"], pl.line_r, pl.page_r)
                              for i, pl in plans.items() if pl.needs_reread}
            rereads, crossed = {}, {}
            for i, f in reread_futures.items():
                rereads[i], timings[i]["reread"] = f.result()
            for i, f in crossed_futures.items():
                crossed[i], ms = f.result()
                timings.setdefault(i, {})["crossed_out"] = ms

        out: list[dict] = []
        context: list[str] = []
        for p in prepped:
            out.append(_build(p, plans.get(p.i), rereads.get(p.i), crossed.get(p.i), regions, context, issues, quality,
                              timings.get(p.i, {})))
            if out[-1]["latex"]:
                context.append(out[-1]["latex"])
        timer.extra.update(lines=len(lines), modeled=len(to_model), cached=sum(1 for p in prepped if p.cached),
                           empty=sum(1 for p in prepped if p.empty), rereads=len(rereads), page_pass=not skip_page,
                           split_flags=len(alignment.covers_split) if to_model else 0)
    if previous_twin is not None and to_model:
        # T4's latency panel: time to read the lines that changed since the last snapshot.
        log("transcribe.incremental", timer.ms, new_lines=len(to_model), rereads=len(rereads), page_pass=not skip_page)
    return out


def _build(p: Prepped, pl, rr, crossed_answer, regions, context, issues, quality, timings: dict) -> dict:
    line, hint = p.line, line_hint(p.line)
    common = {"region_id": _region_for(line, regions), "order": int(line.get("order", p.i)), "bbox": line["bbox"]}
    extra = {"crop_hash": p.hash, "crop_path": line.get("crop_path"), "context_crop_path": line.get("context_crop_path"),
             "status_hint": hint, "ink_density": round(p.density, 4), "latency_ms": dict(timings),
             "reread": rr}
    if p.cached is not None:
        q = p.cached
        status = q["status"] if hint == "unsure" else _status(hint, None, q["status"] == "illegible")
        return make_line(**common, status=status, kind=q["kind"], latex=q["latex"], text=q["text"],
                         confidence=q["confidence"], uncertain_spans=q["uncertain_spans"], parse_ok=q["parse_ok"],
                         extra={**extra, "readings": {**(q.get("readings") or {}), "cached": True}})
    if p.empty:
        return make_line(**common, status="illegible", kind="text", latex="", text="", confidence=0.0,
                         extra={**extra, "readings": {"notes": ["empty_crop"]}})
    r = decide.finalize(pl, rr, context=context, order=common["order"], quality_issues=issues, small_crop=p.small)
    conf = min(r["confidence"], QUALITY_BAD_CAP) if quality and quality.get("ok") is False else r["confidence"]
    return make_line(**common, status=_status(hint, crossed_answer, r["illegible"]), kind=r["kind"], latex=r["latex"],
                     text=r["text"], confidence=conf, uncertain_spans=r["uncertain_spans"], parse_ok=r["parse_ok"],
                     extra={**extra, "readings": {**r["readings"], "cached": False}})


def line_hint(line: dict) -> str:
    hint = line.get("status_hint", "active")
    return hint if hint in ("active", "crossed_out", "unsure") else "unsure"
