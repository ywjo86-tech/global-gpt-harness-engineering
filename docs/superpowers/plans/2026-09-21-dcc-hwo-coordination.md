# DCC Harness-Wide Remediation Coordination Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Coordinate the four approved remediation workstreams so all sixteen Harness-wide findings close without weakening existing authority boundaries.

**Architecture:** Use one coordination plan plus four bounded subplans. Workstream C Task C0 establishes stable state first; A builds continuation core; B closes wait/operator/attention gaps; C completes effect/locking/retention; D runs only after A-C integration EDP is green and publication effects are separately approved.

**Tech Stack:** Python 3.12, stdlib, Git, unittest, existing Global GPT Harness orchestration/runtime infrastructure.

**Spec:** `docs/superpowers/specs/2026-09-21-dcc-harness-wide-operational-remediation-design.md`
**Parent Spec:** `docs/superpowers/specs/2026-09-20-durable-continuation-controller-design.md`
**Approved Spec SHA256:** `6a46268f1b0b4a7e23b5be62642bbe8973d2ad6dd9f17534a0032aac56edad03`
**Plan Status:** REVIEWED-CANDIDATE / EXECUTION-APPROVAL-PENDING

## Global Constraints

- Stable executable predecessor is `a40626c31353f90c0d4c9e677d3886ea5ccce393` until an explicitly approved runtime migration occurs.
- `project_root`, immutable `runtime_code_root`, and durable `harness_state_root` are distinct bindings.
- Full Plan remains sole Task/Gate/fan-in/next-state authority; DCC/wait recovery/Attention/checkpoints gain no alternate authority.
- Router/MPRF remains provider selection/runtime-fact authority; Full MCP remains effect authority; RuntimeMigrationTransaction remains runtime activation authority.
- `GATE_BY_GATE` and genuine `WAITING_APPROVAL` boundaries never auto-resume.
- Legacy jobs/receipts/state/migrations remain readable/manual and never acquire AUTO by inference.
- Every source task uses RED -> minimal GREEN -> focused regression -> adjacent authority regression -> local commit.
- Push, runtime activation, live notification transport, credentials, network effects, and publication remain explicit effect boundaries.
- Owns: HWO-MUST-001~020 / HWO-AC-001~015 coordination.

## Review Focus

1. No subplan may assume a schema/owner implemented only by a later dependency.
2. Stable state-root introduction must not rewrite legacy `_workspace` evidence.
3. Provider/resource recovery must never become generic WAITING_RESOURCE resume.
4. Active-runtime qualification must preserve a legal reverse-activation window.
5. Operator turn loss must always leave durable autonomous ownership or a handoff checkpoint plus notification path.

---

## Plan Set

- `2026-09-21-dcc-hwo-a-continuation-core-authority.md`
- `2026-09-21-dcc-hwo-b-wait-operator-attention.md`
- `2026-09-21-dcc-hwo-c-evidence-effects-persistence.md`
- `2026-09-21-dcc-hwo-d-publication-rollback-qualification.md`

## Dependency Order

```text
C0 stable-state foundation
 -> A continuation core
 -> B wait/operator/attention
 -> C1-C4 effects/locks/retention
 -> A+B+C integration EDP
 -> D publication/rollback/live qualification
 -> final Harness-wide EDP ALL_PASS
```

### Task 0: Execution Baseline and Authority Seal

**Requirements:** HWO-MUST-001,017,018.

**Files:**
- Read Amendment/parent Spec/current EDP evidence
- No production file mutation

**Interfaces:**
- Consumes: approved Amendment and clean design lineage
- Produces: exact execution authority digest set and three-root run inputs

- [ ] **Step 1: Write failing tests**

```bash
# Coordination gate: execute the owning subplan RED tests named in this Task,
# and require at least one intended RED failure before production implementation.
python3 -m unittest -q tests.test_production_full_plan_entry || true
```
The coordination gate does not invent duplicate test code; the exact RED assertions live in the owning subplan and must be linked in the execution receipt.

- [ ] **Step 2: Run RED verification**

```bash
python3 -m unittest -q tests.test_production_full_plan_entry tests.test_operator_plan_execution tests.test_runtime_migration_handoff
```
Expected: at least the new behavior tests fail for the intended missing contract/implementation.

- [ ] **Step 3: Implement the minimal approved behavior**

Bind the future implementation run to mutable project worktree + immutable `a40626c31353f90c0d4c9e677d3886ea5ccce393` runtime release + `${GCH_STATE_ROOT:-${XDG_STATE_HOME:-$HOME/.local/state}/global-gpt-harness}`. Do not register/launch until execution approval.

- [ ] **Step 4: Run focused + adjacent-authority GREEN verification**

```bash
python3 -m unittest -q tests.test_production_full_plan_entry tests.test_operator_plan_execution tests.test_runtime_migration_authority_negative_space
```
Expected: PASS with no authority-boundary relaxation.

- [ ] **Step 5: Commit**

```bash
git status --short --branch && git diff --check
```

---

### Task 1: C0 Stable-State Foundation Gate

**Requirements:** HWO-MUST-001,013,017.

**Files:**
- Execute Workstream C Task C0 only

**Interfaces:**
- Consumes: coordination Task 0
- Produces: stable state-root foundation commit/tree SHA

- [ ] **Step 1: Write failing tests**

```bash
# Coordination gate: execute the owning subplan RED tests named in this Task,
# and require at least one intended RED failure before production implementation.
python3 -m unittest -q tests.test_production_full_plan_entry || true
```
The coordination gate does not invent duplicate test code; the exact RED assertions live in the owning subplan and must be linked in the execution receipt.

- [ ] **Step 2: Run RED verification**

```bash
python3 -m unittest -q tests.test_harness_state_root
```
Expected: at least the new behavior tests fail for the intended missing contract/implementation.

- [ ] **Step 3: Implement the minimal approved behavior**

Execute C0 only, stop if legacy discovery or state-root negative tests fail.

- [ ] **Step 4: Run focused + adjacent-authority GREEN verification**

```bash
python3 -m unittest -q tests.test_harness_state_root tests.test_production_full_plan_boot tests.test_production_attention_watch
```
Expected: PASS with no authority-boundary relaxation.

- [ ] **Step 5: Commit**

```bash
git log -1 --oneline && git status --short
```

---

### Task 2: Workstream A Integration Gate

**Requirements:** HWO-MUST-001~007.

**Files:**
- Execute Workstream A A0-A4

**Interfaces:**
- Consumes: C0 stable-root foundation
- Produces: exact AUTO authority, lineage, receipt v2, transaction, DCC core

- [ ] **Step 1: Write failing tests**

```bash
# Coordination gate: execute the owning subplan RED tests named in this Task,
# and require at least one intended RED failure before production implementation.
python3 -m unittest -q tests.test_production_full_plan_entry || true
```
The coordination gate does not invent duplicate test code; the exact RED assertions live in the owning subplan and must be linked in the execution receipt.

- [ ] **Step 2: Run RED verification**

```bash
python3 -m unittest -q tests.test_gate_continuation_contract tests.test_operator_plan_execution
```
Expected: at least the new behavior tests fail for the intended missing contract/implementation.

- [ ] **Step 3: Implement the minimal approved behavior**

Execute A0-A4 in order with per-task TDD and commits.

- [ ] **Step 4: Run focused + adjacent-authority GREEN verification**

```bash
python3 -m unittest -q tests.test_durable_continuation tests.test_production_full_plan_runner tests.test_runtime_migration_authority_negative_space
```
Expected: PASS with no authority-boundary relaxation.

- [ ] **Step 5: Commit**

```bash
git status --short && git log -5 --oneline
```

---

### Task 3: Workstream B Integration Gate

**Requirements:** HWO-MUST-008~011,019.

**Files:**
- Execute Workstream B B0-B4

**Interfaces:**
- Consumes: A integration + C0 stable root
- Produces: typed wait recovery, safe-yield checkpoints, Attention delivery/supersession

- [ ] **Step 1: Write failing tests**

```bash
# Coordination gate: execute the owning subplan RED tests named in this Task,
# and require at least one intended RED failure before production implementation.
python3 -m unittest -q tests.test_production_full_plan_entry || true
```
The coordination gate does not invent duplicate test code; the exact RED assertions live in the owning subplan and must be linked in the execution receipt.

- [ ] **Step 2: Run RED verification**

```bash
python3 -m unittest -q tests.test_user_interaction_policy tests.test_operator_exit_guard tests.test_production_attention_watch
```
Expected: at least the new behavior tests fail for the intended missing contract/implementation.

- [ ] **Step 3: Implement the minimal approved behavior**

Execute B0-B4; use capture delivery only unless live transport has separate approval.

- [ ] **Step 4: Run focused + adjacent-authority GREEN verification**

```bash
python3 -m unittest -q tests.test_full_plan_wait_recovery tests.test_operator_turn_checkpoint tests.test_attention_delivery tests.test_attention_supersession
```
Expected: PASS with no authority-boundary relaxation.

- [ ] **Step 5: Commit**

```bash
git status --short && git log -5 --oneline
```

---

### Task 4: Finish Workstream C and A-C Integration EDP

**Requirements:** HWO-MUST-012~014,017~018,020.

**Files:**
- Execute Workstream C C1-C4
- Create pre-publication Harness-wide EDP evidence

**Interfaces:**
- Consumes: A+B+C0
- Produces: effect reconciliation, lock hierarchy, retention, negative-space and D eligibility decision

- [ ] **Step 1: Write failing tests**

```bash
# Coordination gate: execute the owning subplan RED tests named in this Task,
# and require at least one intended RED failure before production implementation.
python3 -m unittest -q tests.test_production_full_plan_entry || true
```
The coordination gate does not invent duplicate test code; the exact RED assertions live in the owning subplan and must be linked in the execution receipt.

- [ ] **Step 2: Run RED verification**

```bash
python3 -m unittest -q tests.test_effect_evidence_bridge tests.test_runtime_migration_authority_negative_space
```
Expected: at least the new behavior tests fail for the intended missing contract/implementation.

- [ ] **Step 3: Implement the minimal approved behavior**

Complete C1-C4, run cross-domain/full regression, then EDP. D remains blocked unless `BLOCKER=0`, `MAJOR=0`, HWO MUST 20/20 and AC 15/15.

- [ ] **Step 4: Run focused + adjacent-authority GREEN verification**

```bash
python3 -m unittest discover -s tests -p 'test*.py' && python3 -m compileall -q runtime tests && git diff --check
```
Expected: PASS with no authority-boundary relaxation.

- [ ] **Step 5: Commit**

```bash
git status --short && git log -8 --oneline
```

---

### Task 5: Workstream D Effect-Boundary Handoff

**Requirements:** HWO-MUST-007,015,016,020.

**Files:**
- Execute Workstream D only after separate publication approval

**Interfaces:**
- Consumes: A-C ALL PASS pre-publication EDP
- Produces: migration-v2, reverse activation, live AUTO canary, final EDP

- [ ] **Step 1: Write failing tests**

```bash
# Coordination gate: execute the owning subplan RED tests named in this Task,
# and require at least one intended RED failure before production implementation.
python3 -m unittest -q tests.test_production_full_plan_entry || true
```
The coordination gate does not invent duplicate test code; the exact RED assertions live in the owning subplan and must be linked in the execution receipt.

- [ ] **Step 2: Run RED verification**

```bash
python3 -m unittest -q tests.test_runtime_release tests.test_runtime_migration_handoff
```
Expected: at least the new behavior tests fail for the intended missing contract/implementation.

- [ ] **Step 3: Implement the minimal approved behavior**

Do not push/activate/install/configure live notification transport without the exact separate approval. After approval execute D0-D4.

- [ ] **Step 4: Run focused + adjacent-authority GREEN verification**

```bash
python3 -m unittest -q tests.test_runtime_release tests.test_runtime_migration_handoff tests.test_runtime_migration_authority_negative_space
```
Expected: PASS with no authority-boundary relaxation.

- [ ] **Step 5: Commit**

```bash
git status --short
```

---


## Shared Test Fixture Contract

All `fixture_*` names in subplan RED examples are **test-local deterministic helpers**, not production APIs. They are implemented in `tests/helpers/dcc_hwo_fixtures.py` during the first owning source task and reused only by tests. They may create temporary Git repos/state roots, but they must never reach network, production runtime-current, or user systemd.

| Helper | Deterministic result |
|---|---|
| `fixture_registered_three_root_job()` | temp mutable project, immutable fixture runtime release, stable state root, registered job + sealed runtime identity |
| `fixture_commit_project_change(project, name)` | one local project-only commit; runtime/state roots untouched |
| `fixture_auto_contract_mapping(gate_id)` | exact 15-field AUTO GateContinuationContract mapping |
| `fixture_repo_with_linear_commits()` | temp Git repo + base/child commit SHAs |
| `fixture_descendant_contract(approved_base_head)` | APPROVED_DESCENDANT_CHAIN contract for temp repo |
| `fixture_unrelated_commit(repo)` | non-descendant commit SHA for negative lineage tests |
| `fixture_v2_receipt(source_head)` / `fixture_v2_receipt_bindings()` | immutable v2 receipt fixture bound to supplied source lineage |
| `fixture_verified_attestation()` | valid deterministic attestation with fixed authority/contract/tree/evidence digests |
| `fixture_operator_receipt_store()` | receipt store rooted below temporary stable state root |
| `fixture_state(state, reason)` / `fixture_wait_state(reason)` | digest-valid Full Plan state with exact typed wait reason |
| `fixture_auto_context()` | valid AUTO contract + authority/attestation transaction context |
| `fixture_provider_wait_with_sealed_request()` | WAITING_PROVIDER state + original Router request/eligibility/output digests |
| `fixture_fresh_mprf_health()` | fresh HEALTHY MPRF facts only; no provider decision |
| `fixture_checkpoint_fields()` | complete evidence-only OperatorTurnCheckpoint fields |
| `fixture_r2_eligible_attention_event(event_id)` | R2-eligible outbound Attention event with fixed event ID |
| `fixture_terminal_pending_event(created_at)` | terminal historical pending Attention event |
| `fixture_unrelated_newer_run(created_at)` | newer run with different authority lineage |
| `fixture_begun_effect_without_receipt()` | ToolEffectJournal intent with no receipt + matching contract/scope |
| `fixture_contending_continuation_owners()` | supervisor + stale/current owner candidates for fencing tests |
| `fixture_new_run_with_all_durable_evidence(tmp_path)` | stable-root run/state/receipt/attention/transaction plus disposable project worktree |
| `fixture_remove_project_worktree(project_root)` | removes only disposable temp project tree after safety assertion |
| `fixture_docs_only_closure_repo()` | repo with validated code head and docs-only closure head |
| `fixture_commit_change(repo, path, content)` | one specified local commit and resulting SHA |
| `fixture_migration_v2_store_at_successor_verified()` | MigrationStore + migration-v2 at SUCCESSOR_VERIFIED for phase-transition tests |
| `fixture_migration_v2_at_successor_verified()` | supervisor + migration-v2 at SUCCESSOR_VERIFIED + successor state SHA |
| `fixture_active_target_with_quiesced_migration(tmp_path)` | source/target manifests, active target link, exact quiesced migration-v2 |
| `fixture_three_gate_auto_canary()` | isolated three-Gate AUTO canary harness with fake periodic reconciler driver |

The helper module itself is covered by `python3 -m compileall -q tests/helpers` and contains no production authority.

## Requirements-to-Plan Traceability

| HWO requirement | Owning plan/task |
|---|---|
| HWO-MUST-001 | C0, A0 |
| HWO-MUST-002 | A1 |
| HWO-MUST-003 | A1 |
| HWO-MUST-004 | A2 |
| HWO-MUST-005 | B0, A3/A4 |
| HWO-MUST-006 | A3 |
| HWO-MUST-007 | A2, D0, D4 |
| HWO-MUST-008 | B2 |
| HWO-MUST-009 | B3 |
| HWO-MUST-010 | B4 |
| HWO-MUST-011 | B0, B1 |
| HWO-MUST-012 | C1 |
| HWO-MUST-013 | C0, C3 |
| HWO-MUST-014 | C2 |
| HWO-MUST-015 | D1, D2, D4 |
| HWO-MUST-016 | D3, D4 |
| HWO-MUST-017 | C0, C3, A0/A1/A3, D1 |
| HWO-MUST-018 | C4 plus authority-negative tests in A/B/D |
| HWO-MUST-019 | B3, D4 deployment boundary |
| HWO-MUST-020 | Coordination Tasks 4-5, D4 |

### Original DCC requirement preservation

| Original requirement | New owning task(s) |
|---|---|
| DCC-MUST-001 | A4, C4 |
| DCC-MUST-002 | A1, A4 |
| DCC-MUST-003 | A1, A3, C0 |
| DCC-MUST-004 | A1, A2 |
| DCC-MUST-005 | A1, A2 |
| DCC-MUST-006 | A2, A3 |
| DCC-MUST-007 | C4 |
| DCC-MUST-008 | A3, A4 |
| DCC-MUST-009 | A2, C1 |
| DCC-MUST-010 | A2 |
| DCC-MUST-011 | B0 |
| DCC-MUST-012 | B0, B1 |
| DCC-MUST-013 | C2 |
| DCC-MUST-014 | D1, D2, C4 |
| DCC-MUST-015 | A4, B1, C1 |
| DCC-MUST-016 | C1, C4, D4 |
| DCC-MUST-017 | C1 |
| DCC-MUST-018 | B1, B3, C4 |
| DCC-MUST-019 | C0, A1, A3, D1 |
| DCC-MUST-020 | Coordination Tasks 4-5, D4 |

## Acceptance-to-Plan Traceability

| Acceptance | Owning plan/task |
|---|---|
| HWO-AC-001 | A0 + multi-commit integration fixture |
| HWO-AC-002 | A1 |
| HWO-AC-003 | A2 |
| HWO-AC-004 | B0, B1 |
| HWO-AC-005 | B2 + A4 recovery fixture |
| HWO-AC-006 | B3, B4 |
| HWO-AC-007 | C1 |
| HWO-AC-008 | C0, C3 |
| HWO-AC-009 | C2 |
| HWO-AC-010 | D0 |
| HWO-AC-011 | D1, D2, D4 rollback injection |
| HWO-AC-012 | D3, D4 live canary |
| HWO-AC-013 | C0, A1, A3, D1 legacy fixtures |
| HWO-AC-014 | C4 + adjacent authority regressions |
| HWO-AC-015 | Coordination Task 4, D4 final EDP |

## Finding Closure Ownership

| Finding | Planned closure |
|---|---|
| DCC-ORCH-F001 | C0 + A0 |
| DCC-ORCH-F002 | A1 |
| DCC-ORCH-F003 | A1 |
| DCC-ORCH-F004 | A2 |
| DCC-ORCH-F005 | B0 + A3 |
| DCC-ORCH-F006 | A3 |
| DCC-ORCH-F007 | D0 |
| DCC-HW-F008 | B2 |
| DCC-HW-F009 | B3 |
| DCC-HW-F010 | B4 |
| DCC-HW-F011 | B0 + B1 |
| DCC-HW-F012 | C1 |
| DCC-HW-F013 | C0 + C3 |
| DCC-HW-F014 | C2 |
| DCC-HW-F015 | D1 + D2 + D4 |
| DCC-HW-F016 | D3 + D4 |

## Execution Gate Policy

- This plan set is written and self-reviewed, but implementation execution remains `EXECUTION-APPROVAL-PENDING` until the user reviews the plan set.
- Workstreams A-C may run only under the subsequently approved implementation Full Plan authority.
- Workstream D has a second explicit effect gate for push/runtime-current/systemd/live-notification operations.
- Any material Spec/Amendment change, new risk class, or authority expansion stops for Plan revision/user decision.
