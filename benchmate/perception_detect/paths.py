"""Repository paths used by perception_detect. No I/O at import time."""
from __future__ import annotations

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
REGISTRATIONS_PATH = RUNTIME_DIR / "registrations.json"
