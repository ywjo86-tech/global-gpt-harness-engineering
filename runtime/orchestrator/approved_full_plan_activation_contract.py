"""Closed request contract for executable approved Full Plan activation."""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

APPROVED_FULL_PLAN_ACTIVATION_REQUEST_SCHEMA = "orchestration.approved-full-plan-activation-request.v1"

_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_HEAD = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")
_SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,199}\Z")
_REQUEST_FIELDS = {
    "schema_version", "activation_request_id", "project_alias", "approved_plan", "approved_spec",
    "expected_branch", "expected_head", "runtime_release_digest", "approval_ref", "gate_bindings",
}
_ARTIFACT_FIELDS = {"path", "sha256"}
_LV_ARTIFACT_FIELDS = {"lv_id", "path", "sha256"}
_GATE_FIELDS = {
    "gate_id", "approval_evidence", "engine_requirement_evidence", "project_requirement_evidence_by_lv",
}


class ApprovedFullPlanActivationContractError(ValueError):
    pass


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _sha(value: object) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _safe_id(value: object, label: str) -> str:
    text = str(value or "")
    if not _SAFE_ID.fullmatch(text) or ".." in text:
        raise ApprovedFullPlanActivationContractError(f"{label.upper()}_INVALID")
    return text


def _digest(value: object, label: str) -> str:
    text = str(value or "")
    if not _SHA256.fullmatch(text):
        raise ApprovedFullPlanActivationContractError(f"{label.upper()}_INVALID")
    return text


def _safe_path(value: object, label: str) -> str:
    text = str(value or "")
    relative = Path(text)
    if not text or relative.is_absolute() or ".." in relative.parts or "\\" in text:
        raise ApprovedFullPlanActivationContractError(f"{label.upper()}_INVALID")
    return relative.as_posix()


def _branch(value: object) -> str:
    text = str(value or "")
    forbidden = set(" ~^:?*[\\")
    if (
        not text or text == "HEAD" or len(text.encode("utf-8")) > 244 or text.startswith("-")
        or text.startswith("/") or text.endswith("/") or text.endswith(".") or "//" in text
        or ".." in text or "@{" in text or any(ord(ch) < 32 or ord(ch) == 127 or ch in forbidden for ch in text)
        or any(part.endswith(".lock") or not part for part in text.split("/"))
    ):
        raise ApprovedFullPlanActivationContractError("EXPECTED_BRANCH_INVALID")
    return text


def _approval_ref(value: object) -> str:
    text = str(value or "")
    if not text.strip() or any(ord(ch) < 32 or ord(ch) == 127 for ch in text):
        raise ApprovedFullPlanActivationContractError("APPROVAL_REF_INVALID")
    return text


@dataclass(frozen=True, slots=True)
class ArtifactRefV1:
    path: str
    sha256: str

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any], *, label: str = "artifact") -> "ArtifactRefV1":
        if not isinstance(value, Mapping) or set(value) != _ARTIFACT_FIELDS:
            raise ApprovedFullPlanActivationContractError("FIELDS_MISMATCH")
        return cls(path=_safe_path(value["path"], f"{label}_path"), sha256=_digest(value["sha256"], f"{label}_sha256"))

    def to_dict(self) -> dict[str, str]:
        return {"path": self.path, "sha256": self.sha256}


@dataclass(frozen=True, slots=True)
class LVArtifactRefV1:
    lv_id: str
    path: str
    sha256: str

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "LVArtifactRefV1":
        if not isinstance(value, Mapping) or set(value) != _LV_ARTIFACT_FIELDS:
            raise ApprovedFullPlanActivationContractError("FIELDS_MISMATCH")
        return cls(
            lv_id=_safe_id(value["lv_id"], "LV"),
            path=_safe_path(value["path"], "LV_ARTIFACT_PATH"),
            sha256=_digest(value["sha256"], "LV_ARTIFACT_SHA256"),
        )

    def to_dict(self) -> dict[str, str]:
        return {"lv_id": self.lv_id, "path": self.path, "sha256": self.sha256}


@dataclass(frozen=True, slots=True)
class GateBindingRefV1:
    gate_id: str
    approval_evidence: ArtifactRefV1
    engine_requirement_evidence: ArtifactRefV1 | None
    project_requirement_evidence_by_lv: tuple[LVArtifactRefV1, ...]

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "GateBindingRefV1":
        if not isinstance(value, Mapping) or set(value) != _GATE_FIELDS:
            raise ApprovedFullPlanActivationContractError("FIELDS_MISMATCH")
        rows = value.get("project_requirement_evidence_by_lv")
        if not isinstance(rows, list):
            raise ApprovedFullPlanActivationContractError("FIELDS_MISMATCH")
        lv_refs = tuple(LVArtifactRefV1.from_mapping(item) for item in rows)
        lv_ids = tuple(item.lv_id for item in lv_refs)
        if len(lv_ids) != len(set(lv_ids)):
            raise ApprovedFullPlanActivationContractError("LV_IDS_DUPLICATE")
        engine_raw = value.get("engine_requirement_evidence")
        if engine_raw is not None and not isinstance(engine_raw, Mapping):
            raise ApprovedFullPlanActivationContractError("FIELDS_MISMATCH")
        return cls(
            gate_id=_safe_id(value["gate_id"], "GATE"),
            approval_evidence=ArtifactRefV1.from_mapping(value["approval_evidence"], label="gate_approval"),
            engine_requirement_evidence=None if engine_raw is None else ArtifactRefV1.from_mapping(engine_raw, label="engine_requirement"),
            project_requirement_evidence_by_lv=lv_refs,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "gate_id": self.gate_id,
            "approval_evidence": self.approval_evidence.to_dict(),
            "engine_requirement_evidence": None if self.engine_requirement_evidence is None else self.engine_requirement_evidence.to_dict(),
            "project_requirement_evidence_by_lv": [item.to_dict() for item in self.project_requirement_evidence_by_lv],
        }


@dataclass(frozen=True, slots=True)
class ApprovedFullPlanActivationRequestV1:
    schema_version: str
    activation_request_id: str
    project_alias: str
    approved_plan: ArtifactRefV1
    approved_spec: ArtifactRefV1
    expected_branch: str
    expected_head: str
    runtime_release_digest: str
    approval_ref: str
    gate_bindings: tuple[GateBindingRefV1, ...]

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "ApprovedFullPlanActivationRequestV1":
        if not isinstance(value, Mapping) or set(value) != _REQUEST_FIELDS:
            raise ApprovedFullPlanActivationContractError("FIELDS_MISMATCH")
        gates_raw = value.get("gate_bindings")
        if not isinstance(gates_raw, list) or not gates_raw:
            raise ApprovedFullPlanActivationContractError("GATE_BINDINGS_REQUIRED")
        gates = tuple(GateBindingRefV1.from_mapping(item) for item in gates_raw)
        gate_ids = tuple(item.gate_id for item in gates)
        if len(gate_ids) != len(set(gate_ids)):
            raise ApprovedFullPlanActivationContractError("GATE_IDS_DUPLICATE")
        head = str(value.get("expected_head") or "")
        if not _HEAD.fullmatch(head):
            raise ApprovedFullPlanActivationContractError("EXPECTED_HEAD_INVALID")
        schema = str(value.get("schema_version") or "")
        if schema != APPROVED_FULL_PLAN_ACTIVATION_REQUEST_SCHEMA:
            raise ApprovedFullPlanActivationContractError("SCHEMA_MISMATCH")
        return cls(
            schema_version=schema,
            activation_request_id=_safe_id(value["activation_request_id"], "ACTIVATION_REQUEST_ID"),
            project_alias=_safe_id(value["project_alias"], "PROJECT_ALIAS"),
            approved_plan=ArtifactRefV1.from_mapping(value["approved_plan"], label="approved_plan"),
            approved_spec=ArtifactRefV1.from_mapping(value["approved_spec"], label="approved_spec"),
            expected_branch=_branch(value["expected_branch"]),
            expected_head=head,
            runtime_release_digest=_digest(value["runtime_release_digest"], "RUNTIME_RELEASE_DIGEST"),
            approval_ref=_approval_ref(value["approval_ref"]),
            gate_bindings=gates,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "activation_request_id": self.activation_request_id,
            "project_alias": self.project_alias,
            "approved_plan": self.approved_plan.to_dict(),
            "approved_spec": self.approved_spec.to_dict(),
            "expected_branch": self.expected_branch,
            "expected_head": self.expected_head,
            "runtime_release_digest": self.runtime_release_digest,
            "approval_ref": self.approval_ref,
            "gate_bindings": [item.to_dict() for item in self.gate_bindings],
        }

    @property
    def request_digest(self) -> str:
        return _sha(self.to_dict())
