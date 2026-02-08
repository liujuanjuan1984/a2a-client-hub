"""
User Preferences API Router

This router handles simplified HTTP endpoints for user preference management.
Service logic has been moved to app.services.user_preferences.
"""

from typing import Any, Dict

from fastapi import Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_async_db, get_current_user
from app.api.routing import StrictAPIRouter
from app.core.constants import USER_PREFERENCE_DEFAULTS
from app.core.logging import get_logger
from app.db.models.user import User
from app.handlers import user_preferences as user_preferences_service
from app.handlers.visions import (
    VISION_EXPERIENCE_PREF_KEY,
    InvalidVisionExperienceRateError,
    get_user_experience_rate,
    update_all_vision_experience_rates,
)
from app.schemas.user_preference import UserPreferenceResponse

router = StrictAPIRouter()
logger = get_logger(__name__)


@router.get("/preferences/{key}")
async def get_preference(
    *,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
    key: str,
    meta: bool = Query(
        False, description="Return meta such as allowed_values and default"
    ),
) -> Dict[str, Any]:
    """
    Get a specific preference by key.

    If the preference doesn't exist but is defined in USER_PREFERENCE_DEFAULTS,
    it will be automatically created with the default value and returned.
    """
    sentinel = object()
    value = await user_preferences_service.get_preference_value(
        db,
        user_id=current_user.id,
        key=key,
        default=sentinel,
    )
    if value is sentinel:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Preference with key '{key}' not found",
        )
    if not meta:
        return {"key": key, "value": value}

    cfg = USER_PREFERENCE_DEFAULTS.get(key, {})
    return {
        "key": key,
        "value": value,
        "meta": {
            "allowed_values": list(cfg.get("allowed_values") or []),
            "default_value": cfg.get("value"),
            "description": cfg.get("description"),
            "module": cfg.get("module"),
        },
    }


@router.put("/preferences/{key}", response_model=UserPreferenceResponse)
async def set_preference(
    *,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
    key: str,
    request_data: Dict[str, Any],
) -> UserPreferenceResponse:
    """
    Set a preference (create or update)

    Request body should contain:
    - value: The preference value
    - module: Optional module name (defaults to "general")
    """
    value = request_data.get("value")
    module = request_data.get("module", "general")

    if value is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing required field: value",
        )

    preference = await user_preferences_service.set_preference_value(
        db,
        user_id=current_user.id,
        key=key,
        value=value,
        module=module,
    )

    if key == VISION_EXPERIENCE_PREF_KEY:
        try:
            user_rate = await get_user_experience_rate(db, user_id=current_user.id)
            await update_all_vision_experience_rates(
                db,
                user_id=current_user.id,
                experience_rate_per_hour=user_rate,
            )
        except InvalidVisionExperienceRateError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(exc),
            ) from exc
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.warning(
                "Vision experience resync failed after preference update for user %s: %s",
                current_user.id,
                exc,
                exc_info=True,
            )

    return preference
