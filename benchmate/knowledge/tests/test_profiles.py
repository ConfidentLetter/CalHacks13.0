"""Step 5: every profile is internally consistent — a typo here silently breaks T2 and T3."""
from __future__ import annotations

import pytest

from knowledge import get_profile, list_profiles
from knowledge.paths import DATASHEETS_DIR, INDEX_DIR, REPO_ROOT

PROFILES = list_profiles()
IDS = [p["part_id"] for p in PROFILES]
needs_index = pytest.mark.skipif(not (INDEX_DIR / "bme280.jsonl").is_file(), reason="run knowledge.tools.ingest_all")


def _footprint_pins(profile: dict) -> set[str]:
    return {pin for row in profile["footprint"]["rows"] for pin in row["pins"]}


@pytest.mark.parametrize("part_id", IDS)
def test_required_keys_and_types(part_id):
    p = get_profile(part_id)
    assert p["part_id"] == part_id
    assert p["role"] in ("mcu", "peripheral")
    assert isinstance(p["aliases"], list) and all(isinstance(a, str) and a for a in p["aliases"])
    assert (REPO_ROOT / p["datasheet"]).is_file(), p["datasheet"]
    for row in p["footprint"]["rows"]:
        assert row["axis"] in ("number", "letter")
        assert isinstance(row["pins"], list) and row["pins"]
        assert all(isinstance(pin, str) and pin for pin in row["pins"])


@pytest.mark.parametrize("part_id", IDS)
def test_check_pins_exist_in_footprint(part_id):
    p = get_profile(part_id)
    pins = _footprint_pins(p)
    for chk in p.get("checks", []):
        assert chk["pin"] in pins, f"{part_id}: check {chk['id']} pin {chk['pin']} not in footprint"
        assert chk["kind"] in ("max_supply", "same_net")
        assert chk["severity"] in ("error", "warning", "info")
        assert chk["search_query"].strip()
        if chk["kind"] == "same_net":
            assert chk["target_role"] in ("i2c_sda", "i2c_scl", "gnd")


@pytest.mark.parametrize("part_id", IDS)
def test_role_and_source_pins_exist_in_footprint(part_id):
    p = get_profile(part_id)
    pins = _footprint_pins(p)
    for role, pin in p.get("roles", {}).items():
        assert pin in pins, f"{part_id}: role {role} -> {pin} not in footprint"
    for pin, volts in p.get("sources", {}).items():
        assert pin in pins, f"{part_id}: source {pin} not in footprint"
        assert isinstance(volts, (int, float)) and 0 < volts < 30
    for alias, pin in p.get("pin_aliases", {}).items():
        assert pin in pins, f"{part_id}: pin_alias {alias} -> {pin} not in footprint"


def test_mcu_profiles_cover_the_roles_peripherals_need():
    needed = {chk["target_role"] for p in PROFILES for chk in p.get("checks", []) if chk["kind"] == "same_net"}
    for p in PROFILES:
        if p["role"] == "mcu":
            assert needed <= set(p["roles"]), f"{p['part_id']} lacks roles {needed - set(p['roles'])}"
            assert p["sources"], p["part_id"]


def test_aliases_unique_across_profiles():
    seen: dict[str, str] = {}
    for p in PROFILES:
        for a in [p["part_id"]] + p["aliases"]:
            key = a.lower().replace(" ", "").replace("-", "")
            assert key not in seen or seen[key] == p["part_id"], f"alias {a!r} in both {seen[key]} and {p['part_id']}"
            seen[key] = p["part_id"]


def test_bme280_supply_facts():
    p = get_profile("bme280")
    assert p["supply"]["max_v"] == 3.6 and p["supply"]["datasheet_page"] == "8"
    assert p["supply"]["absolute_max_v"] == 4.25 and p["supply"]["absolute_max_page"] == "13"
    assert set(p["i2c_addresses"]) == {"0x76", "0x77"}
    assert p["interface"] == "i2c"


@needs_index
@pytest.mark.parametrize("part_id", [pid for pid in IDS if get_profile(pid).get("checks")])
def test_check_search_queries_retrieve_their_cited_page(part_id):
    from knowledge import search
    p = get_profile(part_id)
    for chk in p["checks"]:
        hits = search(part_id, chk["search_query"], k=3)
        assert hits, chk["id"]
        assert hits[0]["page"] == chk["datasheet_page"], (chk["id"], [h["page"] for h in hits])


@needs_index
def test_bme280_supply_page_is_the_operating_range_page():
    from knowledge import search
    p = get_profile("bme280")
    hit = search("bme280", p["checks"][0]["search_query"], k=1)[0]
    assert hit["page"] == p["supply"]["datasheet_page"]
    assert "3.6" in hit["text"] and "VDD" in hit["text"]
