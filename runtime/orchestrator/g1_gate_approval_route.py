"""G1-only request-scoped Owner approval route for the OCPv2 issuer."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Protocol

from .gate_approval_issuance import (
    GateApprovalIssuer,
    GateApprovalIssuanceError,
    GateApprovalIssuanceRequest,
    _sha,
)


@dataclass(frozen=True, slots=True)
class G1GateApprovalProfile:
    project_id: str = "OCP-RDC-EXEC-CANARY-20260923-R2"
    project_alias: str = "ocp-rdc-exec-canary-20260923-r2-g1"
    gate_id: str = "GATE-001"
    expected_branch: str = "main"
    expected_head: str = "99dc2ff4081cae87bf2d777b8912d25760592b2f"
    plan_sha256: str = "a2d9b105bafa0e07819d1e35519f59e7e190b18b18223534451dca980241d3fa"
    requirements_sha256: str = "0119f3527f3987eeb4337e7a8c459516d33fb7a077180f448ae49d4a9898b001"
    project_requirement_lv_id: str = "TASK-001"
    project_requirement_evidence_path: str = "docs/req-task-001.json"
    project_requirement_evidence_sha256: str = "0119f3527f3987eeb4337e7a8c459516d33fb7a077180f448ae49d4a9898b001"
    owner_github_login: str = "ywjo86-tech"
    owner_actor_id: str = "235775273"
    global_owner_generation: int = 1
    global_owner_change_id: str = "AI-OFFICE-OWNER-INITIAL-20261023-01"
    global_owner_event_sha256: str = "d80f253b8de90ae9c886afa0848b7ffc64f8a9eb60140852c84c7f6355ccf017"
    project_owner_generation: int = 1
    project_owner_change_id: str = "OCP-RDC-EXEC-CANARY-20260923-R2-OWNER-BINDING-20261023-01"
    project_owner_event_sha256: str = "c58e85e9f8f225721ecfc63c806737553d01c3f748c1f1328b24083be5ebfd58"

    def owner_anchor_snapshot(self) -> dict[str, dict[str, Any]]:
        return {
            "global_owner_head": {
                "schema_version": "orchestration.ai-office-owner-authority-anchor.v1",
                "generation": self.global_owner_generation,
                "change_id": self.global_owner_change_id,
                "event_sha256": self.global_owner_event_sha256,
            },
            "project_owner_binding_head": {
                "schema_version": "orchestration.project-owner-binding-anchor.v2",
                "project_id": self.project_id,
                "generation": self.project_owner_generation,
                "change_id": self.project_owner_change_id,
                "event_sha256": self.project_owner_event_sha256,
            },
        }


G1_GATE_APPROVAL_PROFILE = G1GateApprovalProfile()
G1_OWNER_AUDIT_ANCHOR_SOCKET = "/run/ai-office-owner-anchor/anchor.sock"


class OwnerAnchorReader(Protocol):
    def read_owner_authority(self, project_id: str) -> dict[str, dict[str, Any]]: ...


class OwnerAuditAnchorError(GateApprovalIssuanceError):
    """The read-only Owner anchor did not match the approved G1 authority pins."""


class G1GateApprovalIssuer(GateApprovalIssuer):
    """Constrain the generic create-once issuer to the pinned G1 authority.

    The caller must construct this issuer with a G1-only alias registry. Its
    preflight also binds the independently served Owner-head snapshot into the
    exact digest that the Owner later approves.
    """

    def __init__(self, *, registry_root, mapping_root, harness_state_root,
                 owner_anchor_reader: OwnerAnchorReader,
                 profile: G1GateApprovalProfile = G1_GATE_APPROVAL_PROFILE) -> None:
        super().__init__(
            registry_root=registry_root,
            mapping_root=mapping_root,
            harness_state_root=harness_state_root,
        )
        if not callable(getattr(owner_anchor_reader, "read_owner_authority", None)):
            raise GateApprovalIssuanceError("OWNER_AUDIT_ANCHOR_CLIENT_REQUIRED")
        self.owner_anchor_reader = owner_anchor_reader
        self.profile = profile

    def _validate_request(self, request: GateApprovalIssuanceRequest) -> None:
        profile = self.profile
        project_requirement_refs = request.project_requirement_evidence_by_lv
        expected_project_requirement_ref = {
            "lv_id": profile.project_requirement_lv_id,
            "path": profile.project_requirement_evidence_path,
            "sha256": profile.project_requirement_evidence_sha256,
        }
        requirement_ref_matches = (
            isinstance(project_requirement_refs, list)
            and len(project_requirement_refs) == 1
            and isinstance(project_requirement_refs[0], Mapping)
            and dict(project_requirement_refs[0]) == expected_project_requirement_ref
        )
        if (
            request.project_alias != profile.project_alias
            or request.gate_id != profile.gate_id
            or request.expected_branch != profile.expected_branch
            or request.expected_head != profile.expected_head
            or request.requirements_sha256 != profile.requirements_sha256
            or not requirement_ref_matches
        ):
            raise GateApprovalIssuanceError("G1_REQUEST_BINDING_MISMATCH")

    def _read_owner_anchor(self) -> dict[str, dict[str, Any]]:
        profile = self.profile
        try:
            snapshot = self.owner_anchor_reader.read_owner_authority(profile.project_id)
        except Exception as exc:
            raise OwnerAuditAnchorError("OWNER_AUDIT_ANCHOR_UNAVAILABLE") from exc
        if snapshot != profile.owner_anchor_snapshot():
            raise OwnerAuditAnchorError("OWNER_AUDIT_ANCHOR_BINDING_MISMATCH")
        return snapshot

    def _preflight(self, request: GateApprovalIssuanceRequest) -> tuple[dict[str, Any], str]:
        self._validate_request(request)
        owner_anchor = self._read_owner_anchor()
        binding, _ = super()._preflight(request)
        evidence = binding.get("evidence")
        payload = evidence.get("payload") if isinstance(evidence, Mapping) else None
        profile = self.profile
        if (
            binding.get("project_alias") != profile.project_alias
            or binding.get("source_head") != profile.expected_head
            or not isinstance(payload, Mapping)
            or payload.get("project_id") != profile.project_id
            or payload.get("gate_id") != profile.gate_id
            or payload.get("requirements_sha256") != profile.requirements_sha256
            or payload.get("plan_sha256") != profile.plan_sha256
            or payload.get("branch") != profile.expected_branch
            or payload.get("head") != profile.expected_head
        ):
            raise GateApprovalIssuanceError("G1_SOURCE_BINDING_MISMATCH")
        binding = {**binding, "owner_authority_anchor": owner_anchor}
        return binding, _sha(binding)

    def execute(self, request: GateApprovalIssuanceRequest, *,
                owner_approval_comment: Mapping[str, Any] | None = None,
                owner_actor_id: str = "") -> dict[str, Any]:
        if str(owner_actor_id) != self.profile.owner_actor_id:
            raise GateApprovalIssuanceError("OWNER_AUTHORITY_MISMATCH")
        result = super().execute(
            request,
            owner_approval_comment=owner_approval_comment,
            owner_actor_id=owner_actor_id,
        )
        return {**result, "owner_authority_anchor": self.profile.owner_anchor_snapshot()}
