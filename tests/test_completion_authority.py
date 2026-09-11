from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from runtime.orchestrator.completion_authority import (
    CRITERION_NODE_BINDINGS,
    MANIFEST_RELATIVE,
    SNAPSHOT_RELATIVE,
    CompletionAuthorityError,
    load_task_4a_08_completion_authority,
    materialize_task_4a_08_completion_authority,
    verify_all_frozen_completion_criteria,
)


SOURCE = """\
def test_product_id_key_is_stable_and_does_not_include_price():
    assert True

def test_fallback_key_canonicalizes_merchant_title_and_url():
    assert True

def test_deduplication_is_order_independent_and_preserves_query_lineage():
    assert True

def test_non_authoritative_extra_behavior():
    assert True
"""


class CompletionAuthorityTests(unittest.TestCase):
    def _roots(self):
        temp = tempfile.TemporaryDirectory()
        base = Path(temp.name)
        project = base / "project"
        package = base / "package"
        (project / "tests").mkdir(parents=True)
        (project / ".venv/bin").mkdir(parents=True)
        (project / ".venv/bin/python").write_text("", encoding="utf-8")
        (project / ".venv/bin/pytest").write_text("", encoding="utf-8")
        package.mkdir()
        (project / "tests/test_deduplicator.py").write_text(SOURCE, encoding="utf-8")
        self.addCleanup(temp.cleanup)
        return project, package

    def test_materializes_only_minimal_approved_node_set(self):
        project, package = self._roots()
        authority = materialize_task_4a_08_completion_authority(project, package)
        self.assertEqual(
            tuple((item.criterion_id, item.node_names) for item in authority.criteria),
            CRITERION_NODE_BINDINGS,
        )
        self.assertTrue((package / SNAPSHOT_RELATIVE).is_file())
        self.assertTrue((package / MANIFEST_RELATIVE).is_file())
        self.assertNotIn(
            "test_non_authoritative_extra_behavior",
            {name for item in authority.criteria for name in item.node_names},
        )

    def test_snapshot_is_create_once_and_does_not_follow_live_worker_changes(self):
        project, package = self._roots()
        authority = materialize_task_4a_08_completion_authority(project, package)
        snapshot_before = (package / SNAPSHOT_RELATIVE).read_bytes()
        (project / "tests/test_deduplicator.py").write_text(
            SOURCE.replace("assert True", "assert False"),
            encoding="utf-8",
        )
        loaded = load_task_4a_08_completion_authority(package)
        self.assertEqual(loaded.snapshot_sha256, authority.snapshot_sha256)
        self.assertEqual((package / SNAPSHOT_RELATIVE).read_bytes(), snapshot_before)

    def test_replay_with_different_preworker_source_fails_closed(self):
        project, package = self._roots()
        materialize_task_4a_08_completion_authority(project, package)
        (project / "tests/test_deduplicator.py").write_text(
            SOURCE + "\ndef another_test(): pass\n",
            encoding="utf-8",
        )
        with self.assertRaises(CompletionAuthorityError) as caught:
            materialize_task_4a_08_completion_authority(project, package)
        self.assertEqual(caught.exception.reason_taxonomy, "COMPLETION_AUTHORITY_REPLAY_CONFLICT")

    def test_missing_required_test_node_blocks_materialization(self):
        project, package = self._roots()
        source = (project / "tests/test_deduplicator.py").read_text(encoding="utf-8")
        source = source.replace(
            "def test_deduplication_is_order_independent_and_preserves_query_lineage():",
            "def renamed_test():",
        )
        (project / "tests/test_deduplicator.py").write_text(source, encoding="utf-8")
        with self.assertRaises(CompletionAuthorityError) as caught:
            materialize_task_4a_08_completion_authority(project, package)
        self.assertEqual(caught.exception.reason_taxonomy, "COMPLETION_AUTHORITY_NODESET_DRIFT")

    def test_snapshot_tamper_blocks_load(self):
        project, package = self._roots()
        materialize_task_4a_08_completion_authority(project, package)
        (package / SNAPSHOT_RELATIVE).write_text("tampered\n", encoding="utf-8")
        with self.assertRaises(CompletionAuthorityError) as caught:
            load_task_4a_08_completion_authority(package)
        self.assertEqual(caught.exception.reason_taxonomy, "COMPLETION_AUTHORITY_SNAPSHOT_DRIFT")

    def test_manifest_tamper_blocks_load(self):
        project, package = self._roots()
        materialize_task_4a_08_completion_authority(project, package)
        manifest_path = package / MANIFEST_RELATIVE
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        payload["task_ref"] = "TASK-OTHER"
        manifest_path.write_text(json.dumps(payload), encoding="utf-8")
        with self.assertRaises(CompletionAuthorityError) as caught:
            load_task_4a_08_completion_authority(package)
        self.assertEqual(caught.exception.reason_taxonomy, "COMPLETION_AUTHORITY_MANIFEST_DRIFT")

    @mock.patch("runtime.orchestrator.completion_authority.subprocess.run")
    def test_verifier_uses_frozen_nodes_and_never_live_test_file(self, run):
        project, package = self._roots()
        authority = materialize_task_4a_08_completion_authority(project, package)
        run.return_value = mock.Mock(returncode=0, stdout=b"pass", stderr=b"")
        evidence = verify_all_frozen_completion_criteria(authority, project)
        self.assertEqual([item.state for item in evidence], ["SATISFIED", "SATISFIED"])
        commands = [call.args[0] for call in run.call_args_list]
        self.assertEqual(len(commands), 2)
        for command in commands:
            joined = " ".join(str(item) for item in command)
            self.assertEqual(command[0], str(project / ".venv/bin/python"))
            self.assertEqual(command[1:4], ["-m", "pytest", "-q"])
            self.assertIn(str(package / SNAPSHOT_RELATIVE), joined)
            self.assertNotIn(str(project / "tests/test_deduplicator.py"), joined)

    @mock.patch("runtime.orchestrator.completion_authority.subprocess.run")
    def test_pytest_assertion_failure_is_unsatisfied(self, run):
        project, package = self._roots()
        authority = materialize_task_4a_08_completion_authority(project, package)
        run.return_value = mock.Mock(returncode=1, stdout=b"failed", stderr=b"")
        evidence = verify_all_frozen_completion_criteria(authority, project)
        self.assertEqual([item.state for item in evidence], ["UNSATISFIED", "UNSATISFIED"])

    @mock.patch("runtime.orchestrator.completion_authority.subprocess.run")
    def test_missing_project_venv_is_unknown_without_subprocess(self, run):
        project, package = self._roots()
        authority = materialize_task_4a_08_completion_authority(project, package)
        (project / ".venv/bin/pytest").unlink()
        evidence = verify_all_frozen_completion_criteria(authority, project)
        self.assertEqual([item.state for item in evidence], ["UNKNOWN", "UNKNOWN"])
        self.assertEqual(
            [item.reason_taxonomy for item in evidence],
            [
                "FROZEN_COMPLETION_VERIFIER_UNRESOLVED",
                "FROZEN_COMPLETION_VERIFIER_UNRESOLVED",
            ],
        )
        self.assertEqual([item.pytest_exit_code for item in evidence], [None, None])
        run.assert_not_called()

    @mock.patch("runtime.orchestrator.completion_authority.subprocess.run")
    def test_missing_pytest_module_is_unknown_not_unsatisfied(self, run):
        project, package = self._roots()
        authority = materialize_task_4a_08_completion_authority(project, package)
        run.return_value = mock.Mock(
            returncode=1,
            stdout=b"",
            stderr=b"/usr/bin/python3: No module named pytest\n",
        )
        evidence = verify_all_frozen_completion_criteria(authority, project)
        self.assertEqual([item.state for item in evidence], ["UNKNOWN", "UNKNOWN"])
        self.assertEqual(
            [item.reason_taxonomy for item in evidence],
            [
                "FROZEN_COMPLETION_VERIFIER_UNRESOLVED",
                "FROZEN_COMPLETION_VERIFIER_UNRESOLVED",
            ],
        )
        self.assertEqual([item.pytest_exit_code for item in evidence], [1, 1])

    @mock.patch("runtime.orchestrator.completion_authority.subprocess.run")
    def test_non_assertion_pytest_failure_is_unknown_fail_closed(self, run):
        project, package = self._roots()
        authority = materialize_task_4a_08_completion_authority(project, package)
        run.return_value = mock.Mock(returncode=4, stdout=b"", stderr=b"usage")
        evidence = verify_all_frozen_completion_criteria(authority, project)
        self.assertEqual([item.state for item in evidence], ["UNKNOWN", "UNKNOWN"])

    @unittest.skipUnless(os.environ.get("HARNESS_PROOF97_PRODUCT_ROOT"),
                         "proof97 product checkout root is opt-in")
    def test_proof97_actual_product_frozen_nodes_from_opt_in_root(self):
        product = Path(os.environ["HARNESS_PROOF97_PRODUCT_ROOT"]).resolve()
        self.assertTrue((product / "tests/test_deduplicator.py").is_file())
        with tempfile.TemporaryDirectory() as directory:
            package = Path(directory) / "proof97-package"
            package.mkdir()
            authority = materialize_task_4a_08_completion_authority(product, package)
            evidence = verify_all_frozen_completion_criteria(authority, product)
        self.assertEqual([item.state for item in evidence], ["SATISFIED", "SATISFIED"])
        self.assertTrue(all(item.pytest_exit_code == 0 for item in evidence))


if __name__ == "__main__":
    unittest.main()
