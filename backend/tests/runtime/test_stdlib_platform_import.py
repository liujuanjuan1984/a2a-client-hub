from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def test_sqlalchemy_import_succeeds_from_app_directory() -> None:
    backend_dir = Path(__file__).resolve().parents[2]
    app_dir = backend_dir / "app"

    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import platform; import sqlalchemy; "
                "print(platform.python_implementation())"
            ),
        ],
        cwd=app_dir,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip()
