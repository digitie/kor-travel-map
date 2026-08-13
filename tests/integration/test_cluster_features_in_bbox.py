"""``cluster_features_in_bbox`` 통합 테스트 (T-213c, ADR-012)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import text

from kortravelmap.infra import feature_repo

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.integration

_FETCHED = datetime(2026, 6, 3, 12, 0, tzinfo=timezone(timedelta(hours=9)))


async def _ins(
    session: AsyncSession,
    *,
    fid: str,
    lon: float,
    lat: float,
    sido: str,
    sigungu: str,
    bjd: str,
) -> None:
    """rollup 대상이 되려면 **공개 표면(`feature.public_features`)에 실재**해야 한다.

    `cluster_features_in_bbox`는 `feature.features`가 아니라 공개 view를 읽으므로,
    이 fixture가 세워야 하는 것은 "예전 `status='active'` 값"이 아니라 그 값이
    뜻하던 상태 — 즉 view의 통과 조건인 (lifecycle=active, publication=published,
    quality=valid) 삼중항이다. 0095 backfill도 `status='active'`를 정확히 이
    삼중항으로 옮겼으므로 여기 세 축을 명시하는 것이 원래 의도의 등가 이식이다.
    """
    await session.execute(
        text(
            """
            INSERT INTO feature.features (
                feature_id, kind, name, category, coord,
                lifecycle_state, publication_state, quality_state, updated_at,
                sido_code, sigungu_code, legal_dong_code
            )
            VALUES (
                :fid, 'place', 'x', '06020000',
                x_extension.ST_SetSRID(
                    x_extension.ST_MakePoint(
                        CAST(:lon AS double precision), CAST(:lat AS double precision)
                    ), 4326
                ),
                'active', 'published', 'valid', :ts, :sido, :sigungu, :bjd
            )
            """
        ),
        {
            "fid": fid, "lon": lon, "lat": lat, "ts": _FETCHED,
            "sido": sido, "sigungu": sigungu, "bjd": bjd,
        },
    )
    await session.flush()


async def test_cluster_features_in_bbox_rollup(migrated_session: AsyncSession) -> None:
    await _ins(
        migrated_session, fid="c1", lon=126.97, lat=37.56,
        sido="11", sigungu="11110", bjd="1111010100",
    )
    await _ins(
        migrated_session, fid="c2", lon=126.99, lat=37.57,
        sido="11", sigungu="11110", bjd="1111010200",
    )
    await _ins(
        migrated_session, fid="c3", lon=127.05, lat=37.50,
        sido="11", sigungu="11140", bjd="1114010100",
    )

    sigungu = await feature_repo.cluster_features_in_bbox(
        migrated_session, min_lon=126, min_lat=37, max_lon=128, max_lat=38,
        cluster_unit="sigungu",
    )
    by_key = {c["cluster_key"]: c for c in sigungu}
    assert by_key["11110"]["feature_count"] == 2
    assert by_key["11140"]["feature_count"] == 1
    # region 평균 좌표(대표 마커 위치).
    assert abs(by_key["11110"]["lon"] - 126.98) < 0.05
    assert abs(by_key["11110"]["lat"] - 37.565) < 0.05

    sido = await feature_repo.cluster_features_in_bbox(
        migrated_session, min_lon=126, min_lat=37, max_lon=128, max_lat=38,
        cluster_unit="sido",
    )
    assert len(sido) == 1
    assert sido[0]["cluster_key"] == "11"
    assert sido[0]["feature_count"] == 3


async def test_cluster_features_in_bbox_invalid(migrated_session: AsyncSession) -> None:
    with pytest.raises(ValueError, match="cluster_unit"):
        await feature_repo.cluster_features_in_bbox(
            migrated_session, min_lon=126, min_lat=37, max_lon=127, max_lat=38,
            cluster_unit="bogus",
        )
