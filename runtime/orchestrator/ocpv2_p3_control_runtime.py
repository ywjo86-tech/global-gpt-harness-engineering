"""Bounded, manually invoked P3 control runner.

This runner intentionally has no timer and accepts only Admission, validation-evidence
issue, or validation-registration requests.  The configured serving root remains the
predecessor; the process source must be a separate successor checkout.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

from . import ocpv2_successor_stage_runtime as successor
from .remote_operator_service import ControlMode


class P3ControlRuntimeError(ValueError):
    pass


def _enabled_features(environment: dict[str, str] | Any) -> tuple[str, ...]:
    features = (
        ("promotion", successor.lifecycle_v2_p3_promotion_enabled_from_environment),
        ("validation_evidence", successor.lifecycle_v2_p3_canary_validate_evidence_issue_enabled_from_environment),
        ("validation_registration", successor.lifecycle_v2_p3_canary_validate_enabled_from_environment),
    )
    return tuple(name for name, enabled in features if enabled(environment))


def _validate_p3_control_config(config) -> None:
    if Path.cwd().resolve() == config.repo_root.resolve():
        raise P3ControlRuntimeError("P3_CONTROL_SOURCE_MUST_BE_SEPARATE_FROM_SERVING_ROOT")
    if config.mode != ControlMode.ACTIVE:
        raise P3ControlRuntimeError("P3_CONTROL_MODE_MUST_BE_ACTIVE")
    if successor.successor_release_stage_enabled_from_environment(config.environment):
        raise P3ControlRuntimeError("P3_CONTROL_STAGE_FORBIDDEN")
    forbidden = (
        "OCP_HOST_INSPECTION_ENABLED",
        "OCP_WORK_ACTIVATION_ENABLED",
        "OCP_FULL_PLAN_ACTIVATION_ENABLED",
        "OCP_LIFECYCLE_V2_P3_CANARY_ACTIVATION_ENABLED",
    )
    if any(str(config.environment.get(key) or "").strip() == "1" for key in forbidden):
        raise P3ControlRuntimeError("P3_CONTROL_UNRELATED_CAPABILITY_FORBIDDEN")
    enabled = _enabled_features(config.environment)
    if len(enabled) != 1:
        raise P3ControlRuntimeError("P3_CONTROL_EXACTLY_ONE_REQUEST_KIND_REQUIRED")


def run_once(config) -> dict[str, Any]:
    _validate_p3_control_config(config)
    return successor.run_once(config)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run one bounded P3 OCP control poll")
    parser.add_argument("--env-file", required=True)
    args = parser.parse_args(argv)
    try:
        config = successor.base.load_runtime_config(args.env_file)
        result = run_once(config)
    except (successor.base.RuntimeServiceError, successor.SuccessorStageRuntimeError, P3ControlRuntimeError, ValueError, OSError) as exc:
        print(json.dumps({"status": "BLOCKED", "error": str(exc)}, sort_keys=True), file=os.sys.stderr)
        return 2
    print(json.dumps({"status": "OK", **result}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
