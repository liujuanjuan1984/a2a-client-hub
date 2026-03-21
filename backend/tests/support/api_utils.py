from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator, Callable, Dict, Optional

import httpx
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api import deps


@asynccontextmanager
async def create_test_client(
    router,
    *,
    async_session_maker: async_sessionmaker[AsyncSession],
    current_user=None,
    db_session: AsyncSession | None = None,
    overrides: Optional[Dict[Callable, Callable]] = None,
    base_prefix: Optional[str] = None,
) -> AsyncIterator[httpx.AsyncClient]:
    """FastAPI TestClient replacement backed by httpx + ASGI transport."""

    app = FastAPI()
    prefix = base_prefix or ""
    app.include_router(router, prefix=prefix)

    async def override_get_db():
        if db_session is not None:
            yield db_session
            return
        async with async_session_maker() as session:
            yield session

    app.dependency_overrides[deps.get_async_db] = override_get_db

    if current_user is not None:

        async def override_get_current_user():
            return current_user

        app.dependency_overrides[deps.get_current_user] = override_get_current_user

    if overrides:
        for dependency, implementation in overrides.items():
            app.dependency_overrides[dependency] = implementation

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",
    ) as client:
        yield client

    app.dependency_overrides.clear()
