import unittest
import tempfile
import threading
import subprocess
import time
import sys
from pathlib import Path

from runtime.orchestrator.production_execution_gateway import (
    GATEWAY_CONTRACT_VERSION, HOST_GATEWAY, GatewayError, HostExecutionGateway,
    ManagedHostRunner, UnixSocketGatewayTransport, UnixSocketHostRunner,
    build_gateway_request, build_gateway_result, validate_gateway_request,
    validate_gateway_result, build_effect_reconciliation_request,
    build_effect_reconciliation_result, validate_effect_reconciliation_result,
    resolve_gateway_socket_path, _workspace_artifact_binding,
    _digest, _safe_broker_block,
)
from runtime.orchestrator.tool_authorization import (
    DEC007_DECISION_REF,
    activate_contract, build_dec007_approved_contracts, owned_scope_digest,
)


def request(*, codex_cli_version="0.150.1"):
    owned = ("owned.txt",)
    approved = build_dec007_approved_contracts(
        project_id="p", gate_id="g", lv_id="L", run_id="r",
        canonical_plan_sha256="d" * 64, owned_files=owned,
    )
    contracts = [
        activate_contract(
            item,
            package_binding_sha256="7" * 64,
            authorized_decisions={DEC007_DECISION_REF: "USER_DECISION"},
        ).to_dict()
        for item in approved
    ]
    projection = {
        "decision_ref": DEC007_DECISION_REF,
        "worker_task_id": "TASK-4A-08",
        "active_contract_count": len(contracts),
        "contract_ids": sorted(item["contract_id"] for item in contracts),
        "operation_class_ids": sorted(item["operation_class_id"] for item in contracts),
        "owned_scope_sha256": owned_scope_digest(owned),
        "package_binding_sha256": "7" * 64,
        "requirement_digests": {
            item["operation_class_id"]: item["requirement_digest"]
            for item in contracts
        },
    }
    binding = {
        "schema_version": "orchestration.canonical-launch-authority.v2",
        "package_ref": "package://PKG-1@1#" + "1" * 64,
        "package_digest": "1" * 64,
        "contract_ref": "contract://CEC-1@1#" + "2" * 64,
        "contract_digest": "2" * 64,
        "contract_activation_digest": "3" * 64,
        "worker_task_id": "TASK-4A-08",
        "criterion_set_digest": "4" * 64,
        "execution_obligation": "MUTATION_REQUIRED",
        "preflight_evidence_digest": "5" * 64,
        "codex_auth_readiness_ref": "CAE-initial",
        "codex_auth_recheck_evidence_ref": "CAE-recheck",
        "codex_cli_version": codex_cli_version,
        "launch_authorization_digest": "6" * 64,
        "migration_authority_ref": "migration-authority://test",
    }
    return build_gateway_request(
        project_id="p", run_id="r", gate_id="g", lv_id="L", attempt=1,
        workspace_identity={"project_id": "p", "workspace_kind": "project_root"},
        package_manifest_sha256="a" * 64, preflight_evidence_sha256="b" * 64,
        runtime_prompt_artifact={"kind": "worker_runtime_prompt", "name": "executor.prompt.txt"},
        runtime_prompt_sha256="c" * 64, adapter_contract_version="SEM-025.v2",
        structured_event_contract_version="codex-exec-jsonl.0.150.1.v1",
        canonical_plan_sha256="d" * 64, requirement_digest="e" * 64,
        active_tool_authorization_contracts=contracts,
        owned_files=list(owned),
        tool_authorization_projection=projection,
        tool_authorization_projection_sha256=_digest(projection),
        canonical_authority_binding=binding,
        canonical_authority_binding_digest=_digest(binding),
    )


class GatewayContractTests(unittest.TestCase):
    def test_effect_reconciliation_result_requires_full_mcp_owner_and_exact_binding(self):
        request = build_effect_reconciliation_request(
            project_id="p", run_id="r", task_id="TASK-1", cycle_id="C1",
            effect_intent_id="e"*64, authority_binding_digest="a"*64,
            continuation_contract_digest="b"*64, source_digest="c"*40,
            environment_digest="d"*64,
        )
        result = build_effect_reconciliation_result(
            request, status="APPLIED", canonical_effect_id="TE-123",
            canonical_receipt_ref="full-mcp://receipt/TE-123",
            receipt_digest="f"*64, evidence_ref="full-mcp://evidence/TE-123",
            observed_at="2026-10-01T10:00:00+00:00",
        )
        validated = validate_effect_reconciliation_result(result, expected_request=request)
        self.assertEqual(validated["status"], "APPLIED")
        self.assertEqual(validated["owning_domain"], "FULL_MCP")
        self.assertEqual(validated["receipt_digest"], "f"*64)
        for field, value in (
            ("owning_domain", "LOCAL"),
            ("effect_intent_id", "0"*64),
            ("source_digest", "1"*40),
            ("environment_digest", "2"*64),
        ):
            tampered = dict(result); tampered[field] = value
            unsigned = dict(tampered); unsigned.pop("result_digest")
            tampered["result_digest"] = _digest(unsigned)
            with self.subTest(field=field), self.assertRaises(GatewayError):
                validate_effect_reconciliation_result(tampered, expected_request=request)

    def test_effect_reconciliation_applied_requires_canonical_receipt(self):
        request = build_effect_reconciliation_request(
            project_id="p", run_id="r", task_id="TASK-1", cycle_id="C1",
            effect_intent_id="e"*64, authority_binding_digest="a"*64,
            continuation_contract_digest="b"*64, source_digest="c"*40,
            environment_digest="d"*64,
        )
        with self.assertRaises(GatewayError):
            build_effect_reconciliation_result(
                request, status="APPLIED", canonical_effect_id="TE-123",
                canonical_receipt_ref="", receipt_digest="", evidence_ref="full-mcp://evidence/TE-123",
                observed_at="2026-10-01T10:00:00+00:00",
            )

    def test_broker_block_projection_is_content_free_and_fail_closed(self):
        self.assertEqual(_safe_broker_block({
            "stage": "HANDLE", "error_class": "ToolAuthorizationError",
            "operation_class_id": "PROJECT_OWNED_FILE_WRITE", "raw": "secret"
        }), {"stage": "HANDLE", "error_class": "ToolAuthorizationError",
             "operation_class_id": "PROJECT_OWNED_FILE_WRITE"})
        self.assertIsNone(_safe_broker_block({"stage": "OTHER", "error_class": "RuntimeError"}))

    def dec007_request(self):
        package_binding = "f" * 64
        approved = build_dec007_approved_contracts(
            project_id="p", gate_id="g", lv_id="L", run_id="r",
            canonical_plan_sha256="d" * 64, owned_files=("owned.txt",))
        contracts = [activate_contract(item, package_binding_sha256=package_binding,
            authorized_decisions={"DEC-007": "USER_DECISION"}).to_dict() for item in approved]
        projection = {"decision_ref": "DEC-007", "worker_task_id": "TASK-4A-08",
            "active_contract_count": 3,
            "contract_ids": sorted(item["contract_id"] for item in contracts),
            "operation_class_ids": sorted(item["operation_class_id"] for item in contracts),
            "owned_scope_sha256": owned_scope_digest(("owned.txt",)),
            "package_binding_sha256": package_binding,
            "requirement_digests": {item["operation_class_id"]: item["requirement_digest"]
                                    for item in contracts}}
        return build_gateway_request(
            project_id="p", run_id="r", gate_id="g", lv_id="L", attempt=1,
            workspace_identity={"project_id": "p"}, package_manifest_sha256="a" * 64,
            preflight_evidence_sha256="b" * 64,
            runtime_prompt_artifact={"kind": "worker_runtime_prompt"}, runtime_prompt_sha256="c" * 64,
            adapter_contract_version="SEM-025.v2",
            structured_event_contract_version="codex-exec-jsonl.0.150.1.v1",
            active_tool_authorization_contracts=contracts, owned_files=["owned.txt"],
            canonical_plan_sha256="d" * 64, tool_authorization_projection=projection,
            tool_authorization_projection_sha256=_digest(projection))

    def test_dec007_exact_projection_validates_and_all_binding_drift_blocks(self):
        req = self.dec007_request()
        self.assertEqual(len(validate_gateway_request(req)["active_tool_authorization_contracts"]), 3)
        for field, value in (("project_id", "other"), ("gate_id", "other"), ("lv_id", "other"),
                             ("run_id", "other"), ("canonical_plan_sha256", "0" * 64)):
            tampered = dict(req); tampered[field] = value
            unsigned = dict(tampered); unsigned.pop("request_digest"); tampered["request_digest"] = _digest(unsigned)
            with self.subTest(field=field), self.assertRaises(GatewayError): validate_gateway_request(tampered)
        tampered = dict(req); projection = dict(req["tool_authorization_projection"])
        projection["package_binding_sha256"] = "1" * 64
        tampered["tool_authorization_projection"] = projection
        tampered["tool_authorization_projection_sha256"] = _digest(projection)
        unsigned = dict(tampered); unsigned.pop("request_digest"); tampered["request_digest"] = _digest(unsigned)
        with self.assertRaises(GatewayError): validate_gateway_request(tampered)
    def test_production_and_cplus_final_message_bindings_preserve_exact_scope(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); nested = root / "run" / "attempt"; nested.mkdir(parents=True)
            production_target = nested / "last"
            rebound, relative = _workspace_artifact_binding(root, production_target)
            self.assertEqual(rebound, production_target)
            self.assertEqual(root / relative, production_target)
            smoke_target = root / "smoke-last"
            rebound, relative = _workspace_artifact_binding(root, smoke_target)
            self.assertEqual(rebound, smoke_target)
            self.assertEqual(root / relative, smoke_target)

    def test_final_message_workspace_binding_blocks_outside_missing_and_unsafe(self):
        with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as outside:
            root = Path(d)
            with self.assertRaisesRegex(GatewayError, "outside write scope"):
                _workspace_artifact_binding(root, Path(outside) / "last")
            with self.assertRaisesRegex(GatewayError, "parent is missing"):
                _workspace_artifact_binding(root, root / "missing" / "last")
            unsafe = root / "unsafe"; unsafe.mkdir()
            with self.assertRaisesRegex(GatewayError, "target is unsafe"):
                _workspace_artifact_binding(root, unsafe)

    def test_socket_resolver_shortens_only_overlong_workspace_paths(self):
        short = resolve_gateway_socket_path(Path('/tmp/work'), 'runtime/host-gateway.sock')
        self.assertEqual(short, Path('/tmp/work/runtime/host-gateway.sock'))
        long_root = Path('/tmp') / ('w' * 100)
        shortened = resolve_gateway_socket_path(long_root, 'runtime/host-gateway.sock')
        self.assertLess(len(str(shortened).encode()), 108)
        self.assertTrue(str(shortened).startswith(tempfile.gettempdir()))

    def test_socket_resolver_rejects_unsafe_endpoint(self):
        with self.assertRaises(GatewayError):
            resolve_gateway_socket_path('/tmp/work', '../socket')

    def test_request_and_result_round_trip_without_raw_content(self):
        req = request(); self.assertEqual(validate_gateway_request(req)["gateway_contract_version"], GATEWAY_CONTRACT_VERSION)
        result = build_gateway_result(req, backend_identity=HOST_GATEWAY,
            process_termination_category="EXITED", exit_status_category="EXIT_0",
            structured_event_metadata={"terminal_event_present": True},
            stderr_security_metadata={"status": "CLEAR"},
            final_message_metadata={"exists": True, "nonempty": True},
            worker_result_identity={"artifact": "worker.result.json"}, execution_status="COMPLETED")
        self.assertEqual(validate_gateway_result(result, expected_request=req)["execution_request_id"], req["execution_request_id"])
        self.assertNotIn("secret", repr(result).lower())

    def test_request_digest_and_binding_fail_closed(self):
        req = request(); tampered = dict(req); tampered["attempt"] = 2
        with self.assertRaises(GatewayError): validate_gateway_request(tampered)
        with self.assertRaises(GatewayError): validate_gateway_request(req, expected={"run_id": "other"})

    def test_transport_compatibility_and_native_registry_seal_fail_closed(self):
        req = request()
        self.assertEqual(req["transport_compatibility"]["codex_version_policy"], "STABLE_SEMVER_SCHEMA_VERIFIED")
        self.assertNotIn("codex_version", req["transport_compatibility"])
        for field, value in (("codex_version_policy", "EXACT_0.150.1"), ("native_command_runtime_count", 1),
                             ("native_file_runtime_count", 1), ("direct_mcp_effect_source_count", 1)):
            tampered = dict(req); compatibility = dict(req["transport_compatibility"])
            compatibility[field] = value; tampered["transport_compatibility"] = compatibility
            unsigned = dict(tampered); unsigned.pop("request_digest")
            from runtime.orchestrator.production_execution_gateway import _digest
            tampered["request_digest"] = _digest(unsigned)
            with self.subTest(field=field), self.assertRaisesRegex(GatewayError, "COMPATIBILITY_BLOCK"):
                validate_gateway_request(tampered)

    def test_result_digest_and_stale_binding_fail_closed(self):
        req = request()
        result = build_gateway_result(req, backend_identity=HOST_GATEWAY,
            process_termination_category="EXITED", exit_status_category="EXIT_0",
            structured_event_metadata={}, stderr_security_metadata={}, final_message_metadata={},
            worker_result_identity={}, execution_status="COMPLETED")
        tampered = dict(result); tampered["run_id"] = "other"
        with self.assertRaises(GatewayError): validate_gateway_result(tampered, expected_request=req)
        tampered = dict(result); tampered["result_digest"] = "0" * 64
        with self.assertRaises(GatewayError): validate_gateway_result(tampered, expected_request=req)

    def test_host_gateway_has_no_local_fallback_and_rejects_duplicate(self):
        gateway = HostExecutionGateway()
        with self.assertRaisesRegex(GatewayError, "UNAVAILABLE"):
            gateway.execute(request(), prompt=b"", last_message=__import__("pathlib").Path("/tmp/last"), timeout=1,
                            cancel_path=__import__("pathlib").Path("/tmp/cancel"))
        # A second request is independently rejected as stale/duplicate even
        # when a transport is later unavailable; no child backend is selected.
        with self.assertRaises(GatewayError):
            gateway.execute(request(), prompt=b"", last_message=__import__("pathlib").Path("/tmp/last"), timeout=1,
                            cancel_path=__import__("pathlib").Path("/tmp/cancel"))

    def test_transport_capture_is_in_memory_only(self):
        def transport(req, **kwargs):
            return {"stdout": b"safe", "stderr": b"", "process_evidence": {"exit_code": 0}, "adapter_evidence": {"strict": True}}
        execution = HostExecutionGateway(transport).execute(request(), prompt=b"safe", last_message=__import__("pathlib").Path("/tmp/last"), timeout=1,
                                                            cancel_path=__import__("pathlib").Path("/tmp/cancel"))
        self.assertEqual(execution.stdout, b"safe")
        self.assertEqual(execution.gateway_request["execution_backend"], HOST_GATEWAY)

    def test_managed_host_runner_exposes_one_shot_socket_without_background_daemon(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); sock = root / "runtime" / "managed.sock"; ledger = root / "ledger"
            probe = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    (
                        "import socket, sys; "
                        "s=socket.socket(socket.AF_UNIX); "
                        "s.bind(sys.argv[1]); "
                        "s.close()"
                    ),
                    str(sock),
                ],
                capture_output=True,
                text=True,
            )
            if probe.returncode != 0:
                self.skipTest("subprocess UDS bind is unavailable in this environment")
            sock.unlink(missing_ok=True)
            manager = ManagedHostRunner(sock, ledger, workspace_root=root, timeout=2)
            with manager as transport:
                self.assertIsInstance(transport, UnixSocketGatewayTransport)
                self.assertTrue(sock.is_socket())
                self.assertIsNotNone(manager.process)
                self.assertIsNone(manager.process.poll())
            self.assertFalse(sock.exists())
            self.assertIsNotNone(manager.process.poll())

    def test_authenticated_uds_runner_round_trip_and_durable_ledger(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); sock = root / "runtime" / "gateway.sock"; ledger = root / "ledger"
            events = b'\n'.join((b'{"type":"thread.started","thread_id":"t"}', b'{"type":"turn.started"}',
                                 b'{"type":"item.completed","item":{"id":"item-1","type":"agent_message"}}',
                                 b'{"type":"turn.completed","usage":{}}'))
            def executor(argv, **kwargs):
                if argv == ["codex", "--version"]:
                    return subprocess.CompletedProcess(argv, 0, b"codex-cli 0.150.1\n", b"")
                target = Path(argv[argv.index("--output-last-message") + 1])
                target.write_text("completed", encoding="utf-8")
                return subprocess.CompletedProcess(argv, 0, events, b"")
            runner = UnixSocketHostRunner(sock, ledger, executor=executor)
            errors = []
            def serve():
                try: runner.serve_once()
                except BaseException as exc: errors.append(exc)
            thread = threading.Thread(target=serve, daemon=True); thread.start()
            for _ in range(100):
                if sock.exists() or errors: break
                time.sleep(0.01)
            time.sleep(0.02)
            if errors or not sock.exists():
                self.skipTest("local sandbox does not permit AF_UNIX bind")
            try:
                result = UnixSocketGatewayTransport(sock, workspace_root=root)(request(), prompt=b"safe", last_message=root / "last",
                                                          timeout=2, cancel_path=root / "cancel")
            except GatewayError:
                thread.join(timeout=2)
                if errors:
                    self.skipTest("local sandbox does not permit a complete AF_UNIX round-trip")
                raise
            thread.join(timeout=2)
            self.assertEqual(result["process_evidence"]["exit_code"], 0)
            self.assertEqual(result["adapter_evidence"]["backend"], HOST_GATEWAY)
            records = list(ledger.glob("*.json")); self.assertEqual(len(records), 1)
            self.assertIn('"state":"COMPLETED"', records[0].read_text())

    def test_host_runner_blocks_version_drift_before_codex_execution_and_closes_ledger(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            sock = root / "runtime" / "gateway.sock"
            ledger = root / "ledger"
            calls = []

            def executor(argv, **kwargs):
                calls.append(list(argv))
                if argv == ["codex", "--version"]:
                    return subprocess.CompletedProcess(argv, 0, b"codex-cli 0.151.0\n", b"")
                raise AssertionError("Codex execution must not start after version drift")

            runner = UnixSocketHostRunner(sock, ledger, executor=executor)
            errors = []

            def serve():
                try:
                    runner.serve_once(timeout=3)
                except BaseException as exc:
                    errors.append(exc)

            thread = threading.Thread(target=serve, daemon=True)
            thread.start()
            for _ in range(100):
                if sock.exists() or errors:
                    break
                time.sleep(0.01)
            if errors or not sock.exists():
                self.skipTest("local sandbox does not permit AF_UNIX bind")
            time.sleep(0.02)

            result = UnixSocketGatewayTransport(sock, workspace_root=root)(
                request(codex_cli_version="0.150.1"),
                prompt=b"safe",
                last_message=root / "last",
                timeout=2,
                cancel_path=root / "cancel",
            )
            thread.join(timeout=2)
            self.assertFalse(errors)
            self.assertEqual(calls, [["codex", "--version"]])
            self.assertEqual(result["process_evidence"]["termination"], "BLOCKED")
            self.assertEqual(result["adapter_evidence"]["codex_version"], "0.151.0")
            records = list(ledger.glob("*.json"))
            self.assertEqual(len(records), 1)
            self.assertIn('"state":"FAILED"', records[0].read_text())

    def test_host_runner_version_probe_failure_closes_ledger_without_execution(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            sock = root / "runtime" / "gateway.sock"
            ledger = root / "ledger"
            calls = []

            def executor(argv, **kwargs):
                calls.append(list(argv))
                return subprocess.CompletedProcess(argv, 1, b"unavailable", b"")

            runner = UnixSocketHostRunner(sock, ledger, executor=executor)
            errors = []

            def serve():
                try:
                    runner.serve_once(timeout=3)
                except BaseException as exc:
                    errors.append(exc)

            thread = threading.Thread(target=serve, daemon=True)
            thread.start()
            for _ in range(100):
                if sock.exists() or errors:
                    break
                time.sleep(0.01)
            if errors or not sock.exists():
                self.skipTest("local sandbox does not permit AF_UNIX bind")
            time.sleep(0.02)

            result = UnixSocketGatewayTransport(sock, workspace_root=root)(
                request(), prompt=b"safe", last_message=root / "last",
                timeout=2, cancel_path=root / "cancel",
            )
            thread.join(timeout=2)
            self.assertFalse(errors)
            self.assertEqual(calls, [["codex", "--version"]])
            self.assertEqual(
                result["process_evidence"]["launch_authority_failure_category"],
                "CODEX_LAUNCH_VERSION_PROBE",
            )
            records = list(ledger.glob("*.json"))
            self.assertEqual(len(records), 1)
            self.assertIn('"state":"FAILED"', records[0].read_text())

    def test_broker_native_runner_blocks_bound_version_drift_before_tool_calls(self):
        from unittest.mock import patch
        from runtime.orchestrator.codex_dynamic_transport import CodexAppServerAdapter

        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            sock = root / "runtime" / "gateway.sock"
            ledger = root / "ledger"
            process_calls = []
            verified_schema = {
                "experimental_api": True, "dynamic_tool_request": True,
                "dynamic_tool_response": True, "empty_environment_supported": True,
                "schema_verified": True,
            }

            def adapter_factory():
                return CodexAppServerAdapter(
                    process_factory=lambda *args, **kwargs: process_calls.append(args),
                    version_probe=lambda: "0.151.0",
                    schema_probe=lambda: dict(verified_schema),
                )

            runner = UnixSocketHostRunner(sock, ledger, broker_native=True)
            errors = []

            def serve():
                try:
                    runner.serve_once(timeout=3)
                except BaseException as exc:
                    errors.append(exc)

            thread = threading.Thread(target=serve, daemon=True)
            thread.start()
            for _ in range(100):
                if sock.exists() or errors:
                    break
                time.sleep(0.01)
            if errors or not sock.exists():
                self.skipTest("local sandbox does not permit AF_UNIX bind")
            time.sleep(0.02)

            with patch(
                "runtime.orchestrator.production_tool_transport.CodexAppServerAdapter",
                side_effect=adapter_factory,
            ):
                result = UnixSocketGatewayTransport(sock, workspace_root=root)(
                    request(codex_cli_version="0.150.1"), prompt=b"safe",
                    last_message=root / "last", timeout=2, cancel_path=root / "cancel",
                )
            thread.join(timeout=2)
            self.assertFalse(errors)
            self.assertEqual(process_calls, [])
            self.assertEqual(
                result["process_evidence"]["launch_authority_failure_category"],
                "CODEX_LAUNCH_VERSION_BINDING",
            )
            records = list(ledger.glob("*.json"))
            self.assertEqual(len(records), 1)
            self.assertIn('"state":"FAILED"', records[0].read_text())

    def test_broker_native_post_launch_failure_preserves_effects_and_is_not_authority_block(self):
        from unittest.mock import patch
        from runtime.orchestrator.production_tool_transport import ProductionTransportFailure

        effect = {
            "operation": "PROJECT_OWNED_FILE_WRITE", "effect_id": "TE-POST-LAUNCH",
            "mutation_performed": True, "security_passed": True,
        }
        failure = ProductionTransportFailure(
            failure_category="TRANSPORT_POST_LAUNCH_FAILURE",
            effect_evidence_status="COLLECTED",
            governed_effect_evidence=[effect],
        )
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            sock = root / "runtime" / "gateway.sock"
            ledger = root / "ledger"
            runner = UnixSocketHostRunner(sock, ledger, broker_native=True)
            errors = []

            def serve():
                try:
                    runner.serve_once(timeout=3)
                except BaseException as exc:
                    errors.append(exc)

            thread = threading.Thread(target=serve, daemon=True)
            thread.start()
            for _ in range(100):
                if sock.exists() or errors:
                    break
                time.sleep(0.01)
            if errors or not sock.exists():
                self.skipTest("local sandbox does not permit AF_UNIX bind")
            time.sleep(0.02)

            with patch(
                "runtime.orchestrator.production_tool_transport.ProductionToolTransport.run",
                side_effect=failure,
            ):
                result = UnixSocketGatewayTransport(sock, workspace_root=root)(
                    request(codex_cli_version="0.150.1"), prompt=b"safe",
                    last_message=root / "last", timeout=2, cancel_path=root / "cancel",
                )
            thread.join(timeout=2)

            self.assertFalse(errors)
            evidence = result["process_evidence"]
            self.assertEqual(evidence["termination"], "FAILED")
            self.assertEqual(evidence["launch_authority_check"], "PASS")
            self.assertNotIn("launch_authority_failure_category", evidence)
            self.assertEqual(evidence["governed_effect_evidence"], [effect])
            self.assertEqual(evidence["effect_evidence_status"], "COLLECTED")
            self.assertEqual(evidence["effect_reconciliation_status"], "REQUIRED")
            records = list(ledger.glob("*.json"))
            self.assertEqual(len(records), 1)
            self.assertIn('"state":"FAILED"', records[0].read_text())

    def test_host_runner_accepts_stable_cli_version_outside_the_old_pin(self):
        def executor(argv, **kwargs):
            return subprocess.CompletedProcess(argv, 0, b"codex-cli 0.151.0\n", b"")
        from runtime.orchestrator.production_worker_executor import CodexExecutionAdapter
        self.assertEqual(CodexExecutionAdapter().probe_version(executor), "0.151.0")

    def test_host_runner_no_client_times_out_and_removes_socket(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            sock = root / "gateway.sock"
            runner = UnixSocketHostRunner(sock, root / "ledger", executor=lambda *a, **k: None)
            try:
                with self.assertRaisesRegex(GatewayError, "HOST_GATEWAY_ACCEPT_TIMEOUT"):
                    runner.serve_once(timeout=1)
            except PermissionError:
                self.skipTest("local sandbox does not permit AF_UNIX bind")
            self.assertFalse(sock.exists())

    def test_gateway_request_contract_is_version_bound(self):
        req = request()
        self.assertEqual(req["adapter_contract_version"], "SEM-025.v2")
        self.assertEqual(req["structured_event_contract_version"], "codex-exec-jsonl.0.150.1.v1")

    def test_one_command_synthetic_smoke_is_production_free(self):
        from runtime.orchestrator.host_synthetic_smoke import SmokeFailure, run_smoke
        try:
            result = run_smoke()
        except SmokeFailure as exc:
            if exc.stage in {"UDS_BIND", "SOCKET_POLICY", "CONNECT", "PEER_CREDENTIAL"}:
                self.skipTest("local sandbox does not permit AF_UNIX smoke")
            raise
        except Exception as exc:
            if ("permit" in str(exc).lower() or "operation not permitted" in str(exc).lower()
                    or "closed connection" in str(exc).lower()):
                self.skipTest("local sandbox does not permit AF_UNIX smoke")
            raise
        self.assertEqual(result["RESULT"], "HOST_SYNTHETIC_PASS")
        self.assertEqual(result["DUPLICATE_RERUN"], "NO")
        self.assertEqual(result["ADOPTION"], "PASS")

    def test_runtime_handler_configuration_is_generic_and_mutually_exclusive(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            handler = lambda request, **kwargs: {"execution_status": "BLOCKED"}
            runner = UnixSocketHostRunner(root / "handler.sock", root / "ledger", runtime_handler=handler)
            self.assertIs(runner.runtime_handler, handler)
            with self.assertRaisesRegex(GatewayError, "ambiguous"):
                UnixSocketHostRunner(root / "bad.sock", root / "ledger2", runtime_handler=handler, executor=lambda *a, **k: None)



if __name__ == "__main__":
    unittest.main()
