# G-4A-ACTUAL Readiness Plan

> Status: **PREPARATION ONLY**
>
> Prepared: `2026-09-10`
>
> Entry basis: G-ORCH-01 `GO`, G-ORCH-02 `GO`, and G-ORCH-03 `GO`

## 1. Purpose

This plan defines the remaining preparation work before proof97 or any live actual proof
may run. It is not an authorization to execute live Codex, actual Broker WRITE, product
mutation, deployment, commit, push, or proof97.

## 2. Current Verified Baseline

- G-ORCH-01 focused verification: 36 PASS / 0 skipped.
- G-ORCH-02 focused verification: 97 PASS / 0 skipped.
- G-ORCH-03 focused verification: 260 PASS / 4 skipped.
- latest full local regression after Gate document updates: 1,060 PASS / 3 skipped.

## 3. Remaining Preconditions Before Actual Proof

The following items must be satisfied before proof97 can move out of `HOLD`:

- fresh live `CodexAuthReadinessEvidence=READY`, collected adjacent to proof execution.
- immutable proof fixture with exact run identity, package, task, owned-file scope,
  expected mutation, verifier, crash point, and resume expectations.
- installed Codex broker path evidence, including actual or equivalent AF_UNIX transport
  evidence in an environment that permits it.
- actual Broker WRITE evidence with bounded Intent/Receipt projection and no raw secret
  retention.
- product-owned frozen test node execution.
- expected crash and same `RUN_ID` resume evidence.
- duplicate Worker/effect/checkpoint prevention evidence after resume.
- independent actual verifier evidence.
- `ISSUE-025` actual-security plan or disposition accepted by the relevant Gate reviewer.
- Safety Warning Protocol approval for dangerous/live proof work.

## 4. Issue Status Entering G-4A

- `ISSUE-025`: Critical/Open; local G-ORCH-03 security subcause satisfied, actual-security
  proof still required.
- `ISSUE-059`: open pending actual mutation/completion evidence.
- `ISSUE-060`: open pending actual proof evidence.
- `ISSUE-063`: open pending actual bounded output/effect proof.
- `ISSUE-064`: open pending actual Worker/Reviewer security proof.
- `ISSUE-065`: open pending actual lifecycle/recovery proof.
- `ISSUE-066`: open pending actual proof evidence.
- `ISSUE-068`: resolved for implementation/deterministic regression.
- `ISSUE-069`: local migration/Post-Quality subcauses satisfied; broader
  FULL_ORCHESTRATION/G-ORCH-06 scope remains deferred.
- `ISSUE-092`: retired by append-only disposition only.
- `ISSUE-095`: resolved for G-ORCH-02 implementation/deterministic regression.

## 5. Next Safe Work

Allowed preparation work:

- define the immutable proof97 fixture without executing it.
- define live-readiness evidence schema and collection timing.
- define the exact full-regression and focused actual-proof commands.
- define expected reviewer outputs and hard-stop conditions.

Not allowed without dangerous-work approval:

- live Codex execution for proof.
- actual Broker WRITE or product mutation.
- proof97 execution.
- deployment, commit, or push.

## 6. Current Gate Boundary

```text
proof97 = HOLD
G-4A-ACTUAL = PREPARATION ONLY
```
