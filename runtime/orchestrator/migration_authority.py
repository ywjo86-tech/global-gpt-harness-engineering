from __future__ import annotations

import hashlib
import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

from .execution_contract import ActivationProfile, ApprovalContext


AUTHORITY_SCHEMA_VERSION = "orchestration.migration-authority.v2"
AUTHORITY_MODE = "LEGACY_REFERENCE_SATISFIED_LAYERED_FREEZE"
AUTHORITY_MANIFEST_RELATIVE = Path("docs/harness/R4_1_MIGRATION_AUTHORITY_MANIFEST.json")
APPROVAL_RELATIVE = Path("docs/harness/R4_1_ARCHITECTURE_FREEZE_AMENDMENT_APPROVAL.md")

R4_PACKAGE_SHA256 = "0f03698ffa1bcc438c8f0d97260d930b969da9983052eac50b69344a6c34d4f8"
R4_1_PACKAGE_SHA256 = "9ae0e4bfe62caaf92afb7e81a1d66a373701c8082f56775d2225feed6ca4ca3b"
R4_REQUIREMENT_SHA256 = "71897df1376fcdccba6365f1624c45e706647b674c9fd2de3b81f747f27f9879"
R4_SEMANTIC_SHA256 = "f8c14a3763b7996a7cfe80c89b2689be73c4d837487b816cdc349b3697c1d55f"
R4_1_PLAN_SHA256 = "7b64a2460f28764013b24a04d5afbf71f6db34c9198ff764f4f66dd8019c653f"
R4_1_DESIGN_SHA256 = "ae9e4b7dadab89fff627204759949ee6af03c4ee1343ce17b9b36b49e1d49c8d"
R4_1_SC_EVIDENCE_ONLY_SHA256 = "754ada5d67471ce568ca56aa2c948d48cb899a3046c1b93efa24ac9b4fb1f162"

APPROVAL_COMMIT = "21345c9034346c20cf24a4514de7869dd9cd84f6"
APPROVAL_BLOB_OID = "d4eca431fa340a95f211fd0366a16d7cfa5d9332"
APPROVAL_SHA256 = "1d586a0fb3e3e6fa0874cc452b103699b25ed8f09418ce460bb785930ebbcc92"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")

_REQUIRED_INVARIANTS = (
    "gate_authorization_is_not_full_plan_approval",
    "plan_digest_is_not_semantic_digest",
    "r4_1_candidate_semantic_sha_is_not_approval_semantic_digest",
    "legacy_final_digest_fabrication_prohibited",
    "legacy_lv_lifecycle_preserved",
    "worker_self_success_authority_prohibited",
    "same_run_profile_switch_prohibited",
)


class MigrationAuthorityError(ValueError):
    def __init__(self, message: str, *, reason_taxonomy: str) -> None:
        super().__init__(message)
        self.reason_taxonomy = reason_taxonomy


@dataclass(frozen=True, slots=True)
class MigrationAuthorityEvidence:
    manifest_path: str
    manifest_digest: str
    activation_profile: ActivationProfile
    authority_mode: str
    requirement_digest: str
    plan_digest: str
    semantic_digest: str
    design_digest: str
    approval_ref: str
    approval_commit: str
    approval_blob_oid: str
    approval_sha256: str
    preserved_lineage_refs: tuple[str, ...]
    decision_refs: Mapping[str, str]

    def architecture_source_digests(self) -> Mapping[str, str]:
        """Return R4/R4.1 architecture/approval projection digests only.

        These values are provenance for the frozen architecture package.  They
        MUST NOT be substituted for run-specific plan/requirement bindings in a
        CanonicalExecutionContract or RunBinding.
        """
        return MappingProxyType(
            {
                "requirement": self.requirement_digest,
                "plan": self.plan_digest,
                "semantic": self.semantic_digest,
                "design": self.design_digest,
            }
        )

    def source_digests(self) -> Mapping[str, str]:
        """Fail closed on the formerly ambiguous API.

        Contract builders must call run_source_digests() with the authoritative
        Gate plan and requirements digests for the current run.
        """
        raise MigrationAuthorityError(
            "run-specific plan and requirement digests are required",
            reason_taxonomy="RUN_SOURCE_BINDING_REQUIRED",
        )

    def run_source_digests(
        self,
        *,
        plan_digest: str,
        requirement_digest: str,
    ) -> Mapping[str, str]:
        for name, value in (
            ("plan_digest", plan_digest),
            ("requirement_digest", requirement_digest),
        ):
            if not isinstance(value, str) or not _SHA256.fullmatch(value.strip()):
                raise MigrationAuthorityError(
                    f"{name} must be an exact SHA-256 binding",
                    reason_taxonomy="RUN_SOURCE_BINDING_INVALID",
                )
        return MappingProxyType(
            {
                "plan": plan_digest.strip(),
                "requirement": requirement_digest.strip(),
                "semantic": self.semantic_digest,
            }
        )

    def approval_context(self) -> ApprovalContext:
        return ApprovalContext(
            full_plan_approval_required=False,
            full_plan_approval_ref=self.approval_ref,
            approved_semantic_digest=self.semantic_digest,
            reviewed_semantic_digest=self.semantic_digest,
            other_approval_refs=(
                f"git://{self.approval_commit}/{APPROVAL_RELATIVE.as_posix()}#{self.approval_blob_oid}",
                "decision://DEC-006/APPROVED",
                "decision://DEC-007/APPROVED",
                "decision://DEC-009/A",
            ),
        )


def _canonical_bytes(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise MigrationAuthorityError(
            "migration authority payload is not canonically serializable",
            reason_taxonomy="MIGRATION_AUTHORITY_INVALID",
        ) from exc


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _required_mapping(value: Any, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise MigrationAuthorityError(
            f"{field} must be an object",
            reason_taxonomy="MIGRATION_AUTHORITY_INVALID",
        )
    return value


def _required_string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise MigrationAuthorityError(
            f"{field} is required",
            reason_taxonomy="MIGRATION_AUTHORITY_INVALID",
        )
    return value.strip()


def _verify_manifest_digest(payload: Mapping[str, Any]) -> str:
    supplied = _required_string(payload.get("manifest_digest"), "manifest_digest")
    unsigned = {key: value for key, value in payload.items() if key != "manifest_digest"}
    actual = _sha256(_canonical_bytes(unsigned))
    if supplied != actual:
        raise MigrationAuthorityError(
            "migration authority manifest digest mismatch",
            reason_taxonomy="MIGRATION_AUTHORITY_DIGEST_DRIFT",
        )
    return supplied


def validate_migration_authority_payload(
    payload: Mapping[str, Any],
    *,
    approval_bytes: bytes,
) -> MigrationAuthorityEvidence:
    manifest_digest = _verify_manifest_digest(payload)
    if payload.get("schema_version") != AUTHORITY_SCHEMA_VERSION:
        raise MigrationAuthorityError(
            "unsupported migration authority schema",
            reason_taxonomy="MIGRATION_AUTHORITY_SCHEMA_DRIFT",
        )
    if payload.get("activation_profile") != ActivationProfile.MIGRATION_APPROVED_PLAN.value:
        raise MigrationAuthorityError(
            "migration authority profile mismatch",
            reason_taxonomy="MIGRATION_PROFILE_INVALID",
        )
    if payload.get("authority_mode") != AUTHORITY_MODE:
        raise MigrationAuthorityError(
            "migration authority mode mismatch",
            reason_taxonomy="MIGRATION_AUTHORITY_INVALID",
        )

    decision = _required_mapping(payload.get("decision"), "decision")
    if (
        decision.get("decision_id") != "DEC-009"
        or decision.get("status") != "DECIDED"
        or decision.get("selection") != "A"
    ):
        raise MigrationAuthorityError(
            "DEC-009 authority decision binding mismatch",
            reason_taxonomy="MIGRATION_AUTHORITY_DECISION_DRIFT",
        )

    legacy = _required_mapping(payload.get("preserved_legacy_lineage"), "preserved_legacy_lineage")
    expected_legacy = {
        "requirement_baseline_ref": "FINAL Requirement Baseline 1.0",
        "development_plan_ref": "FINAL DP-2.0",
        "semantic_contract_ref": "FINAL SC-1.0",
    }
    for key, expected in expected_legacy.items():
        if legacy.get(key) != expected:
            raise MigrationAuthorityError(
                f"{key} lineage mismatch",
                reason_taxonomy="MIGRATION_APPROVED_LINEAGE_DRIFT",
            )
    if legacy.get("rewrite_prohibited") is not True or legacy.get("satisfaction_mode") != "REFERENCE_SATISFIED":
        raise MigrationAuthorityError(
            "legacy approval lineage is not reference-satisfied/frozen",
            reason_taxonomy="MIGRATION_APPROVED_LINEAGE_DRIFT",
        )

    base = _required_mapping(payload.get("base_r4_architecture_freeze"), "base_r4_architecture_freeze")
    if (
        base.get("package_sha256") != R4_PACKAGE_SHA256
        or base.get("status") != "PRESERVED_BY_R4_1_APPROVAL"
        or base.get("requirement_projection_sha256") != R4_REQUIREMENT_SHA256
        or base.get("semantic_projection_sha256") != R4_SEMANTIC_SHA256
    ):
        raise MigrationAuthorityError(
            "R4 Architecture Freeze authority binding mismatch",
            reason_taxonomy="MIGRATION_R4_FREEZE_DRIFT",
        )

    amendment = _required_mapping(payload.get("r4_1_amendment"), "r4_1_amendment")
    if amendment.get("package_sha256") != R4_1_PACKAGE_SHA256:
        raise MigrationAuthorityError(
            "R4.1 package binding mismatch",
            reason_taxonomy="MIGRATION_R4_1_AMENDMENT_DRIFT",
        )
    if (
        amendment.get("requirement_meaning_change") != "none"
        or amendment.get("semantic_contract_change") != "none"
        or amendment.get("product_development_scope_expansion") != "none"
        or amendment.get("prior_r4_architecture_freeze") != "preserved"
    ):
        raise MigrationAuthorityError(
            "R4.1 amendment exceeds approved non-semantic scope",
            reason_taxonomy="MIGRATION_R4_1_AMENDMENT_SCOPE_DRIFT",
        )

    approval = _required_mapping(amendment.get("approval"), "r4_1_amendment.approval")
    if (
        approval.get("origin_commit") != APPROVAL_COMMIT
        or approval.get("origin_blob_oid") != APPROVAL_BLOB_OID
        or approval.get("content_sha256") != APPROVAL_SHA256
        or approval.get("user_decision") != "APPROVED"
    ):
        raise MigrationAuthorityError(
            "R4.1 approval provenance mismatch",
            reason_taxonomy="MIGRATION_APPROVAL_PROVENANCE_DRIFT",
        )
    if _sha256(approval_bytes) != APPROVAL_SHA256:
        raise MigrationAuthorityError(
            "materialized R4.1 approval bytes mismatch",
            reason_taxonomy="MIGRATION_APPROVAL_PROVENANCE_DRIFT",
        )

    projection = _required_mapping(payload.get("canonical_authority_projection"), "canonical_authority_projection")
    source_digests = _required_mapping(payload.get("source_digests"), "source_digests")
    expected_sources = {
        "requirement": R4_REQUIREMENT_SHA256,
        "plan": R4_1_PLAN_SHA256,
        "semantic": R4_SEMANTIC_SHA256,
        "design": R4_1_DESIGN_SHA256,
    }
    for key, expected in expected_sources.items():
        if source_digests.get(key) != expected:
            raise MigrationAuthorityError(
                f"canonical {key} source digest mismatch",
                reason_taxonomy="MIGRATION_SOURCE_DIGEST_DRIFT",
            )
    if (
        projection.get("requirement_digest") != expected_sources["requirement"]
        or projection.get("plan_digest") != expected_sources["plan"]
        or projection.get("semantic_digest") != expected_sources["semantic"]
        or projection.get("design_digest") != expected_sources["design"]
    ):
        raise MigrationAuthorityError(
            "canonical authority projection disagrees with source_digests",
            reason_taxonomy="MIGRATION_SOURCE_DIGEST_DRIFT",
        )

    approval_projection = _required_mapping(payload.get("approval_context_projection"), "approval_context_projection")
    approval_ref = _required_string(
        approval_projection.get("full_plan_approval_ref"),
        "approval_context_projection.full_plan_approval_ref",
    )
    if approval_projection.get("full_plan_approval_required") is not False:
        raise MigrationAuthorityError(
            "migration profile must reference-satisfy prior Plan/Design approval",
            reason_taxonomy="MIGRATION_APPROVAL_PROFILE_DRIFT",
        )
    if approval_projection.get("gate_authorization_reused_as_full_plan_approval") is not False:
        raise MigrationAuthorityError(
            "Gate authorization cannot be reused as Plan/Design approval",
            reason_taxonomy="MIGRATION_APPROVAL_AUTHORITY_MIXED",
        )
    if (
        approval_projection.get("approved_semantic_digest") != R4_SEMANTIC_SHA256
        or approval_projection.get("reviewed_semantic_digest") != R4_SEMANTIC_SHA256
    ):
        raise MigrationAuthorityError(
            "approval semantic digest is not the preserved R4 frozen semantic authority",
            reason_taxonomy="MIGRATION_SEMANTIC_AUTHORITY_DRIFT",
        )
    if approval_projection.get("approved_semantic_digest") == R4_1_SC_EVIDENCE_ONLY_SHA256:
        raise MigrationAuthorityError(
            "R4.1 SC amendment bytes cannot replace the preserved semantic authority digest",
            reason_taxonomy="MIGRATION_SEMANTIC_AUTHORITY_DRIFT",
        )

    invariants = _required_mapping(payload.get("invariants"), "invariants")
    if any(invariants.get(name) is not True for name in _REQUIRED_INVARIANTS):
        raise MigrationAuthorityError(
            "migration authority invariant is missing or disabled",
            reason_taxonomy="MIGRATION_AUTHORITY_INVARIANT_DRIFT",
        )

    decision_refs = _required_mapping(payload.get("decision_refs"), "decision_refs")
    expected_decisions = {
        "DEC-006": "APPROVED",
        "DEC-007": "APPROVED",
        "DEC-008": "HOLD",
        "DEC-009": "A",
    }
    if dict(decision_refs) != expected_decisions:
        raise MigrationAuthorityError(
            "migration authority Decision lineage mismatch",
            reason_taxonomy="MIGRATION_AUTHORITY_DECISION_DRIFT",
        )

    return MigrationAuthorityEvidence(
        manifest_path=AUTHORITY_MANIFEST_RELATIVE.as_posix(),
        manifest_digest=manifest_digest,
        activation_profile=ActivationProfile.MIGRATION_APPROVED_PLAN,
        authority_mode=AUTHORITY_MODE,
        requirement_digest=expected_sources["requirement"],
        plan_digest=expected_sources["plan"],
        semantic_digest=expected_sources["semantic"],
        design_digest=expected_sources["design"],
        approval_ref=approval_ref,
        approval_commit=APPROVAL_COMMIT,
        approval_blob_oid=APPROVAL_BLOB_OID,
        approval_sha256=APPROVAL_SHA256,
        preserved_lineage_refs=tuple(expected_legacy.values()),
        decision_refs=MappingProxyType(dict(expected_decisions)),
    )


def _git_text(root: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    if completed.returncode != 0:
        raise MigrationAuthorityError(
            "migration approval Git provenance is unavailable",
            reason_taxonomy="MIGRATION_APPROVAL_PROVENANCE_UNVERIFIED",
        )
    return completed.stdout.strip()


def load_migration_authority(
    harness_root: str | Path,
    *,
    verify_git_provenance: bool = True,
) -> MigrationAuthorityEvidence:
    root = Path(harness_root).resolve()
    manifest_path = root / AUTHORITY_MANIFEST_RELATIVE
    approval_path = root / APPROVAL_RELATIVE
    for path, label in ((manifest_path, "authority manifest"), (approval_path, "approval artifact")):
        if not path.is_file() or path.is_symlink():
            raise MigrationAuthorityError(
                f"{label} is missing or unsafe",
                reason_taxonomy="MIGRATION_AUTHORITY_SOURCE_MISSING",
            )
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise MigrationAuthorityError(
            "migration authority manifest is unreadable",
            reason_taxonomy="MIGRATION_AUTHORITY_INVALID",
        ) from exc
    if not isinstance(payload, Mapping):
        raise MigrationAuthorityError(
            "migration authority manifest root must be an object",
            reason_taxonomy="MIGRATION_AUTHORITY_INVALID",
        )
    evidence = validate_migration_authority_payload(payload, approval_bytes=approval_path.read_bytes())

    if verify_git_provenance:
        commit = _git_text(root, "rev-parse", f"{APPROVAL_COMMIT}^{{commit}}")
        blob = _git_text(root, "rev-parse", f"{APPROVAL_COMMIT}:{APPROVAL_RELATIVE.as_posix()}")
        if commit != APPROVAL_COMMIT or blob != APPROVAL_BLOB_OID:
            raise MigrationAuthorityError(
                "migration approval Git identity drift",
                reason_taxonomy="MIGRATION_APPROVAL_PROVENANCE_DRIFT",
            )
    return evidence


def validate_activation_profile(
    requested_profile: ActivationProfile,
    *,
    existing_run_profile: ActivationProfile | None,
    new_run: bool,
    full_orchestration_ready: bool,
) -> None:
    if existing_run_profile is not None and requested_profile is not existing_run_profile:
        raise MigrationAuthorityError(
            "same-run activation profile switch is prohibited",
            reason_taxonomy="MIGRATION_PROFILE_SWITCH_PROHIBITED",
        )
    if requested_profile is ActivationProfile.MIGRATION_APPROVED_PLAN:
        if new_run and full_orchestration_ready:
            raise MigrationAuthorityError(
                "new runs must use FULL_ORCHESTRATION after ORCH-05/06 readiness",
                reason_taxonomy="MIGRATION_PROFILE_EXPIRED",
            )
        return
    if requested_profile is ActivationProfile.FULL_ORCHESTRATION:
        return
    raise MigrationAuthorityError(
        "unsupported activation profile",
        reason_taxonomy="MIGRATION_PROFILE_INVALID",
    )
