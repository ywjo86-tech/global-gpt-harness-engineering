"""Isolated graph-only CodeGraph adapter for structural code intelligence."""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path
from typing import Any, Callable, Mapping
from urllib.parse import unquote, urlparse

from ..contracts import AnalysisEvidenceEnvelope, AnalysisRequest
from ..security import DiagnosticStaleError, assert_binding_current, prepare_source_snapshot


class CodeGraphAdapterError(RuntimeError):
    pass


CODEGRAPH_VERSION = "0.20.1"
ALLOWED_TOOLS = frozenset({
    "codegraph_analyze_impact", "codegraph_get_callers", "codegraph_get_callees",
    "codegraph_get_dependency_graph", "codegraph_find_related_tests",
    "codegraph_find_entry_points", "codegraph_get_module_summary", "codegraph_traverse_graph",
})


def _digest(value: object) -> str:
    raw=json.dumps(value,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()

class CodeGraphReadOnlyAdapter:
    def __init__(self, binary_path: str | Path, *, isolated_home: str | Path,
                 timeout_seconds: int = 45, project_root: str | Path | None = None,
                 runner: Callable[..., Any] = subprocess.run) -> None:
        self.binary_path=Path(binary_path).expanduser().resolve()
        self.isolated_home=Path(isolated_home).expanduser().resolve()
        self.timeout_seconds=int(timeout_seconds)
        self.project_root=Path(project_root).resolve() if project_root is not None else None
        self.runner=runner
        if not self.binary_path.is_file() or not os.access(self.binary_path,os.X_OK):
            raise CodeGraphAdapterError("CodeGraph binary is missing or not executable")
        if self.timeout_seconds <= 0:
            raise CodeGraphAdapterError("timeout must be positive")
        self.isolated_home.mkdir(parents=True,exist_ok=True)
        if self.isolated_home.is_symlink():
            raise CodeGraphAdapterError("isolated CodeGraph HOME is unsafe")

    def safe_env(self, home: Path, base_env: Mapping[str,str] | None=None) -> dict[str,str]:
        env=dict(os.environ if base_env is None else base_env)
        env["HOME"]=str(home)
        env["CODEGRAPH_TELEMETRY"]="off"
        env["CODEGRAPH_TOOL_PROFILE"]="graph"
        env["XDG_CACHE_HOME"]=str(home/".cache")
        env["XDG_CONFIG_HOME"]=str(home/".config")
        env["XDG_DATA_HOME"]=str(home/".local/share")
        return env

    @staticmethod
    def _under(path: Path, root: Path) -> bool:
        try: path.resolve().relative_to(root.resolve()); return True
        except ValueError: return False

    def _normalize_args(self, value: Any, snapshot: Path, key: str="") -> Any:
        if isinstance(value, dict):
            return {str(k):self._normalize_args(v,snapshot,str(k)) for k,v in value.items()}
        if isinstance(value, list):
            return [self._normalize_args(v,snapshot,key) for v in value]
        if not isinstance(value,str):
            return value
        if value.startswith("file:///snapshot/"):
            rel=Path(unquote(value[len("file:///snapshot/"):]))
            if rel.is_absolute() or ".." in rel.parts:
                raise CodeGraphAdapterError("unsafe snapshot URI")
            return (snapshot/rel).resolve().as_uri()
        if value.startswith("file://"):
            parsed=Path(unquote(urlparse(value).path)).resolve()
            if not self._under(parsed,snapshot):
                raise CodeGraphAdapterError("CodeGraph file URI escapes source snapshot")
            return parsed.as_uri()
        if key in {"directory","path"}:
            if value == ".": return str(snapshot)
            candidate=Path(value)
            resolved=(snapshot/candidate).resolve() if not candidate.is_absolute() else candidate.resolve()
            if not self._under(resolved,snapshot):
                raise CodeGraphAdapterError("CodeGraph path escapes source snapshot")
            return str(resolved)
        return value

    def _envelope(self, request: AnalysisRequest, *, status: str, tool: str,
                  result: dict[str,Any], raw_ref: str="") -> AnalysisEvidenceEnvelope:
        return AnalysisEvidenceEnvelope(
            project_id=request.project_id,run_id=request.run_id,gate_id=request.gate_id,
            task_id=request.task_id,analyzer="codegraph",analyzer_version=CODEGRAPH_VERSION,
            analysis_mode=tool,status=status,source_binding=request.source_binding,
            result_digest=_digest(result),raw_evidence_ref=raw_ref,result=result,
        )

    def query(self, request: AnalysisRequest, tool_name: str, tool_args: Mapping[str,Any],
              analysis_root: str | Path) -> AnalysisEvidenceEnvelope:
        if tool_name not in ALLOWED_TOOLS:
            raise CodeGraphAdapterError("CodeGraph tool is outside the structural read-only allowlist")
        root=Path(analysis_root).resolve(); root.mkdir(parents=True,exist_ok=True)
        if root.is_symlink():
            raise CodeGraphAdapterError("analysis root is unsafe")
        if self.project_root is not None:
            snapshot=prepare_source_snapshot(self.project_root,root,request.source_binding)
        else:
            snapshot=root/"source-snapshot"
            if not snapshot.is_dir() or snapshot.is_symlink():
                raise CodeGraphAdapterError("prepared source snapshot is required")
        home=root/"codegraph-home"; home.mkdir(parents=True,exist_ok=True)
        normalized=self._normalize_args(dict(tool_args),snapshot)
        args_json=json.dumps(normalized,sort_keys=True,separators=(",",":"),ensure_ascii=False)
        command=[str(self.binary_path),"--graph-only","--profile","graph","--workspace",str(snapshot),
                 "--run-tool",tool_name,"--tool-args",args_json]
        completed=self.runner(command,capture_output=True,text=True,check=False,
                              timeout=self.timeout_seconds,env=self.safe_env(home),cwd=str(root))
        if int(getattr(completed,"returncode",1)) != 0:
            detail=str(getattr(completed,"stderr",""))[:2000]
            raise CodeGraphAdapterError(f"CodeGraph one-shot query failed: {detail}")
        binary_sha=hashlib.sha256(self.binary_path.read_bytes()).hexdigest()
        try:
            if self.project_root is not None: assert_binding_current(request.source_binding,self.project_root)
        except DiagnosticStaleError:
            result={"binary_sha256":binary_sha,"tool_name":tool_name,"source_git_head_sha":request.source_binding.git_head_sha,"reason":"CODE_INTELLIGENCE_STALE"}
            return self._envelope(request,status="STALE",tool=tool_name,result=result)
        stdout=str(getattr(completed,"stdout",""))
        try: payload=json.loads(stdout)
        except json.JSONDecodeError: payload={"text":stdout[:240000]}
        result={"binary_sha256":binary_sha,"tool_name":tool_name,"command_mode":"graph-only/graph/one-shot",
                "source_git_head_sha":request.source_binding.git_head_sha,"payload":payload}
        return self._envelope(request,status="CURRENT",tool=tool_name,result=result)
