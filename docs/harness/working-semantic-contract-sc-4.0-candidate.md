# SC-4.0-CANDIDATE — Broker-native Tool Transport

Status: Working Candidate
Decision: DEC-006 Option A
Requirement baseline: 1.0 unchanged
Does not modify: FINAL SC-1.0

- **SEM-025 ACTIVE — Tool Operation Identity.** Registry-issued identity exists before effect.
- **SEM-026 ACTIVE — Tool Authorization Contract.** Authorization exactly binds task, operation,
  capability, intent, scope, package, and approved decision.
- **SEM-027 ACTIVE — Single Brokered Tool Execution.** Governed effects have one broker path.
- **SEM-028 ACTIVE — Authorization is not Security Approval.** Authorized sensitive results block.
- **SEM-029 ACTIVE — Tool Effect Recovery Binding.** FINAL SEM-007–010 govern Tool effects.
- **SEM-030 ACTIVE — Worker Adapter Boundary.** Provider protocol ends inside its thin adapter.
- **SEM-031 ACTIVE/REFINED — Native Side-Effect Non-Bypass.** Production registers no native
  governed runtime and has no native fallback.
- **SEM-032 SUPERSEDED — Sealed Worker Sandbox.** Superseded; IDs are not reused.
- **SEM-033 SUPERSEDED — Sandbox-based Governed Resource Boundary.** Superseded; IDs are not reused.
- **SEM-034 ACTIVE — Context Snapshot.** Worker context is explicit and package-bound.
- **SEM-035 ACTIVE — Broker Tool Request/Result.** Provider-neutral, closed-schema transport.
- **SEM-036 NEW ACTIVE — Transport Version Compatibility Gate.** Production is pinned to Codex
  0.150.1 and blocks on version, experimental capability, or schema mismatch without fallback.
- **SEM-037 NEW ACTIVE — Closed Production Tool Registry.** Only package/task-required operations
  are registered; unknown, unbound, wildcard, and default operations block.
- **SEM-038 NEW ACTIVE — Native Runtime Absence / No Fallback.** Production command, file mutation,
  and independent MCP runtimes are absent. Broker failure produces zero fallback effects.

Codex upgrades require a separate compatibility gate after TASK-4A-08 actual closure.

## DEC-007 exact authorization and traceability

Only the following stable contracts may be activated for the sealed TASK-4A-08 Worker package:

| Contract ID | Operation | Requirement traceability |
| --- | --- | --- |
| `TAC_TASK_4A_08_PROJECT_OWNED_FILE_LIST_V1` | `PROJECT_OWNED_FILE_LIST` | REQ-002, REQ-011, REQ-013 |
| `TAC_TASK_4A_08_PROJECT_OWNED_FILE_READ_V1` | `PROJECT_OWNED_FILE_READ` | REQ-002, REQ-011, REQ-013 |
| `TAC_TASK_4A_08_PROJECT_OWNED_FILE_WRITE_V1` | `PROJECT_OWNED_FILE_WRITE` | REQ-002, REQ-007, REQ-008, REQ-009, REQ-010, REQ-011, REQ-013 |

Each contract binds DEC-007, TASK-4A-08, project, Gate, LV, run, canonical plan,
requirement digest, approved owned-scope digest, and canonical package-input digest.
LIST returns opaque owned-file IDs only. READ and WRITE accept only those IDs. WRITE follows
authorization → durable Intent → effect → security scan → durable Receipt. Unknown, unowned,
traversal, native command, generic shell, and independent MCP requests remain blocked.
