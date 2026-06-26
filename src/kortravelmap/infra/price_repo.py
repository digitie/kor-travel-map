"""``kortravelmap.infra.price_repo`` -- price value 적재.

``PriceValue`` DTO를 ``feature.feature_price_values``에 멱등 upsert한다. PK는
결정적 ``price_value_key``(`make_price_value_key`)이며, commit은 호출자가 소유한다.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Final

from sqlalchemy import text

from kortravelmap.core.ids import make_price_value_key
from kortravelmap.dto._time import kst_now
from kortravelmap.infra.feature_repo import FeatureLoadResult

if TYPE_CHECKING:
    from sqlalchemy import RowMapping
    from sqlalchemy.ext.asyncio import AsyncSession

    from kortravelmap.dto.price import PriceValue

__all__ = [
    "DEFAULT_PRICE_FRESHNESS_SECONDS",
    "PriceCard",
    "PriceFeatureLoadResult",
    "PricePoint",
    "build_price_card",
    "load_price_values",
]

DEFAULT_PRICE_FRESHNESS_SECONDS: Final[int] = 18 * 60 * 60
"""하루 2회 price ETL 기준 freshness 여유값(12h 주기 + 지연)."""


@dataclass(frozen=True)
class PricePoint:
    """feature price card의 제품별 가격 1건."""

    provider: str
    price_domain: str
    product_key: str
    product_name: str | None
    source_product_key: str | None
    source_product_name: str | None
    value_number: Decimal
    unit: str
    observed_at: datetime


@dataclass(frozen=True)
class PriceCard:
    """feature 1건의 price card — 최신 제품 가격 + 최근 이력."""

    feature_id: str
    asof: datetime | None
    current: list[PricePoint]
    history: list[PricePoint]
    latest_at: datetime | None
    is_stale: bool


@dataclass(frozen=True)
class PriceFeatureLoadResult:
    """price anchor feature + ``PriceValue`` 적재 결과."""

    features: FeatureLoadResult
    price_values: int

    def as_metadata(self) -> dict[str, object]:
        return {
            "price_features_total": self.features.bundles_total,
            "price_features_inserted": self.features.features_inserted,
            "price_features_updated": self.features.features_updated,
            "price_source_records_inserted": self.features.source_records_inserted,
            "price_source_links_inserted": self.features.source_links_inserted,
            "price_source_links_updated": self.features.source_links_updated,
            "price_values_upserted": self.price_values,
        }


_INSERT_SQL: Final[str] = """
INSERT INTO feature.feature_price_values (
    price_value_key, feature_id, provider, price_domain, product_key,
    product_name, source_product_key, source_product_name, observed_at,
    value_number, unit, normalization_version, payload, source_record_key,
    collected_at, updated_at
) VALUES (
    :price_value_key, :feature_id, :provider, :price_domain, :product_key,
    :product_name, :source_product_key, :source_product_name, :observed_at,
    :value_number, :unit, :normalization_version, CAST(:payload AS jsonb),
    :source_record_key, :collected_at, now()
)
ON CONFLICT (price_value_key) DO UPDATE SET
    product_name = EXCLUDED.product_name,
    source_product_key = EXCLUDED.source_product_key,
    source_product_name = EXCLUDED.source_product_name,
    value_number = EXCLUDED.value_number,
    unit = EXCLUDED.unit,
    normalization_version = EXCLUDED.normalization_version,
    payload = EXCLUDED.payload,
    source_record_key = EXCLUDED.source_record_key,
    collected_at = EXCLUDED.collected_at,
    updated_at = now()
"""

_PRODUCT_ORDER: Final[dict[str, int]] = {
    "gasoline": 10,
    "diesel": 20,
    "premium_gasoline": 30,
    "lpg": 40,
}

_CURRENT_SQL: Final[str] = """
WITH latest AS (
    SELECT DISTINCT ON (product_key)
        provider, price_domain, product_key, product_name,
        source_product_key, source_product_name,
        value_number, unit, observed_at
    FROM feature.feature_price_values
    WHERE feature_id = :feature_id
      AND (
        CAST(:asof AS timestamptz) IS NULL
        OR observed_at <= CAST(:asof AS timestamptz)
      )
    ORDER BY product_key, observed_at DESC
)
SELECT *
FROM latest
ORDER BY
    CASE product_key
      WHEN 'gasoline' THEN 10
      WHEN 'diesel' THEN 20
      WHEN 'premium_gasoline' THEN 30
      WHEN 'lpg' THEN 40
      ELSE 100
    END,
    product_name NULLS LAST,
    product_key
"""

_HISTORY_SQL: Final[str] = """
SELECT
    provider, price_domain, product_key, product_name,
    source_product_key, source_product_name,
    value_number, unit, observed_at
FROM feature.feature_price_values
WHERE feature_id = :feature_id
  AND (
    CAST(:asof AS timestamptz) IS NULL
    OR observed_at <= CAST(:asof AS timestamptz)
  )
ORDER BY observed_at DESC, product_key
LIMIT :limit
"""


def _enum_value(value: Any) -> str:
    return str(getattr(value, "value", value))


def _price_value_params(value: PriceValue) -> dict[str, Any]:
    price_domain = _enum_value(value.price_domain)
    key = make_price_value_key(
        feature_id=value.feature_id,
        provider=value.provider,
        price_domain=price_domain,
        product_key=value.product_key,
        observed_at=value.observed_at,
    )
    return {
        "price_value_key": key,
        "feature_id": value.feature_id,
        "provider": value.provider,
        "price_domain": price_domain,
        "product_key": value.product_key,
        "product_name": value.product_name,
        "source_product_key": value.source_product_key,
        "source_product_name": value.source_product_name,
        "observed_at": value.observed_at,
        "value_number": value.value_number,
        "unit": value.unit,
        "normalization_version": value.normalization_version,
        "payload": json.dumps(value.payload, ensure_ascii=False, default=str),
        "source_record_key": value.source_record_key,
        "collected_at": value.collected_at,
    }


async def load_price_values(
    session: AsyncSession, values: Iterable[PriceValue]
) -> int:
    """``PriceValue`` 들을 멱등 upsert 적재한다. 적재 건수 반환."""

    params = [_price_value_params(v) for v in values]
    if not params:
        return 0
    await session.execute(text(_INSERT_SQL), params)
    return len(params)


def _price_point(row: RowMapping) -> PricePoint:
    return PricePoint(
        provider=str(row["provider"]),
        price_domain=str(row["price_domain"]),
        product_key=str(row["product_key"]),
        product_name=row["product_name"],
        source_product_key=row["source_product_key"],
        source_product_name=row["source_product_name"],
        value_number=row["value_number"],
        unit=str(row["unit"]),
        observed_at=row["observed_at"],
    )


def _sort_current(points: list[PricePoint]) -> list[PricePoint]:
    return sorted(
        points,
        key=lambda point: (
            _PRODUCT_ORDER.get(point.product_key, 100),
            point.product_name or "",
            point.product_key,
        ),
    )


async def build_price_card(
    session: AsyncSession,
    *,
    feature_id: str,
    asof: datetime | None = None,
    history_limit: int = 100,
    freshness_seconds: int = DEFAULT_PRICE_FRESHNESS_SECONDS,
) -> PriceCard:
    """feature의 price card — 제품별 최신값과 최근 이력.

    각 ``product_key``에서 ``observed_at`` 최신 1건을 현재 가격으로 고르고,
    history는 최신 관측순으로 제한한다. card 자체는 feature 존재 여부를 판정하지
    않는다. 호출 라우터가 필요하면 feature 상세 조회와 조합한다.
    """

    limit = min(max(history_limit, 1), 500)
    params = {"feature_id": feature_id, "asof": asof}
    current_rows = (
        await session.execute(text(_CURRENT_SQL), params)
    ).mappings().all()
    history_rows = (
        await session.execute(text(_HISTORY_SQL), {**params, "limit": limit})
    ).mappings().all()

    current = _sort_current([_price_point(row) for row in current_rows])
    history = [_price_point(row) for row in history_rows]
    latest_at = max((point.observed_at for point in current), default=None)
    reference = asof if asof is not None else kst_now()
    is_stale = (
        latest_at is None
        or (reference - latest_at).total_seconds() > freshness_seconds
    )
    return PriceCard(
        feature_id=feature_id,
        asof=asof,
        current=current,
        history=history,
        latest_at=latest_at,
        is_stale=is_stale,
    )
