from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
RELEASE_SOURCE_PATH = REPO_ROOT / "deploy" / "operator-control-plane-v2" / "release_source.py"
OPERATIONS_PATH = REPO_ROOT / "docs" / "harness" / "ocpv2-current-operations.md"
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "ocpv2-r2-ci.yml"


def load_release_source():
    spec = importlib.util.spec_from_file_location("ocpv2_release_source", RELEASE_SOURCE_PATH)
    if spec is None or spec.loader is None:
        raise AssertionError("release source module cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class OCPv2ReleaseSourceAuthorityTests(unittest.TestCase):
    OPERATIONS = """# OCPv2 Current Operations

## Current authority

- Canonical branch: `impl/ocp-rdc-independent-primary-path-20260923`
"""

    MERGE_SHA = "6ab395dc1293b22e1ad2a4f5592c92a1f6b95847"
    TREE_SHA = "0b37af23ee22a8a71b7f004df441f6fa0491683e"

    def merged_pr(self, *, base: str | None = None):
        return {
            "number": 10,
            "state": "MERGED",
            "mergedAt": "2026-09-24T03:32:21Z",
            "baseRefName": base or "impl/ocp-rdc-independent-primary-path-20260923",
            "mergeCommit": {"oid": self.MERGE_SHA},
        }

    def test_reads_canonical_branch_from_current_operations(self):
        release_source = load_release_source()
        self.assertEqual(
            release_source.parse_canonical_branch(self.OPERATIONS),
            "impl/ocp-rdc-independent-primary-path-20260923",
        )

    def test_rejects_main_when_current_operations_declares_different_canonical_branch(self):
        release_source = load_release_source()
        with self.assertRaisesRegex(release_source.ReleaseSourceError, "canonical branch"):
            release_source.build_release_authority(
                self.merged_pr(base="main"),
                operations_text=self.OPERATIONS,
                tree_sha=self.TREE_SHA,
            )

    def test_merged_pr_on_declared_canonical_branch_yields_exact_release_authority(self):
        release_source = load_release_source()
        authority = release_source.build_release_authority(
            self.merged_pr(),
            operations_text=self.OPERATIONS,
            tree_sha=self.TREE_SHA,
        )
        self.assertEqual(
            authority,
            {
                "schema_version": "ocpv2.release-source-authority.v1",
                "pr_number": 10,
                "canonical_branch": "impl/ocp-rdc-independent-primary-path-20260923",
                "canonical_head": self.MERGE_SHA,
                "canonical_tree": self.TREE_SHA,
            },
        )

    def test_unmerged_pr_cannot_become_release_authority(self):
        release_source = load_release_source()
        metadata = self.merged_pr()
        metadata["state"] = "OPEN"
        metadata["mergedAt"] = None
        metadata["mergeCommit"] = None
        with self.assertRaisesRegex(release_source.ReleaseSourceError, "merged"):
            release_source.build_release_authority(
                metadata,
                operations_text=self.OPERATIONS,
                tree_sha=self.TREE_SHA,
            )

    def test_workflow_runs_release_authority_guard_on_canonical_branch_pushes(self):
        release_source = load_release_source()
        operations = OPERATIONS_PATH.read_text(encoding="utf-8")
        canonical_branch = release_source.parse_canonical_branch(operations)
        workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
        self.assertIn(f"      - {canonical_branch}", workflow)
        self.assertIn(
            "python3 -m unittest -v tests.test_ocpv2_release_source_authority",
            workflow,
        )


if __name__ == "__main__":
    unittest.main()
