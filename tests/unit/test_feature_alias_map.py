"""feature-alias-map-v1 golden vector·fail-close 계약 (T-VN-32C).

`contracts/feature-alias-map-v1-golden.json`은 PinVi가 vendored 사본으로 독립
재계산하는 양 저장소 공용 golden이다 — `cache-target-source-v1` golden과 같은
패턴. 본 테스트는 Map 정본 구현(`core.feature_alias_map`)이 golden bytes를
그대로 재계산하는지와 canonical 검증의 fail-close를 고정한다.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any, cast

import pytest

from kortravelmap.core.feature_alias_map import (
    FEATURE_ALIAS_KINDS,
    FEATURE_ALIAS_MAP_VERSION,
    FeatureAliasMapRowV1,
    feature_alias_leaf_digest,
    feature_alias_map_merkle_root,
    validate_canonical_feature_uuid,
    validate_feature_alias,
)
from kortravelmap.core.ids import FEATURE_UUID_NAMESPACE, feature_uuid_from_legacy

_GOLDEN_PATH = (
    Path(__file__).resolve().parents[2] / "contracts" / "feature-alias-map-v1-golden.json"
)


def _golden() -> dict[str, Any]:
    return cast(dict[str, Any], json.loads(_GOLDEN_PATH.read_text(encoding="utf-8")))


def _golden_rows() -> list[FeatureAliasMapRowV1]:
    return [
        FeatureAliasMapRowV1(
            alias=row["alias"],
            feature_uuid=row["feature_uuid"],
            alias_kind=row["alias_kind"],
        )
        for row in _golden()["merkle_v1"]["rows"]
    ]


def _golden_nonderived_row() -> FeatureAliasMapRowV1:
    row = _golden()["nonderived_v1"]["row"]
    return FeatureAliasMapRowV1(
        alias=row["alias"],
        feature_uuid=row["feature_uuid"],
        alias_kind=row["alias_kind"],
    )


def test_golden_schema_and_namespace_match_code_constants() -> None:
    golden = _golden()
    assert golden["schema"] == FEATURE_ALIAS_MAP_VERSION
    assert golden["alias_kinds"] == sorted(FEATURE_ALIAS_KINDS)
    derivation = golden["derivation"]
    assert derivation["feature_uuid_namespace"] == str(FEATURE_UUID_NAMESPACE)
    # namespace 자체도 명시 basis에서 재파생 가능해야 한다 (영구 약속).
    assert uuid.uuid5(
        uuid.NAMESPACE_URL, "kor-travel-map:feature-uuid:v1"
    ) == FEATURE_UUID_NAMESPACE


def test_golden_rows_match_leaf_digest_order_and_root() -> None:
    golden = _golden()["merkle_v1"]
    rows = _golden_rows()

    assert [feature_alias_leaf_digest(row).hex() for row in rows] == [
        row["leaf_sha256"] for row in golden["rows"]
    ]
    assert [
        row.alias for row in sorted(rows, key=lambda row: row.alias.encode("utf-8"))
    ] == golden["expected_nfc_utf8_order"]
    assert feature_alias_map_merkle_root(rows) == golden["root"]
    # 입력 순서 무관 — 정렬은 계약이 소유한다.
    assert feature_alias_map_merkle_root(list(reversed(rows))) == golden["root"]
    assert feature_alias_map_merkle_root([]) == golden["empty_root"]
    assert (
        feature_alias_map_merkle_root(rows[:3]) == golden["odd_promotion_root_first3"]
    )


# ── 0083 비파생 UUIDv7 행 — 파생 등식 없이도 계약을 통과한다 ────────────────


def test_nonderived_v7_row_is_accepted_and_matches_golden_leaf() -> None:
    """비파생 UUIDv7 행은 shape 검증만으로 수용되고 leaf가 golden과 같다.

    0083(T-VN-32C 값 전환) 이후 신규 행의 ``feature_uuid``는 legacy alias에서
    파생되지 않는다 — 이 행은 ``uuid5(namespace, alias)``와 다르지만 계약상
    적법하다(파생 등식은 더 이상 계약이 아님).
    """
    golden = _golden()["nonderived_v1"]
    row = _golden_nonderived_row()

    assert uuid.UUID(row.feature_uuid).version == 7
    # 파생 세대와 명시적으로 다르다 — "파생을 강제하지 않음"의 실질 증거.
    assert row.feature_uuid != str(feature_uuid_from_legacy(row.alias))
    assert feature_alias_leaf_digest(row).hex() == golden["leaf_sha256"]


def test_mixed_generation_map_root_and_order_match_golden() -> None:
    """파생 4행 + 비파생 1행이 섞인 map의 root·정렬이 golden과 일치한다."""
    golden = _golden()["nonderived_v1"]
    rows = [*_golden_rows(), _golden_nonderived_row()]

    assert feature_alias_map_merkle_root(rows) == golden["root_with_merkle_v1_rows"]
    assert feature_alias_map_merkle_root(list(reversed(rows))) == (
        golden["root_with_merkle_v1_rows"]
    )
    assert [
        row.alias for row in sorted(rows, key=lambda row: row.alias.encode("utf-8"))
    ] == golden["expected_nfc_utf8_order_with_merkle_v1_rows"]


def test_merkle_v1_rows_remain_derived_generation_anchor() -> None:
    """역사 앵커 — 기존(backfill) 세대 4행은 여전히 uuid5 파생 산출이다.

    0082 identity fence가 기존 731,600행의 파생값을 영구 보존하므로, 파생
    **검증**은 폐기해도 파생 **세대 벡터**는 고정해 둔다 (재backfill·
    downgrade 경로가 같은 값을 재계산해야 한다).
    """
    for row in _golden_rows():
        assert row.feature_uuid == str(feature_uuid_from_legacy(row.alias))


def test_golden_derivation_rule_documents_nonderived_cutover() -> None:
    """계약 문서 회귀 앵커 — rule 문구가 0083 전환을 명시해야 한다."""
    rule = _golden()["derivation"]["rule"]
    assert "UUIDv7" in rule
    assert "파생 재계산이 아니라" in rule


def test_alias_validation_rejects_non_nfc_padding_empty_and_overlong() -> None:
    with pytest.raises(ValueError, match="trim"):
        validate_feature_alias("")
    with pytest.raises(ValueError, match="trim"):
        validate_feature_alias(" f_x ")
    with pytest.raises(ValueError, match="NFC"):
        validate_feature_alias("e\u0301")  # NFD — 정규화하지 않고 거부한다.
    with pytest.raises(ValueError, match="256"):
        validate_feature_alias("f" * 257)


def test_uuid_validation_rejects_non_canonical_forms() -> None:
    canonical = "4232803d-a8a7-57c2-b80b-e13ca8fa1a2a"
    assert validate_canonical_feature_uuid(canonical) == canonical
    for bad in (
        canonical.upper(),
        canonical.replace("-", ""),
        "urn:uuid:" + canonical,
        "{" + canonical + "}",
        canonical[:-1],
    ):
        with pytest.raises(ValueError, match="canonical"):
            validate_canonical_feature_uuid(bad)


def test_row_construction_rejects_unknown_kind() -> None:
    with pytest.raises(ValueError, match="alias_kind"):
        FeatureAliasMapRowV1(
            alias="f_global_e_x",
            feature_uuid="4232803d-a8a7-57c2-b80b-e13ca8fa1a2a",
            alias_kind="merge_loser",
        )


def test_merkle_root_rejects_duplicate_alias() -> None:
    rows = _golden_rows()
    with pytest.raises(ValueError, match="중복"):
        feature_alias_map_merkle_root([rows[0], rows[0]])
