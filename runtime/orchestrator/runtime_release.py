"""Immutable Git-backed runtime release staging and safe activation."""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import tarfile
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any

from .durable_io import atomic_write_json
from .harness_state_root import job_state_root
from .runtime_migration_handoff import MigrationPhase, RuntimeMigrationTransaction

SCHEMA_VERSION_V1 = "gch.runtime-release.v1"
SCHEMA_VERSION = "gch.runtime-release.v2"


class RuntimeReleaseError(ValueError):
    pass


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _git(root: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(root), *args], capture_output=True, text=True,
        check=False, timeout=30,
    )
    if completed.returncode != 0:
        raise RuntimeReleaseError("Git verification failed")
    return completed.stdout.strip()


def _regular_sha256(path: Path) -> str:
    if path.is_symlink() or not path.is_file():
        raise RuntimeReleaseError("runtime release file is unsafe")
    return hashlib.sha256(path.read_bytes()).hexdigest()


@dataclass(frozen=True, slots=True)
class RuntimeReleaseManifest:
    schema_version: str
    source_head: str
    source_tree: str
    release_path: str
    runtime_entry: str
    runtime_entry_sha256: str
    manifest_sha256: str
    publication_head: str = ""

    @classmethod
    def from_mapping(cls, payload: dict[str, Any]) -> "RuntimeReleaseManifest":
        common = {
            "schema_version", "source_head", "source_tree", "release_path",
            "runtime_entry", "runtime_entry_sha256", "manifest_sha256",
        }
        schema = str(payload.get("schema_version") or "")
        required = common if schema == SCHEMA_VERSION_V1 else common | {"publication_head"}
        if schema not in {SCHEMA_VERSION_V1, SCHEMA_VERSION} or set(payload) != required:
            raise RuntimeReleaseError("runtime release manifest fields mismatch")
        unsigned = {key: payload[key] for key in required if key != "manifest_sha256"}
        if _digest(unsigned) != str(payload.get("manifest_sha256") or ""):
            raise RuntimeReleaseError("runtime release manifest digest mismatch")
        publication_head = str(payload.get("publication_head") or payload.get("source_head") or "")
        if publication_head != str(payload.get("source_head") or ""):
            raise RuntimeReleaseError("runtime release publication/source head mismatch")
        return cls(
            schema_version=schema, source_head=str(payload["source_head"]),
            source_tree=str(payload["source_tree"]), release_path=str(payload["release_path"]),
            runtime_entry=str(payload["runtime_entry"]), runtime_entry_sha256=str(payload["runtime_entry_sha256"]),
            manifest_sha256=str(payload["manifest_sha256"]), publication_head=publication_head,
        )


def _safe_member_name(name: str) -> PurePosixPath:
    value = PurePosixPath(name)
    if value.is_absolute() or not value.parts or any(part in {"", ".", ".."} for part in value.parts):
        raise RuntimeReleaseError("unsafe archive member")
    return value


def _extract_archive_bytes(payload: bytes, target: str | Path) -> None:
    root = Path(target)
    root.mkdir(parents=True, exist_ok=False)
    try:
        with tarfile.open(fileobj=io.BytesIO(payload), mode="r:") as archive:
            for member in archive.getmembers():
                relative = _safe_member_name(member.name)
                destination = root.joinpath(*relative.parts)
                if member.isdir():
                    destination.mkdir(parents=True, exist_ok=True)
                    continue
                if not member.isreg():
                    raise RuntimeReleaseError("unsafe archive member")
                destination.parent.mkdir(parents=True, exist_ok=True)
                source = archive.extractfile(member)
                if source is None:
                    raise RuntimeReleaseError("runtime archive member is unreadable")
                data = source.read()
                with destination.open("wb") as handle:
                    handle.write(data)
                    handle.flush(); os.fsync(handle.fileno())
                os.chmod(destination, 0o755 if member.mode & 0o111 else 0o644)
    except Exception:
        shutil.rmtree(root, ignore_errors=True)
        raise


def _archive(root: Path, head: str) -> bytes:
    completed = subprocess.run(
        ["git", "-C", str(root), "archive", "--format=tar", head],
        capture_output=True, check=False, timeout=120,
    )
    if completed.returncode != 0:
        raise RuntimeReleaseError("Git archive failed")
    return bytes(completed.stdout)

def verify_runtime_release(release_path: str | Path, expected_head: str) -> RuntimeReleaseManifest:
    release = Path(release_path).expanduser().absolute()
    if release.is_symlink() or not release.is_dir():
        raise RuntimeReleaseError("runtime release root is unsafe")
    manifest_path = release / "RUNTIME_RELEASE_MANIFEST.json"
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise RuntimeReleaseError("runtime release manifest is missing")
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RuntimeReleaseError("runtime release manifest is malformed") from exc
    if not isinstance(payload, dict):
        raise RuntimeReleaseError("runtime release manifest is malformed")
    manifest = RuntimeReleaseManifest.from_mapping(payload)
    if manifest.source_head != str(expected_head):
        raise RuntimeReleaseError("runtime release source head mismatch")
    if Path(manifest.release_path).resolve() != release.resolve():
        raise RuntimeReleaseError("runtime release path binding mismatch")
    entry = release / manifest.runtime_entry
    if _regular_sha256(entry) != manifest.runtime_entry_sha256:
        raise RuntimeReleaseError("runtime release entry digest mismatch")
    return manifest


def build_runtime_release(
    project_root: str | Path, releases_root: str | Path, source_ref: str = "HEAD",
) -> RuntimeReleaseManifest:
    project = Path(project_root).resolve()
    releases = Path(releases_root).expanduser().absolute()
    if not project.is_dir() or project.is_symlink():
        raise RuntimeReleaseError("project root is unsafe")
    if _git(project, "status", "--porcelain=v1", "-uall"):
        raise RuntimeReleaseError("runtime release requires a clean source tree")
    if releases.is_symlink():
        raise RuntimeReleaseError("releases root must not be a symlink")
    releases.mkdir(parents=True, exist_ok=True)
    head = _git(project, "rev-parse", f"{source_ref}^{{commit}}")
    tree = _git(project, "rev-parse", f"{head}^{{tree}}")
    release = releases / head
    if release.exists() or release.is_symlink():
        return verify_runtime_release(release, head)
    temporary = releases / f"{head}.new-{os.getpid()}"
    if temporary.exists() or temporary.is_symlink():
        shutil.rmtree(temporary, ignore_errors=True)
        temporary.unlink(missing_ok=True)
    _extract_archive_bytes(_archive(project, head), temporary)
    entry_relative = "runtime/orchestrator/production_full_plan_boot.py"
    entry = temporary / entry_relative
    entry_sha = _regular_sha256(entry)
    unsigned = {
        "schema_version": SCHEMA_VERSION,
        "source_head": head,
        "source_tree": tree,
        "release_path": str(release.absolute()),
        "runtime_entry": entry_relative,
        "runtime_entry_sha256": entry_sha,
        "publication_head": head,
    }
    payload = {**unsigned, "manifest_sha256": _digest(unsigned)}
    atomic_write_json(temporary / "RUNTIME_RELEASE_MANIFEST.json", payload)
    os.replace(temporary, release)
    fd = os.open(str(releases), getattr(os, "O_DIRECTORY", 0) | os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
    return verify_runtime_release(release, head)


@dataclass(frozen=True, slots=True)
class ActiveRegisteredJob:
    job_path: str
    project_id: str
    run_id: str
    state: str
    state_sha256: str
    migration_id: str = ""
    migration_successor_run_id: str = ""
    load_error: bool = False


def _active_registered_jobs(search_root: str | Path) -> list[ActiveRegisteredJob]:
    from .production_full_plan_boot import discover_registered_jobs
    from .production_full_plan_entry import load_job, recover_registered_job_state_after_external_binding_drift
    from .production_full_plan_runner import DurableFullPlanSupervisor, TERMINAL_STATES

    active: list[ActiveRegisteredJob] = []
    for job_path in discover_registered_jobs(search_root):
        try:
            job = load_job(job_path)
            gates = [str(item["gate_id"]) for item in job["gates"]]
            state, _ = DurableFullPlanSupervisor(
                job_state_root(job), project_id=job["project_id"], run_id=job["run_id"],
                gates=gates, authority_core_sha256=str(job.get("authority_core_sha256") or ""),
                **dict(job.get("policy") or {}),
            ).load()
        except Exception:
            try:
                recovered_job, state = recover_registered_job_state_after_external_binding_drift(job_path)
            except Exception:
                active.append(ActiveRegisteredJob(str(job_path), "", "", "UNKNOWN", "", load_error=True))
                continue
            if str(state.get("state")) in TERMINAL_STATES:
                continue
            active.append(ActiveRegisteredJob(
                str(job_path), str(recovered_job.get("project_id") or ""), str(recovered_job.get("run_id") or ""),
                str(state.get("state") or ""), str(state.get("state_sha256") or ""),
                str(state.get("migration_id") or ""), str(state.get("migration_successor_run_id") or ""), load_error=True,
            ))
            continue
        if str(state.get("state")) not in TERMINAL_STATES:
            active.append(ActiveRegisteredJob(
                str(job_path), str(job.get("project_id") or ""), str(job.get("run_id") or ""),
                str(state.get("state") or ""), str(state.get("state_sha256") or ""),
                str(state.get("migration_id") or ""), str(state.get("migration_successor_run_id") or ""),
            ))
    return active


def _migration_activation_blockers(
    active: list[ActiveRegisteredJob], manifest: RuntimeReleaseManifest,
    transaction: RuntimeMigrationTransaction | None,
) -> list[ActiveRegisteredJob]:
    if transaction is None:
        return active
    if transaction.phase != MigrationPhase.PREDECESSOR_QUIESCED:
        raise RuntimeReleaseError("runtime migration transaction is not quiesced")
    if (transaction.target_release_head != manifest.source_head
            or transaction.target_manifest_sha256 != manifest.manifest_sha256):
        raise RuntimeReleaseError("runtime migration target binding mismatch")
    predecessor = [item for item in active if item.project_id == transaction.project_id
                   and item.run_id == transaction.predecessor_run_id]
    if len(predecessor) != 1:
        raise RuntimeReleaseError("runtime migration predecessor is not uniquely active")
    item = predecessor[0]
    if (item.load_error or item.state != "WAITING_RESOURCE"
            or item.state_sha256 != transaction.quiesced_state_sha256
            or item.migration_id != transaction.migration_id
            or item.migration_successor_run_id != transaction.successor_run_id):
        raise RuntimeReleaseError("runtime migration predecessor quiescence binding mismatch")
    return [candidate for candidate in active if candidate is not item]


def activate_runtime_release(
    manifest: RuntimeReleaseManifest, runtime_link: str | Path, *, job_search_root: str | Path,
    migration_transaction: RuntimeMigrationTransaction | None = None,
) -> Path:
    verified = verify_runtime_release(manifest.release_path, manifest.source_head)
    if verified != manifest:
        raise RuntimeReleaseError("runtime release manifest binding mismatch")
    active = _active_registered_jobs(job_search_root)
    blockers = _migration_activation_blockers(active, manifest, migration_transaction)
    if blockers:
        raise RuntimeReleaseError("cannot retarget runtime link while active Full Plan jobs exist")
    link = Path(runtime_link).expanduser().absolute()
    link.parent.mkdir(parents=True, exist_ok=True)
    if link.exists() or link.is_symlink():
        if not link.is_symlink():
            raise RuntimeReleaseError("runtime link path is not a symlink")
        try:
            current = link.resolve(strict=True)
        except FileNotFoundError:
            current = None
        if current == Path(manifest.release_path).resolve():
            return link
    temporary = link.with_name(link.name + f".tmp-{os.getpid()}")
    temporary.unlink(missing_ok=True)
    os.symlink(str(Path(manifest.release_path).resolve()), str(temporary))
    os.replace(temporary, link)
    fd = os.open(str(link.parent), getattr(os, "O_DIRECTORY", 0) | os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
    return link



def rollback_evidence_path(job_search_root: str | Path, project_id: str, migration_id: str) -> Path:
    if not re.fullmatch(r"[A-Za-z0-9._-]{1,160}", str(project_id or "")):
        raise RuntimeReleaseError("rollback evidence project ID is invalid")
    if not re.fullmatch(r"[A-Za-z0-9._-]{1,160}", str(migration_id or "")):
        raise RuntimeReleaseError("rollback evidence migration ID is invalid")
    return (Path(job_search_root).expanduser().resolve() / "_workspace" / "runtime-rollback-evidence"
            / str(project_id) / f"{migration_id}.json")


def _migration_reverse_blockers(
    active: list[ActiveRegisteredJob], transaction: RuntimeMigrationTransaction,
) -> list[ActiveRegisteredJob]:
    from .runtime_migration_handoff import MIGRATION_SCHEMA_V2
    if transaction.schema_version != MIGRATION_SCHEMA_V2:
        raise RuntimeReleaseError("reverse activation requires migration v2")
    if transaction.phase not in {
        MigrationPhase.RUNTIME_ACTIVATED, MigrationPhase.SUCCESSOR_REGISTERED,
        MigrationPhase.SUCCESSOR_VERIFIED, MigrationPhase.ACTIVE_RUNTIME_QUALIFICATION,
    }:
        raise RuntimeReleaseError("runtime migration is not in a reversible activated phase")
    predecessor = [item for item in active if item.project_id == transaction.project_id
                   and item.run_id == transaction.predecessor_run_id]
    if len(predecessor) != 1:
        raise RuntimeReleaseError("runtime migration predecessor is not uniquely active")
    item = predecessor[0]
    if (item.load_error or item.state != "WAITING_RESOURCE"
            or item.state_sha256 != transaction.quiesced_state_sha256
            or item.migration_id != transaction.migration_id
            or item.migration_successor_run_id != transaction.successor_run_id):
        raise RuntimeReleaseError("runtime migration predecessor quiescence binding mismatch")
    return [candidate for candidate in active if candidate is not item]


def reverse_activate_runtime_release(
    source_manifest: RuntimeReleaseManifest, runtime_link: str | Path, *, job_search_root: str | Path,
    migration_transaction: RuntimeMigrationTransaction,
) -> Path:
    """Restore the sealed v2 source runtime and emit durable rollback evidence.

    This is the runtime effect. MigrationStore.rollback() remains bookkeeping and
    is intentionally illegal after activation until this evidence is recorded.
    """
    verified_source = verify_runtime_release(source_manifest.release_path, source_manifest.source_head)
    if verified_source != source_manifest:
        raise RuntimeReleaseError("runtime rollback source manifest binding mismatch")
    if (migration_transaction.source_head != source_manifest.source_head
            or migration_transaction.source_tree != source_manifest.source_tree
            or migration_transaction.source_manifest_sha256 != source_manifest.manifest_sha256):
        raise RuntimeReleaseError("runtime rollback source binding mismatch")

    link = Path(runtime_link).expanduser().absolute()
    if not link.is_symlink():
        raise RuntimeReleaseError("runtime rollback requires an active runtime symlink")
    try:
        current_release = link.resolve(strict=True)
    except FileNotFoundError as exc:
        raise RuntimeReleaseError("active runtime link is broken") from exc
    current_manifest = verify_runtime_release(current_release, migration_transaction.target_release_head)
    if current_manifest.manifest_sha256 != migration_transaction.target_manifest_sha256:
        raise RuntimeReleaseError("active runtime target binding mismatch")

    active = _active_registered_jobs(job_search_root)
    blockers = _migration_reverse_blockers(active, migration_transaction)
    if blockers:
        raise RuntimeReleaseError("cannot reverse runtime link while unrelated active Full Plan jobs exist")

    temporary = link.with_name(link.name + f".rollback-{os.getpid()}")
    temporary.unlink(missing_ok=True)
    os.symlink(str(Path(source_manifest.release_path).resolve()), str(temporary))
    os.replace(temporary, link)
    fd = os.open(str(link.parent), getattr(os, "O_DIRECTORY", 0) | os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
    restored = verify_runtime_release(link.resolve(strict=True), source_manifest.source_head)
    if restored.manifest_sha256 != source_manifest.manifest_sha256:
        raise RuntimeReleaseError("restored runtime verification failed")

    evidence_path = rollback_evidence_path(job_search_root, migration_transaction.project_id, migration_transaction.migration_id)
    unsigned = {
        "schema_version": "gch.runtime-rollback-evidence.v1",
        "project_id": migration_transaction.project_id,
        "migration_id": migration_transaction.migration_id,
        "predecessor_run_id": migration_transaction.predecessor_run_id,
        "successor_run_id": migration_transaction.successor_run_id,
        "source_head": source_manifest.source_head,
        "source_tree": source_manifest.source_tree,
        "source_manifest_sha256": source_manifest.manifest_sha256,
        "replaced_target_head": current_manifest.source_head,
        "replaced_target_manifest_sha256": current_manifest.manifest_sha256,
        "runtime_link": str(link),
        "restored_release_path": str(Path(source_manifest.release_path).resolve()),
        "restored_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    evidence = {**unsigned, "evidence_sha256": _digest(unsigned)}
    if evidence_path.exists():
        if evidence_path.is_symlink() or not evidence_path.is_file():
            raise RuntimeReleaseError("rollback evidence path is unsafe")
        try:
            existing = json.loads(evidence_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise RuntimeReleaseError("rollback evidence is malformed") from exc
        # Idempotent re-entry may have a different restored_at only if the prior
        # effect already completed. Preserve the first immutable evidence.
        for key in unsigned:
            if key == "restored_at":
                continue
            if existing.get(key) != unsigned[key]:
                raise RuntimeReleaseError("conflicting rollback evidence exists")
    else:
        atomic_write_json(evidence_path, evidence)
    return link

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build, verify, or activate immutable Harness runtime releases")
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build")
    build.add_argument("--project-root", required=True)
    build.add_argument("--releases-root", required=True)
    build.add_argument("--source-ref", default="HEAD")
    verify = sub.add_parser("verify")
    verify.add_argument("--release", required=True)
    verify.add_argument("--expected-head", required=True)
    activate = sub.add_parser("activate")
    activate.add_argument("--release", required=True)
    activate.add_argument("--runtime-link", required=True)
    activate.add_argument("--job-search-root", required=True)
    args = parser.parse_args(argv)
    if args.command == "build":
        result = build_runtime_release(args.project_root, args.releases_root, args.source_ref)
    elif args.command == "verify":
        result = verify_runtime_release(args.release, args.expected_head)
    else:
        manifest_path = Path(args.release) / "RUNTIME_RELEASE_MANIFEST.json"
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        result = RuntimeReleaseManifest.from_mapping(payload)
        activate_runtime_release(result, args.runtime_link, job_search_root=args.job_search_root)
    print(json.dumps(asdict(result), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
