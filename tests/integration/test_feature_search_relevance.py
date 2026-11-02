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
