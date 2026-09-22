from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest

from runtime.orchestrator.read_only_host_diagnostic_contract import DiagnosticPolicy, ReadOnlyDiagnosticRequestV1, REQUEST_SCHEMA
from runtime.orchestrator.read_only_host_diagnostic import (
    DiagnosticSecurityError,
    read_path_metadata,
    read_project_file_range,
    collect_repo_snapshot,
    read_user_service_properties,
    execute_read_only_host_diagnostic,
)


class ReadOnlyHostDiagnosticTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.base = Path(self.tmp.name); self.root = self.base / "root"; self.root.mkdir()
        self.policy = DiagnosticPolicy(roots={"project": self.root.resolve()}, user_services=("ocpv2.service",), max_bytes=128, max_lines=4, timeout_seconds=5)

    def tearDown(self): self.tmp.cleanup()

    def request(self, operation, relative_path, *, start_line=0, line_count=0):
        return ReadOnlyDiagnosticRequestV1.from_mapping({"schema_version": REQUEST_SCHEMA, "request_id": "REQ-1", "operation": operation, "root_id": "project", "relative_path": relative_path, "start_line": start_line, "line_count": line_count, "service_id": ""})
    def file_request(self, relative_path, *, start_line=1, line_count=10): return self.request("project.file_range", relative_path, start_line=start_line, line_count=line_count)
    def meta_request(self, relative_path): return self.request("path.metadata", relative_path)
    def repo_request(self): return ReadOnlyDiagnosticRequestV1.from_mapping({"schema_version": REQUEST_SCHEMA, "request_id": "REQ-GIT", "operation": "repo.snapshot", "root_id": "project", "relative_path": "", "start_line": 0, "line_count": 0, "service_id": ""})
    def service_request(self, service_id="ocpv2.service"): return ReadOnlyDiagnosticRequestV1.from_mapping({"schema_version": REQUEST_SCHEMA, "request_id": "REQ-SVC", "operation": "user_service.properties", "root_id": "", "relative_path": "", "start_line": 0, "line_count": 0, "service_id": service_id})

    def test_file_range_blocks_intermediate_symlink_escape(self):
        outside = self.base / "outside"; outside.mkdir(); (outside / "secret.txt").write_text("password=do-not-return\n", encoding="utf-8"); (self.root / "jump").symlink_to(outside, target_is_directory=True)
        with self.assertRaisesRegex(DiagnosticSecurityError, "symlink"): read_project_file_range(self.file_request("jump/secret.txt"), self.policy)
    def test_file_range_blocks_absolute_parent_and_final_symlink(self):
        target = self.root / "ok.txt"; target.write_text("hello\n", encoding="utf-8"); (self.root / "link.txt").symlink_to(target)
        for path in ("/etc/passwd", "../outside", "link.txt"):
            with self.subTest(path=path), self.assertRaises(DiagnosticSecurityError): read_project_file_range(self.file_request(path), self.policy)
    def test_file_range_blocks_sensitive_names_and_binary(self):
        for name in (".env", "id_rsa", "cert.pem"):
            (self.root / name).write_text("token=abc123\n", encoding="utf-8")
            with self.subTest(name=name), self.assertRaisesRegex(DiagnosticSecurityError, "sensitive"): read_project_file_range(self.file_request(name), self.policy)
        (self.root / "blob.bin").write_bytes(b"abc\x00def")
        with self.assertRaisesRegex(DiagnosticSecurityError, "binary"): read_project_file_range(self.file_request("blob.bin"), self.policy)
    @unittest.skipUnless(hasattr(os, "mkfifo"), "POSIX FIFO required")
    def test_file_range_blocks_special_file(self):
        fifo = self.root / "pipe"; os.mkfifo(fifo)
        with self.assertRaisesRegex(DiagnosticSecurityError, "regular"): read_project_file_range(self.file_request("pipe"), self.policy)
    def test_file_range_redacts_secret_values_and_enforces_line_cap(self):
        (self.root / "notes.txt").write_text("one\ntoken=abc123\nthree\nfour\nfive\nsix\n", encoding="utf-8"); result = read_project_file_range(self.file_request("notes.txt", start_line=1, line_count=10), self.policy)
        self.assertNotIn("abc123", result["text"]); self.assertIn("token=[REDACTED]", result["text"]); self.assertTrue(result["redaction_applied"]); self.assertTrue(result["truncated"]); self.assertEqual(result["lines_returned"], 4)
    def test_file_range_enforces_byte_cap(self):
        (self.root / "long.txt").write_text("x" * 300 + "\n", encoding="utf-8"); result = read_project_file_range(self.file_request("long.txt", start_line=1, line_count=1), self.policy)
        self.assertLessEqual(len(result["text"].encode("utf-8")), self.policy.max_bytes); self.assertTrue(result["truncated"])
    def test_metadata_returns_only_safe_fields_and_missing_state(self):
        (self.root / "file.txt").write_text("hello", encoding="utf-8"); result = read_path_metadata(self.meta_request("file.txt"), self.policy)
        self.assertEqual(set(result), {"exists", "type", "size", "mtime_ns", "mode_class", "canonical_relative_path"}); self.assertTrue(result["exists"]); self.assertEqual(result["type"], "file"); self.assertFalse(read_path_metadata(self.meta_request("missing.txt"), self.policy)["exists"])
    def test_metadata_blocks_symlink_and_sensitive_path(self):
        target = self.root / "file.txt"; target.write_text("hello", encoding="utf-8"); (self.root / "link.txt").symlink_to(target)
        for path in ("link.txt", ".env", "../escape"):
            with self.subTest(path=path), self.assertRaises(DiagnosticSecurityError): read_path_metadata(self.meta_request(path), self.policy)

    def test_repo_snapshot_uses_fixed_shell_false_git_environment(self):
        calls=[]
        class Completed:
            returncode=0; stderr=""
            def __init__(self, stdout=""): self.stdout=stdout
        def runner(argv, **kwargs):
            calls.append((list(argv),dict(kwargs))); args=argv[3:]
            if args[:2]==["status","--porcelain=v2"]: return Completed("# branch.oid "+"a"*40+"\n# branch.head main\n# branch.upstream origin/main\n# branch.ab +1 -2\n")
            if args[:2]==["rev-parse","--verify"]: return Completed("a"*40+"\n")
            if args in (["rev-parse","--git-dir"],["rev-parse","--git-common-dir"]): return Completed(".git\n")
            return Completed("")
        snapshot=collect_repo_snapshot(self.repo_request(),self.policy,runner=runner); self.assertEqual((snapshot["branch"],snapshot["ahead"],snapshot["behind"]),("main",1,2))
        for argv,kwargs in calls:
            self.assertEqual(argv[:3],["git","-C",str(self.root.resolve())]); self.assertFalse(kwargs["shell"]); self.assertTrue(kwargs["capture_output"]); self.assertTrue(kwargs["text"]); self.assertFalse(kwargs["check"])
            for key,value in {"GIT_OPTIONAL_LOCKS":"0","GIT_TERMINAL_PROMPT":"0","GIT_CONFIG_NOSYSTEM":"1","GIT_CONFIG_GLOBAL":"/dev/null","GIT_PAGER":"cat","PAGER":"cat"}.items(): self.assertEqual(kwargs["env"][key],value)
    def test_repo_snapshot_does_not_execute_malicious_diff_helper(self):
        import subprocess
        repo=self.root; subprocess.run(["git","-C",str(repo),"init"],check=True,capture_output=True); subprocess.run(["git","-C",str(repo),"config","user.email","test@example.invalid"],check=True); subprocess.run(["git","-C",str(repo),"config","user.name","Test"],check=True)
        tracked=repo/"tracked.txt"; tracked.write_text("one\n",encoding="utf-8"); (repo/".gitattributes").write_text("*.txt diff=evil\n",encoding="utf-8"); subprocess.run(["git","-C",str(repo),"add","tracked.txt",".gitattributes"],check=True); subprocess.run(["git","-C",str(repo),"commit","-m","base"],check=True,capture_output=True)
        marker=self.base/"helper-ran"; helper=self.base/"evil-helper.sh"; helper.write_text(f"#!/bin/sh\ntouch {marker}\n",encoding="utf-8"); helper.chmod(0o700); subprocess.run(["git","-C",str(repo),"config","diff.evil.command",str(helper)],check=True); tracked.write_text("two\n",encoding="utf-8")
        snapshot=collect_repo_snapshot(self.repo_request(),self.policy); self.assertFalse(marker.exists()); self.assertFalse(snapshot["stale"]); self.assertIn("tracked.txt",snapshot["unstaged_paths"])

    def test_user_service_properties_blocks_non_allowlisted_unit(self):
        with self.assertRaisesRegex(DiagnosticSecurityError,"allowlist"): read_user_service_properties(self.service_request("other.service"),self.policy)
    def test_user_service_properties_uses_fixed_argv(self):
        calls=[]
        class Completed: returncode=0; stdout="ActiveState=active\nSubState=running\nResult=success\nExecMainStatus=0\nInvocationID=abc\n"; stderr=""
        def runner(argv,**kwargs): calls.append((list(argv),dict(kwargs))); return Completed()
        result=read_user_service_properties(self.service_request(),self.policy,runner=runner); self.assertEqual(result["ActiveState"],"active")
        self.assertEqual(calls[0][0],["systemctl","--user","show","ocpv2.service","--no-pager","--property=ActiveState","--property=SubState","--property=Result","--property=ExecMainStatus","--property=InvocationID"])
        kwargs=calls[0][1]; self.assertFalse(kwargs["shell"]); self.assertTrue(kwargs["capture_output"]); self.assertTrue(kwargs["text"]); self.assertFalse(kwargs["check"])

    def test_dispatcher_file_result_is_content_with_provenance(self):
        (self.root/"readme.txt").write_text("hello\n",encoding="utf-8"); result=execute_read_only_host_diagnostic(self.file_request("readme.txt",start_line=1,line_count=1),self.policy,project_id="P1",correlation_id="CORR-1",source_sha="a"*40,runtime_sha="b"*40)
        self.assertEqual(result.status,"OK"); self.assertEqual(result.data_class,"DIAG_CONTENT"); self.assertEqual(result.execution_owner,"NONE"); self.assertTrue(result.captured_at); self.assertTrue(result.payload_hash)
    def test_dispatcher_maps_security_denial_to_blocked_without_secret(self):
        (self.root/".env").write_text("token=abc123\n",encoding="utf-8"); result=execute_read_only_host_diagnostic(self.file_request(".env",start_line=1,line_count=1),self.policy,project_id="P1",correlation_id="CORR-2",source_sha="a"*40,runtime_sha="b"*40)
        self.assertEqual(result.status,"BLOCKED"); self.assertNotIn("abc123",str(result.payload))
    def test_dispatcher_maps_truncated_file_to_partial(self):
        (self.root/"longer.txt").write_text("x"*300+"\n",encoding="utf-8"); result=execute_read_only_host_diagnostic(self.file_request("longer.txt",start_line=1,line_count=1),self.policy,project_id="P1",correlation_id="CORR-3",source_sha="a"*40,runtime_sha="b"*40)
        self.assertEqual(result.status,"PARTIAL"); self.assertTrue(result.truncated)
    def test_dispatcher_maps_stale_snapshot_to_stale(self):
        import runtime.orchestrator.read_only_host_diagnostic as module
        original=module._OPERATION_HANDLERS["repo.snapshot"]; module._OPERATION_HANDLERS["repo.snapshot"]=lambda request,policy:{"stale":True,"truncated":False}
        try: result=execute_read_only_host_diagnostic(self.repo_request(),self.policy,project_id="P1",correlation_id="CORR-4",source_sha="a"*40,runtime_sha="b"*40)
        finally: module._OPERATION_HANDLERS["repo.snapshot"]=original
        self.assertEqual(result.status,"STALE"); self.assertEqual(result.freshness,"STALE")
    def test_dispatcher_maps_service_failure_to_unavailable(self):
        import runtime.orchestrator.read_only_host_diagnostic as module
        original=module._OPERATION_HANDLERS["user_service.properties"]
        def unavailable(request,policy): raise module.DiagnosticExecutionError("user service property read unavailable")
        module._OPERATION_HANDLERS["user_service.properties"]=unavailable
        try: result=execute_read_only_host_diagnostic(self.service_request(),self.policy,project_id="P1",correlation_id="CORR-5",source_sha="a"*40,runtime_sha="b"*40)
        finally: module._OPERATION_HANDLERS["user_service.properties"]=original
        self.assertEqual(result.status,"UNAVAILABLE")


if __name__ == "__main__": unittest.main()
