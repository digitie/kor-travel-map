"""``test_notice_lifecycle`` — notice 사건 단위 identity 라이프사이클 (#632).

``close_notice_features``(특보 해제) / ``supersede_stale_notice_features``
(계보 중복 soft-delete + feed 소멸 닫기) / ``purge_expired_notices``(§9 보존) /
사용자 활성 read 필터(계보 latest만 + 종료 notice 숨김)를 testcontainers
PostGIS로 끝까지 검증한다. 정리 마이그레이션(0040)의 KREX 술어는
``supersede_stale_notice_features``와 동일 계보/최신 판정이라 본 테스트가
사실상 그 술어의 회귀 가드다.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any
from uuid import uuid4

import pytest
from sqlalchemy import text

from kortravelmap.core.ids import (
    make_feature_id,
    make_payload_hash,
    make_source_record_key,
)
from kortravelmap.dto import (
    Address,
    Coordinate,
    Feature,
    FeatureBundle,
    FeatureKind,
    NoticeDetail,
    SourceLink,
    SourceRecord,
    SourceRole,
)
from kortravelmap.infra import admin_feature_repo, feature_repo
from kortravelmap.infra.poi_cache_target_repo import upsert_poi_cache_target
from kortravelmap.providers.kma import (
    kma_alert_notice_feature_id,
    weather_alert_lift_closures,
    weather_alerts_to_notice_bundles,
)
from tests.integration._subtype_seed import seed_feature_subtype

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

pytestmark = pytest.mark.integration

_KST = timezone(timedelta(hours=9))
_NOW = datetime(2026, 7, 3, 12, 0, tzinfo=_KST)
_SEARCH_CURSOR_KEY = b"integration-feature-search-cursor-signing-key-0001"

_KREX = "python-krex-api"
_KREX_DS = "krex_traffic_notices"
_KREX_ET = "traffic_notice"
_CROSS_PROVIDER = "python-cross-notice-api"
_CROSS_DS = "cross_notice_snapshot"
_CROSS_ET = "notice"


async def _ensure_active_provider_dataset(
    session: AsyncSession, *, provider: str, dataset_key: str
) -> None:
    """scope 분리 fixture가 쓰는 provider×dataset 정본을 final catalog에 준비한다."""
    await session.execute(
        text(
            """
            INSERT INTO provider_sync.provider_datasets (
                provider, dataset_key, display_name, source_kind, is_active
            ) VALUES (
                :provider, :dataset_key, 'notice lifecycle integration fixture',
                'manual', true
            )
            ON CONFLICT (provider, dataset_key) DO UPDATE
            SET is_active = true
            """
        ),
        {"provider": provider, "dataset_key": dataset_key},
    )


def _krex_notice_bundle(
    *,
    source_entity_id: str,
    raw_data: dict[str, Any],
    feature_suffix: str | None = None,
    lon: float = 127.1,
    lat: float = 37.4,
    valid_start: datetime | None = None,
    observed_at: datetime | None = None,
    provider: str = _KREX,
    dataset_key: str = _KREX_DS,
    source_entity_type: str = _KREX_ET,
) -> FeatureBundle:
    """계보 시뮬레이션용 KREX notice bundle.

    ``feature_suffix``를 주면 자연키에 suffix를 붙여 **다른 feature_id**를
    만든다 — 구세대(raw-hash/bjd-split) identity가 같은 계보(raw_data 단서)에
    공존하던 상황 재현.
    """
    key_for_id = f"{source_entity_id}::{feature_suffix}" if feature_suffix else source_entity_id
    feature_id = make_feature_id(
        bjd_code=None,
        kind=FeatureKind.NOTICE.value,
        category="99000000",
        source_type=f"{provider}:{dataset_key}",
        source_natural_key=key_for_id,
    )
    payload_hash = make_payload_hash(raw_data)
    source_record_key = make_source_record_key(
        provider=provider,
        dataset_key=dataset_key,
        source_entity_type=source_entity_type,
        source_entity_id=source_entity_id,
        raw_payload_hash=payload_hash,
    )
    start = valid_start or _NOW
    observed = observed_at or _NOW
    feature = Feature(
        feature_id=feature_id,
        kind=FeatureKind.NOTICE,
        name=f"[테스트] 교통 공지 {source_entity_id[-12:]}",
        coord=Coordinate(lon=lon, lat=lat),
        address=Address(),
        category="99000000",
        marker_icon="danger",
        marker_color="P-15",
        detail=NoticeDetail(
            feature_id=feature_id,
            notice_type="traffic",
            severity=None,
            valid_start_time=start,
            valid_end_time=None,
            source_agency="한국도로공사",
            payload={"domain": "highway"},
        ),
    )
    source_record = SourceRecord(
        provider=provider,
        dataset_key=dataset_key,
        source_entity_type=source_entity_type,
        source_entity_id=source_entity_id,
        raw_payload_hash=payload_hash,
        raw_data=raw_data,
        fetched_at=observed,
        imported_at=observed,
        source_record_key=source_record_key,
    )
    source_link = SourceLink(
        feature_id=feature_id,
        source_record_key=source_record_key,
        source_role=SourceRole.PRIMARY,
        match_method="natural_key",
        confidence=100,
    )
    return FeatureBundle(feature=feature, source_record=source_record, source_link=source_link)


_CLUES = {
    "occurred_date": "2026.07.03",
    "occurred_time": "07:25:43",
    "route_no": "0550",
    "direction": "부산방향",
    "point_name": "남제천(272.5k)",
    "incident_type_code": "03",
}
_LINEAGE = "2026.07.03::07:25:43::0550::부산방향::남제천(272.5k)::03"

_MULTI_CLUES_A = {
    "occurred_date": "2026.07.03",
    "occurred_time": "10:00:00",
    "route_no": "0010",
    "direction": "서울방향",
    "point_name": "다중계보-A",
    "incident_type_code": "03",
}
_MULTI_CLUES_B = {
    "occurred_date": "2026.07.03",
    "occurred_time": "10:05:00",
    "route_no": "0020",
    "direction": "부산방향",
    "point_name": "다중계보-B",
    "incident_type_code": "01",
}
_MULTI_LINEAGE_A = "2026.07.03::10:00:00::0010::서울방향::다중계보-a::03"
_MULTI_LINEAGE_B = "2026.07.03::10:05:00::0020::부산방향::다중계보-b::01"

#: notice bbox/in-area 테스트가 공유하는 area geometry (T-VN-35 이후 subtype 정본).
_AREA_WKT = "POLYGON((127.0 37.3,127.2 37.3,127.2 37.5,127.0 37.5,127.0 37.3))"


async def _seed_dup_lineage(
    session: AsyncSession,
) -> tuple[FeatureBundle, FeatureBundle]:
    """같은 계보의 서로 다른 entity 2개를 심는다 (신세대가 latest).

    ADR-063 이후 같은 ``source_entity_id``의 payload 이력은 하나의 entity/current
    관측으로 접힌다. 따라서 legacy identity 중복은 raw 계보 단서는 같되 entity
    identity가 다른 두 source로 재현해야 한다.
    """
    old_gen = _krex_notice_bundle(
        source_entity_id=f"legacy::{_LINEAGE}",
        raw_data={**_CLUES, "gen": "old"},
        feature_suffix="oldgen",
        observed_at=_NOW - timedelta(hours=2),
    )
    new_gen = _krex_notice_bundle(
        source_entity_id=_LINEAGE,
        raw_data={**_CLUES, "gen": "new"},
    )
    assert old_gen.feature.feature_id != new_gen.feature.feature_id
    assert old_gen.source_record.source_entity_id != new_gen.source_record.source_entity_id
    await feature_repo.load_bundles(session, [old_gen, new_gen])
    return old_gen, new_gen


async def _seed_multi_lineage_feature(
    session: AsyncSession,
) -> tuple[FeatureBundle, FeatureBundle, FeatureBundle]:
    """한 feature가 A 계보 winner이면서 B 계보 loser인 상태를 만든다."""
    shared = _krex_notice_bundle(
        source_entity_id="multi::shared::a",
        raw_data=_MULTI_CLUES_A,
        feature_suffix="shared",
    )
    shared_b_source = _krex_notice_bundle(
        source_entity_id="multi::shared::b",
        raw_data=_MULTI_CLUES_B,
        feature_suffix="shared-b-source",
        observed_at=_NOW - timedelta(hours=2),
    )
    older_a = _krex_notice_bundle(
        source_entity_id="multi::older::a",
        raw_data=_MULTI_CLUES_A,
        feature_suffix="older-a",
        observed_at=_NOW - timedelta(hours=2),
    )
    newer_b = _krex_notice_bundle(
        source_entity_id="multi::newer::b",
        raw_data=_MULTI_CLUES_B,
        feature_suffix="newer-b",
    )
    await feature_repo.load_bundles(
        session,
        [shared, shared_b_source, older_a, newer_b],
    )
    await session.execute(
        text(
            """
            INSERT INTO provider_sync.source_links (
                feature_id, source_entity_key, source_role, match_method,
                confidence, created_at
            )
            SELECT
                :feature_id, source_entity_key, 'primary',
                'identity_migration', 100, :seen_at
            FROM provider_sync.source_records
            WHERE source_record_key = :source_record_key
            """
        ),
        {
            "feature_id": shared.feature.feature_id,
            "seen_at": _NOW,
            "source_record_key": shared_b_source.source_record.source_record_key,
        },
    )
    # B entity의 임시 원 feature는 감사 이력으로만 남기고, 같은 entity를 shared의
    # 두 번째 primary lineage로 연결한다.
    await session.execute(
        text(
            "UPDATE feature.features"
            " SET lifecycle_state = 'retired', publication_state = 'suppressed'"
            " WHERE feature_id = :feature_id"
        ),
        {
            "feature_id": shared_b_source.feature.feature_id,
        },
    )
    await session.flush()
    return shared, older_a, newer_b


async def _attach_cross_scope_winner(
    session: AsyncSession,
    *,
    feature_id: str,
    source_entity_id: str,
    provider: str = _CROSS_PROVIDER,
    dataset_key: str = _CROSS_DS,
    source_entity_type: str = _CROSS_ET,
) -> FeatureBundle:
    """다른 provider/dataset의 유일한 winner 계보를 기존 feature에 연결한다."""
    await _ensure_active_provider_dataset(
        session, provider=provider, dataset_key=dataset_key
    )
    cross_scope = _krex_notice_bundle(
        source_entity_id=source_entity_id,
        raw_data={"scope": "cross-provider-dataset"},
        provider=provider,
        dataset_key=dataset_key,
        source_entity_type=source_entity_type,
    )
    await feature_repo.load_bundles(session, [cross_scope])
    await session.execute(
        text(
            """
            INSERT INTO provider_sync.source_links (
                feature_id, source_entity_key, source_role, match_method,
                confidence, created_at
            )
            SELECT
                :feature_id, source_entity_key, 'primary',
                'identity_migration', 100, :seen_at
            FROM provider_sync.source_records
            WHERE source_record_key = :source_record_key
            """
        ),
        {
            "feature_id": feature_id,
            "seen_at": _NOW,
            "source_record_key": cross_scope.source_record.source_record_key,
        },
    )
    # cross-scope entity의 임시 원 feature는 감사 이력으로만 남기고, 전달받은
    # feature가 이 계보의 유일한 공개 winner가 되게 한다.
    await session.execute(
        text(
            "UPDATE feature.features"
            " SET lifecycle_state = 'retired', publication_state = 'suppressed'"
            " WHERE feature_id = :feature_id"
        ),
        {
            "feature_id": cross_scope.feature.feature_id,
        },
    )
    await session.execute(
        text(
            "DELETE FROM provider_sync.source_links "
            "WHERE feature_id = :feature_id"
        ),
        {"feature_id": cross_scope.feature.feature_id},
    )
    await session.flush()
    return cross_scope


async def _seed_split_max_tuple_lineage(
    session: AsyncSession,
) -> tuple[FeatureBundle, FeatureBundle]:
    """서로 다른 row에서 ``max(seen_at)``/``max(source_record_key)``가 나오는 계보.

    한 feature에 같은 계보의 current source entity가 여러 개 연결될 수 있다. 낮은
    record key에는 최신 시각을, 높은 record key에는 과거 시각을 주고, 두 key 사이의
    최신 row를 다른 feature에 둔다. 합성 max tuple은 존재하지 않으며 실제
    lexicographic winner는 가운데 key의 feature다.
    """
    bundles = [
        _krex_notice_bundle(
            source_entity_id=f"split-max::{suffix}",
            raw_data={**_CLUES, "gen": suffix},
            feature_suffix=suffix,
        )
        for suffix in ("a", "b", "c")
    ]
    low, middle, high = sorted(
        bundles,
        key=lambda bundle: bundle.source_record.source_record_key,
    )
    high = high.model_copy(
        update={
            "source_record": high.source_record.model_copy(
                update={
                    "fetched_at": _NOW - timedelta(hours=1),
                    "imported_at": _NOW - timedelta(hours=1),
                }
            )
        }
    )
    bundles = [
        high if bundle.feature.feature_id == high.feature.feature_id else bundle
        for bundle in bundles
    ]
    await feature_repo.load_bundles(session, bundles)

    # low/high entity를 한 feature에 묶는다. high의 원 feature는 감사 이력으로
    # soft-delete해 후보에서 제외하고, middle feature만 실제 최신 경쟁자로 둔다.
    await session.execute(
        text(
            """
            INSERT INTO provider_sync.source_links (
                feature_id, source_entity_key, source_role, match_method,
                confidence, created_at
            )
            SELECT
                :feature_id, source_entity_key, 'primary',
                'identity_migration', 100, :seen_at
            FROM provider_sync.source_records
            WHERE source_record_key = :source_record_key
            """
        ),
        {
            "feature_id": low.feature.feature_id,
            "seen_at": _NOW,
            "source_record_key": high.source_record.source_record_key,
        },
    )
    await session.execute(
        text(
            "UPDATE feature.features"
            " SET lifecycle_state = 'retired', publication_state = 'suppressed'"
            " WHERE feature_id = :feature_id"
        ),
        {
            "feature_id": high.feature.feature_id,
        },
    )
    await session.flush()
    return low, middle


async def _feature_state(
    session: AsyncSession, feature_id: str
) -> tuple[str, str, Any]:
    """(lifecycle, publication, notice valid_end).

    0097이 ``status``/``deleted_at``을 물리 삭제했다. notice supersede의 soft-delete는
    3축에서 ``lifecycle_state='retired'``다 — 값이 아니라 **의미**를 옮긴다.
    호출부가 지표(``[1]``)로 읽던 자리는 아래 ``_is_retired`` 로 이름을 붙였다.
    """

    row = (
        await session.execute(
            text(
                "SELECT f.lifecycle_state, f.publication_state,"
                " n.valid_end_time AS valid_end"
                " FROM feature.features AS f"
                " LEFT JOIN feature.feature_notices AS n"
                "   ON n.feature_id = f.feature_id"
                " WHERE f.feature_id = :fid"
            ),
            {"fid": feature_id},
        )
    ).one()
    return row.lifecycle_state, row.publication_state, row.valid_end


async def _is_retired(session: AsyncSession, feature_id: str) -> bool:
    """legacy ``deleted_at IS NOT NULL``의 3축 등가물."""

    return (await _feature_state(session, feature_id))[0] != "active"


async def _snapshot_state(
    session: AsyncSession,
    *,
    provider: str,
    dataset_key: str,
    source_entity_type: str,
    lineage_key: str,
) -> tuple[bool | None, datetime | None, datetime | None]:
    row = (
        await session.execute(
            text(
                "SELECT present, changed_at, valid_until "
                "FROM provider_sync.notice_lineage_states AS state "
                "JOIN provider_sync.notice_lifecycle_scopes AS scope "
                "ON scope.notice_lifecycle_scope_id = state.notice_lifecycle_scope_id "
                "JOIN provider_sync.provider_datasets AS dataset "
                "ON dataset.provider_dataset_id = scope.provider_dataset_id "
                "WHERE dataset.provider = :provider "
                "AND dataset.dataset_key = :dataset_key "
                "AND scope.source_entity_type = :source_entity_type "
                "AND state.lineage_key = :lineage_key"
            ),
            {
                "provider": provider,
                "dataset_key": dataset_key,
                "source_entity_type": source_entity_type,
                "lineage_key": lineage_key,
            },
        )
    ).one()
    return row.present, row.changed_at, row.valid_until


async def _public_notice_ids(session: AsyncSession) -> set[str]:
    rows = await feature_repo.features_in_bbox(
        session,
        min_lon=127.0,
        min_lat=37.0,
        max_lon=127.5,
        max_lat=37.8,
        kinds=["notice"],
    )
    return {str(row["feature_id"]) for row in rows}


async def test_supersede_soft_deletes_non_latest_per_lineage(
    migrated_session: AsyncSession,
) -> None:
    old_gen, new_gen = await _seed_dup_lineage(migrated_session)

    result = await feature_repo.supersede_stale_notice_features(
        migrated_session,
        provider=_KREX,
        dataset_key=_KREX_DS,
        source_entity_type=_KREX_ET,
    )

    assert result.superseded == 1
    assert result.closed == 0
    lifecycle, publication, _ = await _feature_state(
        migrated_session, old_gen.feature.feature_id
    )
    assert lifecycle == "retired"
    assert publication == "suppressed"
    lifecycle, _publication, valid_end = await _feature_state(
        migrated_session, new_gen.feature.feature_id
    )
    assert lifecycle == "active"
    assert valid_end is None  # 계보가 살아 있으면 닫지 않는다.


async def test_reconcile_exact_tie_prefers_current_identity(
    migrated_session: AsyncSession,
) -> None:
    """seen/source record 동률에도 현 사건 identity feature가 남는다.

    identity 이행 중 하나의 current source entity가 구/신 feature 양쪽에
    primary link로 남은 실제 형태를 재현한다. ``feature_id ASC``만으로
    고르면 구세대가 이기도록 구 ID를 작게 정해 canonical 판정을 검증한다.
    """
    current = _krex_notice_bundle(
        source_entity_id=_LINEAGE,
        raw_data={**_CLUES, "gen": "current"},
    )
    await feature_repo.load_bundles(migrated_session, [current])
    legacy_feature_id = "f_global_n_0000000000000000"
    assert legacy_feature_id < current.feature.feature_id
    # T-VN-35(ADR-086): core에 detail이 없다 — 구세대 사본은 core 축만 복제하고
    # kind별 값은 notice subtype에 같은 규칙으로 복제한다.
    await migrated_session.execute(
        text(
            """
            INSERT INTO feature.features (
                feature_id, kind, name, category, coord, coord_precision_digits,
                marker_icon, marker_color,
                lifecycle_state, publication_state, quality_state
            )
            SELECT
                :legacy_feature_id, kind, name, category, coord,
                coord_precision_digits, marker_icon, marker_color,
                lifecycle_state, publication_state, quality_state
            FROM feature.features
            WHERE feature_id = :current_feature_id
            """
        ),
        {
            "legacy_feature_id": legacy_feature_id,
            "current_feature_id": current.feature.feature_id,
        },
    )
    await migrated_session.execute(
        text(
            """
            INSERT INTO feature.feature_notices (
                feature_id, feature_uuid, kind, notice_type, severity,
                valid_start_time, valid_end_time, source_agency, officer_name, payload
            )
            SELECT
                legacy.feature_id, legacy.feature_uuid, legacy.kind,
                source.notice_type, source.severity, source.valid_start_time,
                source.valid_end_time, source.source_agency, source.officer_name,
                source.payload
            FROM feature.features AS legacy
            JOIN feature.feature_notices AS source
              ON source.feature_id = :current_feature_id
            WHERE legacy.feature_id = :legacy_feature_id
            """
        ),
        {
            "legacy_feature_id": legacy_feature_id,
            "current_feature_id": current.feature.feature_id,
        },
    )
    await migrated_session.execute(
        text(
            """
            INSERT INTO provider_sync.source_links (
                feature_id, source_entity_key, source_role, match_method,
                confidence, created_at
            )
            SELECT
                :legacy_feature_id, source_entity_key, 'primary',
                'identity_migration', 100, :seen_at
            FROM provider_sync.source_records
            WHERE source_record_key = :source_record_key
            """
        ),
        {
            "legacy_feature_id": legacy_feature_id,
            "seen_at": _NOW,
            "source_record_key": current.source_record.source_record_key,
        },
    )
    await migrated_session.flush()

    # write reconcile 전 read 필터도 동일 canonical 1건만 노출한다.
    rows = await feature_repo.features_in_bbox(
        migrated_session,
        min_lon=127.0,
        min_lat=37.0,
        max_lon=127.5,
        max_lat=37.8,
        kinds=["notice"],
    )
    assert {row["feature_id"] for row in rows} == {current.feature.feature_id}

    result = await feature_repo.supersede_stale_notice_features(
        migrated_session,
        provider=_KREX,
        dataset_key=_KREX_DS,
        source_entity_type=_KREX_ET,
    )
    assert result.superseded == 1
    assert await _is_retired(migrated_session, legacy_feature_id)
    assert not await _is_retired(migrated_session, current.feature.feature_id)

    # 같은 snapshot/reconcile을 다시 적용해도 winner가 바뀌지 않는다.
    again = await feature_repo.supersede_stale_notice_features(
        migrated_session,
        provider=_KREX,
        dataset_key=_KREX_DS,
        source_entity_type=_KREX_ET,
    )
    assert again.superseded == 0
    assert not await _is_retired(migrated_session, current.feature.feature_id)


async def test_actual_lexicographic_notice_row_wins_across_reads_and_reconcile(
    migrated_session: AsyncSession,
) -> None:
    """분리된 max 값으로 존재하지 않는 tuple을 만들지 않고 실제 row 하나를 고른다."""
    synthesized_winner, actual_winner = await _seed_split_max_tuple_lineage(migrated_session)
    expected_ids = {actual_winner.feature.feature_id}
    candidate_ids = {
        synthesized_winner.feature.feature_id,
        actual_winner.feature.feature_id,
    }
    await migrated_session.execute(
        text(
            "UPDATE feature.features"
            " SET sido_code = '11', name = '[테스트] 동일 교통 공지'"
            " WHERE feature_id = ANY(CAST(:feature_ids AS text[]))"
        ),
        {"feature_ids": list(candidate_ids)},
    )
    await migrated_session.execute(
        text(
            """
            INSERT INTO feature.features (
                feature_id, kind, name, category, coord,
                lifecycle_state, publication_state, quality_state
            ) VALUES (
                'notice-split-max-area', 'area', '공지 lexicographic 테스트 영역',
                '03000000',
                x_extension.ST_SetSRID(
                    x_extension.ST_MakePoint(127.1, 37.4), 4326
                ),
                'active', 'published', 'valid'
            )
            """
        )
    )
    # T-VN-35(ADR-086): area geometry 정본은 ``feature_areas``(MultiPolygon NOT NULL).
    await seed_feature_subtype(
        migrated_session,
        feature_id="notice-split-max-area",
        kind="area",
        geom_wkt=_AREA_WKT,
    )
    target = await upsert_poi_cache_target(
        migrated_session,
        external_system="notice-test",
        target_key="split-max-tuple",
        lon=127.1,
        lat=37.4,
        radius_km=10.0,
    )
    await migrated_session.flush()

    bbox = (127.0, 37.3, 127.2, 37.5)
    for include_geometry in (False, True):
        rows = await feature_repo.features_in_bbox(
            migrated_session,
            min_lon=bbox[0],
            min_lat=bbox[1],
            max_lon=bbox[2],
            max_lat=bbox[3],
            kinds=["notice"],
            include_geometry=include_geometry,
        )
        assert {row["feature_id"] for row in rows} == expected_ids

    search_by_bbox = await feature_repo.search_features(
        migrated_session,
        bbox=bbox,
        kinds=["notice"],
        page_size=20,
        include_total=True,
        cursor_signing_key=_SEARCH_CURSOR_KEY,
    )
    assert {item.feature_id for item in search_by_bbox.items} == expected_ids
    assert search_by_bbox.total_count == 1

    search_by_name = await feature_repo.search_features(
        migrated_session,
        q="[테스트] 동일 교통 공지",
        kinds=["notice"],
        page_size=20,
        include_total=True,
        cursor_signing_key=_SEARCH_CURSOR_KEY,
    )
    assert {item.feature_id for item in search_by_name.items} == expected_ids
    assert search_by_name.total_count == 1

    nearby = await feature_repo.features_nearby(
        migrated_session,
        lon=127.1,
        lat=37.4,
        radius_m=20_000,
        kinds=["notice"],
        limit=20,
    )
    assert {item.feature_id for item in nearby.items} == expected_ids

    nearby_target = await feature_repo.features_nearby_poi_cache_target(
        migrated_session,
        target_id=target.target_id,
        kinds=["notice"],
        limit=20,
    )
    assert {item.feature_id for item in nearby_target.items} == expected_ids

    contained = await feature_repo.features_contained_in_area(
        migrated_session,
        feature_id="notice-split-max-area",
        kinds=["notice"],
        limit=20,
    )
    assert {row["feature_id"] for row in contained} == expected_ids

    clusters = await feature_repo.cluster_features_in_bbox(
        migrated_session,
        min_lon=bbox[0],
        min_lat=bbox[1],
        max_lon=bbox[2],
        max_lat=bbox[3],
        cluster_unit="sido",
        kinds=["notice"],
    )
    assert clusters == [
        {
            "cluster_key": "11",
            "feature_count": 1,
            "lon": 127.1,
            "lat": 37.4,
        }
    ]
    counts = await feature_repo.category_feature_counts(migrated_session)
    assert counts.get("99000000", 0) == 1

    result = await feature_repo.supersede_stale_notice_features(
        migrated_session,
        provider=_KREX,
        dataset_key=_KREX_DS,
        source_entity_type=_KREX_ET,
    )
    assert result.superseded == 1
    assert not await _is_retired(migrated_session, actual_winner.feature.feature_id)
    assert (await _feature_state(migrated_session, synthesized_winner.feature.feature_id))[
        1
    ] is not None


async def test_multi_lineage_winner_survives_public_read_and_reconcile(
    migrated_session: AsyncSession,
) -> None:
    """한 계보 winner/다른 계보 loser인 feature 전체를 숨기거나 삭제하지 않는다."""
    shared, older_a, newer_b = await _seed_multi_lineage_feature(migrated_session)
    expected = {shared.feature.feature_id, newer_b.feature.feature_id}

    # reconcile 전 공개 필터도 "모든 계보에서 loser"인 older_a만 숨긴다.
    assert await _public_notice_ids(migrated_session) == expected

    result = await feature_repo.supersede_stale_notice_features(
        migrated_session,
        provider=_KREX,
        dataset_key=_KREX_DS,
        source_entity_type=_KREX_ET,
    )
    assert result == feature_repo.NoticeReconcileResult(superseded=1)
    assert not await _is_retired(migrated_session, shared.feature.feature_id)
    assert await _is_retired(migrated_session, older_a.feature.feature_id)
    assert not await _is_retired(migrated_session, newer_b.feature.feature_id)
    assert await _public_notice_ids(migrated_session) == expected


@pytest.mark.parametrize(
    ("different_dimension", "provider", "dataset_key", "source_entity_type"),
    [
        ("provider", _CROSS_PROVIDER, _KREX_DS, _KREX_ET),
        ("dataset", _KREX, _CROSS_DS, _KREX_ET),
        ("entity-type", _KREX, _KREX_DS, _CROSS_ET),
    ],
)
async def test_snapshot_preserves_winner_differing_in_each_scope_dimension(
    migrated_session: AsyncSession,
    different_dimension: str,
    provider: str,
    dataset_key: str,
    source_entity_type: str,
) -> None:
    """provider/dataset/type 중 하나만 달라도 별도 scope winner로 보호한다."""
    scoped = _krex_notice_bundle(
        source_entity_id=f"scope-dimension::{different_dimension}",
        raw_data={"scope": "current", "dimension": different_dimension},
        feature_suffix=f"scope-dimension::{different_dimension}",
    )
    await feature_repo.load_bundles(migrated_session, [scoped])
    cross = await _attach_cross_scope_winner(
        migrated_session,
        feature_id=scoped.feature.feature_id,
        source_entity_id=f"cross-dimension::{different_dimension}",
        provider=provider,
        dataset_key=dataset_key,
        source_entity_type=source_entity_type,
    )
    cross_present = await feature_repo.supersede_stale_notice_features(
        migrated_session,
        provider=provider,
        dataset_key=dataset_key,
        source_entity_type=source_entity_type,
        active_lineage_keys={cross.source_record.source_entity_id},
        closed_at=_NOW + timedelta(minutes=1),
    )
    assert cross_present == feature_repo.NoticeReconcileResult()

    scoped_absent = await feature_repo.supersede_stale_notice_features(
        migrated_session,
        provider=_KREX,
        dataset_key=_KREX_DS,
        source_entity_type=_KREX_ET,
        active_lineage_keys=set(),
        closed_at=_NOW + timedelta(minutes=2),
    )
    assert scoped_absent == feature_repo.NoticeReconcileResult()
    lifecycle, publication, valid_end = await _feature_state(
        migrated_session, scoped.feature.feature_id
    )
    assert lifecycle == "active"
    assert publication == "published"
    assert valid_end is None


async def test_reconcile_preserves_cross_provider_dataset_winners(
    migrated_session: AsyncSession,
) -> None:
    """호출 scope loser/absent여도 다른 provider winner인 feature는 보존한다."""
    delete_clues = {
        "occurred_date": "2026.07.03",
        "occurred_time": "11:00:00",
        "route_no": "0030",
        "direction": "서울방향",
        "point_name": "교차-provider-delete-guard",
        "incident_type_code": "03",
    }
    delete_lineage = (
        "2026.07.03::11:00:00::0030::서울방향::"
        "교차-provider-delete-guard::03"
    )
    cross_scope_winner = _krex_notice_bundle(
        source_entity_id=f"legacy::{delete_lineage}",
        raw_data=delete_clues,
        feature_suffix="cross-scope-delete-guard",
        observed_at=_NOW - timedelta(hours=1),
    )
    scoped_winner = _krex_notice_bundle(
        source_entity_id=delete_lineage,
        raw_data=delete_clues,
    )
    close_clues = {
        "occurred_date": "2026.07.03",
        "occurred_time": "11:10:00",
        "route_no": "0040",
        "direction": "부산방향",
        "point_name": "교차-provider-close-guard",
        "incident_type_code": "01",
    }
    close_guard = _krex_notice_bundle(
        source_entity_id="cross-scope-close-guard",
        raw_data=close_clues,
        feature_suffix="cross-scope-close-guard",
    )
    await feature_repo.load_bundles(
        migrated_session,
        [cross_scope_winner, scoped_winner, close_guard],
    )
    await _attach_cross_scope_winner(
        migrated_session,
        feature_id=cross_scope_winner.feature.feature_id,
        source_entity_id="cross-provider-delete-winner",
    )
    await _attach_cross_scope_winner(
        migrated_session,
        feature_id=close_guard.feature.feature_id,
        source_entity_id="cross-provider-close-winner",
    )
    cross_present = await feature_repo.supersede_stale_notice_features(
        migrated_session,
        provider=_CROSS_PROVIDER,
        dataset_key=_CROSS_DS,
        source_entity_type=_CROSS_ET,
        active_lineage_keys={
            "cross-provider-delete-winner",
            "cross-provider-close-winner",
        },
        closed_at=_NOW + timedelta(minutes=5),
    )
    assert cross_present == feature_repo.NoticeReconcileResult()

    expected = {
        cross_scope_winner.feature.feature_id,
        scoped_winner.feature.feature_id,
        close_guard.feature.feature_id,
    }
    assert await _public_notice_ids(migrated_session) == expected

    # KREX 계보에서는 loser지만 다른 provider/dataset 계보 winner이므로
    # feature 전체를 soft-delete하지 않는다.
    dedup = await feature_repo.supersede_stale_notice_features(
        migrated_session,
        provider=_KREX,
        dataset_key=_KREX_DS,
        source_entity_type=_KREX_ET,
    )
    assert dedup == feature_repo.NoticeReconcileResult()
    assert not await _is_retired(
        migrated_session, cross_scope_winner.feature.feature_id
    )

    # 과거 scope-local close/dedup 잔존을 재현한다. 현재 KREX 계보에서는
    # loser지만 다른 scope의 explicit true winner이므로 다시 열어야 한다.
    await migrated_session.execute(
        text(
            # 0097 이후 soft-delete의 등가물은 3축 retire다.
            "UPDATE feature.features"
            " SET lifecycle_state = 'retired', publication_state = 'suppressed'"
            " WHERE feature_id = :feature_id"
        ),
        {
            "ended_at": _NOW + timedelta(minutes=6),
            "feature_id": cross_scope_winner.feature.feature_id,
        },
    )
    await migrated_session.execute(
        text(
            "UPDATE feature.feature_notices SET valid_end_time = :ended_at "
            "WHERE feature_id = :feature_id"
        ),
        {
            "ended_at": _NOW + timedelta(minutes=6),
            "feature_id": cross_scope_winner.feature.feature_id,
        },
    )

    # KREX snapshot에서 close_guard 계보가 사라져도 다른 scope의 winner가
    # 여전히 열려 있으므로 이 호출이 공유 feature를 종료하지 않는다.
    snapshot = await feature_repo.supersede_stale_notice_features(
        migrated_session,
        provider=_KREX,
        dataset_key=_KREX_DS,
        source_entity_type=_KREX_ET,
        active_lineage_keys={delete_lineage},
        closed_at=_NOW + timedelta(minutes=10),
    )
    assert snapshot == feature_repo.NoticeReconcileResult(reopened=1)
    lifecycle, publication, valid_end = await _feature_state(
        migrated_session,
        cross_scope_winner.feature.feature_id,
    )
    assert lifecycle == "active"
    assert publication == "published"
    assert valid_end is None
    lifecycle, _publication, valid_end = await _feature_state(
        migrated_session, close_guard.feature.feature_id
    )
    assert lifecycle == "active"
    assert valid_end is None
    assert await _public_notice_ids(migrated_session) == expected


async def test_cross_scope_snapshot_state_closes_after_last_winner_disappears(
    migrated_session: AsyncSession,
) -> None:
    """A/B의 persisted 존재 상태가 순차 소멸·재등장 lifecycle을 결정한다."""
    scope_a = _krex_notice_bundle(
        source_entity_id="cross-snapshot-scope-a",
        raw_data={"scope": "a"},
        feature_suffix="cross-snapshot-shared",
    )
    await feature_repo.load_bundles(migrated_session, [scope_a])
    scope_b = await _attach_cross_scope_winner(
        migrated_session,
        feature_id=scope_a.feature.feature_id,
        source_entity_id="cross-snapshot-scope-b",
    )
    t0 = _NOW + timedelta(minutes=30)

    # 두 authoritative scope가 모두 present인 출발 상태를 영속화한다.
    for bundle, checked_at in (
        (scope_a, t0),
        (scope_b, t0 + timedelta(minutes=1)),
    ):
        result = await feature_repo.supersede_stale_notice_features(
            migrated_session,
            provider=bundle.source_record.provider,
            dataset_key=bundle.source_record.dataset_key,
            source_entity_type=bundle.source_record.source_entity_type,
            active_lineage_keys={bundle.source_record.source_entity_id},
            closed_at=checked_at,
        )
        assert result == feature_repo.NoticeReconcileResult()

    # A가 먼저 사라져도 B의 persisted present winner가 공유 Feature를 보존한다.
    a_absent_at = t0 + timedelta(minutes=2)
    a_absent = await feature_repo.supersede_stale_notice_features(
        migrated_session,
        provider=scope_a.source_record.provider,
        dataset_key=scope_a.source_record.dataset_key,
        source_entity_type=scope_a.source_record.source_entity_type,
        active_lineage_keys=set(),
        closed_at=a_absent_at,
    )
    assert a_absent == feature_repo.NoticeReconcileResult()
    assert (await _snapshot_state(
        migrated_session,
        provider=scope_a.source_record.provider,
        dataset_key=scope_a.source_record.dataset_key,
        source_entity_type=scope_a.source_record.source_entity_type,
        lineage_key=scope_a.source_record.source_entity_id,
    )) == (False, a_absent_at, None)
    assert (await _feature_state(migrated_session, scope_a.feature.feature_id))[2] is None

    # 마지막 present winner B까지 사라진 호출만 정확히 한 번 닫는다.
    b_absent_at = t0 + timedelta(minutes=3)
    b_absent = await feature_repo.supersede_stale_notice_features(
        migrated_session,
        provider=scope_b.source_record.provider,
        dataset_key=scope_b.source_record.dataset_key,
        source_entity_type=scope_b.source_record.source_entity_type,
        active_lineage_keys=set(),
        closed_at=b_absent_at,
    )
    assert b_absent == feature_repo.NoticeReconcileResult(closed=1)
    assert await _public_notice_ids(migrated_session) == set()

    # A의 과거 snapshot은 최신 false watermark를 되돌리거나 reopen하지 않는다.
    with pytest.raises(ValueError, match="stale authoritative"):
        await feature_repo.supersede_stale_notice_features(
            migrated_session,
            provider=scope_a.source_record.provider,
            dataset_key=scope_a.source_record.dataset_key,
            source_entity_type=scope_a.source_record.source_entity_type,
            active_lineage_keys={scope_a.source_record.source_entity_id},
            closed_at=t0 + timedelta(minutes=1),
        )
    assert (await _snapshot_state(
        migrated_session,
        provider=scope_a.source_record.provider,
        dataset_key=scope_a.source_record.dataset_key,
        source_entity_type=scope_a.source_record.source_entity_type,
        lineage_key=scope_a.source_record.source_entity_id,
    )) == (False, a_absent_at, None)

    # 더 최신 A 재등장은 reopen 1회, 같은 snapshot 반복은 no-op이다.
    reappeared_at = t0 + timedelta(minutes=4)
    reappeared = await feature_repo.supersede_stale_notice_features(
        migrated_session,
        provider=scope_a.source_record.provider,
        dataset_key=scope_a.source_record.dataset_key,
        source_entity_type=scope_a.source_record.source_entity_type,
        active_lineage_keys={scope_a.source_record.source_entity_id},
        closed_at=reappeared_at,
    )
    assert reappeared == feature_repo.NoticeReconcileResult(reopened=1)
    assert await _public_notice_ids(migrated_session) == {scope_a.feature.feature_id}
    repeated = await feature_repo.supersede_stale_notice_features(
        migrated_session,
        provider=scope_a.source_record.provider,
        dataset_key=scope_a.source_record.dataset_key,
        source_entity_type=scope_a.source_record.source_entity_type,
        active_lineage_keys={scope_a.source_record.source_entity_id},
        closed_at=reappeared_at,
    )
    assert repeated == feature_repo.NoticeReconcileResult()


async def test_snapshot_reconcile_serializes_cross_scope_closure(
    migrated_engine: AsyncEngine,
) -> None:
    """전역 transaction lock 뒤 최신 A/B 상태를 읽어 마지막 scope가 닫는다."""
    from sqlalchemy.ext.asyncio import AsyncSession

    suffix = uuid4().hex
    provider_a = f"snapshot-concurrency-a-{suffix}"
    provider_b = f"snapshot-concurrency-b-{suffix}"
    dataset_a = f"dataset-a-{suffix}"
    dataset_b = f"dataset-b-{suffix}"
    entity_a = f"entity-a-{suffix}"
    entity_b = f"entity-b-{suffix}"
    feature_ids: list[str] = []
    scope_a: FeatureBundle | None = None
    scope_b: FeatureBundle | None = None
    first_session = AsyncSession(migrated_engine, expire_on_commit=False)
    second_session = AsyncSession(migrated_engine, expire_on_commit=False)
    second_task: asyncio.Task[feature_repo.NoticeReconcileResult] | None = None
    try:
        async with AsyncSession(migrated_engine, expire_on_commit=False) as setup:
            await _ensure_active_provider_dataset(
                setup, provider=provider_a, dataset_key=dataset_a
            )
            scope_a = _krex_notice_bundle(
                source_entity_id=entity_a,
                raw_data={"scope": "concurrency-a"},
                feature_suffix=f"concurrency-shared-{suffix}",
                provider=provider_a,
                dataset_key=dataset_a,
                source_entity_type="notice",
            )
            await feature_repo.load_bundles(setup, [scope_a])
            scope_b = await _attach_cross_scope_winner(
                setup,
                feature_id=scope_a.feature.feature_id,
                source_entity_id=entity_b,
                provider=provider_b,
                dataset_key=dataset_b,
                source_entity_type="notice",
            )
            feature_ids = [
                scope_a.feature.feature_id,
                scope_b.feature.feature_id,
            ]
            for bundle, checked_at in (
                (scope_a, _NOW + timedelta(hours=1)),
                (scope_b, _NOW + timedelta(hours=1, minutes=1)),
            ):
                initialized = await feature_repo.supersede_stale_notice_features(
                    setup,
                    provider=bundle.source_record.provider,
                    dataset_key=bundle.source_record.dataset_key,
                    source_entity_type=bundle.source_record.source_entity_type,
                    active_lineage_keys={bundle.source_record.source_entity_id},
                    closed_at=checked_at,
                )
                assert initialized == feature_repo.NoticeReconcileResult()
            await setup.commit()

        await first_session.begin()
        first = await feature_repo.supersede_stale_notice_features(
            first_session,
            provider=provider_a,
            dataset_key=dataset_a,
            source_entity_type="notice",
            active_lineage_keys=set(),
            closed_at=_NOW + timedelta(hours=1, minutes=2),
        )
        assert first == feature_repo.NoticeReconcileResult()

        await second_session.begin()
        second_task = asyncio.create_task(
            feature_repo.supersede_stale_notice_features(
                second_session,
                provider=provider_b,
                dataset_key=dataset_b,
                source_entity_type="notice",
                active_lineage_keys=set(),
                closed_at=_NOW + timedelta(hours=1, minutes=3),
            )
        )
        await asyncio.sleep(0.2)
        assert not second_task.done()  # A transaction의 global snapshot lock 대기.

        await first_session.commit()
        second = await asyncio.wait_for(second_task, timeout=5)
        await second_session.commit()
        assert second == feature_repo.NoticeReconcileResult(closed=1)

        async with AsyncSession(migrated_engine) as verify:
            lifecycle, _publication, valid_end = await _feature_state(
                verify, scope_a.feature.feature_id
            )
        assert lifecycle == "active"
        assert valid_end is not None
    finally:
        if second_task is not None and not second_task.done():
            second_task.cancel()
            await asyncio.gather(second_task, return_exceptions=True)
        await first_session.rollback()
        await second_session.rollback()
        await first_session.close()
        await second_session.close()
        async with migrated_engine.begin() as connection:
            providers = [provider_a, provider_b]
            await connection.execute(
                text(
                    "DELETE FROM provider_sync.source_links AS link "
                    "USING provider_sync.source_entities AS entity "
                    "JOIN provider_sync.provider_datasets AS dataset "
                    "ON dataset.provider_dataset_id = entity.provider_dataset_id "
                    "WHERE link.source_entity_key = entity.source_entity_key "
                    "AND dataset.provider = ANY(CAST(:providers AS text[]))"
                ),
                {"providers": providers},
            )
            if feature_ids:
                await connection.execute(
                    text(
                        "DELETE FROM feature.feature_versions "
                        "WHERE feature_id = ANY(CAST(:feature_ids AS text[]))"
                    ),
                    {"feature_ids": feature_ids},
                )
                await connection.execute(
                    text(
                        "DELETE FROM feature.features "
                        "WHERE feature_id = ANY(CAST(:feature_ids AS text[]))"
                    ),
                    {"feature_ids": feature_ids},
                )
            await connection.execute(
                text(
                    "DELETE FROM provider_sync.source_entity_heads AS head "
                    "USING provider_sync.source_entities AS entity "
                    "JOIN provider_sync.provider_datasets AS dataset "
                    "ON dataset.provider_dataset_id = entity.provider_dataset_id "
                    "WHERE head.source_entity_key = entity.source_entity_key "
                    "AND dataset.provider = ANY(CAST(:providers AS text[]))"
                ),
                {"providers": providers},
            )
            await connection.execute(
                text(
                    "DELETE FROM provider_sync.source_records AS record "
                    "USING provider_sync.source_entities AS entity "
                    "JOIN provider_sync.provider_datasets AS dataset "
                    "ON dataset.provider_dataset_id = entity.provider_dataset_id "
                    "WHERE record.source_entity_key = entity.source_entity_key "
                    "AND dataset.provider = ANY(CAST(:providers AS text[]))"
                ),
                {"providers": providers},
            )
            await connection.execute(
                text(
                    "DELETE FROM provider_sync.source_entities AS entity "
                    "USING provider_sync.provider_datasets AS dataset "
                    "WHERE dataset.provider_dataset_id = entity.provider_dataset_id "
                    "AND dataset.provider = ANY(CAST(:providers AS text[]))"
                ),
                {"providers": providers},
            )
            await connection.execute(
                text(
                    "DELETE FROM provider_sync.notice_lifecycle_scopes AS scope "
                    "USING provider_sync.provider_datasets AS dataset "
                    "WHERE dataset.provider_dataset_id = scope.provider_dataset_id "
                    "AND dataset.provider = ANY(CAST(:providers AS text[]))"
                ),
                {"providers": providers},
            )


async def test_snapshot_uses_only_active_winning_lineage_per_feature(
    migrated_session: AsyncSession,
) -> None:
    """패배 계보만 active면 닫고, 승리 계보가 active일 때만 reopen한다."""
    shared, older_a, newer_b = await _seed_multi_lineage_feature(migrated_session)
    closed_at = _NOW + timedelta(minutes=10)

    # shared는 A winner/B loser다. B만 active이므로 shared의 승리 계보 A는
    # 사라진 상태다. shared는 soft-delete하지 않고 종료하고, B winner만 표시한다.
    b_only = await feature_repo.supersede_stale_notice_features(
        migrated_session,
        provider=_KREX,
        dataset_key=_KREX_DS,
        source_entity_type=_KREX_ET,
        active_lineage_keys={_MULTI_LINEAGE_B},
        closed_at=closed_at,
    )
    assert b_only == feature_repo.NoticeReconcileResult(superseded=1, closed=1)
    shared_lifecycle, shared_publication, shared_end = await _feature_state(
        migrated_session, shared.feature.feature_id
    )
    assert shared_lifecycle == "active"
    assert shared_publication == "published"
    assert shared_end == closed_at
    assert await _is_retired(migrated_session, older_a.feature.feature_id)
    newer_lifecycle, _newer_publication, newer_end = await _feature_state(
        migrated_session, newer_b.feature.feature_id
    )
    assert newer_lifecycle == "active"
    assert newer_end is None
    assert await _public_notice_ids(migrated_session) == {newer_b.feature.feature_id}

    # 반대로 A만 active면 shared를 reopen하고, 사라진 B winner를 닫는다.
    a_only = await feature_repo.supersede_stale_notice_features(
        migrated_session,
        provider=_KREX,
        dataset_key=_KREX_DS,
        source_entity_type=_KREX_ET,
        active_lineage_keys={_MULTI_LINEAGE_A},
        closed_at=closed_at + timedelta(minutes=10),
    )
    assert a_only == feature_repo.NoticeReconcileResult(closed=1, reopened=1)
    shared_lifecycle, _shared_publication, shared_end = await _feature_state(
        migrated_session, shared.feature.feature_id
    )
    assert shared_lifecycle == "active"
    assert shared_end is None
    newer_lifecycle, _newer_publication, newer_end = await _feature_state(
        migrated_session, newer_b.feature.feature_id
    )
    assert newer_lifecycle == "active"
    assert newer_end == closed_at + timedelta(minutes=10)
    assert await _public_notice_ids(migrated_session) == {shared.feature.feature_id}

    # 모든 승리 계보가 absent면 열린 shared만 한 번 닫혀 metric도 row 변화와 같다.
    empty = await feature_repo.supersede_stale_notice_features(
        migrated_session,
        provider=_KREX,
        dataset_key=_KREX_DS,
        source_entity_type=_KREX_ET,
        active_lineage_keys=set(),
        closed_at=closed_at + timedelta(minutes=20),
    )
    assert empty == feature_repo.NoticeReconcileResult(closed=1)
    assert await _public_notice_ids(migrated_session) == set()


async def test_supersede_closes_lineage_missing_from_feed(
    migrated_session: AsyncSession,
) -> None:
    _, new_gen = await _seed_dup_lineage(migrated_session)
    closed_at = _NOW + timedelta(minutes=10)

    result = await feature_repo.supersede_stale_notice_features(
        migrated_session,
        provider=_KREX,
        dataset_key=_KREX_DS,
        source_entity_type=_KREX_ET,
        active_lineage_keys={"다른::계보"},  # 이번 feed에 이 계보 없음.
        closed_at=closed_at,
    )

    assert result.superseded == 1  # 구세대는 여전히 중복 정리.
    assert result.closed == 1
    assert result.reopened == 0
    lifecycle, _publication, valid_end = await _feature_state(
        migrated_session, new_gen.feature.feature_id
    )
    assert lifecycle == "active"  # latest는 retire가 아니라 '종료'.
    assert valid_end is not None
    assert valid_end == closed_at

    # 종료됐던 계보가 feed에 다시 나타나면 active로 self-heal한다.
    reappeared = await feature_repo.supersede_stale_notice_features(
        migrated_session,
        provider=_KREX,
        dataset_key=_KREX_DS,
        source_entity_type=_KREX_ET,
        active_lineage_keys={_LINEAGE},
        closed_at=closed_at + timedelta(minutes=10),
    )
    assert reappeared.superseded == 0
    assert reappeared.closed == 0
    assert reappeared.reopened == 1
    lifecycle, _publication, valid_end = await _feature_state(
        migrated_session, new_gen.feature.feature_id
    )
    assert lifecycle == "active"
    assert valid_end is None

    # 이미 열린 상태에서 같은 snapshot을 재적용하면 no-op이다.
    again = await feature_repo.supersede_stale_notice_features(
        migrated_session,
        provider=_KREX,
        dataset_key=_KREX_DS,
        source_entity_type=_KREX_ET,
        active_lineage_keys={_LINEAGE},
        closed_at=closed_at + timedelta(minutes=20),
    )
    assert again.closed == 0
    assert again.reopened == 0


async def test_reconcile_reactivates_soft_deleted_winner_without_duplicate(
    migrated_session: AsyncSession,
) -> None:
    """현재 feed의 canonical winner가 과거 soft-delete돼도 즉시 복구한다."""
    old_gen, current = await _seed_dup_lineage(migrated_session)
    await migrated_session.execute(
        text(
            "UPDATE feature.features"
            " SET lifecycle_state = 'retired', publication_state = 'suppressed',"
            " updated_at = now()"
            " WHERE feature_id = :feature_id"
        ),
        {
            "feature_id": current.feature.feature_id,
        },
    )

    result = await feature_repo.supersede_stale_notice_features(
        migrated_session,
        provider=_KREX,
        dataset_key=_KREX_DS,
        source_entity_type=_KREX_ET,
        active_lineage_keys={_LINEAGE},
        closed_at=_NOW + timedelta(minutes=10),
    )

    assert result.reopened == 1
    assert result.closed == 0
    assert result.superseded == 1
    old_lifecycle, _old_publication, _ = await _feature_state(
        migrated_session, old_gen.feature.feature_id
    )
    assert old_lifecycle == "retired"
    assert old_lifecycle != "active"
    lifecycle, _publication, valid_end = await _feature_state(
        migrated_session, current.feature.feature_id
    )
    assert lifecycle == "active"
    assert valid_end is None

    # 같은 snapshot은 feature 복구/중복 정리를 반복하지 않는다.
    again = await feature_repo.supersede_stale_notice_features(
        migrated_session,
        provider=_KREX,
        dataset_key=_KREX_DS,
        source_entity_type=_KREX_ET,
        active_lineage_keys={_LINEAGE},
        closed_at=_NOW + timedelta(minutes=20),
    )
    assert again == feature_repo.NoticeReconcileResult()


async def test_atomic_snapshot_load_tracks_new_lineage_and_repairs_exact_replay(
    migrated_session: AsyncSession,
) -> None:
    """신규 lineage는 load 뒤 기록하고 exact replay로 누락 state를 복구한다."""
    bundle = _krex_notice_bundle(
        source_entity_id=_LINEAGE,
        raw_data=_CLUES,
    )
    first_at = _NOW + timedelta(hours=1)
    first = await feature_repo.load_authoritative_notice_snapshot(
        migrated_session,
        bundles=[bundle],
        provider=_KREX,
        dataset_key=_KREX_DS,
        source_entity_type=_KREX_ET,
        active_lineage_keys={_LINEAGE},
        observed_at=first_at,
    )
    assert first.load.bundles_total == 1
    assert first.reconcile == feature_repo.NoticeReconcileResult()
    assert await _snapshot_state(
        migrated_session,
        provider=_KREX,
        dataset_key=_KREX_DS,
        source_entity_type=_KREX_ET,
        lineage_key=_LINEAGE,
    ) == (True, first_at, None)

    # 부분 반영 잔존을 흉내 낸 뒤 같은 watermark/fingerprint를 replay하면
    # bundle load 이후 known lineage sync가 누락 row를 되살린다.
    await migrated_session.execute(
        text(
            "DELETE FROM provider_sync.notice_lineage_states AS state "
            "USING provider_sync.notice_lifecycle_scopes AS scope "
            "JOIN provider_sync.provider_datasets AS dataset "
            "ON dataset.provider_dataset_id = scope.provider_dataset_id "
            "WHERE state.notice_lifecycle_scope_id = scope.notice_lifecycle_scope_id "
            "AND dataset.provider = :provider "
            "AND dataset.dataset_key = :dataset_key "
            "AND scope.source_entity_type = :source_entity_type"
        ),
        {
            "provider": _KREX,
            "dataset_key": _KREX_DS,
            "source_entity_type": _KREX_ET,
        },
    )
    replay = await feature_repo.load_authoritative_notice_snapshot(
        migrated_session,
        bundles=[bundle],
        provider=_KREX,
        dataset_key=_KREX_DS,
        source_entity_type=_KREX_ET,
        active_lineage_keys={_LINEAGE},
        observed_at=first_at,
    )
    assert replay.reconcile == feature_repo.NoticeReconcileResult()
    assert await _snapshot_state(
        migrated_session,
        provider=_KREX,
        dataset_key=_KREX_DS,
        source_entity_type=_KREX_ET,
        lineage_key=_LINEAGE,
    ) == (True, first_at, None)

    unchanged_at = first_at + timedelta(minutes=1)
    await feature_repo.load_authoritative_notice_snapshot(
        migrated_session,
        bundles=[bundle],
        provider=_KREX,
        dataset_key=_KREX_DS,
        source_entity_type=_KREX_ET,
        active_lineage_keys={_LINEAGE},
        observed_at=unchanged_at,
    )
    # scope watermark만 전진하고 member changed_at은 실제 전이 때만 바뀐다.
    assert await _snapshot_state(
        migrated_session,
        provider=_KREX,
        dataset_key=_KREX_DS,
        source_entity_type=_KREX_ET,
        lineage_key=_LINEAGE,
    ) == (True, first_at, None)
    with pytest.raises(ValueError, match="conflicting authoritative"):
        await feature_repo.load_authoritative_notice_snapshot(
            migrated_session,
            bundles=[],
            provider=_KREX,
            dataset_key=_KREX_DS,
            source_entity_type=_KREX_ET,
            active_lineage_keys=set(),
            observed_at=unchanged_at,
        )
    with pytest.raises(ValueError, match="stale authoritative"):
        await feature_repo.load_authoritative_notice_snapshot(
            migrated_session,
            bundles=[],
            provider=_KREX,
            dataset_key=_KREX_DS,
            source_entity_type=_KREX_ET,
            active_lineage_keys=set(),
            observed_at=first_at,
        )


async def test_atomic_event_load_ignores_stale_announcement_after_lift(
    migrated_session: AsyncSession,
) -> None:
    """최신 lift가 stale의 서로 다른 payload/Feature/current를 모두 차단한다."""
    provider = "python-test-notice-events"
    dataset_key = "test_notice_events"
    source_entity_type = "notice_event"
    lineage_key = "event-lineage"
    await _ensure_active_provider_dataset(
        migrated_session, provider=provider, dataset_key=dataset_key
    )
    bundle = _krex_notice_bundle(
        source_entity_id=lineage_key,
        raw_data={"event": "announcement"},
        provider=provider,
        dataset_key=dataset_key,
        source_entity_type=source_entity_type,
    )
    stale_base = _krex_notice_bundle(
        source_entity_id=lineage_key,
        raw_data={"event": "stale-different-payload"},
        provider=provider,
        dataset_key=dataset_key,
        source_entity_type=source_entity_type,
    )
    stale_name = "[stale] 과거 발표가 덮으면 안 되는 이름"
    assert stale_base.feature.detail is not None
    stale_raw_data = {**stale_base.source_record.raw_data, "name": stale_name}
    stale_payload_hash = make_payload_hash(stale_raw_data)
    stale_source_record = stale_base.source_record.model_copy(
        update={
            "raw_data": stale_raw_data,
            "raw_payload_hash": stale_payload_hash,
            "source_record_key": make_source_record_key(
                provider=stale_base.source_record.provider,
                dataset_key=stale_base.source_record.dataset_key,
                source_entity_type=stale_base.source_record.source_entity_type,
                source_entity_id=stale_base.source_record.source_entity_id,
                raw_payload_hash=stale_payload_hash,
            ),
        }
    )
    stale_bundle = stale_base.model_copy(
        update={
            "feature": stale_base.feature.model_copy(
                update={
                    "name": stale_name,
                    "detail": stale_base.feature.detail.model_copy(
                        update={"severity": 5}
                    ),
                }
            ),
            "source_record": stale_source_record,
            "source_link": stale_base.source_link.model_copy(
                update={"source_record_key": stale_source_record.source_record_key}
            ),
        }
    )
    assert (
        stale_bundle.source_record.source_record_key
        != bundle.source_record.source_record_key
    )
    announced_at = _NOW
    with pytest.raises(ValueError, match="multiple bundles for one lineage"):
        await feature_repo.load_notice_event_bundles(
            migrated_session,
            bundles=[bundle, bundle],
            provider=provider,
            dataset_key=dataset_key,
            source_entity_type=source_entity_type,
            lineage_events={lineage_key: (True, announced_at, None)},
            observed_at=announced_at,
        )

    announced = await feature_repo.load_notice_event_bundles(
        migrated_session,
        bundles=[bundle],
        provider=provider,
        dataset_key=dataset_key,
        source_entity_type=source_entity_type,
        lineage_events={lineage_key: (True, announced_at, None)},
        observed_at=announced_at,
    )
    assert announced.load.bundles_total == 1
    with pytest.raises(ValueError, match="equal event time"):
        await feature_repo.load_notice_event_bundles(
            migrated_session,
            bundles=[],
            provider=provider,
            dataset_key=dataset_key,
            source_entity_type=source_entity_type,
            lineage_events={
                lineage_key: (
                    True,
                    announced_at,
                    announced_at + timedelta(hours=1),
                )
            },
            observed_at=announced_at,
        )

    lifted_at = announced_at + timedelta(hours=2)
    lifted = await feature_repo.load_notice_event_bundles(
        migrated_session,
        # 정상 rolling window는 같은 계보의 과거 발표 bundle과 최신 해제를
        # 함께 포함할 수 있다. 최신 false가 이 bundle을 오류 없이 제외해야 한다.
        bundles=[stale_bundle],
        provider=provider,
        dataset_key=dataset_key,
        source_entity_type=source_entity_type,
        lineage_events={lineage_key: (False, lifted_at, None)},
        observed_at=lifted_at,
    )
    assert lifted.load.bundles_total == 0
    assert lifted.reconcile.closed == 1

    # 같은 Feature의 다른 provider 계보가 explicit present면 공유 Feature는
    # 다시 열리되, 원 provider의 최신 false state 자체는 유지한다.
    cross_bundle = await _attach_cross_scope_winner(
        migrated_session,
        feature_id=bundle.feature.feature_id,
        source_entity_id="event-lineage-cross-provider",
        provider="python-test-notice-events-cross",
        dataset_key="test_notice_events_cross",
        source_entity_type=source_entity_type,
    )
    cross_present = await feature_repo.supersede_stale_notice_features(
        migrated_session,
        provider=cross_bundle.source_record.provider,
        dataset_key=cross_bundle.source_record.dataset_key,
        source_entity_type=cross_bundle.source_record.source_entity_type,
        active_lineage_keys={cross_bundle.source_record.source_entity_id},
        closed_at=lifted_at + timedelta(minutes=1),
    )
    assert cross_present == feature_repo.NoticeReconcileResult(reopened=1)

    before_stale = (
        await migrated_session.execute(
            text(
                "SELECT f.name, n.severity AS severity, "
                "head.current_source_record_key "
                "FROM feature.features AS f "
                "LEFT JOIN feature.feature_notices AS n "
                "ON n.feature_id = f.feature_id "
                "JOIN provider_sync.source_links AS sl "
                "ON sl.feature_id = f.feature_id AND sl.source_role = 'primary' "
                "JOIN provider_sync.source_entities AS se "
                "ON se.source_entity_key = sl.source_entity_key "
                "JOIN provider_sync.source_entity_heads AS head "
                "ON head.source_entity_key = se.source_entity_key "
                "JOIN provider_sync.provider_datasets AS dataset "
                "ON dataset.provider_dataset_id = se.provider_dataset_id "
                "WHERE f.feature_id = :feature_id AND dataset.provider = :provider "
                "AND dataset.dataset_key = :dataset_key "
                "AND se.source_entity_type = :source_entity_type"
            ),
            {
                "feature_id": bundle.feature.feature_id,
                "provider": provider,
                "dataset_key": dataset_key,
                "source_entity_type": source_entity_type,
            },
        )
    ).one()
    assert before_stale.current_source_record_key == (
        bundle.source_record.source_record_key
    )

    stale = await feature_repo.load_notice_event_bundles(
        migrated_session,
        bundles=[stale_bundle],
        provider=provider,
        dataset_key=dataset_key,
        source_entity_type=source_entity_type,
        lineage_events={
            lineage_key: (True, announced_at + timedelta(hours=1), None)
        },
        observed_at=lifted_at + timedelta(minutes=1),
    )
    assert stale.load.bundles_total == 0
    assert stale.reconcile == feature_repo.NoticeReconcileResult()
    after_stale = (
        await migrated_session.execute(
            text(
                "SELECT f.name, n.severity AS severity, "
                "head.current_source_record_key "
                "FROM feature.features AS f "
                "LEFT JOIN feature.feature_notices AS n "
                "ON n.feature_id = f.feature_id "
                "JOIN provider_sync.source_links AS sl "
                "ON sl.feature_id = f.feature_id AND sl.source_role = 'primary' "
                "JOIN provider_sync.source_entities AS se "
                "ON se.source_entity_key = sl.source_entity_key "
                "JOIN provider_sync.source_entity_heads AS head "
                "ON head.source_entity_key = se.source_entity_key "
                "JOIN provider_sync.provider_datasets AS dataset "
                "ON dataset.provider_dataset_id = se.provider_dataset_id "
                "WHERE f.feature_id = :feature_id AND dataset.provider = :provider "
                "AND dataset.dataset_key = :dataset_key "
                "AND se.source_entity_type = :source_entity_type"
            ),
            {
                "feature_id": bundle.feature.feature_id,
                "provider": provider,
                "dataset_key": dataset_key,
                "source_entity_type": source_entity_type,
            },
        )
    ).one()
    assert after_stale == before_stale
    assert after_stale.name != stale_name
    assert after_stale.severity != "5"
    lifecycle, _publication, valid_end = await _feature_state(
        migrated_session,
        bundle.feature.feature_id,
    )
    assert lifecycle == "active"
    assert valid_end is None
    assert await _public_notice_ids(migrated_session) == {
        bundle.feature.feature_id
    }
    assert await _snapshot_state(
        migrated_session,
        provider=provider,
        dataset_key=dataset_key,
        source_entity_type=source_entity_type,
        lineage_key=lineage_key,
    ) == (False, lifted_at, None)


async def test_event_lifecycle_resolves_open_finite_unknown_and_reactivation(
    migrated_session: AsyncSession,
) -> None:
    """unknown 계보와 섞여도 explicit present의 기간·재활성화를 보존한다."""
    provider = "python-test-notice-truth"
    dataset_key = "test_notice_truth"
    source_entity_type = "notice_event"
    lineage_key = "truth-lineage"
    await _ensure_active_provider_dataset(
        migrated_session, provider=provider, dataset_key=dataset_key
    )
    bundle = _krex_notice_bundle(
        source_entity_id=lineage_key,
        raw_data={"event": "truth-table"},
        provider=provider,
        dataset_key=dataset_key,
        source_entity_type=source_entity_type,
    )
    feature_id = bundle.feature.feature_id
    wall_now = datetime.now(_KST)
    first_at = wall_now - timedelta(minutes=10)
    await feature_repo.load_notice_event_bundles(
        migrated_session,
        bundles=[bundle],
        provider=provider,
        dataset_key=dataset_key,
        source_entity_type=source_entity_type,
        lineage_events={lineage_key: (True, first_at, None)},
        observed_at=first_at,
    )
    await _attach_cross_scope_winner(
        migrated_session,
        feature_id=feature_id,
        source_entity_id="truth-unknown-lineage",
        provider="python-test-notice-unknown",
        dataset_key="test_notice_unknown",
        source_entity_type=source_entity_type,
    )

    # 다른 scope는 lifecycle state가 없는 unknown이다. open present exact replay는
    # 과거 soft-delete 잔존을 복구하고 unknown 때문에 막히지 않는다.
    await migrated_session.execute(
        text(
            "UPDATE feature.features"
            " SET lifecycle_state = 'retired', publication_state = 'suppressed' "
            "WHERE feature_id = :fid"
        ),
        {"at": wall_now, "fid": feature_id},
    )
    await migrated_session.execute(
        text(
            "UPDATE feature.feature_notices SET valid_end_time = :at "
            "WHERE feature_id = :fid"
        ),
        {"at": wall_now, "fid": feature_id},
    )
    replay = await feature_repo.load_notice_event_bundles(
        migrated_session,
        bundles=[],
        provider=provider,
        dataset_key=dataset_key,
        source_entity_type=source_entity_type,
        lineage_events={lineage_key: (True, first_at, None)},
        observed_at=first_at,
    )
    assert replay.reconcile == feature_repo.NoticeReconcileResult(reopened=1)
    assert await _feature_state(migrated_session, feature_id) == (
        "active",
        None,
        None,
    )

    # unknown + finite는 현재 open/future 기간을 줄이지 않고 더 늦은 끝만 연장한다.
    shorter_end = wall_now + timedelta(hours=6)
    finite = await feature_repo.load_notice_event_bundles(
        migrated_session,
        bundles=[],
        provider=provider,
        dataset_key=dataset_key,
        source_entity_type=source_entity_type,
        lineage_events={
            lineage_key: (True, first_at + timedelta(minutes=1), shorter_end)
        },
        observed_at=first_at + timedelta(minutes=1),
    )
    assert finite.reconcile == feature_repo.NoticeReconcileResult()
    assert (await _feature_state(migrated_session, feature_id))[2] is None

    old_longer_end = wall_now + timedelta(hours=12)
    await migrated_session.execute(
        text(
            "UPDATE feature.feature_notices SET valid_end_time = :end_at "
            "WHERE feature_id = :fid"
        ),
        {"end_at": old_longer_end, "fid": feature_id},
    )
    await feature_repo.load_notice_event_bundles(
        migrated_session,
        bundles=[],
        provider=provider,
        dataset_key=dataset_key,
        source_entity_type=source_entity_type,
        lineage_events={
            lineage_key: (
                True,
                first_at + timedelta(minutes=2),
                shorter_end,
            )
        },
        observed_at=first_at + timedelta(minutes=2),
    )
    assert (await _feature_state(migrated_session, feature_id))[2] == old_longer_end

    extended_end = wall_now + timedelta(hours=18)
    await feature_repo.load_notice_event_bundles(
        migrated_session,
        bundles=[],
        provider=provider,
        dataset_key=dataset_key,
        source_entity_type=source_entity_type,
        lineage_events={
            lineage_key: (
                True,
                first_at + timedelta(minutes=3),
                extended_end,
            )
        },
        observed_at=first_at + timedelta(minutes=3),
    )
    assert (await _feature_state(migrated_session, feature_id))[2] == extended_end

    # 3축에는 "deleted_at 없는 inactive"라는 두 번째 비활성 표현이 없다 — legacy의
    # (inactive, deleted_at NULL)과 (inactive, deleted_at 있음)이 모두 retire 하나로
    # 합쳐진다. 되살리기 동작 자체는 그대로 검증한다.
    past_end = wall_now - timedelta(hours=1)
    await migrated_session.execute(
        text(
            "UPDATE feature.features"
            " SET lifecycle_state = 'retired', publication_state = 'suppressed'"
            " WHERE feature_id = :fid"
        ),
        {"fid": feature_id},
    )
    await migrated_session.execute(
        text(
            "UPDATE feature.feature_notices SET valid_end_time = :end_at "
            "WHERE feature_id = :fid"
        ),
        {"end_at": past_end, "fid": feature_id},
    )
    future_end = wall_now + timedelta(hours=2)
    future = await feature_repo.load_notice_event_bundles(
        migrated_session,
        bundles=[],
        provider=provider,
        dataset_key=dataset_key,
        source_entity_type=source_entity_type,
        lineage_events={
            lineage_key: (
                True,
                first_at + timedelta(minutes=4),
                future_end,
            )
        },
        observed_at=first_at + timedelta(minutes=4),
    )
    assert future.reconcile == feature_repo.NoticeReconcileResult(reopened=1)
    lifecycle, _publication, valid_end = await _feature_state(
        migrated_session, feature_id
    )
    assert lifecycle == "active"
    assert valid_end == future_end

    # 운영자 비활성화 override는 open present 재활성화를 막는다. 같은 event의
    # exact replay는 override 해제 뒤 상태를 self-heal한다.
    await migrated_session.execute(
        text(
            "UPDATE feature.features"
            " SET lifecycle_state = 'retired', publication_state = 'suppressed' "
            "WHERE feature_id = :fid"
        ),
        {"at": wall_now, "fid": feature_id},
    )
    await migrated_session.execute(
        text(
            "INSERT INTO ops.feature_overrides ("
            "feature_id, field_path, override_value, "
            "prevent_provider_reactivation, status) VALUES ("
            # 0095가 field_path를 'lifecycle_state'로 제약하고 값은 'retired'만 받는다.
            ":fid, 'lifecycle_state', to_jsonb('retired'::text), true, 'active')"
        ),
        {"fid": feature_id},
    )
    open_at = first_at + timedelta(minutes=5)
    blocked = await feature_repo.load_notice_event_bundles(
        migrated_session,
        bundles=[],
        provider=provider,
        dataset_key=dataset_key,
        source_entity_type=source_entity_type,
        lineage_events={lineage_key: (True, open_at, None)},
        observed_at=open_at,
    )
    assert blocked.reconcile == feature_repo.NoticeReconcileResult()
    assert (await _feature_state(migrated_session, feature_id))[0] == "retired"
    await migrated_session.execute(
        text(
            "DELETE FROM ops.feature_overrides "
            "WHERE feature_id = :fid AND field_path = 'lifecycle_state'"
        ),
        {"fid": feature_id},
    )
    healed = await feature_repo.load_notice_event_bundles(
        migrated_session,
        bundles=[],
        provider=provider,
        dataset_key=dataset_key,
        source_entity_type=source_entity_type,
        lineage_events={lineage_key: (True, open_at, None)},
        observed_at=open_at,
    )
    assert healed.reconcile == feature_repo.NoticeReconcileResult(reopened=1)

    # 이미 만료된 finite present는 state/SourceRecord 감사 이력만 남기고 deleted
    # Feature를 되살리거나 Feature payload를 갱신하지 않는다.
    await migrated_session.execute(
        text(
            "UPDATE feature.features"
            " SET lifecycle_state = 'retired', publication_state = 'suppressed' "
            "WHERE feature_id = :fid"
        ),
        {"at": wall_now, "fid": feature_id},
    )
    expired_at = wall_now - timedelta(minutes=1)
    expired_bundle = _krex_notice_bundle(
        source_entity_id=lineage_key,
        raw_data={"event": "expired-audit-record"},
        provider=provider,
        dataset_key=dataset_key,
        source_entity_type=source_entity_type,
    )
    assert (
        expired_bundle.source_record.source_record_key
        != bundle.source_record.source_record_key
    )
    expired = await feature_repo.load_notice_event_bundles(
        migrated_session,
        bundles=[expired_bundle],
        provider=provider,
        dataset_key=dataset_key,
        source_entity_type=source_entity_type,
        lineage_events={
            lineage_key: (
                True,
                first_at + timedelta(minutes=6),
                expired_at,
            )
        },
        observed_at=first_at + timedelta(minutes=6),
    )
    assert expired.load.bundles_total == 1
    assert expired.load.source_records_inserted == 1
    assert expired.load.features_inserted == 0
    assert expired.load.features_updated == 0
    assert expired.reconcile == feature_repo.NoticeReconcileResult()
    current_source_record_key = (
        await migrated_session.execute(
            text(
                "SELECT head.current_source_record_key "
                "FROM provider_sync.source_entities AS entity "
                "JOIN provider_sync.source_entity_heads AS head "
                "ON head.source_entity_key = entity.source_entity_key "
                "JOIN provider_sync.provider_datasets AS dataset "
                "ON dataset.provider_dataset_id = entity.provider_dataset_id "
                "WHERE dataset.provider = :provider "
                "AND dataset.dataset_key = :dataset_key "
                "AND entity.source_entity_type = :source_entity_type "
                "AND entity.source_entity_id = :lineage_key"
            ),
            {
                "provider": provider,
                "dataset_key": dataset_key,
                "source_entity_type": source_entity_type,
                "lineage_key": lineage_key,
            },
        )
    ).scalar_one()
    assert current_source_record_key == (
        expired_bundle.source_record.source_record_key
    )
    lifecycle, _publication, valid_end = await _feature_state(
        migrated_session, feature_id
    )
    assert lifecycle == "retired"
    assert lifecycle != "active"
    assert valid_end == expired_at


async def test_close_notice_features_kma_lift_roundtrip(
    migrated_session: AsyncSession,
) -> None:
    announced_at = datetime.now(_KST) - timedelta(hours=7)
    scheduled_end = announced_at + timedelta(hours=12)

    class _Region:
        region_code = "stn:108"
        region_name = "전국"

    class _Alert:
        alert_id = "108:202607030600:20"
        alert_type = "폭염"  # 실제 경로처럼 현상 토큰(정규화 가능 값).
        level = "주의보"
        title = "폭염주의보 발표"
        description = None
        issued_at = announced_at
        effective_from = None
        effective_until = scheduled_end
        source_agency = "기상청"
        regions = [_Region()]

    bundles = weather_alerts_to_notice_bundles(
        [_Alert()], fetched_at=announced_at
    )
    assert len(bundles) == 1
    lineage_key = bundles[0].source_record.source_entity_id
    announced = await feature_repo.load_notice_event_bundles(
        migrated_session,
        bundles=bundles,
        provider="python-kma-api",
        dataset_key="kma_weather_alerts",
        source_entity_type="weather_alert",
        lineage_events={
            lineage_key: (True, announced_at, scheduled_end)
        },
        observed_at=announced_at,
    )
    assert announced.load.bundles_total == 1
    assert announced.reconcile == feature_repo.NoticeReconcileResult()
    feature_id = kma_alert_notice_feature_id("stn:108", "폭염")
    assert bundles[0].feature.feature_id == feature_id
    assert (await _feature_state(migrated_session, feature_id))[2] == scheduled_end
    assert await _snapshot_state(
        migrated_session,
        provider="python-kma-api",
        dataset_key="kma_weather_alerts",
        source_entity_type="weather_alert",
        lineage_key=lineage_key,
    ) == (True, announced_at, scheduled_end)

    class _Lift(_Alert):
        alert_id = "108:202607031800:25"
        title = "폭염주의보 해제"
        issued_at = announced_at + timedelta(hours=6)

    closures = weather_alert_lift_closures([_Lift()])
    closed = await feature_repo.close_notice_features(
        migrated_session,
        provider="python-kma-api",
        dataset_key="kma_weather_alerts",
        source_entity_type="weather_alert",
        closures={c.natural_key: c.closed_at for c in closures},
    )
    assert closed == 1
    lifecycle, _publication, valid_end = await _feature_state(
        migrated_session, feature_id
    )
    assert lifecycle == "active"
    assert valid_end is not None
    # 미래 예정 종료보다 이른 explicit lift가 authoritative false 시각이다.
    assert valid_end == announced_at + timedelta(hours=6)

    # 같은 false 상태라도 더 최신 해제 event면 보존/purge 기준 종료 시각을 전진한다.
    assert (
        await feature_repo.close_notice_features(
            migrated_session,
            provider="python-kma-api",
            dataset_key="kma_weather_alerts",
            source_entity_type="weather_alert",
            closures={
                closures[0].natural_key: announced_at
                + timedelta(hours=6, minutes=30)
            },
        )
        == 0
    )
    assert (
        await _feature_state(migrated_session, feature_id)
    )[2] == announced_at + timedelta(hours=6, minutes=30)


async def test_close_ignores_older_lift_after_reannouncement(
    migrated_session: AsyncSession,
) -> None:
    """해제 시각보다 나중에 재발표된 feature는 닫지 않는다 (순서 역전 방어)."""
    bundle = _krex_notice_bundle(
        source_entity_id="reannounce::계보",
        raw_data={"occurred_date": "2026.07.03"},
        valid_start=_NOW,  # 발표(=valid_start)가 해제 시각보다 나중.
    )
    await feature_repo.load_bundles(migrated_session, [bundle])
    closed = await feature_repo.close_notice_features(
        migrated_session,
        provider=_KREX,
        dataset_key=_KREX_DS,
        source_entity_type=_KREX_ET,
        closures={bundle.source_record.source_entity_id: _NOW - timedelta(hours=1)},
        announcements={bundle.source_record.source_entity_id: _NOW},
    )
    assert closed == 0


async def test_bbox_read_hides_non_latest_and_ended(
    migrated_session: AsyncSession,
) -> None:
    old_gen, new_gen = await _seed_dup_lineage(migrated_session)
    bbox = {
        "min_lon": 127.0,
        "min_lat": 37.0,
        "max_lon": 127.5,
        "max_lat": 37.8,
        "limit": 50,
    }
    rows = await feature_repo.features_in_bbox(migrated_session, kinds=["notice"], **bbox)
    ids = {row["feature_id"] for row in rows}
    # 계보 latest만 — 구세대는 soft-delete 전이라도 read에서 숨는다.
    assert new_gen.feature.feature_id in ids
    assert old_gen.feature.feature_id not in ids

    # 종료된 notice는 숨는다.
    await migrated_session.execute(
        text(
            "UPDATE feature.feature_notices SET valid_end_time = :t"
            " WHERE feature_id = :fid"
        ),
        {"t": _NOW + timedelta(hours=1), "fid": new_gen.feature.feature_id},
    )
    rows = await feature_repo.features_in_bbox(migrated_session, kinds=["notice"], **bbox)
    ids = {row["feature_id"] for row in rows}
    assert new_gen.feature.feature_id not in ids


async def test_public_active_reads_share_latest_and_ended_notice_filter(
    migrated_session: AsyncSession,
) -> None:
    """legacy/current 중복과 종료 notice를 모든 사용자 목록·집계에서 동일 제외한다.

    admin 감사 목록은 원천 이력 추적을 위해 세 feature를 모두 유지한다.
    """
    old_gen, new_gen = await _seed_dup_lineage(migrated_session)
    ended = _krex_notice_bundle(
        source_entity_id="public-read::ended",
        raw_data={
            "occurred_date": "2026.07.03",
            "occurred_time": "08:10:00",
            "route_no": "0010",
            "direction": "서울방향",
            "point_name": "종료지점",
            "incident_type_code": "03",
        },
        lon=127.11,
        lat=37.41,
    )
    await feature_repo.load_bundles(migrated_session, [ended])
    all_ids = {
        old_gen.feature.feature_id,
        new_gen.feature.feature_id,
        ended.feature.feature_id,
    }
    expected_ids = {new_gen.feature.feature_id}
    await migrated_session.execute(
        text(
            "UPDATE feature.features SET sido_code = '11'"
            " WHERE feature_id = ANY(CAST(:feature_ids AS text[]))"
        ),
        {"feature_ids": list(all_ids)},
    )
    # T-VN-35(ADR-086): 효력 종료 시각의 정본은 typed timestamptz 컬럼이다.
    await migrated_session.execute(
        text(
            "UPDATE feature.feature_notices SET valid_end_time = :ended_at"
            " WHERE feature_id = :ended_id"
        ),
        {
            "ended_at": _NOW + timedelta(hours=1),
            "ended_id": ended.feature.feature_id,
        },
    )
    await migrated_session.execute(
        text(
            """
            INSERT INTO feature.features (
                feature_id, kind, name, category, coord,
                lifecycle_state, publication_state, quality_state
            ) VALUES (
                'notice-public-read-area', 'area', '공지 조회 테스트 영역', '03000000',
                x_extension.ST_SetSRID(
                    x_extension.ST_MakePoint(127.1, 37.4), 4326
                ),
                'active', 'published', 'valid'
            )
            """
        )
    )
    await seed_feature_subtype(
        migrated_session,
        feature_id="notice-public-read-area",
        kind="area",
        geom_wkt=_AREA_WKT,
    )
    await migrated_session.flush()

    bbox = (127.0, 37.3, 127.2, 37.5)
    bbox_rows = await feature_repo.features_in_bbox(
        migrated_session,
        min_lon=bbox[0],
        min_lat=bbox[1],
        max_lon=bbox[2],
        max_lat=bbox[3],
        kinds=["notice"],
    )
    assert {row["feature_id"] for row in bbox_rows} == expected_ids

    search_page = await feature_repo.search_features(
        migrated_session,
        bbox=bbox,
        kinds=["notice"],
        page_size=20,
        include_total=True,
        cursor_signing_key=_SEARCH_CURSOR_KEY,
    )
    assert {item.feature_id for item in search_page.items} == expected_ids
    assert search_page.total_count == 1

    nearby_page = await feature_repo.features_nearby(
        migrated_session,
        lon=127.1,
        lat=37.4,
        radius_m=20_000,
        kinds=["notice"],
        limit=20,
    )
    assert {item.feature_id for item in nearby_page.items} == expected_ids

    contained = await feature_repo.features_contained_in_area(
        migrated_session,
        feature_id="notice-public-read-area",
        kinds=["notice"],
        limit=20,
    )
    assert {row["feature_id"] for row in contained} == expected_ids

    clusters = await feature_repo.cluster_features_in_bbox(
        migrated_session,
        min_lon=bbox[0],
        min_lat=bbox[1],
        max_lon=bbox[2],
        max_lat=bbox[3],
        cluster_unit="sido",
        kinds=["notice"],
    )
    assert clusters == [
        {
            "cluster_key": "11",
            "feature_count": 1,
            "lon": 127.1,
            "lat": 37.4,
        }
    ]

    counts = await feature_repo.category_feature_counts(migrated_session)
    assert counts.get("99000000", 0) == 1

    direct_public_ids = set(
        await feature_repo.public_active_notice_feature_identities(
            migrated_session,
            list(all_ids),
        )
    )
    assert direct_public_ids == expected_ids

    audit_page = await admin_feature_repo.list_admin_features(
        migrated_session,
        kinds=["notice"],
        include_ended=True,
        page_size=100,
    )
    assert all_ids <= {item.feature_id for item in audit_page.items}


async def test_purge_expired_notices(migrated_session: AsyncSession) -> None:
    stale = _krex_notice_bundle(
        source_entity_id="purge::stale",
        raw_data={"occurred_date": "2025.06.01"},
        valid_start=_NOW - timedelta(days=400),
    )
    fresh = _krex_notice_bundle(
        source_entity_id="purge::fresh",
        raw_data={"occurred_date": "2026.07.01"},
        valid_start=_NOW - timedelta(days=2),
    )
    await feature_repo.load_bundles(migrated_session, [stale, fresh])

    purged = await feature_repo.purge_expired_notices(migrated_session)

    assert purged == 1
    assert await _is_retired(migrated_session, stale.feature.feature_id)
    assert not await _is_retired(migrated_session, fresh.feature.feature_id)


async def test_read_paths_exclude_ended_notice_by_default(
    migrated_session: AsyncSession,
) -> None:
    """수집 feed에서 사라져 종료된(valid_end_time) notice는 목록·카운트 등 read에서
    기본 제외되고(사용자 요구: 수집에 없는 notice는 과거 자료로 노출하지 않음),
    infra raw by-id와 admin 감사 목록에만 남고 public by-id에서는 숨는다.

    (bbox/search/nearby/area/cluster/counts/admin이 모두 동일 ``valid_end_time``
    술어를 공유하므로 counts·admin·by-id로 대표 검증한다 — bbox는 별도 테스트.)
    """
    active = _krex_notice_bundle(
        source_entity_id="read::active",
        raw_data={"occurred_date": "2026.07.03", "route_no": "0010", "point_name": "가"},
    )
    ended = _krex_notice_bundle(
        source_entity_id="read::ended",
        raw_data={"occurred_date": "2026.07.03", "route_no": "0020", "point_name": "나"},
    )
    await feature_repo.load_bundles(migrated_session, [active, ended])
    active_id = active.feature.feature_id
    ended_id = ended.feature.feature_id
    category = active.feature.category

    counts_before = dict(await feature_repo.category_feature_counts(migrated_session))
    await migrated_session.execute(
        text(
            "UPDATE feature.feature_notices SET valid_end_time = :t"
            " WHERE feature_id = :fid"
        ),
        {"t": _NOW + timedelta(hours=1), "fid": ended_id},
    )

    # category_feature_counts: 종료 notice는 카운트에서 빠진다.
    counts_after = dict(await feature_repo.category_feature_counts(migrated_session))
    assert counts_after.get(category, 0) == counts_before.get(category, 0) - 1

    # admin 목록: 기본 제외.
    default_page = await admin_feature_repo.list_admin_features(
        migrated_session, kinds=["notice"], page_size=100
    )
    default_ids = {item.feature_id for item in default_page.items}
    assert active_id in default_ids
    assert ended_id not in default_ids

    # admin 목록: include_ended=True면 감사용으로 다시 포함.
    audit_page = await admin_feature_repo.list_admin_features(
        migrated_session,
        kinds=["notice"],
        include_ended=True,
        page_size=100,
    )
    assert ended_id in {item.feature_id for item in audit_page.items}

    # infra raw by-id는 admin/감사를 위해 종료돼도 반환한다.
    row = await feature_repo.get_feature_row(migrated_session, ended_id)
    assert row is not None
    assert row["feature_id"] == ended_id
    # public 단건/batch가 사용하는 필터는 ID 직접 조회 우회를 허용하지 않는다.
    assert set(
        await feature_repo.public_active_notice_feature_identities(
            migrated_session,
            [active_id, ended_id],
        )
    ) == {active_id}


async def test_reconcile_empty_snapshot_closes_all_active_lineages(
    migrated_session: AsyncSession,
) -> None:
    """성공한 빈 snapshot은 모든 latest notice가 feed에서 소멸했다는 뜻이다."""
    a = _krex_notice_bundle(
        source_entity_id="empty::a",
        raw_data={"occurred_date": "2026.07.03", "route_no": "0030"},
    )
    b = _krex_notice_bundle(
        source_entity_id="empty::b",
        raw_data={"occurred_date": "2026.07.02", "route_no": "0040"},
    )
    await feature_repo.load_bundles(migrated_session, [a, b])

    result = await feature_repo.supersede_stale_notice_features(
        migrated_session,
        provider=_KREX,
        dataset_key=_KREX_DS,
        source_entity_type=_KREX_ET,
        active_lineage_keys=set(),
        closed_at=_NOW + timedelta(minutes=10),
    )

    assert result.closed == 2
    assert result.reopened == 0
    for bundle in (a, b):
        lifecycle, _publication, valid_end = await _feature_state(
            migrated_session, bundle.feature.feature_id
        )
        assert valid_end is not None
        assert lifecycle == "active"
