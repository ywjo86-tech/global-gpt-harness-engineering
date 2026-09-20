from __future__ import annotations

import unittest

from runtime.orchestrator.provider_candidate_inventory import (
    PROVIDER_CANDIDATE_SCHEMA_V1,
    CandidateInventoryError,
    ProviderCandidateInventoryV1,
    ProviderCandidateRecordV1,
    import_omniroute_discovery,
    project_active_candidates,
    transition_candidate,
)
from runtime.orchestrator.provider_router import ELIGIBILITY_SCHEMA_V1, ProviderEligibilitySnapshotV1


def _record(state: str, **changes) -> ProviderCandidateRecordV1:
    values = dict(
        schema_version=PROVIDER_CANDIDATE_SCHEMA_V1,
        provider_id="provider-x", protocol_class="openai-compatible", state=state,
        model_refs=("provider-x/model-1",), credential_required=False,
        cost_class="free", capability_refs=("reasoning", "read_only"),
        readiness_evidence_refs=("read-pass",) if state == "ACTIVE" else (),
        action_evidence_ref="action-pass" if state == "ACTIVE" else "",
        reroute_evidence_ref="reroute-pass" if state == "ACTIVE" else "",
        activation_approval_ref="PH7-FREE-CANDIDATE" if state == "ACTIVE" else "",
    )
    values.update(changes)
    return ProviderCandidateRecordV1(**values)


def _base_snapshot() -> ProviderEligibilitySnapshotV1:
    return ProviderEligibilitySnapshotV1(
        ELIGIBILITY_SCHEMA_V1, "base", {"nvidia": True},
        {"nvidia": "nvidia/model"}, ("base-evidence",),
        provider_capabilities={"nvidia": ("reasoning", "read_only")},
    )


class ProviderCandidateInventoryTests(unittest.TestCase):
    def test_discovered_provider_never_becomes_router_eligible(self) -> None:
        snapshot = project_active_candidates(_base_snapshot(), ProviderCandidateInventoryV1((_record("DISCOVERED"),)))
        self.assertNotIn("provider-x", snapshot.provider_eligible)

    def test_only_active_record_can_project_to_mprf(self) -> None:
        snapshot = project_active_candidates(_base_snapshot(), ProviderCandidateInventoryV1((_record("ACTIVE"),)))
        self.assertTrue(snapshot.provider_eligible["provider-x"])
        self.assertEqual(snapshot.model_refs["provider-x"], "provider-x/model-1")
        self.assertEqual(snapshot.provider_capabilities["provider-x"], ("reasoning", "read_only"))

    def test_active_requires_complete_live_action_reroute_and_approval_evidence(self) -> None:
        for field in ("readiness_evidence_refs", "action_evidence_ref", "reroute_evidence_ref", "activation_approval_ref"):
            kwargs = {field: () if field == "readiness_evidence_refs" else ""}
            with self.subTest(field=field), self.assertRaises(CandidateInventoryError):
                _record("ACTIVE", **kwargs)

    def test_paid_active_requires_cost_risk_approval(self) -> None:
        with self.assertRaisesRegex(CandidateInventoryError, "cost/risk"):
            _record("ACTIVE", cost_class="paid")
        self.assertEqual(_record("ACTIVE", cost_class="paid", cost_risk_approval_ref="APPROVED").state, "ACTIVE")

    def test_transition_graph_is_exact(self) -> None:
        candidate = transition_candidate(_record("DISCOVERED"), "CANDIDATE")
        validating = transition_candidate(candidate, "VALIDATING")
        self.assertEqual(validating.state, "VALIDATING")
        with self.assertRaisesRegex(CandidateInventoryError, "transition"):
            transition_candidate(validating, "ACTIVE")

    def test_discovery_importer_creates_discovered_only_and_rejects_auto_or_duplicates(self) -> None:
        payload = {"providers": [{"id": "provider-x", "category": "free", "hasFree": True}]}
        inv = import_omniroute_discovery(payload)
        self.assertEqual(inv.records[0].state, "DISCOVERED")
        with self.assertRaises(CandidateInventoryError):
            import_omniroute_discovery({"providers": [{"id": "auto"}]})
        with self.assertRaises(CandidateInventoryError):
            import_omniroute_discovery({"providers": [{"id": "p"}, {"id": "p"}]})
        with self.assertRaises(CandidateInventoryError):
            import_omniroute_discovery({"providers": [{"id": "p", "state": "ACTIVE"}]})

    def test_inventory_rejects_duplicate_provider_ids(self) -> None:
        with self.assertRaisesRegex(CandidateInventoryError, "duplicate"):
            ProviderCandidateInventoryV1((_record("DISCOVERED"), _record("DISCOVERED")))


if __name__ == "__main__":
    unittest.main()
