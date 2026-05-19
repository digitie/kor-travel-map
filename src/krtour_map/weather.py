from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from decimal import Decimal
from typing import Any, Protocol, cast

from krtour_map.models import WeatherValue

KMA_PROVIDER = "python-kma-api"
KMA_NORMALIZATION_VERSION = "weather-feature-v1"


class KmaForecastService(Protocol):
    """Structural contract for `KmaClient.forecast` service facades."""

    def now(self, **kwargs: Any) -> Any: ...

    def short(self, **kwargs: Any) -> Sequence[Any]: ...

    def vilage(self, **kwargs: Any) -> Sequence[Any]: ...


class AsyncKmaForecastService(Protocol):
    """Structural contract for async `KmaClient.aio(...).forecast` facades."""

    async def now(self, **kwargs: Any) -> Any: ...

    async def short(self, **kwargs: Any) -> Sequence[Any]: ...

    async def vilage(self, **kwargs: Any) -> Sequence[Any]: ...


def require_kma_forecast_service(client_or_service: Any) -> KmaForecastService:
    """Return the new python-kma-api forecast facade or fail fast."""

    service = getattr(client_or_service, "forecast", client_or_service)
    for method_name in ("now", "short", "vilage"):
        if not callable(getattr(service, method_name, None)):
            raise TypeError(
                "python-krtour-map expects the python-kma-api service facade: "
                "client.forecast.now/short/vilage"
            )
    return cast(KmaForecastService, service)


def kma_forecast_item_to_weather_value(
    feature_id: str,
    item: Any,
    *,
    weather_domain: str,
    forecast_style: str,
    timeline_bucket: str,
    collected_at: datetime | None = None,
    source_record_key: str | None = None,
) -> WeatherValue:
    """Normalize a python-kma-api `ForecastItem` into a `WeatherValue`."""

    value = getattr(item, "value", None)
    value_number: Decimal | None = None
    value_text: str | None = None
    if isinstance(value, int | float | Decimal):
        value_number = Decimal(str(value))
    elif value is not None:
        value_text = str(value)

    category = getattr(item, "category", None)
    metric_key = str(category)
    payload: dict[str, Any] = {
        "raw": dict(getattr(item, "raw", {}) or {}),
        "nx": getattr(item, "nx", None),
        "ny": getattr(item, "ny", None),
    }
    metadata = getattr(item, "metadata", None)
    if metadata is not None:
        if hasattr(metadata, "model_dump"):
            payload["metadata"] = metadata.model_dump(mode="json")
        else:
            payload["metadata"] = metadata

    kwargs: dict[str, Any] = {}
    if collected_at is not None:
        kwargs["collected_at"] = collected_at

    return WeatherValue(
        feature_id=feature_id,
        provider=KMA_PROVIDER,
        weather_domain=weather_domain,
        forecast_style=forecast_style,
        timeline_bucket=timeline_bucket,
        metric_key=metric_key,
        issued_at=getattr(item, "base_at", None),
        valid_at=getattr(item, "forecast_at", None),
        source_metric_key=metric_key,
        source_metric_name=getattr(item, "label", None),
        metric_name=getattr(item, "label", None),
        value_number=value_number,
        value_text=value_text,
        unit=getattr(item, "unit", None),
        normalization_version=KMA_NORMALIZATION_VERSION,
        payload=payload,
        source_record_key=source_record_key,
        **kwargs,
    )


def _sort_time(value: WeatherValue) -> datetime:
    return value.valid_at or value.observed_at or value.issued_at or value.collected_at


def latest_weather_values(values: list[WeatherValue]) -> list[WeatherValue]:
    latest: dict[tuple[str, str, str], WeatherValue] = {}
    for value in values:
        key = (str(value.weather_domain), str(value.forecast_style), value.metric_key)
        previous = latest.get(key)
        if previous is None or _sort_time(value) >= _sort_time(previous):
            latest[key] = value
    return sorted(
        latest.values(),
        key=lambda value: (str(value.weather_domain), str(value.forecast_style), value.metric_key),
    )
