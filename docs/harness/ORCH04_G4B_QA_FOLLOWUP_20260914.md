# ORCH04 G-4B QA Follow-up — 2026-09-14

> QA ID: `QA-ORCH04-G4B-001`
>
> Status: **CLOSED — remediation validated by fresh r15 Stage Gate**
>
> Scope: persisted Stage Gate artifact fidelity after accepted authority disposition.

## 1. Trigger

Fresh r14 Stage Gate returned `CONDITIONAL GO` after the Project Owner accepted the
r12/r13 evidence packet and all required authority issue dispositions became `RESOLVED`.

Accepted authority:

- `docs/harness/ORCH04_AUTHORITY_DISPOSITION_20260913_ACCEPTED.json`
- SHA-256: `f84f784566b4606043f14a419c394068289d4156668a0f716a0ff130d9d5d964`

Fresh Gate artifact:

- `_workspace/g-4b-release-handoff-fresh-20260913-r14-accepted/gate/stage_gate_result.json`
- SHA-256: `ebb0aaeddc4c0d0bf5269ebfdefc935a757598d04bc1955d0485a8814d1c7cb1`

## 2. Observed mismatch

The r14 persisted Gate result records `CONDITIONAL GO` but contains empty
`conditions`, empty `remaining_risks`, and no `evidence_reviewed` field.
The in-memory `StageGateDecision` generated from the same payload backfills:

```text
conditions = ["complete QA follow-up before next phase"]
remaining_risks = ["QA follow-up remains advisable."]
```

A bounded reproduction against a cloned sample project produced:

```text
RETURNED_DECISION= CONDITIONAL GO
RETURNED_CONDITIONS= ['complete QA follow-up before next phase']
RETURNED_REMAINING_RISKS= ['QA follow-up remains advisable.']
PERSISTED_DECISION= CONDITIONAL GO
PERSISTED_CONDITIONS= []
PERSISTED_REMAINING_RISKS= []
PERSISTED_EVIDENCE_REVIEWED= None
```

## 3. Root-cause diagnosis

`StageGateReviewerAgent.run()` computes conditional authority state and constructs
conditions, risks, and evidence-review metadata. However, the returned `WorkerResult`
does not carry that local payload.

`runtime/orchestrator/worker_runner.py` then rebuilds Gate metadata. For a
`CONDITIONAL GO` with all issue dispositions resolved, `authority_review_risks` is
empty, so the runner writes empty `remaining_risks` and empty `conditions`.
`runtime/orchestrator/stage_gate.py::_decision_from_payload()` later backfills a
generic QA condition only for the returned decision object. It does not rewrite the
already persisted `stage_gate_result.json`. This creates an artifact/return-value split.

## 4. Impact classification

- Authority disposition integrity: **PASS** — no authority issue is reopened.
- r14 decision vocabulary: **PASS** — `CONDITIONAL GO` is preserved.
- Persisted Gate audit fidelity: **FAIL** — conditions/evidence do not match semantics.
- Release/deploy/push authorization: **NO CHANGE** — still forbidden without separate approval.
- Final G-4B handoff seal: **BLOCKED by QA follow-up** until persisted output is corrected and revalidated.

The existing r14 artifacts are historical evidence and must not be rewritten.

## 5. Required remediation acceptance criteria

1. A focused regression test must cover `CONDITIONAL GO` + all required issues
   `RESOLVED` + accepted authority conditions + `qa_required=false`.
2. The persisted Gate artifact must retain a non-empty conditional reason/condition.
3. The persisted artifact must identify the authority review packet as reviewed evidence.
4. Returned `StageGateDecision` and persisted `stage_gate_result.json` must be
   semantically consistent for decision, conditions, risks, and evidence review.
5. Existing GO / NO-GO / deferred-authority behavior must remain unchanged.
6. Focused Stage Gate tests and the G-4B regression set must pass after remediation.
7. A fresh post-fix Stage Gate record must be created; r14 remains immutable history.
## 6. Scope guard

This follow-up record does not authorize runtime-code modification by itself. The r14
Gate task explicitly listed `runtime code` and `.claude/` as forbidden scope. Any
remediation implementation must therefore run as a separately bounded QA task.

No release, deployment, remote push, or historical evidence rewrite is authorized by
this document.

## 7. Current disposition

```text
qa_id: QA-ORCH04-G4B-001
qa_status: CLOSED
root_cause_identified: YES
reproduction: PASS
runtime_fix_applied: YES
post_fix_regression: PASS
fresh_post_fix_gate: CONDITIONAL GO / artifact fidelity PASS
final_g4b_handoff_seal: READY FOR USER APPROVAL
release_deploy_push_authorized: NO
```
## 8. Closure record — 2026-09-14

The remediation was applied only to the Stage Gate persistence boundary and regression
coverage. Historical r14 evidence was not rewritten.

Validation results:

- focused Stage Gate tests: `9 tests OK`
- current G-4B regression selection: `166 tests OK, skipped=2`
- full repository regression: `1,138 tests OK, skipped=9`
- fresh post-fix Gate: `_workspace/g-4b-release-handoff-fresh-20260914-r15-qa-fix/`
- r15 decision: `CONDITIONAL GO`
- persisted/returned decision, conditions, risks, and reviewed evidence: **MATCH**
- authority review checked: `yes`
- authority unresolved issues: `0`

The historical r14 regression recorded `169 tests OK, skipped=2`. The current selected
G-4B module set enumerates 166 tests because the checkout's test composition changed
after r14; all currently enumerated tests pass. The full 1,138-test regression provides
the current checkout-level closure check.

The one initial full-suite failure was a stale Wallet test provenance set. The missing
`5671...` digest is explicitly recorded in the Wallet plan and Gate 0 evidence as the
V20 original plan digest; adding that documented historical digest to the test provenance
set restored the full-suite result without changing runtime approval validation.

Closure evidence:

- `closure/qa_closure.json` SHA-256: `b3231f49f2bb4732cdfd51ef8151926eb8904938d9941ed4b62522d0ef497608`
- r15 Gate result SHA-256: `3f06cd6e4b244f5fdd7b664ff6f071d155e125adbc9529849c045ef8088cb8a0`
- scope manifest: `_workspace/g-4b-release-handoff-fresh-20260914-r15-qa-fix/closure/source_scope_manifest.sha256`
- source scope manifest SHA-256: `cce55c8a41e8685701c78684d8036e33bb358b33bc346e5c3a12a3f48148853f`

`QA-ORCH04-G4B-001` no longer blocks final G-4B handoff approval. Release, deployment,
and remote push remain separately prohibited until explicit approval.
