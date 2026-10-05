"""Canonical typed business schedule state for AI Office read models."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Mapping

from .contracts import canonical_digest

BUSINESS_SCHEDULE_ITEM_SCHEMA_V1 = "ai-office.business-schedule-item.v1"
_ALLOWED_STATUSES = {"SCHEDULED", "IN_PROGRESS", "COMPLETED", "CANCELLED", "BLOCKED"}


class AIOfficeBusinessScheduleError(ValueError):
    pass


def _safe_component(value: object, label: str) -> str:
    item = str(value).strip()
    if not item or len(item) > 160 or "/" in item or "\\" in item or ".." in item:
        raise AIOfficeBusinessScheduleError(f"unsafe {label}")
    return item


def _text(value: object, label: str, *, limit: int = 512) -> str:
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > limit:
        raise AIOfficeBusinessScheduleError(f"invalid {label}")
    return value.strip()


def _timestamp(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise AIOfficeBusinessScheduleError("invalid start_at")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise AIOfficeBusinessScheduleError("invalid start_at") from exc
    if parsed.tzinfo is None:
        raise AIOfficeBusinessScheduleError("start_at must be timezone-aware")
    return parsed.astimezone(timezone.utc).isoformat()


@dataclass(frozen=True, slots=True)
class BusinessScheduleItemV1:
    schema_version: str
    item_id: str
    title: str
    start_at: str
    status: str
    source_ref: str
    revision: int = 0

    def __post_init__(self) -> None:
        if self.schema_version != BUSINESS_SCHEDULE_ITEM_SCHEMA_V1:
            raise AIOfficeBusinessScheduleError("unsupported business schedule schema")
        object.__setattr__(self, "item_id", _safe_component(self.item_id, "item_id"))
        object.__setattr__(self, "title", _text(self.title, "title", limit=300))
        object.__setattr__(self, "start_at", _timestamp(self.start_at))
        status = _text(self.status, "status").upper()
        if status not in _ALLOWED_STATUSES:
            raise AIOfficeBusinessScheduleError("unsupported schedule status")
        object.__setattr__(self, "status", status)
        object.__setattr__(self, "source_ref", _text(self.source_ref, "source_ref"))
        if isinstance(self.revision, bool) or not isinstance(self.revision, int) or self.revision < 0:
            raise AIOfficeBusinessScheduleError("invalid revision")

    @property
    def item_digest(self) -> str:
        return canonical_digest(asdict(self))


class AIOfficeBusinessScheduleStore:
    def __init__(self, state_root: str | Path):
        root = Path(state_root).expanduser().resolve()
        self.root = root / "_workspace" / "ai-office-business-schedule"
        self.items_root = self.root / "items"

    def _ensure_safe_root(self) -> None:
        if self.root.is_symlink() or (self.root.exists() and not self.root.is_dir()):
            raise AIOfficeBusinessScheduleError("unsafe schedule root")
        if self.items_root.is_symlink() or (self.items_root.exists() and not self.items_root.is_dir()):
            raise AIOfficeBusinessScheduleError("unsafe schedule items root")

    @staticmethod
    def _atomic_json(path: Path, value: Mapping[str, Any]) -> None:
        if path.is_symlink():
            raise AIOfficeBusinessScheduleError("unsafe schedule item path")
        path.parent.mkdir(parents=True, exist_ok=True)
        data = (
            json.dumps(dict(value), sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n"
        ).encode("utf-8")
        fd, temp_name = tempfile.mkstemp(prefix=path.name + ".", dir=str(path.parent))
        try:
            os.fchmod(fd, 0o600)
            os.write(fd, data)
            os.fsync(fd)
            os.close(fd)
            fd = -1
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

    def _path(self, item_id: str) -> Path:
        return self.items_root / f"{_safe_component(item_id, item_id)}.json"

    def _load_item(self, path: Path) -> BusinessScheduleItemV1:
        if path.is_symlink() or not path.is_file():
            raise AIOfficeBusinessScheduleError("unsafe schedule item path")
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise AIOfficeBusinessScheduleError("schedule item unreadable") from exc
        expected = {
            "schema_version", "item_id", "title", "start_at", "status",
            "source_ref", "revision", "item_digest",
        }
        if not isinstance(value, dict) or set(value) != expected:
            raise AIOfficeBusinessScheduleError("schedule item shape mismatch")
        try:
            item = BusinessScheduleItemV1(
                value["schema_version"], value["item_id"], value["title"],
                value["start_at"], value["status"], value["source_ref"], value["revision"],
            )
        except (TypeError, ValueError, AIOfficeBusinessScheduleError) as exc:
            raise AIOfficeBusinessScheduleError("schedule item contract invalid") from exc
        if path.stem != item.item_id:
            raise AIOfficeBusinessScheduleError("schedule item path/identity mismatch")
        if str(value["item_digest"]) != item.item_digest:
            raise AIOfficeBusinessScheduleError("schedule item digest mismatch")
        return item

    def publish_item(self, item: BusinessScheduleItemV1) -> Path:
        if not isinstance(item, BusinessScheduleItemV1):
            raise AIOfficeBusinessScheduleError("BusinessScheduleItemV1 required")
        self._ensure_safe_root()
        path = self._path(item.item_id)
        if path.exists() or path.is_symlink():
            existing = self._load_item(path)
            if existing == item:
                return path
            if item.revision != existing.revision + 1:
                raise AIOfficeBusinessScheduleError("schedule revision must advance by one")
        elif item.revision != 0:
            raise AIOfficeBusinessScheduleError("initial schedule revision must be zero")
        payload = asdict(item)
        payload["item_digest"] = item.item_digest
        self._atomic_json(path, payload)
        return path

    def load_items(self) -> tuple[BusinessScheduleItemV1, ...]:
        self._ensure_safe_root()
        if not self.root.exists():
            return ()
        if not self.items_root.exists():
            return ()
        items = [self._load_item(path) for path in sorted(self.items_root.glob("*.json"))]
        return tuple(sorted(items, key=lambda item: (item.start_at, item.item_id)))
