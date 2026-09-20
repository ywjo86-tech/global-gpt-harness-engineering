"""One-way, authority-free diagnostic context bridge for ACTION proposal generation."""
from __future__ import annotations
from dataclasses import replace
from pathlib import Path
from typing import Callable, Mapping

from runtime.diagnostics.config import DiagnosticConfig
from runtime.diagnostics.contracts import AnalysisRequest, DiagnosticContextPack, SourceSnapshotBinding


def _degraded(binding: SourceSnapshotBinding) -> DiagnosticContextPack:
    return DiagnosticContextPack(status='DEGRADED', source_binding=binding, advisory_text='')


def prepare_action_diagnostic_context(
    request, owned: list[str], *, env: Mapping[str,str] | None=None,
    analysis_callback: Callable | None=None, binding: SourceSnapshotBinding | None=None,
) -> DiagnosticContextPack | None:
    cfg=DiagnosticConfig.from_env(env)
    if not cfg.enabled or cfg.mode=='OFF':
        return None
    try:
        project_id=str(request.contract_summary.get('project_id') or '')
        current=binding or SourceSnapshotBinding.capture(request.project_root,project_id=project_id,owned_paths=owned)
        analysis_request=AnalysisRequest(
            project_id=project_id, run_id=str(request.extra_context.get('run_id') or ''),
            gate_id=str(request.contract_summary.get('gate_id') or ''), task_id=str(request.task.thread_id),
            kind='TOPOLOGY_AND_IMPACT', query=str(request.task.input), source_binding=current,
            owned_paths=tuple(owned),
        )
        if analysis_callback is None:
            return _degraded(current)
        pack=analysis_callback(analysis_request,cfg)
        if pack.status != 'CURRENT' or pack.conflicts:
            return replace(pack, advisory_text='')
        if cfg.mode=='SHADOW':
            return replace(pack, advisory_text='')
        return replace(pack, advisory_text=pack.advisory_text[:cfg.max_context_chars])
    except Exception:
        if binding is not None:
            return _degraded(binding)
        try:
            fallback=SourceSnapshotBinding.capture(request.project_root,project_id=str(request.contract_summary.get('project_id') or ''),owned_paths=owned)
            return _degraded(fallback)
        except Exception:
            return None
