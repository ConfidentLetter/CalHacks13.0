"""Every T1 function in contracts/interfaces.md exists with the exact signature."""
import inspect

import capture
from capture import page, source


def _params(fn):
    return [(p.name, p.default) for p in inspect.signature(fn).parameters.values()]


def test_get_snapshot_signature():
    assert _params(source.get_snapshot) == [("source", None)]


def test_wait_for_stable_signature():
    assert _params(source.wait_for_stable) == [("timeout_s", 30.0)]


def test_detect_and_dewarp_signature():
    assert _params(page.detect_and_dewarp) == [("snapshot_path", inspect.Parameter.empty)]


def test_tile_signature():
    assert _params(page.tile) == [("dewarped_path", inspect.Parameter.empty), ("max_tiles", 6)]


def test_package_exports():
    assert set(capture.__all__) == {"get_snapshot", "wait_for_stable", "detect_and_dewarp", "tile"}
