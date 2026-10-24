"""T2 Layout — regions, lines, reading order, crossed-out detection, crops."""
from layout.crossed_out import is_crossed_out
from layout.segment import segment

__all__ = ["segment", "is_crossed_out"]
