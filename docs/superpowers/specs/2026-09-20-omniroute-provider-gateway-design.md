# OmniRoute Non-Authoritative Provider Gateway Design

**Date:** 2026-09-20  
**Project:** Global GPT Harness / AI Office Harness  
**Baseline:** `AI_OFFICE_STABLE_BASELINE` at `897b8922ed5de0fbe8298d6f16ac84c4df2496d1`  
**Status:** DESIGN FOR REVIEW

## 1. Goal

Introduce OmniRoute as a non-authoritative provider discovery, transport, health, quota, and telemetry gateway without transferring Provider/Model selection authority away from the Harness Multi-Provider Router.

The first activation must make provider discovery observable and testable while preserving the current Codex + NVIDIA production baseline. No third provider becomes ACTIVE merely because OmniRoute can see it.

## 2. Authority Boundary

The authority chain remains:

`GPT Operator -> Full Plan -> Harness Multi-Provider Router -> Provider Execution Profile -> OmniRoute transport (when selected) -> Provider`

OmniRoute MUST NOT own or override:
- Full Plan task decomposition, Gate, fan-in, or next-state authority.
- Harness Provider/Model selection authority.
- MPRF lifecycle, checkpoint/resume, or canonical failover-policy authority.
- Full MCP state-changing effect authority.
- AI Office workflow/governance authority.

OmniRoute built-in `model:auto`, automatic provider routing, automatic provider fallback, MCP server, A2A server, and autonomous combo routing remain disabled in the initial integration.

## 3. Scope

### In scope
- Install a version-pinned OmniRoute runtime on the Jarvis server.
- Bind the service to loopback only.
- Require an OmniRoute API key on `/v1/*`.
- Store runtime data and secrets outside the Git repository with restrictive permissions.
- Run `doctor`, provider catalog discovery, provider list/test/validate, and local API smoke checks.
- Project discovered providers into a Harness-owned candidate inventory without activating them.
- Define admission states: `DISCOVERED -> CANDIDATE -> VALIDATING -> QUALIFIED -> APPROVAL -> ACTIVE`.
- Select a third-provider candidate only after evidence-based comparison.
- Add a transport adapter that treats OmniRoute as a gateway, not a routing authority.
- Validate safe failure/reroute semantics before any third provider becomes ACTIVE.
- Preserve current Codex/NVIDIA operation and stable baseline evidence.

### Out of scope for initial G0/G1
- OmniRoute automatic routing/fallback.
- OmniRoute MCP or A2A activation.
- Replacing MPRF Registry/Lifecycle/Failover contracts.
- Replacing Full MCP or granting OmniRoute filesystem/shell/git effect authority.
- Cloud/public exposure of the OmniRoute dashboard/API.
- Automatic credential acquisition or provider signup.
- Paid-provider activation without explicit credential and cost approval.

## 4. Installation Profile

Use npm package `omniroute@3.8.50`, because it is the current npm `latest` and is compatible with server Node `22.23.2`.

Runtime locations:
- package: npm global package, version pinned
- data: `~/.local/share/gch/omniroute/`
- secret/config env: `~/.config/gch/omniroute.env`, mode `0600`
- service log/evidence: Harness-owned evidence path; secrets must never be copied into Git

Security defaults:
- bind host: `127.0.0.1`
- port: `20128`
- `REQUIRE_API_KEY=true`
- unique generated JWT/API/storage secrets
- dashboard/API must not listen on LAN/public interfaces
- MCP/A2A disabled
- automatic routing/fallback disabled

The install must fail closed if the package version, bind address, secret-file permissions, or API-key enforcement differ from this contract.

## 5. Discovery and Admission

OmniRoute provider catalog is evidence only. A catalog entry does not become Harness-eligible automatically.

For each provider candidate record, capture:
- provider id/name
- protocol class
- credential requirement
- free/paid status when determinable
- model catalog visibility
- capability claims
- live readiness/test result
- latency evidence if a non-billable or approved smoke test is possible
- quota/rate visibility
- security/credential boundary
- adapter requirement

Harness admission lifecycle:
1. `DISCOVERED`: seen in OmniRoute catalog only.
2. `CANDIDATE`: passes static policy/suitability review.
3. `VALIDATING`: credential/access and live smoke are explicitly being tested.
4. `QUALIFIED`: required live tests and authority checks pass.
5. `APPROVAL`: activation package is complete and awaiting the required user decision if the provider introduces new cost/credential/network risk.
6. `ACTIVE`: only Harness MPRF/Router may expose the provider as eligible.

## 6. Candidate Selection Policy

Do not preselect Groq, Gemini, Claude, OpenRouter, or any other provider.

Rank candidates using evidence, not brand preference:
- protocol/adapter compatibility with the provider-neutral core
- reliability/readiness
- security and credential handling
- cost/free-tier constraints
- quota/rate limits
- latency
- reasoning/coding/tool capabilities
- structured-output quality
- context window and model availability
- operational observability

No `Codex-first`, `NVIDIA-first`, or OmniRoute-provider-first rule is permitted.

## 7. Runtime Integration

The Harness talks to OmniRoute only when the Router has selected an explicitly admitted OmniRoute-backed provider/model.

The request envelope must bind:
- operation request id
- provider id
- model ref
- execution profile
- capability requirements
- current Router decision digest

OmniRoute receives an explicit provider/model target. `model:auto` is prohibited in G1-G5.

If OmniRoute cannot force the explicitly selected provider/model without re-routing, that path is not eligible for production activation.

Returned output follows the existing canonical Harness proposal validation, raw/sanitized failure evidence, and Full MCP effect boundary.

## 8. Failure and Reroute

A gateway/provider failure is normalized into existing MPRF failure taxonomy.

Cross-provider reselection remains owned by the Harness Router. OmniRoute may report health/quota/rate/failure facts but may not silently choose a different provider.

`INVALID_RESPONSE` reroute remains allowed only when `CONFIRMED_NO_EFFECT` and failed-candidate exclusion are proven. Ambiguous effects fail closed and require reconciliation.

## 9. Validation Gates

### G0 — Review / install preflight
- npm package/version/engine compatibility confirmed.
- no port conflict on 20128.
- loopback-only binding plan validated.
- secret paths/permissions validated.
- no authority conflicts with Stable Baseline.

### G1 — Transport and discovery
- OmniRoute starts locally.
- `doctor` passes to the extent possible without provider credentials.
- `/v1/*` rejects unauthenticated access.
- provider catalog/list/validate commands work.
- no provider is automatically activated.
- auto-routing/fallback/MCP/A2A remain off.

### G2 — Telemetry projection
- health/quota/rate/provider facts can be normalized into Harness evidence without changing selection authority.

### G3-G5 — Candidate qualification
- one candidate at a time moves through CANDIDATE/VALIDATING/QUALIFIED.
- live smoke must use an explicitly selected provider/model.
- no hidden fallback is allowed.

### G6 — Optional routing/fallback study
Separate future approval only. It may evaluate OmniRoute routing features but cannot transfer canonical selection/failover authority from Harness without a new governance decision.

## 10. Test Discovery Cleanup Companion

The current duplicate `LVPreviewTest` discovery is caused by `tests/test_lv_execution_package.py` importing the `unittest.TestCase` class directly from `tests/test_lv_preview.py`.

Correction design:
- extract the reusable LV preview fixture into a non-TestCase helper module under `tests/support/`.
- make both test modules import the helper, never another TestCase class.
- assert that full unittest discovery contains each `LVPreviewTest` method exactly once.
- expected skip count decreases by one for the duplicated Wallet skip, with no test behavior suppressed.

This cleanup is independently testable but joins the OmniRoute work only at final operational qualification.

## 11. Final Qualification

Before declaring Provider Expansion ALL PASS:
- OmniRoute G0/G1 checks PASS.
- selected third-provider live qualification (if credentials/access are available) PASS.
- Codex/NVIDIA regression PASS.
- no authority transfer or double routing is detected.
- duplicate unittest discovery count is zero.
- full repository regression PASS.
- compileall and git diff-check PASS.
- secret scan PASS.
- negative-space and adversarial checks PASS.
- EDP blocker=0, unresolved major=0, traceability=100%.

If no third-provider credential/access is available, G0/G1 may PASS but third-provider activation and Provider Expansion final closure MUST remain OPEN; the system must not manufacture a fake ACTIVE provider.

## 12. External Reference Facts Checked 2026-09-20

- OmniRoute official quick start supports npm and Docker installation and uses port 20128.
- Current npm `omniroute` latest is 3.8.50; Node engine requirement is compatible with server Node 22.23.2.
- OmniRoute exposes headless provider discovery/test/validate commands and `doctor` diagnostics.
- OmniRoute supports API-key enforcement and loopback binding; public/untrusted exposure without API-key protection is unsafe.
- OmniRoute built-in automatic routing/fallback exists, therefore it is explicitly disabled under this design to avoid dual routing authority.
