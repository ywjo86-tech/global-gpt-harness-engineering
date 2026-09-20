from __future__ import annotations
import unittest
from pathlib import Path
class DiagnosticAuthorityNegativeSpaceTests(unittest.TestCase):
    def test_diagnostics_contains_no_control_or_mutation_authority(self):
        root=Path('runtime/diagnostics'); text='\n'.join(p.read_text(errors='ignore') for p in root.rglob('*.py'))
        forbidden=('authorize_tool_operation','SingleToolBroker.execute','route_provider(','resume_wait(','resume_recoverable_block(','AttentionOutbox.publish','git commit','git push','systemctl','graphify hook','graphify watch','graphify install','codegraph_memory_store','codegraph_index_markdown','codegraph_reindex_workspace')
        self.assertEqual([], [x for x in forbidden if x in text])
    def test_edp_extension_preserves_universal_pass_gate(self):
        text=Path('standards/CODE_INTELLIGENCE_DIAGNOSTIC_EXTENSION.md').read_text()
        for x in ('EDP-1.0','cannot weaken','DOMAIN_EVIDENCE_COVERAGE=100%','CI-01','CI-09'): self.assertIn(x,text)
if __name__=='__main__': unittest.main()
