import hashlib,json,unittest
from pathlib import Path
class CurrentStateProjectionTests(unittest.TestCase):
 def test_projection_precedes_historical_contract_and_evidence_digests_match(self):
  text=Path('docs/DEVELOPMENT_PLAN.txt').read_text(); self.assertLess(text.index('CURRENT_OPERATIONAL_STATE'),text.index('FULL PLAN EXECUTION CONTRACT'))
  for x in ('AI_OFFICE_STABLE_BASELINE: DECLARED','PH7_PROVIDER_EXPANSION: PROVIDER_EXPANSION_RUNTIME_ALL_PASS','DIAGNOSTIC_INTELLIGENCE: ADVISORY_QUALIFIED'): self.assertIn(x,text[:2500])
  d=json.loads(Path('docs/harness/CURRENT_OPERATIONAL_STATE.json').read_text())
  for e in d['evidence']: self.assertEqual(hashlib.sha256(Path(e['path']).read_bytes()).hexdigest(),e['sha256'])
if __name__=='__main__': unittest.main()
