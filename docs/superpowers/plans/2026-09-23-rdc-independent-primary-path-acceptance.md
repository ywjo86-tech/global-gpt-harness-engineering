# RDC-Independent Primary Path Acceptance Plan

> **BLOCKED AMENDMENT (2026-09-23):** Task 2's activation→mutation portion is superseded pending implementation of `docs/superpowers/specs/2026-09-23-approved-work-execution-link-remediation-design.md`. Existing V1 activation/canary evidence proves tracking registration/replay only. Do not resume governed mutation or promote RDC status from the old canary. After remediation, restart the executable-activation live window with a fresh activation/run identity.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prove that normal GPT operation can inspect JARVIS-SERVER, start approved new work, resume existing work, and perform governed mutations without RDC participating in the tested path.

**Architecture:** This plan contains no new execution authority. It integrates the completed Host Inspection and Approved Work Activation features with existing OCPv2, Full Plan, Router/MPRF, Production Gateway, Full MCP, attention/recovery, and result delivery, then runs an explicit RDC-independent acceptance gate before documentation changes RDC to optional recovery status.

**Tech Stack:** Python 3 integration tests, existing systemd/OCPv2 deployment, GitHub control transport, existing Harness regression suites.

**Spec:** `docs/superpowers/specs/2026-09-23-ocp-observation-gateway-design.md`

**Prerequisites:** `2026-09-23-host-inspection-port.md` and `2026-09-23-approved-work-activation.md` completed and independently green.

## Global Constraints

- RDC may remain installed but cannot provide input, evidence, or command execution for the acceptance path.
- Host Inspection remains no-effect; tests/patches/Git mutation remain Full Plan/Full MCP effects.
- No silent fallback from OCP/Harness failure to RDC.
- Existing-run resume and new-work activation remain distinct request kinds.
- Final documentation may label RDC `OPTIONAL_RECOVERY` only after every gate below passes.

## Review Focus

1. Feature flags independently disabled/enabled: no cross-feature fallback or mixed authority.
2. Crash between job registration and result publication: canonical job remains single and result delivery can recover.
3. Inspection result becomes stale while mutation proceeds: stale evidence is labeled, never promoted to completion authority.
4. Existing run and new activation share project/task names: request identity prevents cross-run resume/registration.
5. RDC process is unavailable: all tested normal-path functions still complete or fail with typed governed errors.

---

### Task 1: Synthetic End-to-End Authority and Failure Integration



**Files:**
- Create: `tests/test_ocpv2_rdc_independent_primary_path.py`

**Interfaces:**
- Consumes: typed Host Inspection request/result, Approved Work Activation request/result, current V2 existing-run resume, existing Full Plan/Full MCP test fixtures.
- Produces: deterministic proof that the three OCP request classes do not cross authority boundaries.

- [ ] **Step 1: Write failing E2E test before any live acceptance**

```python
inspection = control.send(host_inspection("git.status"))
self.assertEqual(inspection.result_class, "HOST_INSPECTION_OK")
activation = control.send(approved_activation(binding))
self.assertEqual(activation.status, "REGISTERED")
resume = control.send(existing_run_resume(existing_job))
self.assertEqual(resume.result_class, "CANONICAL_FULL_PLAN_RESULT")
```

The fixture must record every callback so assertions prove: inspection called no mutation callback; activation registered exactly one new job and called no existing-run resume; resume registered no new job.

- [ ] **Step 2: Add crash/replay/staleness cases**

Simulate transport publish failure after sealed inspection/activation result, process restart, and replay. Assert no second inspection execution for a sealed result and no second job registration. Mark freshness metadata stale when appropriate rather than substituting a new observation.

- [ ] **Step 3: Run RED then implement only missing test harness adapters**

Run: `python -m unittest tests.test_ocpv2_rdc_independent_primary_path -v`
Expected before prerequisites are complete: feature/import failures; after prerequisites, PASS without production-authority shortcuts.

- [ ] **Step 4: Run authority regressions**

Run: `python -m unittest tests.test_ocpv2_rdc_independent_primary_path tests.test_ocpv2_single_execution_owner tests.test_ocpv2_authority_negative_space tests.test_ai_office_authority_negative_space -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tests/test_ocpv2_rdc_independent_primary_path.py
git commit -m "test(ocpv2): prove RDC-independent authority separation"
```

### Task 2: Live Successor Qualification With RDC Excluded From Evidence



**Files:**
- Create: `docs/harness/ocpv2-rdc-independent-acceptance-runbook.md`
- Add live evidence only under the existing Harness evidence/state root; do not store credentials in Git.

**Interfaces:**
- Consumes: deployed successor runtime with both new features initially OFF, existing OCP GitHub control channel, existing Full Plan boot/reconcile service.
- Produces: signed/digested acceptance evidence for each tested path.

- [ ] **Step 1: Qualify successor with both features OFF**

Verify OCP timer/service, current V2 mutation/resume regression, result publication, Full Plan boot reconciliation, and attention watch before enabling any new capability.

- [ ] **Step 2: Enable Host Inspection only and execute bounded live probes**

Through GPT → GitHub control → OCP only, request `git.branch`, `git.status`, `git.diff`, approved file read/search/metadata, `user_service.properties`, and `harness.attention`. Record request/result digests and source HEAD. Do not use RDC to collect or confirm these results.

- [ ] **Step 3: Enable Approved Work Activation canary**

Use a disposable approved canary spec/plan with explicit approval binding. Submit one activation request; verify exactly one canonical Full Plan job is registered, the existing boot reconciler discovers/launches it, and a repeated identical request does not create a second job.

- [ ] **Step 4: Prove governed mutation path**

From the registered canary Full Plan, perform one bounded file mutation plus focused validation through the existing Production Gateway/Full MCP path. Verify effect/audit evidence and single execution owner; Host Inspection may observe the resulting Git state but cannot perform the mutation.

- [ ] **Step 5: Prove RDC outage tolerance and rollback**

For the acceptance window, ensure no RDC command/session is used. If safe to do so under the approved operational procedure, disconnect or stop only the RDC remote bridge after OCP health is confirmed; otherwise prove via audit/evidence that no RDC invocation occurred. On any failure, disable the affected feature flag first and retain canonical Full Plan state.

### Task 3: Broad Regression, Documentation Promotion, and Closure



**Files:**
- Modify: `docs/DEVELOPMENT_PLAN.txt` only for the approved operational-status promotion.
- Modify/Create: relevant Harness/Jarvis operations documentation that currently treats RDC as a normal dependency.
- Do not modify Jarvis Bridge control implementation in this project; record that convergence for the later Jarvis Upgrade.

**Interfaces:**
- Produces: final acceptance record and operational label `RDC=OPTIONAL_RECOVERY`.
- Requires: Tasks 1-2 plus both prerequisite plans complete.

- [ ] **Step 1: Run the broad regression suite**

Run:
```bash
python -m unittest discover -s tests -v
git diff --check
```
Expected: all tests PASS, or any unrelated pre-existing failures are enumerated and resolved before closure; no hidden red suite is accepted.

- [ ] **Step 2: Run forbidden-path/source audit**

Search OCP/Host Inspection/Activation code for direct provider/model selection, `FullMCPRuntime.call`, arbitrary shell, duplicate project registry, duplicate approved-requirement store, direct Jarvis `OrchestrationEngine` addition, and a second independent result outbox. Every hit must be either an existing preserved boundary, a test, or documentation.

- [ ] **Step 3: Promote operations documentation only after all live gates PASS**

Document:
```text
PRIMARY: GPT -> OCPv2 -> AI Office/Harness -> Full Plan -> Router/MPRF -> Gateway -> Full MCP
READ:    GPT -> OCPv2 -> Host Inspection Port
RDC:     OPTIONAL_RECOVERY / BREAK_GLASS / INTERACTIVE_TERMINAL
```

Also record the later Jarvis Upgrade follow-up: direct `Jarvis Bridge -> OrchestrationEngine` control must converge to the common OCP/Harness control semantics.

- [ ] **Step 4: Commit closure documentation**

```bash
git add docs/DEVELOPMENT_PLAN.txt docs/harness/
git commit -m "docs(harness): promote RDC to optional recovery after acceptance"
```

## Plan Self-Review Result

- Spec coverage: the synthetic authority test, live no-RDC inspection, new-work activation, existing-run resume, governed mutation, replay/recovery, broad regression and final documentation promotion are all represented.
- Placeholder scan: no implementation placeholder is allowed.
- Review Focus coverage: feature isolation Task 1/2; crash/replay Task 1; stale inspection Task 1; cross-run identity Task 1; RDC unavailable Task 2.
- The plan deliberately defers Jarvis UI/Bridge convergence to the approved later Jarvis Upgrade; this prevents scope creep while preserving the target architecture.