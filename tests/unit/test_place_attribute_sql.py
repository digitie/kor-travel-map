"""장소 속성 필터·코드 fragment가 모든 읽기 경로에 들어 있는지 본다(ADR-121 §7.1).

속성은 source link에서 유도한다 — 필터 술어(``place_attribute_filter_sql``)와 코드 집계
(``place_attribute_codes_sql``)는 각각 한 곳에서만 만들고, 공개·admin 읽기 SQL이 그것을
품는다. 새 읽기 경로가 fragment 없이 생기면(혹은 기존 경로에서 빠지면) 여기서 빨개진다.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text

from kortravelmap.infra import admin_feature_repo, feature_repo

pytestmark = pytest.mark.unit

#: 필터 fragment의 표식 — 바인드 이름과 묶음 표. 둘 다 있어야 "공용 fragment"다.
_FILTER_MARKERS = ("CAST(:attributes AS text[]) IS NULL", "feature.dataset_place_attributes")
#: 코드 집계 fragment의 표식.
_CODES_MARKER = "AS attribute_codes"


def _filter_sql() -> dict[str, str]:
    """``attribute`` 필터를 받는 읽기 SQL 전부(공개 + admin)."""
    sql: dict[str, str] = {
        "_FEATURES_IN_BBOX_SQL": feature_repo._FEATURES_IN_BBOX_SQL,
        "_FEATURES_IN_BBOX_WITH_GEOMETRY_SQL": feature_repo._FEATURES_IN_BBOX_WITH_GEOMETRY_SQL,
        "_FEATURE_SEARCH_BY_ID_SQL": feature_repo._FEATURE_SEARCH_BY_ID_SQL,
        "_FEATURE_SEARCH_COUNT_SQL": feature_repo._FEATURE_SEARCH_COUNT_SQL,
        "_FEATURE_SEARCH_BY_SCORE_SQL": feature_repo._FEATURE_SEARCH_BY_SCORE_SQL,
        "_FEATURE_SEARCH_SCORE_COUNT_SQL": feature_repo._FEATURE_SEARCH_SCORE_COUNT_SQL,
        "_ADMIN_FEATURES_IN_BBOX_SQL": admin_feature_repo._ADMIN_FEATURES_IN_BBOX_SQL,
    }
    for key, (page, count) in feature_repo._FEATURE_SEARCH_REGION_SQL.items():
        sql[f"_FEATURE_SEARCH_REGION_SQL[{key}]"] = page
        sql[f"_FEATURE_SEARCH_REGION_SQL[{key}].count"] = count
    for sort, statement in feature_repo._NEARBY_SQL_BY_SORT.items():
        sql[f"_NEARBY_SQL_BY_SORT[{sort}]"] = statement
    for sort, statement in feature_repo._NEARBY_COORD_SQL_BY_SORT.items():
        sql[f"_NEARBY_COORD_SQL_BY_SORT[{sort}]"] = statement
    for unit, statement in feature_repo._CLUSTER_BBOX_SQL_BY_UNIT.items():
        sql[f"_CLUSTER_BBOX_SQL_BY_UNIT[{unit}]"] = statement
    for unit, statement in feature_repo._CLUSTER_BBOX_POINT_ONLY_SQL_BY_UNIT.items():
        sql[f"_CLUSTER_BBOX_POINT_ONLY_SQL_BY_UNIT[{unit}]"] = statement
    for unit, statement in admin_feature_repo._ADMIN_CLUSTER_BBOX_SQL_BY_UNIT.items():
        sql[f"_ADMIN_CLUSTER_BBOX_SQL_BY_UNIT[{unit}]"] = statement
    for sort in sorted(admin_feature_repo._ADMIN_FEATURE_SORT_COLUMNS):
        for order in ("asc", "desc"):
            sql[f"_admin_features_sql({sort},{order})"] = admin_feature_repo._admin_features_sql(
                sort=sort, order=order
            )
    return sql


def _codes_sql() -> dict[str, str]:
    """행마다 ``attribute_codes``를 싣는 page SQL 전부."""
    sql: dict[str, str] = {
        "_FEATURES_IN_BBOX_SQL": feature_repo._FEATURES_IN_BBOX_SQL,
        "_FEATURES_IN_BBOX_WITH_GEOMETRY_SQL": feature_repo._FEATURES_IN_BBOX_WITH_GEOMETRY_SQL,
        "_FEATURE_SEARCH_BY_ID_SQL": feature_repo._FEATURE_SEARCH_BY_ID_SQL,
        "_FEATURE_SEARCH_BY_SCORE_SQL": feature_repo._FEATURE_SEARCH_BY_SCORE_SQL,
        "_FEATURES_CONTAINED_IN_AREA_SQL": feature_repo._FEATURES_CONTAINED_IN_AREA_SQL,
        "_ADMIN_FEATURES_IN_BBOX_SQL": admin_feature_repo._ADMIN_FEATURES_IN_BBOX_SQL,
    }
    for key, (page, _count) in feature_repo._FEATURE_SEARCH_REGION_SQL.items():
        sql[f"_FEATURE_SEARCH_REGION_SQL[{key}]"] = page
    for sort, statement in feature_repo._NEARBY_SQL_BY_SORT.items():
        sql[f"_NEARBY_SQL_BY_SORT[{sort}]"] = statement
    for sort, statement in feature_repo._NEARBY_COORD_SQL_BY_SORT.items():
        sql[f"_NEARBY_COORD_SQL_BY_SORT[{sort}]"] = statement
    return sql


def test_every_attribute_filtered_read_embeds_the_shared_fragment() -> None:
    statements = _filter_sql()
    # 열거가 조용히 줄면(이름이 바뀌어 dict가 비면) 검사가 대상을 잃는다.
    assert len(statements) >= 30
    fragment = feature_repo.place_attribute_filter_sql("f")
    for name, sql in statements.items():
        for marker in _FILTER_MARKERS:
            assert marker in sql, f"{name}: 장소 속성 필터 fragment 누락({marker})"
        assert "attributes" in set(text(sql)._bindparams), name
    # fragment 자체도 다시 구현되지 않았는지 — 공개 bbox 경로는 정확히 그 문자열을 품는다.
    assert fragment in feature_repo._FEATURES_IN_BBOX_SQL
    # UNION 두 갈래(point·geometry arm)를 가진 SQL은 **갈래마다** 필터가 있어야 한다 — 표식이
    # 어딘가에 하나만 있어도 통과하던 검사는 한 갈래가 빠져도 초록이었다(적대 리뷰).
    two_arm = {
        **{f"cluster[{unit}]": sql for unit, sql in feature_repo._CLUSTER_BBOX_SQL_BY_UNIT.items()},
        **{
            f"admin_cluster[{unit}]": sql
            for unit, sql in admin_feature_repo._ADMIN_CLUSTER_BBOX_SQL_BY_UNIT.items()
        },
        "_ADMIN_FEATURES_IN_BBOX_SQL": admin_feature_repo._ADMIN_FEATURES_IN_BBOX_SQL,
    }
    for name, sql in two_arm.items():
        assert sql.count(_FILTER_MARKERS[0]) >= 2, f"{name}: 갈래 하나에 필터가 없다"


def test_every_page_read_carries_attribute_codes() -> None:
    public_codes = feature_repo.place_attribute_codes_sql("candidates")
    for name, sql in _codes_sql().items():
        assert _CODES_MARKER in sql, f"{name}: attribute_codes 열 누락"
        assert "feature.place_attributes AS attr_catalog" in sql, name
    # 공개 page는 공개 코드만, admin은 admin_only까지.
    assert "visibility = 'public'" in public_codes
    assert public_codes in feature_repo._FEATURE_SEARCH_BY_ID_SQL
    admin_codes = feature_repo.place_attribute_codes_sql("c", public_only=False)
    assert "visibility" not in admin_codes
    assert admin_codes in admin_feature_repo._ADMIN_FEATURES_IN_BBOX_SQL


def test_attribute_filter_uses_primary_and_enrichment_links_only() -> None:
    fragment = feature_repo.place_attribute_filter_sql("f")
    assert "attr_link.source_role IN ('primary', 'enrichment')" in fragment
    # 속성 쪽에서 출발하는 semi-join — 행마다 상관 anti-join을 돌지 않는다(적대 리뷰 High).
    assert "f.feature_id IN (" in fragment
    # AND 의미: 요청한 서로 다른 코드 수와 Feature가 가진 요청 코드 수가 같다.
    assert "HAVING count(DISTINCT attr_map.attribute_code)" in fragment
    assert "unnest(CAST(:attributes AS text[]))" in fragment


@pytest.mark.parametrize("alias", ["f; DROP", "1f", "f.x"])
def test_fragments_reject_non_identifier_alias(alias: str) -> None:
    with pytest.raises(ValueError, match="identifier"):
        feature_repo.place_attribute_filter_sql(alias)
    with pytest.raises(ValueError, match="identifier"):
        feature_repo.place_attribute_codes_sql(alias)


def test_search_cursor_fingerprint_ignores_absent_attributes() -> None:
    """속성 필터가 없으면 fingerprint가 종전과 같다 — 진행 중 cursor가 그대로 유효하다."""

    def _contract(attributes: list[str] | None) -> feature_repo._FeatureSearchContract:
        return feature_repo._feature_search_contract(
            q="카페",
            bbox=None,
            kinds=None,
            categories=None,
            page_size=20,
            include_total=False,
            attributes=attributes,
        )

    legacy = feature_repo._feature_search_contract(
        q="카페", bbox=None, kinds=None, categories=None, page_size=20, include_total=False
    )
    assert _contract(None).fingerprint == legacy.fingerprint
    assert _contract([]).fingerprint == legacy.fingerprint
    filtered = _contract(["pet_friendly", "barrier_free"])
    assert filtered.fingerprint != legacy.fingerprint
    # 순서·중복은 fingerprint를 바꾸지 않는다(정렬된 집합).
    reordered = _contract(["barrier_free", "pet_friendly", "barrier_free"])
    assert reordered.fingerprint == filtered.fingerprint
    assert feature_repo._SEARCH_CURSOR_VERSION == 9


def test_normalized_attributes_sorts_dedupes_and_short_circuits() -> None:
    assert feature_repo._normalized_attributes(None) is None
    assert feature_repo._normalized_attributes([]) is None
    assert feature_repo._normalized_attributes([" ", ""]) is None
    assert feature_repo._normalized_attributes(["b", "a", "b"]) == ["a", "b"]
