"""Step 3: two readings, alignment, re-read, verbatim guard, crossed-out query, empty-crop guard, cache."""
import json

import pytest

from transcribe import guard
from transcribe.examples import HERE
from transcribe.page import transcribe_page
from transcribe.tests.fakes import CORRECT_PRODUCT_RULE, FakeModel, example_layout, line_validator

NAMES = ["ex_text_line", "ex_product_rule_mistake", "ex_crossed_out", "ex_fraction", "ex_blank", "ex_ambiguous_1_l"]
PRODUCT = str(HERE / "ex_product_rule_mistake.png")


@pytest.fixture
def fake(monkeypatch, tmp_path):
    monkeypatch.setattr(guard, "GUARD_LOG", tmp_path / "verbatim_guard.jsonl")
    return FakeModel().install(monkeypatch, tiles=[str(HERE / f"{n}.png") for n in NAMES])


def _run(fake, hints=None, previous=None):
    layout = example_layout(NAMES, hints)
    return transcribe_page("page.png", layout, previous)


def test_lines_validate_and_keep_order(fake):
    lines = _run(fake)
    v = line_validator()
    assert [l["order"] for l in lines] == list(range(len(NAMES)))
    for l in lines:
        assert "first_seen" not in l
        v.validate(l)


def test_blank_crop_never_reaches_the_model(fake):
    lines = _run(fake)
    blank = lines[NAMES.index("ex_blank")]
    assert blank["status"] == "illegible" and blank["latex"] == "" and blank["confidence"] == 0.0
    assert fake.calls["line"] == len(NAMES) - 1


def test_agreement_gives_high_confidence_and_verbatim_mistake(fake):
    lines = _run(fake)
    pr = lines[NAMES.index("ex_product_rule_mistake")]
    assert pr["latex"] == "\\frac{d}{dx}x^{2}\\sin x=2x\\cos x"
    assert pr["confidence"] >= 0.85 and pr["parse_ok"] is True


def test_fraction_lines_are_rereread_even_when_readings_agree(fake):
    _run(fake)
    reread_crops = {args[0] for args in fake.reread_args}
    assert PRODUCT in reread_crops and str(HERE / "ex_fraction.png") in reread_crops
    assert str(HERE / "ex_ambiguous_1_l.png") not in reread_crops


def test_disagreement_prefers_reread_not_the_nicer_math(fake):
    fake.page_override[PRODUCT] = {"latex": CORRECT_PRODUCT_RULE, "text": "d/dx x^2 sin x = 2x sin x + x^2 cos x",
                                   "kind": "math", "illegible": False, "uncertain": []}
    fake.reread_choice = "A"
    lines = _run(fake)
    pr = lines[NAMES.index("ex_product_rule_mistake")]
    assert pr["latex"] == "\\frac{d}{dx}x^{2}\\sin x=2x\\cos x"
    assert 0.6 <= pr["confidence"] <= 0.8
    assert pr["uncertain_spans"], "differing spans must be flagged"
    events = [json.loads(l) for l in guard.GUARD_LOG.read_text().splitlines()]
    assert len(events) == 1 and events[0]["nicer"] == "B" and events[0]["chosen_is_nicer"] is False


def test_choosing_the_nicer_reading_caps_confidence_and_flags_span(fake):
    fake.page_override[PRODUCT] = {"latex": CORRECT_PRODUCT_RULE, "text": "", "kind": "math", "illegible": False, "uncertain": []}
    fake.reread_choice = "B"
    pr = _run(fake)[NAMES.index("ex_product_rule_mistake")]
    assert pr["latex"] == CORRECT_PRODUCT_RULE
    assert pr["confidence"] <= 0.7 and pr["uncertain_spans"]
    assert json.loads(guard.GUARD_LOG.read_text().splitlines()[0])["chosen_is_nicer"] is True


def test_reread_failure_keeps_line_pass_with_low_confidence(fake, monkeypatch):
    fake.page_override[PRODUCT] = {"latex": CORRECT_PRODUCT_RULE, "text": "", "kind": "math", "illegible": False, "uncertain": []}
    import transcribe.page as page_mod

    monkeypatch.setattr(page_mod, "reread", lambda *a: None)
    pr = _run(fake)[NAMES.index("ex_product_rule_mistake")]
    assert pr["latex"] == "\\frac{d}{dx}x^{2}\\sin x=2x\\cos x" and pr["confidence"] <= 0.5 and pr["uncertain_spans"]


def test_crossed_out_hint_and_unsure_query(fake):
    lines = _run(fake, hints={"ex_crossed_out": "unsure", "ex_fraction": "crossed_out"})
    assert lines[NAMES.index("ex_crossed_out")]["status"] == "crossed_out"
    assert lines[NAMES.index("ex_crossed_out")]["latex"] == "=2\\cos x"  # still transcribed
    assert lines[NAMES.index("ex_fraction")]["status"] == "crossed_out"
    assert fake.calls["crossed"] == 1
    fake.crossed_answer = False
    assert _run(fake, hints={"ex_crossed_out": "unsure"})[NAMES.index("ex_crossed_out")]["status"] == "active"


def test_model_uncertain_spans_become_offsets(fake):
    amb = _run(fake)[NAMES.index("ex_ambiguous_1_l")]
    assert amb["latex"] == "2l+1=7"
    assert {"start": 1, "end": 2, "alternatives": ["1"]} in amb["uncertain_spans"]


def test_crop_hash_cache_skips_unchanged_lines(fake):
    first = _run(fake)
    before = dict(fake.calls)
    previous = {"lines": [{**l, "first_seen": "t", "last_changed": "t", "id": f"L{i}"} for i, l in enumerate(first)]}
    second = _run(fake, previous=previous)
    assert fake.calls == before, "unchanged crops must not hit the model"
    assert all(l["readings"].get("cached") for l in second if l["status"] != "illegible")
    assert [l["latex"] for l in second] == [l["latex"] for l in first]


def test_bad_quality_caps_confidence(fake):
    layout = example_layout(NAMES)
    layout["quality"] = {"ok": False, "issues": ["blur"]}
    lines = transcribe_page("page.png", layout)
    assert all(l["confidence"] <= 0.4 for l in lines)


def test_which_is_nicer_on_the_demo_page():
    ctx = ["f(x)=x^{2}\\sin x"]
    assert guard.which_is_nicer("f'(x)=2x\\cdot\\cos x", "f'(x)=2x\\sin x+x^{2}\\cos x", ctx) == "B"
    assert guard.which_is_nicer("f'(x)=2x\\cdot\\cos x", "f'(x)=2x\\cos x", ctx) is None
    assert guard.which_is_nicer("(x+3)^{2}=x^{2}+9", "(x+3)^{2}=x^{2}+6x+9", []) == "B"


def test_small_incremental_update_skips_the_page_pass(fake):
    first = _run(fake)
    previous = {"lines": [{**l, "first_seen": "t", "last_changed": "t", "id": f"L{i}"} for i, l in enumerate(first)]}
    # one line "changes": drop its hash so it must be re-read
    previous["lines"][NAMES.index("ex_ambiguous_1_l")]["crop_hash"] = "different"
    before = dict(fake.calls)
    second = _run(fake, previous=previous)
    assert fake.calls["page"] == before["page"], "page pass skipped for a one-line change"
    assert fake.calls["line"] == before["line"] + 1
    amb = second[NAMES.index("ex_ambiguous_1_l")]
    assert amb["latex"] == "2l+1=7" and amb["confidence"] <= 0.7 and "single_pass" in amb["readings"]["notes"]


def test_one_character_difference_is_a_disagreement(fake):
    fake.page_override[PRODUCT] = {"latex": "\\frac{d}{dx}x^{2}\\sin x=2x\\cos x+5", "text": "", "kind": "math",
                                   "illegible": False, "uncertain": []}
    fake.reread_choice = "A"
    pr = _run(fake)[NAMES.index("ex_product_rule_mistake")]
    assert pr["latex"] == "\\frac{d}{dx}x^{2}\\sin x=2x\\cos x" and pr["confidence"] < 0.9
    assert any(s["alternatives"] == ["+5"] for s in pr["uncertain_spans"])


def test_sign_flip_on_a_long_line_is_rereread_and_flagged(fake, monkeypatch):
    long_a = {"latex": "3x^{2}+2x+5=4x-7+x^{2}", "text": "", "kind": "math", "illegible": False, "uncertain": []}
    long_b = {**long_a, "latex": "3x^{2}+2x-5=4x-7+x^{2}"}
    amb = str(HERE / "ex_ambiguous_1_l.png")
    fake.by_image[amb] = long_a
    fake.page_override[amb] = long_b
    import transcribe.page as page_mod

    monkeypatch.setattr(page_mod, "reread", lambda *a: None)  # re-read unavailable
    line = _run(fake)[NAMES.index("ex_ambiguous_1_l")]
    assert line["latex"] == long_a["latex"] and line["confidence"] <= 0.6
    assert any(s["alternatives"] == ["-"] for s in line["uncertain_spans"])


def test_failed_model_call_is_not_cached_and_does_not_overwrite(fake, monkeypatch):
    import transcribe.page as page_mod
    from transcribe.matching import match_to_previous

    good = _run(fake)
    previous = {"page_id": "page_x", "lines": [{**l, "first_seen": "t", "last_changed": "t", "id": f"L{i}"} for i, l in enumerate(good)]}
    monkeypatch.setattr(page_mod, "line_pass", lambda line: None)
    monkeypatch.setattr(page_mod, "page_pass", lambda tiles: None)
    broken = _run(fake)  # every call fails: no_reading lines
    assert all(l["status"] == "illegible" and "no_reading" in l["readings"]["notes"] for l in broken if l["order"] != NAMES.index("ex_blank"))
    # 1) matching keeps the good readings instead of marking them edited
    m = match_to_previous(broken, previous, "now", quality_ok=True)
    pr = next(l for l in m.lines if l["id"] == "L1")
    assert pr["latex"] == "\\frac{d}{dx}x^{2}\\sin x=2x\\cos x" and m.changes["edited"] == []
    # 2) a twin built from failed calls is never used as a cache source
    prev_broken = {"page_id": "page_x", "lines": [{**l, "first_seen": "t", "last_changed": "t", "id": f"L{i}"} for i, l in enumerate(broken)]}
    monkeypatch.setattr(page_mod, "line_pass", fake.line_pass)
    monkeypatch.setattr(page_mod, "page_pass", fake.page_pass)
    before = fake.calls["line"]
    again = _run(fake, previous=prev_broken)
    assert fake.calls["line"] > before and again[NAMES.index("ex_product_rule_mistake")]["confidence"] > 0.8


def test_line_pass_failure_falls_back_to_the_page_reading(fake, monkeypatch):
    import transcribe.page as page_mod

    real = fake.line_pass
    monkeypatch.setattr(page_mod, "line_pass", lambda line: None if line["crop_path"] == PRODUCT else real(line))
    pr = _run(fake)[NAMES.index("ex_product_rule_mistake")]
    assert pr["latex"] == "\\frac{d}{dx}x^{2}\\sin x=2x\\cos x" and "single_pass" in pr["readings"]["notes"]


def test_malformed_t2_lines_do_not_crash(fake):
    layout = example_layout(NAMES)
    layout["lines"].append({"bbox": None, "crop_path": None, "order": None, "status_hint": "weird"})
    layout["lines"].append("garbage")
    lines = transcribe_page("page.png", layout)
    assert len(lines) == len(NAMES) + 1 and lines[-1]["status"] == "illegible"


def test_viewer_fields_per_line_and_incremental_stage(fake, monkeypatch):
    import transcribe.page as page_mod

    logged = []
    monkeypatch.setattr(page_mod, "log", lambda stage, ms, **kw: logged.append((stage, ms, kw)))
    first = _run(fake)
    pr = first[NAMES.index("ex_product_rule_mistake")]
    assert pr["crop_path"] == PRODUCT and pr["context_crop_path"] == PRODUCT
    assert set(pr["latency_ms"]) >= {"page_pass", "line_pass", "reread"} and pr["reread"]["choice"] == "A"
    assert not any("incremental" in s for s, _, _ in logged), "first snapshot is not incremental"
    previous = {"lines": [{**l, "first_seen": "t", "last_changed": "t", "id": f"L{i}"} for i, l in enumerate(first)]}
    previous["lines"][NAMES.index("ex_ambiguous_1_l")]["crop_hash"] = "changed"
    _run(fake, previous=previous)
    inc = [(s, kw) for s, _, kw in logged if "incremental" in s]
    assert len(inc) == 1 and inc[0][1]["new_lines"] == 1
