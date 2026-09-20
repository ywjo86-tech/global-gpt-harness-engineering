# AI Office Harness Final Operationalization + Diagnostic Intelligence Plane Design

Date: 2026-09-20
Status: USER-DIRECTION-APPROVED / SPEC-REVIEW-PENDING
Protocol: EXHAUSTIVE_DIAGNOSIS_PROTOCOL (EDP-1.0)

## 1. Goal

Bring the Harness to one final production-operable baseline by:
1. repairing the diagnosed runtime/governance drift;
2. adopting Graphify, CodeGraph, and Holmes-inspired RCA without changing existing authority boundaries;
3. re-running EDP after every correction and closing only at ALL PASS.

The final state must have one current runtime source, valid restart/recovery, current governance documents, no hidden second orchestrator, and graceful degradation when diagnostic analyzers are unavailable.

## 2. Frozen Authority Boundaries

- Full Plan supervisor/gates: orchestration and progression authority.
- EDP: diagnosis/closure authority.
- Multi-Provider Router: provider/model selection authority.
- MPRF: provider lifecycle/eligibility/recovery authority.
- Execution Backend + Tool Broker/Full MCP: real effect authority.
- ToolEffectJournal + Effect Evidence Bridge: effect evidence authority.
- Completion Authority: completion proof.
- Full Plan Boot/Reconciler: restart/recovery authority.
- AttentionOutbox + Attention Watch: outbound user notification only.
- Graphify: repository topology evidence only.
- CodeGraph: symbol/dependency/impact evidence only.
- Holmes-inspired RCA: investigation/root-cause evidence only.
- Diagnostic Intelligence Plane: control_authority=NONE, mutation_authority=NONE, recovery_authority=NONE, completion_authority=NONE, notification_authority=NONE.

No diagnostic component may approve, mutate, reroute, resume, retry, mark completion, enlarge write scope, or notify the user directly.

## 3. Existing Operational Remediation

### 3.0 Approved-plan continuation semantics

Once an architectural implementation plan and its spec are explicitly approved, later user directives such as `진행`, `이어서 진행`, `계속 진행`, `continue`, or `resume` are continuation instructions for the already-approved scope. They do not require the user to repeat the phrase `Full Plan`. If the approved work is Harness-scale and a durable Full Plan job exists, the Operator must resume that job. If no durable job exists yet, the Operator must promote the approved plan into a durable GPT-operator Full Plan tracking job before further implementation.

The GPT-operator tracking job is non-executing authority: it may bind plan/spec digests, task order, branch, and durable task receipts; it may wait for receipts and expose liveness/attention state. It cannot execute source changes, select providers, grant approvals, call Tool Broker, mark Completion Authority, or reinterpret plan scope. Actual mutations remain under the existing approved Operator/Execution Backend path.

A material scope expansion, higher risk class, or ambiguous dangerous re-execution still uses `evaluate_user_decision()` and may require renewed user approval. Mere continuation wording is never treated as new approval and never broadens scope.

### 3.1 Runtime source convergence

Repair the broken ~/.local/share/global-gpt-harness/runtime-current target and make it point only to a verified, durable, current Harness runtime source. Retargeting must be blocked while active jobs exist. The target must survive removal of disposable worktrees.

The periodic Full Plan reconciler and any automatic Attention execution must use the same approved runtime source. No automation may silently execute an older checkout.

### 3.2 Governance convergence

Reproject docs/DEVELOPMENT_PLAN.txt to the actual current baseline. Historical OPEN records remain immutable history, but the current document must identify superseding closure evidence.

Seal PH7 operational completion and Bounded Turn closure without fabricating deployment authority. Merge/main/deployment remain separate operations unless explicitly authorized by their governing gate.

## 4. Diagnostic Intelligence Plane

Add runtime/diagnostics as a read-only subsystem:
- contracts.py: SourceSnapshotBinding, AnalysisEvidenceEnvelope, ContextPack.
- analysis_router.py: choose Graphify, CodeGraph, RCA, or combinations.
- context_fusion.py: bounded evidence/context pack.
- evidence_store.py: digest-bound analyzer evidence.
- security.py: secret/path/output validation.
- adapters/graphify_adapter.py
- adapters/codegraph_adapter.py
- adapters/rca_adapter.py
- orchestrator/diagnostic_context_bridge.py: one-way bridge from orchestration.
## 5. Graphify Adoption

Graphify is on-demand only. Initial production adoption explicitly disables:
- Git hooks;
- watch mode;
- strict/PreToolUse blocking;
- automatic rebuild;
- external semantic API by default.

Outputs must live under Harness-owned analysis workspace, never mutate the source repository. EXTRACTED/INFERRED/AMBIGUOUS edges are evidence classifications, not authorization.

Graphify answers WHERE: relevant modules, files, subsystem boundaries, and candidate topology.

## 6. CodeGraph Adoption

CodeGraph initially runs graph-only/read-only with the narrowest required structural tool allowlist. Disable CodeGraph telemetry. Do not expose memory/admin/docs-mutation tools to workers.

CodeGraph answers WHAT/IMPACT: callers, callees, dependency paths, affected symbols, related tests, entry points, and impact candidates.

Persistent CodeGraph cache is derived state only. Its own DB recovery/quarantine can never become Harness recovery authority. If safe cache-path isolation cannot be proven, initial production mode uses an isolated/ephemeral environment.

## 7. Holmes-Inspired RCA Adoption

Do not install HolmesGPT as a top-level orchestrator, scheduler, provider router, remediation authority, or notifier.

Adopt only bounded diagnostic behaviors:
- explicit investigation task list;
- evidence-to-claim tracing;
- five-whys style causal exploration;
- blast-radius classification;
- temporal correlation is not causation;
- state/snapshot-aware duplicate-tool detection;
- diagnostic-thrashing metrics.

RCA may request Graphify/CodeGraph evidence through the Analysis Router but produces evidence only.
## 8. Source Snapshot and Freshness

Every analyzer result binds:
- project_id, run_id, gate_id, task_id;
- source_root_id;
- git_head_sha;
- workspace_tree_digest;
- owned_scope_digest;
- analyzer + analyzer_version + analysis_mode;
- indexed_at + result_digest.

Mismatch at consumption time yields CODE_INTELLIGENCE_STALE. Stale evidence cannot drive governed action.

During governed WRITE:
1. capture pre-change snapshot;
2. freeze diagnostic graph view;
3. execute approved effect;
4. mark graph evidence stale;
5. run deterministic verification;
6. reindex after the action;
7. perform post-change impact revalidation.

Indexing/watch and governed WRITE must never race.

## 9. Conflict and Scope Rules

Graph results may propose SCOPE_CHANGE_PROPOSAL only. Existing planning/approval authority decides scope changes.

Graphify/CodeGraph disagreement yields GRAPH_CONFLICT and mandatory raw-source verification. Unresolved material conflict blocks the applicable EDP domain.

“No callers/tests found” is never proof of no impact. EDP Negative-Space audit remains mandatory for reflection, dynamic imports, configuration, generated code, external interfaces, and other non-graph-visible paths.
## 10. Failure and Degradation

Diagnostic Intelligence is a zero-regression optional dependency:
- Graphify unavailable -> CodeGraph + existing repo inspection.
- CodeGraph unavailable -> Graphify + existing search/test discovery.
- both unavailable -> existing Harness behavior.
- RCA unavailable -> existing EDP/runtime evidence.

This is graceful degradation of advisory evidence, not fail-open authorization.

Diagnostic failures cannot change Full Plan state or invoke recovery. No new Full Plan states are introduced. Internal analyzer states are CURRENT, STALE, PARTIAL, DEGRADED, CONFLICT, FAILED.

## 11. EDP Extensions

Applicable Code Intelligence domains:
- CI-01 Source Snapshot Binding
- CI-02 Graphify topology coverage
- CI-03 CodeGraph dependency/impact coverage
- CI-04 Graph conflict
- CI-05 related-test/verifier mapping
- CI-06 freshness
- CI-07 security/secret check
- CI-08 fallback validation
- CI-09 post-change impact revalidation

These domains are applicable only when code-intelligence evidence is used.
## 12. Safety Invariants

INV-01 diagnostics cannot modify Full Plan state.
INV-02 diagnostics cannot modify approval state.
INV-03 diagnostics cannot select Provider.
INV-04 diagnostics cannot execute mutation.
INV-05 diagnostics cannot mark Completion.
INV-06 diagnostics cannot resume/retry Full Plan.
INV-07 diagnostics cannot deliver user notification.
INV-08 analyzer evidence must match the current source snapshot.
INV-09 analyzer evidence cannot enlarge approved write scope.
INV-10 graph/cache failure cannot corrupt canonical state.
INV-11 indexing and governed WRITE cannot race.
INV-12 disabling Diagnostic Intelligence restores original Harness behavior.
INV-13 runtime-current must resolve to an existing approved runtime source.
INV-14 automatic recovery and attention must execute the approved runtime generation.
INV-15 current governance projection must not contradict sealed runtime/baseline evidence.

## 13. Rollout

Phase 0: repair runtime-current, runtime-source convergence, governance projection, and add contracts/feature gate with diagnostics disabled.
Phase 1: Graphify + CodeGraph shadow mode; collect freshness/conflict/performance evidence.
Phase 2: PREPARE advisory context after EDP qualification.
Phase 3: VERIFY advisory post-change impact/test mapping.
Phase 4: Holmes-inspired RCA for test/runtime/tool/provider failures.
Phase 5: final operational EDP, failure injection, baseline seal, and controlled runtime activation.
## 14. Required Failure Injection

At minimum:
- broken/stale runtime-current;
- removed worktree target;
- analyzer disabled;
- Graphify process failure;
- CodeGraph process/DB failure;
- stale source SHA/tree digest;
- Graphify/CodeGraph conflict;
- secret-bearing source/output;
- large analyzer output;
- graph request during governed WRITE;
- Full Plan supervisor restart;
- server/reconciler restart path;
- provider failure while diagnostics are active;
- repeated diagnostic queries with no new evidence.

Every case must prove that diagnostic failure does not become control authority failure.

## 15. Final ALL PASS Gate

Final GO is prohibited unless:
- BLOCKER_COUNT=0;
- UNRESOLVED_MAJOR_COUNT=0;
- MUST_REQUIREMENT_COVERAGE=100%;
- MUST_TRACEABILITY_COVERAGE=100%;
- DOMAIN_EVIDENCE_COVERAGE=100%;
- NEGATIVE_SPACE_OPEN_MATERIAL_COUNT=0;
- CROSS_DOCUMENT_CONFLICT_COUNT=0;
- BROKEN_REFERENCE_COUNT=0;
- UNRESOLVED_MATERIAL_TBD_COUNT=0;
- UNRESOLVED_MATERIAL_OPEN_QUESTION_COUNT=0;
- ADVERSARIAL_NEW_BLOCKER_MAJOR=0;
- PASS_CHALLENGE_OPEN_COUNT=0;
- full repository regression, compile, diff checks pass;
- live runtime-current/reconciler/attention paths resolve to the same approved runtime generation;
- Graphify/CodeGraph/RCA disable/failure returns the Harness to the pre-integration behavior;
- final source, runtime, governance, and remote branch bindings are recorded.

Final decision may then be AI_OFFICE_HARNESS_FINAL_OPERATIONAL_BASELINE = ALL_PASS / GO.
