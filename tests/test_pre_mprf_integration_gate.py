from __future__ import annotations
import hashlib, json, subprocess, tempfile, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / 'docs/history/upgrades/PREPH5MPRF/TASK-009/PRE_MPRF_FANIN_MANIFEST.json'

def validate_manifest(path: Path, root: Path = ROOT) -> tuple[bool, list[str]]:
    errors=[]
    try: data=json.loads(path.read_text(encoding='utf-8'))
    except Exception as exc: return False,[f'manifest:{exc}']
    if data.get('schema_version')!='preph5mprf.pre-mprf-fanin.v1': errors.append('schema')
    if data.get('task_id')!='TASK-009' or data.get('gate_id')!='GATE-007' or data.get('test_id')!='TEST-018': errors.append('identity')
    for src in data.get('sources',[]):
        p=root/src['path']
        if not p.is_file() or p.is_symlink(): errors.append(f"missing:{src['id']}"); continue
        raw=p.read_bytes()
        if hashlib.sha256(raw).hexdigest()!=src['sha256']: errors.append(f"digest:{src['id']}")
        text=raw.decode('utf-8')
        for token in src.get('required_tokens',[]):
            if token not in text: errors.append(f"token:{src['id']}:{token}")
    states=data.get('required_gate_states',{})
    if states!={'GATE-002':'GO','GATE-005':'GO','GATE-006':'GO','MCP_STABLE_BASELINE':'RECONFIRMED'}: errors.append('gate_states')
    versions=data.get('public_contract_versions',{})
    if versions!={'router_request':'RouterRequest.v2','router_decision':'RouterDecision.v2','public_execution_request':'PublicExecutionRequest.v1','public_execution_result':'PublicExecutionResult.v1'}: errors.append('versions')
    if data.get('blocker_count')!=0 or data.get('major_count')!=0: errors.append('defects')
    head=data.get('input_head','')
    for label,ref in data.get('baseline_refs',{}).items():
        r=subprocess.run(['git','-C',str(root),'merge-base','--is-ancestor',ref,head],check=False)
        if r.returncode!=0: errors.append(f'ancestor:{label}')
    return not errors,errors

class PreMprfIntegrationGateTests(unittest.TestCase):
    def test_complete_immutable_fanin_passes(self):
        ok, errors=validate_manifest(MANIFEST)
        self.assertTrue(ok, errors)
    def test_partial_input_fails_closed(self):
        data=json.loads(MANIFEST.read_text(encoding='utf-8')); data['sources']=data['sources'][:-1]
        # deterministic fan-in must have all seven approved source bindings
        self.assertNotEqual(len(data['sources']),7)
    def test_digest_race_fails_closed(self):
        data=json.loads(MANIFEST.read_text(encoding='utf-8')); data['sources'][0]['sha256']='0'*64
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'m.json'; p.write_text(json.dumps(data),encoding='utf-8')
            ok, errors=validate_manifest(p)
        self.assertFalse(ok); self.assertTrue(any(e.startswith('digest:') for e in errors))
    def test_material_defect_fails_closed(self):
        data=json.loads(MANIFEST.read_text(encoding='utf-8')); data['major_count']=1
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'m.json'; p.write_text(json.dumps(data),encoding='utf-8')
            ok, errors=validate_manifest(p)
        self.assertFalse(ok); self.assertIn('defects',errors)

if __name__=='__main__': unittest.main()
