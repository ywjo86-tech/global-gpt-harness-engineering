import json
import os
import subprocess
import unittest

from runtime.orchestrator.codex_dynamic_transport import (
    CodexAppServerAdapter, ToolRequestEnvelope, ToolResultEnvelope,
    TransportCompatibility, TransportError, validate_closed_registry,
)


TOOLS = [{
    "type": "function", "name": "PROJECT_FILE_READ",
    "description": "bounded read",
    "inputSchema": {"type": "object", "properties": {"owned_file_id": {"type": "string"}},
                    "required": ["owned_file_id"], "additionalProperties": False},
}]


class _Pipe:
    def __init__(self, lines=None): self.lines = list(lines or []); self.writes = []
    def write(self, value): self.writes.append(value)
    def flush(self): pass
    def readline(self): return self.lines.pop(0) if self.lines else ""


class _Process:
    def __init__(self, lines):
        self.stdin = _Pipe(); self.stdout = _Pipe(lines); self.stderr = _Pipe(); self.returncode = None
    def poll(self): return self.returncode
    def terminate(self): self.returncode = 0
    def wait(self, timeout=None): return self.returncode
    def kill(self): self.returncode = -9


class CodexDynamicTransportTests(unittest.TestCase):
    def test_compatibility_is_exact_and_fail_closed(self):
        good = CodexAppServerAdapter(version_probe=lambda: "0.150.1")
        self.assertTrue(good.check_compatibility().compatible)
        bad = CodexAppServerAdapter(version_probe=lambda: "0.151.0")
        with self.assertRaisesRegex(TransportError, "COMPATIBILITY_BLOCK"):
            bad.check_compatibility()
        missing = CodexAppServerAdapter(version_probe=lambda: "0.150.1", schema_probe=lambda: {
            "experimental_api": True, "dynamic_tool_request": False, "dynamic_tool_response": True,
            "empty_environment_supported": True, "schema_verified": True})
        with self.assertRaises(TransportError): missing.check_compatibility()

    def test_closed_registry_rejects_unknown_shape_and_duplicates(self):
        self.assertEqual(validate_closed_registry(TOOLS), ("PROJECT_FILE_READ",))
        with self.assertRaises(TransportError): validate_closed_registry([])
        with self.assertRaises(TransportError): validate_closed_registry(TOOLS + TOOLS)
        opened = [{**TOOLS[0], "inputSchema": {"type": "object"}}]
        with self.assertRaises(TransportError): validate_closed_registry(opened)

    def test_adapter_uses_empty_environments_and_returns_bounded_broker_result(self):
        lines = [
            json.dumps({"jsonrpc": "2.0", "id": 1, "result": {}}) + "\n",
            json.dumps({"jsonrpc": "2.0", "id": 2, "result": {"thread": {"id": "thread-1"}}}) + "\n",
            json.dumps({"jsonrpc": "2.0", "id": 3, "result": {"turn": {"id": "turn-1"}}}) + "\n",
            json.dumps({"jsonrpc": "2.0", "id": 80, "method": "item/tool/call", "params": {
                "tool": "PROJECT_FILE_READ", "callId": "call-1", "arguments": {"owned_file_id": "FILE_1"}}}) + "\n",
            json.dumps({"jsonrpc": "2.0", "method": "turn/completed", "params": {}}) + "\n",
        ]
        process = _Process(lines)
        seen = []
        adapter = CodexAppServerAdapter(process_factory=lambda *a, **k: process,
                                        version_probe=lambda: "0.150.1")
        result = adapter.run_turn(prompt="bounded", dynamic_tools=TOOLS,
            tool_handler=lambda envelope: seen.append(envelope) or ToolResultEnvelope(
                "COMPLETED", "PRESENT", "PASS", {"status": "COMPLETED"}))
        self.assertEqual(result["completion"], "COMPLETED")
        self.assertEqual(result["registry"]["native_command_runtime_count"], 0)
        self.assertEqual(len(seen), 1)
        writes = [json.loads(item) for item in process.stdin.writes]
        thread_start = next(item for item in writes if item.get("method") == "thread/start")
        turn_start = next(item for item in writes if item.get("method") == "turn/start")
        self.assertTrue(thread_start["params"]["experimentalRawEvents"])
        self.assertEqual(thread_start["params"]["environments"], [])
        self.assertEqual(turn_start["params"]["environments"], [])
        tool_response = next(item for item in writes if item.get("id") == 80)
        self.assertTrue(tool_response["result"]["success"])
        self.assertFalse(any("command" in json.dumps(item).lower() for item in writes))

    def test_broker_failure_is_returned_as_block_without_native_fallback(self):
        lines = [
            json.dumps({"jsonrpc": "2.0", "id": 1, "result": {}}) + "\n",
            json.dumps({"jsonrpc": "2.0", "id": 2, "result": {"thread": {"id": "thread-1"}}}) + "\n",
            json.dumps({"jsonrpc": "2.0", "id": 3, "result": {"turn": {"id": "turn-1"}}}) + "\n",
            json.dumps({"jsonrpc": "2.0", "id": 90, "method": "item/tool/call", "params": {
                "tool": "PROJECT_FILE_READ", "callId": "call-2", "arguments": {}}}) + "\n",
        ]
        process = _Process(lines)
        adapter = CodexAppServerAdapter(process_factory=lambda *a, **k: process,
                                        version_probe=lambda: "0.150.1")
        result = adapter.run_turn(prompt="bounded", dynamic_tools=TOOLS,
                                  tool_handler=lambda _: (_ for _ in ()).throw(TransportError("BLOCK")))
        self.assertEqual(result["completion"], "BROKER_BLOCKED")
        self.assertEqual(result["broker_block"], {
            "stage": "HANDLE", "error_class": "TransportError",
            "operation_class_id": "PROJECT_FILE_READ"})
        self.assertNotIn("BLOCK", json.dumps(result["broker_block"]))
        response = next(json.loads(item) for item in process.stdin.writes if json.loads(item).get("id") == 90)
        self.assertEqual(response["error"]["message"], "BROKER_BLOCK")

    def test_malformed_tool_request_reports_only_safe_normalization_class(self):
        lines = [
            json.dumps({"jsonrpc": "2.0", "id": 1, "result": {}}) + "\n",
            json.dumps({"jsonrpc": "2.0", "id": 2, "result": {"thread": {"id": "thread-1"}}}) + "\n",
            json.dumps({"jsonrpc": "2.0", "id": 3, "result": {"turn": {"id": "turn-1"}}}) + "\n",
            json.dumps({"jsonrpc": "2.0", "id": 91, "method": "item/tool/call", "params": {
                "tool": "PROJECT_FILE_READ", "callId": "call-3", "arguments": "secret raw value"}}) + "\n",
        ]
        process = _Process(lines)
        adapter = CodexAppServerAdapter(process_factory=lambda *a, **k: process,
                                        version_probe=lambda: "0.150.1")
        result = adapter.run_turn(prompt="bounded", dynamic_tools=TOOLS,
                                  tool_handler=lambda _: self.fail("handler must not run"))
        self.assertEqual(result["broker_block"], {
            "stage": "NORMALIZE", "error_class": "TransportError",
            "operation_class_id": "UNKNOWN"})
        self.assertNotIn("secret raw value", json.dumps(result))

    def test_protocol_result_marks_noncompleted_result_unsuccessful(self):
        response = CodexAppServerAdapter.protocol_result(ToolResultEnvelope(
            "BLOCKED", "ABSENT", "PASS", {"status": "BLOCKED"}))
        self.assertFalse(response["success"])

    @unittest.skipUnless(os.environ.get("HARNESS_RUN_ACTUAL_CODEX_TRANSPORT") == "1",
                         "actual installed Codex protocol test is opt-in")
    def test_installed_codex_01501_actual_dynamic_transport(self):
        calls = []
        result = CodexAppServerAdapter().run_turn(
            prompt="Use PROJECT_FILE_READ exactly once, then finish without any other tool.",
            dynamic_tools=TOOLS,
            tool_handler=lambda envelope: calls.append(envelope) or ToolResultEnvelope(
                "COMPLETED", "PRESENT", "PASS", {"status": "COMPLETED"}),
            worker_task_id="TASK-4A-08", worker_action_id="ACTUAL_PROTOCOL_TEST")
        self.assertEqual(result["completion"], "COMPLETED")
        self.assertEqual(len(calls), 1)
        self.assertEqual(result["registry"]["native_command_runtime_count"], 0)
        self.assertEqual(result["registry"]["native_file_runtime_count"], 0)
        self.assertEqual(result["registry"]["direct_mcp_effect_source_count"], 0)


if __name__ == "__main__": unittest.main()
