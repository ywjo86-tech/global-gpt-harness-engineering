# Orchestration Runtime

This package contains the local runtime orchestration engine used by the Global GPT Harness Engineering repository.

## Stage 1

Stage 1 established the local Python orchestration engine for planning, fan-out, fan-in, approval gating, and stage gating.

## Stage 2

Stage 2 adds a Codex execution adapter on top of the same file-based runtime.

- `manual` mode creates task prompts and waits for human execution.
- `codex-cli` mode best-effort runs task prompts through a local Codex CLI when available.
- `mock` mode keeps the local worker path for smoke tests and deterministic validation.
- `collect` gathers worker outputs into a collection report.
- `fanin` merges collected outputs into a fan-in report and prompt.
- `gate` creates or runs the stage gate review prompt and result.
- `inspect --read-only` validates a project-scoped contract mapping, source hashes, and static approval/gate evidence without constructing the runtime engine or writing state, logs, approvals, fan-out/fan-in outputs, or Gate artifacts.

Project-scoped mappings are opt-in. Projects without a mapping keep the legacy strict contract paths and fail-closed behavior. Mapping paths must stay relative to the selected project root, and mapped source hashes must match before a contract can load.

Read-only output keeps `business_lv_approval_state` and `business_gate_state` separate from `codex_runtime_sandbox_approval_state`. Static business or Gate evidence is never converted into, or reused as, Codex runtime/sandbox authorization.

Current runtime work items are recorded in `docs/harness/orchestration-runtime-work-items.md`.
Jarvis bridge contract is documented in `docs/harness/orchestration-jarvis-bridge.md`.
Jarvis connection readiness is documented in `docs/harness/orchestration-jarvis-bridge-readiness.md`.

The document-based orchestration rules in `docs/harness/` remain the reference contract. This runtime layer expands them into executable file-based workflows without requiring external servers, queues, or databases.
# Wallet Gate 0 canonical transition

The wallet project mapping uses four fail-closed states. `PRE_CHECKPOINT` selects
the approved V20 source. A working-tree-only `CLOSED`/`PASS` declaration is
rejected until a valid Gate 0 checkpoint is found in Git `HEAD`'s first-parent
history. The checkpoint's committed Gate report and approval count, head, full
record hashes, and chain must validate. The current `HEAD` approval log must
preserve and correctly extend that committed chain.
`GATE0_CLOSED_WAITING_GATE1_APPROVAL` reports the verified ancestor commit as
the checkpoint while continuing to select V20. Only a separate, mapped Gate 1
approval committed at the current `HEAD` and bound to the configured
`IMPLEMENTATION_PLAN.md` SHA-256 produces `TRANSITION_READY`. Working-tree-only
approval changes fail closed. A checkpoint SHA written inside the Gate report is
never used as evidence.
