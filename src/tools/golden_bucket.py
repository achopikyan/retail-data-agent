"""Golden Bucket: load Trios and retrieve top-k by cosine, BM25, or hybrid.

Cosine = semantic match via Google embeddings (`gemini-embedding-001`).
BM25 = lexical match via `rank-bm25`, in-memory (rebuilt at process start).
Hybrid = Reciprocal Rank Fusion of the two ranked lists.

Embeddings are persisted to a .npy file so we don't re-embed on every boot.
The BM25 index is cheap (<50ms at our scale) and is rebuilt every time;
no persistence needed.

Mode is configurable via `settings.RETRIEVAL_MODE` ("cosine" | "bm25" |
"hybrid") so we can A/B without code changes. The default "hybrid" is
the production-RAG consensus pick: cosine catches paraphrases, BM25
catches exact tokens (table/column names, specific years), and RRF
combines them rank-wise without score normalization.

For higher scale, swap the in-memory cosine for Vertex AI Vector Search
or pgvector — see ARCHITECTURE.md §3.1.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import List, Optional, Sequence, Tuple

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


# --- helpers ---------------------------------------------------------------


def _cosine(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    a_norm = a / (np.linalg.norm(a, axis=-1, keepdims=True) + 1e-12)
    b_norm = b / (np.linalg.norm(b) + 1e-12)
    return a_norm @ b_norm


_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _tokenize(text: str) -> List[str]:
    """Lowercase + alphanumeric token split.

    Intentionally simple: no stemming, no stopword removal — domain
    stopwords ("by", "in") carry meaning in analytics phrasings ("revenue
    by region"). Numbers are preserved (Q3, 2025) since they're
    frequently the discriminating signal.
    """
    return _TOKEN_RE.findall(text.lower())


def _rrf_fuse(
    rank_lists: Sequence[Sequence[int]], k_rrf: int
) -> List[Tuple[int, float]]:
    """Reciprocal Rank Fusion.

    Each list in `rank_lists` is a sequence of doc indices, ordered by
    *descending* relevance (best first). Returns `[(doc_idx, score), ...]`
    sorted by score descending. Doc absent from a list contributes 0
    from that list.
    """
    scores: dict[int, float] = {}
    for ranks in rank_lists:
        for rank, doc_idx in enumerate(ranks):
            # rank is 0-indexed in our enumerate; the standard RRF
            # formula uses 1-indexed rank, hence the +1.
            scores[doc_idx] = scores.get(doc_idx, 0.0) + 1.0 / (k_rrf + rank + 1)
    return sorted(scores.items(), key=lambda x: -x[1])


# --- BM25 index ------------------------------------------------------------


class BM25Index:
    """Thin wrapper around `rank_bm25.BM25Okapi`.

    Indexes one tokenized document per trio (the question text) at
    construction time. `top_idxs(query, n)` returns the top-N trio
    indices by BM25 score, descending.
    """

    def __init__(self, corpus_texts: List[str]):
        from rank_bm25 import BM25Okapi

        self._tokenized = [_tokenize(t) for t in corpus_texts]
        # rank_bm25 dies on a fully empty corpus; guard so we degrade
        # gracefully (return [] from top_idxs).
        self._bm25 = BM25Okapi(self._tokenized) if self._tokenized else None

    def top_idxs(self, query: str, n: int) -> List[int]:
        if self._bm25 is None or n <= 0:
            return []
        toks = _tokenize(query)
        if not toks:
            return []
        scores = self._bm25.get_scores(toks)
        # argsort descending; cap at the actual corpus size.
        order = np.argsort(-scores)[:n]
        return [int(i) for i in order]


# --- retrieval result ------------------------------------------------------


@dataclass
class RetrievalResult:
    """Top-k trios + diagnostic metadata for the trace.

    Lets callers (the retrieve_node) emit a structured event without
    re-running the search to inspect what each method picked.
    """

    trios: List[Trio]
    mode: str
    cosine_top_idxs: List[int] = field(default_factory=list)
    bm25_top_idxs: List[int] = field(default_factory=list)
    final_idxs: List[int] = field(default_factory=list)


# --- bucket ---------------------------------------------------------------


class GoldenBucket:
    def __init__(
        self,
        trios: List[Trio],
        embeddings: np.ndarray,
        embedder=None,
        bm25: Optional[BM25Index] = None,
    ):
        self.trios = trios
        self.embeddings = embeddings  # shape (N, D)
        self.embedder = embedder
        # Lazy-build BM25 if not supplied (e.g. tests pass it explicitly).
        self.bm25 = bm25 if bm25 is not None else BM25Index([t.question for t in trios])

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

    # --- ranking primitives ------------------------------------------------

    def _cosine_top_idxs(self, query: str, n: int) -> List[int]:
        if self.embedder is None:
            from src.llm.gemini import build_embeddings

            self.embedder = build_embeddings()
        if self.embeddings.size == 0 or n <= 0:
            return []
        q_vec = np.array(self.embedder.embed_query(query), dtype=np.float32)
        sims = _cosine(self.embeddings, q_vec)
        order = np.argsort(-sims)[:n]
        return [int(i) for i in order]

    # --- public retrieval --------------------------------------------------

    def retrieve(self, query: str, k: int = 3, mode: Optional[str] = None) -> List[Trio]:
        """Return top-k trios. Convenience wrapper around `retrieve_with_meta`."""
        return self.retrieve_with_meta(query, k=k, mode=mode).trios

    def retrieve_with_meta(
        self, query: str, k: int = 3, mode: Optional[str] = None
    ) -> RetrievalResult:
        """Retrieve top-k trios with diagnostic metadata.

        `mode`:
          - "cosine"  — embedding similarity only (legacy behavior)
          - "bm25"    — lexical / keyword overlap only
          - "hybrid"  — RRF over cosine + BM25 ranks (default)

        Result includes the per-method ranked lists so callers can log
        exactly which method picked which trio.
        """
        if k <= 0 or not self.trios:
            return RetrievalResult(trios=[], mode=mode or settings.RETRIEVAL_MODE)

        active_mode = mode or settings.RETRIEVAL_MODE
        if active_mode not in ("cosine", "bm25", "hybrid"):
            logger.warning("Unknown RETRIEVAL_MODE=%r — falling back to cosine", active_mode)
            active_mode = "cosine"

        depth = max(k, settings.RETRIEVAL_FUSION_DEPTH)

        if active_mode == "cosine":
            cos_idxs = self._cosine_top_idxs(query, depth)
            final = cos_idxs[:k]
            return RetrievalResult(
                trios=[self.trios[i] for i in final],
                mode=active_mode,
                cosine_top_idxs=cos_idxs,
                bm25_top_idxs=[],
                final_idxs=final,
            )

        if active_mode == "bm25":
            bm25_idxs = self.bm25.top_idxs(query, depth)
            final = bm25_idxs[:k]
            return RetrievalResult(
                trios=[self.trios[i] for i in final],
                mode=active_mode,
                cosine_top_idxs=[],
                bm25_top_idxs=bm25_idxs,
                final_idxs=final,
            )

        # hybrid: RRF fuse the top-`depth` from each method.
        cos_idxs = self._cosine_top_idxs(query, depth)
        bm25_idxs = self.bm25.top_idxs(query, depth)
        fused = _rrf_fuse([cos_idxs, bm25_idxs], k_rrf=settings.RETRIEVAL_RRF_K)
        final = [idx for idx, _ in fused[:k]]
        return RetrievalResult(
            trios=[self.trios[i] for i in final],
            mode=active_mode,
            cosine_top_idxs=cos_idxs,
            bm25_top_idxs=bm25_idxs,
            final_idxs=final,
        )


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
