from __future__ import annotations

import argparse
import json
from pathlib import Path

from .contract_loader import ContractLoadError
from .contract_adapter import ContractMappingError
from .engine import OrchestrationEngine
from .lv_execution_package import LVExecutionPackageError, create_lv_execution_package
from .lv_preview import LVPreviewValidationError, preview_lv_read_only
from .lv_remediation import LVRemediationError
from .lv_review import LVReviewError, preflight_run, review_run
from .read_only_inspector import ReadOnlyValidationError, inspect_read_only


def _print(obj: object) -> None:
    if isinstance(obj, (dict, list)):
        print(json.dumps(obj, indent=2, ensure_ascii=False))
    else:
        print(obj)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Global GPT Harness orchestration runtime")
    subparsers = parser.add_subparsers(dest="command", required=True)

    for name in ["inspect", "plan", "run", "collect", "fanin", "approve", "gate", "status", "lv-plan", "lv-package", "lv-preflight", "lv-review", "lv-remediation-package", "lv-remediation-preflight", "lv-remediation-review"]:
        sub = subparsers.add_parser(name)
        if name in {"lv-plan", "lv-package"}:
            sub.add_argument("--project-root", required=True)
            sub.add_argument("--gate-id", required=True)
            sub.add_argument("--lv-id", required=True)
            if name == "lv-plan":
                sub.add_argument("--read-only", action="store_true")
            else:
                sub.add_argument("--run-id", required=True)
        elif name in {"lv-preflight", "lv-review"}:
            sub.add_argument("--run-id", required=True)
            if name == "lv-review":
                sub.add_argument(
                    "--attempt",
                    required=True,
                    help="canonical positive review attempt; writes only to attempt-<NN>",
                )
        elif name == "lv-remediation-package":
            sub.add_argument("--parent-run-id", required=True)
            sub.add_argument("--run-id", required=True)
            sub.add_argument("--reason-code", required=True)
            sub.add_argument("--reason", required=True)
        elif name in {"lv-remediation-preflight", "lv-remediation-review"}:
            sub.add_argument("--run-id", required=True)
        else:
            sub.add_argument("--project", required=True)
        if name in {"plan", "run", "gate"}:
            sub.add_argument("--mode", default="mock")
        if name in {"plan", "collect", "fanin", "gate", "status", "run"}:
            sub.add_argument("--run-id")
        if name == "approve":
            sub.add_argument("--approval", required=True)
        if name == "inspect":
            sub.add_argument("--read-only", action="store_true", help="validate contracts and static state without creating or changing files")

    args = parser.parse_args(argv)
    try:
        if args.command == "lv-plan":
            if not args.read_only:
                raise LVPreviewValidationError("H4-1 only supports --read-only LV previews")
            _print(preview_lv_read_only(Path(args.project_root), args.gate_id, args.lv_id))
            return 0
        if args.command == "lv-package":
            package = create_lv_execution_package(Path(args.project_root), args.gate_id, args.lv_id, args.run_id)
            _print(package)
            return 0
        if args.command == "lv-preflight":
            _print(preflight_run(args.run_id))
            return 0
        if args.command == "lv-review":
            outcome = review_run(args.run_id, attempt=args.attempt)
            _print(outcome)
            if outcome.get("status") == "PASS":
                return 0
            if outcome.get("status") == "FAIL":
                return 9
            return 10
        if args.command == "lv-remediation-package":
            from .lv_remediation import create_remediation_package
            _print(create_remediation_package(args.parent_run_id, args.run_id, args.reason_code, args.reason))
            return 0
        if args.command == "lv-remediation-preflight":
            from .lv_remediation import create_remediation_preflight
            outcome = create_remediation_preflight(args.run_id)
            _print(outcome)
            return 0 if outcome.get("status") == "READY" else 10
        if args.command == "lv-remediation-review":
            from .lv_remediation import review_remediation
            outcome = review_remediation(args.run_id)
            _print(outcome)
            if outcome.get("status") == "PASS":
                return 0
            if outcome.get("status") == "FAIL":
                return 9
            return 10
        if args.command == "inspect" and args.read_only:
            _print(inspect_read_only(Path(args.project)))
            return 0
        engine = OrchestrationEngine(Path(args.project))
        if args.command == "inspect":
            _print(engine.inspect())
            return 0
        if args.command == "plan":
            _print(engine.plan(mode=args.mode, run_id=args.run_id))
            return 0
        if args.command == "run":
            _print(engine.run(mode=args.mode, run_id=args.run_id))
            return 0
        if args.command == "collect":
            _print(engine.collect(args.run_id))
            return 0
        if args.command == "fanin":
            _print(engine.fanin(args.run_id))
            return 0
        if args.command == "approve":
            _print(engine.approve(args.approval))
            return 0
        if args.command == "gate":
            _print(engine.gate(mode=args.mode, run_id=args.run_id))
            return 0
        if args.command == "status":
            _print(engine.status(args.run_id))
            return 0
    except ContractLoadError as exc:
        _print({"error": str(exc), "missing_files": exc.missing_files})
        return 2
    except PermissionError as exc:
        _print({"error": str(exc)})
        return 3
    except ContractMappingError as exc:
        _print({"error": str(exc), "error_type": "contract_mapping_error"})
        return 4
    except ReadOnlyValidationError as exc:
        _print({"error": str(exc), "error_type": "read_only_validation_error", "validation": exc.report})
        return 5
    except LVPreviewValidationError as exc:
        _print({"error": str(exc), "error_type": "lv_preview_validation_error"})
        return 6
    except LVExecutionPackageError as exc:
        _print({"error": str(exc), "error_type": "lv_execution_package_error"})
        return 7
    except LVReviewError as exc:
        _print({"error": str(exc), "error_type": "lv_review_error"})
        return 8
    except LVRemediationError as exc:
        _print({"error": str(exc), "error_type": "lv_remediation_error"})
        return 11

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
