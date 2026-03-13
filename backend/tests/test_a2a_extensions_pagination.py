from __future__ import annotations

import pytest

from app.integrations.a2a_extensions.session_extension_service import (
    SessionExtensionService,
)


def test_extension_pagination_rejects_size_over_max() -> None:
    with pytest.raises(ValueError) as exc:
        SessionExtensionService._coerce_page_size(
            default_size=20,
            max_size=50,
            page=1,
            size=51,
        )
    assert "size must be <=" in str(exc.value)


def test_build_pagination_params_page_size_mode() -> None:
    params = SessionExtensionService._build_pagination_params(
        mode="page_size",
        page=3,
        size=20,
        supports_offset=False,
    )
    assert params == {"page": 3, "size": 20}


def test_build_pagination_params_limit_mode_with_offset() -> None:
    params = SessionExtensionService._build_pagination_params(
        mode="limit",
        page=3,
        size=20,
        supports_offset=True,
    )
    assert params == {"offset": 40, "limit": 20}


def test_build_pagination_params_limit_mode_first_page_without_offset() -> None:
    params = SessionExtensionService._build_pagination_params(
        mode="limit",
        page=1,
        size=20,
        supports_offset=False,
    )
    assert params == {"limit": 20}


def test_build_pagination_params_limit_mode_rejects_deep_page_without_offset() -> None:
    with pytest.raises(ValueError) as exc:
        SessionExtensionService._build_pagination_params(
            mode="limit",
            page=2,
            size=20,
            supports_offset=False,
        )
    assert "does not support page > 1" in str(exc.value)


def test_build_pagination_params_rejects_unknown_mode() -> None:
    with pytest.raises(ValueError) as exc:
        SessionExtensionService._build_pagination_params(
            mode="cursor",
            page=1,
            size=20,
            supports_offset=False,
        )
    assert "unsupported pagination mode" in str(exc.value)
