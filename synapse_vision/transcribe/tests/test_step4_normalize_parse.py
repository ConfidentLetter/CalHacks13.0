"""Step 4: comparison-only normalization, SymPy parse signal, strict model-response validation + retry."""
import json
from types import SimpleNamespace

import pytest

import transcribe.client as client
from transcribe import normalize_latex, parse_ok
from transcribe.schema import MODEL_LINE_SCHEMA


@pytest.mark.parametrize("a,b", [
    ("2x\\cdot\\cos x", "2x \\times \\cos x"),
    ("2x\\cdot\\cos x", "2x*\\cos(x)"),
    ("\\left(x+1\\right)^{2}", "(x+1)^2"),
    ("x^{2}\\,\\sin x", "x^2 \\sin x"),
    ("a−b", "a-b"),
    ("\\dfrac{1}{2}", "\\frac{1}{2}"),
    ("\\sin(x)", "\\sin x"),
    ("f'(x)", "f^{\\prime}(x)"),
    ("2 · 0", "2\\cdot 0"),
])
def test_normalize_unifies_notation(a, b):
    assert normalize_latex(a) == normalize_latex(b)


@pytest.mark.parametrize("a,b", [
    ("2x\\cos x", "2x\\sin x"),            # different function
    ("x^{2}+9", "x^{2}+6x+9"),              # a mistake stays different from the fix
    ("2\\cos x", "z\\cos x"),               # 2 vs z
    ("f'(x)=2x\\cos x", "f'(x)=2x\\sin x+x^{2}\\cos x"),
])
def test_normalize_never_changes_meaning(a, b):
    assert normalize_latex(a) != normalize_latex(b)


def test_normalize_is_idempotent_and_handles_empty():
    assert normalize_latex("") == ""
    s = "\\left(x+1\\right)\\cdot\\sin(x)"
    assert normalize_latex(normalize_latex(s)) == normalize_latex(s)


@pytest.mark.parametrize("latex", ["x^{2}", "f'(x)=2x\\cdot\\cos x", "\\frac{x^{2}+1}{2x}", "(x+3)^{2}=x^{2}+9",
                                   "f'(0)=2\\cdot 0\\cdot\\cos 0=0"])
def test_parse_ok_true_on_well_formed_including_wrong_math(latex):
    assert parse_ok(latex) is True


@pytest.mark.parametrize("latex", ["", "\\frac{1}{", "x^{2}=", "((x"])
def test_parse_ok_false_on_broken(latex):
    assert parse_ok(latex) is False


class _Resp:
    def __init__(self, text, stop="end_turn"):
        self.content = [SimpleNamespace(type="text", text=text)]
        self.stop_reason = stop
        self.usage = SimpleNamespace(cache_read_input_tokens=0, cache_creation_input_tokens=0, input_tokens=1, output_tokens=1)


def _install(monkeypatch, responses):
    calls = []

    def fake_create(c, *, system, messages, schema, max_tokens):
        calls.append(messages)
        return responses.pop(0)

    monkeypatch.setattr(client, "get_client", lambda: object())
    monkeypatch.setattr(client, "_create", fake_create)
    return calls


def test_invalid_json_is_retried_once_with_the_error(monkeypatch):
    good = {"latex": "x", "text": "x", "kind": "math", "illegible": False, "uncertain": []}
    calls = _install(monkeypatch, [_Resp("{not json"), _Resp(json.dumps(good))])
    assert client.ask_json([{"type": "text", "text": "q"}], MODEL_LINE_SCHEMA, stage="t") == good
    assert len(calls) == 2
    retry_text = calls[1][-1]["content"][0]["text"]
    assert "not valid" in retry_text and "invalid JSON" in retry_text


def test_schema_violation_is_retried_then_raises(monkeypatch):
    bad = {"latex": "x", "text": "x", "kind": "equation", "illegible": False, "uncertain": []}
    _install(monkeypatch, [_Resp(json.dumps(bad)), _Resp(json.dumps(bad))])
    with pytest.raises(client.ModelResponseError):
        client.ask_json([{"type": "text", "text": "q"}], MODEL_LINE_SCHEMA, stage="t")


def test_code_fences_are_tolerated(monkeypatch):
    good = {"latex": "", "text": "hi", "kind": "text", "illegible": False, "uncertain": []}
    _install(monkeypatch, [_Resp("```json\n" + json.dumps(good) + "\n```")])
    assert client.ask_json([{"type": "text", "text": "q"}], MODEL_LINE_SCHEMA, stage="t") == good


def test_refusal_raises(monkeypatch):
    _install(monkeypatch, [_Resp("", stop="refusal")])
    with pytest.raises(client.ModelResponseError):
        client.ask_json([{"type": "text", "text": "q"}], MODEL_LINE_SCHEMA, stage="t")


def test_strict_schema_has_no_additional_properties():
    strict = client._strict(MODEL_LINE_SCHEMA)
    assert strict["additionalProperties"] is False
    assert strict["properties"]["uncertain"]["items"]["additionalProperties"] is False


@pytest.mark.parametrize("latex", ["\\left(x+1\\right)^{2}=1", "x\\leq 2", "a\\neq b", "\\left(x+1\\right)^2"])
def test_parse_ok_handles_left_right_and_relations(latex):
    assert parse_ok(latex) is True
