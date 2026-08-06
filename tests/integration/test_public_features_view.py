"""ADR-067 단일 공개 projection(``feature.public_features``) 상태 matrix 통합 테스트.

T-VN-04 (F-1 양방향):

- **방향 1 (retired 은닉)**: provider retire(inactive + deleted_at)는 모든 공개
  경로에서 **일관되게** 비공개다 — 경로별로 다른 술어가 없다.
- **방향 2 (draft/broken 노출)**: admin deactivate(inactive, deleted_at 없음)·
  draft·broken·hidden은 어떤 공개 경로에서도 노출되지 않는다.

상태별 fixture × 공개 read 경로(detail/batch/bbox/cluster/search/nearby/
in-area/collection/curated/weather anchor/public views) 교차 검사.
공개 술어는 alembic 0059의 VIEW 한 곳에만 정의된다 — 본 테스트는 그 술어의
소비자들이 전부 같은 판정을 내리는지 검증한다.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any

import pytest
from sqlalchemy import text

from kortravelmap.infra import (
    curated_repo,
    curation_repo,
    feature_repo,
    public_views_repo,
    weather_repo,
)
from kortravelmap.infra.poi_cache_target_repo import upsert_poi_cache_target
from tests.integration._subtype_seed import seed_feature_subtype

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.integration

_KST = timezone(timedelta(hours=9))
_NOW = datetime(2026, 7, 19, 12, 0, tzinfo=_KST)
_SEARCH_CURSOR_KEY = b"integration-feature-search-cursor-signing-key-0001"

# 서울시청 근처 bbox.
_BBOX = {"min_lon": 126.9, "min_lat": 37.5, "max_lon": 127.1, "max_lat": 37.7}


async def _ins_feature(
    session: AsyncSession,
    *,
    feature_id: str,
    name: str,
    status: str = "active",
    soft_deleted: bool = False,
    kind: str = "place",
    category: str = "06020000",
    lon: float = 126.978,
    lat: float = 37.5665,
    detail: str = "{}",
    sido: str = "11",
    sigungu: str = "11140",
    bjd: str = "1114010100",
) -> None:
    await session.execute(
        text(
            """
            INSERT INTO feature.features (
                feature_id, kind, name, category, coord, status,
                sido_code, sigungu_code, legal_dong_code, updated_at, deleted_at
            )
            VALUES (
                :feature_id, :kind, :name, :category,
                x_extension.ST_SetSRID(
                    x_extension.ST_MakePoint(
                        CAST(:lon AS double precision),
                        CAST(:lat AS double precision)
                    ),
                    4326
                ),
                :status,
                :sido, :sigungu, :bjd, CAST(:updated_at AS timestamptz),
                CASE
                    WHEN CAST(:soft_deleted AS boolean)
                    THEN CAST(:updated_at AS timestamptz)
                END
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
            "status": status,
            "sido": sido,
            "sigungu": sigungu,
            "bjd": bjd,
            "updated_at": _NOW,
            "soft_deleted": soft_deleted,
        },
    )
    # T-VN-35(ADR-086): kind별 값의 정본은 subtype이다 — core INSERT만으로는
    # 조립 뷰가 돌려주는 detail이 비어 있다.
    await seed_feature_subtype(
        session, feature_id=feature_id, kind=kind, detail=json.loads(detail)
    )
    await session.flush()


# 상태 matrix: (suffix, status, soft_deleted, 기대 공개 여부).
# - retired          → provider retire 경로 (F-1 방향 1)
# - admin-inactive   → admin deactivate 경로: deleted_at 미세팅 (F-1 방향 2)
# - active+deleted_at → 결합 CHECK 부재로 가능한 비정합 조합 — 방어적으로 비공개
_STATE_MATRIX: tuple[tuple[str, str, bool, bool], ...] = (
    ("active", "active", False, True),
    ("retired", "inactive", True, False),
    ("admin-inactive", "inactive", False, False),
    ("draft", "draft", False, False),
    ("broken", "broken", False, False),
    ("hidden", "hidden", False, False),
    ("deleted", "deleted", True, False),
    ("active-souldel", "active", True, False),
)


async def _seed_matrix(
    session: AsyncSession, prefix: str, *, name_token: str, **kw: Any
) -> dict[str, str]:
    """상태 matrix fixture 8종을 넣고 suffix→feature_id 매핑을 돌려준다."""
    ids: dict[str, str] = {}
    for i, (suffix, status, soft_deleted, _public) in enumerate(_STATE_MATRIX):
        fid = f"{prefix}:{suffix}"
        await _ins_feature(
            session,
            feature_id=fid,
            name=f"{name_token} {suffix}",
            status=status,
            soft_deleted=soft_deleted,
            # 같은 좌표에 몰리지 않게 미세 offset (bbox/반경 안 유지).
            lon=126.978 + i * 0.0001,
            lat=37.5665 + i * 0.0001,
            **kw,
        )
        ids[suffix] = fid
    return ids


def _expected_public(ids: dict[str, str]) -> set[str]:
    return {ids[suffix] for suffix, _s, _d, public in _STATE_MATRIX if public}


async def test_view_exists_with_single_predicate(migrated_session: AsyncSession) -> None:
    """0059가 만든 view의 술어가 ADR-067 매핑(status='active' AND deleted_at IS NULL)이다."""
    viewdef = (
        await migrated_session.execute(
            text("SELECT pg_get_viewdef('feature.public_features'::regclass, true)")
        )
    ).scalar_one()
    # pg_get_viewdef는 text 캐스트를 명시해 돌려준다: status::text = 'active'::text
    assert re.search(r"status(::text)? = 'active'(::text)?", viewdef)
    assert "deleted_at IS NULL" in viewdef


async def test_view_membership_matches_state_matrix(migrated_session: AsyncSession) -> None:
    ids = await _seed_matrix(migrated_session, "pfv:member", name_token="멤버십장소")
    rows = (
        await migrated_session.execute(
            text(
                "SELECT feature_id FROM feature.public_features "
                "WHERE feature_id LIKE 'pfv:member:%'"
            )
        )
    ).scalars()
    assert set(rows) == _expected_public(ids) == {ids["active"]}


async def test_bbox_cluster_search_nearby_share_projection(
    migrated_session: AsyncSession,
) -> None:
    """bbox(경량/geometry)·cluster·search(q/bbox)·nearby가 같은 공개 집합을 돌려준다."""
    ids = await _seed_matrix(migrated_session, "pfv:paths", name_token="교차로장소")
    public = _expected_public(ids)

    bbox_rows = await feature_repo.features_in_bbox(
        migrated_session, **_BBOX, price_stale_hide_days=None
    )
    assert {r["feature_id"] for r in bbox_rows} == public

    bbox_geom_rows = await feature_repo.features_in_bbox(
        migrated_session, **_BBOX, include_geometry=True, price_stale_hide_days=None
    )
    assert {r["feature_id"] for r in bbox_geom_rows} == public

    clusters = await feature_repo.cluster_features_in_bbox(
        migrated_session, **_BBOX, cluster_unit="sigungu"
    )
    assert {c["cluster_key"]: c["feature_count"] for c in clusters} == {"11140": 1}

    search_q = await feature_repo.search_features(
        migrated_session,
        q="교차로장소",
        include_total=True,
        cursor_signing_key=_SEARCH_CURSOR_KEY,
    )
    assert {item.feature_id for item in search_q.items} == public
    assert search_q.total_count == len(public)

    search_bbox = await feature_repo.search_features(
        migrated_session,
        bbox=(_BBOX["min_lon"], _BBOX["min_lat"], _BBOX["max_lon"], _BBOX["max_lat"]),
        cursor_signing_key=_SEARCH_CURSOR_KEY,
    )
    assert {item.feature_id for item in search_bbox.items} == public

    nearby = await feature_repo.features_nearby(
        migrated_session, lon=126.978, lat=37.5665, radius_m=500.0, limit=50
    )
    assert {item.feature_id for item in nearby.items} == public

    # 공개 status 필터는 projection과 교집합 — 비공개 status 요청은 노출이 아니라 빈 결과.
    nearby_inactive = await feature_repo.features_nearby(
        migrated_session,
        lon=126.978,
        lat=37.5665,
        radius_m=500.0,
        statuses=("inactive",),
        limit=50,
    )
    assert nearby_inactive.items == ()


async def test_detail_and_batch_rows_use_projection(migrated_session: AsyncSession) -> None:
    """단건(detail)·batch가 F-1 양방향 모두에서 view와 같은 판정을 내린다."""
    ids = await _seed_matrix(migrated_session, "pfv:detail", name_token="상세장소")

    # 방향 2: admin-inactive/draft/broken/hidden은 found로 노출되면 안 된다.
    # 방향 1: retired는 일관되게 비공개(payload 없음)다.
    for suffix, _status, _deleted, public in _STATE_MATRIX:
        row = await feature_repo.get_public_feature_row(migrated_session, ids[suffix])
        assert (row is not None) is public, f"single read mismatch for {suffix}"

    all_ids = [ids[suffix] for suffix, *_ in _STATE_MATRIX] + ["pfv:detail:ghost"]
    rows = await feature_repo.get_public_feature_rows_by_ids(migrated_session, all_ids)
    assert set(rows) == _expected_public(ids)
    # raw read(admin/감사)는 기존 계약 유지 — 전 상태 반환.
    raw = await feature_repo.get_feature_rows_by_ids(migrated_session, all_ids)
    assert set(raw) == {ids[suffix] for suffix, *_ in _STATE_MATRIX}


async def test_service_batch_classifies_five_states_in_request_order(
    migrated_session: AsyncSession,
) -> None:
    ids = await _seed_matrix(migrated_session, "pfv:service", name_token="서비스장소")
    unchanged_id = "pfv:service:unchanged"
    await _ins_feature(
        migrated_session,
        feature_id=unchanged_id,
        name="변경 없는 서비스장소",
    )
    unchanged_row = await feature_repo.get_public_feature_row(migrated_session, unchanged_id)
    assert unchanged_row is not None

    requested = (
        (ids["active"], None),
        (ids["retired"], None),
        (ids["admin-inactive"], None),
        ("pfv:service:ghost", None),
        (unchanged_id, int(unchanged_row["row_revision"])),
    )
    batch = await feature_repo.get_service_feature_batch_items(migrated_session, requested)

    assert [item.feature_id for item in batch] == [feature_id for feature_id, _ in requested]
    assert [item.state for item in batch] == [
        "found",
        "retired",
        "suppressed",
        "missing",
        "unchanged",
    ]
    assert batch[0].trip_card == {
        "feature_id": ids["active"],
        "kind": "place",
        "name": "서비스장소 active",
        "category": "06020000",
        "lon": 126.978,
        "lat": 37.5665,
        "address": {},
        "marker_icon": None,
        "marker_color": None,
    }
    assert batch[0].row_revision is not None
    assert batch[1].row_revision is not None
    assert batch[2].row_revision is not None
    assert batch[3].row_revision is None
    assert batch[4].row_revision == unchanged_row["row_revision"]
    assert all(item.trip_card is None for item in batch[1:])


async def test_nearby_by_target_uses_projection(migrated_session: AsyncSession) -> None:
    ids = await _seed_matrix(migrated_session, "pfv:target", name_token="타깃장소")
    target = await upsert_poi_cache_target(
        migrated_session,
        external_system="external-app",
        target_key="public-view-matrix",
        lon=126.978,
        lat=37.5665,
        radius_km=1.0,
    )
    page = await feature_repo.features_nearby_poi_cache_target(
        migrated_session, target_id=target.target_id, limit=50
    )
    assert {item.feature_id for item in page.items} == _expected_public(ids)


async def test_contained_in_area_uses_projection(migrated_session: AsyncSession) -> None:
    ids = await _seed_matrix(migrated_session, "pfv:area", name_token="구역내장소")
    polygon = "POLYGON((126.9 37.5, 127.1 37.5, 127.1 37.7, 126.9 37.7, 126.9 37.5))"
    for area_id, area_status in (("pfv:area:zone", "active"), ("pfv:area:zone-off", "inactive")):
        # T-VN-35(ADR-086): geometry 정본은 ``feature_areas``다(core에 geom 없음).
        await migrated_session.execute(
            text(
                """
                INSERT INTO feature.features (
                    feature_id, kind, name, category, status, updated_at
                )
                VALUES (:fid, 'area', '검증 구역', '03000000', :status, :ts)
                """
            ),
            {"fid": area_id, "status": area_status, "ts": _NOW},
        )
        await seed_feature_subtype(
            migrated_session,
            feature_id=area_id,
            kind="area",
            detail={"area_kind": "area"},
            geom_wkt=polygon,
        )
    await migrated_session.flush()

    rows = await feature_repo.features_contained_in_area(
        migrated_session, feature_id="pfv:area:zone", kinds=["place"]
    )
    assert {r["feature_id"] for r in rows} == _expected_public(ids)

    # 비공개 area 자체는 공개 in-area 조회의 기준이 될 수 없다.
    off_rows = await feature_repo.features_contained_in_area(
        migrated_session, feature_id="pfv:area:zone-off", kinds=["place"]
    )
    assert off_rows == []


async def test_notice_public_ids_use_projection(migrated_session: AsyncSession) -> None:
    ids = await _seed_matrix(migrated_session, "pfv:notice", name_token="공지", kind="notice")
    visible = set(
        await feature_repo.public_active_notice_feature_identities(
            migrated_session, [ids[suffix] for suffix, *_ in _STATE_MATRIX]
        )
    )
    assert visible == _expected_public(ids)


async def test_public_beach_views_use_projection(migrated_session: AsyncSession) -> None:
    ids = await _seed_matrix(
        migrated_session,
        "pfv:beach",
        name_token="해수욕장",
        category="01050100",
        detail='{"place_kind": "beach"}',
    )
    page = await public_views_repo.list_public_beaches(migrated_session)
    listed = {row.feature_id for row in page.items if row.feature_id.startswith("pfv:beach:")}
    assert listed == _expected_public(ids)

    markers = await public_views_repo.list_public_beach_markers(migrated_session)
    marker_ids = {m.feature_id for m in markers if m.feature_id.startswith("pfv:beach:")}
    assert marker_ids == _expected_public(ids)

    for suffix, _status, _deleted, public in _STATE_MATRIX:
        row = await public_views_repo.get_public_beach(migrated_session, feature_id=ids[suffix])
        assert (row is not None) is public, f"beach detail mismatch for {suffix}"


async def test_weather_anchor_skips_non_public_features(
    migrated_session: AsyncSession,
) -> None:
    """nearest weather anchor가 비공개 feature를 건너뛴다 (공개 표면 feature_id 노출)."""
    await _ins_feature(
        migrated_session,
        feature_id="pfv:wx:center",
        name="날씨 중심",
        lon=126.978,
        lat=37.5665,
    )
    # 더 가까운 hidden anchor + 더 먼 active anchor — hidden이 이기면 leak.
    await _ins_feature(
        migrated_session,
        feature_id="pfv:wx:hidden-near",
        name="비공개 관측점",
        status="hidden",
        lon=126.9781,
        lat=37.5666,
    )
    await _ins_feature(
        migrated_session,
        feature_id="pfv:wx:active-far",
        name="공개 관측점",
        lon=126.99,
        lat=37.57,
    )
    for i, fid in enumerate(["pfv:wx:hidden-near", "pfv:wx:active-far"]):
        await migrated_session.execute(
            text(
                """
                INSERT INTO feature.feature_weather_values (
                    weather_value_key, feature_id, provider, weather_domain,
                    forecast_style, metric_key, value_number, issued_at, valid_at
                )
                VALUES (
                    :key, :fid, 'python-kma-api', 'kma_ultra_short_forecast',
                    'ultra_short', 'T1H', 21.5, :ts, :ts
                )
                """
            ),
            {"key": f"pfv-wx-{i}", "fid": fid, "ts": _NOW},
        )
    await migrated_session.flush()

    anchor = await weather_repo.nearest_weather_feature_for_coordinate(
        migrated_session, lon=126.978, lat=37.5665, radius_m=50_000
    )
    assert anchor is not None
    assert anchor.feature_id == "pfv:wx:active-far"

    by_feature = await weather_repo.nearest_weather_feature_for_feature(
        migrated_session, feature_id="pfv:wx:center", radius_m=50_000
    )
    assert by_feature is not None
    assert by_feature.feature_id == "pfv:wx:active-far"

    # 비공개 feature를 target으로 한 anchor 탐색은 빈 결과(존재 은닉).
    hidden_target = await weather_repo.nearest_weather_feature_for_feature(
        migrated_session, feature_id="pfv:wx:hidden-near", radius_m=50_000
    )
    assert hidden_target is None


async def _seed_curation_foundation(session: AsyncSession) -> tuple[str, str]:
    theme_id = str(
        (
            await session.execute(
                text(
                    """
                    INSERT INTO feature.curated_themes (
                        theme_slug, theme_name, theme_description, theme_group,
                        default_curated, visibility, metadata
                    ) VALUES (
                        'pfv-matrix-theme', '공개 matrix 테마', '', 'official',
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
                        'python-mcst-api', 'pfv-matrix-source', '테스트 출처',
                        'manual', 'unknown', 'manual_only', '{}'::jsonb
                    )
                    RETURNING source_id::text
                    """
                )
            )
        ).scalar_one()
    )
    return theme_id, source_id


async def test_curation_group_reads_use_projection(migrated_session: AsyncSession) -> None:
    """공개 curation group read(collection 표면)가 비공개 feature를 숨긴다."""
    theme_id, source_id = await _seed_curation_foundation(migrated_session)
    collection = await curation_repo.create_curation_collection(
        migrated_session,
        collection_key="pfv-matrix:2026",
        theme_id=theme_id,
        source_id=source_id,
        title="공개 matrix 컬렉션",
        edition_key="2026",
        status="published",
        visibility="public",
    )
    # add_curation_item의 write-side 검증(NOT IN deleted/hidden)은 admin 계약 —
    # draft/inactive 연결은 허용된다. 공개 read가 그걸 숨기는지가 이 테스트의 대상.
    for suffix in ("active", "admin-inactive", "draft"):
        await _ins_feature(
            migrated_session,
            feature_id=f"pfv:cur:{suffix}",
            name=f"큐레이션 {suffix}",
            status={"active": "active", "admin-inactive": "inactive", "draft": "draft"}[suffix],
        )
        await curation_repo.add_curation_item(
            migrated_session,
            collection_id=collection.collection_id,
            feature_id=f"pfv:cur:{suffix}",
            external_item_id=f"pfv-{suffix}",
            status="included",
            sort_order=1,
        )

    groups, _cursor = await curation_repo.list_feature_curation_groups(
        migrated_session, public_only=True, theme_slug="pfv-matrix-theme"
    )
    assert {g.feature_id for g in groups} == {"pfv:cur:active"}

    active_group = await curation_repo.get_feature_curation_group(
        migrated_session, feature_id="pfv:cur:active", public_only=True
    )
    assert active_group is not None
    for hidden in ("pfv:cur:admin-inactive", "pfv:cur:draft"):
        group = await curation_repo.get_feature_curation_group(
            migrated_session, feature_id=hidden, public_only=True
        )
        assert group is None, f"non-public feature exposed via curation group: {hidden}"


async def test_curated_public_read_uses_projection_admin_unchanged(
    migrated_session: AsyncSession,
) -> None:
    """공개 curated read는 public theme의 curated overlay만 노출한다 (리뷰 S1)."""
    theme_id, source_id = await _seed_curation_foundation(migrated_session)
    for suffix, status in (("active", "active"), ("admin-inactive", "inactive")):
        await _ins_feature(
            migrated_session,
            feature_id=f"pfv:curated:{suffix}",
            name=f"레거시 큐레이션 {suffix}",
            status=status,
        )
        await curated_repo.create_curated_feature(
            migrated_session,
            theme_id=theme_id,
            feature_id=f"pfv:curated:{suffix}",
            source_id=source_id,
            curation_status="curated",
        )

    admin_theme = await curated_repo.create_curated_theme(
        migrated_session,
        theme_slug="pfv-admin-only-theme",
        theme_name="관리자 전용 테마",
        theme_group="internal",
        visibility="admin_only",
    )
    overlay_cases = (
        ("admin-theme", admin_theme.theme_id, "curated"),
        ("candidate", theme_id, "candidate"),
        ("rejected", theme_id, "rejected"),
    )
    restricted_overlays = []
    for suffix, overlay_theme_id, curation_status in overlay_cases:
        await _ins_feature(
            migrated_session,
            feature_id=f"pfv:curated:{suffix}",
            name=f"제한 큐레이션 {suffix}",
        )
        restricted_overlays.append(
            await curated_repo.create_curated_feature(
                migrated_session,
                theme_id=overlay_theme_id,
                feature_id=f"pfv:curated:{suffix}",
                source_id=source_id,
                curation_status=curation_status,
                selected_by="private-operator",
                rejected_by=("private-reviewer" if curation_status == "rejected" else None),
                rejection_reason=("internal reason" if curation_status == "rejected" else None),
                metadata={"internal": True},
            )
        )

    public_page = await curated_repo.list_curated_features(
        migrated_session, public_only=True
    )
    assert {row.feature_id for row in public_page.items} == {"pfv:curated:active"}
    rejected_public_page = await curated_repo.list_curated_features(
        migrated_session, curation_status="rejected", public_only=True
    )
    assert rejected_public_page.items == ()

    admin_page = await curated_repo.list_curated_features(
        migrated_session, curation_status=None
    )
    assert {row.feature_id for row in admin_page.items} == {
        "pfv:curated:active",
        "pfv:curated:admin-inactive",
        "pfv:curated:admin-theme",
        "pfv:curated:candidate",
        "pfv:curated:rejected",
    }

    # 단건: 공개는 비공개 feature에서 None, admin은 조회 가능.
    inactive_curated = next(
        row for row in admin_page.items if row.feature_id == "pfv:curated:admin-inactive"
    )
    assert (
        await curated_repo.get_curated_feature(
            migrated_session,
            curated_feature_id=inactive_curated.curated_feature_id,
            public_only=True,
        )
        is None
    )
    assert (
        await curated_repo.get_curated_feature(
            migrated_session,
            curated_feature_id=inactive_curated.curated_feature_id,
        )
        is not None
    )
    for restricted in restricted_overlays:
        assert (
            await curated_repo.get_curated_feature(
                migrated_session,
                curated_feature_id=restricted.curated_feature_id,
                public_only=True,
            )
            is None
        )

    admin_collection = await curation_repo.create_curation_collection(
        migrated_session,
        collection_key="pfv-admin-only:2026",
        theme_id=admin_theme.theme_id,
        source_id=source_id,
        title="관리자 전용 테마의 공개 표시 컬렉션",
        edition_key="2026",
        status="published",
        visibility="public",
    )
    admin_theme_feature_id = "pfv:curation:admin-theme"
    await _ins_feature(
        migrated_session,
        feature_id=admin_theme_feature_id,
        name="관리자 전용 큐레이션 연결 장소",
    )
    await curation_repo.add_curation_item(
        migrated_session,
        collection_id=admin_collection.collection_id,
        feature_id=admin_theme_feature_id,
        external_item_id="pfv-admin-theme-item",
        status="included",
        metadata={"internal": True},
    )
    public_collections, _cursor = await curation_repo.list_curation_collections(
        migrated_session, public_only=True
    )
    assert admin_collection.collection_id not in {
        collection.collection_id for collection in public_collections
    }
    assert (
        await curation_repo.get_curation_collection(
            migrated_session,
            collection_id=admin_collection.collection_id,
            public_only=True,
        )
        is None
    )
    public_groups, _cursor = await curation_repo.list_feature_curation_groups(
        migrated_session, public_only=True
    )
    assert admin_theme_feature_id not in {group.feature_id for group in public_groups}
    assert (
        await curation_repo.get_feature_curation_group(
            migrated_session,
            feature_id=admin_theme_feature_id,
            public_only=True,
        )
        is None
    )
    assert (
        await curation_repo.list_curation_items_by_feature_ids(
            migrated_session,
            feature_ids=[admin_theme_feature_id],
            public_only=True,
        )
        == {}
    )
    admin_items = await curation_repo.list_curation_items_by_feature_ids(
        migrated_session,
        feature_ids=[admin_theme_feature_id],
        public_only=False,
    )
    assert admin_items[admin_theme_feature_id][0].metadata == {"internal": True}


async def test_ended_notice_is_hidden_from_curation_and_curated_surfaces(
    migrated_session: AsyncSession,
) -> None:
    """종료 notice가 feature detail 밖 큐레이션 표면에서 재노출되지 않는다 (S2)."""
    theme_id, source_id = await _seed_curation_foundation(migrated_session)
    feature_id = "pfv:notice:ended"
    await _ins_feature(
        migrated_session,
        feature_id=feature_id,
        name="종료된 공개 특보",
        kind="notice",
        detail=json.dumps({"valid_end_time": "2000-01-01T00:00:00+00:00"}),
    )
    overlay = await curated_repo.create_curated_feature(
        migrated_session,
        theme_id=theme_id,
        feature_id=feature_id,
        source_id=source_id,
        curation_status="curated",
    )
    collection = await curation_repo.create_curation_collection(
        migrated_session,
        collection_key="pfv-ended-notice:2026",
        theme_id=theme_id,
        source_id=source_id,
        title="종료 notice 컬렉션",
        edition_key="2026",
        status="published",
        visibility="public",
    )
    await curation_repo.add_curation_item(
        migrated_session,
        collection_id=collection.collection_id,
        feature_id=feature_id,
        external_item_id="pfv-ended-notice",
        status="included",
    )

    assert (
        await curated_repo.get_curated_feature(
            migrated_session,
            curated_feature_id=overlay.curated_feature_id,
            public_only=True,
        )
        is None
    )
    public_overlays = await curated_repo.list_curated_features(
        migrated_session, theme_slug="pfv-matrix-theme", public_only=True
    )
    assert feature_id not in {item.feature_id for item in public_overlays.items}
    assert (
        await curation_repo.get_feature_curation_group(
            migrated_session, feature_id=feature_id, public_only=True
        )
        is None
    )
    collection_result = await curation_repo.get_curation_collection(
        migrated_session, collection_id=collection.collection_id, public_only=True
    )
    assert collection_result is not None
    public_collection, items = collection_result
    assert items == ()
    assert public_collection.item_count == public_collection.public_item_count == 0


async def test_category_counts_use_projection(migrated_session: AsyncSession) -> None:
    ids = await _seed_matrix(
        migrated_session, "pfv:count", name_token="집계장소", category="09990001"
    )
    counts = await feature_repo.category_feature_counts(migrated_session)
    assert counts.get("09990001", 0) == len(_expected_public(ids))


async def test_collection_items_redact_non_public_linked_features(
    migrated_session: AsyncSession,
) -> None:
    """공개 collection은 비공개 연결 item 전체를 SQL에서 제외한다 (리뷰 S2).

    feature 이름을 ``place_name``으로 자동 복제하고 CSV가 ``address_hint``와
    metadata를 저장하므로 Python에서 feature 필드 일부만 NULL 처리해서는 비공개
    전환 뒤에도 장소 정보를 숨길 수 없다. 공개 SQL은 연결 feature가 최종 공개
    집합에 없으면 item 자체를 반환하지 않고, 공식 미연결 item은 유지한다.
    """
    theme_id, source_id = await _seed_curation_foundation(migrated_session)
    collection = await curation_repo.create_curation_collection(
        migrated_session,
        collection_key="pfv-items:2026",
        theme_id=theme_id,
        source_id=source_id,
        title="공개 item matrix 컬렉션",
        edition_key="2026",
        status="published",
        visibility="public",
    )
    # 연결 시점에는 전부 active로 넣고 이후 상태를 바꾼다 — write-side 검증
    # (NOT IN deleted/hidden)은 admin 계약이라 "연결 후 상태 변경" 시나리오가
    # 실제 leak 경로다.
    for i, (suffix, *_rest) in enumerate(_STATE_MATRIX):
        await _ins_feature(
            migrated_session,
            feature_id=f"pfv:item:{suffix}",
            name=f"아이템장소 {suffix}",
            lon=126.978 + i * 0.0001,
            lat=37.5665 + i * 0.0001,
        )
        await curation_repo.add_curation_item(
            migrated_session,
            collection_id=collection.collection_id,
            feature_id=f"pfv:item:{suffix}",
            external_item_id=f"pfv-item-{suffix}",
            place_name=f"복제 장소명 {suffix}",
            address_hint=f"복제 주소 {suffix}",
            status="included",
            sort_order=i,
            metadata={"copied_name": f"아이템장소 {suffix}"},
        )
    await curation_repo.add_curation_item(
        migrated_session,
        collection_id=collection.collection_id,
        feature_id=None,
        external_item_id="pfv-item-unlinked",
        place_name="공식 미연결 장소",
        address_hint="공식 주소",
        status="included",
        sort_order=len(_STATE_MATRIX),
        metadata={"official": True},
    )
    for suffix, status, soft_deleted, _public in _STATE_MATRIX:
        await migrated_session.execute(
            text(
                """
                UPDATE feature.features
                SET status = :status,
                    deleted_at = CASE
                        WHEN CAST(:soft_deleted AS boolean)
                        THEN CAST(:ts AS timestamptz)
                    END
                WHERE feature_id = :fid
                """
            ),
            {
                "status": status,
                "soft_deleted": soft_deleted,
                "ts": _NOW,
                "fid": f"pfv:item:{suffix}",
            },
        )
    await migrated_session.flush()

    result = await curation_repo.get_curation_collection(
        migrated_session, collection_id=collection.collection_id, public_only=True
    )
    assert result is not None
    row, items = result
    by_external = {item.external_item_id: item for item in items}
    assert set(by_external) == {"pfv-item-active", "pfv-item-unlinked"}
    active = by_external["pfv-item-active"]
    assert active.feature_id == "pfv:item:active"
    assert active.feature_name == "아이템장소 active"
    assert active.lon is not None
    assert active.lat is not None
    assert by_external["pfv-item-unlinked"].feature_id is None
    assert row.item_count == row.public_item_count == 2

    admin_result = await curation_repo.get_curation_collection(
        migrated_session, collection_id=collection.collection_id
    )
    assert admin_result is not None
    _admin_row, admin_items = admin_result
    assert len(admin_items) == len(_STATE_MATRIX) + 1
    hidden = next(item for item in admin_items if item.external_item_id == "pfv-item-hidden")
    assert hidden.place_name == "복제 장소명 hidden"
    assert hidden.address_hint == "복제 주소 hidden"
    assert hidden.metadata == {"copied_name": "아이템장소 hidden"}


async def test_weather_alert_history_hides_non_public_anchor(
    migrated_session: AsyncSession,
) -> None:
    """특보 이력은 alert row를 보존하되 비공개 anchor의 feature 필드는 NULL이다 (리뷰 S2)."""
    for fid, status in (("pfv:alert:active", "active"), ("pfv:alert:hidden", "hidden")):
        await _ins_feature(
            migrated_session, feature_id=fid, name=f"특보 {status}", status=status, kind="notice"
        )
    for i, fid in enumerate(["pfv:alert:active", "pfv:alert:hidden"]):
        entity_key = f"se_pfv_alert_{i}"
        raw_data = {
            "alert_id": f"PFV-{i}",
            "phenomenon": "호우",
            "level": "주의보",
            "title": "호우주의보",
            "issued_at": _NOW.isoformat(),
            "region_code": "99Z99999",
            "region_name": "검증구역",
        }
        await migrated_session.execute(
            text(
                """
                INSERT INTO provider_sync.source_entities (
                    source_entity_key, provider, dataset_key, source_entity_type,
                    source_entity_id, first_seen_at, last_seen_at
                )
                VALUES (
                    :entity_key, 'python-kma-api', 'kma_weather_alerts',
                    'weather_alert', :entity_id, :ts, :ts
                )
                """
            ),
            {"entity_key": entity_key, "entity_id": f"99Z99999::호우::{i}", "ts": _NOW},
        )
        await migrated_session.execute(
            text(
                """
                INSERT INTO provider_sync.source_records (
                    source_record_key, source_entity_key,
                    provider, dataset_key, source_entity_type,
                    source_entity_id, raw_name, raw_data,
                    raw_payload_hash, fetched_at
                )
                VALUES (
                    :record_key, :entity_key,
                    'python-kma-api', 'kma_weather_alerts',
                    'weather_alert', :entity_id, '호우주의보',
                    CAST(:raw_data AS jsonb), :payload_hash, :ts
                )
                """
            ),
            {
                "record_key": f"sr_pfv_alert_{i}",
                "entity_key": entity_key,
                "entity_id": f"99Z99999::호우::{i}",
                "raw_data": json.dumps(raw_data),
                "payload_hash": f"hash-pfv-alert-{i}",
                "ts": _NOW,
            },
        )
        await migrated_session.execute(
            text(
                """
                INSERT INTO provider_sync.source_links (
                    feature_id, source_entity_key, source_role, match_method,
                    confidence, is_primary_source
                )
                VALUES (:fid, :entity_key, 'primary', 'natural_key', 100, true)
                """
            ),
            {"fid": fid, "entity_key": entity_key},
        )
    await migrated_session.flush()

    rows = await weather_repo.list_kma_weather_alert_history(
        migrated_session, region_code="99Z99999"
    )
    by_key = {row.source_record_key: row for row in rows}
    # alert row 2건 모두 생존 — 기상특보 자체는 anchor 공개 여부와 무관한 정보다.
    assert set(by_key) == {"sr_pfv_alert_0", "sr_pfv_alert_1"}
    assert by_key["sr_pfv_alert_0"].feature_id == "pfv:alert:active"
    assert by_key["sr_pfv_alert_0"].feature_name == "특보 active"
    # 비공개 anchor는 feature 필드가 NULL로 떨어진다 (이름/상태 leak 차단).
    assert by_key["sr_pfv_alert_1"].feature_id is None
    assert by_key["sr_pfv_alert_1"].feature_name is None
