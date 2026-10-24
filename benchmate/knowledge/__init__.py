"""T4 Knowledge: datasheets, hybrid search, page citation, component profiles, reading history.

Public API (contracts/interfaces.md):
    ingest, search, get_profile, list_profiles, record_read, recent_reads
"""
from .ingest import ingest
from .profiles_store import get_profile, list_profiles
from .reads import recent_reads, record_read
from .search import search

__all__ = ["ingest", "search", "get_profile", "list_profiles", "record_read", "recent_reads"]
