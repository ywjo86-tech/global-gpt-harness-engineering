# AI Office Harness Multi-Provider Extensibility Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the EDP findings in the still-open AI Office Harness Upgrade without activating a new external Provider.

**Architecture:** Generalize provider identity and dispatch contracts while keeping production admission/effect authority fail-closed. Wire real readiness/lifecycle facts into production routing, activate only evidence-safe reroute, and preserve malformed Provider output as sanitized immutable evidence.

**Tech Stack:** Python 3.12, unittest, dataclasses, existing Full Plan/MPRF/Router/Execution Backend contracts.

**Spec:** `docs/superpowers/specs/2026-09-19-ai-office-harness-multiprovider-extensibility-design.md`

## Global Constraints
- No new external Provider activation, secrets, billing, deployment, merge, push, or authority transfer.
- No Codex-first or NVIDIA-first selection.
- Existing current Provider behavior remains supported.
- Every behavior change follows RED -> GREEN -> full affected regression.
- Fail closed on unknown adapter, stale authority, ambiguous effects, or malformed evidence.

## Review Focus
- Third Provider can exist in registry/router tests without being production-active.
- Deterministic selection is reproducible but not lexically provider-ranked.
- Codex readiness is detected when pre-collected evidence is absent.
- Reroute excludes failed provider and cannot cross ambiguous effects.
- Invalid raw response evidence never leaks secrets and survives validation failure.

---

### Task 1: Provider-neutral identity and registry contracts
**Files:** `runtime/mprf/contracts.py`, `runtime/mprf/registry.py`, `runtime/orchestrator/provider_router.py`, tests under `tests/mprf/` and `tests/test_provider_router.py`.
**Produces:** generic provider identity validation; generic snapshot/decision provider domain; current production activation unchanged.
- [ ] Add failing third-provider registry/router tests and verify RED.
- [ ] Generalize contracts minimally; retain explicit admission and canonical envelope checks.
- [ ] Run focused tests and verify GREEN.

### Task 2: Provider Adapter Registry and generic dispatch
**Files:** create `runtime/orchestrator/provider_adapter_registry.py`; modify `provider_executor.py`; focused executor tests.
**Produces:** adapter lookup by provider identity; built-in Codex/NVIDIA registrations; unknown adapter fail-closed.
- [ ] Add failing fake-third-provider adapter dispatch test and verify RED.
- [ ] Implement registry and refactor governed dispatch through it.
- [ ] Run focused compatibility tests and verify GREEN.

### Task 3: Neutral Router V3 selection
**Files:** `runtime/orchestrator/provider_router.py`, `tests/test_provider_router.py`.
**Produces:** eligibility/capability filter plus request-bound deterministic ranking; no capability-count or lexical priority.
- [ ] Add RED tests proving both current providers can be selected across distinct request identities and provider names do not define winner.
- [ ] Implement deterministic hash ranking and generic model fallback binding.
- [ ] Run focused tests GREEN.

### Task 4: Production readiness and lifecycle binding
**Files:** `production_full_plan_entry.py`, `gate_orchestrator.py`, `provider_runtime_binding.py`, related tests.
**Produces:** actual Codex detection when no explicit override is supplied; required capabilities reach MPRF lifecycle export; lifecycle facts can remove unhealthy/quota-exhausted candidates.
- [ ] Add RED tests reproducing READY Codex projected unavailable and required-capability/lifecycle omission.
- [ ] Correct propagation with no Provider priority change.
- [ ] Run focused integration tests GREEN.

### Task 5: Safe MPRF reroute activation
**Files:** `runtime/mprf/failure.py`, `runtime/mprf/router_client.py`, `runtime/orchestrator/provider_router.py`, recovery tests.
**Produces:** original provider/model binding; failed candidate exclusion; `INVALID_RESPONSE` reroute only on confirmed no-effect evidence.
- [ ] Add RED tests for safe alternate reroute and unsafe effect rejection.
- [ ] Implement minimal contract extension and Router activation.
- [ ] Run reroute/recovery tests GREEN.

### Task 6: Durable invalid-response evidence
**Files:** `runtime/orchestrator/provider_action_execution.py`, provider-action tests.
**Produces:** sanitized hash-bound raw response evidence persisted before parse/schema/Python validation; secrets redacted.
- [ ] Add RED tests for malformed response artifact and secret redaction.
- [ ] Implement evidence persistence before validation.
- [ ] Run provider-action tests GREEN.

### Task 7: Governance reconciliation and EDP closure
**Files:** `docs/DEVELOPMENT_PLAN.txt`, `docs/harness/orchestration-state.md`, `docs/history/upgrades/2026-09-19-AI-OFFICE-HARNESS-EDP-EXTENSIBLE/*`.
**Produces:** scope amendment, finding ledger, evidence matrix, RTM, final ALL PASS record.
- [ ] Run focused provider/MPRF/Full Plan/Attention/Exit Guard regression.
- [ ] Run full unittest discovery, compileall, diff-check.
- [ ] Run negative-space and cross-document scans.
- [ ] Run adversarial second pass and PASS challenge.
- [ ] Record closure metrics only from fresh evidence and commit final documentation.
