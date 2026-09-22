"""Durable non-authoritative replay/tamper ledger for OCPv2 deliveries."""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Sequence

from .durable_io import DurableIOError, durable_json_load, durable_json_save
from .remote_operator_envelope import RemoteOperatorEnvelopeV2


_RECEIPT_SCHEMA = "orchestration.remote-operator-receipt.v1"
_SEQUENCE_SCHEMA = "orchestration.remote-operator-sequence.v1"


class RemoteOperatorReceiptError(ValueError):
    pass


class ReceiptStatus(str, Enum):
    NEW = "NEW"
    IDEMPOTENT_REPLAY = "IDEMPOTENT_REPLAY"
    TAMPER_DETECTED = "TAMPER_DETECTED"
    REPLAY_REJECTED = "REPLAY_REJECTED"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _safe_component(value: str, label: str) -> str:
    text = str(value or "")
    if not text or "/" in text or "\\" in text or ".." in text:
        raise RemoteOperatorReceiptError(f"unsafe {label}")
    return text


class RemoteOperatorReceiptStore:
    """Track delivery identity without owning task/run/migration truth.

    The receipt store is deliberately downstream/non-authoritative.  Its state may
    suppress duplicate transport delivery, but it may not declare canonical Harness
    completion.
    """

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).absolute()
        if self.root.exists() and (self.root.is_symlink() or not self.root.is_dir()):
            raise RemoteOperatorReceiptError("unsafe receipt root")
        self.root.mkdir(parents=True, exist_ok=True)
        if self.root.is_symlink():
            raise RemoteOperatorReceiptError("unsafe receipt root")

    def _channel_dir(self, envelope: RemoteOperatorEnvelopeV2) -> Path:
        adapter = _safe_component(envelope.transport.adapter_id, "adapter ID")
        channel = _safe_component(envelope.transport.channel_id, "channel ID")
        path = self.root / adapter / channel
        for parent in (self.root / adapter, path):
            if parent.is_symlink() or (parent.exists() and not parent.is_dir()):
                raise RemoteOperatorReceiptError("unsafe receipt channel")
        path.mkdir(parents=True, exist_ok=True)
        if path.is_symlink():
            raise RemoteOperatorReceiptError("unsafe receipt channel")
        return path

    def _receipt_path(self, envelope: RemoteOperatorEnvelopeV2) -> Path:
        return self._channel_dir(envelope) / f"{_safe_component(envelope.message_id, 'message ID')}.json"

    def _sequence_path(self, envelope: RemoteOperatorEnvelopeV2) -> Path:
        return self._channel_dir(envelope) / ".sequence.json"

    @staticmethod
    def _load_object(path: Path) -> tuple[dict[str, Any], bool] | None:
        previous = path.with_suffix(path.suffix + ".prev")
        if path.is_symlink() or previous.is_symlink():
            raise RemoteOperatorReceiptError("receipt state is a symlink")
        if not path.exists() and not previous.exists():
            return None
        try:
            return durable_json_load(path)
        except (DurableIOError, OSError, ValueError) as exc:
            raise RemoteOperatorReceiptError(f"receipt state is invalid: {path.name}") from exc

    def _sequence_state(self, envelope: RemoteOperatorEnvelopeV2) -> dict[str, Any]:
        loaded = self._load_object(self._sequence_path(envelope))
        if loaded is None:
            return {
                "schema_version": _SEQUENCE_SCHEMA,
                "highest_sequence": 0,
                "source_message_id": "",
                "updated_at": "",
            }
        value, _ = loaded
        if value.get("schema_version") != _SEQUENCE_SCHEMA:
            raise RemoteOperatorReceiptError("sequence schema mismatch")
        highest = value.get("highest_sequence")
        source = value.get("source_message_id")
        if not isinstance(highest, int) or highest < 0 or not isinstance(source, str):
            raise RemoteOperatorReceiptError("sequence state invalid")
        return value

    def _highest_durable_receipt_sequence(self, envelope: RemoteOperatorEnvelopeV2) -> int:
        highest = 0
        for path in self._channel_dir(envelope).glob("*.json"):
            if path.name == ".sequence.json":
                continue
            loaded = self._load_object(path)
            if loaded is None:
                continue
            receipt, _ = loaded
            if receipt.get("schema_version") != _RECEIPT_SCHEMA:
                raise RemoteOperatorReceiptError("receipt schema mismatch")
            receipt_sequence = receipt.get("sequence")
            if not isinstance(receipt_sequence, int) or receipt_sequence <= 0:
                raise RemoteOperatorReceiptError("receipt sequence invalid")
            highest = max(highest, receipt_sequence)
        return highest

    def _repair_sequence_watermark(self, envelope: RemoteOperatorEnvelopeV2) -> None:
        sequence = self._sequence_state(envelope)
        highest = int(sequence["highest_sequence"])
        if envelope.sequence < highest:
            return
        if envelope.sequence == highest:
            if highest > 0 and sequence["source_message_id"] != envelope.transport.source_message_id:
                raise RemoteOperatorReceiptError("sequence watermark conflicts with durable receipt")
            return
        repaired = {
            "schema_version": _SEQUENCE_SCHEMA,
            "highest_sequence": envelope.sequence,
            "source_message_id": envelope.transport.source_message_id,
            "updated_at": _now(),
        }
        try:
            durable_json_save(self._sequence_path(envelope), repaired)
        except (DurableIOError, OSError, ValueError) as exc:
            raise RemoteOperatorReceiptError("durable sequence watermark repair failed") from exc

    def classify_delivery(self, envelope: RemoteOperatorEnvelopeV2) -> ReceiptStatus:
        receipt_path = self._receipt_path(envelope)
        loaded = self._load_object(receipt_path)
        if loaded is not None:
            receipt, _ = loaded
            if receipt.get("schema_version") != _RECEIPT_SCHEMA:
                raise RemoteOperatorReceiptError("receipt schema mismatch")
            if receipt.get("envelope_sha256") == envelope.envelope_sha256:
                return ReceiptStatus.IDEMPOTENT_REPLAY
            return ReceiptStatus.TAMPER_DETECTED

        sequence = self._sequence_state(envelope)
        highest = max(
            int(sequence["highest_sequence"]),
            self._highest_durable_receipt_sequence(envelope),
        )
        if envelope.sequence < highest:
            return ReceiptStatus.REPLAY_REJECTED
        if envelope.sequence == highest and highest > 0:
            # A sequence number is single-use for a channel.  If the receipt was
            # lost, fail closed rather than risking a duplicate canonical action.
            return ReceiptStatus.REPLAY_REJECTED
        return ReceiptStatus.NEW

    def record_received(self, envelope: RemoteOperatorEnvelopeV2) -> dict[str, Any]:
        status = self.classify_delivery(envelope)
        if status == ReceiptStatus.IDEMPOTENT_REPLAY:
            loaded = self._load_object(self._receipt_path(envelope))
            assert loaded is not None
            receipt = loaded[0]
            self._repair_sequence_watermark(envelope)
            return receipt
        if status != ReceiptStatus.NEW:
            raise RemoteOperatorReceiptError(status.value)

        receipt = {
            "schema_version": _RECEIPT_SCHEMA,
            "message_id": envelope.message_id,
            "envelope_sha256": envelope.envelope_sha256,
            "directive_digest": envelope.directive_digest,
            "transport_adapter_id": envelope.transport.adapter_id,
            "transport_channel_id": envelope.transport.channel_id,
            "source_actor_id": envelope.transport.source_actor_id,
            "source_message_id": envelope.transport.source_message_id,
            "sequence": envelope.sequence,
            "received_at": _now(),
            "validation_status": "RECEIVED",
            "canonical_receipt_refs": [],
            "terminal_projection_status": "PENDING",
        }
        receipt_path = self._receipt_path(envelope)
        if receipt_path.is_symlink():
            raise RemoteOperatorReceiptError("receipt state is a symlink")
        try:
            # Receipt first: if a crash occurs before the sequence watermark write,
            # the same message remains safely idempotent rather than re-executed.
            durable_json_save(receipt_path, receipt)
            sequence = {
                "schema_version": _SEQUENCE_SCHEMA,
                "highest_sequence": envelope.sequence,
                "source_message_id": envelope.transport.source_message_id,
                "updated_at": _now(),
            }
            durable_json_save(self._sequence_path(envelope), sequence)
        except (DurableIOError, OSError, ValueError) as exc:
            raise RemoteOperatorReceiptError("durable receipt write failed") from exc
        return receipt

    def record_terminal_projection(
        self,
        *,
        message_id: str,
        projection_digest: str,
        canonical_receipt_refs: Sequence[str],
    ) -> dict[str, Any]:
        message = _safe_component(message_id, "message ID")
        matches = [
            path for path in self.root.glob(f"*/*/{message}.json")
            if path.name != ".sequence.json"
        ]
        if len(matches) != 1:
            raise RemoteOperatorReceiptError("receipt message identity is not unique")
        path = matches[0]
        loaded = self._load_object(path)
        if loaded is None:
            raise RemoteOperatorReceiptError("receipt missing")
        receipt, _ = loaded
        if not projection_digest or len(projection_digest) != 64:
            raise RemoteOperatorReceiptError("projection digest invalid")
        receipt = dict(receipt)
        receipt["canonical_receipt_refs"] = [str(item) for item in canonical_receipt_refs]
        receipt["terminal_projection_status"] = "PROJECTED"
        receipt["projection_digest"] = str(projection_digest)
        try:
            durable_json_save(path, receipt)
        except (DurableIOError, OSError, ValueError) as exc:
            raise RemoteOperatorReceiptError("durable receipt update failed") from exc
        return receipt
