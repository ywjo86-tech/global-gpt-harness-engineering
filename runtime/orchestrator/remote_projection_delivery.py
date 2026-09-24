"""Durable non-authoritative transport identity for remote-control result recovery.

This store does not grant execution authority and does not declare canonical completion.
It only preserves the exact GitHub control-comment fingerprint needed to make a later
noncanonical projection publish idempotent across process restarts.
"""
from __future__ import annotations

import os
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from .durable_io import DurableIOError, durable_json_load, durable_json_save, sha256_bytes
from .remote_control_envelope import RemoteControlEnvelopeV1


_SCHEMA = "orchestration.remote-projection-delivery.v1"


class RemoteProjectionDeliveryError(ValueError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _safe_id(value: object, label: str) -> str:
    text = str(value or "")
    if not text or len(text) > 200 or "/" in text or "\\" in text or ".." in text:
        raise RemoteProjectionDeliveryError(f"unsafe {label}")
    return text


def _digest(value: object, label: str) -> str:
    text = str(value or "")
    if len(text) != 64 or any(ch not in "0123456789abcdef" for ch in text):
        raise RemoteProjectionDeliveryError(f"invalid {label}")
    return text


def _fsync_directory(path: Path) -> None:
    flags = getattr(os, "O_DIRECTORY", 0) | os.O_RDONLY
    fd = os.open(str(path), flags)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


@dataclass(frozen=True, slots=True)
class RemoteProjectionDeliveryV1:
    message_id: str
    source_message_id: str
    control_content_sha256: str
    envelope_sha256: str
    request_kind: str
    bound_at: str
    schema_version: str = _SCHEMA

    def __post_init__(self) -> None:
        _safe_id(self.message_id, "message ID")
        _safe_id(self.source_message_id, "source message ID")
        _digest(self.control_content_sha256, "control content digest")
        _digest(self.envelope_sha256, "envelope digest")
        _safe_id(self.request_kind, "request kind")
        if not self.bound_at:
            raise RemoteProjectionDeliveryError("bound_at is required")
        if self.schema_version != _SCHEMA:
            raise RemoteProjectionDeliveryError("delivery schema mismatch")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "RemoteProjectionDeliveryV1":
        expected = {
            "schema_version",
            "message_id",
            "source_message_id",
            "control_content_sha256",
            "envelope_sha256",
            "request_kind",
            "bound_at",
        }
        if set(value) != expected:
            raise RemoteProjectionDeliveryError("delivery fields mismatch")
        return cls(
            message_id=str(value["message_id"]),
            source_message_id=str(value["source_message_id"]),
            control_content_sha256=str(value["control_content_sha256"]),
            envelope_sha256=str(value["envelope_sha256"]),
            request_kind=str(value["request_kind"]),
            bound_at=str(value["bound_at"]),
            schema_version=str(value["schema_version"]),
        )


class RemoteProjectionDeliveryStore:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).absolute()
        if self.root.is_symlink() or (self.root.exists() and not self.root.is_dir()):
            raise RemoteProjectionDeliveryError("unsafe projection delivery root")
        self.root.mkdir(parents=True, exist_ok=True)
        if self.root.is_symlink():
            raise RemoteProjectionDeliveryError("unsafe projection delivery root")

    def _path(self, message_id: str) -> Path:
        return self.root / f"{_safe_id(message_id, 'message ID')}.json"

    def _load_path(self, path: Path) -> RemoteProjectionDeliveryV1 | None:
        previous = path.with_suffix(path.suffix + ".prev")
        if path.is_symlink() or previous.is_symlink():
            raise RemoteProjectionDeliveryError("projection delivery state is a symlink")
        if not path.exists() and not previous.exists():
            return None
        try:
            value, _ = durable_json_load(path)
        except (DurableIOError, OSError, ValueError) as exc:
            raise RemoteProjectionDeliveryError("projection delivery state is invalid") from exc
        return RemoteProjectionDeliveryV1.from_mapping(value)

    def get(self, message_id: str) -> RemoteProjectionDeliveryV1 | None:
        return self._load_path(self._path(message_id))

    def record(
        self,
        envelope: RemoteControlEnvelopeV1,
        *,
        control_content: bytes,
    ) -> RemoteProjectionDeliveryV1:
        if not isinstance(envelope, RemoteControlEnvelopeV1):
            raise RemoteProjectionDeliveryError("remote control envelope is required")
        if not isinstance(control_content, bytes) or not control_content:
            raise RemoteProjectionDeliveryError("control content is required")
        candidate = RemoteProjectionDeliveryV1(
            message_id=envelope.message_id,
            source_message_id=envelope.transport.source_message_id,
            control_content_sha256=sha256_bytes(control_content),
            envelope_sha256=envelope.envelope_sha256,
            request_kind=envelope.request_kind,
            bound_at=_now(),
        )
        path = self._path(candidate.message_id)
        existing = self._load_path(path)
        if existing is not None:
            immutable = (
                existing.message_id,
                existing.source_message_id,
                existing.control_content_sha256,
                existing.envelope_sha256,
                existing.request_kind,
            )
            requested = (
                candidate.message_id,
                candidate.source_message_id,
                candidate.control_content_sha256,
                candidate.envelope_sha256,
                candidate.request_kind,
            )
            if immutable != requested:
                raise RemoteProjectionDeliveryError("conflicting projection delivery binding")
            return existing
        try:
            durable_json_save(path, candidate.to_dict())
        except (DurableIOError, OSError, ValueError) as exc:
            raise RemoteProjectionDeliveryError("projection delivery write failed") from exc
        loaded = self._load_path(path)
        assert loaded is not None
        return loaded

    def remove(self, message_id: str) -> None:
        path = self._path(message_id)
        previous = path.with_suffix(path.suffix + ".prev")
        for target in (path, previous):
            if target.is_symlink() or (target.exists() and not target.is_file()):
                raise RemoteProjectionDeliveryError("projection delivery state is unsafe")
        changed = False
        try:
            for target in (path, previous):
                if target.exists():
                    target.unlink()
                    changed = True
            if changed:
                _fsync_directory(self.root)
        except OSError as exc:
            raise RemoteProjectionDeliveryError("projection delivery cleanup failed") from exc
