# OmniRoute Provider Expansion PH7 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Install and qualify OmniRoute as a non-authoritative local Provider gateway, discover and evaluate a real third-Provider candidate without fake activation, remove duplicate unittest discovery at its source, and close the Provider Expansion lifecycle only after EDP operational ALL PASS.

**Execution Status:** `COMPLETE` — Tasks 1–8 executed; Groq ACTIVE under `FREE_TIER_ONLY`; final operational decision `PROVIDER_EXPANSION_RUNTIME_ALL_PASS`; final EDP `ALL_PASS`. Historical OPEN evidence remains immutable and superseded by the final operational closure record.

**Architecture:** OmniRoute is a loopback-only transport/discovery service. Harness Multi-Provider Router remains the only Provider/Model selector, MPRF remains eligibility/lifecycle/recovery authority, and Full MCP remains effect authority. OmniRoute-discovered providers live in a separate admission inventory until an explicitly qualified candidate is promoted to ACTIVE.

**Tech Stack:** Python 3.12/unittest, Node.js 22.23.2, npm 10.9.8, OmniRoute 3.8.50, user-level systemd/CLI process control, existing MPRF/Router/Provider Runner registries.

**Spec:** `docs/superpowers/specs/2026-09-20-omniroute-provider-gateway-design.md`

## Global Constraints

- Preserve predecessor `AI_OFFICE_STABLE_BASELINE` at `897b8922ed5de0fbe8298d6f16ac84c4df2496d1`.
- Pin npm package identity exactly to `omniroute@3.8.50`; verify npm integrity `sha512-qK6REDWQYGh8lwGwDgFMsBqAMXnxIePudr8cSuSYeB9iIlywNhDJxHKt6Cwa31lPci8jXE5bbvl+az0lvyt0Mg==` before activation.
- Use user-owned installation/data/config paths only; do not modify system package state.
- Bind to `127.0.0.1:20128`; require API-key enforcement; disable emergency fallback, proxy auto-selection, direct control-plane fallback, live WS, and background services.
- OmniRoute `model:auto`, automatic cross-provider fallback, MCP, and A2A are prohibited through G5.
- No discovered Provider becomes ACTIVE without real credential/access, live qualification, and any required cost/risk approval.
- No Provider receives filesystem/shell/git effect authority from OmniRoute.
- Duplicate unittest discovery must be fixed at the import/fixture source; masking, filtering, or adding skips is prohibited.
- `DUPLICATE_DISCOVERY_COUNT=0` is a hard final closure condition.
- No merge, push, or deployment is authorized by this plan.

## Review Focus

1. OmniRoute starts with an unsafe default or silently re-enables fallback: preflight and runtime attestation must fail closed.
2. Catalog discovery accidentally changes MPRF eligibility: inventory tests must prove DISCOVERED/CANDIDATE are never Router-eligible.
3. Explicit Provider/Model request is silently rerouted by OmniRoute: gateway adapter must reject response/evidence that cannot prove target binding.
4. Provider credential is absent or paid usage is not approved: qualification must remain OPEN, never synthesize ACTIVE.
5. Duplicate unittest cleanup reduces counts by suppressing tests: integrity tests must prove each LVPreview method is collected once and no new skip is introduced.

---

## Requirement Traceability Matrix

| Requirement | Implementation | Validation / Proof | Closure Gate |
|---|---|---|---|
| OMR-001 | Tasks 3-5, 7 | Router-bound explicit target tests; no OmniRoute selection path | Task 8 negative-space/PASS Challenge |
| OMR-002 | Tasks 4, 7 | Provider ACTION authority regression; MPRF/Full MCP tests | Task 8 authority audit |
| OMR-003 | Tasks 1-2 | listener/auth readiness tests + live `ss`/unauthenticated `/v1/*` probe | G1 PASS |
| OMR-004 | Tasks 1, 4, 7 | fallback flags false; explicit-target mismatch rejection; reroute smoke | G1/G5 PASS |
| OMR-005 | Task 1 | pinned npm integrity + user-owned install + install-script tests | G0 PASS |
| OMR-006 | Tasks 1-2, 7 | mode-0600 validation + secret scan + redacted evidence tests | G1/final secret scan |
| OMR-007 | Task 3 | DISCOVERED/CANDIDATE projection-negative tests | G2 PASS |
| OMR-008 | Task 5 | brand-neutral evidence-vector tests | candidate evaluation PASS |
| OMR-009 | Tasks 3, 5, 7 | ACTIVE transition guards for credential/access/cost evidence | G5 activation gate |
| OMR-010 | Tasks 4, 7 | MPRF failure normalization and Harness-owned reroute smoke | G5 PASS |
| OMR-011 | Task 6 | imported-TestCase reproduction then source-level helper extraction | discovery integrity PASS |
| OMR-012 | Tasks 6, 8 | full-suite id count and `DUPLICATE_DISCOVERY_COUNT=0` | final closure hard gate |
| OMR-013 | Task 2 | start/stop/restart/failed-smoke rollback evidence | G1 PASS |
| OMR-014 | Task 8 | orchestration-state PH5 predecessor + PH7 active lifecycle projection | final cross-document PASS |

## Execution Preflight

Before Task 1, run the exact predecessor-baseline verification from this isolated branch after the plan/EDP planning artifacts are committed:

```bash
git status --short --branch
/tmp/gch-edp-allpass-venv/bin/python -m unittest discover -s tests -v
/tmp/gch-edp-allpass-venv/bin/python -m compileall -q runtime tests
git diff --check
```

Required: branch clean except explicitly approved local tool metadata; full suite has 0 failures/0 errors; compile/diff PASS. If not, diagnose before implementation rather than attributing the failure to OmniRoute work.

### Task 1: G0 OmniRoute install and security preflight

**Files:**
- Create: `runtime/orchestrator/omniroute_runtime.py`
- Create: `tests/test_omniroute_runtime.py`
- Create: `scripts/install_omniroute_gateway.sh`

**Interfaces:**
- Consumes: spec constants for version, integrity, bind address, forbidden features.
- Produces: `OmniRouteRuntimeConfig`, `validate_omniroute_preflight()`, `build_omniroute_env()`, and a user-level install script that exits non-zero on provenance/security mismatch.

- [x] **Step 1: Write the failing runtime-contract tests**

```python
class OmniRouteRuntimeTests(unittest.TestCase):
    def test_secure_env_is_loopback_and_disables_hidden_routing(self):
        env = build_omniroute_env(Path('/tmp/data'), 'secret-ref')
        self.assertEqual(env['OMNIROUTE_SERVER_HOST'], '127.0.0.1')
        self.assertEqual(env['REQUIRE_API_KEY'], 'true')
        self.assertEqual(env['OMNIROUTE_EMERGENCY_FALLBACK'], 'false')
        self.assertEqual(env['PROXY_AUTO_SELECT_ENABLED'], 'false')
        self.assertEqual(env['OMNIROUTE_CONTROL_PLANE_PROXY_DIRECT_FALLBACK'], 'false')
        self.assertEqual(env['OMNIROUTE_ENABLE_LIVE_WS'], 'false')
        self.assertEqual(env['OMNIROUTE_DISABLE_BACKGROUND_SERVICES'], 'true')
```

- [x] **Step 2: Run RED**

Run: `/tmp/gch-edp-allpass-venv/bin/python -m unittest tests.test_omniroute_runtime -v`
Expected: FAIL because `runtime.orchestrator.omniroute_runtime` does not exist.
- [x] **Step 3: Implement the bounded runtime contract**

```python
OMNIROUTE_VERSION = '3.8.50'
OMNIROUTE_NPM_INTEGRITY = 'sha512-qK6REDWQYGh8lwGwDgFMsBqAMXnxIePudr8cSuSYeB9iIlywNhDJxHKt6Cwa31lPci8jXE5bbvl+az0lvyt0Mg=='
OMNIROUTE_HOST = '127.0.0.1'
OMNIROUTE_PORT = 20128

def build_omniroute_env(data_dir: Path, api_key: str) -> dict[str, str]:
    return {
        'DATA_DIR': str(data_dir), 'PORT': '20128',
        'OMNIROUTE_SERVER_HOST': OMNIROUTE_HOST,
        'REQUIRE_API_KEY': 'true', 'OMNIROUTE_API_KEY': api_key,
        'OMNIROUTE_EMERGENCY_FALLBACK': 'false',
        'PROXY_AUTO_SELECT_ENABLED': 'false',
        'OMNIROUTE_CONTROL_PLANE_PROXY_DIRECT_FALLBACK': 'false',
        'OMNIROUTE_ENABLE_LIVE_WS': 'false',
        'OMNIROUTE_DISABLE_BACKGROUND_SERVICES': 'true',
    }
```

The preflight validator must also reject: unsupported Node version, occupied port 20128, secret file not mode 0600, symlinked runtime/config path, package version mismatch, and npm integrity mismatch.

- [x] **Step 4: Implement the user-owned install script**

Use the verified tarball itself as the install source; never re-resolve `latest` after verification. The implementation script must perform this exact sequence:

```bash
VERSION=3.8.50
PREFIX="$HOME/.local/share/gch/omniroute-runtime"
TMP="$(mktemp -d)"
PACK_JSON="$(npm pack "omniroute@$VERSION" --json --pack-destination "$TMP")"
TARBALL="$TMP/$(python3 -c 'import json,sys; print(json.load(sys.stdin)[0]["filename"])' <<<"$PACK_JSON")"
INTEGRITY="$(python3 -c 'import json,sys; print(json.load(sys.stdin)[0]["integrity"])' <<<"$PACK_JSON")"
test "$INTEGRITY" = 'sha512-qK6REDWQYGh8lwGwDgFMsBqAMXnxIePudr8cSuSYeB9iIlywNhDJxHKt6Cwa31lPci8jXE5bbvl+az0lvyt0Mg=='
rm -rf "$PREFIX.new"
mkdir -p "$PREFIX.new"
npm install --prefix "$PREFIX.new" --omit=dev --no-audit --no-fund "$TARBALL"
"$PREFIX.new/node_modules/.bin/omniroute" --version | grep -Fx '3.8.50'
```

Only after validation, atomically replace the previous user-owned prefix. Preserve the previous prefix as rollback input until G1 passes. Do not use `sudo` or system-global npm mutation.

- [x] **Step 5: Run focused tests and static shell checks**

Run: `/tmp/gch-edp-allpass-venv/bin/python -m unittest tests.test_omniroute_runtime -v`
Run: `bash -n scripts/install_omniroute_gateway.sh`
Expected: PASS.

- [x] **Step 6: Commit**

```bash
git add runtime/orchestrator/omniroute_runtime.py tests/test_omniroute_runtime.py scripts/install_omniroute_gateway.sh
git commit -m 'feat(provider): add omniroute runtime preflight'
```
### Task 2: G1 local service lifecycle, readiness, and rollback evidence

**Files:**
- Modify: `runtime/orchestrator/omniroute_runtime.py`
- Create: `tests/test_omniroute_runtime_lifecycle.py`
- Create: `scripts/run_omniroute_gateway.sh`

**Interfaces:**
- Consumes: Task 1 runtime config and user-owned installation prefix.
- Produces: `probe_omniroute_runtime() -> OmniRouteReadiness`, a launcher that sources only the 0600 secret file, and rollback/stop evidence with no secret values.

- [x] **Step 1: Write RED tests for fail-closed readiness**

```python
def test_readiness_rejects_non_loopback_listener(self):
    probe = probe_omniroute_runtime(listener_hosts=('0.0.0.0',), auth_enforced=True)
    self.assertFalse(probe.ready)
    self.assertIn('non_loopback_listener', probe.reasons)

def test_readiness_rejects_unauthenticated_v1(self):
    probe = probe_omniroute_runtime(listener_hosts=('127.0.0.1',), auth_enforced=False)
    self.assertFalse(probe.ready)
```

- [x] **Step 2: Run RED**

Run: `/tmp/gch-edp-allpass-venv/bin/python -m unittest tests.test_omniroute_runtime_lifecycle -v`
Expected: FAIL because readiness/lifecycle functions do not exist.

- [x] **Step 3: Implement readiness and redacted evidence**

`OmniRouteReadiness` must record package version, executable path, listener host/port, authenticated `/v1/models` behavior, `doctor` result class, data-dir identity, and config SHA-256. Evidence may record secret-file path/mode and key presence boolean only; never secret values.

- [x] **Step 4: Implement start/stop/rollback script**

The launcher must export the explicit safe flags, start `omniroute serve --port 20128 --no-open --no-tray --no-recovery`, write a PID/evidence record, and stop cleanly on rollback. A failed G1 smoke must stop the service while preserving logs and must not delete evidence.

- [x] **Step 5: Perform G0/G1 operational smoke in user paths**

Run the version-pinned installer, launch locally, verify `ss -ltnp` shows only `127.0.0.1:20128`, verify unauthenticated `/v1/*` is rejected, run `omniroute doctor`, then stop and restart once to prove controlled lifecycle.

- [x] **Step 6: Commit**

```bash
git add runtime/orchestrator/omniroute_runtime.py tests/test_omniroute_runtime_lifecycle.py scripts/run_omniroute_gateway.sh
git commit -m 'feat(provider): govern omniroute local lifecycle'
```
### Task 3: Provider discovery inventory and admission lifecycle

**Files:**
- Create: `runtime/orchestrator/provider_candidate_inventory.py`
- Create: `tests/test_provider_candidate_inventory.py`
- Modify: `runtime/orchestrator/provider_runtime_binding.py`

**Interfaces:**
- Consumes: machine-readable `omniroute providers available --json`, `providers list --json`, `providers validate --json`, and Task 2 readiness evidence.
- Produces: immutable `ProviderCandidateRecordV1` records and `ProviderCandidateInventoryV1`; only `ACTIVE` records may be projected into MPRF production eligibility.

- [x] **Step 1: Write RED lifecycle/authority tests**

```python
def _record(state: str) -> ProviderCandidateRecordV1:
    return ProviderCandidateRecordV1(
        schema_version=PROVIDER_CANDIDATE_SCHEMA_V1,
        provider_id='provider-x', protocol_class='openai-compatible', state=state,
        model_refs=('provider-x/model-1',), credential_required=False,
        cost_class='free', capability_refs=('reasoning', 'read_only'),
        readiness_evidence_refs=('read-pass',) if state == 'ACTIVE' else (),
        action_evidence_ref='action-pass' if state == 'ACTIVE' else '',
        reroute_evidence_ref='reroute-pass' if state == 'ACTIVE' else '',
        activation_approval_ref='PH7-FREE-CANDIDATE' if state == 'ACTIVE' else '',
    )

def _base_snapshot() -> ProviderEligibilitySnapshotV1:
    return ProviderEligibilitySnapshotV1(
        ELIGIBILITY_SCHEMA_V1, 'base', {'nvidia': True},
        {'nvidia': 'nvidia/model'}, ('base-evidence',),
        provider_capabilities={'nvidia': ('reasoning', 'read_only')},
    )

def test_discovered_provider_never_becomes_router_eligible(self):
    inv = ProviderCandidateInventoryV1(( _record('DISCOVERED'), ))
    snapshot = project_active_candidates(_base_snapshot(), inv)
    self.assertNotIn('provider-x', snapshot.provider_eligible)

def test_only_active_record_can_project_to_mprf(self):
    inv = ProviderCandidateInventoryV1(( _record('ACTIVE'), ))
    snapshot = project_active_candidates(_base_snapshot(), inv)
    self.assertTrue(snapshot.provider_eligible['provider-x'])
```

- [x] **Step 2: Run RED**

Run: `/tmp/gch-edp-allpass-venv/bin/python -m unittest tests.test_provider_candidate_inventory -v`
Expected: FAIL because inventory contracts do not exist.

- [x] **Step 3: Implement exact admission states and transition validation**

```python
ADMISSION_STATES = ('DISCOVERED', 'CANDIDATE', 'VALIDATING', 'QUALIFIED', 'APPROVAL', 'ACTIVE')
ALLOWED_TRANSITIONS = {
    'DISCOVERED': {'CANDIDATE'}, 'CANDIDATE': {'VALIDATING'},
    'VALIDATING': {'QUALIFIED', 'CANDIDATE'}, 'QUALIFIED': {'APPROVAL'},
    'APPROVAL': {'ACTIVE', 'QUALIFIED'}, 'ACTIVE': set(),
}
```

Every record binds provider id, protocol class, explicit model refs, credential requirement, cost/risk disposition, live-test refs, readiness refs, and activation approval ref. Missing live evidence or approval must make `ACTIVE` invalid.

- [x] **Step 4: Add discovery importer without activation side effects**

The importer parses OmniRoute JSON into `DISCOVERED` records only. It must reject duplicate provider ids, malformed catalog objects, hidden `auto` pseudo-providers, and any input attempting to set state above `DISCOVERED`.

- [x] **Step 5: Connect ACTIVE-only projection to production binding**

Extend `collect_production_provider_eligibility()` with an optional validated inventory parameter. Existing Codex/NVIDIA behavior remains unchanged when no inventory is supplied. Projection must not create provider runners or credentials; it only exposes already-qualified ACTIVE facts.

- [x] **Step 6: Run focused regression and commit**

Run: `/tmp/gch-edp-allpass-venv/bin/python -m unittest tests.test_provider_candidate_inventory tests.test_production_mprf_binding tests.test_provider_router -v`
Expected: PASS.

```bash
git add runtime/orchestrator/provider_candidate_inventory.py runtime/orchestrator/provider_runtime_binding.py tests/test_provider_candidate_inventory.py
git commit -m 'feat(provider): add candidate admission inventory'
```
### Task 4: Explicit-target OmniRoute transport adapter

**Files:**
- Create: `runtime/orchestrator/omniroute_adapter.py`
- Modify: `runtime/orchestrator/provider_adapter_registry.py`
- Modify: `runtime/orchestrator/provider_execution_registry.py`
- Create: `tests/test_omniroute_adapter.py`

**Interfaces:**
- Consumes: Router-bound `provider_ref`, `model_ref`, execution profile, operation request id, and local OmniRoute API key reference.
- Produces: normalized Provider result for the already-selected target; it has no selection or fallback authority.

- [x] **Step 1: Write RED tests for explicit binding and hidden-fallback rejection**

```python
def test_adapter_sends_explicit_selected_model(self):
    result = run_omniroute_provider(prompt='x', provider='provider-x', model='provider-x/model-1', opener=self.fake)
    self.assertEqual(self.sent['model'], 'provider-x/model-1')

def test_adapter_rejects_response_that_proves_different_provider(self):
    with self.assertRaisesRegex(OmniRouteAdapterError, 'target binding'):
        normalize_omniroute_result(expected_provider='provider-x', expected_model='provider-x/model-1', raw=self.other_provider)
```

- [x] **Step 2: Run RED**

Run: `/tmp/gch-edp-allpass-venv/bin/python -m unittest tests.test_omniroute_adapter -v`
Expected: FAIL because the adapter does not exist.

- [x] **Step 3: Implement transport with explicit model only**

The adapter calls local `http://127.0.0.1:20128/v1/chat/completions` with `Authorization: Bearer <OmniRoute API key>` and an explicit Router-selected model. It must never emit `auto`, combo ids, or an empty model. For configured connections it also sends `X-OmniRoute-Connection` with the inventory-bound connection id. On success it must verify `X-OmniRoute-Provider` and `X-OmniRoute-Model` against the expected target; a different provider/model or positive `X-OmniRoute-Fallback-Attempts` is a target-binding failure.

```python
def validate_target_binding(headers, *, expected_provider: str, expected_model: str) -> None:
    provider = headers.get('X-OmniRoute-Provider', '').strip()
    model = headers.get('X-OmniRoute-Model', '').strip()
    fallback_attempts = int(headers.get('X-OmniRoute-Fallback-Attempts', '0') or '0')
    if provider != expected_provider or model != expected_model or fallback_attempts != 0:
        raise OmniRouteAdapterError('target binding mismatch')
```

- [x] **Step 4: Preserve existing Harness validation/effect boundaries**

Read-only results normalize to the existing Provider result shape. ACTION calls only generate proposal content consumed by the existing `PROVIDER_ACTION` validator/Broker path; the adapter receives no filesystem/shell/git tool authority.

- [x] **Step 5: Register only ACTIVE OmniRoute-backed providers**

Add a factory that returns `ProviderAdapterRegistry` / `ProviderRunnerRegistry` entries from validated ACTIVE inventory records. Do not add a hardcoded `groq`, `gemini`, or other provider branch to core execution code.

- [x] **Step 6: Run focused authority regression and commit**

Run: `/tmp/gch-edp-allpass-venv/bin/python -m unittest tests.test_omniroute_adapter tests.test_provider_adapter_registry tests.test_provider_execution_registry tests.test_provider_action_execution -v`
Expected: PASS.

```bash
git add runtime/orchestrator/omniroute_adapter.py runtime/orchestrator/provider_adapter_registry.py runtime/orchestrator/provider_execution_registry.py tests/test_omniroute_adapter.py
git commit -m 'feat(provider): add explicit omniroute transport adapter'
```
### Task 5: Evidence-based third-Provider candidate evaluation

**Files:**
- Create: `runtime/orchestrator/provider_candidate_evaluator.py`
- Create: `tests/test_provider_candidate_evaluator.py`
- Create: `docs/history/upgrades/2026-09-20-AI-OFFICE-OMNIROUTE-PH7/provider-candidates/README.md`

**Interfaces:**
- Consumes: Task 3 DISCOVERED inventory plus OmniRoute static catalog fields and approved non-mutating live probe results.
- Produces: a deterministic candidate evidence table; it may nominate a CANDIDATE but may not produce ACTIVE state.

- [x] **Step 1: Write RED tests for neutral evaluation**

```python
def _candidate(provider_id: str, *, ready: bool) -> CandidateEvidenceV1:
    return CandidateEvidenceV1(
        provider_id=provider_id, protocol_class='openai-compatible',
        credential_required=False, cost_class='free', live_ready=ready,
        latency_ms=100 if ready else None, quota_visible=True,
        rate_visible=True, structured_output=True, model_catalog_visible=True,
        observability_score=1,
    )

def test_brand_name_is_not_a_scoring_dimension(self):
    a = _candidate('z-provider', ready=True)
    b = _candidate('a-provider', ready=True)
    self.assertEqual(evaluate_candidate(a).score_vector, evaluate_candidate(b).score_vector)

def test_missing_live_access_cannot_be_qualified(self):
    result = evaluate_candidate(_candidate('provider-x', ready=False))
    self.assertNotEqual(result.recommended_state, 'QUALIFIED')
```

- [x] **Step 2: Run RED**

Run: `/tmp/gch-edp-allpass-venv/bin/python -m unittest tests.test_provider_candidate_evaluator -v`
Expected: FAIL because the evaluator does not exist.

- [x] **Step 3: Implement evidence vector, not a hidden Provider priority**

The evaluator records protocol compatibility, credential requirement, cost class, observed readiness, latency evidence, quota/rate visibility, structured-output support, context/model visibility, and operational observability. Provider name is identity only and must not add score.

- [x] **Step 4: Collect real OmniRoute catalog evidence**

Run the installed CLI with `providers available --json`, `providers list --json`, and `providers validate --json`. Persist only sanitized catalog/candidate metadata under the PH7 history folder; never persist provider API keys, OAuth cookies, or OmniRoute access tokens.

- [x] **Step 5: Nominate exactly one CANDIDATE only when evidence supports it**

Prefer no candidate over a fabricated candidate. If multiple candidates tie, retain all tied records as CANDIDATE and require the next live validation gate to break the tie; do not break ties by brand or lexical provider id.

- [x] **Step 6: Commit**

```bash
git add runtime/orchestrator/provider_candidate_evaluator.py tests/test_provider_candidate_evaluator.py docs/history/upgrades/2026-09-20-AI-OFFICE-OMNIROUTE-PH7/provider-candidates
git commit -m 'feat(provider): evaluate omniroute provider candidates'
```
### Task 6: Remove duplicate unittest discovery at the source

**Files:**
- Create: `tests/support/__init__.py`
- Create: `tests/support/lv_preview_fixture.py`
- Modify: `tests/test_lv_preview.py`
- Modify: `tests/test_lv_execution_package.py`
- Create: `tests/test_test_discovery_integrity.py`

**Interfaces:**
- Consumes: existing LV preview fixture behavior.
- Produces: `build_lv_preview_fixture(base: Path) -> tuple[Path, Path]` and discovery-integrity tests proving no imported TestCase duplication.

- [x] **Step 1: Write a RED discovery-integrity test**

```python
def _flatten(suite):
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from _flatten(item)
        else:
            yield item

def test_lv_execution_package_does_not_reexport_lv_preview_testcase(self):
    module = importlib.import_module('tests.test_lv_execution_package')
    suite = unittest.TestLoader().loadTestsFromModule(module)
    ids = [case.id() for case in _flatten(suite)]
    self.assertFalse(any('.LVPreviewTest.' in test_id for test_id in ids))
```

Add a second assertion that `tests.test_lv_preview` still exposes every original `LVPreviewTest` method exactly once.

- [x] **Step 2: Run RED and capture the duplicate IDs**

Run: `/tmp/gch-edp-allpass-venv/bin/python -m unittest tests.test_test_discovery_integrity -v`
Expected: FAIL because `tests.test_lv_execution_package` currently re-exports `LVPreviewTest`.

- [x] **Step 3: Extract only the reusable fixture**

Move `_fixture()` behavior into `tests/support/lv_preview_fixture.py` as a normal function. `tests/test_lv_preview.py` and `tests/test_lv_execution_package.py` both import that function. Neither test module imports another `unittest.TestCase` class.

- [x] **Step 4: Run GREEN focused tests**

Run: `/tmp/gch-edp-allpass-venv/bin/python -m unittest tests.test_lv_preview tests.test_lv_execution_package tests.test_test_discovery_integrity -v`
Expected: all functional tests PASS; Wallet environment smoke may skip once only.

- [x] **Step 5: Prove discovery-count normalization without suppression**

Run full discovery with verbose output and programmatically count test ids. Required evidence:
- every `LVPreviewTest` method id appears exactly once;
- `DUPLICATE_DISCOVERY_COUNT=0`;
- no test method was deleted;
- no new `skip`, `skipIf`, `skipUnless`, or `skipTest` was introduced by this task;
- the previously duplicated Wallet skip appears once, not twice.

- [x] **Step 6: Commit**

```bash
git add tests/support tests/test_lv_preview.py tests/test_lv_execution_package.py tests/test_test_discovery_integrity.py
git commit -m 'test(harness): remove duplicate unittest discovery'
```
### Task 7: Live third-Provider qualification and controlled activation

**Files:**
- Modify: `runtime/orchestrator/provider_candidate_inventory.py`
- Modify: `runtime/orchestrator/omniroute_adapter.py`
- Modify: `runtime/orchestrator/provider_runtime_binding.py`
- Create: `tests/test_omniroute_live_qualification_contract.py`
- Create: `docs/history/upgrades/2026-09-20-AI-OFFICE-OMNIROUTE-PH7/live-qualification/README.md`

**Interfaces:**
- Consumes: one or more Task 5 CANDIDATE records and actual access/credential state.
- Produces: QUALIFIED/APPROVAL/ACTIVE transition evidence for exactly the provider/model actually tested; otherwise leaves activation OPEN.

- [x] **Step 1: Write RED activation guards**

```python
def _qualified_candidate(*, live_read=True, action=True, reroute=True, cost_class='free'):
    return ProviderCandidateRecordV1(
        schema_version=PROVIDER_CANDIDATE_SCHEMA_V1,
        provider_id='provider-x', protocol_class='openai-compatible', state='QUALIFIED',
        model_refs=('provider-x/model-1',), credential_required=cost_class != 'free',
        cost_class=cost_class, capability_refs=('reasoning', 'read_only', 'patch_generation'),
        readiness_evidence_refs=('read-pass',) if live_read else (),
        action_evidence_ref='action-pass' if action else '',
        reroute_evidence_ref='reroute-pass' if reroute else '',
        activation_approval_ref='',
    )

def test_active_requires_live_read_model_and_reroute_evidence(self):
    candidate = _qualified_candidate(live_read=False, action=False, reroute=False)
    with self.assertRaisesRegex(CandidateInventoryError, 'live qualification'):
        transition_candidate(candidate, 'ACTIVE', approval_ref='USER-APPROVAL')

def test_paid_provider_requires_cost_risk_approval(self):
    candidate = _qualified_candidate(cost_class='paid')
    with self.assertRaisesRegex(CandidateInventoryError, 'cost'):
        transition_candidate(candidate, 'ACTIVE', approval_ref='')
```

- [x] **Step 2: Run RED**

Run: `/tmp/gch-edp-allpass-venv/bin/python -m unittest tests.test_omniroute_live_qualification_contract -v`
Expected: FAIL until activation evidence requirements are enforced.

- [x] **Step 3: Run real candidate probes without hidden fallback**

For each candidate under VALIDATING, run an explicit provider/model READ smoke through OmniRoute and record request/response hashes, selected target, latency, and sanitized failure class. If the Provider cannot be explicitly targeted, move it back to CANDIDATE and mark it production-ineligible.

- [x] **Step 4: Run proposal ACTION smoke without applying effects**

Use an ACTION-generation request that produces a canonical Provider proposal but stop before Full MCP effect application. Prove `CONFIRMED_NO_EFFECT`, schema validation, raw/sanitized invalid-response evidence behavior, and no filesystem/shell/git capability leakage.

- [x] **Step 5: Run safe reroute smoke**

Induce or simulate a classified provider failure using the approved test seam. Prove MPRF classifies the failure, excludes the failed provider/model, and Harness Router—not OmniRoute—owns any reselection. No test may rely on OmniRoute emergency fallback or `model:auto`.

- [x] **Step 6: Decide activation from evidence**

If a free/keyless candidate passes all required live gates, it may move QUALIFIED -> APPROVAL -> ACTIVE under the current user-authorized PH7 envelope if no new cost/credential risk is introduced. If provider-specific credentials, paid usage, OAuth, or new network risk are required, stop at APPROVAL and request that separate decision; never fabricate ACTIVE.

- [x] **Step 7: Run three-provider neutral-routing qualification if ACTIVE exists**

With Codex, NVIDIA, and the new ACTIVE provider eligible, run deterministic request vectors that prove no hardcoded provider priority, stable same-request selection, capability filtering, and health/quota exclusion.

- [x] **Step 8: Commit qualification records**

Commit only sanitized/hash-bound evidence and code/tests. Never commit credentials, OAuth material, cookies, bearer values, or raw secret-bearing responses.
### Task 8: Final operational qualification and EDP closure

**Files:**
- Modify: `docs/harness/orchestration-state.md`
- Create: `docs/history/upgrades/2026-09-20-AI-OFFICE-OMNIROUTE-PH7/EDP_PRE_OPERATIONAL_DIAGNOSIS.md`
- Create: `docs/history/upgrades/2026-09-20-AI-OFFICE-OMNIROUTE-PH7/EDP_POST_OPERATIONAL_ALL_PASS.md`
- Create: `docs/history/upgrades/2026-09-20-AI-OFFICE-OMNIROUTE-PH7/EDP_POST_OPERATIONAL_ALL_PASS.json`

**Interfaces:**
- Consumes: Task 1-7 code, runtime evidence, candidate inventory, full regression, and discovery-integrity evidence.
- Produces: `PROVIDER_EXPANSION_RUNTIME_ALL_PASS` only when every mandatory runtime condition is proven.

- [x] **Step 1: Run focused qualification**

Run all OmniRoute/runtime/inventory/adapter/reroute/discovery tests plus existing Router/MPRF/Provider ACTION/Attention/Exit Guard/AI Office qualification tests. Any failure reopens the owning task.

- [x] **Step 2: Run full repository regression**

Run: `/tmp/gch-edp-allpass-venv/bin/python -m unittest discover -s tests -v`
Run: `/tmp/gch-edp-allpass-venv/bin/python -m compileall -q runtime tests`
Run: `git diff --check`
Required: 0 failures, 0 errors, compile PASS, diff-check PASS.

- [x] **Step 3: Reconcile test count and skips**

Parse the verbose full-suite log and record total tests, exact skipped test ids/reasons, and duplicate ids. Closure requires `DUPLICATE_DISCOVERY_COUNT=0`; the duplicate Wallet skip must no longer exist. Every remaining skip must be classified as intentional environment/opt-in behavior or treated as an open finding.

- [x] **Step 4: Run negative-space and adversarial checks**

Prove: no OmniRoute `model:auto`; no emergency fallback; no public listener; no discovery-to-ACTIVE shortcut; no provider-name priority; no MPRF selection authority; no Provider effect authority; no secret persistence; no hidden fallback after target selection; no imported TestCase duplicate discovery.

- [x] **Step 5: Run PASS Challenge**

Attempt to falsify these claims independently: explicit target binding, ACTIVE admission evidence, Router-only reselection, loopback/API-key security, rollback, candidate neutrality, Codex/NVIDIA compatibility, third-provider evidence if activated, and duplicate-discovery zero.

- [x] **Step 6: Write EDP closure metrics**

Required values:

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
DUPLICATE_DISCOVERY_COUNT=0
MATERIAL_DEFECT_SEARCH=EXHAUSTED_FOR_AVAILABLE_EVIDENCE
```

- [x] **Step 7: Apply final decision correctly**

If a third Provider is genuinely ACTIVE and all metrics pass, set `PROVIDER_EXPANSION_RUNTIME_ALL_PASS`. If OmniRoute G0/G1 passes but no Provider can be honestly activated because credential/access/cost approval is missing, record G0/G1 PASS and keep final Provider Expansion closure OPEN rather than mislabeling ALL PASS.

- [x] **Step 8: Final verification and commit**

Run the full verification commands again against the exact staged tree, then commit the EDP evidence and current-state projection. Do not push, merge, or deploy.
