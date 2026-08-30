import unittest

from runtime.orchestrator.lifecycle_binding import (
    FIELDS, LifecycleBindingError, SCHEMA_VERSION, build_binding,
    canonical_bytes, digest_projection, seal_envelope, validate_binding,
    validate_envelope,
)


def binding(**changes):
    values = {key: f"{index:064x}" for index, key in enumerate(sorted(FIELDS - {
        "schema_version", "attempt", "hard_stop", "project_id", "gate_id",
        "lv_id", "run_id", "recovery_id", "approval_event_id", "branch",
        "baseline_head", "current_head",
    }), 1)}
    values.update(project_id="project", gate_id="GATE-1", lv_id="G1-LV3-1",
                  run_id="run-1", attempt=1, recovery_id="recovery-1",
                  approval_event_id="APR-1", branch="main",
                  baseline_head="a" * 40, current_head="b" * 40, hard_stop=True)
    values.update(changes)
    return build_binding(**values)


class LifecycleBindingTests(unittest.TestCase):
    def test_canonical_serialization_and_blank_self_projection_are_deterministic(self):
        self.assertEqual(canonical_bytes({"é": 1, "a": 2}), b'{"a":2,"\xc3\xa9":1}')
        value = {"x": 1, "envelope_sha256": "f" * 64}
        self.assertEqual(digest_projection(value, "envelope_sha256"),
                         digest_projection({"envelope_sha256": "a" * 64, "x": 1}, "envelope_sha256"))

    def test_strict_schema_types_empty_digest_roles_and_extra_fields_fail_closed(self):
        cases = [
            {**binding(), "extra": 1},
            {**binding(), "schema_version": SCHEMA_VERSION + ".future"},
            {**binding(), "attempt": True},
            {**binding(), "attempt": 0},
            {**binding(), "project_id": ""},
            {**binding(), "artifact_sha256": "bad"},
            {**binding(), "hard_stop": False},
            {**binding(), "artifact_sha256": binding()["payload_sha256"]},
        ]
        for case in cases:
            with self.subTest(case=list(case)), self.assertRaises(LifecycleBindingError):
                validate_binding(case)

    def test_envelope_rejects_wrong_binding_schema_tamper_and_circular_digest(self):
        expected = binding()
        envelope = seal_envelope({"status": "READY"}, expected,
                                 schema_version="orchestration.package.v2")
        self.assertEqual(validate_envelope(envelope,
                                          schema_version="orchestration.package.v2",
                                          expected_binding=expected), envelope)
        for bad in (
            {**envelope, "extra": 1},
            {**envelope, "schema_version": "legacy.v1"},
            {**envelope, "payload": {"status": "BAD"}},
            {**envelope, "envelope_sha256": "0" * 64},
        ):
            with self.assertRaises(LifecycleBindingError):
                validate_envelope(bad, schema_version="orchestration.package.v2",
                                  expected_binding=expected)

    def test_errors_and_repr_do_not_echo_secret_values(self):
        secret = "sk-fixture-secret-never-print"
        with self.assertRaises(LifecycleBindingError) as caught:
            validate_binding({"secret": secret})
        self.assertNotIn(secret, str(caught.exception))
        self.assertNotIn(secret, repr(caught.exception))


if __name__ == "__main__":
    unittest.main()
