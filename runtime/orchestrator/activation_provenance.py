"""Immutable OCPv2 Full Plan activation provenance sidecars."""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from .durable_io import atomic_write_json, canonical_json_bytes

SCHEMA_V1 = "orchestration.full-plan-activation-provenance.v1"
_SHA40 = re.compile(r"[0-9a-f]{40}\Z")
_SHA64 = re.compile(r"[0-9a-f]{64}\Z")


class ActivationProvenanceError(ValueError):
    pass


def _seal(value: Mapping[str, Any]) -> dict[str, Any]:
    raw = {k: v for k, v in value.items() if k != "provenance_sha256"}
    return {**raw, "provenance_sha256": hashlib.sha256(canonical_json_bytes(raw)).hexdigest()}


def _safe_segment(value: str, label: str) -> str:
    text = str(value or "").strip()
    if not text or "/" in text or "\\" in text or ".." in text:
        raise ActivationProvenanceError(f"{label} invalid")
    return text


def validate_activation_provenance(value: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ActivationProvenanceError("provenance mapping required")
    raw = dict(value)
    required = {
        "schema_version", "recorded_at", "activation_request_id", "activation_digest",
        "result_status", "canonical_job_path", "authority_digest",
        "executable_authority_bundle_digest", "executor_component", "control_path",
        "policy_ref", "message_id", "runtime_source_head", "runtime_manifest_sha256",
        "replay_existing_receipt", "provenance_sha256",
    }
    if set(raw) != required or raw.get("schema_version") != SCHEMA_V1:
        raise ActivationProvenanceError("provenance shape/schema mismatch")
    for key in (
        "activation_request_id", "result_status", "canonical_job_path",
        "executor_component", "control_path", "policy_ref", "message_id",
    ):
        if not isinstance(raw.get(key), str) or not raw[key]:
            raise ActivationProvenanceError(f"{key} missing")
    for key in ("activation_digest", "authority_digest", "executable_authority_bundle_digest", "runtime_manifest_sha256", "provenance_sha256"):
        if not isinstance(raw.get(key), str) or not _SHA64.fullmatch(raw[key]):
            raise ActivationProvenanceError(f"{key} invalid")
    if not isinstance(raw.get("runtime_source_head"), str) or not _SHA40.fullmatch(raw["runtime_source_head"]):
        raise ActivationProvenanceError("runtime_source_head invalid")
    if not isinstance(raw.get("replay_existing_receipt"), bool):
        raise ActivationProvenanceError("replay_existing_receipt invalid")
    try:
        ts = datetime.fromisoformat(raw["recorded_at"].replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise ActivationProvenanceError("recorded_at invalid") from exc
    if ts.tzinfo is None:
        raise ActivationProvenanceError("recorded_at must be timezone-aware")
    if raw["provenance_sha256"] != _seal(raw)["provenance_sha256"]:
        raise ActivationProvenanceError("provenance digest mismatch")
    return raw


def record_ocpv2_full_plan_activation_provenance(
    state_root: str | Path,
    *,
    receipt: Mapping[str, Any],
    executor_component: str,
    control_path: str,
    policy_ref: str,
    message_id: str,
    runtime_source_head: str,
    runtime_manifest_sha256: str,
    replay_existing_receipt: bool,
    recorded_at: str | None = None,
) -> Path:
    request_id = _safe_segment(str(receipt.get("activation_request_id") or ""), "activation_request_id")
    msg = str(message_id or "").strip()
    if not msg:
        raise ActivationProvenanceError("message_id missing")
    event_name = hashlib.sha256(msg.encode("utf-8")).hexdigest() + ".json"
    root = Path(state_root).expanduser().resolve()
    if root.is_symlink() or not root.is_dir():
        raise ActivationProvenanceError("state root invalid")
    target_dir = root / "_workspace" / "full-plan-activation-provenance" / request_id
    target = target_dir / event_name
    if target.exists():
        if target.is_symlink() or not target.is_file():
            raise ActivationProvenanceError("provenance path unsafe")
        try:
            existing = validate_activation_provenance(json.loads(target.read_text(encoding="utf-8")))
        except (OSError, UnicodeError, json.JSONDecodeError, ActivationProvenanceError) as exc:
            raise ActivationProvenanceError("existing provenance invalid") from exc
        if existing["message_id"] != msg or existing["activation_digest"] != str(receipt.get("activation_digest") or ""):
            raise ActivationProvenanceError("provenance replay conflict")
        return target

    payload = {
        "schema_version": SCHEMA_V1,
        "recorded_at": recorded_at or datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "activation_request_id": request_id,
        "activation_digest": str(receipt.get("activation_digest") or ""),
        "result_status": str(receipt.get("result_status") or ""),
        "canonical_job_path": str(receipt.get("canonical_job_path") or ""),
        "authority_digest": str(receipt.get("authority_digest") or ""),
        "executable_authority_bundle_digest": str(receipt.get("executable_authority_bundle_digest") or ""),
        "executor_component": str(executor_component or ""),
        "control_path": str(control_path or ""),
        "policy_ref": str(policy_ref or ""),
        "message_id": msg,
        "runtime_source_head": str(runtime_source_head or ""),
        "runtime_manifest_sha256": str(runtime_manifest_sha256 or ""),
        "replay_existing_receipt": bool(replay_existing_receipt),
    }
    value = validate_activation_provenance(_seal(payload))
    target_dir.mkdir(parents=True, exist_ok=True)
    if target_dir.is_symlink() or target.exists():
        raise ActivationProvenanceError("provenance output unsafe")
    atomic_write_json(target, value)
    return target
