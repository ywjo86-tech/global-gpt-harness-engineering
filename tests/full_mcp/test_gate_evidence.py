from __future__ import annotations

import importlib.metadata
import json
import tempfile
import unittest
from pathlib import Path

from mcp.types import LATEST_PROTOCOL_VERSION
from runtime.full_mcp import qualification as q

ROOT = Path(__file__).resolve().parents[2]
SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64
GIT_A = "a" * 40
GIT_B = "b" * 40
NOW = "2026-09-16T10:00:00Z"


def source_binding() -> dict:
    return {
        "head_sha": GIT_A, "origin_main_sha": GIT_A, "phase3_sealed_sha": GIT_B,
        "dependency_lock_sha256": SHA_C, "invocation_context_id": "invocation-test",
        "workspace_state_digest": SHA_A,
    }


def snapshot(path: str = "runtime/full_mcp/qualification.py", digest: str = SHA_A) -> dict:
    data = {"source_set_name": "BOOTSTRAP_SOURCE_SET", "files": [{"path": path, "sha256": digest, "mode": "100644"}], "artifact_inputs": []}
    data["snapshot_digest"] = q.source_snapshot_digest(data)
    return data
def validation_result(test_id: str = "TEST-002", consumer: str = "TASK-002", digest: str = SHA_A) -> dict:
    record = {
        "schema_version": "gch.full-mcp.validation-result.v1", "project_id": "GH-FULL-MCP-PH4",
        "run_id": "run-test", "attempt": 1, "test_id": test_id, "consumer_task_id": consumer,
        "producer_task_id": consumer, "test_contract_digest": SHA_A, "profile_id": None,
        "profile_digest": None, "selector_digest": SHA_B, "started_at_utc": NOW, "ended_at_utc": NOW,
        "verdict": "PASS", "exit_status_category": "EXIT_0", "assertion_summary_digest": SHA_C,
        "audit_ref": f"events/execution-events.jsonl#{test_id}", "audit_digest": SHA_A,
        "source_snapshot": snapshot(digest=digest),
    }
    return q.seal_digest(record, "result_digest")


def evidence(evidence_id: str, test_id: str, result_path: str, result: dict) -> dict:
    record = {
        "schema_version": "gch.full-mcp.evidence.v2", "evidence_id": evidence_id,
        "project_id": "GH-FULL-MCP-PH4", "run_id": "run-test", "origin_gate_id": "GATE-001",
        "attempt": 1, "requirement_refs": ["REQ-001"], "task_refs": ["TASK-002"],
        "test_refs": [test_id], "producer_task_id": "TASK-002",
        "validation_result_refs": [{"test_id": test_id, "source_attempt": 1, "consumer_task_id": "TASK-002", "relative_path": result_path, "result_digest": result["result_digest"]}],
        "artifact_refs": [], "verdict": "PASS", "collected_at_utc": NOW,
        "source_binding": source_binding(),
    }
    return q.seal_digest(record, "record_digest")
def review(index: dict, blocker: int = 0, major: int = 0, minor: int = 0) -> dict:
    findings = ([{"ref": f"b{i}", "severity": "blocker"} for i in range(blocker)] +
                [{"ref": f"m{i}", "severity": "major"} for i in range(major)] +
                [{"ref": f"n{i}", "severity": "minor"} for i in range(minor)])
    record = {
        "schema_version": "gch.full-mcp.review.v1", "project_id": "GH-FULL-MCP-PH4",
        "run_id": "run-test", "attempt": 1, "gate_id": "GATE-001", "review_role": "independent",
        "reviewer_authority": "test-authority", "selection_index_ref": "attempts/1/indexes/GATE-001.json",
        "selection_index_digest": index["index_digest"], "finding_refs": findings,
        "finding_counts": {"blocker": blocker, "major": major, "minor": minor}, "reviewed_at_utc": NOW,
    }
    return q.seal_digest(record, "record_digest")


def workspace_state(unauthorized: int = 0) -> dict:
    record = {
        "schema_version": "gch.full-mcp.workspace-state.v1", "head_sha": GIT_A,
        "approved_target_manifest_sha256": SHA_A, "tracked_diff_sha256": SHA_B,
        "untracked_owned_manifest_sha256": SHA_C, "unauthorized_change_manifest_sha256": SHA_A,
        "unauthorized_change_count": unauthorized, "captured_at_utc": NOW,
    }
    record["state_digest"] = q.workspace_state_digest(record)
    return record
class GateEvidenceBootstrapTests(unittest.TestCase):
    def test_sdk_protocol_and_dependency_lock(self) -> None:
        self.assertEqual(importlib.metadata.version("mcp"), "2.2.0")
        self.assertEqual(importlib.metadata.version("mcp-types"), "2.2.0")
        self.assertEqual(LATEST_PROTOCOL_VERSION, "2026-07-28")
        pins = (ROOT / "requirements/full-mcp.txt").read_text(encoding="utf-8")
        self.assertEqual(pins, "mcp==2.2.0\nmcp-types==2.2.0\n")
        lock = (ROOT / "requirements/full-mcp.lock").read_text(encoding="utf-8")
        self.assertIn("mcp==2.2.0", lock)
        self.assertIn("mcp-types==2.2.0", lock)

    def test_validation_result_digest_and_freshness(self) -> None:
        result = validation_result()
        q.validate_validation_result(result)
        self.assertTrue(q.validation_result_fresh(result, {"runtime/full_mcp/qualification.py": SHA_A}, {}))
        self.assertFalse(q.validation_result_fresh(result, {"runtime/full_mcp/qualification.py": SHA_B}, {}))
        tampered = dict(result)
        tampered["verdict"] = "FAIL"
        with self.assertRaises(q.QualificationError):
            q.validate_validation_result(tampered)

    def test_evidence_requires_bound_fresh_pass_result(self) -> None:
        result = validation_result()
        path = "attempts/1/validation-results/TEST-002/TASK-002.json"
        evd = evidence("EVD-003", "TEST-002", path, result)
        q.validate_evidence(evd)
        self.assertTrue(q.evidence_fresh(evd, {path: result}, {"runtime/full_mcp/qualification.py": SHA_A}, {}))
        self.assertFalse(q.evidence_fresh(evd, {path: result}, {"runtime/full_mcp/qualification.py": SHA_B}, {}))
    def test_selection_review_and_gate001_go(self) -> None:
        result = validation_result()
        result_path = "attempts/1/validation-results/TEST-002/TASK-002.json"
        evidence_by_id = {name: evidence(name, "TEST-002", result_path, result) for name in ("EVD-001", "EVD-002", "EVD-003")}
        entries = [{"evidence_id": name, "source_attempt": 1, "relative_path": f"attempts/1/evidence/{name}.json", "record_digest": evd["record_digest"], "verdict": "PASS", "origin_gate_id": "GATE-001"} for name, evd in evidence_by_id.items()]
        state = workspace_state()
        index = q.build_selection_index(project_id="GH-FULL-MCP-PH4", run_id="run-test", attempt=1, index_scope="GATE-001", workspace_state_ref="attempts/1/source/workspace-state.json", workspace_state_digest=state["state_digest"], evidence_entries=entries, prerequisite_gate_refs=[], review_refs=[], generated_at_utc=NOW)
        rev = review(index)
        gate = q.evaluate_gate(gate_id="GATE-001", project_id="GH-FULL-MCP-PH4", run_id="run-test", attempt=1, index=index, review=rev, evidence_by_id=evidence_by_id, prerequisite_gates={}, official_acceptance_results={}, source_binding=source_binding(), review_ref="attempts/1/reviews/GATE-001.json", selection_index_ref="attempts/1/indexes/GATE-001.json", evaluated_at_utc=NOW, validation_results_by_path={result_path: result}, current_file_digests={"runtime/full_mcp/qualification.py": SHA_A}, current_artifact_digests={}, workspace_state=state)
        self.assertEqual(gate["decision"], "GO")
        q.validate_gate_decision(gate, review=rev, index=index)
        blocked = q.evaluate_gate(gate_id="GATE-001", project_id="GH-FULL-MCP-PH4", run_id="run-test", attempt=1, index=index, review=rev, evidence_by_id=evidence_by_id, prerequisite_gates={}, official_acceptance_results={}, source_binding=source_binding(), review_ref="attempts/1/reviews/GATE-001.json", selection_index_ref="attempts/1/indexes/GATE-001.json", evaluated_at_utc=NOW, validation_results_by_path={result_path: result}, current_file_digests={"runtime/full_mcp/qualification.py": SHA_A}, current_artifact_digests={}, workspace_state=workspace_state(1))
        self.assertEqual(blocked["decision"], "NO_GO")
        stale = q.evaluate_gate(gate_id="GATE-001", project_id="GH-FULL-MCP-PH4", run_id="run-test", attempt=1, index=index, review=rev, evidence_by_id=evidence_by_id, prerequisite_gates={}, official_acceptance_results={}, source_binding=source_binding(), review_ref="attempts/1/reviews/GATE-001.json", selection_index_ref="attempts/1/indexes/GATE-001.json", evaluated_at_utc=NOW, validation_results_by_path={result_path: result}, current_file_digests={"runtime/full_mcp/qualification.py": SHA_B}, current_artifact_digests={}, workspace_state=state)
        self.assertEqual(stale["decision"], "NO_GO")
    def test_source_binding_uses_git_commit_sha_not_sha256(self) -> None:
        result = validation_result()
        path = "attempts/1/validation-results/TEST-002/TASK-002.json"
        evd = evidence("EVD-003", "TEST-002", path, result)
        q.validate_evidence(evd)
        broken = dict(evd)
        broken["source_binding"] = dict(evd["source_binding"], head_sha=SHA_A)
        broken = q.seal_digest(broken, "record_digest")
        with self.assertRaises(q.QualificationError):
            q.validate_evidence(broken)

    def test_gate_policy_binds_prerequisite_evidence(self) -> None:
        self.assertEqual(
            q.required_evidence_for_gate("GATE-002"),
            tuple(f"EVD-{n:03d}" for n in range(1, 9)),
        )
        self.assertIn("EVD-021", q.required_evidence_for_gate("GATE-006"))
        self.assertIn("EVD-019", q.required_evidence_for_gate("GATE-006"))
        self.assertIn("EVD-020", q.required_evidence_for_gate("GATE-006"))

    def test_official_exit_exact_order(self) -> None:
        rows = [
            {"name": name, "result": "PASS", "validation_refs": [], "evidence_refs": []}
            for name in q.OFFICIAL_EXIT_NAMES
        ]
        record = q.seal_digest({
            "schema_version": "gch.full-mcp.official-exit-gates.v1",
            "project_id": "GH-FULL-MCP-PH4", "run_id": "run-test", "attempt": 1,
            "source_gate_ref": "attempts/1/gates/GATE-005.json", "source_gate_digest": SHA_A,
            "rows": rows, "generated_at_utc": NOW,
        }, "record_digest")
        q.validate_official_exit(record)
        reversed_record = dict(record)
        reversed_record["rows"] = list(reversed(rows))
        reversed_record = q.seal_digest(reversed_record, "record_digest")
        with self.assertRaises(q.QualificationError):
            q.validate_official_exit(reversed_record)

    def test_create_once_and_invalidation(self) -> None:
        result = validation_result()
        result_path = "attempts/1/validation-results/TEST-002/TASK-002.json"
        evd = evidence("EVD-003", "TEST-002", result_path, result)
        impact = q.compute_invalidation(
            changed_paths=["runtime/full_mcp/qualification.py"],
            validation_results_by_path={result_path: result},
            evidence_by_path={"attempts/1/evidence/EVD-003.json": evd},
            gate_records={},
        )
        self.assertEqual(impact["stale_validation_result_refs"], [result_path])
        self.assertEqual(impact["stale_evidence_refs"], ["attempts/1/evidence/EVD-003.json"])
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / "record.json"
            q.write_create_once_json(target, evd)
            self.assertTrue(target.exists())
            with self.assertRaises(FileExistsError):
                q.write_create_once_json(target, evd)


if __name__ == "__main__":
    unittest.main()
