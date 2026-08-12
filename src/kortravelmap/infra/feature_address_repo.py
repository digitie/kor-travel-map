"""``feature_address_repo`` — admin 주소/좌표 override SQL (T-212 / DA-D-04).

``/admin/issues`` PATCH 액션(manual_override / apply_kor_travel_geo_address)이 쓰는
feature 주소·좌표 단건 조회/덮어쓰기 raw SQL이다. ORM 모델에는 로직을 두지 않고
본 모듈의 raw SQL로 처리한다(ADR-004). 공간 술어에서 ``ST_Transform``을 쓰지
않으며(ADR-012), 좌표는 ``coord``(4326)에 ``ST_SetSRID(ST_MakePoint(...))``로 적재한다.

commit은 호출자 책임 — 본 모듈 함수는 commit하지 않는다(호출자가 ``session.begin()``).
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final

from sqlalchemy import text

from kortravelmap.infra.domain_command_repo import (
    canonical_domain_command_fingerprint,
    create_domain_command_claim,
    create_domain_command_record,
    lock_domain_command,
)

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
    "feature_id, row_revision, "
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

_AUTHOR_FEATURE_FIELD_OVERRIDES_SQL: Final[str] = """
CALL feature.author_feature_field_overrides(
    CAST(:feature_id AS text), CAST(:expected_row_revision AS bigint),
    CAST(:principal AS text), CAST(:reason_code AS text),
    CAST(:command_id AS bigint), CAST(:values AS jsonb),
    CAST(:geometry_wkt AS jsonb), NULL, NULL, NULL, NULL
)
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
    """주소/좌표 path만 typed field override command로 author한다.

    effective core/subtype에 raw UPDATE를 하지 않는다. 외부 HTTP command replay와
    별개로 field author command receipt를 같은 transaction에 남긴다.

    제공된(``None``이 아닌) 필드만 갱신한다. 좌표는 ``lon``/``lat`` 둘 다 주어야
    한다. feature가 없으면 ``None``(라우터에서 404). 변경할 필드가 하나도 없으면
    ``ValueError``. commit은 호출자 책임.

    ``prevent_provider_reactivation``은 **여전히 미사용이다.** T-VN-34A가 runtime의
    범용 ``ops.feature_overrides`` DML을 폐쇄했을 때 이 인자는 무효가 됐고, T-VN-36이
    field override를 되살린 지금도 배선되지 않았다. API/프론트는 계속 이 값을 보낸다 —
    운영자는 "provider 재적재로부터 잠갔다"고 믿는데 실제로는 아무것도 잠기지 않는다.
    시그니처를 지우지 않은 이유는 OpenAPI 계약이라 깨면 PinVi 재vendoring까지 번지기
    때문이다. 무효라는 사실은
    ``test_address_override_reactivation_flag_is_inert_until_tvn36``가 고정한다 —
    배선하려면 그 테스트를 **의식적으로** 고쳐야 한다.
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

    # procedure도 같은 core lock을 재사용하여 stale write를 fail-close한다.
    locked = (
        await session.execute(
            text(_LOCK_SNAPSHOT_SQL),
            {"feature_id": feature_id},
        )
    ).one_or_none()
    if locked is None:
        return None
    values: dict[str, Any] = {}
    geometry_wkt: dict[str, str | None] = {}
    overridden_fields: list[str] = []

    if address is not None:
        values["core.address"] = dict(address)
        overridden_fields.append("address")
    if coord_update:
        assert lon is not None
        assert lat is not None
        geometry_wkt["core.coord"] = f"POINT({lon} {lat})"
        values["core.coord_precision_digits"] = 6
        overridden_fields.append("coord")
    if legal_dong_code is not None:
        values["core.legal_dong_code"] = legal_dong_code
        overridden_fields.append("legal_dong_code")
    if sido_code is not None:
        values["core.sido_code"] = sido_code
        overridden_fields.append("sido_code")
    if sigungu_code is not None:
        values["core.sigungu_code"] = sigungu_code
        overridden_fields.append("sigungu_code")
    if road_address_management_no is not None:
        values["core.road_address_management_no"] = road_address_management_no
        overridden_fields.append("road_address_management_no")

    principal = (operator or "system:address-override").strip()
    reason_code = (reason or "address_override").strip()
    if not principal or not reason_code:
        raise ValueError("주소 override에는 authenticated operator와 reason이 필요합니다.")
    operation = "admin.feature.override.author"
    command_key = str(uuid.uuid4())
    command_payload = {
        "feature_id": feature_id,
        "values": values,
        "geometry_wkt": geometry_wkt,
        "reason_code": reason_code,
    }
    await lock_domain_command(
        session,
        actor=principal,
        operation=operation,
        idempotency_key=command_key,
    )
    claim = await create_domain_command_claim(
        session,
        actor=principal,
        operation=operation,
        idempotency_key=command_key,
        request_fingerprint=canonical_domain_command_fingerprint(command_payload),
    )
    updated = (
        await session.execute(
            text(_AUTHOR_FEATURE_FIELD_OVERRIDES_SQL),
            {
                "feature_id": feature_id,
                "expected_row_revision": int(locked.row_revision),
                "principal": principal,
                "reason_code": reason_code,
                "command_id": claim.command_id,
                "values": _dumps(values),
                "geometry_wkt": _dumps(geometry_wkt),
            },
        )
    ).mappings().one()
    await create_domain_command_record(
        session,
        command_id=claim.command_id,
        response_status=200,
        response_body={
            "feature_id": str(updated["o_feature_id"]),
            "row_revision": int(updated["o_row_revision"]),
            "overridden_fields": overridden_fields,
        },
        response_headers={},
    )
    updated_row = (
        await session.execute(text(_GET_SNAPSHOT_SQL), {"feature_id": feature_id})
    ).one()
    snapshot = _row_to_snapshot(updated_row)

    return FeatureAddressOverrideResult(
        snapshot=snapshot,
        overridden_fields=tuple(overridden_fields),
    )
