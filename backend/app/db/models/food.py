"""
Food SQLAlchemy model

This model represents food items in the food library with nutritional information.
"""

from sqlalchemy import Boolean, Column, Float, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.db.models.base import SCHEMA_NAME, Base, SoftDeleteMixin, TimestampMixin


class Food(Base, TimestampMixin, SoftDeleteMixin):
    """
    Food model representing food items in the food library

    Each food item contains nutritional information and can be used
    to create food diary entries.
    """

    __tablename__ = "foods"
    __table_args__ = ({"schema": SCHEMA_NAME},)

    # id is inherited from TimestampMixin

    # User ownership (nullable for common/public foods)
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA_NAME}.users.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
        comment="Owner of the food item. NULL for common foods.",
    )

    # Food properties
    name = Column(String(200), nullable=False, index=True, comment="Food name")
    description = Column(
        Text, nullable=True, comment="Additional description of the food"
    )
    is_common = Column(
        Boolean,
        nullable=False,
        default=False,
        comment="Whether this is a commonly used food item",
    )

    # Nutritional information (per 100g)
    calories_per_100g = Column(Float, nullable=True, comment="Calories per 100g")
    protein_per_100g = Column(
        Float, nullable=True, comment="Protein content per 100g (g)"
    )
    carbs_per_100g = Column(
        Float, nullable=True, comment="Carbohydrate content per 100g (g)"
    )
    fat_per_100g = Column(Float, nullable=True, comment="Fat content per 100g (g)")
    fiber_per_100g = Column(Float, nullable=True, comment="Fiber content per 100g (g)")
    sugar_per_100g = Column(Float, nullable=True, comment="Sugar content per 100g (g)")
    sodium_per_100g = Column(
        Float, nullable=True, comment="Sodium content per 100g (mg)"
    )

    # Relationships
    food_entries = relationship(
        "FoodEntry", back_populates="food", cascade="all, delete-orphan"
    )

    def __repr__(self):
        return f"<Food(id={self.id}, name='{self.name}')>"
