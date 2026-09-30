"""Verify a scoped owner decision from a separately authenticated approval issuer.

This verifier cannot issue an approval. The private signing key must remain in
the user-authenticated approval service, outside OCP and its operator account.
"""
from __future__ import annotations

import base64
import hashlib
import json
import re
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from .full_plan_owner_delegation import EXCLUDED, FIELDS as SCOPE_FIELDS, SCHEMA as SCOPE_SCHEMA

SCHEMA = "orchestration.full-plan-owner-attestation.v1"
FIELDS = {"schema_version", "issuer", "audience", "decision_id", "owner_actor_id",
          "confirmation_id", "scope", "issued_at", "expires_at"}
ENVELOPE_FIELDS = {"payload", "signature"}
SAFE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,199}\Z")
SHA = re.compile(r"[0-9a-f]{64}\Z")
HEAD = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")


class OwnerAttestationError(ValueError):
    pass


@dataclass(frozen=True)
class VerifiedOwnerAttestation:
    decision_id: str
    owner_actor_id: str
    confirmation_id: str
    scope_sha256: str
    gate_ids: tuple[str, ...]
    expires_at: str


def _time(value: object) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise OwnerAttestationError("ATTESTATION_TIME_INVALID")
    try:
        return datetime.fromisoformat(value[:-1] + "+00:00").astimezone(timezone.utc)
    except ValueError as exc:
        raise OwnerAttestationError("ATTESTATION_TIME_INVALID") from exc


def _canonical(value: object) -> bytes:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"),
                          ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise OwnerAttestationError("ATTESTATION_ENCODING_INVALID") from exc


def verify_owner_attestation(
    envelope: Mapping[str, Any], *, public_key_path: str | Path,
    public_key_sha256: str, expected_issuer: str, expected_audience: str,
    expected_owner_actor_id: str, now: datetime,
) -> VerifiedOwnerAttestation:
    """Validate a signed decision; tool arguments alone never grant authority."""
    if not isinstance(envelope, Mapping) or set(envelope) != ENVELOPE_FIELDS:
        raise OwnerAttestationError("ATTESTATION_FIELDS_INVALID")
    payload = envelope["payload"]
    if not isinstance(payload, Mapping) or set(payload) != FIELDS:
        raise OwnerAttestationError("ATTESTATION_FIELDS_INVALID")
    scope = payload["scope"]
    if not isinstance(scope, Mapping) or set(scope) != SCOPE_FIELDS:
        raise OwnerAttestationError("ATTESTATION_SCOPE_INVALID")
    if (payload["schema_version"] != SCHEMA
            or payload["issuer"] != expected_issuer
            or payload["audience"] != expected_audience
            or payload["owner_actor_id"] != expected_owner_actor_id
            or not isinstance(expected_owner_actor_id, str)
            or not expected_owner_actor_id.isdecimal()
            or any(not isinstance(payload[k], str) or not SAFE.fullmatch(payload[k])
                   for k in ("decision_id", "confirmation_id"))
            or scope["schema_version"] != SCOPE_SCHEMA
            or scope["decision_id"] != payload["decision_id"]
            or any(not isinstance(scope[k], str) or not SAFE.fullmatch(scope[k])
                   for k in ("project_id",))
            or any(not isinstance(scope[k], str) or not SHA.fullmatch(scope[k])
                   for k in ("plan_sha256", "spec_sha256", "runtime_sha256"))
            or not isinstance(scope["source_head"], str)
            or not HEAD.fullmatch(scope["source_head"])
            or not isinstance(scope["gate_ids"], list) or not scope["gate_ids"]
            or any(not isinstance(g, str) or not SAFE.fullmatch(g) for g in scope["gate_ids"])
            or len(set(scope["gate_ids"])) != len(scope["gate_ids"])
            or not isinstance(scope["excluded_actions"], list)
            or len(scope["excluded_actions"]) != len(EXCLUDED)
            or set(scope["excluded_actions"]) != EXCLUDED):
        raise OwnerAttestationError("ATTESTATION_SCOPE_INVALID")
    issued, expires = _time(payload["issued_at"]), _time(payload["expires_at"])
    scope_issued, scope_expires = _time(scope["issued_at"]), _time(scope["expires_at"])
    if (now.tzinfo is None or not issued <= now < expires
            or not scope_issued <= issued or expires > scope_expires
            or (expires - issued).total_seconds() > 86400):
        raise OwnerAttestationError("ATTESTATION_EXPIRED")
    key = Path(public_key_path)
    if (not isinstance(public_key_sha256, str) or not SHA.fullmatch(public_key_sha256)
            or not key.is_absolute() or key.is_symlink() or not key.is_file()
            or hashlib.sha256(key.read_bytes()).hexdigest() != public_key_sha256):
        raise OwnerAttestationError("ATTESTATION_TRUST_ANCHOR_INVALID")
    signature = envelope["signature"]
    if not isinstance(signature, str) or not re.fullmatch(r"[A-Za-z0-9_-]{86}", signature):
        raise OwnerAttestationError("ATTESTATION_SIGNATURE_INVALID")
    try:
        raw = base64.urlsafe_b64decode(signature + "==")
    except ValueError as exc:
        raise OwnerAttestationError("ATTESTATION_SIGNATURE_INVALID") from exc
    if len(raw) != 64 or base64.urlsafe_b64encode(raw).rstrip(b"=").decode() != signature:
        raise OwnerAttestationError("ATTESTATION_SIGNATURE_INVALID")
    with tempfile.TemporaryDirectory(prefix="ocp-attestation-") as directory:
        data = Path(directory) / "payload.json"
        sig = Path(directory) / "signature.bin"
        data.write_bytes(_canonical(payload))
        sig.write_bytes(raw)
        try:
            result = subprocess.run(
                ["openssl", "pkeyutl", "-verify", "-pubin", "-inkey", str(key),
                 "-rawin", "-in", str(data), "-sigfile", str(sig)],
                capture_output=True, check=False, timeout=10,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise OwnerAttestationError("ATTESTATION_VERIFIER_UNAVAILABLE") from exc
    if result.returncode != 0:
        raise OwnerAttestationError("ATTESTATION_SIGNATURE_INVALID")
    return VerifiedOwnerAttestation(
        decision_id=payload["decision_id"], owner_actor_id=expected_owner_actor_id,
        confirmation_id=payload["confirmation_id"],
        scope_sha256=hashlib.sha256(_canonical(scope)).hexdigest(),
        gate_ids=tuple(scope["gate_ids"]), expires_at=payload["expires_at"],
    )

STATUS_SCHEMA = "orchestration.full-plan-owner-status.v1"
STATUS_FIELDS = {"schema_version", "issuer", "audience", "decision_id", "scope_sha256",
                 "activation_id", "challenge", "active", "checked_at"}


def verify_owner_status(
    envelope: Mapping[str, Any], *, public_key_path: str | Path,
    public_key_sha256: str, expected_issuer: str, expected_audience: str,
    expected_decision_id: str, expected_scope_sha256: str,
    expected_activation_id: str, expected_challenge: str, now: datetime,
) -> None:
    """Require a signed, fresh, active issuer answer for this exact attempt."""
    if not isinstance(envelope, Mapping) or set(envelope) != ENVELOPE_FIELDS:
        raise OwnerAttestationError("STATUS_FIELDS_INVALID")
    payload = envelope["payload"]
    if not isinstance(payload, Mapping) or set(payload) != STATUS_FIELDS:
        raise OwnerAttestationError("STATUS_FIELDS_INVALID")
    if (payload["schema_version"] != STATUS_SCHEMA
            or payload["issuer"] != expected_issuer
            or payload["audience"] != expected_audience
            or payload["decision_id"] != expected_decision_id
            or payload["scope_sha256"] != expected_scope_sha256
            or payload["activation_id"] != expected_activation_id
            or payload["challenge"] != expected_challenge
            or type(payload["active"]) is not bool
            or not payload["active"]):
        raise OwnerAttestationError("STATUS_INACTIVE_OR_MISMATCH")
    checked_at = _time(payload["checked_at"])
    if (now.tzinfo is None or abs((now - checked_at).total_seconds()) > 30):
        raise OwnerAttestationError("STATUS_STALE")
    key = Path(public_key_path)
    if (not isinstance(public_key_sha256, str) or not SHA.fullmatch(public_key_sha256)
            or not key.is_absolute() or key.is_symlink() or not key.is_file()
            or hashlib.sha256(key.read_bytes()).hexdigest() != public_key_sha256):
        raise OwnerAttestationError("ATTESTATION_TRUST_ANCHOR_INVALID")
    signature = envelope["signature"]
    if not isinstance(signature, str) or not re.fullmatch(r"[A-Za-z0-9_-]{86}", signature):
        raise OwnerAttestationError("STATUS_SIGNATURE_INVALID")
    try:
        raw = base64.urlsafe_b64decode(signature + "==")
    except ValueError as exc:
        raise OwnerAttestationError("STATUS_SIGNATURE_INVALID") from exc
    if len(raw) != 64 or base64.urlsafe_b64encode(raw).rstrip(b"=").decode() != signature:
        raise OwnerAttestationError("STATUS_SIGNATURE_INVALID")
    with tempfile.TemporaryDirectory(prefix="ocp-status-") as directory:
        data = Path(directory) / "payload.json"
        sig = Path(directory) / "signature.bin"
        data.write_bytes(_canonical(payload))
        sig.write_bytes(raw)
        try:
            result = subprocess.run(
                ["openssl", "pkeyutl", "-verify", "-pubin", "-inkey", str(key),
                 "-rawin", "-in", str(data), "-sigfile", str(sig)],
                capture_output=True, check=False, timeout=10)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise OwnerAttestationError("STATUS_VERIFIER_UNAVAILABLE") from exc
    if result.returncode != 0:
        raise OwnerAttestationError("STATUS_SIGNATURE_INVALID")
