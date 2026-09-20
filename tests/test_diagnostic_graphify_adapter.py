import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from runtime.diagnostics.adapters.graphify_adapter import (
    GraphifyAdapterError, GraphifyReadOnlyAdapter,
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
    def __init__(self) -> None:
        self.calls = []

    def __call__(self, command, **kwargs):
        self.calls.append((list(command), dict(kwargs)))
        if "extract" in command:
            out = Path(command[command.index("--out") + 1]) / "graphify-out"
            out.mkdir(parents=True, exist_ok=True)
            (out / "graph.json").write_text(json.dumps({"nodes": [], "edges": []}), encoding="utf-8")
            stdout = "extracted"
        else:
            stdout = "route_provider -> provider_router.py"
        return subprocess.CompletedProcess(command, 0, stdout=stdout, stderr="")


class DiagnosticGraphifyAdapterTests(unittest.TestCase):
    def make(self, base: Path):
        repo = base / "repo"; repo.mkdir(); init_repo(repo)
        cli = base / "graphify"; cli.write_text("#!/bin/sh\nexit 0\n"); cli.chmod(0o755)
        home = base / "home"; home.mkdir()
        runner = FakeRunner()
        adapter = GraphifyReadOnlyAdapter(cli, isolated_home=home, project_root=repo, runner=runner)
        binding = SourceSnapshotBinding.capture(repo, project_id="P")
        request = AnalysisRequest(project_id="P", run_id="R", gate_id="G", task_id="T",
            kind="TOPOLOGY", query="provider flow", source_binding=binding)
        return repo, adapter, runner, request

    def test_graphify_build_is_local_read_only_and_strips_provider_keys(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            base = Path(d); repo, adapter, runner, request = self.make(base)
            env = adapter.safe_env({"OPENAI_API_KEY":"secret", "ANTHROPIC_API_KEY":"secret", "PATH":os.environ.get("PATH","")})
            for key in ("OPENAI_API_KEY","ANTHROPIC_API_KEY","GEMINI_API_KEY","GOOGLE_API_KEY","KIMI_API_KEY","DEEPSEEK_API_KEY"):
                self.assertNotIn(key, env)
            self.assertEqual(env["GRAPHIFY_HOOK_STRICT"], "0")
            analysis = base / "analysis"
            envelope = adapter.build_graph(request, analysis)
            command, kwargs = runner.calls[0]
            self.assertEqual(command[1:3], ["extract", str(analysis / "source-snapshot")])
            self.assertEqual(command[-4:], ["--code-only", "--no-cluster", "--out", str(analysis)])
            self.assertEqual(envelope.status, "CURRENT")
            self.assertEqual(envelope.result["source_git_head_sha"], request.source_binding.git_head_sha)

    def test_query_accepts_only_graph_built_by_same_adapter_and_is_bounded(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            base = Path(d); _, adapter, runner, request = self.make(base)
            analysis = base / "analysis"
            built = adapter.build_graph(request, analysis)
            graph = Path(built.result["graph_path"])
            out = adapter.query(request, graph, token_budget=900)
            command, _ = runner.calls[-1]
            self.assertEqual(command[1], "query")
            self.assertEqual(command[2], request.query)
            self.assertEqual(command[3:5], ["--graph", str(graph)])
            self.assertEqual(command[5:7], ["--budget", "900"])
            self.assertEqual(out.result["source_git_head_sha"], request.source_binding.git_head_sha)
            with self.assertRaises(GraphifyAdapterError):
                adapter.query(request, base / "other/graph.json")
            with self.assertRaises(GraphifyAdapterError):
                adapter.query(request, graph, token_budget=999999)

    def test_source_change_after_build_makes_query_stale(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            base = Path(d); repo, adapter, _, request = self.make(base)
            built = adapter.build_graph(request, base / "analysis")
            (repo / "a.py").write_text("def route_provider():\n    return 2\n", encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "CODE_INTELLIGENCE_STALE"):
                adapter.query(request, Path(built.result["graph_path"]))

    def test_adapter_surface_contains_no_mutating_graphify_commands(self) -> None:
        source = Path("runtime/diagnostics/adapters/graphify_adapter.py").read_text(encoding="utf-8")
        for forbidden in ("hook install", "watch ", "graphify install", " serve ", "--transport", "save-result", "global add"):
            self.assertNotIn(forbidden, source)

    def test_installer_is_pinned_user_owned_and_has_no_auto_integration(self) -> None:
        script = Path("scripts/install_graphify_diagnostics.sh").read_text(encoding="utf-8")
        self.assertIn("VERSION=0.9.58", script)
        self.assertIn("e239803288e91c723d6e30540860bd6d5a1dc3f0914b9fc1104b0233e98aaeb8", script)
        self.assertIn("$HOME/.local/share/gch/diagnostics/graphify", script)
        for forbidden in ("sudo ", "graphify install", "hook install", "watch ", "--upgrade"):
            self.assertNotIn(forbidden, script)


if __name__ == "__main__": unittest.main()
