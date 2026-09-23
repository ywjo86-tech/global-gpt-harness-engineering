# Executable Full Plan Live Canary Authorization Package

Status: PREPARED / FEATURE STILL OFF

- Project: `OCP-RDC-EXEC-CANARY-20260923`
- Alias: `ocp-rdc-exec-canary-20260923`
- Project root: `/home/ywjo/AI-Workspace/canary/OCP-RDC-EXEC-CANARY-20260923`
- Expected branch / HEAD: `main` / `e809a33d08f28f7f769648e44fe2ac78eaa1ac8e`
- Activation request / run ID: `GPT-FP-ACT-20260923-01`
- Gate / LV: `GATE-001` / `TASK-001`
- Executable policy ref: `RDC-INDEPENDENT-FULL-PLAN-CANARY-20260923`
- Live runtime source: `62405fb6f006a92ef311bb475a2a39d3033bb03a`
- Runtime manifest digest: `c98957619175a00e0f43fb0c440dfb4be10b49e5858673bbe0959adcd3ef6688`
- Executable authority bundle digest: `c930ea0bff8fa84481a208ada6b9866a5eda67755af2b11f221660bf846e0749`
- Final Gate approval SHA-256: `a79dd24c1340b7040293d90fda8c838bb5ee7ff1e55f5d23888768f8868b2693`
- Expected bounded effect: `canary.txt`, `baseline\n` -> `rdc-independent-full-plan-canary-pass\n`
- Validation: exact file content plus no change outside `canary.txt`; canonical Full Plan evidence required.
- Historical failed canary `GPT-ACT-20260923-02`: excluded, immutable, never reused.

Activation changes only `OCP_FULL_PLAN_ACTIVATION_ENABLED=1` and `OCP_FULL_PLAN_ACTIVATION_POLICY_REF=RDC-INDEPENDENT-FULL-PLAN-CANARY-20260923`. `OCP_MODE`, Host Inspection, V1 activation, diagnostic feature, Provider Router, execution owner policy and Harness `runtime-current` remain unchanged.

Rollback: disable executable activation (`OCP_FULL_PLAN_ACTIVATION_ENABLED=0`, remove its policy ref), restart one OCP one-shot, restore timer active, and preserve all registered Full Plan/evidence state for diagnosis. Product rollback, if required by canary outcome, is limited to the disposable project and must not touch the historical canary.

Expected final state after the test: executable Full Plan activation OFF, OCP `ACTIVE`, timer active, Host Inspection ON, read-only diagnostics ON, V1 work activation OFF.
