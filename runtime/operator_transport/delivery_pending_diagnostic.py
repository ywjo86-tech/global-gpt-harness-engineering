"""Read-only classification of GitHub control delivery pending fingerprints."""
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Mapping

ACK_SCHEMA = "ocpv2.github-delivery-ack.v1"
PENDING_SCHEMA = "ocpv2.github-delivery-pending.v1"


class DeliveryPendingDiagnosticError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class DeliveryPendingDiagnosticV1:
    source_message_id: str
    message_id: str
    content_sha256: str
    status: str
    evidence_refs: tuple[str, ...]


def _entries(path: Path, schema: str) -> tuple[dict[str, str], ...]:
    if not path.exists():
        return ()
    if path.is_symlink() or not path.is_file():
        raise DeliveryPendingDiagnosticError("delivery state path is unsafe")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise DeliveryPendingDiagnosticError("delivery state is unreadable") from exc
    if not isinstance(value, Mapping) or value.get("schema_version") != schema:
        raise DeliveryPendingDiagnosticError("delivery state schema mismatch")
    rows = value.get("entries")
    if not isinstance(rows, list):
        raise DeliveryPendingDiagnosticError("delivery state entries are invalid")
    result: list[dict[str, str]] = []
    for row in rows:
        if not isinstance(row, Mapping):
            raise DeliveryPendingDiagnosticError("delivery state entry is invalid")
        item = {key: str(row.get(key) or "") for key in ("source_message_id", "message_id", "content_sha256")}
        if not item["source_message_id"] or not item["message_id"] or len(item["content_sha256"]) != 64:
            raise DeliveryPendingDiagnosticError("delivery state entry is invalid")
        result.append(item)
    return tuple(result)


def _durable_refs(state_root: Path, message_id: str) -> tuple[str, ...]:
    refs: list[str] = []
    workspace = state_root / "_workspace"
    if not workspace.is_dir():
        return ()
    needle = json.dumps(message_id)
    for path in workspace.rglob("*.json"):
        if path.is_symlink() or not path.is_file() or "transport" in path.parts:
            continue
        try:
            if path.stat().st_size > 4 * 1024 * 1024:
                continue
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            continue
        if needle in text or message_id in path.name:
            refs.append(str(path))
            if len(refs) >= 20:
                break
    return tuple(refs)


def diagnose_delivery_pending(
    *,
    ack_path: str | Path,
    pending_path: str | Path,
    harness_state_root: str | Path,
) -> tuple[DeliveryPendingDiagnosticV1, ...]:
    acks = _entries(Path(ack_path).expanduser().resolve(), ACK_SCHEMA)
    pending = _entries(Path(pending_path).expanduser().resolve(), PENDING_SCHEMA)
    ack_keys = {
        (row["source_message_id"], row["content_sha256"])
        for row in acks
    }
    state_root = Path(harness_state_root).expanduser().resolve()
    result: list[DeliveryPendingDiagnosticV1] = []
    for row in pending:
        key = (row["source_message_id"], row["content_sha256"])
        if key in ack_keys:
            status = "ACKED_PENDING_CLEANUP"
            refs: tuple[str, ...] = ()
        else:
            refs = _durable_refs(state_root, row["message_id"])
            status = "OBSOLETE_WITH_DURABLE_EVIDENCE" if refs else "CURRENT_OR_UNRESOLVED_PENDING"
        result.append(DeliveryPendingDiagnosticV1(
            source_message_id=row["source_message_id"],
            message_id=row["message_id"],
            content_sha256=row["content_sha256"],
            status=status,
            evidence_refs=refs,
        ))
    return tuple(result)
