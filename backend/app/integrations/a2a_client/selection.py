"""Peer descriptor normalization and adapter selection helpers."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from typing import Any
from uuid import uuid4

from a2a.types import AgentCard

from app.integrations.a2a_client.models import (
    A2AInterfaceDescriptor,
    A2AMessageRequest,
    A2APeerDescriptor,
)


def normalize_transport_label(value: str | None) -> str:
    candidate = (value or "").strip().upper()
    if not candidate:
        return "JSONRPC"
    return candidate


def build_peer_descriptor(
    *,
    agent_url: str,
    card: AgentCard,
    selected_transport: str,
    selected_url: str,
) -> A2APeerDescriptor:
    interfaces = tuple(_collect_interfaces(card))
    capabilities = getattr(card, "capabilities", None)
    supports_streaming = bool(getattr(capabilities, "streaming", False))
    fingerprint_payload = {
        "agent_url": agent_url.rstrip("/"),
        "selected_transport": normalize_transport_label(selected_transport),
        "selected_url": selected_url.rstrip("/"),
        "interfaces": [
            {
                "transport": item.transport,
                "url": item.url.rstrip("/"),
                "protocol_version": item.protocol_version,
            }
            for item in interfaces
        ],
        "supports_streaming": supports_streaming,
    }
    fingerprint = hashlib.sha256(
        json.dumps(
            fingerprint_payload,
            ensure_ascii=False,
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()
    return A2APeerDescriptor(
        agent_url=agent_url.rstrip("/"),
        selected_transport=normalize_transport_label(selected_transport),
        selected_url=selected_url.rstrip("/"),
        interfaces=interfaces,
        card=card,
        card_fingerprint=fingerprint,
        supports_streaming=supports_streaming,
    )


def build_pascal_message_payload(request: A2AMessageRequest) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "messageId": str(uuid4()),
        "role": "user",
        "parts": [{"type": "text", "text": request.query}],
    }
    if request.context_id:
        payload["contextId"] = request.context_id
    if request.metadata:
        payload["metadata"] = request.metadata
    return payload


def _collect_interfaces(card: AgentCard) -> Iterable[A2AInterfaceDescriptor]:
    protocol_version = getattr(card, "protocol_version", None)
    preferred_transport = normalize_transport_label(
        getattr(card, "preferred_transport", None)
    )
    preferred_url = (getattr(card, "url", "") or "").strip()
    if preferred_transport and preferred_url:
        yield A2AInterfaceDescriptor(
            transport=preferred_transport,
            url=preferred_url,
            protocol_version=protocol_version,
            source="preferred",
        )

    for iface in getattr(card, "additional_interfaces", None) or []:
        transport = normalize_transport_label(getattr(iface, "transport", None))
        url = (getattr(iface, "url", "") or "").strip()
        if not transport or not url:
            continue
        yield A2AInterfaceDescriptor(
            transport=transport,
            url=url,
            protocol_version=protocol_version,
            source="additional",
        )


__all__ = [
    "A2AMessageRequest",
    "A2APeerDescriptor",
    "build_pascal_message_payload",
    "build_peer_descriptor",
    "normalize_transport_label",
]
