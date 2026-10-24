"""Download the local models once (needs network): MiniLM embeddings + ms-marco cross-encoder.

Run:  python -m knowledge.tools.fetch_models
Search never downloads on its own; without the cross-encoder it silently runs BM25+vector only.
"""
from __future__ import annotations

import sys

from ..embeddings import MODEL_NAME
from ..rerank import RERANK_MODEL


def main() -> int:
    from sentence_transformers import CrossEncoder, SentenceTransformer

    SentenceTransformer(MODEL_NAME, device="cpu")
    print("ok", MODEL_NAME)
    CrossEncoder(RERANK_MODEL, device="cpu")
    print("ok", RERANK_MODEL)
    return 0


if __name__ == "__main__":
    sys.exit(main())
