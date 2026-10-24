"""T3 — Transcribe: verbatim readings with honest confidence, assembled into the page twin.

Public surface (contracts/interfaces.md):
    transcribe_page, normalize_latex, parse_ok, build_page_twin
"""
from transcribe.normalize import normalize_latex
from transcribe.page import transcribe_page
from transcribe.parse import parse_ok
from transcribe.twin import build_page_twin

__all__ = ["transcribe_page", "normalize_latex", "parse_ok", "build_page_twin"]
