import hashlib,json,unittest
from pathlib import Path

class CurrentStateProjectionTests(unittest.TestCase):
 def test_projection_precedes_historical_contract_and_evidence_digests_match(self):
  text=Path('docs/DEVELOPMENT_PLAN.txt').read_text(); self.assertLess(text.index('CURRENT_OPERATIONAL_STATE'),text.index('FULL PLAN EXECUTION CONTRACT'))
  expected=(
   'CURRENT_OPERATIONAL_STATE: AI_OFFICE_HARNESS_FINAL_OPERATIONAL_BASELINE',
   'FINAL_EDP: ALL_PASS','AI_OFFICE_STABLE_BASELINE: DECLARED',
   'PH7_PROVIDER_EXPANSION: PROVIDER_EXPANSION_RUNTIME_ALL_PASS','GROQ: ACTIVE / FREE_TIER_ONLY',
   'RUNTIME_RELEASE: ACTIVE','GRAPHIFY: PRODUCTION_READ_ONLY_ACTIVE','CODEGRAPH: PRODUCTION_READ_ONLY_ACTIVE',
   'HOLMES_INSPIRED_RCA: ACTIVE_READ_ONLY','CLI_ANYTHING: QUALIFIED_TOOL_IMPLEMENTATION',
   'DIAGNOSTIC_INTELLIGENCE: ADVISORY',
  )
  for value in expected: self.assertIn(value,text[:3000])
  d=json.loads(Path('docs/harness/CURRENT_OPERATIONAL_STATE.json').read_text())
  self.assertEqual(d['current_operational_state'],'AI_OFFICE_HARNESS_FINAL_OPERATIONAL_BASELINE')
  self.assertEqual(d['final_edp'],'ALL_PASS')
  for e in d['evidence']: self.assertEqual(hashlib.sha256(Path(e['path']).read_bytes()).hexdigest(),e['sha256'])

if __name__=='__main__': unittest.main()
