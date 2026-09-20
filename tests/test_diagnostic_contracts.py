import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from runtime.diagnostics.config import DiagnosticConfig, DiagnosticConfigError
from runtime.diagnostics.contracts import (
    AnalysisEvidenceEnvelope, AnalysisRequest, DiagnosticContractError,
    DiagnosticContextPack, SourceSnapshotBinding,
)
from runtime.diagnostics.security import DiagnosticStaleError, assert_binding_current, prepare_source_snapshot


def init_repo(root: Path) -> None:
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    subprocess.run(["git", "-C", str(root), "config", "user.email", "test@example.com"], check=True)
    subprocess.run(["git", "-C", str(root), "config", "user.name", "Test"], check=True)
    (root / "a.py").write_text("VALUE=1\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(root), "add", "a.py"], check=True)
    subprocess.run(["git", "-C", str(root), "commit", "-qm", "baseline"], check=True)


class DiagnosticContractTests(unittest.TestCase):
    def test_diagnostics_default_off_and_have_no_authority(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            repo=Path(d); init_repo(repo)
            cfg=DiagnosticConfig.from_env({})
            self.assertFalse(cfg.enabled); self.assertEqual(cfg.mode,"OFF")
            binding=SourceSnapshotBinding.capture(repo, project_id="P")
            env=AnalysisEvidenceEnvelope(project_id="P",run_id="R",gate_id="G",task_id="T",
                analyzer="test",analyzer_version="1",analysis_mode="unit",status="CURRENT",
                source_binding=binding,result_digest="a"*64,raw_evidence_ref="",result={})
            self.assertEqual((env.control_authority,env.mutation_authority,env.recovery_authority,
                              env.completion_authority,env.notification_authority),("NONE",)*5)

    def test_owned_paths_and_status_are_strict(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            repo=Path(d); init_repo(repo)
            with self.assertRaises(DiagnosticContractError):
                SourceSnapshotBinding.capture(repo,project_id="P",owned_paths=("/abs.py",))
            with self.assertRaises(DiagnosticContractError):
                SourceSnapshotBinding.capture(repo,project_id="P",owned_paths=("../x",))
            binding=SourceSnapshotBinding.capture(repo,project_id="P")
            with self.assertRaises(DiagnosticContractError):
                AnalysisEvidenceEnvelope(project_id="P",run_id="R",gate_id="G",task_id="T",
                    analyzer="x",analyzer_version="1",analysis_mode="u",status="UNKNOWN",
                    source_binding=binding,result_digest="a"*64,raw_evidence_ref="",result={})

    def test_workspace_digest_detects_tracked_and_untracked_drift_without_secret_contents(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            repo=Path(d); init_repo(repo)
            one=SourceSnapshotBinding.capture(repo,project_id="P")
            (repo/"a.py").write_text("VALUE=2\n",encoding="utf-8")
            two=SourceSnapshotBinding.capture(repo,project_id="P")
            self.assertNotEqual(one.workspace_tree_digest,two.workspace_tree_digest)
            (repo/"a.py").write_text("VALUE=1\n",encoding="utf-8")
            (repo/"new.txt").write_text("hello\n",encoding="utf-8")
            three=SourceSnapshotBinding.capture(repo,project_id="P")
            self.assertNotEqual(one.workspace_tree_digest,three.workspace_tree_digest)
            (repo/".env").write_text("SUPER_SECRET=abc\n",encoding="utf-8")
            four=SourceSnapshotBinding.capture(repo,project_id="P")
            self.assertNotEqual(three.workspace_tree_digest,four.workspace_tree_digest)

    def test_snapshot_excludes_secrets_workspace_and_symlinks_and_detects_stale(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            base=Path(d); repo=base/"repo"; repo.mkdir(); init_repo(repo)
            (repo/"visible.txt").write_text("visible\n",encoding="utf-8")
            (repo/".env").write_text("secret\n",encoding="utf-8")
            (repo/"link.txt").symlink_to(repo/"visible.txt")
            (repo/"_workspace").mkdir(); (repo/"_workspace/x").write_text("noise")
            binding=SourceSnapshotBinding.capture(repo,project_id="P")
            snapshot=prepare_source_snapshot(repo,base/"analysis",binding)
            self.assertTrue((snapshot/"a.py").is_file())
            self.assertTrue((snapshot/"visible.txt").is_file())
            self.assertFalse((snapshot/".env").exists())
            self.assertFalse((snapshot/"link.txt").exists())
            self.assertFalse((snapshot/"_workspace").exists())
            (repo/"a.py").write_text("VALUE=3\n",encoding="utf-8")
            with self.assertRaisesRegex(DiagnosticStaleError,"CODE_INTELLIGENCE_STALE"):
                assert_binding_current(binding,repo)

    def test_config_caps_and_explicit_enablement(self) -> None:
        self.assertFalse(DiagnosticConfig.from_env({"GCH_DIAGNOSTIC_INTELLIGENCE_MODE":"ADVISORY"}).enabled)
        with self.assertRaises(DiagnosticConfigError):
            DiagnosticConfig.from_env({"GCH_DIAGNOSTIC_INTELLIGENCE_ENABLED":"true","GCH_DIAGNOSTIC_INTELLIGENCE_MODE":"BOGUS"})
        cfg=DiagnosticConfig.from_env({"GCH_DIAGNOSTIC_INTELLIGENCE_ENABLED":"true","GCH_DIAGNOSTIC_INTELLIGENCE_MODE":"SHADOW","GCH_DIAGNOSTIC_MAX_RESULT_BYTES":"128","GCH_DIAGNOSTIC_MAX_CONTEXT_CHARS":"256"})
        self.assertTrue(cfg.enabled); self.assertEqual((cfg.max_result_bytes,cfg.max_context_chars),(128,256))
        with tempfile.TemporaryDirectory() as d:
            repo=Path(d); init_repo(repo); binding=SourceSnapshotBinding.capture(repo,project_id="P")
            with self.assertRaises(DiagnosticContractError):
                AnalysisEvidenceEnvelope(project_id="P",run_id="R",gate_id="G",task_id="T",analyzer="x",analyzer_version="1",analysis_mode="u",status="CURRENT",source_binding=binding,result_digest="a"*64,raw_evidence_ref="",result={"x":"z"*200},max_result_bytes=64)


if __name__ == "__main__": unittest.main()
