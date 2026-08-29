import hashlib
import tempfile
import unittest
from pathlib import Path

from runtime.orchestrator.lv_review import (
    IMMUTABLE_EXTERNAL_INTERPRETER, PROJECT_VENV_READ_ONLY,
    LVReviewError, validate_interpreter_policy,
)

class InterpreterPolicyTests(unittest.TestCase):
    def test_external_policy_validates_identity_and_fingerprint(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); exe = root / "python"; exe.write_bytes(b"#!/bin/sh\n"); exe.chmod(0o755)
            policy = {"schema_version":"orchestration.interpreter-policy.v1", "policy_id":IMMUTABLE_EXTERNAL_INTERPRETER,
                "project_id":"generic", "interpreter":str(exe), "allowed_root":str(root),
                "executable_sha256":hashlib.sha256(exe.read_bytes()).hexdigest(), "required_capabilities":[], "permissions":[], "registry_sha256":"a"*64}
            self.assertEqual(validate_interpreter_policy(policy, project_id="generic", registry_sha256="a"*64).policy_id, IMMUTABLE_EXTERNAL_INTERPRETER)

    def test_unknown_and_drift_policy_block(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); exe=root/"python"; exe.write_bytes(b"x"); exe.chmod(0o755)
            p={"schema_version":"orchestration.interpreter-policy.v1","policy_id":PROJECT_VENV_READ_ONLY,"project_id":"p","interpreter":str(exe),"allowed_root":str(root),"executable_sha256":"f"*64,"required_capabilities":[],"permissions":[],"registry_sha256":"a"*64}
            with self.assertRaises(LVReviewError): validate_interpreter_policy({**p,"policy_id":"UNKNOWN"},project_id="p")
            with self.assertRaisesRegex(LVReviewError,"fingerprint"): validate_interpreter_policy(p,project_id="p")

if __name__ == "__main__": unittest.main()
