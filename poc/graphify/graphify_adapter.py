from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path
from typing import Callable

from .contracts import ProviderQueryRequest, ProviderResult, normalize_source_files

_SRC_RE = re.compile(r"\[src=([^\s\]]+)")


class GraphifyAdapter:
    def __init__(
        self,
        cli_path: str | Path,
        graph_path: str | Path,
        *,
        isolated_home: str | Path,
        runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    ) -> None:
        self.cli_path = Path(cli_path)
        self.graph_path = Path(graph_path)
        self.isolated_home = Path(isolated_home)
        self.runner = runner

    def query(self, request: ProviderQueryRequest) -> ProviderResult:
        request.validate()
        if not self.cli_path.is_file() or not self.graph_path.is_file():
            raise FileNotFoundError("Graphify CLI or graph.json is missing")
        env = dict(os.environ)
        for key in (
            "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GEMINI_API_KEY",
            "GOOGLE_API_KEY", "KIMI_API_KEY", "DEEPSEEK_API_KEY",
        ):
            env.pop(key, None)
        env["HOME"] = str(self.isolated_home)
        env["XDG_CONFIG_HOME"] = str(self.isolated_home / "xdg-config")
        env["XDG_CACHE_HOME"] = str(self.isolated_home / "xdg-cache")
        command = [
            str(self.cli_path), "query", request.query,
            "--graph", str(self.graph_path),
            "--budget", str(request.token_budget),
        ]
        completed = self.runner(
            command, capture_output=True, text=True, check=False, env=env
        )
        if completed.returncode != 0:
            raise RuntimeError(completed.stderr.strip() or "Graphify query failed")
        output = completed.stdout
        source_files = normalize_source_files(_SRC_RE.findall(output))
        result = ProviderResult(
            provider_id="graphify",
            scenario_id=request.scenario_id,
            source_ref=request.source_ref,
            status="completed",
            output=output,
            source_files=source_files,
            write_performed=False,
            freshness_state="CURRENT",
            confidence="EXTRACTED",
        )
        result.validate()
        return result
