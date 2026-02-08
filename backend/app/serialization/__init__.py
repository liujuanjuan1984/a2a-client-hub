"""Central serialization utilities exposed for application modules."""

from __future__ import annotations

from typing import Any, Dict, Iterable, Optional

from app.serialization.registry import (
    SerializeParams,
    SerializerRegistry,
    fallback_serialize,
)

serializer_registry = SerializerRegistry()


def register_schema(
    kind: str,
    schema_class,
    *,
    profile: str = "default",
    supports_many: bool = True,
    dump_kwargs: Optional[Dict[str, Any]] = None,
) -> None:
    """Convenience wrapper to register Pydantic schema serializers."""

    serializer_registry.register_schema(
        kind,
        schema_class,
        profile=profile,
        supports_many=supports_many,
        dump_kwargs=dump_kwargs,
    )


def register_serializer(
    kind: str,
    serializer,
    *,
    profile: str = "default",
    supports_many: bool = False,
) -> None:
    """Register custom serializer callable."""

    serializer_registry.register_callable(
        kind,
        serializer,
        profile=profile,
        supports_many=supports_many,
    )


def serialize(
    obj: Any,
    kind: str,
    *,
    profile: str = "default",
    as_dict: bool = True,
    context: Optional[Dict[str, Any]] = None,
) -> Any:
    return serializer_registry.serialize(
        obj,
        kind,
        profile=profile,
        as_dict=as_dict,
        context=context,
    )


def serialize_many(
    objs: Optional[Iterable[Any]],
    kind: str,
    *,
    profile: str = "default",
    as_dict: bool = True,
    context: Optional[Dict[str, Any]] = None,
) -> list[Any]:
    return serializer_registry.serialize_many(
        objs,
        kind,
        profile=profile,
        as_dict=as_dict,
        context=context,
    )


__all__ = [
    "SerializeParams",
    "fallback_serialize",
    "serialize",
    "serialize_many",
    "serializer_registry",
    "register_schema",
    "register_serializer",
]
