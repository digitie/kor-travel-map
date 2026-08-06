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
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, Final, cast

from pydantic import BaseModel, ValidationError
from sqlalchemy import text

from kortravelmap.dto import (
    AreaDetail,
    EventDetail,
    NoticeDetail,
    PlaceDetail,
    RouteDetail,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from sqlalchemy.ext.asyncio import AsyncSession

__all__ = [
    "DETAIL_MODEL_BY_KIND",
    "GEOMETRY_SUBTYPE_KINDS",
    "SUBTYPE_TABLES",
    "SubtypeDetailError",
    "count_subtype_drift",
    "subtype_params",
    "subtype_table_for_kind",
    "write_subtype",
]

#: geometry가 NOT NULL인 subtype — upsert가 ``:geom_wkt`` 바인딩을 요구한다.
GEOMETRY_SUBTYPE_KINDS: Final[frozenset[str]] = frozenset({"route", "area"})

#: kind → subtype 테이블. 여기 없는 kind(price/weather)는 subtype이 없다.
SUBTYPE_TABLES: Final[dict[str, str]] = {
    "place": "feature_places",
    "event": "feature_events",
    "notice": "feature_notices",
    "route": "feature_routes",
    "area": "feature_areas",
}


def subtype_table_for_kind(kind: str) -> str | None:
    """kind의 subtype 테이블 이름 (없으면 ``None``)."""
    return SUBTYPE_TABLES.get(kind)


#: kind → detail DTO. subtype 컬럼은 이 모델의 DB 대응물이므로, "detail이 kind
#: 계약에 맞는가"의 판정은 **모델 하나**가 갖는다. 종전에는 같은 판정이 세 벌로
#: 흩어져 있었다 — provider 경로의 DTO, admin 라우터의 boundary validator,
#: 그리고 이 모듈의 손수 만든 ``_text``/``_required`` 파서. 손수 만든 파서는
#: DTO가 이미 보장한 것을 다시 (다르게) 판정하는 사본이었다.
DETAIL_MODEL_BY_KIND: Final[dict[str, type[BaseModel]]] = {
    "place": PlaceDetail,
    "event": EventDetail,
    "notice": NoticeDetail,
    "route": RouteDetail,
    "area": AreaDetail,
}


class SubtypeDetailError(ValueError):
    """``detail``이 kind 계약에 맞지 않는다 — 상류(요청/provider) 결함이다.

    admin HTTP 경계는 이걸 422로 옮긴다. 종전에는 결측 필수 필드가 raw
    ``ValueError``로 새어 500이 됐고, 그 500은 **이미 접수된 change request**를
    영구히 승인 불가로 만들었다(적용 시점에 터지므로).
    """

    def __init__(self, kind: str, feature_id: str, cause: ValidationError) -> None:
        self.kind = kind
        self.feature_id = feature_id
        self.cause = cause
        super().__init__(
            f"feature {feature_id!r}: detail does not satisfy the {kind} contract: "
            f"{cause.errors(include_url=False)}"
        )


def _validated_detail(kind: str, feature_id: str, detail: Any) -> BaseModel:
    """raw dict든 DTO든 kind의 detail 모델 인스턴스로 정규화한다.

    이미 맞는 모델이면 그대로 쓴다 — provider 경로는 DTO를 들고 오므로 재검증
    비용이 0이고, admin 경로(raw JSON dict)만 실제 validate를 탄다.

    ``feature_id``는 detail 모델의 필수 키이고 항상 소유 feature와 같아야 하므로
    호출자 값으로 채운다(요청 본문이 생략해도, 다른 값을 보내도 소유자가 이긴다).
    """
    model = DETAIL_MODEL_BY_KIND[kind]
    if isinstance(detail, model):
        return detail
    raw = dict(detail) if isinstance(detail, Mapping) else {}
    raw["feature_id"] = feature_id
    try:
        return model.model_validate(raw)
    except ValidationError as exc:
        raise SubtypeDetailError(kind, feature_id, exc) from exc


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


def subtype_params(
    *,
    feature_id: str,
    feature_uuid: str,
    kind: str,
    detail: Any,
) -> dict[str, Any] | None:
    """kind별 subtype upsert 파라미터 (subtype이 없는 kind면 ``None``).

    ``detail``은 kind의 detail DTO로 검증·정규화된다 — 맞지 않으면
    ``SubtypeDetailError``다. 즉 "필수 필드 결측을 sentinel로 덮지 않는다"는
    규칙이 여기 손수 쓰인 게 아니라 DTO의 필수 선언에서 그대로 따라온다.

    jsonb로 갈 값만 ``model_dump(mode="json")``을 거친다 —
    ``reviews_link``(``AnyUrl``)·``business_hours``(중첩 모델)처럼 파이썬 객체를
    담은 필드가 있기 때문이다. 반대로 typed 컬럼(date/timestamptz/numeric)은
    모델 속성을 **그대로** 바인딩한다: 문자열로 낮췄다가 DB가 다시 파싱하게 하면
    표현이 한 번 더 갈라진다.
    """
    if kind not in SUBTYPE_TABLES:
        return None
    obj = _validated_detail(kind, feature_id, detail)
    as_json = obj.model_dump(mode="json")
    common: dict[str, Any] = {
        "feature_id": feature_id,
        "feature_uuid": feature_uuid,
        "kind": kind,
    }
    if isinstance(obj, PlaceDetail):
        return _bind_jsonb(common | {
            "place_kind": obj.place_kind,
            "phones": list(obj.phones),
            "biz_number": obj.biz_number,
            "license_date": obj.license_date,
            "business_hours": as_json["business_hours"],
            "facility_info": as_json["facility_info"],
            "reviews_link": as_json["reviews_link"],
            "payload": as_json["payload"],
        })
    if isinstance(obj, EventDetail):
        return _bind_jsonb(common | {
            "event_kind": obj.event_kind,
            "starts_on": obj.starts_on,
            "ends_on": obj.ends_on,
            "timezone": obj.timezone,
            "opening_hours": as_json["opening_hours"],
            "venue_name": obj.venue_name,
            "tel": obj.tel,
            "content_id": obj.content_id,
            "content_type_id": obj.content_type_id,
            "area_code": obj.area_code,
            "sigungu_code": obj.sigungu_code,
            "payload": as_json["payload"],
        })
    if isinstance(obj, NoticeDetail):
        return _bind_jsonb(common | {
            "notice_type": obj.notice_type,
            "severity": obj.severity,
            "valid_start_time": obj.valid_start_time,
            "valid_end_time": obj.valid_end_time,
            "source_agency": obj.source_agency,
            "officer_name": obj.officer_name,
            "payload": as_json["payload"],
        })
    if isinstance(obj, RouteDetail):
        return _bind_jsonb(common | {
            "route_type": obj.route_type,
            "geometry_source": obj.geometry_source,
            "geometry_status": obj.geometry_status,
            "total_distance_meters": obj.total_distance_meters,
            "expected_duration_minutes": obj.expected_duration_minutes,
            "difficulty": obj.difficulty,
            "begin_name": obj.begin_name,
            "begin_address": obj.begin_address,
            "end_name": obj.end_name,
            "end_address": obj.end_address,
            "payload": as_json["payload"],
        })
    area = cast("AreaDetail", obj)
    return _bind_jsonb(common | {
        "area_kind": area.area_kind,
        "boundary_source": area.boundary_source,
        "area_square_meters": area.area_square_meters,
        "regulation_scope": area.regulation_scope,
        "administrative_office": area.administrative_office,
        "description": area.description,
        "payload": as_json["payload"],
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
        "sigungu_code",
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


_LOCK_NOTICE_VALID_START_SQL: Final[str] = """
SELECT valid_start_time
FROM feature.feature_notices
WHERE feature_id = :feature_id
FOR UPDATE
"""


def _is_first_probe_notice(detail: object) -> bool:
    """``detail.payload.valid_start_origin``이 ``'first_probe'``인가."""
    return (
        isinstance(detail, NoticeDetail)
        and detail.payload.get("valid_start_origin") == "first_probe"
    )


async def _preserved_notice_valid_start(
    session: AsyncSession, feature_id: str, incoming: Any
) -> Any:
    """``valid_start_origin='first_probe'`` 계보의 최초 관측 시각을 보존한다.

    provider가 "지금 처음 봤다"를 발효 시각으로 추정해 보내는 계보(KREX 돌발 등)는
    재적재마다 시작 시각이 흔들린다. 이미 저장된 값이 있으면 그것이 정본이고,
    없으면(신규) 들어온 값을 그대로 쓴다.
    """
    stored = (
        await session.execute(
            text(_LOCK_NOTICE_VALID_START_SQL), {"feature_id": feature_id}
        )
    ).scalar_one_or_none()
    return stored if stored is not None else incoming


async def write_subtype(
    session: AsyncSession,
    *,
    feature_id: str,
    feature_uuid: str,
    kind: str,
    detail: Any,
    geom_wkt: str | None = None,
) -> None:
    """kind별 subtype UPSERT — 호출자의 core 쓰기와 **같은 트랜잭션**.

    provider writer와 admin apply가 **이 함수 하나**를 쓴다. 종전에는 두 곳이
    각자 ``subtype_upsert_sql``/``subtype_params``를 조립했고, geometry
    바인딩과 first_probe 보존은 provider 쪽에만 있었다 — admin이 route/area로
    넓어지는 순간 ``bind parameter 'geom_wkt'`` 오류가 나는 구조였다.

    subtype이 없는 kind(price/weather)는 no-op다.
    """
    sql = subtype_upsert_sql(kind)
    if sql is None:
        return
    # 한 번만 검증하고 그 **객체**로 이후 판정을 한다 — raw dict(admin)와
    # DTO(provider)가 같은 경로를 지나게 하려면 판정 지점이 하나여야 한다.
    validated = _validated_detail(kind, feature_id, detail)
    params = subtype_params(
        feature_id=feature_id,
        feature_uuid=feature_uuid,
        kind=kind,
        detail=validated,
    )
    if params is None:  # pragma: no cover - SUBTYPE_TABLES와 동시에만 어긋난다
        return
    if kind in GEOMETRY_SUBTYPE_KINDS:
        params["geom_wkt"] = geom_wkt
    if _is_first_probe_notice(validated):
        params["valid_start_time"] = await _preserved_notice_valid_start(
            session, feature_id, params["valid_start_time"]
        )
    await session.execute(text(sql), params)
