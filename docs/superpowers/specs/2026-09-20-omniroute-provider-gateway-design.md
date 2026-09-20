# OmniRoute Non-Authoritative Provider Gateway Design

**Date:** 2026-09-20
**Project:** Global GPT Harness / AI Office Harness
**Predecessor Baseline:** `AI_OFFICE_STABLE_BASELINE` at `897b8922ed5de0fbe8298d6f16ac84c4df2496d1`
**Lifecycle:** PH7 Provider Expansion
**Status:** DESIGN EDP ALL-PASS CANDIDATE

## 1. Goal and Revision Authority

Introduce OmniRoute as a non-authoritative provider discovery, transport, health, quota, and telemetry gateway without transferring Provider/Model selection authority away from the Harness Multi-Provider Router.

The 2026-09-20 user directive authorizes this separate PH7 Provider Expansion lifecycle after the completed AI Office PH5 Stable Baseline. Historical PH5 contracts remain immutable evidence; their prior provider-expansion exclusions are not retroactively edited and do not prohibit this newly authorized lifecycle.

The first activation must make provider discovery observable and testable while preserving the current Codex + NVIDIA production baseline. No third provider becomes `ACTIVE` merely because OmniRoute can see it.

## 2. Frozen Material Requirements

| ID | Requirement | Class |
|---|---|---|
| OMR-001 | OmniRoute remains non-authoritative; Harness Multi-Provider Router retains Provider/Model selection authority. | MUST |
| OMR-002 | Full Plan, MPRF, Full MCP, and AI Office authority boundaries remain unchanged. | MUST |
| OMR-003 | Initial OmniRoute runtime is loopback-only and requires API-key enforcement. | MUST |
| OMR-004 | OmniRoute automatic routing/fallback must not silently replace the Provider/Model selected by Harness. | MUST |
| OMR-005 | Installation is version-pinned, provenance-verified, isolated to user-owned paths, and reversible. | MUST |
| OMR-006 | Secrets remain outside Git with restrictive permissions and are never copied into evidence. | MUST |
| OMR-007 | OmniRoute discovery is evidence only; discovery cannot directly create an `ACTIVE` Provider. | MUST |
| OMR-008 | Third-provider selection is evidence-based and provider-neutral. | MUST |
| OMR-009 | Live activation is blocked without actual credential/access and required provider-specific cost/risk approval. | MUST |
| OMR-010 | Gateway/provider failures normalize into MPRF; cross-provider reselection remains Harness Router-owned. | MUST |
| OMR-011 | Duplicate unittest discovery is fixed at its source rather than hidden, filtered, or accepted. | MUST |
| OMR-012 | Final operational qualification proves duplicate discovery count is zero before Provider Expansion ALL PASS. | MUST |
| OMR-013 | Install/start failure has a defined rollback path that preserves diagnostic evidence. | MUST |
| OMR-014 | Current state projection distinguishes completed PH5 Stable Baseline from authorized PH7 Provider Expansion. | MUST |

## 3. Authority Boundary

The authority chain remains:

`GPT Operator -> Full Plan -> Harness Multi-Provider Router -> Provider Execution Profile -> OmniRoute transport (when selected) -> explicit Provider/Model`

OmniRoute MUST NOT own or override:
- Full Plan task decomposition, Gate, fan-in, or next-state authority.
- Harness Provider/Model selection authority.
- MPRF lifecycle, checkpoint/resume, or canonical failover-policy authority.
- Full MCP state-changing effect authority.
- AI Office workflow/governance authority.

The Harness request MUST carry an explicit provider/model target. `model:auto`, automatic combo routing, and any OmniRoute-owned provider fallback are prohibited in G1-G5.

MCP/A2A agent surfaces are not integrated or invoked by Harness in G0-G5. Their presence in the package is not treated as authority; no Harness credential or workflow is delegated to them.

## 4. Scope

### In scope
- Install a version-pinned OmniRoute runtime in an isolated user-owned prefix on the Jarvis server.
- Bind the service to loopback only and require an API key on `/v1/*` before G1 PASS.
- Store runtime data and secrets outside the Git repository with restrictive permissions.
- Run `doctor`, provider catalog discovery, provider list/test/validate, and local API smoke checks.
- Project discovered providers into a Harness-owned candidate inventory without activating them.
- Use admission states: `DISCOVERED -> CANDIDATE -> VALIDATING -> QUALIFIED -> APPROVAL -> ACTIVE`.
- Select a third-provider candidate only after evidence-based comparison.
- Add a transport adapter that treats OmniRoute as a gateway, not a routing authority.
- Validate safe failure/reroute semantics before any third provider becomes `ACTIVE`.
- Preserve current Codex/NVIDIA operation and Stable Baseline evidence.
- Remove the existing duplicate `LVPreviewTest` unittest discovery before final operational qualification closes.

### Out of scope for G0/G1
- OmniRoute automatic routing/fallback as a Harness authority.
- OmniRoute MCP or A2A integration with Harness.
- Replacing MPRF Registry/Lifecycle/Failover contracts.
- Replacing Full MCP or granting OmniRoute filesystem/shell/git effect authority.
- Cloud/public exposure of the OmniRoute dashboard/API.
- Automatic credential acquisition or provider signup.
- Provider-specific paid credential activation without explicit cost/risk approval where applicable.
- Merge, push, release, or deployment outside this isolated qualification branch.

## 5. Installation and Supply-Chain Profile

### 5.1 Package binding

Use npm package `omniroute@3.8.50`.

Verified pre-design facts:
- server Node: `22.23.2`
- package Node engine: `>=22.22.2 <23 || >=24.0.0 <27`
- npm `dist.shasum`: `d7b4fce4f1b00e5e826b76855665dfae42aab97a`
- npm `dist.integrity`: `sha512-qK6REDWQYGh8lwGwDgFMsBqAMXnxIePudr8cSuSYeB9iIlywNhDJxHKt6Cwa31lPci8jXE5bbvl+az0lvyt0Mg==`
- inspected tarball SHA-256: `738c58af1faae8c57eb643a939d1191f8d7e083d9295ef61687d2bff04878c29`

G0 MUST re-fetch metadata and verify these bindings before installation. Package drift blocks installation and requires design/plan re-review.

### 5.2 Isolated installation

Do not use a system-global npm installation. Use a dedicated user-owned runtime prefix:
- runtime prefix: `~/.local/share/gch/omniroute/runtime/`
- data: `~/.local/share/gch/omniroute/data/`
- wrapper: `~/.local/bin/gch-omniroute`
- secret/config env: `~/.config/gch/omniroute.env`, mode `0600`

The implementation plan MUST use a version-pinned local-prefix npm install and verify the resolved binary reports `3.8.50` before service start. Install scripts may execute only inside the dedicated prefix. Evidence records version/integrity and exit status without secret values.

### 5.3 Security and non-authoritative controls

Package inspection shows the server bind default can be `0.0.0.0`, `REQUIRE_API_KEY` defaults false, and `OMNIROUTE_EMERGENCY_FALLBACK` defaults true. G1 MUST explicitly set and verify:

```text
OMNIROUTE_SERVER_HOST=127.0.0.1
PORT=20128
DATA_DIR=~/.local/share/gch/omniroute/data
REQUIRE_API_KEY=true
OMNIROUTE_EMERGENCY_FALLBACK=false
PROXY_AUTO_SELECT_ENABLED=false
OMNIROUTE_CONTROL_PLANE_PROXY_DIRECT_FALLBACK=false
OMNIROUTE_ENABLE_LIVE_WS=false
OMNIROUTE_DISABLE_BACKGROUND_SERVICES=true
```

Additional rules:
- `model:auto` is forbidden in G1-G5 Harness requests.
- Harness sends an explicit provider/model target and verifies returned identity matches.
- No combo/fallback chain may be selected by the Harness adapter in G1-G5.
- No listener other than the approved loopback HTTP service may be introduced by the G1 profile.
- `/v1/*` unauthenticated access MUST be rejected before G1 PASS.
- Secrets must not appear in process listings, Git, logs, or evidence.
- Background services remain disabled in G1; G2 telemetry enablement requires explicit evidence and cannot gain routing authority.

The install/runtime fails closed if version, bind address, API-key enforcement, hidden fallback controls, secret permissions, or listener inventory differ from this contract.

## 6. Discovery and Admission

OmniRoute provider catalog is evidence only. A catalog entry does not become Harness-eligible automatically.

For each provider candidate record, capture:
- provider id/name and protocol class
- credential requirement and free/paid status when determinable
- model catalog visibility and capability claims
- live readiness/test result
- latency evidence when a non-billable or explicitly approved smoke test is possible
- quota/rate visibility
- security/credential boundary and adapter requirement
- observed OmniRoute provider/model identity on live calls

Harness admission lifecycle:
1. `DISCOVERED`: seen in OmniRoute catalog only.
2. `CANDIDATE`: passes static policy/suitability review.
3. `VALIDATING`: credential/access and live smoke are explicitly being tested.
4. `QUALIFIED`: required live tests and authority checks pass.
5. `APPROVAL`: activation package is complete and awaits any unresolved provider-specific credential/cost/risk user decision.
6. `ACTIVE`: only Harness MPRF/Router may expose the provider as eligible.

Absence of third-provider credential/access is not a reason to manufacture an ACTIVE candidate. G0/G1 may close while G3-G5 and final Provider Expansion closure remain OPEN.

## 7. Candidate Selection Policy

Do not preselect Groq, Gemini, Claude, OpenRouter, or any other provider.

Compare candidates using recorded evidence:
- protocol/adapter compatibility with the provider-neutral core
- reliability/readiness
- security and credential handling
- cost/free-tier constraints and quota/rate limits
- latency
- reasoning/coding/tool capabilities
- structured-output quality
- context window and model availability
- operational observability

No `Codex-first`, `NVIDIA-first`, OmniRoute-provider-first, brand-first, or lexical-name-first policy is permitted.

A selection recommendation is not activation authority. The chosen candidate still follows `VALIDATING -> QUALIFIED -> APPROVAL -> ACTIVE`.

## 8. Runtime Integration

The Harness talks to OmniRoute only when the Router has selected an explicitly admitted OmniRoute-backed provider/model.

The request envelope MUST bind operation request id, provider id, model ref, execution profile, capability requirements, and current Router decision digest.

OmniRoute receives the explicit provider/model target. `model:auto` and automatic combo routing are prohibited in G1-G5. If OmniRoute cannot force the explicitly selected provider/model without re-routing, that path is not eligible for production activation.

Returned output follows the existing canonical Harness proposal validation, sanitized/hash-bound failure evidence, and Full MCP effect boundary.

## 9. Failure, Recovery, and Rollback

A gateway/provider failure is normalized into the existing MPRF failure taxonomy.

Cross-provider reselection remains owned by the Harness Router. OmniRoute may report health/quota/rate/failure facts but may not silently choose a different provider.

`INVALID_RESPONSE` reroute remains allowed only when `CONFIRMED_NO_EFFECT` and failed-candidate exclusion are proven. Ambiguous effects fail closed and require reconciliation.

Installation/runtime rollback MUST be possible without touching the PH5 Stable Baseline:
1. stop only the OmniRoute qualification service;
2. preserve sanitized failure logs/evidence and package provenance records;
3. remove or quarantine the dedicated wrapper and runtime prefix;
4. restore the prior `~/.config/gch/omniroute.env` backup if one existed;
5. verify port `20128` and any G1-specific listener are gone;
6. verify Codex/NVIDIA baseline regression remains unchanged;
7. record rollback result before retry.

No automatic restart loop is permitted after repeated G0/G1 configuration failure. A failed security binding remains fail-closed.

## 10. Validation Gates

### G0 — Review / install preflight
- package version, Node compatibility, npm integrity/shasum, and downloaded artifact SHA-256 match approved bindings;
- dedicated user-owned runtime/data/config locations are writable with expected permissions;
- no port conflict on `20128`;
- rollback commands and evidence destination are defined before install;
- no authority conflict with Stable Baseline.

### G1 — Transport and discovery
- OmniRoute `3.8.50` starts from the isolated runtime prefix;
- actual listener is `127.0.0.1:20128` only for the approved HTTP service profile;
- `doctor` runs and its result is recorded;
- `/v1/*` rejects unauthenticated access;
- `OMNIROUTE_EMERGENCY_FALLBACK=false` is verified;
- proxy auto-selection/direct fallback are disabled;
- live WebSocket and background services are disabled in the initial profile;
- provider catalog/list/validate commands work;
- no provider is automatically activated;
- no `model:auto`, combo, MCP, or A2A path is invoked by Harness.

### G2 — Telemetry projection
- health/quota/rate/provider facts can be normalized into Harness evidence without changing selection authority;
- any background telemetry service needed for G2 is individually justified and cannot make routing decisions.

### G3-G5 — Candidate qualification
- one candidate at a time moves through `CANDIDATE -> VALIDATING -> QUALIFIED`;
- live smoke uses an explicitly selected provider/model;
- response/evidence identity matches the selected provider/model;
- hidden fallback is not observed;
- required credential/cost/risk approval is resolved before `ACTIVE`.

### G6 — Optional routing/fallback study
Separate future approval only. It may evaluate OmniRoute routing features but cannot transfer canonical selection/failover authority from Harness without a new governance decision.

## 11. Mandatory Test Discovery Cleanup

This is a Provider Expansion completion requirement, not optional cleanup.

### Root cause
`tests/test_lv_execution_package.py` imports `LVPreviewTest`, a `unittest.TestCase`, directly from `tests/test_lv_preview.py`. Unittest discovery therefore exposes the imported TestCase in a second module namespace and collects the same 13 methods twice.

### Required correction
- extract the reusable LV preview fixture into a non-TestCase helper module under `tests/support/`;
- make `tests/test_lv_preview.py` and `tests/test_lv_execution_package.py` import only the helper;
- remove every direct import of `LVPreviewTest` from another discovered test module;
- do not use `__test__`, name hiding, discovery filters, skip decorators, or pattern exclusions to mask the duplicate;
- preserve all original assertions and behavior.

### Required evidence
Final operational qualification MUST record:
- each fully qualified `LVPreviewTest` method appears exactly once in full unittest discovery;
- `DUPLICATE_DISCOVERY_COUNT=0`;
- the Wallet checkout skip from `LVPreviewTest` appears at most once;
- no test method was deleted or skipped solely to reduce discovery count;
- test-count accounting equals `previous baseline count - 13 duplicate collections + newly added legitimate tests`;
- skip-count accounting equals `previous baseline skip count - 1 duplicate Wallet skip + newly introduced legitimate conditional skips`, with every remaining skip individually justified.

If any duplicate TestCase collection remains, Provider Expansion final closure is `NO_GO` regardless of OmniRoute/provider results.

## 12. Final Operational Qualification

Provider Expansion may be declared `ALL_PASS` only after all applicable items below are evidence-backed:
- OmniRoute G0/G1 checks PASS;
- G2 telemetry projection PASS if G2 is activated;
- selected third-provider live qualification PASS; if credentials/access are unavailable, final Provider Expansion closure remains OPEN rather than faking PASS;
- Codex/NVIDIA regression PASS;
- no authority transfer or double routing is detected;
- OMR-011/OMR-012 test-discovery cleanup is implemented and proven;
- `DUPLICATE_DISCOVERY_COUNT=0`;
- full repository regression PASS after cleanup and provider changes;
- all remaining skipped tests are enumerated and justified; duplicate-derived skip is gone;
- compileall and `git diff --check` PASS;
- secret scan PASS;
- listener/bind/API-key/fallback security checks PASS;
- rollback drill or deterministic rollback verification PASS before final closure;
- Negative-Space audit PASS;
- cross-document consistency PASS;
- adversarial second pass finds no new BLOCKER/MAJOR;
- PASS challenge has no open item;
- EDP metrics satisfy blocker=0, unresolved major=0, and MUST requirement/traceability/domain evidence=100%.

The final qualification artifact MUST distinguish:
- `DESIGN_EDP_ALL_PASS` — this design is complete and internally qualified;
- `PROVIDER_EXPANSION_RUNTIME_ALL_PASS` — only after implementation/live evidence and duplicate-discovery remediation actually pass.

## 13. Design Traceability Matrix

| Source obligation | Design representation | Planned proof | Status |
|---|---|---|---|
| OMR-001 | §§3, 7, 8 | Router decision identity vs gateway request | COVERED |
| OMR-002 | §§3, 8, 9 | authority negative-space tests | COVERED |
| OMR-003 | §5, G1 | listener + unauthenticated `/v1/*` rejection | COVERED |
| OMR-004 | §§3, 5, 8, G1/G3 | explicit provider/model identity + fallback-disabled checks | COVERED |
| OMR-005 | §5, G0 | npm integrity/version/artifact hash + isolated path | COVERED |
| OMR-006 | §5 | permission + secret scan | COVERED |
| OMR-007 | §6, G1 | inventory remains DISCOVERED/CANDIDATE | COVERED |
| OMR-008 | §7 | candidate evidence matrix | COVERED |
| OMR-009 | §§6, 12 | ACTIVE admission gate | COVERED |
| OMR-010 | §§8-9 | MPRF/reroute tests | COVERED |
| OMR-011 | §11 | helper extraction + discovery output | COVERED |
| OMR-012 | §§11-12 | `DUPLICATE_DISCOVERY_COUNT=0` final gate | COVERED |
| OMR-013 | §§5, 9, G0 | rollback verification | COVERED |
| OMR-014 | §§1, 14 + orchestration-state | cross-document state audit | COVERED |

## 14. Current-State Projection Rule

PH5 `AI_OFFICE_STABLE_BASELINE` remains declared and immutable as predecessor evidence.

PH7 Provider Expansion is a new authorized lifecycle. Design/implementation planning and controlled G0/G1 installation/discovery are authorized by the current user directive. No third provider is `ACTIVE` yet. Candidate-specific credentials, billable access, and new external cost/risk commitments require the corresponding explicit approval before `APPROVAL -> ACTIVE`.

Merge, push, release, and production deployment remain separate actions and are not implied by design approval.

## 15. External Package Facts Checked 2026-09-20

- npm package `omniroute@3.8.50` was inspected directly from the npm registry artifact.
- package Node engine is compatible with server Node `22.23.2`.
- provider CLI exposes `providers available`, `providers list`, `providers test`, and `providers validate`; `doctor` exists.
- package server-host code defaults to `0.0.0.0` unless `OMNIROUTE_SERVER_HOST` is set.
- `REQUIRE_API_KEY` feature default is false.
- `OMNIROUTE_EMERGENCY_FALLBACK` feature default is true.
- `PROXY_AUTO_SELECT_ENABLED` and control-plane direct fallback default false but are pinned explicitly for G1 evidence.
- live WebSocket defaults enabled and is explicitly disabled for G1.
- package includes postinstall/uninstall scripts, so installation is isolated and rollback-bound rather than system-global.

## 16. Design Closure Boundary

This document can reach `DESIGN_EDP_ALL_PASS` before runtime implementation because its target is the design contract itself. Runtime facts that do not yet exist are represented as fail-closed future evidence gates, not assumed PASS.

The following cannot be claimed by this design alone:
- OmniRoute installed and healthy;
- a third provider activated;
- provider live smoke passed;
- duplicate discovery removed in code;
- `PROVIDER_EXPANSION_RUNTIME_ALL_PASS`.

Those claims require implementation and final operational evidence under §§10-12.
