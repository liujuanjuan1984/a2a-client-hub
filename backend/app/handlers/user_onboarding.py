"""Async user onboarding helpers."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.i18n import get_translator
from app.core.logging import get_logger
from app.db.models.dimension import Dimension
from app.db.models.user import User
from app.db.models.vision import Vision
from app.handlers import dimensions as dimension_service
from app.handlers import user_preferences as user_preferences_service
from app.handlers.dimensions import DimensionAlreadyExistsError
from app.schemas.dimension import DimensionCreate


class UserOnboardingService:
    """Service for handling new user onboarding tasks."""

    _DEFAULT_DIMENSIONS = (
        {
            "slug": "health",
            "color": "#10B981",
            "icon": "health",
            "fallback_name": "Health",
            "fallback_description": "Focus on daily actions that support physical and mental wellbeing.",
        },
        {
            "slug": "growth",
            "color": "#6366F1",
            "icon": "learning",
            "fallback_name": "Growth",
            "fallback_description": "Continual learning and personal development activities.",
        },
        {
            "slug": "family",
            "color": "#F59E0B",
            "icon": "family",
            "fallback_name": "Family",
            "fallback_description": "Time invested in nurturing family connections and responsibilities.",
        },
        {
            "slug": "work",
            "color": "#3B82F6",
            "icon": "work",
            "fallback_name": "Work",
            "fallback_description": "Tasks and projects that advance professional and career goals.",
        },
        {
            "slug": "wealth",
            "color": "#F97316",
            "icon": "finance",
            "fallback_name": "Wealth",
            "fallback_description": "Activities that strengthen financial health and resource management.",
        },
        {
            "slug": "relationships",
            "color": "#EC4899",
            "icon": "social",
            "fallback_name": "Relationships",
            "fallback_description": "Building and sustaining meaningful social and community relationships.",
        },
        {
            "slug": "leisure",
            "color": "#22D3EE",
            "icon": "hobby",
            "fallback_name": "Leisure",
            "fallback_description": "Recreational and hobby activities that relax and inspire.",
        },
        {
            "slug": "contribution",
            "color": "#8B5CF6",
            "icon": "spirituality",
            "fallback_name": "Contribution",
            "fallback_description": "Efforts that give back to others and support shared causes.",
        },
        {
            "slug": "other",
            "color": "#9CA3AF",
            "icon": None,
            "fallback_name": "Other",
            "fallback_description": "Items that span multiple areas or are not yet categorized.",
        },
    )

    _logger = get_logger(__name__)

    @staticmethod
    async def create_default_data_for_user(db: AsyncSession, user: User) -> None:
        """
        Create default data for a new user

        This method creates all the necessary default data that a new user
        should have when they first register. It can be easily extended
        to support additional default data creation.

        Args:
            db: Database session
            user: The newly created user
        """

        # Create default "Todos Inbox" vision
        await UserOnboardingService._create_default_vision(db, user)

        # Create default life dimensions
        await UserOnboardingService._create_default_dimensions(db, user)
        # UserOnboardingService._create_default_habits(db, user)
        # UserOnboardingService._create_welcome_tasks(db, user)

    @staticmethod
    async def _create_default_vision(db: AsyncSession, user: User) -> None:
        """
        Create default 'Todos Inbox' vision for new user

        This creates a default vision that serves as an inbox for collecting
        and managing todos. It provides a starting point for new users.

        Args:
            db: Database session
            user: The user to create the vision for
        """
        preference_key = "todos.default_inbox_vision"

        # Skip if user already has a non-empty default inbox vision configured
        existing_pref = await user_preferences_service.get_preference_by_key(
            db, user_id=user.id, key=preference_key
        )
        if existing_pref and existing_pref.value not in (None, "", []):
            return

        stmt = (
            select(Vision)
            .where(
                Vision.user_id == user.id,
                Vision.name == "Todos Inbox",
                Vision.deleted_at.is_(None),
            )
            .order_by(Vision.created_at.asc())
            .limit(1)
        )
        existing_inbox = (await db.execute(stmt)).scalars().first()

        if existing_inbox:
            default_vision = existing_inbox
        else:
            default_vision = Vision(
                user_id=user.id,
                name="Todos Inbox",
                description="收集和管理待办事项的默认愿景。您可以在这里整理和规划您的任务。",
                status="active",
                stage=0,
                experience_points=0,
            )
            db.add(default_vision)

        try:
            # Flush pending changes so the validator can query the new vision
            await db.flush()
            await user_preferences_service.set_preference_value(
                db,
                user_id=user.id,
                key=preference_key,
                value=str(default_vision.id),
                module="todos",
            )
        except Exception as exc:  # pragma: no cover - defensive logging
            UserOnboardingService._logger.warning(
                "Failed to set default inbox vision preference for user %s: %s",
                user.id,
                exc,
                exc_info=True,
            )

    @staticmethod
    async def _create_default_dimensions(db: AsyncSession, user: User) -> None:
        """
        Create default life dimensions for new user

        Args:
            db: Database session
            user: The user to create the dimensions for
        """

        preferred_language = await user_preferences_service.resolve_language_preference(
            db, user_id=user.id, default="en"
        )
        translator = get_translator(preferred_language)

        rows = await db.execute(
            select(Dimension.name).where(Dimension.user_id == user.id)
        )
        existing_names = {name for (name,) in rows.all()}

        for display_order, config in enumerate(
            UserOnboardingService._DEFAULT_DIMENSIONS
        ):
            if not isinstance(config, dict):
                continue

            name = translator(
                f"onboarding.dimension.{config['slug']}.name",
                default=config["fallback_name"],
            )
            if name in existing_names:
                continue

            description = translator(
                f"onboarding.dimension.{config['slug']}.description",
                default=config["fallback_description"],
            )

            dimension_in = DimensionCreate(
                name=name,
                description=description,
                color=config["color"],
                icon=config["icon"],
                is_active=True,
                display_order=display_order,
            )

            try:
                await dimension_service.create_dimension(
                    db, user_id=user.id, dimension_in=dimension_in
                )
                existing_names.add(name)
            except DimensionAlreadyExistsError:
                existing_names.add(name)
            except Exception as exc:  # pragma: no cover - defensive logging
                UserOnboardingService._logger.warning(
                    "Failed to create default dimension '%s' for user %s: %s",
                    config["slug"],
                    user.id,
                    exc,
                    exc_info=True,
                )

    # Future methods for additional default data creation
    # @staticmethod
    # def _create_default_dimensions(db: Session, user: User) -> None:
    #     """Create default dimensions for new user"""
    #     pass
    #
    # @staticmethod
    # def _create_default_habits(db: Session, user: User) -> None:
    #     """Create default habits for new user"""
    #     pass
    #
    # @staticmethod
    # def _create_welcome_tasks(db: Session, user: User) -> None:
    #     """Create welcome tasks for new user"""
    #     pass
