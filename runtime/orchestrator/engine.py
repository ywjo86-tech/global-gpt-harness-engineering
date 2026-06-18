from __future__ import annotations

import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from runtime.agents import ProjectExecutionAgent, ProjectOrchestratorAgent

from .approval_gate import CAUTION, DANGEROUS, approval_prompt_for
from .codex_adapter import create_manual_task, detect_codex_cli, run_task_prompt
from .contract_loader import ContractLoadError, load_contract
from .execution_modes import CODEX_CLI, MANUAL, MOCK, normalize_execution_mode
from .fanin import build_fanin_report_from_collection, render_fanin_markdown
from .fanout import build_fanout_plan, write_json
from .prompt_builder import build_fanin_prompt
from .result_collector import collect_run_outputs
from .schemas import ExecutionContract, FanInReport, PlanningArtifact, RuntimeState, TaskSlice, WorkerRequest
from .stage_gate import run_stage_gate, write_stage_gate_prompt
from .state_store import StateStore, append_log_line
from .task_package import RunPackage, create_run_package


def _write_json(path: str | Path, payload: object) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


class OrchestrationEngine:
    def __init__(self, project_root: str | Path) -> None:
        self.project_root = Path(project_root).resolve()
        self.repo_root = Path(__file__).resolve().parents[2]
        self.contract: ExecutionContract | None = None
        self.store = StateStore(self.project_root)

    def _load_contract(self) -> ExecutionContract:
        self.contract = load_contract(self.project_root, strict=True)
        return self.contract

    def _resolve_run_id(self, explicit_run_id: str | None = None) -> str:
        if explicit_run_id:
            return explicit_run_id
        state = self.store.state
        if state.active_run_id:
            return state.active_run_id
        raise ValueError("A run_id is required when no active run exists.")

    def _run_root(self, run_id: str) -> Path:
        return self.project_root / "runtime" / "orchestrator_runs" / run_id

    def _build_planning_bundle(
        self,
        contract: ExecutionContract,
        state: RuntimeState,
        mode: str,
        *,
        run_id: str | None = None,
        reuse_existing: bool = False,
    ) -> tuple[PlanningArtifact, list[TaskSlice], list[TaskSlice], list[TaskSlice], RunPackage]:
        if reuse_existing and state.planning_artifact and state.active_run_id and not run_id:
            planning_artifact = PlanningArtifact.from_dict(state.planning_artifact)
        else:
            planner = ProjectOrchestratorAgent()
            planning_artifact = planner.build_plan(contract, state)
        executor = ProjectExecutionAgent()
        tasks = executor.materialize_tasks(planning_artifact, contract, state)
        runnable, pending = executor.segment_tasks(tasks, str(self.project_root))
        package = create_run_package(
            contract,
            state,
            planning_artifact,
            tasks,
            mode,
            run_id=run_id,
            codex_cli_available=detect_codex_cli(),
        )
        return planning_artifact, tasks, runnable, pending, package

    def _save_runtime_state(
        self,
        contract: ExecutionContract,
        state: RuntimeState,
        *,
        mode: str,
        package: RunPackage,
        tasks: list[TaskSlice],
        pending: list[TaskSlice],
        planning_artifact: dict[str, Any] | None = None,
        fanin_report: FanInReport | None = None,
        collection_report: dict[str, Any] | None = None,
        stage_gate_decision: dict[str, Any] | None = None,
        stage_gate_prompt_path: str | None = None,
        manual_execution_required: bool = False,
        approval_required: bool = False,
        collection_status: str = "idle",
        fanout_status: str = "planned",
        fanin_status: str = "idle",
        next_step: str = "",
    ) -> RuntimeState:
        runtime_state = RuntimeState(
            current_phase=contract.current_phase,
            active_run_id=package.run_id,
            run_root=package.run_root,
            execution_mode=normalize_execution_mode(mode),
            manual_execution_required=manual_execution_required,
            codex_cli_available=package.codex_cli_available,
            active_threads=[task.as_request_payload() for task in tasks],
            pending_workers=[task.as_request_payload() for task in pending],
            completed_workers=list(state.completed_workers),
            failed_workers=list(state.failed_workers),
            fanout_status=fanout_status,
            fanin_status=fanin_status,
            collection_status=collection_status,
            stage_gate_decision=stage_gate_decision or state.stage_gate_decision,
            stage_gate_prompt_path=stage_gate_prompt_path if stage_gate_prompt_path is not None else state.stage_gate_prompt_path,
            approval_required=approval_required,
            next_step=next_step,
            fanout_plan=[task.as_request_payload() for task in tasks],
            fanin_report=fanin_report.to_dict() if fanin_report else state.fanin_report,
            collection_report=collection_report or state.collection_report,
            planning_artifact=planning_artifact or state.planning_artifact,
        )
        self.store.save(runtime_state)
        return runtime_state

    def inspect(self) -> dict[str, object]:
        contract = self._load_contract()
        state = self.store.state
        return {
            "contract": contract.summary(),
            "state": state.to_dict(),
            "missing_files": list(contract.missing_files),
        }

    def plan(self, mode: str = MOCK, run_id: str | None = None) -> dict[str, object]:
        contract = self._load_contract()
        state = self.store.state
        normalized_mode = normalize_execution_mode(mode)
        planning_artifact, tasks, runnable, pending, package = self._build_planning_bundle(
            contract,
            state,
            normalized_mode,
            run_id=run_id,
            reuse_existing=False,
        )
        plan = build_fanout_plan(tasks)
        write_json(self.project_root / "runtime" / "fanout_plan.json", plan)
        updated = self._save_runtime_state(
            contract,
            state,
            mode=normalized_mode,
            package=package,
            tasks=tasks,
            pending=pending,
            planning_artifact=planning_artifact.to_dict(),
            manual_execution_required=normalized_mode == MANUAL,
            approval_required=bool(pending),
            collection_status="waiting_manual" if normalized_mode == MANUAL else "idle",
            fanout_status="planned",
            fanin_status="idle",
            next_step="run",
        )
        append_log_line(
            self.project_root / "logs" / "app.log",
            "plan",
            self.project_root.name,
            contract.current_phase,
            "planned",
            planning_artifact.planning_summary,
            "run",
        )
        return {
            "run_id": package.run_id,
            "run_root": package.run_root,
            "mode": normalized_mode,
            "planning_artifact": planning_artifact.to_dict(),
            "plan": plan,
            "package": package.to_dict(),
            "task_prompts": package.task_prompt_paths,
            "input_manifests": package.input_manifest_paths,
            "expected_outputs": package.expected_output_paths,
            "manual_execution_required": updated.manual_execution_required,
            "approval_required": updated.approval_required,
        }

    def _execute_local_worker(
        self,
        task: TaskSlice,
        contract_summary: dict[str, object],
        state_snapshot: dict[str, object],
    ) -> dict[str, object]:
        request_path = Path(task.worker_request_path or (Path(task.run_root) / "tasks" / task.thread_id / "worker_request.json"))
        result_path = Path(task.result_path or (Path(task.output_dir or Path(task.run_root) / "outputs" / task.thread_id) / "result.json"))
        request_path.parent.mkdir(parents=True, exist_ok=True)
        result_path.parent.mkdir(parents=True, exist_ok=True)
        request = WorkerRequest(
            project_root=str(self.project_root),
            task=task,
            contract_summary=contract_summary,
            state_snapshot=state_snapshot,
        )
        request_path.write_text(json.dumps(request.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
        subprocess.run(
            [
                sys.executable,
                "-m",
                "runtime.orchestrator.worker_runner",
                "--request-file",
                str(request_path),
                "--result-file",
                str(result_path),
            ],
            cwd=str(self.repo_root),
            check=True,
        )
        return json.loads(result_path.read_text(encoding="utf-8"))

    def _mirror_legacy_thread_output(self, task: TaskSlice, result_payload: dict[str, object]) -> None:
        legacy_dir = self.project_root / "runtime" / "threads" / task.thread_id
        legacy_dir.mkdir(parents=True, exist_ok=True)
        (legacy_dir / "worker_result.json").write_text(
            json.dumps(result_payload, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        handoff_source = Path(task.handoff_report_path)
        handoff_target = legacy_dir / "worker_handoff.md"
        if handoff_source.exists():
            handoff_target.write_text(handoff_source.read_text(encoding="utf-8"), encoding="utf-8")
        else:
            handoff_target.write_text(
                "\n".join(
                    [
                        f"# Worker Handoff - {task.thread_id}",
                        "",
                        f"Agent: {task.assigned_agent}",
                        "Status: completed",
                        "",
                        "Summary",
                        str(result_payload.get("summary", "")),
                    ]
                ).rstrip()
                + "\n",
                encoding="utf-8",
            )

    def _write_fanin_prompt(
        self,
        run_root: Path,
        contract: ExecutionContract,
        collection_report: dict[str, object],
        state_snapshot: dict[str, object],
    ) -> Path:
        fanin_dir = run_root / "fanin"
        fanin_dir.mkdir(parents=True, exist_ok=True)
        prompt_path = fanin_dir / "fanin_prompt.md"
        prompt_text = build_fanin_prompt(contract.summary(), state_snapshot, collection_report, str(run_root))
        prompt_path.write_text(prompt_text, encoding="utf-8")
        return prompt_path

    def _write_fanin_outputs(self, run_root: Path, fanin_report: FanInReport) -> None:
        fanin_dir = run_root / "fanin"
        fanin_dir.mkdir(parents=True, exist_ok=True)
        _write_json(fanin_dir / "fanin_report.json", fanin_report.to_dict())
        _write_json(fanin_dir / "fanin_result.json", fanin_report.to_dict())
        (fanin_dir / "fanin_report.md").write_text(render_fanin_markdown(fanin_report), encoding="utf-8")
        (fanin_dir / "fanin_result.md").write_text(render_fanin_markdown(fanin_report), encoding="utf-8")
        _write_json(self.project_root / "runtime" / "fanin_report.json", fanin_report.to_dict())
        _write_json(self.project_root / "runtime" / "fanin_result.json", fanin_report.to_dict())

    def _existing_completed_threads(self, run_root: str | Path) -> set[str]:
        collection = collect_run_outputs(run_root)
        return set(collection.completed_outputs)

    def run(self, mode: str = MOCK, run_id: str | None = None) -> dict[str, object]:
        contract = self._load_contract()
        state = self.store.state
        normalized_mode = normalize_execution_mode(mode)
        planning_artifact, tasks, runnable, pending, package = self._build_planning_bundle(
            contract,
            state,
            normalized_mode,
            run_id=run_id,
            reuse_existing=True,
        )
        plan = build_fanout_plan(tasks)
        write_json(self.project_root / "runtime" / "fanout_plan.json", plan)

        runnable_results: list[dict[str, object]] = []
        manual_tasks: list[dict[str, object]] = []

        if normalized_mode == MANUAL:
            for task in tasks:
                manual_tasks.append(create_manual_task(task.task_prompt_path, task.output_dir))
            updated = self._save_runtime_state(
                contract,
                state,
                mode=normalized_mode,
                package=package,
                tasks=tasks,
                pending=pending,
                manual_execution_required=True,
                approval_required=bool(pending),
                collection_status="waiting_manual",
                fanout_status="packaged",
                fanin_status="idle",
                next_step="manual execution required",
            )
            append_log_line(
                self.project_root / "logs" / "app.log",
                "run",
                self.project_root.name,
                contract.current_phase,
                "manual",
                f"{len(tasks)} prompt(s) generated",
                "manual execution required",
            )
            return {
                "run_id": package.run_id,
                "run_root": package.run_root,
                "mode": normalized_mode,
                "plan": plan,
                "package": package.to_dict(),
                "manual_tasks": manual_tasks,
                "pending_workers": [task.as_request_payload() for task in pending],
                "collection_status": updated.collection_status,
                "next_step": updated.next_step,
            }

        state_snapshot = state.to_dict()
        resumed_threads = sorted(self._existing_completed_threads(package.run_root))
        if resumed_threads:
            runnable = [task for task in runnable if task.thread_id not in set(resumed_threads)]
        if normalized_mode == CODEX_CLI:
            for task in runnable:
                result = run_task_prompt(task.task_prompt_path, task.output_dir, normalized_mode)
                runnable_results.append(
                    {
                        "thread_id": task.thread_id,
                        "assigned_agent": task.assigned_agent,
                        **result,
                    }
                )
                if str(result.get("mode")) == MANUAL or str(result.get("status", "")).startswith("manual"):
                    manual_tasks.append(result)
                elif Path(task.result_path).exists():
                    self._mirror_legacy_thread_output(task, json.loads(Path(task.result_path).read_text(encoding="utf-8")))
            for task in pending:
                manual_tasks.append(create_manual_task(task.task_prompt_path, task.output_dir))
        else:
            with ThreadPoolExecutor(max_workers=max(1, len(runnable))) as pool:
                futures = [pool.submit(self._execute_local_worker, task, contract.summary(), state_snapshot) for task in runnable]
                runnable_results = [
                    {
                        "thread_id": task.thread_id,
                        "assigned_agent": task.assigned_agent,
                        **future.result(),
                    }
                    for task, future in zip(runnable, futures)
                ]
            for task, result in zip(runnable, runnable_results):
                self._mirror_legacy_thread_output(task, result)
            for task in pending:
                manual_tasks.append(create_manual_task(task.task_prompt_path, task.output_dir))

        collection = collect_run_outputs(package.run_root)
        collection_path = Path(package.run_root) / "fanin" / "collection_report.json"
        _write_json(collection_path, collection.to_dict())
        fanin_report = build_fanin_report_from_collection(collection, tasks)
        self._write_fanin_prompt(Path(package.run_root), contract, collection.to_dict(), state.to_dict())
        self._write_fanin_outputs(Path(package.run_root), fanin_report)

        completed_states: list[dict[str, object]] = []
        failed_states: list[dict[str, object]] = []
        for item in runnable_results:
            status = str(item.get("status", ""))
            if status == "completed":
                completed_states.append(
                    {
                        "thread_id": item["thread_id"],
                        "assigned_agent": item.get("agent_name") or item.get("assigned_agent", ""),
                        "status": status,
                    }
                )
            elif status and status not in {"manual_pending", "manual_fallback"}:
                failed_states.append(
                    {
                        "thread_id": item["thread_id"],
                        "assigned_agent": item.get("agent_name") or item.get("assigned_agent", ""),
                        "status": status,
                    }
                )
        updated = self._save_runtime_state(
            contract,
            state,
            mode=normalized_mode,
            package=package,
            tasks=tasks,
            pending=pending,
            planning_artifact=planning_artifact.to_dict(),
            fanin_report=fanin_report,
            collection_report=collection.to_dict(),
            manual_execution_required=normalized_mode == CODEX_CLI and not package.codex_cli_available,
            approval_required=bool(pending),
            collection_status=collection.collection_status,
            fanout_status="completed" if runnable_results else "no-runnable-workers",
            fanin_status=fanin_report.final_handoff_readiness,
            next_step=fanin_report.next_step_decision,
        )
        updated.completed_workers = completed_states
        updated.failed_workers = failed_states
        self.store.save(updated)
        append_log_line(
            self.project_root / "logs" / "app.log",
            "fanin",
            self.project_root.name,
            contract.current_phase,
            "ready" if fanin_report.final_handoff_readiness == "ready" else "blocked",
            f"completed={len(fanin_report.completed_outputs)} missing={len(fanin_report.missing_outputs)}",
            fanin_report.next_step_decision,
        )
        return {
            "contract": contract.summary(),
            "run_id": package.run_id,
            "run_root": package.run_root,
            "mode": normalized_mode,
            "plan": plan,
            "package": package.to_dict(),
            "resumed_threads": resumed_threads,
            "completed_workers": runnable_results,
            "manual_tasks": manual_tasks,
            "pending_workers": [task.as_request_payload() for task in pending],
            "collection_report": collection.to_dict(),
            "fanin_report": fanin_report.to_dict(),
        }

    def collect(self, run_id: str | None = None) -> dict[str, object]:
        contract = self._load_contract()
        state = self.store.state
        resolved_run_id = self._resolve_run_id(run_id)
        run_root = self._run_root(resolved_run_id)
        collection = collect_run_outputs(run_root)
        self._write_fanin_prompt(run_root, contract, collection.to_dict(), state.to_dict())
        self._save_runtime_state(
            contract,
            state,
            mode=state.execution_mode,
            package=create_run_package(
                contract,
                state,
                PlanningArtifact.from_dict(state.planning_artifact) if state.planning_artifact else ProjectOrchestratorAgent().build_plan(contract, state),
                [TaskSlice(**task) for task in state.active_threads] if state.active_threads else [],
                state.execution_mode,
                run_id=resolved_run_id,
                codex_cli_available=state.codex_cli_available,
            ),
            tasks=[TaskSlice(**task) for task in state.active_threads] if state.active_threads else [],
            pending=[TaskSlice(**task) for task in state.pending_workers] if state.pending_workers else [],
            planning_artifact=state.planning_artifact,
            collection_report=collection.to_dict(),
            collection_status=collection.collection_status,
            next_step=collection.next_step_decision,
        )
        append_log_line(
            self.project_root / "logs" / "app.log",
            "collect",
            self.project_root.name,
            contract.current_phase,
            collection.collection_status,
            f"received={len(collection.received_threads)} missing={len(collection.missing_outputs)}",
            collection.next_step_decision,
        )
        return collection.to_dict()

    def fanin(self, run_id: str | None = None) -> dict[str, object]:
        contract = self._load_contract()
        state = self.store.state
        resolved_run_id = self._resolve_run_id(run_id)
        run_root = self._run_root(resolved_run_id)
        collection = collect_run_outputs(run_root)
        planned = [TaskSlice(**task) for task in (json.loads((run_root / "fanout_plan.json").read_text(encoding="utf-8")) if (run_root / "fanout_plan.json").exists() else [])]
        fanin_report = build_fanin_report_from_collection(collection, planned)
        self._write_fanin_prompt(run_root, contract, collection.to_dict(), state.to_dict())
        self._write_fanin_outputs(run_root, fanin_report)
        self._save_runtime_state(
            contract,
            state,
            mode=state.execution_mode,
            package=create_run_package(
                contract,
                state,
                PlanningArtifact.from_dict(state.planning_artifact) if state.planning_artifact else ProjectOrchestratorAgent().build_plan(contract, state),
                planned or [TaskSlice(**task) for task in state.active_threads],
                state.execution_mode,
                run_id=resolved_run_id,
                codex_cli_available=state.codex_cli_available,
            ),
            tasks=planned or [TaskSlice(**task) for task in state.active_threads],
            pending=[TaskSlice(**task) for task in state.pending_workers] if state.pending_workers else [],
            planning_artifact=state.planning_artifact,
            fanin_report=fanin_report,
            collection_report=collection.to_dict(),
            collection_status=collection.collection_status,
            fanout_status=state.fanout_status,
            fanin_status=fanin_report.final_handoff_readiness,
            next_step=fanin_report.next_step_decision,
        )
        append_log_line(
            self.project_root / "logs" / "app.log",
            "fanin",
            self.project_root.name,
            contract.current_phase,
            "ready" if fanin_report.final_handoff_readiness == "ready" else "blocked",
            f"completed={len(fanin_report.completed_outputs)} missing={len(fanin_report.missing_outputs)}",
            fanin_report.next_step_decision,
        )
        return fanin_report.to_dict()

    def approve(self, approval: str) -> dict[str, object]:
        contract = self._load_contract()
        state = self.store.state
        if not state.pending_workers:
            return {"status": "no-pending-workers"}

        highest = DANGEROUS if any(worker.get("risk_class") == DANGEROUS for worker in state.pending_workers) else CAUTION
        expected = approval_prompt_for(highest)
        if approval.strip() != expected:
            raise PermissionError(f"Approval mismatch. Expected '{expected}' for pending work.")

        pending_tasks = [TaskSlice(**worker) for worker in state.pending_workers]
        state_snapshot = state.to_dict()
        results = []
        with ThreadPoolExecutor(max_workers=max(1, len(pending_tasks))) as pool:
            futures = [pool.submit(self._execute_local_worker, task, contract.summary(), state_snapshot) for task in pending_tasks]
            results = [future.result() for future in futures]

        run_root = self._run_root(state.active_run_id) if state.active_run_id else Path(self.project_root / "runtime")
        collection = collect_run_outputs(run_root)
        fanin_report = build_fanin_report_from_collection(collection, pending_tasks)
        self._write_fanin_prompt(run_root, contract, collection.to_dict(), state.to_dict())
        self._write_fanin_outputs(run_root, fanin_report)
        updated = self._save_runtime_state(
            contract,
            state,
            mode=state.execution_mode,
            package=create_run_package(
                contract,
                state,
                PlanningArtifact.from_dict(state.planning_artifact) if state.planning_artifact else ProjectOrchestratorAgent().build_plan(contract, state),
                pending_tasks,
                state.execution_mode,
                run_id=state.active_run_id or None,
                codex_cli_available=state.codex_cli_available,
            ),
            tasks=[TaskSlice(**worker) for worker in state.active_threads] if state.active_threads else pending_tasks,
            pending=[],
            planning_artifact=state.planning_artifact,
            fanin_report=fanin_report,
            collection_report=collection.to_dict(),
            approval_required=False,
            fanout_status="completed",
            fanin_status=fanin_report.final_handoff_readiness,
            next_step=fanin_report.next_step_decision,
        )
        updated.completed_workers = state.completed_workers + [
            {
                "thread_id": item["thread_id"],
                "assigned_agent": item["agent_name"],
                "status": item["status"],
            }
            for item in results
        ]
        self.store.save(updated)
        append_log_line(
            self.project_root / "logs" / "app.log",
            "approval",
            self.project_root.name,
            contract.current_phase,
            "approved",
            f"{len(results)} worker(s) released",
            fanin_report.next_step_decision,
        )
        return {"status": "approved", "results": results, "fanin_report": fanin_report.to_dict()}

    def gate(self, mode: str = MOCK, run_id: str | None = None) -> dict[str, object]:
        contract = self._load_contract()
        state = self.store.state
        resolved_run_id = self._resolve_run_id(run_id)
        run_root = self._run_root(resolved_run_id)
        fanin_report = FanInReport(**state.fanin_report) if state.fanin_report else FanInReport(
            threads_received=[],
            completed_outputs=[],
            missing_outputs=[],
            failed_workers=[],
            conflicts=[],
            duplicate_work=[],
            requirement_coverage="missing",
            risk_summary=[],
            qa_required=True,
            next_step_decision="remediate",
            final_handoff_readiness="blocked",
        )
        normalized_mode = normalize_execution_mode(mode)
        if normalized_mode == MANUAL:
            prompt_path = write_stage_gate_prompt(
                run_root,
                contract,
                fanin_report,
                state.to_dict(),
                collection_report=state.collection_report,
            )
            manual = create_manual_task(prompt_path, run_root / "gate")
            payload = {
                "status": "PENDING",
                "mode": MANUAL,
                "prompt_path": str(prompt_path),
                "manual_execution_path": manual["manual_execution_path"],
                "next_step": "manual stage gate review pending",
            }
            _write_json(self.project_root / "runtime" / "stage_gate.json", payload)
            _write_json(run_root / "gate" / "stage_gate_result.json", payload)
            (run_root / "gate" / "stage_gate_result.md").write_text(
                "\n".join(
                    [
                        "# Stage Gate Result",
                        "",
                        "Status: PENDING",
                        f"Prompt: {prompt_path}",
                        f"Manual execution: {manual['manual_execution_path']}",
                    ]
                ).rstrip()
                + "\n",
                encoding="utf-8",
            )
            updated = self._save_runtime_state(
                contract,
                state,
                mode=state.execution_mode,
                package=create_run_package(
                    contract,
                    state,
                    PlanningArtifact.from_dict(state.planning_artifact) if state.planning_artifact else ProjectOrchestratorAgent().build_plan(contract, state),
                    [TaskSlice(**task) for task in state.active_threads] if state.active_threads else [],
                    state.execution_mode,
                    run_id=resolved_run_id,
                    codex_cli_available=state.codex_cli_available,
                ),
                tasks=[TaskSlice(**task) for task in state.active_threads] if state.active_threads else [],
                pending=[TaskSlice(**task) for task in state.pending_workers] if state.pending_workers else [],
                planning_artifact=state.planning_artifact,
                stage_gate_decision=payload,
                stage_gate_prompt_path=str(prompt_path),
                next_step="manual stage gate review pending",
            )
            return payload

        decision = run_stage_gate(
            self.project_root,
            contract,
            fanin_report,
            state.to_dict(),
            mode=normalized_mode,
            run_root=str(run_root),
        )
        if isinstance(decision, dict):
            _write_json(self.project_root / "runtime" / "stage_gate.json", decision)
            updated = self._save_runtime_state(
                contract,
                state,
                mode=state.execution_mode,
                package=create_run_package(
                    contract,
                    state,
                    PlanningArtifact.from_dict(state.planning_artifact) if state.planning_artifact else ProjectOrchestratorAgent().build_plan(contract, state),
                    [TaskSlice(**task) for task in state.active_threads] if state.active_threads else [],
                    state.execution_mode,
                    run_id=resolved_run_id,
                    codex_cli_available=state.codex_cli_available,
                ),
                tasks=[TaskSlice(**task) for task in state.active_threads] if state.active_threads else [],
                pending=[TaskSlice(**task) for task in state.pending_workers] if state.pending_workers else [],
                planning_artifact=state.planning_artifact,
                stage_gate_decision=decision,
                stage_gate_prompt_path=decision.get("prompt_path", state.stage_gate_prompt_path),
                next_step=decision.get("next_step", ""),
            )
            return decision

        _write_json(self.project_root / "runtime" / "stage_gate.json", decision.to_dict())
        updated = self._save_runtime_state(
            contract,
            state,
            mode=state.execution_mode,
            package=create_run_package(
                contract,
                state,
                PlanningArtifact.from_dict(state.planning_artifact) if state.planning_artifact else ProjectOrchestratorAgent().build_plan(contract, state),
                [TaskSlice(**task) for task in state.active_threads] if state.active_threads else [],
                state.execution_mode,
                run_id=resolved_run_id,
                codex_cli_available=state.codex_cli_available,
            ),
            tasks=[TaskSlice(**task) for task in state.active_threads] if state.active_threads else [],
            pending=[TaskSlice(**task) for task in state.pending_workers] if state.pending_workers else [],
            planning_artifact=state.planning_artifact,
            stage_gate_decision=decision.to_dict(),
            next_step=decision.next_step,
        )
        append_log_line(
            self.project_root / "logs" / "app.log",
            "stage_gate",
            self.project_root.name,
            contract.current_phase,
            decision.decision,
            ",".join(decision.evidence_reviewed) or "none",
            decision.next_step,
        )
        return decision.to_dict()

    def status(self, run_id: str | None = None) -> dict[str, object]:
        state = self.store.state
        payload: dict[str, object] = {
            "state": state.to_dict(),
            "contract": self.contract.summary() if self.contract else None,
        }
        resolved_run_id = run_id or state.active_run_id
        if resolved_run_id:
            run_root = self._run_root(resolved_run_id)
            manifest_path = run_root / "run_manifest.json"
            if manifest_path.exists():
                payload["run_manifest"] = json.loads(manifest_path.read_text(encoding="utf-8"))
            collection_path = run_root / "fanin" / "collection_report.json"
            if collection_path.exists():
                payload["collection_report"] = json.loads(collection_path.read_text(encoding="utf-8"))
            fanin_path = run_root / "fanin" / "fanin_report.json"
            if fanin_path.exists():
                payload["fanin_report"] = json.loads(fanin_path.read_text(encoding="utf-8"))
            fanin_result_path = run_root / "fanin" / "fanin_result.json"
            if fanin_result_path.exists():
                payload["fanin_result"] = json.loads(fanin_result_path.read_text(encoding="utf-8"))
            gate_path = run_root / "gate" / "stage_gate_result.json"
            if gate_path.exists():
                payload["stage_gate_result"] = json.loads(gate_path.read_text(encoding="utf-8"))
            payload["run_root"] = str(run_root)
        return payload
