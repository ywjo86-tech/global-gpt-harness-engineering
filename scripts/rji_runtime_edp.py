#!/usr/bin/env python3
"""Deterministic runtime EDP qualification runner for Ruflo/Jev advisory seams.

Focused mode intentionally excludes repository-wide regression discovery because
CI already owns that separately. Full mode includes it and emits the canonical
RJI_RUNTIME_EDP PASS line only when every group returns zero.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
import subprocess
import sys
from typing import Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True, slots=True)
class QualificationGroup:
    name: str
    argv: tuple[str, ...]


_FOCUSED_GROUPS: tuple[QualificationGroup, ...] = (
    QualificationGroup(
        "contract",
        (sys.executable, "-m", "unittest", "-v", "tests.test_external_advisory_contract"),
    ),
    QualificationGroup(
        "ruflo_proxy",
        (sys.executable, "-m", "unittest", "-v", "tests.test_ruflo_filtering_proxy"),
    ),
    QualificationGroup(
        "jev_adapter",
        (sys.executable, "-m", "unittest", "-v", "tests.test_jev_provider_bound_adapter"),
    ),
    QualificationGroup(
        "shadow",
        (sys.executable, "-m", "unittest", "-v", "tests.test_external_advisory_shadow"),
    ),
    QualificationGroup(
        "runtime_policy",
        (sys.executable, "-m", "unittest", "-v", "tests.test_external_advisory_runtime"),
    ),
    QualificationGroup(
        "activation",
        (sys.executable, "-m", "unittest", "-v", "tests.test_external_advisory_activation"),
    ),
    QualificationGroup(
        "authority_negative_space",
        (sys.executable, "-m", "unittest", "-v", "tests.test_ruflo_jev_authority_negative_space"),
    ),
    QualificationGroup(
        "provider_registry",
        (sys.executable, "-m", "unittest", "-v", "tests.test_provider_execution_registry"),
    ),
    QualificationGroup(
        "production_tool_transport",
        (sys.executable, "-m", "unittest", "-v", "tests.test_production_tool_transport"),
    ),
    QualificationGroup(
        "ai_office_authority_negative_space",
        (sys.executable, "-m", "unittest", "-v", "tests.test_ai_office_authority_negative_space"),
    ),
    QualificationGroup(
        "compileall",
        (
            sys.executable,
            "-m",
            "compileall",
            "-q",
            "runtime",
            "tests",
            "deploy/operator-control-plane-v2",
        ),
    ),
    QualificationGroup("git_diff_check", ("git", "diff", "--check")),
)

_FULL_ONLY_GROUPS: tuple[QualificationGroup, ...] = (
    QualificationGroup(
        "full_repository_regression",
        (sys.executable, "scripts/ocpv2_full_regression.py"),
    ),
)


def focused_groups() -> tuple[QualificationGroup, ...]:
    return _FOCUSED_GROUPS


def full_groups() -> tuple[QualificationGroup, ...]:
    # Full repository regression runs before final hygiene checks so any test
    # fixture side effect is followed by compile/diff verification.
    focused = list(_FOCUSED_GROUPS)
    hygiene = focused[-2:]
    core = focused[:-2]
    return tuple(core) + _FULL_ONLY_GROUPS + tuple(hygiene)


def focused_group_names() -> tuple[str, ...]:
    return tuple(group.name for group in focused_groups())


def full_group_names() -> tuple[str, ...]:
    return tuple(group.name for group in full_groups())


def run_group(group: QualificationGroup, *, repo_root: Path = REPO_ROOT) -> int:
    print(f"RJI_GROUP_START name={group.name}", flush=True)
    completed = subprocess.run(group.argv, cwd=repo_root, check=False)
    status = "PASS" if completed.returncode == 0 else "FAIL"
    print(
        f"RJI_GROUP_RESULT name={group.name} status={status} rc={completed.returncode}",
        flush=True,
    )
    return completed.returncode


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--focused",
        action="store_true",
        help="run focused RJI qualification without repository-wide regression discovery",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    groups = focused_groups() if args.focused else full_groups()
    failures: list[str] = []
    for group in groups:
        if run_group(group) != 0:
            failures.append(group.name)

    if failures:
        print(
            "RJI_RUNTIME_EDP "
            f"status=FAIL blocker={len(failures)} unresolved_major=0 "
            f"failed_groups={','.join(failures)}",
            flush=True,
        )
        return 1

    if args.focused:
        print(
            "RJI_RUNTIME_EDP_FOCUSED status=PASS blocker=0 unresolved_major=0",
            flush=True,
        )
    else:
        print(
            "RJI_RUNTIME_EDP status=PASS blocker=0 unresolved_major=0 "
            "current_only_regressions=0",
            flush=True,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
