from __future__ import annotations

import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TRANSPORT_ROOT = ROOT / "runtime" / "operator_transport"
ORCHESTRATOR_ROOT = ROOT / "runtime" / "orchestrator"
DEPLOY_ROOT = ROOT / "deploy" / "operator-control-plane-v2"

OCP_ORCHESTRATOR_FILES = (
    ORCHESTRATOR_ROOT / "remote_operator_envelope.py",
    ORCHESTRATOR_ROOT / "remote_operator_receipt.py",
    ORCHESTRATOR_ROOT / "remote_operator_outbox.py",
    ORCHESTRATOR_ROOT / "remote_operator_ingress.py",
    ORCHESTRATOR_ROOT / "remote_operator_transport.py",
    ORCHESTRATOR_ROOT / "remote_operator_service.py",
    ORCHESTRATOR_ROOT / "operator_console_projection.py",
)


def _imports_and_calls(path: Path) -> tuple[set[str], set[str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imports: set[str] = set()
    calls: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imports.add(node.module or "")
        elif isinstance(node, ast.Call):
            fn = node.func
            if isinstance(fn, ast.Name):
                calls.add(fn.id)
            elif isinstance(fn, ast.Attribute):
                calls.add(fn.attr)
    return imports, calls


class OCPv2AuthorityNegativeSpaceTests(unittest.TestCase):
    def test_transport_and_service_have_no_direct_execution_or_broker_authority(self):
        targets = tuple(sorted(TRANSPORT_ROOT.glob("*.py"))) + (
            ORCHESTRATOR_ROOT / "remote_operator_service.py",
            ORCHESTRATOR_ROOT / "operator_console_projection.py",
            ORCHESTRATOR_ROOT / "remote_operator_transport.py",
        )
        forbidden_imports = {
            "subprocess",
            "runtime.orchestrator.provider_router",
            "runtime.orchestrator.production_worker_executor",
            "runtime.orchestrator.runtime_migration_handoff",
            "runtime.full_mcp",
        }
        forbidden_calls = {
            "system",
            "popen",
            "Popen",
            "run",
            "check_call",
            "check_output",
            "SingleToolBroker",
        }
        violations = []
        for path in targets:
            imports, calls = _imports_and_calls(path)
            bad_imports = sorted(
                item for item in imports
                if item in forbidden_imports or item.startswith("runtime.full_mcp.")
            )
            bad_calls = sorted(calls & forbidden_calls)
            text = path.read_text(encoding="utf-8")
            if "SingleToolBroker" in text:
                bad_calls.append("SingleToolBroker")
            if bad_imports or bad_calls:
                violations.append((path.name, bad_imports, sorted(set(bad_calls))))
        self.assertEqual(violations, [])

    def test_only_ingress_may_reference_migration_api_and_never_edits_migration_files_directly(self):
        migration_refs = []
        direct_write_violations = []
        for path in OCP_ORCHESTRATOR_FILES:
            if not path.exists():
                continue
            imports, calls = _imports_and_calls(path)
            if any("runtime_migration_handoff" in item for item in imports):
                migration_refs.append(path.name)
            if path.name == "remote_operator_ingress.py":
                forbidden_writes = {"write_text", "write_bytes", "replace", "rename", "unlink"}
                bad = sorted(calls & forbidden_writes)
                if bad:
                    direct_write_violations.append((path.name, bad))
        self.assertEqual(migration_refs, ["remote_operator_ingress.py"])
        self.assertEqual(direct_write_violations, [])

    def test_provider_router_remains_the_only_provider_model_selection_authority(self):
        violations = []
        for path in tuple(sorted(TRANSPORT_ROOT.glob("*.py"))) + OCP_ORCHESTRATOR_FILES:
            if not path.exists():
                continue
            imports, calls = _imports_and_calls(path)
            bad_imports = sorted(item for item in imports if "provider_router" in item)
            bad_calls = sorted(
                call for call in calls
                if call in {"select_provider", "select_model", "resolve_provider", "route_provider"}
            )
            if bad_imports or bad_calls:
                violations.append((path.name, bad_imports, bad_calls))
        self.assertEqual(violations, [])

    def test_systemd_install_authority_exists_only_in_explicit_bootstrap_package(self):
        violations = []
        for path in tuple(sorted(TRANSPORT_ROOT.glob("*.py"))) + OCP_ORCHESTRATOR_FILES:
            if not path.exists():
                continue
            text = path.read_text(encoding="utf-8").lower()
            if "systemctl" in text or "daemon-reload" in text:
                violations.append(path.name)
        self.assertEqual(violations, [])
        self.assertTrue((DEPLOY_ROOT / "bootstrap.py").exists())

    def test_public_source_repository_is_explicitly_rejected_not_defaulted(self):
        rest = (TRANSPORT_ROOT / "github_rest_client.py").read_text(encoding="utf-8")
        adapter = (TRANSPORT_ROOT / "github_control_adapter.py").read_text(encoding="utf-8")
        example = (DEPLOY_ROOT / "ocpv2.example.env").read_text(encoding="utf-8")
        self.assertIn("PUBLIC_SOURCE_REPOSITORY_ID = 1254385549", rest)
        self.assertIn("public source repository cannot", rest.lower())
        self.assertIn("public source repository cannot", adapter.lower())
        self.assertNotIn("1254385549", example)


if __name__ == "__main__":
    unittest.main()
