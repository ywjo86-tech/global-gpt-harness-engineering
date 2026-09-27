"""Create a validation-only receipt for an already admitted P3 candidate."""
from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping

from .p3_canary_validate_binding import (
    P3CanaryValidateBinding,
    P3CanaryValidateBindingError,
    validate_p3_canary_validate_binding,
)
from .p3_canary_validate_evidence import P3CanaryValidateEvidence


_SCHEMA = "orchestration.lifecycle-v2-p3-canary-validate-registration.v1"
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")


class P3CanaryValidateRegistrationError(ValueError):
    pass


def _canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _digest(value: object, label: str) -> str:
    text = str(value or "")
    if not _SHA256.fullmatch(text):
        raise P3CanaryValidateRegistrationError(f"invalid {label}")
    return text


@dataclass(frozen=True, slots=True)
class P3CanaryValidateRegistration:
    schema_version: str
    project_alias: str
    candidate_run_id: str
    admission_digest: str
    binding_digest: str
    evidence_digest: str
    status: str
    runtime_current_switch_authorized: bool
    predecessor_shutdown_authorized: bool
    existing_run_migration_authorized: bool
    successor_polling_authorized: bool
    execution_authorized: bool
    registration_digest: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> "P3CanaryValidateRegistration":
        if not isinstance(raw, Mapping) or set(raw) != set(cls.__dataclass_fields__):
            raise P3CanaryValidateRegistrationError("registration fields mismatch")
        unsigned = {key: raw[key] for key in cls.__dataclass_fields__ if key != "registration_digest"}
        registration = cls(
            schema_version=str(unsigned["schema_version"]),
            project_alias=str(unsigned["project_alias"]),
            candidate_run_id=str(unsigned["candidate_run_id"]),
            admission_digest=_digest(unsigned["admission_digest"], "admission digest"),
            binding_digest=_digest(unsigned["binding_digest"], "binding digest"),
            evidence_digest=_digest(unsigned["evidence_digest"], "evidence digest"),
            status=str(unsigned["status"]),
            runtime_current_switch_authorized=unsigned["runtime_current_switch_authorized"],
            predecessor_shutdown_authorized=unsigned["predecessor_shutdown_authorized"],
            existing_run_migration_authorized=unsigned["existing_run_migration_authorized"],
            successor_polling_authorized=unsigned["successor_polling_authorized"],
            execution_authorized=unsigned["execution_authorized"],
            registration_digest=_digest(raw["registration_digest"], "registration digest"),
        )
        if (
            registration.schema_version != _SCHEMA
            or registration.status != "P3_CANARY_VALIDATE_REGISTERED"
            or any(
                value is not False
                for value in (
                    registration.runtime_current_switch_authorized,
                    registration.predecessor_shutdown_authorized,
                    registration.existing_run_migration_authorized,
                    registration.successor_polling_authorized,
                    registration.execution_authorized,
                )
            )
        ):
            raise P3CanaryValidateRegistrationError("unsupported registration")
        material = asdict(registration)
        material.pop("registration_digest")
        if registration.registration_digest != hashlib.sha256(_canonical(material)).hexdigest():
            raise P3CanaryValidateRegistrationError("registration digest mismatch")
        return registration


def register_p3_canary_validate(
    *,
    state_root: str | Path,
    project_root: str | Path,
    binding: P3CanaryValidateBinding | Mapping[str, Any],
    evidence: Mapping[str, Any],
) -> P3CanaryValidateRegistration:
    """Persist no authority beyond validation-only registration for one candidate."""
    try:
        sealed_binding = validate_p3_canary_validate_binding(
            binding=binding,
            project_root=project_root,
            evidence=evidence,
        )
        sealed_evidence = P3CanaryValidateEvidence.from_mapping(dict(evidence))
    except (P3CanaryValidateBindingError, TypeError, ValueError) as exc:
        raise P3CanaryValidateRegistrationError("P3 validation binding rejected") from exc

    unsigned = {
        "schema_version": _SCHEMA,
        "project_alias": sealed_binding.project_alias,
        "candidate_run_id": sealed_binding.candidate_run_id,
        "admission_digest": sealed_binding.admission_digest,
        "binding_digest": sealed_binding.binding_digest,
        "evidence_digest": sealed_evidence.evidence_digest,
        "status": "P3_CANARY_VALIDATE_REGISTERED",
        "runtime_current_switch_authorized": False,
        "predecessor_shutdown_authorized": False,
        "existing_run_migration_authorized": False,
        "successor_polling_authorized": False,
        "execution_authorized": False,
    }
    receipt = P3CanaryValidateRegistration(
        **unsigned,
        registration_digest=hashlib.sha256(_canonical(unsigned)).hexdigest(),
    )
    root = Path(state_root).absolute()
    if root.is_symlink() or not root.is_dir() or root.resolve() != root:
        raise P3CanaryValidateRegistrationError("unsafe state root")
    receipts = root / "p3-canary-validate-registrations"
    receipts.mkdir(mode=0o700, exist_ok=True)
    if receipts.is_symlink() or not receipts.is_dir() or receipts.resolve() != receipts:
        raise P3CanaryValidateRegistrationError("unsafe registration root")
    path = receipts / f"{receipt.admission_digest}.json"
    payload = _canonical(receipt.to_dict())
    if path.exists():
        if path.is_symlink() or not path.is_file() or path.read_bytes() != payload:
            raise P3CanaryValidateRegistrationError("registration conflict")
        return receipt
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    except FileExistsError:
        raise P3CanaryValidateRegistrationError("registration conflict")
    with os.fdopen(fd, "wb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    return receipt
