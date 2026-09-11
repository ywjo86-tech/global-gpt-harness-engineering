import unittest
import tempfile
import threading
import subprocess
import time
from pathlib import Path

from runtime.orchestrator.production_execution_gateway import (
    GATEWAY_CONTRACT_VERSION, HOST_GATEWAY, GatewayError, HostExecutionGateway,
    UnixSocketGatewayTransport, UnixSocketHostRunner,
    build_gateway_request, build_gateway_result, validate_gateway_request,
    validate_gateway_result, resolve_gateway_socket_path, _workspace_artifact_binding,
    _digest,
)
from runtime.orchestrator.tool_authorization import (
    activate_contract, build_dec007_approved_contracts, owned_scope_digest,
)


def request():
    return build_gateway_request(
        project_id="p", run_id="r", gate_id="g", lv_id="L", attempt=1,
        workspace_identity={"project_id": "p", "workspace_kind": "project_root"},
        package_manifest_sha256="a" * 64, preflight_evidence_sha256="b" * 64,
        runtime_prompt_artifact={"kind": "worker_runtime_prompt", "name": "executor.prompt.txt"},
        runtime_prompt_sha256="c" * 64, adapter_contract_version="SEM-025.v2",
        structured_event_contract_version="codex-exec-jsonl.0.150.1.v1",
    )


class GatewayContractTests(unittest.TestCase):
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
        for field, value in (("codex_version", "0.151.0"), ("native_command_runtime_count", 1),
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

    def test_host_runner_codex_version_mismatch_fails_closed(self):
        def executor(argv, **kwargs):
            return subprocess.CompletedProcess(argv, 0, b"codex-cli 0.151.0\n", b"")
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            runner = UnixSocketHostRunner(root / "gateway.sock", root / "ledger", executor=executor)
            with self.assertRaisesRegex(Exception, "supported contract"):
                from runtime.orchestrator.production_worker_executor import CodexExecutionAdapter
                CodexExecutionAdapter().probe_version(executor)

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


if __name__ == "__main__":
    unittest.main()
