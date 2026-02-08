"""Finance account domain handlers."""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import Dict, List, Optional, Tuple
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.finance_accounts import FinanceAccount, FinanceAccountTree
from app.db.models.finance_balance_snapshots import (
    FinanceSnapshot,
    FinanceSnapshotEntry,
)
from app.db.transaction import commit_safely
from app.handlers.finance_account_trees import resolve_account_tree
from app.handlers.finance_common import (
    SIX_PLACES,
    FinanceAccountNameConflictError,
    FinanceAccountNotFoundError,
    FinanceParentNotAllowedError,
    build_path,
    compute_depth,
    slugify,
)
from app.utils.timezone_util import utc_now


async def _ensure_unique_path(
    db: AsyncSession,
    user_id: UUID,
    tree_id: UUID,
    base_path: str,
    exclude_account_id: Optional[UUID] = None,
) -> str:
    candidate = base_path
    suffix = 1
    while True:
        stmt = (
            select(FinanceAccount.id)
            .where(
                FinanceAccount.user_id == user_id,
                FinanceAccount.tree_id == tree_id,
                FinanceAccount.path == candidate,
            )
            .limit(1)
        )
        if exclude_account_id:
            stmt = stmt.where(FinanceAccount.id != exclude_account_id)
        exists = (await db.execute(stmt)).scalar_one_or_none()
        if exists is None:
            return candidate
        suffix += 1
        candidate = f"{base_path}-{suffix}"


async def _assert_name_available(
    db: AsyncSession,
    user_id: UUID,
    tree_id: UUID,
    parent_id: Optional[UUID],
    name: str,
    exclude_account_id: Optional[UUID] = None,
) -> None:
    stmt = (
        select(FinanceAccount.id)
        .where(
            FinanceAccount.user_id == user_id,
            FinanceAccount.tree_id == tree_id,
            FinanceAccount.deleted_at.is_(None),
            FinanceAccount.name == name,
        )
        .limit(1)
    )
    if parent_id is None:
        stmt = stmt.where(FinanceAccount.parent_id.is_(None))
    else:
        stmt = stmt.where(FinanceAccount.parent_id == parent_id)
    if exclude_account_id:
        stmt = stmt.where(FinanceAccount.id != exclude_account_id)
    exists = (await db.execute(stmt)).scalar_one_or_none()
    if exists is not None:
        raise FinanceAccountNameConflictError("同一父级下已存在同名账户")


def _normalize_interest_rate(value: Optional[Decimal]) -> Optional[Decimal]:
    if value is None:
        return None
    return value.quantize(SIX_PLACES, rounding=ROUND_HALF_UP)


async def create_account(
    db: AsyncSession,
    user_id: UUID,
    *,
    name: str,
    parent_id: Optional[UUID],
    tree_id: Optional[UUID],
    type: str,
    nature: Optional[str],
    currency_code: str,
    interest_rate: Optional[Decimal],
    metadata: Optional[Dict],
    sort_order: Optional[int],
) -> FinanceAccount:
    parent: Optional[FinanceAccount] = None
    if parent_id:
        stmt = (
            select(FinanceAccount)
            .where(
                FinanceAccount.id == parent_id,
                FinanceAccount.user_id == user_id,
                FinanceAccount.deleted_at.is_(None),
            )
            .limit(1)
        )
        parent = (await db.execute(stmt)).scalars().first()
        if not parent:
            raise FinanceParentNotAllowedError("父级账户不存在")
        if tree_id and parent.tree_id != tree_id:
            raise FinanceParentNotAllowedError("不能跨账户树创建账户")
    resolved_tree = (
        parent.tree if parent else await resolve_account_tree(db, user_id, tree_id)
    )
    await _assert_name_available(
        db, user_id, resolved_tree.id, parent.id if parent else None, name
    )
    slug = slugify(name)
    base_path = build_path(parent.path if parent else None, slug)
    path = await _ensure_unique_path(db, user_id, resolved_tree.id, base_path)
    depth = compute_depth(path)

    if sort_order is None:
        sibling_query = select(
            func.coalesce(func.max(FinanceAccount.display_order), 0)
        ).where(
            FinanceAccount.user_id == user_id,
            FinanceAccount.tree_id == resolved_tree.id,
            FinanceAccount.deleted_at.is_(None),
        )
        if parent:
            sibling_query = sibling_query.where(FinanceAccount.parent_id == parent.id)
        else:
            sibling_query = sibling_query.where(FinanceAccount.parent_id.is_(None))
        sibling_value = (await db.execute(sibling_query)).scalar_one()
        sort_order = (sibling_value or 0) + 1

    account = FinanceAccount(
        user_id=user_id,
        tree_id=resolved_tree.id,
        name=name.strip(),
        parent_id=parent.id if parent else None,
        path=path,
        depth=depth,
        type=type,
        nature=nature,
        currency_code=currency_code.upper(),
        interest_rate=_normalize_interest_rate(interest_rate),
        display_order=sort_order,
        metadata_json=metadata,
    )
    db.add(account)
    await commit_safely(db)
    await db.refresh(account)
    return account


async def _validate_parent(
    db: AsyncSession,
    user_id: UUID,
    account: FinanceAccount,
    parent_id: Optional[UUID],
) -> Optional[FinanceAccount]:
    if parent_id is None:
        return None
    if parent_id == account.id:
        raise FinanceParentNotAllowedError("不能将账户设为自己的父级")
    stmt = (
        select(FinanceAccount)
        .where(
            FinanceAccount.id == parent_id,
            FinanceAccount.user_id == user_id,
            FinanceAccount.deleted_at.is_(None),
        )
        .limit(1)
    )
    parent = (await db.execute(stmt)).scalars().first()
    if not parent:
        raise FinanceParentNotAllowedError("父级账户不存在")
    if parent.tree_id != account.tree_id:
        raise FinanceParentNotAllowedError("不能跨账户树设置父级")
    if parent.path.startswith(f"{account.path}/"):
        raise FinanceParentNotAllowedError("不能移动到自己的子节点下")
    return parent


async def update_account(
    db: AsyncSession,
    user_id: UUID,
    account_id: UUID,
    *,
    name: Optional[str] = None,
    parent_id: Optional[UUID] = None,
    type: Optional[str] = None,
    nature: Optional[str] = None,
    currency_code: Optional[str] = None,
    interest_rate: Optional[Decimal] = None,
    metadata: Optional[Dict] = None,
    sort_order: Optional[int] = None,
) -> FinanceAccount:
    stmt = (
        select(FinanceAccount)
        .where(
            FinanceAccount.id == account_id,
            FinanceAccount.user_id == user_id,
            FinanceAccount.deleted_at.is_(None),
        )
        .with_for_update()
    )
    account = (await db.execute(stmt)).scalars().first()
    if not account:
        raise FinanceAccountNotFoundError("账户不存在")

    parent = account.parent
    if parent_id is not None and parent_id != account.parent_id:
        parent = await _validate_parent(db, user_id, account, parent_id)
        account.parent_id = parent.id if parent else None

    new_name = name.strip() if name is not None else account.name
    await _assert_name_available(
        db,
        user_id,
        account.tree_id,
        account.parent_id,
        new_name,
        exclude_account_id=account.id,
    )

    dirty_path = False

    if name is not None and new_name != account.name:
        account.name = new_name
        dirty_path = True
    if type is not None:
        account.type = type
    if nature is not None:
        account.nature = nature
    if currency_code is not None:
        account.currency_code = currency_code.upper()
    if interest_rate is not None:
        account.interest_rate = _normalize_interest_rate(interest_rate)
    if metadata is not None:
        account.metadata_json = metadata
    if sort_order is not None:
        account.display_order = sort_order
    if parent_id is not None:
        dirty_path = True

    if dirty_path:
        parent_path = parent.path if parent else None
        slug = slugify(account.name)
        base_path = build_path(parent_path, slug)
        new_path = await _ensure_unique_path(
            db,
            user_id,
            account.tree_id,
            base_path,
            exclude_account_id=account.id,
        )
        old_path = account.path
        account.path = new_path
        account.depth = compute_depth(new_path)
        if old_path != new_path:
            stmt = select(FinanceAccount).where(
                FinanceAccount.user_id == user_id,
                FinanceAccount.tree_id == account.tree_id,
                FinanceAccount.deleted_at.is_(None),
                FinanceAccount.path.like(f"{old_path}/%"),
            )
            descendants = (await db.execute(stmt)).scalars().all()
            for child in descendants:
                relative = child.path[len(old_path) :]
                child.path = f"{new_path}{relative}"
                child.depth = compute_depth(child.path)

    await commit_safely(db)
    await db.refresh(account)
    return account


async def delete_account(db: AsyncSession, user_id: UUID, account_id: UUID) -> None:
    stmt = (
        select(FinanceAccount)
        .where(
            FinanceAccount.id == account_id,
            FinanceAccount.user_id == user_id,
            FinanceAccount.deleted_at.is_(None),
        )
        .with_for_update()
    )
    account = (await db.execute(stmt)).scalars().first()
    if not account:
        raise FinanceAccountNotFoundError("账户不存在")

    now = utc_now()
    account.deleted_at = now
    stmt = select(FinanceAccount).where(
        FinanceAccount.user_id == user_id,
        FinanceAccount.tree_id == account.tree_id,
        FinanceAccount.deleted_at.is_(None),
        FinanceAccount.path.like(f"{account.path}/%"),
    )
    descendants = (await db.execute(stmt)).scalars().all()
    for child in descendants:
        child.deleted_at = now
    await commit_safely(db)


async def get_account_tree(
    db: AsyncSession, user_id: UUID, *, tree_id: Optional[UUID]
) -> Tuple[
    FinanceAccountTree,
    List[FinanceAccount],
    Optional[FinanceSnapshot],
    Dict[UUID, FinanceSnapshotEntry],
]:
    tree = await resolve_account_tree(db, user_id, tree_id)
    stmt_accounts = (
        select(FinanceAccount)
        .where(
            FinanceAccount.user_id == user_id,
            FinanceAccount.tree_id == tree.id,
            FinanceAccount.deleted_at.is_(None),
        )
        .order_by(
            FinanceAccount.depth,
            FinanceAccount.display_order.is_(None),
            FinanceAccount.display_order,
            FinanceAccount.name,
        )
    )
    accounts = (await db.execute(stmt_accounts)).scalars().all()
    stmt_snapshot = (
        select(FinanceSnapshot)
        .where(FinanceSnapshot.user_id == user_id)
        .where(FinanceSnapshot.tree_id == tree.id)
        .order_by(FinanceSnapshot.snapshot_ts.desc())
        .limit(1)
    )
    latest_snapshot = (await db.execute(stmt_snapshot)).scalars().first()
    entry_map: Dict[UUID, FinanceSnapshotEntry] = {}
    if latest_snapshot:
        stmt_entries = select(FinanceSnapshotEntry).where(
            FinanceSnapshotEntry.snapshot_id == latest_snapshot.id
        )
        entries = (await db.execute(stmt_entries)).scalars().all()
        entry_map = {entry.account_id: entry for entry in entries}
    return tree, accounts, latest_snapshot, entry_map


def build_account_tree_response(
    accounts: List[FinanceAccount],
    latest_snapshot: Optional[FinanceSnapshot],
    latest_entries: Dict[UUID, FinanceSnapshotEntry],
) -> List[Dict[str, object]]:
    nodes: Dict[UUID, Dict[str, object]] = {}
    roots: List[Dict[str, object]] = []

    for account in accounts:
        entry = latest_entries.get(account.id)
        node = {
            "id": account.id,
            "tree_id": account.tree_id,
            "parent_id": account.parent_id,
            "name": account.name,
            "path": account.path,
            "depth": account.depth,
            "type": account.type,
            "nature": account.nature,
            "currency_code": account.currency_code,
            "interest_rate": _normalize_interest_rate(account.interest_rate),
            "sort_order": account.display_order,
            "metadata": account.metadata_json,
            "latest_snapshot_id": latest_snapshot.id if latest_snapshot else None,
            "latest_balance_raw": entry.balance_original if entry else None,
            "latest_balance_converted": entry.balance_converted if entry else None,
            "children": [],
        }
        nodes[account.id] = node

    for account in accounts:
        node = nodes[account.id]
        if account.parent_id and account.parent_id in nodes:
            nodes[account.parent_id]["children"].append(node)
        else:
            roots.append(node)

    def sort_children(children: List[Dict[str, object]]) -> None:
        children.sort(
            key=lambda item: (
                item["sort_order"] if item["sort_order"] is not None else float("inf"),
                item["name"],
            )
        )
        for child in children:
            sort_children(child["children"])

    sort_children(roots)
    return roots


__all__ = [
    "create_account",
    "update_account",
    "delete_account",
    "get_account_tree",
    "build_account_tree_response",
]
