"""T4 Knowledge: datasheets, hybrid search, page citation, component profiles, reading history.

Public API (contracts/interfaces.md):
    ingest, search, get_profile, list_profiles, record_read, recent_reads
Extra (not in the contract): warmup() — loads the local models + indexes once (T5 calls it at server start).
"""
from .ingestion import ingest
from .profiles_store import get_profile, list_profiles
from .reads import recent_reads, record_read
from .retrieval import search, warmup

__all__ = ["ingest", "search", "get_profile", "list_profiles", "record_read", "recent_reads", "warmup"]
