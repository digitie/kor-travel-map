"""``test_infra_feature_repo`` — ``feature_repo`` param 빌더 + 결과 집계 (DB 무관).

DB 적재 경로는 ``tests/integration/test_feature_repo_load.py``(testcontainers).
본 모듈은 ``Feature``/``SourceRecord``/``SourceLink`` DTO → bind params 변환과
``FeatureLoadResult`` 기본값만 단위 검증 (coord None / detail None 분기 포함).

T-VN-35(ADR-086) 이후 계약
--------------------------

core ``feature.features``에는 ``detail`` JSONB도 ``geom``도 없다(alembic 0086).
따라서 ``_feature_params``는 core 컬럼 바인딩만 만들고, kind별 값은
``feature_subtype.subtype_params``가 typed subtype 컬럼으로 매핑한다. notice
효력 종료 감산도 ``detail ->> 'valid_end_time'`` 문자열 파싱(+ 오염 방어용
``pg_input_is_valid`` cast)이 아니라 ``feature_notices.valid_end_time``
timestamptz 비교다.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Final

import pytest

from kortravelmap.core.exceptions import (
    FeatureSearchCursorInvalidError,
    FeatureSearchCursorQueryMismatchError,
    FeatureSearchCursorTamperedError,
    FeatureSearchCursorVersionUnsupportedError,
)
from kortravelmap.dto import (
    Coordinate,
    Feature,
    PlaceDetail,
    SourceLink,
    SourceRecord,
)
from kortravelmap.dto._enums import FeatureKind, SourceRole
from kortravelmap.infra import feature_repo
from kortravelmap.infra.feature_repo import (
    FeatureLoadResult,
    FeatureSearchRow,
    NearbyFeatureRow,
    _feature_params,
    _source_link_params,
    _source_record_params,
)
from kortravelmap.infra.feature_subtype import subtype_params

_KST = timezone(timedelta(hours=9))
_NOW = datetime(2026, 5, 29, 9, 0, tzinfo=_KST)
_SEARCH_CURSOR_KEY = b"unit-test-feature-search-cursor-signing-key-0001"


def _place(coord: Coordinate | None, detail: PlaceDetail | None) -> Feature:
    return Feature(
        feature_id="place:abc123",
        kind=FeatureKind.PLACE,
        name="홍대 카페",
        category="02020101",
        coord=coord,
        marker_icon="cafe",
        marker_color="P-03",
        detail=detail,
        created_at=_NOW,
        updated_at=_NOW,
    )


def test_feature_params_with_coord_and_detail() -> None:
    feature = _place(
        Coordinate(lon=Decimal("126.92"), lat=Decimal("37.55")),
        PlaceDetail(feature_id="place:abc123", place_kind="cafe"),
    )
    params = _feature_params(feature)

    assert params["feature_id"] == "place:abc123"
    assert params["kind"] == "place"
    assert params["lon"] == 126.92
    assert params["lat"] == 37.55
    # address/urls/raw_refs는 JSON 문자열 (CAST AS jsonb)
    assert isinstance(params["address"], str)
    assert json.loads(params["raw_refs"]) == []
    assert params["status"] == "active"
    # T-VN-35: core에 detail 컬럼이 없으므로 core bind에도 없다.
    assert "detail" not in params


def test_feature_params_carry_geom_wkt_for_subtype_only() -> None:
    """``geom_wkt``은 core 컬럼이 아니라 route/area subtype 전용 바인딩이다.

    ``upsert_feature``가 core 실행 전에 ``pop``하므로 core INSERT 파라미터에는
    남지 않는다 — 여기서는 빌더가 그 키를 만든다는 것만 고정한다.
    """
    params = _feature_params(_place(None, None))
    assert "geom_wkt" in params
    assert params["geom_wkt"] is None


def test_feature_detail_maps_to_typed_subtype_params() -> None:
    """kind별 값의 정본은 subtype이다 — DTO detail이 typed 컬럼으로 간다."""
    feature = _place(
        Coordinate(lon=Decimal("126.92"), lat=Decimal("37.55")),
        PlaceDetail(feature_id="place:abc123", place_kind="cafe", phones=["02-1234-5678"]),
    )
    params = subtype_params(
        feature_id=feature.feature_id,
        feature_uuid="00000000-0000-4000-8000-000000000001",
        kind=feature.kind.value,
        detail=feature.detail,
    )
    assert params is not None
    assert params["place_kind"] == "cafe"
    assert params["phones"] == ["02-1234-5678"]
    # jsonb 컬럼만 JSON 문자열로 직렬화된다(raw text() 경로 바인딩).
    assert json.loads(params["payload"]) == {}


def test_feature_params_without_coord_is_none() -> None:
    feature = _place(None, None)
    params = _feature_params(feature)

    assert params["lon"] is None
    assert params["lat"] is None
    # core bind에 detail은 애초에 없다 — 값 정본은 subtype이다.
    assert "detail" not in params
    # detail 미지정이어도 subtype 파라미터는 kind DTO 기본값으로 채워진다.
    subtype = subtype_params(
        feature_id=feature.feature_id,
        feature_uuid="00000000-0000-4000-8000-000000000001",
        kind=feature.kind.value,
        detail=feature.detail,
    )
    assert subtype is not None
    assert subtype["place_kind"] == PlaceDetail(feature_id="x").place_kind


def test_source_record_params_serializes_raw_data() -> None:
    record = SourceRecord(
        source_record_key="sr_key1",
        provider="python-datagokr-api",
        dataset_key="cultural_festivals",
        source_entity_type="festival",
        source_entity_id="E001",
        raw_payload_hash="hash1",
        raw_data={"a": 1, "b": "값"},
        fetched_at=_NOW,
    )
    params = _source_record_params(record)

    assert params["source_record_key"] == "sr_key1"
    assert params["provider"] == "python-datagokr-api"
    loaded = json.loads(params["raw_data"])
    assert loaded == {"a": 1, "b": "값"}


def test_source_link_params_maps_enum_value() -> None:
    link = SourceLink(
        feature_id="place:abc123",
        source_record_key="sr_key1",
        source_role=SourceRole.PRIMARY,
        match_method="natural_key",
        confidence=100,
        is_primary_source=True,
        created_at=_NOW,
    )
    params = _source_link_params(link)

    assert params["source_role"] == "primary"
    assert params["confidence"] == 100
    assert params["is_primary_source"] is True


def test_feature_load_result_defaults_zero() -> None:
    result = FeatureLoadResult()
    assert result.bundles_total == 0
    assert result.features_inserted == 0
    assert result.source_links_updated == 0


def test_module_exports_load_helpers() -> None:
    for name in (
        "load_bundle",
        "load_bundles",
        "upsert_feature",
        "get_feature_row",
        "features_nearby_poi_cache_target",
    ):
        assert hasattr(feature_repo, name)


@pytest.mark.parametrize("close_missing", [False, True])
def test_notice_reconcile_reranks_only_out_of_scope_feature_lineages(
    close_missing: bool,
) -> None:
    """동일 scope는 ``ranked``를 재사용해 lineage 수의 제곱 비용을 피한다."""
    sql = feature_repo._supersede_stale_notice_sql(close_missing)
    out_of_scope = sql.split("out_of_scope_feature_lineages AS MATERIALIZED (", 1)[
        1
    ].split("),\nglobal_feature_wins AS MATERIALIZED (", 1)[0]
    normalized = " ".join(out_of_scope.split())

    assert (
        "sr.provider <> :provider OR sr.dataset_key <> :dataset_key OR "
        "sr.source_entity_type <> :source_entity_type"
    ) in normalized
    assert "FROM out_of_scope_feature_lineages AS current_notice" in sql
    assert "FROM global_feature_lineages AS current_notice" not in sql


@pytest.mark.parametrize("close_missing", [False, True])
def test_notice_reconcile_materializes_lineage_ctes(close_missing: bool) -> None:
    """계보 승패 CTE는 질의당 1회만 계산돼야 한다 (ADR-087).

    ``MATERIALIZED``가 없으면 Postgres가 이 CTE를 갱신 대상 feature마다 다시
    실행한다 — 3,045 notice 규모에서 124.8초 대 0.58초다.
    """
    sql = feature_repo._supersede_stale_notice_sql(close_missing)

    assert "out_of_scope_feature_lineages AS MATERIALIZED (" in sql
    assert "global_feature_wins AS MATERIALIZED (" in sql


#: ``public_active_notice_filter_sql(..., frozen_h35_schema=True)``의 고정값
#: (2026-08-07 기준 = ``origin/main``의 필터와 byte-identical).
#:
#: H35 리허설의 존재 이유가 "0079 당시 표면을 그대로 재생한다"이므로, 이 SQL은
#: 동등해 보이는 재작성조차 두지 않는다. 리허설 자체는 **컬럼 참조 오류만** 잡지
#: 의미가 같은 재작성은 못 잡으므로(그 세대 스키마에서 실행만 되면 통과한다)
#: 여기서 바이트로 못박는다. 값이 바뀌면 리허설이 재생하는 표면이 달라진 것이다.
_FROZEN_H35_NOTICE_FILTER_SHA256: Final[str] = (
    "e934cdb89f1e390bb054447d572ba103a1c74442138d1d8567a938c560db46a7"
)


def test_frozen_h35_notice_filter_is_byte_stable() -> None:
    frozen = feature_repo.public_active_notice_filter_sql("f", frozen_h35_schema=True)

    assert len(frozen) == 15672
    assert (
        hashlib.sha256(frozen.encode()).hexdigest()
        == _FROZEN_H35_NOTICE_FILTER_SHA256
    )


def test_frozen_h35_notice_filter_does_not_touch_the_stored_column() -> None:
    """0079 세대에는 ``lineage_key`` 컬럼도 파생 함수도 없다 (ADR-087)."""
    frozen = feature_repo.public_active_notice_filter_sql("f", frozen_h35_schema=True)

    assert "sr.lineage_key" not in frozen
    assert "source_record_lineage_key" not in frozen
    # 남는 두 토큰은 파생 테이블 alias뿐이다.
    assert "AS lineage_key" in frozen
    assert "current_notice.lineage_key" in frozen


def test_current_notice_filter_reads_the_stored_lineage_column() -> None:
    """현행 필터는 계보를 **재계산하지 않는다** (ADR-087).

    재계산이 남으면 인덱스가 붙을 수 없고 경쟁자 탐색이 notice 전수 스캔으로
    되돌아간다 — 3,045 notice에서 0.17초 대 21.2초다.
    """
    current = feature_repo.public_active_notice_filter_sql("f")

    assert (
        "COALESCE(other_sr.lineage_key, other_sr.source_entity_id)"
        " = COALESCE(cur_sr.lineage_key, cur_sr.source_entity_id)"
    ) in current
    assert "raw_data" not in current
    assert "concat_ws" not in current


def test_current_notice_filter_keeps_the_ordering_test_indexable() -> None:
    """순서 조건이 **행 비교 하나**여야 Index Cond로 밀린다 (ADR-087).

    한 술어 안에 ``OR``로 묶으면 Postgres가 Filter로 남겨 계보의 payload 이력
    전체를 훑는다 — 50,001 record 계보에서 ``Rows Removed by Filter: 50000``.
    그래서 "확실히 나은 행"과 "동률"을 **두 EXISTS로 나눈다**.
    """
    current = feature_repo.public_active_notice_filter_sql("f")

    normalized = " ".join(current.split())

    assert (
        "(other_sr.last_seen_at, other_sr.source_record_key)"
        " > (cur_sr.last_seen_at, cur_sr.source_record_key)"
    ) in normalized
    assert current.count("HAVING bool_and(") == 1
    # 죽은 COALESCE가 남으면 인덱스 열과 맞지 않는다 — last_seen_at은 NOT NULL이다.
    assert "COALESCE(cur_sr.last_seen_at" not in current
    assert "COALESCE(other_sr.last_seen_at" not in current


def test_nearby_feature_sql_guards_required_lon_lat_contract() -> None:
    sql = feature_repo._NEARBY_TARGET_CTE_SQL

    assert "x_extension.ST_X(f.coord) AS lon" in sql
    assert "x_extension.ST_Y(f.coord) AS lat" in sql
    assert "f.coord IS NOT NULL" in sql
    assert "f.coord_5179 IS NOT NULL" in sql


#: T-VN-35(ADR-086) 이후의 종료 notice 감산 술어 — free-form jsonb 문자열
#: 파싱이 아니라 ``feature_notices.valid_end_time`` typed 비교다.
_TYPED_ENDED_NOTICE_FRAGMENTS: tuple[str, ...] = (
    "FROM feature.feature_notices AS ended_notice",
    "ended_notice.valid_end_time IS NOT NULL",
    "ended_notice.valid_end_time <= now()",
)

#: 되살아나면 안 되는 종전 형태 — 오염된 한 행이 공개 read 전체를 500으로
#: 만들 수 있던 문자열 파싱과 그 방어용 cast 가드(T-VN-06/F-9). typed 컬럼이
#: 그 실패 모드를 구조적으로 없앴으므로 재도입은 회귀다.
_STRING_PARSE_RELICS: tuple[str, ...] = (
    "pg_input_is_valid",
    "detail ->> 'valid_end_time'",
    "detail->>'valid_end_time'",
)


def _assert_typed_notice_filter(sql: str, alias: str, *, label: str) -> None:
    assert f"{alias}.kind <> 'notice'" in sql, f"{label} lost the kind short-circuit"
    for fragment in _TYPED_ENDED_NOTICE_FRAGMENTS:
        assert fragment in sql, f"{label} dropped typed valid_end_time comparison"
    assert f"ended_notice.feature_id = {alias}.feature_id" in sql, (
        f"{label} does not correlate on the caller alias"
    )
    for relic in _STRING_PARSE_RELICS:
        assert relic not in sql, f"{label} reintroduced free-form detail parsing"


def test_shared_notice_filter_function_compares_typed_valid_end_time() -> None:
    """중앙화된 notice 종료 감산 함수가 typed timestamptz 비교여야 한다.

    #745가 이 감산 SQL을 ``_ended_notice_hidden_sql(alias)`` /
    ``public_active_notice_filter_sql(alias)`` 함수로 중앙화하고 curation/curated
    표면까지 정본으로 확산시켰다 — 그 단일 함수가 곧 전 표면의 계약이다.
    T-VN-35(ADR-086)가 ``detail`` 문자열 파싱과 ``pg_input_is_valid`` 방어 cast를
    ``feature_notices.valid_end_time`` 비교로 대체했다(T-VN-06/F-9의 실패 모드
    자체가 소멸). alias를 그대로 반영하는지도 함께 고정한다.
    """
    for alias in ("f", "pf", "public_count_pf"):
        _assert_typed_notice_filter(
            feature_repo._ended_notice_hidden_sql(alias),
            alias,
            label=f"_ended_notice_hidden_sql({alias!r})",
        )
        _assert_typed_notice_filter(
            feature_repo.public_active_notice_filter_sql(alias),
            alias,
            label=f"public_active_notice_filter_sql({alias!r})",
        )
    # 기존 정적 상수(alias 'f')도 같은 계약을 담는다.
    _assert_typed_notice_filter(
        feature_repo._PUBLIC_ACTIVE_NOTICE_FILTER_SQL,
        "f",
        label="_PUBLIC_ACTIVE_NOTICE_FILTER_SQL",
    )


def test_every_composed_public_read_sql_embeds_typed_notice_filter() -> None:
    """_PUBLIC_ACTIVE_NOTICE_FILTER_SQL을 합성한 모든 공개 read 상수가 계약을 포함.

    미래에 특정 표면이 이 필터를 fork하며 감산을 빠뜨리거나(F-9 재발) 문자열
    파싱을 되살리면 fast-fail한다.
    """
    scalar_sql = {
        # T-VN-32B: identities SQL이 ids SQL을 대체(legacy id·UUID 쌍 반환).
        "_PUBLIC_ACTIVE_NOTICE_IDENTITIES_SQL": (
            feature_repo._PUBLIC_ACTIVE_NOTICE_IDENTITIES_SQL
        ),
        "_FEATURES_IN_BBOX_SQL": feature_repo._FEATURES_IN_BBOX_SQL,
        "_FEATURES_IN_BBOX_WITH_GEOMETRY_SQL": (
            feature_repo._FEATURES_IN_BBOX_WITH_GEOMETRY_SQL
        ),
        "_FEATURE_SEARCH_CTE_SQL": feature_repo._FEATURE_SEARCH_CTE_SQL,
        "_FEATURE_SEARCH_SCORE_CTE_SQL": feature_repo._FEATURE_SEARCH_SCORE_CTE_SQL,
        "_NEARBY_TARGET_CTE_SQL": feature_repo._NEARBY_TARGET_CTE_SQL,
        "_NEARBY_COORD_CTE_SQL": feature_repo._NEARBY_COORD_CTE_SQL,
        "_FEATURES_CONTAINED_IN_AREA_SQL": feature_repo._FEATURES_CONTAINED_IN_AREA_SQL,
        "_CATEGORY_FEATURE_COUNTS_SQL": feature_repo._CATEGORY_FEATURE_COUNTS_SQL,
    }
    for name, sql in scalar_sql.items():
        _assert_typed_notice_filter(sql, "f", label=name)
    # cluster는 unit별 3종을 dict로 조립 — 각 변형이 같은 계약을 담아야 한다.
    for unit, sql in feature_repo._CLUSTER_BBOX_SQL_BY_UNIT.items():
        _assert_typed_notice_filter(sql, "f", label=f"cluster SQL[{unit}]")


def test_curation_and_curated_route_through_shared_notice_filter() -> None:
    """#745가 확산한 curation/curated 공개 표면이 중앙 함수를 경유해 계약을 상속.

    각 repo의 합성 SQL 상수가 자신의 alias로 만든 typed 감산을 담고 있어야 한다 —
    naked cast를 다시 인라인하면 여기서 fast-fail한다.
    """
    from kortravelmap.infra import curated_repo, curation_repo

    # curation collection count(count_pf / public_count_pf)·item 필터(pf).
    _assert_typed_notice_filter(
        curation_repo._COLLECTION_COUNT_NOTICE_FILTER_SQL,
        "count_pf",
        label="_COLLECTION_COUNT_NOTICE_FILTER_SQL",
    )
    _assert_typed_notice_filter(
        curation_repo._COLLECTION_PUBLIC_COUNT_NOTICE_FILTER_SQL,
        "public_count_pf",
        label="_COLLECTION_PUBLIC_COUNT_NOTICE_FILTER_SQL",
    )
    _assert_typed_notice_filter(
        curation_repo._ITEM_PUBLIC_NOTICE_FILTER_SQL,
        "pf",
        label="_ITEM_PUBLIC_NOTICE_FILTER_SQL",
    )
    # curated feature 목록 공개 필터(f 별칭).
    _assert_typed_notice_filter(
        curated_repo._PUBLIC_FEATURE_FILTERS_SQL,
        "f",
        label="_PUBLIC_FEATURE_FILTERS_SQL",
    )


def test_nearby_cursor_round_trips_distance_name_and_updated_at() -> None:
    row = NearbyFeatureRow(
        feature_id="feature-1",
        kind="place",
        name="A first",
        category="06020000",
        status="active",
        lon=126.978,
        lat=37.5665,
        distance_m=12.5,
        primary_provider="python-opinet-api",
        primary_dataset_key="opinet_stations",
        last_updated_at=_NOW,
    )

    distance = feature_repo._encode_nearby_cursor(row, sort="distance")
    assert feature_repo._nearby_cursor_params(distance, sort="distance") == {
        "cursor_distance_m": 12.5,
        "cursor_name": None,
        "cursor_last_updated_at": None,
        "cursor_feature_id": "feature-1",
    }

    name = feature_repo._encode_nearby_cursor(row, sort="name")
    assert feature_repo._nearby_cursor_params(name, sort="name")[
        "cursor_name"
    ] == "A first"

    updated = feature_repo._encode_nearby_cursor(row, sort="last_updated_at")
    assert feature_repo._nearby_cursor_params(updated, sort="last_updated_at")[
        "cursor_last_updated_at"
    ] == _NOW


def test_nearby_cursor_rejects_malformed_or_wrong_sort() -> None:
    row = NearbyFeatureRow(
        feature_id="feature-1",
        kind="place",
        name="A first",
        category="06020000",
        status="active",
        lon=126.978,
        lat=37.5665,
        distance_m=12.5,
        primary_provider=None,
        primary_dataset_key=None,
        last_updated_at=_NOW,
    )
    cursor = feature_repo._encode_nearby_cursor(row, sort="distance")

    with pytest.raises(ValueError, match="invalid nearby cursor"):
        feature_repo._nearby_cursor_params("not-base64", sort="distance")
    with pytest.raises(ValueError, match="invalid nearby cursor"):
        feature_repo._nearby_cursor_params(cursor, sort="name")


def test_feature_search_cursor_round_trips_score_and_id_modes() -> None:
    row = FeatureSearchRow(
        feature_id="feature-1",
        kind="place",
        name="경복궁",
        category="01070100",
        lon=126.977,
        lat=37.5796,
        marker_icon="monument",
        marker_color="P-01",
        status="active",
        score=0.95,
        score_cursor="0.9500000476837158",
    )

    score_contract = feature_repo._feature_search_contract(
        q=" 경복궁 ",
        bbox=None,
        kinds=["place", "place"],
        categories=None,
        page_size=20,
        include_total=False,
    )
    score_cursor = feature_repo._encode_search_cursor(
        row,
        contract=score_contract,
        signing_key=_SEARCH_CURSOR_KEY,
    )
    assert feature_repo._search_cursor_params(
        score_cursor,
        contract=score_contract,
        signing_key=_SEARCH_CURSOR_KEY,
    ) == {
        "cursor_score": "0.9500000476837158",
        "cursor_feature_id": "feature-1",
    }

    id_contract = feature_repo._feature_search_contract(
        q=None,
        bbox=(126.0, 37.0, 128.0, 38.0),
        kinds=None,
        categories=["01070100"],
        page_size=20,
        include_total=False,
    )
    id_cursor = feature_repo._encode_search_cursor(
        row,
        contract=id_contract,
        signing_key=_SEARCH_CURSOR_KEY,
    )
    assert feature_repo._search_cursor_params(
        id_cursor,
        contract=id_contract,
        signing_key=_SEARCH_CURSOR_KEY,
    ) == {
        "cursor_score": None,
        "cursor_feature_id": "feature-1",
    }

    with pytest.raises(FeatureSearchCursorQueryMismatchError):
        feature_repo._search_cursor_params(
            score_cursor,
            contract=id_contract,
            signing_key=_SEARCH_CURSOR_KEY,
        )


def test_feature_search_cursor_fingerprint_uses_normalized_repository_contract() -> None:
    first = feature_repo._feature_search_contract(
        q="  경복궁  ",
        bbox=(126.0, 37.0, 128.0, 38.0),
        kinds=["event", "place", "event"],
        categories=["01070100", " 01070100 "],
        page_size=50,
        include_total=True,
    )
    second = feature_repo._feature_search_contract(
        q="경복궁",
        bbox=(126, 37, 128, 38),
        kinds=["place", "event"],
        categories=["01070100"],
        page_size=50,
        include_total=True,
    )
    assert first == second
    assert first.fingerprint == second.fingerprint
    cursor = feature_repo._encode_search_cursor(
        FeatureSearchRow(
            feature_id="feature-1",
            kind="place",
            name="경복궁",
            category="01070100",
            lon=126.977,
            lat=37.5796,
            marker_icon="monument",
            marker_color="P-01",
            status="active",
            score=0.95,
            score_cursor="0.9500000476837158",
        ),
        contract=first,
        signing_key=_SEARCH_CURSOR_KEY,
    )
    assert feature_repo._search_cursor_params(
        cursor,
        contract=second,
        signing_key=_SEARCH_CURSOR_KEY,
    )["cursor_feature_id"] == "feature-1"


def test_feature_search_cursor_rejects_tamper_unknown_version_and_query_reuse() -> None:
    contract = feature_repo._feature_search_contract(
        q="경복궁",
        bbox=None,
        kinds=["place"],
        categories=None,
        page_size=10,
        include_total=False,
    )
    row = FeatureSearchRow(
        feature_id="feature-1",
        kind="place",
        name="경복궁",
        category="01070100",
        lon=126.977,
        lat=37.5796,
        marker_icon="monument",
        marker_color="P-01",
        status="active",
        score=0.95,
        score_cursor="0.9500000476837158",
    )
    cursor = feature_repo._encode_search_cursor(
        row,
        contract=contract,
        signing_key=_SEARCH_CURSOR_KEY,
    )
    payload, signature = cursor.split(".")
    tampered_payload = ("A" if payload[0] != "A" else "B") + payload[1:]
    with pytest.raises(FeatureSearchCursorTamperedError):
        feature_repo._search_cursor_params(
            f"{tampered_payload}.{signature}",
            contract=contract,
            signing_key=_SEARCH_CURSOR_KEY,
        )
    tampered_signature = ("A" if signature[0] != "A" else "B") + signature[1:]
    with pytest.raises(FeatureSearchCursorTamperedError):
        feature_repo._search_cursor_params(
            f"{payload}.{tampered_signature}",
            contract=contract,
            signing_key=_SEARCH_CURSOR_KEY,
        )
    with pytest.raises(FeatureSearchCursorInvalidError):
        feature_repo._search_cursor_params(
            f"{payload}.{signature[:-2]}",
            contract=contract,
            signing_key=_SEARCH_CURSOR_KEY,
        )

    unknown_version = feature_repo._encode_search_cursor_payload(
        {
            "v": 999,
            "kind": "feature_search",
            "query": contract.fingerprint,
            "keyset": {
                "feature_id": "feature-1",
                "score": "0.9500000476837158",
            },
        },
        signing_key=_SEARCH_CURSOR_KEY,
    )
    with pytest.raises(FeatureSearchCursorVersionUnsupportedError):
        feature_repo._search_cursor_params(
            unknown_version,
            contract=contract,
            signing_key=_SEARCH_CURSOR_KEY,
        )

    changed_query = feature_repo._feature_search_contract(
        q="창덕궁",
        bbox=None,
        kinds=["place"],
        categories=None,
        page_size=10,
        include_total=False,
    )
    with pytest.raises(FeatureSearchCursorQueryMismatchError):
        feature_repo._search_cursor_params(
            cursor,
            contract=changed_query,
            signing_key=_SEARCH_CURSOR_KEY,
        )

    for invalid_payload in (
        {
            "v": 1,
            "kind": "other",
            "query": contract.fingerprint,
            "keyset": {
                "feature_id": "feature-1",
                "score": "0.9500000476837158",
            },
        },
        {
            "v": 1,
            "kind": "feature_search",
            "query": contract.fingerprint,
            "keyset": {"feature_id": "feature-1", "score": "NaN"},
        },
    ):
        invalid_cursor = feature_repo._encode_search_cursor_payload(
            invalid_payload,
            signing_key=_SEARCH_CURSOR_KEY,
        )
        with pytest.raises(FeatureSearchCursorInvalidError):
            feature_repo._search_cursor_params(
                invalid_cursor,
                contract=contract,
                signing_key=_SEARCH_CURSOR_KEY,
            )


@pytest.mark.parametrize(
    "cursor",
    [
        "not-a-token",
        "payload=.signature",
        "a" * 2049,
    ],
)
def test_feature_search_cursor_rejects_malformed_tokens(cursor: str) -> None:
    contract = feature_repo._feature_search_contract(
        q=None,
        bbox=(126.0, 37.0, 128.0, 38.0),
        kinds=None,
        categories=None,
        page_size=50,
        include_total=False,
    )
    with pytest.raises(FeatureSearchCursorInvalidError):
        feature_repo._search_cursor_params(
            cursor,
            contract=contract,
            signing_key=_SEARCH_CURSOR_KEY,
        )


@pytest.mark.asyncio
async def test_features_nearby_target_validates_before_db_call() -> None:
    class _Session:
        async def execute(self, *_args: object, **_kwargs: object) -> None:
            raise AssertionError("validation should happen before DB execute")

    with pytest.raises(ValueError, match="sort must be one of"):
        await feature_repo.features_nearby_poi_cache_target(
            _Session(),  # type: ignore[arg-type]
            target_id="target-1",
            sort="bad",
        )
    with pytest.raises(ValueError, match="radius_km must be greater than 0"):
        await feature_repo.features_nearby_poi_cache_target(
            _Session(),  # type: ignore[arg-type]
            target_id="target-1",
            radius_km=0,
        )
    with pytest.raises(ValueError, match="limit must be greater than 0"):
        await feature_repo.features_nearby_poi_cache_target(
            _Session(),  # type: ignore[arg-type]
            target_id="target-1",
            limit=0,
        )


@pytest.mark.asyncio
async def test_search_features_validates_before_db_call() -> None:
    class _Session:
        async def execute(self, *_args: object, **_kwargs: object) -> None:
            raise AssertionError("validation should happen before DB execute")

    with pytest.raises(ValueError, match="q 또는 bbox"):
        await feature_repo.search_features(  # type: ignore[arg-type]
            _Session(),
            cursor_signing_key=_SEARCH_CURSOR_KEY,
        )
    with pytest.raises(ValueError, match="signing key must be at least 32 bytes"):
        await feature_repo.search_features(  # type: ignore[arg-type]
            _Session(),
            q="경복궁",
            cursor_signing_key=b"short",
        )
    with pytest.raises(ValueError, match="page_size must be greater than 0"):
        await feature_repo.search_features(
            _Session(),  # type: ignore[arg-type]
            q="경복궁",
            page_size=0,
            cursor_signing_key=_SEARCH_CURSOR_KEY,
        )
    with pytest.raises(ValueError, match="invalid bbox"):
        await feature_repo.search_features(
            _Session(),  # type: ignore[arg-type]
            bbox=(127, 37, 126, 38),
            cursor_signing_key=_SEARCH_CURSOR_KEY,
        )
    contract = feature_repo._feature_search_contract(
        q="경복궁",
        bbox=None,
        kinds=None,
        categories=None,
        page_size=50,
        include_total=False,
    )
    cursor = feature_repo._encode_search_cursor(
        FeatureSearchRow(
            feature_id="feature-1",
            kind="place",
            name="경복궁",
            category="01070100",
            lon=126.977,
            lat=37.5796,
            marker_icon="monument",
            marker_color="P-01",
            status="active",
            score=0.95,
            score_cursor="0.9500000476837158",
        ),
        contract=contract,
        signing_key=_SEARCH_CURSOR_KEY,
    )
    with pytest.raises(FeatureSearchCursorQueryMismatchError):
        await feature_repo.search_features(  # type: ignore[arg-type]
            _Session(),
            q="창덕궁",
            cursor=cursor,
            cursor_signing_key=_SEARCH_CURSOR_KEY,
        )


@pytest.mark.asyncio
async def test_search_features_include_total_false_never_executes_count() -> None:
    class _Result:
        def mappings(self) -> _Result:
            return self

        def all(self) -> list[dict[str, object]]:
            return []

        def scalar_one(self) -> int:
            return 7

    class _Session:
        def __init__(self) -> None:
            self.statements: list[str] = []

        async def execute(self, statement: object, *_args: object, **_kwargs: object) -> _Result:
            self.statements.append(" ".join(str(statement).lower().split()))
            return _Result()

    without_total = _Session()
    page = await feature_repo.search_features(  # type: ignore[arg-type]
        without_total,
        bbox=(126.0, 37.0, 128.0, 38.0),
        include_total=False,
        cursor_signing_key=_SEARCH_CURSOR_KEY,
    )
    assert page.total_count is None
    assert not any("count(*)" in statement for statement in without_total.statements)

    with_total = _Session()
    counted_page = await feature_repo.search_features(  # type: ignore[arg-type]
        with_total,
        bbox=(126.0, 37.0, 128.0, 38.0),
        include_total=True,
        cursor_signing_key=_SEARCH_CURSOR_KEY,
    )
    assert counted_page.total_count == 7
    assert sum("count(*)" in statement for statement in with_total.statements) == 1
