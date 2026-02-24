from __future__ import annotations

from typing import List
from uuid import UUID

from fastapi import Depends, HTTPException, status
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_async_db, get_current_admin_user
from app.api.routing import StrictAPIRouter
from app.db.models.a2a_proxy_allowlist import A2AProxyAllowlist
from app.db.models.user import User
from app.schemas.a2a_proxy_allowlist import (
    A2AProxyAllowlistCreate,
    A2AProxyAllowlistResponse,
    A2AProxyAllowlistUpdate,
)
from app.services.a2a_proxy_service import a2a_proxy_service

router = StrictAPIRouter(prefix="/admin/proxy/allowlist", tags=["admin"])


@router.get("", response_model=List[A2AProxyAllowlistResponse])
async def list_proxy_allowlist(
    db: AsyncSession = Depends(get_async_db),
    _: User = Depends(get_current_admin_user),
):
    stmt = select(A2AProxyAllowlist).order_by(A2AProxyAllowlist.host_pattern)
    result = await db.execute(stmt)
    return result.scalars().all()


@router.post("", response_model=A2AProxyAllowlistResponse, status_code=status.HTTP_201_CREATED)
async def create_proxy_allowlist_entry(
    payload: A2AProxyAllowlistCreate,
    db: AsyncSession = Depends(get_async_db),
    _: User = Depends(get_current_admin_user),
):
    # Check if already exists
    stmt = select(A2AProxyAllowlist).where(A2AProxyAllowlist.host_pattern == payload.host_pattern)
    existing = await db.execute(stmt)
    if existing.scalars().first():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Host pattern '{payload.host_pattern}' already exists",
        )

    entry = A2AProxyAllowlist(**payload.model_dump())
    db.add(entry)
    await db.commit()
    await db.refresh(entry)
    
    # Refresh cache
    await a2a_proxy_service.refresh_cache(db)
    
    return entry


@router.patch("/{entry_id}", response_model=A2AProxyAllowlistResponse)
async def update_proxy_allowlist_entry(
    entry_id: UUID,
    payload: A2AProxyAllowlistUpdate,
    db: AsyncSession = Depends(get_async_db),
    _: User = Depends(get_current_admin_user),
):
    stmt = select(A2AProxyAllowlist).where(A2AProxyAllowlist.id == entry_id)
    result = await db.execute(stmt)
    entry = result.scalars().first()
    if not entry:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Entry not found")

    update_data = payload.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(entry, key, value)

    await db.commit()
    await db.refresh(entry)
    
    # Refresh cache
    await a2a_proxy_service.refresh_cache(db)
    
    return entry


@router.delete("/{entry_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_proxy_allowlist_entry(
    entry_id: UUID,
    db: AsyncSession = Depends(get_async_db),
    _: User = Depends(get_current_admin_user),
):
    stmt = delete(A2AProxyAllowlist).where(A2AProxyAllowlist.id == entry_id)
    result = await db.execute(stmt)
    if result.rowcount == 0:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Entry not found")

    await db.commit()
    
    # Refresh cache
    await a2a_proxy_service.refresh_cache(db)
    
    return None
