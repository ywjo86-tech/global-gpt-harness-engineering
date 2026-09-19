# Operator Turn Exit Guard — Preimplementation EDP

**Protocol:** EDP-1.0
**Decision:** PASS_FOR_CONTROLLED_IMPLEMENTATION

## Authority register
1. Current explicit user decision: complete the work, use generic EDP diagnosis, and let Multi-Provider Router select the provider.
2. `USER_DECISION_ATTENTION_POLICY_R2_APPROVED_DESIGN.md` and its EDP ALL PASS baseline `c11ca279...`.
3. Verified current runtime: `production_full_plan_runner.py`, `operator_control.py`, `user_interaction_policy.py`, `production_full_plan_entry.py`.
4. `docs/harness/orchestration-execution-standard.md`.

## Evidence matrix
| Domain | Claim | Evidence | Result |
|---|---|---|---|
| Authority | Guard has no transition/provider/effect authority | design authority freeze + negative-space target boundary | PASS |
| Full Plan continuity | nonterminal/unfinished states cannot be final completion | active/wait/terminal state sets and `ALL_GATES_COMPLETED` logic | PASS |
| User decision | genuine approval boundary remains immediate | R2 `evaluate_user_decision` + `WAITING_APPROVAL` semantics | PASS |
| Attention | ordinary incident notification reuses R2 300s policy | `evaluate_attention_delivery` | PASS |
| Completion | completion requires exact Full Plan terminal facts plus caller obligations | OEG-MUST-006/016 | PASS |
| Invocation | guard cannot be an unused helper | OEG-MUST-010/011 + production-entry integration | PASS |
| Compatibility | GATE_BY_GATE and historical state stay unchanged | no Gate/state schema mutation planned | PASS |
| Provider authority | Router alone selects implementation provider | implementation workflow requirement | PASS |

## RTM
OEG-MUST-001..017 → `operator_exit_guard.py` assessment/tests → `production_full_plan_entry.py` output binding → focused/full regression → final EDP.

## Negative-space findings closed in design
- **OEG-F01:** helper-only guard could be bypassed. Closed by mandatory production-entry result binding plus standalone pre-final check.
- **OEG-F02:** treating `BLOCKED` as final could recreate premature completion. Closed by explicit non-completion rule and R2 notification gating.
- **OEG-F03:** project completion may require EDP/baseline after Full Plan completes. Closed by caller-supplied completion obligations.
- **OEG-F04:** duplicating R2 timing would drift. Closed by importing/reusing R2 evaluator.

## Adversarial second pass
Counterexamples tested conceptually: R30-like `TASK-017 ready`, provider wait at 299s, provider wait at 300s, recovered incident, genuine approval, cancelled run (terminal-report only), malformed state, all gates complete but EDP false. No authority transfer is necessary to classify any case.

## Metrics
`BLOCKER_COUNT=0`
`UNRESOLVED_MAJOR_COUNT=0`
`MUST_TRACEABILITY_COVERAGE=100%`
`DOMAIN_EVIDENCE_COVERAGE=100%`
`ADVERSARIAL_NEW_BLOCKER_MAJOR=0`
`PASS_CHALLENGE_OPEN_COUNT=0`

**EDP_DECISION=PASS_FOR_CONTROLLED_IMPLEMENTATION**
