"""
Food Entry SQLAlchemy model

This model represents individual food diary entries recording what and when
the user ate, with portion sizes and nutritional calculations.
"""

import enum

from sqlalchemy import Column, DateTime, Enum, Float, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.db.mixins.user_filter import UserFilterMixin
from app.db.models.base import (
    SCHEMA_NAME,
    Base,
    SoftDeleteMixin,
    TimestampMixin,
    UserOwnedMixin,
)


class MealType(str, enum.Enum):
    """Enumeration of meal types"""

    BREAKFAST = "breakfast"
    LUNCH = "lunch"
    DINNER = "dinner"
    SNACK = "snack"
    OTHER = "other"


class FoodEntry(Base, UserOwnedMixin, TimestampMixin, SoftDeleteMixin, UserFilterMixin):
    """
    Food Entry model representing individual food diary entries

    Each entry records when the user ate a specific food item,
    the portion size, and calculated nutritional values.
    """

    __tablename__ = "food_entries"
    __table_args__ = ({"schema": SCHEMA_NAME},)

    # Date and time
    date = Column(
        String(10), nullable=False, index=True, comment="Date in YYYY-MM-DD format"
    )
    consumed_at = Column(
        DateTime,
        nullable=False,
        index=True,
        comment="Exact time when food was consumed",
    )
    meal_type = Column(
        Enum(
            MealType,
            values_callable=lambda e: [
                m.value for m in e
            ],  # Use enum values (lowercase) instead of names
            name="mealtype",
            schema=SCHEMA_NAME,
        ),
        nullable=False,
        default=MealType.OTHER,
        comment="Type of meal",
    )

    # Food and portion information
    food_id = Column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA_NAME}.foods.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="ID of the food item consumed",
    )
    portion_size_g = Column(Float, nullable=False, comment="Portion size in grams")
    notes = Column(
        Text, nullable=True, comment="Additional notes about this food entry"
    )

    # Calculated nutritional values (based on portion size)
    calories = Column(
        Float, nullable=True, comment="Calculated calories for this portion"
    )
    protein = Column(
        Float, nullable=True, comment="Calculated protein for this portion (g)"
    )
    carbs = Column(
        Float, nullable=True, comment="Calculated carbohydrates for this portion (g)"
    )
    fat = Column(Float, nullable=True, comment="Calculated fat for this portion (g)")
    fiber = Column(
        Float, nullable=True, comment="Calculated fiber for this portion (g)"
    )
    sugar = Column(
        Float, nullable=True, comment="Calculated sugar for this portion (g)"
    )
    sodium = Column(
        Float, nullable=True, comment="Calculated sodium for this portion (mg)"
    )

    # Relationships
    food = relationship("Food", back_populates="food_entries")

    def __repr__(self):
        return f"<FoodEntry(id={self.id}, food='{self.food.name if self.food else 'Unknown'}', date='{self.date}')>"
