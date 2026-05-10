"""Centralized settings loaded from environment / .env."""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")


def _get(key: str, default: str | None = None, required: bool = False) -> str:
    val = os.getenv(key, default)
    if required and not val:
        raise RuntimeError(f"Missing required env var: {key}")
    return val or ""


GOOGLE_API_KEY = _get("GOOGLE_API_KEY", required=False)
GOOGLE_CLOUD_PROJECT = _get("GOOGLE_CLOUD_PROJECT", required=False)

# Defaults are free-tier-friendly. gemini-2.5-pro is on a strict free
# tier (limit=0 on auto-created AI Studio projects), so the default
# "primary" tier is Flash and the fallback is Flash-Lite. Override in
# .env if you have paid quota and want Pro.
GEMINI_MODEL_PRO = _get("GEMINI_MODEL_PRO", "gemini-2.5-flash")
GEMINI_MODEL_FLASH = _get("GEMINI_MODEL_FLASH", "gemini-2.5-flash-lite")
GEMINI_EMBEDDING_MODEL = _get("GEMINI_EMBEDDING_MODEL", "gemini-embedding-001")

DATASET = "bigquery-public-data.thelook_ecommerce"
ALLOWED_TABLES = ("orders", "order_items", "products", "users")

PERSONA_CONFIG_PATH = ROOT / _get("PERSONA_CONFIG_PATH", "config/personas.yaml")
GOLDEN_TRIOS_PATH = ROOT / _get("GOLDEN_TRIOS_PATH", "data/golden_trios.json")
CURATED_TRIOS_PATH = ROOT / _get("CURATED_TRIOS_PATH", "data/curated_trios.json")
GOLDEN_EMBEDDINGS_PATH = ROOT / _get(
    "GOLDEN_EMBEDDINGS_PATH", "data/golden_trios.embeddings.npy"
)
APP_DB_PATH = ROOT / _get("APP_DB_PATH", "data/app.db")
LOG_DIR = ROOT / _get("LOG_DIR", "logs")

SQL_RETRY_LIMIT = int(_get("SQL_RETRY_LIMIT", "2"))
LLM_RETRY_LIMIT = int(_get("LLM_RETRY_LIMIT", "3"))
DEFAULT_USER_ID = _get("DEFAULT_USER_ID", "demo_manager")

# Golden Bucket retrieval mode. "hybrid" combines cosine (semantic) +
# BM25 (lexical) via Reciprocal Rank Fusion — the production-RAG default.
# "cosine" / "bm25" are available for A/B comparison without code changes.
RETRIEVAL_MODE = _get("RETRIEVAL_MODE", "hybrid")  # "cosine" | "bm25" | "hybrid"
# k_rrf in the RRF formula (1 / (k_rrf + rank)). 60 is the de-facto standard
# from the original RRF paper; smaller values weight top ranks more heavily.
RETRIEVAL_RRF_K = int(_get("RETRIEVAL_RRF_K", "60"))
# How deep to read each ranked list before fusing. Trios outside both
# top-N lists contribute zero, so smaller is faster but riskier.
RETRIEVAL_FUSION_DEPTH = int(_get("RETRIEVAL_FUSION_DEPTH", "20"))

# How many recent messages (user + assistant) to load into the
# contextualize step. Bounded so prompt size stays predictable on long
# threads. Past this, older turns are not summarized — production tier-3
# would add vector retrieval over them.
MAX_HISTORY_MESSAGES = int(_get("MAX_HISTORY_MESSAGES", "10"))

# Hard cap on turns per thread before the system nudges the user to
# start a fresh thread. Keeps prompt cost bounded and resolution sharp.
THREAD_TURN_CAP = int(_get("THREAD_TURN_CAP", "20"))
