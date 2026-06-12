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
    status: str


@dataclass(frozen=True)
class FeatureAddressOverrideResult:
    """``apply_feature_address_override`` 결과 — 갱신된 스냅샷 + 덮어쓴 field_path 목록."""

    snapshot: FeatureAddressSnapshot
    overridden_fields: tuple[str, ...]


_SNAPSHOT_COLUMNS: Final[str] = (
    "feature_id, "
    "x_extension.ST_X(coord) AS lon, x_extension.ST_Y(coord) AS lat, "
    "address, legal_dong_code, sido_code, sigungu_code, "
    "road_address_management_no, status"
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

# admin_feature_repo._UPSERT_STATUS_OVERRIDE_SQL과 동일한 ON CONFLICT 규칙
# (feature_id, field_path) WHERE status='active'. source_value/override_value는
# jsonb로 직렬화해 보존한다.
_UPSERT_OVERRIDE_SQL: Final[str] = """
INSERT INTO ops.feature_overrides (
    feature_id, source_record_key, field_path,
    source_value, override_value, prevent_provider_reactivation,
    status, reason, created_by
) VALUES (
    :feature_id, NULL, :field_path,
    CAST(:source_value AS jsonb),
    CAST(:override_value AS jsonb),
    :prevent_provider_reactivation,
    'active', :reason, :operator
)
ON CONFLICT (feature_id, field_path) WHERE status = 'active'
DO UPDATE SET
    source_value = EXCLUDED.source_value,
    override_value = EXCLUDED.override_value,
    prevent_provider_reactivation = EXCLUDED.prevent_provider_reactivation,
    reason = EXCLUDED.reason,
    created_by = EXCLUDED.created_by,
    created_at = now()
"""


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
        status=str(row.status),
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
    """feature 주소/좌표를 덮어쓰고 ``ops.feature_overrides`` active row를 남긴다.

    제공된(``None``이 아닌) 필드만 갱신한다. 좌표는 ``lon``/``lat`` 둘 다 주어야
    하며, 변경된 field_path마다 override row(``source_value`` = 직전 값)를 upsert한다.
    feature가 없으면 ``None``(라우터에서 404). 변경할 필드가 하나도 없으면
    ``ValueError``. commit은 호출자 책임.
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

    # 직전 값 보존을 위해 row를 잠그고 현재 스냅샷을 읽는다.
    locked = (
        await session.execute(
            text(_LOCK_SNAPSHOT_SQL),
            {"feature_id": feature_id},
        )
    ).one_or_none()
    if locked is None:
        return None
    previous = _row_to_snapshot(locked)

    set_fragments: list[str] = ["updated_at = now()"]
    params: dict[str, Any] = {"feature_id": feature_id}
    # field_path → (직전 값, 새 값) — override row 보존용.
    overrides: list[tuple[str, Any, Any]] = []

    if address is not None:
        set_fragments.append("address = CAST(:address AS jsonb)")
        params["address"] = _dumps(dict(address))
        overrides.append(("address", previous.address or None, dict(address)))
    if coord_update:
        set_fragments.append(_COORD_SET_FRAGMENT)
        params["lon"] = lon
        params["lat"] = lat
        prev_coord = (
            {"lon": previous.lon, "lat": previous.lat}
            if previous.lon is not None and previous.lat is not None
            else None
        )
        overrides.append(("coord", prev_coord, {"lon": lon, "lat": lat}))
    if legal_dong_code is not None:
        set_fragments.append("legal_dong_code = :legal_dong_code")
        params["legal_dong_code"] = legal_dong_code
        overrides.append(
            ("legal_dong_code", previous.legal_dong_code, legal_dong_code)
        )
    if sido_code is not None:
        set_fragments.append("sido_code = :sido_code")
        params["sido_code"] = sido_code
        overrides.append(("sido_code", previous.sido_code, sido_code))
    if sigungu_code is not None:
        set_fragments.append("sigungu_code = :sigungu_code")
        params["sigungu_code"] = sigungu_code
        overrides.append(("sigungu_code", previous.sigungu_code, sigungu_code))
    if road_address_management_no is not None:
        set_fragments.append(
            "road_address_management_no = :road_address_management_no"
        )
        params["road_address_management_no"] = road_address_management_no
        overrides.append(
            (
                "road_address_management_no",
                previous.road_address_management_no,
                road_address_management_no,
            )
        )

    update_sql = (
        "UPDATE feature.features SET "
        + ", ".join(set_fragments)
        + " WHERE feature_id = :feature_id "
        + f"RETURNING {_SNAPSHOT_COLUMNS}"
    )
    updated_row = (await session.execute(text(update_sql), params)).one()
    snapshot = _row_to_snapshot(updated_row)

    for field_path, source_value, override_value in overrides:
        await session.execute(
            text(_UPSERT_OVERRIDE_SQL),
            {
                "feature_id": feature_id,
                "field_path": field_path,
                "source_value": _dumps(source_value),
                "override_value": _dumps(override_value),
                "prevent_provider_reactivation": prevent_provider_reactivation,
                "reason": reason,
                "operator": operator,
            },
        )

    return FeatureAddressOverrideResult(
        snapshot=snapshot,
        overridden_fields=tuple(field_path for field_path, _, _ in overrides),
    )
