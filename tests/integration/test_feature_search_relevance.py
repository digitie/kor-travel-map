"""``/v1/features/search`` 순위·별칭 통합 테스트 (migration 436, 2026-11 PinVi live e2e).

봉화·영주·안동 여행 e2e에서 본 세 사례를 그대로 심는다(이름·분류·좌표는 prod 2026-11-02 실측).

- "하회마을" — 서울의 같은 이름 음식점 셋이 안동하회마을보다 앞섰다.
- "고씨동굴" — 고씨네 음식점과 단양 고수동굴이 영월 고씨굴보다 앞섰다.
- "도산서원" — 이름이 정확히 "도산서원"인 주차장·미디어 명소가 국가유산 "안동 도산서원"보다 앞섰다.

DB는 세션 내내 공유되므로(다른 테스트의 committed 행이 있을 수 있다) 단언은 **여기서 심은
행들 사이의 순서**만 본다.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import NAMESPACE_URL, UUID, uuid5

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from kortravelmap.infra import feature_repo
from tests.integration._subtype_seed import seed_feature_subtype

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.integration

_SEARCH_CURSOR_KEY = b"integration-feature-search-relevance-signing-key-01"

# 안동 일대 bbox(하회마을·도산서원 포함, 서울·영월·단양 제외).
_ANDONG_BBOX = (128.4, 36.4, 129.0, 36.9)
# 서울 도심 bbox.
_SEOUL_BBOX = (126.8, 37.4, 127.2, 37.7)


def _uuid(label: str) -> str:
    raw = bytearray(uuid5(NAMESPACE_URL, f"search-relevance:{label}").bytes)
    raw[6] = (raw[6] & 0x0F) | 0x70
    raw[8] = (raw[8] & 0x3F) | 0x80
    return str(UUID(bytes=bytes(raw)))


async def _place(
    session: AsyncSession,
    label: str,
    *,
    name: str,
    category: str,
    lon: float,
    lat: float,
    place_kind: str = "attraction",
) -> str:
    feature_id = _uuid(label)
    await session.execute(
        text(
            """
            INSERT INTO feature.features (
                feature_id, kind, name, category, coord,
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
                'active', 'published', 'valid'
            )
            """
        ),
        {"feature_id": feature_id, "name": name, "category": category, "lon": lon, "lat": lat},
    )
    await seed_feature_subtype(
        session,
        feature_id=feature_id,
        kind="place",
        detail={"place_kind": place_kind},
    )
    return feature_id


async def _seed_trip_places(session: AsyncSession) -> dict[str, str]:
    ids = {
        # 하회마을
        "hahoe_village": await _place(
            session, "hahoe_village", name="안동하회마을", category="01040000",
            lon=128.5289, lat=36.5503,
        ),
        "hahoe_forest": await _place(
            session, "hahoe_forest", name="안동 하회마을 만송정 숲", category="01070300",
            lon=128.5151, lat=36.5402,
        ),
        "hahoe_parking": await _place(
            session, "hahoe_parking", name="하회마을관광지", category="06010000",
            lon=128.5294, lat=36.5508, place_kind="parking",
        ),
        "hahoe_food_1": await _place(
            session, "hahoe_food_1", name="하회마을", category="02010100",
            lon=126.9239, lat=37.5554, place_kind="restaurant",
        ),
        "hahoe_food_2": await _place(
            session, "hahoe_food_2", name="하회마을", category="02010100",
            lon=126.9728, lat=37.5444, place_kind="restaurant",
        ),
        "hahoe_food_3": await _place(
            session, "hahoe_food_3", name="하회마을", category="02010100",
            lon=126.9133, lat=37.4867, place_kind="restaurant",
        ),
        # 고씨동굴
        "gossi_heritage": await _place(
            session, "gossi_heritage", name="영월 고씨굴", category="01070300",
            lon=128.5329, lat=37.1297,
        ),
        "gossi_parking": await _place(
            session, "gossi_parking", name="고씨굴", category="06010000",
            lon=128.5353, lat=37.1312, place_kind="parking",
        ),
        "gosu_cave": await _place(
            session, "gosu_cave", name="고수동굴", category="01020400",
            lon=128.3820, lat=36.9890,
        ),
        "gossi_food_1": await _place(
            session, "gossi_food_1", name="고씨네", category="02010100",
            lon=127.0354, lat=37.5887, place_kind="restaurant",
        ),
        "gossi_food_2": await _place(
            session, "gossi_food_2", name="고씨네", category="02010100",
            lon=126.8655, lat=37.5175, place_kind="restaurant",
        ),
        # 도산서원
        "dosan_heritage": await _place(
            session, "dosan_heritage", name="안동 도산서원", category="01070300",
            lon=128.8403, lat=36.7280,
        ),
        "dosan_media": await _place(
            session, "dosan_media", name="도산서원", category="01000000",
            lon=128.8436, lat=36.7270, place_kind="media_famous_place",
        ),
        "dosan_parking": await _place(
            session, "dosan_parking", name="도산서원", category="06010000",
            lon=128.8403, lat=36.7286, place_kind="parking",
        ),
        "dosan_painting": await _place(
            session, "dosan_painting", name="강세황 필 도산서원도", category="01070000",
            lon=126.9804, lat=37.5240,
        ),
    }
    await session.flush()
    return ids


async def _search_ids(
    session: AsyncSession,
    q: str,
    ids: dict[str, str],
    *,
    bbox: tuple[float, float, float, float] | None = None,
) -> list[str]:
    """한 페이지(200)로 검색해 **여기서 심은** 행의 라벨만 순서대로 돌려준다."""
    by_id = {feature_id: label for label, feature_id in ids.items()}
    page = await feature_repo.search_features(
        session,
        q=q,
        bbox=bbox,
        kinds=["place"],
        page_size=200,
        cursor_signing_key=_SEARCH_CURSOR_KEY,
    )
    return [by_id[item.feature_id] for item in page.items if item.feature_id in by_id]


def _ordered(labels: list[str], *groups: set[str]) -> bool:
    """``labels``가 groups 순서대로 나오는가(그룹 안 순서는 묻지 않는다)."""
    position = 0
    for group in groups:
        chunk = labels[position : position + len(group)]
        if set(chunk) != group:
            return False
        position += len(group)
    return position == len(labels)


async def test_hahoe_village_ranks_before_same_name_seoul_restaurants(
    migrated_session: AsyncSession,
) -> None:
    ids = await _seed_trip_places(migrated_session)
    labels = await _search_ids(migrated_session, "하회마을", ids)
    # 별칭(436 seed: 하회마을 → 안동하회마을) → 관광 → 식음 → 주차장.
    assert _ordered(
        labels,
        {"hahoe_village"},
        {"hahoe_forest"},
        {"hahoe_food_1", "hahoe_food_2", "hahoe_food_3"},
        {"hahoe_parking"},
    ), labels


async def test_gossi_cave_alias_finds_yeongwol_gossigul_first(
    migrated_session: AsyncSession,
) -> None:
    ids = await _seed_trip_places(migrated_session)
    labels = await _search_ids(migrated_session, "고씨동굴", ids)
    # "영월 고씨굴"은 trigram만으로는 문턱(0.2)에 겨우 걸린다 — 별칭이 맨 앞으로 올린다.
    assert labels[0] == "gossi_heritage", labels
    # 그 뒤는 유사도 단계: 관광(고수동굴) → 식음(고씨네) → 주차장(고씨굴).
    fuzzy = {"gosu_cave", "gossi_food_1", "gossi_food_2", "gossi_parking"}
    rest = [label for label in labels[1:] if label in fuzzy]
    assert rest.index("gosu_cave") < rest.index("gossi_food_1")
    assert rest.index("gosu_cave") < rest.index("gossi_food_2")
    if "gossi_parking" in rest:
        assert rest.index("gossi_parking") > max(
            rest.index("gossi_food_1"), rest.index("gossi_food_2")
        )
    # 띄어 쓰거나 지역명을 붙인 별칭도 같은 키로 찾는다.
    spaced = await _search_ids(migrated_session, "  고씨 동굴 ", ids)
    assert spaced[0] == "gossi_heritage", spaced
    regional = await _search_ids(migrated_session, "영월 고씨동굴", ids)
    assert regional[0] == "gossi_heritage", regional


async def test_dosan_seowon_heritage_ranks_before_media_spot_and_parking(
    migrated_session: AsyncSession,
) -> None:
    ids = await _seed_trip_places(migrated_session)
    labels = await _search_ids(migrated_session, "도산서원", ids)
    # 지역명을 뗀 이름 일치("안동 도산서원")는 이름 일치로 본다 — 국가유산(구체 분류)이
    # Tier 1만 있는 미디어 명소("01000000")보다 앞, 이름을 품기만 한 그림은 그 뒤, 주차장은 맨 뒤.
    assert labels == ["dosan_heritage", "dosan_media", "dosan_painting", "dosan_parking"], labels


async def test_transport_hub_exact_name_is_not_buried_under_partial_matches(
    migrated_session: AsyncSession,
) -> None:
    """역·공항·휴게소는 이름으로 찾아가는 시설이다 — 숙박과 같은 그룹(적대 리뷰 2026-11-02).

    분류 그룹을 Tier 1로만 가르면 역(06)이 주차장과 같은 맨 뒤 그룹이라 "롯데리아 서울역점"
    같은 음식점이 역 자체보다 앞섰다. ADR-120부터 이름이 검색어와 **같은** 목적지(역)는 이름에
    검색어를 품기만 한 관광(박물관)보다도 앞이다. 주차장은 이름이 같아도 목적지가 아니라 맨 뒤다.
    """
    ids = {
        "seoul_station": await _place(
            migrated_session, "seoul_station", name="서울역", category="06030300",
            lon=126.9707, lat=37.5547, place_kind="station",
        ),
        "seoul_museum": await _place(
            migrated_session, "seoul_museum", name="서울역사박물관", category="01040100",
            lon=126.9706, lat=37.5703,
        ),
        "seoul_food": await _place(
            migrated_session, "seoul_food", name="롯데리아 서울역점", category="02010100",
            lon=126.9720, lat=37.5550, place_kind="restaurant",
        ),
        "seoul_parking": await _place(
            migrated_session, "seoul_parking", name="서울역", category="06010000",
            lon=126.9715, lat=37.5540, place_kind="parking",
        ),
    }
    await migrated_session.flush()
    labels = await _search_ids(migrated_session, "서울역", ids)
    assert labels == ["seoul_station", "seoul_museum", "seoul_food", "seoul_parking"], labels


async def test_exact_named_airport_ranks_before_a_tourism_row_that_only_contains_it(
    migrated_session: AsyncSession,
) -> None:
    """#1459 §2(2026-11-08 운영): "양양국제공항" 1위가 숙소 "설해원(양양국제공항)"이었다.

    설해원은 관광 그룹(01000000)이고 공항은 그룹 1이라 그룹이 이름 일치보다 앞서면 공항이
    이름 일치로 절대 선택되지 않았다. 이름이 같은 목적지는 그룹보다 앞이다(ADR-120).
    """
    ids = {
        "yangyang_airport": await _place(
            migrated_session, "yangyang_airport", name="양양국제공항", category="06050000",
            lon=128.6690, lat=38.0613, place_kind="airport",
        ),
        "seolhaewon": await _place(
            migrated_session, "seolhaewon", name="설해원(양양국제공항)", category="01000000",
            lon=128.6705, lat=38.0420,
        ),
        "yangyang_parking": await _place(
            migrated_session, "yangyang_parking", name="양양국제공항", category="06010000",
            lon=128.6680, lat=38.0600, place_kind="parking",
        ),
    }
    await migrated_session.flush()
    labels = await _search_ids(migrated_session, "양양국제공항", ids)
    assert labels[0] == "yangyang_airport", labels
    assert labels.index("seolhaewon") < labels.index("yangyang_parking"), labels


async def test_lodging_named_after_a_place_does_not_jump_the_tourism_spot(
    migrated_session: AsyncSession,
) -> None:
    """목적지 이름 일치는 이름 전체로 잰다 — 숙박 "신라스테이 해운대"의 지역 꼬리("해운대")는
    관광지 "해운대해수욕장"을 넘지 못한다(첫 낱말을 뗀 일치는 관광에만 쓴다, ADR-120 리뷰)."""
    ids = {
        "haeundae_beach": await _place(
            migrated_session, "haeundae_beach", name="해운대해수욕장", category="01050100",
            lon=129.1604, lat=35.1587,
        ),
        "haeundae_hotel": await _place(
            migrated_session, "haeundae_hotel", name="신라스테이 해운대", category="03010000",
            lon=129.1590, lat=35.1610, place_kind="hotel",
        ),
    }
    await migrated_session.flush()
    labels = await _search_ids(migrated_session, "해운대", ids)
    assert labels == ["haeundae_beach", "haeundae_hotel"], labels


async def test_exact_named_food_does_not_jump_the_category_groups(
    migrated_session: AsyncSession,
) -> None:
    """목적지가 아닌 분류(식음)의 이름 일치는 여전히 그룹 뒤에서만 가른다 — 436의 결정 그대로.

    "남이섬"이라는 서울 음식점이 이름에 "남이섬"을 품은 관광지보다 앞서지 않는다.
    """
    ids = {
        "nami_island": await _place(
            migrated_session, "nami_island", name="남이섬 유원지 검사", category="01080000",
            lon=127.5255, lat=37.7906,
        ),
        "nami_food": await _place(
            migrated_session, "nami_food", name="남이섬 유원지", category="02010100",
            lon=126.9780, lat=37.5665, place_kind="restaurant",
        ),
    }
    await migrated_session.flush()
    labels = await _search_ids(migrated_session, "남이섬 유원지", ids)
    assert labels == ["nami_island", "nami_food"], labels


async def test_transport_reference_places_are_found_by_their_display_names(
    migrated_session: AsyncSession,
) -> None:
    """휴게소·역·여객선터미널은 표시 이름("…휴게소(…방향)"·"…역")으로 저장된다(ADR-120) —
    "강릉휴게소"·"대전역"·"인천항"을 찾으면 그 시설이 약국·주차장보다 앞이다."""
    ids = {
        "gangneung_rest": await _place(
            migrated_session, "gangneung_rest", name="강릉휴게소(인천방향)", category="06040101",
            lon=128.8054, lat=37.7603, place_kind="rest_area",
        ),
        "gangneung_pharmacy": await _place(
            migrated_session, "gangneung_pharmacy", name="강릉휴게소약국", category="07020000",
            lon=128.8050, lat=37.7600, place_kind="pharmacy",
        ),
        "daejeon_station": await _place(
            migrated_session, "daejeon_station", name="대전역", category="06030200",
            lon=127.4342, lat=36.3321, place_kind="rail_station",
        ),
        "daejeon_pharmacy": await _place(
            migrated_session, "daejeon_pharmacy", name="대전역약국", category="07020000",
            lon=127.4340, lat=36.3320, place_kind="pharmacy",
        ),
        "incheon_port": await _place(
            migrated_session, "incheon_port", name="인천항", category="06060000",
            lon=126.5996, lat=37.4517, place_kind="ferry_terminal",
        ),
        "incheon_parking": await _place(
            migrated_session, "incheon_parking", name="인천항 공영주차장", category="06010000",
            lon=126.6000, lat=37.4520, place_kind="parking",
        ),
    }
    await migrated_session.flush()
    for query, first in (
        ("강릉휴게소", "gangneung_rest"),
        ("대전역", "daejeon_station"),
        ("인천항", "incheon_port"),
    ):
        labels = await _search_ids(migrated_session, query, ids)
        assert labels, query
        assert labels[0] == first, (query, labels)


async def test_region_prefix_split_handles_any_whitespace_and_leading_space(
    migrated_session: AsyncSession,
) -> None:
    """지역명 tail은 공백 집합 어느 문자(U+3000)에서든, 앞 공백을 걷은 뒤 자른다.

    "\u3000영주\u3000소수서원"(국가유산)은 "소수서원"과 이름 일치로 보여야 Tier 1만 있는 미디어 명소
    "소수서원"(01000000)보다 앞선다. ASCII 공백만 보면 일치를 놓쳐 미디어 명소 뒤로 간다.
    """
    ids = {
        "sosu_heritage": await _place(
            migrated_session, "sosu_heritage", name="\u3000영주\u3000소수서원", category="01070300",
            lon=128.5806, lat=36.9253,
        ),
        "sosu_media": await _place(
            migrated_session, "sosu_media", name="소수서원", category="01000000",
            lon=128.5803, lat=36.9255, place_kind="media_famous_place",
        ),
    }
    await migrated_session.flush()
    labels = await _search_ids(migrated_session, "소수서원", ids)
    assert labels == ["sosu_heritage", "sosu_media"], labels


async def test_displayed_parking_name_is_searchable(
    migrated_session: AsyncSession,
) -> None:
    """응답에 "도산서원 주차장"으로 보이는 주차장은 그 이름으로 찾으면 맨 앞이다.

    저장 이름은 "도산서원"이지만 포함·일치 단계는 보이는 이름으로 비교한다.
    """
    ids = await _seed_trip_places(migrated_session)
    labels = await _search_ids(migrated_session, "도산서원 주차장", ids)
    assert labels[0] == "dosan_parking", labels
    assert labels.index("dosan_heritage") < labels.index("dosan_media"), labels


async def test_bbox_is_a_relevance_bias_not_a_filter(
    migrated_session: AsyncSession,
) -> None:
    ids = await _seed_trip_places(migrated_session)
    # 서울 bbox: 서울에 있는 그림이 맨 앞으로 오지만, bbox 밖 행도 빠지지 않는다.
    seoul = await _search_ids(migrated_session, "도산서원", ids, bbox=_SEOUL_BBOX)
    assert seoul == ["dosan_painting", "dosan_heritage", "dosan_media", "dosan_parking"], seoul
    # 안동 bbox: 하회마을 음식점(서울)은 bbox 밖이라 주차장(안동)보다 뒤로 간다.
    andong = await _search_ids(migrated_session, "하회마을", ids, bbox=_ANDONG_BBOX)
    assert _ordered(
        andong,
        {"hahoe_village"},
        {"hahoe_forest"},
        {"hahoe_parking"},
        {"hahoe_food_1", "hahoe_food_2", "hahoe_food_3"},
    ), andong

    with_total = await feature_repo.search_features(
        migrated_session,
        q="도산서원",
        bbox=_SEOUL_BBOX,
        kinds=["place"],
        include_total=True,
        cursor_signing_key=_SEARCH_CURSOR_KEY,
    )
    without_bbox = await feature_repo.search_features(
        migrated_session,
        q="도산서원",
        kinds=["place"],
        include_total=True,
        cursor_signing_key=_SEARCH_CURSOR_KEY,
    )
    # 가중일 뿐이므로 total은 bbox 유무와 같다.
    assert with_total.total_count == without_bbox.total_count
    assert with_total.total_count is not None
    assert with_total.total_count >= 4


async def test_rank_keyset_pagination_matches_single_page_order(
    migrated_session: AsyncSession,
) -> None:
    ids = await _seed_trip_places(migrated_session)
    expected = [
        item.feature_id
        for item in (
            await feature_repo.search_features(
                migrated_session,
                q="하회마을",
                bbox=_ANDONG_BBOX,
                kinds=["place"],
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
            q="하회마을",
            bbox=_ANDONG_BBOX,
            kinds=["place"],
            page_size=2,
            cursor=cursor,
            cursor_signing_key=_SEARCH_CURSOR_KEY,
        )
        assert all(item.rank is not None for item in page.items)
        walked.extend(item.feature_id for item in page.items)
        cursor = page.next_cursor
        if cursor is None:
            break
    assert cursor is None
    assert walked == expected
    assert len(walked) == len(set(walked))
    assert set(ids.values()) & set(walked) >= {ids["hahoe_village"], ids["hahoe_parking"]}


async def test_alias_rows_drive_search_and_reject_unnormalized_keys(
    migrated_session: AsyncSession,
) -> None:
    target = await _place(
        migrated_session,
        "alias_target",
        name="별칭 검사 대상 정자",
        category="01070300",
        lon=128.1,
        lat=36.1,
    )
    await migrated_session.execute(
        text(
            "INSERT INTO feature.feature_search_aliases (alias, canonical_name, note) "
            "VALUES ('ktm별칭검사어', '별칭 검사 대상 정자', 'integration')"
        )
    )
    page = await feature_repo.search_features(
        migrated_session,
        q="KTM 별칭검사어",
        page_size=10,
        cursor_signing_key=_SEARCH_CURSOR_KEY,
    )
    # trigram으로는 전혀 닮지 않았지만 별칭이 대상 이름을 맨 앞에 더한다.
    assert page.items[0].feature_id == target
    assert page.items[0].rank is not None
    assert page.items[0].rank < 10_000

    for alias, canonical in (
        ("하회 마을", "안동하회마을"),  # 공백
        ("HAHOE", "안동하회마을"),  # 대문자
        ("", "안동하회마을"),  # 빈 키
        ("ktm별칭검사어2", " 안동하회마을"),  # 앞뒤 공백 이름
    ):
        savepoint = await migrated_session.begin_nested()
        with pytest.raises(IntegrityError):
            await migrated_session.execute(
                text(
                    "INSERT INTO feature.feature_search_aliases (alias, canonical_name) "
                    "VALUES (:alias, :canonical)"
                ),
                {"alias": alias, "canonical": canonical},
            )
        await savepoint.rollback()


async def test_migration_seeds_trip_aliases_in_normalized_form(
    migrated_session: AsyncSession,
) -> None:
    rows = dict(
        (
            await migrated_session.execute(
                text("SELECT alias, canonical_name FROM feature.feature_search_aliases")
            )
        ).all()
    )
    expected = {
        "고씨동굴": "영월 고씨굴",
        "영월고씨동굴": "영월 고씨굴",
        "하회마을": "안동하회마을",
        "하회민속마을": "안동하회마을",
    }
    assert expected.items() <= rows.items()
    for alias in expected:
        assert feature_repo.search_alias_key(alias) == alias


async def _mois_lodging(
    session: AsyncSession, mng_no: str, *, name: str, lon: float, lat: float
) -> str:
    """MOIS 숙박 인허가 한 건을 **실제 변환·적재 경로**로 싣고 feature id를 돌려준다."""
    from dataclasses import replace

    from kortravelmap.dto import kst_now
    from kortravelmap.providers.mois import license_records_to_bundles
    from tests.integration.test_mois_resumable_load_repo import _Record

    record = replace(
        _Record(service_slug="lodgings", mng_no=f"search-{mng_no}"),
        place_name=name, subtype_name="관광호텔", business_type_name="관광호텔",
        lon=lon, lat=lat,
    )
    [bundle] = await license_records_to_bundles([record], fetched_at=kst_now())
    await feature_repo.load_bundles(session, [bundle])
    return str(
        (
            await session.execute(
                text(
                    """
                    SELECT sl.feature_id FROM provider_sync.source_links AS sl
                    JOIN provider_sync.source_entities AS se
                      ON se.source_entity_key = sl.source_entity_key
                    WHERE se.source_entity_id = :id AND sl.source_role = 'primary'
                    """
                ),
                {"id": f"lodgings::search-{mng_no}"},
            )
        ).scalar_one()
    )


async def test_mois_hotels_are_found_by_common_name_with_lodging_category(
    migrated_session: AsyncSession,
) -> None:
    """법인 상호로 적재된 호텔을 사람이 부르는 이름으로 찾는다(2026-11-09 감사 사례)."""
    ids = {
        "lotte_daejeon": await _mois_lodging(
            migrated_session, "lotte", name="(주)호텔롯데 롯데시티호텔대전",
            lon=127.3870, lat=36.3750,
        ),
        "shilla": await _mois_lodging(
            migrated_session, "shilla", name="호텔신라", lon=127.0057, lat=37.5560,
        ),
        "shilla_motel": await _place(
            migrated_session, "shilla-motel", name="신라호텔모텔", category="03040100",
            lon=127.0800, lat=37.5900, place_kind="lodging_general",
        ),
    }

    lotte = await _search_ids(migrated_session, "롯데시티호텔 대전", ids)
    assert lotte[:1] == ["lotte_daejeon"]
    shilla = await _search_ids(migrated_session, "신라호텔", ids)
    assert shilla[:1] == ["shilla"], "별칭(442) 신라호텔 → 호텔신라가 같은 이름 모텔보다 앞선다"

    page = await feature_repo.search_features(
        migrated_session, q="롯데시티호텔대전", kinds=["place"], page_size=50,
        cursor_signing_key=_SEARCH_CURSOR_KEY,
    )
    found = next(item for item in page.items if item.feature_id == ids["lotte_daejeon"])
    assert found.name == "롯데시티호텔대전"
    assert found.category == "03010100"


@pytest.mark.parametrize(
    ("query", "typed_name", "generic_name", "category", "food_name"),
    [
        ("하회마을", "안동 하회마을", "안동하회마을", "01070400", "하회마을"),
        ("고씨동굴", "영월고씨굴", "영월 고씨굴", "01020400", "고씨네"),
    ],
)
async def test_alias_space_variants_do_not_hide_typed_source_behind_unclassified_theme(
    migrated_session: AsyncSession, query: str, typed_name: str, generic_name: str,
    category: str, food_name: str,
) -> None:
    ids = {}
    for label, name, code in (
        ("typed", typed_name, category), ("theme", generic_name, "00000000"),
        ("food", food_name, "02010100"),
    ):
        ids[label] = await _place(
            migrated_session, "space-variant-" + query + label, name=name, category=code,
            lon=128.5, lat=36.5,
        )
    labels = await _search_ids(migrated_session, query, ids)
    # 별칭 대상(분류 있음) → 별칭 대상(미분류) → 이름이 비슷한 식음 순이다(#1443).
    assert labels[:2] == ["typed", "theme"], labels
    assert labels[2:] in ([], ["food"]), labels
    full = await feature_repo.search_features(
        migrated_session, q=query, kinds=["place"], page_size=200,
        include_total=True, cursor_signing_key=_SEARCH_CURSOR_KEY,
    )
    assert full.total_count == len(full.items)
    walked = []
    cursor = None
    for _ in range(len(full.items) + 1):
        page = await feature_repo.search_features(
            migrated_session, q=query, kinds=["place"], page_size=1,
            cursor=cursor, include_total=True, cursor_signing_key=_SEARCH_CURSOR_KEY,
        )
        assert page.total_count == full.total_count
        walked.extend(item.feature_id for item in page.items)
        cursor = page.next_cursor
        if cursor is None:
            break
    assert cursor is None
    assert walked == [item.feature_id for item in full.items]


async def test_alias_normalization_uses_raw_parking_name_before_display_suffix(
    migrated_session: AsyncSession,
) -> None:
    target = await _place(
        migrated_session, "raw-alias-parking", name="별칭 정자", category="06010000",
        lon=128.5, lat=36.5, place_kind="parking",
    )
    await migrated_session.execute(text(
        "INSERT INTO feature.feature_search_aliases(alias,canonical_name) "
        "VALUES ('공백주차별칭검증','별칭정자')"
    ))
    page = await feature_repo.search_features(
        migrated_session, q="공백주차별칭검증", include_total=True,
        cursor_signing_key=_SEARCH_CURSOR_KEY,
    )
    assert page.items[0].feature_id == target
    assert page.items[0].rank is not None
    assert page.items[0].rank < 10000
    assert page.total_count is not None
    assert page.total_count >= 1


#: 444 별칭 — (검색어, 정본 이름, 정본 분류, 미끼(이름·분류)). 정본·미끼 이름은
#: prod(2026-11-10)·TourAPI
#: 실측이다. 미끼는 별칭이 없을 때 같은 검색어로 앞에 서던(또는 서는) 행이다.
_TRIP_ALIAS_CASES: tuple[tuple[str, str, str, tuple[str, str]], ...] = (
    ("리움", "삼성미술관 Leeum", "01040000", ("LEEUM리움삼성아동교육문화센터", "01040000")),
    ("수성못", "수성유원지", "01040000", ("수성못주유소", "06020000")),
    ("김포공항", "김포국제공항", "06050000", ("미소야김포공항점", "02010100")),
    ("퍼플섬", "반월도·박지도", "01020300", ("퍼플키즈카페", "01010400")),
    ("사천케이블카", "사천바다 케이블카", "01080200", ("사천케이블카자연휴양림", "03030000")),
)


@pytest.mark.parametrize(("q", "canonical", "category", "decoy"), _TRIP_ALIAS_CASES)
async def test_trip_aliases_put_the_canonical_place_first(
    migrated_session: AsyncSession,
    q: str,
    canonical: str,
    category: str,
    decoy: tuple[str, str],
) -> None:
    """#1459 후속(444): 통칭 검색어가 정본 이름의 장소를 맨 앞에 둔다."""
    target = await _place(
        migrated_session, f"trip444:{q}", name=canonical, category=category,
        lon=127.0, lat=36.0,
    )
    decoy_id = await _place(
        migrated_session, f"trip444-decoy:{q}", name=decoy[0], category=decoy[1],
        lon=127.1, lat=36.1,
    )
    await migrated_session.flush()
    page = await feature_repo.search_features(
        migrated_session,
        q=q,
        kinds=["place"],
        page_size=200,
        cursor_signing_key=_SEARCH_CURSOR_KEY,
    )
    ids = [item.feature_id for item in page.items]
    assert target in ids, (q, canonical)
    if decoy_id in ids:
        assert ids.index(target) < ids.index(decoy_id), (q, ids)
    rank = page.items[ids.index(target)].rank
    # 별칭 일치 단계(0)다 — 이름 포함(1)·유사도(2)로 우연히 앞선 것이 아니다.
    assert rank is not None
    assert rank < feature_repo._SEARCH_RANK_MATCH_WEIGHT, (q, rank)


async def test_migration_444_seeds_trip_aliases_in_normalized_form(
    migrated_session: AsyncSession,
) -> None:
    rows = dict(
        (
            await migrated_session.execute(
                text("SELECT alias, canonical_name FROM feature.feature_search_aliases")
            )
        ).all()
    )
    expected = {
        "리움": "삼성미술관 Leeum",
        "리움미술관": "삼성미술관 Leeum",
        "수성못": "수성유원지",
        "김포공항": "김포국제공항",
        "퍼플섬": "반월도·박지도",
        "사천바다케이블카": "사천바다 케이블카",
        "사천케이블카": "사천바다 케이블카",
    }
    assert expected.items() <= rows.items()
    for alias in expected:
        assert feature_repo.search_alias_key(alias) == alias
