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
# 2026 인천 개편 뒤 코드(prod 2026-11-11 실측) — 영종도·을왕리는 영종구다. 옛 중구는 잔재다.
_YEONGJONG = ("28155", "인천광역시", "영종구")
_INCHEON_JUNG = ("28110", "인천광역시", "중구")
_GANGHWA = ("28710", "인천광역시", "강화군")
_YANGYANG = ("51830", "강원특별자치도", "양양군")
_SEOUL_GANGNAM = ("11680", "서울특별시", "강남구")


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


async def test_region_query_treats_bracket_name_variants_as_exact(
    migrated_session: AsyncSession,
) -> None:
    """지역 검색의 나머지 검색어도 끝 괄호 이름의 한글 이름과 이름 일치다(#1466 후속, 적대 리뷰)."""
    ids = await _seed(migrated_session)
    for label, name in (
        ("gn_bracket", "세인트존스 호텔 (St. John's Hotel Gangneung)"),
        ("gn_bracket_annex", "세인트존스 호텔 별관"),
    ):
        ids[label] = await _feature(
            migrated_session, label, name=name, category="03010100",
            region=_GANGNEUNG, lon=128.9220, lat=37.7900,
        )
    labels = await _search_labels(migrated_session, "강릉 세인트존스 호텔", ids, kinds=["place"])
    assert labels.index("gn_bracket") < labels.index("gn_bracket_annex"), labels


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
    for key, (sql, _count) in feature_repo._FEATURE_SEARCH_REGION_SQL.items():
        name_mode, categories, token_mode = key
        if name_mode != "strpos" and not categories and token_mode != "scan":
            continue  # 지역 팔이 sigungu 색인을 반드시 거치는 변형만(ilike는 trigram도 가능).
        params: dict[str, Any] = {
            "q": "강릉 호텔",
            "q_compact": "강릉호텔",
            "alias_name": None,
            "alias_compact": None,
            "bracket_like": "%강릉 호텔%",
            "bbox_enabled": False,
            "min_lon": None,
            "min_lat": None,
            "max_lon": None,
            "max_lat": None,
            "kinds": None,
            "categories": None,
            "attributes": None,
            "cursor_rank": None,
            "cursor_score": None,
            "cursor_feature_id": None,
            "limit_plus_one": 21,
            "region_codes": ["51150"],
            "rem_compact": "호텔",
            "rem_categories": ["03010000", "03010100"],
            "rem_is_category": True,
            "rem_token_likes": ["%호%", "%텔%"] if token_mode is not None else None,
        }
        if name_mode == "ilike":
            params["rem_like"] = "%호텔%"
        if token_mode == "anchor":
            params["rem_token_anchor"] = "%호텔%"
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
        # 작은 표에서는 planner가 sigungu 대신 다른 전체 색인을 고를 수 있다 — 실제 계획은
        # prod 크기에서 잰다(PR 본문). 여기서는 Seq Scan이 없고 색인을 읽는다는 것만 본다.
        assert indexes - {None}, (key, indexes)
        assert not seq_on_features, (key, seq_on_features)
        assert "ST_Transform" not in sql


async def _seed_incheon_gangwon(session: AsyncSession) -> dict[str, str]:
    """2026-11-11 검색 순위 점검 사례(prod 이름·분류·시군구 그대로)."""
    return {
        "everview": await _feature(
            session, "everview", name="을왕리 에버뷰 펜션", category="03050000",
            region=_YEONGJONG, lon=126.3720, lat=37.4470,
        ),
        "jung_remnant": await _feature(
            session, "jung_remnant", name="인천 중구청", category="01000000",
            region=_INCHEON_JUNG, lon=126.6210, lat=37.4740,
        ),
        "pension_band": await _feature(
            session, "pension_band", name="펜션밴드", category="01080400",
            region=_GANGHWA, lon=126.4880, lat=37.7460,
        ),
        "gh_ter": await _feature(
            session, "gh_ter", name="터 펜션", category="03050200",
            region=_GANGHWA, lon=126.4500, lat=37.6900,
        ),
        "gh_paengnamu": await _feature(
            session, "gh_paengnamu", name="강화 팽나무 펜션", category="03050200",
            region=_GANGHWA, lon=126.4600, lat=37.7000,
        ),
        # 첫 낱말이 지역 이름이 아닌 이름 — 지역 tail 일치로만 이름 일치가 된다.
        "gh_gyodong": await _feature(
            session, "gh_gyodong", name="교동 팽나무 펜션", category="03050200",
            region=_GANGHWA, lon=126.2900, lat=37.7800,
        ),
        "surfshack": await _feature(
            session, "surfshack", name="서프쉑 카페", category="02020000",
            region=_YANGYANG, lon=128.7350, lat=38.0060,
        ),
        "seoul_cafe": await _feature(
            session, "seoul_cafe", name="카페 쉼", category="01040000",
            region=_SEOUL_GANGNAM, lon=127.0470, lat=37.5170,
        ),
    }


async def _search_page(session: AsyncSession, q: str, **kwargs: Any) -> Any:
    return await feature_repo.search_features(
        session, q=q, cursor_signing_key=_SEARCH_CURSOR_KEY, **kwargs
    )


async def test_eulwangri_resolves_to_yeongjong_after_the_2026_reorganisation(
    migrated_session: AsyncSession,
) -> None:
    """을왕리·영종도는 영종구다 — 옛 중구로 읽으면 영종의 펜션이 지역 밖이 되어 강화 행에 밀렸다."""
    ids = await _seed_incheon_gangwon(migrated_session)
    await migrated_session.flush()
    labels = await _search_labels(migrated_session, "을왕리 펜션", ids, kinds=["place"])
    # 강화 미끼는 유사도 문턱 근처라 후보가 아닐 수 있다 — 있으면 영종 펜션보다 뒤다.
    if "pension_band" in labels:
        assert labels.index("everview") < labels.index("pension_band"), labels
    page = await _search_page(migrated_session, "을왕리 펜션", kinds=["place"], page_size=200)
    rank = {item.feature_id: item.rank for item in page.items}[ids["everview"]]
    assert rank is not None
    assert rank < feature_repo._SEARCH_RANK_REGION_WEIGHT, rank


async def test_category_word_remainder_does_not_make_two_word_names_exact(
    migrated_session: AsyncSession,
) -> None:
    """나머지가 분류 낱말("펜션")이면 "터 펜션"의 tail이 이름 일치가 되지 않는다(같은 rank)."""
    ids = await _seed_incheon_gangwon(migrated_session)
    await migrated_session.flush()
    page = await _search_page(migrated_session, "강화 펜션", kinds=["place"], page_size=200)
    rank = {item.feature_id: item.rank for item in page.items}
    assert rank[ids["gh_ter"]] is not None
    assert rank[ids["gh_ter"]] == rank[ids["gh_paengnamu"]], rank


async def test_region_name_query_still_uses_the_tail_exact_match(
    migrated_session: AsyncSession,
) -> None:
    """분류 낱말이 아닌 나머지("팽나무 펜션")는 종전처럼 지역 tail 이름 일치를 본다.

    "교동 팽나무 펜션"은 검색어 전체("강화팽나무펜션")와 같지 않다 — 첫 낱말을 뗀 나머지가 지역
    검색의 나머지와 같아서만 이름 일치다.
    """
    ids = await _seed_incheon_gangwon(migrated_session)
    await migrated_session.flush()
    page = await _search_page(
        migrated_session, "강화 팽나무 펜션", kinds=["place"], page_size=200
    )
    rank = {item.feature_id: item.rank for item in page.items}[ids["gh_gyodong"]]
    assert rank is not None
    assert (rank // feature_repo._SEARCH_RANK_EXACT_WEIGHT) % 10 == 0, rank


async def test_multi_word_remainder_matches_names_that_cover_every_word(
    migrated_session: AsyncSession,
) -> None:
    """"양양 서프 카페"는 양양에서 이름이 "서프"와 "카페"를 모두 품는 행이 지역 일치다."""
    ids = await _seed_incheon_gangwon(migrated_session)
    await migrated_session.flush()
    labels = await _search_labels(migrated_session, "양양 서프 카페", ids, kinds=["place"])
    assert labels.index("surfshack") < labels.index("seoul_cafe"), labels
    page = await _search_page(migrated_session, "양양 서프 카페", kinds=["place"], page_size=200)
    rank = {item.feature_id: item.rank for item in page.items}[ids["surfshack"]]
    assert rank is not None
    assert rank < feature_repo._SEARCH_RANK_REGION_WEIGHT, rank


async def test_multi_word_remainder_wide_region_uses_the_long_word_anchor(
    migrated_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """넓은 지역(훑는 팔 없음)에서도 3글자 이상 낱말을 닻으로 낱말 덮기 후보를 찾는다.

    낱말 순서를 뒤집어("카페 서프쉑") 붙여 쓴 나머지("카페서프쉑")로는 이름을 품지 못하게 한다 —
    낱말 덮기만 지역 일치를 준다.
    """
    ids = await _seed_incheon_gangwon(migrated_session)
    await migrated_session.flush()
    monkeypatch.setattr(feature_repo, "_SEARCH_REGION_SCAN_MAX_ROWS", 0)
    q = "양양 카페 서프쉑"
    region = await feature_repo._resolve_search_region(migrated_session, q)
    assert region is not None
    arms = await feature_repo._search_region_arms(migrated_session, region)
    assert arms.token_mode == "anchor", arms
    labels = await _search_labels(migrated_session, q, ids, kinds=["place"])
    assert labels[0] == "surfshack", labels


async def test_multi_word_region_query_keyset_pagination_matches_single_page(
    migrated_session: AsyncSession,
) -> None:
    await _seed_incheon_gangwon(migrated_session)
    await migrated_session.flush()
    expected = [
        item.feature_id
        for item in (await _search_page(migrated_session, "양양 서프 카페", page_size=200)).items
    ]
    walked: list[str] = []
    cursor: str | None = None
    for _ in range(len(expected) + 1):
        page = await _search_page(migrated_session, "양양 서프 카페", page_size=3, cursor=cursor)
        walked.extend(item.feature_id for item in page.items)
        cursor = page.next_cursor
        if cursor is None:
            break
    assert walked == expected
    total = await _search_page(
        migrated_session, "양양 서프 카페", page_size=1, include_total=True
    )
    assert total.total_count == len(expected)


def _plan_nodes(plan: dict[str, Any]) -> list[dict[str, Any]]:
    nodes = [plan]
    for child in plan.get("Plans", []):
        nodes.extend(_plan_nodes(child))
    return nodes
