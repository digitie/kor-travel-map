"""10-22 재현 — 긴 큐 적재가 도는 동안 다른 큐 요청 12건이 끝까지 가는가.

2026-10-22 prod: 큐 요청 13건(KNPS·국가유산·산림청·표준데이터·축제 provider_dataset)을 한꺼번에
넣었다. 그중 하나(산림청 등산로)가 refresh transaction을 76분 열었고, 그동안 claim한 8건이 lock
timeout으로 실패했다. 첫 대기 지점(전역 event clock 행)은 alembic 457이 없앴다. 이 시험은 **그
다음 대기 지점**이 남았는지 본다.

재현 방식.

- 긴 요청: ``knps_trails`` geometry를 **실제 asset**(``run_feature_geometry_knps_records``)으로
  적재한다. 역지오코딩(변환 단계, executor transaction 안)에서 멈춰 transaction을 연 채 다른
  요청이 다 끝날 때까지 기다린다. ADR-113 뒤 provider 적재는 받기·변환을 쓰기 전에
  끝내므로(fence는 쓰기에서 잡는다), 76분 동안 열린 transaction이 실제로 쥔 것은 이 단계의
  잠금이다.
- 다른 요청 12건: KNPS point 5·geometry 4, 국가유산 item·행사를 ``provider_dataset``으로, 축제
  dataset을 ``cache_target_keys``(PinVi 경로, ``poi_cache_targets`` 갱신 → ``dataset_projection``
  topic)로 넣고 실제 asset으로 적재한다.
- 모든 요청은 Dagster runtime LOGIN(``ktm_feature_service``)과 Dagster 엔진과 같은 ``lock_timeout``
  (여기서는 3초로 줄인다)으로 실행기 경로(``execute_feature_update_request``)를 그대로 지난다.
- 긴 요청은 runner 맨 앞에서 topic 원본(``provider_sync_state``·``data_integrity_violations``·
  ``poi_cache_targets``)을 쓴다. prod에서는 쓰기 중간의 ``record_override_geo_stale``과 꼬리의 주소
  finding·sync state가 그 자리다. 458 전에는 이 쓰기가 topic 행을 commit까지 쥐었다(#1548 리뷰).
- 멈춘 동안 긴 transaction이 쥔 전역 행(``ops_live_topic_revisions`` topic, event clock slot)과
  ``feature-curation-write`` fence를 직접 잰다. 기다리는 backend는 ``pg_stat_activity``·``pg_locks``
  표본으로 남긴다.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from collections.abc import AsyncIterator
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Final
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

import pytest
from alembic.config import Config
from kortravelmap.dagster import assets as dagster_assets
from kortravelmap.dagster.assets import (
    run_feature_event_krheritage_events,
    run_feature_event_visitkorea_festivals,
    run_feature_geometry_knps_records,
    run_feature_place_knps_points,
    run_feature_place_krheritage_items,
)
from kortravelmap.dagster.feature_update_runner import (
    FeatureUpdateAssetRunner,
    FeatureUpdateRunnerSpec,
    RunnerResources,
)
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from kortravelmap.client import AsyncKorTravelMapClient
from kortravelmap.infra import feature_repo
from kortravelmap.infra.db import make_async_engine, normalize_async_dsn
from kortravelmap.infra.feature_update_executor import ProviderDatasetRefreshScope
from kortravelmap.infra.feature_update_repo import enqueue_feature_update_request
from kortravelmap.infra.jobs_repo import ImportJobDatasetTarget
from kortravelmap.infra.poi_cache_target_repo import (
    mark_poi_cache_targets_refresh_requested,
    upsert_poi_cache_target,
)
from kortravelmap.infra.provider_refresh_policy_repo import upsert_provider_refresh_policy
from kortravelmap.providers.feature_operation_registry import (
    resolve_feature_operation_handler,
)
from kortravelmap.settings import KorTravelMapSettings
from tests.integration._application_300_bootstrap import (
    _TEST_RUNTIME_PASSWORD,
    upgrade_head_with_application_300_bootstrap,
)
from tests.integration._tourapi_festival import (
    FESTIVAL_DATASET_KEY,
    FESTIVAL_PROVIDER,
    festival_bundles,
    festival_item,
)
from tests.integration.test_dagster_feature_etl import (
    _HeritageEvent,
    _HeritageItem,
    _HeritageKey,
    _KnpsGeometry,
    _KnpsPoint,
    _ReverseGeocoder,
)

pytestmark = pytest.mark.integration

_ROOT: Final = Path(__file__).resolve().parents[2]
_KST: Final = timezone(timedelta(hours=9))
_FETCHED: Final = datetime(2026, 10, 22, 11, 43, tzinfo=_KST)
#: Dagster 엔진은 30초다. 시험은 10배 줄인다 — 기다림이 있으면 3초 뒤 55P03으로 드러난다.
_LOCK_TIMEOUT_MS: Final = "3000"
_LONG_DATASET: Final = "knps_trails"
_KNPS: Final = "python-knps-api"
_KNPS_POINTS: Final = (
    "knps_visitor_centers",
    "knps_restrooms",
    "knps_campgrounds",
    "knps_shelters",
    "knps_cultural_resources",
)
_KNPS_GEOMETRY: Final = (
    "knps_linear_facilities",
    "knps_park_boundaries",
    "knps_hazard_zones",
    "knps_protected_areas",
)
_POLYGON: Final = "POLYGON((126.98 37.65, 126.99 37.65, 126.99 37.66, 126.98 37.66, 126.98 37.65))"
_LINE: Final = "LINESTRING(126.98 37.65, 126.99 37.66, 127.0 37.67)"

_LOOKUP_MEMBERSHIP_SQL: Final = """
SELECT scope.provider_dataset_id, scope.sync_scope, scope.operation_key
FROM provider_sync.provider_dataset_operation_scopes AS scope
JOIN provider_sync.provider_datasets AS dataset
  ON dataset.provider_dataset_id = scope.provider_dataset_id
JOIN provider_sync.provider_dataset_operations AS operation
  ON operation.provider_dataset_id = scope.provider_dataset_id
 AND operation.operation_key = scope.operation_key
 AND operation.operation_kind = scope.operation_kind
WHERE dataset.provider = :provider
  AND dataset.dataset_key = :dataset_key
  AND scope.sync_scope = 'dataset_wide'
  AND scope.operation_kind = 'refresh'
  AND dataset.is_active
  AND operation.is_enabled
ORDER BY scope.operation_key
LIMIT 1
"""

#: 기다리는 backend와 그 원인 잠금의 표본.
_WAITERS_SQL: Final = """
SELECT waiting.pid,
       waiting.wait_event_type,
       waiting.wait_event,
       left(regexp_replace(waiting.query, '\\s+', ' ', 'g'), 160) AS waiting_query,
       lock.locktype,
       lock.relation::regclass::text AS relation,
       lock.classid, lock.objid, lock.objsubid,
       lock.mode,
       pg_blocking_pids(waiting.pid) AS blockers
FROM pg_stat_activity AS waiting
LEFT JOIN pg_locks AS lock ON lock.pid = waiting.pid AND NOT lock.granted
WHERE waiting.datname = current_database()
  AND waiting.wait_event_type = 'Lock'
"""


def _with_database(url: str, database: str) -> str:
    parts = urlsplit(url)
    return urlunsplit(parts._replace(path=f"/{database}"))


async def _admin_execute(url: str, statement: str) -> None:
    import asyncpg

    parts = urlsplit(url)
    connection = await asyncpg.connect(
        user=parts.username,
        password=parts.password,
        host=parts.hostname,
        port=parts.port,
        database=(parts.path or "/postgres").lstrip("/"),
    )
    try:
        await connection.execute(statement)
    finally:
        await connection.close()


@pytest.fixture(scope="module")
async def queue_db(pg_container: object) -> AsyncIterator[tuple[AsyncEngine, AsyncEngine]]:
    """이 모듈 전용 head DB. (superuser engine, Dagster runtime engine)."""

    from kortravelmap.infra.runtime_privileges import reconcile_runtime_privileges

    raw_dsn = pg_container.get_connection_url()  # type: ignore[attr-defined]
    database = f"queue_1022_{uuid4().hex}"
    await _admin_execute(raw_dsn, f'CREATE DATABASE "{database}"')
    await _admin_execute(
        _with_database(raw_dsn, database),
        f'ALTER DATABASE "{database}" SET search_path = public, x_extension',
    )
    superuser_dsn = normalize_async_dsn(_with_database(raw_dsn, database))
    config = Config(str(_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(_ROOT / "alembic"))
    superuser: AsyncEngine | None = None
    runtime: AsyncEngine | None = None
    try:
        await upgrade_head_with_application_300_bootstrap(config, superuser_dsn)
        previous = os.environ.get("KOR_TRAVEL_MAP_PG_DSN")
        os.environ["KOR_TRAVEL_MAP_PG_DSN"] = str(config.get_main_option("sqlalchemy.url"))
        try:
            await reconcile_runtime_privileges()
        finally:
            if previous is None:
                os.environ.pop("KOR_TRAVEL_MAP_PG_DSN", None)
            else:
                os.environ["KOR_TRAVEL_MAP_PG_DSN"] = previous
        superuser = make_async_engine(superuser_dsn, pool_size=4)
        runtime = make_async_engine(
            make_url(superuser_dsn)
            .set(username="ktm_feature_service", password=_TEST_RUNTIME_PASSWORD)
            .render_as_string(hide_password=False),
            pool_size=40,
            server_settings={"statement_timeout": "600000", "lock_timeout": _LOCK_TIMEOUT_MS},
        )
        yield superuser, runtime
    finally:
        if runtime is not None:
            await runtime.dispose()
        if superuser is not None:
            await superuser.dispose()
        await _admin_execute(raw_dsn, f'DROP DATABASE "{database}" WITH (FORCE)')


async def _no_tourapi_details(_settings: object, _content_ids: object) -> dict[str, Any]:
    return {}


def _records_for(scope: ProviderDatasetRefreshScope) -> dict[str, object]:
    key = scope.dataset_key
    if key in _KNPS_POINTS:
        return {
            "knps_point_dataset_key": key,
            "knps_point_records": [
                _KnpsPoint(
                    source_id=f"Q1022-{key}",
                    name=f"{key} 시설",
                    longitude=Decimal("126.9876"),
                    latitude=Decimal("37.6584"),
                    raw={"MNG_NO": f"Q1022-{key}", "CTGRY_NM": "사찰"},
                )
            ],
        }
    if key == _LONG_DATASET or key in _KNPS_GEOMETRY:
        wkt = _LINE if key in {_LONG_DATASET, "knps_linear_facilities"} else _POLYGON
        return {
            "knps_geometry_dataset_key": key,
            "knps_geometry_records": [
                _KnpsGeometry(
                    source_id=f"Q1022-{key}",
                    name=f"{key} 구역",
                    geom_wkt=wkt,
                    # 보호지역은 싣는 지정 종류여야 bundle이 나온다(0건이면 은퇴 전 실패).
                    raw=(
                        {"DESIG_ENG": "Provincial Park", "MARINE": "0"}
                        if key == "knps_protected_areas"
                        else {}
                    ),
                )
            ],
        }
    if key == "krheritage_heritage_features":
        return {
            "krheritage_items": [
                _HeritageItem(
                    key=_HeritageKey(ccba_kdcd="11", ccba_asno="Q1022", ccba_ctcd="37"),
                    name_ko="큐 재현 유산",
                    category="전통사찰",
                    longitude=Decimal("129.349"),
                    latitude=Decimal("35.795"),
                    location_text="경상북도 경주시 진현동",
                )
            ]
        }
    if key == "krheritage_event_list":
        return {
            "krheritage_events": [
                _HeritageEvent(
                    sn="Q1022-EVENT",
                    title="큐 재현 행사",
                    starts_on=date(2026, 11, 1),
                    ends_on=date(2026, 11, 2),
                    place="경주 문화마당",
                    address="경상북도 경주시 교동",
                    longitude=Decimal("129.350"),
                    latitude=Decimal("35.796"),
                )
            ]
        }
    if key == FESTIVAL_DATASET_KEY:
        return {
            "visitkorea_festivals": [
                festival_item(
                    "Q1022-FESTIVAL",
                    "큐 재현 축제",
                    starts_on=date(2026, 11, 1),
                    ends_on=date(2026, 11, 7),
                    addr1="서울특별시 중구 세종대로 110",
                    lon=126.978,
                    lat=37.5665,
                )
            ]
        }
    raise AssertionError(f"fixture 없는 dataset: {key}")


_RUNS: Final = {
    "feature_place_knps_points_job": run_feature_place_knps_points,
    "feature_geometry_knps_records_job": run_feature_geometry_knps_records,
    "feature_place_krheritage_items_job": run_feature_place_krheritage_items,
    "feature_event_krheritage_events_job": run_feature_event_krheritage_events,
}


class _HoldingGeocoder(_ReverseGeocoder):
    """긴 요청의 역지오코더 — 첫 호출에서 멈춘다(변환 단계, transaction은 열려 있다)."""

    def __init__(self) -> None:
        self.reached = asyncio.Event()
        self.release = asyncio.Event()

    async def __call__(self, coord: Any) -> Any:
        self.reached.set()
        await asyncio.wait_for(self.release.wait(), timeout=600)
        return await super().__call__(coord)


_TOPICS_FREE_SQL: Final = """
SELECT topic FROM ops.ops_live_topic_revisions ORDER BY topic FOR UPDATE SKIP LOCKED
"""


async def _held_by_others(engine: AsyncEngine) -> dict[str, object]:
    """다른 transaction이 쥔 전역 행·fence를 잰다(잡아 보고 되돌린다)."""

    async with AsyncSession(engine) as probe:
        await probe.begin()
        all_topics = set(
            (await probe.execute(text("SELECT topic FROM ops.ops_live_topic_revisions")))
            .scalars()
            .all()
        )
        free_topics = set((await probe.execute(text(_TOPICS_FREE_SQL))).scalars().all())
        slots_total = int(
            (
                await probe.execute(text("SELECT count(*) FROM ops.import_job_event_clock_slots"))
            ).scalar_one()
        )
        slots_free = len(
            (
                await probe.execute(
                    text(
                        "SELECT slot_id FROM ops.import_job_event_clock_slots "
                        "FOR UPDATE SKIP LOCKED"
                    )
                )
            )
            .scalars()
            .all()
        )
        fence_free = bool(
            (
                await probe.execute(
                    text(
                        "SELECT pg_try_advisory_xact_lock("
                        "hashtextextended('feature-curation-write', 0))"
                    )
                )
            ).scalar_one()
        )
        await probe.rollback()
    return {
        "topics_held": sorted(all_topics - free_topics),
        "slots_held": slots_total - slots_free,
        "fence_held": not fence_free,
    }


def _runner(
    client: AsyncKorTravelMapClient,
    operation_keys: set[str],
    geocoder: _ReverseGeocoder | None = None,
) -> FeatureUpdateAssetRunner:
    def resources(
        _settings: KorTravelMapSettings, scope: ProviderDatasetRefreshScope
    ) -> RunnerResources:
        return RunnerResources(_records_for(scope))

    specs = []
    for operation_key in sorted(operation_keys):
        handler = resolve_feature_operation_handler(operation_key)
        run = _RUNS.get(operation_key, run_feature_event_visitkorea_festivals)
        specs.append(
            FeatureUpdateRunnerSpec(
                operation_key=operation_key,
                run=run,
                resources=resources,
                asset_key=next(iter(handler.asset_keys)),
            )
        )
    return FeatureUpdateAssetRunner(
        common_resources={
            "kor_travel_map_client": client,
            "reverse_geocoder": geocoder or _ReverseGeocoder(),
            "fetched_at": _FETCHED,
            "strict_address": "off",
        },
        log=logging.getLogger(__name__),
        settings_factory=KorTravelMapSettings.model_construct,
        specs=tuple(specs),
    )


async def _membership(
    session: AsyncSession, provider: str, dataset_key: str
) -> ImportJobDatasetTarget:
    row = (
        await session.execute(
            text(_LOOKUP_MEMBERSHIP_SQL), {"provider": provider, "dataset_key": dataset_key}
        )
    ).one()
    return ImportJobDatasetTarget(
        provider_dataset_id=int(row.provider_dataset_id),
        sync_scope=str(row.sync_scope),
        operation_key=str(row.operation_key),
    )


async def _enqueue(engine: AsyncEngine, provider: str, dataset_key: str) -> tuple[str, str]:
    async with AsyncSession(engine, expire_on_commit=False) as session, session.begin():
        membership = await _membership(session, provider, dataset_key)
        request = await enqueue_feature_update_request(
            session,
            scope={
                "type": "provider_dataset",
                "provider_dataset_id": membership.provider_dataset_id,
                "sync_scope": membership.sync_scope,
                "operation_key": membership.operation_key,
            },
            dataset_memberships=[membership],
        )
    return request.request_id, membership.operation_key


async def _enqueue_cache_target(engine: AsyncEngine, suffix: str = "") -> tuple[str, str]:
    """축제 dataset을 대상으로 하는 cache target 요청(PinVi 경로의 모양) 하나."""

    async with AsyncSession(engine, expire_on_commit=False) as session, session.begin():
        membership = await _membership(session, FESTIVAL_PROVIDER, FESTIVAL_DATASET_KEY)
        seed = festival_item(
            f"Q1022-SEED{suffix}",
            f"큐 재현 축제(기존){suffix}",
            starts_on=date(2026, 11, 1),
            ends_on=date(2026, 11, 7),
            addr1="서울특별시 중구 세종대로 110",
            lon=126.978,
            lat=37.5665,
        )
        bundle = (await festival_bundles([seed], fetched_at=_FETCHED))[0]
        await feature_repo.load_bundle(session, bundle)
        await session.execute(
            text(
                "UPDATE feature.features AS feature SET sigungu_code = '11140', sido_code = '11', "
                "legal_dong_code = '1114010100' FROM feature.feature_aliases AS alias "
                "WHERE alias.feature_id = feature.feature_id AND alias.alias = :alias"
            ),
            {"alias": bundle.feature.feature_id},
        )
        existing = (
            await session.execute(
                text(
                    "SELECT 1 FROM ops.provider_refresh_policies "
                    "WHERE provider_dataset_id = :provider_dataset_id"
                ),
                {"provider_dataset_id": membership.provider_dataset_id},
            )
        ).first()
        if existing is None:
            await upsert_provider_refresh_policy(
                session,
                provider_dataset_id=membership.provider_dataset_id,
                source_kind="openapi",
                expected_revision=None,
                targeted_policy="allow_targeted",
                max_requests_per_minute=60,
            )
        await upsert_poi_cache_target(
            session,
            external_system="q1022-app",
            target_key=f"q1022-target{suffix}",
            lon=126.978,
            lat=37.5665,
            radius_km=1.0,
        )
        request = await enqueue_feature_update_request(
            session,
            scope={
                "type": "cache_target_keys",
                "external_system": "q1022-app",
                "target_keys": [f"q1022-target{suffix}"],
            },
            priority=90,
        )
    return request.request_id, membership.operation_key


#: 긴 요청 backend의 표지. 표본기·probe 연결과 섞이지 않게 pid를 이 이름으로 찾는다.
_LONG_APPLICATION_NAME: Final = "q1022-long"

#: 긴 transaction **앞부분에서** topic 원본을 쓴다(0행 UPDATE도 statement trigger는 발화한다).
#: prod에서는 쓰기 중간의 ``record_override_geo_stale``(``data_integrity_violations`` INSERT)과
#: 꼬리의 주소 finding·sync state가 그 자리다(#1548 리뷰). 458 전에는 이 문장들이 topic 행을
#: commit까지 쥐었다.
_TOPIC_SOURCE_WRITES: Final = (
    "UPDATE provider_sync.provider_sync_state SET updated_at = updated_at WHERE false",
    "UPDATE ops.data_integrity_violations SET status = status WHERE false",
    "UPDATE ops.poi_cache_targets SET updated_at = updated_at WHERE false",
)


class _TopicTouchingRunner:
    """긴 요청의 runner — 표지를 달고 topic 원본을 먼저 쓴 뒤 실제 asset runner로 넘긴다."""

    def __init__(self, inner: FeatureUpdateAssetRunner) -> None:
        self._inner = inner

    async def __call__(self, session: AsyncSession, scope: ProviderDatasetRefreshScope) -> Any:
        await session.execute(text(f"SET LOCAL application_name = '{_LONG_APPLICATION_NAME}'"))
        for statement in _TOPIC_SOURCE_WRITES:
            await session.execute(text(statement))
        return await self._inner(session, scope)


async def _long_pids(engine: AsyncEngine) -> set[int]:
    async with AsyncSession(engine) as observer:
        rows = await observer.execute(
            text("SELECT pid FROM pg_stat_activity WHERE application_name = :name"),
            {"name": _LONG_APPLICATION_NAME},
        )
        return {int(pid) for pid in rows.scalars().all()}


async def _until_reached(reached: asyncio.Event, long_task: asyncio.Task[Any]) -> None:
    """멈춤 지점에 닿을 때까지 — 긴 요청이 그 전에 끝나면(실패) 기다리지 않고 바로 알린다."""

    waiter = asyncio.create_task(reached.wait())
    done, _ = await asyncio.wait(
        {waiter, long_task}, timeout=60, return_when=asyncio.FIRST_COMPLETED
    )
    if waiter not in done:
        waiter.cancel()
        result = long_task.result() if long_task in done else None
        raise AssertionError(f"긴 요청이 멈춤 지점에 닿지 못했다: {result!r}")


async def _sample_waiters(
    engine: AsyncEngine, stop: asyncio.Event, seen: list[dict[str, Any]]
) -> None:
    async with AsyncSession(engine) as observer:
        while not stop.is_set():
            rows = (await observer.execute(text(_WAITERS_SQL))).mappings().all()
            for row in rows:
                seen.append(dict(row))
            await observer.rollback()
            await asyncio.sleep(0.2)


async def test_queue_requests_proceed_while_a_long_load_holds_its_transaction(
    queue_db: tuple[AsyncEngine, AsyncEngine],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    superuser, runtime = queue_db
    monkeypatch.setattr(dagster_assets, "fetch_visitkorea_attraction_details", _no_tourapi_details)

    others = [
        *((_KNPS, key) for key in _KNPS_POINTS),
        *((_KNPS, key) for key in _KNPS_GEOMETRY),
        ("python-krheritage-api", "krheritage_heritage_features"),
        ("python-krheritage-api", "krheritage_event_list"),
    ]
    long_request, long_operation = await _enqueue(superuser, _KNPS, _LONG_DATASET)
    other_requests = [await _enqueue(superuser, provider, key) for provider, key in others]
    other_requests.append(await _enqueue_cache_target(superuser))
    labels = [key for _, key in others] + ["cache_target:" + FESTIVAL_DATASET_KEY]
    operation_keys = {long_operation, *(operation for _, operation in other_requests)}

    geocoder = _HoldingGeocoder()
    long_task = asyncio.create_task(
        AsyncKorTravelMapClient(runtime).execute_feature_update_request(
            long_request,
            runner=_TopicTouchingRunner(
                _runner(AsyncKorTravelMapClient(runtime), operation_keys, geocoder)
            ),
            dagster_run_id="q1022-long",
        )
    )
    stop = asyncio.Event()
    seen: list[dict[str, Any]] = []
    sampler: asyncio.Task[None] | None = None
    try:
        await _until_reached(geocoder.reached, long_task)
        long_pids = await _long_pids(superuser)
        held_during_transform = await _held_by_others(superuser)
        sampler = asyncio.create_task(_sample_waiters(superuser, stop, seen))

        async def _run_other(index: int, request_id: str) -> tuple[str, str]:
            try:
                result = await AsyncKorTravelMapClient(runtime).execute_feature_update_request(
                    request_id,
                    runner=_runner(AsyncKorTravelMapClient(runtime), operation_keys),
                    dagster_run_id=f"q1022-other-{index}",
                )
            except Exception as exc:  # noqa: BLE001 — 결과를 모두 모아 한 번에 단언한다.
                return "raised", f"{type(exc).__name__}: {exc}"[:600]
            if result is None:
                return "none", ""
            return result.status, (result.error_message or "")[:600]

        outcomes = await asyncio.wait_for(
            asyncio.gather(
                *(
                    _run_other(index, request_id)
                    for index, (request_id, _) in enumerate(other_requests)
                )
            ),
            timeout=180,
        )
    finally:
        stop.set()
        if sampler is not None:
            await sampler
        geocoder.release.set()
        long_result = await asyncio.wait_for(long_task, timeout=120)

    print("HELD_DURING_TRANSFORM", held_during_transform)
    for label, outcome in zip(labels, outcomes, strict=True):
        print("OUTCOME", label, outcome[0], outcome[1])
    print("LONG", long_result.status if long_result else None)
    for item in sorted(
        {
            (row["locktype"], row["relation"], row["mode"], row["waiting_query"])
            for row in seen
        },
        key=str,
    ):
        print("WAIT", item)

    # 76분 열린 transaction이 앞부분에서 topic 원본을 썼어도(458: 표식만 남는다) 받기·변환 동안
    # 쥔 전역 행·fence가 없어야 다른 요청이 끝까지 간다. event slot은 자기 것 하나 이하다.
    assert held_during_transform["topics_held"] == []
    assert held_during_transform["fence_held"] is False
    assert held_during_transform["slots_held"] <= 1
    failed = [
        (label, outcome)
        for label, outcome in zip(labels, outcomes, strict=True)
        if outcome[0] != "done"
    ]
    assert not failed, failed
    # 다른 요청끼리의 짧은 fence 대기(ADR-111/113 설계)는 있어도 된다. 긴 transaction을 기다린
    # backend는 없어야 한다.
    assert len(long_pids) == 1, long_pids
    blocked_by_long = [row for row in seen if long_pids & set(row["blockers"] or ())]
    assert not blocked_by_long, blocked_by_long
    assert long_result is not None
    assert long_result.status == "done", long_result.error_message


class _WriteHoldingClient(AsyncKorTravelMapClient):
    """긴 요청의 client — Feature를 다 쓴 뒤(fence를 쥔 채) sync state 기록 직전에 멈춘다."""

    reached: asyncio.Event
    release: asyncio.Event

    async def record_sync_success_for_operation_membership(
        self, *args: Any, **kwargs: Any
    ) -> Any:
        self.reached.set()
        await asyncio.wait_for(self.release.wait(), timeout=600)
        return await super().record_sync_success_for_operation_membership(*args, **kwargs)


async def test_load_write_phase_holds_the_fence_but_no_live_topic_row(
    queue_db: tuple[AsyncEngine, AsyncEngine],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """쓰기 단계 끝(Feature·주소 finding을 다 쓰고 sync state 직전)에도 topic 행은 잡혀 있지 않다.

    record의 소재지(서울)와 좌표(경주)를 어긋나게 해 주소 검증 finding을 만든다 — prod 적재는
    대개 finding이 있고, 그 기록이 ``data_integrity_violations``(``dataset_projection``)를 쓴다.
    458 전에는 이 지점에서 ``topics_held = ['dataset_projection']``이었고 cache target resolve
    문장이 lock timeout이었다(#1548 리뷰 실측). 이제 topic 행은 commit 직전에만 잡히므로 PinVi
    cache target 요청의 resolve 단계는 적재가 쓰는 동안에도 기다리지 않는다. 적재가 쥐는 것은
    ``feature-curation-write`` fence뿐이다(ADR-111/113 설계).
    """

    superuser, runtime = queue_db
    monkeypatch.setattr(dagster_assets, "fetch_visitkorea_attraction_details", _no_tourapi_details)
    original_records_for = _records_for

    def records_with_finding(scope: ProviderDatasetRefreshScope) -> dict[str, object]:
        if scope.dataset_key == "krheritage_heritage_features":
            return {
                "krheritage_items": [
                    _HeritageItem(
                        key=_HeritageKey(ccba_kdcd="11", ccba_asno="Q1022W", ccba_ctcd="11"),
                        name_ko="큐 재현 유산(주소 불일치)",
                        category="전통사찰",
                        longitude=Decimal("129.349"),
                        latitude=Decimal("35.795"),
                        location_text="서울특별시 종로구 세종로",
                    )
                ]
            }
        return original_records_for(scope)

    monkeypatch.setattr(sys.modules[__name__], "_records_for", records_with_finding)
    long_request, long_operation = await _enqueue(
        superuser, "python-krheritage-api", "krheritage_heritage_features"
    )
    async with AsyncSession(superuser) as session:
        findings_before = int(
            (
                await session.execute(
                    text(
                        "SELECT count(*) FROM ops.data_integrity_violations AS finding "
                        "JOIN provider_sync.provider_datasets AS dataset "
                        "  ON dataset.provider_dataset_id = finding.provider_dataset_id "
                        "WHERE dataset.dataset_key = 'krheritage_heritage_features'"
                    )
                )
            ).scalar_one()
        )
    async with AsyncSession(superuser, expire_on_commit=False) as session, session.begin():
        target = await upsert_poi_cache_target(
            session,
            external_system="q1022-write",
            target_key="q1022-write-target",
            lon=126.978,
            lat=37.5665,
            radius_km=1.0,
        )

    holding = _WriteHoldingClient(runtime)
    holding.reached = asyncio.Event()
    holding.release = asyncio.Event()
    long_task = asyncio.create_task(
        AsyncKorTravelMapClient(runtime).execute_feature_update_request(
            long_request,
            runner=_TopicTouchingRunner(_runner(holding, {long_operation})),
            dagster_run_id="q1022-write-long",
        )
    )
    try:
        await _until_reached(holding.reached, long_task)
        held_during_write = await _held_by_others(superuser)
        # 큐 경로 cache target resolve 단계의 문장 그대로, Dagster lock_timeout 아래에서.
        async with AsyncSession(runtime) as resolver, resolver.begin():
            started = asyncio.get_running_loop().time()
            marked = await mark_poi_cache_targets_refresh_requested(resolver, [target.target_id])
            elapsed = asyncio.get_running_loop().time() - started
    finally:
        holding.release.set()
        long_result = await asyncio.wait_for(long_task, timeout=120)

    assert held_during_write["topics_held"] == []
    assert held_during_write["fence_held"] is True
    assert marked == 1
    assert elapsed < 1.0, elapsed
    assert long_result is not None
    assert long_result.status == "done", long_result.error_message
    async with AsyncSession(superuser) as session:
        recorded = int(
            (
                await session.execute(
                    text(
                        "SELECT count(*) FROM ops.data_integrity_violations AS finding "
                        "JOIN provider_sync.provider_datasets AS dataset "
                        "  ON dataset.provider_dataset_id = finding.provider_dataset_id "
                        "WHERE dataset.dataset_key = 'krheritage_heritage_features'"
                    )
                )
            ).scalar_one()
        )
        leaked = int(
            (
                await session.execute(text("SELECT count(*) FROM ops.ops_live_topic_pending"))
            ).scalar_one()
        )
    # 이 record의 finding이 실제로 기록됐다 — topics_held=[]가 finding 0건이라서가 아니다.
    assert recorded > findings_before
    # commit 뒤 표식이 남지 않는다(정상이면 정확히 0, 크면 누수).
    assert leaked == 0
