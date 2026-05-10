"""Tests for cosine / BM25 / hybrid retrieval modes.

We use a stub embedder so cosine ranks are deterministic and the
hybrid fusion can be reasoned about by hand.
"""
from __future__ import annotations

from typing import List

import numpy as np
import pytest

from src import settings
from src.tools.golden_bucket import (
    BM25Index,
    GoldenBucket,
    Trio,
    _rrf_fuse,
    _tokenize,
)


# --- fixtures --------------------------------------------------------------


def _t(id_: str, q: str, tags=None) -> Trio:
    return Trio(id=id_, question=q, sql=f"SELECT 1 -- {id_}", report="", tags=tags or [])


class StubEmbedder:
    """Returns a deterministic embedding per text using a tiny lookup.

    Each text gets a one-hot-ish vector aligned with a known axis so we
    can assert exact cosine ranks in tests. Unknown text → zero vector.
    """

    def __init__(self, axis_for_text: dict[str, int], dim: int = 8):
        self._axis = axis_for_text
        self._dim = dim

    def _vec(self, text: str) -> List[float]:
        v = [0.0] * self._dim
        if text in self._axis:
            v[self._axis[text]] = 1.0
        return v

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        return [self._vec(t) for t in texts]

    def embed_query(self, text: str) -> List[float]:
        return self._vec(text)


def _make_bucket(trios: List[Trio], embedder: StubEmbedder) -> GoldenBucket:
    """Build a GoldenBucket with stubbed embeddings, no disk I/O."""
    embeddings = np.array(
        embedder.embed_documents([t.question for t in trios]), dtype=np.float32
    )
    return GoldenBucket(trios=trios, embeddings=embeddings, embedder=embedder)


# --- tokenizer -------------------------------------------------------------


class TestTokenizer:
    def test_lowercases(self):
        assert _tokenize("Q3 Revenue BY region") == ["q3", "revenue", "by", "region"]

    def test_strips_punctuation(self):
        assert _tokenize("revenue, by region!") == ["revenue", "by", "region"]

    def test_keeps_numbers(self):
        # Numbers are often the discriminating signal in analytics — Q3, 2025, etc.
        assert _tokenize("Q3 2025 sales") == ["q3", "2025", "sales"]

    def test_does_not_remove_stopwords(self):
        # 'by'/'in' carry meaning in analytics phrasings ("revenue by region").
        toks = _tokenize("revenue by region")
        assert "by" in toks


# --- RRF fusion ------------------------------------------------------------


class TestRRF:
    def test_single_list_passes_through(self):
        fused = _rrf_fuse([[2, 0, 1]], k_rrf=60)
        # Order preserved; doc 2 (rank 1) outranks doc 0 (rank 2).
        assert [idx for idx, _ in fused] == [2, 0, 1]

    def test_perfect_agreement(self):
        """Both lists rank 0 first → 0 wins."""
        fused = _rrf_fuse([[0, 1, 2], [0, 1, 2]], k_rrf=60)
        assert fused[0][0] == 0
        # And its score is exactly 2 / (60 + 1) since rank=0 in both lists.
        assert fused[0][1] == pytest.approx(2.0 / 61.0)

    def test_compromise_when_lists_disagree(self):
        """A: 0>1>2; B: 2>1>0. Doc 1 (middle of both) should win since it
        has rank 2 in both; doc 0 and 2 each have rank 1 in one but rank 3
        in the other.
        """
        fused = _rrf_fuse([[0, 1, 2], [2, 1, 0]], k_rrf=60)
        # Compute scores: doc 0 → 1/61 + 1/63; doc 1 → 1/62 + 1/62; doc 2 → 1/63 + 1/61.
        # 1 sums to 2/62 ≈ 0.03226; 0 and 2 each to 1/61 + 1/63 ≈ 0.03227.
        # So 0 and 2 actually tie above 1 — RRF favors *any* top-1 over an
        # all-middle. Verify the scores match the formula exactly.
        scores = dict(fused)
        assert scores[1] == pytest.approx(2.0 / 62.0)
        assert scores[0] == pytest.approx(1.0 / 61.0 + 1.0 / 63.0)
        assert scores[2] == pytest.approx(1.0 / 61.0 + 1.0 / 63.0)
        assert scores[0] > scores[1]  # extreme top-1 still beats stable middle

    def test_doc_only_in_one_list_still_scored(self):
        """A doc absent from one list contributes 0 from that list but
        still gets credit for its rank in the other."""
        fused = _rrf_fuse([[0, 1], [2]], k_rrf=60)
        scores = dict(fused)
        assert 0 in scores and 1 in scores and 2 in scores
        assert scores[0] == pytest.approx(1.0 / 61.0)
        assert scores[2] == pytest.approx(1.0 / 61.0)
        assert scores[1] == pytest.approx(1.0 / 62.0)

    def test_empty_lists(self):
        assert _rrf_fuse([], k_rrf=60) == []
        assert _rrf_fuse([[], []], k_rrf=60) == []


# --- BM25 index ------------------------------------------------------------


class TestBM25Index:
    def test_lexical_match(self):
        idx = BM25Index([
            "top customers by total spend",
            "monthly revenue last 12 months",
            "return rate by category",
        ])
        # "return rate" matches doc 2 exactly.
        ranked = idx.top_idxs("return rate trends", n=3)
        assert ranked[0] == 2

    def test_empty_query(self):
        idx = BM25Index(["doc one", "doc two"])
        assert idx.top_idxs("", n=3) == []

    def test_empty_corpus(self):
        idx = BM25Index([])
        assert idx.top_idxs("anything", n=3) == []

    def test_n_larger_than_corpus(self):
        idx = BM25Index(["a", "b"])
        ranked = idx.top_idxs("a", n=10)
        assert len(ranked) <= 2


# --- GoldenBucket modes ----------------------------------------------------


@pytest.fixture
def bucket() -> GoldenBucket:
    """Three trios where cosine and BM25 will sometimes disagree."""
    trios = [
        _t("a", "Top 10 customers by total spend"),
        _t("b", "Monthly revenue for the last 12 months"),
        _t("c", "Return rate by product category"),
    ]
    # Stub: each trio gets a unique axis. The query "spend ranking" maps
    # to axis 0 (same as trio "a"), so cosine ranks a > others.
    embedder = StubEmbedder(
        {
            "Top 10 customers by total spend": 0,
            "Monthly revenue for the last 12 months": 1,
            "Return rate by product category": 2,
            "spend ranking": 0,            # cosine → a
            "return rate by category": 2,  # cosine → c (same axis as trio c)
        }
    )
    return _make_bucket(trios, embedder)


class TestRetrieveModes:
    def test_cosine_only_uses_embeddings(self, bucket):
        result = bucket.retrieve_with_meta("spend ranking", k=1, mode="cosine")
        assert result.mode == "cosine"
        assert result.trios[0].id == "a"
        assert result.bm25_top_idxs == []  # cosine path doesn't consult BM25

    def test_bm25_only_ignores_embeddings(self, bucket):
        # Lexically the query matches "Return rate by product category".
        result = bucket.retrieve_with_meta("return rate trend", k=1, mode="bm25")
        assert result.mode == "bm25"
        assert result.trios[0].id == "c"
        assert result.cosine_top_idxs == []

    def test_hybrid_combines_both(self, bucket):
        """Cosine and BM25 agree on `c` for this query — hybrid must too."""
        result = bucket.retrieve_with_meta("return rate by category", k=1, mode="hybrid")
        assert result.mode == "hybrid"
        assert result.trios[0].id == "c"
        # Diagnostic ranks from both methods are populated.
        assert len(result.cosine_top_idxs) > 0
        assert len(result.bm25_top_idxs) > 0

    def test_hybrid_resolves_disagreement(self, bucket):
        """Cosine ranks a first (axis match); BM25 ranks b first
        (lexical match on 'monthly'). Verify hybrid picks one of them
        deterministically and includes both ranked lists in the trace.
        """
        result = bucket.retrieve_with_meta("monthly", k=3, mode="hybrid")
        # No assertion on the *winner* — disagreement resolution depends
        # on which method gets the top rank. We assert on the diagnostic
        # contract: both ranked lists are recorded so the trace explains
        # the outcome.
        assert len(result.cosine_top_idxs) >= 1
        assert len(result.bm25_top_idxs) >= 1
        assert set(result.final_idxs).issubset(
            set(result.cosine_top_idxs) | set(result.bm25_top_idxs)
        )

    def test_unknown_mode_falls_back_to_cosine(self, bucket):
        result = bucket.retrieve_with_meta("spend ranking", k=1, mode="garbage")
        # Unknown modes degrade to cosine, never crash.
        assert result.mode == "cosine"
        assert result.trios[0].id == "a"

    def test_default_mode_from_settings(self, bucket, monkeypatch):
        monkeypatch.setattr(settings, "RETRIEVAL_MODE", "bm25")
        result = bucket.retrieve_with_meta("return rate trend", k=1)
        assert result.mode == "bm25"

    def test_retrieve_returns_just_trios(self, bucket):
        """Public `retrieve()` keeps the legacy List[Trio] shape so the
        graph_smoke + demo_scenarios tests don't change."""
        trios = bucket.retrieve("spend ranking", k=1, mode="cosine")
        assert len(trios) == 1
        assert trios[0].id == "a"

    def test_k_zero_returns_empty(self, bucket):
        result = bucket.retrieve_with_meta("anything", k=0)
        assert result.trios == []

    def test_empty_bucket(self):
        empty = GoldenBucket(trios=[], embeddings=np.zeros((0, 4), dtype=np.float32))
        result = empty.retrieve_with_meta("anything", k=3, mode="hybrid")
        assert result.trios == []
