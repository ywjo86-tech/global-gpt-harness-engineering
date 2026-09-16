# Full MCP Runtime / PHASE 4 Qualification Runbook

## Scope
This document describes the qualified PHASE 4 Full MCP runtime boundary and the contract-only handoff package. It does not authorize PHASE 5 implementation, merge, deployment, provider expansion, or an `MCP_STABLE_BASELINE` declaration.

## Runtime boundary
- Transport: MCP stdio using the approved 2026-07-28 protocol contract.
- Consumer boundary: the existing Execution Backend Contract remains the consumer-facing authority.
- Provider selection: `PROVIDER_ROUTER` remains the sole selection authority under `HYBRID` mode.
- NVIDIA state-changing execution and NVIDIA-to-Codex automatic fallback remain prohibited.
- Full MCP has no direct Project Memory, Jarvis, UI, BI, HTTP, or SSE integration in PHASE 4.

## Qualified capability surface
Full MCP exposes the approved filesystem, shell/process, Git inspection/restore/prepare-commit, sealed validation, status, validation, structured observability, and recovery primitives. Authorization, workspace/path policy, effect receipts, failure taxonomy, audit correlation, recovery invalidation, and contract-only adapter behavior are qualification requirements rather than optional extensions.

## Evidence and gate ordering
Qualification records are immutable and attempt-scoped under `_workspace/full-mcp/<run-id>/attempts/<attempt>/`. Earlier ValidationResult, Evidence, Review, Index, and Gate records are never rewritten. A changed proof dependency becomes stale and must re-enter through the earliest invalidated gate.

The final PHASE 4 order is:
`GATE-005 GO -> PREFINAL index -> official-exit-gates -> TEST-028 -> EVD-019 -> phase5-handoff candidate -> TEST-031 -> EVD-020 -> GATE-006 index -> independent review -> GATE-006 -> eligibility manifest`.

## Official exit artifact
`gates/official-exit-gates.json` contains exactly the 12 Plan-authoritative PHASE 4 acceptance rows, in fixed order, and is sourced from the complete GATE-005 GO decision. Every row remains `PASS` for GATE-006 eligibility.

## PHASE 5 handoff candidate
`qualification/phase5-handoff.json` is metadata-only. Its status is always `CANDIDATE_NOT_AUTHORIZED` during PHASE 4. It binds the approved execution contract, plan/design references, dependency lock, PREFINAL index, official exit artifact, EVD-019, prerequisite gates, and current workspace state. It contains no PHASE 5 implementation design or concrete provider assignment.

## Stable-baseline semantics
GATE-006 determines only technical eligibility. After GATE-006 GO, CMP-020 may emit `stable-baseline-manifest.json` with `eligibility_status=ELIGIBLE` and `declaration_status=NOT_DECLARED`. That manifest is not a baseline declaration and does not merge, deploy, push, or authorize PHASE 5.

## Operational prohibitions
- Do not rewrite GATE-001 through GATE-005 or EVD-001 through EVD-018/EVD-021.
- Do not mutate the sealed evaluator/bootstrap test targets CT-028 or CT-041.
- Do not create self-referential Evidence/Index chains.
- Do not use `git add`, `git commit`, or any Git publication without the separately required approval.
- Do not push, deploy, reset, clean, rebase, publish remote branches, or expand providers/routing under this PHASE 4 contract.
