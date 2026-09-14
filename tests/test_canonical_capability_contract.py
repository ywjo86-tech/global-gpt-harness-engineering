from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from dataclasses import asdict, replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from runtime.orchestrator.gate_orchestrator import (
    FULL_PLAN, GateLV, GateOrchestrationError, GatePlan, create_gate_authorization, execute_gate, load_gate_plan,
)
from runtime.orchestrator.gate_controller import GateControllerAdapters
from runtime.orchestrator.operational_capability import (
    OperationalCapabilityError, derive_capability_requirements, load_capability_approval,
    production_inventory_sources, require_full_plan_capability_contract,
)
from runtime.orchestrator.project_isolation import ProjectIsolation
from runtime.orchestrator.skill_adoption import seal_project_install_approval
from runtime.orchestrator.skill_discovery import DiscoveryApproval
from runtime.orchestrator.skill_use_authorization import seal_project_use_approval


PLAN_SHA = "a" * 64
SOURCE_REF = "gate/GATE-1/lv/LV-1/capability_contract/requirements/0"


def contract(mode="REQUIRED", *, version="v1", capability_id="python.testing",
             permissions=None, source_ref=SOURCE_REF, count=1):
    permissions = ["read"] if permissions is None else permissions
    requirements = [] if mode == "DECLARED_NONE" else [
        {"capability_id": capability_id, "required_permissions": permissions, "source_ref": source_ref}
        for _ in range(count)
    ]
    return {"version": version, "mode": mode, "requirements": requirements}


def plan(capability_contract=...):
    lv = GateLV("GATE-1", "LV-1", 1, "test", [], ["tests/"], ["pass"], "sequential", ["tests/test_x.py"],
                None if capability_contract is ... else capability_contract)
    return GatePlan("project", "/fixture/project", "GATE-1", "PLAN.md", PLAN_SHA, [lv])


class CanonicalCapabilityContractTests(unittest.TestCase):
    def test_undeclared_declared_none_and_required_are_distinct(self):
        self.assertEqual(derive_capability_requirements(plan(), "LV-1").status, "UNDECLARED")
        none = derive_capability_requirements(plan(contract("DECLARED_NONE")), "LV-1")
        self.assertEqual(none.status, "NO_CAPABILITY_REQUIREMENT"); self.assertEqual(none.envelopes, ())
        required = derive_capability_requirements(plan(contract()), "LV-1")
        self.assertEqual(required.status, "REQUIRED"); self.assertEqual(len(required.envelopes), 1)

    def test_full_plan_undeclared_is_blocked_except_legacy_test_only(self):
        derivation = derive_capability_requirements(plan(), "LV-1")
        with self.assertRaisesRegex(OperationalCapabilityError, "UNDECLARED"):
            require_full_plan_capability_contract(derivation)
        require_full_plan_capability_contract(derivation, legacy_test_only=True)

    def test_execute_gate_full_plan_undeclared_is_blocked(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)/"project"; root.mkdir()
            def stage(status):
                return lambda context: {"status":status,"exit_code":0,"evidence_sha256":"a"*64,"hard_stop":True}
            adapters=GateControllerAdapters(stage("SEALED"),stage("READY"),stage("COMPLETED"),stage("PASS"),
                stage("PASS"),stage("CHECKPOINTED"),stage("EXITED"),stage("SEALED"))
            with patch("runtime.orchestrator.gate_orchestrator.load_gate_plan",return_value=plan()), \
                 patch("runtime.orchestrator.gate_orchestrator.validate_global_gate_bindings"), \
                 patch("runtime.orchestrator.gate_orchestrator.load_approved_authorization",return_value=create_gate_authorization(
                     plan(), "AUTH-UNDECLARED", mode=FULL_PLAN, full_plan_opt_in=True, project_final_validation=True)), \
                 self.assertRaisesRegex(Exception,"capability prerequisite blocked"):
                execute_gate(root,"GATE-1","run",harness_root=Path(temp),approval_evidence="unused",
                    requirements_sha256="b"*64,branch="main",head="c"*40,mode=FULL_PLAN,adapters=adapters)

    def test_declared_none_must_be_exact_and_empty(self):
        malformed = {**contract("DECLARED_NONE"), "requirements":[{"capability_id":"x"}]}
        self.assertEqual(derive_capability_requirements(plan(malformed), "LV-1").status, "BLOCKED")

    def test_required_fields_version_and_multiple_are_fail_closed(self):
        cases = (
            contract(capability_id=""), contract(permissions=[]), contract(source_ref=""),
            contract(version="v2"), {"version":"v1","mode":"REQUIRED","requirements":[]},
        )
        for value in cases:
            with self.subTest(value=value):
                self.assertEqual(derive_capability_requirements(plan(value), "LV-1").status, "BLOCKED")
        self.assertEqual(derive_capability_requirements(plan(contract(count=2)), "LV-1").status,
                         "ESCALATION_REQUIRED")

    def test_envelope_binds_plan_owned_files_execution_and_source(self):
        derived = derive_capability_requirements(plan(contract()), "LV-1")
        envelope = derived.envelopes[0]
        self.assertTrue(envelope.valid(project_id="project", gate_id="GATE-1", lv_id="LV-1",
            canonical_plan_sha256=PLAN_SHA, owned_files=["tests/"], execution="sequential"))
        self.assertEqual(envelope.requirement(["tests/"]).required_permissions, ("read",))
        for values in (
            {"canonical_plan_sha256":"b"*64}, {"owned_files":["docs/"]}, {"execution":"parallel"},
        ):
            args = dict(project_id="project", gate_id="GATE-1", lv_id="LV-1",
                canonical_plan_sha256=PLAN_SHA, owned_files=["tests/"], execution="sequential")
            args.update(values); self.assertFalse(envelope.valid(**args))

    def test_envelope_permission_and_source_tamper_invalidates_digest(self):
        envelope = derive_capability_requirements(plan(contract()), "LV-1").envelopes[0]
        common = dict(project_id="project", gate_id="GATE-1", lv_id="LV-1",
                      canonical_plan_sha256=PLAN_SHA, owned_files=["tests/"], execution="sequential")
        self.assertFalse(replace(envelope, required_permissions=("write",)).valid(**common))
        self.assertFalse(replace(envelope, source_declaration_ref="other").valid(**common))

    def test_legacy_parser_preserves_undeclared_state(self):
        text = """### Gate 1\n\n| ID | 작업 | 대상 | 완료조건 |\n| --- | --- | --- | --- |\n| LV-1 | test | `tests/a.py` | pass |\n\n| ID | depends_on | execution | owned_files | input / exit_check |\n| --- | --- | --- | --- | --- |\n| LV-1 | Gate 0 | sequential | `tests/a.py` | pass |\n"""
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)/"project"; root.mkdir(); source=root/"PLAN.md"; source.write_text(text)
            mapping=SimpleNamespace(canonical_source=source,canonical_sha256=hashlib.sha256(source.read_bytes()).hexdigest())
            with patch("runtime.orchestrator.gate_orchestrator.load_project_mapping",return_value=mapping):
                parsed=load_gate_plan(root,"GATE-1")
        self.assertIsNone(parsed.lvs[0].capability_contract)
        self.assertEqual(derive_capability_requirements(parsed,"LV-1").status,"UNDECLARED")

    def test_parser_reads_versioned_capability_table(self):
        text = f"""### Gate 1\n\n| ID | 작업 | 대상 | 완료조건 |\n| --- | --- | --- | --- |\n| LV-1 | test | `tests/a.py` | pass |\n\n| ID | depends_on | execution | owned_files | input / exit_check |\n| --- | --- | --- | --- | --- |\n| LV-1 | Gate 0 | sequential | `tests/a.py` | pass |\n\n| ID | capability_contract_version | capability_mode | capability_id | required_permissions | source_ref |\n| --- | --- | --- | --- | --- | --- |\n| LV-1 | v1 | REQUIRED | python.testing | read | {SOURCE_REF} |\n"""
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)/"project"; root.mkdir(); source=root/"PLAN.md"; source.write_text(text)
            mapping=SimpleNamespace(canonical_source=source,canonical_sha256=hashlib.sha256(source.read_bytes()).hexdigest())
            with patch("runtime.orchestrator.gate_orchestrator.load_project_mapping",return_value=mapping):
                parsed=load_gate_plan(root,"GATE-1")
        self.assertEqual(derive_capability_requirements(parsed,"LV-1").status,"REQUIRED")

    def test_actual_approval_contract_loader_and_boolean_rejection(self):
        with tempfile.TemporaryDirectory() as temp:
            namespace=Path(temp)/"namespace"; namespace.mkdir()
            root=Path(temp)/"project"; root.mkdir()
            isolation=ProjectIsolation(namespace,root,"project","project",{"project":"project"})
            install=seal_project_install_approval(project_id="project",gate_id="GATE-1",lv_id="LV-1",
                intent="project_skill_install",candidate_id="owner/repo@safe",evaluation_digest="b"*64,
                supply_chain_review_digest="c"*64,install_scope="project",canonical_plan_sha256=PLAN_SHA,
                status="ACTIVE",evidence_reference="fixture:install")
            use=seal_project_use_approval(project_id="project",gate_id="GATE-1",lv_id="LV-1",
                candidate_id="owner/repo@safe",canonical_plan_sha256=PLAN_SHA,install_approval_digest=install.approval_digest,
                attestation_digest="d"*64,status="ACTIVE",intent="project_skill_use",evidence_reference="fixture:use")
            discovery=DiscoveryApproval("skill_discovery_read_only","dangerous",True,"project","GATE-1","LV-1",
                "approval.json","e"*64,PLAN_SHA,"f"*64)
            for name,value,intent in (("install.json",install,"project_skill_install"),("use.json",use,"project_skill_use"),
                                      ("discovery.json",discovery,"skill_discovery_read_only")):
                serialized=json.dumps(asdict(value)).encode()
                isolation.write_exclusive("approval",name,serialized)
                loaded=load_capability_approval(isolation,name,intent=intent,project_id="project",gate_id="GATE-1",
                    lv_id="LV-1",canonical_plan_sha256=PLAN_SHA,evidence_digest=hashlib.sha256(serialized).hexdigest(),
                    candidate_id="" if intent.startswith("skill_") else "owner/repo@safe")
                self.assertEqual(loaded,value)
            isolation.write_exclusive("approval","boolean.json",b"true")
            with self.assertRaises(OperationalCapabilityError):
                load_capability_approval(isolation,"boolean.json",intent="project_skill_install",project_id="project",
                    gate_id="GATE-1",lv_id="LV-1",canonical_plan_sha256=PLAN_SHA,
                    evidence_digest=hashlib.sha256(b"true").hexdigest())

    def test_project_global_agent_inventory_sources_and_unknown_fail_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            namespace=Path(temp)/"namespace"; namespace.mkdir()
            root=Path(temp)/"project"; root.mkdir()
            isolation=ProjectIsolation(namespace,root,"project","project",{"project":"project"})
            project_value={"asset_id":"p","scope":"project","capabilities":["cap"],"permissions":["read"],"owned_files":["tests/"]}
            global_value={"asset_id":"g","scope":"global","capabilities":["cap"],"permissions":["read"],"owned_files":["tests/"]}
            project_raw=json.dumps(project_value,sort_keys=True).encode(); global_raw=json.dumps(global_value,sort_keys=True).encode()
            isolation.write_exclusive("artifact","inventory/project.json",project_raw)
            isolation.write_exclusive("artifact","inventory/global.json",global_raw)
            project_evidence={"inventory/project.json":hashlib.sha256(project_raw).hexdigest()}
            global_evidence={"inventory/global.json":hashlib.sha256(global_raw).hexdigest()}
            sources=production_inventory_sources(isolation=isolation,project_manifest_evidence=project_evidence,
                                                 global_manifest_evidence={})
            self.assertEqual(sources.project_assets[0].asset_id,"p")
            self.assertEqual(sources.global_assets,())
            self.assertIn("implementation_agent",sources.agent_registry)
            self.assertEqual(len(sources.evidence_digest),64)
            with self.assertRaises(OperationalCapabilityError):
                production_inventory_sources(isolation=isolation,
                    project_manifest_evidence={"inventory/project.json":"0"*64},global_manifest_evidence={})
            with self.assertRaises(OperationalCapabilityError):
                production_inventory_sources(isolation=isolation,
                    project_manifest_evidence=project_evidence,global_manifest_evidence=global_evidence)
            class Impostor:
                agent_name="implementation_agent"
            with patch("runtime.agents.AGENT_REGISTRY",{"implementation_agent":Impostor}), \
                 self.assertRaises(OperationalCapabilityError):
                production_inventory_sources(isolation=isolation,project_manifest_evidence=project_evidence,
                                             global_manifest_evidence={})


if __name__ == "__main__":
    unittest.main()
