from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from runtime.orchestrator.durable_io import (
    DurableIOError,
    atomic_write_json,
    atomic_write_text,
    durable_json_load,
    durable_json_save,
)


class DurableIOTests(unittest.TestCase):
    def test_atomic_text_replaces_complete_generation(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "state.txt"
            atomic_write_text(path, "one")
            atomic_write_text(path, "two")
            self.assertEqual(path.read_text(), "two")

    def test_atomic_json_rejects_symlink_target(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); target = root / "real.json"; target.write_text("{}")
            link = root / "link.json"; link.symlink_to(target)
            with self.assertRaises(DurableIOError): atomic_write_json(link, {"x": 1})

    def test_durable_save_keeps_previous_good_generation(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "state.json"
            durable_json_save(path, {"generation": 1})
            durable_json_save(path, {"generation": 2})
            value, recovered = durable_json_load(path.with_suffix(".json.prev"))
            self.assertEqual(value["generation"], 1); self.assertFalse(recovered)

    def test_corrupt_primary_can_be_replaced_without_destroying_previous(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "state.json"
            durable_json_save(path, {"generation": 1})
            durable_json_save(path, {"generation": 2})
            previous = json.loads(path.with_suffix(".json.prev").read_text())
            path.write_bytes(b"{bad")
            durable_json_save(path, {"generation": 3})
            self.assertEqual(json.loads(path.read_text())["generation"], 3)
            self.assertEqual(json.loads(path.with_suffix(".json.prev").read_text()), previous)
            self.assertEqual((Path(d) / "state.json.corrupt").read_bytes(), b"{bad")


if __name__ == "__main__": unittest.main()
