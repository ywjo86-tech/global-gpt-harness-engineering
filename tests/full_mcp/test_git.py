from __future__ import annotations

import hashlib
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from runtime.full_mcp.git_service import GitService, GitServiceError
from runtime.full_mcp.path_policy import WorkspacePathPolicy


def git(root: Path, *args: str) -> str:
    env={"GIT_TERMINAL_PROMPT":"0","LC_ALL":"C.UTF-8"}
    return subprocess.check_output(["git", *args], cwd=root, text=True, env=env).strip()


class GitServiceBase(unittest.TestCase):
    def setUp(self) -> None:
        self.temp=tempfile.TemporaryDirectory(); self.root=Path(self.temp.name)
        subprocess.check_call(["git","init","-q"], cwd=self.root)
        subprocess.check_call(["git","config","user.email","test@example.invalid"], cwd=self.root)
        subprocess.check_call(["git","config","user.name","Full MCP Test"], cwd=self.root)
        (self.root/"owned").mkdir(); (self.root/"owned/a.txt").write_text("base\n",encoding="utf-8")
        subprocess.check_call(["git","add","owned/a.txt"],cwd=self.root); subprocess.check_call(["git","commit","-qm","base"],cwd=self.root)
        self.policy=WorkspacePathPolicy(self.root,read_scopes=(".",),mutable_scopes=("owned",))
        self.service=GitService(self.root,self.policy)
    def tearDown(self)->None:self.temp.cleanup()


class GitReadCapabilityTests(GitServiceBase):
    def test_status_diff_and_branch_are_bounded(self)->None:
        (self.root/"owned/a.txt").write_text("changed\n",encoding="utf-8")
        status=self.service.status(["owned/a.txt"]); self.assertFalse(status["clean"]); self.assertEqual(len(status["head_sha"]),40)
        diff=self.service.diff(["owned/a.txt"]); self.assertIn("changed",diff["diff"]); self.assertEqual(diff["bytes"],len(diff["diff"].encode()))
        branch=self.service.branch(); self.assertFalse(branch["detached"]); self.assertEqual(branch["head_sha"],status["head_sha"])
        with self.assertRaises(GitServiceError): self.service.diff(["../escape"])
        with self.assertRaises(GitServiceError): self.service.diff(base_ref="--help")


class GitRestoreTests(GitServiceBase):
    def test_approved_restore_and_outside_scope_block(self)->None:
        (self.root/"owned/a.txt").write_text("changed\n",encoding="utf-8")
        result=self.service.restore(["owned/a.txt"],source_ref="HEAD")
        self.assertEqual((self.root/"owned/a.txt").read_text(),"base\n"); self.assertEqual(len(result["source_sha"]),40)
        with self.assertRaises(GitServiceError): self.service.restore(["../escape"],source_ref="HEAD")


class GitCommitPreparationTests(GitServiceBase):
    def test_prepare_commit_is_read_only_for_index_head_and_remotes(self)->None:
        (self.root/"owned/a.txt").write_text("candidate\n",encoding="utf-8")
        head_before=git(self.root,"rev-parse","HEAD"); index=Path(git(self.root,"rev-parse","--git-path","index"))
        if not index.is_absolute(): index=self.root/index
        index_before=hashlib.sha256(index.read_bytes()).hexdigest(); remotes_before=git(self.root,"remote","-v")
        result=self.service.prepare_commit(["owned/a.txt"],subject="bounded change")
        self.assertEqual(result["head_sha"],head_before); self.assertEqual(result["index_sha256_before"],index_before)
        self.assertEqual(git(self.root,"rev-parse","HEAD"),head_before); self.assertEqual(hashlib.sha256(index.read_bytes()).hexdigest(),index_before)
        self.assertEqual(git(self.root,"remote","-v"),remotes_before)
        with self.assertRaises(GitServiceError): self.service.prepare_commit(["owned/a.txt"],subject="x\nbad")
