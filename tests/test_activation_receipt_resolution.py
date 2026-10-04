from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from runtime.orchestrator.activation_receipt_resolution import diagnose_activation_receipts
from runtime.orchestrator.durable_io import canonical_json_bytes, sha256_bytes
from runtime.orchestrator.full_plan_activation import FULL_PLAN_ACTIVATION_RECEIPT_SCHEMA_V1


class ActivationReceiptResolutionDiagnosticTests(unittest.TestCase):
    def test_direct_and_archived_superseded_receipts_resolve_without_rewrite(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            receipts=root/"_workspace"/"full-plan-activation-receipts"
            jobs=root/"_workspace"/"production-full-plan-jobs"/"P"
            archive=root/"_workspace"/"archive"
            receipts.mkdir(parents=True); jobs.mkdir(parents=True); archive.mkdir(parents=True)

            def write_receipt(name, run_id, authority, canonical):
                unsigned={
                    "schema_version":FULL_PLAN_ACTIVATION_RECEIPT_SCHEMA_V1,
                    "activation_request_id":name,
                    "bundle_digest":"b"*64,
                    "result_status":"FULL_PLAN_REGISTERED",
                    "canonical_job_path":str(canonical),
                    "run_id":run_id,
                    "authority_digest":authority,
                    "executable_authority_bundle_digest":"b"*64,
                }
                payload={**unsigned,"activation_digest":sha256_bytes(canonical_json_bytes(unsigned))}
                (receipts/f"{name}.json").write_text(json.dumps(payload))
                return payload

            direct=jobs/"DIRECT.job.json"
            direct.write_text(json.dumps({"run_id":"DIRECT","authority_core_sha256":"a"*64}))
            write_receipt("DIRECT","DIRECT","a"*64,direct)

            missing=jobs/"OLD.job.json"
            archived=archive/"superseded-job-17.json"
            archived.write_text(json.dumps({"run_id":"OLD","authority_core_sha256":"c"*64}))
            old_payload=write_receipt("OLD","OLD","c"*64,missing)

            result=diagnose_activation_receipts(root)
            self.assertEqual(result["receipt_count"],2)
            self.assertEqual(result["counts"]["DIRECT"],1)
            self.assertEqual(result["counts"]["ARCHIVED_SUPERSEDED"],1)
            self.assertEqual(result["unresolved_count"],0)
            self.assertFalse(missing.exists())
            self.assertEqual(json.loads((receipts/"OLD.json").read_text()),old_payload)


if __name__=="__main__":
    unittest.main()
