"""
数据协议工具函数

统一处理前后端数据协议中的空值问题

协议约定（统一前后端语义）：
- 字段不存在/未提供: 字段不在请求中（保持原值）
- None: 字段被明确设置为空值（用户想要清空该字段）
- "": 空字符串（通常需要转换为 None）
- []: 空列表（通常需要转换为 None）
- {}: 空字典（通常需要转换为 None）
"""

from typing import Any, Dict, Optional
from uuid import UUID


def clean_field_value(
    value: Any,
    empty_string_to_none: bool = True,
    empty_list_to_none: bool = True,
    empty_dict_to_none: bool = True,
    trim_strings: bool = True,
    preserve_none: bool = True,
) -> Any:
    """
    清理单个字段的空值。
    """
    if value is None:
        return None if preserve_none else None

    if isinstance(value, str):
        trimmed = value.strip() if trim_strings else value
        if trimmed == "" and empty_string_to_none:
            return None
        return trimmed

    if isinstance(value, list):
        if not value and empty_list_to_none:
            return None

        cleaned = []
        for item in value:
            if isinstance(item, str):
                trimmed = item.strip() if trim_strings else item
                if trimmed:
                    cleaned.append(trimmed)
            elif item is not None:
                cleaned.append(item)

        return None if not cleaned and empty_list_to_none else cleaned

    if isinstance(value, dict):
        if not value and empty_dict_to_none:
            return None
        return value

    return value


def clean_object_fields(
    obj: Dict[str, Any], field_config: Optional[Dict[str, Dict[str, Any]]] = None
) -> Dict[str, Any]:
    """
    按字段配置批量清理对象的空值。
    """
    field_config = field_config or {}
    result: Dict[str, Any] = {}

    for key, value in obj.items():
        cleaned = clean_field_value(value, **field_config.get(key, {}))
        if cleaned is not None:
            result[key] = cleaned

    return result


def validate_uuid_field(value: Any, field_name: str) -> Optional[UUID]:
    """
    验证并清理 UUID 字段。
    """
    if value is None:
        return None

    if isinstance(value, str):
        value = value.strip()
        if value == "":
            return None
        try:
            return UUID(value)
        except ValueError as exc:
            raise ValueError(
                f"Invalid UUID format for field '{field_name}': {value}"
            ) from exc

    if isinstance(value, UUID):
        return value

    raise ValueError(f"Invalid type for UUID field '{field_name}': {type(value)}")


__all__ = ["clean_field_value", "clean_object_fields", "validate_uuid_field"]
