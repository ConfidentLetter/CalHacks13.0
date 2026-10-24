"""Step 1 acceptance: every T4 contract function exists with the exact signature and returns valid shapes."""
from __future__ import annotations

import inspect
import json
from pathlib import Path

import pytest
import yaml

import knowledge
from knowledge import get_profile, ingest, list_profiles, recent_reads, record_read, search

ROOT = Path(__file__).resolve().parents[2]
HIT_KEYS = {"text", "page", "section", "score", "source_file"}


@pytest.mark.parametrize(
    "fn,sig",
    [
        (ingest, "(pdf_path: str, part_id: str) -> int"),
        (search, "(part_id: str, query: str, k: int = 5) -> list[dict]"),
        (get_profile, "(part_id: str) -> dict"),
        (list_profiles, "() -> list[dict]"),
        (record_read, "(url_or_path: str, text: str | None, seconds_on_page: float) -> None"),
        (recent_reads, "(part_id: str | None = None, hours: int = 24) -> list[dict]"),
    ],
)
def test_exact_signatures(fn, sig):
    # `from __future__ import annotations` stringifies annotations; strip the quotes before comparing.
    got = str(inspect.signature(fn)).replace("'", "")
    assert got == sig


def test_public_api_exported():
    assert set(knowledge.__all__) == {"ingest", "search", "get_profile", "list_profiles", "record_read", "recent_reads"}


def test_search_returns_contract_hits():
    hits = search("bme280", "maximum supply voltage")
    assert hits, "stub must return the mock hit"
    for h in hits:
        assert set(h) == HIT_KEYS
        assert isinstance(h["page"], str)
        assert isinstance(h["score"], float)
        assert len(h["text"]) <= 1200
    mock = json.loads((ROOT / "mocks" / "search_bme280_supply.json").read_text())
    assert hits[0]["text"] == mock[0]["text"]


def test_search_respects_k_and_empty_query():
    assert search("bme280", "x", k=0) == []
    assert search("bme280", "") == []
    assert len(search("bme280", "supply", k=1)) == 1


def test_profiles_match_contract_examples():
    examples = {d["part_id"]: d for d in yaml.safe_load_all((ROOT / "contracts" / "profile.example.yaml").read_text())}
    for pid in ("bme280", "esp32-devkitc"):
        assert get_profile(pid) == examples[pid]


def test_list_profiles_contains_both_and_is_sorted():
    ids = [p["part_id"] for p in list_profiles()]
    assert ids == sorted(ids)
    assert {"bme280", "esp32-devkitc"} <= set(ids)
    for p in list_profiles():
        assert isinstance(p["aliases"], list) and p["aliases"]
        assert p["role"] in ("mcu", "peripheral")
        assert p["footprint"]["rows"]


def test_get_profile_missing_raises_keyerror():
    with pytest.raises(KeyError):
        get_profile("does-not-exist")
    with pytest.raises(KeyError):
        get_profile("../contracts/profile.example")


def test_get_profile_returns_a_copy():
    a = get_profile("bme280")
    a["aliases"].append("MUTATED")
    assert "MUTATED" not in get_profile("bme280")["aliases"]


def test_reads_stubs():
    record_read("https://example.com", "some text", 31.0)
    assert recent_reads() == []
    assert recent_reads("bme280", hours=1) == []


def test_ingest_stub(tmp_path):
    pdf = tmp_path / "x.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")
    assert ingest(str(pdf), "bme280") == 0
    with pytest.raises(FileNotFoundError):
        ingest(str(tmp_path / "missing.pdf"), "bme280")
