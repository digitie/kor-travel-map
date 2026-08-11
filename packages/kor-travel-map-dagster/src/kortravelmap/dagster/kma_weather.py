"""KMA weather Dagster asset 3종 (T-219b) — 옵션 B 대상 한정 적재.

초단기실황/초단기예보/단기예보는 대상 좌표가 DB(``ops.poi_cache_targets`` +
설정 추가 좌표)에서 나오므로 표준 record-resource(좌표 무관 스트림) 패턴이
맞지 않는다 — asset이 직접 ① ``kor_travel_map_client``로 대상 좌표/active place
좌표를 조회하고 ② ``python-kma-api``의 ``kma.grid.to_grid``로 격자를 dedupe
(run당 상한 적용) ③ 격자별로 ``KmaClient``를 호출해 ④ krtour 변환 함수로
``WeatherValue``를 만들어 적재한다(계획 정본
`docs/reports/kma-mcst-provider-plan-2026-06-11.md` §2.3).

같은 base 중복 호출 회피는 ``provider_sync_state`` cursor의
``base_datetime``과 target/grid ``membership_fingerprint``가 모두 같을 때만 한다.
KMA 호출 실패 시 cursor를 전진시키지 않고 ``record_sync_failure``만 남긴다
(신선도 대시보드 T-217g 신호).

provider client는 ADR-006대로 wrapper 없이 직접 사용한다. ``KmaClient``의
``ForecastItem``/``WeatherSnapshot``은 base/forecast를 ``datetime``으로 정규화한
모델이라 krtour 변환 Protocol(`KmaShortForecastItem` 등 — KMA 공식 필드명
snake_case row)과 shape이 다르다 — client가 보존한 ``raw`` payload(KMA 공식
필드명, ADR-044 신뢰·미러)에서 Protocol-만족 row를 만들어 변환에 넘긴다.
"""

# NOTE: `from __future__ import annotations` 금지 — dagster가 asset 함수의
# ``context`` 어노테이션을 런타임 타입으로 검증한다(assets.py와 동일).
import hashlib
import importlib
import inspect
import json
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import asdict, dataclass, is_dataclass
from datetime import datetime, timedelta, timezone
from functools import partial
from typing import TYPE_CHECKING, Any, Final, NoReturn, cast

from kortravelmap.core.feature_operation import ProviderDatasetOperationMembership
from kortravelmap.core.ids import make_payload_hash, make_source_record_key
from kortravelmap.core.sync_scope import (
    TARGET_GRIDS_SYNC_SCOPE,
    parse_canonical_sync_scope,
)
from kortravelmap.dto import SourceRecord, kst_now
from kortravelmap.dto.weather import WeatherValue
from kortravelmap.infra.feature_repo import FeatureLoadResult, NoticeFeatureLoadResult
from kortravelmap.infra.feature_update_executor import ProviderDatasetRefreshFailure
from kortravelmap.providers.kma import (
    KMA_MID_FORECAST_DATASET_KEY,
    KMA_PROVIDER_NAME,
    KMA_SHORT_FORECAST_DATASET_KEY,
    KMA_SHORT_GRID_DATASET_KEY,
    KMA_ULTRA_SHORT_FORECAST_DATASET_KEY,
    KMA_ULTRA_SHORT_GRID_DATASET_KEY,
    KMA_ULTRA_SHORT_NOWCAST_DATASET_KEY,
    KMA_WEATHER_ALERT_DATASET_KEY,
    grid_to_weather_bundle,
    mid_land_forecast_to_weather_values,
    mid_temperature_to_weather_values,
    parse_mid_region_features,
    parse_weather_extra_points,
    short_forecast_to_weather_values,
    ultra_short_forecast_to_weather_values,
    ultra_short_nowcast_to_weather_values,
    weather_alert_lift_closures,
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
    _reverse_geocoder,
)
from .etl import DagsterFeatureLoadResult, _add_output_metadata
from .feature_operation_tracking import (
    FeatureOperationGuardUnavailable,
    require_feature_operation_guard,
    run_tracked_feature_asset,
)
from .upstream_retry import (
    PROVIDER_BOUNDARY_BASE_DELAY_SECONDS,
    RetryBudget,
    retry_upstream_async,
)

if TYPE_CHECKING:
    from kortravelmap.client import AsyncKorTravelMapClient

__all__ = [
    "KMA_TARGET_SCOPE_EMPTY_EVENT_CODE",
    "KMA_WEATHER_ASSETS",
    "KmaAlertRegionRow",
    "KmaAlertRow",
    "KmaForecastRow",
    "KmaGridTargets",
    "KmaMidForecastLoadResult",
    "KmaMidLandRow",
    "KmaMidTempRow",
    "KmaNowcastRow",
    "KmaWeatherTargetScopeEmptyError",
    "KmaWeatherGridLimitExceeded",
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
    "weather_response_source_record",
]

_KST: Final = timezone(timedelta(hours=9))
KMA_TARGET_SCOPE_EMPTY_EVENT_CODE: Final = "kma.target_scope_empty"

_KMA_WEATHER_RESOURCE_KEYS: Final[set[str]] = {
    "feature_operation_guard",
    "kor_travel_map_client",
    "kma_weather_client_factory",
    "kma_weather_extra_points",
    "kma_weather_max_grids_per_run",
    "reverse_geocoder",
}
"""KMA weather asset 공통 resource key."""


def _response_row_payload(row: Any) -> dict[str, Any]:
    """typed KMA row를 source record에 보존할 canonical JSON object로 바꾼다."""

    if is_dataclass(row) and not isinstance(row, type):
        return asdict(row)
    raw = getattr(row, "raw", None)
    if isinstance(raw, dict):
        return dict(raw)
    model_dump = getattr(row, "model_dump", None)
    if callable(model_dump):
        dumped = model_dump(mode="json")
        if isinstance(dumped, dict):
            return dumped
    if isinstance(row, dict):
        return dict(row)
    raise TypeError(f"KMA response row cannot be preserved as JSON: {type(row).__name__}")


def weather_response_source_record(
    *,
    dataset_key: str,
    source_entity_id: str,
    rows: Sequence[Any],
    fetched_at: datetime,
) -> SourceRecord:
    """forecast dataset response 1건의 immutable provenance record를 만든다.

    KMA grid Feature의 raw source는 ``kma_*_grid`` dataset에 속한다. 값 fact는
    forecast/nowcast membership이 생산한 응답을 provenance로 가져야 하므로 이
    별도 record를 사용한다(ADR-089).
    """

    raw_data = {
        "source_entity_id": source_entity_id,
        "rows": [_response_row_payload(row) for row in rows],
    }
    payload_hash = make_payload_hash(raw_data)
    return SourceRecord(
        provider=KMA_PROVIDER_NAME,
        dataset_key=dataset_key,
        source_entity_type="weather_response",
        source_entity_id=source_entity_id,
        raw_payload_hash=payload_hash,
        raw_data=raw_data,
        fetched_at=fetched_at,
        source_record_key=make_source_record_key(
            provider=KMA_PROVIDER_NAME,
            dataset_key=dataset_key,
            source_entity_type="weather_response",
            source_entity_id=source_entity_id,
            raw_payload_hash=payload_hash,
        ),
    )


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


def _grid_center(nx: int, ny: int) -> tuple[float, float]:
    """KMA DFS 격자 ``(nx, ny)`` → 격자 중심 WGS84 ``(lat, lon)`` (``kma.grid.to_latlon``).

    격자 weather Feature의 좌표 — KMA 예보는 격자 단위라 격자 중심이 정본 위치다.
    """
    grid = cast(Any, importlib.import_module("kma.grid"))
    lat, lon = grid.to_latlon(nx, ny)
    return (float(lat), float(lon))


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


def _fetch_ultra_short_forecast_rows(kma_client: Any, nx: int, ny: int) -> list[KmaForecastRow]:
    return forecast_rows_from_items(kma_client.forecast.short(nx=nx, ny=ny))


def _fetch_short_forecast_rows(kma_client: Any, nx: int, ny: int) -> list[KmaForecastRow]:
    return forecast_rows_from_items(kma_client.forecast.vilage(nx=nx, ny=ny))


# -- 대상 격자/feature 매핑 (옵션 B) --------------------------------------


@dataclass(frozen=True)
class KmaGridTargets:
    """대상 격자 목록 (``map_grid_targets`` 결과)."""

    grids: tuple[tuple[int, int], ...]
    """run 상한 적용 후 대상 격자 — 입력 순서(poi target → extra point) 유지."""

    grids_dropped: int
    """run 상한 초과로 제외된 격자 수 (운영 로그용 — silent cap 금지)."""

    membership_fingerprint: str
    """target 좌표·extra 좌표·dedupe 전량 격자 membership의 SHA-256."""


def _grid_membership_fingerprint(
    *,
    target_coords: Sequence[tuple[float, float]],
    extra_points: Sequence[tuple[float, float]],
    grids: Sequence[tuple[int, int]],
) -> str:
    payload = {
        "version": 1,
        "target_coords": sorted((lon.hex(), lat.hex()) for lon, lat in target_coords),
        "extra_points": sorted((lon.hex(), lat.hex()) for lon, lat in extra_points),
        "grids": sorted(grids),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def map_grid_targets(
    *,
    target_coords: Sequence[tuple[float, float]],
    extra_points: Sequence[tuple[float, float]],
    to_grid: Callable[[float, float], tuple[int, int]],
    max_grids: int,
) -> KmaGridTargets:
    """(lon, lat) 대상 좌표 → 격자 dedupe + 상한.

    ``target_coords``(poi_cache_targets)가 ``extra_points``(설정 명시 좌표)보다
    먼저다 — 상한 절단 시 수요가 증명된 지점이 우선 생존한다. 각 대상 격자는
    자체 weather-kind Feature(격자 중심)로 적재되므로 place feature 매핑은 없다.
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
    return KmaGridTargets(
        grids=tuple(capped),
        grids_dropped=dropped,
        membership_fingerprint=_grid_membership_fingerprint(
            target_coords=target_coords,
            extra_points=extra_points,
            grids=ordered,
        ),
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
    """cursor의 base와 membership이 모두 같아 호출 없이 끝났으면 True."""

    grids_total: int
    grids_fetched: int
    grids_dropped: int
    features_total: int
    values_loaded: int
    membership_fingerprint: str
    """이번 실행의 target/grid membership fingerprint."""

    sync_scope: str = TARGET_GRIDS_SYNC_SCOPE
    """실제 target 선택과 provider sync state에 사용한 canonical scope."""

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
            "membership_fingerprint": self.membership_fingerprint,
            "sync_scope": self.sync_scope,
        }


# -- 공통 runner ----------------------------------------------------------


class KmaWeatherTargetScopeEmptyError(ProviderDatasetRefreshFailure):
    """KMA scope를 격자로 해석한 결과 실행 가능한 target이 없다."""

    record_sync_failure = False
    event_code = KMA_TARGET_SCOPE_EMPTY_EVENT_CODE


class KmaWeatherGridLimitExceeded(ProviderDatasetRefreshFailure):
    """KMA target 격자가 실행 상한을 초과해 전체 실행을 거부했다."""


async def _exact_kma_sync_membership(
    context: AssetExecutionContext,
    client: "AsyncKorTravelMapClient",
    *,
    expected_sync_scope: str | None = None,
) -> ProviderDatasetOperationMembership:
    """scheduled/queue 실행 모두에서 DB exact membership만 sync-state에 쓴다.

    queue worker는 request를 claim할 때 고정한 typed membership resource를 넘긴다.
    scheduled run은 guard가 고정한 **실행 manifest**를 쓴다. provider나 dataset
    label에서 membership을 역산하는 fallback은 두지 않는다.

    KMA 격자 dataset은 카탈로그에 scope가 둘이다(``dataset_wide`` +
    ``target_grids``, ``0089_tvn33_expand_seed``). 그중 ``dataset_wide``는 이 asset과
    queue runner 양쪽이 명시적으로 거부하므로 실행 경로가 없다. 따라서 run은
    ``target_grids``만 실행 manifest로 선언하고, 여기서 요구하는 "manifest 1건"은 그
    선언을 확인하는 것이지 카탈로그 scope가 1개라는 주장이 아니다.
    """
    resource_membership = await _resource_value(
        context,
        "feature_update_membership",
        default=None,
    )
    if resource_membership is not None:
        if not isinstance(resource_membership, ProviderDatasetOperationMembership):
            raise FeatureOperationGuardUnavailable(
                boundary="kma_sync_state",
                reason="feature_update_membership_wrong_type",
            )
        membership = resource_membership
    else:
        guard = require_feature_operation_guard(context, boundary="kma_sync_state")
        if guard.operation_key is None:
            raise FeatureOperationGuardUnavailable(
                boundary="kma_sync_state",
                reason="operation_key_missing",
            )
        executable = await client.resolve_feature_operation_memberships(
            operation_key=guard.operation_key,
        )
        if not set(guard.memberships) <= set(executable):
            raise FeatureOperationGuardUnavailable(
                boundary="kma_sync_state",
                reason="membership_snapshot_changed",
            )
        if len(guard.memberships) != 1:
            raise FeatureOperationGuardUnavailable(
                boundary="kma_sync_state",
                reason="operation_requires_exactly_one_membership",
            )
        membership = guard.memberships[0]
    if expected_sync_scope is not None and membership.sync_scope != expected_sync_scope:
        raise FeatureOperationGuardUnavailable(
            boundary="kma_sync_state",
            reason="membership_sync_scope_mismatch",
        )
    return membership


def _assert_failure_membership(
    failure: ProviderDatasetRefreshFailure,
    membership: ProviderDatasetOperationMembership,
) -> None:
    if (
        failure.provider_dataset_id,
        failure.sync_scope,
        failure.operation_key,
    ) != (
        membership.provider_dataset_id,
        membership.sync_scope,
        membership.operation_key,
    ):
        raise RuntimeError("KMA refresh failure가 resolved membership과 일치하지 않음")


async def _raise_kma_refresh_failure(
    context: AssetExecutionContext,
    client: "AsyncKorTravelMapClient",
    membership: ProviderDatasetOperationMembership,
    failure: ProviderDatasetRefreshFailure,
    *,
    cause: Exception | None = None,
) -> NoReturn:
    _assert_failure_membership(failure, membership)
    managed_by_executor = await _resource_value(
        context,
        "kma_weather_sync_failure_managed_by_executor",
        default=False,
    )
    if managed_by_executor is not True and failure.record_sync_failure:
        await client.record_sync_failure_for_operation_membership(
            membership=membership,
        )
    if cause is not None:
        raise failure from cause
    raise failure


async def _close_owned_kma_weather_client(client: object) -> None:
    close = getattr(client, "close", None)
    if not callable(close):
        return
    result = close()
    if inspect.isawaitable(result):
        await cast("Awaitable[object]", result)


async def _run_kma_weather_asset(
    context: AssetExecutionContext,
    *,
    dataset_key: str,
    grid_dataset_key: str,
    grid_name_label: str,
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
    raw_sync_scope = await _resource_value(
        context,
        "kma_weather_sync_scope",
        default=TARGET_GRIDS_SYNC_SCOPE,
    )
    if not isinstance(raw_sync_scope, str):
        raise ValueError("kma_weather_sync_scope must be a string")
    sync_scope = parse_canonical_sync_scope(raw_sync_scope)
    if sync_scope.kind == "dataset_wide":
        raise ValueError(
            "KMA grid datasets require target_grids or external_system:<name> sync_scope"
        )
    membership = await _exact_kma_sync_membership(
        context,
        kor_travel_map_client,
        expected_sync_scope=sync_scope.value,
    )

    target_coords = await kor_travel_map_client.list_poi_cache_target_coords(
        external_system=sync_scope.external_system,
    )
    extra_points: Sequence[tuple[float, float]] = ()
    if sync_scope.kind == "target_grids":
        extra_raw = await _resource_value(
            context,
            "kma_weather_extra_points",
            default=None,
        )
        extra_points = parse_weather_extra_points(cast("str | None", extra_raw))
    max_grids = int(
        cast(
            "int",
            await _resource_value(context, "kma_weather_max_grids_per_run", default=300),
        )
    )

    targets = map_grid_targets(
        target_coords=target_coords,
        extra_points=extra_points,
        to_grid=_kma_grid,
        max_grids=max_grids,
    )
    if targets.grids_dropped:
        await _raise_kma_refresh_failure(
            context,
            kor_travel_map_client,
            membership,
            KmaWeatherGridLimitExceeded(
                provider_dataset_id=membership.provider_dataset_id,
                sync_scope=sync_scope.value,
                operation_key=membership.operation_key,
                message=(
                    "KMA target grid count exceeds max_grids; partial execution is forbidden: "
                    f"total={len(targets.grids) + targets.grids_dropped}, "
                    f"max_grids={max_grids}"
                ),
            ),
        )
    if not targets.grids:
        scope_detail = (
            f"external_system={sync_scope.external_system!r}"
            if sync_scope.kind == "external_system"
            else "target_grids (active targets + configured extra points)"
        )
        await _raise_kma_refresh_failure(
            context,
            kor_travel_map_client,
            membership,
            KmaWeatherTargetScopeEmptyError(
                provider_dataset_id=membership.provider_dataset_id,
                sync_scope=sync_scope.value,
                operation_key=membership.operation_key,
                message=(
                    "KMA target scope has no active POI cache targets or effective "
                    f"grids after grid resolution and cap: {scope_detail}"
                ),
            ),
        )

    base_date, base_time = latest_base()
    base_key = f"{base_date}{base_time}"
    membership_fingerprint = targets.membership_fingerprint

    state = await kor_travel_map_client.get_sync_state_for_operation_membership(
        membership=membership,
    )
    if (
        state is not None
        and state.cursor.get("base_datetime") == base_key
        and state.cursor.get("membership_fingerprint") == membership_fingerprint
    ):
        context.log.info(
            "KMA %s base %s, membership %s 이미 적재됨 — skip "
            "(provider_sync_state cursor, scope=%s).",
            dataset_key,
            base_key,
            membership_fingerprint,
            sync_scope.value,
        )
        result = KmaWeatherLoadResult(
            provider=KMA_PROVIDER_NAME,
            dataset_key=dataset_key,
            base_datetime=base_key,
            skipped=True,
            grids_total=len(targets.grids),
            grids_fetched=0,
            grids_dropped=0,
            features_total=0,
            values_loaded=0,
            membership_fingerprint=membership_fingerprint,
            sync_scope=sync_scope.value,
        )
        _add_output_metadata(context, result.as_metadata())
        return result

    grids_fetched = 0
    values_loaded = 0
    matched_features: set[str] = set()
    owned_kma_client: object | None = None
    primary_error: BaseException | None = None
    try:
        client_factory = _resource_object(
            context,
            "kma_weather_client_factory",
        )
        if not callable(client_factory):
            raise TypeError("kma_weather_client_factory must be callable")
        # KmaClient constructor는 outbound I/O를 하지 않는다. preflight 뒤 이
        # task에서 동기 생성해 client 소유권을 즉시 확정한다.
        owned_kma_client = client_factory()
        kma_client = owned_kma_client
        reverse_geocoder = _reverse_geocoder(context)
        fetched_at = kst_now()
        # H45: run당 재시도 예산 — 상관 장애(전 격자 동시 열화)에서 N×backoff
        # 전액을 지불하지 않고 조기 실패한다(리뷰 반영 early abort).
        retry_budget = RetryBudget()
        for nx, ny in targets.grids:
            # H45: 단건 격자 호출만 유한 재시도(retryable 분류 예외 한정 — kma
            # ``retryable`` 규약, quota/rate_limit 제외). N건 순차 호출에서 step
            # 전량 재시도의 시도당 전멸 확률(1-p^N)을 제거한다. attempts 소진
            # 시 원 예외 그대로 전파 — 부분 실행 금지·기존 실패 분류 경로 불변.
            rows = await retry_upstream_async(
                partial(fetch_rows, kma_client, nx, ny),
                label=f"{dataset_key} grid {nx},{ny}",
                base_delay=PROVIDER_BOUNDARY_BASE_DELAY_SECONDS,
                budget=retry_budget,
                on_retry=context.log.warning,
            )
            grids_fetched += 1
            if not rows:
                continue
            # KMA 격자를 자체 weather-kind Feature(격자 중심 좌표)로 만들고 그
            # feature_id에 격자 응답을 1회 적재한다(격자당 1 feature·1 값세트 —
            # #496 anti-replication 유지: 격자×feature 팬아웃 없음). place feature를
            # 빌리지 않으므로 KMA 날씨가 airkorea 측정소와 **별개** 마커로 뜬다. 다른
            # feature의 weather는 build_weather_card가 반경 내 가장 가까운 KMA 격자
            # anchor를 조회·병합해 서빙한다(weather_repo nearest-temp).
            lat, lon = _grid_center(nx, ny)
            bundle = await grid_to_weather_bundle(
                nx,
                ny,
                lat,
                lon,
                dataset_key=grid_dataset_key,
                name_label=grid_name_label,
                fetched_at=fetched_at,
                reverse_geocoder=reverse_geocoder,
            )
            await kor_travel_map_client.load_feature_bundles([bundle])
            anchor = bundle.feature.feature_id
            grid_values: list[WeatherValue] = list(to_values(rows, anchor))
            response_record = weather_response_source_record(
                dataset_key=dataset_key,
                source_entity_id=f"grid:{nx}:{ny}",
                rows=rows,
                fetched_at=fetched_at,
            )
            values_loaded += await kor_travel_map_client.load_weather_values(
                grid_values,
                provider_dataset_id=membership.provider_dataset_id,
                source_record=response_record,
            )
            matched_features.add(anchor)
        if grids_fetched:
            await kor_travel_map_client.record_sync_success_for_operation_membership(
                membership=membership,
                cursor={
                    "base_datetime": base_key,
                    "membership_fingerprint": membership_fingerprint,
                },
            )
    except ProviderDatasetRefreshFailure as exc:
        primary_error = exc
        raise
    except Exception as exc:
        failure = ProviderDatasetRefreshFailure(
            provider_dataset_id=membership.provider_dataset_id,
            sync_scope=sync_scope.value,
            operation_key=membership.operation_key,
            message=f"KMA provider refresh failed: {exc}",
        )
        primary_error = failure
        await _raise_kma_refresh_failure(
            context,
            kor_travel_map_client,
            membership,
            failure,
            cause=exc,
        )
    except BaseException as exc:
        # CancelledError 등 cooperative cancellation은 provider failure로
        # 재분류하지 않는다. cleanup 실패보다 원래 cancellation을 우선한다.
        primary_error = exc
        raise
    finally:
        if owned_kma_client is not None:
            try:
                await _close_owned_kma_weather_client(owned_kma_client)
            except BaseException:
                if primary_error is None:
                    raise
                primary_error.add_note(
                    "KMA client close도 실패했지만 primary error identity를 보존함."
                )
                log_error = getattr(context.log, "error", None)
                if callable(log_error):
                    try:
                        log_error(
                            "KMA primary failure/cancellation 뒤 client close도 실패했지만 "
                            "원래 error identity를 보존한다.",
                            exc_info=True,
                        )
                    except BaseException:
                        # 보조 진단 logger도 cooperative cancellation/primary
                        # failure를 덮을 수 없다.
                        primary_error.add_note("KMA client close 실패 진단 logger도 실패함.")

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
        membership_fingerprint=membership_fingerprint,
        sync_scope=sync_scope.value,
    )
    _add_output_metadata(context, result.as_metadata())
    return result


# -- asset 3종 -------------------------------------------------------------


async def run_feature_weather_kma_ultra_short_nowcast(
    context: AssetExecutionContext,
) -> KmaWeatherLoadResult:
    """KMA 초단기실황(``getUltraSrtNcst``)을 격자 **초단기** weather feature에 적재한다."""
    return await _run_kma_weather_asset(
        context,
        dataset_key=KMA_ULTRA_SHORT_NOWCAST_DATASET_KEY,
        grid_dataset_key=KMA_ULTRA_SHORT_GRID_DATASET_KEY,
        grid_name_label="기상청 초단기",
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
    return await run_tracked_feature_asset(context, run_feature_weather_kma_ultra_short_nowcast)


async def run_feature_weather_kma_ultra_short_forecast(
    context: AssetExecutionContext,
) -> KmaWeatherLoadResult:
    """KMA 초단기예보(``getUltraSrtFcst``)를 격자 **초단기** weather feature에 적재한다.

    초단기실황과 같은 ``grid_dataset_key``(=같은 feature_id)에 적재 — 실황+예보가
    한 초단기 feature에 공존한다."""
    return await _run_kma_weather_asset(
        context,
        dataset_key=KMA_ULTRA_SHORT_FORECAST_DATASET_KEY,
        grid_dataset_key=KMA_ULTRA_SHORT_GRID_DATASET_KEY,
        grid_name_label="기상청 초단기",
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
    return await run_tracked_feature_asset(context, run_feature_weather_kma_ultra_short_forecast)


async def run_feature_weather_kma_short_forecast(
    context: AssetExecutionContext,
) -> KmaWeatherLoadResult:
    """KMA 단기예보(``getVilageFcst``)를 격자 **단기** weather feature에 적재한다.

    초단기와 같은 격자라도 ``grid_dataset_key``가 달라 **별개** feature가 된다."""
    return await _run_kma_weather_asset(
        context,
        dataset_key=KMA_SHORT_FORECAST_DATASET_KEY,
        grid_dataset_key=KMA_SHORT_GRID_DATASET_KEY,
        grid_name_label="기상청 단기",
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
    return await run_tracked_feature_asset(context, run_feature_weather_kma_short_forecast)


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
                kwargs[f"rn_st_{day}_{suffix}"] = _int_or_none(raw.get(f"rnSt{day}{period}"))
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
    "feature_operation_guard",
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
    membership = await _exact_kma_sync_membership(context, kor_travel_map_client)
    base_key = _latest_mid_base()

    state = await kor_travel_map_client.get_sync_state_for_operation_membership(
        membership=membership,
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
    fetched_at = kst_now()
    try:
        # H45(재리뷰 2 N-1): client retries=1 정산은 mid에도 적용되므로, 경계
        # 재시도 없이는 mid만 HTTP 4→2 시도로 약화된다 — 격자 루프와 동일하게
        # 경계당 4 시도로 균일화.
        retry_budget = RetryBudget()
        for spec in specs:
            # 변환 함수 Protocol 인자: frozen dataclass attr은 mypy에서 read-only라
            # 직접 만족 판정이 안 됨 → ``Sequence[Any]`` 우회 (기존 패턴).
            land_rows: Sequence[Any] = mid_land_rows_from_items(
                await retry_upstream_async(
                    partial(
                        cast(Any, datagokr_client).mid_land_forecast,
                        reg_id=spec.land_reg_id,
                    ),
                    label=f"kma mid land {spec.land_reg_id}",
                    base_delay=PROVIDER_BOUNDARY_BASE_DELAY_SECONDS,
                    budget=retry_budget,
                    on_retry=context.log.warning,
                )
            )
            temp_rows: Sequence[Any] = mid_temp_rows_from_items(
                await retry_upstream_async(
                    partial(
                        cast(Any, datagokr_client).mid_temperature_forecast,
                        reg_id=spec.ta_reg_id,
                    ),
                    label=f"kma mid temp {spec.ta_reg_id}",
                    base_delay=PROVIDER_BOUNDARY_BASE_DELAY_SECONDS,
                    budget=retry_budget,
                    on_retry=context.log.warning,
                )
            )
            regions_fetched += 1
            # 복제 제거(메인 격자 루프와 동일 원칙): region 응답을 대표 feature
            # 1개(anchor)에만 적재. 나머지는 read 시 nearest-temp로 서빙.
            land_values: list[WeatherValue] = []
            temperature_values: list[WeatherValue] = []
            anchor = spec.feature_ids[0] if spec.feature_ids else None
            if anchor is not None:
                land_values = mid_land_forecast_to_weather_values(
                    land_rows, feature_id=anchor
                )
                temperature_values = mid_temperature_to_weather_values(
                    temp_rows, feature_id=anchor
                )
            if anchor is not None and land_values:
                values_loaded += await kor_travel_map_client.load_weather_values(
                    land_values,
                    provider_dataset_id=membership.provider_dataset_id,
                    source_record=weather_response_source_record(
                        dataset_key=KMA_MID_FORECAST_DATASET_KEY,
                        source_entity_id=f"mid-land:{spec.land_reg_id}",
                        rows=land_rows,
                        fetched_at=fetched_at,
                    ),
                )
            if anchor is not None and temperature_values:
                values_loaded += await kor_travel_map_client.load_weather_values(
                    temperature_values,
                    provider_dataset_id=membership.provider_dataset_id,
                    source_record=weather_response_source_record(
                        dataset_key=KMA_MID_FORECAST_DATASET_KEY,
                        source_entity_id=f"mid-temperature:{spec.ta_reg_id}",
                        rows=temp_rows,
                        fetched_at=fetched_at,
                    ),
                )
            if (land_values or temperature_values) and anchor is not None:
                matched_features.add(anchor)
    except Exception as exc:
        failure = ProviderDatasetRefreshFailure(
            provider_dataset_id=membership.provider_dataset_id,
            sync_scope=membership.sync_scope,
            operation_key=membership.operation_key,
            message=f"KMA mid forecast refresh failed: {exc}",
        )
        await _raise_kma_refresh_failure(
            context,
            kor_travel_map_client,
            membership,
            failure,
            cause=exc,
        )

    if regions_fetched:
        await kor_travel_map_client.record_sync_success_for_operation_membership(
            membership=membership,
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
    return await run_tracked_feature_asset(context, run_feature_weather_kma_mid_forecast)


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


def _latest_notice_lineage_events(
    bundles: Sequence[Any],
    closures: Sequence[Any],
) -> dict[str, tuple[bool, datetime, datetime | None]]:
    """rolling window의 발표/해제를 계보별 최신 event 한 건으로 접는다."""
    events: dict[str, tuple[bool, datetime, datetime | None]] = {}

    def remember(
        lineage_key: str,
        present: bool,
        changed_at: datetime,
        valid_until: datetime | None,
    ) -> None:
        current = events.get(lineage_key)
        if current is None or changed_at > current[1]:
            events[lineage_key] = (present, changed_at, valid_until)
        elif changed_at == current[1] and (present != current[0] or valid_until != current[2]):
            raise ValueError("KMA notice 계보의 동일 시각 발표/해제가 충돌한다.")

    for bundle in bundles:
        raw_issued_at = bundle.source_record.raw_data.get("issued_at")
        changed_at = (
            datetime.fromisoformat(raw_issued_at)
            if isinstance(raw_issued_at, str)
            else bundle.feature.detail.valid_start_time
        )
        if changed_at is None:
            changed_at = bundle.source_record.fetched_at
        remember(
            bundle.source_record.source_entity_id,
            True,
            changed_at,
            bundle.feature.detail.valid_end_time,
        )
    for closure in closures:
        remember(closure.natural_key, False, closure.closed_at, None)
    return events


async def run_feature_notice_kma_weather_alerts(
    context: AssetExecutionContext,
) -> DagsterFeatureLoadResult:
    """KMA 기상특보 record를 notice Feature로 적재한다(표준 record-resource 패턴).

    좌표는 region 단위라 없음 — raw payload의 ``region_name``이 위치 단서로 주소
    검증을 통과한다(T-219c, ADR-046 정합).
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
    # 발표 → 사건 단위 upsert bundle / 해제 → 열린 feature 닫기 지시(#632).
    bundles = weather_alerts_to_notice_bundles(rows, fetched_at=fetched_at)
    closures = weather_alert_lift_closures(rows)
    lineage_events = _latest_notice_lineage_events(bundles, closures)
    client = cast(
        "AsyncKorTravelMapClient",
        _resource_object(context, "kor_travel_map_client"),
    )
    reconciled: Any | None = None

    async def load_events_atomically(
        validated_bundles: Sequence[Any],
    ) -> FeatureLoadResult:
        nonlocal reconciled
        atomic_load = getattr(client, "load_notice_event_bundles", None)
        if not callable(atomic_load):
            raise RuntimeError("KMA notice는 atomic event load client가 필요하다.")
        outcome = cast(
            "NoticeFeatureLoadResult",
            await atomic_load(
                bundles=validated_bundles,
                provider=KMA_PROVIDER_NAME,
                dataset_key=KMA_WEATHER_ALERT_DATASET_KEY,
                source_entity_type="weather_alert",
                lineage_events=lineage_events,
                observed_at=fetched_at,
            ),
        )
        reconciled = outcome.reconcile
        return outcome.load

    result = await _load(
        context,
        provider=KMA_PROVIDER_NAME,
        dataset_key=KMA_WEATHER_ALERT_DATASET_KEY,
        bundles=bundles,
        authoritative_snapshot_complete=True,
        load_all=load_events_atomically,
    )
    if reconciled is None:
        raise RuntimeError("KMA notice atomic load가 reconcile 결과를 반환하지 않았다.")
    if closures or reconciled.reopened:
        context.log.info(
            "KMA 특보 event — 해제 %d건, 닫음 %d건, 재등장 복구 %d건.",
            len(closures),
            reconciled.closed,
            reconciled.reopened,
        )
    return result


@asset(
    group_name="features_notice",
    required_resource_keys=_COMMON_RESOURCE_KEYS | {"kma_weather_alert_records"},
    retry_policy=FEATURE_LOAD_RETRY_POLICY,
)
async def feature_notice_kma_weather_alerts(
    context: AssetExecutionContext,
) -> DagsterFeatureLoadResult:
    return await run_tracked_feature_asset(context, run_feature_notice_kma_weather_alerts)


KMA_WEATHER_ASSETS: Final = [
    feature_weather_kma_ultra_short_nowcast,
    feature_weather_kma_ultra_short_forecast,
    feature_weather_kma_short_forecast,
    feature_weather_kma_mid_forecast,
    feature_notice_kma_weather_alerts,
]
"""KMA weather/notice 적재 asset 목록 (T-219b/c)."""
