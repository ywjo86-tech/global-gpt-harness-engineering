# Governed Successor Release Stage Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the P2-only `SUCCESSOR_RELEASE_STAGE` capability so OCP can admit an exact reviewed successor release, route mutation through the Production Execution Gateway and a bounded Full MCP port, fast-forward only an already-registered isolated successor workspace, stage only the disabled `lifecycle-v2-p2` service artifacts, and emit immutable replay-safe evidence without disturbing serving OCP.

**Architecture:** Extend the typed OCP remote-control seam with one new request kind, but keep authority asymmetric: OCP validates/admission-routes, `production_execution_gateway.py` enforces the dedicated capability envelope, `SuccessorReleaseStager` owns the transaction, and a narrow `SuccessorReleaseFullMcpPort` is the only mutation dependency. Reuse the immutable `OnboardingRegistry` for alias-to-canonical-root identity and the existing successor-only `stage_user_service()` deployment primitive; do not put release synchronization into onboarding or host inspection. DRY_RUN is observation-only; STAGE acquires a successor lock, revalidates state, performs one request-scoped fetch and fast-forward, stages disabled artifacts, verifies serving preservation/disabled state, and writes immutable receipts.

**Tech Stack:** Python 3.12 standard library, `unittest`/`pytest`, Git CLI through a fixed bounded adapter, existing OCPv2 remote-control contracts, existing Production Execution Gateway, existing OCPv2 deployment bootstrap, JSON/SHA-256/fsync/atomic-create audit artifacts.

**Spec:** `docs/superpowers/specs/2026-09-25-successor-release-stage-design.md`

## Global Constraints

- Scope is OCPv2 **P2 Side-by-Side Deployment only**; do not enter P3 Canary.
- Operate only on an already-registered successor workspace resolved through `OnboardingRegistry`; do not clone, create worktrees, or accept a caller-supplied project path.
- `successor_profile` is exactly `lifecycle-v2-p2`.
- DRY_RUN may inspect local Git and use `git ls-remote`; it must not fetch or mutate refs, object DB, branch, HEAD, index, worktree, artifacts, or service-manager state.
- STAGE fetches only the reviewed `target_ref` into `refs/ocp/successor-stage/<request_id>`, requires the fetched SHA to equal `target_head`, and permits only ancestor/equal fast-forward of the admitted current branch.
- No checkout/branch switch, reset, rebase, force update, detached-HEAD staging, arbitrary refspec, arbitrary shell, or generic service-manager mutation API.
- Reuse existing `deploy/operator-control-plane-v2/bootstrap.py::stage_user_service()` only through a bounded callback/port. Never invoke daemon-reload, enable, start, restart, timer activation, polling activation, or production activation.
- Serving `ocpv2.env`, `ocpv2.service`, `ocpv2.timer`, and serving runtime identity must be unchanged byte-for-byte/identity-for-identity.
- `PROJECT_ONBOARDING` remains declarative registration/bootstrap; `HOST_INSPECTION` remains read-only.
- RDC remains break-glass only and is not an implementation/runtime dependency.
- `runtime-current`, predecessor quiesce/termination, existing Run migration, successor polling, and production activation remain outside this plan.
- Failure after Git advancement must never be compensated with `reset --hard`, forced checkout, or history rewrite; recovery is a new admission bound to the new current HEAD.

## Review Focus

1. **Canonical-root aliasing:** a different alias or symlink spelling that resolves to the serving/predecessor canonical workspace must fail before mutation; Task 2 adds an explicit canonical-identity test.
2. **Remote-ref ambiguity/drift:** a missing ref, multi-result observation, or DRY_RUN→STAGE ref movement must fail closed without advancing branch/HEAD; Task 3 pins exact single-SHA binding and drift.
3. **Concurrent staging:** a second STAGE for the same canonical workspace must not enter a check-then-act window; Task 4 pins exclusive-lock contention and post-lock revalidation.
4. **Partially unsafe staged state:** missing successor artifact, serving hash drift, or active/enabled/polling observation must make the final outcome non-success even when Git reached the approved SHA; Task 5 pins those cases.
5. **Crash/failure phase classification:** failures after fetch and after branch advance must preserve the exact furthest-safe-phase evidence and recovery semantics; Tasks 3 and 4 pin `FAILED_AFTER_FETCH` and `FAILED_AFTER_GIT_ADVANCE` separately.

---

## File Structure

- **Create:** `runtime/orchestrator/successor_release_staging.py` — request normalization/digests, registered-workspace resolution, DRY_RUN/STAGE transaction, locks, phase fencing, postconditions, immutable receipts, and the narrow Full MCP protocol used by the stager.
- **Create:** `runtime/orchestrator/successor_release_stage_gateway.py` — dedicated `SUCCESSOR_RELEASE_STAGE` Production Execution Gateway request/result contract and dispatch adapter; no generic command execution.
- **Modify:** `runtime/orchestrator/production_execution_gateway.py` — expose the dedicated governed capability dispatch without weakening the existing host-worker gateway contract or DEC007 tool authority.
- **Modify:** `runtime/orchestrator/remote_control_envelope.py` — add the typed `SUCCESSOR_RELEASE_STAGE` request kind, payload validation, and stage-policy authorization type.
- **Modify:** `runtime/orchestrator/remote_operator_service.py` — route the new admitted kind to a dedicated callback and emit a bounded status projection; do not reuse `HOST_INSPECTION` or `PROJECT_ONBOARDING` callbacks.
- **Modify:** `deploy/operator-control-plane-v2/bootstrap.py` — compose the production callback from the existing `stage_user_service()` primitive and the gateway/stager port; no service-manager mutation calls.
- **Modify:** `tests/test_ocpv2_successor_release_staging.py` — expand the current RED seam to the full 20-test normative contract before GREEN implementation.
- **Create:** `tests/test_ocpv2_successor_release_stage_gateway.py` — prove remote admission → dedicated Production Execution Gateway → stager/Full MCP boundary and prove direct activation/raw-command authority is unavailable.

---

### Task 1: Seal the request, digest, and two-phase identity contract

**Files:**
- Create: `runtime/orchestrator/successor_release_staging.py`
- Modify: `tests/test_ocpv2_successor_release_staging.py`

**Interfaces:**
- Consumes: `runtime.orchestrator.project_onboarding.OnboardingRegistry`.
- Produces: `SuccessorReleaseStageError`; `SuccessorReleaseStageRequest.from_mapping(mapping) -> SuccessorReleaseStageRequest`; `SuccessorReleaseStageRequest.to_dict() -> dict[str, object]`; `stage_intent_digest`; `phase_request_digest`; constants `SUCCESSOR_RELEASE_STAGE_SCHEMA`, `SUCCESSOR_PROFILE`.

- [ ] **Step 1: Replace the incomplete request fixture with the normative field set and write RED tests 1, 15, 16, and 17.**

```python
BASE_REQUEST = {
    "request_id": "stage-p2-001",
    "schema_version": "orchestration.successor-release-stage-request.v1",
    "project_alias": "successor-p2",
    "expected_branch": "stable",
    "expected_head": "a" * 40,
    "target_ref": "refs/heads/release",
    "target_head": "b" * 40,
    "successor_profile": "lifecycle-v2-p2",
    "approval_policy_ref": "P2-SUCCESSOR-STAGE",
    "approval_policy_digest": "c" * 64,
    "mode": "DRY_RUN",
    "preflight_digest": None,
}

# Pin: STAGE requires a matching preflight lineage; same request_id with changed
# target_head/policy/branch is rejected; DRY_RUN and STAGE have equal
# stage_intent_digest but different phase_request_digest; replay is keyed by the
# complete phase digest.
```

- [ ] **Step 2: Run only the request-contract tests and verify RED.**

Run: `python3 -m pytest -q tests/test_ocpv2_successor_release_staging.py -k 'two_phase or request_id or phase_digest or replay'`
Expected: FAIL because the module/request fields/digest semantics are not implemented.

- [ ] **Step 3: Implement strict normalization and digest derivation only.**

```python
@dataclass(frozen=True, slots=True)
class SuccessorReleaseStageRequest:
    request_id: str
    schema_version: str
    project_alias: str
    expected_branch: str
    expected_head: str
    target_ref: str
    target_head: str
    successor_profile: str
    approval_policy_ref: str
    approval_policy_digest: str
    mode: str
    preflight_digest: str | None

    @property
    def stage_intent_digest(self) -> str: ...

    @property
    def phase_request_digest(self) -> str: ...
```

Validation must use an exact field set, canonical JSON (`sort_keys=True`, compact separators), safe identifiers, 40-hex Git SHAs, 64-hex policy/preflight digests, modes `{DRY_RUN, STAGE}`, fixed profile, `preflight_digest is None` for DRY_RUN and non-empty valid digest for STAGE.

- [ ] **Step 4: Run the Task 1 tests and verify GREEN.**

Run: `python3 -m pytest -q tests/test_ocpv2_successor_release_staging.py -k 'two_phase or request_id or phase_digest'`
Expected: PASS.

- [ ] **Step 5: Commit Task 1.**

```bash
git add runtime/orchestrator/successor_release_staging.py tests/test_ocpv2_successor_release_staging.py
git commit -m "test: seal successor stage request lineage"
```

---

### Task 2: Resolve registered successor identity and prove isolation without mutation

**Files:**
- Modify: `runtime/orchestrator/successor_release_staging.py`
- Modify: `tests/test_ocpv2_successor_release_staging.py`

**Interfaces:**
- Consumes: `OnboardingRegistry.entries()` immutable entries and `validate_alias_entry()` behavior.
- Produces: `SuccessorWorkspaceIdentity(alias: str, canonical_root: Path, project_id: str)`; `SuccessorLifecycleIdentity(serving_root: Path, predecessor_root: Path | None)`; `SuccessorReleaseStager(..., lifecycle_identity_provider=...)`.

- [ ] **Step 1: Add RED tests 4, 5, 7, 8 plus canonical-root/symlink Review Focus.**

```python
# dirty worktree -> FAILED_BEFORE_MUTATION
# expected branch or expected HEAD drift -> FAILED_BEFORE_MUTATION
# successor canonical root == serving root -> reject
# successor canonical root == predecessor root -> reject
# alternate/symlink identity resolving to a protected root -> reject
```

The lifecycle exclusion values must come from the injected canonical provider in tests, never request fields.

- [ ] **Step 2: Run isolation tests and verify RED.**

Run: `python3 -m pytest -q tests/test_ocpv2_successor_release_staging.py -k 'dirty or drift or serving or predecessor or canonical_identity'`
Expected: FAIL before any Git-fetch/staging implementation exists.

- [ ] **Step 3: Implement registry-only alias resolution and read-only preflight observation.**

```python
class SuccessorReleaseStager:
    def __init__(
        self,
        registry: OnboardingRegistry,
        *,
        full_mcp: SuccessorReleaseFullMcpPort,
        lifecycle_identity_provider: Callable[[], SuccessorLifecycleIdentity],
        receipt_store: SuccessorReleaseReceiptStore,
        lock_root: Path,
        ...,
    ) -> None: ...

    def execute(self, request: SuccessorReleaseStageRequest) -> dict[str, object]: ...
```

The stager must find exactly one immutable registry entry by alias, validate that entry, use its canonical `project_root`, reject serving/predecessor canonical identity equality, and inspect `git status --porcelain`, symbolic branch, and HEAD only through the read-only Full MCP methods.

- [ ] **Step 4: Verify the original `project_onboarding.py` is unchanged.**

Run: `git diff -- runtime/orchestrator/project_onboarding.py`
Expected: no output.

- [ ] **Step 5: Run Task 2 tests and commit.**

Run: `python3 -m pytest -q tests/test_ocpv2_successor_release_staging.py -k 'dirty or drift or serving or predecessor or canonical_identity'`
Expected: PASS.

```bash
git add runtime/orchestrator/successor_release_staging.py tests/test_ocpv2_successor_release_staging.py
git commit -m "feat: bind successor stage to registered isolated workspace"
```

---

### Task 3: Implement DRY_RUN remote binding and bounded fetch/fast-forward primitives

**Files:**
- Modify: `runtime/orchestrator/successor_release_staging.py`
- Modify: `tests/test_ocpv2_successor_release_staging.py`

**Interfaces:**
- Produces narrow `SuccessorReleaseFullMcpPort` methods only:
  - `status(root: Path) -> str`
  - `branch(root: Path) -> str`
  - `head(root: Path) -> str`
  - `ls_remote(root: Path, target_ref: str) -> str`
  - `object_exists(root: Path, sha: str) -> bool`
  - `is_ancestor(root: Path, ancestor: str, descendant: str) -> bool`
  - `fetch_target(root: Path, target_ref: str, temporary_ref: str) -> str`
  - `fast_forward_current(root: Path, target_head: str) -> None`
  - `delete_temporary_ref(root: Path, temporary_ref: str) -> None`
- The production implementation accepts parameters, never caller shell text/refspec arrays.

- [ ] **Step 1: Add RED tests 2, 6, 9, 10, and 18 plus missing/ambiguous remote-ref Review Focus.**

```python
# DRY_RUN: target not local -> ancestry=PENDING_FETCH_PROOF and no fetch call.
# non-FF: bounded fetch may occur, but branch/HEAD/worktree stay at expected state.
# fetched SHA != target_head -> FAILED_AFTER_FETCH.
# ls-remote value changes between DRY_RUN and STAGE -> fail before branch advance.
# fetch exception after request-scoped metadata mutation -> FAILED_AFTER_FETCH.
# zero/multiple ls-remote SHA lines -> fail closed.
```

- [ ] **Step 2: Verify RED.**

Run: `python3 -m pytest -q tests/test_ocpv2_successor_release_staging.py -k 'dry_run or non_fast_forward or fetched_sha or target_ref_drift or after_fetch or remote_ref'`
Expected: FAIL.

- [ ] **Step 3: Implement the fixed Git adapter and DRY_RUN semantics.**

The concrete adapter may call Git with fixed argv templates only:

```python
["git", "status", "--porcelain"]
["git", "symbolic-ref", "--short", "HEAD"]
["git", "rev-parse", "HEAD"]
["git", "ls-remote", "--refs", "origin", target_ref]
["git", "cat-file", "-e", f"{sha}^{{commit}}"]
["git", "merge-base", "--is-ancestor", ancestor, descendant]
["git", "fetch", "--no-tags", "origin", f"{target_ref}:{temporary_ref}"]
["git", "merge", "--ff-only", target_head]
["git", "update-ref", "-d", temporary_ref]
```

No API accepts arbitrary argv/shell. DRY_RUN never calls `fetch_target()`. STAGE temporary ref must be exactly `refs/ocp/successor-stage/<request_id>`.

- [ ] **Step 4: Run Task 3 tests and verify GREEN.**

Run: `python3 -m pytest -q tests/test_ocpv2_successor_release_staging.py -k 'dry_run or non_fast_forward or fetched_sha or target_ref_drift or after_fetch or remote_ref'`
Expected: PASS.

- [ ] **Step 5: Commit Task 3.**

```bash
git add runtime/orchestrator/successor_release_staging.py tests/test_ocpv2_successor_release_staging.py
git commit -m "feat: add bounded successor release git operations"
```

---

### Task 4: Add exclusive lock, TOCTOU fences, and no-rollback recovery semantics

**Files:**
- Modify: `runtime/orchestrator/successor_release_staging.py`
- Modify: `tests/test_ocpv2_successor_release_staging.py`

**Interfaces:**
- Produces: `SuccessorStageLock` keyed from canonical root + alias; phase enum/outcomes `FAILED_BEFORE_MUTATION`, `FAILED_AFTER_FETCH`, `FAILED_AFTER_GIT_ADVANCE`, `STAGED`.

- [ ] **Step 1: Add RED tests 11 and 19 plus concurrent-lock Review Focus.**

```python
# Drift HEAD/worktree after DRY_RUN but before STAGE lock/revalidation -> no fetch.
# Drift after fetch but before branch advance -> no branch move.
# Inject staging failure after successful FF -> HEAD remains target_head,
# outcome FAILED_AFTER_GIT_ADVANCE, and no reset/checkout/rebase operation is observed.
# Replaying the failed phase digest does not retry; a new request_id/current-head admission is required.
# A second transaction for the same canonical successor cannot acquire the lock.
```

- [ ] **Step 2: Verify RED.**

Run: `python3 -m pytest -q tests/test_ocpv2_successor_release_staging.py -k 'toctou or git_advance or lock_contention or no_rollback'`
Expected: FAIL.

- [ ] **Step 3: Implement lock and all seven spec fences.**

Use an create-exclusive lock file under the supplied `lock_root` with a deterministic SHA-256 key of canonical root + alias. Recheck identity/branch/HEAD/cleanliness/policy at: preflight; post-lock pre-fetch; post-fetch; post-advance; pre-artifact; post-artifact; final receipt. Before advancement require `expected_head`; after it require `target_head`.

- [ ] **Step 4: Run Task 4 tests and verify GREEN.**

Run: `python3 -m pytest -q tests/test_ocpv2_successor_release_staging.py -k 'toctou or git_advance or lock_contention or no_rollback'`
Expected: PASS.

- [ ] **Step 5: Commit Task 4.**

```bash
git add runtime/orchestrator/successor_release_staging.py tests/test_ocpv2_successor_release_staging.py
git commit -m "feat: fence successor staging transaction"
```

---

### Task 5: Stage successor-only artifacts and verify serving/disabled postconditions

**Files:**
- Modify: `runtime/orchestrator/successor_release_staging.py`
- Modify: `deploy/operator-control-plane-v2/bootstrap.py`
- Modify: `tests/test_ocpv2_successor_release_staging.py`

**Interfaces:**
- Consumes: existing `DeploymentProfile.successor(name)` and `stage_user_service(config, profile=..., user_config_root=..., user_unit_root=...)`.
- Produces: fixed `stage_successor_artifacts(repo_root: Path, profile: str, config_root: Path, unit_root: Path) -> Mapping[str, str]` adapter; read-only `SuccessorServiceStateProbe.observe(profile) -> Mapping[str, bool]` with no mutation methods.

- [ ] **Step 1: Add/expand RED tests 3, 12, 13, and 14 plus partial-artifact Review Focus.**

```python
# exact target + only ocpv2-lifecycle-v2-p2.{env,service,timer} staged.
# stager/port exposes no daemon_reload/enable/start/restart API.
# serving env/service/timer changed between pre/post hash -> transaction fails.
# successor service active OR timer active OR enabled OR polling enabled -> fail.
# missing/unsafe successor artifact -> fail after Git advance, without rollback.
```

- [ ] **Step 2: Verify RED.**

Run: `python3 -m pytest -q tests/test_ocpv2_successor_release_staging.py -k 'happy_path or activation or serving_hash or successor_state or partial_artifact'`
Expected: FAIL.

- [ ] **Step 3: Add only a callable adapter around existing stage-only bootstrap behavior.**

```python
def stage_successor_artifacts(...):
    profile_obj = DeploymentProfile.successor(profile)
    if profile != "lifecycle-v2-p2":
        raise BootstrapError("unsupported P2 successor profile")
    package = stage_user_service(config, profile=profile_obj,
                                 user_config_root=config_root,
                                 user_unit_root=unit_root)
    return {"env_path": str(package.env_path),
            "service_path": str(package.service_path),
            "timer_path": str(package.timer_path)}
```

Do not add any `systemctl` mutation invocation. Hash serving files before the first STAGE Git mutation and again after successor staging; hash all successor artifacts; use read-only service-state probes for active/enabled/polling verification.

- [ ] **Step 4: Verify no service-manager mutation path was introduced.**

Run: `git diff -- deploy/operator-control-plane-v2/bootstrap.py | grep -E 'daemon-reload|systemctl.*(enable|start|restart)|--now' && exit 1 || true`
Expected: success with no forbidden introduced call.

- [ ] **Step 5: Run Task 5 tests and commit.**

Run: `python3 -m pytest -q tests/test_ocpv2_successor_release_staging.py -k 'happy_path or activation or serving_hash or successor_state or partial_artifact'`
Expected: PASS.

```bash
git add runtime/orchestrator/successor_release_staging.py deploy/operator-control-plane-v2/bootstrap.py tests/test_ocpv2_successor_release_staging.py
git commit -m "feat: stage disabled successor service artifacts"
```

---

### Task 6: Seal immutable phase receipts and replay behavior

**Files:**
- Modify: `runtime/orchestrator/successor_release_staging.py`
- Modify: `tests/test_ocpv2_successor_release_staging.py`

**Interfaces:**
- Produces: `SuccessorReleaseReceiptStore(root: Path)` with `read_phase(phase_request_digest)`, `append(receipt)`, and create-once files; successful receipt schema `orchestration.successor-release-stage-receipt.v1`.

- [ ] **Step 1: Complete RED tests 15 and 20.**

Successful receipt assertions must cover request ID; both digests; alias/canonical identity; policy ref/digest; expected branch/pre-head; target ref/SHA; remotely observed/fetched SHA; ancestor/FF result; preflight digest; fetch/branch result; pre/post HEAD; successor artifact hashes; serving artifact pre/post hashes; active/enabled/polling observations; guard outcomes; final outcome.

- [ ] **Step 2: Verify RED.**

Run: `python3 -m pytest -q tests/test_ocpv2_successor_release_staging.py -k 'replay or receipt'`
Expected: FAIL.

- [ ] **Step 3: Implement create-once canonical JSON receipts and replay retrieval.**

Use O_EXCL/O_NOFOLLOW where available, write canonical JSON, `flush()` + `fsync()`, never update an existing receipt. Same `phase_request_digest` returns the existing result without invoking Git/staging ports. A repeated DRY_RUN may only reuse when its stored observation fingerprint is revalidated; otherwise execute a fresh DRY_RUN/preflight lineage.

- [ ] **Step 4: Run receipt tests and the complete 20-test contract.**

Run: `python3 -m pytest -q tests/test_ocpv2_successor_release_staging.py`
Expected: PASS; all normative 20 behaviors are represented.

- [ ] **Step 5: Commit Task 6.**

```bash
git add runtime/orchestrator/successor_release_staging.py tests/test_ocpv2_successor_release_staging.py
git commit -m "feat: seal successor staging receipts"
```

---

### Task 7: Route SUCCESSOR_RELEASE_STAGE through OCP admission and Production Execution Gateway

**Files:**
- Create: `runtime/orchestrator/successor_release_stage_gateway.py`
- Modify: `runtime/orchestrator/production_execution_gateway.py`
- Modify: `runtime/orchestrator/remote_control_envelope.py`
- Modify: `runtime/orchestrator/remote_operator_service.py`
- Modify: `deploy/operator-control-plane-v2/bootstrap.py`
- Create: `tests/test_ocpv2_successor_release_stage_gateway.py`

**Interfaces:**
- `SUCCESSOR_RELEASE_STAGE_KIND = "SUCCESSOR_RELEASE_STAGE"`.
- `RemoteSuccessorReleaseStageAuthorization(successor_release_stage_policy_ref: str)`.
- `SuccessorReleaseStageGatewayRequest.from_stage_request(request) -> SuccessorReleaseStageGatewayRequest` binds kind, phase digest, policy digest, canonical capability ID, and gateway digest.
- `dispatch_successor_release_stage(request, *, stager) -> Mapping[str, object]` is the only mutation dispatch for this capability.
- `RemoteOperatorService(..., stage_successor_authorized: Callable[[RemoteControlEnvelopeV1], Mapping[str, Any]] | None, successor_release_stage_enabled: bool, successor_release_stage_policy_ref: str)`.

- [ ] **Step 1: Write integration RED tests proving the authority chain.**

```python
# valid typed envelope -> stage callback -> dedicated gateway -> stager exactly once.
# unsupported request kind/policy/digest -> rejected before stager.
# HOST_INSPECTION and PROJECT_ONBOARDING callbacks cannot reach stage mutation.
# direct stager unit use remains test-only; production bootstrap wires only gateway dispatch.
# gateway request exposes no command/argv/shell/systemctl/refspec field.
# Full MCP port exposes only the fixed methods from Task 3/5.
```

- [ ] **Step 2: Run the integration test and verify RED.**

Run: `python3 -m pytest -q tests/test_ocpv2_successor_release_stage_gateway.py`
Expected: FAIL because the request kind/gateway wiring does not yet exist.

- [ ] **Step 3: Extend `remote_control_envelope.py` with a typed additive request kind.**

Add the payload to `RemotePayload`, add a dedicated authorization dataclass/field set, validate payload using `SuccessorReleaseStageRequest.from_mapping()`, and reject any mismatched authorization type or policy ref/digest. Do not modify `HOST_INSPECTION_KIND` semantics.

- [ ] **Step 4: Implement the dedicated gateway contract without weakening worker gateway validation.**

`successor_release_stage_gateway.py` owns its small exact schema. `production_execution_gateway.py` exports a narrow dispatcher entry that accepts only that validated object and a `SuccessorReleaseStager`; do not add `SUCCESSOR_RELEASE_STAGE` to generic worker `build_gateway_request()` or relax DEC007 validation.

- [ ] **Step 5: Wire `RemoteOperatorService` and bootstrap composition.**

The service gets a separate branch/counter/projection for the new kind. `bootstrap.py` constructs the stager with the bounded port, receipt/lock roots below OCP state root, the existing stage-only artifact adapter, and canonical lifecycle identity provider. Mutation is requested through the dedicated gateway callback only; no OCP raw Git/shell/systemd call is added.

- [ ] **Step 6: Run integration and focused staging tests.**

Run: `python3 -m pytest -q tests/test_ocpv2_successor_release_stage_gateway.py tests/test_ocpv2_successor_release_staging.py`
Expected: PASS.

- [ ] **Step 7: Commit Task 7.**

```bash
git add runtime/orchestrator/successor_release_stage_gateway.py runtime/orchestrator/production_execution_gateway.py runtime/orchestrator/remote_control_envelope.py runtime/orchestrator/remote_operator_service.py deploy/operator-control-plane-v2/bootstrap.py tests/test_ocpv2_successor_release_stage_gateway.py
git commit -m "feat: route successor staging through production gateway"
```

---

### Task 8: Qualification, regression, boundary review, and P2-only handoff

**Files:**
- Modify only if qualification evidence requires it: `docs/superpowers/specs/2026-09-25-successor-release-stage-design.md` status line from approved design state to implemented/verified state; do not alter normative design content.
- No rollout/runtime-current/P3 file is modified in this task.

**Interfaces:**
- Consumes all prior task outputs.
- Produces verification evidence only; it does not activate the successor.

- [ ] **Step 1: Run focused contract tests.**

Run: `python3 -m pytest -q tests/test_ocpv2_successor_release_staging.py tests/test_ocpv2_successor_release_stage_gateway.py`
Expected: PASS.

- [ ] **Step 2: Run the repository full regression.**

Run: `python3 -m pytest -q`
Expected: PASS with zero failures/errors; record the exact test/skip count from output.

- [ ] **Step 3: Run static/compile checks.**

```bash
python3 -m compileall -q runtime deploy/operator-control-plane-v2 tests
git diff --check
git status --short
```

Expected: compileall and diff-check PASS; status contains only intentional branch changes.

- [ ] **Step 4: Perform the authority-boundary diff review.**

```bash
git diff --unified=0 HEAD~1..HEAD -- runtime/orchestrator deploy/operator-control-plane-v2 tests
```

Reviewer must confirm: no arbitrary shell API; no raw caller-controlled refspec; no checkout/reset/rebase/force; no service-manager mutation; no serving file write path; no `runtime-current`; no P3; no predecessor shutdown; no Run migration; onboarding and host-inspection semantics remain unchanged.

- [ ] **Step 5: Run regression-delta against the PR base using the repository's existing regression-delta procedure.**

Compare base `impl/ocp-rdc-independent-primary-path-20260923` with the final PR HEAD and require `current_only=0`. If the repository's established command/script name differs from prior qualification evidence, use that existing command verbatim rather than inventing a new checker.

- [ ] **Step 6: Verify deployment remains inert.**

Inspect generated/staged successor artifacts only; do **not** call daemon-reload/enable/start/restart and do not switch `runtime-current`. Confirm successor mode/profile remains `DISABLED`, polling is false, and serving artifact hashes/identity are unchanged.

- [ ] **Step 7: Commit only evidence/status changes if any were required.**

```bash
git add docs/superpowers/specs/2026-09-25-successor-release-stage-design.md
git commit -m "docs: record successor release stage verification"
```

Skip this commit if no tracked evidence/status file changed.

- [ ] **Step 8: Stop at the P2 host-staging resume gate.**

Final implementation output must explicitly state that `SUCCESSOR_RELEASE_STAGE` is source-integrated and verified but deployed serving OCP still needs the separately controlled bootstrap/deployment boundary before the previously stalled P2 host staging can resume. Do not enter P3 Canary in this plan.

---

## RED Contract Coverage Matrix

| # | Normative RED behavior | Owning task |
|---|---|---|
| 1 | exact two-phase lineage/intent/preflight binding | Task 1 |
| 2 | DRY_RUN nonmutating/no fetch | Task 3 |
| 3 | happy path exact target/successor-only | Task 5 |
| 4 | dirty worktree fails | Task 2 |
| 5 | branch/HEAD drift fails | Task 2 |
| 6 | non-FF after bounded fetch, no branch movement | Task 3 |
| 7 | serving alias/root fails | Task 2 |
| 8 | predecessor alias/root fails | Task 2 |
| 9 | fetched SHA mismatch fails | Task 3 |
| 10 | target ref drift between phases fails | Task 3 |
| 11 | TOCTOU head/worktree drift fails | Task 4 |
| 12 | activation/service-manager mutation unavailable | Task 5 + Task 7 |
| 13 | serving hash drift fails | Task 5 |
| 14 | successor active/enabled/polling fails | Task 5 |
| 15 | same phase digest replay side-effect free | Task 1 + Task 6 |
| 16 | same request ID/different intent fails | Task 1 |
| 17 | same lineage/different phase digests allowed | Task 1 |
| 18 | failure after fetch = FAILED_AFTER_FETCH/no branch move | Task 3 |
| 19 | failure after Git advance has no rollback/new admission required | Task 4 |
| 20 | success receipt contains all evidence | Task 6 |

## Self-Review Checklist

- **Spec coverage:** Tasks 1-8 cover request identity, two-phase preflight, canonical workspace isolation, TOCTOU lock/fences, bounded Git, successor-only staging, serving preservation, immutable audit/replay, failure/recovery semantics, OCP/Gateway/Full MCP authority split, all 20 RED tests, regression, and P2-only handoff.
- **Placeholder scan:** No `TBD`, `TODO`, “implement later”, generic “add error handling”, or unspecified “write tests” steps are permitted. Every implementation task has named files, interfaces, RED command, GREEN command, and commit boundary.
- **Type consistency:** `SuccessorReleaseStageRequest`, `SuccessorReleaseStager`, `SuccessorReleaseFullMcpPort`, `SuccessorReleaseReceiptStore`, `SuccessorLifecycleIdentity`, and dedicated gateway/admission names are defined once in their owning tasks and reused unchanged by later tasks.
- **Review Focus:** canonical-root aliasing, remote-ref ambiguity/drift, lock contention, unsafe partial artifact/service state, and phase/crash classification each have an explicit owning test task.
- **Authority check:** No task grants OCP arbitrary host mutation, repurposes onboarding/host inspection, activates the successor, changes runtime-current, enters P3, shuts down predecessor, migrates existing Runs, or introduces RDC as a normal dependency.
