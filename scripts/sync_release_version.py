#!/usr/bin/env python3
"""Synchronize metadata version fields with a unified repository release version."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
VERSION_FILE = ROOT / "VERSION"

SEMVER_PATTERN = re.compile(
    r"^(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)"
    r"(?:-[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?"
    r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$"
)


def _read_version_from_file(path: Path = VERSION_FILE) -> str:
    raw = path.read_text(encoding="utf-8").strip()
    return raw.splitlines()[0].strip() if raw else ""


def _write_version_file(version: str) -> tuple[bool, str]:
    previous = _read_version_from_file()
    if previous == version:
        return False, previous

    VERSION_FILE.write_text(f"{version}\n", encoding="utf-8")
    return True, previous


def _validate_version(version: str) -> None:
    if not SEMVER_PATTERN.match(version):
        raise ValueError(f"Invalid semantic version: {version}")


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _update_toml_version(path: Path, version: str, write: bool) -> tuple[bool, str]:
    text = path.read_text(encoding="utf-8")
    pattern = re.compile(r"(?m)^(version\s*=\s*\")([^\"]+)(\")")
    match = pattern.search(text)
    if not match:
        raise ValueError(f"No version field found in {path}")

    current = match.group(2)
    if current == version:
        return False, current

    if write:
        replaced = pattern.sub(f'\\g<1>{version}\\g<3>', text, count=1)
        path.write_text(replaced, encoding="utf-8")
    return True, current


def _update_json_field(path: Path, version: str, write: bool) -> tuple[bool, str]:
    data = _read_json(path)
    if "version" not in data:
        raise ValueError(f"No version field found in {path}")
    current = data["version"]
    if current == version:
        return False, current

    if write:
        data["version"] = version
        _write_json(path, data)
    return True, current


def _update_expo_version(path: Path, version: str, write: bool) -> tuple[bool, str]:
    data = _read_json(path)
    expo = data.get("expo")
    if not isinstance(expo, dict):
        raise ValueError(f"No expo config object found in {path}")

    current = expo.get("version")
    if current == version:
        return False, str(current)

    if write:
        expo["version"] = version
        _write_json(path, data)
    return True, str(current)


def _update_lockfile_root(path: Path, version: str, write: bool) -> tuple[bool, str]:
    data = _read_json(path)
    current = data.get("version", "")
    changed = current != version
    if write:
        if "version" in data:
            data["version"] = version
        packages = data.get("packages")
        if isinstance(packages, dict) and "" in packages:
            package_root = packages[""]
            if isinstance(package_root, dict) and "version" in package_root:
                package_root["version"] = version
                packages[""] = package_root
        _write_json(path, data)
    return changed, str(current)


def _update_uv_lock_self_package(path: Path, version: str, write: bool) -> tuple[bool, str]:
    text = path.read_text(encoding="utf-8")
    pattern = re.compile(
        r'(?ms)(\[\[package\]\]\nname = "a2a-client-hub"\nversion = ")([^"]+)(")'
    )
    match = pattern.search(text)
    if not match:
        raise ValueError(f'No editable "a2a-client-hub" package found in {path}')

    current = match.group(2)
    if current == version:
        return False, current

    if write:
        replaced = pattern.sub(f'\\g<1>{version}\\g<3>', text, count=1)
        path.write_text(replaced, encoding="utf-8")
    return True, current


def collect_updates(version: str) -> list[tuple[str, tuple[bool, str]]]:
    updates = [
        (
            "backend/pyproject.toml",
            _update_toml_version(
                ROOT / "backend/pyproject.toml", version, write=False
            ),
        ),
        (
            "backend/uv.lock",
            _update_uv_lock_self_package(ROOT / "backend/uv.lock", version, write=False),
        ),
        (
            "frontend/package.json",
            _update_json_field(
                ROOT / "frontend/package.json", version, write=False
            ),
        ),
        (
            "frontend/app.json",
            _update_expo_version(ROOT / "frontend/app.json", version, write=False),
        ),
    ]
    lock_path = ROOT / "frontend/package-lock.json"
    if lock_path.exists():
        updates.append(
            ("frontend/package-lock.json", _update_lockfile_root(lock_path, version, write=False))
        )
    return updates


def apply_updates(version: str) -> list[tuple[str, tuple[bool, str]]]:
    updates = [
        (
            "backend/pyproject.toml",
            _update_toml_version(
                ROOT / "backend/pyproject.toml", version, write=True
            ),
        ),
        (
            "backend/uv.lock",
            _update_uv_lock_self_package(ROOT / "backend/uv.lock", version, write=True),
        ),
        (
            "frontend/package.json",
            _update_json_field(
                ROOT / "frontend/package.json", version, write=True
            ),
        ),
        (
            "frontend/app.json",
            _update_expo_version(ROOT / "frontend/app.json", version, write=True),
        ),
    ]
    lock_path = ROOT / "frontend/package-lock.json"
    if lock_path.exists():
        updates.append(
            ("frontend/package-lock.json", _update_lockfile_root(lock_path, version, write=True))
        )
    return updates


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Synchronize repository version metadata for backend and frontend packages."
        )
    )
    parser.add_argument(
        "--version",
        default=None,
        help="Release version to sync; defaults to VERSION file.",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Only check that target files already match the version.",
    )
    parser.add_argument(
        "--write",
        action="store_true",
        help="Write synchronized version values into files.",
    )

    args = parser.parse_args()

    if not args.version:
        args.version = _read_version_from_file()
    _validate_version(args.version)

    if not VERSION_FILE.exists():
        raise ValueError(f"VERSION file is missing: {VERSION_FILE}")

    if args.version != _read_version_from_file():
        if args.check:
            print(f"VERSION file mismatch: {_read_version_from_file()} -> {args.version}")
            raise SystemExit(1)
        if not args.write:
            print(f"WARNING: VERSION file mismatch: {_read_version_from_file()} -> {args.version}")

    if args.check and args.write:
        raise ValueError("Use either --check or --write, not both.")

    if args.write and args.version != _read_version_from_file():
        was_version_updated, previous_version = _write_version_file(args.version)
        if was_version_updated:
            print(f"{VERSION_FILE}: {previous_version} -> {args.version}")

    if args.write:
        updates = apply_updates(args.version)
    else:
        updates = collect_updates(args.version)

    changed = False
    for path, (is_changed, previous) in updates:
        if is_changed:
            changed = True
            print(f"{path}: {previous} -> {args.version}")

    if args.check and changed:
        print(f"Version mismatch detected for target {args.version}")
        raise SystemExit(1)

    if args.write:
        print(f"Synchronized files to version {args.version}")
    else:
        print("Version check passed" if not changed else "Version mismatch detected")


if __name__ == "__main__":
    main()
