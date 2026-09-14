# ORCH04 Remaining Issue Evidence Index

> Recorded: `2026-09-11`
>
> Scope: existing ORCH04/R4 evidence only. This index does not close issues or
> authorize a new Gate, deployment, commit, or push.

## Evidence status

| Issue | Current evidence | Disposition | Next required action |
|---|---|---|---|
| `ISSUE-025` | Actual Codex secret-like WRITE blocked; target unchanged; sentinel not persisted | `RESOLVED` | Retain evidence reference |
| `ISSUE-056` | Actual Worker baseline/current source HEAD/tree and checkpoint provenance revalidated; product-source boundary remains separate | `DEFERRED` | Product-bound actual source/provenance evidence |
| `ISSUE-059` | Actual Worker checkpoint plus WorkerAuthority mutation/completion chain revalidated; production authority closure remains separate | `DEFERRED` | Product-bound actual mutation/completion evidence |
| `ISSUE-060` | Product-owned frozen-node independent verifier passes | `RESOLVED` | Retain verifier evidence; recheck at G-4B |
| `ISSUE-063` | Bounded output/effect tests pass; actual shell-node output-source provenance remains absent | `DEFERRED` | Actual output-source evidence |
| `ISSUE-064` | Local independent Worker/Reviewer provenance chain passes; independent production security proof remains absent | `DEFERRED` | Independent security provenance evidence |
| `ISSUE-065` | Separate-process actual Codex A-crash/B-resume passed with same `RUN_ID`; durable journal and duplicate prevention verified | `RESOLVED` | Recheck at G-4B |
| `ISSUE-066` | Existing FULL_PLAN supervisor is exercised in the bounded authority chain; macro contract Gate review remains absent | `DEFERRED` | Scoped implementation and Gate review |
| `ISSUE-067` | Contract/package digest binding passes in the bounded chain; unified production-contract closure remains absent | `DEFERRED` | Scoped implementation and authority review |
| `ISSUE-068` | Actual first-WRITE/crash/same-`RUN_ID` resume test passes | `RESOLVED` | Recheck at G-4B |
| `ISSUE-069` | Full Plan supervisor integration passes in a bounded chain; broader product Full Plan closure remains absent | `DEFERRED` | Full orchestration evidence and review |
| `ISSUE-070` | Actual product frozen completion verifier passed and actual governed effect evidence is present | `RESOLVED` | Recheck at G-4B |
| `ISSUE-071` | Actual Worker provenance and Full Plan supervisor chain revalidated; complete capability/revision loop remains absent | `DEFERRED` | Scoped implementation and actual loop evidence |
| `ISSUE-075` | Actual READY readiness was consumed by canonical launch authority; launch-adjacent recheck binding passed | `RESOLVED` | Recheck at G-4B |
| `ISSUE-095` | DEC-011 implementation and deterministic regression pass | `RESOLVED` | Recheck at G-4B |

## Direct verification references

- Issue-mapped production/authority/recovery/security tests: `168 PASS / 5 skipped`.
- Full repository regression previously completed: `1,070 PASS / 9 skipped`.
- Actual Codex/Broker opt-in suite: one transient `TRANSPORT_TIMEOUT` was followed by
  a passing single-test retry; no code change was made for that retry.
- Actual crash/resume and secret-like WRITE boundary tests passed.
- Current actual proof record: `docs/harness/ORCH04_DEFERRED_EVIDENCE_SCAN_20260911.md`.
- Latest actual transport/child-worker record: `docs/harness/ORCH04_ACTUAL_EVIDENCE_20260912.md`.
- Latest bounded authority-chain integration test: `tests/test_orch04_evidence_chain.py`.
- `git diff --check`: PASS.

## Handoff boundary

```text
handoff_status: READY WITH FOLLOW-UP
full_plan_status: NOT FINAL
current_gate: G-ORCH-04 / G-4A-ACTUAL proof97 CONDITIONAL GO
next_gate: G-4B-RELEASE-HANDOFF
authority_review: RECORDED_BY_PROJECT_OWNER
```

The next authorized action is a fresh stage-gate review for `G-4B-RELEASE-HANDOFF`.
The Project Owner disposition is recorded separately; deferred issues remain subject
to the conditions in that record.
