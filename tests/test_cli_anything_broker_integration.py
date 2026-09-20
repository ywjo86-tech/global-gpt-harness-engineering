import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from runtime.tool_implementation.manifest import seal_manifest, qualify_manifest
from runtime.orchestrator.production_tool_transport import (
    qualified_cli_registered_operation, qualified_cli_launcher,
)
from runtime.orchestrator.tool_authorization import (
    ClosedOperationRegistry, OperationIdentity, SingleToolBroker,
    ToolAuthorizationContract, ToolAuthorizationError, ToolEffectJournal,
)

PACKAGE='a'*64; PLAN='b'*64; REQ='c'*64; SCOPE='d'*64; VERIFIER='e'*64

def write_cli(root: Path, body: str) -> Path:
    p=root/'qualified-cli'; p.write_text('#!/usr/bin/python3\n'+body); p.chmod(0o700); return p

def qualified_manifest(exe: Path, *, effect='READ_ONLY', input_schema=None):
    schema=input_schema or {'type':'object','properties':{'subcommand':{'type':'string'}},'required':['subcommand'],'additionalProperties':False}
    m=seal_manifest({'manifest_id':'CLI_TEST_V1','state':'CANDIDATE','upstream_url':'https://github.com/HKUDS/CLI-Anything.git','upstream_ref':'HEAD','upstream_commit':'810c18b0d1ab9b234bc996c9fd999318523a3ef0','generated_artifact_sha256':hashlib.sha256(exe.read_bytes()).hexdigest(),'allowed_argv0':str(exe),'allowed_subcommands':('inspect','write'),'input_schema':schema,'output_schema':{'type':'object','properties':{'status':{'type':'string'}},'required':['status'],'additionalProperties':False},'effect_class':effect,'verifier_sha256':VERIFIER,'generated_skill_qualified':False,'generated_skill_qualification_sha256':'','qualification_evidence_sha256':'','manifest_sha256':''})
    return qualify_manifest(m,'f'*64)

def contract(op):
    return ToolAuthorizationContract(contract_id='TAC_CLI_V1',contract_version='tool-authorization.v1',contract_status='ACTIVE',worker_task_id='TASK_CLI',requirement_refs=('REQ_CLI',),plan_task_refs=('TASK_012',),operation_class_id=op.operation_class_id,capability_class=op.capability_class,operation_intent=op.operation_intent,requirement_binding='REQUIRED',scope_binding='IN_SCOPE',scope_authorization_source='USER_DECISION',authorization_decision_ref='CLI_APPROVAL',validity_scope='TASK_ONLY',security_obligation_profile='CLI_BOUNDED_V1',approval_authority='USER_DECISION',project_id='PROJECT_CLI',gate_id='GATE_CLI',lv_id='LV_CLI',run_id='RUN_CLI',canonical_plan_sha256=PLAN,requirement_digest=REQ,owned_scope_sha256=SCOPE,package_binding_sha256=PACKAGE).sealed()

def identity(op):
    return OperationIdentity(op.operation_registration_id,'DISPATCH_CLI','CALLSITE_CLI',op.operation_class_id,'TASK_CLI','ACTION_CLI','PROJECT_CLI','GATE_CLI','LV_CLI','RUN_CLI',PLAN,REQ,PACKAGE,SCOPE)

def broker(root: Path, manifest, verifier, *, with_contract=True):
    op=qualified_cli_registered_operation(manifest)
    journal=ToolEffectJournal(root/'journal')
    b=SingleToolBroker(registry=ClosedOperationRegistry((op,)),contracts={op.operation_class_id:contract(op)} if with_contract else {},journal=journal,launchers={op.operation_class_id:qualified_cli_launcher(manifest,cwd=root,verifier_sha256=VERIFIER,artifact_verifier=verifier)},security_scan=lambda _: True)
    return b,journal,op

class CliAnythingBrokerTests(unittest.TestCase):
    def test_read_only_cli_runs_only_through_broker_and_journal(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); exe=write_cli(root,'import json\nprint(json.dumps({"status":"READ_OK"}))\n'); m=qualified_manifest(exe); b,j,op=broker(root,m,lambda result,cwd: result['status']=='READ_OK')
            bounded,private=b.execute_with_private_result(identity(op),{'subcommand':'inspect'})
            self.assertEqual(private,{'status':'READ_OK'}); self.assertEqual(bounded['security_status'],'PASS')
            self.assertEqual(j.recovery_state(identity(op)),'COMPLETED_NO_RERUN')

    def test_state_change_fixture_is_authorized_then_artifact_verified(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); exe=write_cli(root,'import json,sys\np=[x.split("=",1)[1] for x in sys.argv if x.startswith("--path=")][0]\nopen(p,"w").write("bounded")\nprint(json.dumps({"status":"WROTE"}))\n')
            schema={'type':'object','properties':{'subcommand':{'type':'string'},'path':{'type':'string','x-cli-kind':'relative_path'}},'required':['subcommand','path'],'additionalProperties':False}; m=qualified_manifest(exe,effect='PROJECT_WRITE',input_schema=schema)
            b,j,op=broker(root,m,lambda result,cwd: result['status']=='WROTE' and (cwd/'artifact.txt').read_text()=='bounded')
            b.execute_with_private_result(identity(op),{'subcommand':'write','path':'artifact.txt'}); self.assertEqual((root/'artifact.txt').read_text(),'bounded'); self.assertEqual(j.recovery_state(identity(op)),'COMPLETED_NO_RERUN')

    def test_authorization_failure_never_launches_cli(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); marker=root/'launched'; exe=write_cli(root,f'open({str(marker)!r},"w").write("x")\nimport json\nprint(json.dumps({{"status":"OK"}}))\n'); m=qualified_manifest(exe); b,_,op=broker(root,m,lambda *_: True,with_contract=False)
            with self.assertRaises(ToolAuthorizationError): b.execute_with_private_result(identity(op),{'subcommand':'inspect'})
            self.assertFalse(marker.exists())

    def test_duplicate_and_ambiguous_recovery_fail_closed(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); exe=write_cli(root,'import json\nprint(json.dumps({"status":"OK"}))\n'); m=qualified_manifest(exe); b,j,op=broker(root,m,lambda *_: True); ident=identity(op)
            b.execute_with_private_result(ident,{'subcommand':'inspect'})
            with self.assertRaises(ToolAuthorizationError): b.execute_with_private_result(ident,{'subcommand':'inspect'})
            op2=qualified_cli_registered_operation(m); ident2=OperationIdentity(op2.operation_registration_id,'DISPATCH_OTHER','CALLSITE_CLI',op2.operation_class_id,'TASK_CLI','ACTION_OTHER','PROJECT_CLI','GATE_CLI','LV_CLI','RUN_CLI',PLAN,REQ,PACKAGE,SCOPE)
            j.begin(ident2,{'authorization_status':'AUTHORIZED'}); self.assertEqual(j.recovery_state(ident2),'BLOCKED_RECOVERY_AMBIGUOUS')

    def test_artifact_verification_failure_records_failed_receipt(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); exe=write_cli(root,'import json\nprint(json.dumps({"status":"OK"}))\n'); m=qualified_manifest(exe); b,j,op=broker(root,m,lambda *_: False); ident=identity(op)
            with self.assertRaises(ToolAuthorizationError): b.execute_with_private_result(ident,{'subcommand':'inspect'})
            receipt=json.loads((root/'journal'/f'{ident.effect_id}.receipt.json').read_text())
            self.assertEqual(receipt['execution_status'],'FAILED'); self.assertEqual(receipt['security_status'],'BLOCK')

    def test_bad_verifier_path_and_unqualified_manifest_fail_closed(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); exe=write_cli(root,'import json\nprint(json.dumps({"status":"OK"}))\n'); m=qualified_manifest(exe)
            with self.assertRaises(ToolAuthorizationError): qualified_cli_launcher(m,cwd=root,verifier_sha256='0'*64,artifact_verifier=lambda *_: True)
            candidate=seal_manifest({**{k:getattr(m,k) for k in m.__dataclass_fields__},'state':'CANDIDATE','qualification_evidence_sha256':'','manifest_sha256':''})
            with self.assertRaises(ToolAuthorizationError): qualified_cli_registered_operation(candidate)

    def test_unsafe_argument_and_arbitrary_command_do_not_create_artifact(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); exe=write_cli(root,'import json\nprint(json.dumps({"status":"OK"}))\n'); schema={'type':'object','properties':{'subcommand':{'type':'string'},'path':{'type':'string','x-cli-kind':'relative_path'}},'required':['subcommand','path'],'additionalProperties':False}; m=qualified_manifest(exe,input_schema=schema); b,_,op=broker(root,m,lambda *_: True)
            with self.assertRaises(ToolAuthorizationError): b.execute_with_private_result(identity(op),{'subcommand':'inspect','path':'../escape'})
            ident2=OperationIdentity(op.operation_registration_id,'DISPATCH_2','CALLSITE_CLI',op.operation_class_id,'TASK_CLI','ACTION_2','PROJECT_CLI','GATE_CLI','LV_CLI','RUN_CLI',PLAN,REQ,PACKAGE,SCOPE)
            with self.assertRaises(ToolAuthorizationError): b.execute_with_private_result(ident2,{'subcommand':'inspect','path':'safe','command':'id'})
            self.assertFalse((root.parent/'escape').exists())

if __name__=='__main__': unittest.main()
