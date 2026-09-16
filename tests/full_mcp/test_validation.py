from __future__ import annotations

import subprocess
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from runtime.full_mcp.contracts import InvocationContext, scope_digest
from runtime.full_mcp.path_policy import WorkspacePathPolicy
from runtime.full_mcp.process_service import ProcessService, ShellPolicy
from runtime.full_mcp.validation_profiles import ValidationProfile, ValidationProfileCatalog, ValidationProfileError, default_validation_catalog
from runtime.full_mcp.validation_service import ValidationService, ValidationServiceError

SHA="a"*64


class ValidationServiceFocusedTests(unittest.TestCase):
    def test_default_catalog_is_sealed_and_exact_focused_profile_exists(self)->None:
        catalog=default_validation_catalog(); profile=catalog.get("VP-VALIDATION-FOCUSED")
        self.assertEqual(profile.argv,("python3","-m","unittest","-q","tests.full_mcp.test_validation.ValidationServiceFocusedTests"))
        self.assertEqual(profile.cwd,"."); self.assertEqual(profile.env_allowlist,())
        with self.assertRaises(ValidationProfileError): ValidationProfileCatalog([profile,profile])
        with self.assertRaises(ValidationProfileError): catalog.get("UNKNOWN")

    def test_execute_only_digest_bound_sealed_profile(self)->None:
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); (root/"owned").mkdir()
            profile=ValidationProfile("VP-TEST","UNIT",("python3","-c","print('ok')"),".",10,()).sealed()
            catalog=ValidationProfileCatalog([profile]); policy=WorkspacePathPolicy(root,read_scopes=(".",),mutable_scopes=("owned",))
            process=ProcessService(policy,shell_policy=ShellPolicy(allowed_executables=("python3",)))
            ctx=InvocationContext(schema_version="gch.full-mcp.invocation-context.v1",project_id="P",run_id="R",gate_id="G",lv_id="L",attempt=1,
                request_digest=SHA,correlation_id="C",workspace_root=root.as_posix(),canonical_plan_sha256=SHA,dependency_lock_sha256=SHA,
                authorization_contract_digests=(SHA,),read_scopes=(".",),mutable_scopes=("owned",),read_scope_sha256=scope_digest((".",)),
                mutable_scope_sha256=scope_digest(("owned",)),validation_profile_digests=(profile.profile_digest,)).sealed()
            service=ValidationService(ctx,catalog,process); result=service.execute("VP-TEST")
            self.assertEqual(result["exit_code"],0); self.assertEqual(result["stdout"].strip(),"ok")
            blocked=replace(ctx,validation_profile_digests=("b"*64,)).sealed()
            with self.assertRaises(ValidationServiceError): ValidationService(blocked,catalog,process).execute("VP-TEST")

    def test_status_and_validate_exact_surfaces(self)->None:
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); (root/"owned").mkdir(); profile=ValidationProfile("VP-T","UNIT",("python3","-c","pass"),".",10,()).sealed()
            policy=WorkspacePathPolicy(root,read_scopes=(".",),mutable_scopes=("owned",)); process=ProcessService(policy,shell_policy=ShellPolicy(allowed_executables=("python3",)))
            ctx=InvocationContext(schema_version="gch.full-mcp.invocation-context.v1",project_id="P",run_id="R",gate_id="G",lv_id="L",attempt=1,request_digest=SHA,
                correlation_id="C",workspace_root=root.as_posix(),canonical_plan_sha256=SHA,dependency_lock_sha256=SHA,authorization_contract_digests=(SHA,),
                read_scopes=(".",),mutable_scopes=("owned",),read_scope_sha256=scope_digest((".",)),mutable_scope_sha256=scope_digest(("owned",)),validation_profile_digests=(profile.profile_digest,)).sealed()
            record={"operation_request_id":"op-1","state":"COMPLETED","started_at":"2026-01-01T00:00:00Z","ended_at":"2026-01-01T00:00:01Z",
                    "result_digest":"d"*64,"audit_ref":"events/x","effect_id":"TE-1","exit_code":0,"security_block":False,"restore_equivalent":True}
            service=ValidationService(ctx,ValidationProfileCatalog([profile]),process,status_provider=lambda op: record if op=="op-1" else None)
            self.assertEqual(set(service.execution_status("op-1")),{"operation_request_id","state","started_at","ended_at","result_digest","audit_ref","effect_id"})
            verdict=service.validate("op-1",["RESULT_PRESENT","AUDIT_PRESENT","EXIT_ZERO","NO_SECURITY_BLOCK","RESTORE_EQUIVALENT"]); self.assertEqual(verdict["verdict"],"PASS")
            with self.assertRaises(ValidationServiceError): service.execution_status("missing")

    def test_project_local_lint_detects_trailing_whitespace_and_accepts_task_source(self)->None:
        repo=Path(__file__).resolve().parents[2]
        good=subprocess.run(["python3","scripts/full_mcp_lint.py","runtime/full_mcp/validation_service.py","runtime/full_mcp/validation_profiles.py"],cwd=repo,capture_output=True,text=True)
        self.assertEqual(good.returncode,0,good.stderr)
        with tempfile.NamedTemporaryFile("w",suffix=".py",delete=False) as handle:
            handle.write("x = 1  \n"); bad_path=handle.name
        try:
            bad=subprocess.run(["python3","scripts/full_mcp_lint.py",bad_path],cwd=repo,capture_output=True,text=True); self.assertEqual(bad.returncode,1)
        finally: Path(bad_path).unlink(missing_ok=True)
