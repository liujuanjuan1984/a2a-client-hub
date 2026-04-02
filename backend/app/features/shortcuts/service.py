"""Shortcut feature service for persistence and validation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence, cast
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.shortcut import Shortcut as ShortcutModel
from app.db.models.user import User
from app.db.transaction import commit_safely
from app.features.shortcuts.schemas import ShortcutResponse


class ShortcutServiceError(RuntimeError):
    """Base class for shortcut service errors."""


class ShortcutNotFoundError(ShortcutServiceError):
    """Raised when a shortcut can not be located for the user."""


class ShortcutValidationError(ShortcutServiceError):
    """Raised when shortcut payload validation fails."""


class ShortcutForbiddenError(ShortcutServiceError):
    """Raised when user attempts to modify default shortcuts."""


@dataclass(frozen=True)
class _DefaultShortcutDef:
    shortcut_id: UUID
    title: str
    prompt: str
    order: int


_DEFAULT_SHORTCUTS: tuple[_DefaultShortcutDef, ...] = (
    _DefaultShortcutDef(
        shortcut_id=UUID("11111111-1111-1111-1111-111111111111"),
        title="📝 Summarize",
        prompt="Please summarize our conversation so far.",
        order=0,
    ),
    _DefaultShortcutDef(
        shortcut_id=UUID("22222222-2222-2222-2222-222222222222"),
        title="🔍 Explain",
        prompt="Can you explain this in more detail?",
        order=1,
    ),
    _DefaultShortcutDef(
        shortcut_id=UUID("33333333-3333-3333-3333-333333333333"),
        title="💡 Next Steps",
        prompt="What should be our next steps?",
        order=2,
    ),
    _DefaultShortcutDef(
        shortcut_id=UUID("44444444-4444-4444-4444-444444444444"),
        title="✨ Polish",
        prompt="Please polish the text I just sent.",
        order=3,
    ),
    _DefaultShortcutDef(
        shortcut_id=UUID("55555555-5555-5555-5555-555555555555"),
        title="❓ Help",
        prompt="What are your main capabilities?",
        order=4,
    ),
)

_DEFAULT_SHORTCUT_IDS = frozenset(
    definition.shortcut_id for definition in _DEFAULT_SHORTCUTS
)


def _default_shortcuts() -> list[ShortcutResponse]:
    return [
        ShortcutResponse(
            id=definition.shortcut_id,
            title=definition.title,
            prompt=definition.prompt,
            is_default=True,
            order=definition.order,
            agent_id=None,
            created_at=None,
        )
        for definition in sorted(_DEFAULT_SHORTCUTS, key=lambda item: item.order)
    ]


def _is_default_shortcut_id(shortcut_id: UUID) -> bool:
    return shortcut_id in _DEFAULT_SHORTCUT_IDS


def _normalize_title(value: str) -> str:
    title = value.strip()
    if not title:
        raise ShortcutValidationError("Shortcut title cannot be empty")
    if len(title) > ShortcutModel.TITLE_MAX_LENGTH:
        raise ShortcutValidationError("Shortcut title is too long")
    return title


def _normalize_prompt(value: str) -> str:
    prompt = value.strip()
    if not prompt:
        raise ShortcutValidationError("Shortcut prompt cannot be empty")
    if len(prompt) > ShortcutModel.PROMPT_MAX_LENGTH:
        raise ShortcutValidationError("Shortcut prompt is too long")
    return prompt


def _normalize_order(value: int | None, *, default: int = 0) -> int:
    if value is None:
        return default
    if value < ShortcutModel.ORDER_MIN:
        raise ShortcutValidationError("Shortcut order cannot be negative")
    return value


def _next_order(items: Sequence[ShortcutModel]) -> int:
    if not items:
        return 0
    return max(cast(int, item.sort_order) for item in items) + 1


def _shortcut_to_payload(shortcut: ShortcutModel) -> ShortcutResponse:
    return ShortcutResponse(
        id=cast(UUID, shortcut.id),
        title=cast(str, shortcut.title),
        prompt=cast(str, shortcut.prompt),
        is_default=bool(shortcut.is_default),
        order=int(shortcut.sort_order),
        agent_id=cast(UUID | None, shortcut.agent_id),
        created_at=getattr(shortcut, "created_at", None),
    )


class ShortcutService:
    async def list_shortcuts(
        self,
        *,
        db: AsyncSession,
        user_id: UUID,
        agent_id: UUID | None = None,
        page: int = 1,
        size: int = 50,
        user: User | None = None,
    ) -> tuple[list[ShortcutResponse], int]:
        del user
        defaults = _default_shortcuts()

        # Build base filter for custom shortcuts
        base_filter = [
            ShortcutModel.user_id == user_id,
            ShortcutModel.is_default.is_(False),
        ]
        if agent_id is not None:
            # If agent_id is provided, show both general shortcuts and agent-specific ones
            base_filter.append(
                (ShortcutModel.agent_id == agent_id)
                | (ShortcutModel.agent_id.is_(None))
            )

        # Count custom shortcuts
        count_query = select(func.count(ShortcutModel.id)).where(*base_filter)
        total_customs = (await db.execute(count_query)).scalar() or 0
        total_all = len(defaults) + total_customs

        # Fetch custom shortcuts
        query = (
            select(ShortcutModel)
            .where(*base_filter)
            .order_by(ShortcutModel.sort_order.asc(), ShortcutModel.created_at.asc())
        )

        # Pagination is intentionally mixed here: built-in defaults are a small,
        # fixed in-memory source that must stay ahead of user-defined shortcuts,
        # while custom shortcuts continue to use DB offset/limit.
        start_index = (page - 1) * size
        end_index = start_index + size

        # 1. Slice defaults if they are within the window
        visible_defaults = defaults[start_index:end_index]

        # 2. Fetch customs if the window extends beyond defaults
        custom_offset = max(0, start_index - len(defaults))
        custom_limit = size - len(visible_defaults)

        if custom_limit > 0:
            query = query.offset(custom_offset).limit(custom_limit)
            rows = (await db.execute(query)).scalars().all()
            customs = [_shortcut_to_payload(row) for row in rows]
        else:
            customs = []

        return [*visible_defaults, *customs], total_all

    async def create_shortcut(
        self,
        *,
        db: AsyncSession,
        user_id: UUID,
        title: str,
        prompt: str,
        order: int | None = None,
        agent_id: UUID | None = None,
    ) -> ShortcutResponse:
        normalized_title = _normalize_title(title)
        normalized_prompt = _normalize_prompt(prompt)

        custom_rows = (
            (
                await db.execute(
                    select(ShortcutModel)
                    .where(ShortcutModel.user_id == user_id)
                    .where(ShortcutModel.is_default.is_(False))
                    .order_by(
                        ShortcutModel.sort_order.asc(), ShortcutModel.created_at.asc()
                    )
                )
            )
            .scalars()
            .all()
        )

        normalized_order = _normalize_order(order, default=_next_order(custom_rows))

        shortcut = ShortcutModel(
            user_id=user_id,
            title=normalized_title,
            prompt=normalized_prompt,
            is_default=False,
            sort_order=normalized_order,
            agent_id=agent_id,
        )
        db.add(shortcut)
        await commit_safely(db)
        await db.refresh(shortcut)
        return _shortcut_to_payload(shortcut)

    async def update_shortcut(
        self,
        *,
        db: AsyncSession,
        user: User,
        shortcut_id: UUID,
        title: str | None = None,
        prompt: str | None = None,
        order: int | None = None,
        agent_id: UUID | None = None,
        clear_agent: bool = False,
    ) -> ShortcutResponse:
        if _is_default_shortcut_id(shortcut_id):
            raise ShortcutForbiddenError("Default shortcuts cannot be modified")

        user_id = cast(UUID, user.id)
        shortcut = (
            await db.execute(
                select(ShortcutModel).where(
                    ShortcutModel.id == shortcut_id,
                    ShortcutModel.user_id == user_id,
                )
            )
        ).scalar_one_or_none()

        if shortcut is None:
            raise ShortcutNotFoundError("Shortcut not found")

        if cast(bool, shortcut.is_default):
            raise ShortcutForbiddenError("Default shortcuts cannot be modified")

        if title is not None:
            setattr(shortcut, "title", _normalize_title(title))
        if prompt is not None:
            setattr(shortcut, "prompt", _normalize_prompt(prompt))
        if order is not None:
            setattr(
                shortcut,
                "sort_order",
                _normalize_order(order, default=cast(int, shortcut.sort_order)),
            )
        if clear_agent:
            setattr(shortcut, "agent_id", None)
        elif agent_id is not None:
            setattr(shortcut, "agent_id", agent_id)

        await commit_safely(db)
        await db.refresh(shortcut)
        return _shortcut_to_payload(shortcut)

    async def remove_shortcut(
        self,
        *,
        db: AsyncSession,
        user: User,
        shortcut_id: UUID,
    ) -> None:
        if _is_default_shortcut_id(shortcut_id):
            raise ShortcutForbiddenError("Default shortcuts cannot be deleted")

        user_id = cast(UUID, user.id)
        shortcut = (
            await db.execute(
                select(ShortcutModel).where(
                    ShortcutModel.id == shortcut_id,
                    ShortcutModel.user_id == user_id,
                )
            )
        ).scalar_one_or_none()

        if shortcut is None:
            raise ShortcutNotFoundError("Shortcut not found")

        if cast(bool, shortcut.is_default):
            raise ShortcutForbiddenError("Default shortcuts cannot be deleted")

        await db.delete(shortcut)
        await commit_safely(db)


a2_shortcut_service = ShortcutService()


# Alias kept for compatibility.
shortcuts_service = a2_shortcut_service
