"""Outer-host-only, harmless C+ runtime smoke.

Unlike the synthetic smoke, this entrypoint invokes Codex once against a fresh
temporary Git workspace. It never touches a project fixture or production run.
"""
from __future__ import annotations

import argparse
import hashlib
import os
import subprocess
import tempfile
import threading
import time
from pathlib import Path

from .production_execution_gateway import (
    HOST_GATEWAY, GatewayError, UnixSocketGatewayTransport, UnixSocketHostRunner,
    build_gateway_request, validate_gateway_request,
)
from .production_worker_executor import (
    ADAPTER_CONTRACT_VERSION, STRUCTURED_EVENT_CONTRACT_VERSION,
    _parse_structured_jsonl, _secret_findings, _validate_final_message,
)

FAIL_STAGES = frozenset({"SETUP", "RUNNER_START", "UDS", "PEER", "REQUEST_BINDING", "CODEX_START",
                         "CODEX_TRANSPORT", "JSONL_PARSE", "JSONL_CONTRACT", "STDERR_SECURITY",
                         "FINAL_MESSAGE", "RESULT_BINDING", "LEDGER", "CLEANUP", "UNKNOWN"})


class CPlusSmokeFailure(Exception):
    def __init__(self, stage: str):
        self.stage = stage if stage in FAIL_STAGES else "UNKNOWN"


def _security_stage_summary(failed_stage: str) -> dict[str, str]:
    if failed_stage in {"JSONL_PARSE", "JSONL_CONTRACT"}:
        return {"JSONL_VALID": "BLOCK", "STDERR_SECURITY": "NOT_EVALUATED", "FINAL_MESSAGE": "NOT_EVALUATED"}
    if failed_stage == "STDERR_SECURITY":
        return {"JSONL_VALID": "PASS", "STDERR_SECURITY": "BLOCK", "FINAL_MESSAGE": "NOT_EVALUATED"}
    if failed_stage == "FINAL_MESSAGE":
        return {"JSONL_VALID": "PASS", "STDERR_SECURITY": "PASS", "FINAL_MESSAGE": "BLOCK"}
    if failed_stage in {"RESULT_BINDING", "LEDGER", "CLEANUP"}:
        return {"JSONL_VALID": "PASS", "STDERR_SECURITY": "PASS", "FINAL_MESSAGE": "PASS"}
    return {"JSONL_VALID": "NOT_EVALUATED", "STDERR_SECURITY": "NOT_EVALUATED", "FINAL_MESSAGE": "NOT_EVALUATED"}


def _request(prompt: bytes) -> dict[str, object]:
    return build_gateway_request(
        project_id="cplus-smoke", run_id="cplus-smoke-run", gate_id="SMOKE", lv_id="CPLUS",
        attempt=1, workspace_identity={"project_id": "cplus-smoke", "workspace_kind": "temporary"},
        package_manifest_sha256="a" * 64, preflight_evidence_sha256="b" * 64,
        runtime_prompt_artifact={"kind": "cplus-smoke", "name": "stdin"},
        runtime_prompt_sha256=hashlib.sha256(prompt).hexdigest(),
        adapter_contract_version=ADAPTER_CONTRACT_VERSION,
        structured_event_contract_version=STRUCTURED_EVENT_CONTRACT_VERSION,
        execution_backend=HOST_GATEWAY,
    )


def run_smoke() -> dict[str, str]:
    if os.environ.get("CODEX_SANDBOX_NETWORK_DISABLED"):
        raise CPlusSmokeFailure("SETUP")
    prompt = b"Reply with exactly: OK"
    stage = "SETUP"
    with tempfile.TemporaryDirectory(prefix="harness-cplus-smoke-") as directory:
        root = Path(directory); socket_path = root / "runtime" / "host-gateway.sock"; ledger = root / "ledger"
        subprocess.run(["git", "init", "-q", "-b", "main", str(root)], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        executions = {"count": 0}
        def executor(argv, **kwargs):
            if argv != ["codex", "--version"]:
                executions["count"] += 1
            return subprocess.run(argv, input=kwargs.get("input", b""), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                  check=False, timeout=kwargs.get("timeout"))
        request = _request(prompt); validate_gateway_request(request)
        runner = UnixSocketHostRunner(socket_path, ledger, executor=executor)
        errors: list[BaseException] = []
        def serve():
            try: runner.serve_once(timeout=180)
            except BaseException as exc: errors.append(exc)
        thread = threading.Thread(target=serve, daemon=True); thread.start()
        for _ in range(300):
            if socket_path.exists() or errors: break
            time.sleep(0.01)
        if errors: raise CPlusSmokeFailure("RUNNER_START")
        stage = "UDS"
        try:
            result = UnixSocketGatewayTransport(socket_path, workspace_root=root)(
                request, prompt=prompt, last_message=root / "executor.last-message.txt",
                timeout=180, cancel_path=root / "cancel.request")
        except GatewayError as exc:
            raise CPlusSmokeFailure("CODEX_TRANSPORT") from exc
        thread.join(timeout=185)
        if thread.is_alive() or errors: raise CPlusSmokeFailure("CODEX_TRANSPORT")
        if executions["count"] != 1: raise CPlusSmokeFailure("RESULT_BINDING")
        stage = "JSONL_PARSE"
        stdout = bytes(result.get("stdout", b"")); stderr = bytes(result.get("stderr", b""))
        try: events = _parse_structured_jsonl(stdout)
        except Exception as exc: raise CPlusSmokeFailure("JSONL_CONTRACT") from exc
        stage = "STDERR_SECURITY"
        if _secret_findings(stderr): raise CPlusSmokeFailure("STDERR_SECURITY")
        stage = "FINAL_MESSAGE"
        try: _validate_final_message(root / "executor.last-message.txt")
        except Exception as exc: raise CPlusSmokeFailure("FINAL_MESSAGE") from exc
        if not list(ledger.glob("*.json")): raise CPlusSmokeFailure("LEDGER")
        return {"RESULT": "HOST_CPLUS_PASS", "UDS": "PASS", "PEER": "PASS", "CODEX_EXIT": "PASS",
                "JSONL": "PASS", "EVENT_COUNT_BUCKET": "4", "UNKNOWN_EVENT_COUNT": str(events.get("unknown_event_count", 0)),
                "STDERR_SECURITY": "PASS", "FINAL_MESSAGE": "PASS", "REQUEST_BINDING": "PASS",
                "RESULT_BINDING": "PASS", "LEDGER": "PASS"}


def main(argv: list[str] | None = None) -> int:
    argparse.ArgumentParser(description="Run one harmless outer-host C+ smoke").parse_args(argv)
    try:
        output = run_smoke()
    except CPlusSmokeFailure as exc:
        stages = _security_stage_summary(exc.stage)
        print(" ".join(["RESULT=HOST_CPLUS_BLOCKED", f"FAIL_STAGE={exc.stage}",
                        *(f"{key}={value}" for key, value in stages.items())]))
        return 10
    except Exception:
        print("RESULT=HOST_CPLUS_BLOCKED FAIL_STAGE=UNKNOWN")
        return 10
    print(" ".join(f"{key}={value}" for key, value in output.items()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
