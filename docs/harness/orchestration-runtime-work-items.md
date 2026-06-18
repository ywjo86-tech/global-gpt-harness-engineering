# Orchestration Runtime Work Items

## Purpose

This document records the current runtime work items for the local orchestration engine and the document classes affected by each item.

## Work Item 1: Summary Standardization

Goal:
- Standardize fan-in, collection, and stage-gate summary markdown so the runtime emits compact, comparable review artifacts.

Document classes:
- runtime source
- runtime templates
- runtime tests
- runtime docs

Change targets:
- `runtime/orchestrator/summary_rendering.py`
- `runtime/orchestrator/result_collector.py`
- `runtime/orchestrator/fanin.py`
- `runtime/orchestrator/stage_gate.py`
- `tests/test_summary_rendering.py`
- `docs/harness/orchestration-runtime-engine.md`

## Work Item 2: Resume Granularity

Goal:
- Keep `run_id` resume behavior from re-running completed threads while rerunning only missing outputs.

Document classes:
- runtime source
- runtime tests
- runtime docs

Change targets:
- `runtime/orchestrator/engine.py`
- `runtime/orchestrator/cli.py`
- `runtime/orchestrator/schemas.py`
- `tests/test_codex_runtime_flow.py`

## Work Item 3: Result Normalization

Goal:
- Normalize worker and Codex outputs into a canonical result schema regardless of synonym-heavy payloads.

Document classes:
- runtime source
- runtime templates
- runtime tests
- runtime docs

Change targets:
- `runtime/orchestrator/result_normalizer.py`
- `runtime/orchestrator/worker_runner.py`
- `runtime/orchestrator/codex_adapter.py`
- `runtime/orchestrator/result_collector.py`
- `runtime/orchestrator/fanin.py`
- `runtime/orchestrator/stage_gate.py`
- `tests/test_result_normalizer.py`
- `tests/test_codex_adapter_manual_mode.py`
- `tests/test_result_collector.py`

## Work Item 4: Jarvis Bridge

Goal:
- Expose orchestration state and command dispatch through a file-based bridge that Jarvis Assistant can consume later.

Document classes:
- runtime source
- runtime bridge package
- runtime tests
- runtime docs

Change targets:
- `runtime/jarvis_bridge/state_reader.py`
- `runtime/jarvis_bridge/command_dispatcher.py`
- `runtime/jarvis_bridge/approval_handler.py`
- `runtime/jarvis_bridge/event_stream.py`
- `runtime/jarvis_bridge/bridge_api.py`
- `runtime/orchestrator/task_queue.py`
- `runtime/orchestrator/worker_pool.py`
- `runtime/orchestrator/retry_policy.py`
- `runtime/orchestrator/failure_recovery.py`
- `runtime/orchestrator/approval_inbox.py`
- `runtime/orchestrator/audit_log.py`
- `tests/test_jarvis_bridge_api.py`
- `tests/test_task_queue.py`
- `tests/test_worker_pool.py`
- `tests/test_retry_policy.py`
- `tests/test_failure_recovery.py`
- `tests/test_approval_inbox.py`
- `tests/test_audit_log.py`
- `docs/harness/orchestration-jarvis-bridge.md`

## Validation

- `inspect`, `plan`, `run`, `collect`, `fanin`, `gate`, and `status` must remain functional.
- Summary markdown must stay human-readable and stable across the three runtime summaries.
- Resume behavior must skip completed threads.
- Result normalization must preserve manual fallback and stage-gate status contracts.
- Bridge snapshots must be generated without requiring a separate UI runtime.
