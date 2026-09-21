import io
import json
import subprocess
import tarfile
import tempfile
import unittest
from pathlib import Path

from runtime.orchestrator.production_full_plan_entry import load_job, register_job
from runtime.orchestrator.operator_plan_execution import build_operator_plan_job
from runtime.orchestrator.production_full_plan_runner import DurableFullPlanSupervisor
from runtime.orchestrator.runtime_migration_handoff import MigrationPhase, MigrationStore
from runtime.orchestrator.runtime_release import (
    RuntimeReleaseError,
    RuntimeReleaseManifest,
    _digest,
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


    def test_new_release_manifest_binds_publication_head(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            base = Path(d); repo = base / "repo"; repo.mkdir(); self.make_repo(repo)
            manifest = build_runtime_release(repo, base / "releases")
            self.assertEqual(manifest.schema_version, "gch.runtime-release.v2")
            self.assertEqual(manifest.publication_head, manifest.source_head)

    def test_v1_release_manifest_remains_readable(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            release = Path(d) / "release"; entry = release / "runtime/orchestrator/production_full_plan_boot.py"
            entry.parent.mkdir(parents=True); entry.write_text("# boot\n", encoding="utf-8")
            source_head = "a" * 40
            unsigned = {
                "schema_version": "gch.runtime-release.v1",
                "source_head": source_head,
                "source_tree": "b" * 40,
                "release_path": str(release.absolute()),
                "runtime_entry": "runtime/orchestrator/production_full_plan_boot.py",
                "runtime_entry_sha256": __import__("hashlib").sha256(entry.read_bytes()).hexdigest(),
            }
            payload = {**unsigned, "manifest_sha256": _digest(unsigned)}
            (release / "RUNTIME_RELEASE_MANIFEST.json").write_text(json.dumps(payload), encoding="utf-8")
            manifest = verify_runtime_release(release, source_head)
            self.assertEqual(manifest.schema_version, "gch.runtime-release.v1")
            self.assertEqual(manifest.publication_head, source_head)

    def test_activation_repairs_broken_runtime_link_when_no_active_jobs(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            base = Path(d); repo = base / "repo"; repo.mkdir(); self.make_repo(repo)
            manifest = build_runtime_release(repo, base / "releases")
            workspace = base / "workspace"; workspace.mkdir()
            runtime_link = base / "runtime-current"
            runtime_link.symlink_to(base / "removed-worktree")
            activate_runtime_release(manifest, runtime_link, job_search_root=workspace)
            self.assertEqual(runtime_link.resolve(), Path(manifest.release_path).resolve())

    def test_terminal_operator_job_with_later_spec_drift_does_not_block_activation(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            base = Path(d); repo = base / "repo"; repo.mkdir(); self.make_repo(repo)
            manifest = build_runtime_release(repo, base / "releases")
            harness = base / "harness"; harness.mkdir()
            subprocess.run(["git", "init", "-q", str(harness)], check=True)
            subprocess.run(["git", "-C", str(harness), "config", "user.email", "test@example.com"], check=True)
            subprocess.run(["git", "-C", str(harness), "config", "user.name", "Test"], check=True)
            runtime_entry = harness / "runtime/orchestrator/production_full_plan_boot.py"
            runtime_entry.parent.mkdir(parents=True); runtime_entry.write_text("# runtime\n")
            plan = harness / "plan.md"; spec = harness / "spec.md"
            plan.write_text("approved plan\n"); spec.write_text("approved spec\n")
            subprocess.run(["git", "-C", str(harness), "add", "."], check=True)
            subprocess.run(["git", "-C", str(harness), "commit", "-qm", "approved"], check=True)
            job = build_operator_plan_job(
                project_root=harness, harness_root=harness, runtime_code_root=harness,
                project_id="P", run_id="R", task_ids=["G1"],
                approved_plan_path=plan, approved_spec_path=spec, approval_ref="USER_APPROVED",
            )
            registered = register_job(job); loaded = load_job(registered)
            sup = DurableFullPlanSupervisor(
                harness, project_id="P", run_id="R", gates=["G1"],
                authority_core_sha256=loaded["authority_core_sha256"], **loaded["policy"],
            )
            sup.load(); sup.cancel("HISTORICAL_TERMINAL")
            spec.write_text("approved spec metadata corrected later\n")
            subprocess.run(["git", "-C", str(harness), "add", "spec.md"], check=True)
            subprocess.run(["git", "-C", str(harness), "commit", "-qm", "correct spec metadata"], check=True)
            with self.assertRaisesRegex(Exception, "approved spec digest mismatch"):
                load_job(registered)
            runtime_link = base / "runtime-current"
            activate_runtime_release(manifest, runtime_link, job_search_root=base)
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


class RuntimeMigrationActivationTests(unittest.TestCase):
    def make_release(self, base: Path):
        repo=base/'repo'; repo.mkdir(); RuntimeReleaseTests.make_repo(self,repo)
        return build_runtime_release(repo,base/'releases')

    def register(self, base: Path, run_id: str):
        harness=base/f'harness-{run_id}'; harness.mkdir(parents=True)
        subprocess.run(['git','init','-q',str(harness)],check=True)
        payload={
            'schema_version':'orchestration.production-full-plan-job.v1',
            'project_root':str(harness),'harness_root':str(harness),'project_id':'P','run_id':run_id,'required_executables':['git'],
            'gates':[{'gate_id':'G1','approval_evidence':str(harness/'a.json'),'requirements_sha256':'a'*64,'branch':'main','head':'b'*40,'full_plan_opt_in':True,'project_final_validation':True}],
            'policy':{'retry_budget':0,'gate_timeout_seconds':1,'heartbeat_seconds':.03,'lease_seconds':.08,'min_disk_free_bytes':0,'min_inode_free':0,'min_memory_available_bytes':0},
        }
        requested=harness/'job.json'; requested.write_text(json.dumps(payload)); registered=register_job(load_job(requested)); job=load_job(registered)
        sup=DurableFullPlanSupervisor(harness,project_id='P',run_id=run_id,gates=['G1'],authority_core_sha256=job['authority_core_sha256'],**job['policy'])
        return job,sup

    def prepare_quiesced_tx(self, base: Path, manifest, *, successor='R3', quiesced_sha_override=None, manifest_sha=None, advance=True):
        job,sup=self.register(base,'R2'); initial,_=sup.load()
        state=dict(initial); state['state']='WAITING_RESOURCE'; state['lease']=None; state['last_error']='RUNTIME_MIGRATION_PREDECESSOR_QUIESCED'; state['migration_id']='MIG-A'; state['migration_successor_run_id']=successor
        quiesced=sup._persist(state,{'event':'TEST_MIGRATION_QUIESCE'})
        spec={
            'migration_id':'MIG-A','project_id':'P','predecessor_run_id':'R2','successor_run_id':successor,
            'current_gate':'G1','resume_gate':'G1','approved_plan_sha256':'a'*64,'approved_spec_sha256':'b'*64,
            'authority_core_sha256':job['authority_core_sha256'],'predecessor_state_sha256':initial['state_sha256'],'source_head':'e'*40,
            'target_release_head':manifest.source_head,'target_manifest_sha256':manifest_sha or manifest.manifest_sha256,'successor_job_spec_sha256':'2'*64,
        }
        store=MigrationStore(base/'migrations'); tx=store.create(spec)
        if advance:
            tx=store.advance(tx.migration_id,MigrationPhase.PREDECESSOR_QUIESCED,updates={'quiesced_state_sha256':quiesced_sha_override or quiesced['state_sha256']})
        return tx,quiesced

    def test_exact_quiesced_predecessor_is_only_exempt_active_job(self):
        with tempfile.TemporaryDirectory() as d:
            base=Path(d); manifest=self.make_release(base); tx,_=self.prepare_quiesced_tx(base,manifest)
            link=base/'runtime-current'; activate_runtime_release(manifest,link,job_search_root=base,migration_transaction=tx)
            self.assertEqual(link.resolve(),Path(manifest.release_path).resolve())

    def test_unrelated_active_job_still_blocks(self):
        with tempfile.TemporaryDirectory() as d:
            base=Path(d); manifest=self.make_release(base); tx,_=self.prepare_quiesced_tx(base,manifest); self.register(base,'RX')
            with self.assertRaisesRegex(RuntimeReleaseError,'active Full Plan jobs'): activate_runtime_release(manifest,base/'runtime-current',job_search_root=base,migration_transaction=tx)

    def test_quiesced_state_sha_mismatch_blocks(self):
        with tempfile.TemporaryDirectory() as d:
            base=Path(d); manifest=self.make_release(base); tx,_=self.prepare_quiesced_tx(base,manifest,quiesced_sha_override='0'*64)
            with self.assertRaises(RuntimeReleaseError): activate_runtime_release(manifest,base/'runtime-current',job_search_root=base,migration_transaction=tx)

    def test_target_manifest_binding_mismatch_blocks(self):
        with tempfile.TemporaryDirectory() as d:
            base=Path(d); manifest=self.make_release(base); tx,_=self.prepare_quiesced_tx(base,manifest,manifest_sha='0'*64)
            with self.assertRaises(RuntimeReleaseError): activate_runtime_release(manifest,base/'runtime-current',job_search_root=base,migration_transaction=tx)

    def test_prepared_transaction_cannot_exempt_active_job(self):
        with tempfile.TemporaryDirectory() as d:
            base=Path(d); manifest=self.make_release(base); tx,_=self.prepare_quiesced_tx(base,manifest,advance=False)
            with self.assertRaises(RuntimeReleaseError): activate_runtime_release(manifest,base/'runtime-current',job_search_root=base,migration_transaction=tx)

    def test_successor_active_before_activation_is_blocker(self):
        with tempfile.TemporaryDirectory() as d:
            base=Path(d); manifest=self.make_release(base); tx,_=self.prepare_quiesced_tx(base,manifest); self.register(base,'R3')
            with self.assertRaises(RuntimeReleaseError): activate_runtime_release(manifest,base/'runtime-current',job_search_root=base,migration_transaction=tx)


if __name__ == "__main__":
    unittest.main()
