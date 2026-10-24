"""Tests for app.telemetry (Step 1)."""
import json
import threading
import time

import pytest

from app import telemetry


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    monkeypatch.setenv("BM_RUNTIME_DIR", str(tmp_path))
    return tmp_path


def _records(runtime):
    path = runtime / "telemetry.jsonl"
    return [json.loads(l) for l in path.read_text().splitlines()]


def test_log_appends_one_json_line_with_required_keys(runtime):
    telemetry.log("twin", 1830.25, frame_id="f1", n_wires=6)
    recs = _records(runtime)
    assert len(recs) == 1
    r = recs[0]
    assert set(r) >= {"ts", "stage", "ms", "frame_id", "n_wires"}
    assert r["stage"] == "twin" and r["ms"] == 1830.25
    assert r["frame_id"] == "f1" and r["n_wires"] == 6
    assert "T" in r["ts"]  # ISO 8601


def test_log_creates_missing_directories(runtime, monkeypatch):
    deep = runtime / "a" / "b"
    monkeypatch.setenv("BM_RUNTIME_DIR", str(deep))
    telemetry.log("x", 1)
    assert (deep / "telemetry.jsonl").exists()


def test_log_coerces_non_json_extras(runtime):
    telemetry.log("x", 1, obj=object(), path=runtime)
    r = _records(runtime)[0]
    assert isinstance(r["obj"], str) and isinstance(r["path"], str)


def test_timed_context_manager_logs_duration(runtime):
    with telemetry.timed("rules", frame_id="f2") as info:
        time.sleep(0.02)
        info["findings"] = 2
    r = _records(runtime)[0]
    assert r["stage"] == "rules" and r["ms"] >= 15 and r["frame_id"] == "f2" and r["findings"] == 2


def test_timed_logs_error_and_reraises(runtime):
    with pytest.raises(ValueError):
        with telemetry.timed("boom"):
            raise ValueError("nope")
    r = _records(runtime)[0]
    assert r["stage"] == "boom" and r["error"].startswith("ValueError")


def test_thread_safety_no_interleaved_lines(runtime):
    n_threads, per_thread = 8, 200

    def worker(i):
        for j in range(per_thread):
            telemetry.log("t", j, thread=i, payload="x" * 300)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(n_threads)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    recs = _records(runtime)  # every line must parse
    assert len(recs) == n_threads * per_thread


def test_listener_receives_record_and_bad_listener_is_ignored(runtime):
    seen = []
    bad = lambda r: 1 / 0
    telemetry.add_listener(seen.append)
    telemetry.add_listener(bad)
    try:
        telemetry.log("s", 5)
    finally:
        telemetry.remove_listener(seen.append)
        telemetry.remove_listener(bad)
    assert seen and seen[0]["stage"] == "s"


def test_read_recent_tolerates_partial_last_line(runtime):
    telemetry.log("a", 1)
    telemetry.log("b", 2)
    with (runtime / "telemetry.jsonl").open("a") as fh:
        fh.write('{"ts": "half')
    recs = telemetry.read_recent(10)
    assert [r["stage"] for r in recs] == ["a", "b"]
    assert telemetry.read_recent(1)[0]["stage"] == "b"
