# Final Operational Scope Integrity Amendment — CLI-Anything

Status: USER-APPROVED
Approval: USER / 2026-09-20
Protocol: EXHAUSTIVE_DIAGNOSIS_PROTOCOL / EDP-1.0
Parent: `2026-09-20-diagnostic-intelligence-final-operationalization-design.md`
Companion: `2026-09-20-full-plan-continuity-skill-remediation-design.md`

## 1. Reason for Amendment

The original user scope for the three paused additions was CodeGraph + Holmes-inspired RCA + CLI-Anything. The parent Final Operationalization Spec incorrectly substituted already-qualified Graphify for CLI-Anything. Graphify remains a separate production-adoption baseline item; it is not one of the three paused additions.

This amendment restores the missing approved requirement so final EDP traceability can reach 100%. No final ALL PASS is valid while CLI-Anything is absent.

## 2. Correct Final Operational Scope

The final operational baseline must include:
- diagnosed runtime/governance/continuity remediation;
- Graphify production read-only adoption from its already-qualified PH2 baseline;
- CodeGraph read-only dependency/impact intelligence;
- Holmes-inspired evidence-first RCA;
- CLI-Anything bounded Tool Implementation integration;
- final EDP re-diagnosis and operational closure.
## 3. CLI-Anything Authority Boundary

CLI-Anything is a Tool Implementation mechanism, never an orchestration or authority layer.

Permitted:
- inspect software interfaces and generate bounded CLI adapters;
- discover candidate CLI implementations through its catalog/hub;
- run preflight and dry-run qualification in isolated environments;
- generate tool manifests and candidate skills for later Harness qualification;
- verify real artifacts in controlled test fixtures.

Forbidden:
- arbitrary shell passthrough exposed to workers;
- direct bypass of Tool Authorization, ClosedOperationRegistry, SingleToolBroker, or EffectJournal;
- provider/model selection;
- Full Plan task/gate/approval/completion authority;
- direct Attention/user-notification authority;
- generated skill self-activation or self-authorization;
- mutation of governance/docs outside an approved tool effect.

All actual state-changing execution remains:
`Full Plan -> Tool Authorization -> ClosedOperationRegistry -> SingleToolBroker -> qualified adapter -> EffectJournal -> verification`.
## 4. Required Integration Contract

Create a Harness-owned Tool Implementation plane with immutable/digest-bound manifests. CLI-Hub discovery is informational only. Generated CLIs/skills enter `CANDIDATE` state and cannot be invoked by Full Plan until qualification evidence seals exact source/version/command allowlist/input schema/output schema/effect class/artifact verifier digests.

No generated adapter may expose a generic `exec`, `shell`, `command`, or equivalent arbitrary-command surface. Arguments must use explicit allowlists and structured escaping; subprocess execution must never use `shell=True`.

Installation/activation is a separate authorized effect from discovery/generation. Generated skills require independent qualification before registration.

## 5. Minimum Production Qualification

Qualification must include:
- one read-only representative CLI end-to-end through the qualified adapter;
- one sandboxed state-changing fixture through Tool Authorization -> Broker -> EffectJournal;
- preflight/dry-run failure behavior;
- bad manifest/digest rejection;
- unsafe argument/path traversal rejection;
- arbitrary-shell attempt rejection;
- duplicate logical operation protection;
- crash after intent/before receipt reconciliation;
- artifact-verification failure;
- unqualified generated-skill rejection;
- CLI-Hub/tool generator unavailable degradation without control-plane impact.

## 6. EDP Domains

- `TI-01` Tool manifest/source/version binding
- `TI-02` Command/argument allowlist and no arbitrary shell
- `TI-03` Tool Authorization/Broker/EffectJournal integration
- `TI-04` Preflight/dry-run qualification
- `TI-05` Output/artifact verification
- `TI-06` Generated-skill qualification boundary
- `TI-07` Security/path/secret handling
- `TI-08` Disable/fallback/control-plane isolation

Every applicable domain requires evidence and negative-space review; `DOMAIN_EVIDENCE_COVERAGE=100%` remains mandatory.
## 7. Required Invariants

- `TI-INV-01`: CLI tooling never bypasses Tool Authorization/Broker/EffectJournal.
- `TI-INV-02`: Generated tools/skills cannot self-authorize or self-register.
- `TI-INV-03`: CLI-Hub discovery has `control_authority=NONE`.
- `TI-INV-04`: Generic arbitrary shell/command execution is prohibited.
- `TI-INV-05`: Tool manifests are immutable and digest-bound before activation.
- `TI-INV-06`: Install/activation requires a distinct authorized effect.
- `TI-INV-07`: Disable/unavailable CLI-Anything restores pre-integration behavior without changing Full Plan authority.

## 8. Final Scope Gate

Final project closure must explicitly trace:
- Graphify production adoption;
- CodeGraph integration;
- Holmes-inspired RCA;
- CLI-Anything Tool Implementation integration;
- continuity remediation;
- runtime/Attention operational convergence.

If any one is absent, final decision is `NOT_ELIGIBLE_FOR_ALL_PASS`.

The universal EDP closure metrics from the companion continuity Spec remain unchanged, including `MUST_REQUIREMENT_COVERAGE=100%`, `MUST_TRACEABILITY_COVERAGE=100%`, `DOMAIN_EVIDENCE_COVERAGE=100%`, `BLOCKER_COUNT=0`, `UNRESOLVED_MAJOR_COUNT=0`, and `MATERIAL_DEFECT_SEARCH=EXHAUSTED_FOR_AVAILABLE_EVIDENCE`.
