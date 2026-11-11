"""검색 인지도(P6, migration 451) 산출·순위 통합 테스트(2026-11-11 검색 순위 점검).

- 같은 이름(끝 괄호 무시) 무리의 서로 다른 원천 수, 국가유산·TourAPI 원천, 1 km 안 국가유산의 이름
  낱말 일치 수가 인지도를 올리고, MOIS 인허가 대장에만 있는 행은 0이다.
- 검색 순위의 다른 자리가 모두 같으면 인지도가 높은 행이 앞이다(유사도보다 먼저).
- 끝 한글 괄호("신륵사(여주)")를 뗀 이름이 검색어와 같으면 이름 일치다.

DB는 세션 내내 공유되므로 이름은 이 파일 고유("…접검")로 짓고, 단언은 심은 행끼리의 관계만 본다.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any
from uuid import NAMESPACE_URL, UUID, uuid5

import pytest
from sqlalchemy import text

from kortravelmap.infra import feature_repo
from kortravelmap.infra.search_prominence_repo import (
    SEARCH_PROMINENCE_DEFAULT,
    refresh_search_prominence,
)
from tests.integration._subtype_seed import seed_feature_subtype

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.integration

_SEARCH_CURSOR_KEY = b"integration-feature-search-prominence-key-0000001"
_YEOJU = ("41670", "경기도", "여주시")
_JECHEON = ("43150", "충청북도", "제천시")
_GANGHWA = ("28710", "인천광역시", "강화군")
_M = 0.000009  # 위도 1 m


def _uuid(label: str) -> str:
    raw = bytearray(uuid5(NAMESPACE_URL, f"search-prominence:{label}").bytes)
    raw[6] = (raw[6] & 0x0F) | 0x70
    raw[8] = (raw[8] & 0x3F) | 0x80
    return str(UUID(bytes=bytes(raw)))


async def _dataset_id(session: AsyncSession, provider: str, dataset_key: str) -> int:
    return int(
        (
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
                {"provider": provider, "dataset_key": dataset_key},
            )
        ).scalar_one()
    )


async def _place(
    session: AsyncSession,
    label: str,
    *,
    name: str,
    category: str,
    region: tuple[str, str, str],
    lon: float,
    lat: float,
    sources: tuple[tuple[str, str], ...],
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
                CAST(:feature_id AS uuid), 'place', :name, :category,
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
    await seed_feature_subtype(session, feature_id=feature_id, kind="place")
    for index, (provider, dataset_key) in enumerate(sources):
        entity_key = f"prominence-{label}-{index}"
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
            {"key": entity_key, "dataset_id": await _dataset_id(session, provider, dataset_key)},
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
            {
                "feature_id": feature_id,
                "key": entity_key,
                "role": "primary" if index == 0 else "enrichment",
            },
        )
    return feature_id


_TOUR = ("python-visitkorea-api", "visitkorea_tourist_attractions")
_HERITAGE = ("python-krheritage-api", "krheritage_heritage_features")
_MCST = ("python-mcst-api", "mcst_media_famous_places_csv")
_MOIS = ("python-mois-api", "mois_license_features_bulk")


async def _seed(session: AsyncSession) -> dict[str, str]:
    yeoju_lon, yeoju_lat = 127.6520, 37.3000
    ids = {
        # 여주: TourAPI 사찰 + 같은 이름 MCST 행(가까이) + 딸린 국가유산 둘.
        "yeoju": await _place(
            session, "yeoju", name="신륵사접검(여주)", category="01070100", region=_YEOJU,
            lon=yeoju_lon, lat=yeoju_lat, sources=(_TOUR,),
        ),
        "yeoju_mcst": await _place(
            session, "yeoju_mcst", name="신륵사접검", category="01000000", region=_YEOJU,
            lon=yeoju_lon + 50 * _M, lat=yeoju_lat, sources=(_MCST,),
        ),
        "yeoju_h1": await _place(
            session, "yeoju_h1", name="여주 신륵사접검 조사당", category="01070000",
            region=_YEOJU, lon=yeoju_lon, lat=yeoju_lat + 200 * _M, sources=(_HERITAGE,),
        ),
        "yeoju_h2": await _place(
            session, "yeoju_h2", name="여주 신륵사접검 다층석탑", category="01070000",
            region=_YEOJU, lon=yeoju_lon, lat=yeoju_lat - 300 * _M, sources=(_HERITAGE,),
        ),
        # 제천: 같은 분류·같은 이름(괄호만 다름)의 TourAPI 사찰 하나.
        "jecheon": await _place(
            session, "jecheon", name="신륵사접검(제천)", category="01070100", region=_JECHEON,
            lon=128.1900, lat=37.1300, sources=(_TOUR,),
        ),
        # 강화 펜션: MOIS 단독 vs TourAPI가 소개한 펜션(같은 분류).
        "mois_pension": await _place(
            session, "mois_pension", name="접검 펜션", category="03050200", region=_GANGHWA,
            lon=126.4500, lat=37.7000, sources=(_MOIS,),
        ),
        "tour_pension": await _place(
            session, "tour_pension", name="접검 바다 펜션", category="03050200",
            region=_GANGHWA, lon=126.4700, lat=37.7100, sources=(_TOUR, _MOIS),
        ),
    }
    await session.flush()
    return ids


async def _prominence(session: AsyncSession, feature_id: str) -> int | None:
    value = (
        await session.execute(
            text(
                "SELECT prominence FROM feature.feature_search_prominence "
                "WHERE feature_id = CAST(:id AS uuid)"
            ),
            {"id": feature_id},
        )
    ).scalar_one_or_none()
    return None if value is None else int(value)


async def _page(session: AsyncSession, q: str, **kwargs: Any) -> Any:
    return await feature_repo.search_features(
        session, q=q, cursor_signing_key=_SEARCH_CURSOR_KEY, **kwargs
    )


async def test_refresh_scores_mentions_heritage_and_license_only_rows(
    migrated_session: AsyncSession,
) -> None:
    ids = await _seed(migrated_session)
    result = await refresh_search_prominence(migrated_session)
    assert result.computed >= len(ids)
    yeoju = await _prominence(migrated_session, ids["yeoju"])
    jecheon = await _prominence(migrated_session, ids["jecheon"])
    mois = await _prominence(migrated_session, ids["mois_pension"])
    tour = await _prominence(migrated_session, ids["tour_pension"])
    assert yeoju is not None
    assert jecheon is not None
    assert mois is not None
    assert tour is not None
    # 여주: 원천 2(TourAPI·MCST) + 소개 원천 2 + 딸린 국가유산 2 = 6. 제천: 1 + 2 = 3.
    assert yeoju == 6, yeoju
    assert jecheon == 3, jecheon
    # MOIS 단독은 0, TourAPI가 함께 있으면 MOIS 원천도 세지만 0은 아니다.
    assert mois == 0
    assert tour == 2 + 2, tour
    # 두 번째 갱신은 바뀐 것이 없다(값이 같은 행은 쓰지 않는다).
    again = await refresh_search_prominence(migrated_session)
    assert again.changed == 0, again


async def test_prominence_breaks_ties_before_similarity(
    migrated_session: AsyncSession,
) -> None:
    """"신륵사접검" — 두 사찰 모두 끝 괄호를 뗀 이름이 검색어와 같다(이름 일치). 여주가 앞이다."""
    ids = await _seed(migrated_session)
    await refresh_search_prominence(migrated_session)
    page = await _page(migrated_session, "신륵사접검", kinds=["place"], page_size=200)
    order = [item.feature_id for item in page.items]
    assert order.index(ids["yeoju"]) < order.index(ids["jecheon"]), order
    rank = {item.feature_id: item.rank for item in page.items}
    yeoju_rank, jecheon_rank = rank[ids["yeoju"]], rank[ids["jecheon"]]
    assert yeoju_rank is not None
    assert jecheon_rank is not None
    # 인지도 자리만 다르다 — 나머지 자리(이름 일치 포함)는 같다.
    weight = feature_repo._SEARCH_RANK_SPECIFICITY_WEIGHT
    assert yeoju_rank // weight == jecheon_rank // weight, (yeoju_rank, jecheon_rank)
    # 끝 괄호를 뗀 이름 일치는 이름 일치의 둘째 단계다(1 — 이름 전체 0, 불일치 2).
    assert (yeoju_rank // feature_repo._SEARCH_RANK_EXACT_WEIGHT) % 10 == 1, yeoju_rank


async def test_license_only_pension_ranks_after_a_curated_one(
    migrated_session: AsyncSession,
) -> None:
    ids = await _seed(migrated_session)
    await refresh_search_prominence(migrated_session)
    page = await _page(migrated_session, "강화 펜션", kinds=["place"], page_size=200)
    order = [item.feature_id for item in page.items]
    assert order.index(ids["tour_pension"]) < order.index(ids["mois_pension"]), order


async def test_rows_without_prominence_use_the_default(
    migrated_session: AsyncSession,
) -> None:
    """갱신 전(표에 행이 없는) Feature는 기본 인지도로 순위를 받는다 — 검색은 그대로 돈다."""
    ids = await _seed(migrated_session)
    await refresh_search_prominence(migrated_session)
    assert await _prominence(migrated_session, ids["yeoju"]) is not None
    await migrated_session.execute(
        text(
            "DELETE FROM feature.feature_search_prominence "
            "WHERE feature_id = ANY(CAST(:ids AS uuid[]))"
        ),
        {"ids": [ids["yeoju"], ids["jecheon"]]},
    )
    page = await _page(migrated_session, "신륵사접검", kinds=["place"], page_size=200)
    rank = {item.feature_id: item.rank for item in page.items}
    yeoju_rank = rank[ids["yeoju"]]
    assert yeoju_rank is not None
    digit = (yeoju_rank // feature_repo._SEARCH_RANK_PROMINENCE_WEIGHT) % 10
    assert digit == feature_repo.SEARCH_PROMINENCE_MAX - SEARCH_PROMINENCE_DEFAULT, yeoju_rank


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("신륵사(여주)", "신륵사"),
        ("신륵사（여주）", "신륵사"),
        ("설해원 (양양국제공항)", "설해원"),
        ("JW 메리어트 호텔 서울 (JW Marriott Hotel Seoul)", "jw메리어트호텔서울"),
        ("호미곶 해안단구 (경북 동해안 국가지질공원)", "호미곶해안단구"),
        ("경복궁", None),
        ("(주)", None),
        ("회현(남대문시장)역", None),
    ],
)
async def test_paren_base_name_strips_one_trailing_bracket(
    migrated_session: AsyncSession, name: str, expected: str | None
) -> None:
    sql = feature_repo._search_paren_base_sql("v.name")
    got = (
        await migrated_session.execute(
            text(f"SELECT {sql} FROM (SELECT CAST(:name AS text) AS name) AS v"),
            {"name": name},
        )
    ).scalar_one()
    assert got == expected


async def test_paren_base_exact_does_not_lift_lodging_over_tourism(
    migrated_session: AsyncSession,
) -> None:
    """끝 괄호를 뗀 이름 일치는 관광에만 목적지 일치다.

    "하회접검(민박)"이 관광지 앞에 서지 않는다.
    """
    tour = await _place(
        migrated_session, "hahoe_tour", name="안동하회접검", category="01020100",
        region=_YEOJU, lon=128.5180, lat=36.5390, sources=(_TOUR,),
    )
    lodging = await _place(
        migrated_session, "hahoe_lodging", name="하회접검(민박)", category="03050200",
        region=_YEOJU, lon=128.5200, lat=36.5400, sources=(_MOIS,),
    )
    await migrated_session.flush()
    page = await _page(migrated_session, "하회접검", kinds=["place"], page_size=200)
    order = [item.feature_id for item in page.items]
    assert order.index(tour) < order.index(lodging), order


async def test_full_name_exact_beats_tail_exact_even_when_less_prominent(
    migrated_session: AsyncSession,
) -> None:
    """"광안리" — 이름 전체가 같은 해변이 첫 낱말을 뗀 나머지만 같은 "아크앤북 광안리"보다 앞이다.

    서점은 TourAPI가 소개해 인지도가 더 높다. 인지도는 이름 일치 단계 다음 자리다.
    """
    beach = await _place(
        migrated_session, "gwangan_beach", name="광안접검", category="01050100",
        region=_GANGHWA, lon=129.1180, lat=35.1530, sources=(_MCST,),
    )
    bookstore = await _place(
        migrated_session, "gwangan_book", name="아크앤북 광안접검", category="01040000",
        region=_GANGHWA, lon=129.1190, lat=35.1550, sources=(_TOUR, _MCST),
    )
    await migrated_session.flush()
    await refresh_search_prominence(migrated_session)
    beach_p = await _prominence(migrated_session, beach)
    book_p = await _prominence(migrated_session, bookstore)
    assert beach_p is not None
    assert book_p is not None
    assert book_p > beach_p
    page = await _page(migrated_session, "광안접검", kinds=["place"], page_size=200)
    order = [item.feature_id for item in page.items]
    assert order.index(beach) < order.index(bookstore), order
