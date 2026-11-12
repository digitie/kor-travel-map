"""``/v1/features/search`` 실효 검색 그룹(P4)·중복 접기(P5) 통합 테스트(2026-11-11 검색 순위 점검).

- P4: 관광(``01``)으로 저장된 펜션·식당 행은 이름 끝말이 숙박·식음이면 그 그룹으로 순위를 받는다
  (저장 분류는 그대로).
- P5: 같은 이름(공백·대소문자·끝 괄호 무시)의 place가 300 m 안에 여럿이면 정렬 순서가 가장 앞인 행
  하나만 낸다. 숨김은 후보 전체에서 정하므로 keyset 페이지와 개수 질의가 그대로 맞는다.

DB는 세션 내내 공유되므로 단언은 **여기서 심은 행들 사이의 관계**만 본다(이름은 이 파일 고유).
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any
from uuid import NAMESPACE_URL, UUID, uuid5

import pytest
from sqlalchemy import text

from kortravelmap.category import search_effective_group
from kortravelmap.infra import feature_repo
from tests.integration._subtype_seed import seed_feature_subtype

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.integration

_SEARCH_CURSOR_KEY = b"integration-feature-search-dedup-signing-key-00001"
_YEOJU = ("41670", "경기도", "여주시")
_GANGHWA = ("28710", "인천광역시", "강화군")
_SOKCHO = ("51210", "강원특별자치도", "속초시")

#: 1 m ≈ 위도 0.000009도.
_M = 0.000009


def _uuid(label: str) -> str:
    raw = bytearray(uuid5(NAMESPACE_URL, f"search-dedup:{label}").bytes)
    raw[6] = (raw[6] & 0x0F) | 0x70
    raw[8] = (raw[8] & 0x3F) | 0x80
    return str(UUID(bytes=bytes(raw)))


async def _feature(
    session: AsyncSession,
    label: str,
    *,
    name: str,
    category: str,
    region: tuple[str, str, str],
    lon: float,
    lat: float,
    kind: str = "place",
    provider: tuple[str, str] | None = None,
) -> str:
    feature_id = _uuid(label)
    sigungu_code, sido_name, sigungu_name = region
    await session.execute(
        text(
            """
            INSERT INTO feature.features (
                feature_id, kind, name, category, coord, address, sido_code, sigungu_code,
                lifecycle_state, publication_state, quality_state
            )
            VALUES (
                CAST(:feature_id AS uuid), :kind, :name, :category,
                x_extension.ST_SetSRID(
                    x_extension.ST_MakePoint(
                        CAST(:lon AS double precision), CAST(:lat AS double precision)
                    ),
                    4326
                ),
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
            "address": json.dumps(
                {"sido_name": sido_name, "sigungu_name": sigungu_name}, ensure_ascii=False
            ),
            "sido_code": sigungu_code[:2],
            "sigungu_code": sigungu_code,
        },
    )
    await seed_feature_subtype(session, feature_id=feature_id, kind=kind)
    if provider is not None:
        await _primary_link(session, feature_id, label, provider)
    return feature_id


async def _primary_link(
    session: AsyncSession,
    feature_id: str,
    label: str,
    provider: tuple[str, str],
    *,
    role: str = "primary",
) -> None:
    """Feature에 source link 하나(기본 ``primary``) — 접기 대표의 원천 판정용."""
    dataset_id = (
        await session.execute(
            text(
                """
                INSERT INTO provider_sync.provider_datasets (
                    provider, dataset_key, display_name, source_kind, is_active, capabilities
                )
                SELECT :provider, :dataset_key, :provider, 'system', true,
                       jsonb_build_object('schema_version', 1,
                                          'produces', '[]'::jsonb,
                                          'extensions', '{}'::jsonb)
                ON CONFLICT (provider, dataset_key) DO UPDATE
                    SET display_name = EXCLUDED.display_name
                RETURNING provider_dataset_id
                """
            ),
            {"provider": provider[0], "dataset_key": provider[1]},
        )
    ).scalar_one()
    entity_key = f"search-dedup-{label}-{role}"
    await session.execute(
        text(
            """
            INSERT INTO provider_sync.source_entities (
                source_entity_key, provider_dataset_id, source_entity_type,
                source_entity_id, first_seen_at, last_seen_at
            )
            VALUES (:key, :dataset_id, 'place', :key, now(), now())
            """
        ),
        {"key": entity_key, "dataset_id": dataset_id},
    )
    await session.execute(
        text(
            """
            INSERT INTO provider_sync.source_links (
                feature_id, source_entity_key, source_role, match_method, confidence
            )
            VALUES (CAST(:feature_id AS uuid), :key, :role, 'exact', 100)
            """
        ),
        {"feature_id": feature_id, "key": entity_key, "role": role},
    )


_MOIS = ("python-mois-api", "mois_license_features_bulk")
_MCST_FAMOUS = ("python-mcst-api", "mcst_media_famous_places_csv")
_MCST_LEISURE = ("python-mcst-api", "mcst_leisure_activity_facilities_csv")
_SEOCHO = ("11650", "서울특별시", "서초구")
_YONGSAN = ("11170", "서울특별시", "용산구")
_SEOUL_JUNG = ("11140", "서울특별시", "중구")


async def _seed(session: AsyncSession) -> dict[str, str]:
    lon, lat = 127.6510, 37.2990  # 여주 신륵사 근처
    ids = {
        # 같은 장소를 원천 넷이 따로 적재 — TourAPI 하위 분류 1, MCST Tier 1만 2(가까이), 끝 괄호 1.
        "silleuk_tour": await _feature(
            session, "silleuk_tour", name="신륵사접기관광지", category="01020100",
            region=_YEOJU, lon=lon, lat=lat,
        ),
        "silleuk_mcst_a": await _feature(
            session, "silleuk_mcst_a", name="신륵사접기관광지", category="01000000",
            region=_YEOJU, lon=lon + 40 * _M, lat=lat,
        ),
        "silleuk_mcst_b": await _feature(
            session, "silleuk_mcst_b", name="신륵사 접기관광지", category="01000000",
            region=_YEOJU, lon=lon, lat=lat + 120 * _M,
        ),
        "silleuk_bracket": await _feature(
            session, "silleuk_bracket", name="신륵사접기관광지(여주)", category="01000000",
            region=_YEOJU, lon=lon - 60 * _M, lat=lat,
        ),
        # 같은 이름이지만 5 km 떨어진 다른 곳 — 접지 않는다.
        "silleuk_far": await _feature(
            session, "silleuk_far", name="신륵사접기관광지", category="01000000",
            region=_YEOJU, lon=lon + 0.06, lat=lat,
        ),
        # 같은 이름의 축제(event) — kind가 다르면 접지 않는다.
        "silleuk_event": await _feature(
            session, "silleuk_event", name="신륵사접기관광지", category="01090000",
            region=_YEOJU, lon=lon, lat=lat, kind="event",
        ),
        # 주차장은 같은 이름이 가까이 여럿이어도 접지 않는다.
        "parking_a": await _feature(
            session, "parking_a", name="신륵사접기 공영주차장", category="06010000",
            region=_YEOJU, lon=lon + 10 * _M, lat=lat + 10 * _M,
        ),
        "parking_b": await _feature(
            session, "parking_b", name="신륵사접기 공영주차장", category="06010000",
            region=_YEOJU, lon=lon + 50 * _M, lat=lat + 50 * _M,
        ),
    }
    await session.flush()
    return ids


async def _page(session: AsyncSession, q: str, **kwargs: Any) -> Any:
    return await feature_repo.search_features(
        session, q=q, cursor_signing_key=_SEARCH_CURSOR_KEY, **kwargs
    )


async def test_duplicates_within_radius_collapse_to_the_best_ranked_row(
    migrated_session: AsyncSession,
) -> None:
    ids = await _seed(migrated_session)
    page = await _page(migrated_session, "신륵사접기관광지", page_size=200)
    seen = {item.feature_id for item in page.items}
    # 하위 분류가 있는 TourAPI 행이 대표다(분류 구체성 자리가 앞).
    assert ids["silleuk_tour"] in seen
    for hidden in ("silleuk_mcst_a", "silleuk_mcst_b", "silleuk_bracket"):
        assert ids[hidden] not in seen, hidden
    assert ids["silleuk_far"] in seen
    assert ids["silleuk_event"] in seen


async def test_parking_rows_are_never_collapsed(migrated_session: AsyncSession) -> None:
    ids = await _seed(migrated_session)
    page = await _page(migrated_session, "신륵사접기 공영주차장", page_size=200)
    seen = {item.feature_id for item in page.items}
    assert {ids["parking_a"], ids["parking_b"]} <= seen


async def test_rest_area_directions_are_never_collapsed(migrated_session: AsyncSession) -> None:
    """휴게소 상·하행은 끝 괄호만 다른 같은 이름이고 가깝다 — 교통 분류는 접지 않는다."""
    up = await _feature(
        migrated_session, "rest_up", name="덕평접기휴게소(서울방향)", category="06040101",
        region=_YEOJU, lon=127.4000, lat=37.2400,
    )
    down = await _feature(
        migrated_session, "rest_down", name="덕평접기휴게소(부산방향)", category="06040101",
        region=_YEOJU, lon=127.4000 + 100 * _M, lat=37.2400,
    )
    await migrated_session.flush()
    page = await _page(migrated_session, "덕평접기휴게소", page_size=200)
    assert {up, down} <= {item.feature_id for item in page.items}


async def test_duplicates_chain_into_one_cluster_and_far_cities_keep_their_own(
    migrated_session: AsyncSession,
) -> None:
    """이웃의 이웃도 같은 무리다(A–B 250 m, B–C 200 m → 하나). 대표와 먼 다른 도시의 같은 이름
    무리도 그 안에서 하나로 접힌다."""
    lon, lat = 127.0500, 37.5000
    ids = {
        "a": await _feature(
            migrated_session, "chain_a", name="이음접기공원", category="01050200",
            region=_YEOJU, lon=lon, lat=lat,
        ),
        "b": await _feature(
            migrated_session, "chain_b", name="이음접기공원", category="01000000",
            region=_YEOJU, lon=lon, lat=lat + 250 * _M,
        ),
        "c": await _feature(
            migrated_session, "chain_c", name="이음접기공원", category="01000000",
            region=_YEOJU, lon=lon, lat=lat + 450 * _M,
        ),
        # 다른 도시(약 50 km)의 같은 이름 둘 — 서로 50 m.
        "far_1": await _feature(
            migrated_session, "chain_far_1", name="이음접기공원", category="01000000",
            region=_SOKCHO, lon=lon + 0.5, lat=lat,
        ),
        "far_2": await _feature(
            migrated_session, "chain_far_2", name="이음접기 공원", category="01000000",
            region=_SOKCHO, lon=lon + 0.5 + 50 * _M, lat=lat,
        ),
    }
    await migrated_session.flush()
    page = await _page(migrated_session, "이음접기공원", page_size=200)
    seen = {item.feature_id for item in page.items}
    assert ids["a"] in seen
    assert not {ids["b"], ids["c"]} & seen
    assert len({ids["far_1"], ids["far_2"]} & seen) == 1


async def test_collapse_keeps_keyset_pages_and_total_consistent(
    migrated_session: AsyncSession,
) -> None:
    """page_size 1로 걸어도 한 페이지 결과와 같고, 숨긴 행은 어느 페이지에도 나오지 않는다."""
    ids = await _seed(migrated_session)
    q = "신륵사접기관광지"
    expected = [item.feature_id for item in (await _page(migrated_session, q, page_size=200)).items]
    walked: list[str] = []
    cursor: str | None = None
    for _ in range(len(expected) + 1):
        page = await _page(migrated_session, q, page_size=1, cursor=cursor)
        walked.extend(item.feature_id for item in page.items)
        cursor = page.next_cursor
        if cursor is None:
            break
    assert walked == expected
    assert len(walked) == len(set(walked))
    assert not {ids["silleuk_mcst_a"], ids["silleuk_mcst_b"]} & set(walked)
    total = await _page(migrated_session, q, page_size=1, include_total=True)
    assert total.total_count == len(expected)


async def test_collapse_is_stable_when_the_representative_moves_pages(
    migrated_session: AsyncSession,
) -> None:
    """두 페이지에 걸친 경계에서도(cursor가 대표 행 바로 뒤) 숨긴 행이 다시 나오지 않는다."""
    ids = await _seed(migrated_session)
    q = "신륵사접기관광지"
    seen: list[str] = []
    cursor: str | None = None
    for _ in range(100):
        page = await _page(migrated_session, q, page_size=2, cursor=cursor)
        seen.extend(item.feature_id for item in page.items)
        cursor = page.next_cursor
        if cursor is None:
            break
    assert len(seen) == len(set(seen))
    assert ids["silleuk_bracket"] not in seen


async def test_tourism_coded_lodging_ranks_with_lodging_not_tourism(
    migrated_session: AsyncSession,
) -> None:
    """MCST가 관광(01)으로 넣은 "…펜션"은 숙박 그룹이다 — 관광지 이름 행보다 앞서지 않는다."""
    base_lon, base_lat = 126.4880, 37.7460
    ids = {
        "mcst_pension": await _feature(
            migrated_session, "mcst_pension", name="저어새접기펜션", category="01000000",
            region=_GANGHWA, lon=base_lon, lat=base_lat,
        ),
        "real_pension": await _feature(
            migrated_session, "real_pension", name="저어새접기 바다펜션", category="03050200",
            region=_GANGHWA, lon=base_lon + 0.02, lat=base_lat,
        ),
        "tour_spot": await _feature(
            migrated_session, "tour_spot", name="저어새접기 생태공원", category="01050200",
            region=_GANGHWA, lon=base_lon + 0.04, lat=base_lat,
        ),
    }
    await migrated_session.flush()
    page = await _page(migrated_session, "저어새접기", kinds=["place"], page_size=200)
    rank = {item.feature_id: item.rank for item in page.items}
    group = feature_repo._SEARCH_RANK_GROUP_WEIGHT
    digit = feature_repo._SEARCH_RANK_DIGIT_MAX + 1
    mcst_rank, real_rank, tour_rank = (
        rank[ids["mcst_pension"]], rank[ids["real_pension"]], rank[ids["tour_spot"]],
    )
    assert mcst_rank is not None
    assert real_rank is not None
    assert tour_rank is not None
    # 실효 그룹 자리: MCST 펜션 = 숙박(1) = 진짜 펜션, 관광지 = 0.
    assert (mcst_rank // group) % digit == 1, mcst_rank
    assert (real_rank // group) % digit == 1, real_rank
    assert (tour_rank // group) % digit == 0, tour_rank
    # 저장 분류는 그대로다.
    stored = (
        await migrated_session.execute(
            text("SELECT category FROM feature.features WHERE feature_id = CAST(:id AS uuid)"),
            {"id": ids["mcst_pension"]},
        )
    ).scalar_one()
    assert stored == "01000000"


async def test_branch_shop_named_after_a_market_does_not_jump_the_market(
    migrated_session: AsyncSession,
) -> None:
    """"속초 중앙시장" — 관광으로 넣은 "…중앙시장점" 지점이 전통시장보다 앞서지 않는다."""
    ids = {
        "branch": await _feature(
            migrated_session, "branch", name="만석접기닭강정 중앙시장점", category="01000000",
            region=_SOKCHO, lon=128.5900, lat=38.2040,
        ),
        "market": await _feature(
            migrated_session, "market", name="속초접기종합중앙시장", category="05070000",
            region=_SOKCHO, lon=128.5910, lat=38.2050,
        ),
    }
    await migrated_session.flush()
    page = await _page(migrated_session, "속초 중앙시장", kinds=["place"], page_size=200)
    order = [item.feature_id for item in page.items]
    assert order.index(ids["market"]) < order.index(ids["branch"]), order


async def test_effective_group_sql_matches_core_function(
    migrated_session: AsyncSession,
) -> None:
    cases = [
        ("01000000", "저어새펜션"),
        ("01080400", "신선지어깨동무펜션"),
        ("01000000", "강화 펜션 (강화)"),
        ("01000000", "호야막창"),
        ("01000000", "만석닭강정 중앙시장점"),
        ("01000000", "춘천 명동 닭갈비 골목"),
        ("01000000", "올레 1코스 시작점"),
        ("00000000", "하늘 민박"),
        ("02010100", "호미곶 펜션"),
        ("05070000", "자갈치 회센터 본점"),
        ("03050200", "호미곶민박"),
        ("01000000", "펜션밴드"),
    ]
    effective = feature_repo._search_effective_group_sql(
        "category_search_group", "category", "compact_name"
    )
    base = feature_repo._search_category_group_sql("v.category")
    # 비교 키는 검색 SQL과 같은 ``_search_compact_sql``로 원래 이름에서 만든다(Python
    # ``str.isspace``와 SQL 공백 집합의 대조 — NBSP·전각 공백 포함).
    compact = feature_repo._search_compact_sql("v.name")
    statement = text(
        f"SELECT {effective} FROM ("
        f"SELECT v.category, {compact} AS compact_name, {base} AS category_search_group FROM ("
        "SELECT CAST(:category AS text) AS category, CAST(:name AS text) AS name"
        ") AS v) AS w"
    )
    cases += [
        ("01000000", "저어새" + chr(0xA0) + "펜션"),
        ("01000000", "남대문" + chr(0x3000) + "전주식당"),
        ("01000000", "신선지 펜션（강화）"),
    ]
    for category, name in cases:
        got = (
            await migrated_session.execute(statement, {"category": category, "name": name})
        ).scalar_one()
        assert got == search_effective_group(category, name), (category, name, got)


async def test_search_turns_jit_off_for_its_transaction(migrated_session: AsyncSession) -> None:
    """검색은 JIT 컴파일이 실행보다 비싸다(prod "부산 맛집" 7.6 s 중 7.2 s).

    이 transaction에서만 끈다.
    """
    await migrated_session.execute(text("SET LOCAL jit = on"))
    await _page(migrated_session, "신륵사접기관광지", page_size=8)
    assert (await migrated_session.execute(text("SHOW jit"))).scalar_one() == "off"


async def test_fold_representative_is_the_specific_non_mcst_row(
    migrated_session: AsyncSession,
) -> None:
    """prod 2026-11-12 회귀: MOIS 숙박 행(03010100)이 같은 자리 MCST 촬영지 행(01000000)에 접혀
    "JW 메리어트 서울"·"그랜드 하얏트 서울"이 관광지로 보였다. 대표는 구체 분류·비MCST
    행이고, 무리의 가장 좋은 자리를 물려받는다."""
    pairs = {
        "jw": (
            ("JW메리어트호텔접기서울", "03010100", _MOIS, 127.00362, 37.50436, _SEOCHO),
            ("JW 메리어트 호텔접기 서울", "01000000", _MCST_FAMOUS, 127.00360, 37.50434, _SEOCHO),
        ),
        "hyatt": (
            ("그랜드하얏트접기서울", "03010100", _MOIS, 126.99781, 37.53954, _YONGSAN),
            ("그랜드하얏트접기 서울", "01000000", _MCST_FAMOUS, 126.99715, 37.53935, _YONGSAN),
        ),
    }
    for key, (mois, mcst) in pairs.items():
        mois_id = await _feature(
            migrated_session, f"{key}_mois", name=mois[0], category=mois[1],
            region=mois[5], lon=mois[3], lat=mois[4], provider=mois[2],
        )
        mcst_id = await _feature(
            migrated_session, f"{key}_mcst", name=mcst[0], category=mcst[1],
            region=mcst[5], lon=mcst[3], lat=mcst[4], provider=mcst[2],
        )
        await migrated_session.flush()
        q = mcst[0]
        page = await _page(migrated_session, q, kinds=["place"], page_size=200)
        by_id = {item.feature_id: item for item in page.items}
        assert mois_id in by_id, (key, [i.name for i in page.items])
        assert mcst_id not in by_id, key
        assert by_id[mois_id].category == "03010100"
        # 대표는 무리의 가장 좋은 자리를 받는다 — MCST 행 혼자일 때(관광 그룹 0)와 같은 자리다.
        hidden_alone = await _page(
            migrated_session, q, kinds=["place"], categories=["01000000"], page_size=200
        )
        alone_rank = {item.feature_id: item.rank for item in hidden_alone.items}[mcst_id]
        assert by_id[mois_id].rank == alone_rank, (key, by_id[mois_id].rank, alone_rank)


async def test_fold_prefers_non_mcst_when_both_rows_are_specific(
    migrated_session: AsyncSession,
) -> None:
    """둘 다 하위 분류가 있어도 MCST 목록 행(레저 01080400)보다 MOIS 숙박 행이 대표다."""
    mois_id = await _feature(
        migrated_session, "leisure_mois", name="한강접기리조트", category="03020000",
        region=_YONGSAN, lon=126.9900, lat=37.5300, provider=_MOIS,
    )
    mcst_id = await _feature(
        migrated_session, "leisure_mcst", name="한강접기 리조트", category="01080400",
        region=_YONGSAN, lon=126.9901, lat=37.5300, provider=_MCST_LEISURE,
    )
    await migrated_session.flush()
    page = await _page(migrated_session, "한강접기리조트", kinds=["place"], page_size=200)
    seen = {item.feature_id for item in page.items}
    assert mois_id in seen
    assert mcst_id not in seen


async def test_fold_with_representative_override_keeps_keyset_and_total(
    migrated_session: AsyncSession,
) -> None:
    """대표가 물려받은 자리로도 page_size 1 걷기 = 한 페이지, 개수 일치."""
    for key, name, category, provider, lon in (
        ("ks_mois", "키셋접기호텔서울", "03010100", _MOIS, 127.0100),
        ("ks_mcst", "키셋접기호텔 서울", "01000000", _MCST_FAMOUS, 127.0101),
        ("ks_other", "키셋접기호텔서울 별관", "03010100", _MOIS, 127.0300),
    ):
        await _feature(
            migrated_session, key, name=name, category=category, region=_SEOCHO,
            lon=lon, lat=37.5000, provider=provider,
        )
    await migrated_session.flush()
    q = "키셋접기호텔서울"
    expected = [item.feature_id for item in (await _page(migrated_session, q, page_size=200)).items]
    walked: list[str] = []
    cursor: str | None = None
    for _ in range(len(expected) + 1):
        page = await _page(migrated_session, q, page_size=1, cursor=cursor)
        walked.extend(item.feature_id for item in page.items)
        cursor = page.next_cursor
        if cursor is None:
            break
    assert walked == expected
    total = await _page(migrated_session, q, page_size=1, include_total=True)
    assert total.total_count == len(expected)
    # 대표(MOIS 숙박)는 숨긴 MCST 행의 더 좋은 자리(관광 그룹)를 물려받아 별관보다 앞이다.
    full = await _page(migrated_session, q, page_size=200)
    by_id = {item.feature_id: item for item in full.items}
    mois, annex = _uuid("ks_mois"), _uuid("ks_other")
    assert _uuid("ks_mcst") not in by_id
    rank_mois, rank_annex = by_id[mois].rank, by_id[annex].rank
    assert rank_mois is not None
    assert rank_annex is not None
    assert rank_mois < rank_annex, (rank_mois, rank_annex)
    assert expected.index(mois) < expected.index(annex)


async def test_fold_keeps_a_non_mcst_tourism_row_over_a_same_name_restaurant(
    migrated_session: AsyncSession,
) -> None:
    """비MCST 관광 행(Tier 1만)과 같은 이름 MOIS 식당이 접히면 관광 행이 대표다(분류 구체성이
    그룹보다 앞서지 않는다)."""
    tour = await _feature(
        migrated_session, "tour_gen", name="접기관광명소", category="01000000",
        region=_YONGSAN, lon=126.9800, lat=37.5300,
        provider=("data.go.kr-standard", "datagokr_tourist_attractions"),
    )
    food = await _feature(
        migrated_session, "tour_food", name="접기관광명소", category="02010100",
        region=_YONGSAN, lon=126.9801, lat=37.5300, provider=_MOIS,
    )
    await migrated_session.flush()
    page = await _page(migrated_session, "접기관광명소", kinds=["place"], page_size=200)
    seen = {item.feature_id for item in page.items}
    assert tour in seen
    assert food not in seen


async def test_mcst_enrichment_link_does_not_demote_the_master(
    migrated_session: AsyncSession,
) -> None:
    """R4 뒤 모양: MCST가 MOIS 마스터의 enrichment로 붙어 있어도 마스터가 대표다.

    남은 MCST primary 행은 접힌다.
    """
    master = await _feature(
        migrated_session, "r4_master", name="R4접기호텔", category="03010100",
        region=_SEOCHO, lon=127.0200, lat=37.4900, provider=_MOIS,
    )
    await _primary_link(migrated_session, master, "r4_master", _MCST_FAMOUS, role="enrichment")
    leftover = await _feature(
        migrated_session, "r4_leftover", name="R4접기 호텔", category="01000000",
        region=_SEOCHO, lon=127.0201, lat=37.4900, provider=_MCST_FAMOUS,
    )
    await migrated_session.flush()
    page = await _page(migrated_session, "R4접기호텔", kinds=["place"], page_size=200)
    seen = {item.feature_id for item in page.items}
    assert master in seen
    assert leftover not in seen


async def test_migration_452_lotte_hotel_alias_finds_the_licensed_hotel(
    migrated_session: AsyncSession,
) -> None:
    """452: "롯데호텔 서울" → MOIS 상호 "호텔롯데".

    같은 자리의 숙박·식음 두 행은 숙박 하나로 접힌다.
    """
    alias = (
        await migrated_session.execute(
            text(
                "SELECT canonical_name FROM feature.feature_search_aliases "
                "WHERE alias = '롯데호텔서울'"
            )
        )
    ).scalar_one_or_none()
    assert alias == "호텔롯데"
    lodging = await _feature(
        migrated_session, "lotte_lodging", name="호텔롯데", category="03010100",
        region=_SEOUL_JUNG, lon=126.98109, lat=37.56481, provider=_MOIS,
    )
    food = await _feature(
        migrated_session, "lotte_food", name="호텔롯데", category="02010100",
        region=_SEOUL_JUNG, lon=126.98109, lat=37.56481, provider=_MOIS,
    )
    await migrated_session.flush()
    page = await _page(migrated_session, "롯데호텔 서울", kinds=["place"], page_size=200)
    ids = [item.feature_id for item in page.items]
    assert lodging in ids
    assert food not in ids
    rank = page.items[ids.index(lodging)].rank
    assert rank is not None
    assert rank < feature_repo._SEARCH_RANK_MATCH_WEIGHT, rank
