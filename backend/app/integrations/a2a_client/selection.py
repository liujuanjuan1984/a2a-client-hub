"""Peer descriptor normalization and adapter selection helpers."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from uuid import uuid4

from a2a.types import AgentCard, Message, Part, Role

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


def build_a2a_message(request: A2AMessageRequest) -> Message:
    resolved_context_id = request.context_id or str(uuid4())
    parts: list[Part] = [Part(text=request.query)]
    return Message(
        message_id=str(uuid4()),
        role=Role.ROLE_USER,
        parts=parts,
        context_id=resolved_context_id,
        metadata=request.metadata or None,
    )


def _collect_interfaces(card: AgentCard) -> Iterable[A2AInterfaceDescriptor]:
    for iface in getattr(card, "supported_interfaces", None) or []:
        transport = normalize_transport_label(getattr(iface, "protocol_binding", None))
        url = (getattr(iface, "url", "") or "").strip()
        if not transport or not url:
            continue
        yield A2AInterfaceDescriptor(
            transport=transport,
            url=url,
            protocol_version=(getattr(iface, "protocol_version", None) or None),
            source="supported_interface",
        )
