# OCPv2 Final Acceptance / Release Closure Plan

**Date:** 2026-09-22
**Branch:** `impl/operator-control-plane-v2-r2`
**Pre-plan source:** `e74c1ceb41a3c8eaf1020afe1c9f2df285aad313`
**Execution mode:** Full Plan HYBRID
**User authorization:** Final Acceptance plan + execution approved

## Goal

Close the already-approved OCPv2/Harness scope with fresh operational, authority, recovery, release, and baseline evidence without silently expanding the project into PHASE 6 Jarvis Upgrade or a browser Dashboard implementation.

## Contract boundary

The authoritative `docs/DEVELOPMENT_PLAN.txt` explicitly places PHASE 6 Jarvis Upgrade + Project Continuity Memory outside PHASE 5 scope and forbids implicit PHASE 6/7 activation. Dashboard / BI / Material UI / Storybook / Superset are also listed out of scope. Therefore Final Acceptance for this branch validates the approved Harness/OCP runtime and release closure only.

`gui/orchestration_panel.py` is an orchestration display helper, not an HTTP/browser Dashboard server. Browser Dashboard and PHASE 6 Jarvis implementation require a successor approved contract and are not blockers for this branch's release closure.

## Invariants

- OCP remains transport/control ingress, never orchestration authority.
- Full Plan/Harness remains orchestration authority.
- Production Execution Gateway / Full MCP remain action/effect authority.
- Provider/model selection remains outside OCP.
- Registered jobs have exactly one immutable execution owner: `AUTO_RECONCILE` or `OCPV2`.
- OCP may execute only `OCPV2` jobs; generic Full Plan paths may execute only `AUTO_RECONCILE` jobs.
- Unknown ownership fails closed.
- No arbitrary shell, direct Full MCP, provider selection, job registration, or stage-authority bypass is introduced.
- The generic Full Plan periodic reconciler is not enabled merely for acceptance. Its operational activation is a separate topology decision unless existing approved authority explicitly requires it.
- Failed/rejected qualification evidence is preserved.
- No Final Acceptance PASS is declared without fresh release evidence.

## FA1 — Contract and topology inventory

**Purpose:** establish exactly what is and is not being accepted.

Checks:
- exact source/ref and PR head are identified;
- approved scope is reconciled against Dashboard/Jarvis expectations;
- runtime authority owners and service topology are documented;
- no invented Gate H or silent successor-scope implementation.

Exit evidence:
- PR checkpoint records scope diagnosis;
- Dashboard browser UI = successor scope;
- PHASE 6 Jarvis Upgrade = successor scope;
- current OCP/Harness Final Acceptance = allowed to continue.

## FA2 — Fresh ACTIVE operational continuity

**Purpose:** prove the deployed OCP control path is still alive after Gate F rather than relying only on historical activation evidence.

Checks:
- deployed runtime remains bound to the accepted release lineage;
- `OCP_MODE=ACTIVE` remains the intended mode;
- OCP timer/service has a successful recent one-shot cycle;
- no stale live control directive or unexpected replay churn;
- generic Full Plan periodic reconciler remains unchanged unless separately authorized.

Preferred proof: a bounded non-mutating control/liveness probe plus local service evidence when available. If live-host access is unavailable to the operator, record the exact missing host proof rather than inferring PASS.

## FA3 — Authority, replay, recovery and regression requalification

**Purpose:** verify the release candidate still preserves the safety invariants proven at Gates E/F.

Checks:
- single execution owner focused tests PASS;
- registered Full Plan resume tests PASS;
- crash-after-mutation / canonical result recovery tests PASS;
- OCP runtime service tests PASS;
- authority negative-space checks PASS;
- whole-repository full regression PASS;
- regression delta has no current-only regression;
- `compileall` / `git diff --check` or equivalent workflow checks PASS.

Exit evidence: exact-head GitHub Actions run with all required jobs successful.

## FA4 — Release candidate closure

**Purpose:** turn the validated branch into a reviewable release candidate without changing runtime authority.

Checks:
- PR #5 head matches the exact verified candidate;
- PR is mergeable;
- final acceptance evidence is attached to the PR;
- no unresolved acceptance blocker remains;
- draft status is removed only after FA2/FA3 evidence is adequate.

No merge may be claimed until exact-head checks are green.

## FA5 — Mainline integration

**Purpose:** integrate the accepted OCPv2 release and verify main, not only the feature branch.

Checks:
- merge PR #5 only after FA1–FA4 are satisfied;
- capture merge SHA;
- run/observe required mainline CI on the merged SHA;
- ensure no current-only regression appears on main;
- confirm the deployed runtime decision (pin/promote/redeploy) is explicit and does not silently change service topology.

Exit evidence: merged PR, exact main SHA, successful mainline verification.

## FA6 — Stable-baseline projection and cleanup disposition

**Purpose:** make repository operational documentation match the newly accepted runtime and preserve rollback.

Checks:
- update current operational-state/baseline projection to the final accepted main SHA and OCP ACTIVE status using evidence, not assumption;
- record Gate E/F + Final Acceptance evidence references;
- record Dashboard and PHASE 6 Jarvis Upgrade as successor scope;
- preserve rollback target until the new mainline/runtime is requalified;
- classify old runtime/worktrees as `KEEP_FOR_ROLLBACK`, `SAFE_TO_REMOVE`, or `UNKNOWN`; do not delete unknowns;
- final EDP/verification review before closure declaration.

Exit evidence:
- final acceptance closure record;
- current operational-state projection matches accepted mainline/runtime;
- cleanup disposition is explicit;
- project status can be declared complete **for the approved Harness/OCP scope only**.

## Stop / re-approval conditions

Stop and request scope approval before:
- implementing or activating browser Dashboard functionality;
- implementing PHASE 6 Jarvis Upgrade / Project Continuity Memory;
- enabling an additional recurring control/reconciliation owner not required by existing approved topology;
- changing provider/model selection authority;
- broadening OCP into arbitrary shell/tool execution;
- destructive cleanup that removes the only verified rollback path.

## Execution order

`FA1 → FA2 → FA3 → FA4 → FA5 → FA6`

A failure in any phase is diagnosed, fixed inside the already-approved scope if possible, then requalified before proceeding. Scope expansion follows the stop/re-approval rules above.
