"""notice 효력 종료 시각의 **typed 계약** 통합 테스트 (T-VN-06 → T-VN-35).

원래 이 파일은 T-VN-06(F-9, ADR-073 Wave 0)의 방어적 cast를 지켰다:
``detail->>'valid_end_time'``이 free-form jsonb라 오염된 **한 행**이 직접
``CAST(... AS timestamptz)``에서 예외를 던지면 ``_PUBLIC_ACTIVE_NOTICE_FILTER_SQL``
을 공유하는 모든 공개 read(bbox/search/nearby/in-area/cluster/counts/notice IDs,
그리고 curated/curation 표면)가 500이 됐고, ``pg_input_is_valid`` 가드 +
fail-closed로 완화했다.

T-VN-35(ADR-086, alembic 0085)가 그 실패 모드를 **구조적으로 제거**했다 —
효력 기간의 정본이 ``feature.feature_notices.valid_start_time/valid_end_time``
``timestamptz`` 컬럼이라 "파싱 불가 값"이 애초에 저장될 수 없다. 그래서 가드도,
문자열 파싱도 코드에서 사라졌다.

따라서 이 파일이 지키는 축이 바뀐다:

1. **오염이 저장될 수 없다** — 오염 문자열을 typed 컬럼에 넣으려는 시도는 write
   시점에 DB가 거부한다(가드가 필요 없어진 이유 그 자체).
2. **정상 규칙 회귀** — 미래 종료/종료 없음은 활성, 과거 종료는 숨김. 이 판정이
   공개 read·admin 목록·#745가 확산한 curated/curation 표면에서 **일관**되게
   나온다(중앙 함수 ``public_active_notice_filter_sql`` 한 곳이 정본).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from kortravelmap.infra import (
    admin_feature_repo,
    curated_repo,
    curation_repo,
    feature_repo,
)
from tests.integration._subtype_seed import seed_feature_subtype

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.integration

_KST = timezone(timedelta(hours=9))
_SEARCH_CURSOR_KEY = b"integration-feature-search-cursor-signing-key-0001"
_NOW = datetime(2026, 7, 19, 12, 0, tzinfo=_KST)

_BBOX = {"min_lon": 126.9, "min_lat": 37.5, "max_lon": 127.1, "max_lat": 37.7}

# 종전 오염 변형: 빈 문자열 / garbage / 형태만 그럴듯한 달력 불가값 / 불가능한
# timezone. (마지막 둘은 정규식 shape 가드가 놓치던 부류 — 그래서
# ``pg_input_is_valid``가 필요했다. 이제는 컬럼 타입이 전부 막는다.)
_FIXTURE_CATALOG_SQL = """
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

_CORRUPTED_END_TIMES: tuple[str, ...] = (
    "",
    "garbage",
    "2026-13-40 00:00:00",
    "2026-07-19T12:00:00+99:99",
)


async def _ins_notice(
    session: AsyncSession,
    *,
    feature_id: str,
    name: str,
    valid_end_time: str | None,
    kind: str = "notice",
    lon: float = 126.978,
    lat: float = 37.5665,
) -> None:
    await session.execute(
        text(
            """
            INSERT INTO feature.features (
                feature_id, kind, name, category, coord, status,
                sido_code, sigungu_code, updated_at
            )
            VALUES (
                :feature_id, :kind, :name, '99000000',
                x_extension.ST_SetSRID(
                    x_extension.ST_MakePoint(
                        CAST(:lon AS double precision),
                        CAST(:lat AS double precision)
                    ),
                    4326
                ),
                'active',
                '11', '11140', CAST(:updated_at AS timestamptz)
            )
            """
        ),
        {
            "feature_id": feature_id,
            "kind": kind,
            "name": name,
            "lon": lon,
            "lat": lat,
            "updated_at": _NOW,
        },
    )
    await seed_feature_subtype(
        session,
        feature_id=feature_id,
        kind=kind,
        detail={"notice_type": "traffic", "valid_end_time": valid_end_time}
        if kind == "notice"
        else {"place_kind": "attraction"},
    )
    await session.flush()


async def _seed_notice_matrix(session: AsyncSession) -> dict[str, str]:
    """place 대조군 1 + notice 3종(미래종료/과거종료/종료없음)을 심는다.

    종전 matrix의 ``null-end``/``no-end-key``는 free-form jsonb 시절 "키가 있고
    값이 null"과 "키 자체가 없음"을 구분하던 것이다. typed 컬럼에서는 둘 다
    ``NULL``이라 상태 자체가 하나로 합쳐졌다(정규화 — ADR-086 결정 4).
    """
    ids: dict[str, str] = {}
    rows: tuple[tuple[str, str | None], ...] = (
        ("future-end", "2999-01-01T00:00:00+09:00"),
        ("past-end", "2000-01-01T00:00:00+09:00"),
        ("no-end", None),
    )
    for i, (suffix, end_time) in enumerate(rows):
        fid = f"ndc:{suffix}"
        await _ins_notice(
            session,
            feature_id=fid,
            name=f"방어캐스트공지 {suffix}",
            valid_end_time=end_time,
            lon=126.978 + i * 0.0001,
            lat=37.5665 + i * 0.0001,
        )
        ids[suffix] = fid
    # 대조군 place — notice 감산과 무관하게 place read는 계속 동작해야 한다.
    await _ins_notice(
        session,
        feature_id="ndc:place",
        # 이름은 notice 검색어와 트라이그램이 겹치지 않게 완전히 다르게 둔다.
        name="대조군일반장소",
        valid_end_time=None,
        kind="place",
        lon=126.99,
        lat=37.57,
    )
    ids["place"] = "ndc:place"
    return ids


# 미래 종료·종료 없음은 활성, 과거 종료는 숨김.
_EXPECTED_VISIBLE_NOTICES: frozenset[str] = frozenset({"future-end", "no-end"})


@pytest.mark.parametrize("corrupted", _CORRUPTED_END_TIMES)
async def test_corrupted_timestamp_cannot_reach_the_typed_column(
    migrated_session: AsyncSession, corrupted: str
) -> None:
    """오염 시각은 **저장 자체가 불가능**하다 — 방어 cast가 사라진 근거.

    종전에는 이 값들이 조용히 들어앉아 read 시점에 500을 냈다(F-9). 이제는
    write가 거부하므로 read 경로에 가드가 필요 없다.
    """
    await migrated_session.execute(
        text(
            "INSERT INTO feature.features "
            "(feature_id, kind, name, category, status) "
            "VALUES ('ndc:typed-reject', 'notice', '타입 거부 공지', '99000000', 'active')"
        )
    )
    await migrated_session.flush()

    with pytest.raises(DBAPIError):
        async with migrated_session.begin_nested():
            await migrated_session.execute(
                text(
                    """
                    INSERT INTO feature.feature_notices (
                        feature_id, feature_uuid, kind, notice_type, valid_end_time
                    )
                    SELECT
                        f.feature_id, f.feature_uuid, f.kind, 'traffic',
                        CAST(:corrupted AS timestamptz)
                    FROM feature.features AS f
                    WHERE f.feature_id = 'ndc:typed-reject'
                    """
                ),
                {"corrupted": corrupted},
            )


async def test_bbox_and_search_apply_typed_end_time_filter(
    migrated_session: AsyncSession,
) -> None:
    """bbox/search가 typed ``valid_end_time`` 비교로 종료 notice만 감산한다."""
    ids = await _seed_notice_matrix(migrated_session)
    expected = {ids[s] for s in _EXPECTED_VISIBLE_NOTICES} | {ids["place"]}
    # bbox는 세션 공유 DB의 다른 파일이 **커밋**한 fixture도 함께 잡는다
    # (예: ``test_admin_feature_repo`` 잠금 시드). 판정 대상은 이 파일이 심은
    # matrix뿐이므로 seeded 집합으로 좁혀 비교한다 — 아래 admin 목록 회귀와
    # 같은 방식이다.
    seeded = set(ids.values())

    bbox_rows = await feature_repo.features_in_bbox(
        migrated_session, **_BBOX, price_stale_hide_days=None
    )
    assert {r["feature_id"] for r in bbox_rows} & seeded == expected

    bbox_geom_rows = await feature_repo.features_in_bbox(
        migrated_session, **_BBOX, include_geometry=True, price_stale_hide_days=None
    )
    assert {r["feature_id"] for r in bbox_geom_rows} & seeded == expected

    search = await feature_repo.search_features(
        migrated_session,
        q="방어캐스트공지",
        cursor_signing_key=_SEARCH_CURSOR_KEY,
    )
    assert {item.feature_id for item in search.items} == {
        ids[s] for s in _EXPECTED_VISIBLE_NOTICES
    }


async def test_notice_ids_and_detail_visibility_use_typed_comparison(
    migrated_session: AsyncSession,
) -> None:
    """notice IDs(=detail/batch 가시성 판정)가 종료 notice만 제외한다."""
    ids = await _seed_notice_matrix(migrated_session)
    notice_ids = [fid for suffix, fid in ids.items() if suffix != "place"]

    # T-VN-32B: 가시성 판정 표면은 identities(id→uuid 쌍) 하나다.
    visible = set(
        await feature_repo.public_active_notice_feature_identities(
            migrated_session, notice_ids
        )
    )
    assert visible == {ids[s] for s in _EXPECTED_VISIBLE_NOTICES}

    # detail/batch 라우터는 위 판정을 그대로 소비한다(features.py
    # `_public_feature_row`) — 종료 notice 단건 조회는 404로 떨어지고, view 자체는
    # 예외 없이 행을 돌려준다.
    assert (
        await feature_repo.public_active_notice_feature_identities(
            migrated_session, [ids["past-end"]]
        )
        == {}
    )
    assert (
        await feature_repo.get_public_feature_row(migrated_session, ids["past-end"])
        is not None
    )


async def test_admin_notice_list_include_ended_toggle(
    migrated_session: AsyncSession,
) -> None:
    """admin notice 목록도 같은 typed 비교로 감산하고 감사 모드는 전부 보여준다.

    - include_ended=False(기본): 종료 notice 제외.
    - include_ended=True(감사): 단락으로 감산 자체를 건너뛴다.
    """
    ids = await _seed_notice_matrix(migrated_session)
    # 이 fixture의 notice는 source_link/계보가 없어 admin latest 필터와 무관하다.

    default_page = await admin_feature_repo.list_admin_features(
        migrated_session, kinds=["notice"], page_size=100
    )
    default_ids = {item.feature_id for item in default_page.items}
    seeded_notice_ids = {fid for s, fid in ids.items() if s != "place"}
    assert default_ids & seeded_notice_ids == {
        ids[s] for s in _EXPECTED_VISIBLE_NOTICES
    }

    audit_page = await admin_feature_repo.list_admin_features(
        migrated_session,
        kinds=["notice"],
        include_ended=True,
        page_size=100,
    )
    assert seeded_notice_ids <= {item.feature_id for item in audit_page.items}


# ── #745 rebase: 중앙화된 notice 감산이 확산한 curation/curated 공개 표면 ──
#
# #745가 `public_active_notice_filter_sql`을 curated-features/curations/collections
# 공개 read의 notice 감산 정본으로 만들었다. 그 단일 함수가 typed 비교로 바뀐 뒤에도
# 아래 표면들이 같은 판정을 상속하는지 고정한다.


async def _seed_public_curation_foundation(session: AsyncSession) -> tuple[str, str]:
    theme_id = str(
        (
            await session.execute(
                text(
                    """
                    INSERT INTO feature.curated_themes (
                        theme_slug, theme_name, theme_description, theme_group,
                        default_curated, visibility, metadata
                    ) VALUES (
                        'ndc-theme', '방어캐스트 테마', '', 'official',
                        false, 'public', '{}'::jsonb
                    )
                    RETURNING theme_id::text
                    """
                )
            )
        ).scalar_one()
    )
    # T-VN-33: curated_sources는 자연키 사본 대신 catalog FK 하나만 든다.
    provider_dataset_id = int(
        (
            await session.execute(
                text(_FIXTURE_CATALOG_SQL),
                {"provider": "python-krex-api", "dataset_key": "ndc-source"},
            )
        ).scalar_one()
    )
    source_id = str(
        (
            await session.execute(
                text(
                    """
                    INSERT INTO feature.curated_sources (
                        provider_dataset_id, source_name, source_kind,
                        update_cycle, provider_status, metadata
                    ) VALUES (
                        :provider_dataset_id, '테스트 출처',
                        'manual', 'unknown', 'manual_only', '{}'::jsonb
                    )
                    RETURNING source_id::text
                    """
                ),
                {"provider_dataset_id": provider_dataset_id},
            )
        ).scalar_one()
    )
    return theme_id, source_id


async def _seed_two_notices(session: AsyncSession) -> tuple[str, str]:
    """(healthy 미래종료, ended 과거종료) notice 2건을 심고 id를 돌려준다."""
    await _ins_notice(
        session,
        feature_id="ndc:cur:healthy",
        name="큐레이션 정상공지",
        valid_end_time="2999-01-01T00:00:00+09:00",
    )
    await _ins_notice(
        session,
        feature_id="ndc:cur:ended",
        name="큐레이션 종료공지",
        valid_end_time="2000-01-01T00:00:00+09:00",
        lon=126.9781,
        lat=37.5666,
    )
    return "ndc:cur:healthy", "ndc:cur:ended"


async def test_curated_features_read_hides_ended_notice(
    migrated_session: AsyncSession,
) -> None:
    """``/v1/curated-features`` 공개 read가 종료 notice를 제외한다."""
    theme_id, source_id = await _seed_public_curation_foundation(migrated_session)
    healthy_id, ended_id = await _seed_two_notices(migrated_session)
    overlays = {}
    for fid in (healthy_id, ended_id):
        overlays[fid] = await curated_repo.create_curated_feature(
            migrated_session,
            theme_id=theme_id,
            feature_id=fid,
            source_id=source_id,
            curation_status="curated",
        )

    page = await curated_repo.list_curated_features(
        migrated_session, theme_slug="ndc-theme", public_only=True
    )
    assert {row.feature_id for row in page.items} == {healthy_id}
    assert (
        await curated_repo.get_curated_feature(
            migrated_session,
            curated_feature_id=overlays[ended_id].curated_feature_id,
            public_only=True,
        )
        is None
    )


async def test_curation_collection_read_hides_ended_notice_item(
    migrated_session: AsyncSession,
) -> None:
    """``/v1/curations/collections/{id}`` + 목록이 종료 notice item을 제외한다."""
    theme_id, source_id = await _seed_public_curation_foundation(migrated_session)
    healthy_id, ended_id = await _seed_two_notices(migrated_session)
    collection = await curation_repo.create_curation_collection(
        migrated_session,
        collection_key="ndc-collection:2026",
        theme_id=theme_id,
        source_id=source_id,
        title="방어캐스트 컬렉션",
        edition_key="2026",
        status="published",
        visibility="public",
    )
    for i, fid in enumerate((healthy_id, ended_id)):
        await curation_repo.add_curation_item(
            migrated_session,
            collection_id=collection.collection_id,
            feature_id=fid,
            external_item_id=f"ndc-item-{i}",
            status="included",
            sort_order=i,
        )

    result = await curation_repo.get_curation_collection(
        migrated_session, collection_id=collection.collection_id, public_only=True
    )
    assert result is not None
    public_row, items = result
    assert public_row.item_count == 1
    assert public_row.public_item_count == 1
    by_external = {item.external_item_id: item for item in items}
    # #745의 공개 item 목록은 비공개-notice item을 행째 제외한다(redact보다 강한
    # 제외 방향).
    assert set(by_external) == {"ndc-item-0"}
    assert by_external["ndc-item-0"].feature_id == healthy_id

    collections, _cursor = await curation_repo.list_curation_collections(
        migrated_session, public_only=True, theme_slug="ndc-theme"
    )
    listed_collection = next(
        c for c in collections if c.collection_id == collection.collection_id
    )
    assert listed_collection.item_count == 1
    assert listed_collection.public_item_count == 1


async def test_curation_feature_groups_read_hides_ended_notice(
    migrated_session: AsyncSession,
) -> None:
    """``/v1/curations`` feature group read가 종료 notice를 숨긴다."""
    theme_id, source_id = await _seed_public_curation_foundation(migrated_session)
    healthy_id, ended_id = await _seed_two_notices(migrated_session)
    collection = await curation_repo.create_curation_collection(
        migrated_session,
        collection_key="ndc-group:2026",
        theme_id=theme_id,
        source_id=source_id,
        title="방어캐스트 그룹 컬렉션",
        edition_key="2026",
        status="published",
        visibility="public",
    )
    for i, fid in enumerate((healthy_id, ended_id)):
        await curation_repo.add_curation_item(
            migrated_session,
            collection_id=collection.collection_id,
            feature_id=fid,
            external_item_id=f"ndc-grp-{i}",
            status="included",
            sort_order=i,
        )

    groups, _cursor = await curation_repo.list_feature_curation_groups(
        migrated_session, public_only=True, theme_slug="ndc-theme"
    )
    assert {g.feature_id for g in groups} == {healthy_id}

    assert (
        await curation_repo.get_feature_curation_group(
            migrated_session, feature_id=ended_id, public_only=True
        )
        is None
    )
    assert (
        await curation_repo.get_feature_curation_group(
            migrated_session, feature_id=healthy_id, public_only=True
        )
        is not None
    )
