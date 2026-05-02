"""Helpers for request-scoped A2A extension negotiation."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from a2a.client.service_parameters import ServiceParametersFactory, with_a2a_extensions
from a2a.extensions.common import HTTP_EXTENSION_HEADER, get_requested_extensions


def build_extension_request_headers(
    *,
    base_headers: Mapping[str, str] | None,
    requested_extensions: Sequence[str] | None,
) -> dict[str, str]:
    """Merge standard A2A extension negotiation headers into outbound headers."""

    headers = {
        str(key): str(value)
        for key, value in (base_headers or {}).items()
        if key is not None and value is not None
    }
    normalized_extensions = sorted(
        get_requested_extensions(
            [
                *(
                    [headers.get(HTTP_EXTENSION_HEADER, "")]
                    if headers.get(HTTP_EXTENSION_HEADER)
                    else []
                ),
                *[
                    extension
                    for extension in (requested_extensions or ())
                    if isinstance(extension, str) and extension.strip()
                ],
            ]
        )
    )
    if not normalized_extensions:
        return headers
    return ServiceParametersFactory.create_from(
        headers,
        [with_a2a_extensions(normalized_extensions)],
    )
