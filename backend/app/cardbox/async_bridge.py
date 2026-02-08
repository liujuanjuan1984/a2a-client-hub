"""Async bridge utilities for the Cardbox subsystem.

Cardbox still runs with synchronous services.  To avoid sprinkling
``run_with_session`` or other ad-hoc adapters in the API layer, this module
offers a single async-friendly bridge for CPU bound work and for functions
that require a traditional SQLAlchemy ``Session``.
"""

from __future__ import annotations

from functools import partial
from typing import Any, Callable, TypeVar

import anyio
from sqlalchemy.orm import Session

from app.db.session import SessionLocal

T = TypeVar("T")


async def run_cardbox_io(func: Callable[..., T], /, *args: Any, **kwargs: Any) -> T:
    """Run a Cardbox helper in a worker thread to protect the event loop."""

    bound = partial(func, *args, **kwargs)
    return await anyio.to_thread.run_sync(bound, abandon_on_cancel=False)


async def run_cardbox_with_session(
    func: Callable[[Session], T], /, *args: Any, **kwargs: Any
) -> T:
    """Open an isolated sync ``Session`` and execute ``func`` in a thread."""

    def _call_with_session() -> T:
        session: Session = SessionLocal()
        try:
            return func(session, *args, **kwargs)
        finally:
            session.close()

    return await anyio.to_thread.run_sync(_call_with_session, abandon_on_cancel=False)


__all__ = ["run_cardbox_io", "run_cardbox_with_session"]
