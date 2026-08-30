import subprocess, tempfile, unittest
from pathlib import Path
from unittest.mock import patch

from runtime.orchestrator.production_worker_executor import (
    EXECUTOR_ID, ProductionWorkerError, execute_production_worker,
    production_executor_manifest,
)
from runtime.orchestrator.schemas import TaskSlice, WorkerRequest


class ProductionWorkerExecutorTests(unittest.TestCase):
    def _fixture(self, root: Path, *, scope=None):
        subprocess.run(["git","init","-q","-b","main",root],check=True)
        (root/"README.md").write_text("base\n"); (root/".gitignore").write_text(".venv/\nout/\n")
        subprocess.run(["git","-C",root,"add","README.md",".gitignore"],check=True)
        subprocess.run(["git","-C",root,"-c","user.name=T","-c","user.email=t@x","commit","-qm","base"],check=True)
        base=subprocess.check_output(["git","-C",root,"rev-parse","HEAD"],text=True).strip()
        (root/".venv/bin").mkdir(parents=True); (root/".venv/bin/python").write_text(""); (root/".venv/bin/pytest").write_text("")
        task=TaskSlice(thread_id="L",assigned_agent="implementation_agent",input="implement x",expected_output="product",
            validation_criteria=["tests pass"],editable_scope=scope or ["app/x.py","tests/test_x.py"],forbidden_scope=[],merge_point="EXIT",output_dir=str(root/"out"))
        return WorkerRequest(str(root),task,{"project_id":"p","gate_id":"g","lv_id":"L","canonical_plan_sha256":"a"*64},
            {"head":base},{"execution_mode":"production","run_id":"r","attempt":3,"approval_event_id":"APR-1",
                           "package_manifest_sha256":"b"*64,"source_snapshot":{"source_head":base}})

    def test_manifest_is_actual_not_test_double(self):
        value=production_executor_manifest()
        self.assertEqual(value["asset_id"],EXECUTOR_ID); self.assertTrue(value["production"]); self.assertFalse(value["test_double"])

    def test_actual_executor_commit_is_collected_and_bound(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); request=self._fixture(root)
            def runner(*args,**kwargs):
                (root/"app").mkdir(); (root/"tests").mkdir()
                (root/"app/x.py").write_text("x=1\n"); (root/"tests/test_x.py").write_text("def test_x(): assert True\n")
                subprocess.run(["git","-C",root,"add","app/x.py","tests/test_x.py"],check=True)
                subprocess.run(["git","-C",root,"-c","user.name=T","-c","user.email=t@x","commit","-qm","checkpoint"],check=True)
                return subprocess.CompletedProcess(args[0],0,b"ok",b"")
            ok=lambda root,argv,timeout=900:{"command":argv,"exit_code":0,"timeout":False,"stdout_sha256":"c"*64,"stderr_sha256":"d"*64}
            with patch("runtime.orchestrator.production_worker_executor._command",side_effect=ok):
                result=execute_production_worker(request,executor=runner)
            self.assertEqual(result["attempt"],3); self.assertEqual(result["executor"]["identity"],EXECUTOR_ID)
            self.assertEqual(set(result["changed_files"]),{"app/x.py","tests/test_x.py"})
            self.assertFalse(subprocess.check_output(["git","-C",root,"status","--porcelain"],text=True))

    def test_out_of_scope_commit_is_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); request=self._fixture(root)
            def runner(*args,**kwargs):
                (root/"bad.py").write_text("bad=1\n")
                subprocess.run(["git","-C",root,"add","bad.py"],check=True)
                subprocess.run(["git","-C",root,"-c","user.name=T","-c","user.email=t@x","commit","-qm","bad"],check=True)
                return subprocess.CompletedProcess(args[0],0,b"",b"")
            with self.assertRaisesRegex(ProductionWorkerError,"outside owned scope"):
                execute_production_worker(request,executor=runner)

    def test_failure_and_timeout_are_not_completion(self):
        with tempfile.TemporaryDirectory() as d:
            request=self._fixture(Path(d))
            for result in (subprocess.CompletedProcess([],1,b"",b"failed"),):
                with self.subTest(result=result.returncode), self.assertRaises(ProductionWorkerError):
                    execute_production_worker(request,executor=lambda *a,**k:result)
