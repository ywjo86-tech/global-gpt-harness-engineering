# R22 TASK-015 Generic Diagnosis and Fix Plan

Protocol: standards/EXHAUSTIVE_DIAGNOSIS_PROTOCOL.md (EDP-1.0)
Status: DIAGNOSED / FIX PLAN

## Observed stop point
- r22 is not deadlocked: supervisor heartbeat is current and the worker has an active NVIDIA HTTPS connection.
- Initial segmented generation and Broker writes completed.
- Independent focused validation failed.
- Validation-remediation attempt-01 completed Broker writes but the generated tests still violate authoritative runtime contracts.
- The worker is currently in the next bounded provider generation/retry path; no tracked Harness file may be edited until r22 terminates because that would correctly trigger outside-owned-scope protection.

## Root causes
1. Provider semantic convergence is not proven before governed effects. Schema/syntax/security checks pass, but API-level behavior can still be wrong.
2. Remediation grounding is improved but remains advisory: the model can claim a fix while returning content that still contradicts supplied authoritative source.
3. Network/model retry budgets can make a failed semantic correction appear hung even while heartbeat remains healthy.

## Generic correction
- Preserve all current identity/scope/security/Broker/Router/MPRF boundaries.
- Add pre-effect candidate verification for Provider ACTION proposals in an isolated disposable checkout/overlay using the sealed focused validation command.
- Feed bounded/redacted candidate-validation failures back into the existing Router-approved correction loop before any Broker effect.
- Only after candidate verification passes may the proposal be persisted/applied through ProductionToolTransport.
- Keep post-effect independent verification as defense in depth.
- Add unresolved-local-import precheck as a cheap deterministic guard before candidate test execution.
- Do not increase retry count, sanitizer limits, owned scope, or mutation authority.

## EDP closure criteria
- Candidate with nonexistent local import is rejected pre-effect.
- Candidate with runtime contract mismatch is rejected pre-effect by focused validation and can be corrected without Broker writes from failed candidates.
- Failed candidate leaves project worktree unchanged and effect journal empty.
- Corrected candidate still requires Broker write + post-effect independent validation.
- Focused and full regression PASS; negative-space/adversarial/PASS-challenge blocker=0, unresolved major=0.
