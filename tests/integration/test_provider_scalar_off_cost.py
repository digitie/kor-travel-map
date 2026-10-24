"""기본 OFF의 10k 관리자 synthetic DML 비용. 실제 collector/ARM 성능 주장이 아니다."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import statistics
import time
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from alembic.config import Config
from psycopg import sql
from sqlalchemy.engine import make_url

from alembic import command
from kortravelmap.infra.db import normalize_async_dsn
from tests.integration._application_300_bootstrap import (
    alembic_schema_owner_role,
    bootstrapped_application_300_migrator_dsn,
)
from tests.integration.test_provider_field_scalar_projection import scalar_container  # noqa: F401

pytestmark = pytest.mark.integration
_ROOT = Path(__file__).resolve().parents[2]
_ROWS = 10_000
_STATEMENTS = (
    """INSERT INTO provider_sync.source_entities(source_entity_key,provider_dataset_id,
        source_entity_type,source_entity_id,first_seen_at,last_seen_at)
        SELECT 'scalar-off-'||n,%(dataset)s,'place',n::text,
        '2026-10-24T00:00:00Z'::timestamptz,'2026-10-24T00:00:00Z'::timestamptz
        FROM generate_series(1,%(rows)s) n""",
    """INSERT INTO provider_sync.source_records(source_record_key,source_entity_key,
        raw_data,raw_payload_hash,fetched_at)
        SELECT 'scalar-off-r-'||n,'scalar-off-'||n,jsonb_build_object('n',n),
        encode(x_extension.digest(jsonb_build_object('n',n)::text,'sha256'),'hex'),
        '2026-10-24T00:00:00Z'::timestamptz FROM generate_series(1,%(rows)s) n""",
    """INSERT INTO provider_sync.source_entity_heads(
        source_entity_key,current_source_record_key,observed_at)
        SELECT 'scalar-off-'||n,'scalar-off-r-'||n,'2026-10-24T00:00:00Z'::timestamptz
        FROM generate_series(1,%(rows)s) n""",
    """INSERT INTO feature.features(feature_id,kind,name,category,
        lifecycle_state,publication_state,quality_state)
        SELECT md5('scalar-off-'||n)::uuid,'place','scalar-off-'||n,'01010100',
        'active','published','valid' FROM generate_series(1,%(rows)s) n""",
    """INSERT INTO feature.feature_places(feature_id,kind,place_kind)
        SELECT md5('scalar-off-'||n)::uuid,'place','tourism' FROM generate_series(1,%(rows)s) n""",
    """INSERT INTO provider_sync.source_links(
        feature_id,source_entity_key,source_role,match_method,confidence)
        SELECT md5('scalar-off-'||n)::uuid,'scalar-off-'||n,'primary','fixture',100
        FROM generate_series(1,%(rows)s) n""",
    """INSERT INTO feature.feature_base_field_values(feature_id,field_path,provider_dataset_id,
        source_entity_key,source_record_key,source_raw_payload_hash,value_json,base_revision,observed_at)
        SELECT md5('scalar-off-'||n)::uuid,'core.name',%(dataset)s,'scalar-off-'||n,
        'scalar-off-r-'||n,encode(x_extension.digest(jsonb_build_object('n',n)::text,'sha256'),'hex'),
        to_jsonb('scalar-off-'||n),1,'2026-10-24T00:00:00Z'::timestamptz
        FROM generate_series(1,%(rows)s) n""",
)
_RELATIONS = (
    "provider_sync.source_entities",
    "provider_sync.source_records",
    "provider_sync.source_entity_heads",
    "feature.features",
    "feature.feature_places",
    "provider_sync.source_links",
    "feature.feature_base_field_values",
)


def _backend_stats(container, pid):
    if type(pid) is not int or pid < 1:
        raise ValueError("invalid owned backend pid")
    status, raw = container.get_wrapped_container().exec_run(["cat", f"/proc/{pid}/stat"])
    if status:
        raise RuntimeError("owned backend stat unavailable")
    fields = raw.decode().rsplit(") ", 1)[1].split()
    return {
        "cpu_seconds": (int(fields[11]) + int(fields[12])) / os.sysconf("SC_CLK_TCK"),
        "rss_bytes": int(fields[21]) * os.sysconf("SC_PAGESIZE"),
    }


def _measure(container, url):
    with psycopg.connect(url) as connection:
        connection.execute("SET LOCAL statement_timeout='60s'")
        connection.execute("SET LOCAL lock_timeout='5s'")
        connection.execute("SELECT ops.lock_scoped_feature_write_protocol(true)")
        role = connection.execute("SELECT session_user,current_user").fetchone()
        trigger_count = connection.execute(
            "SELECT count(*) FROM pg_trigger WHERE tgname LIKE 'trg_scalar_%'"
        ).fetchone()[0]
        assert trigger_count == 0
        validator = connection.execute(
            "SELECT pg_get_functiondef('feature.validate_feature_base_field_value()'::regprocedure)"
        ).fetchone()[0]
        dataset = connection.execute("""INSERT INTO provider_sync.provider_datasets(
            provider,dataset_key,display_name,source_kind)
            VALUES('scalar-off','fixture','scalar OFF cost','manual')
            RETURNING provider_dataset_id""").fetchone()[0]
        pid = connection.execute("SELECT pg_backend_pid()").fetchone()[0]
        before = _backend_stats(container, pid)
        wal = connection.execute("SELECT pg_current_wal_insert_lsn()::text").fetchone()[0]
        params = {"dataset": dataset, "rows": _ROWS}
        worker = time.thread_time()
        started = time.perf_counter()
        for statement in _STATEMENTS:
            connection.execute(statement, params)
        dml = time.perf_counter() - started
        queue = connection.execute("""SELECT coalesce(sum(total_bytes),0),
            coalesce(sum(used_bytes),0)
            FROM pg_backend_memory_contexts WHERE name LIKE 'AfterTrigger%'""").fetchone()
        middle = _backend_stats(container, pid)
        started = time.perf_counter()
        connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
        seal = time.perf_counter() - started
        after = _backend_stats(container, pid)
        wal_bytes = connection.execute(
            """SELECT pg_wal_lsn_diff(pg_current_wal_insert_lsn(),
            CAST(CAST(%s AS text) AS pg_lsn))::bigint""",
            (wal,),
        ).fetchone()[0]
        counts = {
            table: connection.execute(
                sql.SQL("SELECT count(*) FROM {}").format(sql.Identifier(*table.split(".")))
            ).fetchone()[0]
            for table in _RELATIONS
        }
        assert set(counts.values()) == {_ROWS}
        started = time.perf_counter()
        connection.commit()
        commit = time.perf_counter() - started
        return {
            "role": list(role),
            "scalar_trigger_count": trigger_count,
            "validator_sha256": hashlib.sha256(validator.encode()).hexdigest(),
            "row_counts": counts,
            "dml_seconds": dml,
            "seal_seconds": seal,
            "commit_seconds": commit,
            "worker_thread_cpu_seconds": time.thread_time() - worker,
            "backend_cpu_seconds": after["cpu_seconds"] - before["cpu_seconds"],
            "backend_rss_max_sampled_bytes": max(
                before["rss_bytes"], middle["rss_bytes"], after["rss_bytes"]
            ),
            "after_trigger_context_total_bytes": int(queue[0]),
            "after_trigger_context_used_bytes": int(queue[1]),
            "wal_insert_bytes": int(wal_bytes),
        }


def _sample(container, master_url):
    database = "scalar_cost_" + uuid4().hex
    admin = make_url(master_url).set(drivername="postgresql", database="postgres")
    master = make_url(master_url).database
    created = False
    try:
        with psycopg.connect(admin.render_as_string(False), autocommit=True) as connection:
            connection.execute(
                sql.SQL("CREATE DATABASE {} TEMPLATE {}").format(
                    sql.Identifier(database), sql.Identifier(master)
                )
            )
            created = True
        return _measure(
            container,
            make_url(master_url)
            .set(drivername="postgresql", database=database)
            .render_as_string(False),
        )
    finally:
        if created:
            with psycopg.connect(admin.render_as_string(False), autocommit=True) as connection:
                active = connection.execute(
                    "SELECT count(*) FROM pg_stat_activity WHERE datname=%s", (database,)
                ).fetchone()[0]
                if active:
                    raise RuntimeError("owned sample database still has active connections")
                connection.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(database)))


async def test_default_off_10k_dml_has_no_added_scalar_queue(scalar_container, tmp_path):  # noqa: F811 - imported module-scoped owned pytest fixture
    admin_dsn = normalize_async_dsn(scalar_container.get_connection_url())
    config = Config(str(_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(_ROOT / "alembic"))
    config.set_main_option(
        "sqlalchemy.url", await bootstrapped_application_300_migrator_dsn(admin_dsn)
    )
    with alembic_schema_owner_role():
        await asyncio.to_thread(command.upgrade, config, "411_scoped_feature_write_kernel")
    baseline = [await asyncio.to_thread(_sample, scalar_container, admin_dsn) for _ in range(3)]
    with alembic_schema_owner_role():
        await asyncio.to_thread(command.upgrade, config, "head")
    current = [await asyncio.to_thread(_sample, scalar_container, admin_dsn) for _ in range(3)]
    samples = baseline + current
    assert len({sample["validator_sha256"] for sample in samples}) == 1
    assert len({tuple(sample["role"]) for sample in samples}) == 1
    metrics = (
        "dml_seconds",
        "seal_seconds",
        "commit_seconds",
        "backend_cpu_seconds",
        "backend_rss_max_sampled_bytes",
        "worker_thread_cpu_seconds",
        "after_trigger_context_total_bytes",
        "after_trigger_context_used_bytes",
        "wal_insert_bytes",
    )
    report = {
        "scope": "owned administrator synthetic DB trigger cost; not native collector or ARM",
        "rows_per_relation": _ROWS,
        "repetitions_per_version": 3,
        "baseline_revision": "411_scoped_feature_write_kernel",
        "current_revision": "412_provider_scalar_projection",
        "baseline": baseline,
        "current": current,
        "medians": {
            name: {
                "baseline": statistics.median(sample[name] for sample in baseline),
                "current": statistics.median(sample[name] for sample in current),
            }
            for name in metrics
        },
        "limitations": [
            "SQL server cache is not controlled",
            "backend RSS includes shared pages",
            "WAL is a cluster insert counter",
            "no actual collector or operational performance conclusion",
        ],
        "external_dsn": False,
        "operational_changes": False,
    }
    output = os.environ.get("KTM_SCALAR_OFF_COST_OUTPUT")
    path = Path(output) if output else tmp_path / "scalar-projection-off-cost.json"

    def save_report():
        with path.open("x", encoding="utf-8") as stream:
            json.dump(report, stream, ensure_ascii=False, indent=2)
            stream.write("\n")

    await asyncio.to_thread(save_report)
