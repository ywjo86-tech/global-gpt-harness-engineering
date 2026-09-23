import tempfile
import unittest
from pathlib import Path

from tests.capability_lifecycle_fixtures import active_record
from runtime.orchestrator.capability_lifecycle_store import (
    CapabilityLifecycleStore,
    CapabilityLifecycleStoreError,
)


class CapabilityLifecycleDrainTests(unittest.TestCase):
    def test_disable_new_assignment_blocks_new_lease_but_preserves_existing(self):
        with tempfile.TemporaryDirectory() as temporary:
            store = CapabilityLifecycleStore(Path(temporary))
            store.put(active_record())
            store.acquire_dependency("cap:ui-design:1", "TASKEXEC-1")
            drained = store.begin_drain("cap:ui-design:1", evidence_ref="evidence:drain")
            self.assertEqual(drained.state, "DRAINING")
            with self.assertRaisesRegex(CapabilityLifecycleStoreError, "new assignment disabled"):
                store.acquire_dependency("cap:ui-design:1", "TASKEXEC-2")
            store.release_dependency("cap:ui-design:1", "TASKEXEC-1")
            self.assertEqual(store.get("cap:ui-design:1").active_dependency_count, 0)
