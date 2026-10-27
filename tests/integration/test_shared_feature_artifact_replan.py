"""한 Feature의 두 dataset 계획 충돌과 동일 불변 artifact 재계획을 검증한다.

생산 coordinator를 추가하지 않는다. 일반 unbound scalar 계획만 public cancel로 정리하며,
Airport/Rest snapshot binding의 reset/lease 규칙은 우회하지 않는다.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import multiprocessing
import os
import resource
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from kortravelmap.dto import FeatureBundle, PlaceDetail
from kortravelmap.infra import scoped_provider_refresh as native
from kortravelmap.infra.db import make_async_engine
from kortravelmap.infra.feature_repo import _make_source_entity_key
from kortravelmap.infra.provider_field_candidates import (
    arm_provider_field_shadow,
    capture_provider_field_candidates,
)
from kortravelmap.infra.scoped_feature_writes import cancel_scoped_feature_write
from tests.integration.test_provider_snapshot_worker_pair import (
    _cleanup,
    _pidfd_open,
    _process_identity,
    _receive,
    _recv,
    _send,
)
from tests.integration.test_scoped_native_scalar_refresh import _bundle, _plan
from tests.integration.test_scoped_native_scalar_refresh import (
    scalar_container as scalar_container,
)
from tests.integration.test_scoped_native_scalar_refresh import scalar_engines as scalar_engines
from tests.integration.test_state_lifecycle_protocol_entry import (
    owned_scalar_resource_bounds as owned_scalar_resource_bounds,
)

pytestmark = [pytest.mark.integration, pytest.mark.timeout(40)]


def _artifact(bundle):
    # bytes 자체를 child에 한 번 전달한다. 재계획 때 provider/normalizer를 다시 호출하지 않는다.
    # native input digest와 같은 encoder로 frozenset의 process별 hash 순서도 정렬한다.
    return json.dumps(
        bundle,
        default=native._artifact_json_value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()


def _decode_artifact(artifact):
    # ADR-018: Feature.detail은 JSON dict를 직접 받지 않고 typed DTO를 요구한다.
    value = json.loads(artifact)
    assert value["feature"]["kind"] == "place"
    value["feature"]["detail"] = PlaceDetail.model_validate(value["feature"]["detail"])
    return FeatureBundle.model_validate(value)


def _selected_stale(error):
    cause = getattr(error.orig, "__cause__", None)
    return (
        getattr(error.orig, "sqlstate", None) == "40001"
        and getattr(cause, "sqlstate", None) == "40001"
        and getattr(cause, "constraint_name", None) is None
        and getattr(cause, "message", None) == "manifest source changed; replan"
    )


async def _seed_shared(admin, reverse):
    feature = uuid4()
    bundles = [_bundle(uuid4().hex, "winner-" + str(i)) for i in range(2)]
    datasets, entities = [], []
    async with AsyncSession(admin) as session, session.begin():
        await session.execute(text("SELECT ops.lock_scoped_feature_write_protocol(true)"))
        await session.execute(text("SET LOCAL statement_timeout='10s'"))
        await session.execute(
            text("""INSERT INTO feature.features(feature_id,kind,name,category)
            VALUES(:f,'place','before','01010100')"""),
            {"f": feature},
        )
        await session.execute(
            text("""INSERT INTO feature.feature_places(feature_id,kind,place_kind)
            VALUES(:f,'place','tourism')"""),
            {"f": feature},
        )
        old = []
        for index, bundle in enumerate(bundles):
            record = _bundle(bundle.source_record.dataset_key, "before-" + str(index), hours=-24)
            old.append(record)
            source = record.source_record
            entity = _make_source_entity_key(
                provider=source.provider,
                dataset_key=source.dataset_key,
                source_entity_type=source.source_entity_type,
                source_entity_id=source.source_entity_id,
            )
            dataset = await session.scalar(
                text("""INSERT INTO provider_sync.provider_datasets(
                provider,dataset_key,display_name,source_kind)
                VALUES(:p,:k,'shared scalar fixture','manual') RETURNING provider_dataset_id"""),
                {"p": source.provider, "k": source.dataset_key},
            )
            datasets.append(dataset)
            entities.append(entity)
            values = dict(
                f=feature,
                e=entity,
                d=dataset,
                identity=source.source_entity_id,
                r=source.source_record_key,
                raw=json.dumps(source.raw_data),
                h=source.raw_payload_hash,
                at=source.imported_at,
            )
            for sql in [
                """INSERT INTO provider_sync.source_entities(source_entity_key,provider_dataset_id,
                source_entity_type,source_entity_id,first_seen_at,last_seen_at)
                VALUES(:e,:d,'place',:identity,:at,:at)""",
                """INSERT INTO provider_sync.source_records(source_record_key,source_entity_key,
                raw_data,raw_payload_hash,fetched_at) VALUES(:r,:e,CAST(:raw AS jsonb),:h,:at)""",
                """INSERT INTO provider_sync.source_entity_heads(source_entity_key,
                current_source_record_key,observed_at) VALUES(:e,:r,:at)""",
                """INSERT INTO provider_sync.source_links(feature_id,source_entity_key,source_role,
                match_method,confidence) VALUES(:f,:e,'primary','fixture',100)""",
            ]:
                await session.execute(text(sql), values)
            await session.execute(
                text("""CALL feature.register_provider_field_shadow_policy(
                1,:d,'native-v1',CAST(:fields AS jsonb))"""),
                {
                    "d": dataset,
                    "fields": json.dumps(
                        [
                            dict(
                                field_path=field,
                                provider_rank=10 + 10 * index,
                                omitted_policy="carry_forward",
                                null_policy="value",
                            )
                            for field in ["core.name", "place.phones"]
                        ]
                    ),
                },
            )
        arm_provider_field_shadow(session, 1)
        for index in [1, 0] if reverse else [0, 1]:
            bundle = old[index]
            await capture_provider_field_candidates(
                session,
                feature_id=str(feature),
                dataset_id=datasets[index],
                entity_key=entities[index],
                record_key=bundle.source_record.source_record_key,
                values=json.dumps(
                    {"core.name": bundle.feature.name, "place.phones": bundle.feature.detail.phones}
                ),
                geometry_wkt="{}",
                presence=bundle.provider_field_presence,
            )
    async with AsyncSession(admin) as session, session.begin():
        await session.execute(text("SET LOCAL statement_timeout='10s'"))
        await session.execute(text("SET LOCAL lock_timeout='2s'"))
        await session.execute(
            text(
                "CALL feature.activate_provider_field_policy("
                ":f,1,ARRAY['core.name','place.phones'])"
            ),
            {"f": feature},
        )
    return feature, datasets, entities, bundles


async def _child(pipe, profile, request):
    artifact = request["artifact"]
    bundle = _decode_artifact(artifact)
    assert _artifact(bundle) == artifact
    engine = make_async_engine(
        request["dsn"],
        pool_size=1,
        max_overflow=0,
        server_settings={
            "application_name": "ktm-shared-scalar-" + profile,
            "statement_timeout": "3000",
            "lock_timeout": "1000",
        },
    )
    original = native._upsert_source_record_state
    writes, held = 0, False

    async def source(session, record):
        nonlocal writes, held
        writes += 1
        result = await original(session, record)
        if request["leader"] and not held:
            held = True
            _send(pipe, {"stage": "held", "profile": profile})
            await _receive(pipe, "release", profile)
        return result

    native._upsert_source_record_state = source
    try:
        plan = await _plan(engine, request["feature"], request["dataset"], bundle)
        _send(
            pipe,
            {
                "stage": "planned",
                "profile": profile,
                "plan": plan,
                "artifact_sha": hashlib.sha256(artifact).hexdigest(),
            },
        )
        await _receive(pipe, "apply", profile)
        try:
            async with AsyncSession(engine) as session, session.begin():
                backend = tuple(
                    (
                        await session.execute(
                            text("""SELECT pg_backend_pid(),
                backend_start,usename FROM pg_stat_activity WHERE pid=pg_backend_pid()""")
                        )
                    ).one()
                )
                xid = await session.scalar(text("SELECT txid_current()"))
                _send(
                    pipe,
                    {"stage": "backend", "profile": profile, "backend": backend, "xid": xid},
                )
                receipt = await native.refresh_scoped_provider_scalars(session, bundle, **plan)
        except DBAPIError as error:
            if request["leader"] or not _selected_stale(error):
                raise
            assert not session.in_transaction()
            assert writes == 0
            _send(
                pipe,
                {
                    "stage": "stale",
                    "profile": profile,
                    "xid": xid,
                    "sqlstate": error.orig.sqlstate,
                    "source_writes": writes,
                },
            )
            # 부모가 unbound READY와 실제 aborted TX를 확인한 뒤에만 일반 public cancel.
            await _receive(pipe, "cancel", profile)
            async with AsyncSession(engine) as session, session.begin():
                assert await cancel_scoped_feature_write(
                    session, attempt_id=plan["attempt_id"], owner=plan["owner"]
                )
            _send(pipe, {"stage": "cancelled", "profile": profile})
            await _receive(pipe, "replan", profile)
            assert _artifact(bundle) == artifact
            plan = await _plan(engine, request["feature"], request["dataset"], bundle)
            _send(
                pipe,
                {
                    "stage": "replanned",
                    "profile": profile,
                    "plan": plan,
                    "artifact_sha": hashlib.sha256(artifact).hexdigest(),
                },
            )
            await _receive(pipe, "apply", profile)
            async with AsyncSession(engine) as session, session.begin():
                receipt = await native.refresh_scoped_provider_scalars(session, bundle, **plan)
        _send(
            pipe,
            {"stage": "committed", "profile": profile, "receipt": receipt, "source_writes": writes},
        )
        await _receive(pipe, "replay", profile)
        previous = writes
        async with AsyncSession(engine) as session, session.begin():
            replay = await native.refresh_scoped_provider_scalars(session, bundle, **plan)
        assert writes == previous == 1
        assert _artifact(bundle) == artifact
        assert replay["result_digest"] == receipt["result_digest"]
        _send(
            pipe,
            {
                "stage": "replayed",
                "profile": profile,
                "result_digest": replay["result_digest"],
                "source_writes": writes,
            },
        )
    finally:
        native._upsert_source_record_state = original
        async with asyncio.timeout(5):
            await engine.dispose()


async def _bounded_child(pipe, profile, request):
    async with asyncio.timeout(30):
        await _child(pipe, profile, request)


def _worker(pipe, profile, parent_pid):
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    resource.setrlimit(resource.RLIMIT_CPU, (20, 20))
    resource.setrlimit(resource.RLIMIT_AS, (1536 * 1024**2, 1536 * 1024**2))
    try:
        assert Path(native.__file__).resolve().parents[3] == Path(__file__).resolve().parents[2]
        parent, started = _process_identity(os.getpid())
        assert parent == parent_pid
        _send(
            pipe,
            dict(
                stage="started",
                profile=profile,
                pid=os.getpid(),
                parent_pid=parent,
                starttime=started,
            ),
        )
        if not pipe.poll(12):
            raise TimeoutError("owned shared scalar request deadline")
        asyncio.run(_bounded_child(pipe, profile, _recv(pipe)))
    except BaseException as error:
        try:
            _send(pipe, dict(stage="error", profile=profile, error_class=type(error).__name__))
        finally:
            os._exit(1)
    finally:
        pipe.close()


async def _scope_blocker(admin, blocked, holder, first_dataset):
    # leader는 source DML 직후 finish 전에 정지: scope의 기존 ctid는 아직 바뀌지 않는다.
    pid, started, login = blocked["backend"]
    holder_pid, holder_start, holder_login = holder["backend"]
    async with asyncio.timeout(0.8), AsyncSession(admin) as session:
        while True:
            async with session.begin():
                await session.execute(text("SET TRANSACTION READ ONLY"))
                await session.execute(text("SET LOCAL statement_timeout='300ms'"))
                row = (
                    await session.execute(
                        text("""SELECT a.wait_event_type,a.wait_event,
                pg_blocking_pids(a.pid),
                a.query LIKE 'SELECT ops.begin_scoped_feature_write%',
                EXISTS(SELECT 1 FROM pg_locks l WHERE l.pid=a.pid AND NOT l.granted
                  AND l.locktype='transactionid' AND l.transactionid::text=:xid),
                EXISTS(SELECT 1 FROM pg_stat_activity h WHERE h.pid=:holder
                  AND h.backend_start=:hs AND h.usename=:hl AND h.backend_xid::text=:xid
                  AND h.state='idle in transaction'),
                EXISTS(SELECT 1 FROM pg_locks l JOIN ops.feature_write_dataset_scopes s
                  ON s.provider_dataset_id=:dataset AND s.ctid::text=
                    '('||l.page::text||','||l.tuple::text||')'
                  WHERE l.pid=a.pid AND l.locktype='tuple' AND l.granted
                    AND l.relation='ops.feature_write_dataset_scopes'::regclass)
                FROM pg_stat_activity a WHERE a.pid=:pid AND a.backend_start=:started
                  AND a.usename=:login"""),
                        dict(
                            pid=pid,
                            started=started,
                            login=login,
                            holder=holder_pid,
                            hs=holder_start,
                            hl=holder_login,
                            xid=str(holder["xid"]),
                            dataset=first_dataset,
                        ),
                    )
                ).one()
            if row[0] == "Lock":
                assert row[2] == [holder_pid]
                assert all(row[i] is True for i in (3, 4, 5, 6))
                return row[1]
            await asyncio.sleep(0.005)


async def _attempt(admin, plan):
    async with AsyncSession(admin) as session, session.begin():
        await session.execute(text("SET LOCAL statement_timeout='3s'"))
        return dict(
            (
                await session.execute(
                    text("""SELECT status,apply_txid,idempotency_key,
        input_digest,manifest_digest,result_digest FROM ops.feature_write_attempts
        WHERE attempt_id=:a"""),
                    {"a": plan["attempt_id"]},
                )
            )
            .mappings()
            .one()
        )


async def _scopes(admin, datasets):
    async with AsyncSession(admin) as session, session.begin():
        await session.execute(text("SET LOCAL statement_timeout='3s'"))
        return [
            tuple(row)
            for row in (
                await session.execute(
                    text("""SELECT
        provider_dataset_id,epoch,owner,lease_until FROM ops.feature_write_dataset_scopes
        WHERE provider_dataset_id=ANY(:datasets) ORDER BY provider_dataset_id"""),
                    {"datasets": datasets},
                )
            ).all()
        ]


@pytest.mark.parametrize("leader_index", [0, 1], ids=["rank-winner-first", "rank-loser-first"])
async def test_shared_feature_stale_plan_reuses_identical_artifact_after_full_rollback(
    scalar_engines, leader_index, request
):
    admin, runtime = scalar_engines
    feature, datasets, entities, bundles = await _seed_shared(admin, reverse=bool(leader_index))
    leader, follower = str(leader_index), str(1 - leader_index)
    profiles = ["0", "1"]
    context = multiprocessing.get_context("spawn")
    workers, pipes, identities, pidfds, plans, backend = {}, {}, {}, {}, {}, {}
    primary = None
    try:
        for profile in profiles:
            parent_pipe, child_pipe = context.Pipe()
            pipes[profile] = parent_pipe, child_pipe
            process = context.Process(target=_worker, args=(child_pipe, profile, os.getpid()))
            workers[profile] = process
            process.start()
            child_pipe.close()
            identities[profile] = _process_identity(process.pid)
            assert identities[profile][0] == os.getpid()
            pidfds[profile] = _pidfd_open(process.pid)
        for profile in profiles:
            started = await _receive(pipes[profile][0], "started", profile, poll_seconds=12)
            assert (started["parent_pid"], started["starttime"]) == identities[profile]
            assert started["pid"] == workers[profile].pid
            index = int(profile)
            _send(
                pipes[profile][0],
                dict(
                    feature=feature,
                    dataset=datasets[index],
                    artifact=_artifact(bundles[index]),
                    dsn=runtime.url.render_as_string(False),
                    leader=profile == leader,
                ),
            )
        for profile in profiles:
            value = await _receive(pipes[profile][0], "planned", profile)
            assert (
                value["artifact_sha"]
                == hashlib.sha256(_artifact(bundles[int(profile)])).hexdigest()
            )
            plans[profile] = value["plan"]
        assert workers[leader].pid != workers[follower].pid
        old = await _attempt(admin, plans[follower])
        for profile in (leader, follower):
            _send(pipes[profile][0], dict(stage="apply", profile=profile))
            backend[profile] = await _receive(pipes[profile][0], "backend", profile)
            if profile == leader:
                await _receive(pipes[profile][0], "held", profile)
        assert backend[leader]["backend"] != backend[follower]["backend"]
        assert backend[leader]["xid"] != backend[follower]["xid"]
        wait = await _scope_blocker(admin, backend[follower], backend[leader], min(datasets))
        _send(pipes[leader][0], dict(stage="release", profile=leader))
        receipts = {leader: await _receive(pipes[leader][0], "committed", leader)}
        stale = await _receive(pipes[follower][0], "stale", follower)
        assert stale["sqlstate"] == "40001"
        assert stale["source_writes"] == 0
        after_stale = await _attempt(admin, plans[follower])
        assert after_stale == old
        assert after_stale["status"] == "ready"
        async with AsyncSession(admin) as observer, observer.begin():
            await observer.execute(text("SET LOCAL statement_timeout='3s'"))
            assert (
                await observer.scalar(
                    text("SELECT pg_xact_status(CAST(:xid AS xid8))"), {"xid": stale["xid"]}
                )
                == "aborted"
            )
            assert (
                await observer.scalar(
                    text("""SELECT count(*) FROM
            ops.provider_snapshot_controls WHERE attempt_id=:a"""),
                    {"a": plans[follower]["attempt_id"]},
                )
                == 0
            )
            assert (
                await observer.scalar(
                    text("""SELECT count(*) FROM provider_sync.source_records
            WHERE source_record_key=:r"""),
                    {"r": bundles[int(follower)].source_record.source_record_key},
                )
                == 0
            )
        scopes = await _scopes(admin, datasets)
        _send(pipes[follower][0], dict(stage="cancel", profile=follower))
        await _receive(pipes[follower][0], "cancelled", follower)
        cancelled_scopes = await _scopes(admin, datasets)
        assert (await _attempt(admin, plans[follower]))["status"] == "cancelled"
        for before, after in zip(scopes, cancelled_scopes, strict=True):
            if before[0] == datasets[int(follower)]:
                assert before[2] == plans[follower]["attempt_id"]
                assert after[:2] == before[:2]
                assert after[2:] == (None, None)
            else:
                assert before == after
        original_plan = plans[follower]
        _send(pipes[follower][0], dict(stage="replan", profile=follower))
        replanned = await _receive(pipes[follower][0], "replanned", follower)
        plans[follower] = replanned["plan"]
        fresh = await _attempt(admin, plans[follower])
        assert plans[follower]["attempt_id"] != original_plan["attempt_id"]
        assert fresh["idempotency_key"] != old["idempotency_key"]
        assert fresh["input_digest"] == old["input_digest"]
        assert fresh["manifest_digest"] != old["manifest_digest"]
        assert (
            replanned["artifact_sha"]
            == hashlib.sha256(_artifact(bundles[int(follower)])).hexdigest()
        )
        _send(pipes[follower][0], dict(stage="apply", profile=follower))
        receipts[follower] = await _receive(pipes[follower][0], "committed", follower)
        for profile in profiles:
            _send(pipes[profile][0], dict(stage="replay", profile=profile))
            replay = await _receive(pipes[profile][0], "replayed", profile)
            assert receipts[profile]["source_writes"] == replay["source_writes"] == 1
            actual = await _attempt(admin, plans[profile])
            assert actual["status"] == "completed"
            assert actual["result_digest"] == receipts[profile]["receipt"]["result_digest"]
            assert replay["result_digest"] == actual["result_digest"]
        async with AsyncSession(admin) as session, session.begin():
            await session.execute(text("SET LOCAL statement_timeout='3s'"))
            assert (
                await session.scalar(
                    text("SELECT name FROM feature.features WHERE feature_id=:f"), {"f": feature}
                )
                == "winner-0"
            )
            bases = (
                await session.execute(
                    text("""SELECT field_path,provider_dataset_id,
            source_entity_key,source_record_key,source_raw_payload_hash FROM
            feature.feature_base_field_values WHERE feature_id=:f ORDER BY field_path"""),
                    {"f": feature},
                )
            ).all()
            assert len(bases) == 2
            for row in bases:
                assert tuple(row[1:]) == (
                    datasets[0],
                    entities[0],
                    bundles[0].source_record.source_record_key,
                    bundles[0].source_record.raw_payload_hash,
                )
            links = (
                await session.execute(
                    text("""SELECT l.source_entity_key,l.source_role,
            l.match_method,l.confidence,h.current_source_record_key
            FROM provider_sync.source_links l
            JOIN provider_sync.source_entity_heads h USING(source_entity_key)
            WHERE feature_id=:f ORDER BY l.source_entity_key"""),
                    {"f": feature},
                )
            ).all()
            expected = sorted(
                (entities[i], "primary", "fixture", 100, bundles[i].source_record.source_record_key)
                for i in range(2)
            )
            assert [tuple(row) for row in links] == expected
        request.node.user_properties.append(
            (
                "shared_feature_replan",
                json.dumps(
                    dict(
                        leader=leader,
                        initial_capture_order=[1, 0] if leader_index else [0, 1],
                        worker_pids={p: workers[p].pid for p in profiles},
                        pool_per_child=1,
                        exact_participant_scope_wait=wait,
                        selected_sqlstate="40001",
                        apply_tx="aborted",
                        same_artifact=True,
                        new_attempt_and_key=True,
                        completed_replay_source_dml=0,
                        operating_cpu_rss="not measured",
                        production_coordinator="not implemented",
                    ),
                    sort_keys=True,
                ),
            )
        )
    except BaseException as error:
        primary = error
        raise
    finally:
        cleanup_error = await _cleanup(workers, pipes, identities, pidfds, primary)
        # 자식 회수 후 자신의 generic 계획만 public cancel한다. binding은 생성하지 않는다.
        for plan in plans.values():
            try:
                async with AsyncSession(runtime) as session, session.begin():
                    await cancel_scoped_feature_write(
                        session, attempt_id=plan["attempt_id"], owner=plan["owner"]
                    )
            except BaseException as error:
                if cleanup_error is None:
                    cleanup_error = error
                else:
                    cleanup_error.add_note(
                        "owned shared-plan cleanup failed: " + type(error).__name__
                    )
        if primary is None and cleanup_error is not None:
            raise cleanup_error
