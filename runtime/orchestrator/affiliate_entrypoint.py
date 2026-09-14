"""Single Affiliate-facing entrypoint for the common orchestration CLI."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Callable, Sequence


class AffiliateEntrypointError(ValueError):
    pass


def resolve_alias(alias: str, mapping_root: str | Path) -> dict[str, object]:
    if not isinstance(alias, str) or not alias or "/" in alias or "\\" in alias or ".." in alias:
        raise AffiliateEntrypointError("unsafe Affiliate alias")
    target = Path(mapping_root).resolve() / "aliases" / f"{alias}.json"
    if not target.is_file() or target.is_symlink():
        raise AffiliateEntrypointError("Affiliate alias is not registered")
    payload = json.loads(target.read_text(encoding="utf-8"))
    if payload.get("alias") != alias or not isinstance(payload.get("project_id"), str) or payload.get("entry_command") != [alias, "codex"]:
        raise AffiliateEntrypointError("Affiliate alias registry binding is invalid")
    return payload


def run_affiliate_entrypoint(argv: Sequence[str], *, mapping_root: str | Path,
                             dispatcher: Callable[[list[str]], int]) -> int:
    """Validate ``<alias> codex`` and delegate without changing approval mode."""
    if len(argv) < 2 or argv[1] != "codex":
        raise AffiliateEntrypointError("Affiliate entrypoint requires '<alias> codex'")
    alias_record = resolve_alias(argv[0], mapping_root)
    forwarded = list(argv[2:])
    if not forwarded:
        raise AffiliateEntrypointError("Affiliate codex requires a controller command")
    return dispatcher(forwarded)
