"""Finance account API routes."""

from __future__ import annotations

from uuid import UUID

from fastapi import Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_async_db, get_current_user
from app.api.routing import StrictAPIRouter
from app.core.config import settings
from app.db.models.user import User
from app.handlers import finance_account_trees as account_tree_service
from app.handlers import finance_accounts as account_service
from app.handlers.finance_common import (
    FinanceAccountNameConflictError,
    FinanceAccountNotFoundError,
    FinanceParentNotAllowedError,
    FinanceTreeDeleteForbiddenError,
    FinanceTreeNameConflictError,
    FinanceTreeNotEmptyError,
    FinanceTreeNotFoundError,
)
from app.handlers.user_preferences import get_finance_primary_currency
from app.schemas.finance_accounts import (
    FinanceAccountCreate,
    FinanceAccountNode,
    FinanceAccountTreeCreate,
    FinanceAccountTreeItem,
    FinanceAccountTreeResponse,
    FinanceAccountTreeUpdate,
    FinanceAccountUpdate,
)

router = StrictAPIRouter(prefix="/finance/accounts", tags=["finance-accounts"])
collection_router = StrictAPIRouter(tags=["finance-accounts"])
resource_router = StrictAPIRouter(
    prefix="/{account_id:uuid}", tags=["finance-accounts"]
)


@collection_router.get("/tree", response_model=FinanceAccountTreeResponse)
async def get_finance_account_tree(
    tree_id: UUID | None = Query(None),
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
) -> FinanceAccountTreeResponse:
    tree, accounts, latest_snapshot, entry_map = await account_service.get_account_tree(
        db, current_user.id, tree_id=tree_id
    )
    nodes_raw = account_service.build_account_tree_response(
        accounts, latest_snapshot, entry_map
    )
    primary_currency = await get_finance_primary_currency(db, user_id=current_user.id)

    return FinanceAccountTreeResponse(
        tree_id=tree.id,
        accounts=[FinanceAccountNode.model_validate(node) for node in nodes_raw],
        latest_snapshot_id=latest_snapshot.id if latest_snapshot else None,
        latest_snapshot_ts=(
            latest_snapshot.snapshot_ts.isoformat() if latest_snapshot else None
        ),
        primary_currency=primary_currency,
    )


@collection_router.post(
    "/", response_model=FinanceAccountNode, status_code=status.HTTP_201_CREATED
)
async def create_finance_account(
    payload: FinanceAccountCreate,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
) -> FinanceAccountNode:
    try:
        account = await account_service.create_account(
            db,
            current_user.id,
            name=payload.name,
            parent_id=payload.parent_id,
            tree_id=payload.tree_id,
            type=payload.type,
            nature=payload.nature,
            currency_code=payload.currency_code,
            interest_rate=payload.interest_rate,
            metadata=payload.metadata,
            sort_order=payload.sort_order,
        )
    except FinanceParentNotAllowedError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except FinanceAccountNameConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except FinanceTreeNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:  # pragma: no cover - safety net
        if settings.debug:
            raise
        raise HTTPException(status_code=500, detail="Failed to create account") from exc

    nodes_raw = account_service.build_account_tree_response([account], None, {})
    return FinanceAccountNode.model_validate(nodes_raw[0])


@resource_router.patch("", response_model=FinanceAccountNode)
async def update_finance_account(
    account_id: UUID,
    payload: FinanceAccountUpdate,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
) -> FinanceAccountNode:
    try:
        account = await account_service.update_account(
            db,
            current_user.id,
            account_id,
            name=payload.name,
            parent_id=payload.parent_id,
            type=payload.type,
            nature=payload.nature,
            currency_code=payload.currency_code,
            interest_rate=payload.interest_rate,
            metadata=payload.metadata,
            sort_order=payload.sort_order,
        )
    except FinanceAccountNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except FinanceParentNotAllowedError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except FinanceAccountNameConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except Exception as exc:  # pragma: no cover
        if settings.debug:
            raise
        raise HTTPException(status_code=500, detail="Failed to update account") from exc

    nodes_raw = account_service.build_account_tree_response([account], None, {})
    return FinanceAccountNode.model_validate(nodes_raw[0])


@resource_router.delete("", status_code=status.HTTP_204_NO_CONTENT)
async def delete_finance_account(
    account_id: UUID,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
) -> None:
    try:
        await account_service.delete_account(db, current_user.id, account_id)
    except FinanceAccountNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:  # pragma: no cover
        if settings.debug:
            raise
        raise HTTPException(status_code=500, detail="Failed to delete account") from exc


@collection_router.get("/trees", response_model=list[FinanceAccountTreeItem])
async def list_finance_account_trees(
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
) -> list[FinanceAccountTreeItem]:
    trees = await account_tree_service.list_account_trees(db, current_user.id)
    return [FinanceAccountTreeItem.model_validate(tree) for tree in trees]


@collection_router.post(
    "/trees",
    response_model=FinanceAccountTreeItem,
    status_code=status.HTTP_201_CREATED,
)
async def create_finance_account_tree(
    payload: FinanceAccountTreeCreate,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
) -> FinanceAccountTreeItem:
    try:
        tree = await account_tree_service.create_account_tree(
            db,
            current_user.id,
            name=payload.name,
            is_default=bool(payload.is_default),
            display_order=payload.display_order,
        )
    except FinanceTreeNameConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return FinanceAccountTreeItem.model_validate(tree)


@collection_router.patch("/trees/{tree_id}", response_model=FinanceAccountTreeItem)
async def update_finance_account_tree(
    tree_id: UUID,
    payload: FinanceAccountTreeUpdate,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
) -> FinanceAccountTreeItem:
    try:
        tree = await account_tree_service.update_account_tree(
            db,
            current_user.id,
            tree_id,
            name=payload.name,
            is_default=payload.is_default,
            display_order=payload.display_order,
        )
    except FinanceTreeNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except FinanceTreeNameConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return FinanceAccountTreeItem.model_validate(tree)


@collection_router.delete("/trees/{tree_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_finance_account_tree(
    tree_id: UUID,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
) -> None:
    try:
        await account_tree_service.delete_account_tree(
            db,
            current_user.id,
            tree_id,
        )
    except FinanceTreeNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except (FinanceTreeNotEmptyError, FinanceTreeDeleteForbiddenError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))


router.include_router(collection_router)
router.include_router(resource_router)

__all__ = ["router"]
