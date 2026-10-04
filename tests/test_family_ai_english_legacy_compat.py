from __future__ import annotations

import json
import unittest

from runtime.orchestrator.contract_adapter import MAPPING_DIR
from runtime.orchestrator.execution_lifecycle_v2 import resolve_lifecycle_binding


FAMILY_PROJECT_ID = "FAMILY_AI_ENGLISH_COACH"
FAMILY_PROJECTION = {
    "path": "docs/harness/task-lv-authority-projection.json",
    "sha256": "9d98c77648b57135d64c94bcef6acea722c9b8a40f262d6a35937a881dfaf327",
}


class FamilyAIEnglishLegacyCompatibilityTests(unittest.TestCase):
    def test_checked_in_mapping_stays_on_existing_task_lv_projection(self) -> None:
        path = MAPPING_DIR / f"{FAMILY_PROJECT_ID}.json"
        before = path.read_bytes()
        payload = json.loads(before)

        self.assertEqual(payload["project_id"], FAMILY_PROJECT_ID)
        self.assertEqual(payload["task_lv_authority_projection"], FAMILY_PROJECTION)
        self.assertEqual(payload["plan_sha_migrations"], [])
        self.assertEqual(payload["interpreter_policy_id"], "IMMUTABLE_EXTERNAL_INTERPRETER")

        successor_only = {
            "lifecycle_binding",
            "execution_authority_bundle",
            "runtime_release_digest",
            "operator_dispatch_v2",
        }
        self.assertTrue(successor_only.isdisjoint(payload))
        self.assertEqual(path.read_bytes(), before)

    def test_existing_family_attempt_without_binding_remains_legacy_and_unmodified(self) -> None:
        legacy_job = {
            "project_id": FAMILY_PROJECT_ID,
            "run_id": "TASK-001-attempt-03",
            "authority_projection": dict(FAMILY_PROJECTION),
        }
        before = json.dumps(legacy_job, sort_keys=True, separators=(",", ":"))

        resolved = resolve_lifecycle_binding(legacy_job)

        self.assertEqual(resolved["lifecycle_mode"], "LEGACY")
        self.assertFalse(resolved["bound_at_activation"])
        self.assertFalse(resolved["migration_allowed"])
        self.assertEqual(resolved["runtime_release_digest"], "")
        self.assertEqual(json.dumps(legacy_job, sort_keys=True, separators=(",", ":")), before)
        self.assertNotIn("lifecycle_binding", legacy_job)
        self.assertNotIn("execution_authority_bundle", legacy_job)


if __name__ == "__main__":
    unittest.main()
