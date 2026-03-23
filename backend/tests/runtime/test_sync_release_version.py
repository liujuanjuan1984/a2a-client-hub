from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_sync_release_version_module():
    module_path = (
        Path(__file__).resolve().parents[3] / "scripts" / "sync_release_version.py"
    )
    spec = importlib.util.spec_from_file_location("sync_release_version", module_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_fixture_tree(root: Path) -> None:
    (root / "backend").mkdir()
    (root / "frontend").mkdir()
    (root / "VERSION").write_text("1.2.2\n", encoding="utf-8")
    (root / "backend/pyproject.toml").write_text(
        '[project]\nname = "a2a-client-hub"\nversion = "1.2.2"\n',
        encoding="utf-8",
    )
    (root / "backend/uv.lock").write_text(
        "version = 1\n"
        "revision = 3\n\n"
        "[[package]]\n"
        'name = "a2a-client-hub"\n'
        'version = "1.2.2"\n'
        'source = { editable = "." }\n\n'
        "[[package]]\n"
        'name = "httpx"\n'
        'version = "0.28.1"\n',
        encoding="utf-8",
    )
    (root / "frontend/package.json").write_text(
        '{\n  "name": "frontend",\n  "version": "1.2.2"\n}\n',
        encoding="utf-8",
    )
    (root / "frontend/app.json").write_text(
        '{\n  "expo": {\n    "version": "1.2.2"\n  }\n}\n',
        encoding="utf-8",
    )
    (root / "frontend/package-lock.json").write_text(
        "{\n"
        '  "name": "frontend",\n'
        '  "version": "1.2.2",\n'
        '  "packages": {\n'
        '    "": {\n'
        '      "version": "1.2.2"\n'
        "    }\n"
        "  }\n"
        "}\n",
        encoding="utf-8",
    )


def test_collect_updates_flags_backend_uv_lock_version(tmp_path, monkeypatch):
    module = _load_sync_release_version_module()
    _write_fixture_tree(tmp_path)
    uv_lock_path = tmp_path / "backend/uv.lock"
    uv_lock_path.write_text(
        uv_lock_path.read_text(encoding="utf-8").replace('"1.2.2"', '"1.3.0"', 1),
        encoding="utf-8",
    )

    monkeypatch.setattr(module, "ROOT", tmp_path)
    monkeypatch.setattr(module, "VERSION_FILE", tmp_path / "VERSION")

    updates = dict(module.collect_updates("1.2.2"))

    assert updates["backend/uv.lock"] == (True, "1.3.0")
    assert updates["backend/pyproject.toml"] == (False, "1.2.2")


def test_apply_updates_synchronizes_backend_uv_lock(tmp_path, monkeypatch):
    module = _load_sync_release_version_module()
    _write_fixture_tree(tmp_path)
    uv_lock_path = tmp_path / "backend/uv.lock"
    original_text = uv_lock_path.read_text(encoding="utf-8")
    uv_lock_path.write_text(
        original_text.replace('version = "1.2.2"', 'version = "1.3.0"', 1),
        encoding="utf-8",
    )

    monkeypatch.setattr(module, "ROOT", tmp_path)
    monkeypatch.setattr(module, "VERSION_FILE", tmp_path / "VERSION")

    updates = dict(module.apply_updates("1.2.2"))

    assert updates["backend/uv.lock"] == (True, "1.3.0")
    synchronized_text = uv_lock_path.read_text(encoding="utf-8")
    assert (
        'name = "a2a-client-hub"\nversion = "1.2.2"\nsource = { editable = "." }'
        in synchronized_text
    )
    assert 'name = "httpx"\nversion = "0.28.1"' in synchronized_text
