"""KMA weather Dagster asset 3종 (T-219b) — 옵션 B 대상 한정 적재.

초단기실황/초단기예보/단기예보는 대상 좌표가 DB(``ops.poi_cache_targets`` +
설정 추가 좌표)에서 나오므로 표준 record-resource(좌표 무관 스트림) 패턴이
맞지 않는다 — asset이 직접 ① ``kor_travel_map_client``로 대상 좌표/active place
좌표를 조회하고 ② ``python-kma-api``의 ``kma.grid.to_grid``로 격자를 dedupe
(run당 상한 적용) ③ 격자별로 ``KmaClient``를 호출해 ④ krtour 변환 함수로
``WeatherValue``를 만들어 적재한다(계획 정본
`docs/reports/kma-mcst-provider-plan-2026-06-11.md` §2.3).

같은 base 중복 호출 회피는 ``provider_sync_state`` cursor(``base_datetime``)로
한다(`docs/etl/kma-weather-etl.md` §6). KMA 호출 실패 시 cursor를 전진시키지 않고
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
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any, Final, cast

from kortravelmap.dto.weather import WeatherValue
from kortravelmap.providers.kma import (
    KMA_MID_FORECAST_DATASET_KEY,
    KMA_PROVIDER_NAME,
    KMA_SHORT_FORECAST_DATASET_KEY,
    KMA_ULTRA_SHORT_FORECAST_DATASET_KEY,
    KMA_ULTRA_SHORT_NOWCAST_DATASET_KEY,
    KMA_WEATHER_ALERT_DATASET_KEY,
    mid_land_forecast_to_weather_values,
    mid_temperature_to_weather_values,
    parse_mid_region_features,
    parse_weather_extra_points,
    short_forecast_to_weather_values,
    ultra_short_forecast_to_weather_values,
    ultra_short_nowcast_to_weather_values,
    weather_alerts_to_notice_bundles,
)

from dagster import AssetExecutionContext, asset

from .assets import (
    _COMMON_RESOURCE_KEYS,
    FEATURE_LOAD_RETRY_POLICY,
    _fetched_at,
    _load,
    _record_list,
    _resource_object,
    _resource_value,
)
from .etl import DagsterFeatureLoadResult, _add_output_metadata

if TYPE_CHECKING:
    from kortravelmap.client import AsyncKorTravelMapClient

__all__ = [
    "KMA_WEATHER_ASSETS",
    "KmaAlertRegionRow",
    "KmaAlertRow",
    "KmaForecastRow",
    "KmaGridTargets",
    "KmaMidForecastLoadResult",
    "KmaMidLandRow",
    "KmaMidTempRow",
    "KmaNowcastRow",
    "KmaWeatherLoadResult",
    "feature_notice_kma_weather_alerts",
    "feature_weather_kma_mid_forecast",
    "feature_weather_kma_short_forecast",
    "feature_weather_kma_ultra_short_forecast",
    "feature_weather_kma_ultra_short_nowcast",
    "forecast_rows_from_items",
    "map_grid_targets",
    "mid_land_rows_from_items",
    "mid_temp_rows_from_items",
    "nowcast_rows_from_snapshot",
    "run_feature_notice_kma_weather_alerts",
    "run_feature_weather_kma_mid_forecast",
    "run_feature_weather_kma_short_forecast",
    "run_feature_weather_kma_ultra_short_forecast",
    "run_feature_weather_kma_ultra_short_nowcast",
    "weather_warning_rows",
]

_KST: Final = timezone(timedelta(hours=9))

_KMA_WEATHER_RESOURCE_KEYS: Final[set[str]] = {
    "kor_travel_map_client",
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
    kor_travel_map_client = cast(
        "AsyncKorTravelMapClient", _resource_object(context, "kor_travel_map_client")
    )
    base_date, base_time = latest_base()
    base_key = f"{base_date}{base_time}"

    state = await kor_travel_map_client.get_sync_state(
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

    target_coords = await kor_travel_map_client.list_poi_cache_target_coords()
    place_coords = await kor_travel_map_client.list_active_place_coords()
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
            values_loaded += await kor_travel_map_client.load_weather_values(grid_values)
            matched_features.update(feature_ids)
    except Exception:
        await kor_travel_map_client.record_sync_failure(
            provider=KMA_PROVIDER_NAME, dataset_key=dataset_key
        )
        raise

    if grids_fetched:
        await kor_travel_map_client.record_sync_success(
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


# =========================================================================
# T-219c — 중기예보 (region 설정 주입) + 특보 (record resource → notice)
# =========================================================================


def _str_or_none(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _int_or_none(value: Any) -> int | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return int(float(text))
    except ValueError:
        return None


@dataclass(frozen=True, slots=True)
class KmaMidLandRow:
    """``KmaMidLandForecastItem`` Protocol을 만족하는 중기육상예보 row.

    ``MidForecastItem.raw``(KMA 공식 camelCase 필드 보존)에서 만든다.
    """

    reg_id: str
    tm_fc: str
    wf_3_am: str | None
    wf_3_pm: str | None
    wf_4_am: str | None
    wf_4_pm: str | None
    wf_5_am: str | None
    wf_5_pm: str | None
    wf_6_am: str | None
    wf_6_pm: str | None
    wf_7_am: str | None
    wf_7_pm: str | None
    wf_8: str | None
    wf_9: str | None
    wf_10: str | None
    rn_st_3_am: int | None
    rn_st_3_pm: int | None
    rn_st_4_am: int | None
    rn_st_4_pm: int | None
    rn_st_5_am: int | None
    rn_st_5_pm: int | None
    rn_st_6_am: int | None
    rn_st_6_pm: int | None
    rn_st_7_am: int | None
    rn_st_7_pm: int | None
    rn_st_8: int | None
    rn_st_9: int | None
    rn_st_10: int | None


@dataclass(frozen=True, slots=True)
class KmaMidTempRow:
    """``KmaMidTemperatureItem`` Protocol을 만족하는 중기기온예보 row."""

    reg_id: str
    tm_fc: str
    ta_min_3: int | None
    ta_max_3: int | None
    ta_min_4: int | None
    ta_max_4: int | None
    ta_min_5: int | None
    ta_max_5: int | None
    ta_min_6: int | None
    ta_max_6: int | None
    ta_min_7: int | None
    ta_max_7: int | None
    ta_min_8: int | None
    ta_max_8: int | None
    ta_min_9: int | None
    ta_max_9: int | None
    ta_min_10: int | None
    ta_max_10: int | None


def mid_land_rows_from_items(items: Sequence[Any]) -> list[KmaMidLandRow]:
    """``DataGoKrClient.mid_land_forecast()`` ``MidForecastItem`` → 육상 row 목록."""
    rows: list[KmaMidLandRow] = []
    for item in items:
        raw = item.raw
        kwargs: dict[str, Any] = {
            "reg_id": str(getattr(item, "reg_id", None) or raw.get("regId") or ""),
            "tm_fc": str(getattr(item, "tm_fc", None) or raw.get("tmFc") or ""),
        }
        for day in (3, 4, 5, 6, 7):
            for period in ("Am", "Pm"):
                suffix = period.lower()
                kwargs[f"wf_{day}_{suffix}"] = _str_or_none(raw.get(f"wf{day}{period}"))
                kwargs[f"rn_st_{day}_{suffix}"] = _int_or_none(
                    raw.get(f"rnSt{day}{period}")
                )
        for day in (8, 9, 10):
            kwargs[f"wf_{day}"] = _str_or_none(raw.get(f"wf{day}"))
            kwargs[f"rn_st_{day}"] = _int_or_none(raw.get(f"rnSt{day}"))
        rows.append(KmaMidLandRow(**kwargs))
    return rows


def mid_temp_rows_from_items(items: Sequence[Any]) -> list[KmaMidTempRow]:
    """``DataGoKrClient.mid_temperature_forecast()`` ``MidForecastItem`` → 기온 row 목록."""
    rows: list[KmaMidTempRow] = []
    for item in items:
        raw = item.raw
        kwargs: dict[str, Any] = {
            "reg_id": str(getattr(item, "reg_id", None) or raw.get("regId") or ""),
            "tm_fc": str(getattr(item, "tm_fc", None) or raw.get("tmFc") or ""),
        }
        for day in (3, 4, 5, 6, 7, 8, 9, 10):
            kwargs[f"ta_min_{day}"] = _int_or_none(raw.get(f"taMin{day}"))
            kwargs[f"ta_max_{day}"] = _int_or_none(raw.get(f"taMax{day}"))
        rows.append(KmaMidTempRow(**kwargs))
    return rows


def _latest_mid_base() -> str:
    """중기예보 최신 발표 ``tmFc`` (``YYYYMMDDHHMM``, ``kma.time_utils``)."""
    time_utils = cast(Any, importlib.import_module("kma.time_utils"))
    return str(time_utils.latest_mid_fcst_time())


@dataclass(frozen=True)
class KmaMidForecastLoadResult:
    """KMA 중기예보 적재 asset 결과."""

    provider: str
    dataset_key: str
    base_datetime: str
    skipped: bool
    regions_total: int
    regions_fetched: int
    features_total: int
    values_loaded: int

    def as_metadata(self) -> dict[str, object]:
        return {
            "provider": self.provider,
            "dataset_key": self.dataset_key,
            "base_datetime": self.base_datetime,
            "skipped": self.skipped,
            "regions_total": self.regions_total,
            "regions_fetched": self.regions_fetched,
            "features_total": self.features_total,
            "values_loaded": self.values_loaded,
        }


_KMA_MID_RESOURCE_KEYS: Final[set[str]] = {
    "kor_travel_map_client",
    "kma_datagokr_client",
    "kma_mid_region_features",
}


async def run_feature_weather_kma_mid_forecast(
    context: AssetExecutionContext,
) -> KmaMidForecastLoadResult:
    """KMA 중기예보(육상+기온)를 설정 주입 region의 feature에 적재한다.

    중기는 region 107 지점 체계(격자 아님)라 옵션 B 좌표 매핑이 불가 — 운영자가
    ``kma_mid_region_features``(JSON)로 region→feature 매핑을 명시 주입하고,
    미설정이면 skip한다(계획 정본 §2.4). cursor는 다른 KMA asset과 동일하게
    ``base_datetime``(발표 ``tmFc``) 기준.
    """
    kor_travel_map_client = cast(
        "AsyncKorTravelMapClient", _resource_object(context, "kor_travel_map_client")
    )
    base_key = _latest_mid_base()

    state = await kor_travel_map_client.get_sync_state(
        provider=KMA_PROVIDER_NAME, dataset_key=KMA_MID_FORECAST_DATASET_KEY
    )
    if state is not None and state.cursor.get("base_datetime") == base_key:
        context.log.info(
            "KMA %s base %s 이미 적재됨 — skip (provider_sync_state cursor).",
            KMA_MID_FORECAST_DATASET_KEY,
            base_key,
        )
        result = KmaMidForecastLoadResult(
            provider=KMA_PROVIDER_NAME,
            dataset_key=KMA_MID_FORECAST_DATASET_KEY,
            base_datetime=base_key,
            skipped=True,
            regions_total=0,
            regions_fetched=0,
            features_total=0,
            values_loaded=0,
        )
        _add_output_metadata(context, result.as_metadata())
        return result

    specs_raw = await _resource_value(context, "kma_mid_region_features", default=None)
    specs = parse_mid_region_features(cast("str | None", specs_raw))
    if not specs:
        context.log.warning(
            "KMA 중기예보 대상 region 미설정 — KOR_TRAVEL_MAP_KMA_MID_REGION_FEATURES가 "
            "비어 있다. cursor는 전진하지 않는다."
        )

    datagokr_client = _resource_object(context, "kma_datagokr_client")
    regions_fetched = 0
    values_loaded = 0
    matched_features: set[str] = set()
    try:
        for spec in specs:
            # 변환 함수 Protocol 인자: frozen dataclass attr은 mypy에서 read-only라
            # 직접 만족 판정이 안 됨 → ``Sequence[Any]`` 우회 (기존 패턴).
            land_rows: Sequence[Any] = mid_land_rows_from_items(
                cast(Any, datagokr_client).mid_land_forecast(reg_id=spec.land_reg_id)
            )
            temp_rows: Sequence[Any] = mid_temp_rows_from_items(
                cast(Any, datagokr_client).mid_temperature_forecast(
                    reg_id=spec.ta_reg_id
                )
            )
            regions_fetched += 1
            region_values: list[WeatherValue] = []
            for feature_id in spec.feature_ids:
                region_values.extend(
                    mid_land_forecast_to_weather_values(
                        land_rows, feature_id=feature_id
                    )
                )
                region_values.extend(
                    mid_temperature_to_weather_values(
                        temp_rows, feature_id=feature_id
                    )
                )
            if region_values:
                values_loaded += await kor_travel_map_client.load_weather_values(region_values)
                matched_features.update(spec.feature_ids)
    except Exception:
        await kor_travel_map_client.record_sync_failure(
            provider=KMA_PROVIDER_NAME, dataset_key=KMA_MID_FORECAST_DATASET_KEY
        )
        raise

    if regions_fetched:
        await kor_travel_map_client.record_sync_success(
            provider=KMA_PROVIDER_NAME,
            dataset_key=KMA_MID_FORECAST_DATASET_KEY,
            cursor={"base_datetime": base_key},
        )

    result = KmaMidForecastLoadResult(
        provider=KMA_PROVIDER_NAME,
        dataset_key=KMA_MID_FORECAST_DATASET_KEY,
        base_datetime=base_key,
        skipped=False,
        regions_total=len(specs),
        regions_fetched=regions_fetched,
        features_total=len(matched_features),
        values_loaded=values_loaded,
    )
    _add_output_metadata(context, result.as_metadata())
    return result


@asset(
    group_name="features_weather",
    required_resource_keys=_KMA_MID_RESOURCE_KEYS,
    retry_policy=FEATURE_LOAD_RETRY_POLICY,
)
async def feature_weather_kma_mid_forecast(
    context: AssetExecutionContext,
) -> KmaMidForecastLoadResult:
    return await run_feature_weather_kma_mid_forecast(context)


# -- 특보 (getWthrWrnList record → notice FeatureBundle) -------------------

_ALERT_TYPE_TOKENS: Final[tuple[str, ...]] = (
    "폭풍해일",
    "호우",
    "대설",
    "폭염",
    "강풍",
    "풍랑",
    "태풍",
    "건조",
    "한파",
    "황사",
)
"""특보 종류 토큰 — title에서 첫 매칭을 ``alert_type``으로 쓴다(긴 토큰 우선).

토큰은 전부 krtour ``normalize_notice_type`` alias에 등록돼 있다. 미매칭은
generic ``weather_alert``로 보내고 원문 title은 ``Feature.name``에 보존된다.
"""

_ALERT_LEVEL_TOKENS: Final[tuple[str, ...]] = ("예비특보", "주의보", "경보", "긴급")
"""특보 등급 토큰 — ``KMA_ALERT_LEVEL_SEVERITY`` 키와 동일 표기."""


@dataclass(frozen=True, slots=True)
class KmaAlertRegionRow:
    """``KmaWeatherAlertRegion`` Protocol을 만족하는 특보 지역 row."""

    region_code: str
    region_name: str


@dataclass(frozen=True)
class KmaAlertRow:
    """``KmaWeatherAlertItem`` Protocol을 만족하는 특보 row.

    ``getWthrWrnList``의 ``WeatherWarningItem``은 발표관서/시각/번호/제목만
    구조화돼 있다 — 종류/등급은 title 토큰 스캔으로 보수적으로 추출하고,
    특보구역은 1차로 발표관서 단위 1건으로 둔다(구역→좌표 enrichment는 백로그,
    계획 정본 §2.4 비고).
    """

    alert_id: str
    alert_type: str
    level: str | None
    title: str
    description: str | None
    issued_at: datetime
    effective_from: datetime | None
    effective_until: datetime | None
    source_agency: str | None
    regions: list[KmaAlertRegionRow]


def _parse_alert_tm_fc(tm_fc: str) -> datetime:
    """특보 ``tmFc``(``YYYYMMDDHHMM`` — 10자리면 분 보정) → KST aware."""
    text = tm_fc.strip()
    if len(text) == 10:
        text += "00"
    if len(text) != 12:
        raise ValueError(f"특보 tm_fc 형식 오류: {tm_fc!r} (10/12자리 필요).")
    return datetime.strptime(text, "%Y%m%d%H%M").replace(tzinfo=_KST)


def weather_warning_rows(records: Sequence[Any]) -> list[KmaAlertRow]:
    """``WeatherWarningItem`` record → ``KmaWeatherAlertItem`` Protocol row.

    title/tm_fc가 없는 row는 식별 불가라 건너뛴다 — 호출 asset이 dropped
    수를 로깅한다.
    """
    rows: list[KmaAlertRow] = []
    for record in records:
        title = _str_or_none(getattr(record, "title", None))
        tm_fc = _str_or_none(getattr(record, "tm_fc", None))
        if title is None or tm_fc is None:
            continue
        stn_id = _str_or_none(getattr(record, "stn_id", None)) or "unknown"
        seq = _str_or_none(getattr(record, "seq", None)) or "0"
        alert_type = next(
            (token for token in _ALERT_TYPE_TOKENS if token in title),
            "weather_alert",
        )
        level = next((token for token in _ALERT_LEVEL_TOKENS if token in title), None)
        regions = [
            KmaAlertRegionRow(
                region_code=f"stn:{stn_id}",
                region_name="전국" if stn_id == "108" else f"발표관서 {stn_id}",
            )
        ]
        rows.append(
            KmaAlertRow(
                alert_id=f"{stn_id}:{tm_fc}:{seq}",
                alert_type=alert_type,
                level=level,
                title=title,
                description=None,
                issued_at=_parse_alert_tm_fc(tm_fc),
                effective_from=None,
                effective_until=None,
                source_agency="기상청",
                regions=regions,
            )
        )
    return rows


async def run_feature_notice_kma_weather_alerts(
    context: AssetExecutionContext,
) -> DagsterFeatureLoadResult:
    """KMA 기상특보 record를 notice Feature로 적재한다(표준 record-resource 패턴).

    좌표는 region 단위라 없음 — ``SourceRecord.raw_address``의 region명이 위치
    단서로 주소 검증을 통과한다(T-219c, ADR-046 정합).
    """
    records = await _record_list(context, "kma_weather_alert_records")
    # Protocol 인자 ``Sequence[Any]`` 우회 — frozen dataclass attr read-only 함정.
    rows: Sequence[Any] = weather_warning_rows(records)
    dropped = len(records) - len(rows)
    if dropped:
        context.log.warning(
            "KMA 특보 record %d건이 title/tm_fc 부재로 제외됨(전체 %d건).",
            dropped,
            len(records),
        )
    fetched_at = await _fetched_at(context)
    bundles = weather_alerts_to_notice_bundles(rows, fetched_at=fetched_at)
    return await _load(
        context,
        provider=KMA_PROVIDER_NAME,
        dataset_key=KMA_WEATHER_ALERT_DATASET_KEY,
        bundles=bundles,
    )


@asset(
    group_name="features_notice",
    required_resource_keys=_COMMON_RESOURCE_KEYS | {"kma_weather_alert_records"},
    retry_policy=FEATURE_LOAD_RETRY_POLICY,
)
async def feature_notice_kma_weather_alerts(
    context: AssetExecutionContext,
) -> DagsterFeatureLoadResult:
    return await run_feature_notice_kma_weather_alerts(context)


KMA_WEATHER_ASSETS: Final = [
    feature_weather_kma_ultra_short_nowcast,
    feature_weather_kma_ultra_short_forecast,
    feature_weather_kma_short_forecast,
    feature_weather_kma_mid_forecast,
    feature_notice_kma_weather_alerts,
]
"""KMA weather/notice 적재 asset 목록 (T-219b/c)."""
