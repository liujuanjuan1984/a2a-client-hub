"""
User Filter Mixin for data isolation

This mixin provides automatic user-based filtering for all models that have a user_id field.
It ensures that users can only access their own data.
"""

from typing import Union
from uuid import UUID

from sqlalchemy import Column
from sqlalchemy.orm import Query


class UserFilterMixin:
    """
    Mixin to add user-based filtering to models by overriding SoftDeleteMixin methods.

    When a model inherits from both SoftDeleteMixin and this mixin, these methods
    will be used, providing both user filtering and soft-delete filtering in one call.
    """

    @classmethod
    def active(cls, db_session, user_id: Union[UUID, Column, None] = None) -> Query:
        """
        Return a query for active records, optionally filtered by user_id.
        Overrides SoftDeleteMixin.active.
        """
        query = super().active(db_session)  # type: ignore
        if user_id is not None and hasattr(cls, "user_id"):
            query = query.filter(cls.user_id == user_id)
        return query

    @classmethod
    def with_deleted(
        cls, db_session, user_id: Union[UUID, Column, None] = None
    ) -> Query:
        """
        Return a query including deleted records, optionally filtered by user_id.
        Overrides SoftDeleteMixin.with_deleted.
        """
        query = super().with_deleted(db_session)  # type: ignore
        if user_id is not None and hasattr(cls, "user_id"):
            query = query.filter(cls.user_id == user_id)
        return query

    @classmethod
    def only_deleted(
        cls, db_session, user_id: Union[UUID, Column, None] = None
    ) -> Query:
        """
        Return a query for only deleted records, optionally filtered by user_id.
        Overrides SoftDeleteMixin.only_deleted.
        """
        query = super().only_deleted(db_session)  # type: ignore
        if user_id is not None and hasattr(cls, "user_id"):
            query = query.filter(cls.user_id == user_id)
        return query
