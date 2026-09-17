# TASK-002 PCA-001 Provider Router v2 Qualification

Status: PASS_CANDIDATE_FOR_GATE002
Date: 2026-09-17
Parent Gate: GATE-001 GO (`d8bde04`)
Scope: TASK-002 / PCA-001 only. No MPRF runtime, provider lifecycle, action-effect, or publication authority is activated here.

## Implemented contract extension
- RouterRequest.v2 now carries eligibility snapshot ref + digest binding in addition to the snapshot facts.
- Eligibility ref/digest mismatch fails closed before provider/model selection.
- `FailureClass.v1` is a closed enum at the Router consumer boundary; unknown values are rejected.
- A failover reference without an exact failure class is rejected.
- Reroute-eligible classes are recognized as contract input, but actual MPRF reroute policy remains inactive until TASK-012; no provider switch is performed by TASK-002.
- Legacy HYBRID `mode/capabilities` semantics have an explicit v2 normalizer. Legacy `test` and `implementation` are split into `test_execution` and `implementation_apply` rather than collapsing generation/apply semantics.
- RouterDecision.v2 remains deterministic and binds provider/model selection to Router-owned eligibility facts.

## TEST-004 / TEST-005 / TEST-006 evidence
Focused Router contract suite: 15/15 PASS.
Combined Router/HYBRID/Operator/NVIDIA/Handoff regression: 39/39 PASS.
Python compile for Router/Executor/NVIDIA adapter: PASS.
Controlled `git diff --check`: PASS.
Static negative-space scan found no task-level provider/model assignment and no automatic NVIDIA-to-Codex fallback path in controlled runtime files.

## Authority preservation
Provider Router remains the only governed provider/model selector.
Provider Executor consumes RouterDecision and does not select a replacement provider/model.
NVIDIA remains non-state-changing in governed HYBRID execution.
Codex action routing remains a fresh ACTION-stage Router decision, not same-stage fallback.
Reroute activation is deliberately deferred to the approved MPRF failure/recovery task sequence.

## Scope isolation
Pre-existing/unrelated local changes in `docs/DEVELOPMENT_PLAN.txt`, `runtime/orchestrator/engine.py`, `tests/test_hybrid_runtime_flow.py`, `tests/test_nvidia_adapter.py`, and PREPH5MPRF source-history files were preserved and are not part of this TASK-002 qualification commit unless explicitly listed by that commit.
