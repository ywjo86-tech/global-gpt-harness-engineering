"""Read-only admission contract for Lifecycle V2 P2 -> P3 canary promotion.

This module grants no deployment, routing, runtime-current, migration, service-manager,
or side-effect authority. V1 admits exactly one fresh-activation canary candidate for
DRY_RUN evaluation only after caller-supplied read-only evidence matches the sealed
request and proves the predecessor remains serving.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any, Mapping


LIFECYCLE_V2_P3_PROMOTION_ADMISSION_SCHEMA = (
    "orchestration.lifecycle-v2-p3-promotion-admission-request.v1"
)
LIFECYCLE_V2_P3_PROMOTION_ADMISSION_EVIDENCE_SCHEMA = (
    "orchestration.lifecycle-v2-p3-promotion-admission-evidence.v1"
)
LIFECYCLE_V2_P3_PROMOTION_ADMISSION_RESULT_SCHEMA = (
    "orchestration.lifecycle-v2-p3-promotion-admission-result.v1"
)

_REQUEST_FIELDS = {
    "schema_version",
    "request_id",
    "project_alias",
    "expected_branch",
    "expected_head",
    "successor_profile",
    "current_phase",
    "requested_phase",
    "candidate_run_id",
    "candidate_run_origin",
    "approval_policy_ref",
    "approval_policy_digest",
    "mode",
    "predecessor_serving_required",
    "predecessor_quiesce_requested",
    "runtime_current_switch_requested",
    "existing_run_migration_requested",
    "canary_scope",
}
_EVIDENCE_FIELDS = {
    "schema_version",
    "project_alias",
    "observed_branch",
    "observed_head",
    "observed_successor_profile",
    "candidate_run_id",
    "candidate_run_registration_state",
    "predecessor_serving",
    "runtime_current_points_to_predecessor",
    "approved_policy_ref",
    "approved_policy_digest",
}
_SAFE_ID = re.compile(r"[A-Za-z0-9._:-]{1,200}\Z")
_SAFE_BRANCH = re.compile(r"[A-Za-z0-9._/-]{1,240}\Z")
_SHA1 = re.compile(r"[0-9a-f]{40}\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_ALLOWED_RUN_REGISTRATION_STATES = {"ABSENT", "REGISTERED", "IN_PROGRESS", "COMPLETED"}


class LifecycleV2P3PromotionAdmissionError(ValueError):
    pass


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def _sha256(value: object) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _safe_id(value: object, label: str) -> str:
    text = str(value or "")
    if not _SAFE_ID.fullmatch(text) or ".." in text:
        raise LifecycleV2P3PromotionAdmissionError(f"invalid {label}")
    return text


def _safe_branch(value: object, label: str = "expected branch") -> str:
    text = str(value or "")
    if (
        not _SAFE_BRANCH.fullmatch(text)
        or ".." in text
        or "//" in text
        or text.startswith("/")
        or text.endswith("/")
        or any(
            part.startswith(".") or part.endswith(".") or part.endswith(".lock")
            for part in text.split("/")
        )
    ):
        raise LifecycleV2P3PromotionAdmissionError(f"invalid {label}")
    return text


def _sha1(value: object, label: str) -> str:
    text = str(value or "")
    if not _SHA1.fullmatch(text):
        raise LifecycleV2P3PromotionAdmissionError(f"invalid {label}")
    return text


def _digest(value: object, label: str) -> str:
    text = str(value or "")
    if not _SHA256.fullmatch(text):
        raise LifecycleV2P3PromotionAdmissionError(f"invalid {label}")
    return text


def _bool(value: object, label: str) -> bool:
    if not isinstance(value, bool):
        raise LifecycleV2P3PromotionAdmissionError(f"invalid {label}")
    return value


def _canary_scope(value: object) -> tuple[str, ...]:
    if not isinstance(value, list) or len(value) != 1:
        raise LifecycleV2P3PromotionAdmissionError(
            "canary scope must contain exactly one fresh candidate run"
        )
    return (_safe_id(value[0], "canary scope run ID"),)


@dataclass(frozen=True, slots=True)
class LifecycleV2P3PromotionAdmissionRequest:
    schema_version: str
    request_id: str
    project_alias: str
    expected_branch: str
    expected_head: str
    successor_profile: str
    current_phase: str
    requested_phase: str
    candidate_run_id: str
    candidate_run_origin: str
    approval_policy_ref: str
    approval_policy_digest: str
    mode: str
    predecessor_serving_required: bool
    predecessor_quiesce_requested: bool
    runtime_current_switch_requested: bool
    existing_run_migration_requested: bool
    canary_scope: tuple[str, ...]

    @classmethod
    def from_mapping(
        cls,
        raw: Mapping[str, Any],
    ) -> "LifecycleV2P3PromotionAdmissionRequest":
        if not isinstance(raw, Mapping):
            raise LifecycleV2P3PromotionAdmissionError("request must be an object")
        if "canary_scope" not in raw:
            raise LifecycleV2P3PromotionAdmissionError("canary scope is required")
        if "predecessor_quiesce_requested" not in raw:
            raise LifecycleV2P3PromotionAdmissionError(
                "predecessor quiesce request flag is required"
            )
        if set(raw) != _REQUEST_FIELDS:
            raise LifecycleV2P3PromotionAdmissionError("request fields mismatch")
        if raw.get("schema_version") != LIFECYCLE_V2_P3_PROMOTION_ADMISSION_SCHEMA:
            raise LifecycleV2P3PromotionAdmissionError("unsupported request schema")

        request = cls(
            schema_version=LIFECYCLE_V2_P3_PROMOTION_ADMISSION_SCHEMA,
            request_id=_safe_id(raw["request_id"], "request ID"),
            project_alias=_safe_id(raw["project_alias"], "project alias"),
            expected_branch=_safe_branch(raw["expected_branch"]),
            expected_head=_sha1(raw["expected_head"], "expected head"),
            successor_profile=_safe_id(raw["successor_profile"], "successor profile"),
            current_phase=_safe_id(raw["current_phase"], "current phase"),
            requested_phase=_safe_id(raw["requested_phase"], "requested phase"),
            candidate_run_id=_safe_id(raw["candidate_run_id"], "candidate run ID"),
            candidate_run_origin=_safe_id(raw["candidate_run_origin"], "candidate run origin"),
            approval_policy_ref=_safe_id(raw["approval_policy_ref"], "approval policy ref"),
            approval_policy_digest=_digest(raw["approval_policy_digest"], "approval policy digest"),
            mode=_safe_id(raw["mode"], "mode"),
            predecessor_serving_required=_bool(
                raw["predecessor_serving_required"],
                "predecessor serving requirement",
            ),
            predecessor_quiesce_requested=_bool(
                raw["predecessor_quiesce_requested"],
                "predecessor quiesce request",
            ),
            runtime_current_switch_requested=_bool(
                raw["runtime_current_switch_requested"],
                "runtime-current switch request",
            ),
            existing_run_migration_requested=_bool(
                raw["existing_run_migration_requested"],
                "existing run migration request",
            ),
            canary_scope=_canary_scope(raw["canary_scope"]),
        )
        request._validate_boundary()
        return request

    def _validate_boundary(self) -> None:
        if self.mode != "DRY_RUN":
            raise LifecycleV2P3PromotionAdmissionError("P3 admission v1 is DRY_RUN only")
        if self.current_phase != "P2_SIDE_BY_SIDE":
            raise LifecycleV2P3PromotionAdmissionError("current phase must be P2_SIDE_BY_SIDE")
        if self.requested_phase != "P3_CANARY":
            raise LifecycleV2P3PromotionAdmissionError("requested phase must be P3_CANARY")
        if self.successor_profile != "lifecycle-v2-p2":
            raise LifecycleV2P3PromotionAdmissionError("unsupported successor profile")
        if self.candidate_run_origin != "FRESH_ACTIVATION":
            raise LifecycleV2P3PromotionAdmissionError("P3 canary requires a fresh activation")
        if not self.predecessor_serving_required:
            raise LifecycleV2P3PromotionAdmissionError("predecessor must remain serving")
        if self.predecessor_quiesce_requested:
            raise LifecycleV2P3PromotionAdmissionError(
                "predecessor quiesce is outside P3 admission"
            )
        if self.runtime_current_switch_requested:
            raise LifecycleV2P3PromotionAdmissionError(
                "runtime-current switch is outside P3 admission"
            )
        if self.existing_run_migration_requested:
            raise LifecycleV2P3PromotionAdmissionError(
                "existing run migration is outside P3 admission"
            )
        if self.canary_scope != (self.candidate_run_id,):
            raise LifecycleV2P3PromotionAdmissionError(
                "canary scope must contain exactly the fresh candidate run"
            )

    @property
    def request_digest(self) -> str:
        return _sha256(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "request_id": self.request_id,
            "project_alias": self.project_alias,
            "expected_branch": self.expected_branch,
            "expected_head": self.expected_head,
            "successor_profile": self.successor_profile,
            "current_phase": self.current_phase,
            "requested_phase": self.requested_phase,
            "candidate_run_id": self.candidate_run_id,
            "candidate_run_origin": self.candidate_run_origin,
            "approval_policy_ref": self.approval_policy_ref,
            "approval_policy_digest": self.approval_policy_digest,
            "mode": self.mode,
            "predecessor_serving_required": self.predecessor_serving_required,
            "predecessor_quiesce_requested": self.predecessor_quiesce_requested,
            "runtime_current_switch_requested": self.runtime_current_switch_requested,
            "existing_run_migration_requested": self.existing_run_migration_requested,
            "canary_scope": list(self.canary_scope),
        }


@dataclass(frozen=True, slots=True)
class LifecycleV2P3PromotionAdmissionEvidence:
    schema_version: str
    project_alias: str
    observed_branch: str
    observed_head: str
    observed_successor_profile: str
    candidate_run_id: str
    candidate_run_registration_state: str
    predecessor_serving: bool
    runtime_current_points_to_predecessor: bool
    approved_policy_ref: str
    approved_policy_digest: str

    @classmethod
    def from_mapping(
        cls,
        raw: Mapping[str, Any],
    ) -> "LifecycleV2P3PromotionAdmissionEvidence":
        if not isinstance(raw, Mapping):
            raise LifecycleV2P3PromotionAdmissionError("evidence must be an object")
        if set(raw) != _EVIDENCE_FIELDS:
            raise LifecycleV2P3PromotionAdmissionError("evidence fields mismatch")
        if raw.get("schema_version") != LIFECYCLE_V2_P3_PROMOTION_ADMISSION_EVIDENCE_SCHEMA:
            raise LifecycleV2P3PromotionAdmissionError("unsupported evidence schema")

        state = _safe_id(
            raw["candidate_run_registration_state"],
            "candidate run registration state",
        )
        if state not in _ALLOWED_RUN_REGISTRATION_STATES:
            raise LifecycleV2P3PromotionAdmissionError(
                "unsupported candidate run registration state"
            )
        return cls(
            schema_version=LIFECYCLE_V2_P3_PROMOTION_ADMISSION_EVIDENCE_SCHEMA,
            project_alias=_safe_id(raw["project_alias"], "observed project alias"),
            observed_branch=_safe_branch(raw["observed_branch"], "observed branch"),
            observed_head=_sha1(raw["observed_head"], "observed head"),
            observed_successor_profile=_safe_id(
                raw["observed_successor_profile"],
                "observed successor profile",
            ),
            candidate_run_id=_safe_id(raw["candidate_run_id"], "observed candidate run ID"),
            candidate_run_registration_state=state,
            predecessor_serving=_bool(raw["predecessor_serving"], "predecessor serving state"),
            runtime_current_points_to_predecessor=_bool(
                raw["runtime_current_points_to_predecessor"],
                "runtime-current predecessor binding",
            ),
            approved_policy_ref=_safe_id(raw["approved_policy_ref"], "approved policy ref"),
            approved_policy_digest=_digest(
                raw["approved_policy_digest"],
                "approved policy digest",
            ),
        )

    @property
    def evidence_digest(self) -> str:
        return _sha256(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "project_alias": self.project_alias,
            "observed_branch": self.observed_branch,
            "observed_head": self.observed_head,
            "observed_successor_profile": self.observed_successor_profile,
            "candidate_run_id": self.candidate_run_id,
            "candidate_run_registration_state": self.candidate_run_registration_state,
            "predecessor_serving": self.predecessor_serving,
            "runtime_current_points_to_predecessor": self.runtime_current_points_to_predecessor,
            "approved_policy_ref": self.approved_policy_ref,
            "approved_policy_digest": self.approved_policy_digest,
        }


@dataclass(frozen=True, slots=True)
class LifecycleV2P3PromotionAdmissionResult:
    schema_version: str
    request_id: str
    project_alias: str
    request_digest: str
    evidence_digest: str
    status: str
    mode: str
    canary_run_id: str
    mutation_authorized: bool
    runtime_current_switch_authorized: bool
    existing_run_migration_authorized: bool
    predecessor_shutdown_authorized: bool
    admission_digest: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "request_id": self.request_id,
            "project_alias": self.project_alias,
            "request_digest": self.request_digest,
            "evidence_digest": self.evidence_digest,
            "status": self.status,
            "mode": self.mode,
            "canary_run_id": self.canary_run_id,
            "mutation_authorized": self.mutation_authorized,
            "runtime_current_switch_authorized": self.runtime_current_switch_authorized,
            "existing_run_migration_authorized": self.existing_run_migration_authorized,
            "predecessor_shutdown_authorized": self.predecessor_shutdown_authorized,
            "admission_digest": self.admission_digest,
        }


def _require_equal(actual: object, expected: object, label: str) -> None:
    if actual != expected:
        raise LifecycleV2P3PromotionAdmissionError(f"{label} mismatch")


def evaluate_p3_promotion_admission(
    request: LifecycleV2P3PromotionAdmissionRequest,
    evidence: LifecycleV2P3PromotionAdmissionEvidence | None,
) -> LifecycleV2P3PromotionAdmissionResult:
    if not isinstance(request, LifecycleV2P3PromotionAdmissionRequest):
        raise LifecycleV2P3PromotionAdmissionError("validated P3 admission request required")
    if not isinstance(evidence, LifecycleV2P3PromotionAdmissionEvidence):
        raise LifecycleV2P3PromotionAdmissionError("validated P3 admission evidence required")

    _require_equal(evidence.project_alias, request.project_alias, "project alias")
    _require_equal(evidence.observed_branch, request.expected_branch, "successor branch")
    _require_equal(evidence.observed_head, request.expected_head, "successor head")
    _require_equal(
        evidence.observed_successor_profile,
        request.successor_profile,
        "successor profile",
    )
    _require_equal(evidence.candidate_run_id, request.candidate_run_id, "candidate run ID")
    _require_equal(
        evidence.candidate_run_registration_state,
        "ABSENT",
        "candidate run registration state",
    )
    _require_equal(evidence.predecessor_serving, True, "predecessor serving state")
    _require_equal(
        evidence.runtime_current_points_to_predecessor,
        True,
        "runtime-current predecessor binding",
    )
    _require_equal(evidence.approved_policy_ref, request.approval_policy_ref, "approval policy ref")
    _require_equal(
        evidence.approved_policy_digest,
        request.approval_policy_digest,
        "approval policy digest",
    )

    result_fields = {
        "schema_version": LIFECYCLE_V2_P3_PROMOTION_ADMISSION_RESULT_SCHEMA,
        "request_id": request.request_id,
        "project_alias": request.project_alias,
        "request_digest": request.request_digest,
        "evidence_digest": evidence.evidence_digest,
        "status": "P3_CANARY_ADMISSION_READY",
        "mode": request.mode,
        "canary_run_id": request.candidate_run_id,
        "mutation_authorized": False,
        "runtime_current_switch_authorized": False,
        "existing_run_migration_authorized": False,
        "predecessor_shutdown_authorized": False,
    }
    return LifecycleV2P3PromotionAdmissionResult(
        **result_fields,
        admission_digest=_sha256(result_fields),
    )
