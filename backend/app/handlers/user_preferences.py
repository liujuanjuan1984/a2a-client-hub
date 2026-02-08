"""
Async helpers for user preference reads used by async handlers.

These functions replicate the behavior of ``user_preferences.py`` but operate
with :class:`~sqlalchemy.ext.asyncio.AsyncSession` so that fully async handlers
don't need to fall back to ``run_with_session``.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple, Union
from uuid import UUID

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.core.constants import USER_PREFERENCE_DEFAULTS
from app.core.preference_validators import get_validator
from app.db.models.user_preference import UserPreference
from app.db.transaction import commit_safely
from app.utils.timezone_util import get_day_window, resolve_timezone

_DEFAULT_SENTINEL = object()


def _normalize_value_by_allowed_sync(
    db: Session,
    *,
    user_id: Union[UUID, str, None],
    key: str,
    value: Any,
) -> Any:
    cfg: Optional[Dict[str, Any]] = USER_PREFERENCE_DEFAULTS.get(key)
    if not cfg:
        return value

    default_value = cfg.get("value")
    validator_name = cfg.get("validator")
    if validator_name and db is not None and user_id is not None:
        validator = get_validator(validator_name)
        if validator:
            return validator.validate(db, user_id, key, value)

    allowed = cfg.get("allowed_values")
    if not allowed:
        if isinstance(default_value, list):
            try:
                incoming_list = list(value) if isinstance(value, list) else []
            except Exception:
                incoming_list = []
            return incoming_list
        return value

    try:
        allowed_set = set(allowed)
    except Exception:
        allowed_set = set()

    if isinstance(default_value, list):
        try:
            incoming_list = list(value) if isinstance(value, list) else []
        except Exception:
            incoming_list = []
        seen: set = set()
        normalized_list: List[Any] = []
        for item in incoming_list:
            if item in allowed_set and item not in seen:
                seen.add(item)
                normalized_list.append(item)
        return normalized_list if normalized_list else list(default_value)

    if isinstance(value, (list, dict)):
        return default_value

    coerced = value
    try:
        if isinstance(default_value, int):
            coerced = int(value)
        elif isinstance(default_value, str):
            coerced = str(value)
    except Exception:
        return default_value

    if coerced in allowed_set:
        return coerced
    return default_value


async def normalize_preference_value(
    db: AsyncSession,
    *,
    user_id: Union[UUID, str],
    key: str,
    value: Any,
) -> Any:
    def _run_normalizer(sync_session: Session):
        return _normalize_value_by_allowed_sync(
            sync_session,
            user_id=user_id,
            key=key,
            value=value,
        )

    return await db.run_sync(_run_normalizer)


async def get_preference_by_key(
    db: AsyncSession,
    *,
    user_id: Union[UUID, str],
    key: str,
) -> Optional[UserPreference]:
    stmt = (
        select(UserPreference)
        .where(
            and_(
                UserPreference.user_id == user_id,
                UserPreference.key == key,
                UserPreference.deleted_at.is_(None),
            )
        )
        .limit(1)
    )
    result = await db.execute(stmt)
    return result.scalars().first()


async def create_default_preference(
    db: AsyncSession,
    *,
    user_id: Union[UUID, str],
    key: str,
) -> Optional[UserPreference]:
    cfg = USER_PREFERENCE_DEFAULTS.get(key)
    if not cfg:
        return None

    preference = UserPreference(
        user_id=user_id,
        key=key,
        value=cfg.get("value"),
        module=cfg.get("module", "general"),
    )
    db.add(preference)
    await commit_safely(db)
    await db.refresh(preference)
    return preference


async def get_preference_value(
    db: AsyncSession,
    *,
    user_id: Union[UUID, str],
    key: str,
    default: Any = _DEFAULT_SENTINEL,
) -> Any:
    preference = await get_preference_by_key(db, user_id=user_id, key=key)
    if preference is None:
        preference = await create_default_preference(db, user_id=user_id, key=key)
    if preference is None:
        return None if default is _DEFAULT_SENTINEL else default

    normalized = await normalize_preference_value(
        db, user_id=user_id, key=key, value=preference.value
    )
    if normalized is None and default is not _DEFAULT_SENTINEL:
        return default
    return normalized


async def get_user_timezone(
    db: AsyncSession,
    *,
    user_id: Union[UUID, str],
    default: str = "UTC",
) -> str:
    value = await get_preference_value(
        db, user_id=user_id, key="system.timezone", default=default
    )
    return value if isinstance(value, str) else default


async def list_preferences(
    db: AsyncSession,
    *,
    user_id: UUID,
    module: Optional[str],
    page: int,
    size: int,
) -> Tuple[List[UserPreference], int, int, int]:
    stmt = select(UserPreference).where(
        UserPreference.user_id == user_id,
        UserPreference.deleted_at.is_(None),
    )
    if module:
        stmt = stmt.where(UserPreference.module == module)

    count_stmt = (
        select(func.count(UserPreference.id))
        .where(
            UserPreference.user_id == user_id,
            UserPreference.deleted_at.is_(None),
        )
        .order_by(None)
    )
    if module:
        count_stmt = count_stmt.where(UserPreference.module == module)

    total = (await db.execute(count_stmt)).scalar_one()
    rows = await db.execute(
        stmt.order_by(UserPreference.module.asc(), UserPreference.key.asc())
        .offset((page - 1) * size)
        .limit(size)
    )
    items = rows.scalars().all()
    pages = (total + size - 1) // size if size else 1
    return items, total, page, pages


async def set_preference_value(
    db: AsyncSession,
    *,
    user_id: UUID,
    key: str,
    value: Any,
    module: Optional[str] = None,
) -> UserPreference:
    preference = await get_preference_by_key(db, user_id=user_id, key=key)
    normalized = await normalize_preference_value(
        db, user_id=user_id, key=key, value=value
    )
    if preference:
        preference.value = normalized
        if module is not None:
            preference.module = module
    else:
        resolved_module = module or USER_PREFERENCE_DEFAULTS.get(key, {}).get(
            "module", "general"
        )
        preference = UserPreference(
            user_id=user_id, key=key, value=normalized, module=resolved_module
        )
        db.add(preference)

    await commit_safely(db)
    await db.refresh(preference)
    return preference


async def get_preference(
    db: AsyncSession,
    *,
    user_id: Union[UUID, str],
    key: str,
    with_meta: bool = False,
) -> Optional[Dict[str, Any]]:
    value = await get_preference_value(
        db, user_id=user_id, key=key, default=_DEFAULT_SENTINEL
    )
    if value is _DEFAULT_SENTINEL:
        return None

    cfg: Dict[str, Any] = USER_PREFERENCE_DEFAULTS.get(key, {})
    if with_meta:
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
    return {"key": key, "value": value}


__all__ = [
    "convert_date_range_to_timezone",
    "create_default_preference",
    "get_preference",
    "get_preference_by_key",
    "get_preference_value",
    "normalize_preference_value",
    "get_user_timezone",
    "list_preferences",
    "set_preference_value",
]


async def convert_date_range_to_timezone(
    db: AsyncSession,
    *,
    user_id: Union[UUID, str],
    start_date: date,
    end_date: date,
    timezone_key: str = "system.timezone",
    default_timezone: str = "UTC",
) -> tuple[datetime, datetime]:
    timezone_name = await get_preference_value(
        db,
        user_id=user_id,
        key=timezone_key,
        default=default_timezone,
    )
    tzinfo = resolve_timezone(str(timezone_name), default=default_timezone)
    resolved = tzinfo.key if hasattr(tzinfo, "key") else timezone_name

    start_window = get_day_window(resolved, start_date)
    end_window = get_day_window(resolved, end_date)

    start_dt = start_window.start_local
    end_dt = end_window.end_local - timedelta(seconds=1)
    return start_dt, end_dt
