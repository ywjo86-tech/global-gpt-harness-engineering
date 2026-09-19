# AI Office Harness Multi-Provider Extensibility Remediation Design

## Authority and scope
- Authority: current user directive on 2026-09-19 plus existing AI Office PH5 Full Plan authority.
- Diagnosis standard: EDP-1.0 / `standards/EXHAUSTIVE_DIAGNOSIS_PROTOCOL.md`.
- Baseline: `5eb5b30be5889f3ddd4f0754404b237697eac231`.
- This is a contract-scope correction while AI Office Harness Upgrade remains open.
- No new external Provider is activated, credentialed, billed, deployed, merged, or pushed.
- GPT remains Operator; Full Plan owns task/gate/fan-in; Router owns provider/model selection; MPRF owns provider runtime facts; Full MCP/Execution Backend owns effects.

## Problem statement
Current planning and task contracts are provider-neutral, but runtime admission, Router envelopes, dispatcher edges, readiness projection, lifecycle production binding, and reroute activation retain Codex/NVIDIA-specific assumptions. Both Providers being READY currently produces a structural NVIDIA selection bias from capability-cardinality scoring. Invalid Provider output is validated fail-closed but malformed raw responses are not durably preserved.

## Requirements
1. Provider/model identity contracts MUST accept arbitrary approved registry identities without a compiled-in `{codex,nvidia}` domain.
2. Production activation MUST remain governed: a generic contract MUST NOT itself activate a new Provider.
3. Router eligibility/decision envelopes MUST be provider-neutral and deterministic.
4. Selection MUST NOT encode Codex-first, NVIDIA-first, provider-name lexical priority, or capability-count bias.
5. Existing Codex and NVIDIA adapters MUST continue to work through a provider adapter registry; unknown/unregistered execution MUST fail closed.
6. Full Plan provider readiness MUST reflect actual readiness; missing optional pre-collected Codex evidence MUST not force `codex=false` before runtime detection.
7. Production MPRF eligibility MUST consume required capabilities and lifecycle facts when available.
8. Safe reroute MUST be activatable only from MPRF-authorized recovery context and MUST exclude the failed provider/model.
9. `INVALID_RESPONSE` MAY reroute only when effect reconciliation proves no effect; otherwise reroute remains prohibited.
10. Invalid Provider responses MUST be sanitized and durably recorded before parse/schema/Python validation failure is raised.
11. Existing approval, effect, Manual Action, Attention, Exit Guard, checkpoint, and immutable evidence boundaries MUST not weaken.
12. Current Codex/NVIDIA behavior and the full repository regression MUST remain green.

## Architecture
`Full Plan -> Provider Runtime Facts -> Eligibility Snapshot -> Provider Router -> Provider Adapter Registry -> Attempt Controller -> Canonical Proposal Validator -> Execution Backend/Full MCP`.

The registry is open to provider identities but activation stays closed by explicit ProviderRecord/Admission/Adapter registration and production policy evidence. Router selection first filters eligibility/capability/health/failure exclusions, then uses a request-bound cryptographic deterministic ranking among the remaining candidates. Provider-specific transport stays in adapters.

## Reroute safety
A reroute request carries the original provider/model plus recovery/effect evidence. The fresh eligibility snapshot must exclude that failed identity. `INVALID_RESPONSE` is eligible only with `CONFIRMED_NO_EFFECT`; ambiguous/confirmed effects block reroute.

## Evidence and closure
Closure requires: focused RED->GREEN tests for every remediation, provider-neutral third-provider fake adapter tests, current Codex/NVIDIA compatibility tests, production readiness/lifecycle/reroute tests, raw-response evidence tests, negative-space scans for fixed provider-domain checks, full unittest discovery, compileall, diff-check, EDP evidence matrix/RTM/adversarial/PASS challenge with blocker=0 and unresolved major=0.
