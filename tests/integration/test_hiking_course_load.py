"""등산 코스 route 적재 → 공개 요약 왕복 (ADR-128).

provider 변환이 만든 코스 bundle을 실제 적재 경로(``feature_repo.load_bundles``)로 싣고,
공개 view(``feature.public_features``)에서 읽은 출발/도착이 조립 때의 방향과 같은지 본다 —
저장(``ST_Multi``)이 정점·파트 순서를 보존한다는 전제를 실 PostGIS에서 확인한다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any

import pytest

from kortravelmap.infra import feature_identity, feature_repo, route_summary_repo
from kortravelmap.providers.krforest import mountain_trail_courses_to_bundles

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.integration

_KST = timezone(timedelta(hours=9))


@dataclass(frozen=True)
class _Trail:
    name: str | None
    source_id: str | None
    source_file: str | None
    layer_name: str | None
    geometry_type: str | None
    geometry: dict[str, Any] | None
    bbox: tuple[float, float, float, float] | None
    raw: Any = field(default_factory=dict)


def _trail(
    serial: int, coords: list[tuple[float, float]], *, segment_name: str, length_km: float = 0.88
) -> _Trail:
    xs = [c[0] for c in coords]
    ys = [c[1] for c in coords]
    return _Trail(
        name=f"시험산 {segment_name}",
        source_id=f"it-course:{serial}",
        source_file="mountain/it.zip/PMNTN.shp",
        layer_name="PMNTN",
        geometry_type="LineString",
        geometry={"type": "LineString", "coordinates": [list(c) for c in coords]},
        bbox=(min(xs), min(ys), max(xs), max(ys)),
        raw={
            "MNTN_CODE": "999900001",
            "MNTN_NM": "시험산",
            "PMNTN_NM": segment_name,
            "PMNTN_SN": serial,
            "PMNTN_LT": length_km,
            "PMNTN_UPPL": 16,
            "PMNTN_GODN": 11,
            "PMNTN_DFFL": "중간",
        },
    )


async def test_course_bundle_roundtrips_direction_and_summary(
    migrated_session: AsyncSession,
) -> None:
    bundles = await mountain_trail_courses_to_bundles(
        [
            # 동쪽 다른 노선이 산 구간망 중심을 동쪽으로 끌어당긴다 → 들머리는 서쪽 끝.
            _trail(1, [(127.000, 37.5), (127.010, 37.5)], segment_name="서쪽구간"),
            _trail(2, [(127.020, 37.5), (127.010, 37.5)], segment_name="서쪽구간"),
            _trail(3, [(127.100, 37.5), (127.140, 37.5)], segment_name="동쪽구간", length_km=3.53),
        ],
        fetched_at=datetime(2026, 11, 27, 12, 0, tzinfo=_KST),
    )
    assert len(bundles) == 2
    await feature_repo.load_bundles(migrated_session, bundles)
    await migrated_session.flush()

    west = next(b for b in bundles if b.feature.name == "시험산 서쪽구간")
    identity = await feature_identity.resolve_feature_identity(
        migrated_session, west.feature.feature_id
    )
    assert identity is not None
    summaries = await route_summary_repo.list_public_route_summaries(
        migrated_session, [identity.feature_id, "00000000-0000-0000-0000-000000000000"]
    )

    assert set(summaries) == {identity.feature_id}
    summary = summaries[identity.feature_id]
    assert summary.route_type == "hiking_course"
    assert summary.shape == "path"
    assert summary.duration_minutes == 32
    assert summary.duration_basis == "source"
    assert summary.difficulty == "moderate"
    assert summary.length_m is not None
    assert 1700 < summary.length_m < 1800
    assert summary.start == pytest.approx((127.000, 37.5))
    assert summary.end == pytest.approx((127.020, 37.5))
    assert west.feature.coord is not None
    assert summary.start == pytest.approx(
        (float(west.feature.coord.lon), float(west.feature.coord.lat))
    )
