"""perception_detect (T2): components, part identification, twin assembly.

Public contract (contracts/interfaces.md):
    register(part_id, row_index, pixel) -> None
    detect_components(frame_path, tiles=None) -> list[dict]
    normalize_part(label_text) -> str | None
    build_twin(frame_path) -> dict
"""
from .components import detect_components
from .normalize import normalize_part
from .registration import register
from .twin import build_twin

__all__ = ["register", "detect_components", "normalize_part", "build_twin"]
