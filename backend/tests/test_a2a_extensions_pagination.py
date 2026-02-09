from __future__ import annotations

import pytest

from app.integrations.a2a_extensions.service import A2AExtensionsService


def test_extension_pagination_rejects_size_over_max() -> None:
    with pytest.raises(ValueError) as exc:
        A2AExtensionsService._coerce_page_size(  # noqa: SLF001
            default_size=20,
            max_size=50,
            page=1,
            size=51,
        )
    assert "size must be <=" in str(exc.value)
