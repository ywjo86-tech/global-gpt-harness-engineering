# Governed Successor Release Stage Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the P2-only `SUCCESSOR_RELEASE_STAGE` capability so OCP can admit one exact reviewed successor release, route all mutation through the Production Execution Gateway and bounded Full MCP operations, fast-forward only an already-registered isolated successor workspace, stage only disabled `lifecycle-v2-p2` artifacts, and emit immutable replay-safe evidence without disturbing serving OCP.

**Architecture:** Add one typed OCP request kind while preserving the existing authority split. OCP validates and admits; `production_execution_gateway.py` accepts only the dedicated successor-stage capability; `SuccessorReleaseStager` owns the transaction; a narrow `SuccessorReleaseFullMcpPort` provides fixed Git and artifact operations; `OnboardingRegistry` supplies immutable alias-to-root identity; existing `stage_user_service()` supplies successor-only inert artifact staging. DRY_RUN is observation-only. STAGE acquires an exclusive successor lock, revalidates state, performs one request-scoped fetch and one fast-forward, stages disabled artifacts, verifies serving preservation and successor-disabled state, then seals an immutable receipt.

**Tech Stack:** Python 3.12 standard library, `unittest`/`pytest`, fixed Git CLI argv through a bounded adapter, OCPv2 typed remote-control contracts, Production Execution Gateway, OCPv2 deployment bootstrap, canonical JSON/SHA-256/fsync/create-once receipts.

**Spec:** `docs/superpowers/specs/2026-09-25-successor-release-stage-design.md`

## Global Constraints

- Scope remains OCPv2 **P2 Side-by-Side Deployment only**. Do not enter P3 Canary.
- Operate only on an already-registered successor root resolved from `OnboardingRegistry`; no clone, worktree creation, caller-supplied root, arbitrary checkout, or branch switch.
- `successor_profile` is exactly `lifecycle-v2-p2`.
- DRY_RUN may use read-only local Git and `git ls-remote`; it must not fetch or mutate refs, object DB, branch, HEAD, index, worktree, artifacts, or service-manager state.
- STAGE fetches only `target_ref` into `refs/ocp/successor-stage/<request_id>`, requires fetched SHA == `target_head`, and allows only ancestor/equal fast-forward of the admitted branch.
- No reset, rebase, force update, detached HEAD, caller-controlled refspec, arbitrary shell, or generic service-manager mutation API.
- Reuse `deploy/operator-control-plane-v2/bootstrap.py::stage_user_service()` only through a bounded adapter. Never daemon-reload, enable, start, restart, activate timers, activate polling, or activate production.
- Serving `ocpv2.env`, `ocpv2.service`, `ocpv2.timer`, and serving runtime identity must remain unchanged.
- `PROJECT_ONBOARDING` remains declarative registration/bootstrap. `HOST_INSPECTION` remains read-only.
- RDC remains break-glass only and is not an implementation or runtime dependency.
- `runtime-current`, predecessor quiesce/termination, existing Run migration, successor polling, and production activation are out of scope.
- Failure after Git advancement is never compensated with `reset --hard`, forced checkout, or history rewrite. Recovery requires a new admission bound to current HEAD.

## Review Focus

1. **Canonical-root aliasing:** a different textual alias/path that resolves to serving/predecessor identity must reject before mutation. Task 2 pins canonical identity equality and symlink rejection.
2. **Remote-ref ambiguity/drift:** missing/multiple remote results or ref movement between DRY_RUN and STAGE must reject without branch advancement. Task 3 pins this.
3. **Concurrent staging:** two STAGE transactions for one canonical successor must not overlap. Task 4 pins lock contention and post-lock revalidation.
4. **Unsafe post-stage state:** missing successor artifacts, serving hash drift, or active/enabled/polling successor state must prevent `STAGED`. Task 5 pins these.
5. **Failure-phase recovery:** failures after fetch and after branch advancement must preserve different outcomes and never trigger history rollback. Tasks 3 and 4 pin these.

---

## File Structure

- **Create:** `runtime/orchestrator/successor_release_staging.py` — request/digests, registry identity, DRY_RUN/STAGE transaction, bounded Full MCP protocol, lock/fences, postconditions, immutable receipts.
- **Create:** `runtime/orchestrator/successor_release_stage_gateway.py` — exact dedicated Production Execution Gateway request/result and dispatcher for `SUCCESSOR_RELEASE_STAGE`.
- **Modify:** `runtime/orchestrator/production_execution_gateway.py` — expose the dedicated dispatch entry without weakening existing host-worker gateway or DEC007 validation.
- **Modify:** `runtime/orchestrator/remote_control_envelope.py` — typed request kind, payload validation, authorization binding.
- **Modify:** `runtime/orchestrator/remote_operator_service.py` — separate stage callback/status projection; do not reuse inspection/onboarding callbacks.
- **Modify:** `deploy/operator-control-plane-v2/bootstrap.py` — compose bounded stager/gateway using existing successor-only `stage_user_service()`; no service-manager mutation.
- **Modify:** `tests/test_ocpv2_successor_release_staging.py` — expand current RED seam to all 20 normative behaviors before GREEN.
- **Create:** `tests/test_ocpv2_successor_release_stage_gateway.py` — prove OCP admission → Production Execution Gateway → stager/Full MCP and prove raw activation/command authority is absent.

---

### Task 1: Seal request identity, digests, and two-phase lineage

**Files:**
- Create: `runtime/orchestrator/successor_release_staging.py`
- Modify: `tests/test_ocpv2_successor_release_staging.py`

**Interfaces:**
- Consumes: `runtime.orchestrator.project_onboarding.OnboardingRegistry`.
- Produces: `SuccessorReleaseStageError`, `SuccessorReleaseStageRequest.from_mapping()`, `SuccessorReleaseStageRequest.to_dict()`, `stage_intent_digest`, `phase_request_digest`, `SUCCESSOR_RELEASE_STAGE_SCHEMA`, `SUCCESSOR_PROFILE`.

- [ ] **Step 1: Write RED tests 1, 15, 16, 17 using the complete request schema.**

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
```

Assertions: STAGE without matching preflight fails; same `request_id` with changed immutable intent fails; DRY_RUN/STAGE for one intent have equal `stage_intent_digest` and different `phase_request_digest`; same complete phase digest is replay identity.

- [ ] **Step 2: Verify RED.**

Run: `python3 -m pytest -q tests/test_ocpv2_successor_release_staging.py -k 'two_phase or request_id or phase_digest or replay'`
Expected: FAIL because the normative request/digest implementation is absent.

- [ ] **Step 3: Implement exact normalization and digest code.**

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

    def intent_mapping(self) -> dict[str, object]:
        value = self.to_dict()
        value.pop("mode")
        value.pop("preflight_digest")
        return value

    @property
    def stage_intent_digest(self) -> str:
        return hashlib.sha256(_canonical(self.intent_mapping())).hexdigest()

    @property
    def phase_request_digest(self) -> str:
        return hashlib.sha256(_canonical(self.to_dict())).hexdigest()
```

Use an exact field set, safe IDs, 40-hex Git SHAs, 64-hex policy/preflight digests, modes `{DRY_RUN, STAGE}`, fixed profile, `None` preflight for DRY_RUN, mandatory digest for STAGE.

- [ ] **Step 4: Verify GREEN.**

Run: `python3 -m pytest -q tests/test_ocpv2_successor_release_staging.py -k 'two_phase or request_id or phase_digest'`
Expected: PASS.

- [ ] **Step 5: Commit.**

```bash
git add runtime/orchestrator/successor_release_staging.py tests/test_ocpv2_successor_release_staging.py
git commit -m "test: seal successor stage request lineage"
```

---

### Task 2: Bind only a registered, isolated successor workspace

**Files:**
- Modify: `runtime/orchestrator/successor_release_staging.py`
- Modify: `tests/test_ocpv2_successor_release_staging.py`

**Interfaces:**
- Consumes: `OnboardingRegistry.entries()` and immutable alias entries.
- Produces: `SuccessorWorkspaceIdentity`, `SuccessorLifecycleIdentity`, `SuccessorReleaseStager(registry, full_mcp, lifecycle_identity_provider, receipt_store, lock_root, stage_artifacts, service_state_probe)`.

- [ ] **Step 1: Write RED tests 4, 5, 7, 8 and canonical-root Review Focus.**

Pin dirty worktree, branch drift, HEAD drift, serving-root equality, predecessor-root equality, and a symlink/canonical alias to a protected root. Every case must fail before fetch/staging.

- [ ] **Step 2: Verify RED.**

Run: `python3 -m pytest -q tests/test_ocpv2_successor_release_staging.py -k 'dirty or branch_drift or head_drift or serving or predecessor or canonical_identity'`
Expected: FAIL.

- [ ] **Step 3: Implement registry-only resolution and read-only identity checks.**

```python
@dataclass(frozen=True, slots=True)
class SuccessorLifecycleIdentity:
    serving_root: Path
    predecessor_root: Path | None

@dataclass(frozen=True, slots=True)
class SuccessorWorkspaceIdentity:
    alias: str
    canonical_root: Path
    project_id: str
```

Resolve exactly one registry entry by alias, call the existing alias validator, use its canonical `project_root`, and compare resolved roots against lifecycle identity supplied by the canonical provider. Do not modify `project_onboarding.py`.

- [ ] **Step 4: Verify onboarding stayed separate.**

Run: `git diff -- runtime/orchestrator/project_onboarding.py`
Expected: no output.

- [ ] **Step 5: Verify GREEN and commit.**

Run: `python3 -m pytest -q tests/test_ocpv2_successor_release_staging.py -k 'dirty or branch_drift or head_drift or serving or predecessor or canonical_identity'`
Expected: PASS.

```bash
git add runtime/orchestrator/successor_release_staging.py tests/test_ocpv2_successor_release_staging.py
git commit -m "feat: bind successor stage to registered isolated workspace"
```

---

### Task 3: Implement observation-only DRY_RUN and bounded Git mutation

**Files:**
- Modify: `runtime/orchestrator/successor_release_staging.py`
- Modify: `tests/test_ocpv2_successor_release_staging.py`

**Interfaces:**
- Produces `SuccessorReleaseFullMcpPort` with only: `status`, `branch`, `head`, `ls_remote`, `object_exists`, `is_ancestor`, `fetch_target`, `fast_forward_current`, `delete_temporary_ref`.
- No method accepts raw shell text, arbitrary argv, or arbitrary refspec.

- [ ] **Step 1: Write RED tests 2, 6, 9, 10, 18 and remote-ref Review Focus.**

Pin: DRY_RUN with absent local target reports `PENDING_FETCH_PROOF` and calls no fetch; non-FF after bounded fetch does not move branch/HEAD/worktree; fetched SHA mismatch fails; remote ref drift fails; failure after bounded fetch records `FAILED_AFTER_FETCH`; zero or multiple exact-ref results fail closed.

- [ ] **Step 2: Verify RED.**

Run: `python3 -m pytest -q tests/test_ocpv2_successor_release_staging.py -k 'dry_run or non_fast_forward or fetched_sha or target_ref_drift or after_fetch or remote_ref'`
Expected: FAIL.

- [ ] **Step 3: Implement fixed Git operations.**

Only these argv shapes are permitted:

```python
("git", "status", "--porcelain")
("git", "symbolic-ref", "--short", "HEAD")
("git", "rev-parse", "HEAD")
("git", "ls-remote", "--refs", "origin", target_ref)
("git", "cat-file", "-e", f"{sha}^{{commit}}")
("git", "merge-base", "--is-ancestor", ancestor, descendant)
("git", "fetch", "--no-tags", "origin", f"{target_ref}:{temporary_ref}")
("git", "merge", "--ff-only", target_head)
("git", "update-ref", "-d", temporary_ref)
```

DRY_RUN never calls `fetch_target`. STAGE temporary ref is exactly `refs/ocp/successor-stage/<request_id>`. Validate remote SHA before fetch and fetched SHA after fetch.

- [ ] **Step 4: Verify GREEN.**

Run: `python3 -m pytest -q tests/test_ocpv2_successor_release_staging.py -k 'dry_run or non_fast_forward or fetched_sha or target_ref_drift or after_fetch or remote_ref'`
Expected: PASS.

- [ ] **Step 5: Commit.**

```bash
git add runtime/orchestrator/successor_release_staging.py tests/test_ocpv2_successor_release_staging.py
git commit -m "feat: add bounded successor release git operations"
```

---

### Task 4: Add exclusive lock, TOCTOU fences, and no-rollback recovery

**Files:**
- Modify: `runtime/orchestrator/successor_release_staging.py`
- Modify: `tests/test_ocpv2_successor_release_staging.py`

**Interfaces:**
- Produces: `SuccessorStageLock`; outcomes `FAILED_BEFORE_MUTATION`, `FAILED_AFTER_FETCH`, `FAILED_AFTER_GIT_ADVANCE`, `STAGED`.

- [ ] **Step 1: Write RED tests 11, 19 and lock-contention Review Focus.**

Pin drift after preflight/before mutation, drift after fetch/before branch advance, second concurrent STAGE rejection, staging failure after FF leaving HEAD at approved target, no reset/checkout/rebase call, same-phase replay not acting as recovery, and new admission required.

- [ ] **Step 2: Verify RED.**

Run: `python3 -m pytest -q tests/test_ocpv2_successor_release_staging.py -k 'toctou or git_advance or lock_contention or no_rollback'`
Expected: FAIL.

- [ ] **Step 3: Implement one create-exclusive lock and seven fences.**

Use an `O_CREAT|O_EXCL|O_NOFOLLOW` lock file keyed by SHA-256 of canonical root + alias. Revalidate at: preflight; post-lock/pre-fetch; post-fetch; post-advance; pre-artifact; post-artifact; final receipt. Before branch advancement require `expected_head`; after advancement require `target_head`.

- [ ] **Step 4: Verify GREEN and commit.**

Run: `python3 -m pytest -q tests/test_ocpv2_successor_release_staging.py -k 'toctou or git_advance or lock_contention or no_rollback'`
Expected: PASS.

```bash
git add runtime/orchestrator/successor_release_staging.py tests/test_ocpv2_successor_release_staging.py
git commit -m "feat: fence successor staging transaction"
```

---

### Task 5: Stage successor-only artifacts and verify inert postconditions

**Files:**
- Modify: `runtime/orchestrator/successor_release_staging.py`
- Modify: `deploy/operator-control-plane-v2/bootstrap.py`
- Modify: `tests/test_ocpv2_successor_release_staging.py`

**Interfaces:**
- Consumes existing `DeploymentProfile.successor()` and `stage_user_service()`.
- Produces `stage_successor_artifacts(repo_root, profile, config_root, unit_root) -> Mapping[str, str]` and a read-only `SuccessorServiceStateProbe.observe(profile) -> Mapping[str, bool]`.

- [ ] **Step 1: Write RED tests 3, 12, 13, 14 and partial-artifact Review Focus.**

Pin exact approved target and only successor artifact writes; absence of daemon-reload/enable/start/restart API; serving artifact hash drift failure; active service/timer, enabled unit, or polling true failure; missing successor artifact failure after Git advance without rollback.

- [ ] **Step 2: Verify RED.**

Run: `python3 -m pytest -q tests/test_ocpv2_successor_release_staging.py -k 'happy_path or activation or serving_hash or successor_state or partial_artifact'`
Expected: FAIL.

- [ ] **Step 3: Add the fixed bootstrap adapter only.**

```python
def stage_successor_artifacts(config, *, profile: str, user_config_root: Path, user_unit_root: Path) -> dict[str, str]:
    if profile != "lifecycle-v2-p2":
        raise BootstrapError("unsupported P2 successor profile")
    package = stage_user_service(
        config,
        profile=DeploymentProfile.successor(profile),
        user_config_root=user_config_root,
        user_unit_root=user_unit_root,
    )
    return {
        "env_path": str(package.env_path),
        "service_path": str(package.service_path),
        "timer_path": str(package.timer_path),
    }
```

Hash serving files before first STAGE Git mutation and after artifact staging. Hash successor env/service/timer. Read-only probes verify inactive/not-enabled/polling-disabled.

- [ ] **Step 4: Prove no forbidden service mutation was introduced.**

Run: `git diff -- deploy/operator-control-plane-v2/bootstrap.py | grep -E '^\+.*(daemon-reload|systemctl.*(enable|start|restart)|--now)' && exit 1 || true`
Expected: success with no matching added line.

- [ ] **Step 5: Verify GREEN and commit.**

Run: `python3 -m pytest -q tests/test_ocpv2_successor_release_staging.py -k 'happy_path or activation or serving_hash or successor_state or partial_artifact'`
Expected: PASS.

```bash
git add runtime/orchestrator/successor_release_staging.py deploy/operator-control-plane-v2/bootstrap.py tests/test_ocpv2_successor_release_staging.py
git commit -m "feat: stage disabled successor service artifacts"
```

---

### Task 6: Seal immutable receipts and idempotent replay

**Files:**
- Modify: `runtime/orchestrator/successor_release_staging.py`
- Modify: `tests/test_ocpv2_successor_release_staging.py`

**Interfaces:**
- Produces `SuccessorReleaseReceiptStore.read_phase(phase_request_digest)` and `append(receipt)`; receipt schema `orchestration.successor-release-stage-receipt.v1`.

- [ ] **Step 1: Complete RED tests 15 and 20.**

Successful receipt must assert: request ID, both digests, alias/canonical root identity, policy ref/digest, expected branch/pre-head, target ref/SHA, remotely observed/fetched SHA, ancestor/FF result, preflight digest, fetch/branch result, pre/post HEAD, successor hashes, serving pre/post hashes, active/enabled/polling observations, guard outcomes, final outcome.

- [ ] **Step 2: Verify RED.**

Run: `python3 -m pytest -q tests/test_ocpv2_successor_release_staging.py -k 'replay or receipt'`
Expected: FAIL.

- [ ] **Step 3: Implement create-once canonical JSON receipts.**

Use `O_WRONLY|O_CREAT|O_EXCL|O_NOFOLLOW`, canonical JSON, flush/fsync, and no in-place update. An existing identical `phase_request_digest` returns stored result without invoking Git/staging. A stale DRY_RUN observation is never silently reused as current mutation authority.

- [ ] **Step 4: Run the full 20-test local contract.**

Run: `python3 -m pytest -q tests/test_ocpv2_successor_release_staging.py`
Expected: PASS.

- [ ] **Step 5: Commit.**

```bash
git add runtime/orchestrator/successor_release_staging.py tests/test_ocpv2_successor_release_staging.py
git commit -m "feat: seal successor staging receipts"
```

---

### Task 7: Route the capability through OCP admission and Production Execution Gateway

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
- `SuccessorReleaseStageGatewayRequest.from_stage_request(request)` binds request kind, stage/phase digests, policy digest, capability ID, and gateway digest.
- `dispatch_successor_release_stage(request, *, stager)` is the only production mutation dispatch for this capability.
- `RemoteOperatorService` gains separate `stage_successor_authorized`, `successor_release_stage_enabled`, and `successor_release_stage_policy_ref` inputs.

- [ ] **Step 1: Write the integration RED suite.**

Pin: typed valid envelope dispatches through dedicated gateway once; wrong kind/policy/digest rejects before stager; inspection/onboarding callbacks cannot reach stage mutation; gateway schema contains no `command`, `argv`, `shell`, `systemctl`, or arbitrary `refspec`; production bootstrap wires gateway dispatch rather than direct stager execution; Full MCP port exposes only Task 3/5 fixed methods.

- [ ] **Step 2: Verify RED.**

Run: `python3 -m pytest -q tests/test_ocpv2_successor_release_stage_gateway.py`
Expected: FAIL.

- [ ] **Step 3: Add the typed remote-control request and authorization.**

Extend `RemotePayload` and `RemoteAuthorization` with the successor-stage types. `_validated_payload()` must call `SuccessorReleaseStageRequest.from_mapping()`. Envelope authorization must bind the dedicated policy ref and reject mismatched authorization classes. Do not alter `HOST_INSPECTION_KIND` semantics.

- [ ] **Step 4: Add the dedicated gateway contract without weakening the existing worker gateway.**

`successor_release_stage_gateway.py` owns its exact schema and digest. `production_execution_gateway.py` exports the bounded dispatcher. Do not add successor staging to generic `build_gateway_request()` and do not relax DEC007 tool authorization validation.

- [ ] **Step 5: Wire service and bootstrap composition.**

`RemoteOperatorService.poll_once()` gets a separate successor-stage branch, counter, and status projection. `bootstrap.py` constructs the stager with state-root receipt/lock directories, fixed Full MCP port, lifecycle identity provider, `stage_successor_artifacts`, read-only service-state probe, and the dedicated gateway callback. OCP gets no direct raw Git/shell/systemd call.

- [ ] **Step 6: Verify integration and focused contract.**

Run: `python3 -m pytest -q tests/test_ocpv2_successor_release_stage_gateway.py tests/test_ocpv2_successor_release_staging.py`
Expected: PASS.

- [ ] **Step 7: Commit.**

```bash
git add runtime/orchestrator/successor_release_stage_gateway.py runtime/orchestrator/production_execution_gateway.py runtime/orchestrator/remote_control_envelope.py runtime/orchestrator/remote_operator_service.py deploy/operator-control-plane-v2/bootstrap.py tests/test_ocpv2_successor_release_stage_gateway.py
git commit -m "feat: route successor staging through production gateway"
```

---

### Task 8: Qualification and P2-only handoff

**Files:**
- No production activation or rollout-transition file is modified.
- Modify the design/qualification document only if the implementation itself requires a tracked verification-status update after all checks pass.

**Interfaces:**
- Consumes all Tasks 1-7.
- Produces verification evidence only; no successor activation.

- [ ] **Step 1: Run focused tests.**

Run: `python3 -m pytest -q tests/test_ocpv2_successor_release_staging.py tests/test_ocpv2_successor_release_stage_gateway.py`
Expected: PASS.

- [ ] **Step 2: Run the repository OCP full-regression harness.**

Run: `python3 scripts/ocpv2_full_regression.py`
Expected: exit 0; record exact passed/skipped/failure/error counts.

- [ ] **Step 3: Run Full MCP boundary lint.**

Run: `python3 scripts/full_mcp_lint.py`
Expected: exit 0.

- [ ] **Step 4: Run compile/diff checks.**

```bash
python3 -m compileall -q runtime deploy/operator-control-plane-v2 tests
git diff --check
git status --short
```

Expected: compileall/diff-check exit 0; status contains only intentional branch changes.

- [ ] **Step 5: Review the complete PR diff against the P2 authority boundary.**

Run: `git diff --check impl/ocp-rdc-independent-primary-path-20260923...HEAD`
Expected: exit 0.

Run: `git diff --name-status impl/ocp-rdc-independent-primary-path-20260923...HEAD`
Expected: only files required by the approved design/plan; no runtime-current, P3, predecessor shutdown, Run migration, or RDC-normal-path file.

- [ ] **Step 6: Verify inert deployment semantics from tests/evidence only.**

Require successor profile `lifecycle-v2-p2`, mode `DISABLED`, polling false, service/timer inactive and not enabled, serving hashes unchanged, serving runtime identity unchanged. Do not call daemon-reload/enable/start/restart and do not switch runtime-current.

- [ ] **Step 7: Stop at the P2 host-staging resume gate.**

Report source integration/verification and the separate controlled deployment/bootstrap boundary still required to make the capability available to deployed serving OCP. Do not enter P3 Canary in this plan.

---

## RED Contract Coverage Matrix

| # | Normative behavior | Owning task |
|---|---|---|
| 1 | exact two-phase lineage/intent/preflight binding | Task 1 |
| 2 | DRY_RUN nonmutating/no fetch | Task 3 |
| 3 | happy path exact target/successor-only | Task 5 |
| 4 | dirty worktree fails | Task 2 |
| 5 | branch/HEAD drift fails | Task 2 |
| 6 | non-FF after bounded fetch; no branch movement | Task 3 |
| 7 | serving alias/root fails | Task 2 |
| 8 | predecessor alias/root fails | Task 2 |
| 9 | fetched SHA mismatch fails | Task 3 |
| 10 | target-ref drift between phases fails | Task 3 |
| 11 | TOCTOU head/worktree drift fails | Task 4 |
| 12 | activation/service-manager mutation unavailable | Tasks 5, 7 |
| 13 | serving hash drift fails | Task 5 |
| 14 | successor active/enabled/polling fails | Task 5 |
| 15 | same phase digest replay side-effect free | Tasks 1, 6 |
| 16 | same request ID/different intent fails | Task 1 |
| 17 | same lineage/different phase digests allowed | Task 1 |
| 18 | after-fetch failure classified without branch move | Task 3 |
| 19 | after-Git-advance failure has no rollback; new admission required | Task 4 |
| 20 | success receipt contains all normative evidence | Task 6 |

## Self-Review Checklist

- **Spec coverage:** Tasks 1-8 cover request identity, two-phase binding, registered canonical identity, serving/predecessor exclusion, TOCTOU locking, bounded fetch/FF, successor-only inert staging, serving preservation, immutable replay-safe receipts, failure/recovery semantics, OCP/Gateway/Full MCP authority split, all 20 RED tests, qualification, and P2-only handoff.
- **Placeholder scan:** No `TBD`, `TODO`, omitted code body, generic “add error handling”, or unspecified “write tests” step remains.
- **Type consistency:** `SuccessorReleaseStageRequest`, `SuccessorReleaseStager`, `SuccessorReleaseFullMcpPort`, `SuccessorReleaseReceiptStore`, `SuccessorLifecycleIdentity`, and the dedicated gateway/admission names are defined once and reused unchanged.
- **Review Focus:** canonical-root aliasing, remote-ref ambiguity/drift, lock contention, unsafe post-stage state, and failure-phase recovery each have an explicit test owner.
- **Authority check:** No task gives OCP arbitrary host mutation, repurposes onboarding/host inspection, activates successor, changes runtime-current, enters P3, shuts down predecessor, migrates existing Runs, or makes RDC normal-path infrastructure.
