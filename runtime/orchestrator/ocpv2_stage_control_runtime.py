"""Bounded, manually invoked successor-stage control runner.

This runner has no timer. It accepts only a typed successor-release-stage request and
keeps the configured serving root distinct from the source checkout that executes it.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

from . import ocpv2_successor_stage_runtime as successor
from .remote_operator_service import ControlMode


class StageControlRuntimeError(ValueError):
    pass


def _validate_stage_control_config(config) -> None:
    if Path.cwd().resolve() == config.repo_root.resolve():
        raise StageControlRuntimeError("STAGE_CONTROL_SOURCE_MUST_BE_SEPARATE_FROM_SERVING_ROOT")
    if config.mode != ControlMode.ACTIVE:
        raise StageControlRuntimeError("STAGE_CONTROL_MODE_MUST_BE_ACTIVE")
    if not successor.successor_release_stage_enabled_from_environment(config.environment):
        raise StageControlRuntimeError("STAGE_CONTROL_GATE_REQUIRED")
    forbidden = (
        "OCP_HOST_INSPECTION_ENABLED",
        "OCP_WORK_ACTIVATION_ENABLED",
        "OCP_FULL_PLAN_ACTIVATION_ENABLED",
        "OCP_LIFECYCLE_V2_P3_PROMOTION_ENABLED",
        "OCP_LIFECYCLE_V2_P3_CANARY_ACTIVATION_ENABLED",
        "OCP_LIFECYCLE_V2_P3_CANARY_VALIDATE_ENABLED",
        "OCP_LIFECYCLE_V2_P3_CANARY_VALIDATE_EVIDENCE_ISSUE_ENABLED",
    )
    if any(str(config.environment.get(key) or "").strip() == "1" for key in forbidden):
        raise StageControlRuntimeError("STAGE_CONTROL_UNRELATED_CAPABILITY_FORBIDDEN")


def run_once(config) -> dict[str, Any]:
    _validate_stage_control_config(config)
    return successor.run_once(config)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run one bounded OCP successor-stage poll")
    parser.add_argument("--env-file", required=True)
    args = parser.parse_args(argv)
    try:
        config = successor.base.load_runtime_config(args.env_file)
        result = run_once(config)
    except (successor.base.RuntimeServiceError, successor.SuccessorStageRuntimeError, StageControlRuntimeError, ValueError, OSError) as exc:
        print(json.dumps({"status": "BLOCKED", "error": str(exc)}, sort_keys=True), file=os.sys.stderr)
        return 2
    print(json.dumps({"status": "OK", **result}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
