# OCP Observation Gateway Design Contract

Date: 2026-09-23
Base stable OCPv2 SHA: `c591b01e8a1d9d9bb2dc438ca85f6c2ffcc79a03`
Superseded implementation candidate: `impl/read-only-host-diagnostic-20260923` at `e6f90a0`
Status: DESIGN CANDIDATE — implementation not authorized by this document

## 1. Goal

Make OCPv2 + AI Office Harness the normal GPT-to-JARVIS-SERVER control path while reducing Remote Desktop Commander (RDC) to an optional manual diagnostics, bootstrap, interactive-terminal, and recovery tool.

Normal operation must continue when RDC is unavailable or its quota is exhausted. GPT must be able to inspect approved local project state through OCP without arbitrary shell access, and all state-changing work must continue through the existing Full Plan execution authority.

Success means:

- local project file read/search/metadata works through OCP + Harness;
- Git status/diff/branch works through OCP + Harness;
- approved user-service health can be inspected through OCP + Harness;
- file writes, patches, tests, Git mutation/publication and other effects still flow through Full Plan -> Provider Router -> Production Execution Gateway -> Full MCP;
- RDC is not on the normal-path dependency chain;
- OCP gains no arbitrary shell, provider selection, Full Plan assignment, or second execution-owner authority.

## 2. Current verified state

Stable OCPv2 `c591b01` is active through its systemd timer and polls successfully in `ACTIVE` mode. State-changing directives can resume the registered Full Plan path.
However, non-mutating directives currently terminate as `READ_ONLY_ACCEPTED`; they do not execute a host observation and do not return live project state.

Full MCP already contains bounded read-only services and operation definitions for `filesystem_read`, `filesystem_search`, `filesystem_metadata`, `git_status`, `git_diff`, `git_branch`, `execution_status`, and `validate`. Its `WorkspacePathPolicy`, `FilesystemService`, and `GitService` already enforce canonical roots, scopes, symlink rejection, sensitive-path policy, bounded Git arguments, `--no-ext-diff`, `--no-textconv`, prompt suppression, and output limits.

The stopped `READ_ONLY_HOST_DIAGNOSTIC` branch began implementing a parallel filesystem/Git diagnostic stack. It also contains useful typed request/result/config work and a bounded systemd reader. Its focused test suite is not currently green: `tests/test_read_only_host_diagnostic.py` has a syntax error at the stopped head.

## 3. EDP diagnosis

### EDP-01 — Capability gap: CONFIRMED

OCP needs an actual observation result path. `READ_ONLY_ACCEPTED` is insufficient for RDC-independent operation.

### EDP-02 — Duplicate implementation risk: CONFIRMED

Reimplementing file metadata, path guards, Git status/diff/branch, and output bounds inside OCP duplicates stable Full MCP behavior and creates policy drift risk.

### EDP-03 — Authority bypass risk: CONFIRMED

Calling the production `FullMCPRuntime.call()` from OCP with synthetic Full Plan invocation authority would blur existing authorization and execution ownership. OCP must not forge a production job context merely to read state.

### EDP-04 — Reuse opportunity: CONFIRMED

The safe boundary is to reuse Full MCP's read-only service implementations and path policy behind a separate Harness-owned observation gateway, not to expose Full MCP wholesale and not to duplicate its implementations.
## 4. Architectural invariants

```text
OCP_EXECUTION_AUTHORITY=NO
OCP_OBSERVATION_REQUEST_AUTHORITY=YES
FULL_PLAN_ASSIGNMENT_AUTHORITY=UNCHANGED
PROVIDER_ROUTER_AUTHORITY=UNCHANGED
PRODUCTION_GATEWAY_AUTHORITY=UNCHANGED
FULL_MCP_MUTATION_AUTHORITY=UNCHANGED
ARBITRARY_HOST_SHELL=NO
DIRECT_PRODUCTION_FULL_MCP_CALL_FROM_OCP=NO
NEW_EXECUTION_OWNER=NO
RDC_NORMAL_PATH_DEPENDENCY=NO
```

Observation results are evidence only. They cannot satisfy Full Plan completion, Gate completion, approval, validation, mutation, or publication requirements.

## 5. Target architecture

```text
GPT / JARVIS
    |
    v
OCPv2 GitHub control transport
    |
    +---------------- read-only ----------------+
    |                                            |
    v                                            |
Harness Observation Gateway                     |
    |                                            |
    +-- closed read-only operation registry      |
    +-- WorkspacePathPolicy                      |
    +-- Full MCP FilesystemService reuse         |
    +-- Full MCP GitService reuse                |
    +-- bounded UserServiceObserver              |
    +-- result redaction / limits / provenance   |
    +-- durable observation outbox               |
    |                                            |
    +---------------- result --------------------+
    |
    +---------------- mutation -----------------> Registered Full Plan
                                                   -> Provider Router
                                                   -> Production Execution Gateway
                                                   -> Full MCP
```
## 6. Observation operation model

The gateway exposes only a closed typed registry. Version 1 contains:

| Observation operation | Reused implementation | Notes |
|---|---|---|
| `filesystem.read` | `FilesystemService.read` | bounded bytes; optional gateway line slicing after safe read |
| `filesystem.search` | `FilesystemService.search` | registered project root only |
| `filesystem.metadata` | `FilesystemService.metadata` | optional SHA-256 |
| `git.status` | `GitService.status` | no mutation |
| `git.diff` | `GitService.diff` | bounded, no external diff/textconv |
| `git.branch` | `GitService.branch` | local HEAD/branch only |
| `user_service.properties` | new `UserServiceObserver` | fixed `systemctl --user show` property allowlist |

No generic subprocess operation exists. No operation accepts arbitrary executable names, argv fragments, environment variables, absolute roots, provider names, models, network destinations, or shell text.

`execution_status` and `validate` remain Full MCP/Full Plan concepts and are not exposed in Observation Gateway v1 unless a later use-case proves they are required.

## 7. Why the gateway reuses services, not `FullMCPRuntime.call()`

Production `FullMCPRuntime.call()` is intentionally bound to `InvocationContext`, authorization contracts, registered worker identity, replay guards, observability and effect evidence. Creating synthetic job authority for a read-only OCP request would weaken the meaning of those controls.

The Observation Gateway therefore imports and composes the same safe implementation primitives (`WorkspacePathPolicy`, `FilesystemService`, `GitService`) under its own closed observation contract. It never imports mutation services, `ProcessService`, publication operations, validation execution, or production completion logic.
## 8. KEEP / ABSORB / REPLACE / DELETE mapping

| Existing stopped work | Decision | Destination / rationale |
|---|---|---|
| typed request IDs, correlation IDs, status/result classes | KEEP | retain in observation contract |
| fail-closed feature/config loader | KEEP | rename/generalize for Observation Gateway |
| registered-root allowlist concept | ABSORB | map to `WorkspacePathPolicy` read scopes |
| output byte/line/time limits | ABSORB | gateway contract + existing service bounds |
| secret/content redaction before transport | KEEP | projection boundary defense-in-depth |
| `read_project_file_range()` custom fd traversal | REPLACE | `FilesystemService.read()` + post-read bounded line selection |
| `read_path_metadata()` custom implementation | REPLACE | `FilesystemService.metadata()` |
| `collect_repo_snapshot()` custom Git runner | REPLACE | compose `GitService.status()`, `branch()`, optional `diff()` |
| custom `_git_environment()` and Git command allowlist | DELETE after replacement | existing `GitService` owns safe Git execution |
| `read_user_service_properties()` | ABSORB | new narrow `UserServiceObserver` with same fixed-property idea |
| V3 typed remote diagnostic envelope concept | ABSORB | rename to typed observation extension; keep V2 compatibility |
| durable diagnostic outbox concept | KEEP | rename `remote_observation_outbox`; replay result, never re-execute mutation |
| direct OCP diagnostic implementation ownership | REPLACE | OCP calls Harness Observation Gateway callback only |
| direct Full MCP invocation from OCP prohibition | KEEP | remains an invariant |
| arbitrary shell prohibition | KEEP | remains an invariant |

No stopped implementation file is deleted until equivalent functionality is green and review evidence proves the replacement. The stopped branch remains historical evidence until final closure.

## 9. Request and result contracts

A typed observation request binds at minimum:

- schema version;
- request/correlation ID and monotonic transport sequence;
- project/root ID selected from server configuration;
- one closed operation ID;
- closed operation-specific arguments;
- `state_change_required=false`;
- request digest included in the remote envelope digest.
The durable result binds:

- exact request digest and transport identity;
- observed stable runtime/source identity;
- operation ID and project/root ID;
- status: `OK`, `PARTIAL`, `STALE`, `UNAVAILABLE`, `BLOCKED`, or `ERROR`;
- bounded/redacted data and data class;
- result digest, creation time and freshness metadata;
- publication state for crash-safe replay.

A restart may republish a sealed observation result but must not silently substitute a newer observation for the original request.

## 10. OCP mode behavior

| OCP mode | typed observation | state-changing directive |
|---|---|---|
| `DISABLED` | blocked | blocked |
| `OBSERVE_ONLY` | allowed if feature enabled | blocked |
| `CONTROL_READ_ONLY` | allowed if feature enabled | blocked |
| `CONTROL_MUTATION_CANARY` | allowed if feature enabled | existing canary rules unchanged |
| `ACTIVE` | allowed if feature enabled | existing canonical Full Plan resume unchanged |

Legacy V2 non-diagnostic read-only behavior remains `READ_ONLY_ACCEPTED`. The new behavior is additive through a typed observation envelope so current producers remain backward-compatible.

## 11. Security and failure behavior

- Feature is OFF by default and fails closed on missing/unsafe configuration.
- Only canonical absolute configured roots may be registered; callers submit root IDs, never host paths.
- Symlink traversal and sensitive paths remain governed by `WorkspacePathPolicy`.
- Observation Gateway must have no import or call path to `ProcessService`, filesystem mutation, Git restore/stage/commit/push, validation execution, provider selection, or completion authority.
- `UserServiceObserver` accepts only allowlisted `.service` unit IDs and a fixed property list; no journal passthrough or service mutation.
- Output is bounded before durable storage and transport publication.
- Secrets are redacted at the projection boundary even if lower layers also block sensitive paths.
## 12. Normal operating flows

### Read-only flow

```text
GPT -> GitHub control request -> OCP ingress/receipt validation
    -> typed Observation Gateway request
    -> closed operation registry
    -> shared safe service implementation
    -> bounded/redacted result
    -> durable observation outbox
    -> GitHub result projection -> GPT
```

### State-changing flow

```text
GPT -> GitHub control request -> OCP ingress
    -> registered Full Plan continuation
    -> existing approval / authority / Provider Router
    -> Production Execution Gateway
    -> Full MCP
    -> canonical result / evidence
```

The two paths must remain distinguishable in audit data and cannot be converted into each other by caller-controlled fields.

## 13. RDC role after rollout

RDC is explicitly outside the primary dependency graph. It remains useful for:

- bootstrap when OCP/Harness itself is not reachable;
- emergency manual inspection and repair;
- interactive TTY/REPL workflows that do not fit bounded remote operations;
- recovery from GitHub control, systemd, Python runtime, or network failure;
- implementation and diagnostics during migration until the RDC-free acceptance gate passes.

Loss of RDC must not stop ordinary file inspection, Git inspection, or approved Full Plan execution.
## 14. Qualification and acceptance gates

Implementation is not complete until all of the following pass:

1. Contract tests reject unknown operations, caller paths, shell text, arbitrary argv, provider/model fields and `state_change_required=true` on observation requests.
2. Reused filesystem tests prove scope, symlink, sensitive-path and output-limit behavior remains equivalent to stable Full MCP.
3. Reused Git tests prove status/diff/branch cannot invoke external diff/textconv, prompts, hooks, network, write operations or publication.
4. User-service tests prove only fixed allowlisted properties can be read and no service action or journal command can run.
5. OCP V2 regression proves legacy `READ_ONLY_ACCEPTED` behavior is unchanged.
6. OCP mutation regression proves CANARY/ACTIVE state-changing work still has exactly one execution owner and enters the registered Full Plan path only.
7. Crash/replay tests prove a sealed observation result is republished without rerunning or mutating host state.
8. Full OCP/Harness regression passes with zero new failures.
9. Live successor-runtime qualification passes with the observation feature OFF before activation.
10. Live feature activation is separately approved and begins with bounded smoke requests only.

### RDC-independent final acceptance

The final operating gate must be executed without using RDC for the tested path. Through GPT -> GitHub control -> OCP -> Harness only, prove:

- `git.branch` returns the actual branch and HEAD;
- `git.status` returns actual clean/dirty state;
- `git.diff` returns a bounded real diff when one exists;
- `filesystem.read` returns an approved file;
- `filesystem.metadata` returns actual metadata;
- `filesystem.search` returns bounded project matches;
- `user_service.properties` returns OCP service health;
- an approved state-changing canary still goes through Full Plan and yields canonical evidence.

RDC may remain online during early development, but it must not participate in or supply evidence for this final gate.

## 15. Migration strategy

Phase A — freeze current stopped implementation branch and preserve `e6f90a0` as evidence.

Phase B — implement Observation Gateway on a new branch from stable `c591b01`; port only KEEP/ABSORB pieces.
Phase C — wire additive typed observation transport, durable outbox and OCP callback while keeping feature OFF.

Phase D — focused/adversarial/full regression, code review and successor-runtime qualification.

Phase E — explicit activation gate, bounded read-only canary, then RDC-independent acceptance.

Phase F — only after acceptance, update operating documentation to classify RDC as optional recovery tooling. Do not uninstall RDC as part of this project.

## 16. Rollback

Rollback is feature-OFF first. Stable runtime `c591b01` and retained rollback runtime must remain intact during rollout. If the observation path fails, disable its feature flag and revert to stable OCP behavior without changing the mutation path.

RDC remains available as a recovery tool during rollout, but rollback must not make RDC a required steady-state dependency.

## 17. Non-goals

This project does not add arbitrary host shell, sudo/root access, GUI automation, free-form systemctl, journal passthrough, arbitrary process inspection, network probing, provider selection, direct Git publication, or a second general-purpose execution engine.

If a later workflow genuinely needs another read-only host capability, it must be added as a new typed allowlisted observation operation with its own tests rather than by opening shell access.

## 18. EDP final verdict

`GO_WITH_REDESIGN`

The business/operational need is real: without a real read-only result path, OCP cannot make RDC optional. The stopped implementation should not continue unchanged because it duplicates stable Full MCP safety code. The correct remediation is a Harness-owned Observation Gateway that reuses Full MCP read-only service implementations while preserving OCP as a non-authoritative control/transport plane and preserving Full Plan as the sole state-changing execution authority.

Implementation remains blocked until this written design is reviewed and approved. After approval, create a fresh implementation plan; do not resume the superseded 997-line plan task-by-task.
