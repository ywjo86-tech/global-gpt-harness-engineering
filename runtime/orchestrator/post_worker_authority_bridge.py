from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from .completion_authority import FrozenCompletionAuthority
from .completion_contract import ExecutionObligation
from .completion_contract_bridge import (
    CompletionBridgeAssessment,
    evaluate_contract_completion,
)
from .execution_contract import CanonicalExecutionContract, ExecutionPackage
from .lv_execution_package import canonical_json_bytes
from .worker_authority import (
    GovernedEffectEvidence,
    WorkerAuthorityError,
    WorkerGateResult,
    WorkerLaunchAuthorization,
    WorkerResultEnvelope,
    evaluate_worker_result,
)

_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class PostWorkerAuthorityBridgeError(RuntimeError):
    def __init__(self, message: str, *, reason_taxonomy: str) -> None:
        super().__init__(message)
        self.reason_taxonomy = reason_taxonomy


@dataclass(frozen=True, slots=True)
class PostWorkerAuthorityEvaluation:
    worker_result: WorkerResultEnvelope
    post_completion: CompletionBridgeAssessment
    worker_gate: WorkerGateResult


def _sha256(value: object, *, field_name: str) -> str:
    if not isinstance(value, str) or not _SHA256.fullmatch(value):
        raise PostWorkerAuthorityBridgeError(
            f"{field_name} is not a canonical sha256 digest",
            reason_taxonomy="POST_WORKER_PROVENANCE_INVALID",
        )
    return value


def _nonempty_string(value: object, *, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise PostWorkerAuthorityBridgeError(
            f"{field_name} is required",
            reason_taxonomy="POST_WORKER_PROVENANCE_INVALID",
        )
    return value.strip()


def _verify_worker_payload_digest(worker_payload: Mapping[str, Any]) -> str:
    supplied = _sha256(
        worker_payload.get("evidence_sha256"),
        field_name="evidence_sha256",
    )
    unsigned = dict(worker_payload)
    unsigned.pop("evidence_sha256", None)
    calculated = hashlib.sha256(canonical_json_bytes(unsigned)).hexdigest()
    if calculated != supplied:
        raise PostWorkerAuthorityBridgeError(
            "production worker evidence digest does not match its canonical payload",
            reason_taxonomy="POST_WORKER_EVIDENCE_DIGEST_DRIFT",
        )
    return supplied


def _effect_evidence(values: object) -> tuple[GovernedEffectEvidence, ...]:
    if not isinstance(values, list):
        raise PostWorkerAuthorityBridgeError(
            "governed effect evidence must be a list",
            reason_taxonomy="POST_WORKER_EFFECT_EVIDENCE_INVALID",
        )
    result: list[GovernedEffectEvidence] = []
    for value in values:
        if not isinstance(value, Mapping):
            raise PostWorkerAuthorityBridgeError(
                "governed effect evidence item is malformed",
                reason_taxonomy="POST_WORKER_EFFECT_EVIDENCE_INVALID",
            )
        try:
            result.append(GovernedEffectEvidence(**dict(value)))
        except (TypeError, ValueError, WorkerAuthorityError) as exc:
            raise PostWorkerAuthorityBridgeError(
                "governed effect evidence item is invalid",
                reason_taxonomy="POST_WORKER_EFFECT_EVIDENCE_INVALID",
            ) from exc
    return tuple(result)


def _changed_files(
    worker_payload: Mapping[str, Any],
    *,
    owned_scope: Sequence[str],
) -> tuple[str, ...]:
    raw = worker_payload.get("changed_files")
    if not isinstance(raw, list) or not raw:
        raise PostWorkerAuthorityBridgeError(
            "MUTATION_REQUIRED worker result has no changed files",
            reason_taxonomy="POST_WORKER_CHANGED_FILES_MISSING",
        )
    if any(not isinstance(item, str) or not item.strip() for item in raw):
        raise PostWorkerAuthorityBridgeError(
            "worker changed-file evidence is malformed",
            reason_taxonomy="POST_WORKER_CHANGED_FILES_INVALID",
        )
    changed = tuple(sorted(set(item.strip() for item in raw)))
    approved = set(owned_scope)
    if any(item not in approved for item in changed):
        raise PostWorkerAuthorityBridgeError(
            "worker changed-file evidence exceeds sealed owned scope",
            reason_taxonomy="POST_WORKER_CHANGED_FILES_OUT_OF_SCOPE",
        )
    return changed


def _artifact_chain(worker_payload: Mapping[str, Any]) -> tuple[str, str, str]:
    chain = worker_payload.get("artifact_sha_chain")
    if not isinstance(chain, Mapping):
        raise PostWorkerAuthorityBridgeError(
            "artifact sha chain is missing",
            reason_taxonomy="POST_WORKER_PROVENANCE_INVALID",
        )
    return (
        _sha256(chain.get("request"), field_name="artifact_sha_chain.request"),
        _sha256(
            chain.get("executor_output"),
            field_name="artifact_sha_chain.executor_output",
        ),
        _sha256(
            chain.get("process_evidence"),
            field_name="artifact_sha_chain.process_evidence",
        ),
    )


def build_mutation_worker_result_envelope(
    package: ExecutionPackage,
    launch: WorkerLaunchAuthorization,
    worker_payload: Mapping[str, Any],
) -> WorkerResultEnvelope:
    if not isinstance(worker_payload, Mapping):
        raise PostWorkerAuthorityBridgeError(
            "production worker payload is malformed",
            reason_taxonomy="POST_WORKER_PAYLOAD_INVALID",
        )
    if worker_payload.get("status") != "completed":
        raise PostWorkerAuthorityBridgeError(
            "production worker did not report completed execution",
            reason_taxonomy="POST_WORKER_NOT_COMPLETED",
        )
    if package.execution_obligation is not ExecutionObligation.MUTATION_REQUIRED:
        raise PostWorkerAuthorityBridgeError(
            "this bridge is restricted to MUTATION_REQUIRED authority",
            reason_taxonomy="POST_WORKER_OBLIGATION_UNSUPPORTED",
        )

    worker_result_digest = _verify_worker_payload_digest(worker_payload)
    changed = _changed_files(
        worker_payload,
        owned_scope=package.owned_scope_projection,
    )
    effects = _effect_evidence(worker_payload.get("governed_effect_evidence"))

    checkpoint_commit = _nonempty_string(
        worker_payload.get("checkpoint_commit"),
        field_name="checkpoint_commit",
    )
    current_tree = _nonempty_string(
        worker_payload.get("current_tree"),
        field_name="current_tree",
    )
    request_digest, executor_output_digest, process_evidence_digest = _artifact_chain(
        worker_payload
    )

    if worker_payload.get("review_verdict") != "PASS":
        raise PostWorkerAuthorityBridgeError(
            "production worker validation verdict is not PASS",
            reason_taxonomy="POST_WORKER_REVIEW_NOT_PASS",
        )

    security_refs = [process_evidence_digest]
    security_refs.extend(
        item.receipt_digest
        for item in effects
        if item.security_passed
    )

    executor = worker_payload.get("executor")
    worker_id = (
        executor.get("identity")
        if isinstance(executor, Mapping)
        else None
    )

    return WorkerResultEnvelope(
        worker_id=_nonempty_string(worker_id, field_name="executor.identity"),
        task_ref=launch.task_ref,
        package_ref=launch.package_ref,
        package_digest=launch.package_digest,
        contract_ref=launch.contract_ref,
        contract_digest=launch.contract_digest,
        terminal_state="CHANGED",
        effect_evidence=effects,
        output_artifact_refs=changed,
        output_provenance_refs=(
            checkpoint_commit,
            current_tree,
            request_digest,
            executor_output_digest,
            process_evidence_digest,
            worker_result_digest,
        ),
        security_evidence_refs=tuple(security_refs),
        worker_claimed_obligation=package.execution_obligation.value,
    )


def evaluate_mutation_post_worker_authority(
    package: ExecutionPackage,
    launch: WorkerLaunchAuthorization,
    active_contract: CanonicalExecutionContract,
    completion_authority: FrozenCompletionAuthority,
    project_root: str | Path,
    worker_payload: Mapping[str, Any],
    *,
    timeout: int = 120,
) -> PostWorkerAuthorityEvaluation:
    if (
        active_contract.contract_digest != package.contract_digest
        or active_contract.activation_digest != package.contract_activation_digest
    ):
        raise PostWorkerAuthorityBridgeError(
            "ACTIVE contract drifted from sealed ExecutionPackage",
            reason_taxonomy="POST_WORKER_CONTRACT_BINDING_DRIFT",
        )

    result = build_mutation_worker_result_envelope(
        package,
        launch,
        worker_payload,
    )
    post = evaluate_contract_completion(
        active_contract,
        completion_authority,
        project_root,
        timeout=timeout,
    )
    gate = evaluate_worker_result(
        package,
        launch,
        result,
        post_completion_assessment=post.assessment,
    )
    return PostWorkerAuthorityEvaluation(
        worker_result=result,
        post_completion=post,
        worker_gate=gate,
    )
