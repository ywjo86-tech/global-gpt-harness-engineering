# OCP + Harness Primary Local Operations Design Contract

Date: 2026-09-23
Base stable OCPv2 SHA: `c591b01e8a1d9d9bb2dc438ca85f6c2ffcc79a03`
Superseded implementation candidate: `impl/read-only-host-diagnostic-20260923` at `e6f90a0`
Revision: TOP-DOWN ARCHITECTURE RECHECK
Status: DESIGN CANDIDATE — implementation not authorized by this document

## 1. Goal

Make OCPv2 + AI Office Harness the normal GPT-to-JARVIS-SERVER operating path and reduce Remote Desktop Commander (RDC) to an optional break-glass, bootstrap, interactive-terminal, and recovery tool.

RDC independence means more than adding `git status`. Normal GPT operation must be possible end-to-end without RDC for:

- bounded local inspection;
- starting an already approved new work package;
- controlling/resuming an existing Full Plan run;
- state-changing work through the canonical Harness execution path;
- status/progress/attention inspection and result retrieval.

OCP remains transport/control, not planner, provider router, shell, or effect runtime.
## 2. Harness operating model — top down

### Layer 0 — Human authority

`USER` owns requirement decisions, approval, scope expansion decisions, and dangerous/high-risk authorization.
No lower layer may synthesize user approval.

### Layer 1 — Interaction and transport

Primary remote GPT path:

```text
ChatGPT / GPT Operator
        ↓
GitHub private control channel
        ↓
OCPv2
```

Local UI path should converge on the same governed control interfaces rather than form a second execution authority.
RDC sits outside this graph as break-glass access.

### Layer 2 — Operating/governance layer

AI Office owns requirement intake, context assembly, workflow state, risk/permission/approval governance, capability-owner routing, recovery coordination, and reporting.
AI Office is an overlay above canonical execution owners. It does not plan tasks, select providers/models, or own effects.

### Layer 3 — Planning and execution coordination

Full Plan remains the sole planning/decomposition/final-assignment/Gate/fan-in authority.
An approved work package becomes a durable Full Plan job only through the existing Harness job-building and registration contracts.

### Layer 4 — Provider selection and provider runtime

```text
Full Plan capability need
        ↓
Multi-Provider Router
        ↓
MPRF provider runtime
```

Router remains the sole provider/model selection authority. OCP and AI Office carry no provider/model fields.

### Layer 5 — Action execution boundary

```text
Full Plan task
   ↓
Production Execution Gateway / Execution Backend Contract
   ↓
Full MCP
```

The gateway owns the governed backend handoff. Full MCP remains action authorization/effect/reconciliation/validation truth.
### Layer 6 — Host primitives

Full MCP already owns bounded filesystem, Git, process and validation implementations for governed execution.
For lightweight remote inspection, Harness may reuse only the already safe read implementations behind a dedicated non-authoritative inspection port.

### Cross-cutting — observability, recovery, attention

- Full MCP and MPRF remain separate canonical observability sources.
- AI Office consumes public runtime observation references; it does not replace them.
- Full Plan owns durable run/recovery/Gate state.
- Production attention is a read/delivery mechanism only and owns no resume or approval authority.
- OCP owns remote transport receipt/replay/result delivery only.

### Out-of-band — RDC

RDC is not an execution layer in the target Harness architecture. It is a recovery access mechanism when OCP, GitHub transport, systemd, Python runtime, or the Harness itself is unavailable.

## 3. Current verified state

Stable OCPv2 `c591b01` polls successfully and can resume an exact registered Full Plan continuation for state-changing directives.
It cannot create a new Full Plan job from a fresh GPT work request.

Non-mutating OCP directives terminate as `READ_ONLY_ACCEPTED`; no live host result is produced.
Full MCP already contains `filesystem_read`, `filesystem_search`, `filesystem_metadata`, `git_status`, `git_diff`, and `git_branch`, backed by `WorkspacePathPolicy`, `FilesystemService`, and `GitService`.

AI Office already contains requirement intake, context assembly, workflow/governance, capability-owner routing, execution coordination and public observability consumption, but there is no OCP→AI Office general work-intake adapter.

`operator_plan_execution.build_operator_plan_job()` and `production_full_plan_entry.register_job()` already define how an approved committed plan/spec becomes a durable Full Plan job. There is no OCP-safe activation adapter around that boundary.

The existing `Jarvis Bridge` can call `OrchestrationEngine` directly and its dashboard read currently writes snapshots/queue/audit artifacts. It must not become a second canonical control or pure-read path.

The newer `operator_console_projection` already establishes the preferable direction: console control intent is normalized into the existing OCPv2 envelope instead of receiving execution authority.

`public_observability_contract` is for Full MCP/MPRF runtime event references. It is not a live host-file/Git inspection API and must not be overloaded for that purpose.

`read_only_inspector` and `production_attention_watch` already provide specialized Harness read models. They should be reused where relevant rather than re-reading internal state ad hoc.

`OnboardingRegistry` already stores validated immutable project alias→project ID→canonical root bindings. A second root registry should not be introduced without a proven gap.

## 4. Top-down request classification

Every OCP request must belong to exactly one semantic class before lower-layer dispatch.
| Class | Purpose | Canonical path | State change |
|---|---|---|---|
| `HOST_INSPECTION` | file/Git/service/Harness state observation | OCP → Harness Host Inspection Port | NO |
| `EXISTING_RUN_CONTROL` | resume/control an already registered exact run | OCP → existing canonical OCP resume/control | control-state only, bounded |
| `APPROVED_WORK_ACTIVATION` | start a new already-approved spec/plan without terminal access | OCP → AI Office/work governance refs → Harness Plan Activation Adapter → registered Full Plan | Harness control-state only |
| `WORK_EXECUTION` | perform approved source/test/Git mutations | registered Full Plan → Router/MPRF → Production Gateway → Full MCP | YES |
| `BREAK_GLASS` | recover when governed path is unavailable | RDC/manual operator | exceptional |

A free-form natural-language request is not itself `APPROVED_WORK_ACTIVATION`. It must first become approved plan/spec evidence under the normal user/design/plan approval process.

This classification closes the prior design gap: host inspection alone cannot make RDC optional if starting an approved new Full Plan job still needs a local terminal.

## 5. Target architecture

```text
USER
  ↓
ChatGPT / GPT Operator
  ↓
OCPv2  ─────────────────────────────────────────────────────┐
  │                                                        │
  ├─ HOST_INSPECTION ──> Harness Host Inspection Port      │
  │                         │                              │
  │                         ├─ FilesystemService READ      │
  │                         ├─ GitService READ            │
  │                         ├─ Harness canonical read models
  │                         └─ fixed UserServiceObserver   │  │                                                        │
  ├─ EXISTING_RUN_CONTROL ──> registered Full Plan resume  │
  │                                                        │
  └─ APPROVED_WORK_ACTIVATION                              │
         ↓                                                 │
     Approved Work Binding Validator                    │
         ↓                                                 │
     AI Office governance / workflow refs                  │
         ↓                                                 │
     Harness Plan Activation Adapter                       │
         ↓                                                 │
     build_operator_plan_job / register_job                │
         ↓                                                 │
     Registered Full Plan <────────────────────────────────┘
         ↓
     Multi-Provider Router
         ↓
     MPRF
         ↓
     Production Execution Gateway
         ↓
     Full MCP
         ↓
     JARVIS-SERVER filesystem / Git / tests / governed process

RDC = out-of-band recovery only
```

The Host Inspection Port and Plan Activation Adapter are not new planners or execution owners. They are narrow Harness adapters around existing canonical capabilities.

## 6. Architectural invariants

```text
OCP_TRANSPORT_CONTROL_AUTHORITY=YES
OCP_PLANNING_AUTHORITY=NO
OCP_PROVIDER_MODEL_AUTHORITY=NO
OCP_PRODUCT_EFFECT_AUTHORITY=NO
HOST_INSPECTION_STATE_CHANGE=NO
HOST_INSPECTION_ARBITRARY_SHELL=NO
AI_OFFICE_PLANNING_AUTHORITY=NO
FULL_PLAN_PLANNING_ASSIGNMENT_GATE_AUTHORITY=YES
MULTI_PROVIDER_ROUTER_SELECTION_AUTHORITY=YES
MPRF_PROVIDER_RUNTIME_AUTHORITY=YES
PRODUCTION_GATEWAY_BACKEND_HANDOFF_AUTHORITY=YES
FULL_MCP_ACTION_EFFECT_AUTHORITY=YES
NEW_EXECUTION_OWNER=NO
RDC_NORMAL_PATH_DEPENDENCY=NO
```

Observation and control results cannot satisfy Full Plan Gate completion, effect evidence, validation, approval, or publication requirements unless the canonical owning runtime separately produces those artifacts.

## 7. Host Inspection Port

Use the term **Host Inspection Port**, not Observation Gateway. `Observability` is already an established AI Office/Full MCP/MPRF event-domain concept; reusing that name would create architectural ambiguity.

Version 1 operations:

| Operation | Implementation | Decision |
|---|---|---|
| `filesystem.read` | `FilesystemService.read` | REUSE |
| `filesystem.search` | `FilesystemService.search` | REUSE |
| `filesystem.metadata` | `FilesystemService.metadata` | REUSE |
| `git.status` | `GitService.status` | REUSE |
| `git.diff` | `GitService.diff` | REUSE |
| `git.branch` | `GitService.branch` | REUSE |
| `harness.inspect` | existing canonical/static read model | REUSE/ADAPT |
| `harness.attention` | `production_attention_watch` read model | REUSE/ADAPT |
| `user_service.properties` | fixed allowlisted `systemctl --user show` adapter | ADD |
The port has a closed operation registry. It does not expose `shell_execute`, process execution, filesystem mutation, Git restore/stage/commit/push, provider/model selection, validation execution, network probing, or arbitrary `systemctl`/journal commands.

### Project/root binding

Do not create an independent OCP roots registry by default.
Resolve project/root IDs from the existing verified `OnboardingRegistry` alias entries and validate the canonical project root again at use time.
If the Harness repository itself requires a special operational root not represented by onboarding, add one explicit system-owned binding rather than a general caller-configurable root list.

### Why service reuse, not production `FullMCPRuntime.call()`

`FullMCPRuntime.call()` is bound to InvocationContext, worker identity, authorization contracts, replay guards and effect/audit semantics. OCP must not fabricate those production bindings merely to obtain a read result.

The Host Inspection Port may compose the same safe read implementations behind its own closed no-effect contract. It must not import `ProcessService` or mutation/publication services.

Do not extract a new shared primitives package in this project unless implementation proves direct reuse impossible; Stable Core Protection favors the additive adapter first.

## 8. Approved Work Activation — missing RDC-independence link

A new approved plan currently can be built into a production job with `build_operator_plan_job()` and registered with `register_job()`, but OCP has no safe remote adapter for this boundary.

The top-down audit found a second gap: AI Office `intake_requirement()` currently requires an injected `approved_register`, and production code has no canonical persistent approved-register implementation or runtime callsite. Tests provide the register directly. The activation design must not invent a second mutable requirement database merely to close OCP transport.

Use a two-step activation boundary:

1. **Approved Work Binding Validator** — pure validation. It derives an immutable, request-local approved binding from existing committed plan/spec/requirement artifacts plus the explicit user approval reference. Where a canonical Full Plan requirement artifact exists, validate it with the existing requirement-artifact dispatcher/contracts rather than defining duplicate requirement semantics. The validator may construct the in-memory approved binding needed by AI Office intake, but it stores no independent source of truth.
2. **Plan Activation Adapter** — bounded Harness control-state mutation. It consumes the validated binding and calls the existing job-build/register contracts.

The activation request accepts only committed, already-approved evidence:

- project ID resolved through the existing project registry;
- approved spec path + SHA-256;
- approved implementation plan path + SHA-256;
- canonical requirement artifact/ref + digest when the approved plan contract requires one;
- explicit user approval reference;
- expected branch/HEAD;
- requested task/Gate IDs;
- runtime release identity;
- unique activation request ID/digest.

Neither step invents a plan, requirement decision, approval, task, provider, model, or editable scope. If required canonical requirement/approval evidence is absent, activation returns `APPROVED_BINDING_REQUIRED`/`PLAN_REQUIRED` and stops.

Activation changes Harness control state, so it requires an explicit activation authorization and create-once replay protection. It is not classified as product/source mutation and it never calls Full MCP directly.

A raw GPT instruction without approved plan/spec evidence cannot be promoted by OCP itself.

## 9. Existing-run control

Keep the current OCP canonical resume path for exact registered jobs.
It already binds continuation state SHA, owner epoch, run identity, source/runtime identity and single execution owner before resume.

Do not generalize this path into new-job creation, arbitrary commands, or host inspection.

The semantic separation is:

```text
new approved work  -> Plan Activation Adapter -> register Full Plan job
existing work      -> current OCP canonical resume
host read          -> Host Inspection Port
product mutation   -> Full Plan -> Gateway -> Full MCP
```

## 10. AI Office boundary

AI Office remains the operating/governance layer for normal new work. OCP transport must not bypass it to create a new business/workflow execution intent.

For `APPROVED_WORK_ACTIVATION`, the Approved Work Binding Validator first anchors the request to canonical committed evidence and explicit user approval. AI Office then consumes only those immutable refs/digests for requirement/workflow/governance coordination; it does not own a second approved-requirement source of truth. The Harness activation adapter handles only mechanical durable Full Plan registration.

For `HOST_INSPECTION`, AI Office workflow creation is not required. A host inspection is a control-plane observation, not an Office business task or Full Plan completion event.
`public_observability_contract` remains dedicated to canonical action/provider runtime event references. Host inspection results must not be inserted into that source-of-truth domain.

## 11. Jarvis / Operator Console convergence

The target architecture permits multiple user interfaces, but only one governed control semantics.

`operator_console_projection.normalize_console_control_request()` already points console control into OCPv2. Preserve that direction.

The legacy Jarvis Bridge must be classified as transitional where it directly instantiates `OrchestrationEngine` for state-changing/control commands. During the later Jarvis Upgrade:

- control commands should normalize to the same OCP/Harness contracts;
- dashboard/status reads should consume canonical read models;
- a nominal GET/status operation should not create queue/snapshot/audit mutations merely to read state;
- Jarvis UI must not become another planner, router, execution gateway or effect owner.

This OCP project does not rewrite the Jarvis UI, but RDC-independent primary-path closure must record the direct-engine bridge as a follow-up compatibility item rather than treating it as the future canonical path.

## 12. Durable result and transport design

Do not create a second independently managed remote outbox state machine if the existing OCP downstream result delivery can be extended safely.

Preferred shape:

1. Host inspection produces a sealed bounded result artifact with request/result digests.
2. Existing OCP downstream delivery/outbox mechanics project the typed result or a sealed result reference.
3. After crash, a sealed result can be re-published without re-running inspection.
4. Legacy `RemoteResultProjectionV1` behavior remains backward-compatible for current mutation/control messages.

If implementation requires a new projection schema, add it as a typed additive version while sharing the same durable delivery lifecycle; do not maintain two unrelated pending/published state machines.
## 13. Remote contract model

Do not overload the existing continuation-oriented `RemoteOperatorEnvelopeV2` with ambiguous free-form fields.
Use an additive typed remote contract/union whose payload kind is explicit and digest-bound.

Minimum shared transport bindings:

- message ID and monotonic sequence;
- issued/expiry timestamps;
- GPT operator actor identity;
- GitHub adapter/channel/source-message identity;
- request kind;
- project identity/root alias where applicable;
- payload digest;
- authorization/reference bindings appropriate to that kind;
- complete envelope digest.

`HOST_INSPECTION` carries one closed inspection operation and closed arguments.
`EXISTING_RUN_CONTROL` preserves current V2 continuation/CAS semantics.
`APPROVED_WORK_ACTIVATION` carries only approved plan/spec/approval/source/runtime bindings.

A request kind cannot be converted into another kind by changing `state_change_required` or another caller boolean.

## 14. OCP modes

| OCP mode | Host inspection | Existing-run mutation/control | Work activation |
|---|---|---|---|
| `DISABLED` | blocked | blocked | blocked |
| `OBSERVE_ONLY` | allowed when inspection feature enabled | blocked | blocked |
| `CONTROL_READ_ONLY` | allowed when inspection feature enabled | blocked | blocked |
| `CONTROL_MUTATION_CANARY` | allowed | existing canary only | blocked unless separately qualified activation canary exists |
| `ACTIVE` | allowed | existing canonical rules | allowed only with activation feature + exact authorization |

Legacy V2 read-only messages keep their current `READ_ONLY_ACCEPTED` behavior. New host inspection behavior is additive and typed.
## 15. Duplicate / conflict / gap audit

| Area | Finding | Decision |
|---|---|---|
| custom OCP filesystem reader | duplicates `FilesystemService` + `WorkspacePathPolicy` | REPLACE with reuse |
| custom OCP Git runner/status/diff/branch | duplicates `GitService` safety and behavior | REPLACE with reuse |
| separate OCP root allowlist | overlaps verified project onboarding registry | REPLACE with registry-derived binding |
| AI Office injected `approved_register` as production source | tests-only input has no canonical runtime source | DO NOT PERSIST NEW REGISTER; derive request-local binding from approved canonical artifacts |
| separate diagnostic outbox lifecycle | overlaps OCP durable downstream result delivery | ABSORB into one delivery lifecycle |
| Host Inspection named “Observability Gateway” | collides conceptually with AI Office runtime observability domain | RENAME to Host Inspection Port |
| OCP direct `FullMCPRuntime.call()` | would require synthetic production authority | PROHIBIT |
| OCP arbitrary shell | bypasses Harness action policy | PROHIBIT |
| OCP new-job creation by extending resume | conflates existing-run CAS with activation | PROHIBIT; add Plan Activation Adapter |
| Jarvis Bridge direct `OrchestrationEngine` control | parallel long-term control path | FOLLOW-UP MIGRATION to common contracts |
| Jarvis status read writing snapshots/queues/audit | violates intuitive pure-read semantics | FOLLOW-UP separation of read model from projection persistence |
| AI Office public observability used for host files | wrong source domain | KEEP SEPARATE |
| `read_only_inspector` reimplementation | existing specialized Harness read model | REUSE where suitable |
| `production_attention_watch` reimplementation | existing stall/attention read model | REUSE |
| Full MCP mutation path | already canonical | KEEP |
| OCP canonical existing-run resume | already single-owner bounded | KEEP |

## 16. Stopped READ_ONLY_HOST_DIAGNOSTIC mapping

| Stopped implementation element | Revised disposition |
|---|---|
| typed request/correlation/status/result classes | ABSORB into typed Host Inspection contract |
| feature flag / fail-closed loader | KEEP concept |
| standalone roots config | REPLACE with verified project registry binding where possible |
| byte/line/time limits | ABSORB into inspection contract + reused service bounds |
| secret/content redaction | KEEP at remote projection boundary |
| custom file-range fd traversal | REPLACE with `FilesystemService.read` + bounded post-processing |
| custom metadata implementation | REPLACE with `FilesystemService.metadata` |
| custom Git runner | REPLACE with `GitService` |
| custom Git env/allowlist | DELETE after equivalent reuse tests pass |
| fixed systemd property reader | ABSORB as `UserServiceObserver` |
| typed remote diagnostic envelope | ABSORB into additive typed remote request union |
| separate diagnostic outbox | REPLACE with shared OCP result-delivery lifecycle |
| arbitrary shell prohibition | KEEP |
| direct Full MCP call prohibition | KEEP |
## 17. Security and failure behavior

- All new features are OFF by default and fail closed on missing/unsafe bindings.
- Callers use registered project identity/alias; never arbitrary absolute host paths.
- Symlink and sensitive-path policy remains enforced by `WorkspacePathPolicy`.
- Host Inspection accepts no executable, argv fragment, environment override, network destination, provider/model, raw secret path, or mutable operation.
- User service inspection accepts only explicitly allowed user units and a fixed property list.
- Plan Activation accepts only committed approved plan/spec artifacts with exact digests, source identity and explicit approval ref.
- Activation is create-once/idempotent; conflicting reuse of an activation request ID is blocked.
- Existing-run control retains exact continuation CAS and single execution-owner requirements.
- Result content is bounded and secret-scanned before durable remote publication.
- Failure in Host Inspection cannot fall through to shell or Full MCP mutation.
- Failure in Plan Activation cannot silently use Manual Action or RDC.
- Recovery never synthesizes approval or changes request kind.

## 18. Normal operating flows

### A. Quick local inspection

```text
GPT
 -> OCP HOST_INSPECTION
 -> Host Inspection Port
 -> verified project registry/root
 -> reused safe read primitive
 -> sealed bounded result
 -> OCP durable result delivery
 -> GPT
```

### B. Start a new approved work package

```text
User-approved spec/plan
 -> GPT/OCP APPROVED_WORK_ACTIVATION
 -> AI Office governance/workflow reference validation
 -> Plan Activation Adapter
 -> existing build_operator_plan_job / register_job
 -> durable Full Plan run
```

No terminal/RDC step is required in the target state.
### C. Execute state-changing work

```text
Registered Full Plan
 -> planning/decomposition/final assignment/Gate
 -> Multi-Provider Router
 -> MPRF
 -> Production Execution Gateway
 -> Full MCP
 -> filesystem/Git/test governed effects
 -> canonical evidence
```

OCP controls or resumes the run but does not perform the effect.

### D. Observe progress / stall / attention

Use canonical Full Plan read models, operator-console projection and production attention watcher through typed inspection/status projections. Do not infer state from process lists or mutable dashboard snapshots when canonical state exists.

### E. Break-glass recovery

```text
OCP/GitHub/Harness unavailable
 -> RDC / manual terminal
 -> diagnose / repair / restore governed primary path
 -> return to OCP + Harness
```

RDC is not a silent fallback for failed normal requests.

## 19. RDC-independent acceptance gates

RDC is optional only after all of the following are proven without RDC participating in the tested path:

1. OCP receives and returns `filesystem.read`, search and metadata results from a registered project.
2. OCP returns real `git.branch`, `git.status` and bounded `git.diff` results.
3. OCP returns canonical Harness run/status and pending-attention information without mutating product state.
4. OCP returns allowlisted user-service health.
5. An already approved spec/plan/required requirement evidence is validated through the Approved Work Binding Validator and activated into a registered Full Plan job without local terminal commands.
6. A fresh unapproved/free-form work request cannot activate execution and returns a plan/approval-required disposition.
7. An existing registered run can be resumed through current OCP CAS/single-owner controls.
8. A controlled state-changing canary performs an actual bounded file/source effect through Full Plan -> Gateway -> Full MCP only.
9. Focused validation/test execution occurs through the existing governed execution path, not Host Inspection.
10. Crash/replay republishes sealed host-inspection/control results without duplicating effects or activation.
11. OCP V2 compatibility regression remains green and legacy read-only messages still project `READ_ONLY_ACCEPTED`.
12. Router/MPRF/Production Gateway/Full MCP authority regressions remain green.
13. No new direct provider/model selection, Full MCP production-call bypass, arbitrary shell, second execution owner, or approval bypass exists.
14. The tested path can be completed with RDC disconnected or unavailable.

Only after Gate 1~14 PASS may operating documentation label RDC `OPTIONAL_RECOVERY` rather than `NORMAL_DEPENDENCY`.

## 20. Migration sequence

Phase A — preserve the stopped `e6f90a0` implementation branch as evidence. Do not continue it task-by-task.

Phase B — implement the Host Inspection Port first, feature OFF, reusing project registry and safe read primitives.

Phase C — add typed remote request/result support and unify with existing OCP durable delivery; keep legacy V2 behavior unchanged.

Phase D — qualify host inspection end-to-end with no mutation and no RDC evidence.

Phase E — implement the pure Approved Work Binding Validator and the Plan Activation Adapter around existing canonical requirement-evidence and approved-plan job build/register contracts, feature OFF.

Phase F — qualify new approved-work activation, existing-run control and state-changing Full Plan execution as separate paths.

Phase G — run broad authority/security/recovery regressions and successor-runtime qualification.

Phase H — explicit user activation approval; enable bounded features incrementally.

Phase I — perform the complete RDC-independent acceptance gate.

Phase J — later Jarvis Upgrade aligns legacy direct-engine UI/control paths with the common OCP/Harness contracts. Do not fold unrelated Jarvis UI rewrite into this OCP implementation.

## 21. Rollback

Rollback is feature-OFF first.
Retain stable OCP runtime `c591b01` and the existing rollback runtime during migration.
Host Inspection and Plan Activation have separate feature flags so one can be disabled without changing the canonical existing-run mutation path.

No rollback step may make RDC a required steady-state dependency; RDC may be used only to perform the recovery itself when the governed path is unavailable.
## 22. Non-goals

This design does not add:

- arbitrary host shell or arbitrary subprocess execution through OCP;
- sudo/root or privilege escalation;
- GUI automation;
- free-form `systemctl`, journal, network or process inspection;
- provider/model selection outside Router;
- a second Full Plan or a second execution owner;
- direct OCP production `FullMCPRuntime.call()` authority;
- automatic synthesis of plans/specs/approvals from a remote execution request;
- Jarvis UI redesign in the same implementation project;
- RDC uninstall/removal.

A new host read capability must be a typed, allowlisted operation with an identified canonical source/implementation and negative-space tests.

## 23. Top-down EDP verdict

`GO_WITH_ARCHITECTURE_REVISION`

The original Observation Gateway redesign correctly identified the missing host-read path and the duplicate filesystem/Git implementation risk, but it was not sufficient to make RDC truly optional.

The top-down audit adds the missing **Approved Work Activation** link and its request-local **Approved Work Binding Validator**, removes naming collision with existing Observability, reuses the project onboarding registry, avoids both a second requirement source-of-truth and a second durable result-delivery lifecycle, explicitly separates new-work activation from existing-run resume, and records the legacy Jarvis direct-engine path as a later convergence item.

The target steady-state rule is:

```text
OCP = governed remote ingress/control transport
AI Office = operating/governance layer for new work
Full Plan = planning/assignment/Gate/continuation authority
Router + MPRF = provider selection/runtime
Production Gateway = governed execution handoff
Full MCP = product/host effect authority
Host Inspection Port = no-effect bounded local inspection only
RDC = optional break-glass recovery
```

Implementation remains blocked until this revised written design is reviewed and approved. After approval, replace the superseded implementation plan with a fresh Full Plan Hybrid plan derived from this architecture.