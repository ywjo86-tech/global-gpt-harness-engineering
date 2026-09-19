# R23 Provider Proposal Schema Normalization — Diagnosis and Fix Plan

Protocol: `standards/EXHAUSTIVE_DIAGNOSIS_PROTOCOL.md` (EDP-1.0)
Status: DIAGNOSED / CORRECTED

## Observed failure
- Fresh production run r23 on HEAD `d13027d` blocked at TASK-015 before any Broker effect.
- Terminal error: `provider ACTION proposal schema mismatch`.
- Controlled model probe with the exact TASK-015 segment prompt showed:
  - Nemotron 3 Super: NVIDIA server error.
  - Ising Calibration 1.5 31B: completed JSON with correct identity/source/writes and target `OWNED_0001`, but omitted only the non-authoritative `summary` field.
  - Nemotron 3.5 Lightning: timeout.

## Root cause
The proposal validator treated omission of `summary` exactly like omission or mutation of authority-bearing identity/write fields. `summary` is descriptive evidence only; it cannot widen scope, select a target, change source binding, or authorize an effect. Rejecting the otherwise valid Ising proposal therefore converted a provider formatting variance into a full run failure. A separate prompt defect also hard-coded `OWNED_0001` in the JSON example for every segment, including `OWNED_0002`.

## Minimal correction
1. Normalize only one case: exact valid proposal keys with only `summary` missing and the expected proposal schema version. Insert deterministic summary `governed provider action proposal`.
2. Never infer or repair `project_id`, `run_id`, `gate_id`, `lv_id`, `plan_sha256`, `source_head`, `writes`, `owned_file_id`, `relative_path`, or `content`.
3. Keep extra keys invalid. Keep identity/write/scope/security validation unchanged.
4. Generate the prompt example with the actual segmented `target_owned_file_id` instead of hard-coded `OWNED_0001`.

## Forbidden changes
- No Router/MPRF/provider authority change.
- No Broker bypass or direct filesystem effect.
- No owned-scope widening.
- No retry-count or sanitizer-limit increase.
- No identity/source/write inference.

## Closure criteria
- Missing summary succeeds in one generation attempt without correction retry.
- Missing identity is not normalized.
- Segment prompt uses its exact owned-file ID.
- Candidate pre-effect validation and post-effect independent validation remain active.
- Targeted, focused, and full regression PASS.
- EDP negative-space/adversarial/PASS challenge leave blocker=0 and unresolved major=0.
