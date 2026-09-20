"""Deterministic analyzer routing with no Provider or execution authority."""
from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any

from .contracts import AnalysisEvidenceEnvelope, AnalysisRequest


ROUTES = {
    "SYMBOL_IMPACT": ("codegraph",),
    "TOPOLOGY": ("graphify",),
    "TOPOLOGY_AND_IMPACT": ("graphify", "codegraph"),
    "RELATED_TESTS": ("codegraph",),
    "RCA_SUPPORT": ("codegraph", "graphify"),
}


class AnalysisRouter:
    def __init__(self, graphify: Any, codegraph: Any, *, analysis_root: str | Path) -> None:
        self.graphify=graphify; self.codegraph=codegraph; self.analysis_root=Path(analysis_root).resolve()

    def _invoke(self, name: str, request: AnalysisRequest) -> AnalysisEvidenceEnvelope:
        adapter=self.graphify if name=="graphify" else self.codegraph
        if adapter is None: raise RuntimeError(f"{name} unavailable")
        root=self.analysis_root/name; root.mkdir(parents=True,exist_ok=True)
        if hasattr(adapter,"analyze"):
            return adapter.analyze(request,root)
        if name=="graphify":
            built=adapter.build_graph(request,root)
            return adapter.query(request,Path(built.result["graph_path"]))
        tool="codegraph_get_module_summary"; args={"directory":"."}
        if request.kind=="RELATED_TESTS":
            tool="codegraph_find_related_tests"; args={"symbol":request.query}
        elif request.kind=="SYMBOL_IMPACT":
            try:
                parsed=json.loads(request.query)
            except json.JSONDecodeError:
                parsed=None
            if isinstance(parsed,dict) and {"uri","line"}.issubset(parsed):
                tool="codegraph_analyze_impact"; args=parsed
        return adapter.query(request,tool,args,root)

    def analyze(self, request: AnalysisRequest) -> tuple[AnalysisEvidenceEnvelope,...]:
        route=ROUTES.get(request.kind)
        if route is None:
            return ()
        successful=[]; failures=0
        for name in route:
            try: successful.append(self._invoke(name,request))
            except Exception: failures+=1
        if not successful:
            return ()
        if failures:
            successful=[replace(item,status="DEGRADED") if item.status=="CURRENT" else item for item in successful]
        return tuple(successful)
