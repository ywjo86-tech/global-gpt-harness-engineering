from __future__ import annotations
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from runtime.orchestrator.production_attention import AttentionOutbox


class AttentionDeliveryTests(unittest.TestCase):
    def api(self):
        try:
            from runtime.orchestrator.attention_delivery import (
                ATTENTION_DELIVERY_UNCONFIGURED,
                AttentionDeliveryReceiptStore,
                CaptureAttentionDeliveryAdapter,
                HTTPSWebhookV1AttentionDeliveryAdapter,
            )
        except ModuleNotFoundError as exc:
            self.fail(f"attention delivery module missing: {exc}")
        return (ATTENTION_DELIVERY_UNCONFIGURED, AttentionDeliveryReceiptStore,
                CaptureAttentionDeliveryAdapter, HTTPSWebhookV1AttentionDeliveryAdapter)

    def event(self, outbox: AttentionOutbox, *, deferred: bool = False):
        return outbox.publish(
            kind="WAITING_PROVIDER" if deferred else "WAITING_APPROVAL",
            state="WAITING_PROVIDER" if deferred else "WAITING_APPROVAL",
            reason="provider timeout" if deferred else "approval required",
            gate_id="G1",
            delivery_class="DEFERRED_INCIDENT" if deferred else "IMMEDIATE_DECISION",
        )

    def test_capture_delivery_is_exactly_once_per_event_id(self):
        _,_,Capture,_=self.api()
        adapter=Capture()
        event={"event_id":"e"*64,"project_id":"P","run_id":"R","direction":"OUTBOUND_ONLY","control_authority":"NONE"}
        first=adapter.send(event); second=adapter.send(event)
        self.assertEqual(first.receipt_sha256,second.receipt_sha256)
        self.assertEqual(adapter.delivery_count(event["event_id"]),1)
        self.assertEqual(first.control_authority,"NONE")

    def test_no_live_transport_reports_unconfigured(self):
        UNCONFIGURED,_,_,HTTPS=self.api()
        adapter=HTTPS(endpoint="https://notify.example.invalid/hook", allowlisted_endpoints=("https://notify.example.invalid/hook",), secret_ref="env:TEST_TOKEN")
        self.assertEqual(adapter.status,UNCONFIGURED)
        with self.assertRaisesRegex(Exception,UNCONFIGURED):
            adapter.send({"event_id":"e"*64,"project_id":"P","run_id":"R","direction":"OUTBOUND_ONLY","control_authority":"NONE"})

    def test_delivery_receipt_is_persisted_before_mark_delivered(self):
        _,Store,Capture,_=self.api()
        with tempfile.TemporaryDirectory() as td:
            base=Path(td); outbox=AttentionOutbox(base,project_id="P",run_id="R"); event=self.event(outbox)
            store=Store(base,project_id="P",run_id="R"); adapter=Capture()
            real_mark=outbox.mark_delivered
            def guarded_mark(event_id,*,channel,receipt):
                self.assertIsNotNone(store.load(event_id))
                return real_mark(event_id,channel=channel,receipt=receipt)
            with patch.object(outbox,"mark_delivered",side_effect=guarded_mark):
                delivered=outbox.deliver_with_adapter(adapter,receipt_store=store,channel="capture")
            self.assertEqual(delivered,[event["event_id"]])
            self.assertEqual(outbox.pending(),[])
            self.assertIsNotNone(store.load(event["event_id"]))

    def test_deferred_incident_requires_policy_eligibility(self):
        _,Store,Capture,_=self.api()
        with tempfile.TemporaryDirectory() as td:
            base=Path(td); outbox=AttentionOutbox(base,project_id="P",run_id="R"); event=self.event(outbox,deferred=True)
            store=Store(base,project_id="P",run_id="R"); adapter=Capture()
            self.assertEqual(outbox.deliver_with_adapter(adapter,receipt_store=store,channel="capture"),[])
            self.assertEqual(adapter.delivery_count(event["event_id"]),0)
            delivered=outbox.deliver_with_adapter(adapter,receipt_store=store,channel="capture",eligible_event_ids={event["event_id"]})
            self.assertEqual(delivered,[event["event_id"]])

    def test_adapter_has_no_inbound_control_surface(self):
        _,_,Capture,HTTPS=self.api()
        for cls in (Capture,HTTPS):
            for forbidden in ("resume","dispatch","approve","route","command"):
                self.assertFalse(hasattr(cls,forbidden))


if __name__ == "__main__": unittest.main()
