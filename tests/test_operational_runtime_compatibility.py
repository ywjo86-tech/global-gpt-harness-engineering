from __future__ import annotations

from pathlib import Path

import pytest

from runtime.orchestrator.operational_runtime_compatibility import (
    OperationalRuntimeCompatibilityError,
    build_runtime_compatibility_manifest,
    evaluate_runtime_compatibility,
    validate_runtime_compatibility_manifest,
)


CURRENT = "a" * 40
PINNED = "b" * 40


def _root(tmp_path: Path) -> Path:
    releases = tmp_path / "releases"
    (releases / CURRENT).mkdir(parents=True)
    (releases / PINNED).mkdir()
    return releases


def _manifest(tmp_path: Path):
    releases = _root(tmp_path)
    return build_runtime_compatibility_manifest(
        current_runtime_source_identity=CURRENT,
        releases_root=releases,
        components=[
            {
                "component_id": "reconcile",
                "unit": "global-gpt-harness-full-plan-reconcile.service",
                "binding_mode": "CURRENT_RUNTIME",
                "expected_source_head": CURRENT,
                "compatibility_evidence_refs": [],
            },
            {
                "component_id": "timer-recovery",
                "unit": "global-gpt-harness-operations-timer-recovery.service",
                "binding_mode": "PINNED_COMPATIBLE",
                "expected_source_head": PINNED,
                "compatibility_evidence_refs": ["qualification:timer-recovery-v1"],
            },
        ],
    )


def test_manifest_and_observed_bindings_pass(tmp_path):
    manifest = _manifest(tmp_path)
    releases = Path(manifest["releases_root"])
    result = evaluate_runtime_compatibility(
        manifest,
        observed_working_directories={
            "global-gpt-harness-full-plan-reconcile.service": releases / CURRENT,
            "global-gpt-harness-operations-timer-recovery.service": releases / PINNED,
        },
    )
    assert result["status"] == "PASS"
    assert result["failures"] == []
    assert len(result["result_sha256"]) == 64


def test_current_binding_can_resolve_runtime_current_symlink(tmp_path):
    manifest = _manifest(tmp_path)
    releases = Path(manifest["releases_root"])
    runtime_current = tmp_path / "runtime-current"
    runtime_current.symlink_to(releases / CURRENT, target_is_directory=True)
    result = evaluate_runtime_compatibility(
        manifest,
        observed_working_directories={
            "global-gpt-harness-full-plan-reconcile.service": runtime_current,
            "global-gpt-harness-operations-timer-recovery.service": releases / PINNED,
        },
    )
    assert result["status"] == "PASS"


def test_source_head_mismatch_blocks(tmp_path):
    manifest = _manifest(tmp_path)
    releases = Path(manifest["releases_root"])
    result = evaluate_runtime_compatibility(
        manifest,
        observed_working_directories={
            "global-gpt-harness-full-plan-reconcile.service": releases / PINNED,
            "global-gpt-harness-operations-timer-recovery.service": releases / PINNED,
        },
    )
    assert result["status"] == "BLOCKED"
    assert "reconcile:SOURCE_HEAD_MISMATCH" in result["failures"]


def test_non_release_working_directory_blocks(tmp_path):
    manifest = _manifest(tmp_path)
    outside = tmp_path / "worktree"
    outside.mkdir()
    releases = Path(manifest["releases_root"])
    result = evaluate_runtime_compatibility(
        manifest,
        observed_working_directories={
            "global-gpt-harness-full-plan-reconcile.service": outside,
            "global-gpt-harness-operations-timer-recovery.service": releases / PINNED,
        },
    )
    assert result["status"] == "BLOCKED"
    assert "reconcile:RELEASE_PATH_INVALID" in result["failures"]


def test_pinned_component_requires_compatibility_evidence(tmp_path):
    releases = _root(tmp_path)
    with pytest.raises(
        OperationalRuntimeCompatibilityError,
        match="pinned component requires compatibility evidence",
    ):
        build_runtime_compatibility_manifest(
            current_runtime_source_identity=CURRENT,
            releases_root=releases,
            components=[{
                "component_id": "ocp",
                "unit": "ocpv2.service",
                "binding_mode": "PINNED_COMPATIBLE",
                "expected_source_head": PINNED,
                "compatibility_evidence_refs": [],
            }],
        )


def test_manifest_digest_tamper_rejected(tmp_path):
    manifest = _manifest(tmp_path)
    manifest["components"][0]["expected_source_head"] = PINNED
    with pytest.raises(
        OperationalRuntimeCompatibilityError,
        match="component binding invalid|manifest digest mismatch",
    ):
        validate_runtime_compatibility_manifest(manifest)
