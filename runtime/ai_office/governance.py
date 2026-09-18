from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping

from .contracts import canonical_digest

RISK_ENVELOPE_SCHEMA_V1 = "ai-office.risk-envelope.v1"
GOVERNANCE_DECISION_SCHEMA_V1 = "ai-office.governance-decision.v1"
ACTIVATION_GATE_SCHEMA_V1 = "ai-office.activation-gate.v1"
HUMAN_APPROVAL_SCHEMA_V1 = "ai-office.human-approval.v1"


class GovernanceError(ValueError):
    pass


def _text(value: object, label: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise GovernanceError(f"invalid {label}")
    text = value.strip()
    if (not text and not allow_empty) or len(text) > 512 or any(ch in text for ch in ("\x00", "\n", "\r")):
        raise GovernanceError(f"invalid {label}")
    return text


def _sha(value: object, label: str) -> str:
    text = _text(value, label)
    if len(text) != 64 or any(ch not in "0123456789abcdef" for ch in text):
        raise GovernanceError(f"invalid {label}")
    return text
@dataclass(frozen=True, slots=True)
class RiskEnvelopeV1:
    schema_version: str
    action_ref: str
    requested_scope_ref: str
    allowed_scope_ref: str
    risk_class: str
    permission_refs: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.schema_version != RISK_ENVELOPE_SCHEMA_V1:
            raise GovernanceError("unsupported risk envelope schema")
        for field in ("action_ref", "requested_scope_ref", "allowed_scope_ref"):
            object.__setattr__(self, field, _text(getattr(self, field), field))
        if self.risk_class not in {"LOW", "MEDIUM", "HIGH"}:
            raise GovernanceError("invalid risk class")
        refs = tuple(_text(ref, "permission_ref") for ref in self.permission_refs)
        if not refs or len(refs) != len(set(refs)):
            raise GovernanceError("invalid permission refs")
        object.__setattr__(self, "permission_refs", refs)

    @property
    def envelope_digest(self) -> str:
        return canonical_digest(asdict(self))
@dataclass(frozen=True, slots=True)
class HumanApprovalV1:
    schema_version: str
    approval_ref: str
    approval_digest: str
    scope_ref: str
    approved_at_epoch: int
    expires_at_epoch: int

    def __post_init__(self) -> None:
        if self.schema_version != HUMAN_APPROVAL_SCHEMA_V1:
            raise GovernanceError("unsupported human approval schema")
        object.__setattr__(self, "approval_ref", _text(self.approval_ref, "approval_ref"))
        object.__setattr__(self, "approval_digest", _sha(self.approval_digest, "approval_digest"))
        object.__setattr__(self, "scope_ref", _text(self.scope_ref, "scope_ref"))
        if (isinstance(self.approved_at_epoch, bool) or not isinstance(self.approved_at_epoch, int) or
                isinstance(self.expires_at_epoch, bool) or not isinstance(self.expires_at_epoch, int) or
                self.approved_at_epoch < 0 or self.expires_at_epoch <= self.approved_at_epoch):
            raise GovernanceError("invalid approval validity window")

    @property
    def record_digest(self) -> str:
        return canonical_digest(asdict(self))

    def is_fresh(self, now_epoch: int, *, expected_scope_ref: str, expected_approval_digest: str) -> bool:
        return (
            self.approved_at_epoch <= now_epoch < self.expires_at_epoch
            and self.scope_ref == expected_scope_ref
            and self.approval_digest == expected_approval_digest
        )
@dataclass(frozen=True, slots=True)
class GovernanceDecisionV1:
    schema_version: str
    risk_envelope_digest: str
    decision: str
    scope_ref: str
    permission_refs: tuple[str, ...]
    human_approval_ref: str
    reason_refs: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.schema_version != GOVERNANCE_DECISION_SCHEMA_V1:
            raise GovernanceError("unsupported governance decision schema")
        object.__setattr__(self, "risk_envelope_digest", _sha(self.risk_envelope_digest, "risk_envelope_digest"))
        if self.decision not in {"ALLOW", "BLOCK", "APPROVAL_REQUIRED"}:
            raise GovernanceError("invalid governance decision")
        object.__setattr__(self, "scope_ref", _text(self.scope_ref, "scope_ref"))
        object.__setattr__(self, "permission_refs", tuple(_text(ref, "permission_ref") for ref in self.permission_refs))
        if self.human_approval_ref:
            object.__setattr__(self, "human_approval_ref", _text(self.human_approval_ref, "human_approval_ref"))
        object.__setattr__(self, "reason_refs", tuple(_text(ref, "reason_ref") for ref in self.reason_refs))

    @property
    def decision_digest(self) -> str:
        return canonical_digest(asdict(self))
@dataclass(frozen=True, slots=True)
class ActivationGateV1:
    schema_version: str
    activation_scope: str
    governance_decision_digest: str
    human_approval_digest: str
    status: str

    def __post_init__(self) -> None:
        if self.schema_version != ACTIVATION_GATE_SCHEMA_V1:
            raise GovernanceError("unsupported activation gate schema")
        if self.activation_scope not in {"PILOT", "PRODUCTION"}:
            raise GovernanceError("invalid activation scope")
        object.__setattr__(self, "governance_decision_digest", _sha(self.governance_decision_digest, "governance_decision_digest"))
        if self.human_approval_digest:
            object.__setattr__(self, "human_approval_digest", _sha(self.human_approval_digest, "human_approval_digest"))
        if self.status not in {"GO", "BLOCKED"}:
            raise GovernanceError("invalid activation gate status")

    @property
    def gate_digest(self) -> str:
        return canonical_digest(asdict(self))


def evaluate_governance(risk: RiskEnvelopeV1, *, permission_allow: bool,
                        approval: HumanApprovalV1 | None, expected_approval_digest: str,
                        now_epoch: int) -> GovernanceDecisionV1:
    reasons: list[str] = []
    if risk.requested_scope_ref != risk.allowed_scope_ref:
        reasons.append("scope-expansion-blocked")
    if not permission_allow:
        reasons.append("permission-blocked")
    approval_required = risk.risk_class in {"MEDIUM", "HIGH"}
    approval_fresh = bool(approval and approval.is_fresh(
        now_epoch, expected_scope_ref=risk.requested_scope_ref,
        expected_approval_digest=expected_approval_digest,
    ))
    if reasons:
        decision = "BLOCK"
    elif approval_required and not approval_fresh:
        decision = "APPROVAL_REQUIRED"
    else:
        decision = "ALLOW"
    return GovernanceDecisionV1(
        GOVERNANCE_DECISION_SCHEMA_V1, risk.envelope_digest, decision, risk.requested_scope_ref,
        risk.permission_refs, approval.approval_ref if approval_fresh and approval else "",
        tuple(reasons) or (("human-approval-required",) if decision == "APPROVAL_REQUIRED" else ("policy-gate-pass",)),
    )
def build_activation_gate(
    *, activation_scope: str, governance: GovernanceDecisionV1,
    approval: HumanApprovalV1 | None, expected_approval_digest: str, now_epoch: int,
) -> ActivationGateV1:
    approval_ok = bool(
        approval
        and approval.is_fresh(
            now_epoch,
            expected_scope_ref=governance.scope_ref,
            expected_approval_digest=expected_approval_digest,
        )
    )
    status = "GO" if governance.decision == "ALLOW" and approval_ok else "BLOCKED"
    return ActivationGateV1(
        ACTIVATION_GATE_SCHEMA_V1,
        activation_scope,
        governance.decision_digest,
        approval.record_digest if approval_ok and approval else "",
        status,
    )
