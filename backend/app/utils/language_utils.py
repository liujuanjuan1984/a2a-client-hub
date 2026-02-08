"""Helpers for describing language codes in human-readable form."""

from __future__ import annotations

from typing import Optional

_LANGUAGE_NAMES = {
    "zh": "Simplified Chinese",
    "zh-cn": "Simplified Chinese",
    "zh-hans": "Simplified Chinese",
    "zh-tw": "Traditional Chinese",
    "zh-hant": "Traditional Chinese",
    "ja": "Japanese",
    "ko": "Korean",
    "es": "Spanish",
    "fr": "French",
    "de": "German",
    "en": "English",
    "en-us": "English",
    "en-gb": "English",
}


def describe_language(code: Optional[str]) -> str:
    """
    Convert a language code into a readable description for prompts.

    Defaults to English when the code is missing or unrecognised.
    """

    normalized = (code or "en").strip().lower()
    if not normalized:
        return "English"
    return _LANGUAGE_NAMES.get(normalized, normalized)


__all__ = ["describe_language"]
