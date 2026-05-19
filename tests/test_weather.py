from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from krtour_map.weather import (
    KMA_PROVIDER,
    kma_forecast_item_to_weather_value,
    require_kma_forecast_service,
)


@dataclass(frozen=True)
class FakeForecastItem:
    base_at: datetime
    forecast_at: datetime
    category: str
    value: object
    label: str | None
    unit: str | None
    nx: int
    ny: int
    raw: dict[str, object]


class FakeForecastService:
    def now(self, **_kwargs: object) -> object:
        return object()

    def short(self, **_kwargs: object) -> list[object]:
        return []

    def vilage(self, **_kwargs: object) -> list[object]:
        return []


class FakeKmaClient:
    forecast = FakeForecastService()


def test_require_kma_forecast_service_accepts_new_facade_shape() -> None:
    service = require_kma_forecast_service(FakeKmaClient())

    assert service is FakeKmaClient.forecast


def test_kma_forecast_item_normalizes_to_weather_value() -> None:
    kst = ZoneInfo("Asia/Seoul")
    item = FakeForecastItem(
        base_at=datetime(2026, 5, 19, 14, 0, tzinfo=kst),
        forecast_at=datetime(2026, 5, 19, 15, 0, tzinfo=kst),
        category="TMP",
        value=18.4,
        label="기온",
        unit="C",
        nx=60,
        ny=127,
        raw={"category": "TMP", "fcstValue": "18.4"},
    )

    value = kma_forecast_item_to_weather_value(
        "feature_1",
        item,
        weather_domain="kma_short_forecast",
        forecast_style="short",
        timeline_bucket="short",
    )

    assert value.provider == KMA_PROVIDER
    assert value.metric_key == "TMP"
    assert value.value_number == Decimal("18.4")
    assert value.value_text is None
    assert value.issued_at == item.base_at
    assert value.valid_at == item.forecast_at
    assert value.payload["nx"] == 60
