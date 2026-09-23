# OCPv2 Approved Work Activation Runbook

Status: V1 TRACKING/MANUAL COMPATIBILITY ONLY — NOT EXECUTABLE PRIMARY-PATH AUTHORITY

> Post-canary diagnosis proved that this V1 flow registers `GPT_OPERATOR_PLAN` and can stop at `OPERATOR_TASK_RECEIPT_PENDING`. Preserve this runbook for V1 registration/replay compatibility only. Executable new-work qualification is governed by `docs/superpowers/specs/2026-09-23-approved-work-execution-link-remediation-design.md` after implementation.

## Purpose

This runbook promotes an already-approved Full Plan into the existing Harness job registry without requiring RDC or an interactive terminal. OCP remains transport/control only. AI Office remains workflow/governance. Full Plan remains planning and Gate authority. Product/source effects remain downstream of the existing execution gateway and Full MCP.

## Safety invariants

- `OCP_WORK_ACTIVATION_ENABLED` defaults to `0`.
- The first successor runtime is deployed with activation OFF.
- Activation is accepted only in OCP `ACTIVE` mode.
- The request must carry committed plan/spec/requirement evidence, explicit approval ref, exact branch/HEAD, approved Task IDs, runtime release digest, and one activation request ID.
- `OCP_WORK_ACTIVATION_POLICY_REF` must exactly match the request authorization ref.
- OCP never accepts caller provider/model/backend, arbitrary shell, argv, editable scope, or raw instruction promotion.
- Registration does not launch a process; existing Full Plan boot/reconcile owns launch/recovery.

## First successor deployment

1. Package the qualified successor code with `OCP_WORK_ACTIVATION_ENABLED=0`.
2. Do not set or rotate an activation policy merely to deploy the code.
3. Verify ordinary OCP polling and existing-run resume behavior with activation still OFF.
4. Host Inspection, if separately approved and enabled, does not imply Work Activation approval.
5. A live activation canary requires its own explicit approval before changing the feature flag.

## Canary prerequisites

Record the exact bounded canary evidence before enabling the feature:

- registered project alias and project ID;
- approved plan/spec paths and SHA-256 digests;
- canonical requirement-evidence path and SHA-256 digest;
- explicit user approval reference;
- expected branch and HEAD;
- approved Task/Gate IDs;
- runtime release manifest digest;
- unique activation request ID;
- one exact `OCP_WORK_ACTIVATION_POLICY_REF` value.

## Bounded canary sequence

1. Confirm the successor runtime is healthy with activation OFF.
2. With separate canary approval, set `OCP_WORK_ACTIVATION_ENABLED=1` and the exact approved policy ref.
3. Send exactly one typed `APPROVED_WORK_ACTIVATION` envelope for the approved request ID.
4. Verify the returned durable activation projection and its digest.
5. Verify exactly one canonical Full Plan job exists for that project/run ID.
6. Verify replay of the same sealed request does not create or register a second job.
7. Use the existing boot/reconcile path to observe the registered job; OCP does not launch it directly.
8. Return `OCP_WORK_ACTIVATION_ENABLED=0` after the bounded smoke unless a separate promotion is approved.

## Immediate rollback

- Set `OCP_WORK_ACTIVATION_ENABLED=0`.
- Leave already-registered canonical Full Plan jobs intact.
- Leave create-once activation receipts and remote outbox evidence intact.
- Do not delete, rewrite, or re-register a job merely because activation transport was disabled.
- Existing Full Plan boot/reconcile remains responsible for recovery of previously registered jobs.
- Do not silently fall back to RDC, Manual Action, arbitrary shell, or direct Full MCP.

## Qualification evidence

Before any live canary, keep these offline checks green:

```bash
python -m unittest tests.test_ocpv2_approved_work_activation_integration -v
python -m unittest tests.test_approved_work_binding tests.test_ai_office_activation tests.test_plan_activation tests.test_operator_plan_execution tests.test_production_full_plan_boot -v
python -m unittest tests.test_ocpv2_single_execution_owner tests.test_ocpv2_authority_negative_space -v
python -m unittest discover -s tests -v
```

The integration qualification must show that a typed, approved request registers one canonical job and that the existing boot reconciler discovers it without OCP spawning a process. Negative cases must register zero additional jobs.

## Promotion boundary

Passing this runbook is implementation qualification only. Changing a live OCP environment, switching runtime generations, enabling the feature, or sending a live activation canary remains a separate operational action requiring explicit approval.
