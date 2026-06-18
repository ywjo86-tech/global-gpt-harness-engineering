from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from .codex_adapter import create_manual_task, detect_codex_cli, run_task_prompt
from .execution_modes import CODEX_CLI, MANUAL, MOCK, normalize_execution_mode
from .prompt_builder import build_stage_gate_prompt
from .summary_rendering import render_stage_gate_markdown
from .schemas import ExecutionContract, FanInReport, StageGateDecision


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def _normalize_gate_status(value: Any) -> str:
    text = str(value or "").strip().replace("_", " ").replace("-", " ")
    normalized = " ".join(text.split()).upper()
    if normalized in {"GO", "CONDITIONAL GO", "NO-GO", "PENDING"}:
        return normalized
    return normalized or "NO-GO"


def _normalize_gate_payload(payload: dict[str, Any], contract: ExecutionContract) -> dict[str, Any]:
    normalized = dict(payload)
    decision = _normalize_gate_status(normalized.get("status", normalized.get("decision", "NO-GO")))
    normalized["status"] = decision
    normalized["decision"] = decision
    normalized.setdefault("phase", contract.current_phase)
    normalized.setdefault("completion_criteria_checked", "yes")
    normalized.setdefault("fan_in_reviewed", "yes")
    return normalized


def write_stage_gate_prompt(
    run_root: str | Path,
    contract: ExecutionContract,
    fanin_report: FanInReport,
    state_snapshot: dict[str, Any],
    collection_report: dict[str, Any] | None = None,
) -> Path:
    root = Path(run_root)
    gate_dir = root / "gate"
    gate_dir.mkdir(parents=True, exist_ok=True)
    prompt_path = gate_dir / "stage_gate_prompt.md"
    prompt_text = build_stage_gate_prompt(
        contract.summary(),
        state_snapshot,
        fanin_report.to_dict(),
        str(root),
        collection_report=collection_report,
    )
    prompt_path.write_text(prompt_text, encoding="utf-8")
    return prompt_path


def _decision_from_payload(payload: dict[str, Any], contract: ExecutionContract) -> StageGateDecision:
    decision = _normalize_gate_status(payload.get("status", payload.get("decision", "NO-GO")))
    if decision not in {"GO", "CONDITIONAL GO", "NO-GO"}:
        decision = "NO-GO"
    if decision == "GO":
        conditions: list[str] = []
        remaining_risks: list[str] = []
        blocker_summary = ""
        authorization = "next phase may start"
        open_questions: list[str] = []
    elif decision == "CONDITIONAL GO":
        conditions = list(payload.get("conditions", [])) or ["complete QA follow-up before next phase"]
        remaining_risks = list(payload.get("remaining_risks", [])) or ["QA follow-up remains advisable."]
        blocker_summary = ""
        authorization = "next phase may start after conditions are satisfied"
        open_questions = list(payload.get("open_questions", [])) or ["review remaining risks"]
    else:
        conditions = []
        remaining_risks = list(payload.get("remaining_risks", [])) or ["stage gate not satisfied"]
        blocker_summary = str(payload.get("blocker_summary", "Stage gate conditions were not met."))
        authorization = ""
        open_questions = list(payload.get("open_questions", [])) or ["review remaining risks"]
    return StageGateDecision(
        decision=decision,
        phase=payload.get("phase", contract.current_phase),
        completion_criteria_checked=payload.get("completion_criteria_checked", "yes"),
        evidence_reviewed=list(payload.get("evidence_reviewed", [])),
        fan_in_reviewed=payload.get("fan_in_reviewed", "yes"),
        open_questions=open_questions,
        remaining_risks=remaining_risks,
        next_step=payload.get("next_step", ""),
        conditions=conditions,
        authorization=authorization,
        blocker_summary=blocker_summary,
    )


def run_stage_gate(
    project_root: str | Path,
    contract: ExecutionContract,
    fanin_report: FanInReport,
    state_snapshot: dict[str, Any],
    *,
    mode: str = MOCK,
    run_root: str | None = None,
) -> StageGateDecision | dict[str, Any]:
    normalized_mode = normalize_execution_mode(mode)
    runtime_dir = Path(project_root) / "runtime"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    result_path = runtime_dir / "stage_gate.json"
    prompt_run_root = run_root or str(
        Path(project_root) / "runtime" / "orchestrator_runs" / state_snapshot.get("active_run_id", "stage-gate")
    )
    prompt_path = write_stage_gate_prompt(
        prompt_run_root,
        contract,
        fanin_report,
        state_snapshot,
        collection_report=state_snapshot.get("collection_report", {}),
    )
    gate_dir = Path(prompt_run_root) / "gate"
    gate_dir.mkdir(parents=True, exist_ok=True)
    gate_result_json = gate_dir / "stage_gate_result.json"
    gate_result_md = gate_dir / "stage_gate_result.md"

    if normalized_mode == MANUAL:
        manual = create_manual_task(prompt_path, Path(prompt_run_root) / "gate")
        payload = {
            "status": "PENDING",
            "mode": MANUAL,
            "prompt_path": str(prompt_path),
            "manual_execution_path": manual["manual_execution_path"],
            "next_step": "manual stage gate review pending",
        }
        _write_json(result_path, payload)
        _write_json(gate_result_json, payload)
        gate_result_md.write_text(
            render_stage_gate_markdown(
                {
                    "decision": "PENDING",
                    "phase": contract.current_phase,
                    "completion_criteria_checked": "no",
                    "fan_in_reviewed": "no",
                    "evidence_reviewed": [],
                    "conditions": [],
                    "open_questions": ["manual stage gate review pending"],
                    "remaining_risks": ["manual stage gate review pending"],
                    "next_step": "manual stage gate review pending",
                    "authorization": "",
                    "blocker_summary": f"Prompt: {prompt_path}\nManual execution: {manual['manual_execution_path']}",
                }
            ),
            encoding="utf-8",
        )
        return payload

    if normalized_mode == CODEX_CLI:
        result = run_task_prompt(prompt_path, Path(prompt_run_root) / "gate", normalized_mode)
        payload_path = Path(result["output_dir"]) / "result.json"
        if payload_path.exists():
            payload = json.loads(payload_path.read_text(encoding="utf-8"))
        else:
            payload = {
                "status": "NO-GO",
                "phase": contract.current_phase,
                "completion_criteria_checked": "no",
                "evidence_reviewed": [],
                "fan_in_reviewed": "no",
                "open_questions": ["codex CLI fallback to manual execution"],
                "remaining_risks": ["codex cli unavailable"],
                "next_step": "manual stage gate review pending",
                "conditions": [],
                "authorization": "",
                "blocker_summary": "Codex CLI execution did not produce a result file.",
            }
        payload = _normalize_gate_payload(payload, contract)
        _write_json(result_path, payload)
        _write_json(gate_result_json, payload)
        gate_result_md.write_text(render_stage_gate_markdown(payload), encoding="utf-8")
        if payload.get("status") in {"GO", "CONDITIONAL GO", "NO-GO"}:
            return _decision_from_payload(payload, contract)
        return payload

    request_path = runtime_dir / "stage_gate_request.json"
    result_path = runtime_dir / "stage_gate.json"
    request_payload = {
        "project_root": str(Path(project_root).resolve()),
        "task": {
            "thread_id": "stage-gate",
            "assigned_agent": "stage_gate_reviewer_agent",
            "input": f"Stage gate review for {contract.current_phase}",
            "expected_output": "GO / CONDITIONAL GO / NO-GO",
            "validation_criteria": [
                "Independent phase-transition decision",
                "Evidence reviewed",
                "Fan-in reviewed",
            ],
            "editable_scope": [],
            "forbidden_scope": ["runtime code", ".claude/"],
            "merge_point": "next phase boundary",
            "status": "pending",
        },
        "contract_summary": contract.summary(),
        "fanin_report": fanin_report.to_dict(),
        "state_snapshot": state_snapshot,
        "extra_context": {
            "fanin_report": fanin_report.to_dict(),
            "next_step": "advance if gate allows",
        },
    }
    request_path.write_text(json.dumps(request_payload, indent=2, ensure_ascii=False), encoding="utf-8")
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
        cwd=str(Path(__file__).resolve().parents[2]),
        check=True,
    )
    payload = _normalize_gate_payload(json.loads(result_path.read_text(encoding="utf-8")), contract)
    _write_json(gate_result_json, payload)
    gate_result_md.write_text(render_stage_gate_markdown(payload), encoding="utf-8")
    if payload.get("status") in {"GO", "CONDITIONAL GO", "NO-GO"}:
        return _decision_from_payload(payload, contract)
    return payload
