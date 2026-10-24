"""Verbatim guard (TTYSC reflection-agent idea, aimed at the known failure mode).

When two readings of a line disagree and one of them is mathematically "nicer" (SymPy says it is a
true identity / the correct derivative while the other is not), we must NOT prefer the nice one.
The decision is made by the 3× re-read; this module only (a) detects the situation, (b) forces an
uncertain span when the chosen reading is the nice one, and (c) logs every case to
runtime/debug/verbatim_guard.jsonl so Henry can review and T4 can count them.
"""
from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeout
import threading
import warnings
from datetime import datetime, timezone

from transcribe.compat import REPO_ROOT
from transcribe.parse import _prepare

GUARD_LOG = REPO_ROOT / "runtime" / "debug" / "verbatim_guard.jsonl"
_lock = threading.Lock()
_DEF_RE = re.compile(r"^\s*([a-zA-Z])\(([a-z])\)\s*=(.+)$")
_PRIME_RE = re.compile(r"^\s*([a-zA-Z])'\(([a-z])\)\s*=(.+)$")
_DDX_RE = re.compile(r"^\s*\\frac\{d\}\{d([a-z])\}(.+?)=(.+)$")


def _parse(expr: str):
    from sympy.parsing.latex import parse_latex

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        try:
            return parse_latex(_prepare(expr))
        except Exception:  # noqa: BLE001
            return None


def _equal(lhs, rhs) -> bool:
    import sympy

    try:
        return bool(sympy.simplify(lhs - rhs) == 0)
    except Exception:  # noqa: BLE001
        return False


def is_consistent(latex: str, context: list[str]) -> bool | None:
    """True if SymPy can show the line is a correct identity/derivative, False if it can show it isn't,
    None when it can't tell (unparseable, no definition in context, not an equation)."""
    import sympy

    if not latex or "=" not in latex:
        return None
    m = _DDX_RE.match(latex)
    if m:
        var, expr, rhs = m.groups()
        e, r = _parse(expr), _parse(rhs)
        if e is None or r is None:
            return None
        return _equal(sympy.diff(e, sympy.Symbol(var)), r)
    m = _PRIME_RE.match(latex)
    if m:
        name, var, rhs = m.groups()
        definition = next((d for d in reversed(context) for dm in [_DEF_RE.match(d)]
                           if dm and dm.group(1) == name), None)
        if definition is None:
            return None
        body = _DEF_RE.match(definition).group(3)
        e, r = _parse(body), _parse(rhs)
        if e is None or r is None:
            return None
        return _equal(sympy.diff(e, sympy.Symbol(var)), r)
    sides = [s for s in latex.split("=") if s.strip()]
    if len(sides) < 2:
        return None
    parsed = [_parse(s) for s in sides]
    if any(p is None for p in parsed):
        return None
    return all(_equal(parsed[i], parsed[i + 1]) for i in range(len(parsed) - 1))


SYMPY_TIMEOUT_S = 3.0
MAX_EXPR_LEN = 300
_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="sympy")


def _consistent_with_timeout(latex: str, context: list[str]) -> bool | None:
    if len(latex) > MAX_EXPR_LEN:
        return None
    try:
        return _pool.submit(is_consistent, latex, context).result(timeout=SYMPY_TIMEOUT_S)
    except FuturesTimeout:
        return None
    except Exception:  # noqa: BLE001
        return None


def which_is_nicer(a: str, b: str, context: list[str]) -> str | None:
    """'A' / 'B' when exactly one reading is mathematically consistent, else None."""
    ca, cb = _consistent_with_timeout(a, context), _consistent_with_timeout(b, context)
    if ca is True and cb is False:
        return "A"
    if cb is True and ca is False:
        return "B"
    return None


def record(event: dict) -> None:
    rec = {"ts": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"), **event}
    with _lock:
        try:
            GUARD_LOG.parent.mkdir(parents=True, exist_ok=True)
            with GUARD_LOG.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
        except OSError:
            pass
