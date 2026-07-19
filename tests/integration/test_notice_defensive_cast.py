"""T-VN-06 — 오염된 notice timestamp 방어적 cast 통합 테스트 (F-9, ADR-073 Wave 0).

``detail->>'valid_end_time'``은 free-form jsonb다. 오염된 **한 행**이 직접
``CAST(... AS timestamptz)``에서 예외를 던지면 ``_PUBLIC_ACTIVE_NOTICE_FILTER_SQL``
을 공유하는 모든 공개 read(bbox/search/nearby/in-area/cluster/counts/notice IDs,
그리고 notice detail/batch 가시성 판정)가 500이 됐다.

Wave 0 완화(스키마 변경 0, migration 0): ``pg_input_is_valid``(PG16+) 가드 +
fail-closed — 파싱 불가 row는 "notice 없음"으로 강등(제외 방향, 노출 아님).
JSON null/키 부재는 기존 의미(종료시각 없음 = 활성) 유지. typed notice
재설계와 오염 관측(카운터)은 T-VN-37 소유.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import text

from kortravelmap.infra import (
    admin_feature_repo,
    curated_repo,
    curation_repo,
    feature_repo,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.integration

_KST = timezone(timedelta(hours=9))
_NOW = datetime(2026, 7, 19, 12, 0, tzinfo=_KST)

_BBOX = {"min_lon": 126.9, "min_lat": 37.5, "max_lon": 127.1, "max_lat": 37.7}

# 오염 변형: 빈 문자열 / garbage / 형태만 그럴듯한 달력 불가값 / 불가능한 timezone.
# (마지막 둘은 정규식 shape 가드가 놓치는 부류 — pg_input_is_valid가 필요한 이유.)
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
    end_time_key_present: bool = True,
    kind: str = "notice",
    lon: float = 126.978,
    lat: float = 37.5665,
) -> None:
    detail: dict[str, object] = {}
    if end_time_key_present:
        detail["valid_end_time"] = valid_end_time
    await session.execute(
        text(
            """
            INSERT INTO feature.features (
                feature_id, kind, name, category, coord, status, detail,
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
                'active', CAST(:detail AS jsonb),
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
            "detail": json.dumps(detail),
            "updated_at": _NOW,
        },
    )
    await session.flush()


async def _seed_notice_matrix(session: AsyncSession) -> dict[str, str]:
    """place 대조군 1 + notice 7종(정상 3 + 오염 4)을 심는다. suffix→id 매핑 반환."""
    ids: dict[str, str] = {}
    rows: list[tuple[str, str | None, bool]] = [
        # (suffix, valid_end_time, end_time_key_present)
        ("future-end", "2999-01-01T00:00:00+09:00", True),
        ("past-end", "2000-01-01T00:00:00+09:00", True),
        ("null-end", None, True),
        ("no-end-key", None, False),
    ]
    rows += [
        (f"corrupt-{i}", corrupted, True)
        for i, corrupted in enumerate(_CORRUPTED_END_TIMES)
    ]
    for i, (suffix, end_time, key_present) in enumerate(rows):
        fid = f"ndc:{suffix}"
        await _ins_notice(
            session,
            feature_id=fid,
            name=f"방어캐스트공지 {suffix}",
            valid_end_time=end_time,
            end_time_key_present=key_present,
            lon=126.978 + i * 0.0001,
            lat=37.5665 + i * 0.0001,
        )
        ids[suffix] = fid
    # 대조군 place — 오염 notice가 있어도 place read는 계속 동작해야 한다.
    await _ins_notice(
        session,
        feature_id="ndc:place",
        # 이름은 notice 검색어와 트라이그램이 겹치지 않게 완전히 다르게 둔다.
        name="대조군일반장소",
        valid_end_time=None,
        end_time_key_present=False,
        kind="place",
        lon=126.99,
        lat=37.57,
    )
    ids["place"] = "ndc:place"
    return ids


# 정상 규칙(회귀): 미래 종료·종료 없음(null/키 부재)은 활성, 과거 종료는 숨김.
# 완화 규칙: 오염 4종은 전부 fail-closed 제외.
_EXPECTED_VISIBLE_NOTICES: frozenset[str] = frozenset(
    {"future-end", "null-end", "no-end-key"}
)


async def test_bbox_and_search_survive_corrupted_notice_timestamp(
    migrated_session: AsyncSession,
) -> None:
    """오염 row 1건이 있어도 bbox/search가 500 없이 동작하고 오염 notice만 빠진다."""
    ids = await _seed_notice_matrix(migrated_session)
    expected = {ids[s] for s in _EXPECTED_VISIBLE_NOTICES} | {ids["place"]}

    bbox_rows = await feature_repo.features_in_bbox(
        migrated_session, **_BBOX, price_stale_hide_days=None
    )
    assert {r["feature_id"] for r in bbox_rows} == expected

    bbox_geom_rows = await feature_repo.features_in_bbox(
        migrated_session, **_BBOX, include_geometry=True, price_stale_hide_days=None
    )
    assert {r["feature_id"] for r in bbox_geom_rows} == expected

    search = await feature_repo.search_features(migrated_session, q="방어캐스트공지")
    assert {item.feature_id for item in search.items} == {
        ids[s] for s in _EXPECTED_VISIBLE_NOTICES
    }


async def test_notice_ids_and_detail_visibility_fail_closed(
    migrated_session: AsyncSession,
) -> None:
    """notice IDs(=detail/batch 가시성 판정)가 오염 row를 '없음'으로 강등한다."""
    ids = await _seed_notice_matrix(migrated_session)
    notice_ids = [fid for suffix, fid in ids.items() if suffix != "place"]

    visible = await feature_repo.public_active_notice_feature_ids(
        migrated_session, notice_ids
    )
    assert visible == {ids[s] for s in _EXPECTED_VISIBLE_NOTICES}

    # detail/batch 라우터는 notice에 대해 위 판정을 그대로 소비한다
    # (features.py `_public_feature_row`) — 오염 notice 단건 조회는 500이 아니라
    # 404로 떨어진다. view 자체(row 존재)는 cast를 하지 않으므로 500 위험이 없다.
    for i in range(len(_CORRUPTED_END_TIMES)):
        corrupted_id = ids[f"corrupt-{i}"]
        assert (
            await feature_repo.public_active_notice_feature_ids(
                migrated_session, [corrupted_id]
            )
            == set()
        )
        row = await feature_repo.get_public_feature_row(migrated_session, corrupted_id)
        assert row is not None  # 예외 없이 조회되고, 가시성 판정만 제외한다.


async def test_admin_notice_list_survives_corrupted_timestamp(
    migrated_session: AsyncSession,
) -> None:
    """admin notice 목록(요청 경로)도 같은 방어적 cast로 오염 row에 500 없이 동작한다.

    운영자가 오염 row를 바로 찾아야 하는 화면이라 fold-in했다(T-VN-06 리뷰 S3).
    - include_ended=False(기본): pg_input_is_valid 가드 + fail-closed로 오염
      notice를 종료된 것처럼 제외한다. 정상 규칙(미래/없음 활성, 과거 종료)
      회귀 불변.
    - include_ended=True(감사): include_ended 단락으로 cast 자체를 건너뛰어
      오염 notice도 500 없이 전부 반환한다.
    """
    ids = await _seed_notice_matrix(migrated_session)
    # 이 fixture의 notice는 source_link/계보가 없어 admin latest 필터와 무관하다.

    default_page = await admin_feature_repo.list_admin_features(
        migrated_session, kinds=["notice"], statuses=None, page_size=100
    )
    default_ids = {item.feature_id for item in default_page.items}
    seeded_notice_ids = {fid for s, fid in ids.items() if s != "place"}
    assert default_ids & seeded_notice_ids == {
        ids[s] for s in _EXPECTED_VISIBLE_NOTICES
    }

    audit_page = await admin_feature_repo.list_admin_features(
        migrated_session,
        kinds=["notice"],
        statuses=None,
        include_ended=True,
        page_size=100,
    )
    audit_ids = {item.feature_id for item in audit_page.items}
    # 감사 목록은 오염 4종 + 정상/과거까지 seeded notice 전부 포함(500 없음).
    assert seeded_notice_ids <= audit_ids


# ── #745 rebase: 중앙화된 notice 감산이 확산한 curation/curated 공개 표면 ──
#
# #745가 `public_active_notice_filter_sql`을 curated-features/curations/collections
# 공개 read의 notice 감산 정본으로 만들면서 naked cast를 그 표면들로 확산시켰다.
# T-VN-06 가드를 그 함수 본문에 이식했으므로 아래 표면들도 오염 row에 500 없이
# 동작하고 오염 notice가 제외/숨김돼야 한다(충돌 리뷰 S2 payoff).


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
    source_id = str(
        (
            await session.execute(
                text(
                    """
                    INSERT INTO feature.curated_sources (
                        provider, dataset_key, source_name, source_kind,
                        update_cycle, provider_status, metadata
                    ) VALUES (
                        'python-krex-api', 'ndc-source', '테스트 출처',
                        'manual', 'unknown', 'manual_only', '{}'::jsonb
                    )
                    RETURNING source_id::text
                    """
                )
            )
        ).scalar_one()
    )
    return theme_id, source_id


async def _seed_two_notices(session: AsyncSession) -> tuple[str, str]:
    """(healthy 미래종료, corrupted 빈문자열) notice 2건을 심고 id를 돌려준다."""
    await _ins_notice(
        session,
        feature_id="ndc:cur:healthy",
        name="큐레이션 정상공지",
        valid_end_time="2999-01-01T00:00:00+09:00",
    )
    await _ins_notice(
        session,
        feature_id="ndc:cur:corrupt",
        name="큐레이션 오염공지",
        valid_end_time="",
        lon=126.9781,
        lat=37.5666,
    )
    return "ndc:cur:healthy", "ndc:cur:corrupt"


async def test_curated_features_read_survives_corrupted_notice(
    migrated_session: AsyncSession,
) -> None:
    """``/v1/curated-features`` 공개 read가 오염 notice에 500 없이 동작·제외한다."""
    theme_id, source_id = await _seed_public_curation_foundation(migrated_session)
    healthy_id, corrupt_id = await _seed_two_notices(migrated_session)
    for fid in (healthy_id, corrupt_id):
        await curated_repo.create_curated_feature(
            migrated_session,
            theme_id=theme_id,
            feature_id=fid,
            source_id=source_id,
            curation_status="curated",
        )

    page = await curated_repo.list_curated_features(
        migrated_session, theme_slug="ndc-theme", public_only=True
    )
    listed = {row.feature_id for row in page.items}
    assert listed == {healthy_id}  # 오염 notice는 종료 취급으로 제외, 500 없음.


async def test_curation_collection_read_survives_corrupted_notice(
    migrated_session: AsyncSession,
) -> None:
    """``/v1/curations/collections/{id}`` + 목록이 오염 notice item에 500 없이 동작."""
    theme_id, source_id = await _seed_public_curation_foundation(migrated_session)
    healthy_id, corrupt_id = await _seed_two_notices(migrated_session)
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
    for i, fid in enumerate((healthy_id, corrupt_id)):
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
    _row, items = result
    by_external = {item.external_item_id: item for item in items}
    # #745의 공개 item 목록은 비공개-notice item을 행째 제외한다(redact보다 강한
    # 제외 방향). 정상 notice item만 남고, 오염 notice item은 500 없이 사라진다.
    assert set(by_external) == {"ndc-item-0"}
    assert by_external["ndc-item-0"].feature_id == healthy_id

    # 목록 read도 오염 item count 계산에서 500이 나지 않아야 한다.
    collections, _cursor = await curation_repo.list_curation_collections(
        migrated_session, public_only=True, theme_slug="ndc-theme"
    )
    assert any(c.collection_id == collection.collection_id for c in collections)


async def test_curation_feature_groups_read_survives_corrupted_notice(
    migrated_session: AsyncSession,
) -> None:
    """``/v1/curations`` feature group read가 오염 notice에 500 없이 동작·숨김."""
    theme_id, source_id = await _seed_public_curation_foundation(migrated_session)
    healthy_id, corrupt_id = await _seed_two_notices(migrated_session)
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
    for i, fid in enumerate((healthy_id, corrupt_id)):
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
    assert {g.feature_id for g in groups} == {healthy_id}  # 오염 notice 숨김, 500 없음.

    # 단건 group도 오염 notice는 공개 표면에서 None, 정상 notice는 조회된다.
    assert (
        await curation_repo.get_feature_curation_group(
            migrated_session, feature_id=corrupt_id, public_only=True
        )
        is None
    )
    assert (
        await curation_repo.get_feature_curation_group(
            migrated_session, feature_id=healthy_id, public_only=True
        )
        is not None
    )
