"""``feature_address_repo`` 통합 테스트 (T-212 / DA-D-04 admin issues).

``apply_feature_address_override``의 raw SQL이 실제 PostGIS에서 동작하는지
검증한다 — 라우터 단위 테스트는 repo를 monkeypatch하므로 SQL 경로가 여기서만
실측된다(feature.features UPDATE + ops.feature_overrides upsert).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
from geoalchemy2 import WKTElement
from sqlalchemy import text

from krtour.map.infra.feature_address_repo import (
    apply_feature_address_override,
    get_feature_address_snapshot,
)
from krtour.map.infra.models import FeatureRow

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.integration

_NOW = datetime(2026, 6, 6, 9, 0, tzinfo=UTC)


def _feature_row(feature_id: str) -> FeatureRow:
    return FeatureRow(
        feature_id=feature_id,
        kind="place",
        name="광화문",
        category="01070300",
        coord=WKTElement("POINT(126.9769 37.5759)", srid=4326),
        address={"road": "서울특별시 종로구 세종대로 1"},
        detail={"place_kind": "attraction"},
        urls={},
        raw_refs=[],
        status="active",
        legal_dong_code="1111010100",
        sido_code="11",
        sigungu_code="11110",
        created_at=_NOW,
        updated_at=_NOW,
    )


async def test_snapshot_and_apply_override(migrated_session: AsyncSession) -> None:
    fid = "f_addr_override"
    migrated_session.add(_feature_row(fid))
    await migrated_session.flush()

    snap = await get_feature_address_snapshot(migrated_session, fid)
    assert snap is not None
    assert snap.legal_dong_code == "1111010100"
    assert snap.lon == pytest.approx(126.9769)

    result = await apply_feature_address_override(
        migrated_session,
        fid,
        address={"road": "서울특별시 중구 세종대로 110"},
        lon=126.9784,
        lat=37.5663,
        legal_dong_code="1114010300",
        sido_code="11",
        sigungu_code="11140",
        reason="manual fix",
        operator="tester",
    )
    assert result is not None
    assert set(result.overridden_fields) == {
        "address",
        "coord",
        "legal_dong_code",
        "sido_code",
        "sigungu_code",
    }
    assert result.snapshot.address == {"road": "서울특별시 중구 세종대로 110"}
    assert result.snapshot.legal_dong_code == "1114010300"
    assert result.snapshot.lat == pytest.approx(37.5663)

    # feature.features 실제 갱신 확인.
    refreshed = await get_feature_address_snapshot(migrated_session, fid)
    assert refreshed is not None
    assert refreshed.sigungu_code == "11140"

    # ops.feature_overrides active row가 field_path별로 남았는지 확인.
    rows = (
        await migrated_session.execute(
            text(
                "SELECT field_path, override_value, source_value, created_by "
                "FROM ops.feature_overrides "
                "WHERE feature_id = :fid AND status = 'active' "
                "ORDER BY field_path"
            ),
            {"fid": fid},
        )
    ).all()
    by_path = {row.field_path: row for row in rows}
    assert {"address", "coord", "legal_dong_code", "sido_code", "sigungu_code"} <= set(
        by_path
    )
    assert by_path["coord"].override_value == {"lon": 126.9784, "lat": 37.5663}
    assert by_path["legal_dong_code"].source_value == "1111010100"
    assert by_path["address"].created_by == "tester"

    # 같은 field_path 재적용 — ON CONFLICT 갱신(중복 없음).
    again = await apply_feature_address_override(
        migrated_session,
        fid,
        legal_dong_code="1114010400",
        reason="second fix",
        operator="tester2",
    )
    assert again is not None
    active = (
        await migrated_session.execute(
            text(
                "SELECT count(*) FROM ops.feature_overrides "
                "WHERE feature_id = :fid AND field_path = 'legal_dong_code' "
                "AND status = 'active'"
            ),
            {"fid": fid},
        )
    ).scalar_one()
    assert active == 1


async def test_apply_override_missing_feature_returns_none(
    migrated_session: AsyncSession,
) -> None:
    result = await apply_feature_address_override(
        migrated_session,
        "f_does_not_exist",
        legal_dong_code="1111010100",
    )
    assert result is None


async def test_apply_override_requires_a_field(
    migrated_session: AsyncSession,
) -> None:
    fid = "f_addr_empty"
    migrated_session.add(_feature_row(fid))
    await migrated_session.flush()
    with pytest.raises(ValueError, match="최소 1개"):
        await apply_feature_address_override(migrated_session, fid)
