import hashlib
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from runtime.orchestrator.production_prefix_adoption import (
    PrefixAdoptionError, SCHEMA_VERSION, validate_prefix_adoption,
)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def run(root, *args):
    return subprocess.check_output(["git", "-C", str(root), *args], text=True).strip()


def commit(root, message, files):
    for name, content in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    subprocess.run(["git", "-C", str(root), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(root), "commit", "-q", "-m", message], check=True)
    return run(root, "rev-parse", "HEAD")


class PrefixAdoptionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        subprocess.run(["git", "-C", str(self.root), "init", "-q"], check=True)
        subprocess.run(["git", "-C", str(self.root), "config", "user.email", "test@example.com"], check=True)
        subprocess.run(["git", "-C", str(self.root), "config", "user.name", "Test"], check=True)
        self.approval = commit(self.root, "approval", {"base.txt": "base\n"})
        commit(self.root, "governance", {"gov.txt": "g\n"})
        self.t10 = commit(self.root, "t10", {"a.py": "a\n", "shared.py": "10\n"})
        self.t11 = commit(self.root, "t11", {"b.py": "b\n", "shared.py": "11\n"})
        self.adoption_head = commit(self.root, "continuity", {"continuity.txt": "ok\n"})
        self.branch = run(self.root, "branch", "--show-current")
        self.order = ["TASK-010", "TASK-011", "TASK-012"]
        self.owned = {
            "TASK-010": ["a.py", "shared.py"],
            "TASK-011": ["b.py", "shared.py"],
            "TASK-012": ["c.py"],
        }
        self.tests = {"TASK-010": ["TEST-019"], "TASK-011": ["TEST-020"], "TASK-012": ["TEST-021"]}

    def tearDown(self):
        self.tmp.cleanup()

    def entry(self, lv, checkpoint, validation_id, range_start):
        changed = sorted(x for x in run(self.root, "diff", "--name-only", f"{range_start}..{checkpoint}").splitlines()
                         if x and any(x == scope.rstrip("/") or (scope.endswith("/") and x.startswith(scope)) for scope in self.owned[lv]))
        value = {
            "lv_id": lv,
            "checkpoint_commit": checkpoint,
            "range_start": range_start,
            "owned_files": self.owned[lv],
            "changed_files": changed,
            "validation_ids": [validation_id],
            "validation_results": [{"command": ["python3", "-m", "unittest", validation_id], "exit_code": 0,
                                    "stdout_sha256": "a" * 64, "stderr_sha256": "b" * 64}],
            "review_verdict": "PASS",
        }
        value["evidence_sha256"] = digest(value)
        return value

    def record(self):
        value = {
            "schema_version": SCHEMA_VERSION,
            "project_id": "P",
            "gate_id": "G",
            "plan_sha256": "c" * 64,
            "branch": self.branch,
            "approval_head": self.approval,
            "adopted_lvs": ["TASK-010", "TASK-011"],
            "adoption_head": self.adoption_head,
            "entries": [self.entry("TASK-010", self.t10, "TEST-019", run(self.root, "rev-parse", self.t10 + "^")),
                        self.entry("TASK-011", self.t11, "TEST-020", self.t10)],
        }
        value["record_sha256"] = digest(value)
        return value

    def validate(self, record, *, require_head=True):
        return validate_prefix_adoption(
            self.root, record, project_id="P", gate_id="G", plan_sha256="c" * 64,
            branch=self.branch, approval_head=self.approval, lv_order=self.order,
            owned_files_by_lv=self.owned, validation_ids_by_lv=self.tests,
            require_adoption_head=require_head,
        )

    def test_valid_exact_prefix_with_overlapping_owned_scope(self):
        result = self.validate(self.record())
        self.assertEqual(result["adopted_lvs"], ["TASK-010", "TASK-011"])
        self.assertEqual(set(result["evidence_by_lv"]), {"TASK-010", "TASK-011"})

    def test_tampered_record_fails_closed(self):
        record = self.record(); record["entries"][0]["review_verdict"] = "FAIL"
        with self.assertRaisesRegex(PrefixAdoptionError, "digest"):
            self.validate(record)

    def test_non_prefix_order_fails_closed(self):
        record = self.record(); record["adopted_lvs"] = ["TASK-011"]; record["entries"] = [record["entries"][1]]
        record["record_sha256"] = digest({k: v for k, v in record.items() if k != "record_sha256"})
        with self.assertRaisesRegex(PrefixAdoptionError, "strict ordered"):
            self.validate(record)

    def test_post_prefix_adopted_scope_drift_fails_closed(self):
        drift = commit(self.root, "bad-drift", {"shared.py": "drift\n"})
        record = self.record(); record["adoption_head"] = drift
        record["record_sha256"] = digest({k: v for k, v in record.items() if k != "record_sha256"})
        with self.assertRaisesRegex(PrefixAdoptionError, "unadopted changes"):
            self.validate(record)

    def test_resume_allows_head_descendant_after_adoption_seal(self):
        record = self.record()
        commit(self.root, "task12", {"c.py": "c\n", "shared.py": "12\n"})
        result = self.validate(record, require_head=False)
        self.assertEqual(result["adoption_head"], self.adoption_head)
        with self.assertRaisesRegex(PrefixAdoptionError, "exact adoption HEAD"):
            self.validate(record, require_head=True)


if __name__ == "__main__":
    unittest.main()
