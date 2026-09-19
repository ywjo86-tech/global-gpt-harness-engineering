# MVP Provider Execution Goal Pass — Full Plan Hybrid

PROJECT_ID: MVP-PROVIDER-EXECUTION-TARGET
MODE: FULL_PLAN_HYBRID
OPERATOR: GPT
SCOPE: Provider execution latency stabilization only. No provider expansion, no Router authority transfer, no MPRF authority transfer, no Full MCP effect-authority change.

## Requirements

| ID | Requirement | Acceptance Criteria | Priority |
|---|---|---|---|
| REQ-001 | Provider ACTION must not multiply retries across outer execution and adapter fallback/retry loops. | Each governed model attempt is single-model and zero nested retry; bounded outer attempts remain. | MUST |
| REQ-002 | Provider failures consumed by the Provider ACTION layer must use provider-neutral failure classes. | NVIDIA adapter errors are normalized at the boundary; retry policy does not depend on NVIDIA-specific names. | MUST |
| REQ-003 | Existing Router/MPRF/Full Plan/Full MCP authority boundaries must remain unchanged. | No provider/model selection moves into Adapter, AI Office, Full Plan task definitions, or Execution Backend. | MUST |
| REQ-004 | Existing NVIDIA and Codex operation must remain regression compatible. | Focused provider/router/production suites and full regression pass. | MUST |
| REQ-005 | Timeout and retry exhaustion must fail closed without writing unvalidated effects. | Failure before proposal validation creates no governed file-write receipt or target mutation. | MUST |

## Change Targets

| ID | Source | Purpose |
|---|---|---|
| CT-001 | `runtime/orchestrator/provider_action_execution.py` | Provider-neutral bounded attempt controller behavior |
| CT-002 | `tests/test_provider_action_execution.py` | Focused regression and adversarial retry tests |

## TASK-001 — Provider-neutral bounded ACTION stabilization

Purpose: Remove nested retry/fallback amplification from Provider ACTION while preserving Router-owned model authority and all existing effect boundaries. Normalize Provider ACTION retry classification into provider-neutral failure classes without adding or activating any provider.

Related Requirements:
- REQ-001
- REQ-002
- REQ-003
- REQ-004
- REQ-005

Dependencies: NONE

Change Targets:
- CT-001
- CT-002

Required Capabilities:
- reasoning
- implementation
- test
- filesystem_write

Execution Authority: STATE_CHANGING

Validation:
- TEST-001
- TEST-002
- TEST-003

Completion Condition: Provider ACTION performs one Router-approved model call per outer attempt with no adapter fallback/retry multiplication; provider-specific adapter errors are normalized to provider-neutral retry classes; auth/policy failures fail immediately; no effect occurs on failed generation; focused and full regression pass.

## Source Projection — Task Dependencies

| Task | Dependency Type | Depends On | Reason |
|---|---|---|---|
| TASK-001 | SEQUENTIAL | NONE | Single bounded remediation LV |

## GATE-001 — MVP Goal Pass

Required Tasks: TASK-001

Gate Exit: TASK-001 validation PASS + EDP blocker 0 + unresolved major 0.
