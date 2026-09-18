from __future__ import annotations

import hashlib
import json
import subprocess
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
    if len(found) == 1:
        return found[0]
    # Runtime transients are intentionally excluded from the integrated stable
    # baseline. Rehydrate the immutable qualified source from the approved
    # Full MCP baseline commit into a temporary, test-owned tree.
    import subprocess, tempfile
    manifest = _load(_root() / "docs/history/upgrades/2026-09-16-UPGRADE-003/MCP_STABLE_BASELINE_FINAL_MANIFEST_20260917.json")
    baseline = manifest["baseline_commit_sha"]
    relative = "_workspace/full-mcp/20260916T123217Z-bd92159d/attempts/2/indexes/PREFINAL.json"
    try:
        raw = subprocess.check_output(["git", "show", f"{baseline}:{relative}"], cwd=_root())
    except subprocess.CalledProcessError as exc:
        raise AssertionError(f"expected exactly one qualified PREFINAL source, active={len(found)}") from exc
    temp = Path(tempfile.mkdtemp(prefix="full-mcp-qualified-"))
    run_root = temp / "20260916T123217Z-bd92159d"
    archive = subprocess.check_output(["git", "archive", baseline, "_workspace/full-mcp/20260916T123217Z-bd92159d"], cwd=_root())
    tar_path = temp / "qualified.tar"
    tar_path.write_bytes(archive)
    subprocess.check_call(["tar", "-xf", str(tar_path), "--strip-components=2", "-C", str(temp)])
    path = run_root / "attempts/2/indexes/PREFINAL.json"
    if not path.is_file() or path.read_bytes() != raw:
        raise AssertionError("qualified PREFINAL rehydration mismatch")
    return path, _load(path)


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
    def test_archived_final_qualification_preserves_pre_final_closure(self) -> None:
        history = _root() / "docs/history/upgrades/2026-09-16-UPGRADE-003"
        official = _load(history / "OFFICIAL_EXIT_GATES.json")
        stable = _load(history / "STABLE_BASELINE_ELIGIBILITY_MANIFEST.json")
        gate6 = _load(history / "GATE-006.json")
        gate6_review = _load(history / "GATE-006_REVIEW.json")
        final_manifest = _load(history / "MCP_STABLE_BASELINE_FINAL_MANIFEST_20260917.json")

        q.validate_official_exit(official)
        q.validate_review(gate6_review)
        q.validate_gate_decision(gate6, review=gate6_review)
        q.validate_stable_baseline_manifest(stable, gate6=gate6)

        self.assertEqual(tuple(row["name"] for row in official["rows"]), q.OFFICIAL_EXIT_NAMES)
        self.assertTrue(all(row["result"] == "PASS" for row in official["rows"]))
        for row in official["rows"]:
            tests, evidence_ids = OFFICIAL_CROSSWALK[row["name"]]
            self.assertEqual(tuple(row["required_test_ids"]), tests)
            self.assertEqual(tuple(row["required_evidence_ids"]), evidence_ids)

        self.assertEqual(stable["official_exit_digest"], official["record_digest"])
        self.assertEqual(stable["gate6_digest"], gate6["record_digest"])
        self.assertEqual(stable["eligibility_status"], "ELIGIBLE")
        self.assertEqual(stable["declaration_status"], "NOT_DECLARED")

        source_refs = {Path(item["path"]).name: item["sha256"] for item in final_manifest["source_records"]}
        self.assertEqual(
            source_refs["official-exit-gates.json"],
            hashlib.sha256((history / "OFFICIAL_EXIT_GATES.json").read_bytes()).hexdigest(),
        )
        self.assertEqual(final_manifest["official_exit_pass"], "12/12")
        self.assertEqual(final_manifest["final_baseline_approval_status"], "APPROVED_SEALED")
        self.assertEqual(
            subprocess.call(
                ["git", "merge-base", "--is-ancestor", final_manifest["baseline_commit_sha"], "HEAD"],
                cwd=_root(),
            ),
            0,
        )


class FinalHandoffQualificationTests(unittest.TestCase):
    def test_phase5_handoff_cross_binding_is_candidate_only(self) -> None:
        history = _root() / "docs/history/upgrades/2026-09-16-UPGRADE-003"
        official = _load(history / "OFFICIAL_EXIT_GATES.json")
        evd019 = _load(history / "EVD-019.json")
        handoff = _load(history / "PHASE5_HANDOFF_CANDIDATE.json")
        stable = _load(history / "STABLE_BASELINE_ELIGIBILITY_MANIFEST.json")
        final_manifest = _load(history / "MCP_STABLE_BASELINE_FINAL_MANIFEST_20260917.json")

        q.validate_official_exit(official)
        q.validate_evidence(evd019)
        q.validate_phase5_handoff(handoff)
        q.validate_stable_baseline_manifest(stable)

        self.assertEqual(evd019["verdict"], "PASS")
        self.assertEqual(evd019["test_refs"], ["TEST-028"])
        self.assertEqual(handoff["official_exit_digest"], official["record_digest"])
        self.assertEqual(handoff["evd019_digest"], evd019["record_digest"])
        self.assertEqual(handoff["execution_mode"], "HYBRID")
        self.assertEqual(handoff["provider_selection_authority"], "PROVIDER_ROUTER")
        self.assertEqual(handoff["handoff_status"], "CANDIDATE_NOT_AUTHORIZED")
        self.assertEqual(tuple(x["gate_id"] for x in handoff["prerequisite_gate_refs"]), EXPECTED_GATES)
        self.assertEqual(stable["phase5_handoff_digest"], handoff["record_digest"])
        self.assertEqual(handoff["pre_final_index_ref"], "attempts/2/indexes/PREFINAL.json")
        self.assertRegex(handoff["pre_final_index_digest"], r"^[0-9a-f]{64}$")

        source_refs = {Path(item["path"]).name: item["sha256"] for item in final_manifest["source_records"]}
        self.assertEqual(
            source_refs["phase5-handoff.json"],
            hashlib.sha256((history / "PHASE5_HANDOFF_CANDIDATE.json").read_bytes()).hexdigest(),
        )
        self.assertFalse(final_manifest["operational_boundary"]["phase5_execution_authorized"])


if __name__ == "__main__":
    unittest.main()
