"""Lightweight sync checker for backend/UI constants.

Compares backend constants with frontend config for:
- Theme options
- Navigation visible modules defaults

Usage:
  python scripts/check_ui_constants_sync.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Iterable, List

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPO_ROOT / "backend"
FRONTEND_ROOT = REPO_ROOT / "frontend"

sys.path.insert(0, str(BACKEND_ROOT))

try:
    from app.core import constants as backend_constants
except Exception as exc:  # pragma: no cover - runtime guard
    print(f"Failed to import backend constants: {exc}")
    sys.exit(2)


def _extract_bracket_block(text: str, start_index: int, open_char: str, close_char: str) -> str:
    open_index = text.find(open_char, start_index)
    if open_index == -1:
        raise ValueError(f"Missing opening '{open_char}' in text")
    depth = 0
    for idx in range(open_index, len(text)):
        char = text[idx]
        if char == open_char:
            depth += 1
        elif char == close_char:
            depth -= 1
            if depth == 0:
                return text[open_index : idx + 1]
    raise ValueError(f"Missing closing '{close_char}' in text")


def _extract_theme_options() -> List[str]:
    settings_path = FRONTEND_ROOT / "src" / "config" / "settingsConfig.tsx"
    text = settings_path.read_text(encoding="utf-8")
    key_index = text.find('key: "theme"')
    if key_index == -1:
        raise ValueError("Unable to locate theme settings in frontend config")
    options_index = text.find("options", key_index)
    if options_index == -1:
        raise ValueError("Unable to locate theme options block in frontend config")
    options_block = _extract_bracket_block(text, options_index, "[", "]")
    return re.findall(r'value:\s*"([^"]+)"', options_block)


def _split_top_level_objects(block: str) -> List[str]:
    items: List[str] = []
    depth = 0
    start = None
    for idx, char in enumerate(block):
        if char == "{":
            if depth == 0:
                start = idx
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0 and start is not None:
                items.append(block[start : idx + 1])
                start = None
    return items


def _extract_visible_modules() -> List[str]:
    modules_path = FRONTEND_ROOT / "src" / "config" / "modulesConfig.ts"
    text = modules_path.read_text(encoding="utf-8")
    export_index = text.find("export const MODULES")
    if export_index == -1:
        raise ValueError("Unable to locate MODULES definition in frontend config")
    modules_block = _extract_bracket_block(text, export_index, "[", "]")
    modules = _split_top_level_objects(modules_block)
    visible: List[str] = []
    for module in modules:
        key_match = re.search(r'key:\s*"([^"]+)"', module)
        if not key_match:
            continue
        if re.search(r"showInNav:\s*true", module):
            visible.append(key_match.group(1))
    return visible


def _format_diff(label: str, missing: Iterable[str]) -> List[str]:
    items = sorted(set(missing))
    if not items:
        return []
    joined = ", ".join(items)
    return [f"  - {label}: {joined}"]


def main() -> int:
    backend_themes = sorted(backend_constants.APP_THEME_OPTIONS)
    backend_visible = list(backend_constants.NAVIGATION_VISIBLE_MODULE_DEFAULTS)

    frontend_themes = _extract_theme_options()
    frontend_visible = _extract_visible_modules()

    errors: List[str] = []

    missing_in_backend = set(frontend_themes) - set(backend_themes)
    missing_in_frontend = set(backend_themes) - set(frontend_themes)
    if missing_in_backend or missing_in_frontend:
        errors.append("Theme options mismatch:")
        errors.extend(_format_diff("Missing in backend", missing_in_backend))
        errors.extend(_format_diff("Missing in frontend", missing_in_frontend))

    missing_defaults_in_backend = set(frontend_visible) - set(backend_visible)
    missing_defaults_in_frontend = set(backend_visible) - set(frontend_visible)
    if missing_defaults_in_backend or missing_defaults_in_frontend:
        errors.append("Navigation default modules mismatch:")
        errors.extend(
            _format_diff("Missing in backend defaults", missing_defaults_in_backend)
        )
        errors.extend(
            _format_diff("Missing in frontend defaults", missing_defaults_in_frontend)
        )

    if errors:
        print("UI constants drift detected:\n" + "\n".join(errors))
        return 1

    print("UI constants are in sync.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
