import json
import tempfile
import unittest
from pathlib import Path

from tests.capability_lifecycle_fixtures import active_record
from runtime.orchestrator.capability_lifecycle_store import (
    CapabilityLifecycleStore,
    CapabilityLifecycleStoreError,
)


class CapabilityLifecycleStoreTests(unittest.TestCase):
    def test_store_round_trip_rejects_tampered_record(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            store = CapabilityLifecycleStore(root)
            record = active_record()
            store.put(record)
            self.assertEqual(store.get(record.contract.contract_id), record)
            path = root / "capability-lifecycle" / "cap_ui-design_1.json"
            payload = json.loads(path.read_text())
            payload["state"] = "RETIRED"
            path.write_text(json.dumps(payload))
            with self.assertRaisesRegex(CapabilityLifecycleStoreError, "digest"):
                store.get(record.contract.contract_id)
