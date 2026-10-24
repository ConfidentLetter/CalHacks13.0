import os
import time
from pathlib import Path

import pytest

from app import config


def test_reads_real_config_values():
    assert config.get("capture.source") in {"pi", "webcam", "upload"}
    assert config.get("budget_ms.snapshot_to_twin_first") == 8000
    assert config.get("transcribe.low_confidence") == pytest.approx(0.6)


def test_missing_key_returns_default():
    assert config.get("nope.nothing", "dflt") == "dflt"
    assert config.get("capture.source.deeper", 7) == 7
    assert config.get("capture") and isinstance(config.get("capture"), dict)


def test_hot_reload_on_mtime_change(tmp_path, monkeypatch):
    p = tmp_path / "vision.yaml"
    p.write_text("a:\n  b: 1\n")
    monkeypatch.setattr(config, "CONFIG_PATH", p)
    config._cache["mtime"] = None
    assert config.get("a.b") == 1
    time.sleep(0.01)
    p.write_text("a:\n  b: 2\n")
    os.utime(p, (time.time() + 5, time.time() + 5))  # force a different mtime
    assert config.get("a.b") == 2


def test_malformed_edit_keeps_last_good_copy(tmp_path, monkeypatch):
    p = tmp_path / "vision.yaml"
    p.write_text("a:\n  b: 1\n")
    monkeypatch.setattr(config, "CONFIG_PATH", p)
    config._cache["mtime"] = None
    assert config.get("a.b") == 1
    p.write_text("a: [unclosed\n")
    os.utime(p, (time.time() + 5, time.time() + 5))
    assert config.get("a.b") == 1


def test_all_returns_copy():
    d = config.all()
    d["capture"] = None
    assert isinstance(config.get("capture"), dict)
