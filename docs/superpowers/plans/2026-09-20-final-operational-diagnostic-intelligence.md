# AI Office Harness Final Operational Diagnostic Intelligence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Repair the current operational drift, productionize Graphify, add CodeGraph and Holmes-inspired RCA as a read-only Diagnostic Intelligence Plane, and close a single final production-operable Harness baseline under EDP ALL PASS.

**Architecture:** Separate immutable runtime code from mutable Full Plan job registries. Run Graphify, CodeGraph, and RCA behind a read-only analysis router whose authority is always NONE; feed only freshness-bound advisory context/evidence into existing execution and failure paths. Existing Full Plan, Provider Router, MPRF, Tool Broker/Full MCP, Completion Authority, Reconciler, and Attention ownership remain unchanged.

**Tech Stack:** Python 3.12/unittest, Git, user-level systemd, Graphify `graphifyy==0.9.58`, CodeGraph `0.20.1` Linux x64 binary, existing OmniRoute/MPRF/Full MCP runtime, JSON evidence records.

**Spec:** `docs/superpowers/specs/2026-09-20-diagnostic-intelligence-final-operationalization-design.md`

## Global Constraints

- EDP-1.0 is the closure standard; no PASS before all mandatory EDP phases complete.
- Preserve Full Plan supervisor/gates as orchestration/progression authority.
- Preserve Multi-Provider Router as the sole Provider/Model selection authority.
- Preserve MPRF as Provider lifecycle/eligibility/recovery authority.
- Preserve Execution Backend + Tool Broker/Full MCP as the sole real-effect authority.
- Preserve Completion Authority, Full Plan Boot/Reconciler, and Attention ownership unchanged.
- Diagnostic Intelligence has `control_authority=NONE`, `mutation_authority=NONE`, `recovery_authority=NONE`, `completion_authority=NONE`, `notification_authority=NONE`.
- Graphify is pinned to the already-qualified `graphifyy==0.9.58`; no hook/watch/strict/assistant install/external semantic backend.
- CodeGraph is pinned to `0.20.1`; Linux x64 engine SHA-256 is `32b26422fa5ffe0a130955b7f7df771f722b2d427d67f53f104d9907bdfb24a6`.
- CodeGraph runs `--graph-only`, `--profile graph`, `CODEGRAPH_TELEMETRY=off`, and an explicit Harness allowlist only.
- HolmesGPT is not installed as an orchestrator; only bounded RCA patterns are implemented locally.
- Governed WRITE and diagnostic indexing/query execution must not race.
- A stale analyzer result cannot affect execution context.
- Diagnostic disable/failure must restore the pre-integration Harness behavior.
- No merge to `main`, release publication, or paid-tier change is implicit in this plan; Git publication is a separate final step after EDP closure.

## Review Focus

1. Broken or removed runtime release target: boot/reconcile must fail closed and never execute from a missing worktree.
2. Active Full Plan job during runtime retarget: activation must refuse the switch and preserve the current runtime generation.
3. Analyzer source drift during/after WRITE: stale evidence must be rejected before provider context consumption.
4. Graphify/CodeGraph disagreement or analyzer outage: execution authority must remain unchanged and deterministic fallback must work.
5. Diagnostic loop with repeated queries but no evidence progress: RCA must mark thrashing and stop bounded investigation without stopping/resuming Full Plan.

---
## File Structure

New focused modules:
- `runtime/orchestrator/runtime_release.py` — immutable runtime-release staging, verification, and activation.
- `runtime/diagnostics/contracts.py` — source binding and analyzer/context evidence contracts.
- `runtime/diagnostics/config.py` — explicit enable/mode/tool paths and safe defaults.
- `runtime/diagnostics/evidence_store.py` — digest-bound diagnostic evidence persistence.
- `runtime/diagnostics/analysis_router.py` — deterministic analyzer selection and graceful degradation.
- `runtime/diagnostics/context_fusion.py` — bounded advisory context pack.
- `runtime/diagnostics/security.py` — path, secret-name, output-size, and source-binding checks.
- `runtime/diagnostics/adapters/graphify_adapter.py` — production read-only Graphify adapter.
- `runtime/diagnostics/adapters/codegraph_adapter.py` — one-shot CodeGraph structural adapter.
- `runtime/diagnostics/rca.py` — bounded investigation task/progress/claim model and thrashing detection.
- `runtime/orchestrator/diagnostic_context_bridge.py` — one-way integration boundary into existing runtime.
- `scripts/install_graphify_diagnostics.sh` — version/hash-pinned user installation.
- `scripts/install_codegraph_diagnostics.sh` — release/hash-pinned user installation.

Existing files changed narrowly:
- `runtime/orchestrator/production_full_plan_boot.py` — runtime code root vs job search root separation.
- `runtime/orchestrator/provider_action_execution.py` — optional advisory diagnostic context only.
- `runtime/orchestrator/production_full_plan_runner.py` — best-effort failure RCA evidence hook only.
- `runtime/orchestrator/production_attention_watch.py` — no authority change; source-generation metadata only if needed for evidence.
- `docs/DEVELOPMENT_PLAN.txt` — current-state projection/supersession block.
- `standards/CODE_INTELLIGENCE_DIAGNOSTIC_EXTENSION.md` — applicable-only CI domains that inherit EDP-1.0 and cannot weaken its PASS gate.

New tests mirror every module and authority boundary; existing Graphify PoC files remain historical evidence and are not deleted.

### Task 0: Promote Approved Harness Plans into Durable GPT-Operator Full Plan Jobs

**Files:**
- Create: `runtime/orchestrator/operator_plan_execution.py`
- Modify: `runtime/orchestrator/production_full_plan_entry.py`
- Modify: `runtime/orchestrator/user_interaction_policy.py`
- Create: `tests/test_operator_plan_execution.py`
- Modify: `tests/test_production_full_plan_entry.py`
- Modify: `tests/test_user_interaction_policy.py`

**Interfaces:**
- New job field: `executor_kind=GPT_OPERATOR_PLAN`; legacy/default remains `CANONICAL_GATE`.
- GPT operator job binds `approved_plan_path`, `approved_plan_sha256`, `approved_spec_path`, `approved_spec_sha256`, `runtime_code_root`, exact branch, project root, and ordered Task gate IDs.
- `OperatorPlanReceiptStore` creates/validates create-once Task PASS receipts under `<harness>/_workspace/operator-plan-receipts/<project>/<run>/`.
- `build_gate_executor()` selects `build_operator_plan_executor(job)` only for `GPT_OPERATOR_PLAN`; that executor waits read-only for the current Task receipt and never performs the Task effect itself.
- `classify_continuation_directive(text, *, approved_scope_active, durable_job_registered, material_contract_change)` returns `RESUME_FULL_PLAN`, `PROMOTE_TO_FULL_PLAN`, `REQUIRE_PLAN_REVISION`, or `NO_CONTINUATION`.
- Korean/English continuation tokens include exact normalized forms `진행`, `이어서 진행`, `계속 진행`, `continue`, `resume`, `proceed`.

- [ ] **Step 1: Write RED continuation-policy tests**

```python
def test_progress_word_promotes_approved_unregistered_harness_work(self):
    out = classify_continuation_directive(
        "진행", approved_scope_active=True, durable_job_registered=False, material_contract_change=False)
    self.assertEqual(out.action, "PROMOTE_TO_FULL_PLAN")

def test_progress_word_resumes_registered_full_plan(self):
    out = classify_continuation_directive(
        "이어서 진행", approved_scope_active=True, durable_job_registered=True, material_contract_change=False)
    self.assertEqual(out.action, "RESUME_FULL_PLAN")
```

Also assert material contract change -> `REQUIRE_PLAN_REVISION`, no approved scope -> `NO_CONTINUATION`, and arbitrary text is not treated as continuation.

- [ ] **Step 2: Run RED**

Run: `/tmp/gch-edp-allpass-venv/bin/python -m unittest tests.test_user_interaction_policy -v`
Expected: FAIL because continuation classification does not exist.

- [ ] **Step 3: Write RED GPT-operator job/receipt tests**

Create a temporary Git repo with committed spec/plan. Build a `GPT_OPERATOR_PLAN` job with Tasks `TASK-001`, `TASK-002`. Assert `load_job()` rejects digest mismatch, missing runtime code root, branch mismatch, duplicate Task IDs, and mutable/symlink plan/spec inputs. Assert the operator executor blocks only on receipt absence and returns `GATE_EXIT` after a valid create-once PASS receipt appears.

- [ ] **Step 4: Run RED**

Run: `/tmp/gch-edp-allpass-venv/bin/python -m unittest tests.test_operator_plan_execution tests.test_production_full_plan_entry -v`
Expected: FAIL because GPT operator plan execution does not exist.

- [ ] **Step 5: Implement continuation classification and operator-plan contracts**

`classify_continuation_directive()` performs only normalization/classification and has no orchestration side effect. `register_operator_plan_job()` verifies plan/spec SHA-256, current branch, `runtime_code_root` existence, and binds the current approval reference/digest. The operator executor polls only its receipt path and returns a canonical gate result after validated PASS evidence.

- [ ] **Step 6: Preserve authority boundaries**

Static tests must assert `operator_plan_execution.py` contains no imports/calls to Provider Router, Tool Broker, approval creation, Completion Authority, AttentionOutbox publish, Git mutation, shell mutation, or source writes outside its own receipt/registration workspace.

- [ ] **Step 7: Run focused and existing Full Plan tests**

Run: `/tmp/gch-edp-allpass-venv/bin/python -m unittest tests.test_operator_plan_execution tests.test_user_interaction_policy tests.test_production_full_plan_entry tests.test_production_full_plan_runner tests.test_production_attention_watch -v`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add runtime/orchestrator/operator_plan_execution.py runtime/orchestrator/production_full_plan_entry.py runtime/orchestrator/user_interaction_policy.py tests/test_operator_plan_execution.py tests/test_production_full_plan_entry.py tests/test_user_interaction_policy.py docs/superpowers/specs/2026-09-20-diagnostic-intelligence-final-operationalization-design.md docs/superpowers/plans/2026-09-20-final-operational-diagnostic-intelligence.md
git commit -m 'feat(full-plan): promote approved operator plans to durable jobs'
```

### Task 1: Decouple Runtime Code Root from Full Plan Job Search Root

**Files:**
- Modify: `runtime/orchestrator/production_full_plan_boot.py`
- Test: `tests/test_production_full_plan_boot.py`
- Test: `tests/test_full_plan_continuity_r2.py`

**Interfaces:**
- Produces: `discover_registered_jobs(search_root: str | Path) -> list[Path]`.
- Produces: `reconcile_all(search_root: str | Path, *, launch: bool = True) -> dict[str, Any]`.
- Produces: `systemd_user_unit(*, runtime_root, search_root, python_executable, preserve_runtime_path=False) -> str`.
- Backward compatibility: CLI `--harness-root` remains accepted as an alias for `--search-root` for existing callers.
- [ ] **Step 1: Write the failing recursive job-discovery tests**

```python
def test_discover_registered_jobs_finds_jobs_across_worktrees(self):
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        a = root / "a/_workspace/production-full-plan-jobs/P/R.job.json"
        b = root / "b/_workspace/production-full-plan-jobs/Q/S.job.json"
        a.parent.mkdir(parents=True); b.parent.mkdir(parents=True)
        a.write_text(json.dumps({"project_id":"P","run_id":"R","harness_root":str(root/'a'),"gates":[]}))
        b.write_text(json.dumps({"project_id":"Q","run_id":"S","harness_root":str(root/'b'),"gates":[]}))
        self.assertEqual(len(discover_registered_jobs(root)), 2)
```

Add a second test proving unrelated `*.job.json` outside `production-full-plan-jobs` is ignored and symlinked job files are ignored.

- [ ] **Step 2: Run RED**

Run: `/tmp/gch-edp-allpass-venv/bin/python -m unittest tests.test_production_full_plan_boot.ProductionFullPlanBootTests.test_discover_registered_jobs_finds_jobs_across_worktrees -v`
Expected: FAIL because `discover_registered_jobs` is not defined.

- [ ] **Step 3: Implement recursive, deduplicated, read-only discovery**

```python
def discover_registered_jobs(search_root: str | Path) -> list[Path]:
    root = Path(search_root).resolve()
    seen: set[tuple[str, str, str]] = set()
    found: list[Path] = []
    for path in root.rglob("*.job.json"):
        if "production-full-plan-jobs" not in path.parts or path.is_symlink() or not path.is_file():
            continue
        job = load_job(path)
        key = (str(job["project_id"]), str(job["run_id"]), str(Path(job["harness_root"]).resolve()))
        if key not in seen:
            seen.add(key); found.append(path)
    return sorted(found)
```

- [ ] **Step 4: Change `reconcile_all()` and CLI parsing to consume `search_root` without changing `reconcile_job()` authority semantics**

The systemd service must execute code from the immutable runtime root while searching `/home/ywjo/AI-Workspace/project-workspace` for registered jobs.

- [ ] **Step 5: Add the systemd-unit test**

Assert generated unit text contains:
```text
WorkingDirectory=/.../runtime-current
ExecStart=<python> -m runtime.orchestrator.production_full_plan_boot --search-root /home/ywjo/AI-Workspace/project-workspace
```

- [ ] **Step 6: Run focused tests**

Run: `/tmp/gch-edp-allpass-venv/bin/python -m unittest tests.test_production_full_plan_boot tests.test_full_plan_continuity_r2 -v`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add runtime/orchestrator/production_full_plan_boot.py tests/test_production_full_plan_boot.py tests/test_full_plan_continuity_r2.py
git commit -m 'fix(runtime): decouple reconciler code and job roots'
```
### Task 2: Add Immutable Runtime Release Staging and Safe Activation

**Files:**
- Create: `runtime/orchestrator/runtime_release.py`
- Create: `tests/test_runtime_release.py`
- Modify: `runtime/orchestrator/production_full_plan_boot.py`

**Interfaces:**
- Produces: `RuntimeReleaseManifest` with `source_head`, `source_tree`, `release_path`, `manifest_sha256`.
- Produces: `build_runtime_release(project_root, releases_root, source_ref="HEAD") -> RuntimeReleaseManifest`.
- Produces: `verify_runtime_release(release_path, expected_head) -> RuntimeReleaseManifest`.
- Produces: `activate_runtime_release(manifest, runtime_link, *, job_search_root) -> Path`.
- CLI: `python -m runtime.orchestrator.runtime_release build --project-root <root> --releases-root <dir> --source-ref <ref>` and `... activate --release <dir> --runtime-link <link> --job-search-root <root>`.
- Runtime release path: `~/.local/share/global-gpt-harness/releases/<git-head>/`.

- [ ] **Step 1: Write RED tests for release staging**

```python
def test_build_release_uses_exact_git_head_and_contains_runtime(self):
    manifest = build_runtime_release(repo, releases, source_ref="HEAD")
    expected = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()
    self.assertEqual(manifest.source_head, expected)
    self.assertTrue((Path(manifest.release_path)/"runtime/orchestrator/production_full_plan_boot.py").is_file())
    self.assertTrue((Path(manifest.release_path)/"RUNTIME_RELEASE_MANIFEST.json").is_file())
```

Add tests rejecting a dirty source tree, unsafe tar member, existing release with a mismatched manifest, and symlinked release root.

- [ ] **Step 2: Run RED**

Run: `/tmp/gch-edp-allpass-venv/bin/python -m unittest tests.test_runtime_release -v`
Expected: FAIL because `runtime_release` does not exist.
- [ ] **Step 3: Implement safe Git archive extraction and manifest sealing**

Use `git rev-parse <source_ref>^{commit}`, `git rev-parse <head>^{tree}`, and `git status --porcelain`. Extract `git archive` into `<head>.new-<pid>` with Python `tarfile` and reject absolute/`..` paths before `os.replace()` to the immutable release directory.

Manifest payload:
```python
{
  "schema_version": "gch.runtime-release.v1",
  "source_head": head,
  "source_tree": tree,
  "release_path": str(release),
  "runtime_entry": "runtime/orchestrator/production_full_plan_boot.py",
}
```
Seal it with canonical JSON SHA-256 and refuse modification of an already-sealed release.

- [ ] **Step 4: Write RED activation tests**

```python
def test_activation_repairs_broken_runtime_link_when_no_active_jobs(self):
    runtime_link.symlink_to(root/"removed-worktree")
    activate_runtime_release(manifest, runtime_link, job_search_root=workspace)
    self.assertEqual(runtime_link.resolve(), Path(manifest.release_path).resolve())

def test_activation_refuses_retarget_when_any_registered_job_is_active(self):
    with self.assertRaisesRegex(RuntimeReleaseError, "active Full Plan jobs"):
        activate_runtime_release(new_manifest, runtime_link, job_search_root=workspace)
```

- [ ] **Step 5: Implement activation using the registered-job search root, not the old runtime target**

The active-job guard must inspect each registered job's canonical state. A missing/unreadable nonterminal job is conservative-active and blocks retarget.

- [ ] **Step 6: Run focused tests**

Run: `/tmp/gch-edp-allpass-venv/bin/python -m unittest tests.test_runtime_release tests.test_production_full_plan_boot tests.test_full_plan_continuity_r2 -v`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add runtime/orchestrator/runtime_release.py runtime/orchestrator/production_full_plan_boot.py tests/test_runtime_release.py tests/test_production_full_plan_boot.py tests/test_full_plan_continuity_r2.py
git commit -m 'feat(runtime): add immutable harness releases'
```
### Task 3: Create the Read-Only Diagnostic Intelligence Contracts and Kill Switch

**Files:**
- Create: `runtime/diagnostics/__init__.py`
- Create: `runtime/diagnostics/contracts.py`
- Create: `runtime/diagnostics/config.py`
- Create: `runtime/diagnostics/security.py`
- Create: `tests/test_diagnostic_contracts.py`

**Interfaces:**
- Produces: `SourceSnapshotBinding.capture(project_root, *, project_id: str, owned_paths=())`.
- Produces: `AnalysisRequest`, `AnalysisEvidenceEnvelope`, `DiagnosticContextPack` frozen dataclasses.
- `AnalysisRequest` fields: `project_id`, `run_id`, `gate_id`, `task_id`, `kind`, `query`, `source_binding`, `owned_paths`.
- `AnalysisEvidenceEnvelope` fields: `project_id`, `run_id`, `gate_id`, `task_id`, `analyzer`, `analyzer_version`, `analysis_mode`, `status`, `source_binding`, `result_digest`, `raw_evidence_ref`, `result`, plus five fixed authority fields set to `NONE`.
- `DiagnosticContextPack` fields: `status`, `source_binding`, `evidence_refs`, `candidate_files`, `related_tests`, `conflicts`, `advisory_text`.
- Produces: `DiagnosticConfig.from_env(env: Mapping[str, str] | None = None)` with default `enabled=False`, `mode="OFF"`.
- Produces: `prepare_source_snapshot(project_root: Path, analysis_root: Path, binding: SourceSnapshotBinding) -> Path`.
- Valid modes: `OFF`, `SHADOW`, `ADVISORY`.
- Authority fields are constants fixed to `NONE` and cannot be overridden by input.

- [ ] **Step 1: Write RED contract tests**

```python
def test_diagnostics_default_off_and_have_no_authority(self):
    cfg = DiagnosticConfig.from_env({})
    self.assertFalse(cfg.enabled)
    binding = SourceSnapshotBinding.capture(repo, project_id="P")
    env = AnalysisEvidenceEnvelope(
        project_id="P", run_id="R", gate_id="G", task_id="T",
        analyzer="test", analyzer_version="1", analysis_mode="unit", status="CURRENT",
        source_binding=binding, result_digest="a"*64, raw_evidence_ref="", result={},
    )
    self.assertEqual(env.control_authority, "NONE")
    self.assertEqual(env.mutation_authority, "NONE")
    self.assertEqual(env.recovery_authority, "NONE")
    self.assertEqual(env.completion_authority, "NONE")
    self.assertEqual(env.notification_authority, "NONE")
```

Add tests that reject absolute owned paths, `..` traversal, non-40-character Git SHA, unrecognized freshness state, and result payload above the configured byte cap.
- [ ] **Step 2: Run RED**

Run: `/tmp/gch-edp-allpass-venv/bin/python -m unittest tests.test_diagnostic_contracts -v`
Expected: FAIL because `runtime.diagnostics` does not exist.

- [ ] **Step 3: Implement exact snapshot binding**

`SourceSnapshotBinding.capture()` must record:
```python
project_id: str
source_root_id: str
git_head_sha: str
workspace_tree_digest: str
owned_paths: tuple[str, ...]
owned_scope_digest: str
captured_at: str
```

`workspace_tree_digest` is the SHA-256 of: current HEAD tree SHA; `git diff --binary HEAD` bytes for staged/unstaged tracked changes; and sorted non-ignored untracked path + content hashes. Secret-pattern untracked paths contribute a redacted path marker rather than secret contents. This detects content changes even when the same file remains in Git status.

`prepare_source_snapshot()` builds `<analysis_root>/source-snapshot` from the union of `git ls-files -z` and `git ls-files --others --exclude-standard -z`, excluding `_workspace/`, VCS/cache/venv/node_modules paths, secret-name patterns, and symlinks. It copies current working-tree bytes for eligible files, captures the binding before and after copy, and raises `CODE_INTELLIGENCE_STALE` if the live tree changes during snapshot creation.

- [ ] **Step 4: Implement source-current comparison**

```python
def assert_binding_current(binding: SourceSnapshotBinding, project_root: Path) -> None:
    current = SourceSnapshotBinding.capture(project_root, project_id=binding.project_id, owned_paths=binding.owned_paths)
    if current.git_head_sha != binding.git_head_sha or current.workspace_tree_digest != binding.workspace_tree_digest:
        raise DiagnosticStaleError("CODE_INTELLIGENCE_STALE")
```

- [ ] **Step 5: Implement safe default config**

Environment keys:
```text
GCH_DIAGNOSTIC_INTELLIGENCE_ENABLED=false
GCH_DIAGNOSTIC_INTELLIGENCE_MODE=OFF
GCH_DIAGNOSTIC_MAX_RESULT_BYTES=262144
GCH_DIAGNOSTIC_MAX_CONTEXT_CHARS=12000
```
Reject `ADVISORY` when `enabled=false`; never infer enablement from tool installation.

- [ ] **Step 6: Run focused tests and commit**

Run: `/tmp/gch-edp-allpass-venv/bin/python -m unittest tests.test_diagnostic_contracts -v`
Expected: PASS.

```bash
git add runtime/diagnostics tests/test_diagnostic_contracts.py
git commit -m 'feat(diagnostics): add authority-free evidence contracts'
```
### Task 4: Productionize the Existing Graphify Sidecar Without Hooks or Write Authority

**Files:**
- Create: `runtime/diagnostics/adapters/__init__.py`
- Create: `runtime/diagnostics/adapters/graphify_adapter.py`
- Create: `scripts/install_graphify_diagnostics.sh`
- Create: `tests/test_diagnostic_graphify_adapter.py`
- Reuse authority: `poc/graphify/config/version_lock.json`

**Interfaces:**
- Produces: `GraphifyReadOnlyAdapter(cli_path, *, isolated_home, timeout_seconds=30)`.
- Produces: `build_graph(request, analysis_root) -> AnalysisEvidenceEnvelope`.
- Produces: `query(request, graph_path, *, token_budget=1200) -> AnalysisEvidenceEnvelope`.
- Output root: `<harness>/_workspace/diagnostics/<project>/<run>/graphify/`.
- The adapter never invokes `graphify install`, `graphify hook`, `graphify watch`, MCP HTTP, or any semantic backend.

- [ ] **Step 1: Write RED tests for command and environment boundaries**

```python
def test_graphify_build_is_local_read_only_and_strips_provider_keys(self):
    adapter = GraphifyReadOnlyAdapter(cli, isolated_home=home, runner=fake_runner)
    env = adapter.safe_env()
    for key in ("OPENAI_API_KEY","ANTHROPIC_API_KEY","GEMINI_API_KEY","GOOGLE_API_KEY","KIMI_API_KEY","DEEPSEEK_API_KEY"):
        self.assertNotIn(key, env)
    self.assertEqual(env["GRAPHIFY_HOOK_STRICT"], "0")
```

Add tests proving all outputs are outside the source root, queries carry the exact `git_head_sha`, absolute/escaping graph paths are rejected, and a command containing `hook`, `watch`, `install`, `serve`, or `--transport http` is impossible through the adapter API.

- [ ] **Step 2: Run RED**

Run: `/tmp/gch-edp-allpass-venv/bin/python -m unittest tests.test_diagnostic_graphify_adapter -v`
Expected: FAIL because the production diagnostics adapter does not exist.
- [ ] **Step 3: Implement the isolated installer**

`scripts/install_graphify_diagnostics.sh` must:
```bash
set -euo pipefail
VERSION=0.9.58
WHEEL=graphifyy-0.9.58-py3-none-any.whl
EXPECTED=e239803288e91c723d6e30540860bd6d5a1dc3f0914b9fc1104b0233e98aaeb8
PREFIX="$HOME/.local/share/gch/diagnostics/graphify/$VERSION"
TMP="$(mktemp -d)"
python3.12 -m pip download --no-deps --dest "$TMP" "graphifyy==$VERSION"
printf '%s  %s\n' "$EXPECTED" "$TMP/$WHEEL" | sha256sum -c -
python3.12 -m venv "$PREFIX.new"
"$PREFIX.new/bin/python" -m pip install "$TMP/$WHEEL[mcp]"
"$PREFIX.new/bin/graphify" --version
rm -rf "$PREFIX"
mv "$PREFIX.new" "$PREFIX"
```

No `sudo`, global pip, assistant integration, hook installation, or auto-update is allowed.

- [ ] **Step 4: Implement snapshot build/query execution**

Build from the shared secret-filtered snapshot returned by `runtime.diagnostics.security.prepare_source_snapshot()`. Execute exactly:
```text
<graphify> extract <analysis-root>/source-snapshot --code-only --no-cluster --out <analysis-root>
```
This must create `<analysis-root>/graphify-out/graph.json` without an LLM key, semantic backend, clustering-label call, or source-tree writes. Query command remains:
```text
<graphify> query <question> --graph <analysis-root>/graphify-out/graph.json --budget <bounded-int>
```

Before returning any query result call `assert_binding_current()`; on mismatch return/raise `CODE_INTELLIGENCE_STALE` rather than use the output.

- [ ] **Step 5: Run Graphify-focused regressions**

Run: `/tmp/gch-edp-allpass-venv/bin/python -m unittest tests.test_diagnostic_graphify_adapter tests.test_graphify_adapter_contract tests.test_graphify_environment tests.test_graphify_fallback tests.test_graphify_policy_boundaries -v`
Expected: PASS with all historical Graphify authority tests preserved.

- [ ] **Step 6: Commit**

```bash
git add runtime/diagnostics/adapters scripts/install_graphify_diagnostics.sh tests/test_diagnostic_graphify_adapter.py
git commit -m 'feat(diagnostics): productionize read-only graphify adapter'
```

### Task 5: Add the CodeGraph Structural Impact Adapter

**Files:**
- Create: `runtime/diagnostics/adapters/codegraph_adapter.py`
- Create: `scripts/install_codegraph_diagnostics.sh`
- Create: `tests/test_diagnostic_codegraph_adapter.py`
- Create: `docs/harness/diagnostics/CODEGRAPH_VERSION_LOCK.json`

**Interfaces:**
- Produces: `CodeGraphReadOnlyAdapter(binary_path, *, isolated_home, timeout_seconds=45)`.
- Produces: `query(request, tool_name, tool_args, analysis_root) -> AnalysisEvidenceEnvelope`.
- Allowed tools: `codegraph_analyze_impact`, `codegraph_get_callers`, `codegraph_get_callees`, `codegraph_get_dependency_graph`, `codegraph_find_related_tests`, `codegraph_find_entry_points`, `codegraph_get_module_summary`, `codegraph_traverse_graph`.
- [ ] **Step 1: Write RED tests for the CodeGraph command surface**

```python
def test_codegraph_is_graph_only_telemetry_off_and_allowlisted(self):
    adapter = CodeGraphReadOnlyAdapter(binary, isolated_home=home, runner=fake_runner)
    adapter.query(request, "codegraph_analyze_impact", {"symbol":"route_provider"}, analysis_root)
    command = fake_runner.call_args.args[0]
    env = fake_runner.call_args.kwargs["env"]
    self.assertIn("--graph-only", command)
    self.assertEqual(env["CODEGRAPH_TELEMETRY"], "off")
    self.assertEqual(env["CODEGRAPH_TOOL_PROFILE"], "graph")
```

Add tests that `codegraph_memory_store`, `codegraph_index_markdown`, `codegraph_reindex_workspace`, unknown tools, `--mcp`, and non-allowlisted admin/memory/docs operations are rejected before subprocess launch.

- [ ] **Step 2: Run RED**

Run: `/tmp/gch-edp-allpass-venv/bin/python -m unittest tests.test_diagnostic_codegraph_adapter -v`
Expected: FAIL because `codegraph_adapter` does not exist.

- [ ] **Step 3: Add the exact version lock**

`CODEGRAPH_VERSION_LOCK.json` records:
```json
{
  "schema_version": "gch.codegraph.version-lock.v1",
  "version": "0.20.1",
  "release_tag": "v0.20.1",
  "asset": "codegraph-server-linux-x64",
  "sha256": "32b26422fa5ffe0a130955b7f7df771f722b2d427d67f53f104d9907bdfb24a6",
  "license": "Apache-2.0",
  "mode": "graph-only",
  "profile": "graph",
  "telemetry": "off"
}
```

- [ ] **Step 4: Implement the user-owned installer**

Download only `https://github.com/codegraph-ai/CodeGraph/releases/download/v0.20.1/codegraph-server-linux-x64` into a temporary path, verify the exact SHA-256 above, `chmod 0755`, execute `--help`, then atomically install to `~/.local/share/gch/diagnostics/codegraph/0.20.1/bin/codegraph-server`. No global npm install is needed.
- [ ] **Step 5: Implement one-shot isolated execution**

For each query first call `prepare_source_snapshot()` and create `<analysis_root>/codegraph-home`, set it as `HOME`, and execute:
```text
<codegraph-server> --graph-only --profile graph --workspace <analysis_root>/source-snapshot --run-tool <allowlisted-tool> --tool-args <canonical-json>
```

Set environment:
```text
CODEGRAPH_TELEMETRY=off
CODEGRAPH_TOOL_PROFILE=graph
HOME=<analysis_root>/codegraph-home
```

Do not run agent-rule installers, PreToolUse hooks, persistent MCP server mode, memory tools, or docs mutation tools. Treat any CodeGraph DB/cache under the isolated HOME as disposable derived state.

- [ ] **Step 6: Bind result freshness and output limits**

Parse stdout as JSON when possible; otherwise store a bounded text payload. Record binary SHA-256, exact command mode, tool name, result digest, and the pre-query source binding. Re-capture source binding after subprocess completion; if changed, mark the envelope `STALE` and do not expose advisory content.

- [ ] **Step 7: Run focused tests and commit**

Run: `/tmp/gch-edp-allpass-venv/bin/python -m unittest tests.test_diagnostic_codegraph_adapter tests.test_diagnostic_contracts -v`
Expected: PASS.

```bash
git add runtime/diagnostics/adapters/codegraph_adapter.py scripts/install_codegraph_diagnostics.sh tests/test_diagnostic_codegraph_adapter.py docs/harness/diagnostics/CODEGRAPH_VERSION_LOCK.json
git commit -m 'feat(diagnostics): add isolated codegraph impact adapter'
```

### Task 6: Add Evidence Store, Analysis Router, and Bounded Context Fusion

**Files:**
- Create: `runtime/diagnostics/evidence_store.py`
- Create: `runtime/diagnostics/analysis_router.py`
- Create: `runtime/diagnostics/context_fusion.py`
- Create: `tests/test_diagnostic_analysis_router.py`
- Create: `tests/test_diagnostic_context_fusion.py`

**Interfaces:**
- Produces: `DiagnosticEvidenceStore(root).put(envelope) -> str` returning a digest-bound reference.
- Produces: `AnalysisRouter(graphify, codegraph).analyze(request) -> tuple[AnalysisEvidenceEnvelope, ...]`.
- Produces: `fuse_context(request, evidence, *, max_chars) -> DiagnosticContextPack`.
- Analyzer internal statuses: `CURRENT`, `STALE`, `PARTIAL`, `DEGRADED`, `CONFLICT`, `FAILED`.
- [ ] **Step 1: Write RED routing tests**

```python
def test_exact_symbol_request_prefers_codegraph(self):
    request = AnalysisRequest(kind="SYMBOL_IMPACT", query="route_provider", source_binding=binding)
    out = router.analyze(request)
    self.assertEqual(out[0].analyzer, "codegraph")

def test_unclear_cross_cutting_request_uses_graphify_then_codegraph(self):
    request = AnalysisRequest(kind="TOPOLOGY_AND_IMPACT", query="provider execution flow", source_binding=binding)
    self.assertEqual([x.analyzer for x in router.analyze(request)], ["graphify","codegraph"])
```

Add tests for Graphify failure -> CodeGraph-only DEGRADED, CodeGraph failure -> Graphify-only DEGRADED, both failures -> empty advisory evidence with `DEGRADED`, and no exception escaping into execution authority.

- [ ] **Step 2: Write RED conflict tests**

When both analyzers return materially different source files for the same exact-symbol impact request, `fuse_context()` must set `status="CONFLICT"`, record `GRAPH_CONFLICT`, include both evidence refs, and set `advisory_text=""` until raw-source verification is supplied.

- [ ] **Step 3: Run RED**

Run: `/tmp/gch-edp-allpass-venv/bin/python -m unittest tests.test_diagnostic_analysis_router tests.test_diagnostic_context_fusion -v`
Expected: FAIL because router/fusion modules do not exist.

- [ ] **Step 4: Implement deterministic routing without Provider calls**

Routing table:
```python
ROUTES = {
  "SYMBOL_IMPACT": ("codegraph",),
  "TOPOLOGY": ("graphify",),
  "TOPOLOGY_AND_IMPACT": ("graphify", "codegraph"),
  "RELATED_TESTS": ("codegraph",),
  "RCA_SUPPORT": ("codegraph", "graphify"),
}
```

The router contains no model/provider selection and no action callbacks.

- [ ] **Step 5: Implement bounded fusion**

Only `CURRENT` evidence contributes advisory text. Sort source files, impact nodes, tests, and conflicts deterministically. Truncate only advisory prose to `max_chars`; preserve full evidence separately by digest. Never add a file to `owned_scope` or an authorization contract.

- [ ] **Step 6: Run tests and commit**

Run: `/tmp/gch-edp-allpass-venv/bin/python -m unittest tests.test_diagnostic_analysis_router tests.test_diagnostic_context_fusion tests.test_diagnostic_graphify_adapter tests.test_diagnostic_codegraph_adapter -v`
Expected: PASS.

```bash
git add runtime/diagnostics/evidence_store.py runtime/diagnostics/analysis_router.py runtime/diagnostics/context_fusion.py tests/test_diagnostic_analysis_router.py tests/test_diagnostic_context_fusion.py
git commit -m 'feat(diagnostics): route and fuse bounded code intelligence'
```
### Task 7: Integrate Advisory Diagnostic Context Without Expanding Write Scope

**Files:**
- Create: `runtime/orchestrator/diagnostic_context_bridge.py`
- Modify: `runtime/orchestrator/provider_action_execution.py`
- Create: `tests/test_diagnostic_context_bridge.py`
- Modify: `tests/test_provider_action_execution.py`

**Interfaces:**
- Produces: `prepare_action_diagnostic_context(request: WorkerRequest, owned: list[str]) -> DiagnosticContextPack | None`.
- `OFF`: returns `None`, performs no analyzer process call.
- `SHADOW`: stores evidence but returns a pack with empty `advisory_text`.
- `ADVISORY`: returns bounded `CURRENT` non-conflicting advisory text.
- Existing `owned` list, Tool Authorization contract, proposal schema, Broker, and security scan remain unchanged.

- [ ] **Step 1: Write the baseline-equivalence RED test**

Capture the prompt from current `build_action_proposal_prompt()` with diagnostics disabled, then assert the modified implementation produces byte-identical prompt content for the same request when `GCH_DIAGNOSTIC_INTELLIGENCE_ENABLED=false`.

```python
def test_diagnostics_off_preserves_action_prompt_and_owned_scope(self):
    before = expected_preintegration_prompt
    after = build_action_proposal_prompt(request, baseline=baseline, owned=owned, diagnostic_context="")
    self.assertEqual(after, before)
    self.assertEqual(owned, original_owned)
```

- [ ] **Step 2: Write SHADOW/ADVISORY behavior tests**

Assert SHADOW executes a fake router and writes evidence but does not add text to the provider prompt. Assert ADVISORY appends a section headed `READ-ONLY DIAGNOSTIC CONTEXT — NO AUTHORITY` and keeps `proposal["writes"]` validation exactly bound to the original owned scope.

- [ ] **Step 3: Write stale/conflict/degradation tests**

A `STALE`, `CONFLICT`, or all-analyzers-failed pack must contribute no advisory text. Diagnostic exceptions are caught by the bridge and returned as degraded evidence; they must not change Provider selection, retry budget, state, or Broker invocation.

- [ ] **Step 4: Run RED**

Run: `/tmp/gch-edp-allpass-venv/bin/python -m unittest tests.test_diagnostic_context_bridge tests.test_provider_action_execution -v`
Expected: FAIL because the bridge and prompt parameter do not exist.
- [ ] **Step 5: Implement the one-way bridge**

The bridge creates `AnalysisRequest(kind="TOPOLOGY_AND_IMPACT", ...)` only from read-only request/task metadata, stores evidence under `_workspace/diagnostics`, and never returns authorization/effect callbacks. It must instantiate adapters only from explicitly configured installed paths.

- [ ] **Step 6: Thread advisory text into prompt construction only**

Change the prompt builder signature to:
```python
def build_action_proposal_prompt(
    request: WorkerRequest, *, baseline: str, owned: list[str],
    validation_feedback: str = "", target_owned_file_id: str | None = None,
    diagnostic_context: str = "",
) -> str:
```

Append at most the configured context cap after deterministic repository context. Prefix it with an explicit instruction that it is advisory, may be incomplete, and cannot enlarge the write set.

- [ ] **Step 7: Run focused authority regression**

Run: `/tmp/gch-edp-allpass-venv/bin/python -m unittest tests.test_diagnostic_context_bridge tests.test_provider_action_execution tests.test_tool_authorization tests.test_effect_evidence_bridge tests.test_production_provider_router_integration -v`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add runtime/orchestrator/diagnostic_context_bridge.py runtime/orchestrator/provider_action_execution.py tests/test_diagnostic_context_bridge.py tests/test_provider_action_execution.py
git commit -m 'feat(diagnostics): add advisory action context bridge'
```

### Task 8: Implement Holmes-Inspired Bounded RCA Without Installing Holmes Authority

**Files:**
- Create: `runtime/diagnostics/rca.py`
- Create: `runtime/diagnostics/adapters/rca_adapter.py`
- Create: `tests/test_diagnostic_rca.py`
- Modify: `runtime/orchestrator/diagnostic_context_bridge.py`

**Interfaces:**
- Produces: `InvestigationTask(id, question, status, evidence_refs)` with statuses `PENDING`, `IN_PROGRESS`, `COMPLETED`, `FAILED`.
- Produces: `FailureEvidence(project_id, run_id, gate_id, reason, failure_class, source_binding)`.
- Produces: `RCAReport(root_cause_claims, evidence_refs, blast_radius, limitations, thrashing_state, tool_call_count, new_evidence_count, repeated_query_count, semantic_progress_sequence)`.
- Produces: `investigate_failure(failure: FailureEvidence, router: AnalysisRouter, *, max_steps=8) -> RCAReport`.
- RCA has no Provider Router, scheduler, remediation, retry, recovery, approval, completion, or notification callbacks.
- [ ] **Step 1: Write RED RCA task/evidence tests**

```python
def test_rca_claim_requires_evidence_reference(self):
    report = investigate_failure(failure, fake_router, max_steps=4)
    for claim in report.root_cause_claims:
        self.assertTrue(claim.evidence_refs)

def test_temporal_coincidence_alone_cannot_be_root_cause(self):
    report = investigate_failure(temporal_only_failure, fake_router, max_steps=4)
    self.assertFalse(any(c.status == "CONFIRMED" for c in report.root_cause_claims))
```

Add blast-radius assertions for `affected`, `checked_healthy`, `changed_for_another_reason`, and `not_checked` sets. Missing analyzer/tool availability must appear in `limitations` rather than silently disappearing.

- [ ] **Step 2: Write RED duplicate/thrashing tests**

```python
def test_three_semantically_repeated_queries_without_new_evidence_marks_thrashing(self):
    tracker = InvestigationProgress(max_repeated_without_progress=3)
    for _ in range(3):
        tracker.record_call("codegraph_analyze_impact", {"symbol":"x"}, new_evidence_count=0)
    self.assertEqual(tracker.thrashing_state, "DIAGNOSTIC_THRASHING_SUSPECTED")
```

The detector key is normalized tool + target/symbol/query + current source snapshot; a changed source snapshot or genuinely new evidence resets the no-progress sequence. Test fixtures construct `fake_router` as a deterministic router returning fixed envelopes and `temporal_only_failure` as a `FailureEvidence` with timestamp correlation but no causal evidence reference.

- [ ] **Step 3: Run RED**

Run: `/tmp/gch-edp-allpass-venv/bin/python -m unittest tests.test_diagnostic_rca -v`
Expected: FAIL because `rca.py` does not exist.

- [ ] **Step 4: Implement bounded investigation planning**

Start every RCA with tasks for failure fact validation, immediate dependency/impact check, competing-cause check, blast-radius check, and evidence validation. Use the Analysis Router only for read-only supporting evidence. Stop at `max_steps`; unfinished tasks remain explicitly `IN_PROGRESS` or `FAILED` in the report.

- [ ] **Step 5: Implement five-whys as evidence questions, not free-form assertions**

Each next “why” is created only when the preceding causal claim has an evidence reference. A causal chain with missing proof is labeled `UNVERIFIED`; it cannot become a confirmed root-cause claim.

- [ ] **Step 6: Run tests and commit**

Run: `/tmp/gch-edp-allpass-venv/bin/python -m unittest tests.test_diagnostic_rca tests.test_diagnostic_analysis_router tests.test_diagnostic_context_fusion -v`
Expected: PASS.

```bash
git add runtime/diagnostics/rca.py runtime/diagnostics/adapters/rca_adapter.py runtime/orchestrator/diagnostic_context_bridge.py tests/test_diagnostic_rca.py
git commit -m 'feat(diagnostics): add bounded evidence-first rca'
```
### Task 9: Attach RCA Evidence to Full Plan Failures Without Changing Recovery Decisions

**Files:**
- Modify: `runtime/orchestrator/diagnostic_context_bridge.py`
- Modify: `runtime/orchestrator/production_full_plan_runner.py`
- Create: `tests/test_diagnostic_full_plan_integration.py`
- Modify: `tests/test_production_full_plan_runner.py`

**Interfaces:**
- Produces: `record_failure_diagnostics(*, harness_root, project_id, run_id, gate_id, reason, failure_class) -> str | None`.
- Return value is an evidence reference only; it cannot return a replacement state, retry decision, Provider, approval, or completion value.
- Full Plan failure classification/retry/wait/dead-letter code executes identically whether diagnostics succeeds, fails, or is disabled.

- [ ] **Step 1: Write RED state-equivalence tests**

Run the same controlled worker failure three times with diagnostics OFF, successful fake RCA, and failing fake RCA. In the test, `run_failure()` builds the same `DurableFullPlanSupervisor` fixture for each diagnostic mode, while `authority_projection()` keeps only canonical state/queue/retry/terminal fields. Assert those projections are identical.

```python
def test_rca_cannot_change_retry_or_terminal_state(self):
    off = run_failure(diagnostics="OFF")
    good = run_failure(diagnostics="SUCCESS")
    bad = run_failure(diagnostics="RAISE")
    self.assertEqual(authority_projection(off), authority_projection(good))
    self.assertEqual(authority_projection(off), authority_projection(bad))
```

- [ ] **Step 2: Write the read-only evidence-path test**

RCA evidence may be written only below:
```text
<harness>/_workspace/production-full-plan/<project>/<run>/diagnostics/
```
Assert no source file, ToolEffectJournal, approval artifact, completion artifact, queue entry, or state hash input is modified by the RCA call.

- [ ] **Step 3: Run RED**

Run: `/tmp/gch-edp-allpass-venv/bin/python -m unittest tests.test_diagnostic_full_plan_integration -v`
Expected: FAIL because the failure hook is absent.

- [ ] **Step 4: Add best-effort failure recording immediately after failure classification**

Call `record_failure_diagnostics()` after `_failure_class(reason)` is known. Wrap only the diagnostic call in `try/except Exception`; append a non-authoritative event line such as `DIAGNOSTIC_RCA_RECORDED` or `DIAGNOSTIC_RCA_FAILED`, then continue the pre-existing `_handle_failure()` branch unchanged.

- [ ] **Step 5: Run full runner/authority focused regression**

Run: `/tmp/gch-edp-allpass-venv/bin/python -m unittest tests.test_diagnostic_full_plan_integration tests.test_production_full_plan_runner tests.test_recovery_e2e tests.test_completion_authority tests.test_production_attention_watch -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add runtime/orchestrator/diagnostic_context_bridge.py runtime/orchestrator/production_full_plan_runner.py tests/test_diagnostic_full_plan_integration.py tests/test_production_full_plan_runner.py
git commit -m 'feat(diagnostics): attach non-authoritative rca evidence'
```
### Task 10: Add EDP Code-Intelligence Extension and Failure-Injection Regression

**Files:**
- Create: `standards/CODE_INTELLIGENCE_DIAGNOSTIC_EXTENSION.md`
- Create: `tests/test_diagnostic_authority_negative_space.py`
- Create: `tests/test_diagnostic_failure_injection.py`
- Modify: `tests/test_ai_office_integrated_qualification.py`

**Interfaces:**
- The extension defines applicable-only domains `CI-01` through `CI-09` from the approved spec.
- It explicitly inherits EDP-1.0 and states it cannot weaken the Universal PASS Gate.
- Integrated qualification returns diagnostic-domain evidence only when Diagnostic Intelligence is enabled.

- [ ] **Step 1: Write RED authority-negative-space tests**

Statically inspect `runtime/diagnostics` and fail if it imports or calls authority mutation symbols including:
```text
authorize_tool_operation
SingleToolBroker.execute
route_provider
resume_wait
resume_recoverable_block
cancel
materialize_*completion*
AttentionOutbox.publish
```

Permit type-only/data imports from diagnostic contracts and standard library. Also fail if `runtime/diagnostics` contains shell commands with `git commit`, `git push`, `systemctl`, Graphify hook/watch/install, or CodeGraph memory/docs/admin tools.

- [ ] **Step 2: Write RED failure-injection tests**

Cover these exact cases:
```text
DIAGNOSTIC_INTELLIGENCE_ENABLED=false
Graphify binary missing
CodeGraph binary missing
Graphify nonzero exit
CodeGraph nonzero exit
source SHA/tree changes during analysis
Full Plan supervisor restart while diagnostics are enabled
reconciler process restart from runtime-current
Graphify/CodeGraph source-file conflict
secret-pattern file present in source
oversized analyzer output
repeated RCA query/no new evidence
```
For every case assert canonical Full Plan/Provider/Tool/Completion authority projections are unchanged from diagnostics-OFF baseline.

- [ ] **Step 3: Add immutable-snapshot race test**

Start an analyzer against a copied diagnostic source snapshot, mutate the live test repository after snapshot creation, and assert the analyzer continues only on the immutable snapshot while its final envelope is marked `STALE` before advisory consumption.

- [ ] **Step 4: Run RED**

Run: `/tmp/gch-edp-allpass-venv/bin/python -m unittest tests.test_diagnostic_authority_negative_space tests.test_diagnostic_failure_injection -v`
Expected: FAIL until the extension and all safety checks are implemented.
- [ ] **Step 5: Implement the EDP extension document exactly**

Document the domains:
```text
CI-01 Source Snapshot Binding
CI-02 Graphify topology coverage
CI-03 CodeGraph dependency/impact coverage
CI-04 Graph conflict/raw-source verification
CI-05 related-test/verifier mapping
CI-06 freshness
CI-07 security/secret check
CI-08 fallback/disable equivalence
CI-09 post-change impact revalidation
```
Each domain defines Evidence, PASS, BLOCKED/N/A, and negative-space requirements. `DOMAIN_EVIDENCE_COVERAGE=100%` applies to all applicable CI domains before final PASS.

- [ ] **Step 6: Verify analyzers use the shared immutable copied snapshot**

Assert both Graphify and CodeGraph adapters call `runtime.diagnostics.security.prepare_source_snapshot()` and never index the live source root directly. Snapshot creation already captures binding before and after copy; mismatch must abort with `CODE_INTELLIGENCE_STALE`.

- [ ] **Step 7: Run the diagnostic safety suite**

Run: `/tmp/gch-edp-allpass-venv/bin/python -m unittest tests.test_diagnostic_contracts tests.test_diagnostic_graphify_adapter tests.test_diagnostic_codegraph_adapter tests.test_diagnostic_analysis_router tests.test_diagnostic_context_fusion tests.test_diagnostic_context_bridge tests.test_diagnostic_rca tests.test_diagnostic_full_plan_integration tests.test_diagnostic_authority_negative_space tests.test_diagnostic_failure_injection -v`
Expected: PASS.

- [ ] **Step 8: Run existing authority regressions**

Run: `/tmp/gch-edp-allpass-venv/bin/python -m unittest tests.test_provider_router tests.test_production_provider_router_integration tests.test_tool_authorization tests.test_effect_evidence_bridge tests.test_completion_authority tests.test_recovery_e2e tests.test_production_attention_watch -v`
Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add standards/CODE_INTELLIGENCE_DIAGNOSTIC_EXTENSION.md runtime/diagnostics tests/test_diagnostic_authority_negative_space.py tests/test_diagnostic_failure_injection.py tests/test_ai_office_integrated_qualification.py
git commit -m 'test(diagnostics): enforce edp authority and failure isolation'
```

### Task 11: Install and Live-Qualify Graphify and CodeGraph in SHADOW Mode

**Files:**
- Create: `docs/history/upgrades/2026-09-20-DIAGNOSTIC-INTELLIGENCE/SHADOW_QUALIFICATION.json`
- Create: `docs/history/upgrades/2026-09-20-DIAGNOSTIC-INTELLIGENCE/SHADOW_QUALIFICATION.md`
- No source-code mutation outside the already-committed installer/runtime files.

**Interfaces:**
- Installed Graphify: `~/.local/share/gch/diagnostics/graphify/0.9.58/bin/graphify`.
- Installed CodeGraph: `~/.local/share/gch/diagnostics/codegraph/0.20.1/bin/codegraph-server`.
- SHADOW qualification passes an explicit `DiagnosticConfig(mode="SHADOW")`/controlled environment to the bridge; no durable operational config is activated until Task 12.
- [ ] **Step 1: Install Graphify through the committed installer**

Run:
```bash
bash scripts/install_graphify_diagnostics.sh
~/.local/share/gch/diagnostics/graphify/0.9.58/bin/graphify --version
```
Required: exact version `0.9.58`; installer exits nonzero on wheel hash mismatch. Verify `git config --get core.hooksPath` and `.git/hooks` were not modified by installation.

- [ ] **Step 2: Install CodeGraph through the committed installer**

Run:
```bash
bash scripts/install_codegraph_diagnostics.sh
sha256sum ~/.local/share/gch/diagnostics/codegraph/0.20.1/bin/codegraph-server
~/.local/share/gch/diagnostics/codegraph/0.20.1/bin/codegraph-server --help
```
Required SHA-256: `32b26422fa5ffe0a130955b7f7df771f722b2d427d67f53f104d9907bdfb24a6`.

- [ ] **Step 3: Run three Graphify live scenarios against a clean source snapshot**

Queries:
```text
show the Full Plan supervisor and recovery path
show Provider Router and MPRF relationships
show Tool Broker to effect/completion authority relationships
```
Record command mode, version, source binding, latency, graph path, source files, result digest, and any truncation. Require canonical source files to appear in each result; Graphify writes must remain confined to `_workspace/diagnostics/.../graphify`.

- [ ] **Step 4: Run CodeGraph live structural scenarios**

Execute one-shot `codegraph_analyze_impact` for `route_provider`, `codegraph_find_related_tests` for `SingleToolBroker`, and `codegraph_get_callers` for `reconcile_all`. Require telemetry off, graph-only mode, isolated HOME, bounded outputs, and current source binding.

- [ ] **Step 5: Run conflict/fallback shadow scenarios**

Force Graphify missing, CodeGraph missing, then both missing using temporary adapter paths. Require `DEGRADED` evidence and unchanged provider prompt/output contract. Inject one synthetic disagreement and require `CONFLICT` with no advisory text.

- [ ] **Step 6: Write SHADOW qualification evidence**

The JSON record must include exact tool versions/hashes, source head/tree, focused test counts, live scenario results, fallback results, `control_authority=NONE`, `write_scope_expansion_count=0`, and `shadow_prompt_change_count=0`.

- [ ] **Step 7: Commit qualification evidence**

```bash
git add docs/history/upgrades/2026-09-20-DIAGNOSTIC-INTELLIGENCE/SHADOW_QUALIFICATION.*
git commit -m 'docs(diagnostics): qualify graphify and codegraph shadow mode'
```
### Task 12: Promote Qualified Diagnostics from SHADOW to ADVISORY

**Files:**
- Modify: `runtime/diagnostics/config.py`
- Modify: `runtime/orchestrator/production_full_plan_boot.py`
- Modify: `runtime/orchestrator/production_full_plan_entry.py`
- Create: `tests/test_diagnostic_operational_config.py`
- Modify: `tests/test_production_full_plan_boot.py`
- Modify: `tests/test_production_full_plan_entry.py`
- Create at operation time: `~/.config/gch/diagnostic-intelligence.json` (user-owned, mode `0600`, not committed)
- Create: `docs/history/upgrades/2026-09-20-DIAGNOSTIC-INTELLIGENCE/ADVISORY_QUALIFICATION.json`

**Interfaces:**
- Diagnostics remain OFF unless `GCH_DIAGNOSTIC_INTELLIGENCE_ENABLED=true` is explicitly present.
- When enabled, `GCH_DIAGNOSTIC_CONFIG` must point to an absolute, regular, non-symlink config file owned by the current user with no group/other write bits.
- File fields: `enabled`, `mode`, `graphify_cli`, `codegraph_binary`, `max_result_bytes`, `max_context_chars`.
- Full Plan service and transient worker units propagate only `GCH_DIAGNOSTIC_INTELLIGENCE_ENABLED` and `GCH_DIAGNOSTIC_CONFIG`; they never propagate API keys through this mechanism.

- [ ] **Step 1: Write RED config-file safety tests**

```python
def test_config_rejects_symlink_and_group_writable_file(self):
    with self.assertRaises(DiagnosticConfigError):
        DiagnosticConfig.load(symlink_path)
    config_path.chmod(0o664)
    with self.assertRaises(DiagnosticConfigError):
        DiagnosticConfig.load(config_path)

def test_config_file_is_ignored_without_explicit_enable_env(self):
    cfg = DiagnosticConfig.from_env({"GCH_DIAGNOSTIC_CONFIG": str(config_path)})
    self.assertFalse(cfg.enabled)
    self.assertEqual(cfg.mode, "OFF")
```

Also test unknown mode -> error, missing binary in ADVISORY -> error, and installed binary path mismatch -> error.

- [ ] **Step 2: Run RED and implement safe config loading**

Run: `/tmp/gch-edp-allpass-venv/bin/python -m unittest tests.test_diagnostic_operational_config -v`
Expected: FAIL before secure file loading exists, then PASS after implementation.

`DiagnosticConfig.from_env()` must return OFF unless the explicit enable flag is truthy. When enabled it calls `DiagnosticConfig.load(Path(env["GCH_DIAGNOSTIC_CONFIG"]))`; no default user-home config is auto-loaded during ordinary tests or ad-hoc imports.

- [ ] **Step 3: Write RED durable-environment propagation tests**

For the persistent reconcile unit, assert generated text contains only:
```text
Environment=GCH_DIAGNOSTIC_INTELLIGENCE_ENABLED=true
Environment=GCH_DIAGNOSTIC_CONFIG=/home/ywjo/.config/gch/diagnostic-intelligence.json
```
when those values are explicitly supplied to `systemd_user_unit()`.

For `transient_systemd_command()`, set those two variables in the test environment and assert the generated `systemd-run` command contains matching `--setenv=` arguments. Set `OPENAI_API_KEY=secret` and assert it is not forwarded.

- [ ] **Step 4: Implement allowlisted propagation**

Add optional `diagnostic_environment: Mapping[str, str] | None = None` to `systemd_user_unit()` / `install_user_unit()`. In `transient_systemd_command()`, read only the two allowlisted diagnostic variables from the current process and append `--setenv=KEY=value` before the executable. Reject newline/NUL values and non-absolute config paths.

Run: `/tmp/gch-edp-allpass-venv/bin/python -m unittest tests.test_diagnostic_operational_config tests.test_production_full_plan_boot tests.test_production_full_plan_entry -v`
Expected: PASS.

- [ ] **Step 5: Create the user-owned SHADOW config and qualify the durable env path**

Config content:
```json
{"enabled":true,"mode":"SHADOW","graphify_cli":"/home/ywjo/.local/share/gch/diagnostics/graphify/0.9.58/bin/graphify","codegraph_binary":"/home/ywjo/.local/share/gch/diagnostics/codegraph/0.20.1/bin/codegraph-server","max_result_bytes":262144,"max_context_chars":12000}
```
Write atomically and `chmod 0600`. Export the explicit enable/config variables only for the controlled qualification process and prove the bridge loads SHADOW while the same code with no enable variable remains OFF.

- [ ] **Step 6: Promote only after SHADOW qualification hashes match current tools/source**

Atomically rewrite only `"mode":"ADVISORY"`; keep tool paths and caps unchanged. Immediately run `tests.test_diagnostic_context_bridge`, `tests.test_provider_action_execution`, `tests.test_diagnostic_authority_negative_space`, and the environment-propagation tests with the real config path explicitly enabled.

- [ ] **Step 7: Record ADVISORY qualification**

Record config SHA-256, installed binary/wheel identities, source head/tree, prompt-boundary tests, stale/conflict suppression tests, durable environment propagation tests, API-key non-propagation proof, and `write_scope_expansion_count=0`.

- [ ] **Step 8: Commit code/evidence**

```bash
git add runtime/diagnostics/config.py runtime/orchestrator/production_full_plan_boot.py runtime/orchestrator/production_full_plan_entry.py tests/test_diagnostic_operational_config.py tests/test_production_full_plan_boot.py tests/test_production_full_plan_entry.py docs/history/upgrades/2026-09-20-DIAGNOSTIC-INTELLIGENCE/ADVISORY_QUALIFICATION.json
git commit -m 'feat(diagnostics): activate qualified advisory mode'
```
### Task 13: Reproject Current Governance State Before Final Validation

**Files:**
- Modify: `docs/DEVELOPMENT_PLAN.txt`
- Create: `docs/harness/CURRENT_OPERATIONAL_STATE.json`
- Create: `tests/test_current_operational_state_projection.py`

**Interfaces:**
- `CURRENT_OPERATIONAL_STATE.json` is a projection, not an authority replacement; it references sealed predecessor/final evidence by path and digest.
- `docs/DEVELOPMENT_PLAN.txt` begins with a current-state block before historical plan text.
- Historical PH5/PH7 OPEN sections remain byte-preserved below the current-state block and are explicitly labeled superseded-for-current-state where applicable.

- [ ] **Step 1: Write RED current-state tests**

```python
def test_development_plan_projects_current_state_before_historical_open_text(self):
    text = PLAN.read_text()
    self.assertLess(text.index("CURRENT_OPERATIONAL_STATE"), text.index("AUTHORIZED_SCOPE_AMENDMENT"))
    self.assertIn("AI_OFFICE_STABLE_BASELINE=DECLARED", text[:4000])
    self.assertIn("PH7_PROVIDER_EXPANSION=RUNTIME_ALL_PASS", text[:4000])
    self.assertIn("DIAGNOSTIC_INTELLIGENCE=ADVISORY_QUALIFIED", text[:4000])
```

Also assert `CURRENT_OPERATIONAL_STATE.json` binds predecessor baseline refs, PH7 operational ALL PASS ref, Bounded Turn ALL PASS ref, Graphify production qualification ref, CodeGraph qualification ref, and Advisory qualification ref.

- [ ] **Step 2: Run RED**

Run: `/tmp/gch-edp-allpass-venv/bin/python -m unittest tests.test_current_operational_state_projection -v`
Expected: FAIL because current projection does not exist.

- [ ] **Step 3: Add the current-state projection block**

Top block must state:
```text
CURRENT_OPERATIONAL_STATE: FINAL_OPERATIONALIZATION_IN_PROGRESS
AI_OFFICE_STABLE_BASELINE: DECLARED
PH7_PROVIDER_EXPANSION: PROVIDER_EXPANSION_RUNTIME_ALL_PASS
GROQ: ACTIVE / FREE_TIER_ONLY
DIAGNOSTIC_INTELLIGENCE: ADVISORY_QUALIFIED
RUNTIME_RELEASE: PENDING_FINAL_ACTIVATION
```
It must state that earlier `UPGRADE_REMAINS_OPEN` and provider-expansion prohibitions are historical predecessor constraints superseded only by their cited later approvals/evidence.

- [ ] **Step 4: Generate `CURRENT_OPERATIONAL_STATE.json` from exact committed evidence refs/digests**

Compute each referenced artifact hash with `sha256sum`, populate the JSON with those exact values, and make the test recompute every digest and fail on missing/mismatched evidence.

- [ ] **Step 5: Run governance and cross-document tests**

Run: `/tmp/gch-edp-allpass-venv/bin/python -m unittest tests.test_current_operational_state_projection tests.test_ai_office_integrated_qualification tests.test_test_discovery_integrity -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add docs/DEVELOPMENT_PLAN.txt docs/harness/CURRENT_OPERATIONAL_STATE.json tests/test_current_operational_state_projection.py
git commit -m 'docs(governance): project current operational harness state'
```
### Task 14: Run Pre-Activation Full Regression and Activate One Durable Runtime Generation

**Files:**
- Create: `docs/history/upgrades/2026-09-20-FINAL-OPERATIONAL/EDP_PRE_ACTIVATION_VALIDATION.json`
- Operational mutation: `~/.local/share/global-gpt-harness/releases/*`, `runtime-current`, user systemd unit/timer.
- Operational mutation: update the existing `Harness Attention Watch` automation to execute from `runtime-current`.

**Interfaces:**
- Runtime release is built only from a clean committed tree.
- `runtime-current` points to an immutable release directory, never to a disposable worktree.
- Reconciler code root is `runtime-current`; job search root is `/home/ywjo/AI-Workspace/project-workspace`.
- Attention Watch uses the same `runtime-current` code root and the same job search root.

- [ ] **Step 1: Run the complete repository verification before deployment**

Run exactly:
```bash
/tmp/gch-edp-allpass-venv/bin/python -m unittest discover -s tests -v
/tmp/gch-edp-allpass-venv/bin/python -m compileall -q runtime tests
git diff --check
git status --short --branch
```
Required: 0 failures, 0 errors, compile rc=0, diff rc=0, clean worktree. Record exact test/skip counts and HEAD/tree SHA.

- [ ] **Step 2: Run EDP negative-space searches before activation**

Search for forbidden diagnostic authority, Graphify hook/watch/strict activation, CodeGraph telemetry/memory/admin tools, hardcoded Provider selection, diagnostic calls to Attention/recovery/completion mutation, and stale current-state text. Any material hit blocks activation until explained or corrected and regressed.

- [ ] **Step 3: Commit the pre-activation validation record**

The record binds the full-suite log digest, focused diagnostic log digest, compile/diff status, source HEAD/tree, tool versions/hashes, config SHA-256, blocker/major counts, and EDP coverage metrics. Commit with:
```bash
git add docs/history/upgrades/2026-09-20-FINAL-OPERATIONAL/EDP_PRE_ACTIVATION_VALIDATION.json
git commit -m 'docs(edp): qualify final operational runtime activation'
```

- [ ] **Step 4: Build an immutable runtime release from the exact validated code head**

Let `VALIDATED_CODE_HEAD` be the clean HEAD captured in Step 1 before the evidence-only commit. Run the runtime-release CLI/API with `--source-ref "$VALIDATED_CODE_HEAD"` to stage:
```text
~/.local/share/global-gpt-harness/releases/<VALIDATED_CODE_HEAD>/
```
Verify `RUNTIME_RELEASE_MANIFEST.json`, source head/tree, and runtime entry digest before link activation. The Step 3 evidence commit is administrative only and is not substituted for the tested code head.
- [ ] **Step 5: Repair and activate `runtime-current`**

Before retargeting, enumerate all registered jobs and require active-state count `0`. Then activate the immutable release. Verify:
```bash
readlink -f ~/.local/share/global-gpt-harness/runtime-current
readlink -f ~/.local/share/global-gpt-harness/runtime-current/runtime/orchestrator/production_full_plan_boot.py
```
Both must resolve under `~/.local/share/global-gpt-harness/releases/<HEAD>/` and no longer reference `PREPH5MPRF` or any worktree.

- [ ] **Step 6: Reinstall/reload the Full Plan reconciler against the durable runtime**

Use `/usr/bin/python3.12` and generate a unit equivalent to:
```text
WorkingDirectory=/home/ywjo/.local/share/global-gpt-harness/runtime-current
Environment=GCH_DIAGNOSTIC_INTELLIGENCE_ENABLED=true
Environment=GCH_DIAGNOSTIC_CONFIG=/home/ywjo/.config/gch/diagnostic-intelligence.json
ExecStart=/usr/bin/python3.12 -m runtime.orchestrator.production_full_plan_boot --search-root /home/ywjo/AI-Workspace/project-workspace
```
Install the 60-second persistent timer. Export `XDG_RUNTIME_DIR=/run/user/$(id -u)` and `DBUS_SESSION_BUS_ADDRESS=unix:path=$XDG_RUNTIME_DIR/bus` for verification commands.

- [ ] **Step 7: Verify live reconcile behavior**

Run from `runtime-current`:
```bash
/usr/bin/python3.12 -m runtime.orchestrator.production_full_plan_boot --search-root /home/ywjo/AI-Workspace/project-workspace --dry-run
systemctl --user is-enabled global-gpt-harness-full-plan-reconcile.service
systemctl --user is-enabled global-gpt-harness-full-plan-reconcile.timer
systemctl --user is-active global-gpt-harness-full-plan-reconcile.timer
```
Required: boot command structural rc=0; service/timer enabled; timer active. Historical terminal/wait jobs may be reported as preserved/skipped and are not blockers. Then run `systemctl --user restart global-gpt-harness-full-plan-reconcile.service` and require successful oneshot completion to prove the reconciler restart path from `runtime-current`.

- [ ] **Step 8: Rebind Harness Attention Watch to the same runtime generation**

Update the existing automation prompt so its command is executed from `/home/ywjo/.local/share/global-gpt-harness/runtime-current` and invokes:
```text
/usr/bin/python3.12 -m runtime.orchestrator.production_attention_watch --search-root /home/ywjo/AI-Workspace/project-workspace
```
Keep it read-only and preserve its existing historical event cutoff/dedup semantics. Because the automation platform supports no cadence faster than hourly, retain the hourly condition-watch schedule rather than claiming 30-minute coverage.

- [ ] **Step 9: Verify Attention code identity and runtime smoke**

Hash `production_attention_watch.py` in the committed source and `runtime-current`; require identical SHA-256. Run the command once and require valid JSON output with no import/runtime error.
- [ ] **Step 10: Record activation evidence and commit**

Create `docs/history/upgrades/2026-09-20-FINAL-OPERATIONAL/RUNTIME_ACTIVATION_EVIDENCE.json` containing runtime link target, release manifest digest, systemd unit/timer text digests, live dry-run result digest, attention source SHA equality, diagnostic config digest, Graphify/CodeGraph installed identities, and OmniRoute listener/auth smoke status.

```bash
git add docs/history/upgrades/2026-09-20-FINAL-OPERATIONAL/RUNTIME_ACTIVATION_EVIDENCE.json
git commit -m 'docs(runtime): record durable harness activation evidence'
```

### Task 15: Final EDP Re-Diagnosis, ALL PASS Seal, and Mainline Convergence

**Files:**
- Create: `docs/history/upgrades/2026-09-20-FINAL-OPERATIONAL/EDP_FINAL_ALL_PASS.json`
- Create: `docs/history/upgrades/2026-09-20-FINAL-OPERATIONAL/EDP_FINAL_ALL_PASS.md`
- Create: `docs/history/upgrades/2026-09-20-FINAL-OPERATIONAL/AI_OFFICE_HARNESS_FINAL_OPERATIONAL_BASELINE_DECLARATION.json`
- Create: `docs/history/upgrades/2026-09-20-FINAL-OPERATIONAL/FINAL_MANIFEST.json`
- Modify: `docs/harness/CURRENT_OPERATIONAL_STATE.json`
- Modify: `docs/DEVELOPMENT_PLAN.txt`

**Interfaces:**
- Final baseline ID: `AI_OFFICE_HARNESS_FINAL_OPERATIONAL_BASELINE`.
- Final technical decision: `ALL_PASS` / `GO` only when the Universal EDP gate is satisfied.
- Main integration is `--ff-only`; force-push and non-fast-forward merge are prohibited.

- [ ] **Step 1: Re-run the entire verification suite after live activation**

Run:
```bash
/tmp/gch-edp-allpass-venv/bin/python -m unittest discover -s tests -v
/tmp/gch-edp-allpass-venv/bin/python -m compileall -q runtime tests
git diff --check
```
Additionally run Graphify and CodeGraph live smoke, diagnostic failure injection, runtime-current dry-run reconciliation, Attention Watch JSON smoke, OmniRoute version/listener/auth probe, and diagnostic config safety validation.

- [ ] **Step 2: Execute the EDP Mandatory Evidence Matrix and RTM**

Applicable domains must include at least: canonical source/baseline, runtime source convergence, recovery, attention, Provider authority, Tool/effect authority, completion authority, Graphify, CodeGraph, RCA, diagnostic freshness, conflict/fallback, security/secrets, governance projection, and operational restart path.

Every applicable domain records exact evidence refs and status; `DOMAIN_EVIDENCE_COVERAGE` and `MUST_TRACEABILITY_COVERAGE` must each be `100%` before proceeding.
- [ ] **Step 3: Run Negative-Space, Cross-Document, and Adversarial Second Pass**

Explicitly try to falsify all of these claims:
```text
runtime-current survives removed worktrees
reconciler discovers jobs outside runtime release
Attention Watch runs the same runtime generation
diagnostics cannot mutate Full Plan/approval/provider/effect/completion/attention
Graphify hooks/watch/semantic API are absent
CodeGraph telemetry/memory/admin/docs mutation are absent
stale/conflicting intelligence cannot reach advisory prompt
RCA cannot cause retry/resume/reroute
Provider Router remains sole model/provider selector
Tool Broker remains sole effect launcher
current governance does not present historical OPEN state as current
```
Any counterexample reopens remediation and requires regression re-diagnosis before this task resumes.

- [ ] **Step 4: Run PASS Challenge and calculate closure metrics from evidence**

Required final values:
```text
BLOCKER_COUNT=0
UNRESOLVED_MAJOR_COUNT=0
MUST_REQUIREMENT_COVERAGE=100%
MUST_TRACEABILITY_COVERAGE=100%
DOMAIN_EVIDENCE_COVERAGE=100%
NEGATIVE_SPACE_OPEN_MATERIAL_COUNT=0
CROSS_DOCUMENT_CONFLICT_COUNT=0
BROKEN_REFERENCE_COUNT=0
UNRESOLVED_MATERIAL_TBD_COUNT=0
UNRESOLVED_MATERIAL_OPEN_QUESTION_COUNT=0
ADVERSARIAL_NEW_BLOCKER_MAJOR=0
PASS_CHALLENGE_OPEN_COUNT=0
SOURCE_AUTHORITY_STATUS=VALID
REGRESSION_REDIAGNOSIS_STATUS=PASS
MATERIAL_DEFECT_SEARCH=EXHAUSTED_FOR_AVAILABLE_EVIDENCE
```
Use measured values only; if any required value differs, final decision is not ALL PASS.

- [ ] **Step 5: Write the final closure artifacts**

`EDP_FINAL_ALL_PASS.json/.md` bind the measured tests, source head/tree, runtime activation evidence, CI-01..CI-09 evidence, negative-space/adversarial/PASS-challenge results. `AI_OFFICE_HARNESS_FINAL_OPERATIONAL_BASELINE_DECLARATION.json` declares the final baseline only if the JSON EDP decision is ALL_PASS. `FINAL_MANIFEST.json` hashes every closure artifact and predecessor authority reference.
- [ ] **Step 6: Update current-state documents to final GO and commit administrative closure**

Change the top current-state projection to:
```text
CURRENT_OPERATIONAL_STATE: AI_OFFICE_HARNESS_FINAL_OPERATIONAL_BASELINE
FINAL_EDP: ALL_PASS
RUNTIME_RELEASE: ACTIVE
GRAPHIFY: PRODUCTION_READ_ONLY_ACTIVE
CODEGRAPH: PRODUCTION_READ_ONLY_ACTIVE
HOLMES_INSPIRED_RCA: ACTIVE_READ_ONLY
DIAGNOSTIC_INTELLIGENCE: ADVISORY
```
Keep historical records below unchanged.

```bash
git add docs/history/upgrades/2026-09-20-FINAL-OPERATIONAL docs/harness/CURRENT_OPERATIONAL_STATE.json docs/DEVELOPMENT_PLAN.txt
git commit -m 'docs(harness): seal final operational baseline'
```

- [ ] **Step 7: Prove the administrative closure commit changed no runtime/test/script code**

Let `VALIDATED_CODE_HEAD` be the HEAD used in Step 1 and `CLOSURE_HEAD` be the new HEAD. Run:
```bash
git diff --exit-code "$VALIDATED_CODE_HEAD".."$CLOSURE_HEAD" -- runtime tests scripts standards
git diff --check "$VALIDATED_CODE_HEAD".."$CLOSURE_HEAD"
```
Required: runtime/tests/scripts/standards diff is empty; only closure/governance documentation changed.

- [ ] **Step 8: Publish the qualified upgrade branch, then fast-forward `main` only after ancestry and remote freshness checks**

First run `git push origin upgrade/ai-office-omniroute-ph7-20260920` and verify the branch upstream is `0/0` at `CLOSURE_HEAD`. Then run:
```bash
git fetch origin main
git merge-base --is-ancestor origin/main "$CLOSURE_HEAD"
```
Required rc=0. Create a temporary clean main integration worktree, fast-forward with `git merge --ff-only "$CLOSURE_HEAD"`, and run `git status --short --branch`. If ancestry fails or the worktree is not clean, stop without main merge/push.

- [ ] **Step 9: Re-run full regression from the fast-forwarded main worktree**

Run the exact full unittest discovery, compileall, and `git diff --check` from the main integration worktree. Required: same zero-failure result class as the validated upgrade branch.

- [ ] **Step 10: Push main without force**

Run:
```bash
git push origin main
```
Then verify `git rev-parse origin/main` equals `CLOSURE_HEAD`. Do not use `--force`, `--force-with-lease`, or merge commits.

- [ ] **Step 11: Rebuild `runtime-current` from the exact pushed main closure head**

Build a new immutable runtime release for `CLOSURE_HEAD` and activate it after confirming active Full Plan count remains zero. Because Step 7 proved no runtime-code delta from `VALIDATED_CODE_HEAD`, no behavior changes are introduced; nevertheless re-run reconcile dry-run, Attention Watch JSON smoke, Graphify/CodeGraph version smoke, and config validation.

- [ ] **Step 12: Final operator evidence**

Verify all of the following are simultaneously true:
```text
origin/upgrade/ai-office-omniroute-ph7-20260920 == CLOSURE_HEAD
origin/main == CLOSURE_HEAD
runtime-current manifest source_head == CLOSURE_HEAD
runtime-current boot/attention SHA == main boot/attention SHA
reconcile timer active
diagnostic config == ADVISORY / 0600
Graphify 0.9.58 available
CodeGraph 0.20.1 binary hash exact
OmniRoute loopback/auth smoke PASS
Groq ACTIVE remains FREE_TIER_ONLY
full repository regression PASS
```
Only then report `AI_OFFICE_HARNESS_FINAL_OPERATIONAL_BASELINE = ALL_PASS / GO`.
