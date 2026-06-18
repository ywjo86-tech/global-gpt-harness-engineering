from __future__ import annotations

import unittest

from runtime.orchestrator.result_normalizer import SCHEMA_VERSION, normalize_worker_result, render_worker_handoff_markdown
from runtime.orchestrator.schemas import TaskSlice


class ResultNormalizerTest(unittest.TestCase):
    def test_normalizes_synonym_payloads(self) -> None:
        task = TaskSlice(
            thread_id="T1",
            assigned_agent="documentation_agent",
            input="refresh docs",
            expected_output="updated docs",
            validation_criteria=["docs updated"],
            editable_scope=["docs/"],
            forbidden_scope=["runtime/"],
            merge_point="docs",
        )
        payload = {
            "thread": "T1",
            "agent": "documentation_agent",
            "state": "done",
            "message": "docs refreshed",
            "issues": ["none"],
            "cautions": ["review later"],
            "failures": [],
            "outputs": ["docs/handoff.md"],
            "recommendation": "merge",
        }
        normalized = normalize_worker_result(
            payload,
            task=task,
            source="collector",
            output_dir="C:/tmp/out",
            run_id="run-123",
            run_root="C:/tmp/run",
        )

        self.assertEqual(normalized["schema_version"], SCHEMA_VERSION)
        self.assertEqual(normalized["thread_id"], "T1")
        self.assertEqual(normalized["agent_name"], "documentation_agent")
        self.assertEqual(normalized["status"], "completed")
        self.assertEqual(normalized["summary"], "docs refreshed")
        self.assertEqual(normalized["findings"], ["none"])
        self.assertEqual(normalized["warnings"], ["review later"])
        self.assertEqual(normalized["artifacts"], ["docs/handoff.md"])
        self.assertEqual(normalized["next_step"], "merge")
        self.assertEqual(normalized["approval_classification"], "general")

    def test_renders_handoff_markdown(self) -> None:
        markdown = render_worker_handoff_markdown(
            {
                "schema_version": SCHEMA_VERSION,
                "source": "worker",
                "mode": "mock",
                "run_id": "run-123",
                "thread_id": "T1",
                "agent_name": "qa_reviewer_agent",
                "status": "completed",
                "summary": "done",
                "findings": ["ok"],
                "warnings": [],
                "errors": [],
                "artifacts": [],
                "validation_criteria": ["check 1"],
                "editable_scope": ["docs/"],
                "forbidden_scope": ["runtime/"],
                "input_files": ["docs/DEVELOPMENT_PLAN.txt"],
                "next_step": "review",
                "approval_classification": "general",
                "prompt_path": "C:/tmp/prompt.md",
                "output_dir": "C:/tmp/out",
                "handoff_report_path": "C:/tmp/out/handoff_report.md",
                "result_path": "C:/tmp/out/result.json",
                "manual_execution_path": "C:/tmp/out/manual_execution.md",
            }
        )

        self.assertIn("Schema Version", markdown)
        self.assertIn("qa_reviewer_agent", markdown)
        self.assertIn("Validation Criteria", markdown)
        self.assertIn("Paths", markdown)


if __name__ == "__main__":
    unittest.main()
