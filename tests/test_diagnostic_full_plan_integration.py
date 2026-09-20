from __future__ import annotations
import tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from runtime.orchestrator.production_full_plan_runner import DurableFullPlanSupervisor

class DiagnosticFullPlanIntegrationTests(unittest.TestCase):
    def _run(self, hook):
        with tempfile.TemporaryDirectory() as td:
            s=DurableFullPlanSupervisor(td,project_id='P',run_id='R',gates=['G'],retry_budget=0,resource_probe=lambda _: {'disk_free_bytes':10**9,'inode_free':10**6,'memory_available_bytes':10**9,'cpu_load_per_cpu_milli':0,'io_pressure_full_avg10_milli':0})
            st=s._initial(); item=st['queue'][0]
            with patch('runtime.orchestrator.production_full_plan_runner.record_failure_diagnostics',side_effect=hook) if isinstance(hook,Exception) else patch('runtime.orchestrator.production_full_plan_runner.record_failure_diagnostics',return_value=hook):
                out=s._handle_failure(st,item,'boom')
            control_queue=[{k:item.get(k) for k in ('gate_id','gate_run_id','idempotency_key','attempt','status','resume','last_error')} for item in out['queue']]
            return {k:out.get(k) for k in ('state','current_gate','terminal_reason','last_error','recovery_count')}, control_queue
    def test_rca_cannot_change_retry_or_terminal_state(self):
        off=self._run(None); good=self._run('diagnostic://sha256/'+'a'*64); bad=self._run(RuntimeError('rca failed'))
        self.assertEqual(off,good); self.assertEqual(off,bad)
    def test_failure_diagnostic_path_is_below_run_diagnostics(self):
        with tempfile.TemporaryDirectory() as td:
            s=DurableFullPlanSupervisor(td,project_id='P',run_id='R',gates=['G'],retry_budget=0,resource_probe=lambda _: {'disk_free_bytes':10**9,'inode_free':10**6,'memory_available_bytes':10**9,'cpu_load_per_cpu_milli':0,'io_pressure_full_avg10_milli':0})
            seen=[]
            with patch('runtime.orchestrator.production_full_plan_runner.record_failure_diagnostics',side_effect=lambda **kw: seen.append(kw['output_root']) or None):
                s._handle_failure(s._initial(),s._initial()['queue'][0],'boom')
            self.assertEqual(Path(seen[0]).resolve(),(s.base/'diagnostics').resolve())
if __name__=='__main__': unittest.main()
