from __future__ import annotations

import unittest

from tests.capability_lifecycle_fixtures import active_record

from runtime.orchestrator.capability_lifecycle_projection import (
    CapabilityLifecycleProjectionV1,
    project_capability_lifecycle,
)


class CapabilityLifecycleProjectionTests(unittest.TestCase):

    def test_lifecycle_projection_contains_bounded_operational_identity(self):
        record = active_record()

        projection = project_capability_lifecycle(record)

        self.assertIsInstance(
            projection,
            CapabilityLifecycleProjectionV1,
        )

        payload = projection.to_dict()

        self.assertEqual(
            payload["contract_id"],
            record.contract.contract_id,
        )
        self.assertEqual(
            payload["contract_version"],
            record.contract.contract_version,
        )
        self.assertEqual(
            payload["endpoint_version"],
            record.contract.endpoint_version,
        )
        self.assertEqual(
            payload["activation_epoch"],
            record.contract.activation_epoch,
        )
        self.assertEqual(payload["state"], "ACTIVE")
        self.assertEqual(
            payload["active_dependency_count"],
            record.active_dependency_count,
        )

    def test_lifecycle_projection_contains_no_assignment_or_credentials(self):
        projection = project_capability_lifecycle(
            active_record()
        )

        payload = projection.to_dict()
        rendered = repr(payload).lower()

        for forbidden in (
            "final_assignee",
            "provider_ref",
            "model_ref",
            "credential",
            "access_token",
            "secret",
        ):
            self.assertNotIn(forbidden, rendered)

    def test_projection_is_read_only_snapshot(self):
        record = active_record()
        before = record

        projection = project_capability_lifecycle(record)

        self.assertEqual(record, before)
        self.assertEqual(
            projection.active_dependency_count,
            record.active_dependency_count,
        )


if __name__ == "__main__":
    unittest.main()
