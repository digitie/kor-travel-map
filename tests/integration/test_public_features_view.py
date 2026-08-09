"""ADR-067 공개 projection의 3축 상태 matrix 통합 테스트.

T-VN-34B에서 ``feature.public_features``는 lifecycle=active,
publication=published, quality=valid의 교집합만 노출한다. retired lifecycle은
항상 숨기고, active지만 draft/suppressed publication 또는 quarantined quality인
행도 같은 공개 경로 어디에서도 노출하지 않는다.

상태별 fixture × 공개 read 경로(detail/batch/bbox/cluster/search/nearby/
in-area/collection/curated/weather anchor/public views) 교차 검사.
공개 술어는 alembic 0096의 VIEW 한 곳에만 정의된다 — 본 테스트는 그 술어의
소비자들이 전부 같은 판정을 내리는지 검증한다.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal
from hashlib import md5
from typing import TYPE_CHECKING, Any

import pytest
from sqlalchemy import text

from kortravelmap.core.ids import make_payload_hash, make_source_record_key
from kortravelmap.dto import SourceRecord
from kortravelmap.dto.weather import WeatherValue
from kortravelmap.infra import (
    curated_repo,
    curation_repo,
    feature_repo,
    public_views_repo,
    weather_repo,
)
from kortravelmap.infra.poi_cache_target_repo import upsert_poi_cache_target
from tests.integration._subtype_seed import seed_feature_subtype
from tests.integration.perf_gate import explain_plan, index_names

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
    lifecycle_state: str = "active",
    publication_state: str = "published",
    quality_state: str = "valid",
    kind: str = "place",
    category: str = "06020000",
    lon: float = 126.978,
    lat: float = 37.5665,
    detail: str = "{}",
    geom_wkt: str | None = None,
    sido: str = "11",
    sigungu: str = "11140",
    bjd: str = "1114010100",
) -> None:
    await session.execute(
        text(
            """
            INSERT INTO feature.features (
                feature_id, kind, name, category, coord,
                lifecycle_state, publication_state, quality_state,
                sido_code, sigungu_code, legal_dong_code, updated_at
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
                :lifecycle_state, :publication_state, :quality_state,
                :sido, :sigungu, :bjd, CAST(:updated_at AS timestamptz)
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
            "lifecycle_state": lifecycle_state,
            "publication_state": publication_state,
            "quality_state": quality_state,
            "sido": sido,
            "sigungu": sigungu,
            "bjd": bjd,
            "updated_at": _NOW,
        },
    )
    # T-VN-35(ADR-086): kind별 값의 정본은 subtype이다 — core INSERT만으로는
    # 조립 뷰가 돌려주는 detail이 비어 있다.
    await seed_feature_subtype(
        session,
        feature_id=feature_id,
        kind=kind,
        detail=json.loads(detail),
        geom_wkt=geom_wkt,
    )
    await session.flush()


# 유효한 3축 tuple 전체: active 3×2 조합과 retired/suppressed 2조합.
_STATE_MATRIX: tuple[tuple[str, str, str, str, bool], ...] = (
    ("active", "active", "published", "valid", True),
    ("quarantined", "active", "published", "quarantined", False),
    ("draft", "active", "draft", "valid", False),
    ("draft-quarantined", "active", "draft", "quarantined", False),
    ("suppressed", "active", "suppressed", "valid", False),
    ("suppressed-quarantined", "active", "suppressed", "quarantined", False),
    ("retired", "retired", "suppressed", "valid", False),
    ("retired-quarantined", "retired", "suppressed", "quarantined", False),
)


async def _seed_matrix(
    session: AsyncSession, prefix: str, *, name_token: str, **kw: Any
) -> dict[str, str]:
    """유효 3축 상태 matrix 8종을 넣고 suffix→feature_id 매핑을 돌려준다."""
    ids: dict[str, str] = {}
    for i, (suffix, lifecycle_state, publication_state, quality_state, _public) in enumerate(
        _STATE_MATRIX
    ):
        fid = f"{prefix}:{suffix}"
        await _ins_feature(
            session,
            feature_id=fid,
            name=f"{name_token} {suffix}",
            lifecycle_state=lifecycle_state,
            publication_state=publication_state,
            quality_state=quality_state,
            # 같은 좌표에 몰리지 않게 미세 offset (bbox/반경 안 유지).
            lon=126.978 + i * 0.0001,
            lat=37.5665 + i * 0.0001,
            **kw,
        )
        ids[suffix] = fid
    return ids


def _expected_public(ids: dict[str, str]) -> set[str]:
    return {ids[suffix] for suffix, _l, _p, _q, public in _STATE_MATRIX if public}


async def test_view_exists_with_single_predicate(migrated_session: AsyncSession) -> None:
    """0096 view가 ADR-067의 3축 공개 predicate를 단독으로 가진다."""
    viewdef = (
        await migrated_session.execute(
            text("SELECT pg_get_viewdef('feature.public_features'::regclass, true)")
        )
    ).scalar_one()
    for column, value in (
        ("lifecycle_state", "active"),
        ("publication_state", "published"),
        ("quality_state", "valid"),
    ):
        assert re.search(rf"{column}(::text)? = '{value}'(::text)?", viewdef)
    # legacy status는 반환 shape에 남아도 predicate가 되어서는 안 된다.
    assert re.search(r"\bstatus(::text)?\s*=", viewdef) is None
    assert re.search(r"\bdeleted_at\s+IS\s+NULL\b", viewdef) is None


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

    # ``statuses``는 T-VN-34C가 제거할 때까지 남는 폐기 예정 인자일 뿐, 전달 값으로
    # 3축 공개 membership을 다시 좁히거나 넓히면 안 된다.
    nearby_obsolete_status = await feature_repo.features_nearby(
        migrated_session,
        lon=126.978,
        lat=37.5665,
        radius_m=500.0,
        statuses=("hidden",),
        limit=50,
    )
    assert {item.feature_id for item in nearby_obsolete_status.items} == public


async def test_detail_and_batch_rows_use_projection(migrated_session: AsyncSession) -> None:
    """단건(detail)·batch가 F-1 양방향 모두에서 view와 같은 판정을 내린다."""
    ids = await _seed_matrix(migrated_session, "pfv:detail", name_token="상세장소")

    # active지만 비공개 tuple과 retired tuple 모두 payload 없이 숨긴다.
    for suffix, _lifecycle, _publication, _quality, public in _STATE_MATRIX:
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
        (ids["retired-quarantined"], None),
        (ids["draft"], None),
        (ids["suppressed"], None),
        (ids["quarantined"], None),
        ("pfv:service:ghost", None),
        (unchanged_id, int(unchanged_row["row_revision"])),
    )
    batch = await feature_repo.get_service_feature_batch_items(migrated_session, requested)

    assert [item.feature_id for item in batch] == [feature_id for feature_id, _ in requested]
    assert [item.state for item in batch] == [
        "found",
        "retired",
        "retired",
        "suppressed",
        "suppressed",
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
    assert batch[3].row_revision is not None
    assert batch[4].row_revision is not None
    assert batch[5].row_revision is not None
    assert batch[6].row_revision is None
    assert batch[7].row_revision == unchanged_row["row_revision"]
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
    for area_id, lifecycle_state, publication_state in (
        ("pfv:area:zone", "active", "published"),
        ("pfv:area:zone-off", "retired", "suppressed"),
    ):
        # T-VN-35(ADR-086): geometry 정본은 ``feature_areas``다(core에 geom 없음).
        await migrated_session.execute(
            text(
                """
                INSERT INTO feature.features (
                    feature_id, kind, name, category,
                    lifecycle_state, publication_state, quality_state, updated_at
                )
                VALUES (
                    :fid, 'area', '검증 구역', '03000000',
                    :lifecycle_state, :publication_state, 'valid', :ts
                )
                """
            ),
            {
                "fid": area_id,
                "lifecycle_state": lifecycle_state,
                "publication_state": publication_state,
                "ts": _NOW,
            },
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

    for suffix, _lifecycle, _publication, _quality, public in _STATE_MATRIX:
        row = await public_views_repo.get_public_beach(migrated_session, feature_id=ids[suffix])
        assert (row is not None) is public, f"beach detail mismatch for {suffix}"


async def test_public_bbox_geometry_arms_use_ready_partial_indexes(
    migrated_session: AsyncSession,
) -> None:
    """실제 공개 bbox SQL의 route/area arm이 ready partial GiST를 쓴다."""

    await _ins_feature(
        migrated_session,
        feature_id="pfv:bbox:route",
        name="bbox 경로",
        kind="route",
        category="06070000",
        geom_wkt="MULTILINESTRING((126.96 37.55,126.99 37.58))",
    )
    await _ins_feature(
        migrated_session,
        feature_id="pfv:bbox:area",
        name="bbox 구역",
        kind="area",
        category="06050000",
        geom_wkt=(
            "MULTIPOLYGON(((126.96 37.55,126.99 37.55,126.99 37.58,"
            "126.96 37.55)))"
        ),
    )
    await migrated_session.execute(text("ANALYZE feature.feature_routes"))
    await migrated_session.execute(text("ANALYZE feature.feature_areas"))

    plan = await explain_plan(
        migrated_session,
        feature_repo._FEATURES_IN_BBOX_SQL,  # noqa: PLC2701 - generated public SQL gate
        {
            "min_lon": 126.95,
            "min_lat": 37.54,
            "max_lon": 127.00,
            "max_lat": 37.59,
            "kinds": ["route", "area"],
            "categories": None,
            "providers": None,
            "cursor_feature_id": None,
            "limit": 100,
            "price_stale_hide_days": 4,
        },
        planner_default=False,
    )
    assert {
        "idx_feature_routes_geom_gist",
        "idx_feature_areas_geom_gist",
    } <= index_names(plan)


async def test_public_festival_views_use_projection(migrated_session: AsyncSession) -> None:
    """축제 목록·marker·상세도 같은 public view membership만 소비한다."""

    ids = await _seed_matrix(
        migrated_session,
        "pfv:festival",
        name_token="축제",
        kind="event",
        category="02010000",
        detail=(
            '{"event_kind": "festival", "starts_on": "2026-07-01", '
            '"ends_on": "2026-07-31"}'
        ),
    )
    page = await public_views_repo.list_public_festivals_monthly(
        migrated_session,
        month_start=date(2026, 7, 1),
        month_end=date(2026, 7, 31),
    )
    listed = {
        row.feature_id for row in page.items if row.feature_id.startswith("pfv:festival:")
    }
    assert listed == _expected_public(ids)

    markers = await public_views_repo.list_public_festival_markers(
        migrated_session,
        month_start=date(2026, 7, 1),
        month_end=date(2026, 7, 31),
    )
    marker_ids = {
        marker.feature_id
        for marker in markers
        if marker.feature_id.startswith("pfv:festival:")
    }
    assert marker_ids == _expected_public(ids)

    for suffix, _lifecycle, _publication, _quality, public in _STATE_MATRIX:
        row = await public_views_repo.get_public_festival(
            migrated_session, feature_id=ids[suffix]
        )
        assert (row is not None) is public, f"festival detail mismatch for {suffix}"


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
    # 더 가까운 suppressed anchor + 더 먼 public anchor — 전자가 이기면 leak.
    await _ins_feature(
        migrated_session,
        feature_id="pfv:wx:suppressed-near",
        name="비공개 관측점",
        publication_state="suppressed",
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
    # T-VN-38 fact는 provider-dataset + immutable response lineage가 필수다.
    # raw INSERT로 옛 provider 문자열 컬럼을 우회하지 않고 공개 anchor와 같은
    # canonical ingestion 경로로 current summary까지 만든다.
    selected_at = datetime.now(UTC)
    provider = "python-kma-api"
    dataset_key = "kma_ultra_short_forecast"
    dataset_id = await _dataset_id(migrated_session, provider, dataset_key)
    await migrated_session.execute(
        text(
            """
            INSERT INTO ops.provider_refresh_policies (
                provider_dataset_id, source_kind, stale_after_minutes
            ) VALUES (:provider_dataset_id, 'system', 60)
            ON CONFLICT (provider_dataset_id) DO UPDATE
            SET enabled = true, stale_after_minutes = EXCLUDED.stale_after_minutes
            """
        ),
        {"provider_dataset_id": dataset_id},
    )
    raw_data = {
        "metric": "T1H",
        "feature_ids": ["pfv:wx:suppressed-near", "pfv:wx:active-far"],
    }
    payload_hash = make_payload_hash(raw_data)
    source_entity_id = f"pfv-weather:{payload_hash[:20]}"
    source_record = SourceRecord(
        provider=provider,
        dataset_key=dataset_key,
        source_entity_type="weather_response",
        source_entity_id=source_entity_id,
        raw_payload_hash=payload_hash,
        raw_data=raw_data,
        fetched_at=selected_at,
        source_record_key=make_source_record_key(
            provider=provider,
            dataset_key=dataset_key,
            source_entity_type="weather_response",
            source_entity_id=source_entity_id,
            raw_payload_hash=payload_hash,
        ),
    )
    await weather_repo.load_weather_values(
        migrated_session,
        [
            WeatherValue(
                feature_id=feature_id,
                provider=provider,
                weather_domain=dataset_key,
                forecast_style="ultra_short",
                timeline_bucket="ultra_short",
                metric_key="T1H",
                value_number=Decimal("21.5"),
                unit="deg_c",
                issued_at=selected_at,
                valid_at=selected_at,
            )
            for feature_id in ("pfv:wx:suppressed-near", "pfv:wx:active-far")
        ],
        provider_dataset_id=dataset_id,
        source_record=source_record,
        selected_at=selected_at,
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
    suppressed_target = await weather_repo.nearest_weather_feature_for_feature(
        migrated_session, feature_id="pfv:wx:suppressed-near", radius_m=50_000
    )
    assert suppressed_target is None


async def _dataset_id(session: AsyncSession, provider: str, dataset_key: str) -> int:
    """fixture 전용 catalog 행을 만들고 canonical id를 돌려준다 (T-VN-33).

    provider/dataset_key 자연키 사본이 사라져 curated source·source entity는
    ``provider_dataset_id``만으로 dataset을 가리킨다.
    """

    return int(
        (
            await session.execute(
                text(
                    """
                    INSERT INTO provider_sync.provider_datasets (
                        provider, dataset_key, display_name, source_kind,
                        is_active, capabilities
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
    dataset_id = await _dataset_id(session, "python-mcst-api", "pfv-matrix-source")
    source_id = str(
        (
            await session.execute(
                text(
                    """
                    INSERT INTO feature.curated_sources (
                        provider_dataset_id, source_name, source_kind,
                        update_cycle, provider_status, metadata
                    ) VALUES (
                        :dataset_id, '테스트 출처',
                        'manual', 'unknown', 'manual_only', '{}'::jsonb
                    )
                    RETURNING source_id::text
                    """
                ),
                {"dataset_id": dataset_id},
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
    # 연결 자체의 admin 검증과 별개로, active/published/valid 밖의 tuple은
    # public read에서 숨겨져야 한다.
    for suffix, publication_state in (
        ("active", "published"),
        ("suppressed", "suppressed"),
        ("draft", "draft"),
    ):
        await _ins_feature(
            migrated_session,
            feature_id=f"pfv:cur:{suffix}",
            name=f"큐레이션 {suffix}",
            publication_state=publication_state,
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
    for hidden in ("pfv:cur:suppressed", "pfv:cur:draft"):
        group = await curation_repo.get_feature_curation_group(
            migrated_session, feature_id=hidden, public_only=True
        )
        assert group is None, f"non-public feature exposed via curation group: {hidden}"


async def test_curated_public_read_uses_projection_admin_unchanged(
    migrated_session: AsyncSession,
) -> None:
    """공개 curated read는 public theme의 curated overlay만 노출한다 (리뷰 S1)."""
    theme_id, source_id = await _seed_curation_foundation(migrated_session)
    for suffix, publication_state in (("active", "published"), ("suppressed", "suppressed")):
        await _ins_feature(
            migrated_session,
            feature_id=f"pfv:curated:{suffix}",
            name=f"레거시 큐레이션 {suffix}",
            publication_state=publication_state,
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
        "pfv:curated:suppressed",
        "pfv:curated:admin-theme",
        "pfv:curated:candidate",
        "pfv:curated:rejected",
    }

    # 단건: 공개는 비공개 feature에서 None, admin은 조회 가능.
    suppressed_curated = next(
        row for row in admin_page.items if row.feature_id == "pfv:curated:suppressed"
    )
    assert (
        await curated_repo.get_curated_feature(
            migrated_session,
            curated_feature_id=suppressed_curated.curated_feature_id,
            public_only=True,
        )
        is None
    )
    assert (
        await curated_repo.get_curated_feature(
            migrated_session,
            curated_feature_id=suppressed_curated.curated_feature_id,
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
    # 먼저 모두 public tuple로 연결한 뒤, 연결 후 3축 상태가 바뀌어도 public read가
    # 비공개 feature 자체를 redaction하는지 검증한다.
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
    for suffix, lifecycle_state, publication_state, quality_state, _public in _STATE_MATRIX:
        await migrated_session.execute(
            text(
                """
                UPDATE feature.features
                SET lifecycle_state = :lifecycle_state,
                    publication_state = :publication_state,
                    quality_state = :quality_state
                WHERE feature_id = :fid
                """
            ),
            {
                "lifecycle_state": lifecycle_state,
                "publication_state": publication_state,
                "quality_state": quality_state,
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
    suppressed = next(
        item for item in admin_items if item.external_item_id == "pfv-item-suppressed"
    )
    assert suppressed.place_name == "복제 장소명 suppressed"
    assert suppressed.address_hint == "복제 주소 suppressed"
    assert suppressed.metadata == {"copied_name": "아이템장소 suppressed"}


async def test_weather_alert_history_hides_non_public_anchor(
    migrated_session: AsyncSession,
) -> None:
    """특보 이력은 alert row를 보존하되 비공개 anchor의 feature 필드는 NULL이다 (리뷰 S2)."""
    for fid, publication_state in (
        ("pfv:alert:active", "published"),
        ("pfv:alert:suppressed", "suppressed"),
    ):
        await _ins_feature(
            migrated_session,
            feature_id=fid,
            name=f"특보 {publication_state}",
            publication_state=publication_state,
            kind="notice",
        )
    dataset_id = await _dataset_id(migrated_session, "python-kma-api", "kma_weather_alerts")
    for i, fid in enumerate(["pfv:alert:active", "pfv:alert:suppressed"]):
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
                    source_entity_key, provider_dataset_id, source_entity_type,
                    source_entity_id, first_seen_at, last_seen_at
                )
                VALUES (
                    :entity_key, :dataset_id,
                    'weather_alert', :entity_id, :ts, :ts
                )
                """
            ),
            {
                "entity_key": entity_key,
                "dataset_id": dataset_id,
                "entity_id": f"99Z99999::호우::{i}",
                "ts": _NOW,
            },
        )
        await migrated_session.execute(
            text(
                """
                INSERT INTO provider_sync.source_records (
                    source_record_key, source_entity_key, raw_data,
                    raw_payload_hash, fetched_at
                )
                VALUES (
                    :record_key, :entity_key,
                    CAST(:raw_data AS jsonb), :payload_hash, :ts
                )
                """
            ),
            {
                "record_key": f"sr_pfv_alert_{i}",
                "entity_key": entity_key,
                "raw_data": json.dumps(raw_data),
                # ck_source_records_payload_hash_canonical = ^[0-9a-f]{1,64}$
                "payload_hash": md5(f"pfv-alert-{i}".encode()).hexdigest(),
                "ts": _NOW,
            },
        )
        await migrated_session.execute(
            text(
                """
                INSERT INTO provider_sync.source_entity_heads (
                    source_entity_key, current_source_record_key, observed_at
                )
                VALUES (:entity_key, :record_key, :ts)
                """
            ),
            {
                "entity_key": entity_key,
                "record_key": f"sr_pfv_alert_{i}",
                "ts": _NOW,
            },
        )
        await migrated_session.execute(
            text(
                """
                INSERT INTO provider_sync.source_links (
                    feature_id, source_entity_key, source_role, match_method,
                    confidence
                )
                VALUES (:fid, :entity_key, 'primary', 'natural_key', 100)
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
    assert by_key["sr_pfv_alert_0"].feature_name == "특보 published"
    # 비공개 anchor는 feature 필드가 NULL로 떨어진다 (이름/상태 leak 차단).
    assert by_key["sr_pfv_alert_1"].feature_id is None
    assert by_key["sr_pfv_alert_1"].feature_name is None
