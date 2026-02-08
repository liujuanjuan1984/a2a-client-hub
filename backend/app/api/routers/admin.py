"""
Admin maintenance endpoints (protected in deployment).
"""

from typing import Any, Dict
from uuid import UUID

from fastapi import Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_async_db, get_current_admin_user
from app.api.routing import StrictAPIRouter
from app.handlers import admin as admin_handler

router = StrictAPIRouter(
    prefix="/admin/maintenance",
    tags=["admin-maintenance"],
    dependencies=[Depends(get_current_admin_user)],
)


@router.post("/recompute/vision/{vision_id}")
async def recompute_vision_efforts(
    vision_id: UUID, db: AsyncSession = Depends(get_async_db)
) -> Any:
    try:
        root_ids = await admin_handler.recompute_vision_efforts(db, vision_id=vision_id)
    except admin_handler.ResourceNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc

    return {"vision_id": vision_id, "recomputed_roots": list(root_ids)}


@router.post("/recompute/task/{task_id}")
async def recompute_task_efforts(
    task_id: UUID, db: AsyncSession = Depends(get_async_db)
) -> Dict[str, Any]:
    try:
        await admin_handler.recompute_task_efforts(db, task_id=task_id)
    except admin_handler.ResourceNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc

    return {"task_id": task_id, "status": "ok"}

