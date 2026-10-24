"""One slow test against T4's real knowledge module (no network, but loads its index). Skips if T4 is not importable."""
import pytest

import reasoning
from reasoning.schema import validation_errors


@pytest.mark.realsearch
def test_real_knowledge_citation_is_schema_valid(twin_5v):
    pytest.importorskip("knowledge")
    d = reasoning.run_checks(twin_5v, [])
    assert validation_errors(d) == []
    f = next(f for f in d["findings"] if f["id"] == "supply_voltage")
    cites = f["evidence"].get("datasheet", [])
    if cites:  # T4 may still be on its mock; either way the shape must hold
        assert isinstance(cites[0]["page"], int) and len(cites[0].get("quote", "")) <= 200
