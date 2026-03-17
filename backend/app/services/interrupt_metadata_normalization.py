"""Helpers for normalizing richer interrupt metadata into display-safe fields."""

from __future__ import annotations

from typing import Any, Iterable, Sequence

from app.utils.payload_extract import as_dict
from app.utils.session_identity import normalize_non_empty_text


def _pick_non_empty_text(payload: dict[str, Any], keys: Iterable[str]) -> str | None:
    for key in keys:
        value = normalize_non_empty_text(payload.get(key))
        if value:
            return value
    return None


def _resolve_nested_value(payload: dict[str, Any], path: Sequence[str]) -> Any:
    current: Any = payload
    for key in path:
        record = as_dict(current)
        if not record:
            return None
        current = record.get(key)
    return current


def _pick_nested_non_empty_text(
    payload: dict[str, Any], paths: Sequence[Sequence[str]]
) -> str | None:
    for path in paths:
        current = _resolve_nested_value(payload, path)
        value = normalize_non_empty_text(current)
        if value:
            return value
    return None


def _pick_first_list(
    payload: dict[str, Any], paths: Sequence[Sequence[str]]
) -> list[Any]:
    for path in paths:
        current = _resolve_nested_value(payload, path)
        if isinstance(current, list):
            return current
    return []


def extract_interrupt_display_message(details: dict[str, Any]) -> str | None:
    return _pick_non_empty_text(
        details,
        (
            "display_message",
            "displayMessage",
            "message",
            "description",
            "prompt",
            "reason",
            "request",
            "context",
        ),
    ) or _pick_nested_non_empty_text(
        details,
        (
            ("request", "message"),
            ("request", "description"),
            ("request", "prompt"),
            ("request", "reason"),
            ("context", "message"),
            ("context", "description"),
            ("context", "prompt"),
            ("context", "reason"),
            ("prompt", "message"),
            ("prompt", "description"),
        ),
    )


def normalize_permission_interrupt_details(details: dict[str, Any]) -> dict[str, Any]:
    patterns = details.get("patterns")
    normalized = {
        "permission": normalize_non_empty_text(details.get("permission")),
        "patterns": (
            [item for item in patterns if isinstance(item, str)]
            if isinstance(patterns, list)
            else []
        ),
    }
    display_message = extract_interrupt_display_message(details)
    if display_message:
        normalized["display_message"] = display_message
    return normalized


def _normalize_question_option(entry: Any) -> dict[str, Any] | None:
    option = as_dict(entry)
    if not option:
        return None
    label = _pick_non_empty_text(option, ("label",))
    if not label:
        return None
    return {
        "label": label,
        "description": _pick_non_empty_text(option, ("description",)),
        "value": _pick_non_empty_text(option, ("value",)),
    }


def _normalize_question_entry(entry: Any) -> dict[str, Any] | None:
    candidate = as_dict(entry)
    if not candidate:
        return None

    question = _pick_non_empty_text(
        candidate,
        ("question", "prompt", "message"),
    ) or _pick_nested_non_empty_text(
        candidate,
        (
            ("request", "question"),
            ("request", "prompt"),
            ("request", "message"),
            ("context", "question"),
            ("context", "prompt"),
            ("context", "message"),
            ("prompt", "question"),
            ("prompt", "message"),
        ),
    )
    if not question:
        return None

    raw_options = _pick_first_list(
        candidate,
        (
            ("options",),
            ("request", "options"),
            ("context", "options"),
            ("prompt", "options"),
        ),
    )
    options = [
        normalized
        for normalized in (
            _normalize_question_option(raw_option) for raw_option in raw_options
        )
        if normalized is not None
    ]

    return {
        "header": _pick_non_empty_text(candidate, ("header", "title"))
        or _pick_nested_non_empty_text(
            candidate,
            (
                ("request", "header"),
                ("request", "title"),
                ("context", "header"),
                ("context", "title"),
            ),
        ),
        "question": question,
        "description": _pick_non_empty_text(
            candidate,
            ("description", "hint", "help_text", "helpText"),
        )
        or _pick_nested_non_empty_text(
            candidate,
            (
                ("request", "description"),
                ("context", "description"),
                ("prompt", "description"),
            ),
        ),
        "options": options,
    }


def normalize_question_interrupt_details(details: dict[str, Any]) -> dict[str, Any]:
    questions = _pick_first_list(
        details,
        (
            ("questions",),
            ("request", "questions"),
            ("context", "questions"),
        ),
    )
    normalized_questions = [
        normalized
        for normalized in (_normalize_question_entry(entry) for entry in questions)
        if normalized is not None
    ]
    normalized = {"questions": normalized_questions}
    display_message = extract_interrupt_display_message(details)
    if display_message:
        normalized["display_message"] = display_message
    return normalized
