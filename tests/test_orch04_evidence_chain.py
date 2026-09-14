from __future__ import annotations

import hashlib
import subprocess
import tempfile
import unittest
from pathlib import Path

from runtime.orchestrator.gate_supervisor import PersistentGateSupervisor
from tests.test_worker_authority import assessment, launch, package, quality, worker_result
from runtime.orchestrator.worker_authority import evaluate_worker_result, review_post_quality


class Orch04EvidenceChainTests(unittest.TestCase):
    """Connect existing ORCH04 authorities without introducing a new authority."""

    def test_source_worker_reviewer_contract_and_full_plan_chain(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            subprocess.run(["git", "init", "-q", "-b", "main", str(root)], check=True)
            subprocess.run(["git", "-C", str(root), "config", "user.name", "ORCH04 evidence fixture"], check=True)
            subprocess.run(["git", "-C", str(root), "config", "user.email", "orch04@example.invalid"], check=True)
            source = root / "source.py"
            source.write_text("def bounded_source(value):\n    return value + 1\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(root), "add", "source.py"], check=True)
            subprocess.run(["git", "-C", str(root), "commit", "-qm", "source baseline"], check=True)
            source_head = subprocess.check_output(
                ["git", "-C", str(root), "rev-parse", "HEAD"], text=True
            ).strip()
            source_tree = subprocess.check_output(
                ["git", "-C", str(root), "rev-parse", "HEAD^{tree}"], text=True
            ).strip()
            source_sha = hashlib.sha256(source.read_bytes()).hexdigest()

            contract, execution_package = package()
            worker = worker_result(execution_package)
            worker_gate = evaluate_worker_result(
                execution_package,
                launch(execution_package),
                worker,
                post_completion_assessment=assessment(
                    __import__(
                        "runtime.orchestrator.completion_contract",
                        fromlist=["CompletionState"],
                    ).CompletionState.SATISFIED
                ),
            )
            self.assertTrue(worker_gate.eligible_for_post_quality)
            review = review_post_quality(
                execution_package,
                contract,
                worker,
                worker_gate,
                quality(contract, execution_package, worker),
            )
            self.assertTrue(review.passed)
            self.assertNotEqual(worker.worker_id, "quality-B")

            supervisor = PersistentGateSupervisor(
                root,
                project_id="orch04-evidence",
                run_id="full-plan-evidence-01",
                gate_id="G-4B-RELEASE-HANDOFF",
                mode="FULL_PLAN",
                lv_order=["TASK-ORCH-01", "TASK-ORCH-02"],
            )
            seen: list[tuple[str, str]] = []

            def transition(state):
                seen.append((state["current_lv"], state["stage"]))
                return {"status": "PASS", "next_stage": "GATE_EXIT" if state["stage"] == "GATE_EXIT" else "EXIT"}

            full_plan = supervisor.run(transition)
            self.assertEqual(full_plan.status, "COMPLETED")
            self.assertEqual(full_plan.state["completed_lvs"], ["TASK-ORCH-01", "TASK-ORCH-02"])
            self.assertEqual({item[0] for item in seen}, {"TASK-ORCH-01", "TASK-ORCH-02"})

            evidence = {
                "schema_version": "orch04.evidence-chain.v1",
                "source_provenance": {
                    "head": source_head,
                    "tree": source_tree,
                    "source_sha256": source_sha,
                },
                "worker_provenance": {
                    "worker_id": worker.worker_id,
                    "result_digest": worker.result_digest,
                    "package_digest": execution_package.package_digest,
                },
                "reviewer_provenance": {
                    "reviewer_id": "quality-B",
                    "assessment_digest": quality(contract, execution_package, worker).assessment_digest,
                    "worker_result_digest": worker.result_digest,
                },
                "unified_contract": {
                    "contract_digest": contract.contract_digest,
                    "package_digest": execution_package.package_digest,
                    "criterion_set_digest": execution_package.criterion_set_digest,
                },
                "full_plan": {
                    "mode": full_plan.state["mode"],
                    "completed_lvs": full_plan.state["completed_lvs"],
                    "status": full_plan.status,
                },
            }
            self.assertEqual(evidence["source_provenance"]["head"], source_head)
            self.assertEqual(evidence["worker_provenance"]["result_digest"], worker.result_digest)
            self.assertEqual(evidence["reviewer_provenance"]["worker_result_digest"], worker.result_digest)
            self.assertEqual(evidence["unified_contract"]["contract_digest"], execution_package.contract_digest)
            self.assertEqual(evidence["full_plan"]["status"], "COMPLETED")


if __name__ == "__main__":
    unittest.main()
