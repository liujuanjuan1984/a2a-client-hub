#!/usr/bin/env python
"""管理员批量为指定用户导入笔记的小工具。

主要能力：
1. 校验目标用户是否存在且未被删除；
2. 如果该用户缺少目标标签，则先创建该标签；
3. 解析输入文件中的多条笔记内容，为每条笔记补齐标签后写入数据库；
4. 提供 dry-run 预览模式与错误统计，方便先验证数据。

支持的输入格式：
- JSON / JSON 数组 / 带 "notes" 键的 JSON 对象；
- JSON Lines（每行一条 JSON）；
- 纯文本（以至少一个空行分隔的段落）。
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple
from uuid import UUID

try:  # noqa: SIM105 - 需要兼容缺失 python-dotenv 的环境
    from dotenv import load_dotenv
except ModuleNotFoundError:
    def load_dotenv(dotenv_path, override=False):  # type: ignore[override]
        """退化版的 .env 解析器，避免额外依赖。"""

        path = Path(dotenv_path)
        if not path.exists():
            return False

        try:
            content = path.read_text(encoding="utf-8")
        except OSError:
            return False

        for raw_line in content.splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if not key:
                continue
            if key in os.environ and not override:
                continue
            os.environ[key] = value
        return True

try:
    from pydantic import ValidationError
except ModuleNotFoundError as exc:  # pragma: no cover - 只在缺依赖时触发
    raise SystemExit("缺少依赖 pydantic，请先安装 backend/pyproject.toml 中列出的依赖。") from exc

try:
    from sqlalchemy import func
    from sqlalchemy.exc import SQLAlchemyError
except ModuleNotFoundError as exc:  # pragma: no cover - 只在缺依赖时触发
    raise SystemExit("缺少依赖 SQLAlchemy，请先安装 backend/pyproject.toml 中列出的依赖。") from exc


def _bootstrap_environment() -> None:
    """把 repo 根目录和 backend 加入 sys.path，并加载 .env。"""

    script_path = Path(__file__).resolve()
    repo_root = script_path.parent.parent
    backend_dir = repo_root / "backend"

    for path in (repo_root, backend_dir):
        str_path = str(path)
        if str_path not in sys.path:
            sys.path.insert(0, str_path)

    for env_path in (repo_root / ".env", backend_dir / ".env"):
        if env_path.exists():
            load_dotenv(env_path, override=False)


_bootstrap_environment()

try:
    from sqlalchemy.ext.asyncio import AsyncSession  # noqa: E402

    from app.db.models.tag import Tag  # noqa: E402  (路径在 _bootstrap_environment 中注入)
    from app.db.models.user import User  # noqa: E402
    from app.db.session import AsyncSessionLocal, SessionLocal  # noqa: E402
    from app.handlers import tags as tag_service  # noqa: E402
    from app.handlers.notes_async import create_note as create_note_async  # noqa: E402
    from app.schemas.note import NoteCreate  # noqa: E402
    from app.schemas.tag import TagCreate  # noqa: E402
except ModuleNotFoundError as exc:  # pragma: no cover - 只在路径未配置时触发
    raise SystemExit(
        "无法导入 backend 模块。请在仓库根目录使用 `poetry shell` 或激活虚拟环境后再运行此脚本。"
    ) from exc


@dataclass
class NoteImportStats:
    """记录执行过程中的计数信息。"""

    total: int = 0
    created: int = 0
    skipped: int = 0
    failed: int = 0
    failures: List[Tuple[int, str]] = None

    def __post_init__(self) -> None:
        if self.failures is None:
            self.failures = []


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="为指定用户批量导入笔记并自动附加标签",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--user-id", help="目标用户 UUID")
    parser.add_argument("--user-email", help="目标用户邮箱，可替代 --user-id")
    parser.add_argument("--tag-name", required=True, help="需要确保存在的标签名称")
    parser.add_argument("--input-file", required=True, help="包含笔记内容的数据文件")
    parser.add_argument("--tag-description", help="可选的标签描述")
    parser.add_argument("--tag-color", help="可选的标签颜色（#000000 形式）")
    parser.add_argument(
        "--encoding",
        default="utf-8",
        help="输入文件编码（纯文本模式会按该编码读取）",
    )
    parser.add_argument(
        "--max-count",
        type=int,
        help="只导入前 N 条记录，便于小批量验证",
    )
    parser.add_argument(
        "--continue-on-error",
        action="store_true",
        help="出现验证/写入错误时继续处理后续记录",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只解析并打印计划写入的笔记，不触发任何数据库写操作",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="输出更详细的调试日志",
    )
    return parser.parse_args()


def configure_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s | %(levelname)s | %(message)s",
    )


def parse_uuid(value: str) -> UUID:
    try:
        return UUID(value)
    except ValueError as exc:
        raise SystemExit(f"无法解析 user-id '{value}': {exc}") from exc


def load_notes_from_file(path: Path, encoding: str) -> List[Dict[str, Any]]:
    """根据文件内容返回标准化的笔记负载列表。"""

    if not path.exists():
        raise FileNotFoundError(f"找不到输入文件: {path}")

    raw_text = path.read_text(encoding=encoding)
    if not raw_text.strip():
        raise ValueError("输入文件为空")

    json_data = _try_parse_json(raw_text)
    if json_data is not None:
        return _normalize_json_entries(json_data)

    json_lines = _try_parse_json_lines(raw_text)
    if json_lines is not None:
        return _normalize_json_entries(json_lines)

    return _parse_plain_text(raw_text)


def _try_parse_json(raw_text: str) -> Optional[Any]:
    try:
        return json.loads(raw_text)
    except json.JSONDecodeError:
        return None


def _try_parse_json_lines(raw_text: str) -> Optional[List[Any]]:
    entries: List[Any] = []
    for line in raw_text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        try:
            entries.append(json.loads(stripped))
        except json.JSONDecodeError:
            return None
    return entries if entries else None


def _normalize_json_entries(data: Any) -> List[Dict[str, Any]]:
    if isinstance(data, dict):
        if "notes" not in data:
            raise ValueError("JSON 对象缺少 'notes' 键")
        data = data["notes"]
    if not isinstance(data, list):
        raise ValueError("JSON 数据必须是数组或包含 notes 数组的对象")

    normalized: List[Dict[str, Any]] = []
    for idx, item in enumerate(data, start=1):
        normalized.append(_normalize_single_entry(item, idx))
    return normalized


def _parse_plain_text(raw_text: str) -> List[Dict[str, Any]]:
    separator_pattern = r"(?:\r?\n\s*){3,}"
    blocks = [block.strip() for block in re.split(separator_pattern, raw_text) if block.strip()]
    if not blocks:
        fallback = raw_text.strip()
        if not fallback:
            raise ValueError("纯文本模式输入为空，请提供内容")
        blocks = [fallback]
    return [{"content": block} for block in blocks]


def _normalize_single_entry(item: Any, idx: int) -> Dict[str, Any]:
    if isinstance(item, str):
        content = item.strip()
        if not content:
            raise ValueError(f"第 {idx} 条记录内容为空")
        return {"content": content}

    if isinstance(item, dict):
        content_value = item.get("content")
        if content_value is None:
            raise ValueError(f"第 {idx} 条记录缺少 content 字段")
        content = str(content_value).strip()
        if not content:
            raise ValueError(f"第 {idx} 条记录的 content 为空")
        normalized = dict(item)
        normalized["content"] = content
        return normalized

    raise ValueError(f"第 {idx} 条记录的类型不受支持: {type(item).__name__}")


def fetch_active_user(
    session,
    *,
    user_id: Optional[UUID],
    user_email: Optional[str],
) -> User:
    if user_id is None and not user_email:
        raise SystemExit("必须提供 --user-id 或 --user-email 之一")

    query = User.active(session)
    user: Optional[User] = None

    if user_id is not None:
        user = query.filter(User.id == user_id).first()
        if not user:
            raise SystemExit(f"未找到 user_id={user_id} 对应的有效用户")
        if user_email and user.email.strip().lower() != user_email.strip().lower():
            raise SystemExit(
                "提供的 user-id 与 user-email 不匹配，请确认输入。"
            )
        return user

    assert user_email is not None  # for mypy-like tools
    normalized_email = user_email.strip().lower()
    user = (
        query.filter(func.lower(User.email) == normalized_email)
        .first()
    )
    if not user:
        raise SystemExit(f"未找到 email={user_email} 对应的有效用户")
    logging.info("根据邮箱 %s 找到用户 ID: %s", user_email, user.id)
    return user


async def ensure_note_tag(
    session: AsyncSession,
    user_id: UUID,
    *,
    name: str,
    description: Optional[str],
    color: Optional[str],
    dry_run: bool,
) -> Tuple[Optional[Tag], str, bool]:
    """确保标签存在；dry-run 下不写库，仅返回占位 ID。"""

    trimmed_name = name.strip()
    if not trimmed_name:
        raise SystemExit("标签名称不能为空")
    lookup_name = trimmed_name.lower()
    existing = (
        Tag.active(session)
        .filter(
            Tag.user_id == user_id,
            func.lower(Tag.name) == lookup_name,
            Tag.entity_type == "note",
        )
        .first()
    )
    if existing:
        return existing, str(existing.id), False

    if dry_run:
        placeholder = f"pending-tag::{lookup_name}"
        logging.info("[dry-run] 标签 '%s' 不存在，正式执行时会自动创建", trimmed_name)
        return None, placeholder, True

    logging.info("标签 '%s' 不存在，正在创建……", trimmed_name)
    try:
        tag_data = TagCreate(
            name=trimmed_name,
            entity_type="note",
            description=description,
            color=color,
        )
    except ValidationError as exc:
        raise SystemExit(f"标签参数校验失败: {exc}") from exc
    tag = await tag_service.create_tag(session, user_id=user_id, tag_in=tag_data)
    logging.info("标签创建完成，id=%s", tag.id)
    return tag, str(tag.id), True


def merge_tag_ids(original: Optional[Sequence[Any]], required_tag_id: str) -> List[str]:
    merged: List[str] = []
    if original:
        for item in original:
            if item is None:
                continue
            text = str(item).strip()
            if not text:
                continue
            if text not in merged:
                merged.append(text)
    if required_tag_id not in merged:
        merged.append(required_tag_id)
    return merged


async def create_notes(
    session: AsyncSession,
    user_id: UUID,
    entries: List[Dict[str, Any]],
    required_tag_id: str,
    *,
    dry_run: bool,
    continue_on_error: bool,
    max_count: Optional[int] = None,
) -> NoteImportStats:
    stats = NoteImportStats(total=len(entries))

    iterable = entries[: max_count or None]
    if max_count:
        stats.total = len(iterable)

    for idx, payload in enumerate(iterable, start=1):
        payload = dict(payload)
        payload["tag_ids"] = merge_tag_ids(payload.get("tag_ids"), required_tag_id)

        try:
            note_in = NoteCreate(**payload)
        except ValidationError as exc:
            stats.failed += 1
            message = f"第 {idx} 条记录未通过校验: {exc}"
            stats.failures.append((idx, message))
            logging.error(message)
            if not continue_on_error:
                break
            continue

        if dry_run:
            logging.info("[dry-run] 将创建笔记 #%d，content 摘要: %s", idx, note_in.content[:40])
            stats.skipped += 1
            continue

        try:
            note = await create_note_async(session, user_id=user_id, note_in=note_in)
        except (SQLAlchemyError, RuntimeError) as exc:
            session.rollback()
            stats.failed += 1
            message = f"第 {idx} 条记录写入失败: {exc}"
            stats.failures.append((idx, message))
            logging.exception("笔记 #%d 写入失败", idx)
            if not continue_on_error:
                break
            continue

        stats.created += 1
        logging.info("笔记 #%d 创建成功，id=%s", idx, note.id)

    return stats


def main() -> None:
    args = parse_args()
    configure_logging(args.verbose)

    raw_user_id = args.user_id.strip() if args.user_id else None
    raw_user_email = args.user_email.strip() if args.user_email else None

    if not raw_user_id and not raw_user_email:
        raise SystemExit("必须提供 --user-id 或 --user-email 之一")

    user_id_value = parse_uuid(raw_user_id) if raw_user_id else None
    user_email_value = raw_user_email
    input_path = Path(args.input_file).resolve()

    try:
        entries = load_notes_from_file(input_path, args.encoding)
    except Exception as exc:  # noqa: BLE001 - 这里需要把所有异常汇报给管理员
        raise SystemExit(f"解析输入文件失败: {exc}") from exc

    logging.info("已加载 %d 条原始记录", len(entries))

    async def _runner() -> None:
        async with AsyncSessionLocal() as async_session:
            # 获取同步 Session 仅用于 fetch_active_user（SQLAlchemy 同步模型）
            with SessionLocal() as sync_session:
                user = fetch_active_user(
                    sync_session, user_id=user_id_value, user_email=user_email_value
                )
            logging.info("目标用户: %s (%s)", user.id, user.email)

            tag, tag_id_str, created_now = await ensure_note_tag(
                async_session,
                user.id,
                name=args.tag_name,
                description=args.tag_description,
                color=args.tag_color,
                dry_run=args.dry_run,
            )

            if created_now and args.dry_run:
                logging.info("[dry-run] 标签将在实际执行时创建：%s", args.tag_name.strip())

            stats = await create_notes(
                async_session,
                user.id,
                entries,
                tag_id_str,
                dry_run=args.dry_run,
                continue_on_error=args.continue_on_error,
                max_count=args.max_count,
            )

            logging.info(
                "处理完成：total=%d, created=%d, skipped=%d, failed=%d",
                stats.total,
                stats.created,
                stats.skipped,
                stats.failed,
            )

            if stats.failures:
                logging.error("失败详情（最多列出前 10 条）：")
                for idx, (record_no, message) in enumerate(stats.failures, start=1):
                    if idx > 10:
                        logging.error("……其余 %d 条失败信息已省略", len(stats.failures) - 10)
                        break
                    logging.error("- #%d: %s", record_no, message)

    import asyncio

    asyncio.run(_runner())


if __name__ == "__main__":
    main()
