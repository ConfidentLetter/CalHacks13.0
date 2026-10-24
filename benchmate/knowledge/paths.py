"""Filesystem layout of the knowledge package. Everything T4 writes lives under these paths."""
from __future__ import annotations

from pathlib import Path

KNOWLEDGE_DIR = Path(__file__).resolve().parent
REPO_ROOT = KNOWLEDGE_DIR.parent
PROFILES_DIR = KNOWLEDGE_DIR / "profiles"
DATASHEETS_DIR = KNOWLEDGE_DIR / "datasheets"
INDEX_DIR = KNOWLEDGE_DIR / "index"
READS_FILE = KNOWLEDGE_DIR / "reads.jsonl"
MOCKS_DIR = REPO_ROOT / "mocks"
