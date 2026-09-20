"""Bounded evidence-first RCA inspired by HolmesGPT investigation discipline."""
from __future__ import annotations
import json
from dataclasses import dataclass, field
from typing import Any
from .contracts import AnalysisRequest, SourceSnapshotBinding

@dataclass(frozen=True,slots=True)
class InvestigationTask:
    id:str; question:str; status:str='PENDING'; evidence_refs:tuple[str,...]=()
@dataclass(frozen=True,slots=True)
class FailureEvidence:
    project_id:str; run_id:str; gate_id:str; reason:str; failure_class:str; source_binding:SourceSnapshotBinding; temporal_correlation_only:bool=False
@dataclass(frozen=True,slots=True)
class RootCauseClaim:
    claim:str; status:str; evidence_refs:tuple[str,...]
@dataclass(frozen=True,slots=True)
class BlastRadius:
    affected:tuple[str,...]=(); checked_healthy:tuple[str,...]=(); changed_for_another_reason:tuple[str,...]=(); not_checked:tuple[str,...]=()
@dataclass(frozen=True,slots=True)
class RCAReport:
    root_cause_claims:tuple[RootCauseClaim,...]; evidence_refs:tuple[str,...]; blast_radius:BlastRadius; limitations:tuple[str,...]; thrashing_state:str; tool_call_count:int; new_evidence_count:int; repeated_query_count:int; semantic_progress_sequence:int; tasks:tuple[InvestigationTask,...]

@dataclass
class InvestigationProgress:
    max_repeated_without_progress:int=3
    tool_call_count:int=0; new_evidence_count:int=0; repeated_query_count:int=0; semantic_progress_sequence:int=0; thrashing_state:str='NORMAL'
    _last_key:str=''; _no_progress:int=0
    def record_call(self,tool:str,args:dict[str,Any],*,source_snapshot:str,new_evidence_count:int)->None:
        key=json.dumps([tool,args,source_snapshot],sort_keys=True,separators=(',',':'))
        self.tool_call_count+=1
        if key==self._last_key and new_evidence_count<=0:
            self.repeated_query_count+=1; self._no_progress+=1
        elif new_evidence_count>0 or key!=self._last_key:
            self._no_progress=0
        if new_evidence_count>0:
            self.new_evidence_count+=new_evidence_count; self.semantic_progress_sequence+=1; self.thrashing_state='NORMAL'
        elif self._no_progress>=self.max_repeated_without_progress-1:
            self.thrashing_state='DIAGNOSTIC_THRASHING_SUSPECTED'
        self._last_key=key

def investigate_failure(failure:FailureEvidence,router,*,max_steps:int=8)->RCAReport:
    if max_steps<=0: raise ValueError('max_steps must be positive')
    questions=('validate failure facts','check immediate dependencies and impact','check competing causes','check blast radius','validate causal evidence')
    tasks=[InvestigationTask(f'RCA-{i+1:02d}',q) for i,q in enumerate(questions)]
    progress=InvestigationProgress(); refs=[]; affected=set(); limitations=[]
    steps=min(max_steps,len(tasks))
    for i in range(steps):
        req=AnalysisRequest(failure.project_id,failure.run_id,failure.gate_id,tasks[i].id,'RCA_SUPPORT',f'{failure.reason}: {tasks[i].question}',failure.source_binding)
        try: evidence=tuple(router.analyze(req))
        except Exception as exc:
            evidence=(); limitations.append(f'analyzer failure: {type(exc).__name__}')
        new=[e.raw_evidence_ref or f'sha256:{e.result_digest}' for e in evidence if e.status=='CURRENT']
        progress.record_call('analysis_router',{'question':tasks[i].question},source_snapshot=failure.source_binding.workspace_tree_digest,new_evidence_count=len(set(new)-set(refs)))
        refs.extend(new)
        for e in evidence:
            if isinstance(e.result,dict):
                for p in e.result.get('candidate_files',()): affected.add(str(p))
        tasks[i]=InvestigationTask(tasks[i].id,tasks[i].question,'COMPLETED' if new else 'FAILED',tuple(new))
    if not refs: limitations.append('no current causal evidence was produced')
    if steps<len(tasks):
        limitations.append('max_steps reached before investigation completion')
        tasks=[t if i<steps else InvestigationTask(t.id,t.question,'IN_PROGRESS',()) for i,t in enumerate(tasks)]
    unique=tuple(dict.fromkeys(refs)); claims=()
    if unique:
        status='UNVERIFIED' if failure.temporal_correlation_only else 'SUPPORTED'
        claims=(RootCauseClaim(f'Failure class {failure.failure_class} is associated with the collected bounded evidence.',status,unique),)
    blast=BlastRadius(tuple(sorted(affected)),(),(),('unobserved dynamic/configuration/external paths',))
    return RCAReport(claims,unique,blast,tuple(dict.fromkeys(limitations)),progress.thrashing_state,progress.tool_call_count,progress.new_evidence_count,progress.repeated_query_count,progress.semantic_progress_sequence,tuple(tasks))
