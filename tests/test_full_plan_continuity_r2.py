from __future__ import annotations

import json
import multiprocessing as mp
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

from runtime.orchestrator.production_attention import AttentionOutbox
from runtime.orchestrator.production_full_plan_boot import FullPlanBootError, ensure_runtime_link, reconcile_job, systemd_user_timer
from runtime.orchestrator.production_full_plan_entry import load_job, register_job
from runtime.orchestrator.production_full_plan_runner import DurableFullPlanSupervisor
from runtime.orchestrator.runtime_migration_handoff import MigrationPhase, MigrationStore
from runtime.orchestrator.cli import main as cli_main


def _completed(gate_id: str, gate_run_id: str, resume: bool):
    return {"status": "GATE_EXIT", "gate_id": gate_id, "run_id": gate_run_id,
            "next": {"action": "SYSTEM_TRANSITION", "automatic": True}}


def _concurrent_run(root: str, start: mp.Event, results: mp.Queue) -> None:
    sup = DurableFullPlanSupervisor(
        root, project_id="proj", run_id="same-run", gates=["G1"], retry_budget=0,
        gate_timeout_seconds=2, heartbeat_seconds=.03, lease_seconds=.08,
        min_disk_free_bytes=0, min_inode_free=0, min_memory_available_bytes=0,
    )
    effect = Path(root) / "effect.log"

    def executor(gate_id: str, gate_run_id: str, resume: bool):
        with effect.open("a", encoding="utf-8") as handle:
            handle.write(f"{mp.current_process().pid}:{gate_id}\n")
            handle.flush()
        time.sleep(.35)
        return _completed(gate_id, gate_run_id, resume)

    start.wait(5)
    try:
        out = sup.run(executor)
        results.put(("ok", out.status))
    except Exception as exc:
        results.put(("error", type(exc).__name__, str(exc)))


class FullPlanContinuityR2Tests(unittest.TestCase):
    def supervisor(self, root: str, *, gates=("G1",)) -> DurableFullPlanSupervisor:
        return DurableFullPlanSupervisor(
            root, project_id="proj", run_id="run", gates=list(gates), retry_budget=0,
            gate_timeout_seconds=1, heartbeat_seconds=.03, lease_seconds=.08,
            min_disk_free_bytes=0, min_inode_free=0, min_memory_available_bytes=0,
        )

    def test_single_writer_lock_prevents_duplicate_effect(self):
        with tempfile.TemporaryDirectory() as d:
            start = mp.Event(); results = mp.Queue()
            workers = [mp.Process(target=_concurrent_run, args=(d, start, results)) for _ in range(2)]
            for worker in workers:
                worker.start()
            start.set()
            for worker in workers:
                worker.join(5)
            rows = [results.get(timeout=2) for _ in range(2)]
            self.assertEqual(sum(1 for row in rows if row[0] == "ok"), 1, rows)
            errors = [row for row in rows if row[0] == "error"]
            self.assertEqual(len(errors), 1, rows)
            self.assertIn("duplicate Full Plan supervisor", errors[0][2])
            lines = (Path(d) / "effect.log").read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(lines), 1, lines)

    def test_preflight_block_creates_alert_and_durable_attention(self):
        with tempfile.TemporaryDirectory() as d:
            sup = self.supervisor(d)
            out = sup.run(_completed, preflight=lambda _: {"status": "BLOCK", "reason": "TEST_PREFLIGHT_BLOCK"})
            self.assertEqual(out.status, "BLOCKED")
            alerts = [json.loads(line) for line in sup.alert_path.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(alerts[-1]["alert"], "PREFLIGHT_BLOCKED")
            pending = sup.attention_outbox.pending()
            self.assertEqual(len(pending), 1)
            self.assertEqual(pending[0]["kind"], "PREFLIGHT_BLOCKED")
            self.assertEqual(pending[0]["control_authority"], "NONE")

    def test_missing_successor_is_explicit_block_with_attention(self):
        with tempfile.TemporaryDirectory() as d:
            sup = self.supervisor(d, gates=("G1", "G2"))
            state, _ = sup.load()
            state["completed_gates"] = ["G1"]
            state["queue"][0]["status"] = "COMPLETED"
            state["current_gate"] = "G2"
            state["state"] = "READY"
            sup._persist(state, {"event": "TEST_MISSING_SUCCESSOR"})
            out = sup.run(_completed)
            self.assertEqual(out.status, "BLOCKED")
            self.assertEqual(out.state["terminal_reason"], "DURABLE_SUCCESSOR_MISSING")
            self.assertEqual(out.state["last_error"], "ELIGIBLE_SUCCESSOR_MISSING")
            self.assertEqual(sup.attention_outbox.pending()[0]["kind"], "DURABLE_SUCCESSOR_MISSING")

    def test_startup_active_state_without_queue_item_blocks_and_alerts(self):
        with tempfile.TemporaryDirectory() as d:
            sup = self.supervisor(d)
            state, _ = sup.load()
            state["queue"][0]["status"] = "COMPLETED"
            state["state"] = "RUNNING"
            state["lease"] = {"epoch": 1}
            sup._persist(state, {"event": "TEST_ORPHAN_ACTIVE_STATE"})
            out = sup.run(_completed)
            self.assertEqual(out.status, "BLOCKED")
            self.assertEqual(out.state["terminal_reason"], "STARTUP_RECONCILIATION_BLOCKED")
            self.assertEqual(out.state["last_error"], "ACTIVE_RUN_QUEUE_MISSING")
            self.assertEqual(sup.attention_outbox.pending()[0]["kind"], "STARTUP_RECONCILIATION_BLOCKED")

    def test_attention_outbox_is_idempotent_and_outbound_only(self):
        with tempfile.TemporaryDirectory() as d:
            outbox = AttentionOutbox(Path(d) / "run", project_id="proj", run_id="run")
            first = outbox.publish(kind="BLOCKED", state="BLOCKED", reason="reason", state_sha256="a" * 64, delivery_class="DEFERRED_INCIDENT")
            second = outbox.publish(kind="BLOCKED", state="BLOCKED", reason="reason", state_sha256="a" * 64, delivery_class="DEFERRED_INCIDENT")
            self.assertEqual(first["event_id"], second["event_id"])
            self.assertEqual(len(outbox.pending()), 1)
            seen = []
            self.assertEqual(outbox.deliver(lambda event: seen.append(dict(event)) or "too-early", channel="test"), [])
            self.assertEqual(seen, [])
            delivered = outbox.deliver(lambda event: seen.append(dict(event)) or "receipt-1", channel="test", eligible_event_ids={first["event_id"]})
            self.assertEqual(delivered, [first["event_id"]])
            self.assertEqual(seen[0]["direction"], "OUTBOUND_ONLY")
            self.assertEqual(seen[0]["control_authority"], "NONE")
            self.assertEqual(outbox.pending(), [])

    def test_attention_coalesces_same_root_cause_across_terminal_kinds(self):
        with tempfile.TemporaryDirectory() as d:
            outbox = AttentionOutbox(Path(d) / "run", project_id="proj", run_id="run")
            first = outbox.publish(kind="DEAD_LETTER", state="BLOCKED", reason="same-root", gate_id="G1")
            second = outbox.publish(kind="BLOCKED", state="BLOCKED", reason="same-root", gate_id="G1")
            self.assertEqual(first["event_id"], second["event_id"])
            self.assertEqual(len(outbox.pending()), 1)
            self.assertEqual(outbox.pending()[0]["kind"], "DEAD_LETTER")

    def test_periodic_reconcile_timer_is_persistent(self):
        text = systemd_user_timer(interval_seconds=60)
        self.assertIn("OnBootSec=30s", text)
        self.assertIn("OnUnitActiveSec=60s", text)
        self.assertIn("Persistent=true", text)
        self.assertIn("global-gpt-harness-full-plan-reconcile.service", text)

    def test_public_gate_run_rejects_unsupervised_full_plan(self):
        rc = cli_main([
            "gate-run", "--project-root", "/tmp/not-used", "--gate-id", "G1", "--run-id", "r",
            "--harness-root", "/tmp", "--mode", "FULL_PLAN", "--requirements-sha256", "a" * 64,
            "--approval-evidence", "/tmp/a", "--branch", "main", "--head", "b" * 40,
            "--requirement-evidence", "/tmp/e",
        ])
        self.assertEqual(rc, 12)

    def test_runtime_link_cannot_retarget_away_from_active_job(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            old = root / "old"; new = root / "new"
            old.mkdir(); new.mkdir()
            subprocess.run(["git", "init", "-q", str(old)], check=True)
            payload = {
                "schema_version": "orchestration.production-full-plan-job.v1",
                "project_root": str(old), "harness_root": str(old),
                "project_id": "proj", "run_id": "active-run", "required_executables": ["git"],
                "gates": [{
                    "gate_id": "G1", "approval_evidence": str(old / "approval.json"),
                    "requirements_sha256": "a" * 64, "branch": "main", "head": "b" * 40,
                    "full_plan_opt_in": True, "project_final_validation": True,
                }],
                "policy": {
                    "retry_budget": 0, "gate_timeout_seconds": 1, "heartbeat_seconds": .03,
                    "lease_seconds": .08, "min_disk_free_bytes": 0, "min_inode_free": 0,
                    "min_memory_available_bytes": 0,
                },
            }
            source = old / "job.json"
            source.write_text(json.dumps(payload), encoding="utf-8")
            register_job(load_job(source))
            link = root / "runtime-current"
            ensure_runtime_link(old, link)
            with self.assertRaisesRegex(FullPlanBootError, "active Full Plan jobs"):
                ensure_runtime_link(new, link)
            self.assertEqual(link.resolve(), old.resolve())

    def test_periodic_reconciler_repairs_missing_terminal_attention(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            subprocess.run(["git", "init", "-q", str(root)], check=True)
            payload = {
                "schema_version": "orchestration.production-full-plan-job.v1",
                "project_root": str(root), "harness_root": str(root),
                "project_id": "proj", "run_id": "repair-run", "required_executables": ["git"],
                "gates": [{
                    "gate_id": "G1", "approval_evidence": str(root / "approval.json"),
                    "requirements_sha256": "a" * 64, "branch": "main", "head": "b" * 40,
                    "full_plan_opt_in": True, "project_final_validation": True,
                }],
                "policy": {
                    "retry_budget": 0, "gate_timeout_seconds": 1, "heartbeat_seconds": .03,
                    "lease_seconds": .08, "min_disk_free_bytes": 0, "min_inode_free": 0,
                    "min_memory_available_bytes": 0,
                },
            }
            source = root / "job.json"
            source.write_text(json.dumps(payload), encoding="utf-8")
            registered = register_job(load_job(source))
            registered_job = load_job(registered)
            sup = DurableFullPlanSupervisor(
                root, project_id="proj", run_id="repair-run", gates=["G1"],
                authority_core_sha256=registered_job["authority_core_sha256"], retry_budget=0,
                gate_timeout_seconds=1, heartbeat_seconds=.03, lease_seconds=.08,
                min_disk_free_bytes=0, min_inode_free=0, min_memory_available_bytes=0,
            )
            state, _ = sup.load()
            state["queue"][0]["status"] = "BLOCKED"
            state["state"] = "BLOCKED"
            state["last_error"] = "SIMULATED_SILENT_BLOCK"
            state["terminal_reason"] = "SIMULATED"
            sup._persist(state, {"event": "SIMULATED_SILENT_BLOCK"})
            self.assertEqual(sup.attention_outbox.pending(), [])
            result = reconcile_job(registered, launch=False)
            self.assertEqual(result["action"], "SKIP_TERMINAL")
            pending = sup.attention_outbox.pending()
            self.assertEqual(len(pending), 1)
            self.assertEqual(pending[0]["kind"], "BLOCKED")
            self.assertEqual(pending[0]["reason"], "SIMULATED_SILENT_BLOCK")



    def test_artifact_contract_failure_never_blindly_retries_and_can_be_explicitly_reopened(self):
        with tempfile.TemporaryDirectory() as d:
            sup = DurableFullPlanSupervisor(
                d, project_id="proj", run_id="artifact-run", gates=["G1"], retry_budget=5,
                gate_timeout_seconds=1, heartbeat_seconds=.03, lease_seconds=.08,
                min_disk_free_bytes=0, min_inode_free=0, min_memory_available_bytes=0,
            )
            def broken(_gate_id, _gate_run_id, _resume):
                raise RuntimeError("EVIDENCE_PUBLICATION_INVALID: worker.request.json missing")
            out = sup.run(broken)
            self.assertEqual(out.status, "BLOCKED")
            self.assertEqual(out.state["terminal_reason"], "ARTIFACT_CONTRACT_RECOVERY_REQUIRED")
            self.assertEqual(out.state["queue"][0]["attempt"], 1)
            self.assertEqual(out.state["dead_letter"][-1]["failure_class"], "ARTIFACT_CONTRACT_FAILURE")
            reopened = sup.resume_recoverable_block()
            self.assertEqual(reopened["state"], "RECOVERING")
            self.assertEqual(reopened["queue"][0]["status"], "READY")
            self.assertTrue(reopened["queue"][0]["resume"])
            self.assertEqual(reopened["queue"][0]["attempt"], 2)


    def test_periodic_reconciler_surfaces_runtime_migration_cancel_orphan_once(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); subprocess.run(['git','init','-q',str(root)],check=True)
            payload={'schema_version':'orchestration.production-full-plan-job.v1','project_root':str(root),'harness_root':str(root),'project_id':'proj','run_id':'migration-orphan','required_executables':['git'],'gates':[{'gate_id':'G1','approval_evidence':str(root/'approval.json'),'requirements_sha256':'a'*64,'branch':'main','head':'b'*40,'full_plan_opt_in':True,'project_final_validation':True}],'policy':{'retry_budget':0,'gate_timeout_seconds':1,'heartbeat_seconds':.03,'lease_seconds':.08,'min_disk_free_bytes':0,'min_inode_free':0,'min_memory_available_bytes':0}}
            source=root/'job.json'; source.write_text(json.dumps(payload)); registered=register_job(load_job(source)); job=load_job(registered)
            sup=DurableFullPlanSupervisor(root,project_id='proj',run_id='migration-orphan',gates=['G1'],authority_core_sha256=job['authority_core_sha256'],retry_budget=0,gate_timeout_seconds=1,heartbeat_seconds=.03,lease_seconds=.08,min_disk_free_bytes=0,min_inode_free=0,min_memory_available_bytes=0)
            sup.cancel('RUNTIME_ACTIVATION_MIGRATION')
            self.assertEqual(sup.attention_outbox.pending(),[])
            first=reconcile_job(registered,launch=False); second=reconcile_job(registered,launch=False)
            self.assertEqual(first['action'],'SKIP_TERMINAL'); self.assertEqual(second['action'],'SKIP_TERMINAL')
            pending=sup.attention_outbox.pending()
            self.assertEqual(len(pending),1); self.assertEqual(pending[0]['kind'],'RUNTIME_MIGRATION_ORPHANED')


    def _migration_job(self, root: Path, run_id: str):
        payload={'schema_version':'orchestration.production-full-plan-job.v1','project_root':str(root),'harness_root':str(root),'project_id':'proj','run_id':run_id,'required_executables':['git'],'gates':[{'gate_id':'G1','approval_evidence':str(root/'approval.json'),'requirements_sha256':'a'*64,'branch':'main','head':'b'*40,'full_plan_opt_in':True,'project_final_validation':True}],'policy':{'retry_budget':0,'gate_timeout_seconds':1,'heartbeat_seconds':.03,'lease_seconds':.08,'min_disk_free_bytes':0,'min_inode_free':0,'min_memory_available_bytes':0}}
        source=root/f'{run_id}.json'; source.write_text(json.dumps(payload)); registered=register_job(load_job(source)); return registered,load_job(registered)

    def test_incomplete_migration_phases_stop_reconcile_and_emit_recovery_attention(self):
        phases=(MigrationPhase.PREPARED,MigrationPhase.PREDECESSOR_QUIESCED,MigrationPhase.RUNTIME_ACTIVATED,MigrationPhase.SUCCESSOR_REGISTERED,MigrationPhase.SUCCESSOR_VERIFIED)
        for target in phases:
            with self.subTest(target=target.value), tempfile.TemporaryDirectory() as d:
                root=Path(d); subprocess.run(['git','init','-q',str(root)],check=True); registered,job=self._migration_job(root,'R2')
                sup=DurableFullPlanSupervisor(root,project_id='proj',run_id='R2',gates=['G1'],authority_core_sha256=job['authority_core_sha256'],**job['policy']); initial,_=sup.load(); initial=sup._persist(initial,{'event':'INIT'})
                store=MigrationStore(root/'_workspace/runtime-migrations/proj'); tx=store.create({'migration_id':'M1','project_id':'proj','predecessor_run_id':'R2','successor_run_id':'R3','current_gate':'G1','resume_gate':'G1','approved_plan_sha256':'a'*64,'approved_spec_sha256':'b'*64,'authority_core_sha256':job['authority_core_sha256'],'predecessor_state_sha256':initial['state_sha256'],'source_head':'c'*40,'target_release_head':'d'*40,'target_manifest_sha256':'e'*64,'successor_job_spec_sha256':'f'*64})
                if target != MigrationPhase.PREPARED:
                    q=sup.quiesce_for_runtime_migration('M1','R3'); tx=store.advance('M1',MigrationPhase.PREDECESSOR_QUIESCED,updates={'quiesced_state_sha256':q['state_sha256']})
                    for phase in (MigrationPhase.RUNTIME_ACTIVATED,MigrationPhase.SUCCESSOR_REGISTERED,MigrationPhase.SUCCESSOR_VERIFIED):
                        if tx.phase==target: break
                        tx=store.advance('M1',phase)
                        if tx.phase==target: break
                result=reconcile_job(registered,launch=False)
                self.assertEqual(result['action'],'MIGRATION_RECOVERY_REQUIRED')
                pending=sup.attention_outbox.pending(); self.assertEqual(len(pending),1); self.assertEqual(pending[0]['kind'],'RUNTIME_MIGRATION_RECOVERY_REQUIRED')

    def test_migrated_terminal_without_registered_successor_is_orphaned(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); subprocess.run(['git','init','-q',str(root)],check=True); registered,job=self._migration_job(root,'R2')
            sup=DurableFullPlanSupervisor(root,project_id='proj',run_id='R2',gates=['G1'],authority_core_sha256=job['authority_core_sha256'],**job['policy']); sup.quiesce_for_runtime_migration('M1','R3'); sup.record_verified_migration_successor('M1','R3','3'*64); sup.close_migrated_predecessor('M1','3'*64)
            reconcile_job(registered,launch=False); pending=sup.attention_outbox.pending(); self.assertEqual(pending[-1]['kind'],'RUNTIME_MIGRATION_ORPHANED')

    def test_migrated_terminal_with_exact_successor_state_is_silent(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); subprocess.run(['git','init','-q',str(root)],check=True); pred_path,pred_job=self._migration_job(root,'R2'); succ_path,succ_job=self._migration_job(root,'R3')
            succ=DurableFullPlanSupervisor(root,project_id='proj',run_id='R3',gates=['G1'],authority_core_sha256=succ_job['authority_core_sha256'],**succ_job['policy']); succ_state,_=succ.load(); succ_state=succ._persist(succ_state,{'event':'SUCCESSOR_DURABLE'})
            pred=DurableFullPlanSupervisor(root,project_id='proj',run_id='R2',gates=['G1'],authority_core_sha256=pred_job['authority_core_sha256'],**pred_job['policy']); pred.quiesce_for_runtime_migration('M1','R3'); pred.record_verified_migration_successor('M1','R3',succ_state['state_sha256']); pred.close_migrated_predecessor('M1',succ_state['state_sha256'])
            result=reconcile_job(pred_path,launch=False); self.assertEqual(result['action'],'SKIP_TERMINAL'); self.assertEqual(pred.attention_outbox.pending(),[])


if __name__ == "__main__":
    unittest.main()
