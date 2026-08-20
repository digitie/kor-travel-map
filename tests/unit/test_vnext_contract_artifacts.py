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
from scripts.lib.c7_prod_attestation import GENERATION_RUNTIME_IMAGE_FIELDS

_ROOT: Final = Path(__file__).resolve().parents[2]
_CONTRACTS: Final = _ROOT / "contracts" / "vnext"
_TVN34_CURRENT_MIGRATION: Final = (
    # squash(`0200`) 이후 체인은 아카이브다 — `alembic/legacy_versions/README.md`.
    _ROOT / "alembic" / "legacy_versions" / "0095_feature_orthogonal_state_spine.py"
)

# artifact bytes 고정 — 갱신 절차: artifact 수정 → 통합 테스트로 fingerprint 재고정
# → 여기 sha256 갱신 (한 PR에서 함께).
ARTIFACT_SHA256: Final[dict[str, str]] = {
    "target-schema-v1.sql": ("11fb6a2ec85d87ca7e32bb63155ede380ced6ebce46e3ebe6c8b34e9cfb756f4"),
    "target-invariants-v1.sql": (
        "971f656169cb1d2f21f9286d22e732daf16a3a9d79456e0f221bae4c04b86e26"
    ),
    # 2026-08-13 T-VN-40 — final catalog/receipt/generation/candidate/audit 관계를
    # target+reference SQL에 반영한 뒤 빈 PostGIS DB에서 7축을 재실측했다.
    "target-schema-fingerprints-v1.json": (
        "084986b9b7764be8098401b6ef26dd48ed174288bec5c7a5a84b3fb63ea1313e"
    ),
    "tvn33-reference-ownership-v1.sql": (
        "2e72796b373691b4d6e10f71eceec4504df94af1a2582edbf445fb2390f20b6b"
    ),
    # 2026-08-13 T-VN-40 — public legacy catalog 제거, scoped service snapshot/mapping,
    # admin catalog/import/candidate ETag·412/428 목표 diff를 machine freeze했다.
    "openapi-diff-v1.json": ("bf462eccdbccdf813e319b35d6a92e9d9b9cfb2756698f79501c89cc0adf399f"),
    # 2026-08-13 T-VN-36 — receipt가 리베이스로 폐기된 커밋(c1fa5a4d)과 그때의
    # spec sha를 가리키고 있었다. 현재 head로 재핀했다.
    # 2026-08-19 T-VN-40 ③ 완료 — C7 prod live 6-spec GREEN(f00e7f48) 뒤 receipt를
    # complete로 봉인했다.
    "consumer-rollout-v1.json": (
        "03b79f491ac258d3864dde5d1626f4f6bd2eac302a0a2601b5d57433c9f1d53d"
    ),
    # T-VN-41S service 계약 변경으로 active receipt가 pending으로 돌아가도, 이전
    # candidate archive·image·Live UI 증거 세트는 detached 이력으로 불변이어야 한다.
    "t-vn-41-candidate-manifest-v1.json": (
        "f5620c37f5f2665371d86d434ae5ef1e0c34815462f335fcb15e760f5d40a085"
    ),
    "t-vn-41-candidate-attestation-v1.json": (
        "ca99a15ce37722362b17fa1b291fba7c7141b87d912971e2a6bf8e418cf219be"
    ),
    "t-vn-41-candidate-live-e2e-evidence-v1.json": (
        "15e05098949d52097a64826c0702fe72149c138f3863ce9be98042b9079e58f4"
    ),
    "violation-fixtures-v1.sql": (
        "84cca48b776387e4b6fd00b702e40b3412c9731f6abcdd250a5c126c2ea155d8"
    ),
    "expected-rejections-v1.json": (
        "9123b16dba0adb27c5da2207ad8bef51225a780e37b28d04a94a8b0e8435f5ed"
    ),
    "recovery-preflight-v1.json": (
        "e3eb905cdfc51b71e2d4feb1979ac65cfe3c1446776e133332a4fa6969634655"
    ),
}

_EXPECTED_INVARIANT_COUNT: Final = 67
_INVARIANT_PHASES: Final = frozenset({"pre-backfill", "post-backfill", "both"})
_SURFACES: Final = ("user", "service", "admin")
_CHANGE_KEYS: Final = (
    "added",
    "removed",
    "renamed",
    "enum_changes",
    "status_changes",
    "error_changes",
    "schema_changes",
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
    "T-VN-41",
    "T-VN-39",
)
_REVENDOR_VALUES: Final = frozenset({"yes", "no", "deferred-to-implementation"})
# 전방 계약: 다음 candidate 승격은 v5 pinned runtime generation으로 발행된다.
# 목록을 손으로 적으면 generation에 runtime이 늘어도 receipt는 그대로여서 늘어난
# image가 증거 밖에 남는다 — v4가 정확히 그 상태였다(PinVi web/dagster 누락).
_C7_ROLE_RECEIPT_FIELDS: Final[dict[str, tuple[str, str]]] = {
    role: (generation_field, f"{role}_image_id")
    for role, generation_field in GENERATION_RUNTIME_IMAGE_FIELDS
}
# detached 이력: 아래 세 archive artifact는 v4 compatible-pair 시절의 후보 증거이며
# freeze 상수로 불변이다. 현행 계약이 v5로 옮겨갔다고 해서 과거 증거의 모양을
# 바꿔 쓰면 그것은 이력이 아니라 위조다. 그래서 전방 계약과 **분리된** 목록을 둔다.
_DETACHED_V4_CANDIDATE_ROLES: Final[tuple[str, ...]] = (
    "map_api",
    "map_ui",
    "map_dagster_web",
    "map_dagster_daemon",
    "pinvi_api",
)


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


def test_frozen_artifacts_have_no_crlf() -> None:
    """동결 산출물은 OS 개행 변환도 bytes freeze drift로 fail-close한다."""
    for name in ARTIFACT_SHA256:
        assert b"\r\n" not in (_CONTRACTS / name).read_bytes(), (
            f"{name} contains CRLF — frozen artifact는 LF bytes로만 저장해야 한다"
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
                    operation_exists = _operation_exists(spec, operation)
                    if key == "removed" and entry.get("applied") is True:
                        assert not operation_exists, (
                            f"{surface}/{key}의 applied operation 잔존: {operation}"
                        )
                    else:
                        assert operation_exists, (
                            f"{surface}/{key}가 참조한 현행 operation 부재: {operation}"
                        )
                target = entry.get("target_operation")
                if target is not None:
                    target_exists = _operation_exists(spec, target)
                    if entry.get("applied") is True:
                        assert target_exists, (
                            f"{surface}/{key}의 applied target operation 부재: {target}"
                        )
                    else:
                        assert not target_exists, (
                            f"{surface}/{key}의 target operation이 이미 현행 spec에 존재: "
                            f"{target} — 적용 완료면 applied=true를 고정하라"
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
    receipt = rollout["tasks"]["T-VN-34"]["pinvi_snapshot_receipt"]
    assert set(receipt) == {
        "map_commit",
        "pinvi_commit",
        "map_user_openapi_sha256",
        "map_full_openapi_sha256",
        "pinvi_user_vendor_sha256",
        "pinvi_admin_detail_vendor_sha256",
        "pinvi_feature_schema_sha256",
        "verification",
    }
    assert re.fullmatch(r"[0-9a-f]{40}", receipt["map_commit"])
    assert re.fullmatch(r"[0-9a-f]{40}", receipt["pinvi_commit"])
    for key in (
        "map_user_openapi_sha256",
        "map_full_openapi_sha256",
        "pinvi_user_vendor_sha256",
        "pinvi_admin_detail_vendor_sha256",
        "pinvi_feature_schema_sha256",
    ):
        assert re.fullmatch(r"[0-9a-f]{64}", receipt[key]), key
    assert receipt["map_user_openapi_sha256"] == receipt["pinvi_user_vendor_sha256"]
    assert receipt["verification"] == [
        "admin-detail deterministic re-extraction",
        "PinVi contract pin consistency",
        "Node 22 Linux workspace typecheck",
        "public Feature no legacy status or internal state axes",
    ]
    final_receipt = rollout["tasks"]["T-VN-36"]["pinvi_snapshot_receipt"]
    assert set(final_receipt) == {
        "map_commit",
        "pinvi_commit",
        "map_user_openapi_sha256",
        "map_full_openapi_sha256",
        "pinvi_user_vendor_sha256",
        "pinvi_admin_detail_vendor_sha256",
        "verification",
    }
    assert re.fullmatch(r"[0-9a-f]{40}", final_receipt["map_commit"])
    assert re.fullmatch(r"[0-9a-f]{40}", final_receipt["pinvi_commit"])
    for key in (
        "map_user_openapi_sha256",
        "map_full_openapi_sha256",
        "pinvi_user_vendor_sha256",
        "pinvi_admin_detail_vendor_sha256",
    ):
        assert re.fullmatch(r"[0-9a-f]{64}", final_receipt[key]), key
    assert final_receipt["map_user_openapi_sha256"] == final_receipt["pinvi_user_vendor_sha256"]
    assert final_receipt["verification"] == [
        "admin-detail deterministic re-extraction",
        "PinVi contract pin consistency",
        "T-VN-36 exact Map/PinVi source pair",
    ]
    paired_receipt = rollout["tasks"]["T-VN-41"]["pinvi_snapshot_receipt"]
    service_sha256 = hashlib.sha256(
        (_ROOT / "packages/kor-travel-map-api/openapi.service.json").read_bytes()
    ).hexdigest()
    assert paired_receipt["state"] in {"pending", "candidate_verified", "complete"}
    if paired_receipt["state"] == "pending":
        assert set(paired_receipt) == {
            "state",
            "map_service_openapi_sha256",
            "pinvi_service_vendor_sha256",
            "blocking_reason",
        }
        assert paired_receipt["blocking_reason"].strip()
        assert paired_receipt["map_service_openapi_sha256"] == service_sha256
        assert (
            paired_receipt["map_service_openapi_sha256"]
            == paired_receipt["pinvi_service_vendor_sha256"]
        )
    else:
        required_keys = {
            "state",
            "map_service_openapi_sha256",
            "pinvi_service_vendor_sha256",
            "verification",
        }
        assert set(_C7_ROLE_RECEIPT_FIELDS) == {
            role for role, _ in GENERATION_RUNTIME_IMAGE_FIELDS
        }
        if paired_receipt["state"] == "candidate_verified":
            prefix = "candidate_"
            state_keys = {
                f"{prefix}map_commit",
                f"{prefix}pinvi_commit",
                f"{prefix}pinned_runtime_manifest_sha256",
                f"{prefix}rebuild_journal_sha256",
                f"{prefix}pinned_runtime_attestation_sha256",
                f"{prefix}live_e2e_evidence_sha256",
                "final_c7_required",
            }
            assert paired_receipt["final_c7_required"] is True
        else:
            prefix = "final_"
            state_keys = {
                f"{prefix}map_commit",
                f"{prefix}pinvi_commit",
                f"{prefix}pinned_runtime_manifest_sha256",
                f"{prefix}rebuild_journal_sha256",
                f"{prefix}c7_attestation_sha256",
                f"{prefix}live_e2e_evidence_sha256",
            }
        image_keys = {
            f"{prefix}{receipt_field}" for _, receipt_field in _C7_ROLE_RECEIPT_FIELDS.values()
        }
        assert len(image_keys) == len(GENERATION_RUNTIME_IMAGE_FIELDS)
        assert set(paired_receipt) == required_keys | state_keys | image_keys
        for key in (f"{prefix}map_commit", f"{prefix}pinvi_commit"):
            assert re.fullmatch(r"[0-9a-f]{40}", paired_receipt[key]), key
        for key in (
            "map_service_openapi_sha256",
            "pinvi_service_vendor_sha256",
            f"{prefix}pinned_runtime_manifest_sha256",
            f"{prefix}rebuild_journal_sha256",
            (
                f"{prefix}pinned_runtime_attestation_sha256"
                if paired_receipt["state"] == "candidate_verified"
                else f"{prefix}c7_attestation_sha256"
            ),
            f"{prefix}live_e2e_evidence_sha256",
        ):
            assert re.fullmatch(r"[0-9a-f]{64}", paired_receipt[key]), key
        for key in image_keys:
            assert re.fullmatch(r"sha256:[0-9a-f]{64}", paired_receipt[key]), key
        assert paired_receipt["map_service_openapi_sha256"] == service_sha256
        assert (
            paired_receipt["map_service_openapi_sha256"]
            == paired_receipt["pinvi_service_vendor_sha256"]
        )
        expected_verification = [
            "PinVi service vendor bytes are exact",
            "n150 isolated candidate Map/PinVi Live UI E2E passed",
            "candidate archive, immutable images, and attestation are exact",
        ]
        if paired_receipt["state"] == "candidate_verified":
            assert paired_receipt["verification"] == expected_verification
        else:
            assert paired_receipt["verification"] == [
                *expected_verification,
                "final main C7 attestation passed",
            ]


def test_active_pinvi_receipt_describes_current_consumed_specs() -> None:
    """마지막 receipt의 소비자 공유 spec sha가 현재 트리와 일치하는지 본다.

    위 단언들은 전부 `[0-9a-f]{40}` 같은 **모양**만 본다. 그래서 receipt가 리베이스로
    폐기된 커밋과 그때의 spec sha를 가리켜도 green이었고, `install-…-live-e2e.sh`는
    그 `map_commit`을 `git archive`해 **다른 트리**를 n150에 올린 뒤 같은 커밋을
    해싱해 통과시켰다 — 자기 정합적이라 아무도 눈치채지 못한다. 실제로 T-VN-34와
    T-VN-36 receipt가 연달아 이 상태로 남았고 T-VN-34 것은 main까지 갔다.

    커밋 도달 가능성은 shallow clone CI에서 확인할 수 없으므로, 검사 가능한 등가
    불변식을 쓴다 — "가장 최근 receipt는 지금 트리의 spec을 서술한다". 리베이스로
    커밋이 갈려도 spec bytes가 그대로면 gate가 검증하는 대상은 같고, spec이 바뀌면
    반드시 red가 된다.
    """

    rollout = _load_json("consumer-rollout-v1.json")
    task = rollout["deployment_receipt_task"]
    assert task in rollout["tasks"]
    receipt = rollout["tasks"][task]["pinvi_snapshot_receipt"]
    api_root = _ROOT / "packages/kor-travel-map-api"
    for name, key in (
        ("openapi.user.json", "map_user_openapi_sha256"),
        ("openapi.service.json", "map_service_openapi_sha256"),
        ("openapi.json", "map_full_openapi_sha256"),
    ):
        observed = hashlib.sha256((api_root / name).read_bytes()).hexdigest()
        assert observed == receipt[key], (
            f"{name}이 {task} receipt와 다르다 — receipt를 현재 head로 재핀하라 "
            f"({key}를 {observed}로)"
        )
    assert receipt["state"] in {"pending", "complete"}
    if receipt["state"] == "pending":
        assert receipt["blocking_reason"].strip()
        assert "map_commit" not in receipt
        assert "pinvi_commit" not in receipt
    else:
        assert set(receipt) == {
            "state",
            "map_commit",
            "pinvi_commit",
            "map_user_openapi_sha256",
            "map_service_openapi_sha256",
            "map_full_openapi_sha256",
            "pinvi_user_vendor_sha256",
            "pinvi_service_vendor_sha256",
            "verification",
        }
        for key in ("map_commit", "pinvi_commit"):
            assert re.fullmatch(r"[0-9a-f]{40}", receipt[key]), key
        for key in (
            "map_user_openapi_sha256",
            "map_service_openapi_sha256",
            "map_full_openapi_sha256",
            "pinvi_user_vendor_sha256",
            "pinvi_service_vendor_sha256",
        ):
            assert re.fullmatch(r"[0-9a-f]{64}", receipt[key]), key
        assert receipt["map_user_openapi_sha256"] == receipt["pinvi_user_vendor_sha256"]
        assert receipt["map_service_openapi_sha256"] == receipt["pinvi_service_vendor_sha256"]
        assert receipt["verification"] == [
            "PinVi user/service vendor bytes are exact",
            "PinVi canonical curation importer has no legacy admin snapshot consumer",
            "paired Map/PinVi n150 canonical snapshot live acceptance passed",
        ]
    entries = rollout["removal_manifest"]["entries"]
    assert entries, "removal manifest가 비어 있다"
    for entry in entries:
        removed_by = entry["removed_by"]
        task_match = re.fullmatch(r"(T-VN-\d+)(?:[A-Z][A-Z0-9-]*)?", removed_by)
        assert task_match, f"제거 task 형식 불일치: {removed_by}"
        assert task_match.group(1) in rollout["tasks"], (
            f"제거 task가 rollout task가 아님: {removed_by}"
        )
        assert entry["fenced_by"].startswith("T-VN-")
        assert isinstance(entry["object"], str)
        assert entry["object"]


def test_tvn41_candidate_artifacts_bind_immutable_live_evidence() -> None:
    """T-VN-41 후보 artifact가 실행한 archive·image·UI 증적을 직접 가리킨다.

    receipt의 digest를 모양만 검증하면 서로 무관한 임의 문자열을 넣어
    ``candidate_verified``를 선언할 수 있다. 세 JSON의 raw bytes와 receipt를 함께
    고정해, source pair·C7 5-image 역할·blocked→ready UI 회복 증적이 한 후보임을
    CI에서 fail-closed로 확인한다. service 계약이 바뀌어 receipt가 ``pending``으로
    돌아간 동안에는 과거 후보를 현행 계약 증거로 재사용하지 않고 detached 이력의
    내부 정합성만 검증한다.
    """

    rollout = _load_json("consumer-rollout-v1.json")
    receipt = rollout["tasks"]["T-VN-41"]["pinvi_snapshot_receipt"]

    manifest_path = _CONTRACTS / "t-vn-41-candidate-manifest-v1.json"
    attestation_path = _CONTRACTS / "t-vn-41-candidate-attestation-v1.json"
    evidence_path = _CONTRACTS / "t-vn-41-candidate-live-e2e-evidence-v1.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    attestation = json.loads(attestation_path.read_text(encoding="utf-8"))
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))

    manifest_sha256 = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    attestation_sha256 = hashlib.sha256(attestation_path.read_bytes()).hexdigest()
    evidence_sha256 = hashlib.sha256(evidence_path.read_bytes()).hexdigest()
    # 이 archive는 v4 시절 증거다. receipt가 다시 candidate_verified가 될 때는 v5
    # generation으로 발행된 **새 archive**를 가리키므로, 이 파일들이 그 자리에 다시
    # 들어오는 일은 없어야 한다. 아래는 detached 이력의 내부 정합성만 본다.
    assert receipt["state"] == "pending"
    assert manifest["map_service_openapi_sha256"] != receipt["map_service_openapi_sha256"]
    assert manifest_sha256 and attestation_sha256 and evidence_sha256

    assert set(manifest) == {
        "schema",
        "map_commit",
        "pinvi_commit",
        "map_service_openapi_sha256",
        "pinvi_service_vendor_sha256",
        "runtime_images",
    }
    assert manifest["schema"] == "t-vn-41-compatible-pair-candidate-manifest-v1"
    assert manifest["map_service_openapi_sha256"] == manifest["pinvi_service_vendor_sha256"]
    if receipt["state"] == "candidate_verified":
        assert manifest["map_commit"] == receipt["candidate_map_commit"]
        assert manifest["pinvi_commit"] == receipt["candidate_pinvi_commit"]
        assert manifest["map_service_openapi_sha256"] == receipt["map_service_openapi_sha256"]
        assert manifest["pinvi_service_vendor_sha256"] == receipt["pinvi_service_vendor_sha256"]

    expected_images = manifest["runtime_images"]
    assert set(expected_images) == set(_DETACHED_V4_CANDIDATE_ROLES)

    assert set(attestation) == {
        "schema",
        "manifest_sha256",
        "map_application_schema_head",
        "pinvi_application_schema_head",
        "runtime_image_revisions",
        "runtime_images",
        "candidate_boundary",
    }
    assert attestation["schema"] == "t-vn-41-compatible-pair-candidate-attestation-v1"
    assert attestation["manifest_sha256"] == manifest_sha256
    assert attestation["runtime_images"] == expected_images
    assert attestation["runtime_image_revisions"] == {
        role: manifest["pinvi_commit"] if role == "pinvi_api" else manifest["map_commit"]
        for role in _DETACHED_V4_CANDIDATE_ROLES
    }
    assert attestation["map_application_schema_head"]
    assert attestation["pinvi_application_schema_head"]
    assert "final main C7" in attestation["candidate_boundary"]
    assert "production consumer enable" in attestation["candidate_boundary"]

    assert set(evidence) == {
        "schema",
        "candidate_compatible_pair_attestation_sha256",
        "initial_blocked_stream",
        "final_ready_stream",
        "playwright",
    }
    assert evidence["schema"] == "t-vn-41-candidate-live-e2e-evidence-v1"
    assert evidence["candidate_compatible_pair_attestation_sha256"] == attestation_sha256
    initial = evidence["initial_blocked_stream"]
    final = evidence["final_ready_stream"]
    assert set(initial) == {
        "external_system",
        "consumer_id",
        "restore_epoch",
        "state",
        "consumer_enabled",
        "blocked_event_id",
        "snapshot_id",
        "snapshot_count",
        "snapshot_merkle_root",
        "dead_event_id",
        "delivery_counts",
    }
    assert set(final) == {
        "external_system",
        "consumer_id",
        "restore_epoch",
        "state",
        "consumer_enabled",
        "blocked_event_id",
        "snapshot_id",
        "snapshot_count",
        "snapshot_merkle_root",
        "delivery_counts",
        "reconciliation",
    }
    assert initial["external_system"] == final["external_system"] == "pinvi"
    assert initial["consumer_id"] == final["consumer_id"] == "pinvi-cache-target-consumer"
    assert initial["restore_epoch"] == final["restore_epoch"]
    assert initial["state"] == "blocked"
    assert initial["consumer_enabled"] is False
    assert initial["blocked_event_id"] == initial["dead_event_id"]
    assert initial["snapshot_count"] == final["snapshot_count"] == 1
    assert initial["snapshot_merkle_root"] == final["snapshot_merkle_root"]
    assert re.fullmatch(r"[0-9a-f-]{36}", initial["snapshot_id"])
    assert re.fullmatch(r"[0-9a-f-]{36}", final["snapshot_id"])
    assert re.fullmatch(r"[0-9a-f-]{36}", initial["dead_event_id"])
    assert initial["delivery_counts"] == {
        "pending": 1,
        "leased": 0,
        "retry": 0,
        "dead": 1,
    }
    assert final["state"] == "ready"
    assert final["consumer_enabled"] is True
    assert final["blocked_event_id"] is None
    assert final["delivery_counts"] == {
        "pending": 0,
        "leased": 0,
        "retry": 0,
        "dead": 0,
    }
    reconciliation = final["reconciliation"]
    assert reconciliation == {
        "request_id": reconciliation["request_id"],
        "status": "succeeded",
        "snapshot_id": final["snapshot_id"],
        "restore_epoch": final["restore_epoch"],
        "snapshot_count": final["snapshot_count"],
        "snapshot_merkle_root": final["snapshot_merkle_root"],
    }
    assert re.fullmatch(r"[0-9a-f-]{36}", reconciliation["request_id"])
    assert evidence["playwright"] == {
        "spec": "cache-target-streams-isolated.live.spec.ts",
        "browser": "chromium",
        "workers": 1,
        "retries": 0,
        "result": "passed",
        "bff_only": True,
        "browser_service_token_exposure": "absent",
    }


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
    curation_relations = {
        relation["name"]: relation
        for relation in shadow["relations"]
        if "curation" in relation["name"]
    }
    assert set(curation_relations) == {
        "curation pre-backfill overlay parity",
        "curation final canonical projection",
        "curation candidate backfill buckets",
    }
    assert curation_relations["curation pre-backfill overlay parity"]["phase"] == "pre-backfill"
    assert curation_relations["curation final canonical projection"]["phase"] == "post-drop"
    curation = shadow["tvn40_curation_definition"]
    assert curation["canonical_projection_leaf_fields"] == [
        "collection_id",
        "curation_item_id",
        "collection_row_revision",
        "item_row_revision",
        "feature_id",
        "feature_row_revision",
        "accepted_link_decision_id",
        "source_present",
        "snapshot_payload_hash",
        "snapshot_etag",
    ]
    assert "collection representation ETag" in curation["service_set_binding"]
    assert len(curation["final_zero"]) == 3


def test_expected_rejections_consistent_with_fixtures_and_ddl() -> None:
    rejections = _load_json("expected-rejections-v1.json")["cases"]
    assert set(rejections) == _load_violation_case_names()
    schema_sql = (
        (_CONTRACTS / "target-schema-v1.sql").read_text(encoding="utf-8")
        + "\n"
        + (_CONTRACTS / "tvn33-reference-ownership-v1.sql").read_text(encoding="utf-8")
    )
    for name, case in rejections.items():
        assert re.fullmatch(r"(?:23(502|503|505|514)|42501)", case["sqlstate"]), name
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


def test_tvn34_current_text_and_final_uuid_procedure_bridge_is_explicit() -> None:
    """0095의 legacy/text writer API를 final UUID freeze와 혼동하지 않는다."""

    current_sql = _TVN34_CURRENT_MIGRATION.read_text(encoding="utf-8")
    target_sql = (_CONTRACTS / "target-schema-v1.sql").read_text(encoding="utf-8")

    assert "feature_id text NOT NULL," in current_sql
    assert "feature_uuid uuid NOT NULL," in current_sql
    assert "IN p_feature_id text," in current_sql
    assert (
        "ALTER PROCEDURE feature.transition_feature_state("
        "text, text, text, text, bigint, jsonb)" in current_sql
    )
    assert "feature_id uuid NOT NULL," in target_sql
    assert "IN p_feature_id uuid," in target_sql
    assert (
        "ALTER PROCEDURE feature.transition_feature_state("
        "uuid, text, text, text, bigint, jsonb)" in target_sql
    )
