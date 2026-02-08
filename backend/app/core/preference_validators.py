"""
Preference Validators

This module provides a registry-based validation system for user preferences.
Each preference can have a custom validator that performs specialized validation
beyond the basic allowed_values check.
"""

import re
import uuid
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import HTTPException, status
from sqlalchemy import and_
from sqlalchemy.orm import Session

from app.core.constants import VISION_EXPERIENCE_RATE_MAX
from app.db.models.dimension import Dimension
from app.db.models.vision import Vision


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
            HTTPException: If validation fails
        """


class VisionValidator(PreferenceValidator):
    """Validator for vision-related preferences"""

    def validate(self, db: Session, user_id: UUID, key: str, value: Any) -> Any:
        """Validate that vision ID exists and belongs to user"""
        if value is None:
            return value

        # Ensure value is valid UUID format before querying database
        try:
            if isinstance(value, str):
                # Try to parse as UUID to validate format
                uuid.UUID(value)
            elif not isinstance(value, UUID):
                raise ValueError("Value must be UUID or valid UUID string")
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid vision ID format. Must be a valid UUID.",
            )

        # Validate that the vision exists and belongs to the user
        vision = (
            db.query(Vision)
            .filter(
                and_(
                    Vision.user_id == user_id,
                    Vision.id == value,
                    Vision.deleted_at.is_(None),
                )
            )
            .first()
        )

        if not vision:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid vision ID. Vision must exist and belong to the user.",
            )

        return value


class DimensionValidator(PreferenceValidator):
    """Validator for dimension-related preferences"""

    def validate(self, db: Session, user_id: UUID, key: str, value: Any) -> Any:
        """Validate dimension order against user's existing dimensions"""
        # Allow explicit None/empty list
        if value is None:
            return []
        if not isinstance(value, list):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Dimension order must be a list of UUID.",
            )
        if len(value) == 0:
            return []

        # Get all dimension IDs for the user (including inactive ones)
        # This allows users to set order for dimensions that might be temporarily inactive
        existing_dimensions = (
            db.query(Dimension.id).filter(Dimension.user_id == user_id).all()
        )
        existing_ids = {d.id for d in existing_dimensions}  # type: ignore[attr-defined]

        # Filter out non-existent dimension IDs and remove duplicates
        # But keep the order as much as possible
        seen = set()
        validated_order = []
        invalid_ids = []
        for dim_id in value:
            # Convert string to UUID for comparison
            try:
                dim_uuid = UUID(dim_id) if isinstance(dim_id, str) else dim_id
            except (ValueError, TypeError):
                invalid_ids.append(dim_id)
                continue

            if dim_uuid in existing_ids and dim_uuid not in seen:
                validated_order.append(dim_uuid)
                seen.add(dim_uuid)
            elif dim_uuid not in seen:
                invalid_ids.append(dim_id)

        # If input was non-empty but all IDs were invalid, return 400
        if len(validated_order) == 0 and len(value) > 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "message": "No valid dimension IDs found.",
                    "invalid_ids": invalid_ids,
                },
            )
        # Convert UUID objects back to strings for JSON serialization
        return [str(uuid_obj) for uuid_obj in validated_order]


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


class VisionExperienceRateValidator(PreferenceValidator):
    """Validate experience rate per hour preference for visions"""

    def validate(self, db: Session, user_id: UUID, key: str, value: Any) -> Any:
        if value in (None, ""):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Experience rate per hour cannot be empty.",
            )

        try:
            rate = int(value)
        except (TypeError, ValueError) as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Experience rate per hour must be an integer.",
            ) from exc

        if rate < 1 or rate > VISION_EXPERIENCE_RATE_MAX:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Experience rate per hour must be between 1 and {VISION_EXPERIENCE_RATE_MAX}.",
            )

        return rate


class CurrencyValidator(PreferenceValidator):
    """Validator for currency codes (both fiat and cryptocurrency)"""

    def validate(self, db: Session, user_id: UUID, key: str, value: Any) -> Any:
        if value in (None, ""):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Currency code cannot be empty.",
            )

        if not isinstance(value, str):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Currency code must be a string.",
            )

        currency = value.strip().upper()

        # Basic validation: 1-16 characters, alphanumeric and some symbols
        if not re.match(r"^[A-Z0-9._-]{1,16}$", currency):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Currency code must be 1-16 characters containing only letters, numbers, dots, hyphens, and underscores.",
            )

        return currency


# Validator registry
VALIDATORS: Dict[str, PreferenceValidator] = {
    "vision_validator": VisionValidator(),
    "dimension_validator": DimensionValidator(),
    "timezone_validator": TimezoneValidator(),
    "vision_experience_rate_validator": VisionExperienceRateValidator(),
    "currency_validator": CurrencyValidator(),
}


def get_validator(validator_name: str) -> Optional[PreferenceValidator]:
    """Get validator by name from registry"""
    return VALIDATORS.get(validator_name)
