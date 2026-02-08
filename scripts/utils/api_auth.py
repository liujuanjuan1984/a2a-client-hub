from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Tuple

import requests


def load_env_from_root() -> None:
    """Load key=value pairs from repo root .env into os.environ if not already set.

    This is a minimal parser supporting lines like KEY=VALUE (no export), ignoring
    comments and quoted values best-effort. Existing env vars are not overridden.
    """
    script_path = Path(__file__).resolve()
    repo_root = script_path.parent.parent.parent
    dotenv_path = repo_root / ".env"
    print(f"Loading env from {dotenv_path}")
    if not dotenv_path.exists():
        return

    try:
        content = dotenv_path.read_text(encoding="utf-8")
    except Exception:
        return

    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            print(f"Setting {key} = {value}")
            os.environ[key] = value


@dataclass
class ApiEnvConfig:
    base_url: str
    email: str
    password: str
    timeout_s: int = 15


def read_env_config(timeout_s: int = 15) -> ApiEnvConfig:
    base_url = os.environ.get("API_BASE_URL", "").strip()
    email = os.environ.get("API_EMAIL", "").strip()
    password = os.environ.get("API_PASSWORD", "").strip()

    missing = [name for name, val in [("API_BASE_URL", base_url), ("API_EMAIL", email), ("API_PASSWORD", password)] if not val]
    if missing:
        raise ValueError(f"Missing required environment variables: {', '.join(missing)}")

    # 验证邮箱格式
    if "@" not in email:
        print(f"警告: API_EMAIL 看起来不是有效的邮箱地址: {email}")
        print("请检查 .env 文件中的 API_EMAIL 和 API_PASSWORD 是否被搞反了")
        print("正确的格式应该是:")
        print("API_EMAIL=your-email@example.com")
        print("API_PASSWORD=your-password")
        raise ValueError(f"API_EMAIL 不是有效的邮箱地址: {email}")

    return ApiEnvConfig(base_url=base_url, email=email, password=password, timeout_s=timeout_s)


def login(config: ApiEnvConfig) -> Tuple[requests.Session, str, str]:
    """Login using email/password and return (session, base_url, access_token).

    The returned session will have Authorization header set with the bearer token.
    """
    base_url_root = config.base_url.rstrip("/")
    session = requests.Session()

    if base_url_root.endswith("/api/v1"):
        api_base_url = base_url_root
    else:
        api_base_url = f"{base_url_root}/api/v1"

    url = f"{api_base_url}/auth/login"

    resp = session.post(url, json={"email": config.email, "password": config.password}, timeout=config.timeout_s)
    if resp.status_code != 200:
        raise RuntimeError(f"Login failed: {resp.status_code} {resp.text}")
    data = resp.json() or {}
    token = data.get("access_token")
    if not token:
        raise RuntimeError("Login succeeded but no access_token in response")
    session.headers.update({"Authorization": f"Bearer {token}"})
    return session, api_base_url, token


def login_with_env(timeout_s: int = 15) -> Tuple[requests.Session, str, str]:
    load_env_from_root()
    cfg = read_env_config(timeout_s=timeout_s)
    return login(cfg)
