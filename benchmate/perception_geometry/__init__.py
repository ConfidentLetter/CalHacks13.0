"""T1 — board geometry: pixels -> holes. Public API per contracts/interfaces.md."""
from .board import BOARD_CONFIG, node_of
from .calibration import CalibrationError, calibrate, hole_to_pixel, pixel_to_hole
from .nets import build_nets
from .tiling import tile
from .wires import detect_wires

__all__ = [
    "BOARD_CONFIG", "CalibrationError", "build_nets", "calibrate", "detect_wires",
    "hole_to_pixel", "node_of", "pixel_to_hole", "tile",
]
