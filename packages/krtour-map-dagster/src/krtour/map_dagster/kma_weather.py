"""KMA weather Dagster asset 3종 (T-219b) — 옵션 B 대상 한정 적재.

초단기실황/초단기예보/단기예보는 대상 좌표가 DB(``ops.poi_cache_targets`` +
설정 추가 좌표)에서 나오므로 표준 record-resource(좌표 무관 스트림) 패턴이
맞지 않는다 — asset이 직접 ① ``krtour_map_client``로 대상 좌표/active place
좌표를 조회하고 ② ``python-kma-api``의 ``kma.grid.to_grid``로 격자를 dedupe
(run당 상한 적용) ③ 격자별로 ``KmaClient``를 호출해 ④ krtour 변환 함수로
``WeatherValue``를 만들어 적재한다(계획 정본
`docs/reports/kma-mcst-provider-plan-2026-06-11.md` §2.3).

같은 base 중복 호출 회피는 ``provider_sync_state`` cursor(``base_datetime``)로
한다(`docs/kma-weather-etl.md` §6). KMA 호출 실패 시 cursor를 전진시키지 않고
``record_sync_failure``만 남긴다(신선도 대시보드 T-217g 신호).

provider client는 ADR-006대로 wrapper 없이 직접 사용한다. ``KmaClient``의
``ForecastItem``/``WeatherSnapshot``은 base/forecast를 ``datetime``으로 정규화한
모델이라 krtour 변환 Protocol(`KmaShortForecastItem` 등 — KMA 공식 필드명
snake_case row)과 shape이 다르다 — client가 보존한 ``raw`` payload(KMA 공식
필드명, ADR-044 신뢰·미러)에서 Protocol-만족 row를 만들어 변환에 넘긴다.
"""

# NOTE: `from __future__ import annotations` 금지 — dagster가 asset 함수의
# ``context`` 어노테이션을 런타임 타입으로 검증한다(assets.py와 동일).
import importlib
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final, cast

from dagster import AssetExecutionContext, asset
from krtour.map.dto.weather import WeatherValue
from krtour.map.providers.kma import (
    KMA_PROVIDER_NAME,
    KMA_SHORT_FORECAST_DATASET_KEY,
    KMA_ULTRA_SHORT_FORECAST_DATASET_KEY,
    KMA_ULTRA_SHORT_NOWCAST_DATASET_KEY,
    parse_weather_extra_points,
    short_forecast_to_weather_values,
    ultra_short_forecast_to_weather_values,
    ultra_short_nowcast_to_weather_values,
)

from .assets import FEATURE_LOAD_RETRY_POLICY, _resource_object, _resource_value
from .etl import _add_output_metadata

if TYPE_CHECKING:
    from krtour.map.client import AsyncKrtourMapClient

__all__ = [
    "KMA_WEATHER_ASSETS",
    "KmaForecastRow",
    "KmaGridTargets",
    "KmaNowcastRow",
    "KmaWeatherLoadResult",
    "feature_weather_kma_short_forecast",
    "feature_weather_kma_ultra_short_forecast",
    "feature_weather_kma_ultra_short_nowcast",
    "forecast_rows_from_items",
    "map_grid_targets",
    "nowcast_rows_from_snapshot",
    "run_feature_weather_kma_short_forecast",
    "run_feature_weather_kma_ultra_short_forecast",
    "run_feature_weather_kma_ultra_short_nowcast",
]

_KMA_WEATHER_RESOURCE_KEYS: Final[set[str]] = {
    "krtour_map_client",
    "kma_weather_client",
    "kma_weather_extra_points",
    "kma_weather_max_grids_per_run",
}
"""KMA weather asset 공통 resource key."""


# -- Protocol-만족 row (raw payload → krtour 변환 입력) -------------------


@dataclass(frozen=True, slots=True)
class KmaNowcastRow:
    """``KmaUltraShortNowcastItem`` Protocol을 만족하는 초단기실황 row.

    ``WeatherSnapshot``은 카테고리를 피벗한 모델이라 row 단위 Protocol과 shape이
    다르다 — ``snapshot.raw["items"]``(KMA 공식 필드명 보존)에서 만든다.
    """

    base_date: str
    base_time: str
    nx: int
    ny: int
    category: str
    obsr_value: str


@dataclass(frozen=True, slots=True)
class KmaForecastRow:
    """``Kma{UltraShort,Short}ForecastItem`` Protocol을 만족하는 예보 row.

    ``ForecastItem.raw``(KMA 공식 필드명 보존)에서 만든다.
    """

    base_date: str
    base_time: str
    fcst_date: str
    fcst_time: str
    nx: int
    ny: int
    category: str
    fcst_value: str


def nowcast_rows_from_snapshot(snapshot: Any) -> list[KmaNowcastRow]:
    """``KmaClient.forecast.now()`` ``WeatherSnapshot`` → 초단기실황 row 목록."""
    raw = getattr(snapshot, "raw", None)
    items = raw.get("items", []) if isinstance(raw, dict) else []
    return [
        KmaNowcastRow(
            base_date=str(item["baseDate"]),
            base_time=str(item["baseTime"]),
            nx=int(item["nx"]),
            ny=int(item["ny"]),
            category=str(item["category"]),
            obsr_value=str(item["obsrValue"]),
        )
        for item in items
    ]


def forecast_rows_from_items(items: Sequence[Any]) -> list[KmaForecastRow]:
    """``KmaClient.forecast.{short,vilage}()`` ``ForecastItem`` 목록 → 예보 row 목록."""
    rows: list[KmaForecastRow] = []
    for item in items:
        raw = item.raw
        rows.append(
            KmaForecastRow(
                base_date=str(raw["baseDate"]),
                base_time=str(raw["baseTime"]),
                fcst_date=str(raw["fcstDate"]),
                fcst_time=str(raw["fcstTime"]),
                nx=int(raw["nx"]),
                ny=int(raw["ny"]),
                category=str(raw["category"]),
                fcst_value=str(raw["fcstValue"]),
            )
        )
    return rows


# -- python-kma-api lazy helper (격자 변환 / 최신 base) -------------------
# provider 라이브러리는 ADR-044 로컬 체크아웃이며 hard dependency가 아니므로
# (부재 가능) 호출 시점에 lazy import한다. 격자 변환(LCC DFS)·발표 스케줄
# 계산은 python-kma-api 책임 — krtour에 재구현하지 않는다(계획 정본 §2.1).


def _kma_grid(lat: float, lon: float) -> tuple[int, int]:
    """WGS84 (lat, lon) → KMA DFS 격자 ``(nx, ny)`` (``kma.grid.to_grid``)."""
    grid = cast(Any, importlib.import_module("kma.grid"))
    nx, ny = grid.to_grid(lat, lon)
    return (int(nx), int(ny))


def _latest_nowcast_base() -> tuple[str, str]:
    """``getUltraSrtNcst`` 최신 조회 가능 ``(base_date, base_time)``."""
    time_utils = cast(Any, importlib.import_module("kma.time_utils"))
    base_date, base_time = time_utils.latest_ultra_srt_ncst_base()
    return (str(base_date), str(base_time))


def _latest_ultra_short_forecast_base() -> tuple[str, str]:
    """``getUltraSrtFcst`` 최신 조회 가능 ``(base_date, base_time)``."""
    time_utils = cast(Any, importlib.import_module("kma.time_utils"))
    base_date, base_time = time_utils.latest_ultra_srt_fcst_base()
    return (str(base_date), str(base_time))


def _latest_short_forecast_base() -> tuple[str, str]:
    """``getVilageFcst`` 최신 조회 가능 ``(base_date, base_time)``."""
    time_utils = cast(Any, importlib.import_module("kma.time_utils"))
    base_date, base_time = time_utils.latest_vilage_base()
    return (str(base_date), str(base_time))


def _fetch_nowcast_rows(kma_client: Any, nx: int, ny: int) -> list[KmaNowcastRow]:
    return nowcast_rows_from_snapshot(kma_client.forecast.now(nx=nx, ny=ny))


def _fetch_ultra_short_forecast_rows(
    kma_client: Any, nx: int, ny: int
) -> list[KmaForecastRow]:
    return forecast_rows_from_items(kma_client.forecast.short(nx=nx, ny=ny))


def _fetch_short_forecast_rows(
    kma_client: Any, nx: int, ny: int
) -> list[KmaForecastRow]:
    return forecast_rows_from_items(kma_client.forecast.vilage(nx=nx, ny=ny))


# -- 대상 격자/feature 매핑 (옵션 B) --------------------------------------


@dataclass(frozen=True)
class KmaGridTargets:
    """대상 격자 + 격자별 place feature 매핑 (``map_grid_targets`` 결과)."""

    grids: tuple[tuple[int, int], ...]
    """run 상한 적용 후 대상 격자 — 입력 순서(poi target → extra point) 유지."""

    feature_ids_by_grid: Mapping[tuple[int, int], tuple[str, ...]]
    """격자 → 그 격자에 속하는 active place ``feature_id`` 목록."""

    grids_dropped: int
    """run 상한 초과로 제외된 격자 수 (운영 로그용 — silent cap 금지)."""


def map_grid_targets(
    *,
    target_coords: Sequence[tuple[float, float]],
    extra_points: Sequence[tuple[float, float]],
    place_coords: Sequence[tuple[str, float, float]],
    to_grid: Callable[[float, float], tuple[int, int]],
    max_grids: int,
) -> KmaGridTargets:
    """(lon, lat) 대상 좌표 → 격자 dedupe + 상한 + place feature 매핑.

    ``target_coords``(poi_cache_targets)가 ``extra_points``(설정 명시 좌표)보다
    먼저다 — 상한 절단 시 수요가 증명된 지점이 우선 생존한다. ``place_coords``는
    ``(feature_id, lon, lat)``이며 상한 적용 후 격자에만 매핑한다.
    """
    if max_grids <= 0:
        raise ValueError("max_grids must be positive")
    ordered: list[tuple[int, int]] = []
    seen: set[tuple[int, int]] = set()
    for lon, lat in [*target_coords, *extra_points]:
        cell = to_grid(lat, lon)
        if cell not in seen:
            seen.add(cell)
            ordered.append(cell)
    dropped = max(0, len(ordered) - max_grids)
    capped = ordered[:max_grids]
    mapping: dict[tuple[int, int], list[str]] = {cell: [] for cell in capped}
    for feature_id, lon, lat in place_coords:
        bucket = mapping.get(to_grid(lat, lon))
        if bucket is not None:
            bucket.append(feature_id)
    return KmaGridTargets(
        grids=tuple(capped),
        feature_ids_by_grid={cell: tuple(ids) for cell, ids in mapping.items()},
        grids_dropped=dropped,
    )


# -- asset 결과 -----------------------------------------------------------


@dataclass(frozen=True)
class KmaWeatherLoadResult:
    """KMA weather 적재 asset 결과."""

    provider: str
    dataset_key: str
    base_datetime: str
    """이번 run의 최신 발표 base (``YYYYMMDDHHMM``)."""

    skipped: bool
    """``provider_sync_state`` cursor와 base가 같아 호출 없이 끝났으면 True."""

    grids_total: int
    grids_fetched: int
    grids_dropped: int
    features_total: int
    values_loaded: int

    def as_metadata(self) -> dict[str, object]:
        return {
            "provider": self.provider,
            "dataset_key": self.dataset_key,
            "base_datetime": self.base_datetime,
            "skipped": self.skipped,
            "grids_total": self.grids_total,
            "grids_fetched": self.grids_fetched,
            "grids_dropped": self.grids_dropped,
            "features_total": self.features_total,
            "values_loaded": self.values_loaded,
        }


# -- 공통 runner ----------------------------------------------------------


async def _run_kma_weather_asset(
    context: AssetExecutionContext,
    *,
    dataset_key: str,
    latest_base: Callable[[], tuple[str, str]],
    fetch_rows: Callable[[Any, int, int], Sequence[Any]],
    to_values: Callable[[Sequence[Any], str], list[WeatherValue]],
) -> KmaWeatherLoadResult:
    """대상 격자 산출 → 격자별 KMA 호출 → ``WeatherValue`` 적재 공통 흐름.

    cursor 의미: skip 판정과 성공 기록 모두 run 시작 시점의 최신 발표
    base(``latest_base()``)를 쓴다 — 발표 경계 race로 실제 응답 base가 더
    새것이어도 다음 run이 새 base를 다시 계산하므로 보수적으로 안전하다.
    """
    krtour_client = cast(
        "AsyncKrtourMapClient", _resource_object(context, "krtour_map_client")
    )
    base_date, base_time = latest_base()
    base_key = f"{base_date}{base_time}"

    state = await krtour_client.get_sync_state(
        provider=KMA_PROVIDER_NAME, dataset_key=dataset_key
    )
    if state is not None and state.cursor.get("base_datetime") == base_key:
        context.log.info(
            "KMA %s base %s 이미 적재됨 — skip (provider_sync_state cursor).",
            dataset_key,
            base_key,
        )
        result = KmaWeatherLoadResult(
            provider=KMA_PROVIDER_NAME,
            dataset_key=dataset_key,
            base_datetime=base_key,
            skipped=True,
            grids_total=0,
            grids_fetched=0,
            grids_dropped=0,
            features_total=0,
            values_loaded=0,
        )
        _add_output_metadata(context, result.as_metadata())
        return result

    extra_raw = await _resource_value(context, "kma_weather_extra_points", default=None)
    extra_points = parse_weather_extra_points(cast("str | None", extra_raw))
    max_grids = int(
        cast(
            "int",
            await _resource_value(
                context, "kma_weather_max_grids_per_run", default=50
            ),
        )
    )

    target_coords = await krtour_client.list_poi_cache_target_coords()
    place_coords = await krtour_client.list_active_place_coords()
    targets = map_grid_targets(
        target_coords=target_coords,
        extra_points=extra_points,
        place_coords=place_coords,
        to_grid=_kma_grid,
        max_grids=max_grids,
    )
    if targets.grids_dropped:
        context.log.warning(
            "KMA %s 대상 격자 %d개가 run 상한(%d) 초과로 제외됨 — "
            "KMA_WEATHER_MAX_GRIDS_PER_RUN 조정 또는 대상 분할 필요.",
            dataset_key,
            targets.grids_dropped,
            max_grids,
        )
    if not targets.grids:
        context.log.warning(
            "KMA %s 대상 격자 없음 — poi_cache_targets/KMA_WEATHER_EXTRA_POINTS가 "
            "비어 있다. cursor는 전진하지 않는다.",
            dataset_key,
        )

    kma_client = _resource_object(context, "kma_weather_client")
    grids_fetched = 0
    values_loaded = 0
    matched_features: set[str] = set()
    try:
        for nx, ny in targets.grids:
            feature_ids = targets.feature_ids_by_grid[(nx, ny)]
            if not feature_ids:
                # 격자에 매핑된 place feature가 없으면 적재할 곳이 없다 —
                # KMA 호출 자체를 생략(일일 호출 한도 보호).
                continue
            rows = fetch_rows(kma_client, nx, ny)
            grids_fetched += 1
            if not rows:
                continue
            grid_values: list[WeatherValue] = []
            for feature_id in feature_ids:
                grid_values.extend(to_values(rows, feature_id))
            values_loaded += await krtour_client.load_weather_values(grid_values)
            matched_features.update(feature_ids)
    except Exception:
        await krtour_client.record_sync_failure(
            provider=KMA_PROVIDER_NAME, dataset_key=dataset_key
        )
        raise

    if grids_fetched:
        await krtour_client.record_sync_success(
            provider=KMA_PROVIDER_NAME,
            dataset_key=dataset_key,
            cursor={"base_datetime": base_key},
        )

    result = KmaWeatherLoadResult(
        provider=KMA_PROVIDER_NAME,
        dataset_key=dataset_key,
        base_datetime=base_key,
        skipped=False,
        grids_total=len(targets.grids),
        grids_fetched=grids_fetched,
        grids_dropped=targets.grids_dropped,
        features_total=len(matched_features),
        values_loaded=values_loaded,
    )
    _add_output_metadata(context, result.as_metadata())
    return result


# -- asset 3종 -------------------------------------------------------------


async def run_feature_weather_kma_ultra_short_nowcast(
    context: AssetExecutionContext,
) -> KmaWeatherLoadResult:
    """KMA 초단기실황(``getUltraSrtNcst``)을 대상 격자 place feature에 적재한다."""
    return await _run_kma_weather_asset(
        context,
        dataset_key=KMA_ULTRA_SHORT_NOWCAST_DATASET_KEY,
        latest_base=_latest_nowcast_base,
        fetch_rows=_fetch_nowcast_rows,
        to_values=lambda rows, feature_id: ultra_short_nowcast_to_weather_values(
            rows, feature_id=feature_id
        ),
    )


@asset(
    group_name="features_weather",
    required_resource_keys=_KMA_WEATHER_RESOURCE_KEYS,
    retry_policy=FEATURE_LOAD_RETRY_POLICY,
)
async def feature_weather_kma_ultra_short_nowcast(
    context: AssetExecutionContext,
) -> KmaWeatherLoadResult:
    return await run_feature_weather_kma_ultra_short_nowcast(context)


async def run_feature_weather_kma_ultra_short_forecast(
    context: AssetExecutionContext,
) -> KmaWeatherLoadResult:
    """KMA 초단기예보(``getUltraSrtFcst``)를 대상 격자 place feature에 적재한다."""
    return await _run_kma_weather_asset(
        context,
        dataset_key=KMA_ULTRA_SHORT_FORECAST_DATASET_KEY,
        latest_base=_latest_ultra_short_forecast_base,
        fetch_rows=_fetch_ultra_short_forecast_rows,
        to_values=lambda rows, feature_id: ultra_short_forecast_to_weather_values(
            rows, feature_id=feature_id
        ),
    )


@asset(
    group_name="features_weather",
    required_resource_keys=_KMA_WEATHER_RESOURCE_KEYS,
    retry_policy=FEATURE_LOAD_RETRY_POLICY,
)
async def feature_weather_kma_ultra_short_forecast(
    context: AssetExecutionContext,
) -> KmaWeatherLoadResult:
    return await run_feature_weather_kma_ultra_short_forecast(context)


async def run_feature_weather_kma_short_forecast(
    context: AssetExecutionContext,
) -> KmaWeatherLoadResult:
    """KMA 단기예보(``getVilageFcst``)를 대상 격자 place feature에 적재한다."""
    return await _run_kma_weather_asset(
        context,
        dataset_key=KMA_SHORT_FORECAST_DATASET_KEY,
        latest_base=_latest_short_forecast_base,
        fetch_rows=_fetch_short_forecast_rows,
        to_values=lambda rows, feature_id: short_forecast_to_weather_values(
            rows, feature_id=feature_id
        ),
    )


@asset(
    group_name="features_weather",
    required_resource_keys=_KMA_WEATHER_RESOURCE_KEYS,
    retry_policy=FEATURE_LOAD_RETRY_POLICY,
)
async def feature_weather_kma_short_forecast(
    context: AssetExecutionContext,
) -> KmaWeatherLoadResult:
    return await run_feature_weather_kma_short_forecast(context)


KMA_WEATHER_ASSETS: Final = [
    feature_weather_kma_ultra_short_nowcast,
    feature_weather_kma_ultra_short_forecast,
    feature_weather_kma_short_forecast,
]
"""KMA weather 적재 asset 목록 (T-219b)."""
