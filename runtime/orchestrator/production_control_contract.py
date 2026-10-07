from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from typing import Any, Mapping

PRODUCTION_CONTROL_ACTION_SCHEMA_V1 = "orchestration.production-control-action-request.v1"
PRODUCTION_CONTROL_RESULT_SCHEMA_V1 = "orchestration.production-control-action-result.v1"

RETIRE_FULL_PLAN_RUN = "RETIRE_FULL_PLAN_RUN"
SYNC_OPERATIONAL_RUNTIME_IDENTITY = "SYNC_OPERATIONAL_RUNTIME_IDENTITY"
OCP_QUIESCE = "OCP_QUIESCE"
P4_CUTOVER = "P4_CUTOVER"
OCP_RESUME = "OCP_RESUME"
POST_CHANGE_VALIDATE = "POST_CHANGE_VALIDATE"

ACTION_ALLOWLIST = frozenset({
    RETIRE_FULL_PLAN_RUN,
    SYNC_OPERATIONAL_RUNTIME_IDENTITY,
    OCP_QUIESCE,
    P4_CUTOVER,
    OCP_RESUME,
    POST_CHANGE_VALIDATE,
})
RESULT_STATUSES = frozenset({"PREPARED", "APPLIED", "VERIFIED", "ROLLED_BACK", "BLOCKED"})
OCP_UNIT_ALLOWLIST = frozenset({
    "ocpv2.service",
    "ocpv2.timer",
    "ocpv2-lifecycle-v2-p2.service",
    "ocpv2-lifecycle-v2-p2.timer",
})
_SHA40 = re.compile(r"[0-9a-f]{40}\Z")
_SHA64 = re.compile(r"[0-9a-f]{64}\Z")
_SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,199}\Z")

_REQUEST_FIELDS = {
    "schema_version",
    "request_id",
    "project_id",
    "action",
    "approval_ref",
    "activation_id",
    "plan_digest",
    "approval_proof_path",
    "approval_proof_sha256",
    "expected_state_sha256",
    "expected_runtime_source_head",
    "target_runtime_source_head",
    "target_runtime_manifest_sha256",
    "idempotency_key",
    "parameters",
}

_PARAMETER_FIELDS = {
    RETIRE_FULL_PLAN_RUN: {"run_id", "expected_terminal_reason"},
    SYNC_OPERATIONAL_RUNTIME_IDENTITY: {
        "predecessor_runtime_source_head",
        "target_runtime_source_head",
    },
    OCP_QUIESCE: {"units"},
    P4_CUTOVER: {
        "admission_digest",
        "qualification_digest",
        "p4_entry_digest",
        "cutover_admission_digest",
    },
    OCP_RESUME: {"units"},
    POST_CHANGE_VALIDATE: {"expected_runtime_source_head"},
}


class ProductionControlContractError(ValueError):
    pass


def _canonical(value: object) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _safe_id(value: object, label: str) -> str:
    text = str(value or "")
    if not _SAFE_ID.fullmatch(text) or ".." in text:
        raise ProductionControlContractError(f"{label} invalid")
    return text


def _sha64(value: object, label: str) -> str:
    text = str(value or "")
    if not _SHA64.fullmatch(text):
        raise ProductionControlContractError(f"{label} invalid")
    return text


def _sha40(value: object, label: str) -> str:
    text = str(value or "")
    if not _SHA40.fullmatch(text):
        raise ProductionControlContractError(f"{label} invalid")
    return text


def _proof_path(value: object) -> str:
    text = str(value or "")
    if (
        not text
        or text.startswith("/")
        or "\\" in text
        or ".." in text.split("/")
        or any(not part for part in text.split("/"))
    ):
        raise ProductionControlContractError("approval proof path invalid")
    return text


def _parameters(action: str, value: object) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ProductionControlContractError("parameters must be an object")
    params = dict(value)
    expected = _PARAMETER_FIELDS[action]
    if set(params) != expected:
        raise ProductionControlContractError("parameters fields mismatch")

    if action == RETIRE_FULL_PLAN_RUN:
        params["run_id"] = _safe_id(params["run_id"], "run_id")
        params["expected_terminal_reason"] = _safe_id(
            params["expected_terminal_reason"], "expected_terminal_reason"
        )
    elif action == SYNC_OPERATIONAL_RUNTIME_IDENTITY:
        params["predecessor_runtime_source_head"] = _sha40(
            params["predecessor_runtime_source_head"], "predecessor runtime source head"
        )
        params["target_runtime_source_head"] = _sha40(
            params["target_runtime_source_head"], "target runtime source head"
        )
    elif action in {OCP_QUIESCE, OCP_RESUME}:
        units = params.get("units")
        if (
            not isinstance(units, list)
            or not units
            or len(units) != len(set(units))
            or any(unit not in OCP_UNIT_ALLOWLIST for unit in units)
        ):
            raise ProductionControlContractError("OCP unit allowlist mismatch")
        params["units"] = list(units)
    elif action == P4_CUTOVER:
        for key in sorted(expected):
            params[key] = _sha64(params[key], key)
    elif action == POST_CHANGE_VALIDATE:
        params["expected_runtime_source_head"] = _sha40(
            params["expected_runtime_source_head"], "expected runtime source head"
        )
    return params


@dataclass(frozen=True, slots=True)
class ProductionControlActionRequestV1:
    schema_version: str
    request_id: str
    project_id: str
    action: str
    approval_ref: str
    activation_id: str
    plan_digest: str
    approval_proof_path: str
    approval_proof_sha256: str
    expected_state_sha256: str
    expected_runtime_source_head: str
    target_runtime_source_head: str
    target_runtime_manifest_sha256: str
    idempotency_key: str
    parameters: Mapping[str, Any]

    @classmethod
    def from_mapping(
        cls, value: Mapping[str, Any]
    ) -> "ProductionControlActionRequestV1":
        if not isinstance(value, Mapping) or set(value) != _REQUEST_FIELDS:
            raise ProductionControlContractError("request fields mismatch")
        if value.get("schema_version") != PRODUCTION_CONTROL_ACTION_SCHEMA_V1:
            raise ProductionControlContractError("request schema mismatch")
        action = str(value.get("action") or "")
        if action not in ACTION_ALLOWLIST:
            raise ProductionControlContractError("action not allowed")
        request = cls(
            schema_version=PRODUCTION_CONTROL_ACTION_SCHEMA_V1,
            request_id=_safe_id(value["request_id"], "request_id"),
            project_id=_safe_id(value["project_id"], "project_id"),
            action=action,
            approval_ref=_safe_id(value["approval_ref"], "approval_ref"),
            activation_id=_safe_id(value["activation_id"], "activation_id"),
            plan_digest=_sha64(value["plan_digest"], "plan_digest"),
            approval_proof_path=_proof_path(value["approval_proof_path"]),
            approval_proof_sha256=_sha64(
                value["approval_proof_sha256"], "approval_proof_sha256"
            ),
            expected_state_sha256=_sha64(
                value["expected_state_sha256"], "expected_state_sha256"
            ),
            expected_runtime_source_head=_sha40(
                value["expected_runtime_source_head"], "expected_runtime_source_head"
            ),
            target_runtime_source_head=_sha40(
                value["target_runtime_source_head"], "target_runtime_source_head"
            ),
            target_runtime_manifest_sha256=_sha64(
                value["target_runtime_manifest_sha256"],
                "target_runtime_manifest_sha256",
            ),
            idempotency_key=_safe_id(value["idempotency_key"], "idempotency_key"),
            parameters=_parameters(action, value["parameters"]),
        )
        request._validate_cross_bindings()
        return request

    def _validate_cross_bindings(self) -> None:
        params = dict(self.parameters)
        if self.action == SYNC_OPERATIONAL_RUNTIME_IDENTITY:
            if (
                params["predecessor_runtime_source_head"]
                != self.expected_runtime_source_head
                or params["target_runtime_source_head"]
                != self.target_runtime_source_head
            ):
                raise ProductionControlContractError("runtime identity binding mismatch")
        elif self.action == POST_CHANGE_VALIDATE:
            if params["expected_runtime_source_head"] != self.target_runtime_source_head:
                raise ProductionControlContractError("validation runtime binding mismatch")

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["parameters"] = dict(self.parameters)
        return value

    @property
    def request_digest(self) -> str:
        return _digest(self.to_dict())


@dataclass(frozen=True, slots=True)
class ProductionControlActionResultV1:
    schema_version: str
    request_id: str
    action: str
    status: str
    result_class: str
    request_digest: str
    idempotency_key: str
    evidence_refs: tuple[str, ...] = ()
    evidence_digests: tuple[str, ...] = ()
    effect_digest: str = ""

    def __post_init__(self) -> None:
        if self.schema_version != PRODUCTION_CONTROL_RESULT_SCHEMA_V1:
            raise ProductionControlContractError("result schema mismatch")
        _safe_id(self.request_id, "request_id")
        if self.action not in ACTION_ALLOWLIST:
            raise ProductionControlContractError("result action invalid")
        if self.status not in RESULT_STATUSES:
            raise ProductionControlContractError("result status invalid")
        _safe_id(self.result_class, "result_class")
        _sha64(self.request_digest, "request_digest")
        _safe_id(self.idempotency_key, "idempotency_key")
        if len(self.evidence_refs) != len(self.evidence_digests):
            raise ProductionControlContractError("result evidence binding mismatch")
        for ref in self.evidence_refs:
            _safe_id(ref, "evidence_ref")
        for digest in self.evidence_digests:
            _sha64(digest, "evidence_digest")
        if self.effect_digest:
            _sha64(self.effect_digest, "effect_digest")

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["evidence_refs"] = list(self.evidence_refs)
        value["evidence_digests"] = list(self.evidence_digests)
        return value

    @property
    def result_digest(self) -> str:
        return _digest(self.to_dict())
