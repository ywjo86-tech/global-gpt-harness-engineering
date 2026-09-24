"""Pure RJI-8 activation decisions for optional external advisory capabilities.

This module owns no deployment, provider selection, network, secret retrieval,
execution, approval, completion, or effect authority.  It only projects already
qualified immutable evidence into READY/ACTIVE/BLOCKED/QUARANTINED decisions.
Actual deployment remains an OCP-controlled side effect outside this module.
"""
from __future__ import annotations

from dataclasses import dataclass

from .external_advisory_contract import ExternalCapabilityDescriptorV1
from .external_advisory_runtime import (
    ExternalAdvisoryRuntimeError,
    ExternalAdvisoryRuntimePolicyV1,
    ExternalCapabilityRuntimeEvidenceV1,
    assert_activation_ready,
)
from .jev_provider_bound_adapter import JEV_CAPABILITY_ID
from .ruflo_filtering_proxy import RUFLO_CAPABILITY_ID, RUFLO_PINNED_VERSION

ACTIVATION_STATUS_READY = "READY"
ACTIVATION_STATUS_ACTIVE = "ACTIVE"
ACTIVATION_STATUS_BLOCKED = "BLOCKED"
ACTIVATION_STATUS_QUARANTINED = "QUARANTINED"

_ALLOWED_TARGET_STATES = frozenset({"READY", "CANARY", "ACTIVE"})


@dataclass(frozen=True, slots=True)
class ActivationEvidenceV1:
    """Non-secret qualification references used to decide an activation slice."""

    rji7_receipt_ref: str
    safety_approval_receipt_ref: str
    ocp_deployment_evidence_ref: str
    endpoint_account_qualified: bool
    retention_qualified: bool
    security_qualified: bool
    actual_provider_ref: str
    actual_model_ref: str
    expected_provider_ref: str
    expected_model_ref: str
    canary_input_class: str
    qualified_tool_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        text_fields = (
            "rji7_receipt_ref",
            "safety_approval_receipt_ref",
            "ocp_deployment_evidence_ref",
            "actual_provider_ref",
            "actual_model_ref",
            "expected_provider_ref",
            "expected_model_ref",
            "canary_input_class",
        )
        for field in text_fields:
            if not isinstance(getattr(self, field), str):
                raise TypeError(f"{field} must be a string")
        if not isinstance(self.qualified_tool_ids, tuple) or any(
            not isinstance(tool_id, str) or not tool_id.strip()
            for tool_id in self.qualified_tool_ids
        ):
            raise TypeError("qualified_tool_ids must be a tuple of non-empty strings")


@dataclass(frozen=True, slots=True)
class ActivationDecisionV1:
    capability_id: str
    target_state: str
    status: str
    reason_code: str
    active_slice: str
    usable_tool_ids: tuple[str, ...]
    rollback_instructions: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ActivationRollbackV1:
    policy: ExternalAdvisoryRuntimePolicyV1
    instructions: tuple[str, ...]


_ROLLBACK_INSTRUCTIONS = (
    "disable Ruflo and Jev external advisory feature flags",
    "preserve the existing Provider Router, MPRF, Production Execution Gateway, and Full MCP stable core",
    "return advisory calls to the existing pre-integration baseline path",
)


def _decision(
    descriptor: ExternalCapabilityDescriptorV1,
    target_state: str,
    *,
    status: str,
    reason_code: str,
    active_slice: str = "",
    usable_tool_ids: tuple[str, ...] = (),
) -> ActivationDecisionV1:
    return ActivationDecisionV1(
        capability_id=descriptor.capability_id,
        target_state=target_state,
        status=status,
        reason_code=reason_code,
        active_slice=active_slice,
        usable_tool_ids=usable_tool_ids,
        rollback_instructions=_ROLLBACK_INSTRUCTIONS,
    )


def _blocked(
    descriptor: ExternalCapabilityDescriptorV1,
    target_state: str,
    reason_code: str,
) -> ActivationDecisionV1:
    return _decision(
        descriptor,
        target_state,
        status=ACTIVATION_STATUS_BLOCKED,
        reason_code=reason_code,
    )


def _quarantined(
    descriptor: ExternalCapabilityDescriptorV1,
    target_state: str,
    reason_code: str,
) -> ActivationDecisionV1:
    return _decision(
        descriptor,
        target_state,
        status=ACTIVATION_STATUS_QUARANTINED,
        reason_code=reason_code,
    )


def _receipt_guard(
    policy: ExternalAdvisoryRuntimePolicyV1,
    evidence: ActivationEvidenceV1,
    descriptor: ExternalCapabilityDescriptorV1,
    target_state: str,
) -> ActivationDecisionV1 | None:
    # Synthetic CANARY remains governed by the existing runtime CANARY policy;
    # READY/ACTIVE require the explicit RJI-7 and dangerous-work receipts.
    if target_state == "CANARY":
        return None
    if not policy.rji7_pass_receipt.strip() or not evidence.rji7_receipt_ref.strip():
        return _blocked(descriptor, target_state, "RJI7_RECEIPT_MISSING")
    if not policy.safety_approval_receipt.strip() or not evidence.safety_approval_receipt_ref.strip():
        return _blocked(descriptor, target_state, "SAFETY_APPROVAL_MISSING")
    if (
        policy.rji7_pass_receipt != evidence.rji7_receipt_ref
        or policy.safety_approval_receipt != evidence.safety_approval_receipt_ref
    ):
        return _quarantined(descriptor, target_state, "ACTIVATION_RECEIPT_MISMATCH")
    return None


def _ruflo_guard(
    descriptor: ExternalCapabilityDescriptorV1,
    runtime_evidence: ExternalCapabilityRuntimeEvidenceV1,
    activation_evidence: ActivationEvidenceV1,
    target_state: str,
) -> ActivationDecisionV1 | None:
    if (
        descriptor.capability_version != RUFLO_PINNED_VERSION
        or runtime_evidence.approved_identity_digest != descriptor.package_or_endpoint_digest
    ):
        return _quarantined(descriptor, target_state, "RUFLO_PIN_DRIFT")
    if not runtime_evidence.zero_tool_only:
        if not runtime_evidence.tool_qualification_refs:
            return _blocked(descriptor, target_state, "RUFLO_TOOL_QUALIFICATION_MISSING")
        if not activation_evidence.qualified_tool_ids:
            return _blocked(descriptor, target_state, "RUFLO_TOOL_IDENTITY_MISSING")
    return None


def _jev_guard(
    descriptor: ExternalCapabilityDescriptorV1,
    runtime_evidence: ExternalCapabilityRuntimeEvidenceV1,
    activation_evidence: ActivationEvidenceV1,
    target_state: str,
) -> ActivationDecisionV1 | None:
    if runtime_evidence.private_data_scope and not runtime_evidence.privacy_qualified:
        return _blocked(descriptor, target_state, "JEV_PRIVATE_SCOPE_UNQUALIFIED")
    if not runtime_evidence.credential_ref.strip():
        return _blocked(descriptor, target_state, "JEV_CREDENTIAL_REFERENCE_MISSING")
    if not runtime_evidence.endpoint_qualified or not activation_evidence.endpoint_account_qualified:
        return _blocked(descriptor, target_state, "JEV_ENDPOINT_ACCOUNT_UNQUALIFIED")
    if not activation_evidence.retention_qualified:
        return _blocked(descriptor, target_state, "JEV_RETENTION_UNQUALIFIED")
    if not activation_evidence.security_qualified:
        return _blocked(descriptor, target_state, "JEV_SECURITY_UNQUALIFIED")
    if not all(
        value.strip()
        for value in (
            activation_evidence.actual_provider_ref,
            activation_evidence.actual_model_ref,
            activation_evidence.expected_provider_ref,
            activation_evidence.expected_model_ref,
        )
    ):
        return _blocked(descriptor, target_state, "JEV_PROVIDER_MODEL_EVIDENCE_MISSING")
    if (
        activation_evidence.actual_provider_ref != activation_evidence.expected_provider_ref
        or activation_evidence.actual_model_ref != activation_evidence.expected_model_ref
    ):
        return _quarantined(
            descriptor, target_state, "JEV_PROVIDER_MODEL_BINDING_MISMATCH"
        )
    if target_state == "CANARY" and activation_evidence.canary_input_class != "SYNTHETIC_NON_SENSITIVE":
        return _blocked(descriptor, target_state, "JEV_CANARY_INPUT_CLASS_UNSAFE")
    return None


def _runtime_guard(
    policy: ExternalAdvisoryRuntimePolicyV1,
    descriptor: ExternalCapabilityDescriptorV1,
    runtime_evidence: ExternalCapabilityRuntimeEvidenceV1,
    target_state: str,
) -> ActivationDecisionV1 | None:
    runtime_target = "ACTIVE" if target_state == "READY" else target_state
    try:
        assert_activation_ready(
            policy,
            descriptor,
            runtime_evidence,
            target_state=runtime_target,
        )
    except ExternalAdvisoryRuntimeError as exc:
        quarantine_codes = {
            "CAPABILITY_VERSION_UNAPPROVED",
            "CAPABILITY_PROVIDER_BINDING_MISMATCH",
            "CAPABILITY_QUARANTINED",
        }
        if exc.code in quarantine_codes:
            return _quarantined(descriptor, target_state, exc.code)
        return _blocked(descriptor, target_state, exc.code)
    return None


def activation_decision(
    *,
    policy: ExternalAdvisoryRuntimePolicyV1,
    descriptor: ExternalCapabilityDescriptorV1,
    runtime_evidence: ExternalCapabilityRuntimeEvidenceV1,
    activation_evidence: ActivationEvidenceV1,
    target_state: str,
) -> ActivationDecisionV1:
    """Evaluate immutable evidence without performing activation side effects."""

    if target_state not in _ALLOWED_TARGET_STATES:
        return _blocked(descriptor, target_state, "ACTIVATION_TARGET_UNSUPPORTED")

    receipt_decision = _receipt_guard(
        policy, activation_evidence, descriptor, target_state
    )
    if receipt_decision is not None:
        return receipt_decision

    if descriptor.capability_id == RUFLO_CAPABILITY_ID:
        specific = _ruflo_guard(
            descriptor, runtime_evidence, activation_evidence, target_state
        )
    elif descriptor.capability_id == JEV_CAPABILITY_ID:
        specific = _jev_guard(
            descriptor, runtime_evidence, activation_evidence, target_state
        )
    else:
        return _quarantined(descriptor, target_state, "CAPABILITY_VERSION_UNAPPROVED")
    if specific is not None:
        return specific

    runtime_decision = _runtime_guard(
        policy, descriptor, runtime_evidence, target_state
    )
    if runtime_decision is not None:
        return runtime_decision

    if target_state == "READY":
        return _decision(
            descriptor,
            target_state,
            status=ACTIVATION_STATUS_READY,
            reason_code="QUALIFIED_FOR_OCP_DEPLOYMENT",
        )

    if not activation_evidence.ocp_deployment_evidence_ref.strip():
        return _blocked(
            descriptor,
            target_state,
            "BLOCKED_EXTERNAL_RUNTIME_EVIDENCE_MISSING",
        )

    if descriptor.capability_id == RUFLO_CAPABILITY_ID:
        if runtime_evidence.zero_tool_only:
            return _decision(
                descriptor,
                target_state,
                status=ACTIVATION_STATUS_ACTIVE,
                reason_code="RUFLO_ZERO_TOOL_NOOP_ACTIVE",
                active_slice="RUFLO_ZERO_TOOL_NOOP",
                usable_tool_ids=(),
            )
        return _decision(
            descriptor,
            target_state,
            status=ACTIVATION_STATUS_ACTIVE,
            reason_code="RUFLO_QUALIFIED_READ_ONLY_TOOLS_ACTIVE",
            active_slice="RUFLO_QUALIFIED_READ_ONLY_TOOLS",
            usable_tool_ids=activation_evidence.qualified_tool_ids,
        )

    return _decision(
        descriptor,
        target_state,
        status=ACTIVATION_STATUS_ACTIVE,
        reason_code=(
            "JEV_SYNTHETIC_NON_SENSITIVE_CANARY_ACTIVE"
            if target_state == "CANARY"
            else "JEV_PROVIDER_BOUND_ADVISORY_ACTIVE"
        ),
        active_slice=(
            "JEV_SYNTHETIC_NON_SENSITIVE_CANARY"
            if target_state == "CANARY"
            else "JEV_PROVIDER_BOUND_ADVISORY"
        ),
        usable_tool_ids=(),
    )


def rollback_to_disabled() -> ActivationRollbackV1:
    """Return feature-disable rollback instructions; mutate no stable core."""

    return ActivationRollbackV1(
        policy=ExternalAdvisoryRuntimePolicyV1(
            kill_switch=False,
            ruflo_enabled=False,
            jev_enabled=False,
            rji7_pass_receipt="",
            safety_approval_receipt="",
        ),
        instructions=_ROLLBACK_INSTRUCTIONS,
    )
