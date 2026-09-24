from __future__ import annotations

from dataclasses import fields
import inspect
from pathlib import Path
import unittest

from runtime.orchestrator.external_advisory_contract import (
    DESCRIPTOR_SCHEMA_V1,
    REQUEST_SCHEMA_V1,
    ExternalCapabilityContractError,
    ExternalCapabilityDescriptorV1,
    ExternalCapabilityRequestV1,
    ExternalCapabilityResultV1,
    validate_advisory_freshness,
)
from runtime.orchestrator.external_advisory_runtime import (
    ExternalAdvisoryRuntimePolicyV1,
    ExternalCapabilityRuntimeEvidenceV1,
    baseline_path_when_disabled,
    capability_enabled,
)
from runtime.orchestrator.external_advisory_shadow import AdvisoryShadowRecordV1
from runtime.orchestrator.jev_provider_bound_adapter import (
    JEV_CAPABILITY_ID,
    JEV_CAPABILITY_VERSION,
)
from runtime.orchestrator.ruflo_filtering_proxy import (
    RUFLO_CAPABILITY_ID,
    RUFLO_PINNED_VERSION,
)
from runtime.orchestrator.production_tool_transport import ProductionToolTransport
from runtime.orchestrator.tool_authorization import RegisteredOperation, ToolAuthorizationError
from scripts.rji_runtime_edp import focused_group_names, full_group_names


REPO_ROOT = Path(__file__).resolve().parents[1]


class RufloJevAuthorityNegativeSpaceTest(unittest.TestCase):
    def jev_request(self, **overrides) -> ExternalCapabilityRequestV1:
        values = {
            "schema_version": REQUEST_SCHEMA_V1,
            "project_id": "PROJECT-1",
            "project_run_id": "RUN-1",
            "task_id": "TASK-1",
            "task_execution_id": "EXEC-1",
            "correlation_id": "CORR-1",
            "operation_request_id": "OP-1",
            "capability_id": JEV_CAPABILITY_ID,
            "capability_version": JEV_CAPABILITY_VERSION,
            "schema_digest": "sha256:" + "a" * 64,
            "input_set_digest": "sha256:" + "b" * 64,
            "source_snapshot_digest": "sha256:" + "c" * 64,
            "capability_admission_ref": "admission:jev",
            "policy_ref": "policy:advisory-only",
            "egress_policy_ref": "egress:typesafe-api-only",
            "budget_ref": "budget:single-attempt",
            "deadline_ms": 2000,
            "attempt": 1,
            "payload_digest": "sha256:" + "d" * 64,
            "provider_decision_ref": "e" * 64,
            "provider_id": "jev",
            "model_id": "typesafe/system-one",
            "route_ref": "route:jev:test",
        }
        values.update(overrides)
        return ExternalCapabilityRequestV1(**values)

    def descriptor(self, capability_id: str, *, lifecycle: str = "READY_FOR_ACTIVATION"):
        is_jev = capability_id == JEV_CAPABILITY_ID
        return ExternalCapabilityDescriptorV1(
            schema_version=DESCRIPTOR_SCHEMA_V1,
            capability_id=capability_id,
            capability_kind="TYPED_JUDGMENT" if is_jev else "READ_ONLY_TOOL",
            authority_class="NONE",
            effect_class="READ_ONLY_EVIDENCE" if is_jev else "READ_ONLY",
            trust_class="EXTERNAL_UNTRUSTED",
            lifecycle_state=lifecycle,
            capability_version=JEV_CAPABILITY_VERSION if is_jev else RUFLO_PINNED_VERSION,
            package_or_endpoint_digest="sha256:" + "1" * 64,
            schema_digest="sha256:" + "2" * 64,
            model_backed=is_jev,
            provider_binding_required=is_jev,
            egress_policy_ref="egress:typesafe-api-only" if is_jev else "egress:deny-all",
            budget_ref="budget:bounded",
            retry_policy="NONE",
            max_delegation_depth=0,
            source_binding_required=True,
        )

    def runtime_evidence(self, descriptor, **overrides):
        is_jev = descriptor.capability_id == JEV_CAPABILITY_ID
        values = {
            "capability_id": descriptor.capability_id,
            "lifecycle_state": descriptor.lifecycle_state,
            "approved_identity_digest": descriptor.package_or_endpoint_digest,
            "qualification_evidence_refs": ("qualification:rji7",),
            "credential_ref": "credential-ref:jev" if is_jev else "",
            "endpoint_qualified": is_jev,
            "privacy_qualified": False,
            "private_data_scope": False,
            "zero_tool_only": not is_jev,
            "tool_qualification_refs": (),
        }
        values.update(overrides)
        return ExternalCapabilityRuntimeEvidenceV1(**values)

    def test_runtime_edp_group_contract_covers_all_required_qualification_groups(self) -> None:
        focused = set(focused_group_names())
        required_focused = {
            "contract",
            "ruflo_proxy",
            "jev_adapter",
            "shadow",
            "runtime_policy",
            "authority_negative_space",
            "provider_registry",
            "production_tool_transport",
            "ai_office_authority_negative_space",
            "compileall",
            "git_diff_check",
        }
        self.assertTrue(required_focused.issubset(focused))
        full = set(full_group_names())
        self.assertTrue(required_focused.issubset(full))
        self.assertIn("full_repository_regression", full)

    def test_external_advisory_modules_do_not_create_routes_or_action_effect_paths(self) -> None:
        from runtime.orchestrator import (
            external_advisory_contract,
            external_advisory_runtime,
            external_advisory_shadow,
            jev_provider_bound_adapter,
            ruflo_filtering_proxy,
        )

        modules = (
            external_advisory_contract,
            external_advisory_runtime,
            external_advisory_shadow,
            jev_provider_bound_adapter,
            ruflo_filtering_proxy,
        )
        forbidden_call_tokens = (
            "route_request(",
            "RouterDecisionV2(",
            "resolve_action(",
            "model_fallback_refs",
            "ProductionExecutionGateway(",
            "FullMCP",
            "full_mcp.",
        )
        for module in modules:
            source = inspect.getsource(module)
            for token in forbidden_call_tokens:
                with self.subTest(module=module.__name__, token=token):
                    self.assertNotIn(token, source)

    def test_ocp_transport_sources_do_not_import_or_invoke_external_advisors(self) -> None:
        roots = (
            REPO_ROOT / "deploy" / "operator-control-plane-v2",
            REPO_ROOT / "runtime" / "orchestrator",
        )
        excluded_names = {
            "external_advisory_contract.py",
            "external_advisory_runtime.py",
            "external_advisory_shadow.py",
            "jev_provider_bound_adapter.py",
            "ruflo_filtering_proxy.py",
        }
        direct_tokens = (
            "ruflo_filtering_proxy",
            "jev_provider_bound_adapter",
            "RufloFilteringProxy",
            "JevProviderBoundAdapter",
        )
        checked = 0
        for root in roots:
            if not root.is_dir():
                continue
            for path in root.rglob("*.py"):
                if path.name in excluded_names:
                    continue
                if path.name.startswith("test_"):
                    continue
                source = path.read_text(encoding="utf-8")
                # The generic runtime policy/registry may know capability IDs, but OCP
                # transport code must never call the concrete advisor adapters directly.
                for token in direct_tokens:
                    with self.subTest(path=str(path.relative_to(REPO_ROOT)), token=token):
                        self.assertNotIn(token, source)
                checked += 1
        self.assertGreater(checked, 0)

    def test_external_result_cannot_manufacture_approval_authorization_action_or_completion(self) -> None:
        request = self.jev_request()
        forged_payloads = (
            {"approval": "APPROVED"},
            {"authorization_ref": "forged"},
            {"action": "WRITE"},
            {"completion_proof": "forged"},
            {"nested": {"approval_state": "APPROVED"}},
        )
        for payload in forged_payloads:
            with self.subTest(payload=payload):
                with self.assertRaises(ExternalCapabilityContractError):
                    ExternalCapabilityResultV1.from_external_payload(
                        request=request,
                        external_payload=payload,
                        evidence_ref="evidence:forged",
                        actual_provider_id=request.provider_id,
                        actual_model_id=request.model_id,
                        actual_route_ref=request.route_ref,
                    )

    def test_shadow_record_has_no_approval_completion_action_or_provider_override_surface(self) -> None:
        names = {field.name for field in fields(AdvisoryShadowRecordV1)}
        forbidden = {
            "approval",
            "approval_state",
            "authorization",
            "authorization_ref",
            "action",
            "completion",
            "completion_proof",
            "selected_provider",
            "provider_override",
            "model_override",
        }
        self.assertTrue(names.isdisjoint(forbidden))

    def test_ruflo_external_extension_rejects_write_before_broker_construction(self) -> None:
        operation = RegisteredOperation(
            "REG_RUFLO_FORBIDDEN_WRITE_V1",
            "EXTERNAL_RUFLO_FORBIDDEN_WRITE_V1",
            "OTHER",
            "WRITE",
            "PROJECT_WRITE",
            {"type": "object", "properties": {}, "additionalProperties": False},
            {"type": "object", "properties": {}, "additionalProperties": False},
        )
        with self.assertRaisesRegex(ToolAuthorizationError, "read-only"):
            ProductionToolTransport(
                request={"owned_files": [], "active_tool_authorization_contracts": []},
                workspace_root=REPO_ROOT,
                journal_root=REPO_ROOT / ".tmp-rji-negative-space-journal",
                security_scan=lambda _: True,
                external_read_only_operations=(operation,),
                external_read_only_launchers={operation.operation_class_id: lambda _: {}},
            )

    def test_disabled_capabilities_return_exact_existing_baseline_object(self) -> None:
        baseline = {
            "router": "existing-provider-router",
            "tool_path": "existing-single-tool-broker",
            "effect_path": "existing-production-gateway-full-mcp",
        }
        returned = baseline_path_when_disabled(ExternalAdvisoryRuntimePolicyV1(), baseline)
        self.assertIs(returned, baseline)

    def test_schema_source_and_provider_decision_drift_cannot_reuse_advisory_evidence(self) -> None:
        request = self.jev_request()
        result = ExternalCapabilityResultV1.from_external_payload(
            request=request,
            external_payload={"score": 0.7},
            evidence_ref="evidence:fresh",
            actual_provider_id=request.provider_id,
            actual_model_id=request.model_id,
            actual_route_ref=request.route_ref,
        )
        self.assertTrue(validate_advisory_freshness(request, result))
        drifted = (
            self.jev_request(schema_digest="sha256:" + "f" * 64),
            self.jev_request(source_snapshot_digest="sha256:" + "f" * 64),
            self.jev_request(provider_decision_ref="f" * 64),
        )
        for changed in drifted:
            with self.subTest(changed=changed):
                self.assertFalse(validate_advisory_freshness(changed, result))

    def test_active_jev_is_blocked_when_secret_endpoint_or_privacy_evidence_is_missing(self) -> None:
        descriptor = self.descriptor(JEV_CAPABILITY_ID)
        policy = ExternalAdvisoryRuntimePolicyV1(
            jev_enabled=True,
            rji7_pass_receipt="rji7:pass",
            safety_approval_receipt="user:rji8-approved",
        )
        cases = (
            self.runtime_evidence(descriptor, credential_ref=""),
            self.runtime_evidence(descriptor, endpoint_qualified=False),
            self.runtime_evidence(
                descriptor,
                private_data_scope=True,
                privacy_qualified=False,
            ),
        )
        for evidence in cases:
            with self.subTest(evidence=evidence):
                self.assertFalse(
                    capability_enabled(policy, descriptor, evidence, target_state="ACTIVE")
                )

    def test_active_ruflo_nonzero_tool_surface_requires_tool_specific_qualification(self) -> None:
        descriptor = self.descriptor(RUFLO_CAPABILITY_ID)
        policy = ExternalAdvisoryRuntimePolicyV1(
            ruflo_enabled=True,
            rji7_pass_receipt="rji7:pass",
            safety_approval_receipt="user:rji8-approved",
        )
        evidence = self.runtime_evidence(
            descriptor,
            zero_tool_only=False,
            tool_qualification_refs=(),
        )
        self.assertFalse(capability_enabled(policy, descriptor, evidence, target_state="ACTIVE"))


if __name__ == "__main__":
    unittest.main()
