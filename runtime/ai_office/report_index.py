"""Canonical append-only AI Office report index."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Mapping

from .contracts import canonical_digest
from .reporting import (
    OFFICE_KPI_SCHEMA_V1,
    OFFICE_REPORT_SCHEMA_V1,
    OFFICE_STATUS_SCHEMA_V1,
    OfficeKPIProjectionV1,
    OfficeReportV1,
    OfficeStatusProjectionV1,
    ReportingError,
)

OFFICE_REPORT_INDEX_REGISTRY_SCHEMA_V1 = "ai-office.report-index-registry.v1"
OFFICE_REPORT_INDEX_ENTRY_SCHEMA_V1 = "ai-office.report-index-entry.v1"


class AIOfficeReportIndexError(ValueError):
    pass


def _safe_component(value: object, label: str) -> str:
    item = str(value).strip()
    if not item or len(item) > 160 or "/" in item or "\\" in item or ".." in item:
        raise AIOfficeReportIndexError(f"unsafe {label}")
    return item


def _text(value: object, label: str, *, limit: int = 512) -> str:
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > limit:
        raise AIOfficeReportIndexError(f"invalid {label}")
    return value.strip()


def _timestamp(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise AIOfficeReportIndexError("invalid published_at")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise AIOfficeReportIndexError("invalid published_at") from exc
    if parsed.tzinfo is None:
        raise AIOfficeReportIndexError("published_at must be timezone-aware")
    return parsed.astimezone(timezone.utc).isoformat()


@dataclass(frozen=True, slots=True)
class OfficeReportIndexRegistryV1:
    schema_version: str
    office_id: str
    registry_ref: str

    def __post_init__(self) -> None:
        if self.schema_version != OFFICE_REPORT_INDEX_REGISTRY_SCHEMA_V1:
            raise AIOfficeReportIndexError("unsupported report index registry schema")
        object.__setattr__(self, "office_id", _safe_component(self.office_id, "office_id"))
        object.__setattr__(self, "registry_ref", _text(self.registry_ref, "registry_ref"))

    @property
    def registry_digest(self) -> str:
        return canonical_digest(asdict(self))


@dataclass(frozen=True, slots=True)
class OfficeReportIndexEntryV1:
    schema_version: str
    report_id: str
    title: str
    published_at: str
    project_id: str
    run_id: str
    workflow_state: str
    report_digest: str
    report_ref: str

    def __post_init__(self) -> None:
        if self.schema_version != OFFICE_REPORT_INDEX_ENTRY_SCHEMA_V1:
            raise AIOfficeReportIndexError("unsupported report index entry schema")
        object.__setattr__(self, "report_id", _safe_component(self.report_id, "report_id"))
        object.__setattr__(self, "title", _text(self.title, "title", limit=300))
        object.__setattr__(self, "published_at", _timestamp(self.published_at))
        for field in ("project_id", "run_id", "workflow_state", "report_ref"):
            object.__setattr__(self, field, _text(getattr(self, field), field))
        digest = _text(self.report_digest, "report_digest")
        if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
            raise AIOfficeReportIndexError("invalid report_digest")
        object.__setattr__(self, "report_digest", digest)

    @property
    def entry_digest(self) -> str:
        return canonical_digest(asdict(self))


def office_report_from_mapping(value: Mapping[str, Any]) -> OfficeReportV1:
    if not isinstance(value, Mapping):
        raise AIOfficeReportIndexError("office report mapping required")
    expected = {
        "schema_version", "status", "kpi", "external_assignment_ref",
        "external_fanin_ref", "full_plan_completion_digest",
        "observation_refs", "recovery_refs", "report_digest",
    }
    if set(value) != expected:
        raise AIOfficeReportIndexError("office report shape mismatch")
    status_raw = value.get("status")
    kpi_raw = value.get("kpi")
    if not isinstance(status_raw, Mapping) or not isinstance(kpi_raw, Mapping):
        raise AIOfficeReportIndexError("office report nested shape invalid")
    try:
        status = OfficeStatusProjectionV1(
            status_raw["schema_version"], status_raw["project_id"], status_raw["run_id"],
            status_raw["workflow_state"], status_raw["revision"],
            status_raw["pending_approval_ref"], status_raw["pending_manual_action_ref"],
        )
        kpi = OfficeKPIProjectionV1(
            kpi_raw["schema_version"], kpi_raw["observation_ref_count"],
            kpi_raw["recovery_ref_count"], kpi_raw["has_pending_approval"],
            kpi_raw["has_pending_manual_action"],
        )
        report = OfficeReportV1(
            value["schema_version"], status, kpi,
            value["external_assignment_ref"], value["external_fanin_ref"],
            value["full_plan_completion_digest"], tuple(value["observation_refs"]),
            tuple(value["recovery_refs"]),
        )
    except (KeyError, TypeError, ValueError, ReportingError) as exc:
        raise AIOfficeReportIndexError("office report contract invalid") from exc
    if report.schema_version != OFFICE_REPORT_SCHEMA_V1:
        raise AIOfficeReportIndexError("office report schema mismatch")
    if status.schema_version != OFFICE_STATUS_SCHEMA_V1 or kpi.schema_version != OFFICE_KPI_SCHEMA_V1:
        raise AIOfficeReportIndexError("office report nested schema mismatch")
    if str(value.get("report_digest") or "") != report.report_digest:
        raise AIOfficeReportIndexError("office report digest mismatch")
    return report


class AIOfficeReportIndexStore:
    def __init__(self, state_root: str | Path):
        root = Path(state_root).expanduser().resolve()
        self.root = root / "_workspace" / "ai-office-report-index"
        self.registry_path = self.root / "registry.json"
        self.entries_root = self.root / "entries"
        self.reports_root = self.root / "reports"

    def _ensure_safe_root(self) -> None:
        if self.root.is_symlink() or (self.root.exists() and not self.root.is_dir()):
            raise AIOfficeReportIndexError("unsafe report index root")
        for path in (self.entries_root, self.reports_root):
            if path.is_symlink() or (path.exists() and not path.is_dir()):
                raise AIOfficeReportIndexError("unsafe report index child root")

    @staticmethod
    def _atomic_json(path: Path, value: Mapping[str, Any]) -> None:
        if path.is_symlink():
            raise AIOfficeReportIndexError("unsafe report index output path")
        path.parent.mkdir(parents=True, exist_ok=True)
        data = (json.dumps(dict(value), sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n").encode("utf-8")
        fd, temp_name = tempfile.mkstemp(prefix=path.name + ".", dir=str(path.parent))
        try:
            os.fchmod(fd, 0o600)
            os.write(fd, data)
            os.fsync(fd)
            os.close(fd); fd = -1
            os.replace(temp_name, path)
            dir_fd = os.open(str(path.parent), os.O_RDONLY)
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)
        finally:
            if fd >= 0:
                os.close(fd)
            if os.path.exists(temp_name):
                os.unlink(temp_name)

    def publish_registry(self, registry: OfficeReportIndexRegistryV1) -> Path:
        if not isinstance(registry, OfficeReportIndexRegistryV1):
            raise AIOfficeReportIndexError("OfficeReportIndexRegistryV1 required")
        self._ensure_safe_root()
        if self.registry_path.exists() or self.registry_path.is_symlink():
            existing = self.load_registry()
            if existing == registry:
                return self.registry_path
            raise AIOfficeReportIndexError("report index registry already exists with different content")
        payload = asdict(registry)
        payload["registry_digest"] = registry.registry_digest
        self._atomic_json(self.registry_path, payload)
        return self.registry_path

    def load_registry(self) -> OfficeReportIndexRegistryV1:
        self._ensure_safe_root()
        path = self.registry_path
        if path.is_symlink() or not path.is_file():
            raise AIOfficeReportIndexError("report index registry missing or unsafe")
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise AIOfficeReportIndexError("report index registry unreadable") from exc
        expected = {"schema_version", "office_id", "registry_ref", "registry_digest"}
        if not isinstance(value, dict) or set(value) != expected:
            raise AIOfficeReportIndexError("report index registry shape mismatch")
        registry = OfficeReportIndexRegistryV1(
            value["schema_version"], value["office_id"], value["registry_ref"]
        )
        if str(value["registry_digest"]) != registry.registry_digest:
            raise AIOfficeReportIndexError("report index registry digest mismatch")
        return registry

    def _entry_path(self, report_id: str) -> Path:
        return self.entries_root / f"{_safe_component(report_id, report_id)}.json"

    def _report_path(self, report_id: str) -> Path:
        return self.reports_root / f"{_safe_component(report_id, report_id)}.json"

    def load_report(self, report_id: str) -> OfficeReportV1:
        self.load_registry()
        path = self._report_path(report_id)
        if path.is_symlink() or not path.is_file():
            raise AIOfficeReportIndexError("canonical report missing or unsafe")
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise AIOfficeReportIndexError("canonical report unreadable") from exc
        return office_report_from_mapping(value)

    def _load_entry(self, path: Path) -> OfficeReportIndexEntryV1:
        if path.is_symlink() or not path.is_file():
            raise AIOfficeReportIndexError("unsafe report index entry path")
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise AIOfficeReportIndexError("report index entry unreadable") from exc
        expected = {
            "schema_version", "report_id", "title", "published_at", "project_id",
            "run_id", "workflow_state", "report_digest", "report_ref", "entry_digest",
        }
        if not isinstance(value, dict) or set(value) != expected:
            raise AIOfficeReportIndexError("report index entry shape mismatch")
        entry = OfficeReportIndexEntryV1(
            value["schema_version"], value["report_id"], value["title"], value["published_at"],
            value["project_id"], value["run_id"], value["workflow_state"],
            value["report_digest"], value["report_ref"],
        )
        if path.stem != entry.report_id:
            raise AIOfficeReportIndexError("report index path/identity mismatch")
        if str(value["entry_digest"]) != entry.entry_digest:
            raise AIOfficeReportIndexError("report index entry digest mismatch")
        report = self.load_report(entry.report_id)
        if (
            report.report_digest != entry.report_digest
            or report.status.project_id != entry.project_id
            or report.status.run_id != entry.run_id
            or report.status.workflow_state != entry.workflow_state
        ):
            raise AIOfficeReportIndexError("report index/report binding mismatch")
        return entry

    def publish_report(
        self,
        *,
        report_id: str,
        title: str,
        published_at: str,
        report: OfficeReportV1,
        report_ref: str,
    ) -> Path:
        if not isinstance(report, OfficeReportV1):
            raise AIOfficeReportIndexError("OfficeReportV1 required")
        self.load_registry()
        rid = _safe_component(report_id, "report_id")
        entry = OfficeReportIndexEntryV1(
            OFFICE_REPORT_INDEX_ENTRY_SCHEMA_V1,
            rid, title, published_at,
            report.status.project_id, report.status.run_id, report.status.workflow_state,
            report.report_digest, report_ref,
        )
        entry_path = self._entry_path(rid)
        report_path = self._report_path(rid)
        if entry_path.exists() or entry_path.is_symlink() or report_path.exists() or report_path.is_symlink():
            if not entry_path.is_file() or not report_path.is_file():
                raise AIOfficeReportIndexError("conflicting report index path exists")
            existing = self._load_entry(entry_path)
            if existing == entry and self.load_report(rid) == report:
                return entry_path
            raise AIOfficeReportIndexError("report_id already exists with different content")
        self._atomic_json(report_path, report.to_dict())
        payload = asdict(entry)
        payload["entry_digest"] = entry.entry_digest
        try:
            self._atomic_json(entry_path, payload)
        except Exception:
            report_path.unlink(missing_ok=True)
            raise
        return entry_path

    def load_entries(self) -> tuple[OfficeReportIndexEntryV1, ...]:
        self.load_registry()
        if not self.entries_root.exists():
            return ()
        entries = [self._load_entry(path) for path in sorted(self.entries_root.glob("*.json"))]
        return tuple(sorted(entries, key=lambda entry: (entry.published_at, entry.report_id), reverse=True))
