"""Async runtime debugging helpers."""

from __future__ import annotations

import traceback
import tracemalloc
import warnings
from typing import Callable, Optional

from app.core.logging import get_logger

_logger = get_logger(__name__)
_configured = False
_original_showwarning: Optional[Callable] = None


def enable_unawaited_coroutine_logging(*, stack_limit: int = 20) -> None:
    """Log stack traces when RuntimeWarning reports an un-awaited coroutine."""

    global _configured, _original_showwarning
    if _configured:
        return
    _configured = True

    if not tracemalloc.is_tracing():
        try:
            tracemalloc.start()
        except RuntimeError:
            pass

    _original_showwarning = warnings.showwarning

    def _showwarning(
        message,
        category,
        filename,
        lineno,
        file=None,
        line=None,
    ):
        text = str(message)
        if category is RuntimeWarning and "was never awaited" in text:
            stack = "".join(traceback.format_stack(limit=stack_limit))
            memory_summary = ""
            if tracemalloc.is_tracing():
                try:
                    snapshot = tracemalloc.take_snapshot()
                    top = snapshot.statistics("lineno")[:3]
                    if top:
                        formatted = [
                            f"{stat.count}x {stat.size / 1024:.1f} KiB @ {stat.traceback[0]}"
                            for stat in top
                        ]
                        memory_summary = "\nTop allocations:\n" + "\n".join(formatted)
                except Exception:
                    memory_summary = ""

            _logger.error(
                "Un-awaited coroutine detected: %s\nOrigin stack (most recent call last):\n%s%s",
                text,
                stack,
                memory_summary,
            )

        if _original_showwarning is not None:
            _original_showwarning(message, category, filename, lineno, file, line)
        else:  # pragma: no cover - fallback for unusual environments
            warnings._showwarnmsg_impl(
                warnings.WarningMessage(message, category, filename, lineno, file, line)
            )

    warnings.showwarning = _showwarning
    warnings.filterwarnings(
        "always",
        message="coroutine .* was never awaited",
        category=RuntimeWarning,
    )


__all__ = ["enable_unawaited_coroutine_logging"]
