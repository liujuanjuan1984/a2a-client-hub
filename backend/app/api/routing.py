"""
Routing utilities that enforce strict path converters for FastAPI routers.

The StrictAPIRouter ensures that path parameters annotated as UUID automatically
map to Starlette's ``:uuid`` converter so that static paths such as
``/experience-rates`` are never swallowed by dynamic ``/{item_id}`` routes.
"""

from __future__ import annotations

import inspect
import re
import types
from typing import Annotated, Any, Callable, Mapping, Union, get_args, get_origin
from uuid import UUID

from fastapi import APIRouter as FastAPIRouter

_PATH_PARAM_PATTERN = re.compile(
    r"{(?P<name>[a-zA-Z_][a-zA-Z0-9_]*)(?::(?P<converter>[^}]+))?}"
)


def _is_uuid_type(annotation: Any) -> bool:
    """Return True when the provided annotation represents a UUID type."""
    if annotation is inspect._empty:
        return False

    if annotation is UUID:
        return True

    origin = get_origin(annotation)

    if origin is None:
        return annotation is UUID

    if origin in (Union, types.UnionType):
        return any(
            _is_uuid_type(arg)
            for arg in get_args(annotation)
            if arg is not type(None)  # noqa: E721
        )

    if origin is Annotated:
        annotated_args = get_args(annotation)
        if annotated_args:
            return _is_uuid_type(annotated_args[0])
        return False

    return False


def _ensure_uuid_converters(path: str, endpoint: Callable[..., Any]) -> str:
    """Inject ``:uuid`` converters for UUID path parameters that lack explicit converters."""
    signature = inspect.signature(endpoint)
    path_params: Mapping[str, inspect.Parameter] = {
        name: parameter
        for name, parameter in signature.parameters.items()
        if parameter.kind
        in (
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
            inspect.Parameter.KEYWORD_ONLY,
        )
    }

    def _replace(match: re.Match[str]) -> str:
        name = match.group("name")
        converter = match.group("converter")
        if converter is not None:
            return match.group(0)

        parameter = path_params.get(name)
        if parameter is None:
            return match.group(0)

        if _is_uuid_type(parameter.annotation):
            return f"{{{name}:uuid}}"

        return match.group(0)

    return _PATH_PARAM_PATTERN.sub(_replace, path)


class StrictAPIRouter(FastAPIRouter):
    """APIRouter that automatically tightens UUID path parameters."""

    def add_api_route(
        self,
        path: str,
        endpoint: Callable[..., Any],
        **kwargs: Any,
    ) -> None:
        adjusted_path = _ensure_uuid_converters(path, endpoint)
        super().add_api_route(adjusted_path, endpoint, **kwargs)


APIRouter = StrictAPIRouter
