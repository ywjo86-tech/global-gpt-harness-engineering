from __future__ import annotations

import ast
import tempfile
import unittest
from pathlib import Path

from runtime.full_mcp.observability import ObservabilityError, ObservabilityStore
from runtime.mprf.checkpoint import CHECKPOINT_VALID, seal_checkpoint, validate_checkpoint
from runtime.mprf.contracts import (
    ADMISSION_ADMITTED,
    ADMISSION_RECORD_SCHEMA_V1,
    CODEX_PROVIDER,
    MODEL_RECORD_SCHEMA_V1,
    NVIDIA_PROVIDER,
    PROVIDER_RECORD_SCHEMA_V1,
    AdmissionRecordV1,
    ModelRecordV1,
    MPRFContractError,
    ProviderRecordV1,
)
from runtime.mprf.failure import (
    FAILOVER_PREREQUISITES_SCHEMA_V1,
    FailureClassV1,
    FailoverPrerequisitesV1,
)
from runtime.mprf.observability import (
    AUTHORITY_SCOPE,
    MPRFObservabilityError,
    ProviderRuntimeEventStoreV1,
    correlation_projection,
)
from runtime.mprf.registry import REGISTRY_SCHEMA_V1, ProviderModelRegistryV1
from runtime.mprf.router_client import build_reroute_request, to_router_request_v2
from runtime.mprf.runtime import MPRFRuntimeV1, RUNTIME_SCHEMA_V1
from runtime.orchestrator.operator_control import OPERATOR_DIRECTIVE_SCHEMA, OperatorDirectiveV1
from runtime.orchestrator.provider_router import (
    ELIGIBILITY_SCHEMA_V1,
    GOVERNED_POLICY_V1,
    ROUTER_REQUEST_SCHEMA_V2,
    ProviderEligibilitySnapshotV1,
    RouterRequestV2,
    route_request,
)
from runtime.orchestrator.public_execution_contract import (
    PUBLIC_EXECUTION_REQUEST_SCHEMA_V1,
    PublicExecutionRequestV1,
    project_full_mcp_result,
    public_execution_tool_call,
)


PLAN_DIGEST = "a" * 64


def admitted_runtime(*, store: ProviderRuntimeEventStoreV1 | None = None) -> MPRFRuntimeV1:
    registry = ProviderModelRegistryV1(
        REGISTRY_SCHEMA_V1,
        "integrated-registry-1",
        1,
        (
            ProviderRecordV1(PROVIDER_RECORD_SCHEMA_V1, NVIDIA_PROVIDER, 1),
            ProviderRecordV1(PROVIDER_RECORD_SCHEMA_V1, CODEX_PROVIDER, 1),
        ),
        (
            ModelRecordV1(MODEL_RECORD_SCHEMA_V1, NVIDIA_PROVIDER, "nvidia/model-a", 1),
            ModelRecordV1(MODEL_RECORD_SCHEMA_V1, CODEX_PROVIDER, "codex/model-b", 1),
        ),
        (
            AdmissionRecordV1(
                ADMISSION_RECORD_SCHEMA_V1, "admit-n", NVIDIA_PROVIDER,
                "nvidia/model-a", 1, ADMISSION_ADMITTED,
            ),
            AdmissionRecordV1(
                ADMISSION_RECORD_SCHEMA_V1, "admit-c", CODEX_PROVIDER,
                "codex/model-b", 1, ADMISSION_ADMITTED,
            ),
        ),
    )
    return MPRFRuntimeV1(RUNTIME_SCHEMA_V1, registry, observability_store=store)


def complete_prerequisites(checkpoint_ref: str) -> FailoverPrerequisitesV1:
    return FailoverPrerequisitesV1(
        FAILOVER_PREREQUISITES_SCHEMA_V1,
        checkpoint_ref,
        "artifact-integrity-pass",
        "effect-reconciliation-pass",
        "authorization-validation-pass",
        "policy-validation-pass",
    )


class IntegratedE2EQualificationTests(unittest.TestCase):
    def test_029_happy_path_preserves_router_mprf_public_execution_and_effect_authority(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td).resolve()
            provider_store = ProviderRuntimeEventStoreV1(root, "integrated-run")
            mprf = admitted_runtime(store=provider_store)

            prepare_directive = OperatorDirectiveV1(
                OPERATOR_DIRECTIVE_SCHEMA, "P1", "R1", "T1", "E1",
                "ENTRY", "PREPARE", ("reasoning", "read_only"), False, (),
                "GATE-009", "DIR-PREPARE",
            )
            snapshot = mprf.export_router_snapshot("snap-happy", ("mprf-eligibility",))
            prepare_request = RouterRequestV2(
                ROUTER_REQUEST_SCHEMA_V2, "REQ-PREPARE", "P1", "R1", "T1", "E1",
                prepare_directive.directive_digest, "PREPARE", ("reasoning", "read_only"),
                False, GOVERNED_POLICY_V1, snapshot,
            )
            prepare_decision = route_request(prepare_request)
            self.assertTrue(prepare_decision.eligible)
            self.assertIn(prepare_decision.provider_ref, {NVIDIA_PROVIDER, CODEX_PROVIDER})
            self.assertIn(prepare_decision.model_ref, {"nvidia/model-a", "codex/model-b"})

            action_directive = OperatorDirectiveV1(
                OPERATOR_DIRECTIVE_SCHEMA, "P1", "R1", "T1", "E1",
                "PREPARE", "ACTION", ("filesystem_write",), True,
                (prepare_decision.decision_digest,), "GATE-009", "DIR-ACTION",
            )
            action_request = RouterRequestV2(
                ROUTER_REQUEST_SCHEMA_V2, "REQ-ACTION", "P1", "R1", "T1", "E1",
                action_directive.directive_digest, "ACTION", ("filesystem_write",),
                True, GOVERNED_POLICY_V1, snapshot,
            )
            action_decision = route_request(action_request)
            self.assertTrue(action_decision.eligible)
            self.assertIn(action_decision.provider_ref, {NVIDIA_PROVIDER, CODEX_PROVIDER})
            self.assertIn(action_decision.model_ref, {"nvidia/model-a", "codex/model-b"})

            public_request = PublicExecutionRequestV1(
                PUBLIC_EXECUTION_REQUEST_SCHEMA_V1,
                "git_stage",
                {"paths": ["owned/a.txt"], "publication_policy_digest": PLAN_DIGEST},
                "AUTH-PUB-1", "op-happy", "corr-happy", (PLAN_DIGEST,), "STATE_CHANGING",
            )
            call = public_execution_tool_call(public_request)
            self.assertEqual(call["operation"], "git_stage")
            self.assertNotIn("provider", call)
            self.assertNotIn("model", call)

            provider_event = mprf.record_provider_runtime_event(
                project_id="P1", task_id="T1", task_execution_id="E1",
                correlation_id="corr-happy", operation_request_id="op-happy",
                provider_id=action_decision.provider_ref, model_ref=action_decision.model_ref,
                event_type="TRANSITION", facts={"runtime_stage": "ACTION", "health_state": "HEALTHY"},
            )
            provider_projection = correlation_projection(provider_event)
            self.assertEqual(provider_projection["authority_scope"], AUTHORITY_SCOPE)
            self.assertNotIn("effect_id", provider_projection)
            self.assertNotIn("result_digest", provider_projection)

            action_store = ObservabilityStore(root, "full-mcp-run")
            authorized = action_store.append_event(
                operation_request_id="op-happy", correlation_id="corr-happy",
                operation="git_stage", state="AUTHORIZED",
            )
            effect = action_store.append_event(
                operation_request_id="op-happy", correlation_id="corr-happy",
                operation="git_stage", state="EFFECT_RECEIPT", effect_id="effect-happy",
            )
            sealed = action_store.seal_result(
                operation_request_id="op-happy", correlation_id="corr-happy",
                operation="git_stage", state="COMPLETED",
                started_at="2026-09-18T00:00:00Z", ended_at="2026-09-18T00:00:01Z",
                audit_ref=str(authorized["audit_ref"]), effect_id="effect-happy", exit_code=0,
            )
            public_result = project_full_mcp_result(public_request, {
                "operation_request_id": "op-happy",
                "correlation_id": "corr-happy",
                "status": "COMPLETED",
                "result_digest": sealed["result_digest"],
                "effect_id": effect["effect_id"],
                "audit_ref": "audit-happy",
                "data": {"reconciliation_state": "NOT_REQUIRED"},
                "error": None,
            })
            self.assertEqual(public_result.status, "COMPLETED")
            self.assertEqual(public_result.effect_ref, "effect-happy")
            self.assertEqual(public_result.result_digest, sealed["result_digest"])
            self.assertEqual(public_result.correlation_id, provider_projection["correlation_id"])

    def test_030_failure_recovery_requires_prerequisites_and_never_duplicates_or_auto_falls_back(self) -> None:
        mprf = admitted_runtime()
        snapshot = ProviderEligibilitySnapshotV1(
            ELIGIBILITY_SCHEMA_V1, "snap-failure",
            {NVIDIA_PROVIDER: True, CODEX_PROVIDER: False},
            {NVIDIA_PROVIDER: "nvidia/model-a"}, ("mprf-eligibility",), {},
        )
        original_request = RouterRequestV2(
            ROUTER_REQUEST_SCHEMA_V2, "REQ-ORIGINAL", "P1", "R1", "T1", "E1",
            "d" * 64, "PREPARE", ("reasoning", "read_only"), False,
            GOVERNED_POLICY_V1, snapshot,
        )
        original_decision = route_request(original_request)
        self.assertEqual(original_decision.provider_ref, NVIDIA_PROVIDER)

        checkpoint = seal_checkpoint(
            project_id="P1", run_id="R1", task_id="T1", task_execution_id="E1",
            stage="PREPARE", provider_runtime_state_version=1,
            artifact_digest_refs=("artifact-1",),
            router_decision_refs=(original_decision.decision_digest,),
            effect_reconciliation_refs=("effect-reconciled",),
            authorization_ref="auth-valid",
        )
        validation = validate_checkpoint(
            checkpoint, project_id="P1", run_id="R1", task_id="T1", task_execution_id="E1"
        )
        self.assertEqual(validation.status, CHECKPOINT_VALID)

        incomplete = FailoverPrerequisitesV1(
            FAILOVER_PREREQUISITES_SCHEMA_V1,
            checkpoint.checkpoint_ref, "", "effect-reconciliation-pass",
            "authorization-validation-pass", "policy-validation-pass",
        )
        self.assertFalse(mprf.failure_disposition(FailureClassV1.PROVIDER_FAILURE, incomplete).reroute_eligible)

        prerequisites = complete_prerequisites(checkpoint.checkpoint_ref)
        disposition = mprf.failure_disposition(FailureClassV1.PROVIDER_FAILURE, prerequisites)
        self.assertTrue(disposition.reroute_eligible)
        reroute = build_reroute_request(
            request_id="RR-PROVIDER", project_id="P1", run_id="R1", task_id="T1",
            task_execution_id="E1", original_router_decision=original_decision,
            failure=FailureClassV1.PROVIDER_FAILURE, prerequisites=prerequisites,
        )
        after_failure = ProviderEligibilitySnapshotV1(
            ELIGIBILITY_SCHEMA_V1, "snap-after-failure",
            {NVIDIA_PROVIDER: False, CODEX_PROVIDER: True},
            {CODEX_PROVIDER: "codex/model-b"}, ("failure-evidence",), {},
        )
        reroute_request = to_router_request_v2(
            reroute, directive_digest="e" * 64, eligibility_snapshot=after_failure
        )
        reroute_decision = route_request(reroute_request)
        self.assertEqual(reroute_request.stage, "PREPARE")
        self.assertFalse(reroute_request.state_change_required)
        self.assertTrue(reroute_decision.eligible)
        self.assertEqual(reroute_decision.provider_ref, CODEX_PROVIDER)
        self.assertEqual(reroute_decision.model_ref, "codex/model-b")
        self.assertEqual(reroute_decision.stage, "PREPARE")
        self.assertEqual(reroute_decision.reason_code, "governed_reroute_by_neutral_rank")

        for prohibited in (
            FailureClassV1.POLICY_REJECTION,
            FailureClassV1.AUTH_FAILURE,
            FailureClassV1.ACTION_SIDE_EFFECT_AMBIGUOUS,
            FailureClassV1.RECOVERY_REQUIRED,
        ):
            with self.subTest(prohibited=prohibited), self.assertRaisesRegex(MPRFContractError, "reroute prohibited"):
                build_reroute_request(
                    request_id=f"NO-{prohibited.value}", project_id="P1", run_id="R1",
                    task_id="T1", task_execution_id="E1",
                    original_router_decision=original_decision, failure=prohibited,
                    prerequisites=prerequisites,
                    permission_related_auth=prohibited is FailureClassV1.AUTH_FAILURE,
                )

        with tempfile.TemporaryDirectory() as td:
            action_store = ObservabilityStore(Path(td).resolve(), "full-mcp-failure")
            action_store.seal_result(
                operation_request_id="op-once", correlation_id="corr-once", operation="git_stage",
                state="COMPLETED", started_at="2026-09-18T00:00:00Z",
                ended_at="2026-09-18T00:00:01Z", audit_ref="audit-once",
                effect_id="effect-once", exit_code=0,
            )
            with self.assertRaisesRegex(ObservabilityError, "create-once"):
                action_store.seal_result(
                    operation_request_id="op-once", correlation_id="corr-once", operation="git_stage",
                    state="COMPLETED", started_at="2026-09-18T00:00:00Z",
                    ended_at="2026-09-18T00:00:01Z", audit_ref="audit-once",
                    effect_id="effect-once", exit_code=0,
                )

    def test_031_negative_space_keeps_selection_effects_fallback_and_event_ownership_separate(self) -> None:
        import runtime.mprf as mprf_package
        mprf_root = Path(mprf_package.__file__).resolve().parent
        sources = {
            path.name: path.read_text(encoding="utf-8")
            for path in mprf_root.glob("*.py") if path.is_file()
        }
        joined = "\n".join(sources.values())
        self.assertNotIn("from runtime.full_mcp", joined)
        self.assertNotIn("import runtime.full_mcp", joined)
        forbidden_router_calls = []
        for name, source in sources.items():
            tree = ast.parse(source, filename=name)
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and any(alias.name == "route_request" for alias in node.names):
                    forbidden_router_calls.append((name, node.lineno, "import"))
                if isinstance(node, ast.Call):
                    target = node.func
                    if isinstance(target, ast.Name) and target.id == "route_request":
                        forbidden_router_calls.append((name, node.lineno, "call"))
                    if isinstance(target, ast.Attribute) and target.attr == "route_request":
                        forbidden_router_calls.append((name, node.lineno, "attribute-call"))
        self.assertEqual(forbidden_router_calls, [])

        unavailable = ProviderEligibilitySnapshotV1(
            ELIGIBILITY_SCHEMA_V1, "snap-no-nvidia",
            {NVIDIA_PROVIDER: False, CODEX_PROVIDER: True},
            {CODEX_PROVIDER: "codex/model-b"}, ("nvidia-failed",), {},
        )
        request = RouterRequestV2(
            ROUTER_REQUEST_SCHEMA_V2, "REQ-NO-FALLBACK", "P1", "R1", "T1", "E1",
            "f" * 64, "PREPARE", ("reasoning", "read_only"), False,
            GOVERNED_POLICY_V1, unavailable,
        )
        decision = route_request(request)
        # MPRF still does not select a provider; it only projects eligibility.
        # Router may choose another eligible capability-compatible provider.
        self.assertTrue(decision.eligible)
        self.assertEqual(decision.provider_ref, CODEX_PROVIDER)
        self.assertEqual(decision.model_ref, "codex/model-b")
        self.assertEqual(decision.reason_code, "governed_read_by_neutral_rank")

        with tempfile.TemporaryDirectory() as td:
            provider_store = ProviderRuntimeEventStoreV1(Path(td).resolve(), "negative-run")
            base = dict(
                project_id="P1", task_id="T1", task_execution_id="E1",
                correlation_id="corr-negative", operation_request_id="op-negative",
                provider_id=NVIDIA_PROVIDER, model_ref="nvidia/model-a", event_type="HEALTH",
            )
            with self.assertRaisesRegex(MPRFObservabilityError, "action truth"):
                provider_store.append(**base, facts={"effect_id": "effect-negative"})
            event = provider_store.append(**base, facts={"health_state": "HEALTHY"})
            projection = correlation_projection(event)
            self.assertEqual(projection["authority_scope"], AUTHORITY_SCOPE)
            self.assertFalse(any(key in projection for key in ("effect_id", "result_digest", "action_state")))


if __name__ == "__main__":
    unittest.main()
