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

Current runtime work items are recorded in `docs/harness/orchestration-runtime-work-items.md`.
Jarvis bridge contract is documented in `docs/harness/orchestration-jarvis-bridge.md`.
Jarvis connection readiness is documented in `docs/harness/orchestration-jarvis-bridge-readiness.md`.

The document-based orchestration rules in `docs/harness/` remain the reference contract. This runtime layer expands them into executable file-based workflows without requiring external servers, queues, or databases.
