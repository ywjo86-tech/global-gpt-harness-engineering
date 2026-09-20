from __future__ import annotations
import tempfile, unittest
from pathlib import Path
from unittest.mock import patch
from runtime.diagnostics.contracts import DiagnosticContextPack, SourceSnapshotBinding
from runtime.orchestrator.diagnostic_context_bridge import prepare_action_diagnostic_context
from tests.test_provider_action_execution import worker

class DiagnosticContextBridgeTests(unittest.TestCase):
    def test_off_performs_no_analysis(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); (root/'.git').mkdir()
            req=worker(root,['a.py'])
            with patch('runtime.orchestrator.diagnostic_context_bridge.SourceSnapshotBinding.capture', side_effect=AssertionError('must not capture')):
                self.assertIsNone(prepare_action_diagnostic_context(req,['a.py'],env={}))

    def test_shadow_hides_advisory_text(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); req=worker(root,['a.py'])
            binding=SourceSnapshotBinding('P','b'*64,'a'*40,'c'*64,('a.py',),'d'*64,'2026-09-20T00:00:00+00:00')
            pack=DiagnosticContextPack('CURRENT',binding,('ref',),('a.py',),(),(), 'secret advisory')
            out=prepare_action_diagnostic_context(req,['a.py'],env={'GCH_DIAGNOSTIC_INTELLIGENCE_ENABLED':'true','GCH_DIAGNOSTIC_INTELLIGENCE_MODE':'SHADOW'},analysis_callback=lambda request, cfg: pack,binding=binding)
            self.assertEqual(out.advisory_text,'')
            self.assertEqual(out.status,'CURRENT')

    def test_advisory_returns_only_current_nonconflicting_text(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); req=worker(root,['a.py'])
            binding=SourceSnapshotBinding('P','b'*64,'a'*40,'c'*64,('a.py',),'d'*64,'2026-09-20T00:00:00+00:00')
            pack=DiagnosticContextPack('CURRENT',binding,('ref',),('a.py',),(),(), 'read-only evidence')
            out=prepare_action_diagnostic_context(req,['a.py'],env={'GCH_DIAGNOSTIC_INTELLIGENCE_ENABLED':'true','GCH_DIAGNOSTIC_INTELLIGENCE_MODE':'ADVISORY'},analysis_callback=lambda request, cfg: pack,binding=binding)
            self.assertEqual(out.advisory_text,'read-only evidence')

    def test_diagnostic_failure_degrades_without_escaping(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); req=worker(root,['a.py'])
            binding=SourceSnapshotBinding('P','b'*64,'a'*40,'c'*64,('a.py',),'d'*64,'2026-09-20T00:00:00+00:00')
            out=prepare_action_diagnostic_context(req,['a.py'],env={'GCH_DIAGNOSTIC_INTELLIGENCE_ENABLED':'true','GCH_DIAGNOSTIC_INTELLIGENCE_MODE':'ADVISORY'},analysis_callback=lambda *_: (_ for _ in ()).throw(RuntimeError('boom')),binding=binding)
            self.assertEqual(out.status,'DEGRADED'); self.assertEqual(out.advisory_text,'')

if __name__=='__main__': unittest.main()
