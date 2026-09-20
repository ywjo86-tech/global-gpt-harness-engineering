from __future__ import annotations
import unittest
from runtime.diagnostics.contracts import AnalysisEvidenceEnvelope, SourceSnapshotBinding
from runtime.diagnostics.rca import FailureEvidence, InvestigationProgress, investigate_failure

B=SourceSnapshotBinding('P','b'*64,'a'*40,'c'*64,(), 'd'*64,'2026-09-20T00:00:00+00:00')

def env(ref='diagnostic://sha256/'+'e'*64):
    return AnalysisEvidenceEnvelope(project_id='P',run_id='R',gate_id='G',task_id='T',analyzer='codegraph',analyzer_version='1',analysis_mode='RCA',status='CURRENT',source_binding=B,result_digest='e'*64,raw_evidence_ref=ref,result={'candidate_files':['runtime/x.py']})

class FakeRouter:
    def __init__(self, evidence=()): self.evidence=tuple(evidence)
    def analyze(self, request): return self.evidence

class RCATests(unittest.TestCase):
    def test_claims_require_evidence_and_temporal_only_is_unverified(self):
        f=FailureEvidence('P','R','G','boom','EXECUTION_FAILURE',B,temporal_correlation_only=True)
        r=investigate_failure(f,FakeRouter([env()]),max_steps=4)
        self.assertTrue(all(c.evidence_refs for c in r.root_cause_claims))
        self.assertFalse(any(c.status=='CONFIRMED' for c in r.root_cause_claims))
        self.assertTrue(r.blast_radius.not_checked)

    def test_missing_analyzer_is_explicit_limitation(self):
        f=FailureEvidence('P','R','G','boom','EXECUTION_FAILURE',B)
        r=investigate_failure(f,FakeRouter(),max_steps=3)
        self.assertTrue(any('evidence' in x.lower() for x in r.limitations))
        self.assertFalse(r.root_cause_claims)

    def test_repeated_no_progress_marks_thrashing_and_new_snapshot_resets(self):
        p=InvestigationProgress(max_repeated_without_progress=3)
        for _ in range(3): p.record_call('codegraph_analyze_impact',{'symbol':'x'},source_snapshot='a'*40,new_evidence_count=0)
        self.assertEqual(p.thrashing_state,'DIAGNOSTIC_THRASHING_SUSPECTED')
        p.record_call('codegraph_analyze_impact',{'symbol':'x'},source_snapshot='b'*40,new_evidence_count=1)
        self.assertEqual(p.thrashing_state,'NORMAL')

    def test_rca_has_no_control_callbacks(self):
        f=FailureEvidence('P','R','G','boom','EXECUTION_FAILURE',B)
        r=investigate_failure(f,FakeRouter([env()]),max_steps=4)
        for name in ('retry','resume','approve','notify','mutate','select_provider'):
            self.assertFalse(hasattr(r,name))

if __name__=='__main__': unittest.main()
