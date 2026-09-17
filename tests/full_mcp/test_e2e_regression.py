from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from mcp.client.stdio import StdioServerParameters

from runtime.orchestrator.execution_modes import HYBRID, NVIDIA
from runtime.orchestrator.full_mcp_backend_adapter import AdapterToolCall, FullMCPBackendAdapter
from runtime.orchestrator.provider_router import CODEX_PROVIDER, MANUAL_PROVIDER, NVIDIA_PROVIDER, route_provider
from tests.full_mcp.test_adapter_contract import gateway_request, initialize_repo, invocation_fixture


class ProviderHybridRegressionTests(unittest.TestCase):
    def test_provider_router_and_fallback_semantics_are_preserved(self) -> None:
        read_only = route_provider(HYBRID, ("read_only", "reasoning", "evidence_analysis"))
        self.assertEqual(read_only.provider, NVIDIA_PROVIDER)
        self.assertTrue(read_only.eligible)
        state = route_provider(HYBRID, ("filesystem_write", "implementation", "test"))
        self.assertEqual(state.provider, CODEX_PROVIDER)
        self.assertTrue(state.eligible)
        rejected = route_provider(NVIDIA, ("filesystem_write",))
        self.assertEqual(rejected.provider, MANUAL_PROVIDER)
        self.assertFalse(rejected.eligible)
        self.assertEqual(rejected.reason_code, "nvidia_rejects_state_changing")


class RepresentativeLifecycleTests(unittest.TestCase):
    def test_read_change_execute_validate_restore_returns_to_baseline(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            initialize_repo(root)
            target = root / "owned/base.txt"
            target.write_text("base\n", encoding="utf-8")
            subprocess.check_call(["git", "add", "owned/base.txt"], cwd=root)
            subprocess.check_call(["git", "commit", "-qm", "owned baseline"], cwd=root)
            baseline = target.read_bytes()
            req = gateway_request(root)
            context, contracts, _ = invocation_fixture(root, req["request_digest"])
            repo = Path(__file__).resolve().parents[2]
            def params_factory(ctx, active_contracts):
                del ctx, active_contracts
                return StdioServerParameters(
                    command=sys.executable,
                    args=["-m", "tests.full_mcp.test_adapter_contract", "--serve", root.as_posix(), req["request_digest"]],
                    cwd=repo,
                    env=dict(os.environ),
                )
            adapter = FullMCPBackendAdapter(
                context=context, contracts=contracts, server_params_factory=params_factory,
                tool_calls=(
                    AdapterToolCall("filesystem_read", {"path": "owned/base.txt"}, "e2e-read-before"),
                    AdapterToolCall("filesystem_write", {"path": "owned/base.txt", "content": "changed\n", "expected_sha256": hashlib.sha256(baseline).hexdigest()}, "e2e-write"),
                    AdapterToolCall("shell_execute", {"argv": [sys.executable, "-c", "from pathlib import Path; assert Path('owned/base.txt').read_text() == 'changed\\n'"], "cwd": ".", "timeout_seconds": 10}, "e2e-execute"),
                    AdapterToolCall("validate", {"operation_request_id": "e2e-execute", "expectations": ["RESULT_PRESENT", "AUDIT_PRESENT", "EXIT_ZERO", "NO_SECURITY_BLOCK"]}, "e2e-validate"),
                    AdapterToolCall("git_restore", {"paths": ["owned/base.txt"], "source_ref": "HEAD"}, "e2e-restore"),
                    AdapterToolCall("filesystem_read", {"path": "owned/base.txt"}, "e2e-read-after"),
                ),
            )
            outcome = adapter(req, prompt=b"approved", workspace_root=root, last_message=root/"last", timeout=30, cancel_path=root/"cancel")
            self.assertEqual(outcome["execution_status"], "COMPLETED")
            self.assertEqual(outcome["structured_event_metadata"]["tool_call_count"], 6)
            self.assertEqual(target.read_bytes(), baseline)
            dirty = subprocess.check_output(["git", "status", "--porcelain", "--", "owned/base.txt"], cwd=root, text=True)
            self.assertEqual(dirty, "")


class GovernanceIsolationTests(unittest.TestCase):
    def test_worktree_preserved_boundaries_and_gate_order(self) -> None:
        repo = Path(__file__).resolve().parents[2]
        canonical = Path("/home/ywjo/AI-Workspace/project-workspace/global-gpt-harness-engineering")
        branch = subprocess.check_output(["git", "branch", "--show-current"], cwd=repo, text=True).strip()
        self.assertEqual(branch, "preph5mprf/multi-provider-foundation")
        self.assertEqual(
            subprocess.call(["git", "merge-base", "--is-ancestor",
                             "0bdfad12c438f4f101d3fdeafda9daac8d5069b4", "HEAD"], cwd=repo),
            0,
        )
        self.assertEqual(
            subprocess.call(["git", "merge-base", "--is-ancestor",
                             "0848dab7596f59a7eae98f223b47636bad27b4bd", "HEAD"], cwd=repo),
            0,
        )
        self.assertEqual(
            subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=canonical, text=True).strip(),
            "fffe93a330d59c8dd91f60abde2bf4c53cd0542e",
        )
        prefinal = repo / "_workspace/full-mcp/20260916T123217Z-bd92159d/attempts/2/indexes/PREFINAL.json"
        self.assertTrue(prefinal.is_file())
        approved_prefinal = Path(
            "/home/ywjo/AI-Workspace/project-workspace/.worktrees/GH-FULL-MCP-PH4/UPGRADE-003/"
            "_workspace/full-mcp/20260916T123217Z-bd92159d/attempts/2/indexes/PREFINAL.json"
        )
        self.assertEqual(hashlib.sha256(prefinal.read_bytes()).hexdigest(),
                         hashlib.sha256(approved_prefinal.read_bytes()).hexdigest())



if __name__ == "__main__":
    unittest.main()
