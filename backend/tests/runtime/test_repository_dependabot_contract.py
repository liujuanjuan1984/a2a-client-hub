from __future__ import annotations

from pathlib import Path


def test_dependabot_keeps_only_backend_grouped_updates() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    dependabot_config = (repo_root / ".github" / "dependabot.yml").read_text(
        encoding="utf-8"
    )

    assert 'package-ecosystem: "uv"' in dependabot_config
    assert 'directory: "/backend"' in dependabot_config
    assert "backend-all-updates" in dependabot_config
    assert "open-pull-requests-limit: 1" in dependabot_config
    assert 'package-ecosystem: "npm"' not in dependabot_config
    assert 'directory: "/frontend"' not in dependabot_config
    assert "labels:" not in dependabot_config


def test_contributing_documents_backend_dependabot_and_audit_flow() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    contributing_text = (repo_root / "CONTRIBUTING.md").read_text(encoding="utf-8")

    assert "Dependabot keeps backend updates grouped weekly" in contributing_text
    assert "Frontend dependency updates are planned manually" in contributing_text
    assert "Existing audit workflows remain in place" in contributing_text
