"""The Chrome extension is static files; check the manifest and that the scripts parse (if node is available)."""
from __future__ import annotations

import json
import shutil
import subprocess

import pytest

from knowledge.paths import KNOWLEDGE_DIR

EXT = KNOWLEDGE_DIR / "extension"


def test_manifest_v3_shape():
    m = json.loads((EXT / "manifest.json").read_text())
    assert m["manifest_version"] == 3
    assert m["background"]["service_worker"] == "background.js"
    assert "storage" in m["permissions"] and "tabs" in m["permissions"]
    assert all("localhost" in h or "127.0.0.1" in h for h in m["host_permissions"]), "only localhost may be contacted"
    for f in ("background.js", "content.js", "popup.html", "popup.js", "options.html", "options.js", "common.js"):
        assert (EXT / f).is_file(), f


def test_only_localhost_endpoint_in_scripts():
    for f in ("background.js", "common.js", "options.js"):
        src = (EXT / f).read_text()
        for line in src.splitlines():
            if "http" in line and "://" in line:
                assert "localhost" in line or "127.0.0.1" in line or line.strip().startswith("//") or '"http://*/*"' in line, (f, line)


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
@pytest.mark.parametrize("script", ["background.js", "content.js", "popup.js", "options.js", "common.js"])
def test_scripts_parse(script):
    subprocess.run(["node", "--check", str(EXT / script)], check=True)
