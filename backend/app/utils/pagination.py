"""Shared pagination helpers."""

from __future__ import annotations

from typing import Iterable, TypeVar

from app.schemas.pagination import Pagination

T = TypeVar("T")


def paginate(
    items: Iterable[T],
    *,
    page: int,
    size: int,
    total: int | None = None,
) -> tuple[list[T], Pagination]:
    """Slice items and build pagination metadata."""

    item_list = list(items)
    effective_total = total if total is not None else len(item_list)
    pages = (effective_total + size - 1) // size if size else 0
    offset = (page - 1) * size

    # If we didn't get a total, we assume item_list is the full set and we slice it.
    # If we DID get a total, we assume item_list is already a slice.
    if total is None:
        page_items = item_list[offset : offset + size]
    else:
        page_items = item_list

    pagination = Pagination(
        page=page,
        size=size,
        total=effective_total,
        pages=pages,
    )
    return page_items, pagination
