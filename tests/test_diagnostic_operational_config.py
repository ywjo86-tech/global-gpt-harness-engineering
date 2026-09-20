from __future__ import annotations
import json,os,tempfile,unittest
from pathlib import Path
from runtime.diagnostics.config import DiagnosticConfig,DiagnosticConfigError
class OperationalConfigTests(unittest.TestCase):
 def make(self,root,mode='SHADOW'):
  g=root/'g'; c=root/'c'; g.write_text('x'); c.write_text('x'); g.chmod(0o700); c.chmod(0o700)
  p=root/'cfg.json'; p.write_text(json.dumps({'enabled':True,'mode':mode,'graphify_cli':str(g),'codegraph_binary':str(c),'max_result_bytes':100,'max_context_chars':100})); p.chmod(0o600); return p
 def test_ignored_without_explicit_enable(self):
  with tempfile.TemporaryDirectory() as td:
   p=self.make(Path(td)); self.assertFalse(DiagnosticConfig.from_env({'GCH_DIAGNOSTIC_CONFIG':str(p)}).enabled)
 def test_loads_safe_explicit_config(self):
  with tempfile.TemporaryDirectory() as td:
   p=self.make(Path(td)); cfg=DiagnosticConfig.from_env({'GCH_DIAGNOSTIC_INTELLIGENCE_ENABLED':'true','GCH_DIAGNOSTIC_CONFIG':str(p)}); self.assertEqual(cfg.mode,'SHADOW'); self.assertTrue(cfg.graphify_cli)
 def test_rejects_symlink_and_group_writable(self):
  with tempfile.TemporaryDirectory() as td:
   r=Path(td); p=self.make(r); link=r/'link'; link.symlink_to(p)
   with self.assertRaises(DiagnosticConfigError): DiagnosticConfig.load(link)
   p.chmod(0o664)
   with self.assertRaises(DiagnosticConfigError): DiagnosticConfig.load(p)
if __name__=='__main__': unittest.main()
