from __future__ import annotations

import unittest

from runtime.orchestrator.host_inspection_contract import (
    HOST_INSPECTION_OPERATIONS,
    HostInspectionContractError,
    HostInspectionRequestV1,
    HostInspectionResultV1,
)


class HostInspectionContractTests(unittest.TestCase):
    @staticmethod
    def payload(**changes):
        value = {
            "schema_version": "orchestration.host-inspection-request.v1",
            "request_id": "INSP-1",
            "correlation_id": "CORR-1",
            "project_alias": "global-gpt-harness-engineering",
            "operation": "git.status",
            "arguments": {},
            "state_change_required": False,
        }
        value.update(changes)
        return value

    def test_valid_request_round_trips_and_has_digest(self):
        request = HostInspectionRequestV1.from_mapping(self.payload())
        self.assertEqual(request.operation, "git.status")
        self.assertEqual(request.to_dict(), self.payload())
        self.assertEqual(len(request.request_digest), 64)
    def test_closed_operation_registry_rejects_shell_and_unknown_operation(self):
        self.assertIn("git.status", HOST_INSPECTION_OPERATIONS)
        self.assertNotIn("shell.execute", HOST_INSPECTION_OPERATIONS)
        for operation in ("shell.execute", "filesystem.write", "git.commit", "unknown"):
            with self.subTest(operation=operation):
                with self.assertRaisesRegex(HostInspectionContractError, "operation"):
                    HostInspectionRequestV1.from_mapping(self.payload(operation=operation))

    def test_unknown_fields_and_state_change_fail_closed(self):
        with self.assertRaisesRegex(HostInspectionContractError, "fields"):
            HostInspectionRequestV1.from_mapping({**self.payload(), "extra": "x"})
        with self.assertRaisesRegex(HostInspectionContractError, "state change"):
            HostInspectionRequestV1.from_mapping(self.payload(state_change_required=True))

    def test_forbidden_control_material_is_rejected_recursively(self):
        forbidden = (
            {"root": "/tmp"},
            {"path": "/etc/passwd"},
            {"provider": "nvidia"},
            {"model": "x"},
            {"argv": ["git", "status"]},
            {"env": {"TOKEN": "secret"}},
            {"options": {"executable": "bash"}},
        )
        for arguments in forbidden:
            with self.subTest(arguments=arguments):
                with self.assertRaisesRegex(HostInspectionContractError, "arguments"):
                    HostInspectionRequestV1.from_mapping(self.payload(arguments=arguments))

    def test_relative_search_root_is_allowed_but_absolute_root_is_blocked(self):
        request = HostInspectionRequestV1.from_mapping(
            self.payload(operation="filesystem.search", arguments={"root": ".", "query": "x"})
        )
        self.assertEqual(request.arguments["root"], ".")
        with self.assertRaisesRegex(HostInspectionContractError, "absolute"):
            HostInspectionRequestV1.from_mapping(
                self.payload(operation="filesystem.search", arguments={"root": "/tmp", "query": "x"})
            )

    def test_result_binds_exact_request_and_is_mapping_only(self):
        request = HostInspectionRequestV1.from_mapping(self.payload(operation="git.branch"))
        result = HostInspectionResultV1.ok(request, {"branch": "main"})
        self.assertEqual(result.status, "OK")
        self.assertEqual(result.request_digest, request.request_digest)
        self.assertEqual(result.data, {"branch": "main"})
        self.assertEqual(result.to_dict()["operation"], "git.branch")
        with self.assertRaisesRegex(HostInspectionContractError, "result data"):
            HostInspectionResultV1.ok(request, ["not", "a", "mapping"])

    def test_result_rejects_unknown_status_and_invalid_request_digest(self):
        request = HostInspectionRequestV1.from_mapping(self.payload())
        with self.assertRaisesRegex(HostInspectionContractError, "status"):
            HostInspectionResultV1(
                schema_version="orchestration.host-inspection-result.v1",
                request_id=request.request_id,
                correlation_id=request.correlation_id,
                project_alias=request.project_alias,
                operation=request.operation,
                request_digest=request.request_digest,
                status="MAYBE",
                data={},
                error_code="",
            )


if __name__ == "__main__":
    unittest.main()
