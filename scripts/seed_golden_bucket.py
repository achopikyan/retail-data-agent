"""Idempotent seed: ensure the Golden Bucket embeddings cache exists.

Run once after install:  python -m scripts.seed_golden_bucket
"""
from __future__ import annotations

import logging

from src import settings
from src.tools.golden_bucket import GoldenBucket


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    if settings.GOLDEN_EMBEDDINGS_PATH.exists():
        print(f"Embeddings already at {settings.GOLDEN_EMBEDDINGS_PATH}. Nothing to do.")
        return
    bucket = GoldenBucket.load()
    print(f"Embedded {len(bucket.trios)} trios → {settings.GOLDEN_EMBEDDINGS_PATH}")


if __name__ == "__main__":
    main()
