"""normalize_latex: canonical form for COMPARISON ONLY. Never written into the twin."""
from __future__ import annotations

import re

# Unicode look-alikes that handwriting readers emit; mapped to ASCII for comparison.
_UNICODE_MAP = {
    "\u2212": "-",  # minus sign
    "\u2013": "-",  # en dash
    "\u2014": "-",  # em dash
    "\u00b7": "\\cdot",  # middle dot
    "\u22c5": "\\cdot",  # dot operator
    "\u00d7": "\\cdot",  # multiplication sign
    "\u2032": "'",  # prime
    "\u2019": "'",
    "\u2018": "'",
    "\u00b2": "^2",
    "\u00b3": "^3",
    "\u221a": "\\sqrt",
    "\u03c0": "\\pi",
}

# Commands that carry no mathematical meaning (spacing, sizing).
_NOISE_COMMANDS = [
    r"\\left", r"\\right", r"\\big[lr]?", r"\\Big[lr]?", r"\\bigg[lr]?", r"\\Bigg[lr]?",
    r"\\displaystyle", r"\\textstyle", r"\\mathrm", r"\\operatorname", r"\\text",
    r"\\,", r"\;", r"\\:", r"\\!", r"\\quad", r"\\qquad", r"\\ ", r"~",
]
_NOISE_RE = re.compile("|".join(_NOISE_COMMANDS))

_MULT_RE = re.compile(r"\\times|\\ast|\\cdot|\*")
_DFRAC_RE = re.compile(r"\\[dt]frac")
_FUNCS = ("sin", "cos", "tan", "cot", "sec", "csc", "ln", "log", "exp", "arcsin", "arccos", "arctan", "sinh", "cosh", "tanh")
_FUNC_PAREN_RE = re.compile(r"\\(" + "|".join(_FUNCS) + r")\(([^()]*)\)")
_FUNC_BRACE_RE = re.compile(r"\\(" + "|".join(_FUNCS) + r")\{([^{}]*)\}")
_SINGLE_BRACE_RE = re.compile(r"([\^_])\{([A-Za-z0-9])\}")


def _strip_single_char_braces(s: str) -> str:
    """^{2} -> ^2, _{i} -> _i (repeat until stable)."""
    prev = None
    while prev != s:
        prev, s = s, _SINGLE_BRACE_RE.sub(r"\1\2", s)
    return s


def normalize_latex(latex: str) -> str:
    """Canonical spacing/commands for comparison only (\\cdot vs *, \\left( vs (, etc.). Never changes math meaning."""
    if not latex:
        return ""
    s = latex
    for src, dst in _UNICODE_MAP.items():
        s = s.replace(src, dst)
    s = s.replace("$", "")
    s = _NOISE_RE.sub("", s)
    s = _DFRAC_RE.sub(r"\\frac", s)
    s = _MULT_RE.sub("*", s)
    s = s.replace("\\prime", "'")
    s = s.replace("^\\prime", "'")
    s = _FUNC_PAREN_RE.sub(r"\\\1 \2", s)
    s = _FUNC_BRACE_RE.sub(r"\\\1 \2", s)
    s = _strip_single_char_braces(s)
    s = re.sub(r"\\(d|t)?frac\s*", r"\\frac", s)
    # Collapse whitespace entirely: it never changes meaning after the above rewrites,
    # except between a command and a following letter, where we keep one space.
    s = re.sub(r"\s+", " ", s).strip()
    s = re.sub(r"(?<![A-Za-z\\]) | (?![A-Za-z])", "", s)
    s = re.sub(r"(\\[A-Za-z]+) (?=[A-Za-z])", r"\1 ", s)
    return s
