from __future__ import annotations

import sys
from pathlib import Path


def _top_level_importable_names(app_dir: Path) -> set[str]:
    names: set[str] = set()
    for entry in app_dir.iterdir():
        if entry.name == "__pycache__":
            continue
        if entry.is_dir():
            names.add(entry.name)
            continue
        if (
            entry.is_file()
            and entry.suffix == ".py"
            and not entry.name.startswith("__")
        ):
            names.add(entry.stem)
    return names


def test_backend_app_top_level_names_do_not_shadow_stdlib_modules() -> None:
    app_dir = Path(__file__).resolve().parents[2] / "app"
    collisions = sorted(
        _top_level_importable_names(app_dir) & set(sys.stdlib_module_names)
    )

    assert (
        collisions == []
    ), "Top-level names under backend/app shadow stdlib modules: " + ", ".join(
        collisions
    )
