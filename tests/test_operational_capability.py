from __future__ import annotations

import unittest
import hashlib, json, tempfile
from pathlib import Path
from dataclasses import replace
from unittest.mock import patch

from runtime.orchestrator.operational_capability import (
    DryRunExecutionContext, DryRunOperations, OperationalCapabilityError,
    FixtureApprovalBundle, FixtureModuleAdapters,
    run_module_backed_fixture_dry_run, run_operational_capability_dry_run,
)
from runtime.orchestrator.project_isolation import AssetManifest
from runtime.orchestrator.schemas import CapabilityRequirement
from runtime.orchestrator.skill_discovery import DiscoveryApproval, HTTPDiscoveryResponse, legacy_http_transport_contract
from runtime.orchestrator.skill_adoption import seal_project_install_approval
from runtime.orchestrator.skill_use_authorization import seal_project_use_approval
from runtime.orchestrator.candidate_content_resolver import ResolutionTransportContract
from runtime.orchestrator.lv_execution_package import canonical_json_bytes


PLAN = "a" * 64
STAGES = (
    "DISCOVERY_APPROVAL", "DISCOVERY", "RESOLUTION", "EVALUATION",
    "SUPPLY_CHAIN_REVIEW", "ADOPTION", "INSTALL_AUTHORIZATION", "INSTALL",
    "ATTESTATION", "USE_AUTHORIZATION", "USED_ASSETS",
)


def manifest(asset_id, capability, scope="project"):
    return AssetManifest(asset_id, scope, frozenset((capability,)), frozenset(("read",)), ("src/a.py",))


class OperationalCapabilityTests(unittest.TestCase):
    def setUp(self):
        self.requirement = CapabilityRequirement("cap", "G1", "LV1", ("read",), ("src/a.py",))
        self.context = DryRunExecutionContext("project", "G1", "LV1", PLAN, "/fixture/project")
        self.calls = []

    def operations(self, fail=""):
        def operation(stage):
            def call(inputs):
                self.calls.append(stage)
                if stage == fail:
                    return {"ok": False}
                value = {"ok": True, "stage": stage, "gate_passed": False}
                if stage == "INSTALL": value.update(artifact_digest="b" * 64)
                if stage == "ATTESTATION": value.update(attestation_digest="c" * 64)
                if stage == "USE_AUTHORIZATION":
                    value.update(candidate_id="owner/repo@skill", target=".agents/skills/skill",
                                 candidate_use_authorized=True, stable_asset_identifier="installed-skill:sha256:" + "d" * 64,
                                 authorization_digest="e" * 64)
                if stage == "USED_ASSETS":
                    value.update(stable_asset_identifier="installed-skill:sha256:" + "d" * 64)
                return value
            return call
        return DryRunOperations({stage: operation(stage) for stage in STAGES},
                                {stage: (lambda value: value.get("ok") is True) for stage in STAGES})

    def concrete_fixture(self, temp):
        root = Path(temp) / "project"; (root / ".agents" / "skills").mkdir(parents=True)
        repo = Path(temp) / "repo"; (repo / "skills" / "safe").mkdir(parents=True)
        skill = b"---\nname: safe\ndescription: safe fixture\n---\nRead tests.\n"
        (repo / "skills" / "safe" / "SKILL.md").write_bytes(skill)
        transport = legacy_http_transport_contract()
        payload = {"schema_version":"orchestration.skill-discovery.approval.v1","intent":"skill_discovery_read_only",
                   "classification":"dangerous","status":"ACTIVE","project_id":"project","gate_id":"G1","lv_id":"LV1",
                   "canonical_plan_sha256":PLAN,"discovery_contract_sha256":transport.contract_sha256}
        approval_path = root / "approval.json"
        approval_path.write_bytes(canonical_json_bytes({"payload":payload,"record_hash":hashlib.sha256(canonical_json_bytes(payload)).hexdigest()}))
        discovery_approval = DiscoveryApproval("skill_discovery_read_only","dangerous",True,"project","G1","LV1",
            "approval.json",hashlib.sha256(approval_path.read_bytes()).hexdigest(),PLAN,transport.contract_sha256)
        binding={"provider":"fixture","owner":"owner","repository":"repo","source_url":"file:///fixture/owner/repo",
                 "immutable_revision":"a"*40,"candidate_path":"skills/safe","source_evidence_reference":"fixture:index"}
        resolution=ResolutionTransportContract("LOCAL_FIXTURE","fixture","fixture","owner","repo",
            "file:///fixture/owner/repo","a"*40,"skills/safe","fixture:index",
            hashlib.sha256(canonical_json_bytes(binding)).hexdigest(), expected_skill_md_digest=hashlib.sha256(skill).hexdigest())
        def http(**kwargs):
            body=json.dumps({"count":1,"duration_ms":0,"query":"cap","searchType":"semantic","searchVersion":"1","skills":[{"id":"owner/repo@safe","name":"safe","skillId":"owner/repo@safe","installs":1,"source":"fixture"}]}).encode()
            return HTTPDiscoveryResponse(200,"application/json",body)
        metadata={"skill_md_exists":True,"license":"MIT","permissions":["read"],"owned_files":["tests/"],
                  "network":False,"shell":False,"package_install":False,"secret":False,"file_write":False,
                  "external_service":False,"paid_service":False,"deployment":False,"global_change":False,"destructive_action":False,
                  "external_write_scope_known":True,"credential_required":False,"project_applicable":True,"global_install_required":False}
        created = {}
        self.concrete_created = created
        def install_factory(evaluation, review, plan):
            approval = seal_project_install_approval(
                project_id="project", gate_id="G1", lv_id="LV1", intent="project_skill_install",
                candidate_id=evaluation.evidence["candidate_id"], evaluation_digest=evaluation.evidence["evidence_digest"],
                supply_chain_review_digest=review.review_digest, install_scope="project", canonical_plan_sha256=PLAN,
                status="ACTIVE", evidence_reference="sha256:" + plan.plan_digest)
            created["install"] = approval
            return approval
        def use_factory(attestation):
            approval = seal_project_use_approval(
                project_id="project", gate_id="G1", lv_id="LV1", candidate_id="owner/repo@safe",
                canonical_plan_sha256=PLAN, install_approval_digest=created["install"].approval_digest,
                attestation_digest=attestation.attestation_digest, status="ACTIVE",
                intent="project_skill_use", evidence_reference="fixture:use")
            created["use"] = approval
            return approval
        kwargs = {"context":DryRunExecutionContext("project","G1","LV1",PLAN,str(root)),
                  "requirement":CapabilityRequirement("cap","G1","LV1",("read",),("tests/",)),
                  "discovery_approval":discovery_approval,"discovery_transport":transport,
                  "resolution_transport":resolution,"http_executor":http,"fixture_repository_root":str(repo),
                  "project_root":str(root),"candidate_metadata":metadata,"permissions":("read",),"owned_files":("tests/",)}
        return root, kwargs, install_factory, use_factory

    def test_project_global_and_agent_fast_paths_call_no_gap_executor(self):
        cases = (
            ("PROJECT", [manifest("project-skill", "cap")], [], {}, "project-skill"),
            ("GLOBAL", [], [manifest("global-skill", "cap", "global")], {}, "global-skill"),
            ("AGENT", [], [], {"cap": object()}, "cap"),
        )
        for source, project, global_, agents, expected in cases:
            with self.subTest(source=source):
                result = run_operational_capability_dry_run(
                    context=self.context, requirement=self.requirement, project_assets=project,
                    global_assets=global_, agent_registry=agents, operations=self.operations())
                self.assertEqual(result.status, "READY_FOR_WORKER")
                self.assertEqual(result.runtime_selection.source, source)
                self.assertEqual(result.runtime_selection.asset_id, expected)
                self.assertEqual(self.calls, [])

    def test_gap_runs_complete_order_and_never_passes_gate_or_executes_skill(self):
        result = run_operational_capability_dry_run(
            context=self.context, requirement=self.requirement, operations=self.operations())
        self.assertEqual(tuple(self.calls), STAGES)
        self.assertTrue(result.worker_prerequisites_satisfied)
        self.assertFalse(result.gate_passed)
        self.assertTrue(result.runtime_selection.simulated)
        self.assertFalse(result.runtime_selection.execution_allowed_in_dry_run)

    def test_each_failure_short_circuits(self):
        for failed in STAGES:
            with self.subTest(stage=failed):
                self.calls = []
                result = run_operational_capability_dry_run(
                    context=self.context, requirement=self.requirement, operations=self.operations(failed))
                self.assertEqual(result.status, "BLOCKED")
                self.assertEqual(result.blocked_stage, failed)
                self.assertEqual(self.calls, list(STAGES[:STAGES.index(failed) + 1]))

    def test_resume_reuses_all_sealed_stages_without_duplicate_calls(self):
        checkpoint = {}
        first = run_operational_capability_dry_run(
            context=self.context, requirement=self.requirement, operations=self.operations(), checkpoint=checkpoint)
        self.assertEqual(first.status, "READY_FOR_WORKER")
        self.calls = []
        second = run_operational_capability_dry_run(
            context=self.context, requirement=self.requirement, operations=self.operations(), checkpoint=checkpoint)
        self.assertEqual(second.status, "READY_FOR_WORKER")
        self.assertEqual(self.calls, [])
        self.assertEqual(first.runtime_selection, second.runtime_selection)

    def test_partial_resume_does_not_repeat_discovery_or_install(self):
        checkpoint = {}
        run_operational_capability_dry_run(
            context=self.context, requirement=self.requirement, operations=self.operations(), checkpoint=checkpoint)
        for stop in ("DISCOVERY", "EVALUATION", "INSTALL", "USE_AUTHORIZATION"):
            partial = {stage: checkpoint[stage] for stage in STAGES[:STAGES.index(stop) + 1]}
            self.calls = []
            result = run_operational_capability_dry_run(
                context=self.context, requirement=self.requirement, operations=self.operations(), checkpoint=partial)
            self.assertEqual(result.status, "READY_FOR_WORKER")
            self.assertEqual(self.calls, list(STAGES[STAGES.index(stop) + 1:]))

    def test_stale_evidence_and_mutated_install_are_rejected(self):
        checkpoint = {}
        run_operational_capability_dry_run(
            context=self.context, requirement=self.requirement, operations=self.operations(), checkpoint=checkpoint)
        for stage in ("DISCOVERY", "INSTALL"):
            changed = {key: dict(value) for key, value in checkpoint.items()}
            changed[stage] = dict(changed[stage])
            changed[stage]["payload"] = {**changed[stage]["payload"], "mutated": True}
            self.calls = []
            result = run_operational_capability_dry_run(
                context=self.context, requirement=self.requirement, operations=self.operations(), checkpoint=changed)
            self.assertEqual(result.status, "BLOCKED")
            self.assertEqual(result.blocked_stage, stage)
            self.assertEqual(self.calls, [])

    def test_full_plan_context_cannot_enable_any_side_effect(self):
        for field in ("network_allowed", "repository_fetch_allowed", "live_install_allowed", "skill_execution_allowed"):
            with self.subTest(field=field), self.assertRaises(OperationalCapabilityError):
                run_operational_capability_dry_run(
                    context=replace(self.context, **{field: True}), requirement=self.requirement,
                    operations=self.operations())

    def test_module_backed_adapter_requires_explicit_sealed_verifiers(self):
        callback = lambda inputs: {"ok": True}
        adapters = FixtureModuleAdapters(*(callback for _ in range(9)))
        with self.assertRaises(OperationalCapabilityError):
            adapters.as_operations()

    def test_module_backed_approval_is_independent_and_fail_closed(self):
        calls = []

        class Approval:
            approval_digest = "f" * 64
            def valid(self):
                return True

        def stage(name):
            def operation(inputs):
                calls.append(name)
                return {"ok": True, "stage": name, "gate_passed": False,
                        "candidate_id": "owner/repo@skill",
                        "stable_asset_identifier": "installed-skill:sha256:" + "d" * 64,
                        "candidate_use_authorized": True,
                        "artifact_digest": "b" * 64,
                        "attestation_digest": "c" * 64,
                        "authorization_digest": "e" * 64,
                        "target": ".agents/skills/skill"}
            return operation

        verifier = {name: lambda value: value.get("ok") is True for name in STAGES}
        adapters = FixtureModuleAdapters(
            *(stage(name) for name in ("DISCOVERY", "RESOLUTION", "EVALUATION",
                                       "SUPPLY_CHAIN_REVIEW", "ADOPTION", "INSTALL",
                                       "ATTESTATION", "USE_AUTHORIZATION", "USED_ASSETS")),
            verifiers=verifier)
        # No discovery approval: the real adapter must stop before discovery.
        blocked = run_module_backed_fixture_dry_run(
            context=self.context, requirement=self.requirement, adapters=adapters,
            approvals=FixtureApprovalBundle())
        self.assertEqual(blocked.status, "BLOCKED")
        self.assertEqual(calls, [])
        # Discovery approval alone permits discovery but still blocks at install approval.
        calls.clear()
        partial = run_module_backed_fixture_dry_run(
            context=self.context, requirement=self.requirement, adapters=adapters,
            approvals=FixtureApprovalBundle(discovery=Approval()))
        self.assertEqual(partial.status, "BLOCKED")
        self.assertEqual(calls, ["DISCOVERY", "RESOLUTION", "EVALUATION",
                                 "SUPPLY_CHAIN_REVIEW", "ADOPTION"])

    def test_concrete_module_fan_in_reaches_real_evaluator_and_blocks_without_install(self):
        from runtime.orchestrator.operational_capability import run_concrete_module_fixture_dry_run
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "project"; (root / ".agents" / "skills").mkdir(parents=True)
            repo = Path(temp) / "repo"; (repo / "skills" / "safe").mkdir(parents=True)
            skill = b"---\nname: safe\ndescription: safe fixture\n---\nRead tests.\n"
            (repo / "skills" / "safe" / "SKILL.md").write_bytes(skill)
            transport = legacy_http_transport_contract()
            payload = {"schema_version":"orchestration.skill-discovery.approval.v1","intent":"skill_discovery_read_only",
                       "classification":"dangerous","status":"ACTIVE","project_id":"project","gate_id":"G1","lv_id":"LV1",
                       "canonical_plan_sha256":PLAN,"discovery_contract_sha256":transport.contract_sha256}
            approval_path = root / "approval.json"; approval_path.write_bytes(canonical_json_bytes({"payload":payload,"record_hash":hashlib.sha256(canonical_json_bytes(payload)).hexdigest()}))
            approval = DiscoveryApproval("skill_discovery_read_only","dangerous",True,"project","G1","LV1",
                                         "approval.json",hashlib.sha256(approval_path.read_bytes()).hexdigest(),PLAN,transport.contract_sha256)
            source_binding={"provider":"fixture","owner":"owner","repository":"repo","source_url":"file:///fixture/owner/repo",
                            "immutable_revision":"a"*40,"candidate_path":"skills/safe","source_evidence_reference":"fixture:index"}
            source_digest=hashlib.sha256(canonical_json_bytes(source_binding)).hexdigest()
            resolution_transport=ResolutionTransportContract("LOCAL_FIXTURE","fixture","fixture","owner","repo",
                "file:///fixture/owner/repo","a"*40,"skills/safe","fixture:index",source_digest,
                expected_skill_md_digest=hashlib.sha256(skill).hexdigest())
            def http_executor(**kwargs):
                body=json.dumps({"count":1,"duration_ms":0,"query":"cap","searchType":"semantic","searchVersion":"1","skills":[{"id":"owner/repo@safe","name":"safe","skillId":"owner/repo@safe","installs":1,"source":"fixture"}]}).encode()
                return HTTPDiscoveryResponse(200,"application/json",body)
            metadata={"skill_md_exists":True,"license":"MIT","permissions":["read"],"owned_files":["tests/"],
                      "network":False,"shell":False,"package_install":False,"secret":False,"file_write":False,
                      "external_service":False,"paid_service":False,"deployment":False,"global_change":False,"destructive_action":False,
                      "external_write_scope_known":True,"credential_required":False,"project_applicable":True,"global_install_required":False}
            result=run_concrete_module_fixture_dry_run(context=DryRunExecutionContext("project","G1","LV1",PLAN,str(root)),
                requirement=CapabilityRequirement("cap","G1","LV1",("read",),("tests/",)), discovery_approval=approval,
                discovery_transport=transport,resolution_transport=resolution_transport,http_executor=http_executor,
                fixture_repository_root=str(repo),project_root=str(root),candidate_metadata=metadata,permissions=("read",),owned_files=("tests/",))
            self.assertEqual(result.status,"BLOCKED")
            self.assertIn(result.blocked_stage,{"ADOPTION","INSTALL_AUTHORIZATION"})
            self.assertIn("EVALUATION",result.stage_records)
            self.assertIn("CONTENT_RESOLUTION",result.stage_records)
            metadata = None
            evaluation_blocked = run_concrete_module_fixture_dry_run(context=DryRunExecutionContext("project","G1","LV1",PLAN,str(root)),
                requirement=CapabilityRequirement("cap","G1","LV1",("read",),("tests/",)), discovery_approval=approval,
                discovery_transport=transport,resolution_transport=resolution_transport,http_executor=http_executor,
                fixture_repository_root=str(repo),project_root=str(root),candidate_metadata=metadata,permissions=("read",),owned_files=("tests/",))
            self.assertEqual(evaluation_blocked.blocked_stage, "EVALUATION")
            self.assertNotIn("ADOPTION", evaluation_blocked.stage_records)

    def test_concrete_gap_pipeline_reaches_runtime_selection_without_gate_pass(self):
        """Exercise every real lifecycle module using only fixture boundaries."""
        from runtime.orchestrator.operational_capability import run_concrete_module_fixture_dry_run
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "project"; (root / ".agents" / "skills").mkdir(parents=True)
            repo = Path(temp) / "repo"; (repo / "skills" / "safe").mkdir(parents=True)
            skill = b"---\nname: safe\ndescription: safe fixture\n---\nRead tests.\n"
            (repo / "skills" / "safe" / "SKILL.md").write_bytes(skill)
            transport = legacy_http_transport_contract()
            payload = {"schema_version":"orchestration.skill-discovery.approval.v1","intent":"skill_discovery_read_only",
                       "classification":"dangerous","status":"ACTIVE","project_id":"project","gate_id":"G1","lv_id":"LV1",
                       "canonical_plan_sha256":PLAN,"discovery_contract_sha256":transport.contract_sha256}
            approval_path = root / "approval.json"; approval_path.write_bytes(canonical_json_bytes({"payload":payload,"record_hash":hashlib.sha256(canonical_json_bytes(payload)).hexdigest()}))
            discovery_approval = DiscoveryApproval("skill_discovery_read_only","dangerous",True,"project","G1","LV1",
                                         "approval.json",hashlib.sha256(approval_path.read_bytes()).hexdigest(),PLAN,transport.contract_sha256)
            source_binding={"provider":"fixture","owner":"owner","repository":"repo","source_url":"file:///fixture/owner/repo",
                            "immutable_revision":"a"*40,"candidate_path":"skills/safe","source_evidence_reference":"fixture:index"}
            source_digest=hashlib.sha256(canonical_json_bytes(source_binding)).hexdigest()
            resolution_transport=ResolutionTransportContract("LOCAL_FIXTURE","fixture","fixture","owner","repo",
                "file:///fixture/owner/repo","a"*40,"skills/safe","fixture:index",source_digest,
                expected_skill_md_digest=hashlib.sha256(skill).hexdigest())
            def http_executor(**kwargs):
                body=json.dumps({"count":1,"duration_ms":0,"query":"cap","searchType":"semantic","searchVersion":"1","skills":[{"id":"owner/repo@safe","name":"safe","skillId":"owner/repo@safe","installs":1,"source":"fixture"}]}).encode()
                return HTTPDiscoveryResponse(200,"application/json",body)
            metadata={"skill_md_exists":True,"license":"MIT","permissions":["read"],"owned_files":["tests/"],
                      "network":False,"shell":False,"package_install":False,"secret":False,"file_write":False,
                      "external_service":False,"paid_service":False,"deployment":False,"global_change":False,"destructive_action":False,
                      "external_write_scope_known":True,"credential_required":False,"project_applicable":True,"global_install_required":False}
            install_approval_factory = lambda evaluation, review, plan: seal_project_install_approval(
                project_id="project", gate_id="G1", lv_id="LV1", intent="project_skill_install",
                candidate_id=evaluation.evidence["candidate_id"], evaluation_digest=evaluation.evidence["evidence_digest"],
                supply_chain_review_digest=review.review_digest, install_scope="project", canonical_plan_sha256=PLAN,
                status="ACTIVE", evidence_reference="sha256:" + plan.plan_digest)
            def use_approval_factory(attestation):
                return seal_project_use_approval(project_id="project", gate_id="G1", lv_id="LV1",
                    candidate_id="owner/repo@safe", canonical_plan_sha256=PLAN,
                    install_approval_digest=created_install.approval_digest,
                    attestation_digest=attestation.attestation_digest, status="ACTIVE",
                    intent="project_skill_use", evidence_reference="fixture:use")
            created_install = None
            def install_factory(evaluation, review, plan):
                nonlocal created_install
                created_install = seal_project_install_approval(
                    project_id="project", gate_id="G1", lv_id="LV1", intent="project_skill_install",
                    candidate_id=evaluation.evidence["candidate_id"], evaluation_digest=evaluation.evidence["evidence_digest"],
                    supply_chain_review_digest=review.review_digest, install_scope="project", canonical_plan_sha256=PLAN,
                    status="ACTIVE", evidence_reference="sha256:" + plan.plan_digest)
                return created_install
            run_context = DryRunExecutionContext("project","G1","LV1",PLAN,str(root))
            # A real install approval is sufficient to reach installation, but
            # never implicitly grants use authorization.
            blocked_use = run_concrete_module_fixture_dry_run(context=run_context,
                requirement=CapabilityRequirement("cap","G1","LV1",("read",),("tests/",)), discovery_approval=discovery_approval,
                discovery_transport=transport,resolution_transport=resolution_transport,http_executor=http_executor,
                install_approval_factory=install_factory,
                fixture_repository_root=str(repo),project_root=str(root),candidate_metadata=metadata,permissions=("read",),owned_files=("tests/",))
            self.assertEqual(blocked_use.status, "BLOCKED")
            self.assertEqual(blocked_use.blocked_stage, "USE_AUTHORIZATION")
            self.assertEqual(blocked_use.stage_records["INSTALL"]["payload"]["install_status"], "INSTALL_COMPLETED")
            self.assertNotIn("USED_ASSETS", blocked_use.stage_records)
            result=run_concrete_module_fixture_dry_run(context=run_context,
                requirement=CapabilityRequirement("cap","G1","LV1",("read",),("tests/",)), discovery_approval=discovery_approval,
                discovery_transport=transport,resolution_transport=resolution_transport,http_executor=http_executor,
                install_approval_factory=install_factory, use_approval_factory=use_approval_factory,
                fixture_repository_root=str(repo),project_root=str(root),candidate_metadata=metadata,permissions=("read",),owned_files=("tests/",))
            self.assertEqual(result.status, "READY_FOR_WORKER", result.blocked_reason)
            self.assertTrue(result.worker_prerequisites_satisfied)
            self.assertFalse(result.gate_passed)
            self.assertTrue(result.runtime_selection.simulated)
            self.assertFalse(result.runtime_selection.execution_allowed_in_dry_run)
            self.assertTrue(result.stage_records["USE_AUTHORIZATION"]["payload"]["candidate_use_authorized"])
            self.assertIn(result.stage_records["INSTALL"]["payload"]["install_status"], {"INSTALL_COMPLETED", "IDENTICAL"})
            self.assertIn("ATTESTATION", result.stage_records)
            self.assertTrue(result.stage_records["ATTESTATION"]["payload"].get("attestation_digest"))
            self.assertTrue(result.stage_records["USED_ASSETS"]["payload"]["stable_asset_identifier"].startswith("installed-skill:sha256:"))
            self.assertTrue((root / ".agents" / "skills" / "safe").is_dir())

    def test_concrete_install_approval_failure_never_invokes_installer(self):
        from runtime.orchestrator.operational_capability import run_concrete_module_fixture_dry_run
        ledger = {"used_assets":["unrelated:asset"], "use_authorized_candidates":["unrelated"],
                  "use_authorization_evidence_references":["fixture:unrelated"], "gate_passed":False}
        before = {key:list(value) if isinstance(value, list) else value for key, value in ledger.items()}
        with tempfile.TemporaryDirectory() as temp:
            root, kwargs, _, _ = self.concrete_fixture(temp)
            destination = root / ".agents" / "skills" / "safe"
            with patch("runtime.orchestrator.operational_capability.install_project_skill", wraps=__import__(
                    "runtime.orchestrator.skill_installer", fromlist=["install_project_skill"]).install_project_skill) as installer, \
                 patch("runtime.orchestrator.operational_capability.attest_installed_artifact") as attester, \
                 patch("runtime.orchestrator.operational_capability.authorize_candidate_use") as authorizer:
                result = run_concrete_module_fixture_dry_run(**kwargs, install_approval=None, ledger=ledger)
            self.assertEqual(result.status, "BLOCKED")
            self.assertIn(result.blocked_stage, {"ADOPTION", "INSTALL_AUTHORIZATION"})
            self.assertNotIn("INSTALL_AUTHORIZATION", result.stage_records)
            installer.assert_not_called(); attester.assert_not_called(); authorizer.assert_not_called()
            self.assertFalse(destination.exists())
            self.assertNotIn("INSTALL", result.stage_records)
            self.assertIsNone(result.runtime_selection); self.assertFalse(result.gate_passed)
            self.assertEqual(ledger, before)

    def test_concrete_attestation_failure_never_authorizes_or_transitions_asset(self):
        from runtime.orchestrator.operational_capability import run_concrete_module_fixture_dry_run
        from runtime.orchestrator.skill_use_authorization import attest_installed_artifact as actual_attest
        ledger = {"used_assets":["unrelated:asset"], "use_authorized_candidates":["unrelated"],
                  "use_authorization_evidence_references":["fixture:unrelated"], "gate_passed":False}
        before = {key:list(value) if isinstance(value, list) else value for key, value in ledger.items()}
        with tempfile.TemporaryDirectory() as temp:
            root, kwargs, install_factory, use_factory = self.concrete_fixture(temp)
            def tamper_then_attest(request, install, *, timestamp):
                (root / ".agents" / "skills" / "safe" / "SKILL.md").write_bytes(b"tampered fixture\n")
                return actual_attest(request, install, timestamp=timestamp)
            with patch("runtime.orchestrator.operational_capability.attest_installed_artifact", side_effect=tamper_then_attest) as attester, \
                 patch("runtime.orchestrator.operational_capability.authorize_candidate_use") as authorizer, \
                 patch("runtime.orchestrator.operational_capability.transition_used_asset") as transition:
                result = run_concrete_module_fixture_dry_run(
                    **kwargs, install_approval_factory=install_factory, use_approval_factory=use_factory, ledger=ledger)
            self.assertEqual(result.status, "BLOCKED")
            self.assertEqual(result.blocked_stage, "ATTESTATION")
            self.assertEqual(result.stage_records["INSTALL"]["payload"]["install_status"], "INSTALL_COMPLETED")
            attester.assert_called_once(); authorizer.assert_not_called(); transition.assert_not_called()
            self.assertNotIn("ATTESTATION", result.stage_records)
            self.assertNotIn("USE_AUTHORIZATION", result.stage_records)
            self.assertNotIn("USED_ASSETS", result.stage_records)
            self.assertIsNone(result.runtime_selection); self.assertFalse(result.gate_passed)
            self.assertEqual(ledger, before)

    def test_concrete_use_approval_failure_never_transitions_used_asset(self):
        from runtime.orchestrator.operational_capability import run_concrete_module_fixture_dry_run
        from runtime.orchestrator.skill_use_authorization import authorize_candidate_use as actual_authorize
        ledger = {"used_assets":[], "use_authorized_candidates":[],
                  "use_authorization_evidence_references":[], "gate_passed":False}
        before = {key:list(value) if isinstance(value, list) else value for key, value in ledger.items()}
        with tempfile.TemporaryDirectory() as temp:
            _, kwargs, install_factory, _ = self.concrete_fixture(temp)
            authorizations = []
            def capture_authorization(*args, **call_kwargs):
                authorization = actual_authorize(*args, **call_kwargs)
                authorizations.append(authorization)
                return authorization
            with patch("runtime.orchestrator.operational_capability.authorize_candidate_use", side_effect=capture_authorization) as authorizer, \
                 patch("runtime.orchestrator.operational_capability.transition_used_asset") as transition:
                result = run_concrete_module_fixture_dry_run(
                    **kwargs, install_approval_factory=install_factory, use_approval=None, ledger=ledger)
            self.assertEqual(result.status, "BLOCKED")
            self.assertEqual(result.blocked_stage, "USE_AUTHORIZATION")
            self.assertIn("ATTESTATION", result.stage_records)
            authorizer.assert_called_once(); transition.assert_not_called()
            self.assertFalse(authorizations[0].candidate_use_authorized)
            self.assertNotIn("USE_AUTHORIZATION", result.stage_records)
            self.assertNotIn("USED_ASSETS", result.stage_records)
            self.assertIsNone(result.runtime_selection); self.assertFalse(result.gate_passed)
            self.assertEqual(ledger, before)

    def test_concrete_discovery_contract_failure_short_circuits_before_resolver(self):
        from runtime.orchestrator.operational_capability import run_concrete_module_fixture_dry_run
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)/"project"; (root/".agents"/"skills").mkdir(parents=True)
            repo=Path(temp)/"repo"; (repo/"skills"/"safe").mkdir(parents=True)
            (repo/"skills"/"safe"/"SKILL.md").write_text("---\nname: safe\n---\nRead.\n")
            transport=legacy_http_transport_contract()
            bad=DiscoveryApproval("skill_discovery_read_only","dangerous",False,"project","G1","LV1","missing.json","f"*64,PLAN,transport.contract_sha256)
            resolution=ResolutionTransportContract("LOCAL_FIXTURE","fixture","fixture","owner","repo","file:///fixture/owner/repo","a"*40,"skills/safe","fixture:index","c"*64)
            called=[]
            def http(**kwargs): called.append(True); return HTTPDiscoveryResponse(200,"application/json",b"{}")
            result=run_concrete_module_fixture_dry_run(context=self.context,requirement=self.requirement,
                discovery_approval=bad,discovery_transport=transport,resolution_transport=resolution,http_executor=http,
                fixture_repository_root=str(repo),project_root=str(root),candidate_metadata={},permissions=("read",),owned_files=("src/a.py",))
            self.assertEqual(result.status,"BLOCKED"); self.assertEqual(result.blocked_stage,"DISCOVERY"); self.assertEqual(called,[])

    def test_concrete_resolver_failure_short_circuits_evaluator(self):
        """A resolver/provenance failure must stop before the real evaluator."""
        from runtime.orchestrator.operational_capability import run_concrete_module_fixture_dry_run
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "project"; (root / ".agents" / "skills").mkdir(parents=True)
            repo = Path(temp) / "repo"; (repo / "skills" / "safe").mkdir(parents=True)
            skill = b"---\nname: safe\n---\nRead.\n"; (repo / "skills" / "safe" / "SKILL.md").write_bytes(skill)
            transport = legacy_http_transport_contract()
            payload = {"schema_version":"orchestration.skill-discovery.approval.v1","intent":"skill_discovery_read_only","classification":"dangerous","status":"ACTIVE","project_id":"project","gate_id":"G1","lv_id":"LV1","canonical_plan_sha256":PLAN,"discovery_contract_sha256":transport.contract_sha256}
            approval_path = root / "approval.json"; approval_path.write_bytes(canonical_json_bytes({"payload":payload,"record_hash":hashlib.sha256(canonical_json_bytes(payload)).hexdigest()}))
            approval = DiscoveryApproval("skill_discovery_read_only","dangerous",True,"project","G1","LV1","approval.json",hashlib.sha256(approval_path.read_bytes()).hexdigest(),PLAN,transport.contract_sha256)
            binding = {"provider":"fixture","owner":"owner","repository":"repo","source_url":"file:///fixture/owner/repo","immutable_revision":"a"*40,"candidate_path":"skills/safe","source_evidence_reference":"fixture:index"}
            source_digest = hashlib.sha256(canonical_json_bytes(binding)).hexdigest()
            resolution = ResolutionTransportContract("LOCAL_FIXTURE","fixture","fixture","owner","repo","file:///fixture/owner/repo","a"*40,"skills/safe","fixture:index",source_digest,expected_skill_md_digest=hashlib.sha256(skill).hexdigest())
            def http(**kwargs):
                body=json.dumps({"count":1,"duration_ms":0,"query":"cap","searchType":"semantic","searchVersion":"1","skills":[{"id":"owner/repo@safe","name":"safe","skillId":"owner/repo@safe","installs":1,"source":"fixture"}]}).encode(); return HTTPDiscoveryResponse(200,"application/json",body)
            with patch("runtime.orchestrator.operational_capability.resolve_candidate_content", side_effect=OperationalCapabilityError("CONTENT_RESOLUTION: provenance failure")) as resolver, patch("runtime.orchestrator.operational_capability.evaluate_candidate") as evaluator:
                result = run_concrete_module_fixture_dry_run(context=self.context, requirement=self.requirement, discovery_approval=approval, discovery_transport=transport, resolution_transport=resolution, http_executor=http, fixture_repository_root=str(repo), project_root=str(root), candidate_metadata={}, permissions=("read",), owned_files=("src/a.py",))
            self.assertEqual(result.status, "BLOCKED"); self.assertEqual(result.blocked_stage, "CONTENT_RESOLUTION"); resolver.assert_called_once(); evaluator.assert_not_called()

if __name__ == "__main__":
    unittest.main()
