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
    return feature_id


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
    first = await _page(migrated_session, q, page_size=2)
    rest = await _page(migrated_session, q, page_size=200, cursor=first.next_cursor)
    seen = [item.feature_id for item in (*first.items, *rest.items)]
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
    statement = text(
        f"SELECT {effective} FROM ("
        f"SELECT v.category, v.compact_name, {base} AS category_search_group FROM ("
        "SELECT CAST(:category AS text) AS category, CAST(:compact AS text) AS compact_name"
        ") AS v) AS w"
    )
    for category, name in cases:
        got = (
            await migrated_session.execute(
                statement,
                {"category": category, "compact": feature_repo.search_alias_key(name)},
            )
        ).scalar_one()
        assert got == search_effective_group(category, name), (category, name, got)
