from __future__ import annotations

import tempfile
import unittest
from pathlib import Path


class LiveAutoCanaryTests(unittest.TestCase):
    def test_canary_completes_after_foreground_owner_loss(self):
        from runtime.orchestrator.live_auto_canary import LiveAutoCanary
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state_root = root / "state"; state_root.mkdir()
            runtime_root = Path.cwd().resolve()
            canary = LiveAutoCanary(state_root, runtime_code_root=runtime_root, run_id="canary-loss")
            canary.prepare()
            dropped = canary.run_gate_a_then_drop_foreground_owner(timeout_seconds=15)
            self.assertTrue(dropped["foreground_owner_dropped"])
            self.assertEqual(dropped["completed_receipts"], ["CANARY-A"])
            result = canary.reconcile_until_idle(use_systemd=False, timeout_seconds=20)
            self.assertEqual(result["state"], "COMPLETED")
            self.assertEqual(result["terminal_reason"], "ALL_GATES_COMPLETED")
            evidence = canary.seal_evidence(reconciler_mode="DIRECT_TEST_RECONCILER")
            self.assertEqual(evidence["receipt_count"], 3)
            self.assertEqual(evidence["chat_resume_count"], 0)
            self.assertTrue(evidence["foreground_owner_dropped"])
            self.assertEqual(evidence["external_effect_count"], 0)
            self.assertEqual(len(set(evidence["commit_heads"])), 3)

    def test_canary_receipts_are_v2_no_external_effect_and_survive_workspace_cleanup(self):
        from runtime.orchestrator.live_auto_canary import LiveAutoCanary
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); state_root = root / "state"; state_root.mkdir()
            canary = LiveAutoCanary(state_root, runtime_code_root=Path.cwd(), run_id="canary-retention")
            canary.prepare(); canary.run_gate_a_then_drop_foreground_owner(timeout_seconds=15)
            canary.reconcile_until_idle(use_systemd=False, timeout_seconds=20)
            evidence = canary.seal_evidence(reconciler_mode="DIRECT_TEST_RECONCILER")
            for receipt in canary.load_receipts():
                self.assertEqual(receipt["schema_version"], "orchestration.live-auto-canary-receipt.v2")
                self.assertEqual(receipt["external_effect_policy"], "NO_EXTERNAL_EFFECT")
                self.assertEqual(receipt["external_effects"], [])
            evidence_path = canary.evidence_path
            canary.cleanup_project_workspace()
            self.assertFalse(canary.project_root.exists())
            self.assertTrue(evidence_path.is_file())
            self.assertEqual(canary.load_evidence()["evidence_sha256"], evidence["evidence_sha256"])

    def test_canary_executor_kind_is_closed_and_has_no_network_or_package_effects(self):
        from runtime.orchestrator.live_auto_canary import CANARY_EXECUTOR_KIND, canary_authority_profile
        self.assertEqual(CANARY_EXECUTOR_KIND, "DCC_LIVE_AUTO_CANARY")
        profile = canary_authority_profile()
        self.assertEqual(profile["network"], "DENIED")
        self.assertEqual(profile["credentials"], "DENIED")
        self.assertEqual(profile["packages"], "DENIED")
        self.assertEqual(profile["external_effect_policy"], "NO_EXTERNAL_EFFECT")


if __name__ == "__main__":
    unittest.main()
