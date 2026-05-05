"""Curator job — promote 👍 feedback into the Golden Bucket.

For every unpromoted, up-voted pending_trios row we:
  1. Embed the question.
  2. Reject if cosine similarity ≥ 0.92 against any existing trio
     (seed or already-curated). Avoids duplicates.
  3. Score with a Gemini judge (1–5 on 4 axes).
  4. Promote ones whose average score ≥ 4.0 into data/curated_trios.json.
  5. Re-build the embeddings cache so retrieval picks them up.
  6. Mark the source rows as `promoted=1` in SQLite.

Usage:
    python -m scripts.curate           # production-style run
    python -m scripts.curate --dry-run # show what would happen, no writes
    python -m scripts.curate --min-score 3.5  # override threshold
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import uuid
from typing import Any, Dict, List

import numpy as np
from langchain_core.messages import HumanMessage, SystemMessage

from src import settings
from src.llm.gemini import GeminiLLM, build_embeddings
from src.tools import feedback_store
from src.tools.golden_bucket import GoldenBucket, Trio


_SIMILARITY_DEDUPE = 0.92


_JUDGE_SYS = """You are a strict QA reviewer scoring an analyst Trio (Question, SQL, Report)
for inclusion in the Golden Bucket of approved exemplars. Score 1–5 on each:

- sql_correctness: does the SQL look like it answers the question accurately?
  (Look for safe joins, sensible filters, fully qualified table names.)
- report_clarity: is the report concise, accurate, and useful to an executive?
- factual_consistency: does the report match what the SQL would return?
- generalizability: is this Trio likely to be useful as a few-shot example
  for similar future questions? (Or is it too narrow / too specific?)

Return ONLY a JSON object: {"sql_correctness": int, "report_clarity": int, "factual_consistency": int, "generalizability": int, "comment": "<one sentence>"}.
"""


def _load_curated() -> List[Trio]:
    path = settings.CURATED_TRIOS_PATH
    if not path.exists():
        return []
    with open(path, "r", encoding="utf-8") as f:
        return [Trio.from_dict(t) for t in json.load(f)]


def _save_curated(trios: List[Trio]) -> None:
    path = settings.CURATED_TRIOS_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = [
        {"id": t.id, "question": t.question, "sql": t.sql, "report": t.report, "tags": t.tags}
        for t in trios
    ]
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)


def _embed_questions(embedder, questions: List[str]) -> np.ndarray:
    return np.array(embedder.embed_documents(questions), dtype=np.float32)


def _max_cosine(query_vec: np.ndarray, bank: np.ndarray) -> float:
    if bank.size == 0:
        return 0.0
    bank_norm = bank / (np.linalg.norm(bank, axis=-1, keepdims=True) + 1e-12)
    q_norm = query_vec / (np.linalg.norm(query_vec) + 1e-12)
    return float(np.max(bank_norm @ q_norm))


def _judge(llm: GeminiLLM, question: str, sql: str, report: str) -> Dict[str, Any]:
    msg = (
        f"Question:\n{question}\n\nSQL:\n{sql}\n\nReport:\n{report}\n"
    )
    try:
        resp = llm.invoke([SystemMessage(content=_JUDGE_SYS), HumanMessage(content=msg)])
        text = resp.content if hasattr(resp, "content") else str(resp)
        text = text.strip()
        if text.startswith("```"):
            text = text.split("```")[1].lstrip("json").strip()
        return json.loads(text)
    except Exception as e:  # noqa: BLE001
        return {
            "sql_correctness": 0,
            "report_clarity": 0,
            "factual_consistency": 0,
            "generalizability": 0,
            "comment": f"judge error: {e}",
        }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="No writes; print decisions only")
    parser.add_argument("--min-score", type=float, default=4.0, help="Minimum average judge score")
    args = parser.parse_args()

    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")

    candidates = feedback_store.list_unpromoted_upvoted()
    if not candidates:
        print("nothing to curate (no unpromoted up-voted trios).")
        return 0

    print(f"loaded {len(candidates)} candidate(s) from pending_trios.")

    # Build the existing-bucket corpus to dedupe against.
    seed = GoldenBucket.load()
    existing = list(seed.trios) + _load_curated()
    embedder = build_embeddings()
    existing_vecs = (
        _embed_questions(embedder, [t.question for t in existing])
        if existing
        else np.zeros((0, 1), dtype=np.float32)
    )

    llm = GeminiLLM()
    promoted: List[Trio] = list(_load_curated())
    promoted_trace_ids: List[str] = []

    for cand in candidates:
        # Dedup
        cand_vec = np.array(embedder.embed_query(cand.question), dtype=np.float32)
        sim = _max_cosine(cand_vec, existing_vecs)
        if sim >= _SIMILARITY_DEDUPE:
            print(f"  [skip] '{cand.question[:60]}'  reason=duplicate (sim={sim:.3f})")
            continue

        # Judge
        scores = _judge(llm, cand.question, cand.sql, cand.report)
        avg = (
            scores["sql_correctness"]
            + scores["report_clarity"]
            + scores["factual_consistency"]
            + scores["generalizability"]
        ) / 4.0
        decision = "promote" if avg >= args.min_score else "skip"
        print(f"  [{decision}] '{cand.question[:60]}'  avg={avg:.2f}  ({scores.get('comment','')})")

        if decision == "promote":
            new_trio = Trio(
                id=f"curated-{uuid.uuid4().hex[:6]}",
                question=cand.question,
                sql=cand.sql,
                report=cand.report,
                tags=["curated"],
            )
            promoted.append(new_trio)
            promoted_trace_ids.append(cand.trace_id)
            # Refresh existing vectors so subsequent dedup considers this one.
            existing_vecs = np.vstack([existing_vecs, cand_vec[None, :]]) if existing_vecs.size else cand_vec[None, :]

    if args.dry_run:
        print(f"\n(dry-run) would promote {len(promoted_trace_ids)} new trio(s).")
        return 0

    if not promoted_trace_ids:
        print("\nno promotions this run.")
        return 0

    _save_curated(promoted)
    feedback_store.mark_promoted(promoted_trace_ids)

    # Re-embed the full bucket so the agent picks up the new examples.
    seed_vecs = _embed_questions(embedder, [t.question for t in seed.trios])
    cur_vecs = (
        _embed_questions(embedder, [t.question for t in promoted])
        if promoted
        else np.zeros((0, seed_vecs.shape[1]), dtype=np.float32)
    )
    combined = np.vstack([seed_vecs, cur_vecs]) if cur_vecs.size else seed_vecs
    np.save(settings.GOLDEN_EMBEDDINGS_PATH, combined)

    print(f"\npromoted {len(promoted_trace_ids)} new trio(s) into {settings.CURATED_TRIOS_PATH}")
    print(f"refreshed embeddings cache → {settings.GOLDEN_EMBEDDINGS_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
