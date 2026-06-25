"""``kortravelmap.infra.price_repo`` -- price value 적재.

``PriceValue`` DTO를 ``feature.feature_price_values``에 멱등 upsert한다. PK는
결정적 ``price_value_key``(`make_price_value_key`)이며, commit은 호출자가 소유한다.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final

from sqlalchemy import text

from kortravelmap.core.ids import make_price_value_key
from kortravelmap.infra.feature_repo import FeatureLoadResult

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from kortravelmap.dto.price import PriceValue

__all__ = [
    "PriceFeatureLoadResult",
    "load_price_values",
]


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
