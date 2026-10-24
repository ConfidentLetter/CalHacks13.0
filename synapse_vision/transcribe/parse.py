"""parse_ok: can SymPy parse the LaTeX?  Confidence signal only; never triggers a 'fix'."""
from __future__ import annotations

import re
import warnings

_EQ_SPLIT_RE = re.compile(r"=|\\le(?:q)?|\\ge(?:q)?|\\ne(?:q)?|<|>")
_PRIME_RE = re.compile(r"([A-Za-z])'+")


def _prepare(side: str) -> str:
    """Rewrite handwriting conventions the parser rejects but that are unambiguous: f'(x) -> f_{prime}(x)."""
    s = side.strip()
    s = s.replace("\u2212", "-").replace("\u00b7", "\\cdot")
    s = _PRIME_RE.sub(lambda m: m.group(1) + "_{p}", s)
    s = re.sub(r"\\(?:left|right)", "", s)
    return s


def _parse_one(side: str) -> bool:
    from sympy.parsing.latex import parse_latex

    expr = _prepare(side)
    if not expr:
        return False
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        try:
            parse_latex(expr)
            return True
        except Exception:  # noqa: BLE001
            pass
        try:
            parse_latex(expr, backend="lark")
            return True
        except Exception:  # noqa: BLE001
            return False


def parse_ok(latex: str) -> bool:
    """True if SymPy can parse it. Used for confidence only; a failed parse never triggers a 'fix'."""
    if not latex or not latex.strip():
        return False
    sides = [p for p in _EQ_SPLIT_RE.split(latex) if p.strip()]
    if not sides:
        return False
    return all(_parse_one(side) for side in sides)
