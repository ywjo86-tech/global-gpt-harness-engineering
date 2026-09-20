from __future__ import annotations
import unittest
from runtime.diagnostics.config import DiagnosticConfig
from runtime.diagnostics.rca import InvestigationProgress
class DiagnosticFailureInjectionTests(unittest.TestCase):
    def test_disabled_is_strict_off(self): self.assertEqual(DiagnosticConfig.from_env({}).mode,'OFF')
    def test_repeated_no_evidence_is_detected(self):
        p=InvestigationProgress(max_repeated_without_progress=3)
        for _ in range(3): p.record_call('q',{'x':1},source_snapshot='a'*64,new_evidence_count=0)
        self.assertEqual(p.thrashing_state,'DIAGNOSTIC_THRASHING_SUSPECTED')
if __name__=='__main__': unittest.main()
