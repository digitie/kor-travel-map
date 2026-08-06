"""통합 테스트용 kind별 subtype seed 헬퍼 (T-VN-35, ADR-086).

alembic 0086 이후 core ``feature.features``에는 ``detail`` JSONB도 ``geom``도
없다. kind별 값의 정본은 subtype 5종(``feature_places``/``feature_events``/
``feature_notices``/``feature_routes``/``feature_areas``)이고, 응답이 요구하는
``detail``/``geom``은 ``feature.features_detailed`` 뷰가 조립한다.

따라서 raw SQL로 feature를 심는 테스트는 **core INSERT 다음에 subtype 행도**
만들어야 종전과 같은 read 결과를 얻는다. 이 모듈은 그 한 줄을 제공하되
매핑 규칙은 프로덕션 정본(``kortravelmap.infra.feature_subtype``)을 그대로
호출한다 — 테스트가 규칙을 복제하면 계약이 두 벌이 되고, 그게 정확히 이
재설계가 없앤 문제다.

필수 필드 기본값
----------------

``place_kind``/``event_kind``/``notice_type``은 subtype에서 NOT NULL이고 writer도
결측을 ``ValueError``로 거부한다(sentinel 폐기). 종전 테스트 seed는 detail을
``'{}'``로 두는 경우가 많았으므로, 여기서 kind별 최소 기본값을 채워 준다 —
"place면 place_kind가 있다"는 새 계약을 seed가 어기지 않게 하는 것이지,
프로덕션 fail-close를 우회하는 것이 아니다(호출자가 값을 주면 그 값이 이긴다).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy import text

from kortravelmap.infra.feature_subtype import subtype_params, subtype_upsert_sql

if TYPE_CHECKING:
    from collections.abc import Mapping

    from sqlalchemy.ext.asyncio import AsyncSession

__all__ = ["seed_feature_subtype", "seed_feature_subtypes_for_prefix"]

#: kind별 필수 필드 최소 기본값 — 호출자가 준 detail이 우선한다.
_REQUIRED_DEFAULTS: dict[str, dict[str, Any]] = {
    "place": {"place_kind": "attraction"},
    "event": {"event_kind": "festival"},
    "notice": {"notice_type": "safety"},
}

_STORED_UUID_SQL = """
SELECT CAST(feature_uuid AS text)
FROM feature.features
WHERE feature_id = :feature_id
"""


async def seed_feature_subtype(
    session: AsyncSession,
    *,
    feature_id: str,
    kind: str,
    detail: Mapping[str, Any] | None = None,
    geom_wkt: str | None = None,
) -> None:
    """core 행이 이미 있는 feature에 kind별 subtype 행을 만든다(있으면 갱신).

    ``feature_uuid``는 **core에 저장된 값을 읽어** 쓴다 — 파생 계산하면 identity
    사본 FK(``fk_*_identity_pair``)가 깨진다. subtype이 없는 kind(price/weather)는
    no-op이다.
    """
    sql = subtype_upsert_sql(kind)
    if sql is None:
        return
    payload: dict[str, Any] = dict(_REQUIRED_DEFAULTS.get(kind, {}))
    payload.update(dict(detail or {}))
    params = subtype_params(
        feature_id=feature_id,
        feature_uuid=str(
            (
                await session.execute(text(_STORED_UUID_SQL), {"feature_id": feature_id})
            ).scalar_one()
        ),
        kind=kind,
        detail=payload,
    )
    if params is None:  # pragma: no cover — subtype_upsert_sql과 동시에만 어긋난다
        return
    if geom_wkt is not None:
        params["geom_wkt"] = geom_wkt
    await session.execute(text(sql), params)


_PREFIX_SUBTYPE_SQL = """
INSERT INTO feature.{table} (feature_id, feature_uuid, kind, {required_column})
SELECT f.feature_id, f.feature_uuid, f.kind, :required_value
FROM feature.features AS f
WHERE f.feature_id LIKE :prefix || '%' AND f.kind = '{kind}'
ON CONFLICT (feature_id) DO NOTHING
"""


async def seed_feature_subtypes_for_prefix(
    session: AsyncSession,
    prefix: str,
    *,
    place_kind: str = "attraction",
    event_kind: str = "festival",
    notice_type: str = "safety",
) -> None:
    """``feature_id`` prefix로 심은 대량 seed에 place/event/notice subtype을 채운다.

    generate_series 기반 벌크 seed용 — 행당 왕복을 만들지 않는다. geometry가
    필수인 route/area는 값이 kind별로 달라 여기서 다루지 않는다(호출자가
    ``seed_feature_subtype``으로 명시 seed).
    """
    for kind, table, column, value in (
        ("place", "feature_places", "place_kind", place_kind),
        ("event", "feature_events", "event_kind", event_kind),
        ("notice", "feature_notices", "notice_type", notice_type),
    ):
        await session.execute(
            text(
                _PREFIX_SUBTYPE_SQL.format(
                    table=table, required_column=column, kind=kind
                )
            ),
            {"prefix": prefix, "required_value": value},
        )
