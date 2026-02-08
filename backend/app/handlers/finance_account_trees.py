"""Finance account tree handlers."""

from __future__ import annotations

from typing import List, Optional
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.finance_accounts import FinanceAccount, FinanceAccountTree
from app.db.models.finance_balance_snapshots import FinanceSnapshot
from app.db.transaction import commit_safely
from app.handlers.finance_common import (
    FinanceTreeDeleteForbiddenError,
    FinanceTreeNameConflictError,
    FinanceTreeNotEmptyError,
    FinanceTreeNotFoundError,
)
from app.utils.timezone_util import utc_now

DEFAULT_TREE_NAME = "Default"


async def _load_tree(
    db: AsyncSession,
    user_id: UUID,
    tree_id: UUID,
    *,
    with_for_update: bool = False,
) -> Optional[FinanceAccountTree]:
    stmt = (
        select(FinanceAccountTree)
        .where(
            FinanceAccountTree.id == tree_id,
            FinanceAccountTree.user_id == user_id,
            FinanceAccountTree.deleted_at.is_(None),
        )
        .limit(1)
    )
    if with_for_update:
        stmt = stmt.with_for_update()
    return (await db.execute(stmt)).scalars().first()


async def _assert_tree_name_available(
    db: AsyncSession,
    user_id: UUID,
    name: str,
    *,
    exclude_tree_id: Optional[UUID] = None,
) -> None:
    stmt = (
        select(func.count())
        .select_from(FinanceAccountTree)
        .where(
            FinanceAccountTree.user_id == user_id,
            FinanceAccountTree.deleted_at.is_(None),
            FinanceAccountTree.name == name,
        )
    )
    if exclude_tree_id:
        stmt = stmt.where(FinanceAccountTree.id != exclude_tree_id)
    exists = (await db.execute(stmt)).scalar_one()
    if exists:
        raise FinanceTreeNameConflictError("同名账户树已存在")


async def _next_display_order(db: AsyncSession, user_id: UUID) -> int:
    stmt = (
        select(func.coalesce(func.max(FinanceAccountTree.display_order), 0))
        .where(
            FinanceAccountTree.user_id == user_id,
            FinanceAccountTree.deleted_at.is_(None),
        )
        .limit(1)
    )
    value = (await db.execute(stmt)).scalar_one() or 0
    return value + 1


async def _list_trees(db: AsyncSession, user_id: UUID) -> List[FinanceAccountTree]:
    stmt = (
        select(FinanceAccountTree)
        .where(
            FinanceAccountTree.user_id == user_id,
            FinanceAccountTree.deleted_at.is_(None),
        )
        .order_by(
            FinanceAccountTree.is_default.desc(),
            FinanceAccountTree.display_order.is_(None),
            FinanceAccountTree.display_order,
            FinanceAccountTree.name,
        )
    )
    return (await db.execute(stmt)).scalars().all()


async def ensure_default_account_tree(
    db: AsyncSession,
    user_id: UUID,
) -> FinanceAccountTree:
    trees = await _list_trees(db, user_id)
    if not trees:
        tree = FinanceAccountTree(
            user_id=user_id,
            name=DEFAULT_TREE_NAME,
            is_default=True,
            display_order=1,
        )
        db.add(tree)
        await commit_safely(db)
        await db.refresh(tree)
        return tree

    default_tree = next((tree for tree in trees if tree.is_default), None)
    if default_tree:
        return default_tree

    fallback = trees[0]
    fallback.is_default = True
    await commit_safely(db)
    await db.refresh(fallback)
    return fallback


async def resolve_account_tree(
    db: AsyncSession,
    user_id: UUID,
    tree_id: Optional[UUID],
) -> FinanceAccountTree:
    if tree_id:
        tree = await _load_tree(db, user_id, tree_id)
        if not tree:
            raise FinanceTreeNotFoundError("账户树不存在")
        return tree
    return await ensure_default_account_tree(db, user_id)


async def list_account_trees(
    db: AsyncSession,
    user_id: UUID,
) -> List[FinanceAccountTree]:
    tree = await ensure_default_account_tree(db, user_id)
    trees = await _list_trees(db, user_id)
    if not trees:
        return [tree]
    return trees


async def create_account_tree(
    db: AsyncSession,
    user_id: UUID,
    *,
    name: str,
    is_default: bool = False,
    display_order: Optional[int] = None,
) -> FinanceAccountTree:
    normalized_name = name.strip()
    if not normalized_name:
        raise FinanceTreeNameConflictError("账户树名称不能为空")
    await _assert_tree_name_available(db, user_id, normalized_name)

    if display_order is None:
        display_order = await _next_display_order(db, user_id)

    tree = FinanceAccountTree(
        user_id=user_id,
        name=normalized_name,
        is_default=bool(is_default),
        display_order=display_order,
    )
    if tree.is_default:
        await _unset_default(db, user_id, exclude_tree_id=None)
    db.add(tree)
    await commit_safely(db)
    await db.refresh(tree)
    return tree


async def _unset_default(
    db: AsyncSession,
    user_id: UUID,
    *,
    exclude_tree_id: Optional[UUID],
) -> None:
    stmt = (
        select(FinanceAccountTree)
        .where(
            FinanceAccountTree.user_id == user_id,
            FinanceAccountTree.deleted_at.is_(None),
        )
        .with_for_update()
    )
    trees = (await db.execute(stmt)).scalars().all()
    for tree in trees:
        if exclude_tree_id and tree.id == exclude_tree_id:
            continue
        if tree.is_default:
            tree.is_default = False


async def update_account_tree(
    db: AsyncSession,
    user_id: UUID,
    tree_id: UUID,
    *,
    name: Optional[str] = None,
    is_default: Optional[bool] = None,
    display_order: Optional[int] = None,
) -> FinanceAccountTree:
    tree = await _load_tree(db, user_id, tree_id, with_for_update=True)
    if not tree:
        raise FinanceTreeNotFoundError("账户树不存在")

    if name is not None:
        normalized_name = name.strip()
        if not normalized_name:
            raise FinanceTreeNameConflictError("账户树名称不能为空")
        if normalized_name != tree.name:
            await _assert_tree_name_available(
                db, user_id, normalized_name, exclude_tree_id=tree.id
            )
            tree.name = normalized_name

    if display_order is not None:
        tree.display_order = display_order

    if is_default is True:
        await _unset_default(db, user_id, exclude_tree_id=tree.id)
        tree.is_default = True
    elif is_default is False:
        tree.is_default = False

    await commit_safely(db)
    await db.refresh(tree)
    return tree


async def delete_account_tree(
    db: AsyncSession,
    user_id: UUID,
    tree_id: UUID,
) -> None:
    tree = await _load_tree(db, user_id, tree_id, with_for_update=True)
    if not tree:
        raise FinanceTreeNotFoundError("账户树不存在")

    tree_count_stmt = (
        select(func.count())
        .select_from(FinanceAccountTree)
        .where(
            FinanceAccountTree.user_id == user_id,
            FinanceAccountTree.deleted_at.is_(None),
        )
    )
    tree_count = (await db.execute(tree_count_stmt)).scalar_one() or 0
    if tree_count <= 1:
        raise FinanceTreeDeleteForbiddenError("至少保留一个账户树")

    accounts_stmt = (
        select(func.count())
        .select_from(FinanceAccount)
        .where(
            FinanceAccount.user_id == user_id,
            FinanceAccount.tree_id == tree_id,
            FinanceAccount.deleted_at.is_(None),
        )
    )
    if (await db.execute(accounts_stmt)).scalar_one():
        raise FinanceTreeNotEmptyError("账户树下仍有账户")

    snapshots_stmt = (
        select(func.count())
        .select_from(FinanceSnapshot)
        .where(
            FinanceSnapshot.user_id == user_id,
            FinanceSnapshot.tree_id == tree_id,
            FinanceSnapshot.deleted_at.is_(None),
        )
    )
    if (await db.execute(snapshots_stmt)).scalar_one():
        raise FinanceTreeNotEmptyError("账户树下仍有快照")

    tree.deleted_at = utc_now()

    if tree.is_default:
        fallback_stmt = (
            select(FinanceAccountTree)
            .where(
                FinanceAccountTree.user_id == user_id,
                FinanceAccountTree.deleted_at.is_(None),
                FinanceAccountTree.id != tree.id,
            )
            .order_by(
                FinanceAccountTree.display_order.is_(None),
                FinanceAccountTree.display_order,
                FinanceAccountTree.created_at.asc(),
            )
            .limit(1)
        )
        fallback = (await db.execute(fallback_stmt)).scalars().first()
        if fallback:
            fallback.is_default = True

    await commit_safely(db)


__all__ = [
    "DEFAULT_TREE_NAME",
    "create_account_tree",
    "delete_account_tree",
    "ensure_default_account_tree",
    "list_account_trees",
    "resolve_account_tree",
    "update_account_tree",
]
