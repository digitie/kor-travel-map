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
    verify_legacy_alias_derivation,
)
from kortravelmap.core.ids import FEATURE_UUID_NAMESPACE

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


def test_golden_rows_pass_legacy_derivation_verification() -> None:
    for row in _golden_rows():
        verify_legacy_alias_derivation(row)


def test_derivation_mismatch_is_rejected() -> None:
    row = FeatureAliasMapRowV1(
        alias="f_1168010100_p_3c0c2820e96d28d3",
        # 형태는 canonical이지만 파생 규칙과 다른 uuid.
        feature_uuid="00000000-0000-4000-8000-000000000000",
        alias_kind="legacy_feature_id",
    )
    with pytest.raises(ValueError, match="파생 불일치"):
        verify_legacy_alias_derivation(row)


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
