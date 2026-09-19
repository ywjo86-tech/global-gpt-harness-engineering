from __future__ import annotations

import ast
import unittest
from pathlib import Path

from runtime.ai_office.baseline_closure import (
    BASELINE_CLOSURE_CANDIDATE_SCHEMA_V1,
    EVIDENCE_REF_SCHEMA_V1,
    REQUIRED_EXIT_EVIDENCE_IDS,
    BaselineClosureEvidenceRefV1,
    build_baseline_closure_candidate,
)

ROOT = Path(__file__).resolve().parents[1]
D = {name: (char * 64) for name, char in zip(REQUIRED_EXIT_EVIDENCE_IDS, "abcdef")}


def evidence(*, mutate_id: str = "", mutate_digest: str = ""):
    rows = []
    for evidence_id in REQUIRED_EXIT_EVIDENCE_IDS:
        digest = mutate_digest if evidence_id == mutate_id and mutate_digest else D[evidence_id]
        rows.append(BaselineClosureEvidenceRefV1(
            EVIDENCE_REF_SCHEMA_V1,
            evidence_id,
            f"evidence:{evidence_id.lower()}",
            digest,
            "PASS",
        ))
    return tuple(rows)


class AIOfficeBaselineClosureTest(unittest.TestCase):
    def test_032_complete_exit_evidence_and_identical_alias_is_go_candidate(self) -> None:
        canonical = evidence()
        candidate = build_baseline_closure_candidate(
            canonical_identity_ref="baseline:ai-office-ph5",
            canonical_evidence=canonical,
            alias_name="AI_OFFICE_STABLE_BASELINE_LOCAL",
            alias_evidence=canonical,
            blocker_count=0,
            unresolved_major_count=0,
            must_traceability_coverage=100,
        )
        self.assertEqual(candidate.schema_version, BASELINE_CLOSURE_CANDIDATE_SCHEMA_V1)
        self.assertEqual(candidate.disposition, "GO_CANDIDATE")
        self.assertEqual(candidate.alias_equality_disposition, "IDENTICAL")
        self.assertEqual(candidate.required_evidence_ids, REQUIRED_EXIT_EVIDENCE_IDS)
        self.assertEqual(len(candidate.candidate_digest), 64)
        self.assertNotIn("declared", candidate.to_dict())
        self.assertNotIn("published", candidate.to_dict())

    def test_032_missing_or_extra_evidence_is_no_go_not_partial_success(self) -> None:
        canonical = evidence()
        missing = build_baseline_closure_candidate(
            canonical_identity_ref="baseline:ai-office-ph5",
            canonical_evidence=canonical[:-1], alias_name="local", alias_evidence=canonical[:-1],
            blocker_count=0, unresolved_major_count=0, must_traceability_coverage=100,
        )
        self.assertEqual(missing.disposition, "NO_GO")
        self.assertIn("INCOMPLETE_CANONICAL_EVIDENCE", missing.reason_codes)
        extra = canonical + (BaselineClosureEvidenceRefV1(EVIDENCE_REF_SCHEMA_V1, "EVD-999", "evidence:extra", "f" * 64, "PASS"),)
        unexpected = build_baseline_closure_candidate(
            canonical_identity_ref="baseline:ai-office-ph5", canonical_evidence=extra,
            alias_name="local", alias_evidence=extra,
            blocker_count=0, unresolved_major_count=0, must_traceability_coverage=100,
        )
        self.assertEqual(unexpected.disposition, "NO_GO")
        self.assertIn("UNEXPECTED_CANONICAL_EVIDENCE", unexpected.reason_codes)

    def test_032_alias_set_or_digest_mismatch_is_no_go(self) -> None:
        canonical = evidence()
        digest_mismatch = build_baseline_closure_candidate(
            canonical_identity_ref="baseline:ai-office-ph5", canonical_evidence=canonical,
            alias_name="local", alias_evidence=evidence(mutate_id="EVD-021", mutate_digest="9" * 64),
            blocker_count=0, unresolved_major_count=0, must_traceability_coverage=100,
        )
        self.assertEqual(digest_mismatch.disposition, "NO_GO")
        self.assertEqual(digest_mismatch.alias_equality_disposition, "MISMATCH")
        self.assertIn("ALIAS_EVIDENCE_MISMATCH", digest_mismatch.reason_codes)
        partial_alias = build_baseline_closure_candidate(
            canonical_identity_ref="baseline:ai-office-ph5", canonical_evidence=canonical,
            alias_name="local", alias_evidence=canonical[:-1],
            blocker_count=0, unresolved_major_count=0, must_traceability_coverage=100,
        )
        self.assertEqual(partial_alias.disposition, "NO_GO")
        self.assertIn("INCOMPLETE_ALIAS_EVIDENCE", partial_alias.reason_codes)

    def test_032_material_exit_metrics_block_candidate(self) -> None:
        canonical = evidence()
        for kwargs, reason in (
            ({"blocker_count": 1, "unresolved_major_count": 0, "must_traceability_coverage": 100}, "BLOCKERS_OPEN"),
            ({"blocker_count": 0, "unresolved_major_count": 1, "must_traceability_coverage": 100}, "MAJORS_OPEN"),
            ({"blocker_count": 0, "unresolved_major_count": 0, "must_traceability_coverage": 99}, "TRACEABILITY_INCOMPLETE"),
        ):
            with self.subTest(reason=reason):
                candidate = build_baseline_closure_candidate(
                    canonical_identity_ref="baseline:ai-office-ph5", canonical_evidence=canonical,
                    alias_name="local", alias_evidence=canonical, **kwargs,
                )
                self.assertEqual(candidate.disposition, "NO_GO")
                self.assertIn(reason, candidate.reason_codes)

    def test_032_non_pass_evidence_and_duplicate_identity_fail_closed(self) -> None:
        canonical = list(evidence())
        canonical[0] = BaselineClosureEvidenceRefV1(
            EVIDENCE_REF_SCHEMA_V1, "EVD-018", "evidence:evd-018", D["EVD-018"], "FAIL")
        candidate = build_baseline_closure_candidate(
            canonical_identity_ref="baseline:ai-office-ph5", canonical_evidence=tuple(canonical),
            alias_name="local", alias_evidence=tuple(canonical),
            blocker_count=0, unresolved_major_count=0, must_traceability_coverage=100,
        )
        self.assertEqual(candidate.disposition, "NO_GO")
        self.assertIn("CANONICAL_EVIDENCE_NOT_PASS", candidate.reason_codes)
        duplicate = evidence() + (evidence()[0],)
        duplicate_candidate = build_baseline_closure_candidate(
            canonical_identity_ref="baseline:ai-office-ph5", canonical_evidence=duplicate,
            alias_name="local", alias_evidence=duplicate,
            blocker_count=0, unresolved_major_count=0, must_traceability_coverage=100,
        )
        self.assertEqual(duplicate_candidate.disposition, "NO_GO")
        self.assertIn("DUPLICATE_CANONICAL_EVIDENCE", duplicate_candidate.reason_codes)

    def test_032_closure_candidate_module_has_no_git_merge_push_deploy_effects(self) -> None:
        path = ROOT / "runtime" / "ai_office" / "baseline_closure.py"
        tree = ast.parse(path.read_text(encoding="utf-8"))
        imports = set()
        calls = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imports.add(node.module or "")
            elif isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name): calls.add(node.func.id)
                elif isinstance(node.func, ast.Attribute): calls.add(node.func.attr)
        self.assertFalse({"subprocess", "git", "shutil"}.intersection(imports))
        self.assertFalse({"system", "run", "Popen", "push", "merge", "deploy"}.intersection(calls))


if __name__ == "__main__":
    unittest.main()
