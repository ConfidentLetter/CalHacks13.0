"""Repository paths used by perception_detect. No I/O at import time."""
from __future__ import annotations

import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CONTRACTS_DIR = REPO_ROOT / "contracts"
MOCKS_DIR = REPO_ROOT / "mocks"
RUNTIME_DIR = REPO_ROOT / "runtime"
PROFILES_DIR = REPO_ROOT / "knowledge" / "profiles"

TWIN_SCHEMA_PATH = CONTRACTS_DIR / "twin.schema.json"
DIAGNOSIS_SCHEMA_PATH = CONTRACTS_DIR / "diagnosis.schema.json"
PROFILE_EXAMPLE_PATH = CONTRACTS_DIR / "profile.example.yaml"
MOCK_TWIN_OK_PATH = MOCKS_DIR / "twin_ok.json"


def runtime_dir() -> Path:
    """Where runtime artefacts go. Env BM_RUNTIME_DIR overrides (same convention as app.telemetry)."""
    return Path(os.environ.get("BM_RUNTIME_DIR", RUNTIME_DIR))


def registrations_path() -> Path:
    return runtime_dir() / "registrations.json"
