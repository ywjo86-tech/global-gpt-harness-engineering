from __future__ import annotations

import unittest

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


if __name__ == "__main__":
    unittest.main()
