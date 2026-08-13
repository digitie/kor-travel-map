"""``feature_address_repo`` — admin 주소/좌표 override SQL (T-212 / DA-D-04).

``/admin/issues`` PATCH 액션(manual_override / apply_kor_travel_geo_address)이 쓰는
feature 주소·좌표 단건 조회/덮어쓰기 raw SQL이다. ORM 모델에는 로직을 두지 않고
본 모듈의 raw SQL로 처리한다(ADR-004). 공간 술어에서 ``ST_Transform``을 쓰지
않으며(ADR-012), 좌표는 ``coord``(4326)에 ``ST_SetSRID(ST_MakePoint(...))``로 적재한다.

commit은 호출자 책임 — 본 모듈 함수는 commit하지 않는다(호출자가 ``session.begin()``).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final

from sqlalchemy import text

if TYPE_CHECKING:
    from collections.abc import Mapping

    from sqlalchemy.ext.asyncio import AsyncSession

__all__ = [
    "FeatureAddressSnapshot",
    "FeatureAddressOverrideResult",
    "get_feature_address_snapshot",
    "apply_feature_address_override",
]


@dataclass(frozen=True)
class FeatureAddressSnapshot:
    """``feature.features`` 주소/좌표 단건 스냅샷."""

    feature_id: str
    lon: float | None
    lat: float | None
    address: dict[str, Any]
    legal_dong_code: str | None
    sido_code: str | None
    sigungu_code: str | None
    road_address_management_no: str | None
    lifecycle_state: str
    publication_state: str
    quality_state: str


@dataclass(frozen=True)
class FeatureAddressOverrideResult:
    """``apply_feature_address_override`` 결과 — 갱신된 스냅샷 + 덮어쓴 field_path 목록."""

    snapshot: FeatureAddressSnapshot
    overridden_fields: tuple[str, ...]


_SNAPSHOT_COLUMNS: Final[str] = (
    "feature_id, "
    "x_extension.ST_X(coord) AS lon, x_extension.ST_Y(coord) AS lat, "
    "address, legal_dong_code, sido_code, sigungu_code, "
    "road_address_management_no, lifecycle_state, publication_state, quality_state"
)

_GET_SNAPSHOT_SQL: Final[str] = f"""
SELECT {_SNAPSHOT_COLUMNS}
FROM feature.features
WHERE feature_id = :feature_id
"""

_LOCK_SNAPSHOT_SQL: Final[str] = f"""
SELECT {_SNAPSHOT_COLUMNS}
FROM feature.features
WHERE feature_id = :feature_id
FOR UPDATE
"""

# feature.features 좌표는 항상 4326으로 적재 (ADR-012 — 술어 ST_Transform 금지,
# coord_5179은 generated column이 자동 채움).
_COORD_SET_FRAGMENT: Final[str] = (
    "coord = x_extension.ST_SetSRID("
    "x_extension.ST_MakePoint("
    "CAST(:lon AS double precision), CAST(:lat AS double precision)"
    "), 4326)"
)

def _json_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, str):
        value = json.loads(value)
    return dict(value) if value else {}


def _dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _row_to_snapshot(row: Any) -> FeatureAddressSnapshot:
    return FeatureAddressSnapshot(
        feature_id=str(row.feature_id),
        lon=float(row.lon) if row.lon is not None else None,
        lat=float(row.lat) if row.lat is not None else None,
        address=_json_dict(row.address),
        legal_dong_code=row.legal_dong_code,
        sido_code=row.sido_code,
        sigungu_code=row.sigungu_code,
        road_address_management_no=row.road_address_management_no,
        lifecycle_state=str(row.lifecycle_state),
        publication_state=str(row.publication_state),
        quality_state=str(row.quality_state),
    )


async def get_feature_address_snapshot(
    session: AsyncSession,
    feature_id: str,
) -> FeatureAddressSnapshot | None:
    """feature 주소/좌표 단건 스냅샷. 없으면 ``None``."""
    row = (
        await session.execute(
            text(_GET_SNAPSHOT_SQL),
            {"feature_id": feature_id},
        )
    ).one_or_none()
    return _row_to_snapshot(row) if row is not None else None


async def apply_feature_address_override(
    session: AsyncSession,
    feature_id: str,
    *,
    address: Mapping[str, Any] | None = None,
    lon: float | None = None,
    lat: float | None = None,
    legal_dong_code: str | None = None,
    sido_code: str | None = None,
    sigungu_code: str | None = None,
    road_address_management_no: str | None = None,
    reason: str | None = None,
    operator: str | None = None,
    prevent_provider_reactivation: bool = True,
) -> FeatureAddressOverrideResult | None:
    """feature 주소/좌표를 덮어쓴다.

    제공된(``None``이 아닌) 필드만 갱신한다. 좌표는 ``lon``/``lat`` 둘 다 주어야
    한다. T-VN-34A는 runtime의 범용 ``ops.feature_overrides`` DML을 폐쇄한다.
    lifecycle 외 field override는 T-VN-36 effective projection writer가 단일화할
    때까지 이 경로에서 새로 만들지 않는다. feature가 없으면 ``None``(라우터에서
    404). 변경할 필드가 하나도 없으면 ``ValueError``. commit은 호출자 책임.

    ``prevent_provider_reactivation``은 **현재 무효다.** override row를 아예 만들지
    않으므로 켜든 끄든 동작이 같다. API/프론트가 계속 이 값을 보내고 있어 시그니처를
    지우지 않았지만(계약을 깨면 PinVi 재vendoring까지 번진다), 살아 있는 제어처럼
    읽히면 안 된다 — 운영자는 "provider 재적재로부터 잠갔다"고 믿는데 실제로는
    아무것도 잠기지 않는다. T-VN-36이 field override provenance를 되살릴 때 이 인자를
    **의식적으로** 다시 배선해야 하고, 그 전까지는 무효라는 사실을
    ``test_address_override_reactivation_flag_is_inert_until_tvn36``가 고정한다.
    """
    if lon is None and lat is None:
        coord_update = False
    elif lon is not None and lat is not None:
        coord_update = True
    else:
        raise ValueError("coord override는 lon/lat 둘 다 필요함")

    has_mutation = (
        address is not None
        or coord_update
        or legal_dong_code is not None
        or sido_code is not None
        or sigungu_code is not None
        or road_address_management_no is not None
    )
    if not has_mutation:
        raise ValueError("덮어쓸 주소/좌표 필드가 최소 1개 필요함")

    # Feature 행 lock은 core write의 TOCTOU를 막는다. generic override write는
    # T-VN-36 소유라 여기서 재도입하지 않는다.
    locked = (
        await session.execute(
            text(_LOCK_SNAPSHOT_SQL),
            {"feature_id": feature_id},
        )
    ).one_or_none()
    if locked is None:
        return None
    set_fragments: list[str] = ["updated_at = now()"]
    params: dict[str, Any] = {"feature_id": feature_id}
    overridden_fields: list[str] = []

    if address is not None:
        set_fragments.append("address = CAST(:address AS jsonb)")
        params["address"] = _dumps(dict(address))
        overridden_fields.append("address")
    if coord_update:
        set_fragments.append(_COORD_SET_FRAGMENT)
        params["lon"] = lon
        params["lat"] = lat
        overridden_fields.append("coord")
    if legal_dong_code is not None:
        set_fragments.append("legal_dong_code = :legal_dong_code")
        params["legal_dong_code"] = legal_dong_code
        overridden_fields.append("legal_dong_code")
    if sido_code is not None:
        set_fragments.append("sido_code = :sido_code")
        params["sido_code"] = sido_code
        overridden_fields.append("sido_code")
    if sigungu_code is not None:
        set_fragments.append("sigungu_code = :sigungu_code")
        params["sigungu_code"] = sigungu_code
        overridden_fields.append("sigungu_code")
    if road_address_management_no is not None:
        set_fragments.append(
            "road_address_management_no = :road_address_management_no"
        )
        params["road_address_management_no"] = road_address_management_no
        overridden_fields.append("road_address_management_no")

    update_sql = (
        "UPDATE feature.features SET "
        + ", ".join(set_fragments)
        + " WHERE feature_id = :feature_id "
        + f"RETURNING {_SNAPSHOT_COLUMNS}"
    )
    updated_row = (await session.execute(text(update_sql), params)).one()
    snapshot = _row_to_snapshot(updated_row)

    return FeatureAddressOverrideResult(
        snapshot=snapshot,
        overridden_fields=tuple(overridden_fields),
    )
