"""Helpers for normalizing richer interrupt metadata into display-safe fields."""

from __future__ import annotations

import json
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


def _dedupe_non_empty_strings(values: Iterable[Any]) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = normalize_non_empty_text(value)
        if text is None or text in seen:
            continue
        seen.add(text)
        normalized.append(text)
    return normalized


def _normalize_patterns(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return _dedupe_non_empty_strings(value)


def _extract_paths_from_mapping_entries(
    values: list[Any], *, field_names: Sequence[str]
) -> list[str]:
    paths: list[str] = []
    for item in values:
        record = as_dict(item)
        if not record:
            continue
        for field_name in field_names:
            path = normalize_non_empty_text(record.get(field_name))
            if path:
                paths.append(path)
    return _dedupe_non_empty_strings(paths)


def _truncate_json_text(value: Any, *, max_length: int = 240) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        normalized = normalize_non_empty_text(value)
        if normalized is None:
            return None
        return normalized[:max_length]
    try:
        serialized = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    except TypeError:
        serialized = repr(value)
    normalized = normalize_non_empty_text(serialized)
    if normalized is None:
        return None
    return normalized[:max_length]


def _extract_codex_raw_interrupt_metadata(
    provider_context: dict[str, Any] | None,
) -> tuple[dict[str, Any], str | None]:
    provider_metadata = as_dict(provider_context)
    metadata = as_dict(provider_metadata.get("metadata"))
    return as_dict(metadata.get("raw")), normalize_non_empty_text(
        metadata.get("method")
    )


def _extract_codex_permission_fallback(
    provider_context: dict[str, Any] | None,
) -> dict[str, Any]:
    raw, method = _extract_codex_raw_interrupt_metadata(provider_context)
    if not raw:
        return {}

    patterns = _dedupe_non_empty_strings(
        [
            *_normalize_patterns(raw.get("targets")),
            *_normalize_patterns(raw.get("paths")),
            *_normalize_patterns(raw.get("files")),
            normalize_non_empty_text(raw.get("path")),
            normalize_non_empty_text(raw.get("target")),
            normalize_non_empty_text(_resolve_nested_value(raw, ("request", "path"))),
            normalize_non_empty_text(_resolve_nested_value(raw, ("request", "target"))),
            *_extract_paths_from_mapping_entries(
                _pick_first_list(raw, (("parsedCmd",), ("parsed_cmd",))),
                field_names=("path", "target"),
            ),
        ]
    )
    display_message = _pick_nested_non_empty_text(
        raw,
        (
            ("request", "description"),
            ("request", "message"),
            ("request", "title"),
            ("context", "description"),
            ("context", "message"),
            ("context", "title"),
        ),
    ) or _pick_non_empty_text(
        raw,
        (
            "title",
            "message",
            "description",
            "prompt",
            "reason",
        ),
    )
    if display_message is None:
        command_preview = None
        parsed_commands = _pick_first_list(raw, (("parsedCmd",), ("parsed_cmd",)))
        if parsed_commands:
            command_preview = _pick_non_empty_text(
                as_dict(parsed_commands[0]), ("cmd",)
            )
        if command_preview is None:
            command = raw.get("command")
            if isinstance(command, list):
                command_preview = (
                    " ".join(
                        item for item in command if isinstance(item, str) and item
                    ).strip()
                    or None
                )
            else:
                command_preview = normalize_non_empty_text(command)
        if command_preview is not None:
            display_message = f"Approval requested for command: {command_preview}"
        elif patterns:
            method_label = "operation"
            if method in {"item/fileChange/requestApproval", "applyPatchApproval"}:
                method_label = "file change"
            elif method in {
                "item/commandExecution/requestApproval",
                "execCommandApproval",
            }:
                method_label = "command"
            display_message = f"Approval requested for {method_label}."
        else:
            display_message = _truncate_json_text(raw)

    fallback: dict[str, Any] = {}
    if display_message:
        fallback["display_message"] = display_message
    if patterns:
        fallback["patterns"] = patterns
    return fallback


def _extract_codex_question_fallback(
    provider_context: dict[str, Any] | None,
) -> dict[str, Any]:
    raw, _ = _extract_codex_raw_interrupt_metadata(provider_context)
    if not raw:
        return {}

    fallback: dict[str, Any] = {}
    display_message = _pick_nested_non_empty_text(
        raw,
        (
            ("context", "description"),
            ("context", "message"),
            ("request", "description"),
            ("request", "message"),
        ),
    ) or _pick_non_empty_text(
        raw,
        (
            "description",
            "message",
            "prompt",
            "title",
        ),
    )
    if display_message:
        fallback["display_message"] = display_message

    questions = _pick_first_list(raw, (("questions",), ("context", "questions")))
    normalized_questions = [
        normalized
        for normalized in (_normalize_question_entry(entry) for entry in questions)
        if normalized is not None
    ]
    if normalized_questions:
        fallback["questions"] = normalized_questions
    return fallback


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


def normalize_permission_interrupt_details(
    details: dict[str, Any],
    *,
    provider_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    patterns = details.get("patterns")
    normalized_patterns = _normalize_patterns(patterns)
    normalized: dict[str, Any] = {
        "permission": normalize_non_empty_text(details.get("permission")),
        "patterns": normalized_patterns,
    }
    display_message = extract_interrupt_display_message(details)
    fallback = _extract_codex_permission_fallback(provider_context)
    fallback_patterns = fallback.get("patterns")
    if isinstance(fallback_patterns, list):
        normalized["patterns"] = _dedupe_non_empty_strings(
            [*normalized_patterns, *fallback_patterns]
        )
    if display_message:
        normalized["display_message"] = display_message
    elif isinstance(fallback.get("display_message"), str):
        normalized["display_message"] = fallback["display_message"]
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


def normalize_question_interrupt_details(
    details: dict[str, Any],
    *,
    provider_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
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
    fallback = _extract_codex_question_fallback(provider_context)
    if not normalized_questions:
        fallback_questions = fallback.get("questions")
        if isinstance(fallback_questions, list):
            normalized_questions = fallback_questions
    normalized: dict[str, Any] = {"questions": normalized_questions}
    display_message = extract_interrupt_display_message(details)
    if display_message:
        normalized["display_message"] = display_message
    elif isinstance(fallback.get("display_message"), str):
        normalized["display_message"] = fallback["display_message"]
    return normalized
