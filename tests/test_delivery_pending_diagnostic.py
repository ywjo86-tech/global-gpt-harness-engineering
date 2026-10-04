from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from runtime.operator_transport.delivery_pending_diagnostic import diagnose_delivery_pending


class DeliveryPendingDiagnosticTests(unittest.TestCase):
    def test_exact_ack_and_durable_state_are_classified_without_mutation(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            ack=root/"transport"/"acks.json"; pending=root/"transport"/"acks.json.pending"
            ack.parent.mkdir(parents=True)
            ack.write_text(json.dumps({
                "schema_version":"ocpv2.github-delivery-ack.v1",
                "entries":[{"source_message_id":"1","message_id":"ACKED","content_sha256":"a"*64}],
            }))
            pending.write_text(json.dumps({
                "schema_version":"ocpv2.github-delivery-pending.v1",
                "entries":[
                    {"source_message_id":"1","message_id":"ACKED","content_sha256":"a"*64},
                    {"source_message_id":"2","message_id":"DONE-RUN","content_sha256":"b"*64},
                    {"source_message_id":"3","message_id":"UNKNOWN","content_sha256":"c"*64},
                ],
            }))
            evidence=root/"_workspace"/"runs"/"state.json"; evidence.parent.mkdir(parents=True)
            evidence.write_text(json.dumps({"message_id":"DONE-RUN","state":"COMPLETED"}))
            rows=diagnose_delivery_pending(
                ack_path=ack,pending_path=pending,harness_state_root=root,
            )
            self.assertEqual([row.status for row in rows],[
                "ACKED_PENDING_CLEANUP",
                "OBSOLETE_WITH_DURABLE_EVIDENCE",
                "CURRENT_OR_UNRESOLVED_PENDING",
            ])
            self.assertEqual(len(rows[1].evidence_refs),1)


if __name__=="__main__":
    unittest.main()
