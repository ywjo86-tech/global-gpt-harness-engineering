from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any


class MappingMigrationError(ValueError):
    pass


_SHA256 = re.compile(r"[0-9a-f]{64}\Z")


def migrate_plan_sha_mapping(
    *, mapping_root: str | Path, project_root: str | Path, old_plan_sha256: str,
    new_plan_sha256: str, dry_run: bool = False,
) -> dict[str, Any]:
    registry = Path(mapping_root)
    project = Path(project_root).resolve()
    if not registry.is_absolute() or not registry.is_dir() or registry.is_symlink() or registry.resolve() != registry:
        raise MappingMigrationError("mapping root is unsafe")
    if not _SHA256.fullmatch(old_plan_sha256) or not _SHA256.fullmatch(new_plan_sha256) or old_plan_sha256 == new_plan_sha256:
        raise MappingMigrationError("plan SHA migration values are invalid")
    mapping_path = registry / f"{project.name}.json"
    if not mapping_path.is_file() or mapping_path.is_symlink() or mapping_path.parent.resolve() != registry:
        raise MappingMigrationError("mapping entry is missing or unsafe")
    try:
        payload = json.loads(mapping_path.read_text(encoding="utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise MappingMigrationError("mapping entry is malformed") from exc
    if not isinstance(payload, dict) or payload.get("project_id") != project.name:
        raise MappingMigrationError("mapping project_id does not match target project")
    canonical = payload.get("canonical_implementation_source")
    if not isinstance(canonical, dict) or canonical.get("sha256") != old_plan_sha256:
        raise MappingMigrationError("historical plan SHA is not the current canonical mapping")
    history = payload.get("plan_sha_migrations", [])
    if not isinstance(history, list):
        raise MappingMigrationError("plan_sha_migrations must be a list")
    if any(not isinstance(item, dict) or set(item) != {"from", "to"} for item in history):
        raise MappingMigrationError("plan_sha_migrations contains an invalid entry")
    updated = json.loads(json.dumps(payload))
    updated["canonical_implementation_source"]["sha256"] = new_plan_sha256
    if isinstance(updated.get("approved_source_reference"), dict) and updated["approved_source_reference"].get("sha256") == old_plan_sha256:
        updated["approved_source_reference"]["sha256"] = new_plan_sha256
    updated["plan_sha_migrations"] = [*history, {"from": old_plan_sha256, "to": new_plan_sha256}]
    result = {"status": "DRY_RUN" if dry_run else "MIGRATED", "mutation_performed": not dry_run, "mapping": updated}
    if dry_run:
        return result
    data = json.dumps(updated, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8") + b"\n"
    descriptor, temporary = tempfile.mkstemp(prefix=f".{mapping_path.name}.", dir=registry)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data); stream.flush(); os.fsync(stream.fileno())
        os.replace(temporary, mapping_path)
    except Exception:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise
    return result
