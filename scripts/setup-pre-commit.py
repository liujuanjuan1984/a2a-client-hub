#!/usr/bin/env python3
"""
Setup script for pre-commit hooks in Common Compass project.
This script installs and configures pre-commit hooks for code quality.
"""

import subprocess
import sys
from pathlib import Path


def run_command(cmd, description):
    """Run a command and handle errors."""
    print(f"[INFO] {description}...")
    try:
        result = subprocess.run(
            cmd, shell=True, check=True, capture_output=True, text=True
        )
        print(f"[SUCCESS] {description} completed successfully")
        if result.stdout:
            print(f"   Output: {result.stdout.strip()}")
        return True
    except subprocess.CalledProcessError as e:
        print(f"[ERROR] {description} failed")
        print(f"   Error: {e.stderr}")
        return False


def setup_config_file():
    """Ensure the pre-commit config file exists."""
    target_path = Path(".pre-commit-config.yaml")

    if target_path.exists():
        print(f"[CONFIG] Using .pre-commit-config.yaml")
        return True
    else:
        print(f"[ERROR] .pre-commit-config.yaml not found")
        return False


def main():
    """Main setup function."""
    print("[SETUP] Setting up pre-commit hooks for Common Compass")
    print("=" * 60)

    # Check if we're in the right directory (project root)
    if not Path("backend/pyproject.toml").exists():
        print("[ERROR] Please run this script from the project root directory")
        print("   Expected to find: backend/pyproject.toml")
        sys.exit(1)

    # Check if frontend directory exists
    frontend_exists = Path("frontend").exists()
    if frontend_exists:
        print("[INFO] Frontend directory found - will configure frontend hooks")
    else:
        print("[INFO] Frontend directory not found - skipping frontend hooks")

    # Set up appropriate config file based on OS
    setup_config_file()

    # Install pre-commit if not already installed
    print("[INSTALL] Installing pre-commit...")
    if not run_command("pip install pre-commit", "Installing pre-commit"):
        sys.exit(1)

    # Install the git hook scripts
    if not run_command("pre-commit install", "Installing git hook scripts"):
        sys.exit(1)

    # Install commit-msg hook for conventional commits (optional)
    run_command(
        "pre-commit install --hook-type commit-msg",
        "Installing commit-msg hook (optional)",
    )

    # Run hooks on all files to ensure everything is working
    print("\n[CHECK] Running pre-commit hooks on all files (this may take a while)...")
    if run_command("pre-commit run --all-files", "Running initial check on all files"):
        print("\n[SUCCESS] Pre-commit hooks setup completed successfully!")
        print(
            "\n[INFO] From now on, every time you commit, the following will run automatically:"
        )
        print("   - Black (code formatting)")
        print("   - isort (import sorting)")
        print("   - autoflake (remove unused imports)")
        print("   - ruff (fast linting)")
        print("   - mypy (type checking)")
        print("   - General file checks")
        if frontend_exists:
            print("   - Frontend Prettier (for React/TypeScript files)")
            print("   - Frontend ESLint (for React/TypeScript files)")

        print("\n[TIPS] Pro tips:")
        print("   - To skip hooks temporarily: git commit --no-verify")
        print("   - To run hooks manually: pre-commit run --all-files")
        print("   - To update hook versions: pre-commit autoupdate")
        print("   - Backend code is in: backend/")
        if frontend_exists:
            print("   - Frontend code is in: frontend/")

    else:
        print("\n[WARNING] Some checks failed. Please fix the issues and try again.")
        print("   You can run 'pre-commit run --all-files' to see what needs fixing.")


if __name__ == "__main__":
    main()
