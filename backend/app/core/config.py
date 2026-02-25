"""Core configuration settings for a2a-client-hub.

This module contains configuration settings using Pydantic for environment
variable management.
"""

from typing import Any
from urllib.parse import urlparse

from cryptography.exceptions import UnsupportedAlgorithm
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from dotenv import load_dotenv
from pydantic import ConfigDict, Field, field_validator, model_validator
from pydantic_settings import BaseSettings
from sqlalchemy.engine.url import make_url

load_dotenv(override=True)

SUPPORTED_JWT_ALGORITHMS = frozenset(
    {
        "RS256",
        "RS384",
        "RS512",
        "ES256",
        "ES384",
        "ES512",
    }
)


class Settings(BaseSettings):
    """
    Application settings loaded from environment variables
    """

    # Application settings
    app_name: str = "a2a-client-hub API"
    app_version: str = "1.0.0"
    debug: bool = False
    app_env: str = Field(
        default="development",
        alias="APP_ENV",
        description="Deployment environment name (development/staging/production).",
    )

    # Server settings
    host: str = Field(
        default="127.0.0.1",
        alias="BACKEND_HOST",
        description="Host to bind the server to",
    )
    port: int = Field(
        default=8000,
        alias="BACKEND_PORT",
        description="Port to bind the server to",
    )
    uvicorn_workers: int = Field(
        default=1,
        alias="UVICORN_WORKERS",
        description="Number of worker processes for the ASGI server",
    )

    # Database settings
    database_url: str = Field(
        default="postgresql://username:password@localhost:5432/a2a_client",
        alias="DATABASE_URL",
    )
    database_echo: bool = False  # Set to True for SQL query logging in development
    database_async_url: str | None = Field(
        default=None,
        alias="DATABASE_ASYNC_URL",
        description="Optional explicit SQLAlchemy async URL; defaults to asyncpg variant of DATABASE_URL",
    )
    async_db_pool_size: int = Field(
        default=10,
        alias="DATABASE_ASYNC_POOL_SIZE",
        description="Async SQLAlchemy engine pool size",
    )
    async_db_max_overflow: int = Field(
        default=10,
        alias="DATABASE_ASYNC_MAX_OVERFLOW",
        description="Maximum async connections to open beyond the pool size",
    )
    async_db_pool_timeout: float = Field(
        default=30.0,
        alias="DATABASE_ASYNC_POOL_TIMEOUT",
        description="Seconds to wait for a free async connection before timing out",
    )
    schema_name: str = Field(
        default="a2a_client_hub_schema",
        alias="SCHEMA_NAME",
    )

    @property
    def app_database_url_for_alembic(self) -> str:
        """Return a sync-compatible database URL for Alembic migrations."""

        url = make_url(self.database_url)
        if url.drivername.endswith("+asyncpg"):
            return url.set(drivername="postgresql+psycopg2").render_as_string(
                hide_password=False
            )

        return self.database_url

    @property
    def async_database_url(self) -> str:
        """Resolve the SQLAlchemy async connection URL."""
        if self.database_async_url:
            return self.database_async_url

        url = make_url(self.database_url)
        if url.drivername.endswith("+asyncpg"):
            return self.database_url

        if url.drivername.startswith("postgresql"):
            async_url = url.set(drivername="postgresql+asyncpg")
            return async_url.render_as_string(hide_password=False)

        return self.database_url

    @property
    def ws_allowed_origins_resolved(self) -> list[str]:
        """Resolve WS allowed origins, falling back to CORS origins."""

        return self.ws_allowed_origins or self.backend_cors_origins

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    # API settings
    api_v1_prefix: str = "/api/v1"

    # CORS settings
    backend_cors_origins: list[str] = Field(
        default=[
            "http://localhost:3000",
            "http://127.0.0.1:3000",
            "http://localhost:5173",
            "http://127.0.0.1:5173",
        ],
        alias="BACKEND_CORS_ORIGINS",
    )

    # Authentication settings
    first_user_superuser: bool = Field(
        default=True,
        alias="FIRST_USER_SUPERUSER",
        description="Make first registered user a superuser",
    )
    require_invitation_for_registration: bool = Field(
        default=True,
        alias="REQUIRE_INVITATION_FOR_REGISTRATION",
        description="Require a valid invitation code for new registrations after the first user",
    )
    jwt_algorithm: str = Field(
        default="RS256",
        alias="JWT_ALGORITHM",
        description="JWT signing algorithm (recommended: RS256)",
    )
    jwt_private_key_pem: str | None = Field(
        default=None,
        alias="JWT_PRIVATE_KEY_PEM",
        description="PEM-encoded private key for asymmetric JWT signing",
    )
    jwt_public_key_pem: str | None = Field(
        default=None,
        alias="JWT_PUBLIC_KEY_PEM",
        description="PEM-encoded public key for asymmetric JWT verification",
    )
    jwt_issuer: str = Field(
        default="a2a-client-hub",
        alias="JWT_ISSUER",
        description="JWT issuer (iss claim) enforced on decode",
    )
    jwt_access_token_ttl_seconds: int = Field(
        default=30 * 60,
        alias="JWT_ACCESS_TOKEN_TTL_SECONDS",
        description="Access token TTL (seconds)",
    )
    jwt_refresh_token_ttl_seconds: int = Field(
        default=14 * 24 * 60 * 60,
        alias="JWT_REFRESH_TOKEN_TTL_SECONDS",
        description="Refresh token TTL (seconds)",
    )
    auth_refresh_cookie_name: str = Field(
        default="a2a_refresh_token",
        alias="AUTH_REFRESH_COOKIE_NAME",
        description="Cookie name for refresh token",
    )
    auth_refresh_cookie_secure: bool = Field(
        default=True,
        alias="AUTH_REFRESH_COOKIE_SECURE",
        description="Whether refresh cookie is marked Secure (requires HTTPS)",
    )
    auth_refresh_cookie_samesite: str = Field(
        default="lax",
        alias="AUTH_REFRESH_COOKIE_SAMESITE",
        description="Refresh cookie SameSite policy (lax/strict/none)",
    )
    auth_refresh_cookie_path: str = Field(
        default="/api/v1/auth",
        alias="AUTH_REFRESH_COOKIE_PATH",
        description="Path scope for refresh cookie",
    )
    ws_ticket_secret_key: str = Field(
        ...,
        alias="WS_TICKET_SECRET_KEY",
        description="Secret key for WS ticket HMAC hashing",
    )
    ws_ticket_ttl_seconds: int = Field(
        default=90,
        alias="WS_TICKET_TTL_SECONDS",
        description="Time-to-live (seconds) for WS one-time tickets",
    )
    ws_ticket_length: int = Field(
        default=48,
        alias="WS_TICKET_LENGTH",
        description="Length of generated WS ticket tokens",
    )
    ws_ticket_retention_days: int = Field(
        default=7,
        alias="WS_TICKET_RETENTION_DAYS",
        description="Number of days to retain used WS tickets for audit before cleanup",
    )
    ws_allowed_origins: list[str] = Field(
        default_factory=list,
        alias="WS_ALLOWED_ORIGINS",
        description="Allowlisted origins for WebSocket connections",
    )
    ws_require_origin: bool = Field(
        default=True,
        alias="WS_REQUIRE_ORIGIN",
        description="Require Origin header for WebSocket connections",
    )
    auth_max_failed_login_attempts: int = Field(
        default=5,
        alias="AUTH_MAX_FAILED_LOGIN_ATTEMPTS",
        description="Maximum consecutive failed logins before temporary lockout",
    )
    auth_failed_login_lock_minutes: int = Field(
        default=15,
        alias="AUTH_FAILED_LOGIN_LOCK_MINUTES",
        description="Minutes to keep the account locked after exceeding failed logins",
    )
    invitation_code_length: int = Field(
        default=32,
        alias="INVITATION_CODE_LENGTH",
        description="Length of generated invitation codes (before base64 trimming)",
    )

    @field_validator("jwt_private_key_pem", "jwt_public_key_pem", mode="before")
    @classmethod
    def _normalize_pem(cls, value: Any) -> Any:
        if value is None:
            return None
        if not isinstance(value, str):
            return value
        normalized = value.strip()
        # Support env var PEMs encoded as a single line with literal \n sequences.
        if "\\n" in normalized and "-----BEGIN" in normalized:
            normalized = normalized.replace("\\n", "\n")
        return normalized or None

    @field_validator("jwt_algorithm", mode="before")
    @classmethod
    def _normalize_jwt_algorithm(cls, value: Any) -> Any:
        if value is None:
            return value
        if not isinstance(value, str):
            return value
        return value.strip().upper()

    @field_validator("auth_refresh_cookie_samesite", mode="before")
    @classmethod
    def _normalize_samesite(cls, value: Any) -> Any:
        if value is None:
            return value
        if not isinstance(value, str):
            return value
        return value.strip().lower()

    @field_validator("app_env", mode="before")
    @classmethod
    def _normalize_app_env(cls, value: Any) -> Any:
        if value is None:
            return value
        if not isinstance(value, str):
            return value
        normalized = value.strip().lower()
        allowed_values = {"development", "staging", "production"}
        if normalized not in allowed_values:
            allowed = ", ".join(sorted(allowed_values))
            raise ValueError(f"APP_ENV must be one of: {allowed}")
        return normalized

    @staticmethod
    def _is_weak_secret(value: str) -> bool:
        candidate = (value or "").strip().lower()
        if not candidate:
            return True
        weak_markers = (
            "change-me",
            "changeme",
            "replace-me",
            "replace_with",
            "default",
        )
        return any(marker in candidate for marker in weak_markers)

    @staticmethod
    def _origin_is_local(origin: str) -> bool:
        normalized = (origin or "").strip().lower()
        if not normalized:
            return False
        parsed = urlparse(normalized)
        host = (parsed.hostname or "").strip().lower()
        if not host:
            host = normalized
        if host.startswith("[") and host.endswith("]"):
            host = host[1:-1]
        return host in {"localhost", "127.0.0.1", "::1"} or host.endswith(".localhost")

    @staticmethod
    def _load_jwt_private_key(private_key_pem: str) -> Any:
        try:
            return serialization.load_pem_private_key(
                private_key_pem.encode("utf-8"),
                password=None,
            )
        except (TypeError, ValueError, UnsupportedAlgorithm) as exc:
            raise ValueError(
                "JWT_PRIVATE_KEY_PEM must be a valid unencrypted PEM private key"
            ) from exc

    @staticmethod
    def _load_jwt_public_key(public_key_pem: str) -> Any:
        try:
            return serialization.load_pem_public_key(public_key_pem.encode("utf-8"))
        except (TypeError, ValueError, UnsupportedAlgorithm) as exc:
            raise ValueError(
                "JWT_PUBLIC_KEY_PEM must be a valid PEM public key"
            ) from exc

    @classmethod
    def _validate_jwt_key_material(
        cls,
        *,
        algorithm: str,
        private_key_pem: str,
        public_key_pem: str,
    ) -> None:
        private_key = cls._load_jwt_private_key(private_key_pem)
        public_key = cls._load_jwt_public_key(public_key_pem)

        if algorithm.startswith("RS"):
            if not isinstance(private_key, rsa.RSAPrivateKey) or not isinstance(
                public_key, rsa.RSAPublicKey
            ):
                raise ValueError(
                    "JWT_ALGORITHM with RS* requires RSA private/public key PEM values"
                )
        elif algorithm.startswith("ES"):
            if not isinstance(
                private_key, ec.EllipticCurvePrivateKey
            ) or not isinstance(public_key, ec.EllipticCurvePublicKey):
                raise ValueError(
                    "JWT_ALGORITHM with ES* requires EC private/public key PEM values"
                )

        if private_key.public_key().public_numbers() != public_key.public_numbers():
            raise ValueError(
                "JWT_PRIVATE_KEY_PEM and JWT_PUBLIC_KEY_PEM must be a matching key pair"
            )

    @model_validator(mode="after")
    def _validate_jwt_config(self) -> "Settings":
        if self.schema_name not in {
            "a2a_client_hub_schema",
            "test_a2a_client_hub_schema",
        }:
            raise ValueError(
                "SCHEMA_NAME is fixed for this project. "
                "Use SCHEMA_NAME=a2a_client_hub_schema "
                "(or test_a2a_client_hub_schema for tests)."
            )

        algorithm = (self.jwt_algorithm or "").upper()
        if algorithm not in SUPPORTED_JWT_ALGORITHMS:
            allowed = ", ".join(sorted(SUPPORTED_JWT_ALGORITHMS))
            raise ValueError(
                "JWT_ALGORITHM must be one of: "
                f"{allowed}. Symmetric algorithms (HS*) are not supported."
            )
        if not self.jwt_private_key_pem or not self.jwt_public_key_pem:
            raise ValueError(
                "JWT_PRIVATE_KEY_PEM and JWT_PUBLIC_KEY_PEM are required for "
                f"JWT_ALGORITHM={self.jwt_algorithm}"
            )
        self._validate_jwt_key_material(
            algorithm=algorithm,
            private_key_pem=self.jwt_private_key_pem,
            public_key_pem=self.jwt_public_key_pem,
        )

        if self.jwt_access_token_ttl_seconds <= 0:
            raise ValueError("JWT_ACCESS_TOKEN_TTL_SECONDS must be positive")

        if self.jwt_refresh_token_ttl_seconds <= 0:
            raise ValueError("JWT_REFRESH_TOKEN_TTL_SECONDS must be positive")

        if self.auth_refresh_cookie_samesite not in {"lax", "strict", "none"}:
            raise ValueError(
                "AUTH_REFRESH_COOKIE_SAMESITE must be one of: lax/strict/none"
            )

        # Browsers reject SameSite=None cookies without Secure.
        if (
            self.auth_refresh_cookie_samesite == "none"
            and not self.auth_refresh_cookie_secure
        ):
            raise ValueError(
                "AUTH_REFRESH_COOKIE_SECURE must be true when AUTH_REFRESH_COOKIE_SAMESITE=none"
            )

        if self.is_production:
            baseline_errors: list[str] = []

            if self._is_weak_secret(self.ws_ticket_secret_key):
                baseline_errors.append(
                    "WS_TICKET_SECRET_KEY must be set to a strong non-default value in production"
                )
            if not self.auth_refresh_cookie_secure:
                baseline_errors.append(
                    "AUTH_REFRESH_COOKIE_SECURE must be true in production"
                )
            if not self.a2a_proxy_allowed_hosts:
                baseline_errors.append(
                    "A2A_PROXY_ALLOWED_HOSTS must not be empty in production"
                )
            if any(
                (entry or "").strip() == "*" for entry in self.a2a_proxy_allowed_hosts
            ):
                baseline_errors.append(
                    "A2A_PROXY_ALLOWED_HOSTS must not include '*' in production"
                )
            if any(
                (origin or "").strip() == "*" for origin in self.backend_cors_origins
            ):
                baseline_errors.append(
                    "BACKEND_CORS_ORIGINS must not include '*' in production"
                )
            if any(
                self._origin_is_local(origin) for origin in self.backend_cors_origins
            ):
                baseline_errors.append(
                    "BACKEND_CORS_ORIGINS must not include localhost origins in production"
                )
            if not self.ws_require_origin:
                baseline_errors.append("WS_REQUIRE_ORIGIN must be true in production")
            if not self.ws_allowed_origins:
                baseline_errors.append(
                    "WS_ALLOWED_ORIGINS must be explicitly configured in production"
                )
            if any((origin or "").strip() == "*" for origin in self.ws_allowed_origins):
                baseline_errors.append(
                    "WS_ALLOWED_ORIGINS must not include '*' in production"
                )
            if any(self._origin_is_local(origin) for origin in self.ws_allowed_origins):
                baseline_errors.append(
                    "WS_ALLOWED_ORIGINS must not include localhost origins in production"
                )

            if baseline_errors:
                joined_errors = "; ".join(baseline_errors)
                raise ValueError(
                    f"Production security baseline checks failed: {joined_errors}"
                )
        return self

    # Logging settings
    log_level: str = "INFO"
    user_llm_token_encryption_key: str = Field(
        default="",
        alias="USER_LLM_TOKEN_ENCRYPTION_KEY",
        description="Base64 URL-safe key for encrypting user-supplied LLM API tokens (leave blank to disable BYOT)",
    )
    hub_a2a_token_encryption_key: str = Field(
        default="",
        alias="HUB_A2A_TOKEN_ENCRYPTION_KEY",
        description="Base64 URL-safe key for encrypting admin-managed hub A2A credentials (falls back to USER_LLM_TOKEN_ENCRYPTION_KEY when omitted)",
    )

    # A2A integration settings
    a2a_default_timeout: float = Field(
        default=300.0,
        alias="A2A_DEFAULT_TIMEOUT",
        description="Default timeout (seconds) applied to A2A agent requests.",
    )
    a2a_max_connections: int = Field(
        default=20,
        alias="A2A_MAX_CONNECTIONS",
        description="Maximum concurrent HTTP connections maintained per A2A agent client.",
    )
    a2a_card_fetch_timeout: float = Field(
        default=15.0,
        alias="A2A_CARD_FETCH_TIMEOUT",
        description="Timeout (seconds) for retrieving A2A agent metadata (agent card).",
    )
    a2a_invoke_watchdog_interval: float = Field(
        default=5.0,
        alias="A2A_INVOKE_WATCHDOG_INTERVAL",
        description="Seconds between watchdog logs while waiting for an A2A agent response (<=0 disables).",
    )
    a2a_use_client_preference: bool = Field(
        default=True,
        alias="A2A_USE_CLIENT_PREFERENCE",
        description="Respect downstream agent preferred transports when negotiating sessions.",
    )
    a2a_max_context_bytes: int = Field(
        default=4096,
        alias="A2A_MAX_CONTEXT_BYTES",
        description="Maximum allowed size (bytes) for the context payload forwarded to downstream A2A agents.",
    )
    a2a_client_idle_timeout: float = Field(
        default=600.0,
        alias="A2A_CLIENT_IDLE_TIMEOUT",
        description="Seconds of inactivity after which cached A2A HTTP clients are re-created (<=0 disables).",
    )
    a2a_schedule_agent_concurrency_limit: int = Field(
        default=3,
        alias="A2A_SCHEDULE_AGENT_CONCURRENCY_LIMIT",
        description="Maximum concurrent running scheduled executions per target agent.",
    )
    a2a_schedule_global_concurrency_limit: int = Field(
        default=3,
        alias="A2A_SCHEDULE_GLOBAL_CONCURRENCY_LIMIT",
        description="Maximum concurrent running scheduled executions globally.",
    )
    a2a_schedule_worker_concurrency: int = Field(
        default=3,
        alias="A2A_SCHEDULE_WORKER_CONCURRENCY",
        description="Number of in-process workers consuming claimed scheduled tasks.",
    )
    a2a_schedule_task_invoke_timeout: float = Field(
        default=3600.0,
        alias="A2A_SCHEDULE_TASK_INVOKE_TIMEOUT",
        description="Maximum total timeout in seconds for a single scheduled A2A stream execution.",
    )
    a2a_schedule_task_stream_idle_timeout: float = Field(
        default=60.0,
        alias="A2A_SCHEDULE_TASK_STREAM_IDLE_TIMEOUT",
        description="Idle timeout in seconds for scheduled A2A stream execution (no upstream chunk received).",
    )
    a2a_schedule_run_lease_seconds: int = Field(
        default=2400,
        alias="A2A_SCHEDULE_RUN_LEASE_SECONDS",
        description="Configured lease timeout in seconds for one scheduled run before recovery finalization.",
    )
    a2a_schedule_run_lease_grace_seconds: int = Field(
        default=120,
        alias="A2A_SCHEDULE_RUN_LEASE_GRACE_SECONDS",
        description="Additional grace seconds added on top of invoke timeout for recovery lease enforcement.",
    )
    a2a_schedule_task_failure_threshold: int = Field(
        default=3,
        alias="A2A_SCHEDULE_TASK_FAILURE_THRESHOLD",
        description="Consecutive failures before a scheduled task is automatically disabled.",
    )
    a2a_schedule_min_interval_minutes: int = Field(
        default=60,
        alias="A2A_SCHEDULE_MIN_INTERVAL_MINUTES",
        description="Minimum allowed scheduling interval in minutes (to prevent rapid invocations).",
    )
    a2a_schedule_max_active_tasks_per_user: int = Field(
        default=3,
        alias="A2A_SCHEDULE_MAX_ACTIVE_TASKS_PER_USER",
        description="Maximum number of active scheduled tasks permitted per non-admin user.",
    )
    a2a_stream_heartbeat_interval: float = Field(
        default=15.0,
        alias="A2A_STREAM_HEARTBEAT_INTERVAL",
        description="Seconds between heartbeat frames emitted by hub SSE/WS streams while upstream is idle (<=0 disables).",
    )
    a2a_proxy_allowed_hosts: list[str] = Field(
        default_factory=list,
        alias="A2A_PROXY_ALLOWED_HOSTS",
        description="Allowlisted hosts for all outbound A2A HTTP requests (agent card + transports + extensions).",
    )

    # OpenCode sessions directory (global list) settings
    opencode_sessions_cache_ttl_seconds: int = Field(
        default=90,
        alias="OPENCODE_SESSIONS_CACHE_TTL_SECONDS",
        description="TTL (seconds) for cached OpenCode session listings per agent.",
    )
    opencode_sessions_per_agent_size: int = Field(
        default=50,
        alias="OPENCODE_SESSIONS_PER_AGENT_SIZE",
        description="Maximum number of OpenCode sessions fetched per agent when refreshing the directory.",
    )
    opencode_sessions_refresh_concurrency: int = Field(
        default=4,
        alias="OPENCODE_SESSIONS_REFRESH_CONCURRENCY",
        description="Maximum concurrent upstream refreshes when updating cached OpenCode session listings.",
    )
    opencode_stream_metadata_max_chars: int = Field(
        default=12000,
        alias="OPENCODE_STREAM_METADATA_MAX_CHARS",
        description="Maximum characters persisted per streamed message block content.",
    )

    model_config = ConfigDict(
        env_file=".env",
        case_sensitive=False,
        extra="ignore",  # Ignore extra fields from environment
    )

    @field_validator("invitation_code_length")
    @classmethod
    def validate_invitation_code_length(cls, value: int) -> int:
        if value < 8:
            raise ValueError("INVITATION_CODE_LENGTH must be at least 8")
        if value > 64:
            raise ValueError("INVITATION_CODE_LENGTH must not exceed 64")
        return value

    @field_validator("ws_ticket_length")
    @classmethod
    def validate_ws_ticket_length(cls, value: int) -> int:
        if value < 16:
            raise ValueError("WS_TICKET_LENGTH must be at least 16")
        if value > 128:
            raise ValueError("WS_TICKET_LENGTH must not exceed 128")
        return value

    @field_validator("ws_ticket_ttl_seconds")
    @classmethod
    def validate_ws_ticket_ttl_seconds(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("WS_TICKET_TTL_SECONDS must be positive")
        if value > 600:
            raise ValueError("WS_TICKET_TTL_SECONDS must not exceed 600")
        return value

    @field_validator("opencode_sessions_cache_ttl_seconds")
    @classmethod
    def validate_opencode_sessions_cache_ttl_seconds(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("OPENCODE_SESSIONS_CACHE_TTL_SECONDS must be positive")
        if value > 3600:
            raise ValueError("OPENCODE_SESSIONS_CACHE_TTL_SECONDS must not exceed 3600")
        return value

    @field_validator("opencode_sessions_per_agent_size")
    @classmethod
    def validate_opencode_sessions_per_agent_size(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("OPENCODE_SESSIONS_PER_AGENT_SIZE must be positive")
        if value > 200:
            raise ValueError("OPENCODE_SESSIONS_PER_AGENT_SIZE must not exceed 200")
        return value

    @field_validator("opencode_sessions_refresh_concurrency")
    @classmethod
    def validate_opencode_sessions_refresh_concurrency(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("OPENCODE_SESSIONS_REFRESH_CONCURRENCY must be positive")
        if value > 20:
            raise ValueError("OPENCODE_SESSIONS_REFRESH_CONCURRENCY must not exceed 20")
        return value

    @field_validator("opencode_stream_metadata_max_chars")
    @classmethod
    def validate_opencode_stream_metadata_max_chars(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("OPENCODE_STREAM_METADATA_MAX_CHARS must be positive")
        if value > 1_000_000:
            raise ValueError(
                "OPENCODE_STREAM_METADATA_MAX_CHARS must not exceed 1000000"
            )
        return value

    @field_validator("a2a_stream_heartbeat_interval")
    @classmethod
    def validate_a2a_stream_heartbeat_interval(cls, value: float) -> float:
        if value < 0:
            raise ValueError("A2A_STREAM_HEARTBEAT_INTERVAL must be non-negative")
        if value > 300:
            raise ValueError("A2A_STREAM_HEARTBEAT_INTERVAL must not exceed 300")
        return value

    @field_validator(
        "a2a_schedule_agent_concurrency_limit",
        "a2a_schedule_global_concurrency_limit",
        "a2a_schedule_worker_concurrency",
    )
    @classmethod
    def validate_a2a_schedule_concurrency_limits(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("A2A schedule concurrency values must be positive")
        if value > 1000:
            raise ValueError("A2A schedule concurrency values must not exceed 1000")
        return value

    @field_validator(
        "a2a_schedule_task_invoke_timeout", "a2a_schedule_task_stream_idle_timeout"
    )
    @classmethod
    def validate_a2a_schedule_timeouts(cls, value: float) -> float:
        if value <= 0:
            raise ValueError("Scheduled A2A timeout values must be positive")
        if value > 86_400:
            raise ValueError("Scheduled A2A timeout values must not exceed 86400")
        return value

    @field_validator("a2a_schedule_run_lease_seconds")
    @classmethod
    def validate_a2a_schedule_run_lease_seconds(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("A2A schedule run lease seconds must be positive")
        if value > 604_800:
            raise ValueError("A2A schedule run lease seconds must not exceed 604800")
        return value

    @field_validator("a2a_schedule_run_lease_grace_seconds")
    @classmethod
    def validate_a2a_schedule_run_lease_grace_seconds(cls, value: int) -> int:
        if value < 0:
            raise ValueError(
                "A2A schedule run lease grace seconds must be zero or positive"
            )
        if value > 604_800:
            raise ValueError(
                "A2A schedule run lease grace seconds must not exceed 604800"
            )
        return value


# Global settings instance
settings = Settings()
