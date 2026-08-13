"""``feature_address_repo`` 통합 테스트 (T-212 / DA-D-04 admin issues).

``apply_feature_address_override``의 raw SQL이 실제 PostGIS에서 동작하는지
검증한다 — 라우터 단위 테스트는 repo를 monkeypatch하므로 SQL 경로가 여기서만
실측된다(typed field override author procedure + effective projection).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
from geoalchemy2 import WKTElement
from sqlalchemy import text

from kortravelmap.infra.feature_address_repo import (
    apply_feature_address_override,
    get_feature_address_snapshot,
)
from kortravelmap.infra.models import FeatureRow

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
        urls={},
        raw_refs=[],
        # 이 fixture가 원래 말하던 legacy ``status='active'``는 "공개 표면에
        # 정상적으로 실재하는 feature"라는 뜻이었다. T-VN-34 3축에서 그 한 값은
        # 세 축의 조합으로 흩어진다 — 살아있고(lifecycle=active), 공개돼 있으며
        # (publication=published), 격리되지 않은(quality=valid) 상태다. 주소/좌표
        # override SQL은 상태 축을 건드리지 않으므로 여기서는 "평범한 공개 feature"
        # 라는 출발점만 3축으로 정확히 재현하면 된다.
        lifecycle_state="active",
        publication_state="published",
        quality_state="valid",
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

    # effective projection 실제 갱신 확인.
    refreshed = await get_feature_address_snapshot(migrated_session, fid)
    assert refreshed is not None
    assert refreshed.sigungu_code == "11140"

    # 주소 writer는 generic override DML 없이 registry field path를 author한다.
    rows = (
        await migrated_session.execute(
            text(
                "SELECT field_path, override_value, source_value, created_by, "
                "x_extension.ST_AsText(value_geometry) AS value_geometry "
                "FROM ops.feature_overrides "
                "WHERE feature_id = :fid AND status = 'active' "
                "ORDER BY field_path"
            ),
            {"fid": fid},
        )
    ).all()
    actual_overrides = [
        (row.field_path, row.override_value, row.value_geometry, row.created_by)
        for row in rows
    ]
    assert actual_overrides == [
        ("core.address", {"road": "서울특별시 중구 세종대로 110"}, None, "tester"),
        ("core.coord", None, "POINT(126.9784 37.5663)", "tester"),
        ("core.coord_precision_digits", 6, None, "tester"),
        ("core.legal_dong_code", "1114010300", None, "tester"),
        ("core.sido_code", "11", None, "tester"),
        ("core.sigungu_code", "11140", None, "tester"),
    ]

    # 같은 field 재적용은 기존 active receipt를 supersede하고 하나만 남긴다.
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
                "WHERE feature_id = :fid AND field_path = 'core.legal_dong_code' "
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


async def test_address_override_is_lifecycle_reactivation_neutral(
    migrated_session: AsyncSession,
) -> None:
    """주소 override가 lifecycle 재적재 축을 건드리지 않음을 고정한다.

    T-VN-34A는 이 경로의 범용 override DML을 폐쇄해 ``prevent_provider_reactivation``
    인자를 무효로 만들었고, ``..._is_inert_until_tvn36``가 그 사실을 고정해 T-VN-36이
    field override를 되살릴 때 배선 여부를 의식적으로 마주치게 했다. 답은
    **배선하지 않는다**였다 — ``feature_repo``의 두 재적재 가드가 모두
    ``field_path = 'lifecycle_state'``로 한정되므로 그 플래그는 lifecycle 축 전용이고,
    주소/좌표 override에는 의미가 없다. 그래서 인자와 admin-issues 요청 필드를 함께
    제거했다.

    이 테스트가 지키는 것은 그 결정의 관측 가능한 귀결이다: 주소 override는
    ``lifecycle_state`` override를 만들지 않고, 남기는 field override row는 전부
    ``prevent_provider_reactivation = false``다. 즉 이 경로로는 재적재 잠금이
    **생길 수 없다**. 주소 보정이 provider 재적재에서 살아남는 근거는 별개로
    ``test_tvn36_registry_base_lineage_and_override_type_fence``(active override
    masking)가 지킨다.
    """

    fid = "f_addr_lifecycle_neutral"
    migrated_session.add(_feature_row(fid))
    await migrated_session.flush()
    result = await apply_feature_address_override(
        migrated_session,
        fid,
        legal_dong_code="1114010300",
        reason="lifecycle neutrality probe",
        operator="tester",
    )
    assert result is not None

    rows = (
        await migrated_session.execute(
            text(
                "SELECT field_path, prevent_provider_reactivation "
                "FROM ops.feature_overrides WHERE feature_id = :fid"
            ),
            {"fid": fid},
        )
    ).mappings().all()

    assert rows, "주소 override는 field override row를 남겨야 한다"
    assert [row["field_path"] for row in rows] == ["core.legal_dong_code"]
    assert all(row["prevent_provider_reactivation"] is False for row in rows)
