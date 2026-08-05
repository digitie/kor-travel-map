"""typed subtype 매핑·관측 (T-VN-35, ADR-084).

``feature.features``의 kind별 ``detail`` JSONB와 subtype 테이블
(``feature_places``/``feature_events``/``feature_notices``/``feature_routes``/
``feature_areas``) 사이의 **단일 매핑 정본**이다. writer는 여기서 파라미터를
만들고, backfill migration(0084~0086)은 같은 규칙을 SQL로 표현한다 — 두
표현이 어긋나면 drift 관측이 잡는다.

단일 정본 계약 (ADR-084 결정 4)
-------------------------------

- subtype이 kind별 값의 **유일한 정본**이다. core ``detail``은 0086에서
  제거됐고, 응답용 ``detail``은 ``feature.features_detailed`` 뷰가 subtype에서
  조립한다. writer는 subtype에만 쓴다 — 이중 쓰기도, drift도 없다.
- 배타 arc(kind 상수 CHECK + ``(feature_id, kind)`` 복합 FK)가 "한 feature는
  최대 한 subtype" 과 "subtype이 있는 동안 core kind 불변"을 DB에서 강제한다.
- price/weather는 subtype이 없다(detail이 비어 있고 값 정본은 별도 테이블).

파싱 규칙은 migration backfill과 **글자 그대로 같은 판정**이어야 한다:
선택 필드는 날짜 ISO 형식만·timestamptz는 파싱 가능한 값만 받고 나머지는
NULL로 남기며, 필수 필드는 결측을 거부한다(NOT NULL 제약과 같은 판정).
"""

from __future__ import annotations

import json
import re
from datetime import date, datetime
from typing import TYPE_CHECKING, Any, Final

from sqlalchemy import text

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from sqlalchemy.ext.asyncio import AsyncSession

__all__ = [
    "SUBTYPE_TABLES",
    "count_subtype_drift",
    "subtype_params",
    "subtype_table_for_kind",
]

#: kind → subtype 테이블. 여기 없는 kind(price/weather)는 subtype이 없다.
SUBTYPE_TABLES: Final[dict[str, str]] = {
    "place": "feature_places",
    "event": "feature_events",
    "notice": "feature_notices",
    "route": "feature_routes",
    "area": "feature_areas",
}

_ISO_DATE_RE: Final[re.Pattern[str]] = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def subtype_table_for_kind(kind: str) -> str | None:
    """kind의 subtype 테이블 이름 (없으면 ``None``)."""
    return SUBTYPE_TABLES.get(kind)


def _iso_date(value: Any) -> date | None:
    """ISO ``YYYY-MM-DD``만 date로. 그 외(자유 문자열·부분 날짜)는 None."""
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if not isinstance(value, str) or not _ISO_DATE_RE.match(value):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _aware_datetime(value: Any) -> datetime | None:
    """파싱 가능한 시각만 datetime으로 (migration의 ``pg_input_is_valid`` 대응)."""
    if isinstance(value, datetime):
        return value
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _text(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _required(value: Any, field: str) -> str:
    """NOT NULL typed 컬럼의 필수 값 — 결측은 sentinel로 덮지 않고 거부한다.

    ``'unknown'`` 같은 가짜 값은 "없음"과 "unknown이라는 값"을 뭉개고, 그
    구분을 되살리려 소비 측이 ``NULLIF(x, 'unknown')`` 같은 우회를 짜게 만든다
    (실제로 공개 festival 표면이 그랬다). DTO가 필수로 강제하는 필드이므로
    결측은 상류 결함이고, 여기서 크게 실패하는 편이 옳다.
    """
    text_value = _text(value)
    if text_value is None:
        raise ValueError(f"subtype 필수 필드 결측: {field}")
    return text_value


def _object(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _optional_object(value: Any) -> dict[str, Any] | None:
    return dict(value) if isinstance(value, dict) else None


def _bind_jsonb(params: dict[str, Any]) -> dict[str, Any]:
    """jsonb 컬럼 값(dict)을 JSON 문자열로 직렬화한다.

    raw ``text()`` 실행 경로에는 컬럼 타입 정보가 없어 SQLAlchemy/asyncpg가
    dict를 jsonb로 인코딩하지 못한다 — 실측:
    ``DataError: invalid input for query argument $9: {...}
    ('dict' object has no attribute 'encode')``. 저장소 전 raw SQL이 이미
    ``json.dumps`` + jsonb 바인딩 관례를 따르므로 여기서 한 번만 맞춘다
    (writer가 각자 직렬화하면 규칙이 갈라진다).

    ``phones``(``text[]``)는 list라 그대로 통과하고, ``None``은 SQL NULL로
    남는다 — dict만 대상이다.
    """

    return {
        key: (json.dumps(value, ensure_ascii=False, default=str)
              if isinstance(value, dict) else value)
        for key, value in params.items()
    }


def _int_in_range(value: Any, *, low: int, high: int) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int) and low <= value <= high:
        return value
    if isinstance(value, str) and value.isdigit() and low <= int(value) <= high:
        return int(value)
    return None


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _positive_int(value: Any) -> int | None:
    return _int_in_range(value, low=1, high=2**31 - 1)


def _string_list(value: Any, *, limit: int = 3) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)][:limit]


def subtype_params(
    *,
    feature_id: str,
    feature_uuid: str,
    kind: str,
    detail: Mapping[str, Any] | None,
) -> dict[str, Any] | None:
    """kind별 subtype upsert 파라미터 (subtype이 없는 kind면 ``None``).

    필수 필드(place_kind/event_kind/notice_type)가 없으면 ``ValueError``로
    거부한다 — sentinel로 덮지 않는다(``_required`` docstring). route/area의
    ``route_type``/``area_kind``는 DTO 자체가 기본값을 갖는 필드라 그 기본을
    그대로 쓴다.
    """
    if kind not in SUBTYPE_TABLES:
        return None
    payload = _object(detail)
    common: dict[str, Any] = {
        "feature_id": feature_id,
        "feature_uuid": feature_uuid,
        "kind": kind,
    }
    if kind == "place":
        return _bind_jsonb(common | {
            "place_kind": _required(payload.get("place_kind"), "place_kind"),
            "phones": _string_list(payload.get("phones")),
            "biz_number": _text(payload.get("biz_number")),
            "license_date": _iso_date(payload.get("license_date")),
            "business_hours": _optional_object(payload.get("business_hours")),
            "facility_info": _object(payload.get("facility_info")),
            "reviews_link": _object(payload.get("reviews_link")),
            "payload": _object(payload.get("payload")),
        })
    if kind == "event":
        return _bind_jsonb(common | {
            "event_kind": _required(payload.get("event_kind"), "event_kind"),
            "starts_on": _iso_date(payload.get("starts_on")),
            "ends_on": _iso_date(payload.get("ends_on")),
            "timezone": _text(payload.get("timezone")) or "Asia/Seoul",
            "opening_hours": _optional_object(payload.get("opening_hours")),
            "venue_name": _text(payload.get("venue_name")),
            "tel": _text(payload.get("tel")),
            "content_id": _text(payload.get("content_id")),
            "content_type_id": _text(payload.get("content_type_id")),
            "area_code": _text(payload.get("area_code")),
            "payload": _object(payload.get("payload")),
        })
    if kind == "notice":
        return _bind_jsonb(common | {
            "notice_type": _required(payload.get("notice_type"), "notice_type"),
            "severity": _int_in_range(payload.get("severity"), low=0, high=5),
            "valid_start_time": _aware_datetime(payload.get("valid_start_time")),
            "valid_end_time": _aware_datetime(payload.get("valid_end_time")),
            "source_agency": _text(payload.get("source_agency")),
            "officer_name": _text(payload.get("officer_name")),
            "payload": _object(payload.get("payload")),
        })
    if kind == "route":
        return _bind_jsonb(common | {
            "route_type": _text(payload.get("route_type")) or "route",
            "geometry_source": _text(payload.get("geometry_source")),
            "geometry_status": _text(payload.get("geometry_status")),
            "total_distance_meters": _number(payload.get("total_distance_meters")),
            "expected_duration_minutes": _positive_int(
                payload.get("expected_duration_minutes")
            ),
            "difficulty": _text(payload.get("difficulty")),
            "begin_name": _text(payload.get("begin_name")),
            "begin_address": _text(payload.get("begin_address")),
            "end_name": _text(payload.get("end_name")),
            "end_address": _text(payload.get("end_address")),
            "payload": _object(payload.get("payload")),
        })
    # area
    return _bind_jsonb(common | {
        "area_kind": _text(payload.get("area_kind")) or "area",
        "boundary_source": _text(payload.get("boundary_source")),
        "area_square_meters": _number(payload.get("area_square_meters")),
        "regulation_scope": _text(payload.get("regulation_scope")),
        "administrative_office": _text(payload.get("administrative_office")),
        "description": _text(payload.get("description")),
        "payload": _object(payload.get("payload")),
    })


# subtype 사본 무결성 관측 — ``count_features_missing_identity``(0083 선례)와
# 같은 성격이다. 0이 아니면 writer 이중 쓰기가 새고 있다는 뜻이므로 호출자는
# fail-close 판정에 쓴다.
_SUBTYPE_DRIFT_SQL: Final[str] = """
WITH expected AS (
    SELECT f.feature_id, f.kind
    FROM feature.features AS f
    WHERE f.kind = ANY(CAST(:kinds AS text[]))
), actual AS (
    SELECT feature_id, kind FROM feature.feature_places
    UNION ALL SELECT feature_id, kind FROM feature.feature_events
    UNION ALL SELECT feature_id, kind FROM feature.feature_notices
    UNION ALL SELECT feature_id, kind FROM feature.feature_routes
    UNION ALL SELECT feature_id, kind FROM feature.feature_areas
)
SELECT
    (
        SELECT count(*) FROM expected e
        LEFT JOIN actual a ON a.feature_id = e.feature_id
        WHERE a.feature_id IS NULL
    ) AS missing_subtype,
    (
        SELECT count(*) FROM actual a
        LEFT JOIN feature.features f ON f.feature_id = a.feature_id
        WHERE f.feature_id IS NULL
    ) AS orphan_subtype,
    (
        SELECT count(*) FROM actual a
        JOIN feature.features f ON f.feature_id = a.feature_id
        WHERE f.kind IS DISTINCT FROM a.kind
    ) AS kind_mismatch
"""


async def count_subtype_drift(session: AsyncSession) -> tuple[int, int, int]:
    """(subtype 결측, 고아 subtype, kind 불일치) — 정상은 ``(0, 0, 0)``.

    ``kind_mismatch``/``orphan_subtype``은 배타 arc FK가 이미 구조적으로
    막지만(replica-mode 우회 제외) 관측을 함께 둔다 — 0083 identity 4축과
    같은 규약이다. ``missing_subtype``만이 writer 이중 쓰기 누락을 직접
    드러내는 축이다.
    """
    row = (
        await session.execute(
            text(_SUBTYPE_DRIFT_SQL), {"kinds": list(SUBTYPE_TABLES)}
        )
    ).mappings().one()
    return (
        int(row["missing_subtype"]),
        int(row["orphan_subtype"]),
        int(row["kind_mismatch"]),
    )


#: route/area subtype은 geometry가 NOT NULL이다 — core upsert와 같은
#: ``:geom_wkt`` 파라미터를 쓰고 subtype 타입(Multi*)으로 승격해 바인딩한다.
_GEOM_EXPR: Final[dict[str, str]] = {
    "route": (
        "CAST(x_extension.ST_Multi(x_extension.ST_SetSRID("
        "x_extension.ST_GeomFromText(CAST(:geom_wkt AS text)), 4326)) "
        "AS x_extension.geometry(MultiLineString, 4326))"
    ),
    "area": (
        "CAST(x_extension.ST_Multi(x_extension.ST_SetSRID("
        "x_extension.ST_GeomFromText(CAST(:geom_wkt AS text)), 4326)) "
        "AS x_extension.geometry(MultiPolygon, 4326))"
    ),
}


def subtype_upsert_sql(kind: str) -> str | None:
    """kind별 subtype UPSERT SQL (writer 이중 쓰기 공용).

    core upsert와 **같은 트랜잭션**에서 실행한다. 충돌 시 전 컬럼을 갱신해
    core ``detail``의 최신 상태를 그대로 반영한다(사본 정의).

    route/area는 ``:geom_wkt``(core upsert와 같은 파라미터)를 추가로 요구한다 —
    geometry가 NOT NULL이므로 WKT가 없으면 subtype 행을 만들 수 없다(호출자가
    geometry 없는 route/area bundle을 거부해야 한다는 뜻이며, 이는 종전
    ``_INACTIVATE_GEOMETRYLESS_AREA_BY_SOURCE_SQL`` 보정이 하던 일을 write
    시점으로 앞당긴 것이다).
    """
    table = SUBTYPE_TABLES.get(kind)
    if table is None:
        return None
    columns = _SUBTYPE_COLUMNS[kind]
    geom_expr = _GEOM_EXPR.get(kind)
    all_columns = ("feature_id", "feature_uuid", "kind", *columns)
    values = [f":{name}" for name in all_columns]
    update_columns = list(columns)
    if geom_expr is not None:
        all_columns = (*all_columns, "geom")
        values.append(geom_expr)
        update_columns.append("geom")
    updates = ", ".join(f"{name} = EXCLUDED.{name}" for name in update_columns)
    return f"""
INSERT INTO feature.{table} ({", ".join(all_columns)})
VALUES ({", ".join(values)})
ON CONFLICT (feature_id) DO UPDATE SET {updates}
"""


_SUBTYPE_COLUMNS: Final[dict[str, Sequence[str]]] = {
    "place": (
        "place_kind",
        "phones",
        "biz_number",
        "license_date",
        "business_hours",
        "facility_info",
        "reviews_link",
        "payload",
    ),
    "event": (
        "event_kind",
        "starts_on",
        "ends_on",
        "timezone",
        "opening_hours",
        "venue_name",
        "tel",
        "content_id",
        "content_type_id",
        "area_code",
        "payload",
    ),
    "notice": (
        "notice_type",
        "severity",
        "valid_start_time",
        "valid_end_time",
        "source_agency",
        "officer_name",
        "payload",
    ),
    "route": (
        "route_type",
        "geometry_source",
        "geometry_status",
        "total_distance_meters",
        "expected_duration_minutes",
        "difficulty",
        "begin_name",
        "begin_address",
        "end_name",
        "end_address",
        "payload",
    ),
    "area": (
        "area_kind",
        "boundary_source",
        "area_square_meters",
        "regulation_scope",
        "administrative_office",
        "description",
        "payload",
    ),
}
