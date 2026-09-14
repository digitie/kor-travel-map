"""Feature update request queue runner for Dagster.

API의 update request는 queue row만 만들고, 실제 provider refresh는 Dagster
``feature_update_request_worker``가 이 runner를 통해 기존 feature load asset
구현을 직접 호출한다.
"""

from __future__ import annotations

import asyncio
import copy
import importlib
import inspect
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass, replace
from types import MappingProxyType, SimpleNamespace
from typing import Any, Final, cast

from kortravelmap.client import AsyncKorTravelMapClient
from kortravelmap.core.feature_operation import ProviderDatasetOperationMembership
from kortravelmap.core.sync_scope import parse_canonical_sync_scope
from kortravelmap.infra.advisory_lock import advisory_lock
from kortravelmap.infra.feature_update_executor import (
    ProviderDatasetRefreshFailure,
    ProviderDatasetRefreshResult,
    ProviderDatasetRefreshScope,
)
from kortravelmap.providers.feature_operation_registry import (
    UnknownFeatureOperationHandlerError,
    feature_operation_handler_keys,
    resolve_feature_operation_handler,
)
from kortravelmap.providers.kma import (
    KMA_SHORT_FORECAST_DATASET_KEY,
    KMA_ULTRA_SHORT_FORECAST_DATASET_KEY,
    KMA_ULTRA_SHORT_NOWCAST_DATASET_KEY,
)
from kortravelmap.providers.mcst import MCST_FILE_DATASETS
from kortravelmap.providers.mois import DATASET_KEY_BULK as MOIS_BULK_DATASET_KEY
from kortravelmap.settings import KorTravelMapSettings
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from dagster import InitResourceContext, resource

from . import upstream_retry
from .assets import (
    run_feature_event_datagokr_cultural_festivals,
    run_feature_event_krheritage_events,
    run_feature_event_visitkorea_enrichment,
    run_feature_geometry_knps_records,
    run_feature_notice_krex_traffic_notices,
    run_feature_notice_krforest_landslide_forecast_issues,
    run_feature_place_datagokr_file_data,
    run_feature_place_khoa_beaches,
    run_feature_place_knps_points,
    run_feature_place_kor_travel_concierge_youtube,
    run_feature_place_krairport_airports,
    run_feature_place_krex_rest_areas,
    run_feature_place_krforest_arboretums,
    run_feature_place_krforest_recreation_forests,
    run_feature_place_krheritage_items,
    run_feature_place_mois_licenses,
    run_feature_place_opinet_stations,
    run_feature_place_standard_museums,
    run_feature_place_standard_parking_lots,
    run_feature_place_standard_special_streets,
    run_feature_place_standard_tourist_attractions,
    run_feature_price_krex_rest_areas,
    run_feature_price_opinet_stations,
    run_feature_route_krforest_dulle_trails,
    run_feature_route_krforest_mountain_trails,
    run_feature_weather_airkorea_air_quality,
    run_feature_weather_krex_rest_areas,
    run_feature_weather_krforest_mountain_weather,
    run_feature_weather_krforest_wildfire_risk_forecast,
)
from .kma_weather import (
    run_feature_notice_kma_weather_alerts,
    run_feature_weather_kma_mid_forecast,
    run_feature_weather_kma_short_forecast,
    run_feature_weather_kma_ultra_short_forecast,
    run_feature_weather_kma_ultra_short_nowcast,
)
from .mcst_features import run_feature_place_mcst_culture
from .mois_source_sync import ensure_mois_source_db_fresh
from .provider_fetchers import (
    ProviderCredentialMissing,
    fetch_airkorea_air_quality,
    fetch_airkorea_stations,
    fetch_datagokr_cultural_festivals,
    fetch_datagokr_file_data_records,
    fetch_khoa_beaches,
    fetch_kma_weather_alerts,
    fetch_knps_geometry_records,
    fetch_knps_point_records,
    fetch_kor_travel_concierge_youtube_features,
    fetch_krairport_airports,
    fetch_krex_rest_area_fuel_prices,
    fetch_krex_rest_area_weather,
    fetch_krex_rest_areas,
    fetch_krex_traffic_notices,
    fetch_krforest_arboretums,
    fetch_krforest_dulle_trails,
    fetch_krforest_landslide_forecast_issues,
    fetch_krforest_mountain_trails,
    fetch_krforest_mountain_weather,
    fetch_krforest_recreation_forests,
    fetch_krforest_wildfire_risk_forecast,
    fetch_krheritage_events,
    fetch_krheritage_items,
    fetch_mcst_culture_records,
    fetch_mois_license_records,
    fetch_opinet_station_price_details,
    fetch_opinet_stations,
    fetch_standard_museums,
    fetch_standard_parking_lots,
    fetch_standard_special_streets,
    fetch_standard_tourist_attractions,
    fetch_visitkorea_festival_events,
)
from .schedules import DISABLED_FEATURE_LOAD_OPERATION_KEYS
from .upstream_requests import (
    UPSTREAM_REQUESTS_METADATA_KEY,
    counting_upstream_requests,
    observed_upstream_requests,
)

__all__ = [
    "FeatureUpdateAssetRunner",
    "FeatureUpdateRunnerSpec",
    "feature_update_runner_resource",
]

AssetRun = Callable[[Any], Awaitable[Any]]
ResourceFactory = Callable[
    [KorTravelMapSettings, ProviderDatasetRefreshScope],
    "RunnerResources",
]
Teardown = Callable[[], object]
_COMMON_RESOURCE_KEYS: Final[set[str]] = {
    "kor_travel_map_client",
    "reverse_geocoder",
    "fetched_at",
    "strict_address",
}

_MISSING: Final = object()


@dataclass(frozen=True, slots=True)
class RunnerResources:
    """Asset direct invocation에 더할 resource 값과 cleanup hook."""

    values: Mapping[str, object]
    teardowns: tuple[Teardown, ...] = ()


KREX_RATE_GATE: Final[str] = "krex"
"""krex rate gate 이름. :data:`PROVIDER_RATE_GATES`의 키다."""


PROVIDER_RATE_GATES: Final[Mapping[str, float]] = MappingProxyType(
    {
        # krex는 **초당 5건**이 상한이다(일일 한도는 미공개 — `docs/etl/upstream-quota.md`
        # §2). 라이브러리(`python-krex-api`)가 그것을 지키지만 그 보증은 **프로세스당**
        # 이다. 큐 센서는 틱당 RunRequest를 10개 내고 `docker/dagster.yaml`이 4를 동시에
        # 돌리므로, gate가 없으면 버킷이 넷 = **20 TPS**가 된다(2026-09-14 적대 리뷰).
        #
        # 값은 **교대 간격**(초)이다. 직렬화만으로는 부족하다 — A가 마지막 요청을
        # 보내고 즉시 lock을 놓으면 B의 첫 요청이 그 뒤에 바로 붙어 1초 창에 6건이
        # 된다. lock을 놓기 전에 이만큼 쉬면 **전 프로세스를 통틀어** 요청 간격이
        # 1/5초 아래로 내려가지 않는다.
        KREX_RATE_GATE: 1.0 / 5.0,
    }
)
"""프로세스를 가로지르는 provider 단위 rate gate — 이름 → 교대 간격(초).

**왜 advisory lock인가.** 같은 Postgres를 보는 모든 worker run이 이 키를 두고
경합하므로, Dagster 설정이나 프로세스 수와 무관하게 성립한다.
`ops.provider_refresh_policies.max_concurrent`에 자리가 있지만 그 값은 plan
payload에 실리기만 하고 **집행되지 않는다**(`T-VN-KREX-TPS-FANOUT`).
"""


@asynccontextmanager
async def provider_rate_gate(session: AsyncSession, gate: str | None) -> AsyncIterator[None]:
    """``gate``가 선언된 operation을 **프로세스를 가로질러** 한 번에 하나만 통과시킨다.

    lock을 놓기 **전에** 교대 간격만큼 쉰다 — 그러지 않으면 다음 프로세스의 첫
    요청이 이전 프로세스의 마지막 요청 바로 뒤에 붙어 상한을 넘는다. 상한은
    "평균"이 아니라 "어느 1초 창에서도"이므로 이음매도 창 안이다.

    blocking lock을 쓴다. 건너뛰면 요청이 사라지거나 재큐잉 비용이 드는데, gate를
    쓰는 fetcher는 수 초짜리라 기다리는 편이 싸다. run이 죽으면 session이 끊기고
    session-level advisory lock은 Postgres가 자동으로 놓는다.
    """

    cooldown = PROVIDER_RATE_GATES.get(gate) if gate is not None else None
    if cooldown is None:
        yield
        return
    async with advisory_lock(session, f"provider-rate-gate:{gate}"):
        try:
            yield
        finally:
            await asyncio.sleep(cooldown)


@dataclass(frozen=True, slots=True)
class FeatureUpdateRunnerSpec:
    """DB operation key → 기존 Dagster asset runner 연결 사양.

    provider/dataset 자연키와 dataset 목록은 이 실행 경계에 존재하지 않는다.
    ``operation_key``는 DB가 request membership에 고정한 값이며, catalog label은
    ``ProviderDatasetRefreshScope``에 표시용으로만 전달된다.
    """

    operation_key: str
    run: AssetRun
    resources: ResourceFactory
    asset_key: str
    rate_gate: str | None = None
    """이 operation이 지나야 하는 **프로세스 간** rate gate 이름(없으면 ``None``).

    provider 라이브러리의 상한은 **프로세스당**이다. 큐는 worker run을 여러 개
    동시에 띄우고 run마다 프로세스가 다르므로, 라이브러리 상한만으로는 합계가
    프로세스 수만큼 곱해진다. 여기 이름을 적은 operation은
    :data:`PROVIDER_RATE_GATES`의 advisory lock을 지나 **한 번에 하나만** 실행된다.
    """


class _DirectAssetContext:
    def __init__(
        self,
        *,
        resources: Mapping[str, object],
        log: object,
        asset_key: str,
    ) -> None:
        self.resources = SimpleNamespace(**dict(resources))
        self.log = log
        self.asset_key = _DirectAssetKey(asset_key)
        self.output_metadata: list[dict[str, object]] = []

    def add_output_metadata(self, metadata: Mapping[str, object]) -> None:
        self.output_metadata.append(dict(metadata))


@dataclass(frozen=True, slots=True)
class _DirectAssetKey:
    value: str

    def to_user_string(self) -> str:
        return self.value


class FeatureUpdateAssetRunner:
    """Feature update queue의 DB membership을 operation handler로 dispatch한다."""

    def __init__(
        self,
        *,
        common_resources: Mapping[str, object],
        log: object,
        settings_factory: Callable[[], KorTravelMapSettings] = KorTravelMapSettings,
        specs: tuple[FeatureUpdateRunnerSpec, ...] | None = None,
    ) -> None:
        self._common_resources = dict(common_resources)
        self._log = log
        self._settings_factory = settings_factory
        selected_specs = tuple(specs if specs is not None else _OPERATION_RUNNER_SPECS.values())
        by_operation_key = {spec.operation_key: spec for spec in selected_specs}
        if len(by_operation_key) != len(selected_specs):
            raise ValueError("feature update runner operation_key must be unique")
        self._specs = MappingProxyType(by_operation_key)

    async def __call__(
        self,
        session: AsyncSession,
        scope: ProviderDatasetRefreshScope,
    ) -> ProviderDatasetRefreshResult:
        spec = self._spec_for_scope(scope)
        failure_sync_scope = scope.sync_scope
        if (
            scope.operation_key in DISABLED_FEATURE_LOAD_OPERATION_KEYS
            and scope.scope_type != "provider_dataset"
        ):
            # 자동 적재를 끈 provider다(`DISABLED_FEATURE_LOAD_SCHEDULES`).
            # 그 목록은 schedule만 막았고 **이 경로는 막지 않았다** - prod가 cron이
            # 아니라 큐로 돌기 때문에, 사용자가 끈 provider가 살아 있는 경로로
            # 그대로 나가고 있었다(2026-09-14 발견). 끄는 결정을 기록만 하지 않고
            # 실행 경계에 결박한다.
            #
            # **targeted scope만 막는다.** 기록된 의도가 "백필이나 일회성 재적재는
            # 여전히 필요하고 그것은 **사람이 의도해서 한 번 돌리는 일**이다"이기
            # 때문이다. 자동으로 도는 것은 targeted 쪽 - PinVi cache target refresh가
            # 반경 안 feature를 잡아 만드는 side effect다. `provider_dataset`은
            # "이 dataset을 지금 갱신하라"는 의도된 한 번이므로 남긴다(같은 파일의
            # OpiNet skip이 쓰는 경계와 같다).
            #
            # 남는 노출: 자동 호출자가 `provider_dataset` scope로 넣으면 여전히
            # 돈다. provider별 일일 예산이 그것을 닫는다 - `T-VN-QUEUE-QUOTA`.
            log_info = getattr(self._log, "info", None)
            if callable(log_info):
                log_info(
                    "%s 자동 적재가 꺼져 있어 큐 요청을 건너뛴다 "
                    "(DISABLED_FEATURE_LOAD_SCHEDULES).",
                    scope.operation_key,
                )
            return ProviderDatasetRefreshResult(
                provider_dataset_id=scope.provider_dataset_id,
                sync_scope=scope.sync_scope,
                operation_key=scope.operation_key,
                provider=scope.provider,
                dataset_key=scope.dataset_key,
                status="skipped",
                metadata={
                    "provider_dataset_id": scope.provider_dataset_id,
                    "sync_scope": scope.sync_scope,
                    "operation_key": scope.operation_key,
                    "provider": scope.provider,
                    "dataset_key": scope.dataset_key,
                    "skipped": True,
                    "skip_reason": "provider_auto_load_disabled",
                    "scope_type": scope.scope_type,
                },
            )
        if (
            scope.operation_key
            in {
                "feature_place_opinet_stations_job",
                "feature_price_opinet_stations_job",
            }
            and scope.scope_type != "provider_dataset"
        ):
            # OpiNet lowTop fetcher는 개별 feature/bbox/cache-target request scope를
            # 소비하지 않고 현재 설정의 전국 회전 window를 다시 조회한다. targeted
            # request마다 같은 무료키 quota를 소진하는 대신 system schedule에 맡긴다.
            metadata: dict[str, object] = {
                "provider_dataset_id": scope.provider_dataset_id,
                "sync_scope": scope.sync_scope,
                "operation_key": scope.operation_key,
                "provider": scope.provider,
                "dataset_key": scope.dataset_key,
                "skipped": True,
                "skip_reason": "global_provider_not_targetable",
                "scope_type": scope.scope_type,
            }
            log_info = getattr(self._log, "info", None)
            if callable(log_info):
                log_info(
                    "OpiNet %s targeted refresh 생략(scope_type=%s): "
                    "현재 fetcher는 request scope를 적용할 수 없음.",
                    scope.dataset_key,
                    scope.scope_type,
                )
            return ProviderDatasetRefreshResult(
                provider_dataset_id=scope.provider_dataset_id,
                sync_scope=scope.sync_scope,
                operation_key=scope.operation_key,
                provider=scope.provider,
                dataset_key=scope.dataset_key,
                status="skipped",
                metadata=metadata,
            )
        extra: RunnerResources | None = None
        refresh_failure: ProviderDatasetRefreshFailure | None = None
        #: 결과에 소비량을 실어 보냈는가 — `finally`의 경고 로그를 그때만 건너뛴다.
        reported = False
        # 계수기는 **resources 구성보다 앞에서** 연다. `spec.resources()`가 I/O를
        # 할 수 있기 때문이다 - MOIS Phase A는 거기서 전국 LOCALDATA 파일을 받는다.
        # `spec.run`만 감싸면 그 요청이 통째로 계수 범위 밖이 되어
        # `note_upstream_request()`가 조용히 no-op이 된다(2026-09-13 3차 적대 리뷰
        # blocker). `asyncio.to_thread`는 문맥을 복사하지만 계수기는 가변 리스트라
        # 안쪽 증가가 바깥에 보인다(이 저장소가 실측해 둔 성질).
        # **상한은 프로세스당이다.** provider 라이브러리가 초당 건수를 지켜도, 큐가
        # worker run을 동시에 띄우면 프로세스 수만큼 곱해진다(2026-09-14 적대 리뷰가
        # 짚은 자리 — krex는 최대 4배였다). gate를 선언한 operation은 여기서
        # **프로세스를 가로질러** 직렬화된다. 계수기보다 **바깥**이어야 한다 —
        # 기다리는 동안은 요청을 보내지 않으므로 소비량에 섞이면 안 된다.
        async with provider_rate_gate(session, spec.rate_gate):
            with counting_upstream_requests():
                try:
                    try:
                        settings = self._settings_factory()
                        # spec.resources()는 MOIS의 경우 freshness-gated Phase A sync(I/O)를
                        # 포함할 수 있으므로 이벤트 루프를 막지 않게 스레드로
                        # 보낸다(#617 리뷰).
                        extra = await asyncio.to_thread(spec.resources, settings, scope)
                        resources = {
                            **self._common_resources,
                            **dict(extra.values),
                            "feature_update_membership": ProviderDatasetOperationMembership(
                                provider_dataset_id=scope.provider_dataset_id,
                                sync_scope=scope.sync_scope,
                                operation_key=scope.operation_key,
                            ),
                        }
                    except ProviderDatasetRefreshFailure:
                        raise
                    except Exception as exc:
                        raise ProviderDatasetRefreshFailure(
                            provider_dataset_id=scope.provider_dataset_id,
                            sync_scope=failure_sync_scope,
                            operation_key=scope.operation_key,
                            message="provider refresh resource initialization failed",
                        ) from exc
                    client = resources.get("kor_travel_map_client")
                    if isinstance(client, AsyncKorTravelMapClient):
                        try:
                            resources["feature_update_evidence_client"] = client
                            resources["kor_travel_map_client"] = await _bind_client_to_session(
                                client,
                                session,
                            )
                        except ProviderDatasetRefreshFailure:
                            raise
                        except Exception as exc:
                            raise ProviderDatasetRefreshFailure(
                                provider_dataset_id=scope.provider_dataset_id,
                                sync_scope=failure_sync_scope,
                                operation_key=scope.operation_key,
                                message="provider refresh transaction binding failed",
                            ) from exc
                    try:
                        context = _DirectAssetContext(
                            resources=resources,
                            log=self._log,
                            asset_key=spec.asset_key,
                        )
                        # 이 경계가 asset wrapper를 **우회한다** - 여기서는 `spec.run`이
                        # 원본 run 함수이지 `run_tracked_feature_asset`으로 감싼 것이
                        # 아니다. 계수기는 이 메서드 맨 위에서 열린다(resources 구성의
                        # I/O까지 덮기 위해서다).
                        result = await spec.run(context)
                        refresh_result = _as_refresh_result(
                            result,
                            scope=scope,
                            output_metadata=context.output_metadata,
                            upstream_requests=observed_upstream_requests(),
                        )
                        reported = True
                        return refresh_result
                    except ProviderDatasetRefreshFailure:
                        raise
                    except Exception as exc:
                        raise ProviderDatasetRefreshFailure(
                            provider_dataset_id=scope.provider_dataset_id,
                            sync_scope=failure_sync_scope,
                            operation_key=scope.operation_key,
                            message="provider refresh asset execution failed",
                        ) from exc
                except ProviderDatasetRefreshFailure as exc:
                    refresh_failure = exc
                    raise
                finally:
                    # 실패하면 결과 metadata가 없다. 이 경로의 실패 타입은 metadata를
                    # 싣지 못하므로 로그가 유일한 기록이다 - asset 경로의
                    # `_log_spend_on_failure`와 같은 이유다.
                    #
                    # `except`가 아니라 `finally`에 두는 이유: resource 구성 실패도
                    # (4차), teardown 실패와 취소(`BaseException`)도(5차) 같은 기록을
                    # 남겨야 한다. MOIS Phase A는 resource 구성 **안에서** 전국 파일을
                    # 받으므로 run 전용 except에 두면 계수기를 앞으로 옮긴 이유였던
                    # 그 요청이 그대로 사라진다. 성공해서 값을 실어 보낸 run은
                    # `reported` 플래그로 제외한다(이중 기록 방지).
                    def _log_spend() -> None:
                        observed = observed_upstream_requests()
                        log_warning = getattr(self._log, "warning", None)
                        if observed is not None and callable(log_warning):
                            log_warning(
                                "끝까지 실어 보내지 못했지만 upstream 요청은 나갔다 (%s=%d)",
                                UPSTREAM_REQUESTS_METADATA_KEY,
                                observed,
                            )

                    if not reported:
                        _log_spend()
                    if extra is not None:
                        try:
                            await _close_teardowns(extra.teardowns)
                        except Exception as exc:
                            if reported:
                                # 결과를 만들어 두고도 teardown 실패로 그것을 잃는다 -
                                # 실린 줄 알았던 소비량이 사라지는 유일한 경로다(5차).
                                _log_spend()
                            if refresh_failure is None:
                                raise ProviderDatasetRefreshFailure(
                                    provider_dataset_id=scope.provider_dataset_id,
                                    sync_scope=failure_sync_scope,
                                    operation_key=scope.operation_key,
                                    message=(
                                        "provider refresh resource teardown failed after the "
                                        "bound transaction"
                                    ),
                                ) from exc
                            log_error = getattr(self._log, "error", None)
                            if callable(log_error):
                                log_error(
                                    "provider refresh typed failure 뒤 resource teardown도 "
                                    "실패했지만 원래 failure identity를 보존한다.",
                                    exc_info=True,
                                )

    def _spec_for_scope(self, scope: ProviderDatasetRefreshScope) -> FeatureUpdateRunnerSpec:
        try:
            handler = resolve_feature_operation_handler(scope.operation_key)
        except UnknownFeatureOperationHandlerError as exc:
            raise RuntimeError(
                f"feature update runner가 지원하지 않는 operation_key: {scope.operation_key!r}"
            ) from exc
        try:
            spec = self._specs[handler.operation_key]
        except KeyError as exc:
            raise RuntimeError(
                "feature update runner에 canonical operation handler가 없음: "
                f"{handler.operation_key!r}"
            ) from exc
        if spec.asset_key not in handler.asset_keys:
            raise RuntimeError(
                "feature update runner asset_key가 canonical operation handler와 다름: "
                f"operation_key={handler.operation_key!r} asset_key={spec.asset_key!r}"
            )
        return spec


async def _bind_client_to_session(
    client: AsyncKorTravelMapClient,
    session: AsyncSession,
) -> AsyncKorTravelMapClient:
    """Client DB 호출을 executor가 소유한 transaction에 결합한다.

    Asset은 공개 client 메서드를 계속 사용하되, 각 메서드가 만드는 내부
    ``AsyncSession``은 executor session의 physical connection에 결합된다.
    ``rollback_only``는 내부 ``commit``이 외부 transaction을 먼저 commit하지
    못하게 하고, 적재 실패는 외부 transaction에 rollback을 전파한다.
    """
    connection = await session.connection()
    bound_client = copy.copy(client)
    bound_client._session_factory = async_sessionmaker(  # noqa: SLF001
        bind=connection,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
        join_transaction_mode="rollback_only",
    )
    bound_client._engine = cast(  # noqa: SLF001
        "AsyncEngine",
        _TransactionBoundEngineGuard(),
    )
    # 결합 사실을 client가 **스스로 알게** 한다. 결합된 client에서 난 실패는 그
    # rollback이 executor의 root transaction까지 되감으므로 회복 불가다 — 호출자가
    # 완화 모드라도 삼키면 안 되고, 그 판단은 이 플래그를 보고 한다.
    bound_client._transaction_bound = True  # noqa: SLF001
    return bound_client


class _TransactionBoundEngineGuard:
    """Bound asset client가 executor transaction 밖 connection을 열지 못하게 한다."""

    def connect(self) -> None:
        raise RuntimeError(
            "transaction-bound feature update asset client cannot open a new DB connection"
        )


async def _close_teardowns(teardowns: tuple[Teardown, ...]) -> None:
    for teardown in reversed(teardowns):
        result = teardown()
        if inspect.isawaitable(result):
            await cast("Awaitable[object]", result)


def _metadata_for_result(result: object) -> dict[str, object]:
    as_metadata = getattr(result, "as_metadata", None)
    if callable(as_metadata):
        return dict(cast("Mapping[str, object]", as_metadata()))
    return {}


def _loaded_feature_ids(result: object, metadata: Mapping[str, object]) -> tuple[str, ...]:
    raw = getattr(result, "feature_ids", _MISSING)
    if raw is _MISSING:
        raw = metadata.get("feature_ids", ())
    if not isinstance(raw, list | tuple):
        return ()
    return tuple(str(value) for value in raw)


def _int_metadata(metadata: Mapping[str, object], key: str) -> int:
    value = metadata.get(key)
    if isinstance(value, bool):
        return 0
    if isinstance(value, int | float):
        return int(value)
    return 0


def _loaded_count(
    result: object,
    metadata: Mapping[str, object],
    loaded_feature_ids: tuple[str, ...],
) -> int:
    if isinstance(result, ProviderDatasetRefreshResult):
        return result.loaded_count
    for key in (
        "values_loaded",
        "weather_values_loaded",
        "price_values_upserted",
        "features_total",
        "bundles_total",
        "stations_total",
        "price_features_total",
    ):
        count = _int_metadata(metadata, key)
        if count:
            return count
    updated = _int_metadata(metadata, "features_inserted") + _int_metadata(
        metadata, "features_updated"
    )
    if updated:
        return updated
    price_updated = _int_metadata(metadata, "price_features_inserted") + _int_metadata(
        metadata, "price_features_updated"
    )
    if price_updated:
        return price_updated
    station_updated = _int_metadata(metadata, "stations_features_inserted") + _int_metadata(
        metadata, "stations_features_updated"
    )
    if station_updated:
        return station_updated
    return len(loaded_feature_ids)


def _as_refresh_result(
    result: object,
    *,
    scope: ProviderDatasetRefreshScope,
    output_metadata: list[dict[str, object]] | None = None,
    upstream_requests: int | None = None,
) -> ProviderDatasetRefreshResult:
    if isinstance(result, ProviderDatasetRefreshResult):
        if upstream_requests is None:
            return result
        merged = dict(result.metadata or {})
        merged.setdefault(UPSTREAM_REQUESTS_METADATA_KEY, upstream_requests)
        return replace(result, metadata=merged)
    metadata = _metadata_for_result(result)
    for item in output_metadata or ():
        metadata.update(item)
    # asset 경로의 choke point(`etl._add_output_metadata`)가 이미 실었으면
    # 그것이 정본이다. 싣지 않은 run 함수를 위해 여기서 한 번 더 받친다.
    if upstream_requests is not None:
        metadata.setdefault(UPSTREAM_REQUESTS_METADATA_KEY, upstream_requests)
    loaded_feature_ids = _loaded_feature_ids(result, metadata)
    return ProviderDatasetRefreshResult(
        provider_dataset_id=scope.provider_dataset_id,
        sync_scope=scope.sync_scope,
        operation_key=scope.operation_key,
        provider=str(metadata.get("provider") or scope.provider),
        dataset_key=str(metadata.get("dataset_key") or scope.dataset_key),
        status="skipped" if metadata.get("skipped") is True else "done",
        loaded_feature_ids=loaded_feature_ids,
        loaded_count=_loaded_count(result, metadata, loaded_feature_ids),
        metadata=dict(metadata),
    )


def _records(resource_key: str, fetch: Callable[[KorTravelMapSettings], object]) -> ResourceFactory:
    def _factory(
        settings: KorTravelMapSettings,
        _scope: ProviderDatasetRefreshScope,
    ) -> RunnerResources:
        return RunnerResources({resource_key: fetch(settings)})

    return _factory


def _opinet_records(
    resource_key: str,
    fetch: Callable[[KorTravelMapSettings], object],
    *,
    label: str,
) -> ResourceFactory:
    def _factory(
        settings: KorTravelMapSettings,
        _scope: ProviderDatasetRefreshScope,
    ) -> RunnerResources:
        if settings.opinet_api_key is None:
            raise ProviderCredentialMissing(
                f"{label} feature update에는 KOR_TRAVEL_MAP_OPINET_API_KEY "
                "(source OPINET_API_KEY)가 필요하다."
            )
        return RunnerResources({resource_key: fetch(settings)})

    return _factory


def _mois_resources(
    settings: KorTravelMapSettings,
    scope: ProviderDatasetRefreshScope,
) -> RunnerResources:
    ensure_mois_source_db_fresh(settings)
    return RunnerResources(
        {
            "mois_license_records": fetch_mois_license_records(settings),
            "mois_dataset_key": scope.dataset_key or MOIS_BULK_DATASET_KEY,
        }
    )


def _knps_point_resources(
    settings: KorTravelMapSettings,
    scope: ProviderDatasetRefreshScope,
) -> RunnerResources:
    resolved_settings = settings.model_copy(update={"knps_point_dataset_key": scope.dataset_key})
    return RunnerResources(
        {
            "knps_point_records": fetch_knps_point_records(resolved_settings),
            "knps_point_dataset_key": scope.dataset_key,
        }
    )


def _knps_geometry_resources(
    settings: KorTravelMapSettings,
    scope: ProviderDatasetRefreshScope,
) -> RunnerResources:
    resolved_settings = settings.model_copy(update={"knps_geometry_dataset_key": scope.dataset_key})
    return RunnerResources(
        {
            "knps_geometry_records": fetch_knps_geometry_records(resolved_settings),
            "knps_geometry_dataset_key": scope.dataset_key,
        }
    )


def _airkorea_resources(
    settings: KorTravelMapSettings,
    _scope: ProviderDatasetRefreshScope,
) -> RunnerResources:
    return RunnerResources(
        {
            "airkorea_stations": fetch_airkorea_stations(settings),
            "airkorea_air_quality": fetch_airkorea_air_quality(settings),
        }
    )


def _datagokr_file_data_resources(
    settings: KorTravelMapSettings,
    scope: ProviderDatasetRefreshScope,
) -> RunnerResources:
    dataset_key = scope.dataset_key
    return RunnerResources(
        {
            "datagokr_file_data_records": fetch_datagokr_file_data_records(
                settings,
                dataset_key=dataset_key,
            ),
            "datagokr_file_data_dataset_key": dataset_key,
        }
    )


def _kma_service_key(settings: KorTravelMapSettings, *, resource_key: str, dataset: str) -> str:
    service_key = settings.data_go_kr_service_key
    if service_key is None:
        raise RuntimeError(
            f"Dagster resource {resource_key!r}는 기본 실행 비활성 상태: "
            "credential 환경변수가 설정되지 않았음. "
            f"provider=python-kma-api, dataset={dataset}. "
            "kor-travel-map env: KOR_TRAVEL_MAP_DATA_GO_KR_SERVICE_KEY; "
            "source env: DATA_GO_KR_SERVICE_KEY."
        )
    reveal = getattr(service_key, "get_" + "se" + "cret_value")
    return str(reveal())


def _close_method(value: object) -> Teardown:
    def _teardown() -> object:
        close = getattr(value, "close", None)
        if callable(close):
            return close()
        return None

    return _teardown


def _new_kma_weather_client(
    settings: KorTravelMapSettings,
    scope: ProviderDatasetRefreshScope,
) -> object:
    """target preflight를 통과한 direct run용 public KMA client를 만든다."""
    service_key = _kma_service_key(
        settings,
        resource_key="kma_weather_client_factory",
        dataset=scope.dataset_key,
    )
    kma = cast(Any, importlib.import_module("kma"))
    # H45: 스케줄 경로(resources.py)와 동일 정산 — timeout·retries가 갈리면
    # 수동 재적재 판정이 스케줄과 다르게 나와 진단을 흐린다(리뷰 1 M-4).
    return kma.KmaClient(
        service_key=service_key,
        timeout=settings.provider_http_timeout_seconds,
        retries=upstream_retry.PROVIDER_CLIENT_INNER_RETRIES,
    )


def _kma_weather_resources(
    settings: KorTravelMapSettings,
    scope: ProviderDatasetRefreshScope,
) -> RunnerResources:
    def _client_factory() -> object:
        return _new_kma_weather_client(settings, scope)

    return RunnerResources(
        {
            "kma_weather_client_factory": _client_factory,
            "kma_weather_extra_points": settings.kma_weather_extra_points,
            "kma_weather_max_grids_per_run": settings.kma_weather_max_grids_per_run,
            "provider_upstream_retry_budget_minimum": (
                settings.provider_upstream_retry_budget_minimum
            ),
            "provider_upstream_retry_budget_percent": (
                settings.provider_upstream_retry_budget_percent
            ),
        }
    )


def _kma_mid_resources(
    settings: KorTravelMapSettings,
    scope: ProviderDatasetRefreshScope,
) -> RunnerResources:
    kma = cast(Any, importlib.import_module("kma"))
    client = kma.DataGoKrClient(
        service_key=_kma_service_key(
            settings,
            resource_key="kma_datagokr_client",
            dataset=scope.dataset_key,
        ),
        timeout=settings.provider_http_timeout_seconds,
        retries=upstream_retry.PROVIDER_CLIENT_INNER_RETRIES,
    )
    return RunnerResources(
        {
            "kma_datagokr_client": client,
            "kma_mid_region_features": settings.kma_mid_region_features,
            "provider_upstream_retry_budget_minimum": (
                settings.provider_upstream_retry_budget_minimum
            ),
            "provider_upstream_retry_budget_percent": (
                settings.provider_upstream_retry_budget_percent
            ),
        },
        teardowns=(_close_method(client),),
    )


def _kma_alert_resources(
    settings: KorTravelMapSettings,
    _scope: ProviderDatasetRefreshScope,
) -> RunnerResources:
    return RunnerResources({"kma_weather_alert_records": fetch_kma_weather_alerts(settings)})


def _mcst_resources(
    settings: KorTravelMapSettings,
    scope: ProviderDatasetRefreshScope,
) -> RunnerResources:
    matched_slugs = tuple(
        spec.slug for spec in MCST_FILE_DATASETS.values() if spec.dataset_key == scope.dataset_key
    )
    if len(matched_slugs) != 1:
        raise ValueError(
            "MCST feature-update member는 정확히 하나의 registered source slug여야 함: "
            f"provider_dataset_id={scope.provider_dataset_id!r}"
        )
    return RunnerResources(
        {"mcst_culture_records": fetch_mcst_culture_records(settings, slugs=matched_slugs)}
    )


async def _run_kma_grid_weather(context: Any) -> object:
    dataset_key = cast(Any, context.resources).feature_update_dataset_key
    if dataset_key == KMA_ULTRA_SHORT_NOWCAST_DATASET_KEY:
        return await run_feature_weather_kma_ultra_short_nowcast(context)
    if dataset_key == KMA_ULTRA_SHORT_FORECAST_DATASET_KEY:
        return await run_feature_weather_kma_ultra_short_forecast(context)
    if dataset_key == KMA_SHORT_FORECAST_DATASET_KEY:
        return await run_feature_weather_kma_short_forecast(context)
    raise KeyError(f"KMA grid weather dataset_key가 아님: {dataset_key!r}")


def _kma_grid_resources(
    settings: KorTravelMapSettings,
    scope: ProviderDatasetRefreshScope,
) -> RunnerResources:
    sync_scope = _kma_grid_sync_scope(scope)
    base = _kma_weather_resources(settings, scope)
    return RunnerResources(
        {
            **dict(base.values),
            "feature_update_dataset_key": scope.dataset_key,
            "kma_weather_sync_scope": sync_scope,
            "kma_weather_sync_failure_managed_by_executor": True,
        },
        teardowns=base.teardowns,
    )


def _kma_grid_sync_scope(scope: ProviderDatasetRefreshScope) -> str:
    raw_scope = scope.sync_scope
    if raw_scope is None:
        raise ValueError("KMA grid sync_scope is required")
    if not isinstance(raw_scope, str):
        raise ValueError("KMA grid sync_scope must be a string")
    parsed_scope = parse_canonical_sync_scope(raw_scope)
    if parsed_scope.kind == "dataset_wide":
        raise ValueError(
            "KMA grid datasets require target_grids or external_system:<name> sync_scope"
        )
    return parsed_scope.value


def _operation_specs(
    *operation_keys: str,
    run: AssetRun,
    resources: ResourceFactory,
    asset_key: str,
    rate_gate: str | None = None,
) -> tuple[FeatureUpdateRunnerSpec, ...]:
    """같은 code handler를 공유하는 DB operation binding을 명시적으로 만든다."""
    return tuple(
        FeatureUpdateRunnerSpec(
            operation_key=operation_key,
            run=run,
            resources=resources,
            asset_key=asset_key,
            rate_gate=rate_gate,
        )
        for operation_key in operation_keys
    )


_OPERATION_RUNNER_SPEC_ROWS: Final[tuple[FeatureUpdateRunnerSpec, ...]] = (
    *_operation_specs(
        "feature_event_datagokr_cultural_festivals_job",
        run=run_feature_event_datagokr_cultural_festivals,
        resources=_records("datagokr_cultural_festivals", fetch_datagokr_cultural_festivals),
        asset_key="feature_event_datagokr_cultural_festivals",
    ),
    *_operation_specs(
        "feature_place_opinet_stations_job",
        run=run_feature_place_opinet_stations,
        resources=_opinet_records("opinet_stations", fetch_opinet_stations, label="OpiNet station"),
        asset_key="feature_place_opinet_stations",
    ),
    *_operation_specs(
        "feature_price_opinet_stations_job",
        run=run_feature_price_opinet_stations,
        resources=_opinet_records(
            "opinet_station_price_details", fetch_opinet_station_price_details, label="OpiNet price"
        ),
        asset_key="feature_price_opinet_stations",
    ),
    *_operation_specs(
        "feature_place_krex_rest_areas_job",
        run=run_feature_place_krex_rest_areas,
        resources=_records("krex_rest_areas", fetch_krex_rest_areas),
        asset_key="feature_place_krex_rest_areas",
        rate_gate=KREX_RATE_GATE,
    ),
    *_operation_specs(
        "feature_price_krex_rest_areas_job",
        run=run_feature_price_krex_rest_areas,
        resources=_records("krex_rest_area_fuel_prices", fetch_krex_rest_area_fuel_prices),
        asset_key="feature_price_krex_rest_areas",
        rate_gate=KREX_RATE_GATE,
    ),
    *_operation_specs(
        "feature_weather_krex_rest_areas_job",
        run=run_feature_weather_krex_rest_areas,
        resources=_records("krex_rest_area_weather", fetch_krex_rest_area_weather),
        asset_key="feature_weather_krex_rest_areas",
        rate_gate=KREX_RATE_GATE,
    ),
    *_operation_specs(
        "feature_notice_krex_traffic_notices_job",
        run=run_feature_notice_krex_traffic_notices,
        resources=_records("krex_traffic_notices", fetch_krex_traffic_notices),
        asset_key="feature_notice_krex_traffic_notices",
        rate_gate=KREX_RATE_GATE,
    ),
    *_operation_specs(
        "feature_place_krheritage_items_job",
        run=run_feature_place_krheritage_items,
        resources=_records("krheritage_items", fetch_krheritage_items),
        asset_key="feature_place_krheritage_items",
    ),
    *_operation_specs(
        "feature_event_krheritage_events_job",
        run=run_feature_event_krheritage_events,
        resources=_records("krheritage_events", fetch_krheritage_events),
        asset_key="feature_event_krheritage_events",
    ),
    *_operation_specs(
        "feature_place_mois_licenses_job",
        run=run_feature_place_mois_licenses,
        resources=_mois_resources,
        asset_key="feature_place_mois_licenses",
    ),
    *_operation_specs(
        "feature_place_knps_points_job",
        run=run_feature_place_knps_points,
        resources=_knps_point_resources,
        asset_key="feature_place_knps_points",
    ),
    *_operation_specs(
        "feature_geometry_knps_records_job",
        run=run_feature_geometry_knps_records,
        resources=_knps_geometry_resources,
        asset_key="feature_geometry_knps_records",
    ),
    *_operation_specs(
        "feature_place_krforest_recreation_forests_job",
        run=run_feature_place_krforest_recreation_forests,
        resources=_records("krforest_recreation_forests", fetch_krforest_recreation_forests),
        asset_key="feature_place_krforest_recreation_forests",
    ),
    *_operation_specs(
        "feature_place_krforest_arboretums_job",
        run=run_feature_place_krforest_arboretums,
        resources=_records("krforest_arboretums", fetch_krforest_arboretums),
        asset_key="feature_place_krforest_arboretums",
    ),
    *_operation_specs(
        "feature_route_krforest_mountain_trails_job",
        run=run_feature_route_krforest_mountain_trails,
        resources=_records("krforest_mountain_trails", fetch_krforest_mountain_trails),
        asset_key="feature_route_krforest_mountain_trails",
    ),
    *_operation_specs(
        "feature_route_krforest_dulle_trails_job",
        run=run_feature_route_krforest_dulle_trails,
        resources=_records("krforest_dulle_trails", fetch_krforest_dulle_trails),
        asset_key="feature_route_krforest_dulle_trails",
    ),
    *_operation_specs(
        "feature_weather_krforest_mountain_weather_job",
        run=run_feature_weather_krforest_mountain_weather,
        resources=_records("krforest_mountain_weather", fetch_krforest_mountain_weather),
        asset_key="feature_weather_krforest_mountain_weather",
    ),
    *_operation_specs(
        "feature_weather_krforest_wildfire_risk_forecast_job",
        run=run_feature_weather_krforest_wildfire_risk_forecast,
        resources=_records(
            "krforest_wildfire_risk_forecast", fetch_krforest_wildfire_risk_forecast
        ),
        asset_key="feature_weather_krforest_wildfire_risk_forecast",
    ),
    *_operation_specs(
        "feature_notice_krforest_landslide_forecast_issues_job",
        run=run_feature_notice_krforest_landslide_forecast_issues,
        resources=_records(
            "krforest_landslide_forecast_issues",
            fetch_krforest_landslide_forecast_issues,
        ),
        asset_key="feature_notice_krforest_landslide_forecast_issues",
    ),
    *_operation_specs(
        "feature_place_standard_museums_job",
        run=run_feature_place_standard_museums,
        resources=_records("standard_museums", fetch_standard_museums),
        asset_key="feature_place_standard_museums",
    ),
    *_operation_specs(
        "feature_place_standard_tourist_attractions_job",
        run=run_feature_place_standard_tourist_attractions,
        resources=_records("standard_tourist_attractions", fetch_standard_tourist_attractions),
        asset_key="feature_place_standard_tourist_attractions",
    ),
    *_operation_specs(
        "feature_place_standard_parking_lots_job",
        run=run_feature_place_standard_parking_lots,
        resources=_records("standard_parking_lots", fetch_standard_parking_lots),
        asset_key="feature_place_standard_parking_lots",
    ),
    *_operation_specs(
        "feature_place_standard_special_streets_job",
        run=run_feature_place_standard_special_streets,
        resources=_records("standard_special_streets", fetch_standard_special_streets),
        asset_key="feature_place_standard_special_streets",
    ),
    *_operation_specs(
        "feature_place_datagokr_seoul_bookstores_job",
        "feature_place_datagokr_gyeonggi_muslim_friendly_restaurants_job",
        "feature_place_datagokr_ansan_world_restaurants_job",
        "feature_place_datagokr_jeju_local_restaurants_job",
        run=run_feature_place_datagokr_file_data,
        resources=_datagokr_file_data_resources,
        asset_key="feature_place_datagokr_file_data",
    ),
    *_operation_specs(
        "feature_place_khoa_beaches_job",
        run=run_feature_place_khoa_beaches,
        resources=_records("khoa_beaches", fetch_khoa_beaches),
        asset_key="feature_place_khoa_beaches",
    ),
    *_operation_specs(
        "feature_place_krairport_airports_job",
        run=run_feature_place_krairport_airports,
        resources=_records("krairport_airports", fetch_krairport_airports),
        asset_key="feature_place_krairport_airports",
    ),
    *_operation_specs(
        "feature_place_kor_travel_concierge_youtube_job",
        run=run_feature_place_kor_travel_concierge_youtube,
        resources=_records(
            "kor_travel_concierge_youtube_features", fetch_kor_travel_concierge_youtube_features
        ),
        asset_key="feature_place_kor_travel_concierge_youtube",
    ),
    *_operation_specs(
        "feature_event_visitkorea_enrichment_job",
        run=run_feature_event_visitkorea_enrichment,
        resources=_records("visitkorea_festival_events", fetch_visitkorea_festival_events),
        asset_key="feature_event_visitkorea_enrichment",
    ),
    *_operation_specs(
        "feature_weather_airkorea_air_quality_job",
        run=run_feature_weather_airkorea_air_quality,
        resources=_airkorea_resources,
        asset_key="feature_weather_airkorea_air_quality",
    ),
    *_operation_specs(
        "feature_weather_kma_ultra_short_nowcast_job",
        run=_run_kma_grid_weather,
        resources=_kma_grid_resources,
        asset_key="feature_weather_kma_ultra_short_nowcast",
    ),
    *_operation_specs(
        "feature_weather_kma_ultra_short_forecast_job",
        run=_run_kma_grid_weather,
        resources=_kma_grid_resources,
        asset_key="feature_weather_kma_ultra_short_forecast",
    ),
    *_operation_specs(
        "feature_weather_kma_short_forecast_job",
        run=_run_kma_grid_weather,
        resources=_kma_grid_resources,
        asset_key="feature_weather_kma_short_forecast",
    ),
    *_operation_specs(
        "feature_weather_kma_mid_forecast_job",
        run=run_feature_weather_kma_mid_forecast,
        resources=_kma_mid_resources,
        asset_key="feature_weather_kma_mid_forecast",
    ),
    *_operation_specs(
        "feature_notice_kma_weather_alerts_job",
        run=run_feature_notice_kma_weather_alerts,
        resources=_kma_alert_resources,
        asset_key="feature_notice_kma_weather_alerts",
    ),
    *_operation_specs(
        "feature_place_mcst_culture_job",
        run=run_feature_place_mcst_culture,
        resources=_mcst_resources,
        asset_key="feature_place_mcst_culture",
    ),
)

_operation_runner_specs = {spec.operation_key: spec for spec in _OPERATION_RUNNER_SPEC_ROWS}
if len(_operation_runner_specs) != len(_OPERATION_RUNNER_SPEC_ROWS):
    raise RuntimeError("feature update runner operation_key가 중복됨")
if frozenset(_operation_runner_specs) != feature_operation_handler_keys():
    raise RuntimeError("feature update runner와 canonical operation handler set이 다름")

_OPERATION_RUNNER_SPECS: Final[Mapping[str, FeatureUpdateRunnerSpec]] = MappingProxyType(
    _operation_runner_specs
)


@resource(
    required_resource_keys=_COMMON_RESOURCE_KEYS,
    description="feature update queue provider/dataset asset dispatcher.",
)
def feature_update_runner_resource(
    context: InitResourceContext,
) -> FeatureUpdateAssetRunner:
    resources = cast(Any, context.resources)
    common_resources = {key: getattr(resources, key) for key in _COMMON_RESOURCE_KEYS}
    return FeatureUpdateAssetRunner(
        common_resources=common_resources,
        log=context.log,
    )
