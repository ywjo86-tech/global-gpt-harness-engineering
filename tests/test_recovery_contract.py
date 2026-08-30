import tempfile, unittest
from pathlib import Path
from runtime.orchestrator.recovery_contract import RecoveryError, write_recovery_record

class RecoveryContractTests(unittest.TestCase):
    def test_append_only_replay(self):
        with tempfile.TemporaryDirectory() as d:
            kw=dict(project_id='p',gate_id='g',lv_id='l',run_id='r',rejected_attempt=1,rejected_artifacts={'a.json':'a'*64},reason_code='REJECTED_UNBOUND_LEGACY',missing_bindings=['project_id'],recovery_attempt=2,approval_event_id='e',plan_sha256='b'*64,branch='main',baseline_head='c'*40,current_head='d'*40,active_transition_sha256='f'*64,source_shas={'a.json':'a'*64},predecessor=None,supersedes='old')
            first=write_recovery_record(d,**kw); second=write_recovery_record(d,**kw)
            self.assertEqual(first,second); self.assertEqual(first['hard_stop'],True)
    def test_traversal_rejected(self):
        with self.assertRaises(RecoveryError):
            write_recovery_record(tempfile.mkdtemp(),project_id='p',gate_id='g',lv_id='l',run_id='r',rejected_attempt=1,rejected_artifacts={'../x':'a'*64},reason_code='x',missing_bindings=[],recovery_attempt=2,approval_event_id='e',plan_sha256='b'*64,branch='main',baseline_head='c'*40,current_head='d'*40,active_transition_sha256='f'*64,source_shas={},predecessor=None,supersedes='old')
