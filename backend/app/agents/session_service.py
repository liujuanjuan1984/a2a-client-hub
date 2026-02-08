"""
Session Service Layer

This module contains business logic for session operations.
It orchestrates the session workflow by coordinating between:
- Session Handler (data persistence)
- Business workflow coordination
"""

import sys
from typing import List
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger, log_exception
from app.handlers import agent_session as session_handler
from app.handlers.agent_session import SessionHandlerError
from app.schemas.session import CreateSessionRequest, UpdateSessionRequest
from app.services import notifications as notification_service

logger = get_logger(__name__)


class SessionServiceError(Exception):
    """Base exception for session service errors."""


class SessionService:
    """
    Service class for orchestrating session operations.

    This service coordinates the session workflow by:
    - Business logic validation
    - Workflow coordination
    - Error handling and logging
    """

    async def _apply_system_unread_counts(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        sessions: List,
    ) -> None:
        system_sessions = [
            session
            for session in sessions
            if getattr(session, "session_type", None) == "system"
        ]
        if not system_sessions:
            return

        for session in system_sessions:
            session.unread_count = (
                await notification_service.count_unread_system_notifications(
                    db, user_id=user_id, session_id=session.id
                )
            )

    async def create_session(
        self,
        db: AsyncSession,
        user_id: UUID,
        request: CreateSessionRequest,
    ):
        """
        Create a new session for the user.

        Args:
            db: Database session
            user_id: ID of the user
            request: Session creation request

        Returns:
            Created session

        Raises:
            SessionServiceError: If session creation fails
        """
        try:
            session = await session_handler.create_session(
                db,
                user_id=user_id,
                name=request.name,
                sync_cardbox=request.sync_cardbox,
                module_key=request.agent_name,
            )

            logger.info(f"Successfully created session {session.id} for user {user_id}")
            return session

        except SessionHandlerError as e:
            log_exception(logger, f"Session handler error: {str(e)}", sys.exc_info())
            raise SessionServiceError(f"Failed to create session: {str(e)}")
        except Exception as e:
            log_exception(
                logger, f"Unexpected error in create_session: {str(e)}", sys.exc_info()
            )
            raise SessionServiceError(f"Failed to create session: {str(e)}")

    async def get_session(
        self,
        db: AsyncSession,
        session_id: UUID,
        user_id: UUID,
    ):
        """
        Get a session by ID for the user.

        Args:
            db: Database session
            session_id: Session ID
            user_id: ID of the user

        Returns:
            Session if found, None otherwise

        Raises:
            SessionServiceError: If session retrieval fails
        """
        try:
            session = await session_handler.get_session(
                db,
                session_id=session_id,
                user_id=user_id,
            )
            return session

        except SessionHandlerError as e:
            log_exception(logger, f"Session handler error: {str(e)}", sys.exc_info())
            raise SessionServiceError(f"Failed to get session: {str(e)}")
        except Exception as e:
            log_exception(
                logger, f"Unexpected error in get_session: {str(e)}", sys.exc_info()
            )
            raise SessionServiceError(f"Failed to get session: {str(e)}")

    async def get_user_sessions(
        self,
        db: AsyncSession,
        user_id: UUID,
        limit: int = 20,
        offset: int = 0,
    ) -> List:
        """
        Get sessions for a user with pagination.

        Args:
            db: Database session
            user_id: ID of the user
            limit: Maximum number of sessions to return
            offset: Number of sessions to skip

        Returns:
            List of sessions

        Raises:
            SessionServiceError: If session retrieval fails
        """
        try:
            sessions = await session_handler.get_user_sessions(
                db,
                user_id=user_id,
                limit=limit,
                offset=offset,
            )
            await self._apply_system_unread_counts(
                db,
                user_id=user_id,
                sessions=sessions,
            )

            logger.info(f"Retrieved {len(sessions)} sessions for user {user_id}")
            return sessions

        except SessionHandlerError as e:
            log_exception(logger, f"Session handler error: {str(e)}", sys.exc_info())
            raise SessionServiceError(f"Failed to get user sessions: {str(e)}")
        except Exception as e:
            log_exception(
                logger,
                f"Unexpected error in get_user_sessions: {str(e)}",
                sys.exc_info(),
            )
            raise SessionServiceError(f"Failed to get user sessions: {str(e)}")

    async def get_user_sessions_with_total(
        self,
        db: AsyncSession,
        user_id: UUID,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[List, int]:
        """Get sessions for a user with total count."""
        try:
            sessions, total = await session_handler.get_user_sessions_with_total(
                db,
                user_id=user_id,
                limit=limit,
                offset=offset,
            )
            await self._apply_system_unread_counts(
                db,
                user_id=user_id,
                sessions=sessions,
            )
            logger.info(f"Retrieved {len(sessions)} sessions for user {user_id}")
            return sessions, total
        except SessionHandlerError as e:
            log_exception(logger, f"Session handler error: {str(e)}", sys.exc_info())
            raise SessionServiceError(f"Failed to get user sessions: {str(e)}") from e
        except Exception as e:
            log_exception(
                logger,
                f"Unexpected error in get_user_sessions_with_total: {str(e)}",
                sys.exc_info(),
            )
            raise SessionServiceError(f"Failed to get user sessions: {str(e)}") from e

    async def update_session(
        self,
        db: AsyncSession,
        session_id: UUID,
        user_id: UUID,
        request: UpdateSessionRequest,
    ):
        """
        Update a session.

        Args:
            db: Database session
            session_id: Session ID
            user_id: ID of the user
            request: Session update request

        Returns:
            Updated session if found, None otherwise

        Raises:
            SessionServiceError: If session update fails
        """
        try:
            session = await session_handler.update_session(
                db,
                session_id=session_id,
                user_id=user_id,
                name=request.name,
                agent_name=request.agent_name,
            )

            if session:
                logger.info(f"Successfully updated session {session_id}")
            else:
                logger.warning(f"Session {session_id} not found for user {user_id}")

            return session

        except SessionHandlerError as e:
            log_exception(logger, f"Session handler error: {str(e)}", sys.exc_info())
            raise SessionServiceError(f"Failed to update session: {str(e)}")
        except Exception as e:
            log_exception(
                logger, f"Unexpected error in update_session: {str(e)}", sys.exc_info()
            )
            raise SessionServiceError(f"Failed to update session: {str(e)}")

    async def delete_session(
        self,
        db: AsyncSession,
        session_id: UUID,
        user_id: UUID,
    ) -> bool:
        """
        Delete a session.

        Args:
            db: Database session
            session_id: Session ID
            user_id: ID of the user

        Returns:
            True if session was deleted, False if not found

        Raises:
            SessionServiceError: If session deletion fails
        """
        try:
            deleted = await session_handler.delete_session(
                db,
                session_id=session_id,
                user_id=user_id,
            )

            if deleted:
                logger.info(f"Successfully deleted session {session_id}")
            else:
                logger.warning(f"Session {session_id} not found for user {user_id}")

            return deleted

        except SessionHandlerError as e:
            log_exception(logger, f"Session handler error: {str(e)}", sys.exc_info())
            raise SessionServiceError(f"Failed to delete session: {str(e)}")
        except Exception as e:
            log_exception(
                logger, f"Unexpected error in delete_session: {str(e)}", sys.exc_info()
            )
            raise SessionServiceError(f"Failed to delete session: {str(e)}")


# Create singleton instance
session_service = SessionService()
