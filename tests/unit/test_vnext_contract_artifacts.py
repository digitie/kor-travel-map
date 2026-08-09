"""T-VN-31 freeze artifact의 drift fail-close (T-VN-31C).

unit job은 매 PR 실행되므로 이 테스트가 T-VN-31A/B artifact drift의 CI 게이트다:

1. artifact 7종(파일 8개)의 bytes sha256을 상수로 고정한다 — artifact를 바꾸는
   PR은 반드시 이 상수를 함께 갱신해야 한다(의식적 freeze 개정).
2. openapi-diff-v1.json의 baseline sha256이 현행 3 spec bytes와 일치하고, diff가
   참조하는 모든 현행 operation이 실제 spec에 존재한다(added의 target은 부재).
3. consumer-rollout-v1.json·recovery-preflight-v1.json의 JSON shape 검증.
4. violation fixture ↔ expected rejection ↔ target DDL의 상호 일관성.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import fields
from pathlib import Path
from typing import Any, Final

from kortravelmap.core.cache_target_stream import SnapshotMerkleRowV1

_ROOT: Final = Path(__file__).resolve().parents[2]
_CONTRACTS: Final = _ROOT / "contracts" / "vnext"

# artifact bytes 고정 — 갱신 절차: artifact 수정 → 통합 테스트로 fingerprint 재고정
# → 여기 sha256 갱신 (한 PR에서 함께).
ARTIFACT_SHA256: Final[dict[str, str]] = {
    "target-schema-v1.sql": ("87048b3caaabf60b9f3f0d03d06057f53706417ca99773e2013e4dda85fbdf03"),
    "target-invariants-v1.sql": (
        "7fbe90daf7f6f48386ce96877189b444e57d18f5d2897fd81a09cbadb2aee200"
    ),
    "target-schema-fingerprints-v1.json": (
        "08a68f86233aa84f818da4bc47e8826b1485b67e69632bb99760f12702c03883"
    ),
    "tvn33-reference-ownership-v1.sql": (
        "e9a342f7c227f25643f3c1360b081abafac1e89bfb4c52339b89e985401b1604"
    ),
    "openapi-diff-v1.json": ("1ff2af411172aa69b01bc42f48360b094b284d242b299e322ff5e8e8594b26c1"),
    "consumer-rollout-v1.json": (
        "d9983dbe96094c9439b575e8ff8e5f1e4bca0656fa4b8166f2449010ad2b8d38"
    ),
    "violation-fixtures-v1.sql": (
        "d7d254b2bf01c6c2ec9c06ac6f862d652b1833051f6cf0f5ab0135f91255ac9d"
    ),
    "expected-rejections-v1.json": (
        "8523efb6cc8d93028624e9c10d0a4b6180954b64ee4e4ca5f81e5e0b8483f5ed"
    ),
    "recovery-preflight-v1.json": (
        "0e7e1ea595d034aacda8b4c94b56de6c2a24059f150c8cbd6c0670aebce7dfdd"
    ),
}

_EXPECTED_INVARIANT_COUNT: Final = 53
_INVARIANT_PHASES: Final = frozenset({"pre-backfill", "post-backfill", "both"})
_SURFACES: Final = ("user", "service", "admin")
_CHANGE_KEYS: Final = (
    "added",
    "removed",
    "renamed",
    "enum_changes",
    "status_changes",
    "error_changes",
)
_WAVE2_TASKS: Final = (
    "T-VN-32",
    "T-VN-33",
    "T-VN-34",
    "T-VN-35",
    "T-VN-36",
    "T-VN-37",
    "T-VN-38",
    "T-VN-40",
    "T-VN-39",
)
_REVENDOR_VALUES: Final = frozenset({"yes", "no", "deferred-to-implementation"})


def _load_json(name: str) -> dict[str, Any]:
    payload = json.loads((_CONTRACTS / name).read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def _load_invariant_queries() -> list[tuple[str, str]]:
    """(질의, phase) 쌍 파싱 — 통합 테스트 파서와 같은 문법·같은 fail-open 봉합(D1)."""
    content = (_CONTRACTS / "target-invariants-v1.sql").read_text(encoding="utf-8")
    parsed = re.findall(
        r"(?ms)^(SELECT .*?); -- expect: 0 -- phase: (pre-backfill|post-backfill|both)$",
        content,
    )
    marker_count = content.count("-- expect: 0")
    assert marker_count == len(parsed), (
        f"invariant trailer {marker_count}개 중 {len(parsed)}개만 파싱됨 — "
        "phase 태그 누락 또는 trailer 문법 위반"
    )
    return [(query, phase) for query, phase in parsed]


def _load_violation_case_names() -> set[str]:
    content = (_CONTRACTS / "violation-fixtures-v1.sql").read_text(encoding="utf-8")
    return set(re.findall(r"(?m)^-- case: (\S+)$", content))


def _operation_exists(spec: dict[str, Any], operation: str) -> bool:
    method, _, path = operation.partition(" ")
    item = spec.get("paths", {}).get(path)
    return item is not None and method.lower() in item


def test_artifact_bytes_are_frozen() -> None:
    for name, expected in ARTIFACT_SHA256.items():
        observed = hashlib.sha256((_CONTRACTS / name).read_bytes()).hexdigest()
        assert observed == expected, (
            f"{name} bytes drift — freeze 개정이면 상수를 {observed}로 갱신하라"
        )


def test_openapi_diff_baseline_matches_current_specs() -> None:
    diff = _load_json("openapi-diff-v1.json")
    assert tuple(diff["surfaces"]) == _SURFACES
    for surface in _SURFACES:
        baseline = diff["baseline"][surface]
        spec_path = _ROOT / baseline["file"]
        observed = hashlib.sha256(spec_path.read_bytes()).hexdigest()
        assert observed == baseline["sha256"], (
            f"{surface} spec drift — 현행 spec이 바뀌었다. diff freeze를 재검토하고 "
            f"baseline sha256을 {observed}로 갱신하라"
        )


def test_openapi_diff_referenced_operations_exist() -> None:
    diff = _load_json("openapi-diff-v1.json")
    for surface in _SURFACES:
        spec = json.loads((_ROOT / diff["baseline"][surface]["file"]).read_text(encoding="utf-8"))
        changes = diff["surfaces"][surface]
        # 리뷰 D3 — counts 2차 방어: 선언된 개수와 실제 배열 길이 대조.
        counts = changes["counts"]
        assert set(counts) == {*_CHANGE_KEYS, "deferred"}, f"{surface} counts 축 불일치"
        for key, declared in counts.items():
            assert declared == len(changes.get(key, [])), (
                f"{surface}/{key} counts {declared} != 실제 {len(changes.get(key, []))}"
            )
        for key in _CHANGE_KEYS:
            assert key in changes, f"{surface}에 change 축 {key} 누락"
            for entry in changes[key]:
                assert entry.get("basis"), f"{surface}/{key} 항목에 basis 누락: {entry}"
                operation = entry.get("operation")
                if operation is not None:
                    assert _operation_exists(spec, operation), (
                        f"{surface}/{key}가 참조한 현행 operation 부재: {operation}"
                    )
                target = entry.get("target_operation")
                if target is not None:
                    assert not _operation_exists(spec, target), (
                        f"{surface}/{key}의 target operation이 이미 현행 spec에 존재: {target}"
                    )
        for entry in changes.get("deferred", []):
            assert entry.get("decision") == "deferred-to-implementation"
            assert entry.get("owner", "").startswith("T-VN-"), entry


def test_consumer_rollout_shape() -> None:
    rollout = _load_json("consumer-rollout-v1.json")
    assert rollout["pinvi_snapshots"] == ["user", "service", "admin-detail"]
    assert tuple(rollout["tasks"]) == _WAVE2_TASKS
    for task_id, task in rollout["tasks"].items():
        for key in ("title", "write_fence", "compat_drop"):
            assert isinstance(task[key], str), f"{task_id}.{key}"
            assert task[key], f"{task_id}.{key} 비어 있음"
        order = task["consumer_first_order"]
        assert isinstance(order, list), f"{task_id} 배포 순서 타입"
        assert order, f"{task_id} 배포 순서 누락"
        revendor = task["pinvi_snapshot_revendor"]
        assert set(revendor) == {"user", "service", "admin-detail"}, task_id
        assert set(revendor.values()) <= _REVENDOR_VALUES, task_id
    entries = rollout["removal_manifest"]["entries"]
    assert entries, "removal manifest가 비어 있다"
    for entry in entries:
        assert entry["removed_by"] == "T-VN-39"
        assert entry["fenced_by"].startswith("T-VN-")
        assert isinstance(entry["object"], str)
        assert entry["object"]


def test_recovery_preflight_shape() -> None:
    preflight = _load_json("recovery-preflight-v1.json")
    registry = preflight["writer_registry"]
    assert len(registry["classes"]) == 5, "H35 runbook §6 writer class는 5종이다"
    assert "registry" in registry["completeness_rule"]
    evidence = preflight["fence_evidence_keys"]["keys"]
    assert set(evidence) == {
        "database_identity",
        "runtime_mutation_count",
        "external_event_count",
        "forward_boundary",
        "transaction_id",
        "prior_receipt_digest",
    }
    rules = preflight["forward_recovery_rules"]["rules"]
    assert isinstance(rules, list)
    assert len(rules) >= 4
    shadow = preflight["shadow_checksum"]
    assert {relation["name"] for relation in shadow["relations"]} >= {
        "feature identity alias map",
        "cache target snapshot",
    }
    merkle = shadow["merkle_definition"]
    assert merkle["leaf_fields"] == [field.name for field in fields(SnapshotMerkleRowV1)]
    assert "KTMCTLEAF" in merkle["leaf"]
    assert "KTMCTNODE" in merkle["node"]
    assert "KTMCTEMPTY" in merkle["empty_root"]


def test_expected_rejections_consistent_with_fixtures_and_ddl() -> None:
    rejections = _load_json("expected-rejections-v1.json")["cases"]
    assert set(rejections) == _load_violation_case_names()
    schema_sql = (
        (_CONTRACTS / "target-schema-v1.sql").read_text(encoding="utf-8")
        + "\n"
        + (_CONTRACTS / "tvn33-reference-ownership-v1.sql").read_text(encoding="utf-8")
    )
    for name, case in rejections.items():
        assert re.fullmatch(r"23(502|503|505|514)", case["sqlstate"]), name
        if "column" in case:
            assert set(case) >= {"sqlstate", "column", "basis"}, name
            assert f"{case['column']} text NOT NULL" in schema_sql, (
                f"case {name}의 NOT NULL 열 {case['column']}이 target DDL에 없다"
            )
        else:
            assert case["constraint"] in schema_sql, (
                f"case {name}의 제약명 {case['constraint']}이 target DDL에 없다"
            )
        assert case["basis"].startswith(("ADR-", "T-VN-")), name


def test_invariants_are_parseable_zero_assertions() -> None:
    queries = _load_invariant_queries()
    assert len(queries) == _EXPECTED_INVARIANT_COUNT
    for query, phase in queries:
        assert phase in _INVARIANT_PHASES, phase
        assert query.lstrip().upper().startswith("SELECT COUNT(*)"), query[:80]
