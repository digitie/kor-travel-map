"""전용 testcontainer에서만 실행하는 ADR115 source/patch/seal 측정 엔진."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import subprocess
import time
from collections.abc import Iterable, Mapping
from contextlib import suppress
from dataclasses import asdict
from datetime import timedelta
from importlib import import_module
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, uuid4, uuid5

import psycopg
from alembic.config import Config
from psycopg import sql
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, AsyncSession

from kortravelmap.core import make_payload_hash, make_source_record_key
from kortravelmap.dto import (
    Coordinate,
    Feature,
    FeatureBundle,
    PlaceDetail,
    SourceLink,
    SourceRecord,
)
from kortravelmap.infra.db import assert_runtime_db_privilege_boundary, make_async_engine
from kortravelmap.infra.feature_repo import (
    arm_feature_curation_write_wait,
    capture_provider_curation_input,
    load_bundles,
    load_source_record_links,
    lock_feature_curation_write,
)
from kortravelmap.infra.runtime_privileges import reconcile_runtime_privileges_in_transaction
from scripts.scoped_write_baseline import Fixture, Point, interval_overlap, plan
from tests.integration._application_300_bootstrap import (
    _TEST_RUNTIME_PASSWORD,
    upgrade_head_with_application_300_bootstrap,
)
from tests.integration._postgis_image import resolve_postgis_image

_ROOT = Path(__file__).resolve().parents[1]


def feature_id(case: str, writer: str, point: Point) -> str:
    owner = "left" if case == "shared" else writer
    return str(uuid5(NAMESPACE_URL, f"map-cwrite-baseline-v1:{case}:{owner}:{point.key}"))


def record(
    case: str, writer: str, point: Point, fixture: Fixture, *, measured: bool
) -> SourceRecord:
    payload = {**asdict(point), "revision": int(measured)}
    digest = make_payload_hash(payload)
    identity = {
        "provider": f"cwrite-benchmark-{case}",
        "dataset_key": writer,
        "source_entity_type": "place",
        "source_entity_id": point.key,
    }
    return SourceRecord(
        provider=identity["provider"],
        dataset_key=identity["dataset_key"],
        source_entity_type=identity["source_entity_type"],
        source_entity_id=point.key,
        source_record_key=make_source_record_key(**identity, raw_payload_hash=digest),
        raw_payload_hash=digest,
        raw_data=payload,
        fetched_at=fixture.observed_at + timedelta(seconds=int(measured)),
        imported_at=fixture.observed_at,
    )


def source_manifest() -> dict[str, Any]:
    revision = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=_ROOT, check=True, capture_output=True, text=True
    ).stdout.strip()
    dirty = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=no"],
        cwd=_ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    return {
        "git_head": revision,
        "tracked_worktree_clean": not bool(dirty),
        "runner_sha256": {
            name: hashlib.sha256((_ROOT / "scripts" / name).read_bytes()).hexdigest()
            for name in ("scoped_write_baseline.py", "_scoped_write_baseline_pg.py")
        },
    }


def _database(admin: str, action: str, name: str, template: str | None = None) -> None:
    # name은 이 호출자가 UUID로 발급해 소유 목록에 넣은 값만 전달한다.
    with psycopg.connect(
        admin,
        autocommit=True,
        connect_timeout=5,
        options="-c statement_timeout=5000 -c lock_timeout=1000",
    ) as connection:
        if action == "create":
            connection.execute(
                sql.SQL("CREATE DATABASE {} TEMPLATE {}").format(
                    sql.Identifier(name), sql.Identifier(template or "template0")
                )
            )
        elif action == "drop":
            connection.execute(
                sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name))
            )
        else:
            raise ValueError("지원하지 않는 소유 DB 작업")


def _rss() -> int:
    with Path("/proc/self/status").open(encoding="ascii") as handle:
        for line in handle:
            if line.startswith("VmRSS:"):
                return int(line.split()[1]) * 1024
    raise RuntimeError("Linux process RSS를 읽을 수 없습니다")


def _container_sample(container: Any) -> dict[str, int | None]:
    value = container.stats(stream=False, one_shot=True)
    memory = value.get("memory_stats", {})
    cpu = value["cpu_stats"]["cpu_usage"]["total_usage"]
    return {
        "cpu_ns": int(cpu),
        "memory_bytes": memory.get("usage"),
        "lifetime_peak_bytes": memory.get("max_usage") or None,
    }


def cpu_delta(before: dict[str, Any], after: dict[str, Any]) -> float:
    delta = after["cpu_ns"] - before["cpu_ns"]
    if delta < 0:
        raise RuntimeError("측정 중 container CPU counter가 역행했습니다")
    return float(delta) / 1_000_000_000


async def _prepare_runtime_acl(dsn: str) -> None:
    # 정본 post-upgrade 단계다. SET ROLE을 쓴 setup pool은 worker와 공유하지 않는다.
    engine = make_async_engine(
        dsn,
        pool_size=1,
        max_overflow=0,
        server_settings={"statement_timeout": "15000", "lock_timeout": "5000"},
    )
    try:
        async with engine.begin() as connection:
            await reconcile_runtime_privileges_in_transaction(connection)
    finally:
        await engine.dispose()


async def _seed(admin_engine: AsyncEngine, runtime_engine: AsyncEngine, fixture: Fixture) -> None:
    async with AsyncSession(admin_engine) as session, session.begin():
        for case in ("independent", "shared"):
            for writer in ("left", "right"):
                dataset = await session.scalar(
                    text("""
                    INSERT INTO provider_sync.provider_datasets
                        (provider,dataset_key,display_name,source_kind)
                    VALUES (:provider,:writer,'격리 기준선','manual')
                    RETURNING provider_dataset_id
                    """),
                    {"provider": f"cwrite-benchmark-{case}", "writer": writer},
                )
                for point in fixture.points:
                    if case == "independent" or writer == "left":
                        await session.execute(
                            text("""
                            INSERT INTO feature.features (
                                feature_id,kind,name,category,coord,
                                lifecycle_state,publication_state,quality_state
                            ) VALUES (
                                CAST(:id AS uuid),'place',:name,'01010100',
                                x_extension.ST_SetSRID(x_extension.ST_MakePoint(:lon,:lat),4326),
                                'active','published','valid'
                            )
                            """),
                            {
                                "id": feature_id(case, writer, point),
                                "name": point.name + " 초기",
                                "lon": point.lon,
                                "lat": point.lat,
                            },
                        )
                        await session.execute(
                            text("""
                            INSERT INTO feature.feature_places(feature_id,kind,place_kind)
                            VALUES (CAST(:id AS uuid),'place','tourism')
                            """),
                            {"id": feature_id(case, writer, point)},
                        )
                    # 승인된 N:1 membership의 synthetic fixture다. 자동 dedup/실제 claim 생성
                    # 속도를 재는 것이 아니며, existing claim을 생산 코드가 그대로 재검증한다.
                    await session.execute(
                        text("""
                        INSERT INTO provider_sync.provider_feature_identities (
                            provider_dataset_id,feature_kind,natural_key,
                            feature_id,bound_by_operation
                        ) VALUES (:dataset,'place',:key,CAST(:id AS uuid),'baseline-fixture-v1')
                        """),
                        {
                            "dataset": dataset,
                            "key": point.key,
                            "id": feature_id(case, writer, point),
                        },
                    )
    async with AsyncSession(runtime_engine) as session, session.begin():
        for case in ("independent", "shared"):
            for writer in ("left", "right"):
                pairs = []
                for point in fixture.points:
                    source = record(case, writer, point, fixture, measured=False)
                    pairs.append(
                        (
                            source,
                            SourceLink(
                                feature_id=feature_id(case, writer, point),
                                source_record_key=source.source_record_key,
                                source_role="primary",
                                match_method="fixture",
                                confidence=100,
                                created_at=fixture.observed_at,
                            ),
                        )
                    )
                await load_source_record_links(session, pairs)


def _bundle(case: str, writer: str, point: Point, fixture: Fixture) -> FeatureBundle:
    source = record(case, writer, point, fixture, measured=True)
    identity = feature_id(case, writer, point)
    return FeatureBundle(
        feature=Feature(
            feature_id=identity,
            provider_natural_key=point.key,
            kind="place",
            name=point.name,
            coord=Coordinate(lon=point.lon, lat=point.lat),
            category="01010100",
            marker_icon="circle",
            marker_color="P-01",
            detail=PlaceDetail(feature_id=identity, place_kind="tourism"),
            created_at=fixture.observed_at,
            updated_at=fixture.observed_at,
        ),
        source_record=source,
        source_link=SourceLink(
            feature_id=identity,
            source_record_key=source.source_record_key,
            source_role="primary",
            match_method="fixture",
            confidence=100,
            created_at=fixture.observed_at,
        ),
    )


async def _writer(
    engine: AsyncEngine, case: str, writer: str, fixture: Fixture, barrier: asyncio.Barrier
) -> dict[str, Any]:
    async with AsyncSession(engine) as session:
        began = time.perf_counter()
        async with session.begin():
            identity = (
                (
                    await session.execute(
                        text("""
                    SELECT pg_backend_pid() AS backend_pid,
                           session_user::text AS session_login,
                           current_user::text AS effective_login
                """)
                    )
                )
                .mappings()
                .one()
            )
            if any(
                identity[field] != "ktm_feature_service"
                for field in ("session_login", "effective_login")
            ):
                raise RuntimeError("benchmark worker는 실제 ktm_feature_service여야 합니다")
            pid = int(identity["backend_pid"])
            await session.execute(text("SET LOCAL statement_timeout='15s'"))
            await session.execute(text("SET LOCAL lock_timeout='5s'"))
            arm_feature_curation_write_wait(session, 5000)
            await barrier.wait()
            waiting = time.perf_counter()
            await lock_feature_curation_write(session)
            acquired = time.perf_counter()
            loaded = await load_bundles(
                session, (_bundle(case, writer, point, fixture) for point in fixture.points)
            )
            dml_ended = time.perf_counter()
            seal = await capture_provider_curation_input(
                session, provider=f"cwrite-benchmark-{case}", dataset_key=writer
            )
            sealed = time.perf_counter()
            if seal.curation_input_member_count != len(fixture.points):
                raise RuntimeError("seal membership이 고정 fixture와 다릅니다")
        committed = time.perf_counter()
    return {
        "writer": writer,
        "backend_pid": pid,
        "session_login": str(identity["session_login"]),
        "effective_login": str(identity["effective_login"]),
        "transaction_started": began,
        "lock_requested": waiting,
        "lock_acquired": acquired,
        "dml_started": acquired,
        "dml_ended": dml_ended,
        "committed": committed,
        "lock_wait_seconds": acquired - waiting,
        "dml_seconds": dml_ended - acquired,
        "seal_seconds": sealed - dml_ended,
        "commit_seconds": committed - sealed,
        "load": asdict(loaded),
        "seal_member_count": seal.curation_input_member_count,
        "seal_sha256": seal.curation_input_set_hash,
    }


def _effective_state(
    rows: Iterable[Mapping[str, Any]], case: str, fixture: Fixture
) -> list[dict[str, Any]]:
    fields = (
        "feature_id",
        "kind",
        "name",
        "category",
        "lon",
        "lat",
        "marker_icon",
        "marker_color",
        "place_kind",
    )
    actual = sorted(
        ({field: row[field] for field in fields} for row in rows),
        key=lambda item: item["feature_id"],
    )
    expected = {
        feature_id(case, writer, point): {
            "feature_id": feature_id(case, writer, point),
            "kind": "place",
            "name": point.name,
            "category": "01010100",
            "lon": point.lon,
            "lat": point.lat,
            "marker_icon": "circle",
            "marker_color": "P-01",
            "place_kind": "tourism",
        }
        for writer in ("left", "right")
        for point in fixture.points
    }
    if actual != [expected[key] for key in sorted(expected)]:
        raise RuntimeError("effective 값/Feature 집합이 고정 fixture와 다릅니다")
    return actual


async def _state(engine: AsyncEngine, case: str, fixture: Fixture) -> dict[str, Any]:
    # 이 도구가 만든 synthetic Feature만 읽는다. 전체 이력 집계가 아니다.
    ids = sorted(
        {
            feature_id(case, writer, point)
            for writer in ("left", "right")
            for point in fixture.points
        }
    )
    async with engine.connect() as connection:
        rows = (
            (
                await connection.execute(
                    text("""
                SELECT f.feature_id::text,f.kind,f.name,f.category,f.row_revision,
                       x_extension.ST_X(f.coord) AS lon,x_extension.ST_Y(f.coord) AS lat,
                       f.marker_icon,f.marker_color,p.place_kind
                FROM feature.features AS f
                LEFT JOIN feature.feature_places AS p USING(feature_id)
                WHERE f.feature_id=ANY(CAST(:ids AS uuid[]))
                ORDER BY f.feature_id
                """),
                    {"ids": ids},
                )
            )
            .mappings()
            .all()
        )
        source_count = await connection.scalar(
            text("""
            SELECT count(*) FROM provider_sync.source_entity_heads AS head
            JOIN provider_sync.source_entities AS entity USING(source_entity_key)
            JOIN provider_sync.provider_datasets AS dataset USING(provider_dataset_id)
            JOIN provider_sync.source_records AS r
              ON r.source_record_key=head.current_source_record_key
            WHERE dataset.provider=:provider AND r.fetched_at=:observed
            """),
            {
                "provider": f"cwrite-benchmark-{case}",
                "observed": fixture.observed_at + timedelta(seconds=1),
            },
        )
    effective = _effective_state((dict(row) for row in rows), case, fixture)
    if source_count != 2 * len(fixture.points):
        raise RuntimeError("source current head 집합이 고정 fixture와 다릅니다")
    # revision은 replay/마지막 base 소유자에 따라 달라질 수 있어 effective digest와 분리한다.
    return {
        "feature_count": len(rows),
        "source_count": source_count,
        "effective_sha256": hashlib.sha256(
            json.dumps(effective, sort_keys=True, allow_nan=False).encode()
        ).hexdigest(),
        "row_revisions": [int(row["row_revision"]) for row in rows],
    }


async def _measure(
    admin_engine: AsyncEngine,
    runtime_engine: AsyncEngine,
    container: Any,
    case: str,
    fixture: Fixture,
) -> dict[str, Any]:
    samples: list[dict[str, Any]] = []
    stopped = asyncio.Event()

    async def sample(observer: AsyncConnection) -> None:
        while not stopped.is_set():
            item = await asyncio.to_thread(_container_sample, container)
            locks = (
                (
                    await observer.execute(
                        text("""
                    SELECT count(*) FILTER (WHERE NOT locks.granted) AS waiting,
                           count(*) FILTER (WHERE locks.locktype='advisory') AS advisory,
                           count(*) AS total
                    FROM pg_catalog.pg_locks AS locks
                    JOIN pg_catalog.pg_stat_activity AS activity USING(pid)
                    WHERE activity.datname=current_database()
                      AND activity.application_name='map-cwrite-baseline-worker'
                    """)
                    )
                )
                .mappings()
                .one()
            )
            samples.append(
                {
                    **item,
                    "worker_rss_bytes": _rss(),
                    "waiting_locks": int(locks["waiting"]),
                    "advisory_locks": int(locks["advisory"]),
                    "total_locks": int(locks["total"]),
                }
            )
            with suppress(TimeoutError):
                await asyncio.wait_for(stopped.wait(), timeout=0.1)

    async with admin_engine.connect() as connection:
        observer = await connection.execution_options(isolation_level="AUTOCOMMIT")
        before_lsn = await observer.scalar(text("SELECT pg_current_wal_insert_lsn()::text"))
        before = await asyncio.to_thread(_container_sample, container)
        cpu_before = time.process_time()
        began = time.perf_counter()
        sampler = asyncio.create_task(sample(observer))
        try:
            async with asyncio.timeout(30), asyncio.TaskGroup() as group:
                barrier = asyncio.Barrier(2)
                writers = [
                    group.create_task(_writer(runtime_engine, case, writer, fixture, barrier))
                    for writer in ("left", "right")
                ]
        finally:
            stopped.set()
            await sampler
        finished = time.perf_counter()
        cpu_after = time.process_time()
        after = await asyncio.to_thread(_container_sample, container)
        wal = await observer.scalar(
            text("SELECT pg_wal_lsn_diff(pg_current_wal_insert_lsn(),CAST(:before AS pg_lsn))"),
            {"before": before_lsn},
        )
    results = [task.result() for task in writers]
    overlap = interval_overlap([(r["dml_started"], r["dml_ended"]) for r in results])
    if overlap:
        raise RuntimeError("현재 global fence 아래 DML 구간이 겹쳤습니다")
    state = await _state(admin_engine, case, fixture)
    return {
        "wall_seconds": finished - began,
        "worker_cpu_core_seconds": cpu_after - cpu_before,
        "pg_cpu_core_seconds": cpu_delta(before, after),
        "worker_rss_sample_peak_bytes": max(
            (s["worker_rss_bytes"] for s in samples), default=_rss()
        ),
        "pg_memory_sample_peak_bytes": max(
            (s["memory_bytes"] for s in samples if s["memory_bytes"] is not None),
            default=None,
        ),
        "pg_memory_sample_peak_unavailable_reason": (
            None
            if any(s["memory_bytes"] is not None for s in samples)
            else "Docker/cgroup가 phase memory usage를 제공하지 않음"
        ),
        "pg_memory_lifetime_peak_bytes": after["lifetime_peak_bytes"],
        "pg_memory_lifetime_peak_unavailable_reason": (
            "Docker/cgroup가 lifetime peak를 제공하지 않음"
            if after["lifetime_peak_bytes"] is None
            else None
        ),
        "sample_interval_seconds": 0.1,
        "sample_count": len(samples),
        "waiting_locks_sample_peak": max((s["waiting_locks"] for s in samples), default=0),
        "advisory_locks_sample_peak": max((s["advisory_locks"] for s in samples), default=0),
        "pg_locks_sample_peak": max((s["total_locks"] for s in samples), default=0),
        "wal_bytes": int(wal),
        "dml_overlap_seconds": overlap,
        "writers": sorted(results, key=lambda result: result["lock_acquired"]),
        "state": state,
    }


_READY_ATTEMPT_SECONDS = 1.0
_READY_TOTAL_SECONDS = 30.0
_READY_PAUSE_SECONDS = 0.1


async def _ready(admin: str) -> bool:
    connection: psycopg.AsyncConnection[Any] | None = None
    try:
        async with asyncio.timeout(_READY_ATTEMPT_SECONDS):
            connection = await psycopg.AsyncConnection.connect(
                admin, autocommit=True, connect_timeout=1
            )
            await connection.execute("SELECT 1")
        return True
    except (psycopg.OperationalError, TimeoutError):
        return False
    finally:
        if connection is not None:
            # autocommit이므로 rollback 왕복 없이 public close가 로컬 연결을 종료한다.
            await connection.close()


async def _wait_ready(admin: str) -> None:
    async with asyncio.timeout(_READY_TOTAL_SECONDS):
        for _ in range(300):
            if await _ready(admin):
                return
            await asyncio.sleep(_READY_PAUSE_SECONDS)
    raise TimeoutError("소유 PostgreSQL 재기동 준비 시간이 상한을 넘었습니다")


async def _start_owned_container(container: Any) -> None:
    # to_thread는 caller 취소만으로 끝나지 않는다. 시작 완료 뒤에만 outer finally가 stop한다.
    startup = asyncio.create_task(asyncio.to_thread(container.start))
    try:
        await asyncio.shield(startup)
    except asyncio.CancelledError:
        while not startup.done():
            with suppress(Exception, asyncio.CancelledError):
                await asyncio.shield(startup)
        with suppress(Exception, asyncio.CancelledError):
            startup.result()
        raise


async def run_baseline(fixture: Fixture, *, repetitions: int = 3) -> dict[str, Any]:
    """자체 testcontainer만 만든다. 호출자가 DSN/기존 container를 주입할 수 없다."""
    if not 1 <= repetitions <= 10:
        raise ValueError("repetitions는 1~10이어야 합니다")
    if not await asyncio.to_thread(Path("/proc/self/status").exists):
        raise RuntimeError("이 측정기는 Linux 전용입니다")
    docker_host = os.environ.get("DOCKER_HOST", "")
    if docker_host and not docker_host.startswith("unix://"):
        raise RuntimeError("로컬 Unix Docker socket만 사용합니다")
    container_type = import_module("testcontainers.postgres").PostgresContainer

    provenance = await asyncio.to_thread(source_manifest)
    image = resolve_postgis_image()
    container = container_type(
        image,
        username="baseline_admin",
        password=f"baseline-root-{uuid4().hex}",
        dbname="postgres",
    )
    owned: list[str] = []
    report = {**plan(fixture), "repetitions": repetitions, "trials": [], "image": image}
    try:
        await _start_owned_container(container)
        docker_container = container.get_wrapped_container()
        report["source"] = provenance
        report["image_id"] = docker_container.image.id
        report["image_architecture"] = docker_container.image.attrs.get("Architecture")
        admin_url = make_url(container.get_connection_url()).set(drivername="postgresql")
        admin = admin_url.render_as_string(hide_password=False)
        template = "ktm_cwrite_baseline_" + uuid4().hex
        await asyncio.to_thread(_database, admin, "create", template)
        owned.append(template)
        template_admin = admin_url.set(database=template).render_as_string(hide_password=False)
        config = Config(str(_ROOT / "alembic.ini"))
        config.set_main_option("script_location", str(_ROOT / "alembic"))
        await upgrade_head_with_application_300_bootstrap(config, template_admin)
        await _prepare_runtime_acl(
            admin_url.set(
                database=template,
                username="ktm_feature_service",
                password=_TEST_RUNTIME_PASSWORD,
            ).render_as_string(hide_password=False)
        )

        def engines(database: str) -> tuple[AsyncEngine, AsyncEngine]:
            settings = {
                "statement_timeout": "15000",
                "lock_timeout": "5000",
                "application_name": "map-cwrite-baseline-observer",
            }
            owner = make_async_engine(
                admin_url.set(database=database).render_as_string(hide_password=False),
                pool_size=1,
                max_overflow=0,
                server_settings=settings,
            )
            runtime = make_async_engine(
                admin_url.set(
                    database=database,
                    username="ktm_feature_service",
                    password=_TEST_RUNTIME_PASSWORD,
                ).render_as_string(hide_password=False),
                pool_size=2,
                max_overflow=0,
                server_settings={**settings, "application_name": "map-cwrite-baseline-worker"},
            )
            return owner, runtime

        owner, runtime = engines(template)
        try:
            await assert_runtime_db_privilege_boundary(
                runtime, expected_login="ktm_feature_service"
            )
            report["runtime_acl_boundary_verified"] = True
            await _seed(owner, runtime, fixture)
            async with owner.connect() as connection:
                report["schema_head"] = await connection.scalar(
                    text("SELECT version_num FROM alembic_version")
                )
                report["postgres_version"] = await connection.scalar(text("SELECT version()"))
        finally:
            await runtime.dispose()
            await owner.dispose()

        for case in ("independent", "shared"):
            for iteration in range(1, repetitions + 1):
                name = "ktm_cwrite_baseline_" + uuid4().hex
                await asyncio.to_thread(_database, admin, "create", name, template)
                owned.append(name)
                await asyncio.to_thread(docker_container.restart, timeout=10)
                await _wait_ready(admin)
                owner, runtime = engines(name)
                try:
                    cold = await _measure(owner, runtime, docker_container, case, fixture)
                    warm = await _measure(owner, runtime, docker_container, case, fixture)
                    if cold["state"]["effective_sha256"] != warm["state"]["effective_sha256"]:
                        raise RuntimeError("같은 artifact replay에서 effective 값이 달라졌습니다")
                    report["trials"].append(
                        {
                            "case": case,
                            "iteration": iteration,
                            "cold": cold,
                            "warm": warm,
                        }
                    )
                finally:
                    await runtime.dispose()
                    await owner.dispose()
                await asyncio.to_thread(_database, admin, "drop", name)
                owned.remove(name)
        report["three_repetition_baseline"] = repetitions >= 3
        report["scope_complete"] = False
        report["metric_limits"] = [
            "OS page cache 미통제; PG shared_buffers cold만 구분",
            "RSS/memory peak는 100ms 샘플, lifetime peak는 cgroup 제공시에만 별도 기록",
            "CPU/WAL은 meter overhead와 전용 PG background 비용을 포함",
            "lock_wait_seconds는 client fence 호출 RTT 포함; PG lock은100ms샘플",
            "pg_locks 샘플은 실제 모든 row lock 수를 뜻하지 않음",
            "provider fetch/Geo/최초 identity 생성/retire/root/API/UI 기준선 아님",
        ]
        return report
    finally:
        try:
            # 생성 성공한 정확한 소유 목록만 정리한다. prefix로 소유를 추정하지 않는다.
            if owned:
                admin = (
                    make_url(container.get_connection_url())
                    .set(drivername="postgresql")
                    .render_as_string(hide_password=False)
                )
                for name in reversed(owned):
                    await asyncio.to_thread(_database, admin, "drop", name)
        finally:
            await asyncio.to_thread(container.stop)


def write_report(path: Path, report: dict[str, Any]) -> None:
    temporary = path.with_name(path.name + ".tmp-" + uuid4().hex)
    try:
        with temporary.open("x", encoding="utf-8") as handle:
            json.dump(report, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        # 같은 디렉터리의 hard link는 atomic no-clobber다. 기존 측정 기록을 덮지 않는다.
        os.link(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
