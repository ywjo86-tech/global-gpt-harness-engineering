from __future__ import annotations

import unittest

from runtime.mprf.failure import (
    EFFECT_STATE_NO_EFFECT, FAILOVER_PREREQUISITES_SCHEMA_V1,
    FailureClassV1, FailoverPrerequisitesV1,
)
from runtime.mprf.router_client import build_reroute_request, to_router_request_v2
from runtime.orchestrator.provider_router import (
    ELIGIBILITY_SCHEMA_V1, GOVERNED_POLICY_V1, ROUTER_REQUEST_SCHEMA_V2,
    ProviderEligibilitySnapshotV1, RouterRequestV2, route_request,
)
from runtime.orchestrator.provider_candidate_inventory import (
    PROVIDER_CANDIDATE_SCHEMA_V1,
    CandidateInventoryError,
    ProviderCandidateRecordV1,
    transition_candidate,
)


def _record(state: str, *, cost_class: str = "free", qualified: bool = True) -> ProviderCandidateRecordV1:
    return ProviderCandidateRecordV1(
        schema_version=PROVIDER_CANDIDATE_SCHEMA_V1,
        provider_id="provider-x",
        protocol_class="omniroute-openai-v1",
        state=state,
        model_refs=("provider-x/model-1",),
        credential_required=cost_class != "free",
        cost_class=cost_class,
        capability_refs=("reasoning", "read_only", "patch_generation"),
        readiness_evidence_refs=("read-pass",) if qualified else (),
        action_evidence_ref="action-pass" if qualified else "",
        reroute_evidence_ref="reroute-pass" if qualified else "",
        activation_approval_ref="",
        cost_risk_approval_ref="",
    )


class OmniRouteLiveQualificationContractTests(unittest.TestCase):
    def test_qualified_state_requires_complete_live_read_action_and_reroute_evidence(self) -> None:
        with self.assertRaisesRegex(CandidateInventoryError, "QUALIFIED requires complete live qualification evidence"):
            _record("QUALIFIED", qualified=False)

    def test_approval_state_requires_complete_live_qualification_evidence(self) -> None:
        with self.assertRaisesRegex(CandidateInventoryError, "APPROVAL requires complete live qualification evidence"):
            _record("APPROVAL", qualified=False)

    def test_active_requires_approval_transition_and_activation_ref(self) -> None:
        qualified = _record("QUALIFIED")
        approval = transition_candidate(qualified, "APPROVAL")
        with self.assertRaisesRegex(CandidateInventoryError, "activation approval"):
            transition_candidate(approval, "ACTIVE")
        active = transition_candidate(approval, "ACTIVE", activation_approval_ref="PH7-FREE-CANDIDATE")
        self.assertEqual(active.state, "ACTIVE")

    def test_paid_active_requires_cost_risk_approval(self) -> None:
        qualified = _record("QUALIFIED", cost_class="paid")
        approval = transition_candidate(qualified, "APPROVAL")
        with self.assertRaisesRegex(CandidateInventoryError, "cost/risk"):
            transition_candidate(approval, "ACTIVE", activation_approval_ref="USER-APPROVAL")

    def test_direct_qualified_to_active_is_forbidden(self) -> None:
        with self.assertRaisesRegex(CandidateInventoryError, "transition"):
            transition_candidate(_record("QUALIFIED"), "ACTIVE", activation_approval_ref="X")

    def test_groq_provider_failure_reroutes_only_through_router(self) -> None:
        original_snapshot = ProviderEligibilitySnapshotV1(
            ELIGIBILITY_SCHEMA_V1, "groq-before",
            {"groq": True}, {"groq": "openai/gpt-oss-120b"}, ("live-read",),
            provider_capabilities={"groq": ("reasoning", "read_only")},
        )
        original_request = RouterRequestV2(
            ROUTER_REQUEST_SCHEMA_V2, "REQ-GROQ-ORIGINAL", "P", "R", "TASK-GROQ", "E", "a" * 64,
            "PREPARE", ("reasoning", "read_only"), False, GOVERNED_POLICY_V1, original_snapshot,
        )
        original = route_request(original_request)
        self.assertEqual(original.provider_ref, "groq")
        self.assertEqual(original.model_ref, "openai/gpt-oss-120b")

        prerequisites = FailoverPrerequisitesV1(
            FAILOVER_PREREQUISITES_SCHEMA_V1, "checkpoint-pass", "artifact-pass",
            "effect-pass", "authorization-pass", "policy-pass",
            effect_state=EFFECT_STATE_NO_EFFECT,
        )
        reroute = build_reroute_request(
            request_id="RR-GROQ", project_id="P", run_id="R", task_id="TASK-GROQ",
            task_execution_id="E", original_router_decision=original,
            failure=FailureClassV1.PROVIDER_FAILURE, prerequisites=prerequisites,
        )
        after_failure = ProviderEligibilitySnapshotV1(
            ELIGIBILITY_SCHEMA_V1, "groq-after",
            {"groq": False, "codex": True}, {"codex": "codex/model-b"}, ("failure-evidence",),
            provider_capabilities={"codex": ("reasoning", "read_only")},
        )
        routed = to_router_request_v2(
            reroute, directive_digest="b" * 64, eligibility_snapshot=after_failure,
        )
        decision = route_request(routed)
        self.assertEqual(routed.failed_provider_ref, "groq")
        self.assertEqual(routed.failed_model_ref, "openai/gpt-oss-120b")
        self.assertEqual(decision.provider_ref, "codex")
        self.assertEqual(decision.model_ref, "codex/model-b")
        self.assertEqual(decision.reason_code, "governed_reroute_by_neutral_rank")

    def test_three_provider_neutral_routing_is_stable_and_filters_runtime_facts(self) -> None:
        caps = ("reasoning", "read_only")
        def snapshot(*, groq_eligible=True, groq_caps=caps):
            return ProviderEligibilitySnapshotV1(
                ELIGIBILITY_SCHEMA_V1, "three-provider",
                {"codex": True, "nvidia": True, "groq": groq_eligible},
                {"codex": "codex/model-b", "nvidia": "nvidia/model-a", "groq": "openai/gpt-oss-120b"},
                ("runtime-health",),
                provider_capabilities={"codex": caps, "nvidia": caps, "groq": groq_caps},
            )
        def routed_provider(request_id: str, snap):
            request = RouterRequestV2(
                ROUTER_REQUEST_SCHEMA_V2, request_id, "P", "R", "TASK-READ", "E", "c" * 64,
                "PREPARE", caps, False, GOVERNED_POLICY_V1, snap,
            )
            return route_request(request).provider_ref

        ids = [f"REQ-3P-{index:03d}" for index in range(1, 65)]
        first = [routed_provider(request_id, snapshot()) for request_id in ids]
        second = [routed_provider(request_id, snapshot()) for request_id in ids]
        self.assertEqual(first, second)
        self.assertEqual(set(first), {"codex", "nvidia", "groq"})

        unhealthy = [routed_provider(request_id, snapshot(groq_eligible=False)) for request_id in ids]
        self.assertNotIn("groq", unhealthy)
        self.assertEqual(set(unhealthy), {"codex", "nvidia"})

        incapable = [routed_provider(request_id, snapshot(groq_caps=("reasoning",))) for request_id in ids]
        self.assertNotIn("groq", incapable)
        self.assertEqual(set(incapable), {"codex", "nvidia"})


if __name__ == "__main__":
    unittest.main()
