"""Exception definitions shared by note handlers."""

from __future__ import annotations


class NoteNotFoundError(Exception):
    """Raised when a note is not found."""


class TagNotFoundError(Exception):
    """Raised when a tag is not found."""


class TagAlreadyAssociatedError(Exception):
    """Raised when a tag is already associated with a note."""


class TagNotAssociatedError(Exception):
    """Raised when a tag is not associated with a note."""


class InvalidOperationError(Exception):
    """Raised when an invalid operation is attempted."""


__all__ = [
    "InvalidOperationError",
    "NoteNotFoundError",
    "TagAlreadyAssociatedError",
    "TagNotAssociatedError",
    "TagNotFoundError",
]
