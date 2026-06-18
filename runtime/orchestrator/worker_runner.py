from __future__ import annotations

import argparse
import json
from pathlib import Path

from runtime.agents import get_agent_class
from runtime.orchestrator.schemas import TaskSlice, WorkerRequest
from runtime.orchestrator.result_normalizer import normalize_worker_result, render_worker_handoff_markdown


def _load_request(path: Path) -> WorkerRequest:
    payload = json.loads(path.read_text(encoding="utf-8"))
    task = TaskSlice(**payload["task"])
    return WorkerRequest(
        project_root=payload["project_root"],
        task=task,
        contract_summary=payload["contract_summary"],
        state_snapshot=payload["state_snapshot"],
        extra_context=payload.get("extra_context", {}),
    )


def _write_markdown(result: dict[str, object], output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / "handoff_report.md"
    report_path.write_text(render_worker_handoff_markdown(result), encoding="utf-8")
    legacy_path = output_dir / "worker_handoff.md"
    legacy_path.write_text(report_path.read_text(encoding="utf-8"), encoding="utf-8")
    return report_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run a single orchestration worker.")
    parser.add_argument("--request-file", required=True)
    parser.add_argument("--result-file", required=True)
    args = parser.parse_args(argv)

    request_path = Path(args.request_file)
    result_path = Path(args.result_file)
    request = _load_request(request_path)
    agent_class = get_agent_class(request.task.assigned_agent)
    agent = agent_class()
    result = agent.run(request)
    result_payload = normalize_worker_result(
        result.to_dict(),
        task=request.task,
        source="worker",
        mode=request.extra_context.get("execution_mode", "mock"),
        prompt_path=request.task.task_prompt_path,
        output_dir=request.task.output_dir,
        run_id=request.extra_context.get("run_id", ""),
        run_root=request.extra_context.get("run_root", ""),
    )
    result_path.parent.mkdir(parents=True, exist_ok=True)
    result_path.write_text(json.dumps(result_payload, indent=2, ensure_ascii=False), encoding="utf-8")
    _write_markdown(result_payload, result_path.parent)
    return 0 if not result.errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
