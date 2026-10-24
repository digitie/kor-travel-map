#!/usr/bin/env python3
"""ADR115 제한 native scalar의 자체 PostGIS 측정. 외부 DSN/운영 입력은 받지 않는다."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import subprocess
import time
from contextlib import suppress
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5
from zoneinfo import ZoneInfo

from sqlalchemy import text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from kortravelmap.core.ids import make_feature_id, make_payload_hash, make_source_record_key
from kortravelmap.dto import (
    Feature,
    FeatureBundle,
    PlaceDetail,
    SourceLink,
    SourceRecord,
    SourceRole,
)
from kortravelmap.dto.provider_field_presence import ProviderFieldPresence
from kortravelmap.infra import scoped_provider_refresh as native
from kortravelmap.infra.db import assert_runtime_db_privilege_boundary, make_async_engine
from kortravelmap.infra.feature_repo import _make_source_entity_key
from kortravelmap.infra.provider_field_candidates import (
    arm_provider_field_shadow,
    capture_provider_field_candidates,
)
from kortravelmap.infra.scoped_feature_writes import (
    ScopedWriteDependency,
    append_scoped_feature_write_manifest,
    claim_scoped_feature_write,
    seal_scoped_feature_write_manifest,
)
from scripts._scoped_write_baseline_pg import (
    _container_sample,
    _database,
    _prepare_runtime_acl,
    _rss,
    _start_owned_container,
    cpu_delta,
    write_report,
)
from scripts.scoped_write_baseline import interval_overlap
from tests.integration._application_300_bootstrap import (
    _TEST_RUNTIME_PASSWORD,
    upgrade_head_with_application_300_bootstrap,
)
from tests.integration._postgis_image import resolve_postgis_image

_ROOT = Path(__file__).resolve().parents[2]
_TIME = datetime(2026, 10, 24, 12, tzinfo=ZoneInfo("Asia/Seoul"))
_LABEL = "codex.native-scalar-measure"
_SAMPLE_SECONDS = 0.1


def bundle(writer: str, *, measured: bool) -> FeatureBundle:
    """직렬/병렬/모든 clone이 같은 시각·원문·키·UUID를 사용한다."""
    if writer not in ("left", "right"):
        raise ValueError("unknown fixture writer")
    provider = "native-scalar-measure-v1"
    raw = {"name": f"{writer}-{'after' if measured else 'before'}", "phones": ["010-0000-0000"]}
    payload_hash = make_payload_hash(raw)
    record_key = make_source_record_key(
        provider=provider,
        dataset_key=writer,
        source_entity_type="place",
        source_entity_id=writer,
        raw_payload_hash=payload_hash,
    )
    alias = make_feature_id(
        bjd_code=None,
        kind="place",
        category="01010100",
        source_type=provider,
        source_natural_key=writer,
    )
    return FeatureBundle(
        feature=Feature(
            feature_id=alias,
            created_at=_TIME,
            updated_at=_TIME,
            provider_natural_key=writer,
            kind="place",
            name=raw["name"],
            category="01010100",
            marker_icon="marker",
            marker_color="P-01",
            detail=PlaceDetail(feature_id=alias, place_kind="tourism", phones=raw["phones"]),
        ),
        source_record=SourceRecord(
            provider=provider,
            dataset_key=writer,
            source_entity_type="place",
            source_entity_id=writer,
            raw_data=raw,
            raw_payload_hash=payload_hash,
            source_record_key=record_key,
            fetched_at=_TIME + timedelta(seconds=int(measured)),
            imported_at=_TIME + timedelta(seconds=int(measured)),
        ),
        source_link=SourceLink(
            feature_id=alias,
            source_record_key=record_key,
            source_role=SourceRole.PRIMARY,
            match_method="fixture",
            confidence=100,
            created_at=_TIME,
        ),
        provider_field_presence=ProviderFieldPresence(
            normalizer_revision="native-measure-v1",
            supplied_fields={"core.name", "place.phones"},
        ),
    )


def feature_id(writer: str) -> UUID:
    return uuid5(NAMESPACE_URL, f"map-native-scalar-measure-v1:{writer}")


def fixture_digest() -> str:
    values = [
        bundle(w, measured=m).model_dump(mode="json")
        for m in (False, True)
        for w in ("left", "right")
    ]
    for value in values:
        value["provider_field_presence"]["supplied_fields"].sort()
    return hashlib.sha256(
        json.dumps(values, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def plan() -> dict[str, Any]:
    return {
        "version": 1,
        "fixture_sha256": fixture_digest(),
        "modes": ["serial", "concurrent2"],
        "repetitions": 3,
        "writers": 2,
        "source_records_per_trial": 2,
        "operating_access": False,
        "external_provider_http": False,
        "fresh_seeded_template_clone_per_trial": True,
        "measurement": "sealed plan 후 native source/head/candidate/winner/finish+commit",
        "overlap_probe": "별도 clone; 실제 source DML 반환 뒤 미커밋 barrier(성능표본 제외)",
        "limits": [
            "2개 독립 dataset/Feature의 synthetic 작은 입력이며 실제 전체 수집·ARM·API 측정 아님",
            "OS page cache/PG shared_buffers cold를 통제하지 않음; fresh DB 상태만 동일",
            "100ms RSS/cgroup sample은 정확한 phase peak가 아니며 lifetime peak와 구분",
            "Python CPU는 sampler/클라이언트 포함, PG CPU/WAL은 전용 PG background 포함",
            "DML interval은 클라이언트 SQL 왕복 시각이며 PG 서버 실행 시간 추정이 아님",
        ],
    }


async def seed(engine: AsyncEngine) -> dict[str, int]:
    datasets = {}
    async with AsyncSession(engine) as session, session.begin():
        await session.execute(text("SELECT ops.lock_scoped_feature_write_protocol(true)"))
        for writer in ("left", "right"):
            old = bundle(writer, measured=False)
            record = old.source_record
            entity = _make_source_entity_key(
                provider=record.provider,
                dataset_key=writer,
                source_entity_type="place",
                source_entity_id=writer,
            )
            dataset = await session.scalar(
                text("""INSERT INTO provider_sync.provider_datasets(
                provider,dataset_key,display_name,source_kind)
                VALUES(:provider,:key,'native measure','manual')
                RETURNING provider_dataset_id"""),
                {"provider": record.provider, "key": writer},
            )
            datasets[writer] = int(dataset)
            params = {
                "feature": feature_id(writer),
                "entity": entity,
                "dataset": dataset,
                "key": writer,
                "record": record.source_record_key,
                "hash": record.raw_payload_hash,
                "raw": json.dumps(record.raw_data),
                "at": record.imported_at,
            }
            for sql in (
                "INSERT INTO feature.features(feature_id,kind,name,category) "
                "VALUES(:feature,'place',:key||'-before','01010100')",
                "INSERT INTO feature.feature_places(feature_id,kind,place_kind) "
                "VALUES(:feature,'place','tourism')",
                "INSERT INTO provider_sync.source_entities(source_entity_key,provider_dataset_id,"
                "source_entity_type,source_entity_id,first_seen_at,last_seen_at) "
                "VALUES(:entity,:dataset,'place',:key,:at,:at)",
                "INSERT INTO provider_sync.source_records(source_record_key,source_entity_key,"
                "raw_data,raw_payload_hash,fetched_at,imported_at) "
                "VALUES(:record,:entity,CAST(:raw AS jsonb),:hash,:at,:at)",
                "INSERT INTO provider_sync.source_entity_heads(source_entity_key,"
                "current_source_record_key,observed_at) VALUES(:entity,:record,:at)",
                "INSERT INTO provider_sync.source_links(feature_id,source_entity_key,"
                "source_role,match_method,confidence) "
                "VALUES(:feature,:entity,'primary','fixture',100)",
            ):
                await session.execute(text(sql), params)
            await session.execute(
                text("""CALL feature.register_provider_field_shadow_policy(
                1,:dataset,'native-measure-v1',CAST(:fields AS jsonb))"""),
                {
                    "dataset": dataset,
                    "fields": json.dumps(
                        [
                            {
                                "field_path": f,
                                "provider_rank": 10,
                                "omitted_policy": "carry_forward",
                                "null_policy": "value",
                            }
                            for f in ("core.name", "place.phones")
                        ]
                    ),
                },
            )
            arm_provider_field_shadow(session, 1)
            await capture_provider_field_candidates(
                session,
                feature_id=str(feature_id(writer)),
                dataset_id=int(dataset),
                entity_key=entity,
                record_key=record.source_record_key,
                values=json.dumps(
                    {"core.name": old.feature.name, "place.phones": ["010-0000-0000"]}
                ),
                geometry_wkt="{}",
                presence=old.provider_field_presence,
            )
    for writer in ("left", "right"):
        async with AsyncSession(engine) as session, session.begin():
            await session.execute(
                text(
                    "CALL feature.activate_provider_field_policy("
                    ":feature,1,ARRAY['core.name','place.phones'])"
                ),
                {"feature": feature_id(writer)},
            )
    return datasets


async def prepare(engine: AsyncEngine, datasets: dict[str, int]) -> dict[str, dict[str, Any]]:
    plans = {}
    for writer in ("left", "right"):
        attempt, owner = uuid4(), uuid4()
        fid = feature_id(writer)
        async with AsyncSession(engine) as session, session.begin():
            revision = await session.scalar(
                text("SELECT row_revision FROM feature.features WHERE feature_id=:f"), {"f": fid}
            )
            heads = (
                await session.execute(
                    text("""SELECT source_entity_key,current_source_record_key
                FROM provider_sync.source_links
                JOIN provider_sync.source_entity_heads USING(source_entity_key)
                WHERE feature_id=:f ORDER BY source_entity_key COLLATE "C"
                """),
                    {"f": fid},
                )
            ).all()
            membership = await session.scalar(
                text("SELECT ops.scoped_feature_write_membership_digest(:f)"), {"f": fid}
            )
            members = [
                ScopedWriteDependency(i, "source_head", entity, key)
                for i, (entity, key) in enumerate(heads)
            ]
            members.extend(
                [
                    ScopedWriteDependency(len(members), "feature", str(fid), str(revision)),
                    ScopedWriteDependency(
                        len(members) + 1, "feature_membership", str(fid), str(membership)
                    ),
                ]
            )
            await claim_scoped_feature_write(
                session,
                attempt_id=attempt,
                owner=owner,
                dataset_id=datasets[writer],
                idempotency_key=f"measure-{writer}",
                regions=(),
                expected_members=len(members),
                input_digest=native.scoped_provider_refresh_input_digest(
                    bundle(writer, measured=True),
                    feature_id=fid,
                    dataset_id=datasets[writer],
                    policy_revision=1,
                ),
            )
            await append_scoped_feature_write_manifest(
                session, attempt_id=attempt, owner=owner, members=members
            )
            digest = await seal_scoped_feature_write_manifest(
                session, attempt_id=attempt, owner=owner
            )
        plans[writer] = dict(
            feature_id=fid,
            dataset_id=datasets[writer],
            policy_revision=1,
            attempt_id=attempt,
            owner=owner,
            manifest_digest=digest,
        )
    return plans


async def state(engine: AsyncEngine) -> dict[str, Any]:
    async with engine.connect() as conn:
        rows = (
            (
                await conn.execute(
                    text("""SELECT feature.feature_id::text,feature.name,
            to_jsonb(place.phones) AS phones,head.current_source_record_key,record.raw_payload_hash,
            record.raw_data,head.observed_at::text,entity.first_seen_at::text,
            (SELECT count(*) FROM provider_sync.source_records r
             WHERE r.source_entity_key=entity.source_entity_key) AS raw_count
            FROM feature.features feature JOIN feature.feature_places place USING(feature_id)
            JOIN provider_sync.source_links link USING(feature_id)
            JOIN provider_sync.source_entities entity USING(source_entity_key)
            JOIN provider_sync.source_entity_heads head USING(source_entity_key)
            JOIN provider_sync.source_records record
              ON record.source_record_key=head.current_source_record_key
            ORDER BY feature.feature_id""")
                )
            )
            .mappings()
            .all()
        )
        receipts = (
            (
                await conn.execute(
                    text(
                        "SELECT input_digest,result_digest FROM ops.feature_write_attempts "
                        "WHERE status='completed' ORDER BY input_digest COLLATE \"C\""
                    )
                )
            )
            .mappings()
            .all()
        )
        completed = len(receipts)
        bases = (
            (
                await conn.execute(
                    text("""SELECT feature_id::text,field_path,value_json,
                source_record_key,source_raw_payload_hash
            FROM feature.feature_base_field_values ORDER BY feature_id,field_path COLLATE "C"
                """)
                )
            )
            .mappings()
            .all()
        )
    values = [dict(row) for row in rows]
    for row in values:
        writer = "left" if row["feature_id"] == str(feature_id("left")) else "right"
        expected = bundle(writer, measured=True)
        if (
            row["name"] != expected.feature.name
            or row["phones"] != ["010-0000-0000"]
            or row["current_source_record_key"] != expected.source_record.source_record_key
            or row["raw_payload_hash"] != expected.source_record.raw_payload_hash
            or row["raw_data"] != expected.source_record.raw_data
            or row["raw_count"] != 2
        ):
            raise RuntimeError("native output/lineage differs from fixture")
    if len(values) != 2 or completed != 2 or len(bases) != 4:
        raise RuntimeError("native output cardinality differs from fixture")
    for base_row in bases:
        writer = "left" if base_row["feature_id"] == str(feature_id("left")) else "right"
        expected = bundle(writer, measured=True)
        expected_value = (
            expected.feature.name if base_row["field_path"] == "core.name" else ["010-0000-0000"]
        )
        if (
            base_row["value_json"] != expected_value
            or base_row["source_record_key"] != expected.source_record.source_record_key
            or base_row["source_raw_payload_hash"] != expected.source_record.raw_payload_hash
        ):
            raise RuntimeError("base winner lacks expected canonical source lineage")
    canonical = {
        "features": values,
        "base": [dict(row) for row in bases],
        "completed_count": int(completed),
        "receipts": [dict(row) for row in receipts],
    }
    canonical["sha256"] = hashlib.sha256(
        json.dumps(canonical, sort_keys=True, default=str, separators=(",", ":")).encode()
    ).hexdigest()
    return canonical


async def measure(
    owner_engine: AsyncEngine,
    runtime: AsyncEngine,
    container: Any,
    mode: str,
    plans: dict[str, dict[str, Any]],
    *,
    proof: bool = False,
) -> dict[str, Any]:
    if mode not in ("serial", "concurrent2") or (proof and mode != "concurrent2"):
        raise ValueError("invalid measurement mode")
    original = native._upsert_source_record_state  # type: ignore[attr-defined]
    intervals: dict[str, dict[str, Any]] = {}
    barrier = asyncio.Barrier(2) if proof else None
    stopped = asyncio.Event()
    samples: list[dict[str, Any]] = []

    async def capture(session: AsyncSession, record: SourceRecord) -> Any:
        writer = record.dataset_key
        item = intervals[writer]
        item["dml_started"] = time.perf_counter()
        result = await original(session, record)
        item["source_dml_returned"] = time.perf_counter()
        if barrier is not None:
            await asyncio.wait_for(barrier.wait(), timeout=5)
        return result

    async def worker(writer: str) -> dict[str, Any]:
        item: dict[str, Any] = {"writer": writer}
        intervals[writer] = item
        async with AsyncSession(connections[writer]) as session:
            await session.begin()
            try:
                item["backend_pid"] = int(await session.scalar(text("SELECT pg_backend_pid()")))
                item["call_started"] = time.perf_counter()
                receipt = await native.refresh_scoped_provider_scalars(
                    session, bundle(writer, measured=True), **plans[writer]
                )
                if receipt["status"] != "completed":
                    raise RuntimeError("native attempt did not complete")
                item["commit_started"] = time.perf_counter()
                await session.commit()
                item["committed"] = time.perf_counter()
                return item
            finally:
                await session.rollback()

    async def sample() -> None:
        while not stopped.is_set():
            samples.append(
                {**await asyncio.to_thread(_container_sample, container), "python_rss": _rss()}
            )
            with suppress(TimeoutError):
                await asyncio.wait_for(stopped.wait(), _SAMPLE_SECONDS)

    connections = {}
    native._upsert_source_record_state = capture  # type: ignore[attr-defined]
    try:
        for writer in ("left", "right"):
            connections[writer] = await runtime.connect()
        async with owner_engine.connect() as connection:
            observer = await connection.execution_options(isolation_level="AUTOCOMMIT")
            lsn = await observer.scalar(text("SELECT pg_current_wal_insert_lsn()::text"))
            before = await asyncio.to_thread(_container_sample, container)
            start_cpu, start = time.process_time(), time.perf_counter()
            sampler = asyncio.create_task(sample())
            try:
                async with asyncio.timeout(30):
                    if mode == "serial":
                        results = [await worker(w) for w in ("left", "right")]
                    else:
                        # TaskGroup는 한 writer가 실패/취소되면 상대를 취소하고 join한다.
                        async with asyncio.TaskGroup() as group:
                            tasks = [group.create_task(worker(w)) for w in ("left", "right")]
                        results = [task.result() for task in tasks]
            finally:
                elapsed, python_cpu = time.perf_counter() - start, time.process_time() - start_cpu
                stopped.set()
                await sampler
            after = await asyncio.to_thread(_container_sample, container)
            wal = await observer.scalar(
                text(
                    "SELECT pg_wal_lsn_diff(pg_current_wal_insert_lsn(),"
                    "CAST(CAST(:before AS text) AS pg_lsn))"
                ),
                {"before": lsn},
            )
    finally:
        native._upsert_source_record_state = original  # type: ignore[attr-defined]
        for connection in connections.values():
            await connection.close()
    dml_overlap = interval_overlap([(r["dml_started"], r["source_dml_returned"]) for r in results])
    uncommitted_overlap = interval_overlap(
        [(r["source_dml_returned"], r["commit_started"]) for r in results]
    )
    if len({r["backend_pid"] for r in results}) != 2:
        raise RuntimeError("two distinct backend sessions required")
    if proof and uncommitted_overlap <= 0:
        raise RuntimeError("source DML did not overlap before commit")
    if mode == "serial" and (dml_overlap or uncommitted_overlap):
        raise RuntimeError("serial intervals unexpectedly overlap")
    return {
        "mode": mode,
        "barrier_probe_only": proof,
        "elapsed_seconds": elapsed,
        "python_cpu_core_seconds": python_cpu,
        "pg_cpu_core_seconds": cpu_delta(before, after),
        "python_rss_sample_peak_bytes": max((s["python_rss"] for s in samples), default=_rss()),
        "pg_memory_sample_peak_bytes": max(
            (s["memory_bytes"] for s in samples if s["memory_bytes"] is not None), default=None
        ),
        "pg_memory_lifetime_peak_bytes": after["lifetime_peak_bytes"],
        "samples": len(samples),
        "wal_bytes": int(wal),
        "dml_client_rtt_overlap_seconds": dml_overlap,
        "uncommitted_source_overlap_seconds": uncommitted_overlap,
        "writers": results,
        "state": await state(owner_engine),
    }


def engines(admin_url: URL, database: str) -> tuple[AsyncEngine, AsyncEngine]:
    settings = {
        "statement_timeout": "30000",
        "lock_timeout": "1000",
        "application_name": "map-native-scalar-measure",
    }
    owner = make_async_engine(
        admin_url.set(database=database).render_as_string(False),
        pool_size=1,
        max_overflow=0,
        server_settings=settings,
    )
    runtime = make_async_engine(
        admin_url.set(
            database=database, username="ktm_feature_service", password=_TEST_RUNTIME_PASSWORD
        ).render_as_string(False),
        pool_size=2,
        max_overflow=0,
        server_settings=settings,
    )
    return owner, runtime


def source_provenance() -> dict[str, Any]:
    return {
        "head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=_ROOT, text=True).strip(),
        "tracked_clean": not subprocess.check_output(
            ["git", "status", "--porcelain", "--untracked-files=no"], cwd=_ROOT, text=True
        ).strip(),
        "runner_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    }


async def run() -> dict[str, Any]:
    """새 이름/label/ID로 소유를 확인한 로컬 container 한 개만 사용한다."""
    from alembic.config import Config
    from testcontainers.postgres import PostgresContainer

    if not await asyncio.to_thread(Path("/proc/self/status").is_file) or (
        os.environ.get("DOCKER_HOST") and not os.environ["DOCKER_HOST"].startswith("unix://")
    ):
        raise RuntimeError("only local Linux Docker is supported")
    identity = uuid4().hex
    name = "kt-map-native-measure-" + identity
    container = (
        PostgresContainer(
            resolve_postgis_image(),
            username="native_admin",
            password="native-" + uuid4().hex,
            dbname="postgres",
        )
        .with_name(name)
        .with_kwargs(
            labels={_LABEL: identity},
            nano_cpus=2_000_000_000,
            mem_limit="1536m",
            memswap_limit="1536m",
            pids_limit=256,
        )
    )
    wrapped = None
    created_id = None
    owned = []
    report = {**plan(), "trials": [], "source": await asyncio.to_thread(source_provenance)}
    report["cleanup_verified"] = False
    report["phase"] = "owned-container-start"
    try:
        await _start_owned_container(container)
        wrapped = container.get_wrapped_container()
        created_id = wrapped.id
        wrapped.reload()
        if wrapped.name != name or wrapped.attrs["Config"]["Labels"].get(_LABEL) != identity:
            raise RuntimeError("owned container identity mismatch")
        admin_url = make_url(container.get_connection_url()).set(drivername="postgresql")
        admin = admin_url.render_as_string(False)
        template = "native_measure_" + uuid4().hex
        await asyncio.to_thread(_database, admin, "create", template)
        owned.append(template)
        config = Config(str(_ROOT / "alembic.ini"))
        config.set_main_option("script_location", str(_ROOT / "alembic"))
        report["phase"] = "canonical-bootstrap"
        await upgrade_head_with_application_300_bootstrap(
            config, admin_url.set(database=template).render_as_string(False)
        )
        await _prepare_runtime_acl(
            admin_url.set(
                database=template, username="ktm_feature_service", password=_TEST_RUNTIME_PASSWORD
            ).render_as_string(False)
        )
        owner, runtime = engines(admin_url, template)
        try:
            await assert_runtime_db_privilege_boundary(
                runtime, expected_login="ktm_feature_service"
            )
            report["phase"] = "seed-and-activate-fixture"
            datasets = await seed(owner)
            async with owner.connect() as connection:
                report["schema_head"] = await connection.scalar(
                    text("SELECT version_num FROM alembic_version")
                )
            report["image_id"] = wrapped.image.id
            report["image_reference"] = resolve_postgis_image()
            report["runtime_acl_verified"] = True
        finally:
            await runtime.dispose()
            await owner.dispose()
        for mode, repeat, proof in [("concurrent2", 0, True)] + [
            (mode, n, False) for n in range(1, 4) for mode in ("serial", "concurrent2")
        ]:
            database = "native_measure_" + uuid4().hex
            await asyncio.to_thread(_database, admin, "create", database, template)
            owned.append(database)
            owner, runtime = engines(admin_url, database)
            try:
                report["phase"] = f"prepare-{mode}-{repeat}"
                plans = await prepare(runtime, datasets)
                report["phase"] = f"measure-{mode}-{repeat}"
                result = await measure(owner, runtime, wrapped, mode, plans, proof=proof)
                result["iteration"] = repeat
                if proof:
                    report["overlap_probe"] = result
                else:
                    report["trials"].append(result)
            finally:
                await runtime.dispose()
                await owner.dispose()
            await asyncio.to_thread(_database, admin, "drop", database)
            owned.remove(database)
        if len({trial["state"]["sha256"] for trial in report["trials"]}) != 1:
            raise RuntimeError("serial/concurrent canonical output differs")
        report["scope_complete"] = False
        report["status"] = "passed"
        report["phase"] = "complete"
    except Exception as exc:
        # 오류 원문에는 DSN/SQL 바인드가 들어갈 수 있으므로 고정 타입만 남긴다.
        report["status"] = "failed"
        report["error_type"] = type(exc).__name__
        sqlstate = getattr(getattr(exc, "orig", None), "sqlstate", None)
        if isinstance(sqlstate, str) and len(sqlstate) == 5 and sqlstate.isalnum():
            report["sqlstate"] = sqlstate
    finally:
        if wrapped is None:
            with suppress(RuntimeError):
                wrapped = container.get_wrapped_container()
                created_id = wrapped.id
        if wrapped is not None:
            wrapped.reload()
            if (
                wrapped.id != created_id
                or wrapped.name != name
                or wrapped.attrs["Config"]["Labels"].get(_LABEL) != identity
            ):
                raise RuntimeError("refusing cleanup of unowned container")
            await asyncio.to_thread(wrapped.remove, force=True, v=True)
            # 정확한 생성 ID의 부재만 확인한다. 다른 동명/공유 자원은 만지지 않는다.
            from docker.errors import NotFound  # type: ignore[import-not-found]

            try:
                await asyncio.to_thread(wrapped.client.containers.get, created_id)
            except NotFound:
                report["cleanup_verified"] = True
            else:
                raise RuntimeError("owned container survived cleanup")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if not args.run:
        print(json.dumps(plan(), ensure_ascii=False, sort_keys=True))
        return 0
    if args.output is None or args.output.exists() or not args.output.parent.is_dir():
        parser.error("--run requires a new --output in an existing directory")
    report = asyncio.run(run())
    write_report(args.output, report)
    print(
        json.dumps(
            {
                "fixture_sha256": report["fixture_sha256"],
                "trials": len(report["trials"]),
                "cleanup_verified": report["cleanup_verified"],
                "status": report["status"],
            }
        )
    )
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
