from __future__ import annotations

import unittest

from runtime.orchestrator.provider_handoff import (
    HANDOFF_SCHEMA,
    ProviderHandoffError,
    build_provider_handoff,
)


class ProviderHandoffTest(unittest.TestCase):
    def test_completed_prepare_for_state_change_requires_output_lineage(self) -> None:
        with self.assertRaises(ProviderHandoffError):
            build_provider_handoff(
                parent_execution_id="E1",
                stage="PREPARE",
                provider_decision_digest="a" * 64,
                state_change_required=True,
                status="completed",
            )

    def test_prepare_handoff_is_digest_bound_and_can_request_action(self) -> None:
        handoff = build_provider_handoff(
            parent_execution_id="E1",
            stage="PREPARE",
            provider_decision_digest="a" * 64,
            output_artifact_digests=("b" * 64,),
            proposed_change_manifest=("runtime/orchestrator/",),
            required_next_capabilities=("filesystem_write", "test_execution"),
            state_change_required=True,
            status="completed",
        )
        self.assertEqual(handoff.schema_version, HANDOFF_SCHEMA)
        self.assertTrue(handoff.may_request_action)
        self.assertEqual(len(handoff.handoff_digest), 64)
        self.assertEqual(handoff.to_dict()["handoff_digest"], handoff.handoff_digest)

    def test_failed_prepare_never_requests_action(self) -> None:
        handoff = build_provider_handoff(
            parent_execution_id="E1",
            stage="PREPARE",
            provider_decision_digest="a" * 64,
            output_artifact_digests=("b" * 64,),
            state_change_required=True,
            status="provider_failed",
            errors=("nvidia_timeout",),
        )
        self.assertFalse(handoff.may_request_action)


if __name__ == "__main__":
    unittest.main()
