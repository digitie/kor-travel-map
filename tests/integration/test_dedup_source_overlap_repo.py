"""#1468 원천 겹침 규칙의 DB 쪽 — 반경 안만 읽기·선형 겹침 쌍·master 선정 입력."""

from __future__ import annotations

from datetime import UTC, datetime
from hashlib import md5
from typing import TYPE_CHECKING

import pytest
from geoalchemy2 import WKTElement
from sqlalchemy import text

from kortravelmap.infra import merge_repo
from kortravelmap.infra.dedup_refresh_repo import (
    DedupRefreshScope,
    list_dedup_refresh_features,
    list_route_overlap_pairs,
)
from kortravelmap.infra.models import (
    FeatureRow,
    SourceEntityHeadRow,
    SourceEntityRow,
    SourceLinkRow,
    SourceRecordRow,
)
from tests.integration._subtype_seed import seed_feature_subtype

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.integration

_T = datetime(2026, 11, 10, 9, 0, tzinfo=UTC)
_LEFT = ("python-overlap-left-api", "overlap_left")
_RIGHT = ("python-overlap-right-api", "overlap_right")
#: 위도 37.5°에서 1 m ≈ 위도 0.000009°.
_M = 1 / 111_320


def _fid(n: int) -> str:
    return f"00000000-0000-7000-8000-00000014{n:04d}"


async def _dataset_id(session: AsyncSession, provider: str, dataset_key: str) -> int:
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


async def _seed(
    session: AsyncSession,
    *,
    feature_id: str,
    source: tuple[str, str],
    name: str,
    lon: float,
    lat: float,
    category: str = "03060000",
    kind: str = "place",
    geom_wkt: str | None = None,
) -> None:
    label = f"overlap-{feature_id[-6:]}"
    dataset_id = await _dataset_id(session, *source)
    session.add(
        FeatureRow(
            feature_id=feature_id,
            kind=kind,
            name=name,
            category=category,
            coord=WKTElement(f"POINT({lon} {lat})", srid=4326),
            coord_precision_digits=7,
            lifecycle_state="active",
            publication_state="published",
            quality_state="valid",
            created_at=_T,
            updated_at=_T,
        )
    )
    session.add(
        SourceEntityRow(
            source_entity_key=f"se-{label}",
            provider_dataset_id=dataset_id,
            source_entity_type=kind,
            source_entity_id=label,
            first_seen_at=_T,
            last_seen_at=_T,
        )
    )
    await session.flush()
    session.add(
        SourceRecordRow(
            source_record_key=f"sr-{label}",
            source_entity_key=f"se-{label}",
            raw_payload_hash=md5(label.encode()).hexdigest(),
            raw_data={"feature_id": feature_id},
            fetched_at=_T,
            imported_at=_T,
        )
    )
    await session.flush()
    session.add(
        SourceEntityHeadRow(
            source_entity_key=f"se-{label}",
            current_source_record_key=f"sr-{label}",
            observed_at=_T,
        )
    )
    await session.flush()
    session.add(
        SourceLinkRow(
            feature_id=feature_id,
            source_entity_key=f"se-{label}",
            source_role="primary",
            match_method="natural_key",
            confidence=100,
            created_at=_T,
        )
    )
    await session.flush()
    await seed_feature_subtype(session, feature_id=feature_id, kind=kind, geom_wkt=geom_wkt)


async def test_near_filter_reads_only_right_features_within_radius(
    migrated_session: AsyncSession,
) -> None:
    left_id, near_id, far_id = _fid(1), _fid(2), _fid(3)
    await _seed(migrated_session, feature_id=left_id, source=_LEFT, name="솔밭캠핑장",
                lon=127.0, lat=37.5)
    await _seed(migrated_session, feature_id=near_id, source=_RIGHT, name="솔밭캠핑장",
                lon=127.0, lat=37.5 + 100 * _M)
    await _seed(migrated_session, feature_id=far_id, source=_RIGHT, name="솔밭캠핑장",
                lon=127.0, lat=37.5 + 2_000 * _M)
    scope = DedupRefreshScope(provider=_RIGHT[0], dataset_key=_RIGHT[1])

    everything = await list_dedup_refresh_features(migrated_session, scope)
    assert {f.feature_id for f in everything} == {near_id, far_id}

    near = await list_dedup_refresh_features(
        migrated_session, scope, near_feature_ids=[left_id], near_radius_m=300
    )
    assert [f.feature_id for f in near] == [near_id]

    assert (
        await list_dedup_refresh_features(
            migrated_session, scope, near_feature_ids=[], near_radius_m=300
        )
        == []
    )
    with pytest.raises(ValueError, match="together"):
        await list_dedup_refresh_features(migrated_session, scope, near_radius_m=300)


async def test_route_overlap_pairs_pick_best_match_above_ratio(
    migrated_session: AsyncSession,
) -> None:
    knps_main, knps_side = _fid(10), _fid(11)
    parallel, half_out, elsewhere = _fid(20), _fid(21), _fid(22)
    lat = 37.5
    off = lat + 10 * _M  # 탐방로에서 북쪽으로 10 m 평행
    # 오른쪽(원장) 두 탐방로 — 주 탐방로와 그 끝에서 이어지는 갈래.
    await _seed(migrated_session, feature_id=knps_main, source=_RIGHT, name="주 탐방로",
                lon=127.000, lat=lat, category="01020103", kind="route",
                geom_wkt=f"LINESTRING(127.000 {lat}, 127.010 {lat})")
    await _seed(migrated_session, feature_id=knps_side, source=_RIGHT, name="갈래 탐방로",
                lon=127.008, lat=lat, category="01020103", kind="route",
                geom_wkt=f"LINESTRING(127.008 {lat}, 127.020 {lat})")
    # 왼쪽 — 주 탐방로를 그대로 따라가는 등산로(겹침 ≈1.0, 갈래와는 ≈0.2).
    await _seed(migrated_session, feature_id=parallel, source=_LEFT, name="1구간",
                lon=127.000, lat=off, category="01080500", kind="route",
                geom_wkt=f"LINESTRING(127.000 {off}, 127.010 {off})")
    # 절반 넘게 탐방로 밖으로 나가는 등산로 — 주 탐방로와 겹치는 것은 길이의 1/4.
    await _seed(migrated_session, feature_id=half_out, source=_LEFT, name="2구간",
                lon=127.0075, lat=off + 500 * _M, category="01080500", kind="route",
                geom_wkt=(
                    f"LINESTRING(127.0075 {off + 500 * _M}, 127.0075 {off}, 127.0100 {off})"
                ))
    # 다른 산.
    await _seed(migrated_session, feature_id=elsewhere, source=_LEFT, name="3구간",
                lon=128.0, lat=36.0, category="01080500", kind="route",
                geom_wkt="LINESTRING(128.000 36.000, 128.010 36.000)")

    pairs = await list_route_overlap_pairs(
        migrated_session,
        DedupRefreshScope(provider=_LEFT[0], dataset_key=_LEFT[1]),
        DedupRefreshScope(provider=_RIGHT[0], dataset_key=_RIGHT[1]),
        buffer_m=30,
        min_overlap_ratio=0.5,
    )

    assert [(a.feature_id, b.feature_id) for a, b, _ratio in pairs] == [(parallel, knps_main)]
    [(left, right, ratio)] = pairs
    assert ratio > 0.95
    assert (left.kind, right.kind) == ("route", "route")
    assert (left.name, right.name) == ("1구간", "주 탐방로")
    assert left.coord is not None


async def test_master_candidate_carries_primary_dataset_key(
    migrated_session: AsyncSession,
) -> None:
    feature_id = _fid(30)
    await _seed(migrated_session, feature_id=feature_id, source=_LEFT, name="문화자원",
                lon=127.0, lat=37.5)
    candidate = await merge_repo._master_candidate(migrated_session, feature_id)
    assert (candidate.provider, candidate.dataset_key) == _LEFT
    assert candidate.has_coord is True


async def test_master_candidate_picks_highest_priority_primary_link(
    migrated_session: AsyncSession,
) -> None:
    # 병합을 흡수한 master는 primary link가 여럿이다. 낮은 원천(MCST)이 먼저 와도 높은
    # 원천(MOIS)으로 판정한다 — 그래야 원천 우선 선정이 link 순서에 흔들리지 않는다.
    feature_id = _fid(31)
    await _seed(migrated_session, feature_id=feature_id, source=("python-mcst-api", "overlap_mcst"),
                name="흡수한 master", lon=127.0, lat=37.5)
    dataset_id = await _dataset_id(migrated_session, "python-mois-api", "overlap_mois")
    migrated_session.add(
        SourceEntityRow(
            source_entity_key="se-overlap-absorbed-mois",
            provider_dataset_id=dataset_id,
            source_entity_type="place",
            source_entity_id="absorbed-mois",
            first_seen_at=_T,
            last_seen_at=_T,
        )
    )
    await migrated_session.flush()
    migrated_session.add(
        SourceLinkRow(
            feature_id=feature_id,
            source_entity_key="se-overlap-absorbed-mois",
            source_role="primary",
            match_method="natural_key",
            confidence=90,
            created_at=_T,
        )
    )
    await migrated_session.flush()
    candidate = await merge_repo._master_candidate(migrated_session, feature_id)
    assert (candidate.provider, candidate.dataset_key) == ("python-mois-api", "overlap_mois")


async def test_route_overlap_drops_short_segment_on_long_trail(
    migrated_session: AsyncSession,
) -> None:
    # #1468 소유자 결정: 긴 탐방로 위의 짧은 등산로 조각은 한쪽 방향으로는 완전히 겹치지만
    # (비율 1.0) 같은 선이 아니다 — 길이 비율·양방향 겹침 조건으로 빠진다. 길이가 비슷한 쌍은 남는다.
    long_trail, twin_trail = _fid(40), _fid(41)
    short_piece, twin = _fid(50), _fid(51)
    lat, lat2 = 37.6, 37.7
    await _seed(migrated_session, feature_id=long_trail, source=_RIGHT, name="긴 탐방로",
                lon=127.000, lat=lat, category="01020103", kind="route",
                geom_wkt=f"LINESTRING(127.000 {lat}, 127.050 {lat})")  # 약 4.4 km
    await _seed(migrated_session, feature_id=twin_trail, source=_RIGHT, name="짝 탐방로",
                lon=127.000, lat=lat2, category="01020103", kind="route",
                geom_wkt=f"LINESTRING(127.000 {lat2}, 127.010 {lat2})")
    off = lat + 5 * _M
    await _seed(migrated_session, feature_id=short_piece, source=_LEFT, name="짧은 조각",
                lon=127.020, lat=off, category="01080500", kind="route",
                geom_wkt=f"LINESTRING(127.020 {off}, 127.022 {off})")  # 약 180 m, 비율 1.0
    off2 = lat2 + 5 * _M
    await _seed(migrated_session, feature_id=twin, source=_LEFT, name="짝 등산로",
                lon=127.000, lat=off2, category="01080500", kind="route",
                geom_wkt=f"LINESTRING(127.000 {off2}, 127.0095 {off2})")  # 길이 0.95배

    pairs = await list_route_overlap_pairs(
        migrated_session,
        DedupRefreshScope(provider=_LEFT[0], dataset_key=_LEFT[1]),
        DedupRefreshScope(provider=_RIGHT[0], dataset_key=_RIGHT[1]),
        buffer_m=30,
        min_overlap_ratio=0.5,
    )

    assert [(a.feature_id, b.feature_id) for a, b, _ratio in pairs] == [(twin, twin_trail)]


async def test_route_overlap_rejects_invalid_length_ratio(
    migrated_session: AsyncSession,
) -> None:
    scope = DedupRefreshScope(provider=_LEFT[0], dataset_key=_LEFT[1])
    with pytest.raises(ValueError, match="length_ratio"):
        await list_route_overlap_pairs(
            migrated_session, scope, scope, buffer_m=30, min_overlap_ratio=0.5,
            length_ratio=(1.2, 1.5),
        )