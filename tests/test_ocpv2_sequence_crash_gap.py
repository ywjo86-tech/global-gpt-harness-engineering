from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from runtime.orchestrator import remote_operator_receipt as receipt_module
from runtime.orchestrator.remote_operator_receipt import (
    ReceiptStatus,
    RemoteOperatorReceiptError,
    RemoteOperatorReceiptStore,
)
from tests.test_ocpv2_final_acceptance_release_blockers import _envelope


class OCPv2SequenceCrashGapTests(unittest.TestCase):
    def test_durable_receipt_blocks_same_sequence_reuse_before_original_replay(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            store = RemoteOperatorReceiptStore(root)
            original = _envelope(
                message_id="MSG-CRASHED",
                sequence=7,
                source_message_id="707",
            )
            real_save = receipt_module.durable_json_save
            writes = 0

            def crash_between_receipt_and_watermark(path, value):
                nonlocal writes
                writes += 1
                if writes == 2:
                    raise OSError("synthetic crash before sequence watermark")
                return real_save(path, value)

            with patch.object(
                receipt_module,
                "durable_json_save",
                side_effect=crash_between_receipt_and_watermark,
            ):
                with self.assertRaises(RemoteOperatorReceiptError):
                    store.record_received(original)

            recovered = RemoteOperatorReceiptStore(root)
            reused = _envelope(
                message_id="MSG-REUSED-SEQUENCE",
                sequence=7,
                source_message_id="708",
            )
            self.assertEqual(
                recovered.classify_delivery(reused),
                ReceiptStatus.REPLAY_REJECTED,
            )


if __name__ == "__main__":
    unittest.main()
