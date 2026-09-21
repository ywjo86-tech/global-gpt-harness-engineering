"""Transport-neutral OCPv2 ingress/egress contract.

The transport carries bytes, acknowledgements and non-authoritative projections only.
It exposes no execution, provider-routing or canonical-state mutation capability.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Protocol


@dataclass(frozen=True, slots=True)
class RawControlEnvelope:
    source_repository_id: int | None
    source_channel_id: str
    source_actor_id: str
    source_message_id: str
    content: bytes
    received_at: str

    def __post_init__(self) -> None:
        if self.source_repository_id is not None:
            if isinstance(self.source_repository_id, bool) or self.source_repository_id <= 0:
                raise ValueError("source repository ID must be a positive integer")
        for value, label in (
            (self.source_channel_id, "source channel ID"),
            (self.source_actor_id, "source actor ID"),
            (self.source_message_id, "source message ID"),
            (self.received_at, "received_at"),
        ):
            if not isinstance(value, str) or not value:
                raise ValueError(f"{label} is required")
        if not isinstance(self.content, bytes):
            raise TypeError("control envelope content must be bytes")


class RemoteOperatorTransport(Protocol):
    def receive(self, *, limit: int = 16) -> tuple[RawControlEnvelope, ...]: ...

    def acknowledge_delivery(self, message_id: str) -> None: ...

    def publish_projection(self, projection: Mapping[str, Any]) -> None: ...
