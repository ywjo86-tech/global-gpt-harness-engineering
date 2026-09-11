import os, json, hashlib, subprocess, tempfile, unittest
from pathlib import Path
from unittest.mock import patch

from runtime.orchestrator.production_worker_executor import (
    EXECUTOR_ID, ProductionWorkerError, execute_production_worker,
    production_executor_manifest, _run_managed_child,
    _prompt, _secret_findings, _secret_origin_classifications,
    _hardcoded_credential_findings, _task_allows_secret_handling,
    _parse_unified_diff_lines, CodexExecutionAdapter, StructuredEventError,
    StructuredContentSecurityError,
    _bounded_structured_security_provenance,
    _parse_structured_jsonl, _validate_final_message,
    _validate_final_message_target, _validate_final_message_argv,
    _validate_final_message_bytes, _persist_private_final_message,
    _command_metadata, _tool_output_provenance,
    _bounded_command_output_source,
    _bounded_tool_task_scope_binding,
    _shell_graph_metadata, _tokenize_command, _file_content_provenance,
    _search_provenance, _search_record_matches,
    _independent_verification_steps,
    _independent_verification_provenance, _independent_verification_failure,
    _focused_execution_metadata,
    _test_runner_metadata,
)
from runtime.orchestrator.schemas import TaskSlice, WorkerRequest


def _valid_structured_stdout(*, agent_text: str = "completed") -> bytes:
    return b"\n".join(json.dumps(event).encode() for event in (
        {"type": "thread.started", "thread_id": "thread-1"},
        {"type": "turn.started"},
        {"type": "item.completed", "item": {"id": "message-1", "type": "agent_message", "text": agent_text}},
        {"type": "turn.completed", "usage": _usage()},
    ))


def _usage() -> dict[str, int]:
    return {"input_tokens": 1, "cached_input_tokens": 0, "cache_write_input_tokens": 0,
            "output_tokens": 1, "reasoning_output_tokens": 0}


class ProductionWorkerExecutorTests(unittest.TestCase):
    def test_test_runner_metadata_is_bounded(self):
        failed = _test_runner_metadata(b"===== 1 failed, 2 passed in 0.1s =====", b"", 1)
        self.assertEqual(failed["test_runner_result_category"], "TEST_FAILURE")
        self.assertEqual(failed["test_failed_count_bucket"], "1")
        collected = _test_runner_metadata(b"===== 2 errors in 0.1s =====", b"", 1)
        self.assertEqual(collected["test_runner_result_category"], "COLLECTION_ERROR")
        timeout = _test_runner_metadata(b"", b"", 124)
        self.assertEqual(timeout["test_runner_result_category"], "TIMEOUT")
    def test_multi_source_graph_retains_bounded_candidates(self):
        graph = _shell_graph_metadata(["rg", "one", ";", "rg", "two"])
        self.assertEqual(graph["search_source_count_bucket"], "2")
        self.assertEqual(graph["search_source_families"], ["rg", "rg"])
        self.assertEqual(graph["shell_output_attribution"], "MULTIPLE_POSSIBLE_SOURCES")
        self.assertTrue(all("source_candidate_scope" in item for item in graph["source_candidates"]))

    def test_text_processor_input_role_is_structural(self):
        stdin_graph = _shell_graph_metadata(["cat", "file", "|", "sed", "-n", "1,2p"])
        self.assertEqual(stdin_graph["shell_node_roles"][-1], "FILTER")
        file_graph = _shell_graph_metadata(["sed", "-n", "1,2p", "file"])
        self.assertEqual(file_graph["shell_node_roles"][0], "SOURCE_AND_FILTER")
        self.assertIn("FILE_CONTENT", file_graph["possible_output_source_categories"])

    def test_two_filesystem_text_processors_are_multiple_sources(self):
        graph = _shell_graph_metadata(["sed", "-n", "1p", "one", "&&", "sed", "-n", "1p", "two"])
        self.assertEqual(graph["source_candidate_count_bucket"], "2")
        self.assertEqual(graph["shell_output_attribution"], "MULTIPLE_POSSIBLE_SOURCES")

    def test_unknown_source_candidate_is_not_dropped(self):
        graph = _shell_graph_metadata(["rg", "one", "&&", "unknown-command"])
        self.assertIn("UNKNOWN", graph["possible_output_source_categories"])
        self.assertTrue(any(item["source_candidate_family"] == "unknown" for item in graph["source_candidates"]))

    def test_unknown_node_keeps_possible_source_candidate(self):
        graph = _shell_graph_metadata(["mystery-tool", "--emit"])
        self.assertTrue(graph["source_candidates"])
        self.assertEqual(graph["source_candidates"][0]["source_candidate_role"], "UNKNOWN")
        self.assertEqual(graph["source_candidates"][0]["source_candidate_output_capability"], "MAY_PRODUCE_OUTPUT")

    def test_unknown_shell_compound_node_is_not_serialized_as_control(self):
        metadata = _command_metadata("mystery-tool --emit")
        self.assertEqual(metadata["shell_node_families"], ["unknown"])
        self.assertEqual(metadata["shell_node_roles"], ["UNKNOWN"])
        self.assertEqual(metadata["shell_node_output_capabilities"], ["MAY_PRODUCE_OUTPUT"])
        self.assertEqual(len(metadata["source_candidates"]), 1)
    def test_independent_verification_reports_bounded_steps(self):
        steps = _independent_verification_steps({
            "focused_test": {"exit_code": 0, "timeout": False},
            "full_regression": {"exit_code": 2, "timeout": False},
            "compile_import": {"exit_code": 0, "timeout": False},
            "git_diff_check": {"exit_code": 0, "timeout": False},
        })
        self.assertEqual(steps[0]["verification_step_category"], "FOCUSED_TEST")
        self.assertEqual(steps[1]["verification_step_status"], "BLOCK")
        self.assertEqual(steps[1]["verification_step_failure_category"], "COMMAND_NONZERO")
        self.assertNotIn("command", steps[1])

    def test_issue060_independent_verification_failure_taxonomy_is_bounded(self):
        valid = {"exit_code": 0, "timeout": False}
        cases = (
            ({"focused_test":{"exit_code":1,"timeout":False}, "full_regression":valid,
              "compile_import":valid, "git_diff_check":valid}, "FOCUSED_TEST_EXECUTION", "NONZERO_EXIT", "PROCESS"),
            ({"focused_test":valid, "full_regression":{"exit_code":124,"timeout":True},
              "compile_import":valid, "git_diff_check":valid}, "FULL_TEST_EXECUTION", "TIMEOUT", "TIMEOUT"),
            ({"focused_test":valid, "full_regression":valid,
              "compile_import":{}, "git_diff_check":valid}, "COMPILE_EXECUTION", "RESULT_SCHEMA", "VALIDATION"),
        )
        for commands, step, category, bucket in cases:
            with self.subTest(step=step):
                provenance = _independent_verification_provenance(commands)
                self.assertEqual(provenance["worker_verification_failure_step"], step)
                self.assertEqual(provenance["worker_verification_failure_category"], category)
                self.assertEqual(provenance["worker_verification_exception_bucket"], bucket)
                failure = _independent_verification_failure(commands)
                self.assertEqual(failure.worker_verification_failure_step, step)

    def test_issue060_focused_execution_metadata_is_bounded(self):
        expected = {
            "focused_runner_source", "focused_runner_kind", "focused_command_builder_id",
            "focused_argv_shape_id", "focused_test_scope_source_id", "focused_cwd_source_id",
            "focused_env_projection_id", "focused_process_launcher_id", "focused_process_exit_class",
            "prior_fix_callsite_reached", "registered_runner_used", "legacy_module_path_reachable",
        }
        cases = (({"exit_code":0,"timeout":False}, "ZERO"),
                 ({"exit_code":3,"timeout":False}, "NONZERO"),
                 ({"exit_code":124,"timeout":True}, "TIMEOUT"),
                 ({"exit_code":None,"timeout":False,"spawn_error":True}, "SPAWN_ERROR"))
        for result, exit_class in cases:
            metadata = _focused_execution_metadata(result)
            self.assertEqual(set(metadata), expected)
            self.assertEqual(metadata["focused_process_exit_class"], exit_class)
            self.assertNotIn("command", metadata)

    def test_issue060_registered_test_runner_is_used_for_production_verification(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); request=self._fixture(root)
            python=root/".venv/bin/python"; pytest=root/".venv/bin/pytest"
            python.write_text("#!/bin/sh\nif [ \"$1\" = \"-m\" ] && [ \"$2\" = \"pytest\" ]; then exit 17; fi\nexec python3 \"$@\"\n")
            pytest.write_text("#!/bin/sh\nexit 0\n")
            python.chmod(0o755); pytest.chmod(0o755)
            def runner(*args, **kwargs):
                (root/"app").mkdir(); (root/"tests").mkdir()
                (root/"app/x.py").write_text("x=1\n")
                (root/"tests/test_x.py").write_text("def test_x(): assert True\n")
                return subprocess.CompletedProcess(args[0],0,b"ok",b"")
            result=execute_production_worker(request,executor=runner)
            self.assertEqual(result["independent_verification_status"], "PASS")
            process=json.loads((root/"out/executor.process.json").read_text())
            self.assertEqual(process["worker_verification_failure_step"], "NONE")
            self.assertEqual(process["worker_verification_last_successful_step"], "DIFF_CHECK_EXECUTION")
            self.assertEqual(process["prior_fix_callsite_reached"], "YES")
            self.assertEqual(process["registered_runner_used"], "YES")
            self.assertEqual(process["legacy_module_path_reachable"], "NO")
            self.assertEqual(process["focused_process_exit_class"], "ZERO")
            self.assertEqual(process["runner_environment_identity"], "PROJECT_VENV")
            self.assertEqual(process["cwd_binding_match"], "YES")
            self.assertEqual(process["project_root_import_path_present"], "YES")
            self.assertEqual(process["test_targets_resolvable"], "YES")
            self.assertEqual(process["pytest_config_load_status"], "PASS")
            self.assertEqual(process["plugin_load_status"], "PASS")

    def test_issue060_collection_failure_persists_only_bounded_diagnostics(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); request=self._fixture(root)
            python=root/".venv/bin/python"; pytest=root/".venv/bin/pytest"
            python.write_text("#!/bin/sh\nexec python3 \"$@\"\n"); pytest.write_text("#!/bin/sh\nexit 0\n")
            python.chmod(0o755); pytest.chmod(0o755)
            def runner(*args, **kwargs):
                (root/"app").mkdir(); (root/"tests").mkdir()
                (root/"app/x.py").write_text("x=1\n")
                (root/"tests/test_x.py").write_text("def test_x(): assert True\n")
                return subprocess.CompletedProcess(args[0],0,b"ok",b"")
            focused={"exit_code":1,"timeout":False,"test_exit_semantics":"COLLECTION_FAILED",
                     "collection_failure_phase":"PROJECT_MODULE_IMPORT",
                     "import_failure_family":"PROJECT_LOCAL_MODULE",
                     "dependency_presence_class":"MISSING"}
            passing={"exit_code":0,"timeout":False}
            probes=iter((focused, focused, passing, passing, passing, focused, focused))
            with patch("runtime.orchestrator.production_worker_executor._command",
                       side_effect=lambda *args, **kwargs: next(probes)):
                with self.assertRaises(ProductionWorkerError):
                    execute_production_worker(request,executor=runner)
            process=json.loads((root/"out/executor.process.json").read_text())
            self.assertEqual(process["collection_failure_phase"], "PROJECT_MODULE_IMPORT")
            self.assertEqual(process["import_failure_family"], "PROJECT_LOCAL_MODULE")
            self.assertEqual(process["dependency_presence_class"], "MISSING")
            self.assertEqual(process["focused_process_exit_class"], "NONZERO")
            self.assertFalse(any(key in process for key in ("focused_command", "focused_output", "focused_error")))
    def test_search_provenance_distinguishes_filesystem_and_stdin(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); (root / "src").mkdir(); (root / "src/a.py").write_text("token = 1\n")
            fs = _search_provenance({"command": ["rg", "token", "src"]}, workspace_root=root, owned_files=["src/a.py"])
            self.assertEqual(fs["search_input_mode"], "EXPLICIT_ROOT")
            self.assertEqual(fs["search_root_scopes"], ["WORKSPACE_OWNED"])
            stdin = _search_provenance({"command": ["rg", "token", "-"]}, workspace_root=root, owned_files=[])
            self.assertEqual(stdin["search_input_mode"], "STDIN")

    def test_search_file_record_requires_exact_source_line(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); (root / "src").mkdir(); (root / "src/a.py").write_text("token = 1\n")
            matched, framing = _search_record_matches("src/a.py:1:token = 1\n", workspace_root=root, owned_files=["src/a.py"])
            self.assertEqual(matched, {"src/a.py"}); self.assertEqual(framing, "RG_FILE_RECORD")
            unmatched, framing = _search_record_matches("src/a.py:1:prefix token = 1 suffix\n", workspace_root=root, owned_files=["src/a.py"])
            self.assertFalse(unmatched); self.assertEqual(framing, "RG_FILE_RECORD")

    def test_search_projection_uses_unique_graph_source_node(self):
        result = _tool_output_provenance(
            {"command": "bash -lc 'rg token src | sed -n 1,4p'"},
            "src/a.py:1:token = 1", workspace_root=None, owned_files=[],
        )
        self.assertEqual(result["tool_output_source_category"], "SEARCH_OUTPUT")
        self.assertEqual(result["search_tool_family"], "rg")

    def test_search_scope_projection_preserves_shell_compound_source(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); (root / "src").mkdir(); (root / "src/a.py").write_text("token = 1\n")
            result = __import__("runtime.orchestrator.production_worker_executor", fromlist=["_tool_output_provenance"])._tool_output_provenance(
                {"command": "true && rg token src"}, "src/a.py:1:token = 1", workspace_root=root, owned_files=["src/a.py"],
            )
            self.assertEqual(result["possible_output_source_categories"], ["SEARCH_OUTPUT"])
            self.assertEqual(result["search_input_mode"], "EXPLICIT_ROOT")
            self.assertEqual(result["search_root_scopes"], ["WORKSPACE_OWNED"])
            self.assertEqual(result["search_owned_attribution"], "OWNED")
            self.assertEqual(result["search_result_scope"], "WORKSPACE_OWNED")
            self.assertEqual(result["source_candidates"][0]["source_candidate_scope"], "WORKSPACE_OWNED")
    def test_file_content_provenance_uses_structural_scope_only(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workspace = root / "workspace"; run_root = root / "run"; host = root / "host"; temp = root / "temp"
            for item in (workspace, run_root, host, temp): item.mkdir()
            owned = workspace / "tests" / "test_safe.py"; owned.parent.mkdir(); owned.write_text("x\n")
            generated = run_root / "artifact.json"; generated.write_text("{}")
            system_like = host / "config.json"; system_like.write_text("{}")
            self.assertEqual(_file_content_provenance(owned, workspace_root=workspace, test_fixture_bound=True)["file_source_scope"], "WORKSPACE_OWNED")
            self.assertEqual(_file_content_provenance(generated, run_root=run_root, generated_current_run=True)["file_source_origin_category"], "GENERATED_ARTIFACT")
            self.assertEqual(_file_content_provenance(system_like, host_runtime_root=host)["file_source_scope"], "HOST_RUNTIME")
            self.assertEqual(_file_content_provenance("relative/file.txt")["file_source_scope"], "UNKNOWN")

    def test_file_content_scope_projects_to_shell_source_candidates(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); (root / "tests").mkdir()
            owned = root / "tests" / "fixture.txt"; owned.write_text("secret-like\n")
            provenance = __import__("runtime.orchestrator.production_worker_executor", fromlist=["_tool_output_provenance"])._tool_output_provenance(
                {"command": "sed -n 1p tests/fixture.txt"}, "secret-like",
                workspace_root=root, owned_files=["tests/fixture.txt"],
            )
            candidates = [item for item in provenance["source_candidates"] if item["source_candidate_purpose"] == "FILE_READ"]
            self.assertEqual(len(candidates), 1)
            self.assertEqual(candidates[0]["source_candidate_scope"], "WORKSPACE_OWNED")
            self.assertEqual(candidates[0]["file_source_origin_category"], "TEST_FIXTURE")
            self.assertEqual(provenance["credential_exposure_assessment"], "UNRESOLVED")

    def test_wrapped_multi_file_content_candidates_keep_independent_provenance(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); (root / "src").mkdir(); (root / "tests").mkdir()
            (root / "src/a.txt").write_text("api-key=synthetic\n")
            (root / "tests/fixture.txt").write_text("api-key=synthetic\n")
            provenance = __import__("runtime.orchestrator.production_worker_executor", fromlist=["_tool_output_provenance"])._tool_output_provenance(
                {"command": "bash -lc 'sed -n 1p src/a.txt; sed -n 1p tests/fixture.txt'"},
                "api-key=other", workspace_root=root, owned_files=["src/a.txt", "tests/fixture.txt"],
            )
            candidates = [item for item in provenance["source_candidates"] if item["source_candidate_purpose"] == "FILE_READ"]
            self.assertEqual(len(candidates), 2)
            self.assertTrue(all("file_source_scope" in item for item in candidates))
            self.assertTrue(all("file_source_origin_category" in item for item in candidates))
            self.assertEqual({item["source_candidate_scope"] for item in candidates}, {"WORKSPACE_OWNED"})
            self.assertEqual(provenance["credential_exposure_assessment"], "UNRESOLVED")
    def test_shell_execution_graph_is_canonical_and_bounded(self):
        cases = (
            ("git diff && git status", ["git", "git"], ["AND"], ["GIT_DIFF", "GIT_STATUS"], "MULTIPLE_POSSIBLE_SOURCES"),
            ("pytest && echo done", ["pytest", "shell_builtin"], ["AND"], ["TEST_RUNNER"], {"SINGLE_SOURCE", "MULTIPLE_POSSIBLE_SOURCES", "UNRESOLVED"}),
            ("git diff | head && git status", ["git", "head", "git"], ["MIXED"], ["GIT_DIFF", "GIT_STATUS"], "MULTIPLE_POSSIBLE_SOURCES"),
            ("rg pattern | head", ["rg", "head"], ["PIPE"], ["SEARCH_OUTPUT"], "FILTERED_SOURCE"),
            ("unknown_cmd && sed -n 1p", ["unknown", "sed"], ["AND"], ["UNKNOWN"], "UNRESOLVED"),
            ("( git diff || git status )", ["git", "git"], ["MIXED"], ["GIT_DIFF", "GIT_STATUS"], "MULTIPLE_POSSIBLE_SOURCES"),
        )
        for command, families, operators, sources, attribution in cases:
            with self.subTest(command=command):
                graph = _shell_graph_metadata(_tokenize_command(command))
                self.assertEqual(graph["shell_node_families"], families)
                self.assertEqual(graph["shell_operator_categories"], operators)
                self.assertEqual(graph["possible_output_source_categories"], sources)
                if isinstance(attribution, set):
                    self.assertIn(graph["shell_output_attribution"], attribution)
                else:
                    self.assertEqual(graph["shell_output_attribution"], attribution)
                self.assertNotIn(command, json.dumps(graph))

    def test_secret_like_tool_output_from_any_graph_remains_blocked(self):
        for command in ("git diff && git status", "git diff | head && git status", "unknown_cmd && sed -n 1p"):
            events = ("{" + f'"type":"thread.started","thread_id":"t"' + "}",
                      "{" + '"type":"turn.started"' + "}",
                      "{" + f'"type":"item.completed","item":{{"id":"c","type":"command_execution","status":"completed","command":{json.dumps(command)},"aggregated_output":"api-key=synthetic"}}' + "}")
            with self.subTest(command=command), self.assertRaises(StructuredContentSecurityError):
                _parse_structured_jsonl("\n".join(events).encode())

    def test_issue025_structured_security_provenance_is_bounded_and_unknown_fails_closed(self):
        known = StructuredContentSecurityError({"structured_security_findings":[{
            "structured_field_category":"TOOL_OUTPUT", "secret_kind":"password",
        }]})
        summary = _bounded_structured_security_provenance(known)
        self.assertEqual(summary["security_source_channel"], "WORKER")
        self.assertEqual(summary["security_value_origin"], "COMMAND_OUTPUT")
        self.assertEqual(summary["security_detector_family"], "SECRET_PATTERN")
        self.assertEqual(summary["security_event_stage"], "EVENT_VALIDATION")
        self.assertEqual(summary["worker_process_started"], "YES")
        self.assertEqual(summary["worker_result_boundary_reached"], "NO")
        self.assertEqual(summary["independent_verification_reached"], "NO")
        unknown = StructuredContentSecurityError({"structured_security_findings":[{}]})
        unknown_summary = _bounded_structured_security_provenance(unknown)
        self.assertEqual(unknown_summary["security_value_origin"], "UNKNOWN")
        self.assertEqual(unknown_summary["security_detector_family"], "UNKNOWN")
        self.assertEqual(unknown_summary["security_command_source_family"], "UNKNOWN")
        self.assertEqual(unknown_summary["security_source_resolution"], "UNKNOWN")
        self.assertEqual(unknown_summary["security_source_candidate_count"], 0)
        with self.assertRaises(StructuredContentSecurityError):
            raise unknown

    def test_issue025_command_output_source_binding_is_bounded_and_fail_closed(self):
        cases = (
            ("pytest -q", "WORKER_TEST_EXECUTION", "TEST", "EXACT", 1),
            ("git diff && git status", "WORKER_SHELL_EXECUTION", "SHELL", "MULTIPLE", 2),
            ("mystery-tool --emit", "WORKER_UNKNOWN_EXECUTION", "UNKNOWN", "UNKNOWN", 1),
        )
        for command, source_id, family, resolution, count in cases:
            events = (
                {"type": "thread.started", "thread_id": "thread-1"},
                {"type": "turn.started"},
                {"type": "item.completed", "item": {
                    "id": "cmd", "type": "command_execution", "status": "completed",
                    "command": command, "aggregated_output": "api-key=synthetic", "exit_code": 1,
                }},
            )
            with self.subTest(family=family), self.assertRaises(StructuredContentSecurityError) as caught:
                _parse_structured_jsonl(b"\n".join(json.dumps(event).encode() for event in events))
            finding = caught.exception.safe_metadata["structured_security_findings"][0]
            self.assertEqual(finding["security_command_source_id"], source_id)
            self.assertEqual(finding["security_command_source_family"], family)
            self.assertEqual(finding["security_command_execution_phase"], "COMPLETED")
            self.assertEqual(finding["security_source_resolution"], resolution)
            self.assertEqual(finding["security_source_candidate_count"], count)
            summary = _bounded_structured_security_provenance(caught.exception)
            self.assertEqual(summary["security_command_source_family"], family)
            self.assertEqual(summary["security_source_resolution"], resolution)
            self.assertNotIn(command, json.dumps(summary))
        safe_events = (
            {"type": "thread.started", "thread_id": "thread-1"},
            {"type": "turn.started"},
            {"type": "item.completed", "item": {
                "id": "cmd", "type": "command_execution", "status": "completed",
                "command": "pytest -q", "aggregated_output": "completed", "exit_code": 0,
            }},
            {"type": "turn.completed", "usage": _usage()},
        )
        parsed = _parse_structured_jsonl(b"\n".join(json.dumps(event).encode() for event in safe_events))
        self.assertEqual(parsed["structured_terminal_status"], "SUCCEEDED")

    def test_issue025_command_source_provenance_persists_in_process_evidence(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); request = self._fixture(root)
            events = (
                {"type": "thread.started", "thread_id": "thread-1"},
                {"type": "turn.started"},
                {"type": "item.completed", "item": {
                    "id": "cmd", "type": "command_execution", "status": "completed",
                    "command": "git diff && git status",
                    "aggregated_output": "password=synthetic", "exit_code": 1,
                }},
            )
            stdout = b"\n".join(json.dumps(event).encode() for event in events)
            evidence = {"termination": "EXITED", "exit_code": 0, "signal": None,
                        "requested_signal": None, "hard_stop": True}
            with patch("runtime.orchestrator.production_worker_executor._run_managed_child",
                       return_value=(stdout, b"", evidence)):
                with self.assertRaises(ProductionWorkerError):
                    execute_production_worker(request)
            stored = json.loads((root / "out/executor.process.json").read_text())
            self.assertEqual(stored["security_command_source_id"], "WORKER_SHELL_EXECUTION")
            self.assertEqual(stored["security_command_source_family"], "SHELL")
            self.assertEqual(stored["security_command_execution_phase"], "COMPLETED")
            self.assertEqual(stored["security_source_resolution"], "MULTIPLE")
            self.assertEqual(stored["security_source_candidate_count"], 2)
            self.assertEqual(stored["security_tool_capability"], "SHELL")
            self.assertEqual(stored["security_tool_data_origin"], "GENERATED_PROCESS_OUTPUT")
            self.assertEqual(stored["security_tool_operation_intent"], "EXECUTE")
            self.assertEqual(stored["tool_operation_required_for_worker_task"], "UNKNOWN")
            self.assertEqual(stored["tool_operation_within_approved_scope"], "UNKNOWN")
            self.assertEqual(stored["worker_task_id"], request.task.thread_id)
            self.assertEqual(stored["worker_action_id"], "COMMAND_EXECUTION_1")
            self.assertEqual(stored["tool_operation_policy_id"], "UNBOUND_TOOL_POLICY")
            self.assertEqual(stored["tool_operation_requirement_binding"], "UNKNOWN")
            self.assertEqual(stored["tool_scope_binding"], "UNKNOWN")
            self.assertEqual(stored["tool_scope_authorization_source"], "UNKNOWN")
            candidate = stored["tool_auth_contract_candidate"]
            self.assertEqual(candidate["contract_status"], "CANDIDATE")
            self.assertEqual(candidate["candidate_status"], "DECISION_REQUIRED")
            self.assertEqual(candidate["authorization_status"], "BLOCK")
            self.assertNotIn("synthetic", json.dumps(stored))

    def test_issue025_proof92_exact_tool_key_material_stays_blocked_and_raw_free(self):
        events = (
            {"type": "thread.started", "thread_id": "thread-1"},
            {"type": "turn.started"},
            {"type": "item.completed", "item": {
                "id": "cmd", "type": "command_execution", "status": "completed",
                "command": "gcc --version", "aggregated_output": "api-key=synthetic", "exit_code": 0,
            }},
        )
        with self.assertRaises(StructuredContentSecurityError) as caught:
            _parse_structured_jsonl(b"\n".join(json.dumps(event).encode() for event in events))
        summary = _bounded_structured_security_provenance(caught.exception)
        self.assertEqual(summary["security_detector_family"], "KEY_MATERIAL")
        self.assertEqual(summary["security_command_source_id"], "WORKER_TOOL_EXECUTION")
        self.assertEqual(summary["security_command_source_family"], "TOOL")
        self.assertEqual(summary["security_command_execution_phase"], "COMPLETED")
        self.assertEqual(summary["security_source_resolution"], "EXACT")
        self.assertEqual(summary["security_source_candidate_count"], 1)
        self.assertEqual(summary["security_tool_capability"], "OTHER")
        self.assertEqual(summary["security_tool_data_origin"], "GENERATED_PROCESS_OUTPUT")
        self.assertEqual(summary["security_tool_operation_intent"], "EXECUTE")
        self.assertEqual(summary["tool_operation_required_for_worker_task"], "UNKNOWN")
        self.assertEqual(summary["tool_operation_within_approved_scope"], "UNKNOWN")
        candidate = summary["tool_auth_contract_candidate"]
        self.assertEqual(candidate["contract_status"], "CANDIDATE")
        self.assertEqual(candidate["authorization_status"], "BLOCK")
        self.assertEqual(candidate["operation_class_id"], "UNBOUND_OPERATION_CLASS")
        self.assertIn("OPERATION_CLASS_ID", candidate["missing_authority_fields"])
        self.assertIn("REQUIREMENT_BINDING", candidate["missing_authority_fields"])
        self.assertIn("SCOPE_BINDING", candidate["missing_authority_fields"])
        self.assertIn("AUTHORIZATION_DECISION_REF", candidate["missing_authority_fields"])
        self.assertNotIn("synthetic", json.dumps(summary))

    def test_issue025_tool_task_scope_policy_bindings_are_explicit_and_closed(self):
        cases = (
            ({"required": ["TEST"], "in_scope": ["TEST"], "authorization_source": "PLAN_TASK"},
             "TEST", "REQUIRED", "IN_SCOPE", "YES", "YES"),
            ({"unrelated": ["OTHER"], "in_scope": ["OTHER"], "authorization_source": "POLICY"},
             "OTHER", "UNRELATED", "IN_SCOPE", "NO", "YES"),
            ({"required": ["FILE_READ"], "out_of_scope": ["FILE_READ"], "authorization_source": "OWNED_FILES"},
             "FILE_READ", "REQUIRED", "OUT_OF_SCOPE", "YES", "NO"),
            ({}, "UNKNOWN", "UNKNOWN", "UNKNOWN", "UNKNOWN", "UNKNOWN"),
        )
        for policy, capability, requirement, scope, required, in_scope in cases:
            with self.subTest(capability=capability, requirement=requirement, scope=scope):
                result = _bounded_tool_task_scope_binding(
                    capability=capability,
                    context={"worker_task_id": "TASK_1", "worker_action_id": "COMMAND_EXECUTION_1",
                             "tool_operation_policy_id": "POLICY_1", "policy": policy},
                )
                self.assertEqual(result["worker_task_id"], "TASK_1")
                self.assertEqual(result["worker_action_id"], "COMMAND_EXECUTION_1")
                self.assertEqual(result["tool_operation_policy_id"], "POLICY_1")
                self.assertEqual(result["tool_operation_requirement_binding"], requirement)
                self.assertEqual(result["tool_scope_binding"], scope)
                self.assertEqual(result["tool_operation_required_for_worker_task"], required)
                self.assertEqual(result["tool_operation_within_approved_scope"], in_scope)

    def test_command_shape_direct_and_wrapped_classification(self):
        cases = (
            ("git diff -- app/x.py", "DIRECT_EXEC", "git", "git", "DIFF", "GIT_DIFF", "0"),
            ("bash -lc 'git diff -- app/x.py'", "SHELL_C", "git", "git", "DIFF", "GIT_DIFF", "1"),
            ("pytest -q", "DIRECT_EXEC", "pytest", "pytest", "TEST", "TEST_RUNNER", "0"),
            ("sh -c 'pytest -q'", "SHELL_C", "pytest", "pytest", "TEST", "TEST_RUNNER", "1"),
        )
        for command, shape, executable, family, purpose, source, depth in cases:
            metadata = _command_metadata(command)
            self.assertEqual(metadata["command_shape_category"], shape)
            self.assertEqual(metadata["executable_family"], executable)
            self.assertEqual(metadata["command_family"], family)
            self.assertEqual(metadata["command_purpose"], purpose)
            self.assertEqual(metadata["wrapper_depth_bucket"], depth)
            provenance = __import__("runtime.orchestrator.production_worker_executor", fromlist=["_tool_output_provenance"])._tool_output_provenance(
                {"command": command}, "token=synthetic", workspace_root=None, owned_files=None)
            self.assertEqual(provenance["tool_output_source_category"], source)
            self.assertNotIn(command, json.dumps(provenance))

    def test_command_shape_compound_pipeline_and_substring_are_fail_closed(self):
        for command, expected_shape in (
            ("git diff | grep x", "PIPELINE"),
            ("git diff && pytest", "COMPOUND_AND"),
            ("git diff || pytest", "COMPOUND_OR"),
            ("( git diff )", "SUBSHELL"),
            ("bash -lc 'git diff | pytest'", "PIPELINE"),
        ):
            metadata = _command_metadata(command)
            self.assertIn(metadata["command_family"], {"mixed", "unknown"})
            self.assertEqual(metadata["command_purpose"], "OTHER")
            self.assertEqual(metadata["command_shape_category"], expected_shape)
        deceptive = _command_metadata("my-git-diff-helper")
        self.assertEqual(deceptive["command_family"], "unknown")
        self.assertEqual(deceptive["command_attribution_cause"], "DIRECT_EXEC_UNRECOGNIZED")

    def test_pipeline_stage_upstream_and_terminal_metadata_is_bounded(self):
        cases = (
            ("git diff | head", ["git", "head"], ["DIFF", "FILTER"], "head", "FILTER", "GIT_DIFF"),
            ("pytest | tail", ["pytest", "tail"], ["TEST", "FILTER"], "tail", "FILTER", "TEST_RUNNER"),
            ("rg pattern | head", ["rg", "head"], ["SEARCH", "FILTER"], "head", "FILTER", "SEARCH_OUTPUT"),
        )
        for command, families, purposes, terminal, terminal_purpose, upstream in cases:
            metadata = _command_metadata(command)
            self.assertEqual(metadata["pipeline_stage_count_bucket"], "2")
            self.assertEqual(metadata["pipeline_stage_families"], families)
            self.assertEqual(metadata["pipeline_stage_purposes"], purposes)
            self.assertEqual(metadata["pipeline_operator_category"], "PIPE_ONLY")
            self.assertEqual(metadata["pipeline_terminal_family"], terminal)
            self.assertEqual(metadata["pipeline_terminal_purpose"], terminal_purpose)
            self.assertEqual(metadata["pipeline_upstream_source_category"], upstream)
            self.assertEqual(metadata["pipeline_output_attribution"], "UPSTREAM_SOURCE")
            provenance = _tool_output_provenance(
                {"command": command}, "api-key=synthetic", workspace_root=None, owned_files=None)
            self.assertEqual(provenance["tool_output_source_category"], upstream)
            self.assertNotIn(command, json.dumps(provenance))

    def test_pipeline_unknown_redirection_and_compound_are_fail_closed(self):
        cases = (
            ("unknown_cmd | sed -n 1p", "PIPE_ONLY", "UNKNOWN", "UNRESOLVED"),
            ("git diff | head > result", "PIPE_WITH_REDIRECTION", "UNKNOWN", "UNRESOLVED"),
            ("git diff | head && pytest", "PIPE_WITH_COMPOUND", "UNKNOWN", "MULTI_STAGE"),
            ("git diff | head || pytest", "PIPE_WITH_COMPOUND", "UNKNOWN", "MULTI_STAGE"),
            ("notgitdiff | head", "PIPE_ONLY", "UNKNOWN", "UNRESOLVED"),
        )
        for command, operator, upstream, attribution in cases:
            metadata = _command_metadata(command)
            self.assertEqual(metadata["pipeline_operator_category"], operator)
            self.assertEqual(metadata["pipeline_upstream_source_category"], upstream)
            self.assertEqual(metadata["pipeline_output_attribution"], attribution)
            provenance = _tool_output_provenance(
                {"command": command}, "api-key=synthetic", workspace_root=None, owned_files=None)
            self.assertEqual(provenance["tool_output_source_category"], "UNKNOWN")
            self.assertEqual(provenance["credential_exposure_assessment"], "UNRESOLVED")
            self.assertNotIn(command, json.dumps(provenance))

    def test_pipeline_safe_metadata_is_durable_but_secret_output_stays_blocked(self):
        command = "bash -lc 'git diff | head'"
        output = "api-key=synthetic-pipeline"
        events = ({"type": "thread.started", "thread_id": "thread-1"},
                  {"type": "turn.started"},
                  {"type": "item.completed", "item": {"id": "cmd", "type": "command_execution",
                   "status": "completed", "command": command, "aggregated_output": output,
                   "exit_code": 0}})
        with self.assertRaises(StructuredContentSecurityError) as caught:
            _parse_structured_jsonl(b"\n".join(json.dumps(event).encode() for event in events))
        finding = caught.exception.safe_metadata["structured_security_findings"][0]
        self.assertEqual(finding["pipeline_stage_families"], ["git", "head"])
        self.assertEqual(finding["pipeline_upstream_source_category"], "GIT_DIFF")
        self.assertEqual(finding["pipeline_output_attribution"], "UPSTREAM_SOURCE")
        serialized = json.dumps(finding)
        self.assertNotIn(command, serialized)
        self.assertNotIn(output, serialized)
        self.assertNotIn("synthetic-pipeline", serialized)

    def test_command_shape_missing_empty_unsupported_and_parse_failure(self):
        cases = (
            (_command_metadata(None, present=False), "COMMAND_METADATA_MISSING"),
            (_command_metadata(""), "COMMAND_METADATA_EMPTY"),
            (_command_metadata(["git", "diff"]), "UNSUPPORTED_SCHEMA_SHAPE"),
            (_command_metadata("'unterminated"), "PARSE_FAILURE"),
        )
        for metadata, cause in cases:
            self.assertEqual(metadata["command_attribution_cause"], cause)
            self.assertEqual(metadata["command_family"], "unknown")

    def test_missing_and_unsupported_command_metadata_tool_output_stays_blocked(self):
        for command_present, command, expected_cause in (
            (False, None, "COMMAND_METADATA_MISSING"),
            (True, ["git", "diff"], "UNSUPPORTED_SCHEMA_SHAPE"),
        ):
            item = {"id": "cmd", "type": "command_execution", "status": "completed",
                    "aggregated_output": "token=synthetic", "exit_code": 0}
            if command_present:
                item["command"] = command
            events = ({"type": "thread.started", "thread_id": "thread-1"},
                      {"type": "turn.started"}, {"type": "item.completed", "item": item})
            with self.assertRaises(StructuredContentSecurityError) as caught:
                _parse_structured_jsonl(b"\n".join(json.dumps(event).encode() for event in events))
            finding = caught.exception.safe_metadata["structured_security_findings"][0]
            self.assertEqual(finding["command_attribution_cause"], expected_cause)
            self.assertEqual(finding["tool_output_source_category"], "UNKNOWN")
            self.assertEqual(finding["credential_exposure_assessment"], "UNRESOLVED")
            self.assertNotIn("synthetic", json.dumps(finding))

    def test_adapter_argv_binds_json_stdin_and_runtime_controls(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); target = root / "private" / "last"; target.parent.mkdir()
            argv = CodexExecutionAdapter().argv(root=root, last_message=target)
            self.assertEqual(argv[:2], ["codex", "--ask-for-approval"])
            self.assertIn("workspace-write", argv)
            self.assertIn("--json", argv)
            self.assertIn("--output-last-message", argv)
            self.assertEqual(argv[-1], "-")

    def test_final_message_target_and_flag_contract_fail_closed(self):
        with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as outside:
            root = Path(d); parent = root / "private"; parent.mkdir(); target = parent / "last"
            metadata = _validate_final_message_target(root, target)
            self.assertTrue(metadata["target_parent_exists"])
            self.assertTrue(metadata["target_parent_writable"])
            self.assertTrue(metadata["target_within_workspace"])
            self.assertTrue(metadata["target_within_allowed_write_scope"])
            argv = CodexExecutionAdapter().argv(root=root, last_message=target)
            with self.assertRaisesRegex(ProductionWorkerError, "flag binding"):
                _validate_final_message_argv([value for value in argv if value != "--output-last-message"], target)
            with self.assertRaisesRegex(ProductionWorkerError, "target binding mismatch"):
                _validate_final_message_argv(argv, parent / "other")
            with self.assertRaisesRegex(ProductionWorkerError, "outside workspace-write"):
                _validate_final_message_target(root, Path(outside) / "last")
            with self.assertRaisesRegex(ProductionWorkerError, "parent is missing"):
                _validate_final_message_target(root, root / "missing" / "last")

    def test_final_message_validation_and_cleanup_order_contract(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); target = root / "last"
            with self.assertRaisesRegex(ProductionWorkerError, "missing or unsafe"):
                _validate_final_message(target)
            target.write_bytes(b"")
            with self.assertRaisesRegex(ProductionWorkerError, "empty"):
                _validate_final_message(target)
            target.unlink(); target.mkdir()
            with self.assertRaisesRegex(ProductionWorkerError, "missing or unsafe"):
                _validate_final_message(target)
            target.rmdir(); target.write_text("completed", encoding="utf-8")
            self.assertTrue(_validate_final_message(target)["nonempty"])
            self.assertTrue(target.is_file())
            target.write_text("api-key=synthetic-final", encoding="utf-8")
            with self.assertRaises(StructuredContentSecurityError):
                _validate_final_message(target)

    def test_host_validated_final_message_is_privately_persisted_before_owned_cleanup(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); staging_parent = root / "staging"; evidence_parent = root / "evidence"
            staging_parent.mkdir(); evidence_parent.mkdir()
            staging = staging_parent / "last"; staging.write_text("completed", encoding="utf-8")
            payload = staging.read_bytes()
            self.assertTrue(_validate_final_message_bytes(payload)["nonempty"])
            persisted = evidence_parent / "last"
            _persist_private_final_message(persisted, payload)
            self.assertTrue(_validate_final_message(persisted)["nonempty"])
            self.assertEqual(persisted.stat().st_mode & 0o777, 0o600)
            self.assertTrue(staging.exists())
            staging.unlink(); staging_parent.rmdir()
            self.assertFalse(staging_parent.exists())

    def test_structured_jsonl_valid_lifecycle_is_value_free(self):
        events = b"\n".join(json.dumps(item).encode() for item in (
            {"type": "thread.started", "thread_id": "thread-1"}, {"type": "turn.started"},
            {"type": "item.completed", "item": {"id": "item-1", "type": "agent_message"}},
            {"type": "turn.completed", "usage": _usage()},
        ))
        parsed = _parse_structured_jsonl(events)
        self.assertEqual(parsed["event_type_counts"]["item.completed"], 1)
        self.assertTrue(parsed["terminal_event_present"])
        self.assertEqual(parsed["item_type_counts"], {"agent_message": 1})
        self.assertNotIn("item-1", json.dumps(parsed))

    def test_structured_jsonl_invalid_unknown_and_ordering_fail_closed(self):
        cases = (
            b"not-json",
            b'{"type":"future.event"}',
            b'{"type":"thread.started"}',
            b'{"type":"turn.completed"}',
            b'{"type":"thread.started"}\n{"type":"turn.started"}\n{"type":"turn.completed"}\n{"type":"turn.completed"}',
        )
        for payload in cases:
            with self.subTest(payload=payload[:12]), self.assertRaises(StructuredEventError):
                _parse_structured_jsonl(payload)

    def test_safe_unknown_event_type_is_bounded_metadata_and_stays_blocked(self):
        with self.assertRaisesRegex(StructuredEventError, "unknown structured event type") as caught:
            _parse_structured_jsonl(
                b'{"type":"thread.started","thread_id":"thread-1"}\n'
                b'{"type":"future.event","item":{"content":"must-not-survive"}}'
            )
        metadata = caught.exception.safe_metadata
        self.assertEqual(metadata["event_type_counts"], {"thread.started": 1})
        self.assertEqual(metadata["unknown_event_count"], 1)
        self.assertEqual(metadata["unknown_event_types"], ["future.event"])
        self.assertNotIn("must-not-survive", json.dumps(metadata))

    def test_unsafe_unknown_event_type_is_replaced_by_category(self):
        unsafe_type = "item started\nsecret"
        with self.assertRaises(StructuredEventError) as caught:
            _parse_structured_jsonl(json.dumps({"type": unsafe_type}).encode())
        metadata = caught.exception.safe_metadata
        self.assertEqual(metadata["unknown_event_count"], 1)
        self.assertEqual(metadata["unknown_event_type_category"], "INVALID_SAFE_IDENTIFIER")
        self.assertNotIn("unknown_event_types", metadata)
        self.assertNotIn(unsafe_type, json.dumps(metadata))

    def test_unknown_top_level_secret_body_is_not_retained_and_cannot_bypass_block(self):
        secret_body = "api-key=synthetic-secret-value"
        payload = json.dumps({
            "type": "future.event", "item": {"content": secret_body},
        }).encode()
        with self.assertRaises(StructuredEventError) as caught:
            _parse_structured_jsonl(payload)
        metadata = caught.exception.safe_metadata
        self.assertEqual(metadata["unknown_event_types"], ["future.event"])
        self.assertEqual(metadata["unknown_event_count"], 1)
        self.assertNotIn(secret_body, json.dumps(metadata))
        self.assertNotIn("item", metadata)
        self.assertNotIn("content", metadata)

    def test_known_event_counts_are_exact_and_canonical(self):
        events = b"\n".join(json.dumps(item).encode() for item in (
            {"type": "thread.started", "thread_id": "thread-1"},
            {"type": "turn.started"},
            {"type": "item.completed", "item": {"id": "one", "type": "agent_message"}},
            {"type": "item.completed", "item": {"id": "two", "type": "reasoning"}},
            {"type": "turn.completed", "usage": _usage()},
        ))
        parsed = _parse_structured_jsonl(events)
        self.assertEqual(parsed["event_type_counts"], {
            "item.completed": 2, "thread.started": 1,
            "turn.completed": 1, "turn.started": 1,
        })
        self.assertEqual(set(parsed["event_type_counts"]), {
            "thread.started", "turn.started", "item.completed", "turn.completed",
        })
        self.assertEqual(parsed["item_type_counts"], {"agent_message": 1, "reasoning": 1})

    def test_v01501_item_started_and_updated_lifecycles_succeed(self):
        events = (
            {"type": "thread.started", "thread_id": "thread-1"},
            {"type": "turn.started"},
            {"type": "item.started", "item": {"id": "cmd-1", "type": "command_execution", "status": "in_progress"}},
            {"type": "item.completed", "item": {"id": "cmd-1", "type": "command_execution", "status": "completed"}},
            {"type": "item.started", "item": {"id": "todo-1", "type": "todo_list"}},
            {"type": "item.updated", "item": {"id": "todo-1", "type": "todo_list"}},
            {"type": "item.completed", "item": {"id": "todo-1", "type": "todo_list"}},
            {"type": "turn.completed", "usage": _usage()},
        )
        parsed = _parse_structured_jsonl(b"\n".join(json.dumps(event).encode() for event in events))
        self.assertEqual(parsed["structured_terminal_status"], "SUCCEEDED")
        self.assertEqual(parsed["unknown_event_count"], 0)
        self.assertEqual(parsed["event_type_counts"]["item.started"], 2)
        self.assertEqual(parsed["event_type_counts"]["item.updated"], 1)
        self.assertEqual(parsed["item_type_counts"], {"command_execution": 2, "todo_list": 3})

    def test_completed_only_official_item_subtypes_succeed(self):
        events = (
            {"type": "thread.started", "thread_id": "thread-1"},
            {"type": "turn.started"},
            {"type": "item.completed", "item": {"id": "msg-1", "type": "agent_message"}},
            {"type": "item.completed", "item": {"id": "reason-1", "type": "reasoning"}},
            {"type": "item.completed", "item": {"id": "patch-1", "type": "file_change", "status": "completed"}},
            {"type": "item.completed", "item": {"id": "search-1", "type": "web_search"}},
            {"type": "item.completed", "item": {"id": "warning-1", "type": "error"}},
            {"type": "turn.completed", "usage": _usage()},
        )
        parsed = _parse_structured_jsonl(b"\n".join(json.dumps(event).encode() for event in events))
        self.assertEqual(parsed["structured_terminal_status"], "SUCCEEDED")
        self.assertEqual(parsed["item_type_counts"]["file_change"], 1)

    def test_file_change_started_and_completed_lifecycles_match_v01501(self):
        change = [{"path": "app/x.py", "kind": "update"}]
        prefix = (
            {"type": "thread.started", "thread_id": "thread-1"},
            {"type": "turn.started"},
        )
        started = {"type": "item.started", "item": {
            "id": "patch-private-id", "type": "file_change", "changes": change, "status": "in_progress",
        }}
        completed = {"type": "item.completed", "item": {
            "id": "patch-private-id", "type": "file_change", "changes": change, "status": "completed",
        }}
        parsed = _parse_structured_jsonl(b"\n".join(json.dumps(event).encode() for event in (
            *prefix, started, completed, {"type": "turn.completed", "usage": _usage()},
        )))
        self.assertEqual(parsed["structured_terminal_status"], "SUCCEEDED")
        self.assertEqual(parsed["item_type_counts"], {"file_change": 2})
        completed_only = _parse_structured_jsonl(b"\n".join(json.dumps(event).encode() for event in (
            *prefix, {**completed, "item": {**completed["item"], "id": "completed-only"}},
            {"type": "turn.completed", "usage": _usage()},
        )))
        self.assertEqual(completed_only["structured_terminal_status"], "SUCCEEDED")

    def test_file_change_wrong_status_and_duplicate_start_remain_blocked(self):
        prefix = (
            {"type": "thread.started", "thread_id": "thread-1"},
            {"type": "turn.started"},
        )
        wrong = {"type": "item.started", "item": {
            "id": "patch-private-id", "type": "file_change", "changes": [], "status": "completed",
        }}
        with self.assertRaises(StructuredEventError) as status_error:
            _parse_structured_jsonl(b"\n".join(json.dumps(event).encode() for event in (*prefix, wrong)))
        self.assertEqual(status_error.exception.safe_metadata["structured_failure_stage"], "ITEM_STATUS")
        self.assertEqual(status_error.exception.safe_metadata["structured_expected_status_category"], "IN_PROGRESS")
        started = {**wrong, "item": {**wrong["item"], "status": "in_progress"}}
        with self.assertRaises(StructuredEventError) as duplicate:
            _parse_structured_jsonl(b"\n".join(json.dumps(event).encode() for event in (*prefix, started, started)))
        self.assertEqual(duplicate.exception.safe_metadata["structured_failure_stage"], "ITEM_TRANSITION")

    def test_lifecycle_incompatibility_is_not_mislabeled_item_status(self):
        payload = b"\n".join(json.dumps(event).encode() for event in (
            {"type": "thread.started", "thread_id": "thread-1"},
            {"type": "turn.started"},
            {"type": "item.started", "item": {"id": "message-1", "type": "agent_message", "text": "safe"}},
        ))
        with self.assertRaises(StructuredEventError) as caught:
            _parse_structured_jsonl(payload)
        self.assertEqual(caught.exception.safe_metadata["structured_failure_stage"], "ITEM_TRANSITION")
        self.assertNotEqual(caught.exception.safe_metadata["structured_failure_stage"], "ITEM_STATUS")

    def test_item_state_machine_blocks_invalid_transitions_and_subtypes(self):
        prefixes = ({"type": "thread.started", "thread_id": "thread-1"}, {"type": "turn.started"})
        invalid_events = (
            {"type": "item.updated", "item": {"id": "todo-1", "type": "todo_list"}},
            {"type": "item.started", "item": {"id": "msg-1", "type": "agent_message"}},
            {"type": "item.completed", "item": {"id": "x", "type": "unknown_item"}},
        )
        for invalid in invalid_events:
            with self.subTest(event=invalid["type"], item_type=invalid["item"]["type"]):
                payload = b"\n".join(json.dumps(event).encode() for event in (*prefixes, invalid))
                with self.assertRaises(StructuredEventError):
                    _parse_structured_jsonl(payload)

    def test_structured_failure_metadata_preserves_partial_counts_and_meaning(self):
        prefix = (
            {"type": "thread.started", "thread_id": "thread-1"},
            {"type": "turn.started"},
        )
        cases = (
            ({"type": "item.started", "item": {"id": "private-item-id", "type": "command_execution",
                                                  "status": "failed"}}, "ITEM_STATUS", "item.started", "command_execution"),
            ({"type": "item.updated", "item": {"id": "private-item-id", "type": "todo_list"}},
             "ITEM_TRANSITION", "item.updated", "todo_list"),
            ({"type": "item.completed", "item": {"id": "private-item-id", "type": "future_item"}},
             "ITEM_TYPE", "item.completed", "UNKNOWN"),
        )
        for event, stage, event_type, item_type in cases:
            payload = b"\n".join(json.dumps(value).encode() for value in (*prefix, event))
            with self.subTest(stage=stage), self.assertRaises(StructuredEventError) as caught:
                _parse_structured_jsonl(payload)
            metadata = caught.exception.safe_metadata
            self.assertEqual(metadata["structured_failure_stage"], stage)
            self.assertEqual(metadata["structured_failure_event_type"], event_type)
            self.assertEqual(metadata["structured_failure_item_type"], item_type)
            self.assertEqual(metadata["event_type_counts"], {"thread.started": 1, "turn.started": 1})
            self.assertEqual(metadata["unknown_event_count"], 0)
            self.assertNotIn("private-item-id", json.dumps(metadata))

    def test_unknown_event_and_json_parse_have_distinct_failure_metadata(self):
        with self.assertRaises(StructuredEventError) as unknown:
            _parse_structured_jsonl(b'{"type":"future.event"}')
        self.assertEqual(unknown.exception.safe_metadata["structured_failure_stage"], "TOP_LEVEL_EVENT")
        self.assertEqual(unknown.exception.safe_metadata["unknown_event_count"], 1)
        with self.assertRaises(StructuredEventError) as malformed:
            _parse_structured_jsonl(b"not-json")
        self.assertEqual(malformed.exception.safe_metadata["structured_failure_stage"], "JSON_PARSE")
        self.assertEqual(malformed.exception.safe_metadata["unknown_event_count"], 0)
        self.assertEqual(malformed.exception.safe_metadata["parse_error_count"], 1)

    def test_invalid_raw_status_is_replaced_by_bounded_categories(self):
        raw_status = "api-key=must-not-survive"
        payload = b"\n".join(json.dumps(value).encode() for value in (
            {"type": "thread.started", "thread_id": "thread-1"},
            {"type": "turn.started"},
            {"type": "item.started", "item": {
                "id": "item-1", "type": "command_execution", "status": raw_status,
            }},
        ))
        with self.assertRaises(StructuredEventError) as caught:
            _parse_structured_jsonl(payload)
        metadata = caught.exception.safe_metadata
        self.assertEqual(metadata["structured_failure_stage"], "ITEM_STATUS")
        self.assertEqual(metadata["structured_failure_status_category"], "UNKNOWN")
        self.assertEqual(metadata["structured_expected_status_category"], "IN_PROGRESS")
        self.assertNotIn(raw_status, json.dumps(metadata))

    def test_duplicate_item_and_terminal_events_are_blocked(self):
        cases = (
            (
                {"type": "item.started", "item": {"id": "cmd-1", "type": "command_execution", "status": "in_progress"}},
                {"type": "item.started", "item": {"id": "cmd-1", "type": "command_execution", "status": "in_progress"}},
            ),
            (
                {"type": "turn.completed", "usage": _usage()},
                {"type": "turn.completed", "usage": _usage()},
            ),
        )
        prefix = ({"type": "thread.started", "thread_id": "thread-1"}, {"type": "turn.started"})
        for suffix in cases:
            with self.subTest(suffix=suffix[0]["type"]):
                with self.assertRaises(StructuredEventError):
                    _parse_structured_jsonl(b"\n".join(json.dumps(event).encode() for event in (*prefix, *suffix)))

    def test_known_failure_events_are_safe_failed_terminals(self):
        for failure in (
            {"type": "turn.failed", "error": {"message": "synthetic failure"}},
            {"type": "error", "message": "synthetic stream error"},
        ):
            prefix = ({"type": "thread.started", "thread_id": "thread-1"}, {"type": "turn.started"})
            with self.subTest(event=failure["type"]), self.assertRaises(StructuredEventError) as caught:
                _parse_structured_jsonl(b"\n".join(json.dumps(event).encode() for event in (*prefix, failure)))
            metadata = caught.exception.safe_metadata
            self.assertEqual(metadata["structured_terminal_status"], "FAILED")
            self.assertEqual(metadata["failure_event_type"], failure["type"])
            self.assertNotIn("synthetic", json.dumps(metadata))

    def test_missing_success_terminal_and_item_secrets_are_blocked(self):
        incomplete = b'{"type":"thread.started","thread_id":"thread-1"}\n{"type":"turn.started"}'
        with self.assertRaises(StructuredEventError):
            _parse_structured_jsonl(incomplete)
        for event_type in ("item.started", "item.completed"):
            item = {"id": "cmd-1", "type": "command_execution",
                    "status": "in_progress" if event_type == "item.started" else "completed",
                    "command": "api-key=synthetic-secret-value"}
            payload = b"\n".join(json.dumps(event).encode() for event in (
                {"type": "thread.started", "thread_id": "thread-1"},
                {"type": "turn.started"}, {"type": event_type, "item": item},
            ))
            with self.subTest(event_type=event_type), self.assertRaisesRegex(ProductionWorkerError, "secret-like"):
                _parse_structured_jsonl(payload)

    def test_codex_version_is_exactly_bound_to_structured_contract(self):
        self.assertEqual(CodexExecutionAdapter.validate_version_output(b"codex-cli 0.150.1\n"), "0.150.1")
        for value in (b"codex-cli 0.150.0\n", b"codex-cli 0.151.0\n", b"unknown\n"):
            with self.subTest(value=value), self.assertRaises(StructuredEventError):
                CodexExecutionAdapter.validate_version_output(value)

    def test_structured_event_secret_and_final_message_are_blocked(self):
        payload = _valid_structured_stdout(agent_text="api-key=synthetic-secret-value")
        with self.assertRaisesRegex(ProductionWorkerError, "secret-like"):
            _parse_structured_jsonl(payload)
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "last"
            path.write_text("api-key=synthetic-secret-value", encoding="utf-8")
            with self.assertRaisesRegex(StructuredContentSecurityError, "secret-like") as caught:
                _validate_final_message(path)
            finding = caught.exception.safe_metadata["security_findings"][0]
            self.assertEqual(finding["security_channel"], "FINAL_MESSAGE")
            self.assertEqual(finding["structured_field_category"], "CONTENT_TEXT")

    def test_structural_identity_is_not_broad_scanned_as_serialized_json(self):
        events = (
            {"type": "thread.started", "thread_id": "api-key=structural-identifier"},
            {"type": "turn.started"},
            {"type": "item.completed", "item": {"id": "token=structural-id", "type": "agent_message", "text": "safe"}},
            {"type": "turn.completed", "usage": _usage()},
        )
        parsed = _parse_structured_jsonl(b"\n".join(json.dumps(event).encode() for event in events))
        self.assertEqual(parsed["structured_terminal_status"], "SUCCEEDED")

    def test_typed_command_tool_and_error_content_remain_blocking(self):
        cases = (
            ({"id": "cmd", "type": "command_execution", "status": "completed",
              "command": "api-key=synthetic-command", "aggregated_output": ""}, "COMMAND"),
            ({"id": "mcp", "type": "mcp_tool_call", "status": "completed",
              "result": {"content": [{"text": "token=synthetic-output"}], "structured_content": None}}, "TOOL_OUTPUT"),
            ({"id": "err", "type": "error", "message": "password=synthetic-error"}, "ERROR_CONTENT"),
        )
        for item, category in cases:
            events = (
                {"type": "thread.started", "thread_id": "thread-1"},
                {"type": "turn.started"},
                {"type": "item.completed", "item": item},
            )
            with self.subTest(category=category), self.assertRaises(StructuredContentSecurityError) as caught:
                _parse_structured_jsonl(b"\n".join(json.dumps(event).encode() for event in events))
            finding = caught.exception.safe_metadata["structured_security_findings"][0]
            self.assertEqual(finding["structured_field_category"], category)
            self.assertEqual(finding["security_channel"], "STRUCTURED_JSONL")

    def test_tool_output_safe_provenance_is_bounded_and_fail_closed(self):
        cases = (
            ("git diff -- app/x.py", "+api_key = 'synthetic-a'", "git", "DIFF", "GIT_DIFF"),
            ("pytest -q", "api-key=synthetic-b", "pytest", "TEST", "TEST_RUNNER"),
            ("unrecognized-tool", "api-key=synthetic-c", "unknown", "UNKNOWN", "UNKNOWN"),
        )
        for command, output, family, purpose, source in cases:
            events = (
                {"type": "thread.started", "thread_id": "thread-1"},
                {"type": "turn.started"},
                {"type": "item.completed", "item": {
                    "id": "cmd", "type": "command_execution", "status": "completed",
                    "command": command, "aggregated_output": output, "exit_code": 0,
                }},
            )
            with self.subTest(source=source), self.assertRaises(StructuredContentSecurityError) as caught:
                _parse_structured_jsonl(b"\n".join(json.dumps(event).encode() for event in events))
            finding = caught.exception.safe_metadata["structured_security_findings"][0]
            self.assertEqual(finding["command_family"], family)
            self.assertEqual(finding["command_purpose"], purpose)
            self.assertEqual(finding["tool_output_source_category"], source)
            self.assertEqual(finding["credential_exposure_assessment"], "UNRESOLVED")
            serialized = json.dumps(finding)
            self.assertNotIn(command, serialized)
            self.assertNotIn(output, serialized)

    def test_tool_output_exact_owned_source_and_fixture_attribution(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); (root / "app").mkdir(); (root / "tests").mkdir()
            source_line = "api_key = 'synthetic-owned-source'"
            fixture_line = "api_key = 'synthetic-owned-fixture'"
            (root / "app/x.py").write_text(source_line + "\n", encoding="utf-8")
            (root / "tests/test_x.py").write_text(fixture_line + "\n", encoding="utf-8")
            for line, expected_path, expected_category, assessment in (
                (source_line, "app/x.py", "EXACT_SOURCE_LINE", "CONFIRMED_CONTENT_SECRET"),
                (fixture_line, "tests/test_x.py", "EXACT_TEST_FIXTURE_LINE", "OWNED_NONCREDENTIAL_ECHO"),
            ):
                events = (
                    {"type": "thread.started", "thread_id": "thread-1"}, {"type": "turn.started"},
                    {"type": "item.completed", "item": {"id": "cmd", "type": "command_execution",
                     "status": "completed", "command": "sed -n 1p " + expected_path,
                     "aggregated_output": line, "exit_code": 0}},
                )
                with self.subTest(category=expected_category), self.assertRaises(StructuredContentSecurityError) as caught:
                    _parse_structured_jsonl(b"\n".join(json.dumps(event).encode() for event in events),
                                            workspace_root=root, owned_files=["app/x.py", "tests/test_x.py"])
                finding = caught.exception.safe_metadata["structured_security_findings"][0]
                self.assertTrue(finding["owned_workspace_match"])
                self.assertEqual(finding["owned_relative_paths"], [expected_path])
                self.assertEqual(finding["owned_source_category"], expected_category)
                self.assertEqual(finding["credential_exposure_assessment"], assessment)

    def test_tool_output_exact_diff_and_substring_only_rejection(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); (root / "app").mkdir()
            exact = "api_key = 'synthetic-diff-value'"
            (root / "app/x.py").write_text(exact + "\n", encoding="utf-8")
            for output, matched in (("+" + exact, True), ("+" + exact + "-suffix", False)):
                events = (
                    {"type": "thread.started", "thread_id": "thread-1"}, {"type": "turn.started"},
                    {"type": "item.completed", "item": {"id": "cmd", "type": "command_execution",
                     "status": "completed", "command": "git diff -- app/x.py",
                     "aggregated_output": output, "exit_code": 0}},
                )
                with self.subTest(matched=matched), self.assertRaises(StructuredContentSecurityError) as caught:
                    _parse_structured_jsonl(b"\n".join(json.dumps(event).encode() for event in events),
                                            workspace_root=root, owned_files=["app/x.py"])
                finding = caught.exception.safe_metadata["structured_security_findings"][0]
                self.assertEqual(finding["owned_workspace_match"], matched)
                self.assertEqual(finding["owned_source_category"], "EXACT_DIFF_LINE" if matched else "NONE")
                self.assertEqual(finding["tool_output_source_category"], "GIT_DIFF")

    def test_tool_output_mixed_and_unknown_producers_remain_blocked(self):
        cases = (
            ("git diff", "+api-key=synthetic-mixed\nTraceback (most recent call last):", "MIXED"),
            ("unknown", "api-key=synthetic-unknown", "UNKNOWN"),
        )
        for command, output, expected in cases:
            events = (
                {"type": "thread.started", "thread_id": "thread-1"}, {"type": "turn.started"},
                {"type": "item.completed", "item": {"id": "cmd", "type": "command_execution",
                 "status": "failed", "command": command, "aggregated_output": output, "exit_code": 1}},
            )
            with self.subTest(expected=expected), self.assertRaises(StructuredContentSecurityError) as caught:
                _parse_structured_jsonl(b"\n".join(json.dumps(event).encode() for event in events))
            self.assertEqual(caught.exception.safe_metadata["structured_security_findings"][0]
                             ["tool_output_source_category"], expected)

    def test_unknown_structured_field_semantics_are_blocked(self):
        payload = b"\n".join(json.dumps(event).encode() for event in (
            {"type": "thread.started", "thread_id": "thread-1"},
            {"type": "turn.started"},
            {"type": "item.completed", "item": {
                "id": "message-1", "type": "agent_message", "text": "safe", "future_content": "safe",
            }},
        ))
        with self.assertRaisesRegex(StructuredEventError, "unknown or missing fields"):
            _parse_structured_jsonl(payload)

    def test_final_message_valid_shape_is_bounded_metadata(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "last"
            path.write_text("completed", encoding="utf-8")
            metadata = _validate_final_message(path)
            self.assertEqual(metadata["exists"], True)
            self.assertEqual(metadata["nonempty"], True)
            self.assertNotIn("completed", json.dumps(metadata))

    def test_secret_origin_metadata_never_contains_value_or_hash(self):
        candidate = "safe-test-candidate-0123456789abcdef"
        with patch.dict(os.environ, {"HARNESS_TEST_CREDENTIAL": candidate}, clear=False):
            result = _secret_origin_classifications(
                f"api-key={candidate}".encode(), channel="stderr", prompt=b"", last_message=b""
            )
        entry = result["api-key"]["NON_PLACEHOLDER_32+_mixed"]
        self.assertEqual(entry["count"], 1)
        self.assertTrue(entry["origin"]["secret_env_match"])
        serialized = json.dumps(result, sort_keys=True)
        self.assertNotIn(candidate, serialized)
        self.assertNotIn(hashlib.sha256(candidate.encode()).hexdigest(), serialized)

    def test_secret_origin_prompt_last_message_and_unknown_are_aggregated(self):
        prompt_candidate = "prompt-candidate-0123456789abcdef0"
        last_candidate = "last-candidate-0123456789abcdef0"
        prompt = f"token={prompt_candidate}".encode()
        last = f"api-key={last_candidate}".encode()
        result = _secret_origin_classifications(
            f"token={prompt_candidate} api-key={last_candidate} authorization=unknown-candidate-0123456789abcdef".encode(),
            channel="stderr", prompt=prompt, last_message=last,
            prompt_sources={"execution_package.task_context.input": prompt},
        )
        self.assertTrue(result["token"]["NON_PLACEHOLDER_32+_mixed"]["origin"]["prompt_match"])
        self.assertEqual(result["token"]["NON_PLACEHOLDER_32+_mixed"]["origin"]["prompt_logical_fields"],
                         ["execution_package.task_context.input"])
        self.assertTrue(result["api-key"]["NON_PLACEHOLDER_32+_mixed"]["origin"]["last_message_match"])
        self.assertTrue(result["authorization"]["NON_PLACEHOLDER_32+_mixed"]["origin"]["stderr_only_unknown"])

    def test_runtime_prompt_has_no_credential_assignment(self):
        with tempfile.TemporaryDirectory() as d:
            request = self._fixture(Path(d))
            self.assertEqual(_secret_findings(_prompt(request, "a" * 40, ["app/x.py"]).encode()), {})

    def test_structured_codex_telemetry_is_classified_but_not_allowed(self):
        result = _secret_origin_classifications(
            b"codex-usage token=123456", channel="stderr"
        )
        origin = result["token"]["NON_PLACEHOLDER_1-15_alnum"]["origin"]
        self.assertEqual(origin["producer_categories"], ["CODEX_USAGE_TELEMETRY"])
        self.assertFalse(origin["stderr_only_unknown"])
        self.assertEqual(origin["structure_category"], ["STRUCTURED_CLI_DIAGNOSTIC"])
        self.assertTrue(origin["known_cli_frame"])

    def test_stderr_structure_metadata_is_value_free_and_deterministic(self):
        candidate = "synthetic-structure-value"
        cases = (
            (f"api-key:{candidate}", "PLAIN_KEY_VALUE", "COLON", "UNQUOTED", "WHOLE_LINE_KEY_VALUE"),
            (f"api-key={candidate}", "PLAIN_KEY_VALUE", "EQUALS", "UNQUOTED", "WHOLE_LINE_KEY_VALUE"),
            (f'{{"message":"api-key={candidate}"}}', "JSON_KEY_VALUE", "EQUALS", "UNQUOTED", "PREFIXED_KEY_VALUE"),
            (f"export API_KEY={candidate}", "SHELL_ASSIGNMENT", "EQUALS", "UNQUOTED", "PREFIXED_KEY_VALUE"),
            (f"+ api-key={candidate}", "DIFF_SOURCE_ECHO", "EQUALS", "UNQUOTED", "PREFIXED_KEY_VALUE"),
            (f"`api-key={candidate}`", "MARKDOWN_CODE", "EQUALS", "UNQUOTED", "PREFIXED_KEY_VALUE"),
        )
        for line, structure, delimiter, quote, finding_scope in cases:
            with self.subTest(structure=structure):
                origin = next(iter(_secret_origin_classifications(
                    line.encode(), channel="stderr"
                )["api-key"].values()))["origin"]
                self.assertEqual(origin["structure_category"], [structure])
                self.assertEqual(origin["delimiter_category"], [delimiter])
                self.assertEqual(origin["quote_category"], [quote])
                self.assertEqual(origin["finding_scope_category"], [finding_scope])
                self.assertFalse(origin["known_cli_frame"])
                serialized = json.dumps(origin)
                self.assertNotIn(candidate, serialized)
                self.assertNotIn(hashlib.sha256(candidate.encode()).hexdigest(), serialized)

    def test_known_cli_diagnostic_frame_is_structural_not_allowlisted(self):
        candidate = "synthetic-diagnostic-value"
        origin = _secret_origin_classifications(
            f"codex-diagnostic api-key={candidate}".encode(), channel="stderr"
        )["api-key"]["NON_PLACEHOLDER_16-31_mixed"]["origin"]
        self.assertEqual(origin["producer_category"], "CODEX_CLI_DIAGNOSTIC")
        self.assertEqual(origin["structure_category"], ["STRUCTURED_CLI_DIAGNOSTIC"])
        self.assertTrue(origin["known_cli_frame"])

    def test_stateful_diff_add_remove_context_attribution_is_safe(self):
        candidate = "synthetic-diff-value"
        diff = ("diff --git a/app/a.py b/app/a.py\n"
                "--- a/app/a.py\n+++ b/app/a.py\n@@ -1,3 +1,3 @@\n"
                f"+password:{candidate}\n"
                f"-password:{candidate}\n"
                f" password:{candidate}\n").encode()
        result = _secret_origin_classifications(diff, channel="stderr")
        entries = result["password"]["NON_PLACEHOLDER_16-31_mixed"]
        self.assertEqual(entries["count"], 3)
        origin = entries["origin"]
        self.assertEqual(origin["diff_target_relative_paths"], ["app/a.py"])
        self.assertEqual(set(origin["diff_change_category"]), {"ADD", "REMOVE", "CONTEXT"})
        self.assertEqual(origin["diff_file_type"], ["PYTHON"])
        self.assertEqual(origin["producer_category"], "UNKNOWN")
        self.assertTrue(origin["stderr_only_unknown"])
        self.assertNotIn(candidate, json.dumps(result))

    def test_stateful_diff_switches_targets_and_handles_dev_null(self):
        candidate = "synthetic-switch-value"
        diff = ("diff --git a/app/a.py b/app/a.py\n--- a/app/a.py\n+++ b/app/a.py\n@@ -1 +1 @@\n"
                f"+password:{candidate}\n"
                "diff --git a/app/b.py b/app/b.py\n--- a/app/b.py\n+++ b/app/b.py\n@@ -1 +1 @@\n"
                f"-password:{candidate}\n"
                "diff --git a/app/new.py b/app/new.py\n--- /dev/null\n+++ b/app/new.py\n@@ -0,0 +1 @@\n"
                f"+password:{candidate}\n").encode()
        origins = _secret_origin_classifications(diff, channel="stderr")["password"]["NON_PLACEHOLDER_16-31_mixed"]["origin"]
        self.assertEqual(origins["diff_target_relative_paths"], ["app/a.py", "app/b.py", "app/new.py"])
        self.assertEqual(origins["diff_change_category"], ["ADD", "REMOVE"])

    def test_malformed_or_unsafe_diff_has_no_path_attribution(self):
        candidate = "synthetic-unsafe-value"
        malformed = ("diff --git a/../bad.py b/../bad.py\n--- a/../bad.py\n+++ b/../bad.py\n"
                     "@@ malformed\n+password:" + candidate + "\n").encode()
        origin = _secret_origin_classifications(malformed, channel="stderr")["password"]["NON_PLACEHOLDER_16-31_mixed"]["origin"]
        self.assertEqual(origin["diff_target_relative_paths"], [])
        self.assertEqual(origin["diff_change_category"], ["UNKNOWN"])
        self.assertEqual(origin["producer_category"], "UNKNOWN")
        self.assertTrue(origin["stderr_only_unknown"])
        direct = _parse_unified_diff_lines(malformed.decode(), workspace_root=Path("/tmp"))
        self.assertEqual(direct, {})

    def test_owned_workspace_match_is_safe_metadata_only(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            candidate = "owned-candidate-0123456789abcdef"
            (root / "owned.py").write_text(f"api_key = '{candidate}'\n", encoding="utf-8")
            result = _secret_origin_classifications(
                f"api-key={candidate}".encode(), channel="stderr",
                workspace_root=root, owned_files=["owned.py"],
            )
            origin = result["api-key"]["NON_PLACEHOLDER_32+_mixed"]["origin"]
            self.assertTrue(origin["owned_workspace_match"])
            self.assertEqual(origin["owned_relative_paths"], ["owned.py"])
            self.assertEqual(origin["source_categories"], ["OWNED_WORKSPACE_CONTENT"])
            self.assertEqual(origin["producer_category"], "UNKNOWN")
            self.assertNotIn(candidate, json.dumps(result))

    def test_generated_code_echo_requires_exact_owned_line_and_remains_blocked(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            candidate = "synthetic-echo-value"
            (root / "owned.txt").write_text(f"api-key={candidate}\n", encoding="utf-8")
            origin = _secret_origin_classifications(
                f"api-key={candidate}".encode(), channel="stderr",
                workspace_root=root, owned_files=["owned.txt"],
            )["api-key"]["NON_PLACEHOLDER_16-31_mixed"]["origin"]
            self.assertEqual(origin["producer_category"], "GENERATED_CODE_ECHO")
            self.assertEqual(origin["framing_category"], ["OWNED_ASSIGNMENT_ECHO"])

    def test_candidate_only_general_owned_value_is_not_source_attribution(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            candidate = "ordinary-general-value"
            (root / "owned.py").write_text(f"collection_key = '{candidate}'\n", encoding="utf-8")
            origin = _secret_origin_classifications(
                f"api-key={candidate}".encode(), channel="stderr",
                workspace_root=root, owned_files=["owned.py"],
            )["api-key"]["NON_PLACEHOLDER_16-31_mixed"]["origin"]
            self.assertFalse(origin["owned_workspace_match"])
            self.assertEqual(origin["owned_relative_paths"], [])
            self.assertEqual(origin["source_categories"], [])
            self.assertEqual(origin["producer_category"], "UNKNOWN")

    def test_punctuation_and_escaping_owned_match_is_exact_not_fuzzy(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            candidate = "synthetic-owned-value"
            (root / "tests").mkdir()
            (root / "tests/test_x.py").write_text(
                f'api_key = "{candidate}"\n', encoding="utf-8")
            matched = _secret_origin_classifications(
                f"api-key='{candidate}';".encode(), channel="stderr",
                workspace_root=root, owned_files=["tests/test_x.py"],
            )["api-key"]["NON_PLACEHOLDER_16-31_other"]["origin"]
            unrelated_result = _secret_origin_classifications(
                f"api-key='{candidate}-different';".encode(), channel="stderr",
                workspace_root=root, owned_files=["tests/test_x.py"],
            )["api-key"]
            unrelated = next(iter(unrelated_result.values()))["origin"]
            self.assertTrue(matched["owned_workspace_match"])
            self.assertEqual(matched["owned_relative_paths"], ["tests/test_x.py"])
            self.assertFalse(unrelated["owned_workspace_match"])

    def test_execution_package_logical_field_and_section_are_safe_metadata(self):
        candidate = "synthetic-task-value"
        result = _secret_origin_classifications(
            f"api-key={candidate}".encode(), channel="stderr",
            prompt=f"Task: api-key={candidate}".encode(),
            prompt_sources={"execution_package.task_context.input": f"api-key={candidate}".encode()},
        )
        origin = result["api-key"]["NON_PLACEHOLDER_16-31_mixed"]["origin"]
        self.assertEqual(origin["prompt_logical_fields"], ["execution_package.task_context.input"])
        self.assertEqual(origin["package_sections"], ["task_context"])
        serialized = json.dumps(result)
        self.assertNotIn(candidate, serialized)
        self.assertNotIn(hashlib.sha256(candidate.encode()).hexdigest(), serialized)

    def test_unrelated_stderr_remains_unknown_and_blocking(self):
        candidate = "synthetic-unrelated"
        classified = _secret_origin_classifications(
            f"api-key={candidate}".encode(), channel="stderr"
        )["api-key"]["NON_PLACEHOLDER_16-31_mixed"]["origin"]
        self.assertTrue(classified["stderr_only_unknown"])
        self.assertEqual(classified["producer_category"], "UNKNOWN")
        self.assertEqual(classified["framing_category"], ["UNFRAMED"])
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); request = self._fixture(root)
            evidence = {"termination":"EXITED", "exit_code":0, "signal":None,
                        "requested_signal":None, "hard_stop":True}
            with patch("runtime.orchestrator.production_worker_executor._run_managed_child",
                       return_value=(_valid_structured_stdout(), f"api-key={candidate}".encode(), evidence)):
                with self.assertRaisesRegex(ProductionWorkerError, "secret-like"):
                    execute_production_worker(request)
            persisted = (root / "out/executor.process.json").read_text()
            self.assertNotIn(candidate, persisted)
            self.assertNotIn(hashlib.sha256(candidate.encode()).hexdigest(), persisted)
            finding = json.loads(persisted)["security_findings"][0]
            self.assertEqual(finding["security_channel"], "STDERR")
            self.assertEqual(finding["structured_field_category"], "UNKNOWN")

    def test_unknown_event_metadata_is_persisted_without_body_or_pass_bypass(self):
        hidden_body = "body-must-not-be-evidence"
        stdout = b"\n".join((
            b'{"type":"thread.started","thread_id":"thread-1"}',
            json.dumps({"type": "future.event", "item": {"content": hidden_body}}).encode(),
        ))
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); request = self._fixture(root)
            evidence = {"termination":"EXITED", "exit_code":0, "signal":None,
                        "requested_signal":None, "hard_stop":True}
            with patch("runtime.orchestrator.production_worker_executor._run_managed_child",
                       return_value=(stdout, b"", evidence)):
                with self.assertRaisesRegex(StructuredEventError, "unknown structured event type"):
                    execute_production_worker(request)
            stored_text = (root / "out/executor.process.json").read_text()
            stored = json.loads(stored_text)["structured_events"]
            self.assertEqual(stored["event_type_counts"], {"thread.started": 1})
            self.assertEqual(stored["unknown_event_count"], 1)
            self.assertEqual(stored["unknown_event_types"], ["future.event"])
            self.assertEqual(stored["event_type_sequence_category"], "INVALID")
            self.assertFalse(stored["terminal_event_present"])
            self.assertNotIn(hidden_body, stored_text)
            self.assertNotIn('"item"', stored_text)
            self.assertNotIn('"content"', stored_text)

    def test_item_status_failure_is_not_persisted_as_unknown_event(self):
        stdout = b"\n".join(json.dumps(value).encode() for value in (
            {"type": "thread.started", "thread_id": "thread-1"},
            {"type": "turn.started"},
            {"type": "item.started", "item": {
                "id": "private-item-id", "type": "command_execution", "status": "failed",
            }},
        ))
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); request = self._fixture(root)
            evidence = {"termination":"EXITED", "exit_code":0, "signal":None,
                        "requested_signal":None, "hard_stop":True}
            with patch("runtime.orchestrator.production_worker_executor._run_managed_child",
                       return_value=(stdout, b"", evidence)):
                with self.assertRaisesRegex(StructuredEventError, "status is incompatible"):
                    execute_production_worker(request)
            stored_text = (root / "out/executor.process.json").read_text()
            stored = json.loads(stored_text)["structured_events"]
            self.assertEqual(stored["structured_failure_stage"], "ITEM_STATUS")
            self.assertEqual(stored["event_type_counts"], {"thread.started": 1, "turn.started": 1})
            self.assertEqual(stored["unknown_event_count"], 0)
            self.assertNotIn("private-item-id", stored_text)

    def test_owned_diff_hardcoded_credential_is_blocked_with_safe_evidence(self):
        candidate = "synthetic-realistic-material-123456"
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); request = self._fixture(root)
            def runner(argv, **kwargs):
                (root / "app").mkdir(); (root / "tests").mkdir()
                (root / "app/x.py").write_text(f"api_key = '{candidate}'\n", encoding="utf-8")
                (root / "tests/test_x.py").write_text("def test_x(): assert True\n", encoding="utf-8")
                subprocess.run(["git", "-C", str(root), "add", "app/x.py", "tests/test_x.py"], check=True)
                subprocess.run(["git", "-C", str(root), "-c", "user.name=T", "-c", "user.email=t@x",
                               "commit", "-qm", "checkpoint"], check=True)
                return subprocess.CompletedProcess(argv, 0, b"", b"")
            with self.assertRaisesRegex(ProductionWorkerError, "OWNED_DIFF_HARDCODED_CREDENTIAL"):
                execute_production_worker(request, executor=runner)
            persisted = json.loads((root / "out/executor.process.json").read_text())
            validation = persisted["owned_diff_security_validation"]
            self.assertEqual(validation["status"], "BLOCK")
            self.assertEqual(validation["findings"][0], {
                "relative_path": "app/x.py", "ast_node_category": "Assign",
                "identifier_category": "api_key", "literal_length_bucket": "32+", "hardcoded": True,
            })
            serialized = json.dumps(validation)
            self.assertNotIn(candidate, serialized)
            self.assertNotIn(hashlib.sha256(candidate.encode()).hexdigest(), serialized)

    def test_normal_deduplicator_ast_has_no_credential_finding(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); (root / "app/services").mkdir(parents=True)
            (root / "app/services/deduplicator.py").write_text(
                "def deduplicate(items):\n    return list(dict.fromkeys(items))\n", encoding="utf-8")
            self.assertEqual(_hardcoded_credential_findings(
                root, ["app/services/deduplicator.py"]), [])

    def test_explicit_secret_interface_with_config_reference_is_allowed(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); request = self._fixture(root)
            request.extra_context["task_capabilities"] = ["secret_handling"]
            (root / "app").mkdir()
            (root / "app/x.py").write_text("api_key = settings.api_key\n", encoding="utf-8")
            self.assertTrue(_task_allows_secret_handling(request))
            self.assertEqual(_hardcoded_credential_findings(root, ["app/x.py"]), [])

    def test_last_message_secret_like_assignment_is_redacted_before_persistence(self):
        candidate = "last-message-secret-0123456789abcdef0"
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); request = self._fixture(root)
            def runner(argv, **kwargs):
                (root / "out" / "executor.last-message.txt").write_text(
                    f"api-key={candidate}", encoding="utf-8"
                )
                (root / "app").mkdir(); (root / "tests").mkdir()
                (root / "app/x.py").write_text("x=1\n")
                (root / "tests/test_x.py").write_text("def test_x(): assert True\n")
                subprocess.run(["git", "-C", str(root), "add", "app/x.py", "tests/test_x.py"], check=True)
                subprocess.run(["git", "-C", str(root), "-c", "user.name=T", "-c", "user.email=t@x",
                                "commit", "-qm", "checkpoint"], check=True)
                return subprocess.CompletedProcess(argv, 0, b"", b"")
            with patch("runtime.orchestrator.production_worker_executor._command",
                       side_effect=lambda *a, **k: {"exit_code": 0, "timeout": False}):
                execute_production_worker(request, executor=runner)
            persisted = (root / "out" / "executor.last-message.txt").read_text(encoding="utf-8")
            self.assertNotIn(candidate, persisted)
            self.assertIn("[REDACTED]", persisted)
    def test_worker_prompt_bounds_child_to_implementation_only(self):
        with tempfile.TemporaryDirectory() as d:
            request = self._fixture(Path(d))
            prompt = _prompt(request, "a" * 40, ["app/x.py"])
            self.assertNotIn("run focused and full tests", prompt)
            self.assertIn("deterministic Harness validator owns those checks", prompt)
            self.assertIn("review, remediation", prompt)
            self.assertIn("exit immediately", prompt)

    def test_mutation_requirement_and_target_are_projected_to_worker_prompt(self):
        with tempfile.TemporaryDirectory() as d:
            request = self._fixture(Path(d))
            request.extra_context.update({"task_effect_requirement": "MUTATION_REQUIRED",
                                          "change_target_count": 2})
            prompt = _prompt(request, "a" * 40, ["app/x.py", "tests/test_x.py"])
            self.assertIn("Task effect requirement: MUTATION_REQUIRED", prompt)
            self.assertIn("Approved change-target count: 2", prompt)
            self.assertIn("a governed WRITE is required", prompt)

    def test_runtime_prompt_artifact_matches_stdin_bytes(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); request = self._fixture(root); captured = {}
            def runner(argv, **kwargs):
                captured["stdin"] = kwargs["input"]
                (root / "app").mkdir(); (root / "tests").mkdir()
                (root / "app/x.py").write_text("x=1\n"); (root / "tests/test_x.py").write_text("def test_x(): assert True\n")
                subprocess.run(["git", "-C", str(root), "add", "app/x.py", "tests/test_x.py"], check=True)
                subprocess.run(["git", "-C", str(root), "-c", "user.name=T", "-c", "user.email=t@x", "commit", "-qm", "checkpoint"], check=True)
                return subprocess.CompletedProcess(argv, 0, b"ok", b"")
            with patch("runtime.orchestrator.production_worker_executor._command", side_effect=lambda *a, **k: {"exit_code":0,"timeout":False}):
                result = execute_production_worker(request, executor=runner)
            prompt = root / "out/executor.prompt.txt"
            self.assertEqual(hashlib.sha256(captured["stdin"]).hexdigest(), (root / "out/executor.prompt.sha256").read_text())
            self.assertEqual(captured["stdin"], prompt.read_bytes())
            self.assertIn("Project/Gate/LV/run/attempt", captured["stdin"].decode())
            self.assertEqual(result["runtime_prompt_sha256"], hashlib.sha256(captured["stdin"]).hexdigest())

    def test_checkpoint_commit_uses_machine_identity_and_isolated_hooks(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); request = self._fixture(root)
            subprocess.run(["git", "-C", str(root), "config", "--unset", "user.name"], check=False)
            subprocess.run(["git", "-C", str(root), "config", "--unset", "user.email"], check=False)
            subprocess.run(["git", "-C", str(root), "config", "commit.gpgSign", "true"], check=True)
            marker = root / "hook-ran"
            hook = root / ".git/hooks/pre-commit"
            hook.write_text(f"#!/bin/sh\ntouch {marker}\nexit 1\n")
            hook.chmod(0o755)
            def runner(argv, **kwargs):
                (root / "app").mkdir(); (root / "tests").mkdir()
                (root / "app/x.py").write_text("x=1\n")
                (root / "tests/test_x.py").write_text("def test_x(): assert True\n")
                return subprocess.CompletedProcess(argv, 0, b"", b"")
            with patch("runtime.orchestrator.production_worker_executor._command", side_effect=lambda *a, **k: {"exit_code":0,"timeout":False}):
                result = execute_production_worker(request, executor=runner)
            author = subprocess.check_output(["git", "-C", str(root), "show", "-s", "--format=%an <%ae>|%cn <%ce>", result["checkpoint_commit"]], text=True).strip()
            self.assertEqual(author, "Global GPT Harness <harness@localhost.invalid>|Global GPT Harness <harness@localhost.invalid>")
            self.assertFalse(marker.exists())
            self.assertFalse(subprocess.check_output(["git", "-C", str(root), "status", "--porcelain"], text=True))
            self.assertEqual(result["checkpoint_commit"], subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip())
    def _fixture(self, root: Path, *, scope=None):
        subprocess.run(["git","init","-q","-b","main",root],check=True)
        subprocess.run(["git","-C",root,"config","user.name","Fixture Worker"],check=True)
        subprocess.run(["git","-C",root,"config","user.email","fixture@example.invalid"],check=True)
        (root/"README.md").write_text("base\n"); (root/".gitignore").write_text(".venv/\nout/\n__pycache__/\n*.pyc\n")
        subprocess.run(["git","-C",root,"add","README.md",".gitignore"],check=True)
        subprocess.run(["git","-C",root,"-c","user.name=T","-c","user.email=t@x","commit","-qm","base"],check=True)
        base=subprocess.check_output(["git","-C",root,"rev-parse","HEAD"],text=True).strip()
        (root/".venv/bin").mkdir(parents=True); (root/".venv/bin/python").write_text(""); (root/".venv/bin/pytest").write_text("")
        task=TaskSlice(thread_id="L",assigned_agent="implementation_agent",
            input="Create app/x.py with function add_one(value) returning value + 1, and tests/test_x.py using unittest to verify 0 becomes 1 and -1 becomes 0.",expected_output="product",
            validation_criteria=["tests/test_x.py passes"],editable_scope=scope or ["app/x.py","tests/test_x.py"],forbidden_scope=[],merge_point="EXIT",output_dir=str(root/"out"))
        return WorkerRequest(str(root),task,{"project_id":"p","gate_id":"g","lv_id":"L","canonical_plan_sha256":"a"*64},
            {"head":base},{"execution_mode":"production","run_id":"r","attempt":3,"approval_event_id":"APR-1",
            "package_manifest_sha256":"b"*64,"execution_backend":"LOCAL_CHILD","allow_local_child_production":True,
                           "source_snapshot":{"source_head":base}})

    def test_manifest_is_actual_not_test_double(self):
        value=production_executor_manifest()
        self.assertEqual(value["asset_id"],EXECUTOR_ID); self.assertTrue(value["production"]); self.assertFalse(value["test_double"])

    def test_durable_production_request_cannot_select_local_child_fallback(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); request = self._fixture(root)
            request.extra_context["run_root"] = str(root / "durable-run")
            with self.assertRaisesRegex(ProductionWorkerError, "LOCAL_CHILD_PRODUCTION_DISABLED"):
                execute_production_worker(request, executor=lambda *a, **k: None)

    def test_actual_executor_commit_is_collected_and_bound(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); request=self._fixture(root)
            def runner(*args,**kwargs):
                (root/"app").mkdir(); (root/"tests").mkdir()
                (root/"app/x.py").write_text("x=1\n"); (root/"tests/test_x.py").write_text("def test_x(): assert True\n")
                subprocess.run(["git","-C",root,"add","app/x.py","tests/test_x.py"],check=True)
                subprocess.run(["git","-C",root,"-c","user.name=T","-c","user.email=t@x","commit","-qm","checkpoint"],check=True)
                return subprocess.CompletedProcess(args[0],0,b"ok",b"")
            ok=lambda root,argv,timeout=900,**kwargs:{"command":argv,"exit_code":0,"timeout":False,"stdout_sha256":"c"*64,"stderr_sha256":"d"*64}
            with patch("runtime.orchestrator.production_worker_executor._command",side_effect=ok):
                result=execute_production_worker(request,executor=runner)
            self.assertEqual(result["attempt"],3); self.assertEqual(result["executor"]["identity"],EXECUTOR_ID)
            self.assertEqual(set(result["changed_files"]),{"app/x.py","tests/test_x.py"})
            self.assertEqual(result["validation_events"], ["VALIDATION_STARTED", "FOCUSED_TEST_COMPLETED", "FULL_REGRESSION_COMPLETED", "WORKER_RESULT_SEALED"])
            self.assertFalse(subprocess.check_output(["git","-C",root,"status","--porcelain"],text=True))

    def test_out_of_scope_commit_is_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); request=self._fixture(root)
            def runner(*args,**kwargs):
                (root/"bad.py").write_text("bad=1\n")
                subprocess.run(["git","-C",root,"add","bad.py"],check=True)
                subprocess.run(["git","-C",root,"-c","user.name=T","-c","user.email=t@x","commit","-qm","bad"],check=True)
                return subprocess.CompletedProcess(args[0],0,b"",b"")
            with self.assertRaisesRegex(ProductionWorkerError,"outside owned scope"):
                execute_production_worker(request,executor=runner)

    def test_failure_and_timeout_are_not_completion(self):
        with tempfile.TemporaryDirectory() as d:
            request=self._fixture(Path(d))
            for result in (subprocess.CompletedProcess([],1,b"",b"failed"),):
                with self.subTest(result=result.returncode), self.assertRaises(ProductionWorkerError):
                    execute_production_worker(request,executor=lambda *a,**k:result)

    def test_timeout_terminates_process_group_and_records_signal(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); cancel=root/"cancel"
            stdout,stderr,evidence=_run_managed_child(["python3","-c","import time; time.sleep(30)"],root=root,prompt=b"",timeout=0,cancel_path=cancel,grace_period=0.05)
            self.assertEqual(evidence["termination"],"TIMED_OUT")
            self.assertIn(evidence["requested_signal"],{"SIGTERM","SIGKILL"})
            self.assertIsNotNone(evidence["signal"])

    def test_large_stdout_and_stderr_are_drained_without_pipe_deadlock(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); cancel = root / "cancel"
            script = "import sys; data='x'*262144; sys.stdout.write(data); sys.stderr.write(data)"
            stdout, stderr, evidence = _run_managed_child(["python3", "-c", script], root=root,
                                                           prompt=b"", timeout=10, cancel_path=cancel)
            self.assertEqual(evidence["termination"], "EXITED")
            self.assertEqual(len(stdout), 262144)
            self.assertEqual(len(stderr), 262144)
            self.assertEqual(evidence["stdout_sha256"], __import__("hashlib").sha256(stdout).hexdigest())
            self.assertEqual(evidence["stderr_sha256"], __import__("hashlib").sha256(stderr).hexdigest())

    def test_large_output_timeout_and_cancel_preserve_primary_termination(self):
        for cancelled in (False, True):
            with tempfile.TemporaryDirectory() as d:
                root = Path(d); cancel = root / "cancel"
                if cancelled:
                    cancel.write_text("cancel")
                script = "import sys,time; data='y'*262144; sys.stdout.write(data); sys.stderr.write(data); sys.stdout.flush(); sys.stderr.flush(); time.sleep(30)"
                _, _, evidence = _run_managed_child(["python3", "-c", script], root=root,
                                                     prompt=b"", timeout=30 if cancelled else 0,
                                                     cancel_path=cancel, grace_period=0.05)
                self.assertEqual(evidence["termination"], "CANCELLED" if cancelled else "TIMED_OUT")

    def test_large_output_secret_pattern_is_detected_without_raw_output_evidence(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); cancel = root / "cancel"
            script = "import sys; sys.stdout.write('a'*200000 + 'authorization=hidden-value' + 'b'*200000)"
            stdout, stderr, evidence = _run_managed_child(["python3", "-c", script], root=root,
                                                           prompt=b"", timeout=10, cancel_path=cancel)
            self.assertEqual(evidence["termination"], "EXITED")
            self.assertTrue(__import__("re").search(r"authorization=\S+", stdout.decode()))
            self.assertEqual(evidence["stdout_sha256"], __import__("hashlib").sha256(stdout).hexdigest())
            self.assertNotIn("hidden-value", json.dumps(evidence))

    def test_cancel_terminates_process_group_and_excludes_completion(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); cancel=root/"cancel"; cancel.write_text("cancel\n")
            _,_,evidence=_run_managed_child(["python3","-c","import time; time.sleep(30)"],root=root,prompt=b"",timeout=30,cancel_path=cancel,grace_period=0.05)
            self.assertEqual(evidence["termination"],"CANCELLED")
            self.assertTrue(evidence["hard_stop"])
            self.assertIsNotNone(evidence["ended_at"])

    def test_timeout_with_secret_output_keeps_timeout_primary_and_redacts_finding(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); request = self._fixture(root)
            evidence = {"termination":"TIMED_OUT", "exit_code":None, "signal":15,
                        "requested_signal":"SIGTERM", "hard_stop":True}
            with patch("runtime.orchestrator.production_worker_executor._run_managed_child",
                       return_value=(b"token=do-not-print", b"", evidence)):
                with self.assertRaisesRegex(ProductionWorkerError, "WORKER_TIMEOUT"):
                    execute_production_worker(request)
            stored = json.loads((root / "out/executor.process.json").read_text())
            self.assertTrue(stored["secret_like_output_detected"])
            self.assertEqual(stored["secret_like_output_channels"], ["stdout"])
            self.assertEqual(stored["secret_like_output_kinds"], {"stdout": {"token": 1}, "stderr": {}})
            self.assertEqual(stored["secret_like_output_classifications"]["stdout"]["token"].get("NON_PLACEHOLDER_1-15_mixed"), 1)
            self.assertNotIn("do-not-print", (root / "out/executor.process.json").read_text())

    def test_structured_content_attribution_is_typed_and_raw_free(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); request = self._fixture(root)
            evidence = {"termination":"EXITED", "exit_code":0, "signal":None, "requested_signal":None, "hard_stop":True}
            candidate = "synthetic-secret-value"
            with patch("runtime.orchestrator.production_worker_executor._run_managed_child",
                       return_value=(_valid_structured_stdout(agent_text=f"api-key={candidate}"), b"", evidence)):
                with self.assertRaisesRegex(ProductionWorkerError, "secret-like"):
                    execute_production_worker(request)
            stored = json.loads((root / "out/executor.process.json").read_text())
            finding = stored["structured_events"]["structured_security_findings"][0]
            self.assertEqual(finding["security_channel"], "STRUCTURED_JSONL")
            self.assertEqual(finding["structured_field_category"], "AGENT_MESSAGE")
            self.assertEqual(finding["event_type"], "item.completed")
            self.assertEqual(finding["item_type"], "agent_message")
            self.assertEqual(stored["security_source_channel"], "WORKER")
            self.assertEqual(stored["security_value_origin"], "MODEL_OUTPUT")
            self.assertEqual(stored["security_detector_family"], "KEY_MATERIAL")
            self.assertEqual(stored["security_event_stage"], "EVENT_VALIDATION")
            self.assertEqual(stored["worker_process_spawn_reached"], "YES")
            self.assertEqual(stored["worker_process_started"], "YES")
            self.assertEqual(stored["worker_result_boundary_reached"], "NO")
            self.assertEqual(stored["independent_verification_reached"], "NO")
            self.assertNotIn(candidate, json.dumps(stored))
            self.assertNotIn("message-1", json.dumps(stored))

    def test_structured_placeholder_secret_like_content_is_still_blocked(self):
        for value, expected in (("none", "PLACEHOLDER_LITERAL"), ("[REDACTED]", "REDACTED_LITERAL"), ("******", "REDACTED_LITERAL")):
            with tempfile.TemporaryDirectory() as d:
                root = Path(d); request = self._fixture(root)
                evidence = {"termination":"EXITED", "exit_code":0, "signal":None, "requested_signal":None, "hard_stop":True}
                with patch("runtime.orchestrator.production_worker_executor._run_managed_child",
                           return_value=(_valid_structured_stdout(agent_text=f"api-key={value}"), b"", evidence)):
                    with self.assertRaisesRegex(ProductionWorkerError, "secret-like"):
                        execute_production_worker(request)
                stored = json.loads((root / "out/executor.process.json").read_text())
                self.assertEqual(stored["security_stage_status"]["JSONL_VALID"], "BLOCK")
                self.assertEqual(stored["structured_events"]["structured_security_findings"][0]["secret_kind"], "api-key")
                self.assertNotIn(value, json.dumps(stored))

    def test_nonzero_and_cancelled_secret_output_keep_process_failure_primary(self):
        for termination, expected in (("CANCELLED", "WORKER_CANCELLED"), ("EXITED", "WORKER_PROCESS_FAILURE")):
            with tempfile.TemporaryDirectory() as d:
                root = Path(d); request = self._fixture(root)
                evidence = {"termination":termination, "exit_code":(1 if termination == "EXITED" else None),
                            "signal":15 if termination == "CANCELLED" else None,
                            "requested_signal":"SIGTERM" if termination == "CANCELLED" else None, "hard_stop":True}
                with patch("runtime.orchestrator.production_worker_executor._run_managed_child",
                           return_value=(b"authorization=hidden", b"", evidence)):
                    with self.assertRaisesRegex(ProductionWorkerError, expected):
                        execute_production_worker(request)
                stored = json.loads((root / "out/executor.process.json").read_text())
                self.assertTrue(stored["secret_like_output_detected"])

    @unittest.skipUnless(os.getenv("HARNESS_RUN_ACTUAL_CODEX_FIXTURE") == "1", "actual Codex fixture is opt-in")
    def test_actual_codex_child_implements_tests_and_commits(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); request=self._fixture(root)
            python=root/".venv/bin/python"; pytest=root/".venv/bin/pytest"
            python.write_text("#!/bin/sh\nexec python3 \"$@\"\n"); pytest.write_text("#!/bin/sh\nexec python3 -m unittest discover -s tests -q\n")
            python.chmod(0o755); pytest.chmod(0o755)
            result=execute_production_worker(request,timeout=300)
            self.assertEqual(result["status"],"completed")
            self.assertEqual(result["executor"]["identity"],EXECUTOR_ID)
            self.assertTrue(result["checkpoint_commit"])
