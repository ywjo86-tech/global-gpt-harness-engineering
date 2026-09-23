import dataclasses
import unittest

from tests.capability_lifecycle_fixtures import active_record
from runtime.orchestrator.capability_lifecycle import (
    CapabilityLifecycleError,
    transition_capability_lifecycle,
)


class CapabilityLifecycleTests(unittest.TestCase):
    def test_direct_retire_with_active_dependencies_is_rejected(self):
        record = dataclasses.replace(
            active_record(), active_dependency_ids=("TASKEXEC-1", "TASKEXEC-2")
        )
        with self.assertRaisesRegex(CapabilityLifecycleError, "active dependencies"):
            transition_capability_lifecycle(record, "RETIRED", ("evidence:retire",))

    def test_direct_retire_without_dependencies_requires_evidence(self):
        with self.assertRaisesRegex(CapabilityLifecycleError, "retire evidence"):
            transition_capability_lifecycle(active_record(), "RETIRED", ())


if __name__ == "__main__":
    unittest.main()
