import hashlib
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from runtime.diagnostics.adapters.codegraph_adapter import (
    ALLOWED_TOOLS, CodeGraphAdapterError, CodeGraphReadOnlyAdapter,
)
from runtime.diagnostics.contracts import AnalysisRequest, SourceSnapshotBinding


def init_repo(root: Path) -> None:
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    subprocess.run(["git", "-C", str(root), "config", "user.email", "test@example.com"], check=True)
    subprocess.run(["git", "-C", str(root), "config", "user.name", "Test"], check=True)
    (root / "a.py").write_text("def route_provider():\n    return 1\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(root), "add", "a.py"], check=True)
    subprocess.run(["git", "-C", str(root), "commit", "-qm", "baseline"], check=True)


class FakeRunner:
    def __init__(self, mutate=None): self.calls=[]; self.mutate=mutate
    def __call__(self, command, **kwargs):
        self.calls.append((list(command), dict(kwargs)))
        if self.mutate: self.mutate()
        return subprocess.CompletedProcess(command, 0, stdout=json.dumps({"impact":["a.py"]}), stderr="")

class DiagnosticCodeGraphAdapterTests(unittest.TestCase):
    def make(self, base: Path, runner=None):
        repo=base/"repo"; repo.mkdir(); init_repo(repo)
        binary=base/"codegraph-server"; binary.write_bytes(b"fake-codegraph"); binary.chmod(0o755)
        home=base/"home"; home.mkdir()
        runner=runner or FakeRunner()
        adapter=CodeGraphReadOnlyAdapter(binary,isolated_home=home,project_root=repo,runner=runner)
        binding=SourceSnapshotBinding.capture(repo,project_id="P")
        req=AnalysisRequest(project_id="P",run_id="R",gate_id="G",task_id="T",
            kind="SYMBOL_IMPACT",query="route_provider",source_binding=binding)
        return repo,binary,adapter,runner,req

    def test_codegraph_is_graph_only_telemetry_off_and_allowlisted(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            base=Path(d); _,binary,adapter,runner,req=self.make(base)
            out=adapter.query(req,"codegraph_analyze_impact",{"uri":"file:///snapshot/a.py","line":0},base/"analysis")
            command,kwargs=runner.calls[0]
            self.assertIn("--graph-only",command)
            self.assertEqual(command[command.index("--profile")+1],"graph")
            self.assertEqual(command[command.index("--run-tool")+1],"codegraph_analyze_impact")
            self.assertEqual(kwargs["env"]["CODEGRAPH_TELEMETRY"],"off")
            self.assertEqual(kwargs["env"]["CODEGRAPH_TOOL_PROFILE"],"graph")
            self.assertEqual(out.status,"CURRENT")
            self.assertEqual(out.result["binary_sha256"],hashlib.sha256(binary.read_bytes()).hexdigest())

    def test_admin_memory_docs_and_unknown_tools_are_rejected_before_launch(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            base=Path(d); _,_,adapter,runner,req=self.make(base)
            forbidden=("codegraph_memory_store","codegraph_index_markdown","codegraph_reindex_workspace","unknown")
            for tool in forbidden:
                with self.assertRaises(CodeGraphAdapterError): adapter.query(req,tool,{},base/"analysis")
            self.assertEqual(runner.calls,[])
            self.assertNotIn("codegraph_memory_store",ALLOWED_TOOLS)

    def test_one_shot_surface_has_no_mcp_or_hook_mode(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            base=Path(d); _,_,adapter,runner,req=self.make(base)
            adapter.query(req,"codegraph_get_module_summary",{"directory":"."},base/"analysis")
            command,_=runner.calls[0]
            self.assertNotIn("--mcp",command)
            self.assertNotIn("install-hooks",command)
            self.assertNotIn("reindex",command)
            self.assertIn("--run-tool",command)

    def test_source_drift_returns_stale_without_payload(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            base=Path(d); repo=base/"repo"; repo.mkdir(); init_repo(repo)
            binary=base/"codegraph-server"; binary.write_bytes(b"fake"); binary.chmod(0o755)
            home=base/"home"; home.mkdir()
            runner=FakeRunner(mutate=lambda:(repo/"a.py").write_text("def route_provider():\n return 2\n"))
            adapter=CodeGraphReadOnlyAdapter(binary,isolated_home=home,project_root=repo,runner=runner)
            binding=SourceSnapshotBinding.capture(repo,project_id="P")
            req=AnalysisRequest(project_id="P",run_id="R",gate_id="G",task_id="T",kind="SYMBOL_IMPACT",query="x",source_binding=binding)
            out=adapter.query(req,"codegraph_analyze_impact",{"uri":"file:///snapshot/a.py","line":0},base/"analysis")
            self.assertEqual(out.status,"STALE")
            self.assertNotIn("payload",out.result)

    def test_version_lock_and_installer_are_exact(self) -> None:
        lock=json.loads(Path("docs/harness/diagnostics/CODEGRAPH_VERSION_LOCK.json").read_text())
        self.assertEqual(lock["version"],"0.20.1")
        self.assertEqual(lock["sha256"],"32b26422fa5ffe0a130955b7f7df771f722b2d427d67f53f104d9907bdfb24a6")
        self.assertEqual((lock["mode"],lock["profile"],lock["telemetry"]),("graph-only","graph","off"))
        script=Path("scripts/install_codegraph_diagnostics.sh").read_text()
        self.assertIn(lock["sha256"],script); self.assertIn("v0.20.1",script)
        for forbidden in ("sudo ","npm install -g","install-hooks","--upgrade"):
            self.assertNotIn(forbidden,script)


if __name__ == "__main__": unittest.main()
