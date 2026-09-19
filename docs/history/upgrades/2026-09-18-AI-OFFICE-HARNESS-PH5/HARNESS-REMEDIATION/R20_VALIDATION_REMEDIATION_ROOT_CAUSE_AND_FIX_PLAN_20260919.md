# R20 Validation Remediation Root Cause and Fix Plan

Status: DIAGNOSED / FIX AUTHORIZED BY CURRENT USER CONTINUE INSTRUCTION
Protocol: `standards/EXHAUSTIVE_DIAGNOSIS_PROTOCOL.md` (EDP-1.0)
Run evidence: `ai-office-ph5-gate005-20260919-r20`, TASK-015

## Root cause
1. Initial segmented proposal and Broker writes succeeded.
2. Independent focused/full validation failed on generated API usage.
3. Two bounded validation-remediation attempts executed, but OWNED_0001 remained byte-identical and OWNED_0002 converged to a still-invalid result.
4. Validation feedback was flattened/truncated globally, so a late exception could be omitted.
5. Remediation context selection spent bounded file slots on owned/generated tests and generic tests while the authoritative imported contract source (`runtime/orchestrator/office_execution_contract.py`) was not guaranteed to be present.

## Fix
- Preserve complete bounded error groups rather than a flat first-N event list.
- Derive target-specific feedback for each segmented owned file.
- During remediation, exclude owned/generated files from ordinary context slots because the target file is already supplied through bounded current-target context.
- Prioritize runtime trace sources and the target file's resolvable local Python import dependencies.
- Keep the existing 8-file / 16-KiB-per-file / 64-KiB-total sanitizer boundary.

## Non-goals / forbidden changes
- Do not increase provider retry count or validation-remediation count.
- Do not widen editable owned scope or mutation authority.
- Do not weaken identity, security, Broker, Router, MPRF, or Full Plan authority checks.
- Do not increase sanitizer file-count, per-file, or total-byte limits.

## Closure criteria
- Targeted regression proves late exception preservation, per-file feedback isolation, authoritative dependency inclusion, and zero authority expansion.
- Focused production/Router/Broker/validation regression passes.
- Full repository regression passes.
- EDP negative-space, adversarial second pass, and PASS challenge show blocker=0 and unresolved major=0.
- Fresh production run reaches TASK-015 validation without the R20 grounding defect; only then may checkpoint/TASK-016 progression be assessed.
