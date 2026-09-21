"""Immutable verified Gate attestation evidence for AUTO continuation."""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from .durable_io import atomic_write_json

SCHEMA = "orchestration.verified-gate-attestation.v1"
_SAFE_ID = re.compile(r"[A-Za-z0-9._-]{1,160}\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_SHA = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")

class AttestationError(ValueError): pass

def _now() -> str: return datetime.now(timezone.utc).isoformat(timespec="seconds")
def _digest(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()

@dataclass(frozen=True, slots=True)
class VerifiedGateAttestation:
    schema_version: str
    project_id: str
    run_id: str
    gate_id: str
    authority_core_sha256: str
    contract_sha256: str
    source_head: str
    source_tree_sha256: str
    changed_paths_sha256: str
    verifier_results: dict[str, dict[str, str]]
    evidence_digests: dict[str, str]
    status: str
    created_at: str
    attestation_sha256: str

    @classmethod
    def create(cls, *, project_id: str, run_id: str, gate_id: str,
               authority_core_sha256: str, contract_sha256: str, source_head: str,
               source_tree_sha256: str, changed_paths_sha256: str,
               verifier_results: Mapping[str, Mapping[str, str]], evidence_digests: Mapping[str, str]) -> "VerifiedGateAttestation":
        for name,value in (("project_id",project_id),("run_id",run_id),("gate_id",gate_id)):
            if not _SAFE_ID.fullmatch(str(value or "")): raise AttestationError(f"invalid {name}")
        for name,value in (("authority_core_sha256",authority_core_sha256),("contract_sha256",contract_sha256),("changed_paths_sha256",changed_paths_sha256)):
            if not _SHA256.fullmatch(str(value or "")): raise AttestationError(f"invalid {name}")
        if not _SHA.fullmatch(str(source_head or "")) or not _SHA.fullmatch(str(source_tree_sha256 or "")):
            raise AttestationError("invalid source identity")
        verifiers: dict[str, dict[str, str]] = {}
        if not verifier_results:
            raise AttestationError("verifier evidence is required")
        for verifier,raw in verifier_results.items():
            status=str(raw.get("status") or ""); evidence=str(raw.get("evidence_sha256") or "")
            if not verifier or status != "PASS" or not _SHA256.fullmatch(evidence):
                raise AttestationError("verifier result is not PASS evidence")
            verifiers[str(verifier)]={"status":"PASS","evidence_sha256":evidence}
        evidence={str(k):str(v) for k,v in evidence_digests.items()}
        if not evidence or any(not k or not _SHA256.fullmatch(v) for k,v in evidence.items()):
            raise AttestationError("evidence digest is invalid")
        unsigned={"schema_version":SCHEMA,"project_id":str(project_id),"run_id":str(run_id),"gate_id":str(gate_id),
                  "authority_core_sha256":str(authority_core_sha256),"contract_sha256":str(contract_sha256),
                  "source_head":str(source_head),"source_tree_sha256":str(source_tree_sha256),
                  "changed_paths_sha256":str(changed_paths_sha256),"verifier_results":verifiers,
                  "evidence_digests":evidence,"status":"VERIFIED","created_at":_now()}
        return cls(**unsigned,attestation_sha256=_digest(unsigned))

    def canonical_projection(self) -> dict[str, Any]: return asdict(self)

    def validate_for_contract(self, contract: Any) -> None:
        from .gate_continuation_contract import GateContinuationContract
        if not isinstance(contract, GateContinuationContract):
            raise AttestationError("GateContinuationContract is required")
        self.validate()
        contract.require_gate(self.gate_id)
        if self.contract_sha256 != contract.contract_sha256:
            raise AttestationError("attestation contract digest mismatch")
        missing = [name for name in contract.required_evidence_classes if name not in self.evidence_digests]
        if missing:
            raise AttestationError("required evidence class is missing")
        if contract.external_effect_policy == "GOVERNED_REPOSITORY_EFFECTS_ONLY":
            if "EFFECT_RECONCILIATION" not in contract.required_evidence_classes:
                raise AttestationError("governed effect policy requires EFFECT_RECONCILIATION evidence")
            if "EFFECT_RECONCILIATION" not in self.evidence_digests:
                raise AttestationError("required evidence class is missing")

    def validate(self) -> None:
        payload=self.canonical_projection(); observed=payload.pop("attestation_sha256")
        if observed != _digest(payload): raise AttestationError("attestation SHA mismatch")
        rebuilt=self.create(project_id=self.project_id,run_id=self.run_id,gate_id=self.gate_id,
            authority_core_sha256=self.authority_core_sha256,contract_sha256=self.contract_sha256,
            source_head=self.source_head,source_tree_sha256=self.source_tree_sha256,changed_paths_sha256=self.changed_paths_sha256,
            verifier_results=self.verifier_results,evidence_digests=self.evidence_digests)
        if self.status != "VERIFIED" or not self.created_at: raise AttestationError("attestation status invalid")
        # create() revalidates field shapes; timestamps/hashes are validated above.

class VerifiedGateAttestationStore:
    def __init__(self, state_root: str | Path) -> None:
        self.root=Path(state_root).resolve() / "_workspace" / "dcc-attestations"
    def path(self,project_id:str,run_id:str,gate_id:str)->Path:
        for value in (project_id,run_id,gate_id):
            if not _SAFE_ID.fullmatch(str(value or "")): raise AttestationError("unsafe attestation identity")
        return self.root/project_id/run_id/f"{gate_id}.json"
    def create(self,attestation:VerifiedGateAttestation)->VerifiedGateAttestation:
        attestation.validate(); path=self.path(attestation.project_id,attestation.run_id,attestation.gate_id)
        if path.exists():
            existing=self.load(attestation.project_id,attestation.run_id,attestation.gate_id)
            if existing.attestation_sha256==attestation.attestation_sha256: return existing
            raise AttestationError("conflicting attestation already exists")
        path.parent.mkdir(parents=True,exist_ok=True)
        if path.parent.is_symlink(): raise AttestationError("unsafe attestation root")
        atomic_write_json(path,attestation.canonical_projection()); return attestation
    def load(self,project_id:str,run_id:str,gate_id:str)->VerifiedGateAttestation:
        path=self.path(project_id,run_id,gate_id)
        if path.is_symlink() or not path.is_file(): raise AttestationError("attestation missing")
        raw=json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw,dict) or set(raw)!=set(VerifiedGateAttestation.__dataclass_fields__): raise AttestationError("attestation fields mismatch")
        try: att=VerifiedGateAttestation(**raw)
        except Exception as exc: raise AttestationError("attestation values invalid") from exc
        att.validate(); return att
