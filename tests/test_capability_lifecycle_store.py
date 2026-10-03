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
            path = store._path(record.contract.contract_id)
            payload = json.loads(path.read_text())
            payload["state"] = "RETIRED"
            path.write_text(json.dumps(payload))
            with self.assertRaisesRegex(CapabilityLifecycleStoreError, "digest"):
                store.get(record.contract.contract_id)

    def test_legacy_contract_id_filename_remains_readable(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            store = CapabilityLifecycleStore(root)
            record = active_record()
            path = root / "capability-lifecycle" / "cap_ui-design_1.json"
            path.write_text(json.dumps(record.to_dict()))

            self.assertEqual(store.get(record.contract.contract_id), record)

    def test_legacy_record_update_does_not_create_duplicate_revision(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            store = CapabilityLifecycleStore(root)
            record = active_record()
            legacy = root / "capability-lifecycle" / "cap_ui-design_1.json"
            legacy.write_text(json.dumps(record.to_dict()))
            updated = store.acquire_dependency(record.contract.contract_id, "TASKEXEC-1")
            rows = store.list_records()
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0], updated)
            self.assertEqual(rows[0].active_dependency_ids, ("TASKEXEC-1",))
            self.assertFalse(store._path(record.contract.contract_id).exists())
