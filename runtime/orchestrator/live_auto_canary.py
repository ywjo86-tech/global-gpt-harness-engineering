"""Harmless production-shape 3-Gate AUTO canary for active runtime qualification."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from .durable_io import atomic_write_json
from .gate_continuation_contract import GateContinuationContract
from .production_run_authority import executor_runtime_identity

CANARY_EXECUTOR_KIND = "DCC_LIVE_AUTO_CANARY"
CANARY_PROJECT_ID = "DCC_LIVE_AUTO_CANARY"
CANARY_GATES = ("CANARY-A", "CANARY-B", "CANARY-C")
PAUSE_ENV = "GCH_LIVE_AUTO_CANARY_PAUSE_AFTER_GATE_A"


class LiveAutoCanaryError(ValueError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _digest(value: object) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _git(root: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(root), *args], capture_output=True, text=True,
        check=False, timeout=20,
    )
    if completed.returncode != 0:
        raise LiveAutoCanaryError("canary Git operation failed")
    return completed.stdout.strip()


def canary_authority_profile() -> dict[str, str]:
    return {
        "network": "DENIED",
        "credentials": "DENIED",
        "packages": "DENIED",
        "external_effect_policy": "NO_EXTERNAL_EFFECT",
        "repository_effect": "BOUNDED_LOCAL_CANARY_COMMIT_ONLY",
    }


def _canary_base(state_root: str | Path, run_id: str) -> Path:
    return Path(state_root).resolve() / "_workspace" / "live-auto-canary" / CANARY_PROJECT_ID / run_id


def _receipt_dir(state_root: str | Path, run_id: str) -> Path:
    return _canary_base(state_root, run_id) / "receipts"


def _receipt_path(state_root: str | Path, run_id: str, gate_id: str) -> Path:
    return _receipt_dir(state_root, run_id) / f"{gate_id}.json"


def _load_receipt(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise LiveAutoCanaryError("canary receipt is unavailable")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise LiveAutoCanaryError("canary receipt is malformed") from exc
    if not isinstance(value, dict) or value.get("schema_version") != "orchestration.live-auto-canary-receipt.v2":
        raise LiveAutoCanaryError("canary receipt schema mismatch")
    expected = str(value.get("receipt_sha256") or "")
    unsigned = {key: item for key, item in value.items() if key != "receipt_sha256"}
    if expected != _digest(unsigned):
        raise LiveAutoCanaryError("canary receipt digest mismatch")
    return value


def build_live_auto_canary_executor(job: Mapping[str, Any]):
    if job.get("executor_kind") != CANARY_EXECUTOR_KIND:
        raise LiveAutoCanaryError("canary executor kind mismatch")
    project = Path(str(job["project_root"])).resolve()
    state_root = Path(str(job.get("harness_state_root") or job["harness_root"])).resolve()
    run_id = str(job["run_id"])
    gates = {str(item["gate_id"]): dict(item) for item in job["gates"]}
    if tuple(gates) != CANARY_GATES:
        raise LiveAutoCanaryError("canary Gate topology mismatch")

    def execute(gate_id: str, gate_run_id: str, resume: bool) -> Mapping[str, Any]:
        del gate_run_id, resume
        if gate_id not in gates:
            raise LiveAutoCanaryError("canary Gate is outside sealed topology")
        receipt_path = _receipt_path(state_root, run_id, gate_id)
        if receipt_path.exists():
            receipt = _load_receipt(receipt_path)
            return {"status": "GATE_EXIT", "receipt_sha256": receipt["receipt_sha256"],
                    "next": {"action": "SYSTEM_TRANSITION", "automatic": True}}

        # Test/live qualification can intentionally strand B in RUNNING after A
        # to prove durable recovery. Pause happens before any B mutation.
        if gate_id != CANARY_GATES[0] and os.environ.get(PAUSE_ENV) == "1":
            while True:
                time.sleep(1.0)

        relative = Path("artifacts") / f"{gate_id}.txt"
        artifact = project / relative
        if artifact.exists():
            raise LiveAutoCanaryError("ambiguous canary artifact exists without receipt")
        if _git(project, "status", "--porcelain=v1", "-uall"):
            raise LiveAutoCanaryError("canary project must be clean before Gate mutation")
        before = _git(project, "rev-parse", "HEAD")
        artifact.parent.mkdir(parents=True, exist_ok=True)
        content = f"{run_id}:{gate_id}\n"
        artifact.write_text(content, encoding="utf-8")
        _git(project, "add", "--", relative.as_posix())
        _git(project, "commit", "-m", f"canary: {gate_id}")
        after = _git(project, "rev-parse", "HEAD")
        contract = GateContinuationContract.from_mapping(gates[gate_id]["continuation_contract"])
        unsigned = {
            "schema_version": "orchestration.live-auto-canary-receipt.v2",
            "project_id": CANARY_PROJECT_ID,
            "run_id": run_id,
            "gate_id": gate_id,
            "continuation_policy": contract.continuation_policy,
            "contract_sha256": contract.contract_sha256,
            "source_head": before,
            "result_head": after,
            "artifact_path": relative.as_posix(),
            "artifact_sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
            "external_effect_policy": "NO_EXTERNAL_EFFECT",
            "external_effects": [],
            "provider_calls": 0,
            "network_calls": 0,
            "created_at": _now(),
        }
        receipt = {**unsigned, "receipt_sha256": _digest(unsigned)}
        atomic_write_json(receipt_path, receipt)
        return {"status": "GATE_EXIT", "receipt_sha256": receipt["receipt_sha256"],
                "next": {"action": "SYSTEM_TRANSITION", "automatic": True}}

    return execute


class LiveAutoCanary:
    def __init__(self, state_root: str | Path, *, runtime_code_root: str | Path,
                 run_id: str, python_executable: str | Path | None = None) -> None:
        self.state_root = Path(state_root).resolve()
        self.runtime_code_root = Path(runtime_code_root).resolve()
        self.run_id = str(run_id)
        if not self.state_root.is_dir() or self.state_root.is_symlink():
            raise LiveAutoCanaryError("stable canary state root is unsafe")
        if not self.runtime_code_root.is_dir():
            raise LiveAutoCanaryError("canary runtime code root is unavailable")
        if not self.run_id or "/" in self.run_id or ".." in self.run_id:
            raise LiveAutoCanaryError("canary run ID is unsafe")
        self.python_executable = Path(python_executable or sys.executable).resolve()
        self.base = _canary_base(self.state_root, self.run_id)
        self.project_root = self.base / "project"
        self.requested_job_path = self.base / "requested.job.json"
        self.evidence_path = self.base / "qualification-evidence.json"
        self.drop_path = self.base / "foreground-owner-drop.json"
        self.canonical_job_path: Path | None = None

    @property
    def state_path(self) -> Path:
        return (self.state_root / "_workspace" / "production-full-plan" / CANARY_PROJECT_ID
                / self.run_id / "state.json")

    def _contract(self, gate_id: str, base_head: str) -> dict[str, Any]:
        raw = {
            "schema_version": "orchestration.gate-continuation-contract.v1",
            "gate_id": gate_id,
            "continuation_policy": "AUTO_WITHIN_APPROVED_CONTRACT",
            "approved_base_head": base_head,
            "source_lineage_policy": "APPROVED_DESCENDANT_CHAIN",
            "allowed_write_paths": [f"artifacts/{gate_id}.txt"],
            "forbidden_paths": [".git/", "runtime/", "scripts/", "credentials/"],
            "required_verifiers": ["CANARY_LOCAL_RECEIPT"],
            "required_evidence_classes": ["CANARY_RECEIPT"],
            "commit_policy": "LOCAL_COMMIT_ALLOWED",
            "risk_classes": ["REPOSITORY_WRITE"],
            "approval_coverage_ref": "workstream-d-user-approval://2026-09-21",
            "approval_coverage_digest": _digest({"scope": "DCC_LIVE_AUTO_CANARY", "approved": True}),
            "external_effect_policy": "NO_EXTERNAL_EFFECT",
            "runtime_migration_policy": "NO_RUNTIME_MIGRATION",
        }
        return GateContinuationContract.from_mapping(raw).canonical_projection()

    def prepare(self) -> Path:
        from .production_full_plan_entry import register_job
        if self.base.exists():
            if self.canonical_job_path and self.canonical_job_path.is_file():
                return self.canonical_job_path
            raise LiveAutoCanaryError("canary run namespace already exists")
        self.project_root.mkdir(parents=True)
        subprocess.run(["git", "init", "-q", str(self.project_root)], check=True)
        subprocess.run(["git", "-C", str(self.project_root), "config", "user.email", "canary@local.invalid"], check=True)
        subprocess.run(["git", "-C", str(self.project_root), "config", "user.name", "DCC Live Canary"], check=True)
        (self.project_root / "README.md").write_text("DCC live AUTO canary\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(self.project_root), "add", "."], check=True)
        subprocess.run(["git", "-C", str(self.project_root), "commit", "-qm", "canary baseline"], check=True)
        base_head = _git(self.project_root, "rev-parse", "HEAD")
        branch = _git(self.project_root, "branch", "--show-current")
        common = Path(_git(self.project_root, "rev-parse", "--git-common-dir"))
        if not common.is_absolute():
            common = (self.project_root / common).resolve()
        approval = self.base / "approval.json"
        atomic_write_json(approval, {"scope": "DCC_LIVE_AUTO_CANARY", "approved": True, "external_effects": "NONE"})
        gates = []
        for gate_id in CANARY_GATES:
            contract = self._contract(gate_id, base_head)
            gates.append({
                "gate_id": gate_id,
                "approval_evidence": str(approval),
                "requirements_sha256": _digest(contract),
                "branch": branch,
                "head": base_head,
                "full_plan_opt_in": True,
                "project_final_validation": True,
                "continuation_contract": contract,
            })
        job = {
            "schema_version": "orchestration.production-full-plan-job.v1",
            "executor_kind": CANARY_EXECUTOR_KIND,
            "project_root": str(self.project_root),
            "harness_root": str(self.state_root),
            "harness_state_root": str(self.state_root),
            "runtime_code_root": str(self.runtime_code_root),
            "project_id": CANARY_PROJECT_ID,
            "run_id": self.run_id,
            "git_common_dir": str(common),
            "expected_branch": branch,
            "gates": gates,
            "required_executables": ["git"],
            "python_executable": str(self.python_executable),
            "executor_runtime_identity": executor_runtime_identity(self.runtime_code_root),
            "policy": {
                "retry_budget": 0, "gate_timeout_seconds": 120,
                "heartbeat_seconds": 0.2, "lease_seconds": 1.0,
                "stall_alert_seconds": 30, "min_disk_free_bytes": 0,
                "min_inode_free": 0, "min_memory_available_bytes": 0,
            },
        }
        atomic_write_json(self.requested_job_path, job)
        self.canonical_job_path = register_job(job)
        return self.canonical_job_path

    def load_state(self) -> dict[str, Any]:
        if self.state_path.is_symlink() or not self.state_path.is_file():
            raise LiveAutoCanaryError("canary durable state is unavailable")
        value = json.loads(self.state_path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise LiveAutoCanaryError("canary durable state is malformed")
        return value

    def load_receipts(self) -> list[dict[str, Any]]:
        rows = []
        for gate_id in CANARY_GATES:
            path = _receipt_path(self.state_root, self.run_id, gate_id)
            if path.exists():
                rows.append(_load_receipt(path))
        return rows

    def run_gate_a_then_drop_foreground_owner(self, *, timeout_seconds: float = 30) -> dict[str, Any]:
        job_path = self.canonical_job_path or self.prepare()
        env = dict(os.environ); env[PAUSE_ENV] = "1"
        process = subprocess.Popen(
            [str(self.python_executable), "-m", "runtime.orchestrator.production_full_plan_entry", "--job", str(job_path)],
            cwd=self.runtime_code_root, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        deadline = time.monotonic() + timeout_seconds
        observed = False
        while time.monotonic() < deadline:
            try:
                receipts = self.load_receipts()
                state = self.load_state()
            except LiveAutoCanaryError:
                time.sleep(0.05); continue
            if ([row["gate_id"] for row in receipts] == [CANARY_GATES[0]]
                    and state.get("current_gate") == CANARY_GATES[1]
                    and state.get("state") in {"DISPATCHED", "RUNNING"}):
                observed = True; break
            if process.poll() is not None:
                break
            time.sleep(0.05)
        if not observed:
            process.terminate(); process.wait(timeout=5)
            raise LiveAutoCanaryError("foreground canary did not reach post-Gate-A loss point")
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill(); process.wait(timeout=5)
        marker = {
            "schema_version": "orchestration.live-auto-canary-owner-loss.v1",
            "project_id": CANARY_PROJECT_ID, "run_id": self.run_id,
            "foreground_pid": process.pid, "foreground_owner_dropped": True,
            "completed_receipts": [CANARY_GATES[0]], "dropped_at": _now(),
        }
        marker["marker_sha256"] = _digest(marker)
        atomic_write_json(self.drop_path, marker)
        return marker

    def reconcile_until_idle(self, *, use_systemd: bool, timeout_seconds: float = 60) -> dict[str, Any]:
        job_path = self.canonical_job_path
        if job_path is None:
            raise LiveAutoCanaryError("canary is not prepared")
        if use_systemd:
            from .production_full_plan_boot import reconcile_job
            outcome = reconcile_job(job_path, launch=True)
            if outcome.get("action") not in {"RESUME_REQUESTED", "ALREADY_ACTIVE"}:
                raise LiveAutoCanaryError(f"systemd reconciler did not resume canary: {outcome}")
        else:
            from .production_full_plan_entry import run_job
            outcome = run_job(job_path)
            if outcome.get("status") != "COMPLETED":
                raise LiveAutoCanaryError(f"direct test reconciler did not complete canary: {outcome}")
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            state = self.load_state()
            if state.get("state") in {"COMPLETED", "BLOCKED", "FAILED", "CANCELLED"}:
                if state.get("state") != "COMPLETED":
                    raise LiveAutoCanaryError(f"canary reached non-success terminal state: {state.get('state')}")
                return {"state": state["state"], "terminal_reason": state.get("terminal_reason"), "outcome": outcome}
            time.sleep(0.1)
        raise LiveAutoCanaryError("canary reconciliation timed out")

    def seal_evidence(self, *, reconciler_mode: str) -> dict[str, Any]:
        state = self.load_state()
        receipts = self.load_receipts()
        if state.get("state") != "COMPLETED" or len(receipts) != len(CANARY_GATES):
            raise LiveAutoCanaryError("canary is not complete")
        drop = json.loads(self.drop_path.read_text(encoding="utf-8"))
        unsigned = {
            "schema_version": "orchestration.live-auto-canary-qualification.v1",
            "project_id": CANARY_PROJECT_ID,
            "run_id": self.run_id,
            "state": state.get("state"),
            "terminal_reason": state.get("terminal_reason"),
            "final_state_sha256": state.get("state_sha256"),
            "receipt_count": len(receipts),
            "receipt_sha256s": [row["receipt_sha256"] for row in receipts],
            "commit_heads": [row["result_head"] for row in receipts],
            "foreground_owner_dropped": bool(drop.get("foreground_owner_dropped")),
            "chat_resume_count": 0,
            "reconciler_mode": str(reconciler_mode),
            "external_effect_count": sum(len(row.get("external_effects", [])) for row in receipts),
            "network_call_count": sum(int(row.get("network_calls", 0)) for row in receipts),
            "provider_call_count": sum(int(row.get("provider_calls", 0)) for row in receipts),
            "authority_profile": canary_authority_profile(),
            "sealed_at": _now(),
        }
        evidence = {**unsigned, "evidence_sha256": _digest(unsigned)}
        atomic_write_json(self.evidence_path, evidence)
        return evidence

    def load_evidence(self) -> dict[str, Any]:
        value = json.loads(self.evidence_path.read_text(encoding="utf-8"))
        expected = value.get("evidence_sha256")
        unsigned = {key: item for key, item in value.items() if key != "evidence_sha256"}
        if expected != _digest(unsigned):
            raise LiveAutoCanaryError("canary qualification evidence digest mismatch")
        return value

    def cleanup_project_workspace(self) -> None:
        if self.project_root.exists():
            shutil.rmtree(self.project_root)
