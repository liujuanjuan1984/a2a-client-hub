"""Serialization registry to centralize entity-to-dict conversion logic."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time
from decimal import Decimal
from typing import Any, Callable, Dict, Iterable, Optional, Type
from uuid import UUID

from pydantic import BaseModel

SerializerFunc = Callable[[Any, "SerializeParams"], Any]


@dataclass
class SerializeParams:
    """Run-time parameters passed to serializer callables."""

    profile: str = "default"
    as_dict: bool = True
    context: Optional[Dict[str, Any]] = None


@dataclass
class RegisteredSerializer:
    """Wrapper storing a serializer callable and optional metadata."""

    func: SerializerFunc
    supports_many: bool = False


class SerializerRegistry:
    """Registry mapping logical entity kinds to serializer implementations."""

    def __init__(self) -> None:
        self._registry: Dict[str, Dict[str, RegisteredSerializer]] = {}

    # ------------------------------------------------------------------
    # Registration API
    # ------------------------------------------------------------------
    def register_schema(
        self,
        kind: str,
        schema_class: Type[BaseModel],
        *,
        profile: str = "default",
        supports_many: bool = True,
        dump_kwargs: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Register a serializer backed by a Pydantic schema class."""

        dump_kwargs = dump_kwargs or {"mode": "json"}

        def _serialize_instance(instance: Any, params: SerializeParams) -> Any:
            try:
                if isinstance(instance, schema_class):
                    schema_instance = instance
                elif isinstance(instance, BaseModel):
                    schema_instance = schema_class.model_validate(
                        instance.model_dump(mode="python")
                    )
                else:
                    schema_instance = schema_class.model_validate(instance)
            except Exception:
                return fallback_serialize(instance, params)

            return schema_instance.model_dump(**dump_kwargs)

        def serializer(obj: Any, params: SerializeParams) -> Any:
            if obj is None:
                return None
            if params.as_dict:
                return _serialize_instance(obj, params)
            return (
                schema_class.model_validate(obj)
                if not isinstance(obj, schema_class)
                else obj
            )

        self.register_callable(
            kind,
            serializer,
            profile=profile,
            supports_many=supports_many,
        )

    def register_callable(
        self,
        kind: str,
        serializer: SerializerFunc,
        *,
        profile: str = "default",
        supports_many: bool = False,
    ) -> None:
        """Register a custom serializer callable."""

        profile_map = self._registry.setdefault(kind, {})
        profile_map[profile] = RegisteredSerializer(
            func=serializer,
            supports_many=supports_many,
        )

    # ------------------------------------------------------------------
    # Serialization API
    # ------------------------------------------------------------------
    def serialize(
        self,
        obj: Any,
        kind: str,
        *,
        profile: str = "default",
        as_dict: bool = True,
        context: Optional[Dict[str, Any]] = None,
    ) -> Any:
        params = SerializeParams(profile=profile, as_dict=as_dict, context=context)
        serializer = self._resolve(kind, profile)
        return serializer.func(obj, params)

    def serialize_many(
        self,
        objs: Optional[Iterable[Any]],
        kind: str,
        *,
        profile: str = "default",
        as_dict: bool = True,
        context: Optional[Dict[str, Any]] = None,
    ) -> list[Any]:
        serializer = self._resolve(kind, profile)
        if objs is None:
            return []
        if not serializer.supports_many:
            return [
                serializer.func(
                    obj,
                    SerializeParams(profile=profile, as_dict=as_dict, context=context),
                )
                for obj in objs
            ]
        params = SerializeParams(profile=profile, as_dict=as_dict, context=context)
        return [serializer.func(obj, params) for obj in objs]

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _resolve(self, kind: str, profile: str) -> RegisteredSerializer:
        profile_map = self._registry.get(kind)
        if not profile_map:
            raise KeyError(f"No serializer registered for kind '{kind}'")

        if profile in profile_map:
            return profile_map[profile]

        if "default" in profile_map:
            return profile_map["default"]

        first_profile = next(iter(profile_map))
        return profile_map[first_profile]


def fallback_serialize(obj: Any, params: SerializeParams) -> Any:
    """Very permissive fallback serialization used as last resort."""

    if obj is None:
        return None

    if isinstance(obj, (datetime, date, time)):
        return obj.isoformat()

    if isinstance(obj, UUID):
        return str(obj)

    if isinstance(obj, Decimal):
        return float(obj)

    if isinstance(obj, dict):
        return {k: fallback_serialize(v, params) for k, v in obj.items()}

    if isinstance(obj, (list, tuple, set)):
        return [fallback_serialize(item, params) for item in obj]

    if hasattr(obj, "model_dump"):
        try:
            return obj.model_dump(mode="json")
        except Exception:
            return obj.model_dump()

    if hasattr(obj, "__dict__"):
        return {
            key: fallback_serialize(value, params)
            for key, value in obj.__dict__.items()
            if not key.startswith("_")
        }

    return obj


__all__ = [
    "SerializerRegistry",
    "RegisteredSerializer",
    "SerializeParams",
    "fallback_serialize",
]
