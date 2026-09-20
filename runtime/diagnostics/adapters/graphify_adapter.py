"""Pinned local-only Graphify adapter with zero control or mutation authority."""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path
from typing import Any, Callable, Mapping

from ..contracts import AnalysisEvidenceEnvelope, AnalysisRequest, SourceSnapshotBinding
from ..security import assert_binding_current, prepare_source_snapshot


class GraphifyAdapterError(RuntimeError):
    pass


GRAPHIFY_VERSION = "0.9.58"
_PROVIDER_PREFIXES = (
    "OPENAI_", "ANTHROPIC_", "GEMINI_", "KIMI_", "DEEPSEEK_",
    "GOOGLE_API", "AWS_ACCESS_KEY", "AWS_SECRET", "AWS_SESSION_TOKEN",
)


def _digest(value: object) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()

class GraphifyReadOnlyAdapter:
    def __init__(
        self, cli_path: str | Path, *, isolated_home: str | Path,
        timeout_seconds: int = 30, project_root: str | Path | None = None,
        runner: Callable[..., Any] = subprocess.run,
    ) -> None:
        self.cli_path = Path(cli_path).expanduser().resolve()
        self.isolated_home = Path(isolated_home).expanduser().resolve()
        self.timeout_seconds = int(timeout_seconds)
        self.project_root = Path(project_root).resolve() if project_root is not None else None
        self.runner = runner
        self._known_graphs: dict[Path, tuple[Path, SourceSnapshotBinding]] = {}
        if not self.cli_path.is_file() or not os.access(self.cli_path, os.X_OK):
            raise GraphifyAdapterError("Graphify CLI is missing or not executable")
        if self.timeout_seconds <= 0:
            raise GraphifyAdapterError("timeout must be positive")
        self.isolated_home.mkdir(parents=True, exist_ok=True)
        if self.isolated_home.is_symlink():
            raise GraphifyAdapterError("isolated Graphify HOME is unsafe")

    def safe_env(self, base_env: Mapping[str, str] | None = None) -> dict[str, str]:
        source = dict(os.environ if base_env is None else base_env)
        for key in list(source):
            upper = key.upper()
            if any(upper.startswith(prefix) for prefix in _PROVIDER_PREFIXES):
                source.pop(key, None)
        source["HOME"] = str(self.isolated_home)
        source["GRAPHIFY_HOOK_STRICT"] = "0"
        source.pop("GRAPHIFY_FORCE", None)
        return source

    def _analysis_root(self, value: str | Path) -> Path:
        root = Path(value).resolve()
        if root.is_symlink():
            raise GraphifyAdapterError("analysis root is unsafe")
        if self.project_root is not None:
            try:
                relative = root.relative_to(self.project_root)
            except ValueError:
                relative = None
            if relative is not None and (not relative.parts or relative.parts[0] != "_workspace"):
                raise GraphifyAdapterError("diagnostic output cannot enter source-controlled paths")
        root.mkdir(parents=True, exist_ok=True)
        return root

    def _run(self, command: list[str], *, cwd: Path) -> Any:
        completed = self.runner(
            command, capture_output=True, text=True, check=False,
            timeout=self.timeout_seconds, env=self.safe_env(), cwd=str(cwd),
        )
        if int(getattr(completed, "returncode", 1)) != 0:
            detail = str(getattr(completed, "stderr", ""))[:2000]
            raise GraphifyAdapterError(f"Graphify read-only operation failed: {detail}")
        return completed

    def _envelope(self, request: AnalysisRequest, *, mode: str, result: dict[str, Any],
                  raw_ref: str) -> AnalysisEvidenceEnvelope:
        return AnalysisEvidenceEnvelope(
            project_id=request.project_id, run_id=request.run_id,
            gate_id=request.gate_id, task_id=request.task_id,
            analyzer="graphify", analyzer_version=GRAPHIFY_VERSION,
            analysis_mode=mode, status="CURRENT", source_binding=request.source_binding,
            result_digest=_digest(result), raw_evidence_ref=raw_ref, result=result,
        )

    def build_graph(self, request: AnalysisRequest, analysis_root: str | Path) -> AnalysisEvidenceEnvelope:
        root = self._analysis_root(analysis_root)
        if self.project_root is not None:
            snapshot = prepare_source_snapshot(self.project_root, root, request.source_binding)
        else:
            snapshot = root / "source-snapshot"
            if not snapshot.is_dir() or snapshot.is_symlink():
                raise GraphifyAdapterError("prepared source snapshot is required")
        command = [
            str(self.cli_path), "extract", str(snapshot),
            "--code-only", "--no-cluster", "--out", str(root),
        ]
        completed = self._run(command, cwd=root)
        graph = (root / "graphify-out" / "graph.json").resolve()
        if not graph.is_file() or graph.is_symlink():
            raise GraphifyAdapterError("Graphify did not produce a safe graph.json")
        if self.project_root is not None:
            assert_binding_current(request.source_binding, self.project_root)
        self._known_graphs[graph] = (root, request.source_binding)
        result = {
            "graph_path": str(graph),
            "source_git_head_sha": request.source_binding.git_head_sha,
            "mode": "code-only/no-cluster",
            "stdout": str(getattr(completed, "stdout", ""))[:12000],
        }
        return self._envelope(request, mode="BUILD", result=result, raw_ref=str(graph))

    def query(self, request: AnalysisRequest, graph_path: str | Path, *, token_budget: int = 1200) -> AnalysisEvidenceEnvelope:
        graph = Path(graph_path).resolve()
        known = self._known_graphs.get(graph)
        if known is None or not graph.is_file() or graph.is_symlink():
            raise GraphifyAdapterError("graph path is not a graph produced by this adapter")
        if not 1 <= int(token_budget) <= 4000:
            raise GraphifyAdapterError("Graphify query token budget is outside the safe bound")
        analysis_root, binding = known
        if binding != request.source_binding:
            raise GraphifyAdapterError("Graphify graph source binding mismatch")
        if self.project_root is not None:
            assert_binding_current(request.source_binding, self.project_root)
        command = [str(self.cli_path), "query", request.query, "--graph", str(graph), "--budget", str(int(token_budget))]
        completed = self._run(command, cwd=analysis_root)
        if self.project_root is not None:
            assert_binding_current(request.source_binding, self.project_root)
        result = {
            "text": str(getattr(completed, "stdout", ""))[:24000],
            "graph_path": str(graph),
            "source_git_head_sha": request.source_binding.git_head_sha,
            "token_budget": int(token_budget),
        }
        return self._envelope(request, mode="QUERY", result=result, raw_ref=str(graph))
