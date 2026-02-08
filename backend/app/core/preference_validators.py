"""Preference validators for user preferences.

This backend cut keeps only the validators required by the A2A client surface.
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, Optional
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import HTTPException, status
from sqlalchemy.orm import Session


class PreferenceValidator(ABC):
    """Base class for preference validators"""

    @abstractmethod
    def validate(self, db: Session, user_id: UUID, key: str, value: Any) -> Any:
        """
        Validate and normalize a preference value.

        Args:
            db: Database session
            user_id: User ID
            key: Preference key
            value: Value to validate

        Returns:
            Validated and normalized value

        Raises:
            HTTPException: If validation fails.
        """


class TimezoneValidator(PreferenceValidator):
    """Validator for timezone preference values"""

    def validate(self, db: Session, user_id: UUID, key: str, value: Any) -> Any:
        if value in (None, ""):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Timezone cannot be empty.",
            )

        if not isinstance(value, str):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Timezone must be a string.",
            )

        tz_value = value.strip()
        try:
            ZoneInfo(tz_value)
        except ZoneInfoNotFoundError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid timezone identifier.",
            ) from exc

        return tz_value


# Validator registry
VALIDATORS: Dict[str, PreferenceValidator] = {
    "timezone_validator": TimezoneValidator(),
}


def get_validator(validator_name: str) -> Optional[PreferenceValidator]:
    """Get validator by name from registry"""
    return VALIDATORS.get(validator_name)
