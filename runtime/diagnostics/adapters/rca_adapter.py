"""Authority-free adapter exposing bounded RCA as diagnostic evidence only."""
from __future__ import annotations
import hashlib,json
from dataclasses import asdict
from ..contracts import AnalysisEvidenceEnvelope, AnalysisRequest
from ..rca import FailureEvidence, investigate_failure

class RCAReadOnlyAdapter:
    def __init__(self,router,*,max_steps:int=8): self.router=router; self.max_steps=max_steps
    def investigate(self,request:AnalysisRequest,*,reason:str,failure_class:str)->AnalysisEvidenceEnvelope:
        report=investigate_failure(FailureEvidence(request.project_id,request.run_id,request.gate_id,reason,failure_class,request.source_binding),self.router,max_steps=self.max_steps)
        result=asdict(report); raw=json.dumps(result,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode(); digest=hashlib.sha256(raw).hexdigest()
        return AnalysisEvidenceEnvelope(project_id=request.project_id,run_id=request.run_id,gate_id=request.gate_id,task_id=request.task_id,analyzer='holmes-inspired-rca',analyzer_version='1',analysis_mode='BOUNDED_RCA',status='CURRENT' if report.evidence_refs else 'DEGRADED',source_binding=request.source_binding,result_digest=digest,raw_evidence_ref=f'sha256:{digest}',result=result)
