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

    # feature.features 실제 갱신 확인.
    refreshed = await get_feature_address_snapshot(migrated_session, fid)
    assert refreshed is not None
    assert refreshed.sigungu_code == "11140"

    # T-VN-34A runtime은 generic feature override DML을 폐쇄한다. address core
    # write는 유지하지만 T-VN-36 writer가 오기 전 새 override는 만들지 않는다.
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
    assert rows == []

    # 같은 field 재적용도 runtime의 generic override 권한을 되살리지 않는다.
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
    assert active == 0


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


async def test_address_override_reactivation_flag_is_inert_until_tvn36(
    migrated_session: AsyncSession,
) -> None:
    """``prevent_provider_reactivation``이 현재 아무것도 하지 않음을 고정한다.

    T-VN-34A가 runtime의 범용 ``ops.feature_overrides`` DML을 폐쇄해서 이 경로는
    override row를 **아예 만들지 않는다.** 그런데 API/프론트는 계속 이 값을 보내고
    라우터도 그대로 넘긴다 — 운영자 입장에서는 "provider 재적재로부터 잠갔다"고
    믿는데 실제로는 아무것도 잠기지 않는다.

    시그니처를 지우지 않은 이유는 계약을 깨면 PinVi 재vendoring까지 번지기 때문이고,
    T-VN-36이 field override provenance를 되살릴 때 이 인자를 다시 배선할 예정이기
    때문이다. 그때 이 테스트가 red가 되어 **의식적으로** 마주치게 만든다 — 조용히
    살아나거나 조용히 죽은 채로 남는 것 둘 다 막는다.
    """

    overrides_before = (
        await migrated_session.execute(
            text("SELECT count(*) FROM ops.feature_overrides")
        )
    ).scalar_one()

    for flag in (True, False):
        fid = f"f_addr_inert_{int(flag)}"
        migrated_session.add(_feature_row(fid))
        await migrated_session.flush()
        result = await apply_feature_address_override(
            migrated_session,
            fid,
            legal_dong_code="1114010300",
            reason="inert flag probe",
            operator="tester",
            prevent_provider_reactivation=flag,
        )
        assert result is not None, flag

    assert (
        await migrated_session.execute(
            text("SELECT count(*) FROM ops.feature_overrides")
        )
    ).scalar_one() == overrides_before
