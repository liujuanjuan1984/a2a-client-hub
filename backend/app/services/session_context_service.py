"""Persist user-selected CardBox context per session."""

from __future__ import annotations

from typing import Any, Dict, List, Sequence
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.handlers import user_preferences as user_preferences_service
from app.utils.timezone_util import utc_now_iso

PREFERENCE_PREFIX = "agent.context.session"
PREFERENCE_MODULE = "agent"


class SessionContextService:
    """Store and retrieve CardBox selections for an agent session."""

    def _build_payload(self, box_ids: Sequence[int]) -> Dict[str, Any]:
        ordered = [
            {"box_id": box_id, "order": index}
            for index, box_id in enumerate(box_ids)
            if isinstance(box_id, int)
        ]
        return {
            "boxes": ordered,
            "updated_at": utc_now_iso(),
        }

    def _normalize_selection(self, pref_value: Any) -> List[Dict[str, Any]]:
        if not isinstance(pref_value, dict):
            return []
        raw_boxes = pref_value.get("boxes")
        if not isinstance(raw_boxes, list):
            return []
        results: List[Dict[str, Any]] = []
        for item in raw_boxes:
            if not isinstance(item, dict):
                continue
            box_id = item.get("box_id")
            order = item.get("order", 0)
            if isinstance(box_id, int):
                results.append({"box_id": box_id, "order": int(order)})
        results.sort(key=lambda entry: entry["order"])
        return results

    def _pref_key(self, session_id: UUID) -> str:
        return f"{PREFERENCE_PREFIX}.{session_id}"

    async def save_selection(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        session_id: UUID,
        box_ids: List[int],
    ) -> Dict[str, Any]:
        payload = self._build_payload(box_ids)
        await user_preferences_service.set_preference_value(
            db,
            user_id=user_id,
            key=self._pref_key(session_id),
            value=payload,
            module=PREFERENCE_MODULE,
        )
        return payload

    async def load_selection(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        session_id: UUID,
    ) -> List[Dict[str, Any]]:
        pref = await user_preferences_service.get_preference_by_key(
            db,
            user_id=user_id,
            key=self._pref_key(session_id),
        )
        if pref is None or not pref.value:
            return []
        return self._normalize_selection(pref.value)


session_context_service = SessionContextService()

__all__ = ["SessionContextService", "session_context_service"]
