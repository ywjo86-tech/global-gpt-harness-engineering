"""Durable one-way user-attention outbox for Full Plan runtime incidents.

The outbox is deliberately not an orchestration authority.  It can publish and
acknowledge notification records, but it cannot approve, resume, reroute, or
mutate a Full Plan run.
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

from .durable_io import atomic_write_json, canonical_json_bytes
from .user_interaction_policy import DEFERRED_INCIDENT, DELIVERY_CLASSES, infer_delivery_class

SCHEMA_VERSION = "orchestration.user-attention.v1"


class AttentionOutboxError(ValueError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _digest(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _safe_text(value: object, *, limit: int = 512) -> str:
    text = str(value or "").strip()
    return text[:limit]


class AttentionOutbox:
    """Crash-safe, idempotent notification outbox with no inbound control path."""

    def __init__(self, run_base: str | Path, *, project_id: str, run_id: str):
        self.base = Path(run_base).resolve() / "attention"
        self.project_id = _safe_text(project_id, limit=160)
        self.run_id = _safe_text(run_id, limit=160)
        if not self.project_id or not self.run_id:
            raise AttentionOutboxError("attention outbox identity is incomplete")
        self.pending_dir = self.base / "pending"
        self.delivered_dir = self.base / "delivered"

    def publish(self, *, kind: str, state: str, reason: str, gate_id: str | None = None,
                state_sha256: str | None = None, details: Mapping[str, Any] | None = None,
                delivery_class: str | None = None) -> dict[str, Any]:
        if delivery_class is not None and delivery_class not in DELIVERY_CLASSES:
            raise AttentionOutboxError("invalid attention delivery class")
        identity = {
            "project_id": self.project_id,
            "run_id": self.run_id,
            "kind": _safe_text(kind, limit=96),
            "state": _safe_text(state, limit=96),
            "reason": _safe_text(reason),
            "gate_id": _safe_text(gate_id, limit=160) if gate_id else None,
            "state_sha256": _safe_text(state_sha256, limit=64) if state_sha256 else None,
        }
        # One runtime incident may surface first as DEAD_LETTER and later as
        # terminal BLOCKED during reconciliation.  Correlate by root cause, not
        # by presentation state, so the user receives one notification.
        incident_identity = {
            "project_id": self.project_id, "run_id": self.run_id,
            "gate_id": identity["gate_id"], "reason": identity["reason"],
        }
        event_id = _digest(incident_identity)
        payload = {
            "schema_version": SCHEMA_VERSION,
            "event_id": event_id,
            "incident_key": event_id,
            **identity,
            "details": dict(details or {}),
            "created_at": _now(),
            "direction": "OUTBOUND_ONLY",
            "control_authority": "NONE",
        }
        if delivery_class is not None:
            payload["delivery_class"] = delivery_class
        target = self.pending_dir / f"{event_id}.json"
        delivered = self.delivered_dir / f"{event_id}.json"
        if delivered.is_file():
            return json.loads(delivered.read_text(encoding="utf-8"))
        if target.exists():
            if target.is_symlink() or not target.is_file():
                raise AttentionOutboxError("unsafe attention outbox record")
            existing = json.loads(target.read_text(encoding="utf-8"))
            if existing.get("event_id") != event_id or existing.get("schema_version") != SCHEMA_VERSION:
                raise AttentionOutboxError("attention outbox identity drift")
            # Kind/state may evolve while the root cause remains identical.
            # Preserve the first immutable notification record instead of
            # producing duplicate user-facing events.
            return existing
        atomic_write_json(target, payload)
        return payload

    def pending(self) -> list[dict[str, Any]]:
        if not self.pending_dir.exists():
            return []
        rows: list[dict[str, Any]] = []
        for path in sorted(self.pending_dir.glob("*.json")):
            if path.is_symlink() or not path.is_file():
                continue
            delivered = self.delivered_dir / path.name
            if delivered.is_file():
                continue
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError):
                continue
            if isinstance(value, dict) and value.get("schema_version") == SCHEMA_VERSION:
                rows.append(value)
        return rows

    def mark_delivered(self, event_id: str, *, channel: str, receipt: str) -> dict[str, Any]:
        source = self.pending_dir / f"{event_id}.json"
        target = self.delivered_dir / f"{event_id}.json"
        if target.is_file():
            return json.loads(target.read_text(encoding="utf-8"))
        if source.is_symlink() or not source.is_file():
            raise AttentionOutboxError("pending attention event is missing")
        payload = json.loads(source.read_text(encoding="utf-8"))
        if payload.get("event_id") != event_id:
            raise AttentionOutboxError("attention event ID mismatch")
        delivered = {
            **payload,
            "delivery": {
                "channel": _safe_text(channel, limit=96),
                "receipt": _safe_text(receipt, limit=512),
                "delivered_at": _now(),
            },
        }
        atomic_write_json(target, delivered)
        try:
            source.unlink()
            fd = os.open(str(source.parent), getattr(os, "O_DIRECTORY", 0) | os.O_RDONLY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
        except FileNotFoundError:
            pass
        return delivered


    def deliver_with_adapter(
        self, adapter: Any, *, receipt_store: Any, channel: str,
        eligible_event_ids: set[str] | frozenset[str] | None = None,
    ) -> list[str]:
        """Persist adapter receipt before marking an eligible event delivered."""
        eligible = set(eligible_event_ids or ())
        delivered: list[str] = []
        for event in self.pending():
            event_id = str(event["event_id"])
            if infer_delivery_class(event) == DEFERRED_INCIDENT and event_id not in eligible:
                continue
            existing = receipt_store.load(event_id)
            receipt = existing if existing is not None else adapter.send(dict(event))
            receipt = receipt_store.save(receipt)
            self.mark_delivered(event_id, channel=channel, receipt=str(receipt.receipt_sha256))
            delivered.append(event_id)
        return delivered

    def deliver(
        self, sender: Callable[[Mapping[str, Any]], str], *, channel: str,
        eligible_event_ids: set[str] | frozenset[str] | None = None,
    ) -> list[str]:
        """Deliver only policy-eligible pending records through an outbound sender.

        Deferred incidents are not deliverable by default; a read-only policy layer
        must explicitly supply their eligible event IDs. Immediate-decision and
        confirmed-stall records remain directly deliverable.
        """
        eligible = set(eligible_event_ids or ())
        delivered: list[str] = []
        for event in self.pending():
            event_id = str(event["event_id"])
            if infer_delivery_class(event) == DEFERRED_INCIDENT and event_id not in eligible:
                continue
            receipt = sender(dict(event))
            if not isinstance(receipt, str) or not receipt.strip():
                raise AttentionOutboxError("notification sender returned no receipt")
            self.mark_delivered(event_id, channel=channel, receipt=receipt)
            delivered.append(event_id)
        return delivered
