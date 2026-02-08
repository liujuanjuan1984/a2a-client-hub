"""
Core configuration settings for Common Compass Backend

This module contains all configuration settings using Pydantic for environment variable management.
"""

import json
import os
from pathlib import Path
from typing import Any, Dict, Mapping

from dotenv import load_dotenv
from pydantic import ConfigDict, Field, field_validator, model_validator
from pydantic_settings import BaseSettings
from sqlalchemy.engine.url import make_url

load_dotenv(override=True)


class Settings(BaseSettings):
    """
    Application settings loaded from environment variables
    """

    # Application settings
    app_name: str = "Common Compass API"
    app_version: str = "1.0.0"
    debug: bool = False

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
    # TODO: 多workers访问duckdb会出问题，需fix后才能把workers>1
    uvicorn_workers: int = Field(
        default=1,
        alias="UVICORN_WORKERS",
        description="Number of worker processes for the ASGI server",
    )
    tasks_max_page_size: int = Field(
        default=500,
        alias="TASKS_MAX_PAGE_SIZE",
        description="Maximum number of tasks returned per list call",
    )
    actual_events_search_limit: int = Field(
        default=1000,
        alias="ACTUAL_EVENTS_SEARCH_LIMIT",
        description="Maximum number of actual events returned for advanced search queries",
    )

    # Database settings
    database_url: str = Field(
        default="postgresql://compass_user:compass_password@localhost:5432/common_compass",
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
        default="common_compass_schema",
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
    jwt_secret_key: str = Field(
        default="change-me-32-chars-minimum-secret-key",
        alias="JWT_SECRET_KEY",
        description="Secret key for JWT token signing",
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
        default="common-compass",
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
        default="cc_refresh_token",
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
        default="change-me-32-chars-minimum-ws-ticket-secret",
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
    frontend_base_url: str = Field(
        default="http://localhost:5173",
        alias="FRONTEND_BASE_URL",
        description="Base URL of the frontend, used for invitation links",
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

    @model_validator(mode="after")
    def _validate_jwt_config(self) -> "Settings":
        algorithm = (self.jwt_algorithm or "").upper()
        if algorithm.startswith(("RS", "ES")):
            if not self.jwt_private_key_pem or not self.jwt_public_key_pem:
                raise ValueError(
                    "JWT_PRIVATE_KEY_PEM and JWT_PUBLIC_KEY_PEM are required for "
                    f"JWT_ALGORITHM={self.jwt_algorithm}"
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
        return self

    # Logging settings
    log_level: str = "INFO"
    # Cardbox settings
    card_box_duckdb_path: str = Field(
        default="./storage/cardbox.duckdb",
        alias="CARD_BOX_DUCKDB_PATH",
        description="Filesystem path for the embedded Cardbox DuckDB store",
    )
    card_box_history_level: str = Field(
        default="card_only",
        alias="CARD_BOX_HISTORY_LEVEL",
        description="History verbosity level for Cardbox (e.g. none/card_only/full)",
    )
    card_box_verbose_logs: bool = Field(
        default=False,
        alias="CARD_BOX_VERBOSE_LOGS",
        description="Enable verbose Cardbox logging for debugging",
    )

    # AI/LiteLLM settings
    litellm_model: str = Field(
        default="gpt-3.5-turbo",
        alias="LITELLM_MODEL",
        description="Default model for LiteLLM chat completion",
    )
    litellm_api_key: str = Field(
        default="",
        alias="LITELLM_API_KEY",
        description="API key for LiteLLM service (OpenAI, Anthropic, etc.)",
    )
    litellm_base_url: str = Field(
        default="",
        alias="LITELLM_BASE_URL",
        description="Base URL for LiteLLM service (optional, for custom endpoints)",
    )
    litellm_temperature: float = Field(
        default=0.7,
        alias="LITELLM_TEMPERATURE",
        description="Temperature for chat completion (0.0 to 2.0)",
    )
    litellm_completion_max_tokens: int = Field(
        default=8000,
        alias="LITELLM_COMPLETION_MAX_TOKENS",
        description="Maximum tokens allocated for a single completion response",
    )
    litellm_context_window_tokens: int = Field(
        default=131072,
        alias="LITELLM_CONTEXT_WINDOW_TOKENS",
        description="Hard context window limit used when budgeting conversation history",
    )
    litellm_debug: bool = Field(
        default=False,
        alias="LITELLM_DEBUG",
        description="Enable LiteLLM debug mode for detailed error information",
    )
    litellm_timeout: int = Field(
        default=30,
        alias="LITELLM_TIMEOUT",
        description="Timeout in seconds for LiteLLM requests",
    )
    conversation_context_budget: int = Field(
        default=120000,
        alias="CONVERSATION_CONTEXT_BUDGET",
        description="Approximate token budget allocated to historical context before compression",
    )
    conversation_context_buffer: int = Field(
        default=4000,
        alias="CONVERSATION_CONTEXT_BUFFER",
        description="Safety margin tokens reserved to avoid hitting the model hard limit",
    )
    conversation_summary_reserve_ratio: float = Field(
        default=0.05,
        alias="CONVERSATION_SUMMARY_RESERVE_RATIO",
        description="Fraction of the context budget reserved for future summarization",
    )
    conversation_summary_min_messages: int = Field(
        default=6,
        alias="CONVERSATION_SUMMARY_MIN_MESSAGES",
        description="Minimum trimmed messages required before triggering automatic summarization",
    )
    session_overview_min_messages: int = Field(
        default=3,
        alias="SESSION_OVERVIEW_MIN_MESSAGES",
        description="Minimum number of conversation messages before auto-generating a user-facing overview",
    )
    session_overview_history_limit: int = Field(
        default=6,
        alias="SESSION_OVERVIEW_HISTORY_LIMIT",
        description="Maximum number of recent messages to feed into the overview generator",
    )
    session_overview_refresh_seconds: int = Field(
        default=180,  # 3 minutes
        alias="SESSION_OVERVIEW_REFRESH_SECONDS",
        description="Cooldown in seconds between automatic overview refresh attempts",
    )
    agent_stream_heartbeat_interval: float = Field(
        default=5.0,
        alias="AGENT_STREAM_HEARTBEAT_INTERVAL",
        description="Seconds between heartbeat events in streaming responses (<=0 disables).",
    )
    agent_max_tool_rounds: int = Field(
        default=6,
        alias="AGENT_MAX_TOOL_ROUNDS",
        description="Maximum sequential tool-execution rounds allowed within a single agent turn",
    )
    agent_tool_name_retry_attempts: int = Field(
        default=3,
        alias="AGENT_TOOL_NAME_RETRY_ATTEMPTS",
        description="Number of times to re-query the LLM when tool call names are missing.",
    )
    agent_tool_name_retry_delay_seconds: float = Field(
        default=1.0,
        alias="AGENT_TOOL_NAME_RETRY_DELAY_SECONDS",
        description="Delay in seconds between LLM retries for missing tool call names.",
    )
    user_daily_token_limit: int = Field(
        default=102800,
        alias="USER_DAILY_TOKEN_LIMIT",
        description="Per-user total_tokens limit per UTC natural day",
    )
    enforce_user_token_limit: bool = Field(
        default=True,
        alias="ENFORCE_USER_TOKEN_LIMIT",
        description="Enable per-user daily token quota enforcement",
    )
    user_llm_credentials_enabled: bool = Field(
        default=True,
        alias="USER_LLM_CREDENTIALS_ENABLED",
        description="Allow users to configure their own LLM API credentials when encryption key is set",
    )
    user_llm_token_encryption_key: str = Field(
        default="",
        alias="USER_LLM_TOKEN_ENCRYPTION_KEY",
        description="Base64 URL-safe key for encrypting user-supplied LLM API tokens (leave blank to disable BYOT)",
    )

    # A2A integration settings
    a2a_enabled: bool = Field(
        default=False,
        alias="A2A_ENABLED",
        description="Enable A2A client integration for external agents.",
    )
    a2a_agents: Dict[str, Dict[str, Any]] = Field(
        default_factory=dict,
        alias="A2A_AGENTS",
        description=(
            "Mapping of external A2A agents; accepts JSON content or a filesystem path "
            "pointing to a JSON file."
        ),
    )
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
    a2a_health_probe_agent: str = Field(
        default="",
        alias="A2A_HEALTH_PROBE_AGENT",
        description="Optional agent name used for health probes; defaults to the first configured agent.",
    )
    a2a_health_probe_ttl_seconds: int = Field(
        default=180,
        alias="A2A_HEALTH_PROBE_TTL_SECONDS",
        description="Cache TTL in seconds for A2A health probe results to avoid hammering downstream agents.",
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
    a2a_proxy_allowed_hosts: list[str] = Field(
        default_factory=list,
        alias="A2A_PROXY_ALLOWED_HOSTS",
        description="Allowlisted hosts for the A2A agent card proxy endpoint.",
    )

    # Health probe settings
    health_llm_active_probe_enabled: bool = Field(
        default=False,
        alias="HEALTH_LLM_ACTIVE_PROBE_ENABLED",
        description="Enable active LiteLLM connectivity checks during health probes.",
    )
    health_llm_active_probe_ttl_seconds: int = Field(
        default=60,
        alias="HEALTH_LLM_ACTIVE_PROBE_TTL_SECONDS",
        description="Cache TTL in seconds for successful/failed LiteLLM active probe results.",
    )

    model_config = ConfigDict(
        env_file=".env",
        case_sensitive=False,
        extra="ignore",  # Ignore extra fields from environment
    )

    @field_validator("a2a_agents", mode="before")
    @classmethod
    def load_a2a_agents(cls, value: Any) -> Dict[str, Any]:
        if value in (None, "", {}):
            return {}

        if isinstance(value, Mapping):
            return dict(value)

        if isinstance(value, str):
            raw_value = value.strip()
            if not raw_value:
                return {}

            try:
                parsed = json.loads(raw_value)
            except json.JSONDecodeError:
                expanded = os.path.expandvars(raw_value)
                path = Path(expanded).expanduser()
                if not path.is_absolute():
                    path = (Path.cwd() / path).resolve()

                if not path.is_file():
                    raise ValueError(
                        f"A2A agents configuration file '{path}' does not exist."
                    )

                try:
                    file_data = path.read_text(encoding="utf-8")
                except OSError as exc:
                    raise ValueError(
                        f"Failed to read A2A agents configuration file '{path}': {exc}"
                    ) from exc

                try:
                    parsed = json.loads(file_data)
                except json.JSONDecodeError as exc:
                    raise ValueError(
                        f"A2A agents configuration file '{path}' contains invalid JSON: {exc}"
                    ) from exc

            if isinstance(parsed, Mapping):
                return dict(parsed)

            raise ValueError(
                "A2A agents configuration must be a JSON object mapping agent names to definitions."
            )

        raise TypeError(
            "A2A agents configuration must be provided as a mapping, JSON string, or path to a JSON file."
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


# Global settings instance
settings = Settings()
