from __future__ import annotations

import ast
import hashlib
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Mapping, Sequence


SCHEMA_VERSION = "orchestration.completion-authority.task-4a-08.v1"
TASK_REF = "TASK-4A-08"
SOURCE_RELATIVE = "tests/test_deduplicator.py"
SNAPSHOT_RELATIVE = "canonical_completion/TASK-4A-08/test_deduplicator.py"
MANIFEST_RELATIVE = "canonical_completion/TASK-4A-08/completion-authority.json"
VERIFIER_TYPE = "FROZEN_PYTEST_NODESET_V1"

# Minimal mapping only to already verified tests that directly implement the
# approved TASK-4A-08 completion meaning.  No extra product behavior is promoted
# to a mandatory Completion criterion.
CRITERION_NODE_BINDINGS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "CC-TASK-4A-08-001",
        (
            "test_product_id_key_is_stable_and_does_not_include_price",
            "test_fallback_key_canonicalizes_merchant_title_and_url",
        ),
    ),
    (
        "CC-TASK-4A-08-002",
        (
            "test_deduplication_is_order_independent_and_preserves_query_lineage",
        ),
    ),
)


class CompletionAuthorityError(RuntimeError):
    def __init__(self, message: str, *, reason_taxonomy: str) -> None:
        super().__init__(message)
        self.reason_taxonomy = reason_taxonomy


@dataclass(frozen=True, slots=True)
class CriterionMaterialization:
    criterion_id: str
    verifier_type: str
    authoritative_source_ref: str
    node_names: tuple[str, ...]
    mandatory: bool = True

    def canonical_projection(self) -> dict[str, Any]:
        return {
            "criterion_id": self.criterion_id,
            "verifier_type": self.verifier_type,
            "authoritative_source_ref": self.authoritative_source_ref,
            "node_names": list(self.node_names),
            "mandatory": self.mandatory,
        }


@dataclass(frozen=True, slots=True)
class FrozenCompletionAuthority:
    task_ref: str
    source_relative: str
    source_sha256: str
    snapshot_relative: str
    snapshot_sha256: str
    node_set_digest: str
    manifest_digest: str
    criteria: tuple[CriterionMaterialization, ...]
    package_root: Path

    @property
    def snapshot_path(self) -> Path:
        return self.package_root / self.snapshot_relative


@dataclass(frozen=True, slots=True)
class CriterionVerificationEvidence:
    criterion_id: str
    state: str
    reason_taxonomy: str
    authoritative_source_ref: str
    snapshot_sha256: str
    node_set_digest: str
    pytest_exit_code: int | None
    stdout_sha256: str
    stderr_sha256: str
    command_digest: str
    evidence_digest: str

    def canonical_projection(self) -> dict[str, Any]:
        return {
            "criterion_id": self.criterion_id,
            "state": self.state,
            "reason_taxonomy": self.reason_taxonomy,
            "authoritative_source_ref": self.authoritative_source_ref,
            "snapshot_sha256": self.snapshot_sha256,
            "node_set_digest": self.node_set_digest,
            "pytest_exit_code": self.pytest_exit_code,
            "stdout_sha256": self.stdout_sha256,
            "stderr_sha256": self.stderr_sha256,
            "command_digest": self.command_digest,
        }


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
        raise CompletionAuthorityError(
            "completion authority value is not canonical-json serializable",
            reason_taxonomy="COMPLETION_AUTHORITY_INVALID",
        ) from exc


def _digest_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _digest(value: object) -> str:
    return _digest_bytes(_canonical_bytes(value))


def _safe_relative(value: str, *, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CompletionAuthorityError(
            f"{field} is required",
            reason_taxonomy="COMPLETION_AUTHORITY_INVALID",
        )
    path = PurePosixPath(value.strip())
    lowered = {part.lower() for part in path.parts}
    if (
        path.is_absolute()
        or ".." in path.parts
        or not path.parts
        or ".git" in lowered
        or ".env" in lowered
        or lowered.intersection({"auth.json", "credentials", "credentials.json"})
    ):
        raise CompletionAuthorityError(
            f"{field} is unsafe",
            reason_taxonomy="COMPLETION_AUTHORITY_PATH_UNSAFE",
        )
    return path.as_posix()


def _safe_file_under(root: Path, relative: str, *, must_exist: bool) -> Path:
    relative = _safe_relative(relative, field="relative path")
    target = root / relative
    root_resolved = root.resolve()
    try:
        target.resolve(strict=False).relative_to(root_resolved)
    except ValueError as exc:
        raise CompletionAuthorityError(
            "completion authority path escaped its root",
            reason_taxonomy="COMPLETION_AUTHORITY_PATH_UNSAFE",
        ) from exc
    current = target
    while current != root:
        if current.exists() and current.is_symlink():
            raise CompletionAuthorityError(
                "completion authority path contains a symlink",
                reason_taxonomy="COMPLETION_AUTHORITY_PATH_UNSAFE",
            )
        current = current.parent
    if must_exist and (not target.is_file() or target.is_symlink()):
        raise CompletionAuthorityError(
            f"required completion authority file is missing: {relative}",
            reason_taxonomy="COMPLETION_AUTHORITY_SOURCE_MISSING",
        )
    return target


def _write_create_once(path: Path, value: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise CompletionAuthorityError(
            "completion authority target is a symlink",
            reason_taxonomy="COMPLETION_AUTHORITY_PATH_UNSAFE",
        )
    if path.exists():
        if not path.is_file():
            raise CompletionAuthorityError(
                "completion authority target is not a regular file",
                reason_taxonomy="COMPLETION_AUTHORITY_PATH_UNSAFE",
            )
        if path.read_bytes() != value:
            raise CompletionAuthorityError(
                "create-once completion authority artifact already exists with different bytes",
                reason_taxonomy="COMPLETION_AUTHORITY_REPLAY_CONFLICT",
            )
        return
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            descriptor = -1
            handle.write(value)
            handle.flush()
            os.fsync(handle.fileno())
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def _required_test_functions(source_bytes: bytes) -> None:
    try:
        text = source_bytes.decode("utf-8")
        tree = ast.parse(text, filename=SOURCE_RELATIVE)
    except (UnicodeError, SyntaxError) as exc:
        raise CompletionAuthorityError(
            "approved test source is not valid UTF-8 Python",
            reason_taxonomy="COMPLETION_AUTHORITY_SOURCE_INVALID",
        ) from exc
    names = {
        node.name
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    required = {name for _criterion, node_names in CRITERION_NODE_BINDINGS for name in node_names}
    missing = sorted(required - names)
    if missing:
        raise CompletionAuthorityError(
            f"approved Completion test nodes are missing: {missing}",
            reason_taxonomy="COMPLETION_AUTHORITY_NODESET_DRIFT",
        )


def _criterion_records(snapshot_sha256: str, node_set_digest: str) -> tuple[CriterionMaterialization, ...]:
    records = []
    for criterion_id, node_names in CRITERION_NODE_BINDINGS:
        source_ref = (
            f"completion-authority://{TASK_REF}/{criterion_id}"
            f"?snapshot_sha256={snapshot_sha256}&node_set_digest={node_set_digest}"
        )
        records.append(
            CriterionMaterialization(
                criterion_id=criterion_id,
                verifier_type=VERIFIER_TYPE,
                authoritative_source_ref=source_ref,
                node_names=node_names,
                mandatory=True,
            )
        )
    return tuple(records)


def materialize_task_4a_08_completion_authority(
    project_root: str | Path,
    package_root: str | Path,
) -> FrozenCompletionAuthority:
    project = Path(project_root).resolve()
    package = Path(package_root).resolve()
    if not project.is_dir() or project.is_symlink():
        raise CompletionAuthorityError(
            "project root is missing or unsafe",
            reason_taxonomy="COMPLETION_AUTHORITY_PROJECT_ROOT_INVALID",
        )
    if not package.is_dir() or package.is_symlink():
        raise CompletionAuthorityError(
            "package root must already exist and be a regular directory",
            reason_taxonomy="COMPLETION_AUTHORITY_PACKAGE_ROOT_INVALID",
        )

    source = _safe_file_under(project, SOURCE_RELATIVE, must_exist=True)
    source_bytes = source.read_bytes()
    _required_test_functions(source_bytes)
    source_sha256 = _digest_bytes(source_bytes)

    snapshot = _safe_file_under(package, SNAPSHOT_RELATIVE, must_exist=False)
    _write_create_once(snapshot, source_bytes)
    snapshot_bytes = snapshot.read_bytes()
    snapshot_sha256 = _digest_bytes(snapshot_bytes)
    if snapshot_sha256 != source_sha256:
        raise CompletionAuthorityError(
            "frozen Completion snapshot differs from pre-Worker source bytes",
            reason_taxonomy="COMPLETION_AUTHORITY_SNAPSHOT_DRIFT",
        )

    node_projection = [
        {"criterion_id": criterion_id, "node_names": list(node_names)}
        for criterion_id, node_names in CRITERION_NODE_BINDINGS
    ]
    node_set_digest = _digest(node_projection)
    criteria = _criterion_records(snapshot_sha256, node_set_digest)

    base = {
        "schema_version": SCHEMA_VERSION,
        "task_ref": TASK_REF,
        "source_relative": SOURCE_RELATIVE,
        "source_sha256": source_sha256,
        "snapshot_relative": SNAPSHOT_RELATIVE,
        "snapshot_sha256": snapshot_sha256,
        "node_set_digest": node_set_digest,
        "verifier_type": VERIFIER_TYPE,
        "criteria": [item.canonical_projection() for item in criteria],
        "worker_may_modify_live_test_source": True,
        "authoritative_source_is_frozen_snapshot": True,
        "post_worker_live_test_source_is_not_authority": True,
    }
    manifest_digest = _digest(base)
    manifest = dict(base)
    manifest["manifest_digest"] = manifest_digest
    manifest_bytes = json.dumps(
        manifest, sort_keys=True, indent=2, ensure_ascii=False
    ).encode("utf-8") + b"\n"
    manifest_path = _safe_file_under(package, MANIFEST_RELATIVE, must_exist=False)
    _write_create_once(manifest_path, manifest_bytes)

    return FrozenCompletionAuthority(
        task_ref=TASK_REF,
        source_relative=SOURCE_RELATIVE,
        source_sha256=source_sha256,
        snapshot_relative=SNAPSHOT_RELATIVE,
        snapshot_sha256=snapshot_sha256,
        node_set_digest=node_set_digest,
        manifest_digest=manifest_digest,
        criteria=criteria,
        package_root=package,
    )


def load_task_4a_08_completion_authority(
    package_root: str | Path,
) -> FrozenCompletionAuthority:
    package = Path(package_root).resolve()
    manifest_path = _safe_file_under(package, MANIFEST_RELATIVE, must_exist=True)
    snapshot_path = _safe_file_under(package, SNAPSHOT_RELATIVE, must_exist=True)

    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (UnicodeError, json.JSONDecodeError, OSError) as exc:
        raise CompletionAuthorityError(
            "Completion authority manifest is unreadable",
            reason_taxonomy="COMPLETION_AUTHORITY_MANIFEST_INVALID",
        ) from exc
    if not isinstance(payload, Mapping):
        raise CompletionAuthorityError(
            "Completion authority manifest root must be an object",
            reason_taxonomy="COMPLETION_AUTHORITY_MANIFEST_INVALID",
        )
    supplied_digest = payload.get("manifest_digest")
    if not isinstance(supplied_digest, str) or not supplied_digest:
        raise CompletionAuthorityError(
            "Completion authority manifest digest is missing",
            reason_taxonomy="COMPLETION_AUTHORITY_MANIFEST_INVALID",
        )
    unsigned = {key: value for key, value in payload.items() if key != "manifest_digest"}
    if _digest(unsigned) != supplied_digest:
        raise CompletionAuthorityError(
            "Completion authority manifest digest mismatch",
            reason_taxonomy="COMPLETION_AUTHORITY_MANIFEST_DRIFT",
        )
    if (
        payload.get("schema_version") != SCHEMA_VERSION
        or payload.get("task_ref") != TASK_REF
        or payload.get("source_relative") != SOURCE_RELATIVE
        or payload.get("snapshot_relative") != SNAPSHOT_RELATIVE
        or payload.get("verifier_type") != VERIFIER_TYPE
        or payload.get("worker_may_modify_live_test_source") is not True
        or payload.get("authoritative_source_is_frozen_snapshot") is not True
        or payload.get("post_worker_live_test_source_is_not_authority") is not True
    ):
        raise CompletionAuthorityError(
            "Completion authority manifest semantics drifted",
            reason_taxonomy="COMPLETION_AUTHORITY_MANIFEST_DRIFT",
        )

    snapshot_bytes = snapshot_path.read_bytes()
    snapshot_sha256 = _digest_bytes(snapshot_bytes)
    if snapshot_sha256 != payload.get("snapshot_sha256"):
        raise CompletionAuthorityError(
            "frozen Completion snapshot digest mismatch",
            reason_taxonomy="COMPLETION_AUTHORITY_SNAPSHOT_DRIFT",
        )
    _required_test_functions(snapshot_bytes)

    expected_node_projection = [
        {"criterion_id": criterion_id, "node_names": list(node_names)}
        for criterion_id, node_names in CRITERION_NODE_BINDINGS
    ]
    expected_node_set_digest = _digest(expected_node_projection)
    if payload.get("node_set_digest") != expected_node_set_digest:
        raise CompletionAuthorityError(
            "Completion criterion node-set digest drifted",
            reason_taxonomy="COMPLETION_AUTHORITY_NODESET_DRIFT",
        )

    criteria = _criterion_records(snapshot_sha256, expected_node_set_digest)
    if payload.get("criteria") != [item.canonical_projection() for item in criteria]:
        raise CompletionAuthorityError(
            "Completion criterion materialization drifted",
            reason_taxonomy="COMPLETION_AUTHORITY_CRITERION_DRIFT",
        )

    return FrozenCompletionAuthority(
        task_ref=TASK_REF,
        source_relative=SOURCE_RELATIVE,
        source_sha256=str(payload.get("source_sha256")),
        snapshot_relative=SNAPSHOT_RELATIVE,
        snapshot_sha256=snapshot_sha256,
        node_set_digest=expected_node_set_digest,
        manifest_digest=supplied_digest,
        criteria=criteria,
        package_root=package,
    )


def _criterion(authority: FrozenCompletionAuthority, criterion_id: str) -> CriterionMaterialization:
    for item in authority.criteria:
        if item.criterion_id == criterion_id:
            return item
    raise CompletionAuthorityError(
        "unknown Completion criterion blocked",
        reason_taxonomy="COMPLETION_AUTHORITY_CRITERION_UNKNOWN",
    )



def _pytest_module_unavailable(stdout: bytes, stderr: bytes) -> bool:
    if stdout:
        return False
    text = stderr.decode("utf-8", "replace").strip()
    return (
        text.endswith(": No module named pytest")
        or text.endswith(": No module named 'pytest'")
    )

def verify_frozen_completion_criterion(
    authority: FrozenCompletionAuthority,
    project_root: str | Path,
    criterion_id: str,
    *,
    timeout: int = 120,
) -> CriterionVerificationEvidence:
    project = Path(project_root).resolve()
    if not project.is_dir() or project.is_symlink():
        raise CompletionAuthorityError(
            "project root is missing or unsafe",
            reason_taxonomy="COMPLETION_AUTHORITY_PROJECT_ROOT_INVALID",
        )

    # Reload first so a tampered snapshot/manifest can never be verified.
    current = load_task_4a_08_completion_authority(authority.package_root)
    if (
        current.manifest_digest != authority.manifest_digest
        or current.snapshot_sha256 != authority.snapshot_sha256
        or current.node_set_digest != authority.node_set_digest
    ):
        raise CompletionAuthorityError(
            "Completion authority handle is stale",
            reason_taxonomy="COMPLETION_AUTHORITY_HANDLE_DRIFT",
        )

    item = _criterion(current, criterion_id)
    snapshot_path = current.snapshot_path
    node_ids = [f"{snapshot_path}::{name}" for name in item.node_names]
    project_python = project / ".venv" / "bin" / "python"
    project_pytest = project / ".venv" / "bin" / "pytest"
    command = [str(project_python), "-m", "pytest", "-q", *node_ids]
    command_digest = _digest(
        {
            "runtime_binding": "PROJECT_LOCAL_VENV",
            "executable": ".venv/bin/python",
            "pytest_entrypoint": ".venv/bin/pytest",
            "module": "pytest",
            "args": ["-q", *[f"{SNAPSHOT_RELATIVE}::{name}" for name in item.node_names]],
            "criterion_id": criterion_id,
            "snapshot_sha256": current.snapshot_sha256,
            "node_set_digest": current.node_set_digest,
        }
    )
    env = dict(os.environ)
    existing_pythonpath = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = str(project) + (
        os.pathsep + existing_pythonpath if existing_pythonpath else ""
    )
    if not project_python.is_file() or not project_pytest.is_file():
        exit_code = None
        stdout_sha = _digest_bytes(b"")
        stderr_sha = _digest_bytes(b"")
        state = "UNKNOWN"
        reason = "FROZEN_COMPLETION_VERIFIER_UNRESOLVED"
    else:
        try:
            completed = subprocess.run(
                command,
                cwd=project,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
                timeout=timeout,
            )
            exit_code = completed.returncode
            stdout_sha = _digest_bytes(completed.stdout)
            stderr_sha = _digest_bytes(completed.stderr)
            if completed.returncode == 0:
                state = "SATISFIED"
                reason = "PASS"
            elif completed.returncode == 1 and _pytest_module_unavailable(
                completed.stdout, completed.stderr
            ):
                state = "UNKNOWN"
                reason = "FROZEN_COMPLETION_VERIFIER_UNRESOLVED"
            elif completed.returncode == 1:
                state = "UNSATISFIED"
                reason = "FROZEN_COMPLETION_TEST_FAILED"
            else:
                state = "UNKNOWN"
                reason = "FROZEN_COMPLETION_VERIFIER_UNRESOLVED"
        except (OSError, subprocess.TimeoutExpired) as exc:
            exit_code = None
            stdout = (
                exc.stdout
                if isinstance(exc, subprocess.TimeoutExpired)
                and isinstance(exc.stdout, bytes)
                else b""
            )
            stderr = (
                exc.stderr
                if isinstance(exc, subprocess.TimeoutExpired)
                and isinstance(exc.stderr, bytes)
                else b""
            )
            stdout_sha = _digest_bytes(stdout)
            stderr_sha = _digest_bytes(stderr)
            state = "UNKNOWN"
            reason = "FROZEN_COMPLETION_VERIFIER_UNRESOLVED"
    projection = {
        "criterion_id": criterion_id,
        "state": state,
        "reason_taxonomy": reason,
        "authoritative_source_ref": item.authoritative_source_ref,
        "snapshot_sha256": current.snapshot_sha256,
        "node_set_digest": current.node_set_digest,
        "pytest_exit_code": exit_code,
        "stdout_sha256": stdout_sha,
        "stderr_sha256": stderr_sha,
        "command_digest": command_digest,
    }
    return CriterionVerificationEvidence(
        criterion_id=criterion_id,
        state=state,
        reason_taxonomy=reason,
        authoritative_source_ref=item.authoritative_source_ref,
        snapshot_sha256=current.snapshot_sha256,
        node_set_digest=current.node_set_digest,
        pytest_exit_code=exit_code,
        stdout_sha256=stdout_sha,
        stderr_sha256=stderr_sha,
        command_digest=command_digest,
        evidence_digest=_digest(projection),
    )


def verify_all_frozen_completion_criteria(
    authority: FrozenCompletionAuthority,
    project_root: str | Path,
    *,
    timeout: int = 120,
) -> tuple[CriterionVerificationEvidence, ...]:
    return tuple(
        verify_frozen_completion_criterion(
            authority,
            project_root,
            item.criterion_id,
            timeout=timeout,
        )
        for item in authority.criteria
    )


def authoritative_source_projection(
    evidence: Sequence[CriterionVerificationEvidence],
) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for item in evidence:
        if item.authoritative_source_ref in result:
            raise CompletionAuthorityError(
                "duplicate authoritative Completion source ref",
                reason_taxonomy="COMPLETION_AUTHORITY_DUPLICATE_SOURCE",
            )
        projection = item.canonical_projection()
        projection["evidence_digest"] = item.evidence_digest
        result[item.authoritative_source_ref] = projection
    return result
