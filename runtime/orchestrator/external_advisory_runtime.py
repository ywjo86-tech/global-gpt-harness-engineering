"""Pure runtime guards for optional external advisory capabilities.

This module evaluates immutable configuration/evidence only.  It performs no
provider selection, secret retrieval, network access, package installation, or
canonical state mutation.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .external_advisory_contract import ExternalCapabilityDescriptorV1
from .jev_provider_bound_adapter import JEV_CAPABILITY_ID
from .ruflo_filtering_proxy import RUFLO_CAPABILITY_ID


class ExternalAdvisoryRuntimeError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class ExternalAdvisoryRuntimePolicyV1:
    kill_switch: bool = False
    ruflo_enabled: bool = False
    jev_enabled: bool = False
    rji7_pass_receipt: str = ""
    safety_approval_receipt: str = ""


@dataclass(frozen=True, slots=True)
class ExternalCapabilityRuntimeEvidenceV1:
    capability_id: str
    lifecycle_state: str
    approved_identity_digest: str
    qualification_evidence_refs: tuple[str, ...]
    credential_ref: str = ""
    endpoint_qualified: bool = False
    privacy_qualified: bool = False
    private_data_scope: bool = False
    zero_tool_only: bool = False
    tool_qualification_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.capability_id, str) or not self.capability_id.strip():
            raise ExternalAdvisoryRuntimeError(
                "CAPABILITY_RESULT_INVALID", "runtime evidence capability id is required"
            )
        if not isinstance(self.lifecycle_state, str) or not self.lifecycle_state.strip():
            raise ExternalAdvisoryRuntimeError(
                "CAPABILITY_RESULT_INVALID", "runtime evidence lifecycle state is required"
            )
        if not isinstance(self.approved_identity_digest, str):
            raise ExternalAdvisoryRuntimeError(
                "CAPABILITY_RESULT_INVALID", "runtime evidence identity digest is invalid"
            )
        if not isinstance(self.qualification_evidence_refs, tuple) or any(
            not isinstance(ref, str) or not ref.strip() for ref in self.qualification_evidence_refs
        ):
            raise ExternalAdvisoryRuntimeError(
                "CAPABILITY_RESULT_INVALID", "runtime qualification evidence refs are invalid"
            )
        if not isinstance(self.tool_qualification_refs, tuple) or any(
            not isinstance(ref, str) or not ref.strip() for ref in self.tool_qualification_refs
        ):
            raise ExternalAdvisoryRuntimeError(
                "CAPABILITY_RESULT_INVALID", "runtime tool qualification refs are invalid"
            )


def _enabled_flag(policy: ExternalAdvisoryRuntimePolicyV1, capability_id: str) -> bool:
    if capability_id == RUFLO_CAPABILITY_ID:
        return policy.ruflo_enabled
    if capability_id == JEV_CAPABILITY_ID:
        return policy.jev_enabled
    return False


def _require_common(
    policy: ExternalAdvisoryRuntimePolicyV1,
    descriptor: ExternalCapabilityDescriptorV1,
    evidence: ExternalCapabilityRuntimeEvidenceV1,
    *,
    target_state: str,
) -> None:
    if target_state not in {"CANARY", "ACTIVE"}:
        raise ExternalAdvisoryRuntimeError(
            "CAPABILITY_RESULT_INVALID", "unsupported external advisory target state"
        )
    if policy.kill_switch:
        raise ExternalAdvisoryRuntimeError(
            "CAPABILITY_QUARANTINED", "external advisory kill switch is active"
        )
    if descriptor.capability_id not in {RUFLO_CAPABILITY_ID, JEV_CAPABILITY_ID}:
        raise ExternalAdvisoryRuntimeError(
            "CAPABILITY_VERSION_UNAPPROVED", "external capability is not approved"
        )
    if not _enabled_flag(policy, descriptor.capability_id):
        raise ExternalAdvisoryRuntimeError(
            "CAPABILITY_QUARANTINED", "external capability enable flag is false"
        )
    if evidence.capability_id != descriptor.capability_id:
        raise ExternalAdvisoryRuntimeError(
            "CAPABILITY_PROVIDER_BINDING_MISMATCH", "runtime capability identity mismatch"
        )
    if evidence.lifecycle_state != descriptor.lifecycle_state:
        raise ExternalAdvisoryRuntimeError(
            "CAPABILITY_EVIDENCE_STALE", "runtime lifecycle evidence is stale"
        )
    if evidence.approved_identity_digest != descriptor.package_or_endpoint_digest:
        raise ExternalAdvisoryRuntimeError(
            "CAPABILITY_VERSION_UNAPPROVED", "external runtime identity has drifted"
        )
    if not evidence.qualification_evidence_refs:
        raise ExternalAdvisoryRuntimeError(
            "CAPABILITY_EVIDENCE_STALE", "external qualification evidence is missing"
        )

    allowed_lifecycle = (
        {"CANARY", "READY_FOR_ACTIVATION", "ACTIVE"}
        if target_state == "CANARY"
        else {"READY_FOR_ACTIVATION", "ACTIVE"}
    )
    if descriptor.lifecycle_state not in allowed_lifecycle:
        raise ExternalAdvisoryRuntimeError(
            "CAPABILITY_QUARANTINED", "external capability lifecycle is not activation-ready"
        )

    if target_state == "ACTIVE":
        if not isinstance(policy.rji7_pass_receipt, str) or not policy.rji7_pass_receipt.strip():
            raise ExternalAdvisoryRuntimeError(
                "CAPABILITY_EVIDENCE_STALE", "RJI-7 PASS receipt is required"
            )
        if not isinstance(policy.safety_approval_receipt, str) or not policy.safety_approval_receipt.strip():
            raise ExternalAdvisoryRuntimeError(
                "CAPABILITY_QUARANTINED", "dangerous-work safety approval receipt is required"
            )


def _require_capability_specific(
    descriptor: ExternalCapabilityDescriptorV1,
    evidence: ExternalCapabilityRuntimeEvidenceV1,
) -> None:
    if descriptor.capability_id == JEV_CAPABILITY_ID:
        if not isinstance(evidence.credential_ref, str) or not evidence.credential_ref.strip():
            raise ExternalAdvisoryRuntimeError(
                "CAPABILITY_AUTH_MISSING", "Jev credential reference is missing"
            )
        if not evidence.endpoint_qualified:
            raise ExternalAdvisoryRuntimeError(
                "CAPABILITY_PRIVACY_POLICY_UNQUALIFIED", "Jev endpoint/account qualification is missing"
            )
        if evidence.private_data_scope and not evidence.privacy_qualified:
            raise ExternalAdvisoryRuntimeError(
                "CAPABILITY_PRIVACY_POLICY_UNQUALIFIED", "Jev private-data qualification is missing"
            )
        return
    if descriptor.capability_id == RUFLO_CAPABILITY_ID:
        if not evidence.zero_tool_only and not evidence.tool_qualification_refs:
            raise ExternalAdvisoryRuntimeError(
                "CAPABILITY_SCHEMA_MISMATCH", "Ruflo tool-specific qualification is missing"
            )
        return
    raise ExternalAdvisoryRuntimeError(
        "CAPABILITY_VERSION_UNAPPROVED", "external capability is not approved"
    )


def assert_activation_ready(
    policy: ExternalAdvisoryRuntimePolicyV1,
    descriptor: ExternalCapabilityDescriptorV1,
    evidence: ExternalCapabilityRuntimeEvidenceV1,
    *,
    target_state: str,
) -> None:
    _require_common(policy, descriptor, evidence, target_state=target_state)
    _require_capability_specific(descriptor, evidence)


def capability_enabled(
    policy: ExternalAdvisoryRuntimePolicyV1,
    descriptor: ExternalCapabilityDescriptorV1,
    evidence: ExternalCapabilityRuntimeEvidenceV1,
    *,
    target_state: str,
) -> bool:
    try:
        assert_activation_ready(policy, descriptor, evidence, target_state=target_state)
    except ExternalAdvisoryRuntimeError:
        return False
    return True


def baseline_path_when_disabled(
    policy: ExternalAdvisoryRuntimePolicyV1,
    baseline_value: Any,
) -> Any:
    if policy.ruflo_enabled or policy.jev_enabled:
        raise ExternalAdvisoryRuntimeError(
            "CAPABILITY_RESULT_INVALID",
            "baseline-only projection requires both external capabilities disabled",
        )
    return baseline_value
