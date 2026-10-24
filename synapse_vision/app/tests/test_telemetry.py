import json
import threading

import pytest

from app import telemetry


@pytest.fixture
def tpath(tmp_path, monkeypatch):
    p = tmp_path / "telemetry.jsonl"
    monkeypatch.setattr(telemetry, "TELEMETRY_PATH", p)
    return p


def test_log_appends_json_lines(tpath):
    telemetry.log("layout.segment", 12.5, lines=3)
    telemetry.log("page.dewarp", 1.25)
    recs = [json.loads(l) for l in tpath.read_text().splitlines()]
    assert [r["stage"] for r in recs] == ["layout.segment", "page.dewarp"]
    assert recs[0]["ms"] == 12.5 and recs[0]["lines"] == 3
    assert "ts" in recs[0]


def test_timed_context_manager_logs_elapsed(tpath):
    with telemetry.timed("x", snapshot="s1") as t:
        t["n"] = 2
    rec = telemetry.read()[-1]
    assert rec["stage"] == "x" and rec["ms"] >= 0 and rec["n"] == 2 and rec["snapshot"] == "s1"


def test_timed_logs_error_and_reraises(tpath):
    with pytest.raises(ValueError):
        with telemetry.timed("boom"):
            raise ValueError("bad")
    assert "ValueError" in telemetry.read()[-1]["error"]


def test_thread_safe_appends(tpath):
    def work(i):
        for _ in range(50):
            telemetry.log(f"t{i}", 1.0)
    threads = [threading.Thread(target=work, args=(i,)) for i in range(8)]
    for th in threads:
        th.start()
    for th in threads:
        th.join()
    lines = tpath.read_text().splitlines()
    assert len(lines) == 400
    for l in lines:
        json.loads(l)  # every line intact


def test_read_filters_and_limits(tpath):
    for i in range(5):
        telemetry.log("a", i)
    telemetry.log("b", 9)
    assert len(telemetry.read(stage="a")) == 5
    assert telemetry.read(limit=2)[-1]["stage"] == "b"


def test_unserialisable_extra_does_not_raise(tpath):
    telemetry.log("odd", 1, obj=object())
    assert telemetry.read()[-1]["stage"] == "odd"
