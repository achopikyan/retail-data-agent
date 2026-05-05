"""Golden Bucket: load Trios, embed once, retrieve top-k by cosine.

We use Google's `gemini-embedding-001` via langchain-google-genai (override
via GEMINI_EMBEDDING_MODEL in .env). Embeddings are persisted to a .npy
file so we don't re-embed on every boot. Cosine similarity is computed
in numpy — no vector DB needed for this scale (≤ a few thousand Trios).
At higher scale, swap in Vertex AI Vector Search or pgvector — see
ARCHITECTURE.md §3.1.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import List, Sequence

import numpy as np

from src import settings

logger = logging.getLogger(__name__)


@dataclass
class Trio:
    id: str
    question: str
    sql: str
    report: str
    tags: List[str]

    @classmethod
    def from_dict(cls, d: dict) -> "Trio":
        return cls(
            id=d["id"],
            question=d["question"],
            sql=d["sql"],
            report=d["report"],
            tags=d.get("tags", []),
        )


def _cosine(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    a_norm = a / (np.linalg.norm(a, axis=-1, keepdims=True) + 1e-12)
    b_norm = b / (np.linalg.norm(b) + 1e-12)
    return a_norm @ b_norm


class GoldenBucket:
    def __init__(self, trios: List[Trio], embeddings: np.ndarray, embedder=None):
        self.trios = trios
        self.embeddings = embeddings  # shape (N, D)
        self.embedder = embedder

    @classmethod
    def load(cls, embedder=None) -> "GoldenBucket":
        with open(settings.GOLDEN_TRIOS_PATH, "r", encoding="utf-8") as f:
            seed = [Trio.from_dict(t) for t in json.load(f)]

        curated: List[Trio] = []
        if settings.CURATED_TRIOS_PATH.exists():
            with open(settings.CURATED_TRIOS_PATH, "r", encoding="utf-8") as f:
                try:
                    curated = [Trio.from_dict(t) for t in json.load(f)]
                except Exception as e:  # noqa: BLE001
                    logger.warning("Could not parse curated trios (%s); skipping.", e)

        trios = seed + curated

        if settings.GOLDEN_EMBEDDINGS_PATH.exists():
            embeddings = np.load(settings.GOLDEN_EMBEDDINGS_PATH)
            if embeddings.shape[0] != len(trios):
                logger.warning(
                    "Embedding cache size (%d) != trios (%d) — re-embedding.",
                    embeddings.shape[0],
                    len(trios),
                )
                embeddings = cls._embed_all(trios, embedder)
                np.save(settings.GOLDEN_EMBEDDINGS_PATH, embeddings)
        else:
            embeddings = cls._embed_all(trios, embedder)
            np.save(settings.GOLDEN_EMBEDDINGS_PATH, embeddings)

        return cls(trios=trios, embeddings=embeddings, embedder=embedder)

    @staticmethod
    def _embed_all(trios: List[Trio], embedder) -> np.ndarray:
        if embedder is None:
            from src.llm.gemini import build_embeddings

            embedder = build_embeddings()
        texts = [t.question for t in trios]
        logger.info("Embedding %d trios via Google embeddings", len(texts))
        vectors = embedder.embed_documents(texts)
        return np.array(vectors, dtype=np.float32)

    def retrieve(self, query: str, k: int = 3) -> List[Trio]:
        if self.embedder is None:
            from src.llm.gemini import build_embeddings

            self.embedder = build_embeddings()
        q_vec = np.array(self.embedder.embed_query(query), dtype=np.float32)
        sims = _cosine(self.embeddings, q_vec)
        top_idx = np.argsort(-sims)[:k]
        return [self.trios[i] for i in top_idx]


def format_trios_for_prompt(trios: Sequence[Trio]) -> str:
    """Render retrieved Trios as few-shot context for SQL generation."""
    blocks: List[str] = []
    for i, t in enumerate(trios, 1):
        blocks.append(
            f"--- Example {i} ---\n"
            f"Question: {t.question}\n"
            f"SQL:\n{t.sql}\n"
            f"Analyst note:\n{t.report}\n"
        )
    return "\n".join(blocks)
