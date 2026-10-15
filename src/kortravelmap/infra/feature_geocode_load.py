"""적재 경로의 geo 재해석 — stale 분기·값 동일 무쓰기·빈 답 가드·override finding(ADR-109).

``load_bundle``(``infra/feature_repo.py``)이 부르는 순수 판정과 그 판정이 읽는 DB 사실을 모은다.
재지오코딩은 새 엔진이 아니라 적재 경로의 unchanged-skip 보강이다 — 같은 payload라도 행의 스탬프가
현재 토큰과 다르면(stale) 적재 경로를 다시 탄다. 그때 세 규칙이 데이터를 지킨다:

- **값 동일 무쓰기.** 새로 지오코딩한 주소 유도 열이 저장된 값과 같으면 ``features``를 쓰지 않고
  스탬프만 전진한다 — ``row_revision``(ETag·seal·cache target 입력)을 값 변화 없이 흔들지 않는다.
  사람이 고정한 열(active override)은 비교에서 뺀다 — patch가 어차피 건너뛰므로 넣으면 "항상
  다름"이다.
- **빈 답 가드(행).** geo가 부분장애로 빈 답을 내면 새 bundle의 geo 유도 필드가 전부
  None이 된다. 저장된 같은 필드에 값이 있는데 새 값이 전부 None이면 주소 열을 덮지 않고
  스탬프도 찍지 않는다(다음 run이 다시 본다). 판정 필드는 **geo에서만 오는 것**이다 —
  ``road/legal/admin``은 여러 provider가 원문으로 채우므로 넣으면 그 provider에서 가드가 영영
  발화하지 않는다(``docs/etl/address-geocoding.md`` §4).
- **부분 퇴행 유지.** stale 행에서 새 답의 법정동코드가 저장값과 같은데 geo에서만 오는 필드
  (``road_name_code``·``admin_dong_code``·``zipcode``)가 새 답에서만 비었으면 그 필드는 저장값을
  지킨다 — 같은 위치의 같은 법정동인데 값이 사라진 것은 데이터 변경보다 부분 응답일 가능성이 크다.
- **override finding.** override 값과 새 geo 값이 다르면 ``address_override_geo_stale``(info) 1건을
  ``(feature_id, geo_data_token)``로 dedupe해 남긴다. 사람의 결정은 자동으로 바꾸지 않는다.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final

from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.types import Text

from kortravelmap.dto import Address

if TYPE_CHECKING:
    from collections.abc import Collection

    from sqlalchemy.engine import RowMapping
    from sqlalchemy.ext.asyncio import AsyncSession

__all__ = [
    "ADDRESS_GEO_COLUMNS",
    "GEO_GUARD_ADDRESS_FIELDS",
    "PARTIAL_REGRESSION_FIELDS",
    "StoredGeoColumns",
    "address_column_values",
    "differing_columns",
    "empty_answer_guard",
    "override_mismatches",
    "provider_code_present",
    "keep_partially_regressed_fields",
    "read_stored_geo_columns",
    "read_stored_geo_columns_many",
    "record_override_geo_stale",
]

#: ``features``의 주소 유도 열(``address`` jsonb + 코드 6개) — ``_feature_params``가 ``Address``에서
#: 쓴다.
ADDRESS_GEO_COLUMNS: Final[tuple[str, ...]] = (
    "address",
    "legal_dong_code",
    "road_name_code",
    "road_address_management_no",
    "admin_dong_code",
    "sido_code",
    "sigungu_code",
)

#: 빈 답 가드의 판정 필드 중 ``address`` jsonb 안의 것 — 어느 provider에서도 geo에서만 온다.
GEO_GUARD_ADDRESS_FIELDS: Final[tuple[str, ...]] = (
    "sido_name",
    "sigungu_name",
    "admin_dong_code",
    "road_name_code",
    "zipcode",
)

#: 판정 필드 중 열 — provider payload에 법정동코드가 있는 행에서는 뺀다(provider가 채운 값이다).
_GEO_GUARD_CODE_COLUMNS: Final[tuple[str, ...]] = ("legal_dong_code", "sigungu_code")

_OVERRIDE_VIOLATION_TYPE: Final[str] = "address_override_geo_stale"


def address_column_values(address: Address) -> dict[str, Any]:
    """``Address`` → 적재가 쓰는 주소 유도 열 값(``feature_repo._feature_params``와 같은 대응)."""
    return {
        "address": json.loads(address.model_dump_json()),
        "legal_dong_code": address.bjd_code,
        "road_name_code": address.road_name_code,
        "road_address_management_no": address.road_address_management_no,
        "admin_dong_code": address.admin_dong_code,
        "sido_code": address.sido_code,
        "sigungu_code": address.sigungu_code,
    }


def provider_code_present(raw_data: object, *, _depth: int = 0) -> bool:
    """source_record payload에 provider 법정동코드(``legal_dong_code``)가 있는가(깊이 4까지)."""
    if _depth > 4:
        return False
    if isinstance(raw_data, Mapping):
        value = raw_data.get("legal_dong_code")
        if isinstance(value, str) and value.strip():
            return True
        return any(
            provider_code_present(child, _depth=_depth + 1)
            for child in raw_data.values()
            if isinstance(child, Mapping)
        )
    return False


@dataclass(frozen=True)
class StoredGeoColumns:
    """저장된 주소 유도 열과 그 열들의 active override(``field_path → override_value``)."""

    values: Mapping[str, Any]
    overrides: Mapping[str, Any]

    def overridden_columns(self) -> frozenset[str]:
        return frozenset(path.removeprefix("core.") for path in self.overrides)


_STORED_COLUMNS_SQL: Final[str] = """
       feature.address, feature.legal_dong_code, feature.road_name_code,
       feature.road_address_management_no, feature.admin_dong_code,
       feature.sido_code, feature.sigungu_code,
       COALESCE(
           (SELECT jsonb_object_agg(override.field_path, override.override_value)
              FROM ops.feature_overrides AS override
             WHERE override.feature_id = feature.feature_id
               AND override.status = 'active'
               AND override.field_path = ANY(CAST(:field_paths AS text[]))),
           '{}'::jsonb
       ) AS overrides
"""

_READ_STORED_SQL: Final = text(
    "SELECT"
    + _STORED_COLUMNS_SQL
    + """  FROM feature.features AS feature
 WHERE feature.feature_id = CAST(:feature_id AS uuid)
"""
)

_READ_STORED_MANY_SQL: Final = text(
    "SELECT feature.feature_id::text AS feature_id,"
    + _STORED_COLUMNS_SQL
    + """  FROM feature.features AS feature
 WHERE feature.feature_id = ANY(CAST(:feature_ids AS uuid[]))
"""
).bindparams(bindparam("feature_ids", type_=ARRAY(Text)))

_FIELD_PATHS: Final[list[str]] = [f"core.{column}" for column in ADDRESS_GEO_COLUMNS]


def _stored_from_row(row: RowMapping) -> StoredGeoColumns:
    values = {column: row[column] for column in ADDRESS_GEO_COLUMNS}
    if isinstance(values["address"], str):
        values["address"] = json.loads(values["address"])
    overrides = row["overrides"]
    if isinstance(overrides, str):
        overrides = json.loads(overrides)
    return StoredGeoColumns(values=values, overrides=dict(overrides or {}))


async def read_stored_geo_columns(session: AsyncSession, feature_id: str) -> StoredGeoColumns:
    row = (
        await session.execute(
            _READ_STORED_SQL, {"feature_id": feature_id, "field_paths": _FIELD_PATHS}
        )
    ).mappings().one()
    return _stored_from_row(row)


async def read_stored_geo_columns_many(
    session: AsyncSession, feature_ids: Collection[str]
) -> dict[str, StoredGeoColumns]:
    """:func:`read_stored_geo_columns`의 chunk 판 — 한 번의 왕복으로 ``feature_id → 저장값``."""
    if not feature_ids:
        return {}
    rows = (
        await session.execute(
            _READ_STORED_MANY_SQL,
            {"feature_ids": list(feature_ids), "field_paths": _FIELD_PATHS},
        )
    ).mappings().all()
    return {str(row["feature_id"]): _stored_from_row(row) for row in rows}


def _guard_values(values: Mapping[str, Any], *, provider_code: bool) -> list[Any]:
    address = values.get("address") or {}
    picked = [address.get(field) for field in GEO_GUARD_ADDRESS_FIELDS]
    if not provider_code:
        picked += [values.get(column) for column in _GEO_GUARD_CODE_COLUMNS]
    return picked


def empty_answer_guard(
    stored: StoredGeoColumns, new: Mapping[str, Any], *, provider_code: bool
) -> bool:
    """저장된 판정 필드에 값이 있는데 새 판정 필드가 전부 비었는가 — 참이면 덮지 않는다."""
    stored_values = _guard_values(stored.values, provider_code=provider_code)
    new_values = _guard_values(new, provider_code=provider_code)
    stored_any = any(value not in (None, "") for value in stored_values)
    new_all_empty = all(value in (None, "") for value in new_values)
    return stored_any and new_all_empty


#: 부분 퇴행 유지 대상 중 낱개로 지키는 필드 — geo에서만 오고 같은 법정동 안에서 사라질 이유가 없다.
#: ``road_name_code``는 도로명주소와 짝이라 :func:`keep_partially_regressed_fields`가 따로 다룬다.
PARTIAL_REGRESSION_FIELDS: Final[tuple[str, ...]] = ("admin_dong_code", "zipcode")


def keep_partially_regressed_fields(
    stored: StoredGeoColumns, address: Address
) -> tuple[Address, tuple[str, ...]]:
    """새 답이 저장값과 같은 법정동인데 geo 전용 필드만 잃었으면 그 필드는 저장값을 지킨다.

    ``admin_dong_code``·``zipcode``는 낱개로 지킨다. ``road_name_code``는 새 도로명 텍스트가
    저장값과 같을 때만 낱개로, 아니면 ``road_address_management_no``와 **함께** 사라졌을 때만 짝으로
    지킨다(서로 다른 릴리스의 코드를 섞지 않는다).

    돌려주는 것은 (보정한 ``Address``, 지킨 필드). 법정동코드가 없거나 다르면 그대로다 — 위치·행정
    구역이 바뀐 행은 새 답이 정답이다. 그 필드에 override가 있으면 손대지 않는다(override가 이긴다).
    """
    stored_bjd = stored.values.get("legal_dong_code")
    if stored_bjd is None or address.bjd_code != stored_bjd:
        return address, ()
    stored_address = stored.values.get("address") or {}
    overridden = stored.overridden_columns()
    kept: dict[str, Any] = {}

    def lost(field_name: str) -> bool:
        return (
            field_name not in overridden
            and getattr(address, field_name) is None
            and stored_address.get(field_name) not in (None, "")
        )

    for field_name in PARTIAL_REGRESSION_FIELDS:
        if lost(field_name):
            kept[field_name] = stored_address[field_name]
    # 도로명코드는 도로명주소와 짝이다 — 서로 다른 릴리스의 코드를 섞지 않는다. 새 도로명 텍스트가
    # 저장값과 같으면 그 코드만, 다르면 도로명주소 관리번호도 함께 사라졌을 때 **둘을 함께** 지킨다.
    if lost("road_name_code"):
        if address.road is not None and address.road == stored_address.get("road"):
            kept["road_name_code"] = stored_address["road_name_code"]
        elif lost("road_address_management_no"):
            kept["road_name_code"] = stored_address["road_name_code"]
            kept["road_address_management_no"] = stored_address["road_address_management_no"]
    if not kept:
        return address, ()
    return address.model_copy(update=kept), tuple(sorted(kept))


def differing_columns(stored: StoredGeoColumns, new: Mapping[str, Any]) -> frozenset[str]:
    """override가 없는 주소 유도 열 중 값이 다른 열."""
    overridden = stored.overridden_columns()
    return frozenset(
        column
        for column in ADDRESS_GEO_COLUMNS
        if column not in overridden and stored.values.get(column) != new.get(column)
    )


def override_mismatches(
    stored: StoredGeoColumns, new: Mapping[str, Any]
) -> dict[str, dict[str, Any]]:
    """active override 값과 새 geo 값이 다른 열 → ``{override, geo}``."""
    mismatches: dict[str, dict[str, Any]] = {}
    for path, override_value in stored.overrides.items():
        column = path.removeprefix("core.")
        if column in new and override_value != new[column]:
            mismatches[column] = {"override": override_value, "geo": new[column]}
    return mismatches


_OPEN_OVERRIDE_FINDING_SQL: Final = text(
    """
SELECT 1
  FROM ops.data_integrity_violations AS finding
 WHERE finding.violation_type = :violation_type
   AND finding.status = 'open'
   AND (finding.payload ->> 'dedupe_key') = :dedupe_key
 LIMIT 1
"""
)

_INSERT_OVERRIDE_FINDING_SQL: Final = text(
    """
INSERT INTO ops.data_integrity_violations (
    provider_dataset_id, feature_id, violation_type, severity, message, payload
) VALUES (
    :provider_dataset_id, CAST(:feature_id AS uuid), :violation_type, 'info', :message,
    CAST(:payload AS jsonb)
)
"""
)


async def record_override_geo_stale(
    session: AsyncSession,
    *,
    feature_id: str,
    provider_dataset_id: int,
    geo_data_token: str,
    mismatches: Mapping[str, Mapping[str, Any]],
) -> bool:
    """override와 새 geo 값이 다르면 info finding 1건 — ``(feature_id, geo_data_token)``로 dedupe.

    같은 토큰에서 이미 열린 finding이 있으면 쓰지 않는다(False). 해소는 기존 admin 이슈 액션
    ``apply_kor_travel_geo_address``다.
    """
    if not mismatches:
        return False
    dedupe_key = f"{_OVERRIDE_VIOLATION_TYPE}:{feature_id}:{geo_data_token}"
    exists = (
        await session.execute(
            _OPEN_OVERRIDE_FINDING_SQL,
            {"violation_type": _OVERRIDE_VIOLATION_TYPE, "dedupe_key": dedupe_key},
        )
    ).first()
    if exists is not None:
        return False
    payload = {
        "dedupe_key": dedupe_key,
        "geo_data_token": geo_data_token,
        "override_values": {column: value["override"] for column, value in mismatches.items()},
        "geo_values": {column: value["geo"] for column, value in mismatches.items()},
    }
    await session.execute(
        _INSERT_OVERRIDE_FINDING_SQL,
        {
            "provider_dataset_id": provider_dataset_id,
            "feature_id": feature_id,
            "violation_type": _OVERRIDE_VIOLATION_TYPE,
            "message": (
                "주소 override 값이 새 kor-travel-geo 데이터셋의 값과 다르다 — "
                "필요하면 apply_kor_travel_geo_address로 갱신한다."
            ),
            "payload": json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        },
    )
    return True
