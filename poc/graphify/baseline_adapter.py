from __future__ import annotations

import json
from pathlib import Path

from runtime.orchestrator.read_only_inspector import inspect_read_only

from .contracts import ProviderQueryRequest, ProviderResult


class ExistingInspectionAdapter:
    def __init__(self, project_root: str | Path) -> None:
        self.project_root = Path(project_root).resolve()

    def query(self, request: ProviderQueryRequest) -> ProviderResult:
        request.validate()
        report = inspect_read_only(self.project_root)
        if report.get("write_operations_performed") is not False:
            raise RuntimeError("Existing Inspection violated read-only contract")
        output = json.dumps(report, sort_keys=True, ensure_ascii=False)
        result = ProviderResult(
            provider_id="existing_inspection",
            scenario_id=request.scenario_id,
            source_ref=request.source_ref,
            status="completed",
            output=output,
            source_files=(),
            write_performed=False,
            freshness_state="CURRENT",
            confidence="CANONICAL",
        )
        result.validate()
        return result
