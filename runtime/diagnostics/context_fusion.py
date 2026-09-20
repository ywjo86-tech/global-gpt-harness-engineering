"""Bounded, deterministic fusion of advisory diagnostic evidence."""
from __future__ import annotations

import json
import re
from typing import Any, Iterable

from .contracts import AnalysisEvidenceEnvelope, AnalysisRequest, DiagnosticContextPack


_PATH_RE=re.compile(r"(?<![A-Za-z0-9_./-])([A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*\.(?:py|js|ts|tsx|rs|go|java|kt|c|cpp|h|hpp|md|json|yaml|yml))(?![A-Za-z0-9_./-])")


def _strings(value: Any) -> Iterable[str]:
    if isinstance(value,str): yield value
    elif isinstance(value,dict):
        for item in value.values(): yield from _strings(item)
    elif isinstance(value,(list,tuple,set)):
        for item in value: yield from _strings(item)


def _candidate_files(envelope: AnalysisEvidenceEnvelope) -> set[str]:
    found=set()
    if isinstance(envelope.result,dict):
        raw=envelope.result.get("candidate_files",())
        if isinstance(raw,(list,tuple,set)):
            found.update(str(x) for x in raw if isinstance(x,str))
    scan_value=envelope.result
    if isinstance(envelope.result,dict):
        scan_value={k:v for k,v in envelope.result.items() if k!="related_tests"}
    for text in _strings(scan_value):
        found.update(_PATH_RE.findall(text))
    return {item for item in found if not item.startswith("graphify-out/")}


def _related_tests(envelope: AnalysisEvidenceEnvelope) -> set[str]:
    found=set()
    if isinstance(envelope.result,dict):
        raw=envelope.result.get("related_tests",())
        if isinstance(raw,(list,tuple,set)): found.update(str(x) for x in raw if isinstance(x,str))
    found.update(x for x in _candidate_files(envelope) if x.startswith("tests/") or "/test" in x or x.startswith("test_"))
    return found

def fuse_context(request: AnalysisRequest, evidence: Iterable[AnalysisEvidenceEnvelope], *, max_chars: int) -> DiagnosticContextPack:
    items=tuple(evidence)
    refs=tuple(sorted({item.raw_evidence_ref or f"sha256:{item.result_digest}" for item in items}))
    current=tuple(item for item in items if item.status=="CURRENT")
    files=tuple(sorted(set().union(*(_candidate_files(item) for item in current)) if current else set()))
    tests=tuple(sorted(set().union(*(_related_tests(item) for item in current)) if current else set()))
    conflicts=[]
    if request.kind=="SYMBOL_IMPACT" and len(current)>=2:
        sets=[_candidate_files(item) for item in current if _candidate_files(item)]
        if len(sets)>=2 and set.intersection(*sets)==set(): conflicts.append("GRAPH_CONFLICT")
    if conflicts:
        return DiagnosticContextPack(status="CONFLICT",source_binding=request.source_binding,evidence_refs=refs,
            candidate_files=files,related_tests=tests,conflicts=tuple(conflicts),advisory_text="")
    if not current or any(item.status!="CURRENT" for item in items):
        return DiagnosticContextPack(status="DEGRADED",source_binding=request.source_binding,evidence_refs=refs,
            candidate_files=files,related_tests=tests,conflicts=(),advisory_text="")
    if max_chars<=0: raise ValueError("max_chars must be positive")
    lines=["Candidate files: "+(", ".join(files) if files else "none"),
           "Related tests: "+(", ".join(tests) if tests else "none")]
    for item in sorted(current,key=lambda x:x.analyzer):
        lines.append(f"{item.analyzer}: "+json.dumps(item.result,sort_keys=True,ensure_ascii=False))
    advisory="\n".join(lines)[:max_chars]
    return DiagnosticContextPack(status="CURRENT",source_binding=request.source_binding,evidence_refs=refs,
        candidate_files=files,related_tests=tests,conflicts=(),advisory_text=advisory)
