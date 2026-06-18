from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from runtime.knot_v2.semantic_checker import KnotV2SemanticChecker


class KnotV2SemanticCheckerTest(unittest.TestCase):
    def test_detects_merge_candidates_and_stale_status(self) -> None:
        with TemporaryDirectory() as temp_dir:
            vault = Path(temp_dir)
            (vault / "wiki" / "projects").mkdir(parents=True)
            (vault / "wiki" / "decisions").mkdir(parents=True)
            (vault / "indexes").mkdir(parents=True)
            (vault / "wiki" / "projects" / "alpha.md").write_text(
                "# Alpha\n\n## Current Status\nCompleted.\n\n## Related Pages\n- [[Beta]]\n\n## Handoff Summary\nBlocked by review.\n\n## Next Step\nArchive the project.\n\n## History\nCreated as first page.\n",
                encoding="utf-8",
            )
            (vault / "wiki" / "projects" / "alpha-copy.md").write_text(
                "# Alpha\n\n## Notes\nDuplicate placeholder page.\n",
                encoding="utf-8",
            )
            (vault / "wiki" / "projects" / "beta.md").write_text(
                "# Beta\n\n## Current Status\nNot started.\n\n## Related Pages\n- [[Alpha]]\n",
                encoding="utf-8",
            )
            (vault / "wiki" / "projects" / "gamma.md").write_text(
                "# Gamma\n\n## Current Status\nCompleted.\n\n## Handoff Summary\nReady for handoff to implementation.\n\n## Next Step\nContinue implementation work.\n",
                encoding="utf-8",
            )
            (vault / "wiki" / "projects" / "delta.md").write_text(
                "# Delta\n\n## Current Status\nBlocked.\n\n## History\nMarked as completed in the prior review.\n\n## Handoff Summary\nReady for handoff to closeout.\n\n## Next Step\nContinue implementation work.\n",
                encoding="utf-8",
            )
            (vault / "wiki" / "decisions" / "approve-gamma.md").write_text(
                "# Approve Gamma\n\n## Decision\nApproved with conditions.\n\n## Current Status\nBlocked.\n\n## Related Pages\n- [[Gamma]]\n",
                encoding="utf-8",
            )
            (vault / "indexes" / "project-index.md").write_text(
                "# Project Index\n\n- [[Alpha]]\n- [[Beta]]\n- [[Gamma]]\n- [[Delta]]\n",
                encoding="utf-8",
            )
            checker = KnotV2SemanticChecker()
            report = checker.scan(vault)
            finding_types = {finding.finding_type for finding in report.findings}
            self.assertIn("contradiction", finding_types)
            self.assertIn("handoff_drift", finding_types)
            self.assertIn("decision_drift", finding_types)
            self.assertIn("merge_candidate", finding_types)
            self.assertIn("stale_status", finding_types)
            self.assertIn("coverage_gap", finding_types)
            self.assertGreaterEqual(len(report.contradiction_findings), 1)
            self.assertGreaterEqual(len(report.handoff_drift_findings), 1)
            self.assertGreaterEqual(len(report.decision_drift_findings), 1)
            self.assertTrue(report.contradiction_findings)
            self.assertTrue(report.handoff_drift_findings)
            self.assertTrue(report.decision_drift_findings)
            self.assertTrue(
                any(
                    finding.finding_type == "merge_candidate"
                    and any("wiki/projects/alpha.md" == page for page in finding.pages)
                    and finding.severity == "high"
                    for finding in report.findings
                )
            )
            self.assertTrue(
                any(
                    finding.finding_type == "stale_status"
                    and any("wiki/projects/beta.md" == page for page in finding.pages)
                    and finding.severity == "high"
                    for finding in report.findings
                )
            )
            self.assertTrue(
                any(
                    finding.finding_type == "coverage_gap"
                    and any("wiki/projects/alpha-copy.md" == page for page in finding.pages)
                    and finding.severity == "high"
                    for finding in report.findings
                )
            )
            self.assertTrue(
                any(
                    finding.finding_type == "handoff_drift"
                    and any("wiki/projects/alpha.md" == page for page in finding.pages)
                    and finding.severity == "high"
                    for finding in report.findings
                )
            )
            self.assertTrue(report.render_markdown().startswith("# Knot v2 Semantic Report"))

    def test_page_type_specific_drift_rules(self) -> None:
        with TemporaryDirectory() as temp_dir:
            vault = Path(temp_dir)
            (vault / "wiki" / "projects").mkdir(parents=True)
            (vault / "wiki" / "decisions").mkdir(parents=True)
            (vault / "wiki" / "concepts").mkdir(parents=True)
            (vault / "indexes").mkdir(parents=True)
            (vault / "wiki" / "projects" / "alpha.md").write_text(
                "# Alpha\n\n## Current Status\nBlocked.\n\n## Decision\nGO.\n\n## Related Pages\n- [[Approve Alpha]]\n",
                encoding="utf-8",
            )
            (vault / "wiki" / "decisions" / "approve-alpha.md").write_text(
                "# Approve Alpha\n\n## Decision\nApproved.\n\n## Current Status\nApproved.\n\n## Related Pages\n- [[Alpha]]\n",
                encoding="utf-8",
            )
            (vault / "wiki" / "decisions" / "conditional-alpha.md").write_text(
                "# Conditional Alpha\n\n## Decision\nConditional GO.\n\n## Current Status\nBlocked.\n\n## Related Pages\n- [[Alpha]]\n",
                encoding="utf-8",
            )
            (vault / "wiki" / "concepts" / "llm-wiki.md").write_text(
                "# LLM Wiki\n\n## Current Status\nReady for handoff.\n\n## Decision\nApproved.\n\n## Handoff Summary\nReady for handoff to implementation.\n",
                encoding="utf-8",
            )
            (vault / "wiki" / "concepts" / "llm-wiki-conflict.md").write_text(
                "# LLM Wiki Conflict\n\n## Current Status\nCompleted.\n\n## History\nBlocked in prior draft.\n\n## Related Pages\n- [[LLM Wiki]]\n",
                encoding="utf-8",
            )
            (vault / "wiki" / "concepts" / "draft-concept.md").write_text(
                "# Draft Concept\n\n## Current Status\nDraft.\n",
                encoding="utf-8",
            )
            (vault / "indexes" / "project-index.md").write_text(
                "# Project Index\n\n## Handoff Summary\nReady for handoff.\n\n## Next Step\nContinue implementation.\n",
                encoding="utf-8",
            )
            checker = KnotV2SemanticChecker()
            report = checker.scan(vault)
            self.assertTrue(
                any(
                    finding.finding_type == "decision_drift" and any("wiki/concepts/llm-wiki.md" == page for page in finding.pages)
                    for finding in report.findings
                )
            )
            self.assertTrue(
                any(
                    finding.finding_type == "handoff_drift" and any("indexes/project-index.md" == page for page in finding.pages)
                    for finding in report.findings
                )
            )
            self.assertTrue(
                any(
                    finding.finding_type == "handoff_drift"
                    and any("wiki/concepts/llm-wiki.md" == page for page in finding.pages)
                    and finding.severity == "low"
                    for finding in report.findings
                )
            )
            self.assertTrue(
                any(
                    finding.finding_type == "handoff_drift"
                    and any("indexes/project-index.md" == page for page in finding.pages)
                    and finding.severity == "low"
                    for finding in report.findings
                )
            )
            self.assertTrue(
                any(
                    finding.finding_type == "decision_drift" and any("wiki/decisions/approve-alpha.md" == page for page in finding.pages)
                    for finding in report.findings
                )
            )
            self.assertTrue(
                any(
                    finding.finding_type == "decision_drift" and any("wiki/decisions/conditional-alpha.md" == page for page in finding.pages)
                    for finding in report.findings
                )
            )
            self.assertTrue(
                any(
                    finding.finding_type == "contradiction"
                    and any("wiki/concepts/llm-wiki-conflict.md" == page for page in finding.pages)
                    and finding.severity == "low"
                    for finding in report.findings
                )
            )
            self.assertTrue(
                any(
                    finding.finding_type == "stale_status"
                    and any("wiki/concepts/draft-concept.md" == page for page in finding.pages)
                    and finding.severity == "low"
                    for finding in report.findings
                )
            )
            self.assertTrue(
                any(
                    finding.finding_type == "decision_drift"
                    and any("wiki/projects/alpha.md" == page for page in finding.pages)
                    and finding.severity == "high"
                    for finding in report.findings
                )
            )
            self.assertTrue(
                any(
                    finding.finding_type == "decision_drift"
                    and any("wiki/decisions/conditional-alpha.md" == page for page in finding.pages)
                    and finding.severity == "medium"
                    for finding in report.findings
                )
            )
            self.assertGreaterEqual(len(report.decision_drift_findings), 1)
            self.assertGreaterEqual(len(report.handoff_drift_findings), 1)

    def test_page_type_specific_handoff_quality_rules(self) -> None:
        with TemporaryDirectory() as temp_dir:
            vault = Path(temp_dir)
            (vault / "wiki" / "projects").mkdir(parents=True)
            (vault / "wiki" / "decisions").mkdir(parents=True)
            (vault / "wiki" / "concepts").mkdir(parents=True)
            (vault / "indexes").mkdir(parents=True)
            (vault / "wiki" / "projects" / "epsilon.md").write_text(
                "# Epsilon\n\n## Current Status\nIn progress.\n\n## Handoff Summary\nLooks good overall, probably ready soon.\n\n## Open Questions\n- Need final approval.\n",
                encoding="utf-8",
            )
            (vault / "wiki" / "decisions" / "zeta.md").write_text(
                "# Zeta\n\n## Current Status\nOpen.\n",
                encoding="utf-8",
            )
            (vault / "wiki" / "concepts" / "eta.md").write_text(
                "# Eta\n\n## Current Status\nOpen.\n",
                encoding="utf-8",
            )
            (vault / "indexes" / "concept-index.md").write_text(
                "# Concept Index\n\n- [[Eta]]\n",
                encoding="utf-8",
            )
            checker = KnotV2SemanticChecker()
            report = checker.scan(vault)
            self.assertTrue(
                any(
                    finding.finding_type == "misleading_summary"
                    and any("wiki/projects/epsilon.md" == page for page in finding.pages)
                    and finding.severity == "high"
                    for finding in report.findings
                )
            )
            self.assertTrue(
                any(
                    finding.finding_type == "handoff_quality_issue"
                    and any("wiki/decisions/zeta.md" == page for page in finding.pages)
                    and finding.severity == "medium"
                    for finding in report.findings
                )
            )
            self.assertTrue(
                any(
                    finding.finding_type == "handoff_quality_issue"
                    and any("wiki/concepts/eta.md" == page for page in finding.pages)
                    and finding.severity == "low"
                    for finding in report.findings
                )
            )
            self.assertGreaterEqual(len(report.handoff_quality_findings), 2)
            self.assertGreaterEqual(len(report.misleading_summary_findings), 1)


if __name__ == "__main__":
    unittest.main()
