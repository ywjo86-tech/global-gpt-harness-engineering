import io
import json
import subprocess
import tarfile
import tempfile
import unittest
from pathlib import Path

from runtime.orchestrator.production_full_plan_entry import load_job, register_job
from runtime.orchestrator.production_full_plan_runner import DurableFullPlanSupervisor
from runtime.orchestrator.runtime_release import (
    RuntimeReleaseError,
    _extract_archive_bytes,
    activate_runtime_release,
    build_runtime_release,
    verify_runtime_release,
)


def git(root: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(root), *args], text=True).strip()


class RuntimeReleaseTests(unittest.TestCase):
    def make_repo(self, root: Path) -> None:
        subprocess.run(["git", "init", "-q", str(root)], check=True)
        subprocess.run(["git", "-C", str(root), "config", "user.email", "test@example.com"], check=True)
        subprocess.run(["git", "-C", str(root), "config", "user.name", "Test"], check=True)
        target = root / "runtime/orchestrator/production_full_plan_boot.py"
        target.parent.mkdir(parents=True)
        target.write_text("# boot\n", encoding="utf-8")
        (root / "README.md").write_text("runtime release test\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(root), "add", "."], check=True)
        subprocess.run(["git", "-C", str(root), "commit", "-qm", "baseline"], check=True)

    def test_build_release_uses_exact_git_head_and_contains_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            base = Path(d); repo = base / "repo"; repo.mkdir(); self.make_repo(repo)
            releases = base / "releases"
            manifest = build_runtime_release(repo, releases, source_ref="HEAD")
            self.assertEqual(manifest.source_head, git(repo, "rev-parse", "HEAD"))
            release = Path(manifest.release_path)
            self.assertTrue((release / "runtime/orchestrator/production_full_plan_boot.py").is_file())
            self.assertTrue((release / "RUNTIME_RELEASE_MANIFEST.json").is_file())
            self.assertEqual(verify_runtime_release(release, manifest.source_head), manifest)

    def test_build_release_rejects_dirty_source_and_symlinked_release_root(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            base = Path(d); repo = base / "repo"; repo.mkdir(); self.make_repo(repo)
            (repo / "README.md").write_text("dirty\n", encoding="utf-8")
            with self.assertRaisesRegex(RuntimeReleaseError, "clean"):
                build_runtime_release(repo, base / "releases")
            subprocess.run(["git", "-C", str(repo), "checkout", "--", "README.md"], check=True)
            real = base / "real"; real.mkdir()
            link = base / "release-link"; link.symlink_to(real, target_is_directory=True)
            with self.assertRaisesRegex(RuntimeReleaseError, "symlink"):
                build_runtime_release(repo, link)

    def test_extract_archive_rejects_path_traversal_and_links(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            payload = io.BytesIO()
            with tarfile.open(fileobj=payload, mode="w") as tar:
                info = tarfile.TarInfo("../escape.txt")
                data = b"bad"
                info.size = len(data)
                tar.addfile(info, io.BytesIO(data))
            with self.assertRaisesRegex(RuntimeReleaseError, "unsafe archive member"):
                _extract_archive_bytes(payload.getvalue(), root / "out")

    def test_existing_release_with_mismatched_manifest_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            base = Path(d); repo = base / "repo"; repo.mkdir(); self.make_repo(repo)
            releases = base / "releases"
            manifest = build_runtime_release(repo, releases)
            path = Path(manifest.release_path) / "RUNTIME_RELEASE_MANIFEST.json"
            data = json.loads(path.read_text())
            data["source_tree"] = "f" * 40
            path.write_text(json.dumps(data))
            with self.assertRaises(RuntimeReleaseError):
                build_runtime_release(repo, releases)

    def test_activation_repairs_broken_runtime_link_when_no_active_jobs(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            base = Path(d); repo = base / "repo"; repo.mkdir(); self.make_repo(repo)
            manifest = build_runtime_release(repo, base / "releases")
            workspace = base / "workspace"; workspace.mkdir()
            runtime_link = base / "runtime-current"
            runtime_link.symlink_to(base / "removed-worktree")
            activate_runtime_release(manifest, runtime_link, job_search_root=workspace)
            self.assertEqual(runtime_link.resolve(), Path(manifest.release_path).resolve())

    def test_activation_refuses_retarget_when_registered_job_is_nonterminal(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            base = Path(d); repo = base / "repo"; repo.mkdir(); self.make_repo(repo)
            manifest = build_runtime_release(repo, base / "releases")
            harness = base / "harness"; harness.mkdir()
            subprocess.run(["git", "init", "-q", str(harness)], check=True)
            job_payload = {
                "schema_version": "orchestration.production-full-plan-job.v1",
                "project_root": str(harness), "harness_root": str(harness),
                "project_id": "P", "run_id": "R", "required_executables": ["git"],
                "gates": [{"gate_id":"G1","approval_evidence":str(harness/"a.json"),
                           "requirements_sha256":"a"*64,"branch":"main","head":"b"*40,
                           "full_plan_opt_in":True,"project_final_validation":True}],
                "policy": {"retry_budget":0,"gate_timeout_seconds":1,"heartbeat_seconds":.03,
                           "lease_seconds":.08,"min_disk_free_bytes":0,"min_inode_free":0,
                           "min_memory_available_bytes":0},
            }
            requested = harness / "job.json"; requested.write_text(json.dumps(job_payload))
            registered = register_job(load_job(requested)); job = load_job(registered)
            DurableFullPlanSupervisor(
                harness, project_id="P", run_id="R", gates=["G1"],
                authority_core_sha256=job["authority_core_sha256"], **job["policy"],
            ).load()
            runtime_link = base / "runtime-current"
            with self.assertRaisesRegex(RuntimeReleaseError, "active Full Plan jobs"):
                activate_runtime_release(manifest, runtime_link, job_search_root=base)


if __name__ == "__main__":
    unittest.main()
