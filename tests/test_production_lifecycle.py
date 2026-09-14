import unittest

from runtime.orchestrator.lifecycle_binding import FIELDS, build_binding
from runtime.orchestrator.production_lifecycle import (
    ARTIFACT_KINDS, ProductionLifecycleError, assert_no_legacy_direct_consumer,
    consume, produce, transition,
)


def binding(**changes):
    identities = {"project_id":"project", "gate_id":"GATE-1", "lv_id":"LV-1",
                  "run_id":"run-1", "recovery_id":"recovery-1",
                  "approval_event_id":"APR-1", "branch":"main",
                  "baseline_head":"a"*40, "current_head":"b"*40,
                  "attempt":1, "hard_stop":True}
    digests = sorted(FIELDS - {"schema_version", *identities})
    identities.update({name:f"{index:064x}" for index,name in enumerate(digests,1)})
    identities.update(changes)
    return build_binding(**identities)


class ProductionLifecycleTests(unittest.TestCase):
    def test_every_producer_and_consumer_uses_common_strict_envelope(self):
        expected = binding()
        for kind in ARTIFACT_KINDS:
            with self.subTest(kind=kind):
                artifact = produce(kind, {"status":"READY"}, expected)
                self.assertEqual(consume(kind, artifact, expected), artifact)

    def test_wrong_identity_attempt_plan_approval_head_scope_and_predecessor_fail(self):
        expected = binding()
        artifact = produce("package", {"status":"READY"}, expected)
        cases = {
            "project_id":"other", "gate_id":"GATE-2", "lv_id":"LV-2",
            "run_id":"run-2", "attempt":2, "approval_event_id":"APR-2",
            "canonical_plan_sha256":"e"*64, "baseline_head":"c"*40,
            "current_head":"d"*40, "owned_scope_digest":"f"*64,
        }
        for field, value in cases.items():
            with self.subTest(field=field), self.assertRaises(ProductionLifecycleError):
                consume("package", artifact, binding(**{field:value}))
        with self.assertRaisesRegex(ProductionLifecycleError, "predecessor"):
            consume("package", artifact, expected,
                    predecessor={"envelope_sha256":"f"*64})

    def test_rejected_artifact_never_promotes_and_attempt_result_never_reuses(self):
        rejected = produce("recovery_rejection",
                           {"status":"REJECTED", "completion_eligible":True}, binding())
        with self.assertRaisesRegex(ProductionLifecycleError, "rejected"):
            consume("recovery_rejection", rejected, binding())
        result = produce("worker_result", {"status":"completed"}, binding())
        with self.assertRaises(ProductionLifecycleError):
            consume("worker_result", result, binding(attempt=2))

    def test_cross_project_noncanonical_destination_schema_and_legacy_bypass_fail(self):
        artifact = transition("handoff", {"destination":"canonical"}, binding())
        self.assertEqual(artifact["payload"]["destination"], "canonical")
        with self.assertRaises(ProductionLifecycleError):
            consume("handoff", artifact, binding(project_id="another"))
        with self.assertRaises(ProductionLifecycleError):
            consume("unknown", artifact, binding())
        assert_no_legacy_direct_consumer({"consume":consume})
        with self.assertRaisesRegex(ProductionLifecycleError, "legacy"):
            assert_no_legacy_direct_consumer({"consume_legacy":lambda value:value})


if __name__ == "__main__": unittest.main()
