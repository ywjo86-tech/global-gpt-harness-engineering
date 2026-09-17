"""Crash-safe local persistence primitives for orchestration state."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any, Mapping


class DurableIOError(ValueError):
    pass


def canonical_json_bytes(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _fsync_directory(path: Path) -> None:
    flags = getattr(os, "O_DIRECTORY", 0) | os.O_RDONLY
    fd = os.open(str(path), flags)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def atomic_write_bytes(path: str | Path, data: bytes, *, reject_symlink: bool = True) -> Path:
    target = Path(path)
    if reject_symlink and target.exists() and target.is_symlink():
        raise DurableIOError(f"refusing symlink target: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=target.name + ".", dir=str(target.parent))
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
        _fsync_directory(target.parent)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return target


def atomic_write_text(path: str | Path, text: str, *, encoding: str = "utf-8") -> Path:
    return atomic_write_bytes(path, text.encode(encoding))


def atomic_write_json(path: str | Path, payload: Mapping[str, Any] | list[Any]) -> Path:
    return atomic_write_bytes(path, canonical_json_bytes(payload))


def durable_json_save(path: str | Path, payload: Mapping[str, Any]) -> Path:
    """Save primary JSON while retaining a verified previous-good generation."""
    target = Path(path)
    previous = target.with_suffix(target.suffix + ".prev")
    if target.exists():
        if target.is_symlink() or not target.is_file():
            raise DurableIOError(f"unsafe state target: {target}")
        raw = target.read_bytes()
        try:
            current = json.loads(raw.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError):
            current = None
        if isinstance(current, dict):
            atomic_write_bytes(previous, raw)
        else:
            # Preserve corrupt bytes for forensics, but do not let them prevent
            # recovery from an already verified previous-good generation.
            corrupt = target.with_name(target.name + ".corrupt")
            atomic_write_bytes(corrupt, raw)
    return atomic_write_json(target, payload)


def durable_json_load(path: str | Path) -> tuple[dict[str, Any], bool]:
    """Load primary state, falling back to previous-good generation if required."""
    target = Path(path)
    candidates = (target, target.with_suffix(target.suffix + ".prev"))
    last_error: Exception | None = None
    for index, candidate in enumerate(candidates):
        if not candidate.exists():
            continue
        try:
            if candidate.is_symlink() or not candidate.is_file():
                raise DurableIOError(f"unsafe state file: {candidate}")
            value = json.loads(candidate.read_text(encoding="utf-8"))
            if not isinstance(value, dict):
                raise DurableIOError(f"state is not an object: {candidate}")
            return value, index == 1
        except (OSError, UnicodeError, json.JSONDecodeError, DurableIOError) as exc:
            last_error = exc
    if last_error is not None:
        raise DurableIOError(f"no valid state generation: {target}") from last_error
    raise FileNotFoundError(target)


def _memory_available_bytes() -> int:
    try:
        for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
            if line.startswith("MemAvailable:"):
                return int(line.split()[1]) * 1024
    except (OSError, ValueError, IndexError):
        pass
    return -1


def _io_pressure_avg10_milli() -> int:
    """Return Linux PSI IO full avg10 as thousandths of a percent, or -1."""
    try:
        for line in Path("/proc/pressure/io").read_text(encoding="utf-8").splitlines():
            if not line.startswith("full "):
                continue
            fields = dict(item.split("=", 1) for item in line.split()[1:] if "=" in item)
            return int(float(fields["avg10"]) * 1000)
    except (OSError, ValueError, KeyError):
        pass
    return -1


def resource_snapshot(path: str | Path) -> dict[str, int]:
    root = Path(path)
    usage = shutil.disk_usage(root)
    stat = os.statvfs(root)
    cpu_count = max(1, os.cpu_count() or 1)
    try:
        load1 = os.getloadavg()[0]
        load_per_cpu_milli = int((load1 / cpu_count) * 1000)
    except OSError:
        load_per_cpu_milli = -1
    return {
        "disk_free_bytes": int(usage.free),
        "disk_total_bytes": int(usage.total),
        "inode_free": int(stat.f_favail),
        "inode_total": int(stat.f_files),
        "memory_available_bytes": _memory_available_bytes(),
        "cpu_load_per_cpu_milli": load_per_cpu_milli,
        "io_pressure_full_avg10_milli": _io_pressure_avg10_milli(),
    }
