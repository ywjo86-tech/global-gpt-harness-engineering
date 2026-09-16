from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path

from runtime.full_mcp.filesystem_service import FilesystemService, FilesystemServiceError
from runtime.full_mcp.path_policy import WorkspacePathPolicy


class FilesystemReadWriteTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / "read").mkdir(); (self.root / "owned").mkdir()
        (self.root / "read/a.txt").write_text("alpha\nbeta\n", encoding="utf-8")
        self.service = FilesystemService(WorkspacePathPolicy(self.root, read_scopes=(".",), mutable_scopes=("owned",)))

    def tearDown(self) -> None: self.temp.cleanup()

    def test_authorized_read_and_atomic_create_replace(self) -> None:
        read = self.service.read("read/a.txt")
        self.assertEqual(read["text"], "alpha\nbeta\n")
        created = self.service.write("owned/new.txt", "one\n", expected_absent=True)
        self.assertIsNone(created["before_sha256"])
        replaced = self.service.write("owned/new.txt", "two\n", expected_sha256=created["after_sha256"])
        self.assertEqual((self.root / "owned/new.txt").read_text(), "two\n")
        self.assertEqual(replaced["before_sha256"], created["after_sha256"])

    def test_replace_requires_optimistic_precondition(self) -> None:
        (self.root / "owned/existing.txt").write_text("old", encoding="utf-8")
        with self.assertRaises(FilesystemServiceError): self.service.write("owned/existing.txt", "new")
        with self.assertRaises(FilesystemServiceError): self.service.write("owned/existing.txt", "new", expected_sha256="0" * 64)

    def test_outside_scope_and_symlink_are_blocked(self) -> None:
        (self.root / "owned/link").symlink_to("/etc/passwd")
        for target in ("../escape", "/etc/passwd", "read/a.txt"):
            with self.subTest(target=target), self.assertRaises(FilesystemServiceError):
                self.service.write(target, "x")
        with self.assertRaises(FilesystemServiceError): self.service.read("owned/link")


class FilesystemPatchTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)
        (self.root / "owned").mkdir(); self.target = self.root / "owned/p.txt"
        self.target.write_text("a\nb\nc\n", encoding="utf-8")
        self.service = FilesystemService(WorkspacePathPolicy(self.root, read_scopes=(".",), mutable_scopes=("owned",)))

    def tearDown(self) -> None: self.temp.cleanup()

    def test_controlled_patch_and_stale_hash(self) -> None:
        base = hashlib.sha256(self.target.read_bytes()).hexdigest()
        result = self.service.patch("owned/p.txt", base_sha256=base,
            edits=[{"start_line": 2, "end_line": 2, "replacement": "B"}])
        self.assertEqual(self.target.read_text(), "a\nB\nc\n")
        self.assertEqual(result["before_sha256"], base)
        with self.assertRaises(FilesystemServiceError):
            self.service.patch("owned/p.txt", base_sha256=base,
                edits=[{"start_line": 1, "end_line": 1, "replacement": "A"}])

    def test_overlap_fails_without_partial_write(self) -> None:
        before = self.target.read_bytes(); base = hashlib.sha256(before).hexdigest()
        with self.assertRaises(FilesystemServiceError):
            self.service.patch("owned/p.txt", base_sha256=base, edits=[
                {"start_line": 1, "end_line": 2, "replacement": "X"},
                {"start_line": 2, "end_line": 3, "replacement": "Y"},])
        self.assertEqual(self.target.read_bytes(), before)


class FilesystemSearchMetadataTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)
        (self.root / "read").mkdir(); (self.root / "read/a.txt").write_text("needle here\nnone\n", encoding="utf-8")
        (self.root / "read/b.txt").write_text("needle again\n", encoding="utf-8")
        self.service = FilesystemService(WorkspacePathPolicy(self.root, read_scopes=("read",), mutable_scopes=("read",)))

    def tearDown(self) -> None: self.temp.cleanup()

    def test_bounded_literal_and_regex_search(self) -> None:
        literal = self.service.search(root="read", query="needle", max_matches=1)
        self.assertEqual(literal["match_count"], 1)
        regex = self.service.search(root="read", query=r"need.e", mode="REGEX")
        self.assertEqual(regex["match_count"], 2)
        with self.assertRaises(FilesystemServiceError): self.service.search(root="read", query="(", mode="REGEX")

    def test_metadata_exact_shape_and_symlink_block(self) -> None:
        meta = self.service.metadata("read/a.txt")
        self.assertEqual(meta["kind"], "REGULAR_FILE"); self.assertFalse(meta["symlink"])
        self.assertEqual(len(meta["sha256"]), 64)
        (self.root / "read/link").symlink_to("/etc/passwd")
        with self.assertRaises(FilesystemServiceError): self.service.metadata("read/link")
