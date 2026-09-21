"""Outbound-only Attention delivery adapters and immutable delivery receipts."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Callable, Mapping
from urllib import request as urllib_request

from .durable_io import atomic_write_json

RECEIPT_SCHEMA = "orchestration.attention-delivery-receipt.v1"
ATTENTION_DELIVERY_UNCONFIGURED = "ATTENTION_DELIVERY_UNCONFIGURED"
CONTROL_AUTHORITY = "NONE"
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")


class AttentionDeliveryError(ValueError):
    pass


def _digest(value: object) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _validate_event(event: Mapping[str, Any]) -> str:
    event_id = str(event.get("event_id") or "")
    if _SHA256.fullmatch(event_id) is None:
        raise AttentionDeliveryError("attention event ID is invalid")
    if event.get("direction") != "OUTBOUND_ONLY" or event.get("control_authority") != CONTROL_AUTHORITY:
        raise AttentionDeliveryError("attention event authority/direction mismatch")
    if not str(event.get("project_id") or "") or not str(event.get("run_id") or ""):
        raise AttentionDeliveryError("attention event identity is incomplete")
    return event_id


@dataclass(frozen=True, slots=True)
class AttentionDeliveryReceipt:
    schema_version: str
    event_id: str
    project_id: str
    run_id: str
    adapter_kind: str
    provider_receipt: str
    delivered_at: str
    control_authority: str
    receipt_sha256: str

    @classmethod
    def create(cls, event: Mapping[str, Any], *, adapter_kind: str, provider_receipt: str) -> "AttentionDeliveryReceipt":
        event_id = _validate_event(event)
        provider = str(provider_receipt or "").strip()
        if not provider or len(provider) > 1024 or "\n" in provider:
            raise AttentionDeliveryError("provider delivery receipt is invalid")
        unsigned = {
            "schema_version": RECEIPT_SCHEMA,
            "event_id": event_id,
            "project_id": str(event["project_id"]),
            "run_id": str(event["run_id"]),
            "adapter_kind": str(adapter_kind),
            "provider_receipt": provider,
            "delivered_at": _now(),
            "control_authority": CONTROL_AUTHORITY,
        }
        return cls(**unsigned, receipt_sha256=_digest(unsigned))

    def to_dict(self) -> dict[str, str]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "AttentionDeliveryReceipt":
        fields = {"schema_version","event_id","project_id","run_id","adapter_kind","provider_receipt","delivered_at","control_authority","receipt_sha256"}
        if not isinstance(value, Mapping) or set(value) != fields:
            raise AttentionDeliveryError("delivery receipt fields mismatch")
        receipt = cls(**{field: str(value[field]) for field in fields})
        if receipt.schema_version != RECEIPT_SCHEMA or receipt.control_authority != CONTROL_AUTHORITY:
            raise AttentionDeliveryError("delivery receipt schema/authority mismatch")
        unsigned = receipt.to_dict(); unsigned.pop("receipt_sha256")
        if receipt.receipt_sha256 != _digest(unsigned):
            raise AttentionDeliveryError("delivery receipt digest mismatch")
        return receipt


class AttentionDeliveryReceiptStore:
    def __init__(self, run_base: str | Path, *, project_id: str, run_id: str) -> None:
        root = Path(run_base).resolve()
        if not root.is_dir() or root.is_symlink():
            raise AttentionDeliveryError("delivery receipt root is unsafe")
        self.project_id = str(project_id); self.run_id = str(run_id)
        if not self.project_id or not self.run_id:
            raise AttentionDeliveryError("delivery receipt identity is incomplete")
        self.base = root / "attention" / "delivery-receipts"

    def _path(self, event_id: str) -> Path:
        if _SHA256.fullmatch(str(event_id)) is None:
            raise AttentionDeliveryError("delivery event ID is invalid")
        return self.base / f"{event_id}.json"

    def save(self, receipt: AttentionDeliveryReceipt) -> AttentionDeliveryReceipt:
        if receipt.project_id != self.project_id or receipt.run_id != self.run_id:
            raise AttentionDeliveryError("delivery receipt store identity mismatch")
        path = self._path(receipt.event_id)
        if path.exists():
            existing = self.load(receipt.event_id)
            if existing is None or existing.receipt_sha256 != receipt.receipt_sha256:
                raise AttentionDeliveryError("conflicting delivery receipt already exists")
            return existing
        self.base.mkdir(parents=True, exist_ok=True)
        if self.base.is_symlink():
            raise AttentionDeliveryError("delivery receipt store is unsafe")
        atomic_write_json(path, receipt.to_dict())
        return receipt

    def load(self, event_id: str) -> AttentionDeliveryReceipt | None:
        path = self._path(event_id)
        if not path.exists():
            return None
        if path.is_symlink() or not path.is_file():
            raise AttentionDeliveryError("delivery receipt path is unsafe")
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise AttentionDeliveryError("delivery receipt is malformed") from exc
        receipt = AttentionDeliveryReceipt.from_dict(value)
        if receipt.event_id != event_id:
            raise AttentionDeliveryError("delivery receipt event mismatch")
        return receipt


class CaptureAttentionDeliveryAdapter:
    """Test-only adapter. Repeated event IDs return the same immutable receipt."""
    adapter_kind = "CAPTURE_TEST_V1"
    control_authority = CONTROL_AUTHORITY
    status = "READY"

    def __init__(self) -> None:
        self._receipts: dict[str, AttentionDeliveryReceipt] = {}
        self._counts: dict[str, int] = {}

    def send(self, event: Mapping[str, Any]) -> AttentionDeliveryReceipt:
        event_id = _validate_event(event)
        existing = self._receipts.get(event_id)
        if existing is not None:
            return existing
        receipt = AttentionDeliveryReceipt.create(event, adapter_kind=self.adapter_kind, provider_receipt=f"capture:{event_id}")
        self._receipts[event_id] = receipt
        self._counts[event_id] = 1
        return receipt

    def delivery_count(self, event_id: str) -> int:
        return self._counts.get(str(event_id), 0)


class HTTPSWebhookV1AttentionDeliveryAdapter:
    """Gated outbound HTTPS transport; disabled unless separately authorized/configured."""
    adapter_kind = "HTTPS_WEBHOOK_V1"
    control_authority = CONTROL_AUTHORITY

    def __init__(
        self, *, endpoint: str, allowlisted_endpoints: tuple[str, ...], secret_ref: str,
        transport_authorized: bool = False, secret_loader: Callable[[str], str] | None = None,
        timeout_seconds: float = 5.0,
    ) -> None:
        self.endpoint = str(endpoint).strip()
        self.allowlisted_endpoints = tuple(str(item).strip() for item in allowlisted_endpoints)
        self.secret_ref = str(secret_ref).strip()
        self.transport_authorized = bool(transport_authorized)
        self.secret_loader = secret_loader
        self.timeout_seconds = float(timeout_seconds)
        if not self.endpoint.startswith("https://") or self.endpoint not in self.allowlisted_endpoints:
            raise AttentionDeliveryError("HTTPS webhook endpoint is not allowlisted")
        if not self.secret_ref or self.timeout_seconds <= 0 or self.timeout_seconds > 30:
            raise AttentionDeliveryError("HTTPS webhook configuration is invalid")

    @property
    def status(self) -> str:
        if not self.transport_authorized or self.secret_loader is None:
            return ATTENTION_DELIVERY_UNCONFIGURED
        return "READY"

    def send(self, event: Mapping[str, Any]) -> AttentionDeliveryReceipt:
        event_id = _validate_event(event)
        if self.status != "READY":
            raise AttentionDeliveryError(ATTENTION_DELIVERY_UNCONFIGURED)
        token = str(self.secret_loader(self.secret_ref) or "").strip()
        if not token:
            raise AttentionDeliveryError("approved notification secret is unavailable")
        body = json.dumps(dict(event), sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        req = urllib_request.Request(
            self.endpoint, data=body, method="POST",
            headers={"Content-Type":"application/json","Authorization":f"Bearer {token}","Idempotency-Key":event_id},
        )
        try:
            with urllib_request.urlopen(req, timeout=self.timeout_seconds) as response:
                status = int(getattr(response, "status", 0) or 0)
                provider_receipt = str(response.headers.get("X-Request-Id") or f"https:{status}:{event_id}")
        except Exception as exc:
            raise AttentionDeliveryError(f"HTTPS_WEBHOOK_V1_DELIVERY_FAILED:{type(exc).__name__}") from exc
        if status < 200 or status >= 300:
            raise AttentionDeliveryError(f"HTTPS_WEBHOOK_V1_HTTP_STATUS:{status}")
        return AttentionDeliveryReceipt.create(event, adapter_kind=self.adapter_kind, provider_receipt=provider_receipt)
