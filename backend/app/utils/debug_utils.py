"""
Unified debugging utilities for LiteLLM debug functionality.
This module centralizes debug mode configuration and logging to eliminate code duplication.
"""

import sys

import litellm

from app.core.config import settings
from app.core.logging import get_logger, log_exception

logger = get_logger(__name__)


class DebugManager:
    """Centralized debug manager for LiteLLM operations."""

    @staticmethod
    def is_litellm_debug_enabled() -> bool:
        """Check if LiteLLM debug mode is enabled."""
        return settings.litellm_debug

    @staticmethod
    def is_debug_enabled() -> bool:
        """Check if any debug mode is enabled (LiteLLM debug or general debug)."""
        return settings.litellm_debug or settings.debug

    @staticmethod
    def enable_litellm_debug() -> None:
        """Enable LiteLLM debug mode for detailed error information."""
        try:
            litellm._turn_on_debug()
            logger.info("LiteLLM debug mode enabled")
        except Exception as e:
            log_exception(
                logger, f"Failed to enable LiteLLM debug mode: {e}", sys.exc_info()
            )

    @staticmethod
    def log_litellm_config(
        model: str,
        api_key: str | None,
        base_url: str | None,
        temperature: float,
        completion_max_tokens: int,
        context_window_tokens: int,
    ) -> None:
        """Log LiteLLM configuration details."""
        logger.info("LiteLLM Configuration:")
        logger.info(f"  Model: {model}")
        logger.info(f"  API Key: {'***' + api_key[-4:] if api_key else 'Not set'}")
        logger.info(f"  Base URL: {base_url or 'Default'}")
        logger.info(f"  Temperature: {temperature}")
        logger.info(f"  Completion Max Tokens: {completion_max_tokens}")
        logger.info(f"  Context Window Tokens: {context_window_tokens}")

    @staticmethod
    def log_context_token_usage(token_usage) -> None:
        """Log context token usage if debug mode is enabled."""
        if DebugManager.is_debug_enabled():
            logger.debug("Context token usage: %s", token_usage)

    @staticmethod
    def log_litellm_response(model: str, usage, tool_calls_count: int) -> None:
        """Log LiteLLM response details if debug mode is enabled."""
        if DebugManager.is_debug_enabled():
            logger.debug("LiteLLM Response:")
            logger.debug(f"  Model Used: {model}")
            logger.debug(f"  Usage: {usage}")
            logger.debug(f"  Tool Calls: {tool_calls_count}")

    @staticmethod
    def log_error_details(
        user_message: str,
        user_id: str,
        session_id: str,
        message_id: str,
        model: str,
        api_key: str | None,
    ) -> None:
        """Log detailed error information if debug mode is enabled."""
        if DebugManager.is_debug_enabled():
            logger.error("Debug Information:")
            logger.error(f"  User Message: {user_message}")
            logger.error(f"  User ID: {user_id}")
            logger.error(f"  Session ID: {session_id}")
            logger.error(f"  Message ID: {message_id}")
            logger.error(f"  Model: {model}")
            logger.error(f"  API Key Set: {bool(api_key)}")


# Global debug manager instance
debug_manager = DebugManager()
