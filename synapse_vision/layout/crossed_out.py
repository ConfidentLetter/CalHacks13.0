"""``is_crossed_out(crop_path)`` — classical strike-through detection.

Step 1 stub: no ink analysis yet; always returns (False, 0.0).  Step 4 replaces
the body with skeleton + Hough analysis.
"""
from __future__ import annotations


def is_crossed_out(crop_path: str) -> tuple[bool, float]:
    """Classical check (strike-through stroke over the ink); returns (crossed, confidence)."""
    return False, 0.0
