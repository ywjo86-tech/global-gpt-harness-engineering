from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

PRE_QUALITY_REFERENCE_SATISFIED = "PRE_QUALITY_REFERENCE_SATISFIED"
MIGRATION_APPROVED_PLAN = "MIGRATION_APPROVED_PLAN"
FULL_ORCHESTRATION = "FULL_ORCHESTRATION"


AUTHORITY_SCHEMA = "orchestration.migration-quality-authority.r4.2.v1"
CONTRACT_SCHEMA = "orchestration.migration-quality-criteria-contract.r4.2.v1"
SOURCE_MODE = "APPROVED_MIGRATION_BASELINE"
POLICY_SCHEMA = "orchestration.harness-quality-policy.migration.v1"
POLICY_ID = "HQP-MIGRATION-001"
POLICY_VERSION = "1.0"
POLICY_DIGEST = "f4418d48899917bfea40185d3d9e71f73ff50a729187e9f5dca3443cf34fccc7"
APPROVAL_REF = "R4.2-MIGRATION-QUALITY-AUTHORITY-APPROVAL-2026-09-10"
DECISION_REF = "DEC-011"

POLICY_RELATIVE = Path("docs/harness/HARNESS_QUALITY_POLICY_MIGRATION_V1_APPROVED.json")
AMENDMENT_RELATIVE = Path("docs/harness/R4_2_MIGRATION_QUALITY_AUTHORITY_AMENDMENT_APPROVED.md")
DECISION_RELATIVE = Path("docs/harness/DEC-011_ISSUE-095_MIGRATION_QUALITY_AUTHORITY_DECIDED.md")
RECOVERY_RELATIVE = Path("docs/harness/ISSUE-095_AUTHORITY_RECOVERY_REPORT_A.md")
TRACEABILITY_RELATIVE = Path("docs/harness/R4_2_TRACEABILITY_TEST_IMPACT_APPROVED.md")
STATUS_RELATIVE = Path("docs/harness/R4_2_APPROVAL_STATUS.md")

APPROVED_FILE_SHA256: Mapping[Path, str] = {
    POLICY_RELATIVE: "aff3d2919a77bd95046d0e5ac6c105504306d27d8f35bd285f9b3f4410fd377e",
    AMENDMENT_RELATIVE: "c49ee359a4178dbeb055a52e74141da8b7e5b058d773217238466ca5a433c15c",
    DECISION_RELATIVE: "9cf5477be12c5942aef505a747cc1ba7817b0befdc9749c25e2b499246c8d62d",
    RECOVERY_RELATIVE: "febc6cdac0f57893abae41412024ef416b5fff18250fe3bb0cc5aa468431453a",
    TRACEABILITY_RELATIVE: "a890624d88c0e77d4445ab3cd2995c89e4154879410184db7061110e56cc590f",
    STATUS_RELATIVE: "292d5ec972272b489c621b016431536c84356a605736ed823c403a65dd45d84b",
}

R4_PACKAGE_SHA256 = "0f03698ffa1bcc438c8f0d97260d930b969da9983052eac50b69344a6c34d4f8"
R4_1_PACKAGE_SHA256 = "9ae0e4bfe62caaf92afb7e81a1d66a373701c8082f56775d2225feed6ca4ca3b"
R4_1_APPROVAL_COMMIT = "21345c9034346c20cf24a4514de7869dd9cd84f6"
R4_1_APPROVAL_BLOB = "d4eca431fa340a95f211fd0366a16d7cfa5d9332"

EXPECTED_CRITERIA = (
    ("MQC-001", "COMPLETENESS"),
    ("MQC-002", "CONSISTENCY"),
    ("MQC-003", "IMPLEMENTABILITY"),
    ("MQC-004", "DEPENDENCY_INTEGRITY"),
    ("MQC-005", "TESTABILITY"),
    ("MQC-006", "SECURITY_INTEGRITY"),
    ("MQC-007", "SEMANTIC_INTEGRITY"),
    ("MQC-008", "TRACEABILITY"),
)
EXPECTED_CROSS_CHECKS = (
    "AUTOMATIC_REMEDIATION_DISABLED",
    "BROKER_SECURITY_INVARIANTS_PRESERVED",
    "FULL_ORCHESTRATION_USE_PROHIBITED",
    "NO_COMPLETION_TRUTH_REDEFINITION",
    "NO_NEW_REQUIREMENT",
    "NO_PERMISSION_EXPANSION",
    "NO_PRODUCT_SCOPE_EXPANSION",
    "PRE_POST_QUALITY_CRITERIA_LINEAGE_EXACT",
    "UNRESOLVED_CRITICAL_OR_MAJOR_NOT_PROMOTED_TO_PASS",
)
_FORBIDDEN_CRITERION_FIELDS = frozenset(
    {
        "requirement_refs",
        "scope_refs",
        "permission_refs",
        "completion_truth_refs",
        "new_requirement_refs",
        "new_scope_refs",
        "new_permission_refs",
    }
)


class MigrationQualityAuthorityError(ValueError):
    def __init__(self, message: str, *, reason_taxonomy: str) -> None:
        super().__init__(message)
        self.reason_taxonomy = reason_taxonomy


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
        raise MigrationQualityAuthorityError(
            "migration quality authority is not canonically serializable",
            reason_taxonomy="MIGRATION_QUALITY_AUTHORITY_INVALID",
        ) from exc


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _digest_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _required_file(root: Path, relative: Path) -> bytes:
    path = root / relative
    if not path.is_file() or path.is_symlink():
        raise MigrationQualityAuthorityError(
            f"approved migration quality authority file is missing or unsafe: {relative}",
            reason_taxonomy="MIGRATION_QUALITY_APPROVAL_MISSING",
        )
    value = path.read_bytes()
    expected = APPROVED_FILE_SHA256[relative]
    if _digest_bytes(value) != expected:
        raise MigrationQualityAuthorityError(
            f"approved migration quality authority file drift: {relative}",
            reason_taxonomy="MIGRATION_QUALITY_APPROVAL_DRIFT",
        )
    return value


def validate_policy_semantics(payload: Mapping[str, Any]) -> None:
    if payload.get("schema") != POLICY_SCHEMA:
        raise MigrationQualityAuthorityError(
            "migration quality policy schema drift",
            reason_taxonomy="MIGRATION_QUALITY_POLICY_SCHEMA_DRIFT",
        )
    if payload.get("policy_id") != POLICY_ID or payload.get("policy_version") != POLICY_VERSION:
        raise MigrationQualityAuthorityError(
            "migration quality policy identity drift",
            reason_taxonomy="MIGRATION_QUALITY_POLICY_IDENTITY_DRIFT",
        )
    if payload.get("status") != "APPROVED" or payload.get("decision_ref") != DECISION_REF:
        raise MigrationQualityAuthorityError(
            "migration quality policy is not approved by DEC-011",
            reason_taxonomy="MIGRATION_QUALITY_POLICY_APPROVAL_DRIFT",
        )
    if payload.get("activation_profile") != MIGRATION_APPROVED_PLAN:
        raise MigrationQualityAuthorityError(
            "migration quality policy activation profile drift",
            reason_taxonomy="MIGRATION_QUALITY_PROFILE_INVALID",
        )
    prohibited = payload.get("prohibited_profiles")
    if prohibited != [FULL_ORCHESTRATION]:
        raise MigrationQualityAuthorityError(
            "FULL_ORCHESTRATION prohibition drift",
            reason_taxonomy="MIGRATION_QUALITY_FULL_ORCHESTRATION_NOT_PROHIBITED",
        )
    if payload.get("contract_source_mode_after_approval") != SOURCE_MODE:
        raise MigrationQualityAuthorityError(
            "migration quality source mode drift",
            reason_taxonomy="MIGRATION_QUALITY_SOURCE_MODE_DRIFT",
        )

    approval = payload.get("approval")
    if not isinstance(approval, Mapping):
        raise MigrationQualityAuthorityError(
            "migration quality approval metadata missing",
            reason_taxonomy="MIGRATION_QUALITY_POLICY_APPROVAL_DRIFT",
        )
    if (
        approval.get("decision_ref") != DECISION_REF
        or approval.get("approval_ref") != APPROVAL_REF
        or approval.get("approved_by") != "USER"
        or approval.get("scope") != "PLANNING_AUTHORITY_ONLY"
    ):
        raise MigrationQualityAuthorityError(
            "migration quality approval metadata drift",
            reason_taxonomy="MIGRATION_QUALITY_POLICY_APPROVAL_DRIFT",
        )

    source = payload.get("source_authority")
    if not isinstance(source, Mapping):
        raise MigrationQualityAuthorityError(
            "migration quality source authority missing",
            reason_taxonomy="MIGRATION_QUALITY_SOURCE_DRIFT",
        )
    expected_source = {
        "r4_zip_sha256": R4_PACKAGE_SHA256,
        "r4_1_zip_sha256": R4_1_PACKAGE_SHA256,
        "r4_1_approval_commit": R4_1_APPROVAL_COMMIT,
        "r4_1_approval_blob": R4_1_APPROVAL_BLOB,
    }
    for key, expected in expected_source.items():
        if source.get(key) != expected:
            raise MigrationQualityAuthorityError(
                f"migration quality source authority drift: {key}",
                reason_taxonomy="MIGRATION_QUALITY_SOURCE_DRIFT",
            )

    criteria = payload.get("criteria")
    if not isinstance(criteria, list) or len(criteria) != len(EXPECTED_CRITERIA):
        raise MigrationQualityAuthorityError(
            "migration quality criterion set size drift",
            reason_taxonomy="MIGRATION_QUALITY_CRITERIA_DRIFT",
        )
    actual: list[tuple[str, str]] = []
    for item in criteria:
        if not isinstance(item, Mapping):
            raise MigrationQualityAuthorityError(
                "migration quality criterion is malformed",
                reason_taxonomy="MIGRATION_QUALITY_CRITERIA_DRIFT",
            )
        forbidden = _FORBIDDEN_CRITERION_FIELDS.intersection(item)
        if forbidden:
            raise MigrationQualityAuthorityError(
                f"migration quality criterion attempts meaning expansion: {sorted(forbidden)}",
                reason_taxonomy="MIGRATION_QUALITY_MEANING_EXPANSION",
            )
        criterion_id = item.get("criterion_id")
        name = item.get("name")
        rule = item.get("rule")
        if not isinstance(criterion_id, str) or not isinstance(name, str) or not isinstance(rule, str) or not rule.strip():
            raise MigrationQualityAuthorityError(
                "migration quality criterion is incomplete",
                reason_taxonomy="MIGRATION_QUALITY_CRITERIA_DRIFT",
            )
        actual.append((criterion_id, name))
    if tuple(actual) != EXPECTED_CRITERIA:
        raise MigrationQualityAuthorityError(
            "migration quality criterion identity/order drift",
            reason_taxonomy="MIGRATION_QUALITY_CRITERIA_DRIFT",
        )

    cross_checks = payload.get("mandatory_cross_checks")
    if not isinstance(cross_checks, list) or tuple(sorted(cross_checks)) != EXPECTED_CROSS_CHECKS:
        raise MigrationQualityAuthorityError(
            "migration quality mandatory cross-check drift",
            reason_taxonomy="MIGRATION_QUALITY_CROSS_CHECK_DRIFT",
        )


def _validate_policy_digest(payload: Mapping[str, Any]) -> None:
    supplied = payload.get("policy_digest")
    if supplied != POLICY_DIGEST:
        raise MigrationQualityAuthorityError(
            "approved migration quality policy digest identity drift",
            reason_taxonomy="MIGRATION_QUALITY_POLICY_DIGEST_DRIFT",
        )
    unsigned = {key: value for key, value in payload.items() if key != "policy_digest"}
    if _digest(unsigned) != POLICY_DIGEST:
        raise MigrationQualityAuthorityError(
            "approved migration quality policy canonical digest drift",
            reason_taxonomy="MIGRATION_QUALITY_POLICY_DIGEST_DRIFT",
        )


def _criteria_from_policy(payload: Mapping[str, Any]) -> tuple[MigrationQualityCriterion, ...]:
    result: list[MigrationQualityCriterion] = []
    for item in payload["criteria"]:
        criterion_id = item["criterion_id"]
        result.append(
            MigrationQualityCriterion(
                criterion_id=criterion_id,
                rule_ref=f"quality-policy://{POLICY_ID}@{POLICY_VERSION}/{criterion_id}",
                source_ref=f"file://{POLICY_RELATIVE.as_posix()}#{POLICY_DIGEST}",
            )
        )
    return tuple(result)


@dataclass(frozen=True, slots=True)
class MigrationQualityCriterion:
    criterion_id: str
    rule_ref: str
    source_ref: str

    def canonical_projection(self) -> dict[str, Any]:
        return {
            "criterion_id": self.criterion_id,
            "rule_ref": self.rule_ref,
            "source_ref": self.source_ref,
            "requirement_refs": [],
            "scope_refs": [],
            "permission_refs": [],
        }


@dataclass(frozen=True, slots=True)
class ApprovedMigrationQualityAuthority:
    authority_schema: str
    decision_ref: str
    approval_ref: str
    policy_id: str
    policy_version: str
    policy_digest: str
    source_mode: str
    source_refs: tuple[str, ...]
    criteria: tuple[MigrationQualityCriterion, ...]
    authority_digest: str


@dataclass(frozen=True, slots=True)
class ApprovedMigrationQualityCriteriaContract:
    schema: str
    contract_id: str
    contract_version: str
    activation_profile: str
    source_mode: str
    source_refs: tuple[str, ...]
    decision_ref: str
    amendment_ref: str
    policy_id: str
    policy_version: str
    policy_digest: str
    criteria: tuple[MigrationQualityCriterion, ...]
    criterion_set_digest: str
    pre_post_lineage_digest: str
    created_at_utc: str
    pre_quality_state: str
    contract_digest: str

    def canonical_projection(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "contract_id": self.contract_id,
            "contract_version": self.contract_version,
            "activation_profile": self.activation_profile,
            "source_mode": self.source_mode,
            "source_refs": list(self.source_refs),
            "decision_ref": self.decision_ref,
            "amendment_ref": self.amendment_ref,
            "policy_id": self.policy_id,
            "policy_version": self.policy_version,
            "policy_digest": self.policy_digest,
            "criteria": [criterion.canonical_projection() for criterion in self.criteria],
            "criterion_set_digest": self.criterion_set_digest,
            "pre_post_lineage_digest": self.pre_post_lineage_digest,
            "created_at_utc": self.created_at_utc,
            "pre_quality_state": self.pre_quality_state,
        }

    def to_dict(self) -> dict[str, Any]:
        value = self.canonical_projection()
        value["contract_digest"] = self.contract_digest
        return value

    @property
    def contract_ref(self) -> str:
        return f"migration-quality://{self.contract_id}@{self.contract_version}#{self.contract_digest}"

    def persist(self, path: str | Path) -> None:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(self.to_dict(), indent=2, sort_keys=True, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )


def load_approved_migration_quality_authority(harness_root: str | Path) -> ApprovedMigrationQualityAuthority:
    root = Path(harness_root).resolve()
    if not root.is_dir() or root.is_symlink():
        raise MigrationQualityAuthorityError(
            "harness root is missing or unsafe",
            reason_taxonomy="MIGRATION_QUALITY_HARNESS_ROOT_INVALID",
        )
    blobs = {relative: _required_file(root, relative) for relative in APPROVED_FILE_SHA256}
    try:
        policy = json.loads(blobs[POLICY_RELATIVE].decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise MigrationQualityAuthorityError(
            "approved migration quality policy is not valid JSON",
            reason_taxonomy="MIGRATION_QUALITY_POLICY_INVALID",
        ) from exc
    if not isinstance(policy, Mapping):
        raise MigrationQualityAuthorityError(
            "approved migration quality policy must be an object",
            reason_taxonomy="MIGRATION_QUALITY_POLICY_INVALID",
        )
    _validate_policy_digest(policy)
    validate_policy_semantics(policy)

    source_refs = (
        f"decision://{DECISION_REF}/DECIDED#{APPROVED_FILE_SHA256[DECISION_RELATIVE]}",
        f"approval://{APPROVAL_REF}#{APPROVED_FILE_SHA256[AMENDMENT_RELATIVE]}",
        f"quality-policy://{POLICY_ID}@{POLICY_VERSION}#{POLICY_DIGEST}",
        f"recovery://ISSUE-095/A/NOT_FOUND_IN_VERIFIED_SOURCES#{APPROVED_FILE_SHA256[RECOVERY_RELATIVE]}",
        f"package://R4#{R4_PACKAGE_SHA256}",
        f"package://R4.1#{R4_1_PACKAGE_SHA256}",
        f"git://{R4_1_APPROVAL_COMMIT}/docs/harness/R4_1_ARCHITECTURE_FREEZE_AMENDMENT_APPROVAL.md#{R4_1_APPROVAL_BLOB}",
    )
    criteria = _criteria_from_policy(policy)
    projection = {
        "authority_schema": AUTHORITY_SCHEMA,
        "decision_ref": DECISION_REF,
        "approval_ref": APPROVAL_REF,
        "policy_id": POLICY_ID,
        "policy_version": POLICY_VERSION,
        "policy_digest": POLICY_DIGEST,
        "source_mode": SOURCE_MODE,
        "source_refs": list(source_refs),
        "criteria": [criterion.canonical_projection() for criterion in criteria],
    }
    return ApprovedMigrationQualityAuthority(
        authority_schema=AUTHORITY_SCHEMA,
        decision_ref=DECISION_REF,
        approval_ref=APPROVAL_REF,
        policy_id=POLICY_ID,
        policy_version=POLICY_VERSION,
        policy_digest=POLICY_DIGEST,
        source_mode=SOURCE_MODE,
        source_refs=source_refs,
        criteria=criteria,
        authority_digest=_digest(projection),
    )


def _normalize_utc(value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise MigrationQualityAuthorityError(
            "created_at_utc is required",
            reason_taxonomy="MIGRATION_QUALITY_CONTRACT_INVALID",
        )
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise MigrationQualityAuthorityError(
            "created_at_utc must be ISO-8601",
            reason_taxonomy="MIGRATION_QUALITY_CONTRACT_INVALID",
        ) from exc
    if parsed.tzinfo is None:
        raise MigrationQualityAuthorityError(
            "created_at_utc must be timezone-aware",
            reason_taxonomy="MIGRATION_QUALITY_CONTRACT_INVALID",
        )
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def build_approved_migration_quality_contract(
    *,
    authority: ApprovedMigrationQualityAuthority,
    activation_profile: object,
    contract_id: str,
    contract_version: str,
    created_at_utc: str,
) -> ApprovedMigrationQualityCriteriaContract:
    profile = getattr(activation_profile, "value", activation_profile)
    if profile != MIGRATION_APPROVED_PLAN:
        raise MigrationQualityAuthorityError(
            "approved migration quality baseline is prohibited outside MIGRATION_APPROVED_PLAN",
            reason_taxonomy="MIGRATION_QUALITY_PROFILE_INVALID",
        )
    if authority.source_mode != SOURCE_MODE or authority.policy_digest != POLICY_DIGEST:
        raise MigrationQualityAuthorityError(
            "approved migration quality authority handle drift",
            reason_taxonomy="MIGRATION_QUALITY_AUTHORITY_DRIFT",
        )
    if not isinstance(contract_id, str) or not contract_id.strip() or not isinstance(contract_version, str) or not contract_version.strip():
        raise MigrationQualityAuthorityError(
            "migration quality contract identity is required",
            reason_taxonomy="MIGRATION_QUALITY_CONTRACT_INVALID",
        )
    created = _normalize_utc(created_at_utc)
    criteria_projection = [criterion.canonical_projection() for criterion in authority.criteria]
    criterion_set_digest = _digest(criteria_projection)
    lineage = _digest(
        {
            "policy_id": authority.policy_id,
            "policy_version": authority.policy_version,
            "policy_digest": authority.policy_digest,
            "criterion_set_digest": criterion_set_digest,
            "criteria_ids": [criterion.criterion_id for criterion in authority.criteria],
        }
    )
    projection = {
        "schema": CONTRACT_SCHEMA,
        "contract_id": contract_id.strip(),
        "contract_version": contract_version.strip(),
        "activation_profile": profile,
        "source_mode": authority.source_mode,
        "source_refs": list(authority.source_refs),
        "decision_ref": authority.decision_ref,
        "amendment_ref": authority.approval_ref,
        "policy_id": authority.policy_id,
        "policy_version": authority.policy_version,
        "policy_digest": authority.policy_digest,
        "criteria": criteria_projection,
        "criterion_set_digest": criterion_set_digest,
        "pre_post_lineage_digest": lineage,
        "created_at_utc": created,
        "pre_quality_state": PRE_QUALITY_REFERENCE_SATISFIED,
    }
    return ApprovedMigrationQualityCriteriaContract(
        schema=CONTRACT_SCHEMA,
        contract_id=contract_id.strip(),
        contract_version=contract_version.strip(),
        activation_profile=profile,
        source_mode=authority.source_mode,
        source_refs=authority.source_refs,
        decision_ref=authority.decision_ref,
        amendment_ref=authority.approval_ref,
        policy_id=authority.policy_id,
        policy_version=authority.policy_version,
        policy_digest=authority.policy_digest,
        criteria=authority.criteria,
        criterion_set_digest=criterion_set_digest,
        pre_post_lineage_digest=lineage,
        created_at_utc=created,
        pre_quality_state=PRE_QUALITY_REFERENCE_SATISFIED,
        contract_digest=_digest(projection),
    )



def validate_approved_migration_quality_contract(
    contract: ApprovedMigrationQualityCriteriaContract,
) -> None:
    if not isinstance(contract, ApprovedMigrationQualityCriteriaContract):
        raise MigrationQualityAuthorityError(
            "migration quality contract type is invalid",
            reason_taxonomy="MIGRATION_QUALITY_CONTRACT_INVALID",
        )
    if (
        contract.schema != CONTRACT_SCHEMA
        or contract.activation_profile != MIGRATION_APPROVED_PLAN
        or contract.source_mode != SOURCE_MODE
        or contract.decision_ref != DECISION_REF
        or contract.amendment_ref != APPROVAL_REF
        or contract.policy_id != POLICY_ID
        or contract.policy_version != POLICY_VERSION
        or contract.policy_digest != POLICY_DIGEST
        or contract.pre_quality_state != PRE_QUALITY_REFERENCE_SATISFIED
    ):
        raise MigrationQualityAuthorityError(
            "approved migration quality contract authority drift",
            reason_taxonomy="MIGRATION_QUALITY_CONTRACT_AUTHORITY_DRIFT",
        )

    expected_source_refs = (
        f"decision://{DECISION_REF}/DECIDED#{APPROVED_FILE_SHA256[DECISION_RELATIVE]}",
        f"approval://{APPROVAL_REF}#{APPROVED_FILE_SHA256[AMENDMENT_RELATIVE]}",
        f"quality-policy://{POLICY_ID}@{POLICY_VERSION}#{POLICY_DIGEST}",
        f"recovery://ISSUE-095/A/NOT_FOUND_IN_VERIFIED_SOURCES#{APPROVED_FILE_SHA256[RECOVERY_RELATIVE]}",
        f"package://R4#{R4_PACKAGE_SHA256}",
        f"package://R4.1#{R4_1_PACKAGE_SHA256}",
        f"git://{R4_1_APPROVAL_COMMIT}/docs/harness/R4_1_ARCHITECTURE_FREEZE_AMENDMENT_APPROVAL.md#{R4_1_APPROVAL_BLOB}",
    )
    if tuple(contract.source_refs) != expected_source_refs:
        raise MigrationQualityAuthorityError(
            "approved migration quality contract source refs drift",
            reason_taxonomy="MIGRATION_QUALITY_CONTRACT_SOURCE_DRIFT",
        )

    expected_criteria = tuple(
        MigrationQualityCriterion(
            criterion_id=criterion_id,
            rule_ref=f"quality-policy://{POLICY_ID}@{POLICY_VERSION}/{criterion_id}",
            source_ref=f"file://{POLICY_RELATIVE.as_posix()}#{POLICY_DIGEST}",
        )
        for criterion_id, _ in EXPECTED_CRITERIA
    )
    if tuple(item.canonical_projection() for item in contract.criteria) != tuple(
        item.canonical_projection() for item in expected_criteria
    ):
        raise MigrationQualityAuthorityError(
            "approved migration quality contract criteria drift",
            reason_taxonomy="MIGRATION_QUALITY_CONTRACT_CRITERIA_DRIFT",
        )

    criteria_projection = [criterion.canonical_projection() for criterion in contract.criteria]
    expected_criterion_set_digest = _digest(criteria_projection)
    expected_lineage_digest = _digest(
        {
            "policy_id": contract.policy_id,
            "policy_version": contract.policy_version,
            "policy_digest": contract.policy_digest,
            "criterion_set_digest": expected_criterion_set_digest,
            "criteria_ids": [criterion.criterion_id for criterion in contract.criteria],
        }
    )
    if contract.criterion_set_digest != expected_criterion_set_digest:
        raise MigrationQualityAuthorityError(
            "approved migration quality contract criterion-set digest drift",
            reason_taxonomy="MIGRATION_QUALITY_CONTRACT_CRITERION_SET_DRIFT",
        )
    if contract.pre_post_lineage_digest != expected_lineage_digest:
        raise MigrationQualityAuthorityError(
            "approved migration quality contract lineage digest drift",
            reason_taxonomy="MIGRATION_QUALITY_PRE_POST_LINEAGE_DRIFT",
        )

    created = _normalize_utc(contract.created_at_utc)
    if created != contract.created_at_utc:
        raise MigrationQualityAuthorityError(
            "approved migration quality contract timestamp is not canonical UTC",
            reason_taxonomy="MIGRATION_QUALITY_CONTRACT_INVALID",
        )
    if not contract.contract_id.strip() or not contract.contract_version.strip():
        raise MigrationQualityAuthorityError(
            "approved migration quality contract identity is missing",
            reason_taxonomy="MIGRATION_QUALITY_CONTRACT_INVALID",
        )

    projection = {
        "schema": CONTRACT_SCHEMA,
        "contract_id": contract.contract_id,
        "contract_version": contract.contract_version,
        "activation_profile": MIGRATION_APPROVED_PLAN,
        "source_mode": SOURCE_MODE,
        "source_refs": list(expected_source_refs),
        "decision_ref": DECISION_REF,
        "amendment_ref": APPROVAL_REF,
        "policy_id": POLICY_ID,
        "policy_version": POLICY_VERSION,
        "policy_digest": POLICY_DIGEST,
        "criteria": criteria_projection,
        "criterion_set_digest": expected_criterion_set_digest,
        "pre_post_lineage_digest": expected_lineage_digest,
        "created_at_utc": created,
        "pre_quality_state": PRE_QUALITY_REFERENCE_SATISFIED,
    }
    if contract.contract_digest != _digest(projection):
        raise MigrationQualityAuthorityError(
            "approved migration quality contract digest drift",
            reason_taxonomy="MIGRATION_QUALITY_CONTRACT_DIGEST_DRIFT",
        )

def validate_pre_post_quality_lineage(
    contract: ApprovedMigrationQualityCriteriaContract,
    *,
    post_policy_digest: str,
    post_criterion_set_digest: str,
    post_lineage_digest: str,
) -> None:
    if (
        post_policy_digest != contract.policy_digest
        or post_criterion_set_digest != contract.criterion_set_digest
        or post_lineage_digest != contract.pre_post_lineage_digest
    ):
        raise MigrationQualityAuthorityError(
            "Pre/Post migration quality criteria lineage drift",
            reason_taxonomy="MIGRATION_QUALITY_PRE_POST_LINEAGE_DRIFT",
        )
