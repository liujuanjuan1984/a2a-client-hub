#!/usr/bin/env python
"""Manual worker to drain pending note ingest jobs.

Usage::
    python scripts/run_note_ingest_jobs.py

The script loads .env files, then processes every user that currently has
pending note ingest jobs by reusing the same background execution pipeline as
FastAPI. This is useful for ops or local testing when BackgroundTasks is not
running.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

from dotenv import load_dotenv


def _bootstrap_environment() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    backend_dir = repo_root / "backend"
    for path in (repo_root, backend_dir):
        if str(path) not in sys.path:
            sys.path.insert(0, str(path))

    for env_path in (repo_root / ".env", backend_dir / ".env"):
        if env_path.exists():
            load_dotenv(env_path, override=False)


_bootstrap_environment()

from app.services.note_ingest_jobs import process_all_pending_jobs

logger = logging.getLogger("note_ingest_worker")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    processed_users = process_all_pending_jobs()
    logger.info("Processed pending note ingest queues for %d user(s)", processed_users)


if __name__ == "__main__":
    main()
