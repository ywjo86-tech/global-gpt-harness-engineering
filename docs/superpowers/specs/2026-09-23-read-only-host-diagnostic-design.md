# READ_ONLY_HOST_DIAGNOSTIC Design Contract

**Status:** APPROVED — EDP DESIGN-CONTRACT ALL PASS  
**Protocol:** `EXHAUSTIVE_DIAGNOSIS_PROTOCOL (EDP-1.0)`  
**Baseline:** `FA6_STABLE_BASELINE=PASS`  
**Bound source/runtime:** `c591b01e8a1d9d9bb2dc438ca85f6c2ffcc79a03`  
**Binding gate:** `BINDING_GATE-R01=PASS` on 2026-09-23  
**Implementation:** NOT STARTED

## Goal

Allow JARVIS / GPT Operator to inspect bounded project and user-service state on JARVIS-SERVER through a typed read-only diagnostic capability without changing existing AI Office Harness execution authorities.

The capability exists to remove recurring manual copy/paste for safe diagnostics such as Git worktree state, bounded file inspection, path metadata, and selected user-service health.

## Authority invariants

```text
OCP_EXECUTION_AUTHORITY=NO
FULL_PLAN_ASSIGNMENT_AUTHORITY=YES
ROUTER_PROVIDER_MODEL_AUTHORITY=YES
DIAGNOSTIC_PROVIDER_MODEL_AUTHORITY=NO
DIRECT_FULL_MCP_BYPASS=NO
ARBITRARY_HOST_SHELL=NO
NEW_EXECUTION_OWNER=NO
HOST_MUTATION=NO
FA6_BASELINE_MUTATION=NO
```

OCPv2 remains a bounded, non-authoritative transport/control-plane. State-changing work continues to return to the existing registered Full Plan path, Provider Router, Production Execution Gateway and Full MCP. The exact `c591b01` source confirms that `CONTROL_READ_ONLY` is already a non-mutating OCP mode and that the current service does not execute read-only directives; it only projects `READ_ONLY_ACCEPTED`. The diagnostic feature therefore extends the existing **observation** path only. It must not claim Full Plan execution ownership, create a second execution owner, or create a side-effect path.

This source-binding refinement is permitted by the approved EDP contract: verified canonical source wins over a pre-binding implementation assumption, and no parallel authority path may be created to preserve an assumption.

## In scope

1. `repo.snapshot`
2. `project.file_range`
3. `path.metadata`
4. `user_service.properties`
5. Typed request validation
6. Registered-root and allowlisted-service configuration
7. Summary/content result classification
8. Provenance, freshness, correlation, truncation, redaction and explicit error semantics
9. Durable, replay-safe read-only result projection
10. Feature-gated rollout and rollback
11. Focused, adversarial and regression tests

## Out of scope

- arbitrary shell or caller-supplied argv
- file/source mutation
- `sudo` / root / privilege escalation
- service start/stop/restart/reload/enable/disable/daemon-reload
- journal passthrough
- general network diagnostics
- provider/model selection by the diagnostic capability
- direct Full MCP invocation from OCP/JARVIS
- raw secrets, `.env`, token/key/credential files
- unbounded source/diff dumps
- new execution-owner class

## Typed operations

### `repo.snapshot`

Returns a bounded Git worktree snapshot for one registered root:

- root/repository identity
- branch or detached state
- HEAD
- upstream existence
- ahead/behind when defined
- staged, unstaged and untracked paths
- bounded diff stat and name-status
- `git diff --check` result
- linked-worktree/submodule indicators when available without network access
- capture time / freshness

Detached HEAD, no upstream, unborn repository and non-Git roots are structured states. No value is invented.

### `project.file_range`

Reads only an approved text range under a registered root.

Required controls:

- caller supplies `root_id`, never an arbitrary absolute root
- canonical containment
- symlink-escape prevention
- special-file rejection
- binary default deny
- maximum line and byte counts
- timeout / encoding policy
- sensitive-path deny policy
- secret scan/redaction before result return
- TOCTOU-resistant open-beneath semantics

### `path.metadata`

Returns bounded metadata for a path under a registered root, subject to the same containment and sensitive-path rules.

Allowed examples: existence, file type, size, mtime, safe mode class, canonical relative path.

### `user_service.properties`

Reads only strict allowlisted user-level service properties such as:

```text
ActiveState
SubState
Result
ExecMainStatus
InvocationID
```

Use a structured property read. Free-text `systemctl status`, journal output and every lifecycle verb are prohibited.

## Git safety contract

`GIT_OPTIONAL_LOCKS=0` is useful but is not the safety boundary.

Required:

```text
NO arbitrary Git subcommand
NO caller-defined Git flags
NO shell=True
NO prompt
NO pager
NO external diff helper
NO textconv helper
NO credential-helper invocation
NO network fetch/pull/push
SANITIZED Git environment/config
FIXED registered cwd
TIMEOUT
OUTPUT SIZE CAP
```

Read-only repository diagnostics must not intentionally mutate source, index, worktree or service state.

## Result classes

### `DIAG_SUMMARY`

Sanitized operational metadata suitable for the private OCP control/evidence projection. Pathnames and filenames are classified; metadata is not automatically non-sensitive.

### `DIAG_CONTENT`

Bounded source/diff snippets only. Requires the private control result path, secret scan/redaction, size cap and path classification. Raw sensitive values must never be persisted in transport receipts/audit metadata.

## Result envelope

Each diagnostic result carries:

```text
request_id
correlation_id
project_id
root_id
execution_owner
operation_id
authorization_decision
captured_at
freshness
source_sha
runtime_sha
data_class
redaction_applied
truncated
payload_hash
status
error_class
payload
```

Allowed status values:

```text
OK
PARTIAL
STALE
UNAVAILABLE
BLOCKED
ERROR
```

`STALE`, `UNAVAILABLE`, `BLOCKED` and `ERROR` may never be promoted to PASS. `PARTIAL` may never be represented as complete evidence.

## Remote contract evolution

Existing `orchestration.remote-operator-envelope.v2` mutation and non-diagnostic behavior must remain backward-compatible.

A diagnostic request requires an additive, typed remote contract. The implementation must not encode paths/operations as free-form shell text or overload provider/model fields. A new schema version or dedicated typed extension must bind the diagnostic request into the envelope digest while preserving existing V2 validation for current producers.

A read-only request is valid only when:

- `state_change_required == false`
- the declared capability is `read_only_host_diagnostic`
- the typed request validates exactly
- OCP mode is `CONTROL_READ_ONLY` or `ACTIVE`
- feature flag is enabled
- registered root/service policy authorizes the target

Without a typed diagnostic request, current `READ_ONLY_ACCEPTED` behavior remains unchanged.

## Durable result / replay behavior

A diagnostic result must be sealed before transport publication and must be recoverable after a crash between local completion and remote projection. Exact replay of a sealed request must not re-run an unbounded diagnostic or lose the prior result. Transport receipts remain non-authoritative bookkeeping.

Diagnostic result durability must be separate from canonical mutation completion evidence; a diagnostic result is observational evidence, not a Full Plan completion claim.

## Configuration and rollout

The feature is additive and OFF by default.

```text
FEATURE_READ_ONLY_HOST_DIAGNOSTIC=OFF
```

Configuration must contain registered `root_id → canonical path` mappings, allowlisted user services and fixed bounds. The config path itself must be absolute, regular, non-symlink, owner-controlled, and validated fail-closed.

Activation requires:

1. exact source/runtime binding PASS
2. unit tests PASS
3. security/property tests PASS
4. integration tests PASS
5. adversarial tests PASS
6. regression tests PASS
7. FA6 invariant checks PASS
8. rollback evidence prepared
9. explicit activation decision

Rollback is feature-OFF plus additive revision rollback if needed. Existing `c591b01` runtime and the retained `e74c1ce` rollback runtime must not be deleted by this feature.

## EDP verdict

Round 1 diagnosis found 2 blockers, 12 major findings and 2 medium findings. The corrected design closed exact-source proof, authority ownership, canonical containment, Git helper risk, service-output leakage, metadata sensitivity, result/provenance semantics, stale/partial semantics, adversarial coverage, provider authority, and rollout/rollback gaps.

Final design-scope result:

```text
EDP_REDIAGNOSIS=ALL_PASS
HARSH_PASS=PASS
BLOCKER_COUNT=0
UNRESOLVED_MAJOR_COUNT=0
MUST_REQUIREMENT_COVERAGE=100%
DOMAIN_EVIDENCE_COVERAGE=100%_WITHIN_LOCKED_DESIGN_SCOPE
```

This is a design-contract verdict only. It does not claim implementation or runtime qualification.

## BINDING_GATE-R01 evidence

Live JARVIS-SERVER verification after correcting a stale `OCP_REPO_ROOT` binding established:

```text
OCP_REPO_ROOT=/home/ywjo/AI-Workspace/runtime/ocpv2-r2-c591b01
OCP_HEAD=c591b01e8a1d9d9bb2dc438ca85f6c2ffcc79a03
OCP_WORKING_DIRECTORY=/home/ywjo/AI-Workspace/runtime/ocpv2-r2-c591b01
OCP_RESULT=success
OCP_EXEC_MAIN_STATUS=0
FULL_PLAN_RUNTIME=/home/ywjo/AI-Workspace/runtime/ocpv2-r2-c591b01
FULL_PLAN_HEAD=c591b01e8a1d9d9bb2dc438ca85f6c2ffcc79a03
BINDING_GATE-R01=PASS
```

The old runtime `/home/ywjo/AI-Workspace/runtime/ocpv2-r2-e74c1ce` remains rollback evidence and is not part of the active binding.
