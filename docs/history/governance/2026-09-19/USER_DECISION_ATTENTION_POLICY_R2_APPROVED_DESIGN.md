# User Decision & Attention Policy R2 — Approved Design Contract

**Date:** 2026-09-19  
**Status:** APPROVED DESIGN CANDIDATE / IMPLEMENTATION REQUIRES EDP PASS  
**Protocol:** `standards/EXHAUSTIVE_DIAGNOSIS_PROTOCOL.md` / EDP-1.0  
**Authority:** current explicit user decision approving the corrected R2 direction  
**Baseline:** `ee27f8bd0718a49a390a0f82b933c7fec0b8d9a1`

## 1. Goal

Reduce unnecessary user approval requests and mid-work notifications without weakening fail-closed recovery, evidence durability, or authority boundaries.

The system must continue automatically inside an already approved Full Plan contract, while requesting the user only for a genuine decision and notifying the user about runtime incidents only after autonomous recovery has stopped making semantic progress for the configured notification window.

## 2. Authority Freeze

- GPT remains Operator.
- Full Plan remains the sole owner of Task/Gate/fan-in/next-state transitions.
- Multi-Provider Router remains the sole provider/model selection authority.
- MPRF remains provider runtime/health/recovery-fact authority.
- Execution Backend / Full MCP remains state-changing effect authority.
- GPT Operator Manual Action remains bounded by existing approval, owned scope, and effect authority.
- Attention remains outbound-only and has no approve/resume/reroute/patch/provider-change authority.
- This design does not activate provider expansion or AI Office PHASE 7 scope.

## 3. User Decision Contract

A user decision is required only when at least one condition below is true.

- **UDAP-MUST-001 — Initial execution approval:** the first state-changing or dangerous implementation run lacks valid prior user approval.
- **UDAP-MUST-002 — Material contract revision:** requirement, scope, constraint, success criterion, deliverable, project identity, root, version, or authority boundary changes materially.
- **UDAP-MUST-003 — Risk-envelope escalation:** the requested action is outside the risk/action classes explicitly covered by the current approval lineage.
- **UDAP-MUST-004 — Ambiguous dangerous effect:** a dangerous/external state-changing effect cannot be proven absent, reconciled, or idempotently completed before retry.

The following are not user-decision events when they remain inside the same approved contract and have safe evidence-preserving recovery:

- test or validation failure;
- syntax or generated-code failure;
- bounded retry/remediation;
- checkpoint recovery or verified prefix adoption;
- same-scope bounded Manual Action;
- provider/model replacement under the same capability/output/validation contract;
- next LV or ordinary Full Plan Gate transition;
- EDP regression/re-diagnosis.

No runtime component may fabricate a new `USER_OWNER` approval. Continuation must derive from verified existing approval lineage or stop at `USER_DECISION_REQUIRED`.

## 4. Continuation Contract

- **UDAP-MUST-005 — Evaluator-only continuation policy:** any continuation policy may only classify whether existing Full Plan authority can continue; it must never dispatch, resume, reroute, approve, or select the next state itself.
- **UDAP-MUST-006 — Full Plan owns continuation:** when no user decision is required, Full Plan remains responsible for retry, remediation, next-LV, next-Gate, checkpoint adoption, and successor dispatch.
- **UDAP-MUST-007 — Fresh-run lineage:** a fresh Run may reuse prior approval only when Plan SHA, requirement/scope bindings, owned scope, risk coverage, and verified checkpoint/review lineage remain compatible. Otherwise return `PLAN_REVISION_REQUIRED` or `USER_DECISION_REQUIRED`.
- **UDAP-MUST-008 — Gate-mode compatibility:** `FULL_PLAN` ordinary Gate exits remain automatic system transitions; `GATE_BY_GATE` retains its existing next-Gate user-approval boundary.

## 5. Incident and User-Attention Contract

- **UDAP-MUST-009 — Immediate durable incident evidence:** runtime errors/waits/blocks must be persisted immediately. Delaying user notification must never delay incident evidence.
- **UDAP-MUST-010 — Deferred ordinary notification:** ordinary runtime incidents become user-notification eligible only after at least 300 seconds without semantic/recovery progress.
- **UDAP-MUST-011 — Immediate decision delivery:** `USER_DECISION_REQUIRED` / genuine `WAITING_APPROVAL` events bypass the delay and are immediately user-notification eligible.
- **UDAP-MUST-012 — Liveness separation:** heartbeat/liveness is not semantic progress. Internal liveness loss may be detected earlier, but user-facing liveness notification requires the user-attention threshold unless a decision is required.
- **UDAP-MUST-013 — Recovered incident suppression:** completed/cancelled runs and incidents followed by current semantic/recovery progress are not user-notification eligible.
- **UDAP-MUST-014 — Outbound-only:** attention records and delivery evaluation have `control_authority=NONE` and never mutate orchestration state.

## 6. Dangerous Retry / Effect Reconciliation

- **UDAP-MUST-015 — Fail closed by default:** dangerous failed work remains non-retryable when approval coverage or effect state is unavailable.
- **UDAP-MUST-016 — Covered safe retry:** a dangerous retry may continue under the existing approval only when the requested action remains inside approval coverage and effect reconciliation proves `NO_EFFECT` or `RECONCILED`/idempotently safe completion.
- **UDAP-MUST-017 — Ambiguous effect escalation:** `AMBIGUOUS` or missing effect evidence requires a fresh user decision before dangerous re-execution.
- **UDAP-MUST-018 — Evidence-bound approval coverage:** production retry/continuation code must not trust a naked boolean assertion of approval coverage. Coverage is valid only when an approval reference exists, approved/reviewed semantic digests are exact-compatible, and the requested operation/risk class is explicitly represented by the verified coverage projection.

## 7. Compatibility and Migration

- Existing `orchestration.user-attention.v1` records remain readable.
- Approval coverage is represented as a pure verified projection referencing existing approval lineage; it is not a new approval authority and cannot mint `USER_OWNER` evidence.
- New optional delivery-policy fields may be added without changing event identity or granting control authority.
- Historical pending events without delivery metadata remain byte-unchanged and readable; delivery class is deterministically inferred by kind (`WAITING_APPROVAL`/decision = immediate, stall/liveness anomaly = stall-confirmed, other incidents = deferred) so historical evidence cannot bypass R2 notification policy.
- Existing approval evidence schemas remain authoritative; this change does not silently rewrite or supersede historical approvals.
- `production_approval.py`, Router, MPRF, and Full MCP selection/effect authority are not changed unless a later EDP finding proves a necessary controlled change.

## 8. Implementation Boundary

Expected implementation surfaces:

- create `runtime/orchestrator/user_interaction_policy.py` — pure decision/delivery eligibility evaluators only;
- modify `runtime/orchestrator/production_attention.py` — persist optional delivery-policy metadata while remaining outbound-only;
- modify `runtime/orchestrator/production_attention_watch.py` — filter user-visible delivery using R2 timing/progress rules;
- modify `runtime/orchestrator/production_full_plan_runner.py` — tag incidents with the correct delivery class; do not change Gate meaning or next-state ownership;
- modify `runtime/orchestrator/retry_policy.py` — preserve fail-closed default and permit only evidence-backed dangerous retries;
- add focused tests for user-decision classification, attention delay/suppression, mode compatibility, and dangerous retry reconciliation.

`gate_orchestrator.py` ordinary FULL_PLAN/GATE_BY_GATE transition semantics are a protected regression surface, not an intended implementation target.

## 9. Acceptance / Adversarial Tests

| Test | Required proof |
|---|---|
| TEST-UDAP-001 | FULL_PLAN Gate transition stays automatic and does not request renewed user approval. |
| TEST-UDAP-002 | GATE_BY_GATE still stops for next-Gate approval. |
| TEST-UDAP-003 | Same-scope ordinary failure is eligible for existing Full Plan recovery without a new user decision. |
| TEST-UDAP-004 | Material plan/scope/authority change classifies as `USER_DECISION_REQUIRED` / plan revision. |
| TEST-UDAP-005 | Risk escalation outside approval coverage requires a user decision. |
| TEST-UDAP-006 | Dangerous retry without effect evidence remains blocked. |
| TEST-UDAP-007 | Dangerous retry with valid approval coverage + `NO_EFFECT` is allowed. |
| TEST-UDAP-008 | Dangerous retry with `AMBIGUOUS` effect is blocked for fresh approval. |
| TEST-UDAP-009 | WAITING_PROVIDER incident is durably recorded immediately but is not user-visible before 300s without progress. |
| TEST-UDAP-010 | The same unresolved incident becomes user-visible at/after 300s without semantic progress. |
| TEST-UDAP-011 | Semantic/recovery progress resets the effective notification timer. |
| TEST-UDAP-012 | COMPLETED/CANCELLED run suppresses stale ordinary incident delivery. |
| TEST-UDAP-013 | Genuine WAITING_APPROVAL is immediately user-visible. |
| TEST-UDAP-014 | Liveness heartbeat alone never resets semantic-progress timing. |
| TEST-UDAP-015 | Attention output stays `OUTBOUND_ONLY` / `control_authority=NONE`. |
| TEST-UDAP-016 | Historical v1 attention records remain readable. |
| TEST-UDAP-017 | Fresh-run continuation cannot fabricate USER_OWNER authority or bypass incompatible Plan/scope lineage. |
| TEST-UDAP-018 | Router/MPRF/Full MCP authority negative-space remains unchanged. |

## 10. AI Office Continuation Disposition

R24/R25/R26/R27/R28 remain immutable historical evidence. R29 preparation is preserved and not mutated by this remediation.

After this Harness remediation reaches EDP ALL PASS, AI Office resumes through a fresh Run identity based on the new Harness baseline. Verified TASK-015/TASK-016 checkpoints may be adopted only through the existing evidence-preserving prefix-adoption contract; TASK-017 must execute under the refreshed authority/baseline.

## 11. Success Gate

Implementation is acceptable only when focused regression, full repository regression, compileall, diff-check, authority negative-space, all TEST-UDAP-001~018, and EDP-1.0 closure all pass with `BLOCKER_COUNT=0`, `UNRESOLVED_MAJOR_COUNT=0`, `MUST_TRACEABILITY_COVERAGE=100%`, and `ADVERSARIAL_NEW_BLOCKER_MAJOR=0`.