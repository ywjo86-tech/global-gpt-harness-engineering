"""One-command, non-production HOST_GATEWAY UDS contract smoke."""
from __future__ import annotations

import argparse
import subprocess
import tempfile
import threading
import time
from pathlib import Path

from .production_execution_gateway import (
    HOST_GATEWAY, GatewayError, UnixSocketGatewayTransport, UnixSocketHostRunner,
    build_gateway_request, validate_gateway_request, validate_gateway_result,
)

FAIL_STAGES = frozenset({"SETUP", "UDS_BIND", "UDS_SOCKET_CREATE", "UDS_PATH_VALIDATE", "UDS_CHMOD", "UDS_LISTEN",
                         "SOCKET_POLICY", "CONNECT", "PEER_CREDENTIAL",
                         "REQUEST_BINDING", "LEDGER_RECEIVED", "LEDGER_RUNNING", "SYNTHETIC_EXECUTOR",
                         "RESULT_BUILD", "RESULT_BINDING", "LEDGER_COMPLETED", "DUPLICATE_CHECK",
                         "ADOPTION", "CLEANUP", "UNKNOWN"})


class SmokeFailure(Exception):
    def __init__(self, stage: str):
        self.stage = stage if stage in FAIL_STAGES else "UNKNOWN"


def _safe_substage(exc: BaseException) -> str:
    text = str(exc)
    for marker, stage in (("uds_path_too_long", "UDS_PATH_VALIDATE"), ("uds_chmod", "UDS_CHMOD"),
                          ("uds_listen", "UDS_LISTEN"), ("socket unavailable", "SOCKET_POLICY"), ("permission", "SOCKET_POLICY"),
                          ("peer credential", "PEER_CREDENTIAL"), ("request", "REQUEST_BINDING"),
                          ("ledger", "LEDGER_RECEIVED"), ("closed connection", "CONNECT"),
                          ("frame", "RESULT_BINDING"), ("result", "RESULT_BINDING")):
        if marker in text.lower():
            return stage
    return "UDS_BIND"


def _request() -> dict[str, object]:
    return build_gateway_request(
        project_id="synthetic-smoke", run_id="synthetic-run", gate_id="SMOKE", lv_id="SMOKE-LV",
        attempt=1, workspace_identity={"project_id": "synthetic-smoke", "workspace_kind": "temporary"},
        package_manifest_sha256="a" * 64, preflight_evidence_sha256="b" * 64,
        runtime_prompt_artifact={"kind": "synthetic", "name": "prompt"}, runtime_prompt_sha256="c" * 64,
        adapter_contract_version="SEM-025.v2",
        structured_event_contract_version="codex-exec-jsonl.0.150.1.v1",
        execution_backend=HOST_GATEWAY,
    )


def _serve_once(runner: UnixSocketHostRunner, errors: list[BaseException]) -> None:
    try:
        runner.serve_once(timeout=10)
    except BaseException as exc:
        errors.append(exc)


def _round_trip(runner: UnixSocketHostRunner, socket_path: Path, root: Path,
                request: dict[str, object], *, transport: UnixSocketGatewayTransport) -> tuple[dict[str, object], list[BaseException]]:
    errors: list[BaseException] = []
    thread = threading.Thread(target=_serve_once, args=(runner, errors), daemon=True)
    thread.start()
    for _ in range(300):
        if socket_path.exists() or errors:
            break
        time.sleep(0.01)
    if errors:
        raise SmokeFailure(_safe_substage(errors[0]))
    try:
        response = transport(request, prompt=b"synthetic", last_message=root / "last", timeout=10, cancel_path=root / "cancel")
    except Exception as exc:
        thread.join(timeout=10)
        if errors:
            raise SmokeFailure(_safe_substage(errors[0])) from exc
        raise SmokeFailure(_safe_substage(exc)) from exc
    thread.join(timeout=10)
    if thread.is_alive() or errors:
        raise GatewayError("synthetic runner did not terminate cleanly")
    return response, errors


def run_smoke() -> dict[str, str]:
    stage = "SETUP"
    with tempfile.TemporaryDirectory(prefix="harness-host-smoke-") as directory:
        try:
            root = Path(directory); socket_path = root / "runtime" / "host-gateway.sock"; ledger = root / "ledger"
            executions = {"count": 0}
            def executor(argv, **kwargs):
                if argv == ["codex", "--version"]:
                    return subprocess.CompletedProcess(argv, 0, b"codex-cli 0.150.1\n", b"")
                executions["count"] += 1
                target_index = argv.index("--output-last-message") + 1
                Path(argv[target_index]).write_text("synthetic", encoding="utf-8")
                return subprocess.CompletedProcess(argv, 0, b"synthetic", b"")
            runner = UnixSocketHostRunner(socket_path, ledger, executor=executor)
            stage = "REQUEST_BINDING"; request = _request(); validate_gateway_request(request)
            transport = UnixSocketGatewayTransport(socket_path, workspace_root=root)
            stage = "UDS_BIND"; first, _ = _round_trip(runner, socket_path, root, request, transport=transport)
            stage = "DUPLICATE_CHECK"; restarted_runner = UnixSocketHostRunner(socket_path, ledger, executor=executor)
            stage = "ADOPTION"; second, _ = _round_trip(restarted_runner, socket_path, root, request, transport=transport)
            if executions["count"] != 1: raise GatewayError("duplicate synthetic execution occurred")
            if not first.get("process_evidence") or not second.get("adopted"): raise GatewayError("synthetic adoption metadata is invalid")
            stage = "LEDGER_COMPLETED"; records = list(ledger.glob("*.json"))
            if len(records) != 1 or '"state":"COMPLETED"' not in records[0].read_text(encoding="utf-8"): raise GatewayError("synthetic ledger completion is invalid")
            wrong = dict(request); wrong["attempt"] = 2
            try: validate_gateway_request(wrong)
            except GatewayError: pass
            else: raise GatewayError("request mismatch was accepted")
            return {"RESULT": "HOST_SYNTHETIC_PASS", "UDS": "PASS", "PEER": "PASS", "REQUEST_BINDING": "PASS", "RESULT_BINDING": "PASS", "LEDGER": "PASS", "DUPLICATE_RERUN": "NO", "ADOPTION": "PASS"}
        except SmokeFailure: raise
        except PermissionError as exc: raise SmokeFailure("UDS_BIND") from exc
        except Exception as exc: raise SmokeFailure(stage) from exc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run a non-production HOST_GATEWAY UDS synthetic smoke")
    parser.parse_args(argv)
    try:
        result = run_smoke()
    except SmokeFailure as exc:
        uds = "FAIL" if exc.stage in {"UDS_BIND", "SOCKET_POLICY", "CONNECT", "PEER_CREDENTIAL"} else "NOT_REACHED"
        print(f"RESULT=HOST_SYNTHETIC_BLOCKED FAIL_STAGE={exc.stage} UDS={uds} PEER=NOT_REACHED REQUEST_BINDING=NOT_REACHED RESULT_BINDING=NOT_REACHED LEDGER=NOT_REACHED DUPLICATE_RERUN=NOT_REACHED ADOPTION=NOT_REACHED")
        return 10
    except Exception:
        print("RESULT=HOST_SYNTHETIC_BLOCKED FAIL_STAGE=UNKNOWN UDS=NOT_REACHED PEER=NOT_REACHED REQUEST_BINDING=NOT_REACHED RESULT_BINDING=NOT_REACHED LEDGER=NOT_REACHED DUPLICATE_RERUN=NOT_REACHED ADOPTION=NOT_REACHED")
        return 10
    print(" ".join(f"{key}={value}" for key, value in result.items()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
