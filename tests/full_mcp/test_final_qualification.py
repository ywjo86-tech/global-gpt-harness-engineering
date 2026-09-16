from __future__ import annotations

import json
import unittest
from pathlib import Path

from runtime.full_mcp import qualification as q

PROJECT_ID = "GH-FULL-MCP-PH4"
EXPECTED_EVIDENCE = tuple([f"EVD-{n:03d}" for n in range(1, 19)] + ["EVD-021"])
EXPECTED_GATES = tuple(f"GATE-{n:03d}" for n in range(1, 6))
OFFICIAL_CROSSWALK = {
    "Contract Conformance": (("TEST-003",), ("EVD-004",)),
    "Filesystem": (("TEST-006", "TEST-007", "TEST-008"), ("EVD-005",)),
    "Shell": (("TEST-009", "TEST-010"), ("EVD-006",)),
    "Git": (("TEST-011", "TEST-012", "TEST-013"), ("EVD-007",)),
    "Test / Build": (("TEST-014", "TEST-015", "TEST-016", "TEST-017"), ("EVD-008",)),
    "Security": (("TEST-004", "TEST-005", "TEST-010", "TEST-012", "TEST-026", "TEST-029"), ("EVD-009", "EVD-010", "EVD-013", "EVD-016")),
    "Audit": (("TEST-019",), ("EVD-011",)),
    "Failure Handling": (("TEST-020", "TEST-021"), ("EVD-012", "EVD-013")),
    "Restore": (("TEST-012", "TEST-021", "TEST-024"), ("EVD-013", "EVD-017")),
    "Structured Observability Compatibility": (("TEST-019", "TEST-026"), ("EVD-011", "EVD-016")),
    "Contract-only Handoff Compatibility": (("TEST-003", "TEST-022"), ("EVD-004", "EVD-014")),
    "E2E Execution": (("TEST-024", "TEST-027"), ("EVD-017", "EVD-018")),
}


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _root() -> Path:
    return Path(__file__).resolve().parents[2]


def _active_pre_final() -> tuple[Path, dict]:
    base = _root() / "_workspace" / "full-mcp"
    found: list[tuple[Path, dict]] = []
    for path in sorted(base.glob("*/attempts/*/indexes/PREFINAL.json")):
        record = _load(path)
        if record.get("project_id") == PROJECT_ID and record.get("index_scope") == "PREFINAL":
            found.append((path, record))
    if len(found) != 1:
        raise AssertionError(f"expected exactly one active PREFINAL index, found={len(found)}")
    return found[0]


def _run_root(pre_final_path: Path) -> Path:
    return pre_final_path.parents[3]


def _read_ref(run_root: Path, relative_path: str) -> dict:
    path = run_root / relative_path
    if not path.is_file():
        raise AssertionError(f"missing referenced artifact: {relative_path}")
    return _load(path)


def _validate_prior_gate(run_root: Path, gate_ref: dict) -> tuple[dict, dict]:
    gate = _read_ref(run_root, gate_ref["relative_path"])
    review = _read_ref(run_root, gate["review_ref"])
    index = _read_ref(run_root, gate["selection_index_ref"])
    q.validate_review(review)
    q.validate_selection_index(index)
    q.validate_gate_decision(gate, review=review, index=index)
    if gate["record_digest"] != gate_ref["record_digest"] or gate["decision"] != "GO":
        raise AssertionError(f"invalid prerequisite gate ref: {gate_ref['gate_id']}")
    return gate, review


class PreFinalQualificationTests(unittest.TestCase):
    def test_pre_final_package_is_complete_and_acyclic(self) -> None:
        pre_path, pre = _active_pre_final()
        run_root = _run_root(pre_path)
        q.validate_selection_index(pre)
        self.assertEqual(pre["attempt"], 2)
        self.assertEqual(tuple(x["evidence_id"] for x in pre["evidence_entries"]), EXPECTED_EVIDENCE)
        self.assertNotIn("EVD-019", EXPECTED_EVIDENCE)
        self.assertNotIn("EVD-020", EXPECTED_EVIDENCE)
        self.assertEqual(tuple(x["gate_id"] for x in pre["prerequisite_gate_refs"]), EXPECTED_GATES)
        self.assertEqual(tuple(x["gate_id"] for x in pre["review_refs"]), EXPECTED_GATES)

        evidence_by_id: dict[str, dict] = {}
        for entry in pre["evidence_entries"]:
            evidence = _read_ref(run_root, entry["relative_path"])
            q.validate_evidence(evidence)
            self.assertEqual(evidence["record_digest"], entry["record_digest"])
            self.assertEqual(evidence["verdict"], "PASS")
            evidence_by_id[evidence["evidence_id"]] = evidence
            for ref in evidence["validation_result_refs"]:
                result = _read_ref(run_root, ref["relative_path"])
                q.validate_validation_result(result)
                self.assertEqual(result["result_digest"], ref["result_digest"])
                self.assertEqual(result["verdict"], "PASS")

        gates: dict[str, dict] = {}
        reviews: dict[str, dict] = {}
        for gate_ref in pre["prerequisite_gate_refs"]:
            gate, review = _validate_prior_gate(run_root, gate_ref)
            gates[gate_ref["gate_id"]] = gate
            reviews[gate_ref["gate_id"]] = review
        for review_ref in pre["review_refs"]:
            review = _read_ref(run_root, review_ref["relative_path"])
            q.validate_review(review)
            self.assertEqual(review["record_digest"], review_ref["record_digest"])
            self.assertEqual(review["finding_counts"]["blocker"], 0)
            self.assertEqual(review["finding_counts"]["major"], 0)
            self.assertEqual(review["record_digest"], reviews[review_ref["gate_id"]]["record_digest"])

        official_path = run_root / "attempts" / str(pre["attempt"]) / "gates" / "official-exit-gates.json"
        official = _load(official_path)
        q.validate_official_exit(official, source_gate=gates["GATE-005"])
        self.assertEqual(tuple(row["name"] for row in official["rows"]), q.OFFICIAL_EXIT_NAMES)
        self.assertTrue(all(row["result"] == "PASS" for row in official["rows"]))
        for row in official["rows"]:
            tests, evidence_ids = OFFICIAL_CROSSWALK[row["name"]]
            self.assertEqual(tuple(row["required_test_ids"]), tests)
            self.assertEqual(tuple(row["required_evidence_ids"]), evidence_ids)
            self.assertEqual({x["evidence_id"] for x in row["evidence_refs"]}, set(evidence_ids))
            self.assertTrue(set(tests) <= {x["test_id"] for x in row["validation_refs"]})
            for ref in row["evidence_refs"]:
                self.assertEqual(ref["record_digest"], evidence_by_id[ref["evidence_id"]]["record_digest"])
            for ref in row["validation_refs"]:
                result = _read_ref(run_root, ref["relative_path"])
                q.validate_validation_result(result)
                self.assertEqual(result["result_digest"], ref["result_digest"])
                self.assertEqual(result["verdict"], "PASS")


class FinalHandoffQualificationTests(unittest.TestCase):
    def test_phase5_handoff_cross_binding_is_candidate_only(self) -> None:
        pre_path, pre = _active_pre_final()
        run_root = _run_root(pre_path)
        attempt = pre["attempt"]
        official = _load(run_root / "attempts" / str(attempt) / "gates" / "official-exit-gates.json")
        evd019 = _load(run_root / "attempts" / str(attempt) / "evidence" / "EVD-019.json")
        test028 = _load(run_root / "attempts" / str(attempt) / "validation-results" / "TEST-028" / "TASK-014.json")
        handoff = _load(run_root / "attempts" / str(attempt) / "qualification" / "phase5-handoff.json")

        q.validate_selection_index(pre)
        q.validate_official_exit(official)
        q.validate_validation_result(test028)
        q.validate_evidence(evd019)
        q.validate_phase5_handoff(handoff)
        self.assertEqual(evd019["verdict"], "PASS")
        self.assertEqual(evd019["test_refs"], ["TEST-028"])
        self.assertEqual(evd019["validation_result_refs"][0]["result_digest"], test028["result_digest"])
        self.assertEqual(handoff["pre_final_index_ref"], pre_path.relative_to(run_root).as_posix())
        self.assertEqual(handoff["pre_final_index_digest"], pre["index_digest"])
        self.assertEqual(handoff["official_exit_digest"], official["record_digest"])
        self.assertEqual(handoff["evd019_digest"], evd019["record_digest"])
        self.assertEqual(handoff["execution_mode"], "HYBRID")
        self.assertEqual(handoff["provider_selection_authority"], "PROVIDER_ROUTER")
        self.assertEqual(handoff["handoff_status"], "CANDIDATE_NOT_AUTHORIZED")
        self.assertEqual(tuple(x["gate_id"] for x in handoff["prerequisite_gate_refs"]), EXPECTED_GATES)
        for gate_ref in handoff["prerequisite_gate_refs"]:
            gate = _read_ref(run_root, gate_ref["relative_path"])
            self.assertEqual(gate["record_digest"], gate_ref["record_digest"])
            self.assertEqual(gate["decision"], "GO")


if __name__ == "__main__":
    unittest.main()
