from __future__ import annotations

from pathlib import Path


def test_dependabot_limits_backend_and_frontend_to_one_grouped_pr() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    dependabot_config = (repo_root / ".github" / "dependabot.yml").read_text(
        encoding="utf-8"
    )

    assert 'package-ecosystem: "uv"' in dependabot_config
    assert 'directory: "/backend"' in dependabot_config
    assert "backend-all-updates" in dependabot_config

    assert 'package-ecosystem: "npm"' in dependabot_config
    assert 'directory: "/frontend"' in dependabot_config
    assert "frontend-all-updates" in dependabot_config

    assert dependabot_config.count("open-pull-requests-limit: 1") == 2


def test_readme_documents_dependabot_and_audit_split() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    readme_text = (repo_root / "README.md").read_text(encoding="utf-8")

    assert "Dependabot opens at most one weekly grouped version-update PR" in readme_text
    assert "Existing audit workflows remain in place" in readme_text
