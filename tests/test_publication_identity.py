from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path


def git(root: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(root), *args], text=True).strip()


def commit(root: Path, message: str) -> str:
    subprocess.run(["git", "-C", str(root), "add", "."], check=True)
    subprocess.run(["git", "-C", str(root), "commit", "-qm", message], check=True)
    return git(root, "rev-parse", "HEAD")


class PublicationIdentityTests(unittest.TestCase):
    def make_repo(self, root: Path) -> str:
        subprocess.run(["git", "init", "-q", str(root)], check=True)
        subprocess.run(["git", "-C", str(root), "config", "user.email", "test@example.com"], check=True)
        subprocess.run(["git", "-C", str(root), "config", "user.name", "Test"], check=True)
        (root / "runtime/orchestrator").mkdir(parents=True)
        (root / "tests").mkdir()
        (root / "scripts").mkdir()
        (root / "docs").mkdir()
        (root / "runtime/orchestrator/example.py").write_text("VALUE = 1\n", encoding="utf-8")
        (root / "tests/test_example.py").write_text("# test\n", encoding="utf-8")
        (root / "scripts/check.sh").write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        (root / "docs/report.md").write_text("baseline\n", encoding="utf-8")
        return commit(root, "validated")

    def test_docs_only_closure_and_publication_descendant_are_eligible(self):
        from runtime.orchestrator.publication_identity import verify_publication_identity
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory) / "repo"; repo.mkdir(); validated = self.make_repo(repo)
            (repo / "docs/report.md").write_text("closure\n", encoding="utf-8")
            closure = commit(repo, "closure docs")
            (repo / "docs/publication.md").write_text("publication evidence\n", encoding="utf-8")
            publication = commit(repo, "publication docs")
            result = verify_publication_identity(repo, validated, closure, publication)
            self.assertTrue(result.eligible)
            self.assertEqual(result.reason, "PUBLICATION_IDENTITY_VERIFIED")
            self.assertEqual(result.executable_changed_paths, ())
            self.assertEqual(result.validated_code_head, validated)
            self.assertEqual(result.closure_head, closure)
            self.assertEqual(result.publication_head, publication)

    def test_executable_drift_invalidates_publication(self):
        from runtime.orchestrator.publication_identity import verify_publication_identity
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory) / "repo"; repo.mkdir(); validated = self.make_repo(repo)
            (repo / "docs/report.md").write_text("closure\n", encoding="utf-8")
            closure = commit(repo, "closure docs")
            (repo / "runtime/orchestrator/example.py").write_text("VALUE = 2\n", encoding="utf-8")
            publication = commit(repo, "runtime drift")
            result = verify_publication_identity(repo, validated, closure, publication)
            self.assertFalse(result.eligible)
            self.assertEqual(result.reason, "EXECUTABLE_SURFACE_DRIFT")
            self.assertEqual(result.executable_changed_paths, ("runtime/orchestrator/example.py",))

    def test_non_descendant_publication_is_rejected(self):
        from runtime.orchestrator.publication_identity import verify_publication_identity
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory) / "repo"; repo.mkdir(); validated = self.make_repo(repo)
            (repo / "docs/report.md").write_text("closure\n", encoding="utf-8")
            closure = commit(repo, "closure docs")
            subprocess.run(["git", "-C", str(repo), "checkout", "-qb", "other", validated], check=True)
            (repo / "docs/other.md").write_text("other\n", encoding="utf-8")
            publication = commit(repo, "other branch")
            result = verify_publication_identity(repo, validated, closure, publication)
            self.assertFalse(result.eligible)
            self.assertEqual(result.reason, "PUBLICATION_NOT_DESCENDANT_OF_CLOSURE")

    def test_non_docs_closure_change_is_rejected_even_outside_executable_surface(self):
        from runtime.orchestrator.publication_identity import verify_publication_identity
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory) / "repo"; repo.mkdir(); validated = self.make_repo(repo)
            (repo / "standards").mkdir()
            (repo / "standards/policy.txt").write_text("changed\n", encoding="utf-8")
            closure = commit(repo, "not docs only")
            result = verify_publication_identity(repo, validated, closure, closure)
            self.assertFalse(result.eligible)
            self.assertEqual(result.reason, "CLOSURE_NOT_DOCS_ONLY")


if __name__ == "__main__":
    unittest.main()
