"""
Centralised APScheduler management.

This module exposes a shared AsyncIOScheduler instance so that different
services can register background jobs while ensuring the scheduler lifecycle
is controlled by the FastAPI application.
"""

from __future__ import annotations

import asyncio

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.core.logging import get_logger

logger = get_logger(__name__)

# Global scheduler instance shared across the application.
_scheduler: AsyncIOScheduler | None = None


def _ensure_scheduler_bound_to_current_loop() -> AsyncIOScheduler:
    """Create or refresh the scheduler so it targets the active event loop."""

    global _scheduler

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = asyncio.get_event_loop_policy().get_event_loop()

    if _scheduler is None:
        _scheduler = AsyncIOScheduler(event_loop=loop)
        return _scheduler

    scheduler_loop = getattr(_scheduler, "_eventloop", None)
    if scheduler_loop is None or scheduler_loop.is_closed():
        _scheduler = AsyncIOScheduler(event_loop=loop)
        return _scheduler

    if scheduler_loop is not loop:
        logger.debug("Rebinding APScheduler to the current event loop.")
        if _scheduler.running:
            _scheduler.shutdown(wait=False)
        _scheduler = AsyncIOScheduler(event_loop=loop)
        return _scheduler

    return _scheduler


def get_scheduler() -> AsyncIOScheduler:
    """Return the shared AsyncIOScheduler instance."""

    if _scheduler is None:
        raise RuntimeError("Scheduler has not been started yet.")
    return _scheduler


def start_scheduler() -> None:
    """Start the scheduler if it is not already running."""

    scheduler = _ensure_scheduler_bound_to_current_loop()

    if scheduler.running:
        logger.debug("APScheduler already running; skipping start.")
        return
    scheduler.start()
    logger.info("APScheduler started.")


def shutdown_scheduler() -> None:
    """Shutdown the scheduler if it is currently running."""

    global _scheduler

    if _scheduler is None:
        logger.debug("APScheduler not initialised; skipping shutdown.")
        return

    if not _scheduler.running:
        logger.debug("APScheduler already stopped; skipping shutdown.")
        _scheduler = None
        return

    _scheduler.shutdown(wait=False)
    logger.info("APScheduler stopped.")

    _scheduler = None
