"""Token usage helper utilities for LLM API calls."""

import sys
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Dict, Optional, Tuple

import litellm

from app.core.logging import get_logger, log_exception

logger = get_logger(__name__)

_COST_PRECISION = Decimal("0.000001")

_MANUAL_PRICING_RATES: Tuple[Tuple[str, Dict[str, Decimal]], ...] = (
    (
        "glm-4.5-air",
        {
            "input": Decimal("0.0005") / 1000,
            "output": Decimal("0.0015") / 1000,
        },
    ),
)


@dataclass(frozen=True)
class TokenUsage:
    """Lightweight view of usage metrics returned by the LLM."""

    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


class TokenTracker:
    """Provide helpers for extracting usage metrics and estimating cost."""

    def extract_usage(self, completion_response: Any) -> TokenUsage:
        """Build a normalized usage object from LiteLLM responses."""

        usage = getattr(completion_response, "usage", None)

        prompt_tokens = getattr(usage, "prompt_tokens", 0) or 0
        completion_tokens = getattr(usage, "completion_tokens", 0) or 0
        total_tokens = getattr(usage, "total_tokens", None)

        if total_tokens is None:
            total_tokens = prompt_tokens + completion_tokens

        return TokenUsage(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
        )

    def calculate_cost(self, completion_response: Any) -> Optional[Decimal]:
        """Estimate the USD cost for a completion response."""

        model_name = getattr(completion_response, "model", "unknown") or "unknown"

        manual_rates = self._get_manual_rates(model_name)
        if manual_rates is not None:
            return self._manual_cost_calculation(completion_response)

        try:
            cost = litellm.completion_cost(completion_response=completion_response)
            if cost is not None:
                return Decimal(str(cost)).quantize(
                    _COST_PRECISION, rounding=ROUND_HALF_UP
                )
        except ValueError as exc:  # pragma: no cover - unsupported model pricing
            model_name = getattr(completion_response, "model", "unknown")
            logger.info(
                "LiteLLM pricing unavailable for model %s: %s",
                model_name,
                exc,
            )
        except Exception as exc:  # pragma: no cover - defensive logging
            log_exception(
                logger,
                f"LiteLLM cost calculation failed: {exc}",
                sys.exc_info(),
            )

        # Fallback manual calculation for unsupported models
        return self._manual_cost_calculation(completion_response)

    def _manual_cost_calculation(self, completion_response: Any) -> Optional[Decimal]:
        """Manual cost calculation for models not supported by LiteLLM."""

        try:
            usage = self.extract_usage(completion_response)

            model_name = getattr(completion_response, "model", "unknown") or "unknown"
            rates = self._get_manual_rates(model_name)

            if rates is None:
                logger.debug("TokenTracker: no pricing rates for model %s", model_name)
                return Decimal(0)
                # return None

            input_cost = Decimal(usage.prompt_tokens) * rates["input"]
            output_cost = Decimal(usage.completion_tokens) * rates["output"]
            return (input_cost + output_cost).quantize(
                _COST_PRECISION, rounding=ROUND_HALF_UP
            )

        except Exception as exc:  # pragma: no cover - defensive logging
            log_exception(
                logger,
                f"Manual cost calculation failed: {exc}",
                sys.exc_info(),
            )
            return Decimal(0)

    def _get_manual_rates(self, model_name: str) -> Optional[Dict[str, Decimal]]:
        """Return manual pricing for known models."""

        normalized_name = (model_name or "").lower()
        for pattern, rates in _MANUAL_PRICING_RATES:
            if pattern in normalized_name:
                return rates

        return None

    def get_model_pricing(self, model_name: str) -> Optional[dict]:
        """Proxy to LiteLLM pricing discovery."""

        try:
            return litellm.get_model_pricing(model_name)
        except Exception as exc:  # pragma: no cover - defensive logging
            log_exception(
                logger,
                f"Failed to get pricing for model {model_name}: {exc}",
                sys.exc_info(),
            )
            return Decimal(0)


# Shared tracker instance
token_tracker = TokenTracker()

__all__ = ["TokenTracker", "TokenUsage", "token_tracker"]
