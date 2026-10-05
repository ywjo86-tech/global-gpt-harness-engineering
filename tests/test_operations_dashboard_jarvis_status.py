from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
import tempfile
from pathlib import Path

import pytest

from runtime.orchestrator.operations_dashboard_jarvis_status import (
    COMPACT_STATUS_SCHEMA_V1,
    COMPACT_STATUS_SOURCE_V1,
    OperationsDashboardJarvisStatusError,
    read_operations_dashboard_jarvis_status,
)
from runtime.orchestrator.operations_dashboard_source import build_live_operations_dashboard_projection

HEAD = "b" * 40


def _digest(value):
    unsigned={k:v for k,v in value.items() if k!="status_digest"}
    raw=json.dumps(unsigned,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode()
    return hashlib.sha256(raw).hexdigest()


def _write(root, *, generated_at, webapp="AVAILABLE", memory="AVAILABLE", llmwiki="AVAILABLE"):
    p=Path(root)/"operations-v2"/"jarvis-compact-status.json"
    p.parent.mkdir(parents=True,exist_ok=True)
    value={
        "schema_version":COMPACT_STATUS_SCHEMA_V1,
        "generated_at":generated_at,
        "publisher_source_head":HEAD,
        "webapp":webapp,
        "memory":memory,
        "llmwiki":llmwiki,
        "source_state":COMPACT_STATUS_SOURCE_V1,
    }
    value["status_digest"]=_digest(value)
    p.write_text(json.dumps(value))
    return p


def _read(root, **kwargs):
    return read_operations_dashboard_jarvis_status(
        root, expected_publisher_head=HEAD, **kwargs
    )


def test_missing_status_preserves_unbound():
    with tempfile.TemporaryDirectory() as td:
        assert _read(td) is None


def test_fresh_status_projects_only_compact_fields():
    now=datetime(2026,10,5,7,0,tzinfo=timezone.utc)
    with tempfile.TemporaryDirectory() as td:
        _write(td,generated_at=(now-timedelta(seconds=10)).isoformat())
        value=_read(td,now=now)
        assert value=={
            "webapp":"AVAILABLE",
            "memory":"AVAILABLE",
            "llmwiki":"AVAILABLE",
            "source_state":COMPACT_STATUS_SOURCE_V1,
        }


def test_present_status_requires_expected_publisher_head(monkeypatch):
    now=datetime(2026,10,5,7,0,tzinfo=timezone.utc)
    monkeypatch.delenv("AI_OFFICE_JARVIS_COMPACT_STATUS_EXPECTED_PUBLISHER_HEAD", raising=False)
    with tempfile.TemporaryDirectory() as td:
        _write(td,generated_at=now.isoformat())
        with pytest.raises(OperationsDashboardJarvisStatusError,match="expected publisher head required"):
            read_operations_dashboard_jarvis_status(td,now=now)


def test_publisher_head_mismatch_fails_closed():
    now=datetime(2026,10,5,7,0,tzinfo=timezone.utc)
    with tempfile.TemporaryDirectory() as td:
        _write(td,generated_at=now.isoformat())
        with pytest.raises(OperationsDashboardJarvisStatusError,match="publisher head mismatch"):
            read_operations_dashboard_jarvis_status(
                td,now=now,expected_publisher_head="c"*40
            )


def test_stale_status_is_unknown_without_false_green():
    now=datetime(2026,10,5,7,0,tzinfo=timezone.utc)
    with tempfile.TemporaryDirectory() as td:
        _write(td,generated_at=(now-timedelta(seconds=181)).isoformat())
        value=_read(td,now=now,max_age_seconds=180)
        assert value=={
            "webapp":"UNKNOWN","memory":"UNKNOWN","llmwiki":"UNKNOWN","source_state":"STALE"
        }


def test_digest_tamper_fails_closed():
    now=datetime(2026,10,5,7,0,tzinfo=timezone.utc)
    with tempfile.TemporaryDirectory() as td:
        p=_write(td,generated_at=now.isoformat())
        value=json.loads(p.read_text())
        value["memory"]="UNAVAILABLE"
        p.write_text(json.dumps(value))
        with pytest.raises(OperationsDashboardJarvisStatusError,match="digest mismatch"):
            _read(td,now=now)


def test_future_timestamp_fails_closed():
    now=datetime(2026,10,5,7,0,tzinfo=timezone.utc)
    with tempfile.TemporaryDirectory() as td:
        _write(td,generated_at=(now+timedelta(seconds=31)).isoformat())
        with pytest.raises(OperationsDashboardJarvisStatusError,match="future"):
            _read(td,now=now)


def test_symlink_status_rejected():
    with tempfile.TemporaryDirectory() as td:
        root=Path(td)
        operations=root/"operations-v2"; operations.mkdir()
        target=root/"target.json"; target.write_text("{}")
        (operations/"jarvis-compact-status.json").symlink_to(target)
        with pytest.raises(OperationsDashboardJarvisStatusError,match="unsafe"):
            _read(td)


def test_live_projection_consumes_compact_status(monkeypatch):
    now=datetime(2026,10,5,7,0,tzinfo=timezone.utc)
    monkeypatch.setenv("AI_OFFICE_JARVIS_COMPACT_STATUS_EXPECTED_PUBLISHER_HEAD", HEAD)
    with tempfile.TemporaryDirectory() as td:
        _write(td,generated_at=now.isoformat(),memory="DEGRADED")
        projection=build_live_operations_dashboard_projection(td,now=now)
        assert projection["jarvis_status"]=={
            "webapp":"AVAILABLE",
            "memory":"DEGRADED",
            "llmwiki":"AVAILABLE",
            "source_state":COMPACT_STATUS_SOURCE_V1,
        }
