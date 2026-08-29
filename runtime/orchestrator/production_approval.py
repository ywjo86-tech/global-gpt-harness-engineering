from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping

from .approval_hash import calculate_record_hash as calculate_legacy_record_hash


SCHEMA_V2 = "orchestration.production-approval.v2"
SCHEMA_V1 = "orchestration.gate-approval.v1"
APPROVAL_MODES = {"GATE_BY_GATE"}
EVENT_TYPES = {"APPROVED", "CORRECTION"}
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_HEAD = re.compile(r"[0-9a-f]{40,64}\Z")
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")
_SECRET = re.compile(
    r"(?:-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----|"
    r"\b(?:AKIA[0-9A-Z]{16}|gh[pousr]_[A-Za-z0-9]{20,}|sk-[A-Za-z0-9]{20,})\b|"
    r"\b(?:api[_-]?key|authorization|password|token)\s*[:=]\s*\S+)",
    re.IGNORECASE,
)

FIELDS = {
    "schema_version", "event_id", "event_type", "project_id", "gate_id",
    "plan_sha256", "branch", "baseline_head", "approved_at", "recorded_at",
    "approval_mode", "canonical_lv_scope", "owned_file_scope",
    "completion_conditions_sha256", "predecessor", "supersedes",
    "authorization_source", "record_hash",
}


class ProductionApprovalError(ValueError):
    """Fail-closed production approval validation error."""


@dataclass(frozen=True)
class ApprovalBindings:
    project_id: str
    gate_id: str
    plan_sha256: str
    branch: str
    baseline_head: str
    approval_mode: str
    canonical_lv_scope: tuple[str, ...]
    owned_file_scope: Mapping[str, tuple[str, ...]]
    completion_conditions_sha256: str


def canonical_json_bytes(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def calculate_v2_record_hash(event: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_json_bytes({key: value for key, value in event.items() if key != "record_hash"})).hexdigest()


def _utc_time(value: object, field: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ProductionApprovalError(f"{field} must be UTC RFC3339")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise ProductionApprovalError(f"invalid {field}") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise ProductionApprovalError(f"{field} must be UTC RFC3339")
    return parsed


def _identifier(value: object, field: str) -> str:
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise ProductionApprovalError(f"invalid {field}")
    return value


def _relative_path(value: object, field: str) -> str:
    if not isinstance(value, str) or not value or "\\" in value or Path(value).is_absolute():
        raise ProductionApprovalError(f"invalid {field}")
    parts = PurePosixPath(value).parts
    if ".." in parts or "." in parts or any(not part for part in parts):
        raise ProductionApprovalError(f"invalid {field}")
    return value


def _contains_secret(value: object) -> bool:
    if isinstance(value, str):
        return bool(_SECRET.search(value))
    if isinstance(value, Mapping):
        return any(_contains_secret(key) or _contains_secret(item) for key, item in value.items())
    if isinstance(value, (list, tuple)):
        return any(_contains_secret(item) for item in value)
    return False


def validate_v2_schema(event: Mapping[str, Any], *, now: datetime | None = None) -> dict[str, Any]:
    if set(event) != FIELDS or event.get("schema_version") != SCHEMA_V2:
        raise ProductionApprovalError("production approval v2 schema mismatch")
    if _contains_secret(event):
        raise ProductionApprovalError("approval event contains secret-like material")
    for field in ("event_id", "project_id", "gate_id", "branch", "authorization_source"):
        _identifier(event.get(field), field)
    if event.get("event_type") not in EVENT_TYPES:
        raise ProductionApprovalError("invalid event_type")
    for field in ("plan_sha256", "completion_conditions_sha256", "record_hash"):
        if not isinstance(event.get(field), str) or not _SHA256.fullmatch(event[field]):
            raise ProductionApprovalError(f"invalid {field}")
    if not isinstance(event.get("baseline_head"), str) or not _HEAD.fullmatch(event["baseline_head"]):
        raise ProductionApprovalError("invalid baseline_head")
    if event.get("approval_mode") not in APPROVAL_MODES:
        raise ProductionApprovalError("invalid approval_mode")

    scope = event.get("canonical_lv_scope")
    owned = event.get("owned_file_scope")
    if not isinstance(scope, list) or not scope or len(scope) != len(set(scope)):
        raise ProductionApprovalError("invalid canonical_lv_scope")
    for item in scope:
        _identifier(item, "canonical_lv_scope")
    if not isinstance(owned, dict) or set(owned) != set(scope):
        raise ProductionApprovalError("owned_file_scope must exactly cover canonical_lv_scope")
    for lv_id, paths in owned.items():
        if not isinstance(paths, list) or not paths or len(paths) != len(set(paths)):
            raise ProductionApprovalError(f"invalid owned_file_scope for {lv_id}")
        for path in paths:
            _relative_path(path, "owned_file_scope path")

    predecessor = event.get("predecessor")
    supersedes = event.get("supersedes")
    if predecessor is not None and (not isinstance(predecessor, str) or not _SHA256.fullmatch(predecessor)):
        raise ProductionApprovalError("invalid predecessor")
    if supersedes is not None:
        _identifier(supersedes, "supersedes")
    if event["event_type"] == "APPROVED" and supersedes is not None:
        raise ProductionApprovalError("APPROVED event cannot supersede another event")
    if event["event_type"] == "CORRECTION" and (predecessor is None or supersedes is None):
        raise ProductionApprovalError("CORRECTION requires predecessor and supersedes")

    approved = _utc_time(event.get("approved_at"), "approved_at")
    recorded = _utc_time(event.get("recorded_at"), "recorded_at")
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None or current.utcoffset() != timezone.utc.utcoffset(current):
        raise ProductionApprovalError("validation clock must be UTC-aware")
    if approved > recorded:
        raise ProductionApprovalError("approved_at cannot be after recorded_at")
    if recorded > current:
        raise ProductionApprovalError("recorded_at cannot be in the future")
    if calculate_v2_record_hash(event) != event["record_hash"]:
        raise ProductionApprovalError("production approval record_hash mismatch")
    return dict(event)


def validate_v2_chain(
    events: Iterable[Mapping[str, Any]], *, now: datetime | None = None,
    initial_predecessor: str | None = None, known_supersedes: Iterable[str] = (),
) -> list[dict[str, Any]]:
    validated: list[dict[str, Any]] = []
    ids: set[str] = set()
    previous_hash: str | None = initial_predecessor
    by_id: dict[str, dict[str, Any]] = {}
    historical_ids = set(known_supersedes)
    for index, raw in enumerate(events, start=1):
        event = validate_v2_schema(raw, now=now)
        event_id = event["event_id"]
        if event_id in ids:
            raise ProductionApprovalError(f"duplicate production approval event_id at event {index}")
        if event["predecessor"] != previous_hash:
            raise ProductionApprovalError(f"broken predecessor at event {index}")
        supersedes = event["supersedes"]
        if supersedes is not None:
            prior = by_id.get(supersedes)
            if prior is None and supersedes not in historical_ids:
                raise ProductionApprovalError(f"supersedes does not identify a prior event at event {index}")
            if prior is not None and (prior["project_id"], prior["gate_id"]) != (event["project_id"], event["gate_id"]):
                raise ProductionApprovalError(f"cross-scope correction at event {index}")
        ids.add(event_id)
        by_id[event_id] = event
        previous_hash = event["record_hash"]
        validated.append(event)
    if not validated:
        raise ProductionApprovalError("no production approval v2 events")
    return validated


def evaluate_production_authorization(
    events: Iterable[Mapping[str, Any]], bindings: ApprovalBindings, *, now: datetime | None = None,
    historical_predecessor: str | None = None, historical_event_ids: Iterable[str] = (),
) -> dict[str, Any]:
    chain = validate_v2_chain(
        events, now=now, initial_predecessor=historical_predecessor,
        known_supersedes=historical_event_ids,
    )
    event = chain[-1]
    expected: dict[str, object] = {
        "project_id": bindings.project_id,
        "gate_id": bindings.gate_id,
        "plan_sha256": bindings.plan_sha256,
        "branch": bindings.branch,
        "baseline_head": bindings.baseline_head,
        "approval_mode": bindings.approval_mode,
        "canonical_lv_scope": list(bindings.canonical_lv_scope),
        "owned_file_scope": {key: list(value) for key, value in bindings.owned_file_scope.items()},
        "completion_conditions_sha256": bindings.completion_conditions_sha256,
    }
    for field, value in expected.items():
        if event.get(field) != value:
            raise ProductionApprovalError(f"production approval {field} binding mismatch")
    return event


def classify_approval_schema(event: Mapping[str, Any]) -> str:
    """Classify legacy records without ever authorizing production from v1."""
    if event.get("schema_version") == SCHEMA_V1:
        return "HISTORICAL_READ_ONLY"
    if event.get("schema_version") == SCHEMA_V2:
        return "PRODUCTION_V2"
    return "UNSUPPORTED"


def load_v2_event_log(path: str | Path, *, now: datetime | None = None) -> list[dict[str, Any]]:
    source = Path(path)
    if not source.is_file() or source.is_symlink() or source.stat().st_size > 1024 * 1024:
        raise ProductionApprovalError("production approval log is missing or unsafe")
    try:
        text_value = source.read_text(encoding="utf-8")
        raw = json.loads(text_value)
    except (UnicodeError, json.JSONDecodeError) as exc:
        if isinstance(exc, UnicodeError):
            raise ProductionApprovalError("production approval log is malformed") from exc
        legacy, production = _load_markdown_events(text_value)
        predecessor = legacy[-1]["record_hash"] if legacy else None
        return validate_v2_chain(
            production, now=now, initial_predecessor=predecessor,
            known_supersedes=(str(item["approval_id"]) for item in legacy),
        )
    if not isinstance(raw, dict) or set(raw) != {"schema_version", "events"}:
        raise ProductionApprovalError("production approval log schema mismatch")
    if raw["schema_version"] != "orchestration.production-approval-log.v2" or not isinstance(raw["events"], list):
        raise ProductionApprovalError("production approval log schema mismatch")
    return validate_v2_chain(raw["events"], now=now)


def _load_markdown_events(text_value: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    blocks = re.findall(r"```json[ \t]*\r?\n(.*?)\r?\n```", text_value, flags=re.DOTALL)
    if not blocks:
        raise ProductionApprovalError("production approval log is malformed")
    legacy: list[dict[str, Any]] = []
    production: list[dict[str, Any]] = []
    previous_hash: str | None = None
    legacy_ids: set[str] = set()
    for index, block in enumerate(blocks, start=1):
        try:
            event = json.loads(block)
        except json.JSONDecodeError as exc:
            raise ProductionApprovalError("approval Markdown contains malformed JSON") from exc
        if not isinstance(event, dict):
            raise ProductionApprovalError("approval Markdown event must be an object")
        if event.get("schema_version") == SCHEMA_V2:
            production.append(event)
            continue
        approval_id = event.get("approval_id")
        record_hash = event.get("record_hash")
        if not isinstance(approval_id, str) or not approval_id or approval_id in legacy_ids:
            raise ProductionApprovalError(f"legacy approval event {index} has an invalid or duplicate ID")
        if event.get("previous_record_hash") != previous_hash:
            raise ProductionApprovalError(f"legacy approval event {index} has a broken hash chain")
        if not isinstance(record_hash, str) or not _SHA256.fullmatch(record_hash) or calculate_legacy_record_hash(event) != record_hash:
            raise ProductionApprovalError(f"legacy approval event {index} record_hash mismatch")
        legacy_ids.add(approval_id)
        previous_hash = record_hash
        legacy.append(event)
    if production:
        validate_v2_chain(
            production, initial_predecessor=previous_hash,
            known_supersedes=legacy_ids,
        )
    return legacy, production


def _git(root: Path, *args: str) -> str:
    result = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise ProductionApprovalError("Git binding inspection failed")
    return result.stdout.strip()


def inspect_git_binding(project_root: str | Path, *, allowed_dirty_paths: Iterable[str] = ()) -> tuple[Path, str, str]:
    root = Path(project_root).resolve()
    if not root.is_dir() or _git(root, "rev-parse", "--show-toplevel") != str(root):
        raise ProductionApprovalError("project_root must be a Git top-level directory")
    allowed = set(allowed_dirty_paths)
    dirty = _git(root, "status", "--porcelain=v1", "--untracked-files=all").splitlines()
    dirty_paths = {line[3:].split(" -> ")[-1] for line in dirty if len(line) > 3}
    if dirty_paths - allowed:
        raise ProductionApprovalError("production approval requires a clean Git worktree")
    branch_result = subprocess.run(
        ["git", "-C", str(root), "symbolic-ref", "--quiet", "--short", "HEAD"],
        capture_output=True, text=True, check=False,
    )
    branch = branch_result.stdout.strip()
    if branch_result.returncode != 0 or not branch:
        raise ProductionApprovalError("production approval requires an attached Git branch")
    head = _git(root, "rev-parse", "HEAD")
    if not _HEAD.fullmatch(head):
        raise ProductionApprovalError("invalid Git baseline HEAD")
    return root, branch, head


def _atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink() or path.parent.is_symlink():
        raise ProductionApprovalError("production approval log path is unsafe")
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except Exception:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def write_production_approval(
    *, project_root: str | Path, output_path: str | Path, gate_id: str,
    plan_sha256: str, approval_mode: str, canonical_lv_scope: Iterable[str],
    owned_file_scope: Mapping[str, Iterable[str]], completion_conditions_sha256: str,
    authorization_source: str, correction_of: str | None = None,
    dry_run: bool = False, read_only: bool = False,
) -> dict[str, Any]:
    root = Path(project_root).resolve()
    output = Path(output_path)
    if not output.is_absolute():
        output = root / output
    resolved_parent = output.parent.resolve()
    if not resolved_parent.is_relative_to(root) or output.is_symlink():
        raise ProductionApprovalError("production approval output escapes the project root or is unsafe")
    relative_output = output.relative_to(root).as_posix()
    root, branch, head = inspect_git_binding(project_root, allowed_dirty_paths=(relative_output,))
    existing: list[dict[str, Any]] = []
    legacy: list[dict[str, Any]] = []
    markdown_text: str | None = None
    markdown_log = False
    if output.exists():
        try:
            markdown_text = output.read_text(encoding="utf-8")
        except UnicodeError as exc:
            raise ProductionApprovalError("production approval log is malformed") from exc
        if markdown_text.lstrip().startswith("#"):
            markdown_log = True
            legacy, existing = _load_markdown_events(markdown_text)
        else:
            existing = load_v2_event_log(output)
    all_ids = {str(item["approval_id"]) for item in legacy} | {str(item["event_id"]) for item in existing}
    if correction_of is not None and not (legacy or existing):
        raise ProductionApprovalError("correction requires an existing production approval log")
    if correction_of is not None and correction_of not in all_ids:
        raise ProductionApprovalError("correction target does not exist")

    clock = datetime.now(timezone.utc)
    timestamp = clock.isoformat(timespec="microseconds").replace("+00:00", "Z")
    event_id = f"APR-{gate_id}-{clock.strftime('%Y%m%dT%H%M%S%fZ')}"
    superseded_event = next(
        (item for item in [*legacy, *existing] if item.get("approval_id", item.get("event_id")) == correction_of),
        None,
    )
    approved_timestamp = superseded_event.get("approved_at") if superseded_event is not None else timestamp
    _utc_time(approved_timestamp, "approved_at")
    predecessor = existing[-1]["record_hash"] if existing else legacy[-1]["record_hash"] if legacy else None
    candidate: dict[str, Any] = {
        "schema_version": SCHEMA_V2,
        "event_id": event_id,
        "event_type": "CORRECTION" if correction_of else "APPROVED",
        "project_id": root.name,
        "gate_id": gate_id,
        "plan_sha256": plan_sha256,
        "branch": branch,
        "baseline_head": head,
        "approved_at": approved_timestamp,
        "recorded_at": timestamp,
        "approval_mode": approval_mode,
        "canonical_lv_scope": list(canonical_lv_scope),
        "owned_file_scope": {key: list(value) for key, value in owned_file_scope.items()},
        "completion_conditions_sha256": completion_conditions_sha256,
        "predecessor": predecessor,
        "supersedes": correction_of,
        "authorization_source": authorization_source,
        "record_hash": "0" * 64,
    }
    candidate["record_hash"] = calculate_v2_record_hash(candidate)
    validate_v2_chain(
        [*existing, candidate], now=clock,
        initial_predecessor=legacy[-1]["record_hash"] if legacy else None,
        known_supersedes=(str(item["approval_id"]) for item in legacy),
    )
    result = {
        "status": "DRY_RUN" if dry_run else "READ_ONLY" if read_only else "WRITTEN",
        "mutation_performed": not (dry_run or read_only),
        "event": candidate,
        "event_count": len(existing) + 1,
    }
    if dry_run or read_only:
        return result
    if markdown_log and markdown_text is not None:
        heading = f"## Production Approval v2 — {candidate['event_id']}"
        block = json.dumps(candidate, sort_keys=True, indent=2, ensure_ascii=False)
        appended = markdown_text.rstrip("\n") + f"\n\n{heading}\n\n```json\n{block}\n```\n"
        _atomic_write(output, appended.encode("utf-8"))
    else:
        envelope = {"schema_version": "orchestration.production-approval-log.v2", "events": [*existing, candidate]}
        _atomic_write(output, canonical_json_bytes(envelope) + b"\n")
    return result
