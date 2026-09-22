# OCPv2 Single Execution Owner Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every registered Full Plan run resolve to exactly one immutable execution owner so OCPv2 and the normal Full Plan reconciler can never execute the same run.

**Architecture:** Add a single owner resolver to the existing immutable production run authority layer. Legacy jobs with no owner resolve to `AUTO_RECONCILE`; OCP-controlled jobs explicitly seal `execution_owner: OCPV2`. Boot/periodic reconciliation, the generic Full Plan runner, and OCP canonical resume each enforce the same resolver before they can acquire execution authority.

**Tech Stack:** Python 3.12, `unittest`, durable JSON authority/state contracts, systemd user transient execution, GitHub Actions OCPv2 R2 CI.

**Spec:** `docs/superpowers/specs/2026-09-22-ocpv2-single-execution-owner-design.md`

## Global Constraints

- Allowed execution owners are exactly `AUTO_RECONCILE` and `OCPV2`.
- Missing `execution_owner` means `AUTO_RECONCILE` and must not rewrite legacy registered job JSON or its authority digest.
- Owner identity is immutable for a registered project/run; changing it requires a new run or governed migration.
- Boot/periodic reconciliation may execute only `AUTO_RECONCILE` jobs.
- OCP canonical resume may execute only `OCPV2` jobs.
- Generic `production_full_plan_entry.run_job()` may execute only `AUTO_RECONCILE` jobs.
- Unknown owner values fail closed; there is no owner fallback.
- No provider/model selection, shell authority, job-registration authority, or direct tool authority is added to OCPv2.
- Existing Gate E recovery/outbox behavior and legacy normal Full Plan behavior must remain green.
- `ACTIVE` remains off until a separate Gate F decision after live single-owner qualification.

## Review Focus

1. **Legacy ownerless registered jobs:** resolving the default must not mutate the job or change its existing authority SHA; pinned in Task 1.
2. **OCP-owned WAIT states:** background reconciliation must skip before typed wait recovery can persist any state transition; pinned in Task 2.
3. **Direct generic-runner bypass:** invoking `run_job()` on an OCP-owned job must fail before the gate executor is called; pinned in Task 2.
4. **OCP bypass in the opposite direction:** canonical OCP resume against an ownerless/AUTO job must fail before continuation-owner claim; pinned in Task 3.
5. **Owner rebind / malformed owner:** same run with a different owner and unknown owner values must fail closed without creating a second authority path; pinned in Tasks 1 and 4.

---

## File Structure

- `runtime/orchestrator/production_run_authority.py` — defines the canonical owner constants and `resolve_execution_owner()`; validates the owner before sealing/validating authority.
- `runtime/orchestrator/production_full_plan_boot.py` — enforces `AUTO_RECONCILE` before supervisor load, wait recovery, or systemd launch; returns `SKIP_EXTERNAL_OWNER` for OCP-owned jobs.
- `runtime/orchestrator/production_full_plan_entry.py` — blocks generic `run_job()` execution of OCP-owned jobs.
- `runtime/orchestrator/ocpv2_canonical_resume.py` — blocks OCP canonical resume unless the registered job is `OCPV2` owned.
- `runtime/orchestrator/live_auto_canary.py` — supports explicit canary owner selection while retaining `AUTO_RECONCILE` as the default.
- `tests/test_ocpv2_single_execution_owner.py` — focused ownership contract and cross-path regression tests.
- `.github/workflows/ocpv2-r2-ci.yml` — adds the new focused test module.

### Task 1: Canonical execution-owner contract and immutability

**Files:**
- Modify: `runtime/orchestrator/production_run_authority.py`
- Create: `tests/test_ocpv2_single_execution_owner.py`

**Interfaces:**
- Produces: `AUTO_RECONCILE_OWNER: str`, `OCPV2_OWNER: str`, `resolve_execution_owner(job: Mapping[str, Any]) -> str`.
- Consumed by: Tasks 2–4.

- [ ] **Step 1: Write RED tests for default, explicit owner, invalid owner, and immutable rebind**

Create `tests/test_ocpv2_single_execution_owner.py` with a minimal registered-job fixture and these assertions:

```python
from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from runtime.orchestrator.production_full_plan_entry import FullPlanJobError, load_job, register_job
from runtime.orchestrator.production_run_authority import (
    AUTO_RECONCILE_OWNER,
    OCPV2_OWNER,
    RunAuthorityError,
    resolve_execution_owner,
)


class OCPv2SingleExecutionOwnerTests(unittest.TestCase):
    def _job(self, root: Path, *, run_id: str = "run", owner: str | None = None) -> dict:
        subprocess.run(["git", "init", "-q", str(root)], check=True)
        payload = {
            "schema_version": "orchestration.production-full-plan-job.v1",
            "project_root": str(root),
            "harness_root": str(root),
            "project_id": "P",
            "run_id": run_id,
            "required_executables": ["git"],
            "gates": [{
                "gate_id": "G1",
                "approval_evidence": str(root / "approval.json"),
                "requirements_sha256": "a" * 64,
                "branch": "main",
                "head": "b" * 40,
                "full_plan_opt_in": True,
                "project_final_validation": True,
            }],
            "policy": {
                "retry_budget": 0,
                "gate_timeout_seconds": 1,
                "heartbeat_seconds": 0.03,
                "lease_seconds": 0.08,
                "min_disk_free_bytes": 0,
                "min_inode_free": 0,
                "min_memory_available_bytes": 0,
            },
        }
        if owner is not None:
            payload["execution_owner"] = owner
        return payload

    def test_ownerless_job_resolves_auto_without_mutation(self):
        job = {"schema_version": "orchestration.production-full-plan-job.v1"}
        before = dict(job)
        self.assertEqual(resolve_execution_owner(job), AUTO_RECONCILE_OWNER)
        self.assertEqual(job, before)

    def test_explicit_ocpv2_owner_resolves(self):
        self.assertEqual(resolve_execution_owner({"execution_owner": "OCPV2"}), OCPV2_OWNER)

    def test_unknown_owner_fails_closed(self):
        with self.assertRaisesRegex(RunAuthorityError, "EXECUTION_OWNER_INVALID"):
            resolve_execution_owner({"execution_owner": "UNKNOWN"})

    def test_same_run_cannot_rebind_execution_owner(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            registered = register_job(self._job(root, owner="AUTO_RECONCILE"))
            self.assertTrue(registered.is_file())
            with self.assertRaisesRegex(FullPlanJobError, "RUN_ID_REBIND_FORBIDDEN"):
                register_job(self._job(root, owner="OCPV2"))
```

- [ ] **Step 2: Run the focused test and confirm RED**

Run:

```bash
python3 -m unittest -v tests.test_ocpv2_single_execution_owner
```

Expected: import failure or missing-symbol failures for the owner constants/resolver.

- [ ] **Step 3: Implement the minimal authority helper**

In `production_run_authority.py` add:

```python
AUTO_RECONCILE_OWNER = "AUTO_RECONCILE"
OCPV2_OWNER = "OCPV2"
EXECUTION_OWNERS = frozenset({AUTO_RECONCILE_OWNER, OCPV2_OWNER})


def resolve_execution_owner(job: Mapping[str, Any]) -> str:
    raw = job.get("execution_owner")
    if raw is None:
        return AUTO_RECONCILE_OWNER
    owner = str(raw)
    if owner not in EXECUTION_OWNERS:
        raise RunAuthorityError("EXECUTION_OWNER_INVALID")
    return owner
```

Call `resolve_execution_owner(job)` at the start of `seal_authority_core()` and `validate_authority_core()` to reject malformed explicit owners without inserting a default field into legacy dictionaries.

- [ ] **Step 4: Run focused tests**

Run:

```bash
python3 -m unittest -v tests.test_ocpv2_single_execution_owner
python3 -m unittest -v tests.test_production_full_plan_boot
```

Expected: new Task 1 tests PASS; existing boot tests remain PASS.

- [ ] **Step 5: Commit**

```bash
git add runtime/orchestrator/production_run_authority.py tests/test_ocpv2_single_execution_owner.py
git commit -m "feat(ocpv2): seal immutable execution owner"
```

### Task 2: Enforce AUTO_RECONCILE on boot and generic runner

**Files:**
- Modify: `runtime/orchestrator/production_full_plan_boot.py`
- Modify: `runtime/orchestrator/production_full_plan_entry.py`
- Modify: `tests/test_ocpv2_single_execution_owner.py`

**Interfaces:**
- Consumes: `resolve_execution_owner()` and owner constants from Task 1.
- Produces: boot action `SKIP_EXTERNAL_OWNER` with `execution_owner`, and generic-runner owner rejection.

- [ ] **Step 1: Add RED tests for READY skip, WAIT no-recovery, legacy resume, and direct runner bypass**

Append tests that register an `OCPV2` job, then assert:

```python
from unittest.mock import patch

from runtime.orchestrator.production_full_plan_boot import reconcile_job
from runtime.orchestrator.production_full_plan_entry import run_job
from runtime.orchestrator.production_full_plan_runner import DurableFullPlanSupervisor


def test_boot_skips_ocpv2_ready_job_before_launch(self):
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        registered = register_job(self._job(root, owner="OCPV2"))
        with patch("runtime.orchestrator.production_full_plan_boot.subprocess.run") as run:
            result = reconcile_job(registered, launch=True)
        self.assertEqual(result["action"], "SKIP_EXTERNAL_OWNER")
        self.assertEqual(result["execution_owner"], "OCPV2")
        self.assertFalse(result["launched"])
        run.assert_not_called()


def test_boot_skips_ocpv2_wait_without_wait_recovery(self):
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        registered = register_job(self._job(root, owner="OCPV2"))
        loaded = load_job(registered)
        sup = DurableFullPlanSupervisor(
            root, project_id="P", run_id="run", gates=["G1"],
            authority_core_sha256=loaded["authority_core_sha256"], **loaded["policy"])
        state, _ = sup.load()
        state["state"] = "WAITING_RESOURCE"
        state["wait_reason"] = "LOW_RESOURCE_BACKPRESSURE"
        before = sup._persist(state, {"event": "TEST_WAIT"})["state_sha256"]
        with patch("runtime.orchestrator.production_full_plan_boot._attempt_typed_wait_recovery") as recovery:
            result = reconcile_job(registered, launch=True)
        self.assertEqual(result["action"], "SKIP_EXTERNAL_OWNER")
        recovery.assert_not_called()
        after, _ = sup.load()
        self.assertEqual(after["state_sha256"], before)


def test_ownerless_boot_behavior_remains_auto_reconcile(self):
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        registered = register_job(self._job(root))
        with patch("runtime.orchestrator.production_full_plan_boot._unit_active", return_value=False):
            result = reconcile_job(registered, launch=False)
        self.assertEqual(result["action"], "WOULD_RESUME")


def test_generic_runner_rejects_ocpv2_owner_before_gate_executor(self):
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        registered = register_job(self._job(root, owner="OCPV2"))
        with patch("runtime.orchestrator.production_full_plan_entry.build_gate_executor") as executor:
            with self.assertRaisesRegex(FullPlanJobError, "EXECUTION_OWNER_MISMATCH"):
                run_job(registered)
        executor.assert_not_called()
```

- [ ] **Step 2: Run and confirm RED**

```bash
python3 -m unittest -v tests.test_ocpv2_single_execution_owner
```

Expected: OCP-owned boot job currently returns `RESUME_REQUESTED`/`WOULD_RESUME`, wait recovery is reachable, and generic runner does not reject owner.

- [ ] **Step 3: Add boot owner gate before supervisor creation**

Immediately after successfully loading a job in `reconcile_job()` resolve owner and return early:

```python
owner = resolve_execution_owner(job)
if owner != AUTO_RECONCILE_OWNER:
    return {
        "job": str(job_path),
        "action": "SKIP_EXTERNAL_OWNER",
        "state": "UNREAD",
        "execution_owner": owner,
        "launched": False,
    }
```

Catch `RunAuthorityError` and return a normal `BLOCKED` result with `launched=False`. Keep `SKIP_EXTERNAL_OWNER` outside `reconcile_all()`'s blocked/failure count.

- [ ] **Step 4: Add generic runner owner gate before supervisor/gate execution**

In `run_job()` after `load_registered_job(canonical)` and before creating `DurableFullPlanSupervisor`:

```python
try:
    owner = resolve_execution_owner(job)
except RunAuthorityError as exc:
    raise FullPlanJobError(str(exc)) from exc
if owner != AUTO_RECONCILE_OWNER:
    raise FullPlanJobError(
        f"EXECUTION_OWNER_MISMATCH: generic Full Plan runner requires {AUTO_RECONCILE_OWNER}"
    )
```

- [ ] **Step 5: Run owner and existing boot tests**

```bash
python3 -m unittest -v tests.test_ocpv2_single_execution_owner
python3 -m unittest -v tests.test_production_full_plan_boot
```

Expected: all PASS; existing ownerless boot tests continue to return `WOULD_RESUME`.

- [ ] **Step 6: Commit**

```bash
git add runtime/orchestrator/production_full_plan_boot.py runtime/orchestrator/production_full_plan_entry.py tests/test_ocpv2_single_execution_owner.py
git commit -m "fix(full-plan): fence external execution owners"
```

### Task 3: Enforce OCPV2 ownership on canonical remote resume

**Files:**
- Modify: `runtime/orchestrator/ocpv2_canonical_resume.py`
- Modify: `tests/test_ocpv2_single_execution_owner.py`
- Verify: `tests/test_ocpv2_registered_full_plan_resume.py`
- Verify: `tests/test_ocpv2_live_recovery_composition.py`

**Interfaces:**
- Consumes: `resolve_execution_owner()` and `OCPV2_OWNER`.
- Produces: canonical OCP fail-closed owner check before source/runtime/state/owner-claim mutation.

- [ ] **Step 1: Add RED test proving OCP refuses ownerless/AUTO job before owner claim**

Create an AUTO job with a durable initial state, capture its state SHA, and call `execute_registered_full_plan_continuation()` with exact bindings. Patch `_persist` or inspect the durable state afterward and require:

```python
with self.assertRaisesRegex(CanonicalRemoteResumeError, "EXECUTION_OWNER_MISMATCH"):
    execute_registered_full_plan_continuation(...exact bindings...)
after = json.loads(state_path.read_text())
self.assertEqual(after["state_sha256"], before_sha)
self.assertIsNone(after.get("continuation_owner"))
```

Use current project head/runtime release and `expected_owner_epoch=1` so the only failing condition is ownership.

- [ ] **Step 2: Run owner test and confirm RED**

```bash
python3 -m unittest -v tests.test_ocpv2_single_execution_owner
```

Expected: AUTO job reaches later canonical checks rather than rejecting on owner.

- [ ] **Step 3: Add canonical owner enforcement immediately after registered-job identity checks**

In `ocpv2_canonical_resume.py` import the owner helper and enforce before source-head/runtime probes or supervisor creation:

```python
try:
    execution_owner = resolve_execution_owner(job)
except RunAuthorityError as exc:
    raise CanonicalRemoteResumeError(str(exc)) from exc
if execution_owner != OCPV2_OWNER:
    raise CanonicalRemoteResumeError(
        f"EXECUTION_OWNER_MISMATCH: OCPv2 requires {OCPV2_OWNER}"
    )
```

- [ ] **Step 4: Update existing OCP-positive fixtures to explicitly seal `execution_owner: OCPV2`**

Any fixture that expects `execute_registered_full_plan_continuation()` to succeed must create/register the job with:

```python
job["execution_owner"] = "OCPV2"
```

Do not weaken negative tests by defaulting OCP ownership globally.

- [ ] **Step 5: Run canonical resume and recovery suites**

```bash
python3 -m unittest -v tests.test_ocpv2_single_execution_owner
python3 -m unittest -v tests.test_ocpv2_registered_full_plan_resume
python3 -m unittest -v tests.test_ocpv2_live_recovery_composition
```

Expected: all PASS; Gate E crash recovery remains unchanged for OCP-owned jobs.

- [ ] **Step 6: Commit**

```bash
git add runtime/orchestrator/ocpv2_canonical_resume.py tests/test_ocpv2_single_execution_owner.py tests/test_ocpv2_registered_full_plan_resume.py tests/test_ocpv2_live_recovery_composition.py
git commit -m "fix(ocpv2): require canonical OCP execution ownership"
```

### Task 4: Make LiveAutoCanary owner-explicit without changing the default behavior

**Files:**
- Modify: `runtime/orchestrator/live_auto_canary.py`
- Modify: `tests/test_ocpv2_single_execution_owner.py`
- Modify as needed: OCP-specific canary/recovery tests that construct `LiveAutoCanary`

**Interfaces:**
- Consumes: owner constants/resolver.
- Produces: `LiveAutoCanary(..., execution_owner: str = AUTO_RECONCILE_OWNER)` and sealed job field `execution_owner`.

- [ ] **Step 1: Add RED tests for canary default and explicit OCP owner**

```python
def test_live_canary_defaults_auto_reconcile_owner(self):
    canary = LiveAutoCanary(state_root, runtime_code_root=runtime_root, run_id="AUTO")
    job = load_job(canary.prepare())
    self.assertEqual(resolve_execution_owner(job), AUTO_RECONCILE_OWNER)


def test_live_canary_can_seal_ocpv2_owner(self):
    canary = LiveAutoCanary(
        state_root,
        runtime_code_root=runtime_root,
        run_id="OCP",
        execution_owner=OCPV2_OWNER,
    )
    job = load_job(canary.prepare())
    self.assertEqual(job["execution_owner"], OCPV2_OWNER)
```

Also add an invalid-constructor owner test requiring `LiveAutoCanaryError` before filesystem mutation.

- [ ] **Step 2: Run and confirm RED**

```bash
python3 -m unittest -v tests.test_ocpv2_single_execution_owner
```

Expected: constructor does not yet accept `execution_owner`.

- [ ] **Step 3: Implement owner parameter and seal it into new canary jobs**

In `LiveAutoCanary.__init__`:

```python
def __init__(..., execution_owner: str = AUTO_RECONCILE_OWNER, ...) -> None:
    try:
        self.execution_owner = resolve_execution_owner({"execution_owner": execution_owner})
    except RunAuthorityError as exc:
        raise LiveAutoCanaryError(str(exc)) from exc
```

In `prepare()` add before `register_job(job)`:

```python
job["execution_owner"] = self.execution_owner
```

OCP qualification tests must pass `execution_owner=OCPV2_OWNER`; generic canary tests may retain the default.

- [ ] **Step 4: Run canary, initial-state, canonical-resume, and recovery tests**

```bash
python3 -m unittest -v tests.test_ocpv2_single_execution_owner
python3 -m unittest -v tests.test_ocpv2_initial_state_materialization
python3 -m unittest -v tests.test_ocpv2_registered_full_plan_resume
python3 -m unittest -v tests.test_ocpv2_live_recovery_composition
```

Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add runtime/orchestrator/live_auto_canary.py tests/test_ocpv2_single_execution_owner.py tests/test_ocpv2_initial_state_materialization.py tests/test_ocpv2_registered_full_plan_resume.py tests/test_ocpv2_live_recovery_composition.py
git commit -m "test(ocpv2): make canary execution owner explicit"
```

### Task 5: CI focus, full regression, and ownership negative-space verification

**Files:**
- Modify: `.github/workflows/ocpv2-r2-ci.yml`
- Verify: `tests/test_ocpv2_authority_negative_space.py`
- Verify: all repository tests

**Interfaces:**
- Consumes: complete ownership implementation from Tasks 1–4.
- Produces: hosted verification evidence for Gate F readiness; no activation.

- [ ] **Step 1: Add the focused ownership suite to CI**

Add next to the other OCP focused suites:

```yaml
- run: python3 -m unittest -v tests.test_ocpv2_single_execution_owner
```

- [ ] **Step 2: Extend authority-negative-space assertions if necessary**

Pin that adding execution ownership does **not** add provider/model/shell/tool selection to OCP. The negative-space test should continue to assert that OCP only reaches the registered-Full-Plan continuation interface and does not import/call provider/tool backends directly.

- [ ] **Step 3: Run local focused verification**

```bash
python3 -m unittest -v \
  tests.test_ocpv2_single_execution_owner \
  tests.test_production_full_plan_boot \
  tests.test_ocpv2_registered_full_plan_resume \
  tests.test_ocpv2_live_recovery_composition \
  tests.test_ocpv2_initial_state_materialization \
  tests.test_ocpv2_runtime_service \
  tests.test_ocpv2_authority_negative_space
python3 -m compileall -q runtime tests deploy/operator-control-plane-v2
git diff --check
```

Expected: all PASS, compileall clean, `git diff --check` clean.

- [ ] **Step 4: Run whole-repository regression**

```bash
python3 scripts/ocpv2_full_regression.py
```

Expected: no new failures/errors.

- [ ] **Step 5: Commit CI change**

```bash
git add .github/workflows/ocpv2-r2-ci.yml tests/test_ocpv2_authority_negative_space.py
git commit -m "ci(ocpv2): focus single execution owner regressions"
```

- [ ] **Step 6: Push and require hosted CI convergence**

Push `impl/operator-control-plane-v2-r2`, then require the latest exact HEAD workflow to show:

```text
focused         PASS
full-regression PASS
regression-delta PASS
```

Do not use a previous commit's CI as evidence for the final HEAD.

### Task 6: Jarvis live single-owner qualification before Gate F

**Files:**
- No source modification expected.
- Evidence is operational on `jarvis-server` and should be summarized on PR #5 after completion.

**Interfaces:**
- Consumes: exact hosted-CI-verified implementation HEAD.
- Produces: live proof that background reconciliation and OCP cannot execute the same OCP-owned run.

- [ ] **Step 1: Redeploy exact verified HEAD in `OBSERVE_ONLY`**

Require exact worktree SHA equality, `OCP_MODE=OBSERVE_ONLY`, `ocpv2.timer=inactive`, and reconciler timer/service inactive before qualification.

- [ ] **Step 2: Create a fresh OCP-owned canary**

Construct:

```python
LiveAutoCanary(
    state_root,
    runtime_code_root=verified_runtime_root,
    run_id=fresh_run_id,
    execution_owner="OCPV2",
)
```

Require durable initial state, stable state SHA, zero receipts, baseline-only project history, and the registered job's `execution_owner == "OCPV2"`.

- [ ] **Step 3: Prove background reconciler cannot claim the OCP-owned job**

Run the reconciler one-shot/dry qualification against the registered job and require:

```text
action=SKIP_EXTERNAL_OWNER
execution_owner=OCPV2
launched=false
CANARY-A receipt absent
project commit count=1
state SHA unchanged
```

- [ ] **Step 4: Run one exact OCP mutation canary**

Issue a fresh control sequence bound to the new state SHA, owner epoch, source HEAD, runtime digest, run/gate/task/task_execution, and exact directive ID. Arm `CONTROL_MUTATION_CANARY` exact scope and require exactly one CANARY-A mutation.

- [ ] **Step 5: Re-run reconciler after OCP mutation**

Require again:

```text
action=SKIP_EXTERNAL_OWNER
launched=false
no CANARY-B/C receipt
no additional commit
```

- [ ] **Step 6: Roll back qualification mode**

Restore:

```text
OCP_MODE=OBSERVE_ONLY
ocpv2.service=inactive
ocpv2.timer=inactive
reconcile.service=inactive
reconcile.timer=inactive
```

Archive/inert the live control directive. Do not enable `ACTIVE`.

- [ ] **Step 7: Record Gate F precondition evidence**

Add a PR #5 evidence comment containing exact implementation SHA, hosted CI run, live run ID, `SKIP_EXTERNAL_OWNER` before and after OCP mutation, receipt/commit counts, rollback status, and the statement `ACTIVE remains unauthorized pending separate Gate F decision`.
