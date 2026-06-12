"""
Backfill script: re-index toàn bộ quiz public hiện có trong PostgreSQL vào Qdrant.

Usage (theo PHASE2_SETUP.md mục Setup Step 4):
    docker compose exec backend python -m scripts.backfill_embeddings
hoặc:
    cd backend && python -m scripts.backfill_embeddings

Idempotent: chạy nhiều lần an toàn (Qdrant upsert by point ID).
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from typing import Optional

from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.services.ingestion_service import reingest_all_public_quizzes

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("backfill")


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Backfill Qdrant embeddings for public quizzes")
    p.add_argument(
        "--batch-size",
        type=int,
        default=50,
        help="Số quiz ingest mỗi lần log progress (mặc định 50)",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Chỉ đếm quiz public, không gọi Qdrant/embedding",
    )
    return p.parse_args()


def _count_public_quizzes(db: Session) -> int:
    from app.models.quiz.quizzes import Quiz

    return (
        db.query(Quiz)
        .filter(Quiz.is_deleted.is_(False), Quiz.is_public.is_(True))
        .count()
    )


def main() -> int:
    args = _parse_args()
    db = SessionLocal()
    try:
        total = _count_public_quizzes(db)
        logger.info("Found %s public quizzes (not deleted)", total)

        if args.dry_run:
            logger.info("[dry-run] skip ingestion.")
            return 0

        if total == 0:
            logger.info("Nothing to do.")
            return 0

        t0 = time.time()
        count = reingest_all_public_quizzes(db, batch_size=args.batch_size)
        elapsed = time.time() - t0
        logger.info(
            "Backfill done: %s/%s quizzes in %.1fs (%.2fs/quiz)",
            count,
            total,
            elapsed,
            (elapsed / count) if count else 0.0,
        )
        return 0 if count == total else 1
    except Exception as e:  # noqa: BLE001
        logger.exception("Backfill failed: %s", e)
        return 2
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
