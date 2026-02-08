"""
Person utility functions

This module contains shared utility functions for working with Person objects
across different API routers.
"""

from typing import List

from app.db.models.person import Person
from app.schemas.person import PersonSummaryResponse
from app.schemas.tag import TagResponse


def convert_persons_to_summary(persons: List[Person]) -> List[PersonSummaryResponse]:
    """
    Convert Person objects to PersonSummaryResponse objects

    Args:
        persons: List of Person objects

    Returns:
        List of PersonSummaryResponse objects
    """
    person_summaries = []
    for person in persons:
        try:
            # Ensure tags are loaded
            if not hasattr(person, "_tags_loaded"):
                person.tags  # This will trigger lazy loading

            summary = PersonSummaryResponse(
                id=person.id,
                name=person.name,
                display_name=person.display_name,
                primary_nickname=person.get_primary_nickname(),
                birth_date=person.birth_date,
                location=person.location,
                tags=[
                    TagResponse(
                        id=tag.id,
                        name=tag.name,
                        entity_type=tag.entity_type,
                        category=getattr(tag, "category", "general"),
                        description=tag.description,
                        color=tag.color,
                        created_at=tag.created_at,
                        updated_at=tag.updated_at,
                    )
                    for tag in person.tags
                ],
            )
            person_summaries.append(summary)
        except Exception:
            # Fallback: create summary without tags if there's an error
            summary = PersonSummaryResponse(
                id=person.id,
                name=person.name,
                display_name=person.display_name,
                primary_nickname=person.get_primary_nickname(),
                birth_date=person.birth_date,
                location=person.location,
                tags=[],
            )
            person_summaries.append(summary)
    return person_summaries
