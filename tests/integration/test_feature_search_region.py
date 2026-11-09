"""``/v1/features/search`` 지역 검색·좌표 없는 행 숨김 통합 테스트(#1459 §4·§7).

2026-11-08 PinVi 여행 시나리오 검증에서 본 사례를 심는다(이름·분류·좌표는 prod 실측 모양).

- "강릉 호텔" — 1위가 대구 '밀독 호텔'이었다(지역 토큰을 쓰지 않는 trigram OR 매칭).
- "춘천 닭갈비" — 이름이 "춘천닭갈비"인 서울 식당이 춘천 닭갈비집보다 앞섰다.
- "대관령눈꽃축제" — 이름 일치 1위 행에 좌표가 없었다.

DB는 세션 내내 공유되므로 단언은 **여기서 심은 행들 사이의 순서**만 본다.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any
from uuid import NAMESPACE_URL, UUID, uuid5

import pytest
from sqlalchemy import text

from kortravelmap.infra import feature_repo
from tests.integration._subtype_seed import seed_feature_subtype

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.integration

_SEARCH_CURSOR_KEY = b"integration-feature-search-region-signing-key-0001"

# (시군구 코드, 시도 이름, 시군구 이름) — prod 2026-11-09 실측.
_GANGNEUNG = ("51150", "강원특별자치도", "강릉시")
_CHUNCHEON = ("51110", "강원특별자치도", "춘천시")
_DAEGU_JUNG = ("27110", "대구광역시", "중구")
_SEOUL_JONGNO = ("11110", "서울특별시", "종로구")
_PYEONGCHANG = ("51760", "강원특별자치도", "평창군")
_SEOUL_GANGSEO = ("11500", "서울특별시", "강서구")
_GIMPO = ("41570", "경기도", "김포시")


def _uuid(label: str) -> str:
    raw = bytearray(uuid5(NAMESPACE_URL, f"search-region:{label}").bytes)
    raw[6] = (raw[6] & 0x0F) | 0x70
    raw[8] = (raw[8] & 0x3F) | 0x80
    return str(UUID(bytes=bytes(raw)))


async def _feature(
    session: AsyncSession,
    label: str,
    *,
    name: str,
    category: str,
    region: tuple[str, str, str] | None,
    lon: float | None,
    lat: float | None,
    kind: str = "place",
) -> str:
    feature_id = _uuid(label)
    address: dict[str, Any] = {}
    sigungu_code = sido_code = None
    if region is not None:
        sigungu_code, sido_name, sigungu_name = region
        sido_code = sigungu_code[:2]
        address = {"sido_name": sido_name, "sigungu_name": sigungu_name}
    await session.execute(
        text(
            """
            INSERT INTO feature.features (
                feature_id, kind, name, category, coord, address, sido_code, sigungu_code,
                lifecycle_state, publication_state, quality_state
            )
            VALUES (
                CAST(:feature_id AS uuid), :kind, :name, :category,
                CASE WHEN CAST(:lon AS double precision) IS NULL THEN NULL
                ELSE x_extension.ST_SetSRID(
                    x_extension.ST_MakePoint(
                        CAST(:lon AS double precision), CAST(:lat AS double precision)
                    ),
                    4326
                ) END,
                CAST(:address AS jsonb), :sido_code, :sigungu_code,
                'active', 'published', 'valid'
            )
            """
        ),
        {
            "feature_id": feature_id,
            "kind": kind,
            "name": name,
            "category": category,
            "lon": lon,
            "lat": lat,
            "address": json.dumps(address, ensure_ascii=False),
            "sido_code": sido_code,
            "sigungu_code": sigungu_code,
        },
    )
    await seed_feature_subtype(session, feature_id=feature_id, kind=kind)
    return feature_id


async def _seed(session: AsyncSession) -> dict[str, str]:
    ids = {
        # 강릉 호텔
        "daegu_hotel": await _feature(
            session, "daegu_hotel", name="밀독 호텔", category="03010000",
            region=_DAEGU_JUNG, lon=128.5939, lat=35.8690,
        ),
        "gn_seamarq": await _feature(
            session, "gn_seamarq", name="씨마크 호텔", category="01000000",
            region=_GANGNEUNG, lon=128.9150, lat=37.7980,
        ),
        # 이름에 "호텔"이 없는 강릉의 호텔 분류 행 — 분류 팔로 찾는다.
        "gn_stjohns": await _feature(
            session, "gn_stjohns", name="세인트존스 경포", category="03010100",
            region=_GANGNEUNG, lon=128.9210, lat=37.7910,
        ),
        "gn_cityhall": await _feature(
            session, "gn_cityhall", name="강릉시청", category="01000000",
            region=_GANGNEUNG, lon=128.8760, lat=37.7520,
        ),
        # 춘천 닭갈비
        "seoul_dakgalbi": await _feature(
            session, "seoul_dakgalbi", name="춘천닭갈비", category="02010100",
            region=_SEOUL_JONGNO, lon=126.9850, lat=37.5700,
        ),
        "cc_dakgalbi": await _feature(
            session, "cc_dakgalbi", name="통나무집닭갈비", category="02010100",
            region=_CHUNCHEON, lon=127.7930, lat=37.9330,
        ),
        # 김포 공항 — 김포공항은 서울 강서구다(지역 이름이 이름의 일부인 목적지).
        "gimpo_airport": await _feature(
            session, "gimpo_airport", name="김포공항", category="06050000",
            region=_SEOUL_GANGSEO, lon=126.7960, lat=37.5580,
        ),
        "gimpo_noodle": await _feature(
            session, "gimpo_noodle", name="공항칼국수", category="02010100",
            region=_GIMPO, lon=126.7150, lat=37.6150,
        ),
        # 좌표 없는 축제(같은 이름의 좌표 있는 행과 함께).
        "snow_unplaced": await _feature(
            session, "snow_unplaced", name="대관령눈꽃축제", category="01090000",
            region=None, lon=None, lat=None, kind="event",
        ),
        "snow_placed": await _feature(
            session, "snow_placed", name="대관령 눈꽃축제", category="01090000",
            region=_PYEONGCHANG, lon=128.7170, lat=37.6770, kind="event",
        ),
    }
    await session.flush()
    return ids


async def _search_labels(
    session: AsyncSession,
    q: str,
    ids: dict[str, str],
    *,
    kinds: list[str] | None = None,
    page_size: int = 200,
) -> list[str]:
    by_id = {feature_id: label for label, feature_id in ids.items()}
    page = await feature_repo.search_features(
        session,
        q=q,
        kinds=kinds,
        page_size=page_size,
        cursor_signing_key=_SEARCH_CURSOR_KEY,
    )
    return [by_id[item.feature_id] for item in page.items if item.feature_id in by_id]


async def test_region_query_ranks_local_rows_and_category_matches_first(
    migrated_session: AsyncSession,
) -> None:
    ids = await _seed(migrated_session)
    labels = await _search_labels(migrated_session, "강릉 호텔", ids, kinds=["place"])
    # 강릉의 "호텔" 이름 행과 호텔 분류 행이 대구 호텔보다 앞이다. 강릉시청은 지역 안이지만
    # 나머지 검색어("호텔")와 맞지 않아 지역 일치가 아니다.
    assert labels[:2] == ["gn_seamarq", "gn_stjohns"], labels
    assert labels.index("gn_stjohns") < labels.index("daegu_hotel"), labels


async def test_region_query_beats_same_name_in_another_city(
    migrated_session: AsyncSession,
) -> None:
    ids = await _seed(migrated_session)
    labels = await _search_labels(migrated_session, "춘천 닭갈비", ids, kinds=["place"])
    assert labels.index("cc_dakgalbi") < labels.index("seoul_dakgalbi"), labels


async def test_region_query_keeps_a_destination_whose_full_name_is_the_query(
    migrated_session: AsyncSession,
) -> None:
    """이름이 검색어 전체와 같은 목적지는 지역 밖이어도 지역 일치 자리다(식음은 아니다)."""
    ids = await _seed(migrated_session)
    labels = await _search_labels(migrated_session, "김포 공항", ids, kinds=["place"])
    assert labels.index("gimpo_airport") < labels.index("gimpo_noodle"), labels


async def test_single_token_query_keeps_exact_name_behaviour(
    migrated_session: AsyncSession,
) -> None:
    ids = await _seed(migrated_session)
    labels = await _search_labels(migrated_session, "춘천닭갈비", ids, kinds=["place"])
    # 낱말 하나는 지역 해석을 하지 않는다 — 이름이 정확히 같은 서울 식당이 그대로 1위.
    assert labels[0] == "seoul_dakgalbi", labels


async def test_region_query_wide_scope_still_boosts_trigram_candidates(
    migrated_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """지역이 넓어 지역을 훑는 팔을 뺀 경우에도 trigram 후보 안에서 지역 순위가 산다."""
    ids = await _seed(migrated_session)
    monkeypatch.setattr(feature_repo, "_SEARCH_REGION_SCAN_MAX_ROWS", 0)
    labels = await _search_labels(migrated_session, "강릉 호텔", ids, kinds=["place"])
    assert labels.index("gn_seamarq") < labels.index("daegu_hotel"), labels


async def test_region_query_keyset_pagination_matches_single_page(
    migrated_session: AsyncSession,
) -> None:
    ids = await _seed(migrated_session)
    expected = [
        item.feature_id
        for item in (
            await feature_repo.search_features(
                migrated_session,
                q="강릉 호텔",
                page_size=200,
                cursor_signing_key=_SEARCH_CURSOR_KEY,
            )
        ).items
    ]
    walked: list[str] = []
    cursor: str | None = None
    for _ in range(len(expected) + 1):
        page = await feature_repo.search_features(
            migrated_session,
            q="강릉 호텔",
            page_size=1,
            cursor=cursor,
            cursor_signing_key=_SEARCH_CURSOR_KEY,
        )
        walked.extend(item.feature_id for item in page.items)
        cursor = page.next_cursor
        if cursor is None:
            break
    assert walked == expected
    assert {ids["gn_seamarq"], ids["gn_stjohns"]} <= set(walked)
    total = await feature_repo.search_features(
        migrated_session,
        q="강릉 호텔",
        page_size=1,
        include_total=True,
        cursor_signing_key=_SEARCH_CURSOR_KEY,
    )
    assert total.total_count == len(expected)


async def test_unplaced_rows_are_hidden_from_search(
    migrated_session: AsyncSession,
) -> None:
    ids = await _seed(migrated_session)
    labels = await _search_labels(migrated_session, "대관령눈꽃축제", ids)
    assert "snow_unplaced" not in labels, labels
    assert "snow_placed" in labels, labels


async def test_region_entries_sql_reads_names_per_sigungu_code(
    migrated_session: AsyncSession,
) -> None:
    await _seed(migrated_session)
    rows = (
        await migrated_session.execute(text(feature_repo._SEARCH_REGION_ENTRIES_SQL))
    ).mappings().all()
    seen = {(row["sigungu_code"], row["sido_name"], row["sigungu_name"]) for row in rows}
    assert {_GANGNEUNG, _CHUNCHEON, _DAEGU_JUNG} <= seen


async def test_region_search_sql_reads_the_region_arm_through_sigungu_index(
    migrated_session: AsyncSession,
) -> None:
    """지역 팔은 색인으로 읽힌다(strpos 팔은 ``idx_features_sigungu``) — features Seq Scan이면 빨강.

    ``enable_seqscan=off``는 금지가 아니라 벌점이다 — 인덱스로 받을 수 없는 술어면 계획에 Seq Scan이
    그대로 남는다. 그래서 "sigungu 색인을 쓴다"와 "features Seq Scan이 없다"를 함께 본다.
    """
    await _seed(migrated_session)
    await migrated_session.execute(text("SET LOCAL pg_trgm.similarity_threshold = 0.2"))
    await migrated_session.execute(text("SET LOCAL enable_seqscan = off"))
    for (name_mode, categories), (sql, _count) in feature_repo._FEATURE_SEARCH_REGION_SQL.items():
        if name_mode != "strpos" and not categories:
            continue  # 지역 팔이 sigungu 색인을 반드시 거치는 변형만(ilike는 trigram도 가능).
        params: dict[str, Any] = {
            "q": "강릉 호텔",
            "q_compact": "강릉호텔",
            "alias_name": None,
            "alias_compact": None,
            "bbox_enabled": False,
            "min_lon": None,
            "min_lat": None,
            "max_lon": None,
            "max_lat": None,
            "kinds": None,
            "categories": None,
            "cursor_rank": None,
            "cursor_score": None,
            "cursor_feature_id": None,
            "limit_plus_one": 21,
            "region_codes": ["51150"],
            "rem_compact": "호텔",
        }
        if name_mode == "ilike":
            params["rem_like"] = "%호텔%"
        if categories:
            params["rem_categories"] = ["03010000", "03010100"]
        explained = (
            await migrated_session.execute(text("EXPLAIN (FORMAT JSON) " + sql), params)
        ).scalar_one()
        nodes = _plan_nodes(explained[0]["Plan"])
        indexes = {node.get("Index Name") for node in nodes}
        seq_on_features = [
            node
            for node in nodes
            if node.get("Node Type") in {"Seq Scan", "Parallel Seq Scan"}
            and node.get("Relation Name") == "features"
        ]
        if name_mode == "strpos":
            # strpos 이름 팔은 GIN이 받지 않는다 — sigungu 색인이 유일한 색인 경로다.
            assert "idx_features_sigungu" in indexes, (name_mode, categories, indexes)
        assert not seq_on_features, (name_mode, categories, seq_on_features)
        assert "ST_Transform" not in sql


def _plan_nodes(plan: dict[str, Any]) -> list[dict[str, Any]]:
    nodes = [plan]
    for child in plan.get("Plans", []):
        nodes.extend(_plan_nodes(child))
    return nodes
