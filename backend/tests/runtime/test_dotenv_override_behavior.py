from pathlib import Path


def test_config_does_not_override_existing_environment_variables() -> None:
    config_path = Path(__file__).resolve().parents[2] / "app" / "core" / "config.py"
    content = config_path.read_text()

    assert "load_dotenv(override=False)" in content
    assert "load_dotenv(override=True)" not in content
