"""Step 2: verbatim prompt, example bank, cacheable prefix."""
import json
from pathlib import Path

from jsonschema import Draft202012Validator

from transcribe import prompts
from transcribe.examples import BANK_PATH, HERE, example_messages, load_bank, prefix, system_blocks
from transcribe.schema import MODEL_LINE_SCHEMA

ALL_PROMPTS = [prompts.SYSTEM_PROMPT, prompts.PAGE_PASS_PROMPT, prompts.LINE_PASS_PROMPT,
               prompts.LINE_PASS_PROMPT_NO_CONTEXT, prompts.REREAD_PROMPT, prompts.CROSSED_OUT_PROMPT]


def test_prompts_never_ask_the_model_to_help():
    for p in ALL_PROMPTS:
        low = p.lower()
        for bad in prompts.FORBIDDEN_PROMPT_WORDS:
            assert bad not in low, f"forbidden wording {bad!r} in prompt"
    assert "exactly" in prompts.SYSTEM_PROMPT and "illegible" in prompts.SYSTEM_PROMPT


def test_bank_has_required_coverage():
    bank = load_bank()
    assert 5 <= len(bank) <= 8
    assert sum(1 for ex in bank if ex["mistake"]) >= 3
    names = {ex["name"] for ex in bank}
    assert "ex_crossed_out" in names and "ex_ambiguous_1_l" in names and "ex_fraction" in names and "ex_blank" in names
    for ex in bank:
        assert Path(ex["image_path"]).exists(), ex["name"]
        Draft202012Validator(MODEL_LINE_SCHEMA).validate(ex["output"])


def test_mistake_examples_are_wrong_math_kept_verbatim():
    by = {ex["name"]: ex["output"]["latex"] for ex in load_bank()}
    assert by["ex_product_rule_mistake"] == "\\frac{d}{dx}x^{2}\\sin x=2x\\cos x"
    assert by["ex_distribution_mistake"] == "(x+3)^{2}=x^{2}+9"
    assert by["ex_chain_rule_mistake"] == "\\frac{d}{dx}\\sin(x^{2})=\\cos(x^{2})"
    assert by["ex_blank"] == ""


def test_prefix_is_stable_and_cached_at_the_end():
    sys1, msgs1 = prefix()
    sys2, msgs2 = prefix()
    assert json.dumps(sys1) == json.dumps(sys2) and json.dumps(msgs1) == json.dumps(msgs2)
    assert sys1[0]["cache_control"] == {"type": "ephemeral"}
    assert msgs1[0]["role"] == "user" and msgs1[-1]["role"] == "assistant"
    cached = [b for m in msgs1 for b in m["content"] if b.get("cache_control")]
    assert len(cached) == 1 and cached[0] is msgs1[-1]["content"][0]
    assert all(msgs1[i]["role"] == ("user" if i % 2 == 0 else "assistant") for i in range(len(msgs1)))
    # at most 4 breakpoints per request: system + last example leaves room for 2 more
    assert len(cached) + sum(1 for b in sys1 if b.get("cache_control")) <= 4
