from __future__ import annotations

from app.schemas.pagination import Pagination


def compute_offset(page: int, size: int) -> int:
    """Compute the SQL OFFSET for a given page and size."""
    return (max(1, page) - 1) * max(1, size)


def build_pagination_meta(total: int, page: int, size: int) -> Pagination:
    """Build standardized pagination metadata."""
    safe_size = max(1, size)
    return Pagination(
        page=page,
        size=size,
        total=total,
        pages=(total + safe_size - 1) // safe_size if safe_size else 0,
    )
