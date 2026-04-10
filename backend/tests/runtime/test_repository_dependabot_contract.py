from __future__ import annotations

from pathlib import Path


def test_dependabot_keeps_backend_grouped_and_frontend_split_by_risk() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    dependabot_config = (repo_root / ".github" / "dependabot.yml").read_text(
        encoding="utf-8"
    )

    assert 'package-ecosystem: "uv"' in dependabot_config
    assert 'directory: "/backend"' in dependabot_config
    assert "backend-all-updates" in dependabot_config

    assert 'package-ecosystem: "npm"' in dependabot_config
    assert 'directory: "/frontend"' in dependabot_config
    assert "open-pull-requests-limit: 3" in dependabot_config
    assert 'dependency-name: "*"' in dependabot_config
    assert "version-update:semver-major" in dependabot_config
    assert "frontend-expo-sdk" in dependabot_config
    assert "frontend-react-native-core" in dependabot_config
    assert "frontend-state-storage" in dependabot_config
    assert "frontend-dev-tooling" in dependabot_config
    assert "frontend-runtime-misc" in dependabot_config
    assert 'dependency-type: "development"' in dependabot_config
    assert 'dependency-type: "production"' in dependabot_config
    assert "labels:" not in dependabot_config


def test_readme_documents_dependabot_and_audit_split() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    readme_text = (repo_root / "README.md").read_text(encoding="utf-8")

    assert "Dependabot keeps backend updates grouped weekly" in readme_text
    assert (
        "Frontend npm updates are split into smaller patch/minor review lanes"
        in readme_text
    )
    assert "Semver-major frontend updates are intentionally ignored" in readme_text
    assert "Existing audit workflows remain in place" in readme_text
