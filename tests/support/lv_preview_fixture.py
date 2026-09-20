from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

from runtime.orchestrator.approval_hash import calculate_record_hash
from runtime.orchestrator.contract_adapter import sha256_file
from tests import test_read_only_inspect as read_only_fixtures


def build_lv_preview_fixture(base: Path) -> tuple[Path, Path]:
    helper = read_only_fixtures.ReadOnlyInspectTest("runTest")
    root, mapping_dir, _ = helper._wallet_lifecycle_fixture(base, active=True)
    plan = root / "IMPLEMENTATION_PLAN.md"
    plan.write_text(
        "\n".join([
            "### Gate 1 — Core Model", "",
            "| ID | 작업 | 대상 | 완료조건 |", "|---|---|---|---|",
            "| G1-LV3-1 | 설정·수집 프로필 로더 | `app/config.py` | 환경변수 검증, COACH 프로필 단일 관리 및 secret 미출력 |",
            "| G1-LV3-2 | Product 모델 | `app/models/product.py` | 표준 필드와 검증 구현 |", "",
            "| ID | depends_on | execution | owned_files | input → output / exit_check |",
            "|---|---|---|---|---|",
            "| G1-LV3-1 | Gate 0 | parallel-eligible | `app/config.py`, 관련 테스트 | 환경변수·수집 프로필 계약 → 설정·프로필 로더 / 단일 프로필 테스트 |",
            "| G1-LV3-2 | Gate 0 | parallel-eligible | `app/models/product.py`, 관련 테스트 | 표준 상품 필드 → Product 모델 / 모델 테스트 |", "",
        ]), encoding="utf-8",
    )
    plan_hash = sha256_file(plan)
    approval_path = root / "docs" / "APPROVAL.md"
    approval_blocks = approval_path.read_text(encoding="utf-8")
    parsed_events = [json.loads(block) for block in re.findall(r"```json\n(.*?)\n```", approval_blocks, flags=re.DOTALL)]
    parsed_events[-1]["plan_sha256"] = plan_hash
    parsed_events[-1]["record_hash"] = calculate_record_hash(parsed_events[-1])
    approval_path.write_text(helper._approval_text(parsed_events), encoding="utf-8")
    ledger_path = root / "docs" / "GATE_STATE.md"
    ledger_text = ledger_path.read_text(encoding="utf-8")
    ledger = json.loads(ledger_text.split("```json\n", 1)[1].split("\n```", 1)[0])
    ledger["plan_sha256"] = plan_hash
    ledger["approval_record_hash"] = parsed_events[-1]["record_hash"]
    ledger_path.write_text("# Gate State Ledger\n\n```json\n" + json.dumps(ledger, indent=2) + "\n```\n", encoding="utf-8")
    mapping_path = mapping_dir / f"{root.name}.json"
    mapping = json.loads(mapping_path.read_text(encoding="utf-8"))
    mapping["canonical_implementation_source"]["sha256"] = plan_hash
    mapping_path.write_text(json.dumps(mapping), encoding="utf-8")
    subprocess.run(["git", "-C", str(root), "add", "--", "IMPLEMENTATION_PLAN.md", "docs/APPROVAL.md", "docs/GATE_STATE.md"], check=True)
    subprocess.run(["git", "-C", str(root), "commit", "-q", "-m", "bind LV preview plan"], check=True)
    return root, mapping_dir
