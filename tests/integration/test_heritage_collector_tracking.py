"""실제 heritage asset→client→EX/legacy→후속 receipt 경계. worker 실행은 아니다."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4
from zoneinfo import ZoneInfo

import httpx
import pytest
from dagster import DagsterRunStatus
from kortravelmap.dagster.assets import run_feature_place_krheritage_items
from kortravelmap.dagster.feature_operation_sensors import _apply_run_record
from kortravelmap.dagster.feature_operation_tracking import (
    _guard_from_context_async,
    run_tracked_feature_asset,
)
from kortravelmap.dagster.provider_fetchers import fetch_krheritage_items
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

import kortravelmap.client as client_module
from kortravelmap.client import AsyncKorTravelMapClient
from kortravelmap.dto import Address
from kortravelmap.dto import _time as dto_time
from kortravelmap.dto.geo_dataset import DatasetRef
from kortravelmap.geocoding import GeoCallStats
from kortravelmap.infra import exclusive_provider_refresh as full
from kortravelmap.infra import feature_repo
from kortravelmap.infra.application_schema_head import application_schema_head
from kortravelmap.infra.db import make_async_engine
from kortravelmap.providers.feature_operation_registry import resolve_feature_operation_handler
from kortravelmap.providers.krheritage import (
    DATASET_KEY_HERITAGE,
    PROVIDER_NAME,
    heritage_items_to_bundles,
)
from kortravelmap.settings import KorTravelMapSettings
from tests.integration.test_canonical_provider_operations import (
    _resource_init_context,
    _tracking_context,
    _tracking_record,
)
from tests.integration.test_provider_field_scalar_projection import (
    scalar_container as scalar_container,
)
from tests.integration.test_provider_field_scalar_projection import (
    scalar_engines as scalar_engines,
)
from tests.integration.test_scoped_provider_batch import _seed_bundles

pytestmark = pytest.mark.integration
_AT = datetime(2026, 10, 24, 12, tzinfo=ZoneInfo("Asia/Seoul"))
_OPERATION = "feature_place_krheritage_items_job"


class _Geo:
    """정본 Geo 계약의 고정 대역이며 실제 Geo HTTP를 호출하지 않는다."""

    async def __call__(self, _coordinate):
        return Address(
            legal="서울특별시 종로구",
            bjd_code="1111010100",
            sigungu_code="11110",
            sido_code="11",
            sido_name="서울특별시",
            sigungu_name="종로구",
        )

    async def current(self):
        return DatasetRef(version_token="dv1-" + "a" * 32, data_token="dd1-" + "1" * 32)


class _ObservedGeo(_Geo):
    """EX 시험은 고정 Geo 응답의 관측 토큰까지 정본 stats 계약으로 남긴다."""

    def __init__(self):
        self.stats = GeoCallStats()

    async def __call__(self, coordinate):
        address = await super().__call__(coordinate)
        self.stats.record("reverse", failed=False)
        self.stats.observe_dataset(await self.current())
        return address


async def _readonly(engine, sql, params=None):
    async with AsyncSession(engine) as session, session.begin():
        await session.execute(text("SET TRANSACTION READ ONLY"))
        await session.execute(text("SET LOCAL statement_timeout='3s'"))
        await session.execute(text("SET LOCAL lock_timeout='1s'"))
        return (await session.execute(text(sql), params or {})).mappings().all()


async def _tree(admin, run_id):
    rows = await _readonly(
        admin,
        """
        SELECT job.job_id::text, job.parent_job_id::text, job.kind, job.status,
               member.provider_dataset_id, member.sync_scope, member.operation_key
        FROM ops.import_jobs job
        LEFT JOIN ops.import_job_datasets member ON member.job_id=job.job_id
        WHERE job.dagster_run_id=:run ORDER BY job.parent_job_id NULLS FIRST,job.job_id
    """,
        {"run": run_id},
    )
    assert len(rows) == 2
    return rows


@pytest.fixture
async def collector_client(scalar_engines, scalar_container, request):
    """setup 도중 실패해도 pool1 전용 engine을 반드시 반납한다."""
    admin, fixture_runtime = scalar_engines
    wrapped = scalar_container.get_wrapped_container()
    wrapped.reload()
    attrs = wrapped.attrs
    label = attrs["Config"]["Labels"]["codex.scalar-projection"]
    assert attrs["Name"] == "/kt-map-scalar-" + label
    assert attrs["HostConfig"]["NanoCpus"] == 2_000_000_000
    assert attrs["HostConfig"]["Memory"] == attrs["HostConfig"]["MemorySwap"] == 1536 * 1024**2
    assert attrs["HostConfig"]["PidsLimit"] == 256
    request.node.user_properties.extend(
        [
            ("owned_pg_id", attrs["Id"]),
            ("owned_pg_name", attrs["Name"]),
            ("owned_pg_label", label),
            ("owned_pg_image_id", attrs["Image"]),
        ]
    )
    head = await _readonly(admin, "SELECT version_num FROM alembic_version")
    assert [row["version_num"] for row in head] == [application_schema_head()]
    request.node.user_properties.append(("actual_schema", head[0]["version_num"]))
    runtime = make_async_engine(
        fixture_runtime.url.render_as_string(hide_password=False),
        pool_size=1,
        max_overflow=0,
    )
    try:
        yield admin, runtime, AsyncKorTravelMapClient(runtime)
    finally:
        await runtime.dispose()
        rows = await _readonly(
            admin,
            """
            SELECT count(*) AS count FROM pg_stat_activity
            WHERE datname=current_database() AND usename=:runtime_role
        """,
            {"runtime_role": runtime.url.username},
        )
        assert rows[0]["count"] == 0
        request.node.user_properties.append(("runtime_backend_count_after_dispose", 0))


@pytest.mark.parametrize(
    ("exclusive", "drift_before_seal"),
    [(False, False), (False, True), (True, False), (True, True)],
    ids=["legacy-seal", "legacy-seal-drift", "exclusive-seal", "exclusive-apply-rollback"],
)
async def test_real_heritage_asset_tracking_and_serializable_seal(
    collector_client,
    monkeypatch,
    drift_before_seal,
    exclusive,
):
    """load commit→sync commit→별도 SERIALIZABLE seal. 후속 실패가 앞 commit을 지우지 않는다."""
    sdk = pytest.importorskip("krheritage", reason="pinned public SDK required")
    admin, runtime, client = collector_client
    if exclusive:
        # scope-only 설정은 정본 provider 식별자이며 최종 input/Geo/clock Plan이 아니다.
        client = AsyncKorTravelMapClient(
            runtime,
            exclusive_provider_snapshot=full.ExclusiveProviderSnapshotOptions(
                PROVIDER_NAME, DATASET_KEY_HERITAGE, "heritage"
            ),
        )
    identity = uuid4().hex
    run_id = str(uuid4())
    keys = [str((int(identity[:12], 16) + index) % 10**13).zfill(13) for index in range(2)]
    names = [f"collector-{identity}-{index}" for index in range(2)]
    clock = SimpleNamespace(now=_AT, changed=False)

    class _FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return clock.now.astimezone(tz) if tz is not None else clock.now.replace(tzinfo=None)

    monkeypatch.setattr(dto_time, "datetime", _FrozenDatetime)
    init = _resource_init_context(
        client,
        run_id=run_id,
        tags={"kor_travel_map.operation_key": _OPERATION, "kor_travel_map.trigger_kind": "manual"},
    )
    init.run.job_name = resolve_feature_operation_handler(_OPERATION).job_name
    guard = await _guard_from_context_async(init)
    assert len(guard.memberships) == 1
    await guard.ensure()
    member = guard.memberships[0]
    initial = await _tree(admin, run_id)
    assert initial[0]["status"] == initial[1]["status"] == "running"
    assert initial[1]["provider_dataset_id"] == member.provider_dataset_id
    assert initial[1]["sync_scope"] == member.sync_scope == "dataset_wide"
    assert initial[1]["operation_key"] == _OPERATION
    root_id, child_id = initial[0]["job_id"], initial[1]["job_id"]
    if not exclusive:
        assert not await _readonly(admin, "SELECT 1 FROM feature.provider_field_active_policies")

    phases = []
    requests = []
    sessions, sdk_clients = [], []
    original_sdk = sdk.HeritageClient

    async def handler(request):
        # 요청 전에 authoritative root/child가 실제 DB에 있어야 한다.
        tree = await _tree(admin, run_id)
        assert tree[0]["status"] == tree[1]["status"] == "running"
        query = dict(request.url.params)
        assert request.method == "GET"
        path = request.url.path
        if path.endswith("/SearchKindOpenapiList.do"):
            assert query == {"pageUnit": "100", "pageIndex": "1", "ccbaKdcd": "11"}
            requests.append("list")
            items = "".join(
                f"<item><ccbaKdcd>11</ccbaKdcd><ccbaAsno>{key}</ccbaAsno>"
                f"<ccbaCtcd>11</ccbaCtcd><ccbaMnm1>{name}</ccbaMnm1></item>"
                for key, name in zip(keys, names, strict=True)
            )
            body = (
                "<result><totalCnt>2</totalCnt><pageIndex>1</pageIndex>"
                f"<pageUnit>100</pageUnit>{items}</result>"
            )
        elif path.endswith("/SearchKindOpenapiDt.do"):
            assert set(query) == {"ccbaKdcd", "ccbaAsno", "ccbaCtcd"}
            assert query["ccbaKdcd"] == query["ccbaCtcd"] == "11"
            index = keys.index(query["ccbaAsno"])
            requests.append("detail")
            name = names[index] + ("-changed" if clock.changed else "")
            body = (
                f"<result><ccbaKdcd>11</ccbaKdcd><ccbaAsno>{keys[index]}</ccbaAsno>"
                "<ccbaCtcd>11</ccbaCtcd><longitude>127.0</longitude><latitude>37.5</latitude>"
                f"<item><ccbaMnm1>{name}</ccbaMnm1><ccmaName>문화유산</ccmaName>"
                "<ccbaLcad>서울특별시 종로구</ccbaLcad></item></result>"
            )
        else:
            raise AssertionError("unplanned provider HTTP")
        return httpx.Response(200, content=body.encode())

    def sdk_factory():
        http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        sessions.append(http)
        real = original_sdk(session=http)
        sdk_clients.append(real)
        return real

    monkeypatch.setattr(sdk, "HeritageClient", sdk_factory)
    settings = KorTravelMapSettings(krheritage_kind_codes="11", krheritage_max_items_per_run=10)
    context = _tracking_context(guard, retry_number=0)
    geo = _ObservedGeo() if exclusive else _Geo()
    context.log = logging.getLogger(__name__)
    metadata = []
    context.add_output_metadata = lambda value: metadata.append(value)
    context.resources.reverse_geocoder = geo
    context.resources.kor_travel_geo_dataset = geo
    context.resources.fetched_at = _AT
    context.resources.strict_address = "strict"
    observed_natural_keys = []

    async def records():
        async for row in fetch_krheritage_items(settings):
            observed_natural_keys.append(row.key.natural_key)
            yield row

    if exclusive:
        # seed도 public SDK→정본 converter→실제 legacy loader/candidate/cutover를 거친다.
        # 미래 최종 bundle을 미리 Plan으로 주입하지 않는다.
        seed_rows = [row async for row in fetch_krheritage_items(settings)]
        seed_bundles = await heritage_items_to_bundles(
            seed_rows, fetched_at=_AT, reverse_geocoder=geo
        )
        dataset, seeded = await _seed_bundles(admin, runtime, seed_bundles, seed_bundles)
        assert dataset == member.provider_dataset_id
        assert len(seeded) == 2
        record = seed_bundles[0].source_record
        assert (record.provider, record.dataset_key, record.source_entity_type) == (
            PROVIDER_NAME,
            DATASET_KEY_HERITAGE,
            "heritage",
        )
        clock.changed, clock.now = True, _AT + timedelta(minutes=1)
        context.resources.fetched_at = clock.now
        requests.clear()
    context.resources.krheritage_items = records()
    capture = client_module.capture_provider_curation_input
    sync = client_module.repo_record_operation_success
    finish_repo = client_module.repo_finish_dagster_feature_membership
    real_finish = client.finish_dagster_feature_membership
    captures, finish_isolation = [], []
    plans, planning_states, apply_states = [], [], []
    prepare = client_module.prepare_exclusive_provider_snapshot
    apply = client_module.refresh_exclusive_provider_snapshot
    actual_source_write = feature_repo._upsert_source_record_state
    source_writes = []

    async def tx_state(session):
        return (
            (
                await session.execute(
                    text(
                        "SELECT current_setting('transaction_isolation') AS isolation, "
                        "txid_current() AS txid"
                    )
                )
            )
            .mappings()
            .one()
        )

    async def prepare_probe(session, bundles, **kwargs):
        state = await tx_state(session)
        assert state["isolation"] == "read committed"
        assert runtime.pool.checkedout() == 1
        assert len(bundles) == 2
        assert all(b.feature.name.endswith("-changed") for b in bundles)
        assert all(b.feature.address.bjd_code == "1111010100" for b in bundles)
        assert all((b.feature.coord.lon, b.feature.coord.lat) == (127.0, 37.5) for b in bundles)
        assert kwargs["geo"].current_dataset == await geo.current()
        assert kwargs["geo"].geo_applied.reverse is True
        assert kwargs["geo"].effective_token() == (await geo.current()).data_token
        assert kwargs["retire_geometryless_areas"] is True
        plan = await prepare(session, bundles, **kwargs)
        assert plan is not None
        plans.append(plan)
        planning_states.append(state)
        phases.append("prepare")
        return plan

    async def apply_probe(session, bundles, **kwargs):
        state = await tx_state(session)
        assert state["isolation"] == "read committed"
        assert state["txid"] != planning_states[0]["txid"]
        assert runtime.pool.checkedout() == 1
        apply_states.append(state)
        result = await apply(session, bundles, **kwargs)
        assert result.replayed is False
        assert result.attempt["status"] == "completed"
        phases.append("apply")
        return result

    async def source_write_probe(session, record):
        result = await actual_source_write(session, record)
        source_writes.append(record.source_record_key)
        modes = (
            (
                await session.execute(
                    text("""
            SELECT mode FROM pg_locks WHERE pid=pg_backend_pid() AND locktype='advisory'
              AND granted AND classid=1369104691::oid AND objid=115::oid AND objsubid=2
        """)
                )
            )
            .scalars()
            .all()
        )
        assert modes == ["ExclusiveLock"]
        assert (await tx_state(session))["txid"] == apply_states[0]["txid"]
        if exclusive and drift_before_seal and len(source_writes) == 2:
            raise RuntimeError("owned actual asset second source DML failure")
        return result

    async def capture_probe(session, **kwargs):
        state = (
            (
                await session.execute(
                    text(
                        "SELECT current_setting('transaction_isolation') AS isolation, "
                        "txid_current() AS txid"
                    )
                )
            )
            .mappings()
            .one()
        )
        result = await capture(session, **kwargs)
        assert state["isolation"] == "read committed"
        captures.append((state["txid"], result))
        phases.append("capture")
        return result

    async def sync_probe(session, **kwargs):
        result = await sync(session, **kwargs)
        phases.append("sync")
        return result

    async def finish_probe(session, **kwargs):
        # client가 SET TRANSACTION을 실행한 뒤에만 실제 Session을 관측한다.
        state = (
            (
                await session.execute(
                    text(
                        "SELECT current_setting('transaction_isolation') AS isolation, "
                        "txid_current() AS txid"
                    )
                )
            )
            .mappings()
            .one()
        )
        finish_isolation.append(state)
        phases.append("finish")
        return await finish_repo(session, **kwargs)

    async def before_finish(**kwargs):
        if drift_before_seal:
            # load/sync는 이미 commit됐다. 원 client의 실제 writer로 새 head를 전진시킨다.
            assert phases == ["capture", "sync"]
            clock.changed, clock.now = True, _AT + timedelta(minutes=1)
            rows = [row async for row in fetch_krheritage_items(settings)]
            bundles = await heritage_items_to_bundles(
                rows, fetched_at=clock.now, reverse_geocoder=geo
            )
            await client.load_feature_bundles(bundles)
            phases.append("separate_writer")
        return await real_finish(**kwargs)

    monkeypatch.setattr(client_module, "capture_provider_curation_input", capture_probe)
    if exclusive:
        monkeypatch.setattr(feature_repo, "capture_provider_curation_input", capture_probe)
        monkeypatch.setattr(client_module, "prepare_exclusive_provider_snapshot", prepare_probe)
        monkeypatch.setattr(client_module, "refresh_exclusive_provider_snapshot", apply_probe)
        monkeypatch.setattr(feature_repo, "_upsert_source_record_state", source_write_probe)
    monkeypatch.setattr(client_module, "repo_record_operation_success", sync_probe)
    monkeypatch.setattr(client_module, "repo_finish_dagster_feature_membership", finish_probe)
    monkeypatch.setattr(client, "finish_dagster_feature_membership", before_finish)
    try:
        if exclusive and drift_before_seal:
            sync_before = await _readonly(
                admin,
                "SELECT cursor FROM provider_sync.provider_sync_state "
                "WHERE provider_dataset_id=:id",
                {"id": member.provider_dataset_id},
            )
            with pytest.raises(RuntimeError, match="actual asset second source DML"):
                await run_tracked_feature_asset(context, run_feature_place_krheritage_items)
            assert phases == ["prepare"]
            assert len(plans) == len(apply_states) == 1
            assert len(source_writes) == 2
            assert not captures
            assert not finish_isolation
            attempts = await _readonly(
                admin,
                "SELECT status,result_digest FROM ops.feature_write_attempts WHERE attempt_id=:id",
                {"id": plans[0].attempt_id},
            )
            assert [dict(row) for row in attempts] == [
                {"status": "cancelled", "result_digest": None}
            ]
            stored = await _readonly(
                admin,
                """
                SELECT f.name,r.fetched_at FROM feature.features f
                JOIN provider_sync.source_links l USING(feature_id)
                JOIN provider_sync.source_entity_heads h USING(source_entity_key)
                JOIN provider_sync.source_records r
                  ON r.source_record_key=h.current_source_record_key
                WHERE f.feature_id=ANY(CAST(:ids AS uuid[])) ORDER BY f.name
            """,
                {"ids": [item.feature_id for item in seeded]},
            )
            assert sorted(row["name"] for row in stored) == sorted(names)
            assert all(row["fetched_at"] == _AT for row in stored)
            assert not await _readonly(
                admin,
                "SELECT 1 FROM provider_sync.source_records "
                "WHERE source_record_key=ANY(CAST(:keys AS text[]))",
                {"keys": source_writes},
            )
            candidate_rows = await _readonly(
                admin,
                "SELECT value_json FROM feature.provider_field_shadow_candidates "
                "WHERE feature_id=ANY(CAST(:ids AS uuid[])) AND field_path='core.name'",
                {"ids": [item.feature_id for item in seeded]},
            )
            assert sorted(row["value_json"] for row in candidate_rows) == sorted(names)
            assert (
                await _readonly(
                    admin,
                    "SELECT cursor FROM provider_sync.provider_sync_state "
                    "WHERE provider_dataset_id=:id",
                    {"id": member.provider_dataset_id},
                )
                == sync_before
            )
            assert not await _readonly(
                admin,
                "SELECT 1 FROM ops.curation_provider_snapshot_receipts "
                "WHERE source_job_id=CAST(:id AS uuid)",
                {"id": child_id},
            )
            assert not await _readonly(
                admin,
                "SELECT 1 FROM ops.curation_provider_root_receipts "
                "WHERE root_job_id=CAST(:id AS uuid)",
                {"id": root_id},
            )
            tree = await _tree(admin, run_id)
            assert tree[0]["status"] == tree[1]["status"] == "running"
            assert requests == ["list", "detail", "detail"]
            assert all(instance.closed for instance in sdk_clients)
            assert runtime.pool.checkedout() == 0
            return
        if drift_before_seal:
            with pytest.raises(DBAPIError) as error:
                await run_tracked_feature_asset(context, run_feature_place_krheritage_items)
            assert getattr(error.value.orig, "sqlstate", None) == "23514"
            assert (
                error.value.orig.__cause__.constraint_name
                == "ck_tvn40_provider_snapshot_load_input"
            )
        else:
            result = await run_tracked_feature_asset(context, run_feature_place_krheritage_items)
            assert result.observation_receipt.authoritative_snapshot_complete is True
            assert result.load.bundles_total == 2
            assert result.load.features_inserted == (0 if exclusive else 2)
            if exclusive:
                assert len(plans) == len(apply_states) == 1
                assert len(source_writes) == 2
                assert result.load.geo_stamps_written == 2
                candidate_rows = await _readonly(
                    admin,
                    "SELECT value_json FROM feature.provider_field_shadow_candidates "
                    "WHERE feature_id=ANY(CAST(:ids AS uuid[])) AND field_path='core.name'",
                    {"ids": [item.feature_id for item in seeded]},
                )
                assert sorted(row["value_json"] for row in candidate_rows) == sorted(
                    name + "-changed" for name in names
                )
            assert metadata
        assert phases == (
            ["capture", "sync", "separate_writer", "finish"]
            if drift_before_seal
            else (
                ["prepare", "capture", "apply", "sync", "finish"]
                if exclusive
                else ["capture", "sync", "finish"]
            )
        )
        assert len(captures) == len(finish_isolation) == 1
        assert finish_isolation[0]["isolation"] == "serializable"
        assert captures[0][0] != finish_isolation[0]["txid"]
        if exclusive:
            assert captures[0][0] == apply_states[0]["txid"]
            assert captures[0][0] != planning_states[0]["txid"]
        assert requests == (["list", "detail", "detail"] * (2 if drift_before_seal else 1))
        assert all(instance.closed for instance in sdk_clients)
        stored = await _readonly(
            admin,
            """
            SELECT feature.name,record.fetched_at,head.observed_at,record.raw_data
            FROM provider_sync.source_entities entity
            JOIN provider_sync.source_entity_heads head USING(source_entity_key)
            JOIN provider_sync.source_records record
              ON record.source_record_key=head.current_source_record_key
            JOIN provider_sync.source_links link ON link.source_entity_key=entity.source_entity_key
            JOIN feature.features feature ON feature.feature_id=link.feature_id
            WHERE entity.provider_dataset_id=:dataset
              AND entity.source_entity_id=ANY(CAST(:keys AS text[]))
            ORDER BY entity.source_entity_id COLLATE "C"
        """,
            {"dataset": member.provider_dataset_id, "keys": observed_natural_keys},
        )
        assert len(stored) == 2
        assert sorted(row["name"] for row in stored) == sorted(
            name + ("-changed" if drift_before_seal or exclusive else "") for name in names
        )
        assert all(row["fetched_at"] == row["observed_at"] == clock.now for row in stored)
        sync_rows = await _readonly(
            admin,
            """
            SELECT cursor FROM provider_sync.provider_sync_state
            WHERE provider_dataset_id=:dataset AND sync_scope=:scope AND operation_key=:operation
        """,
            {
                "dataset": member.provider_dataset_id,
                "scope": member.sync_scope,
                "operation": _OPERATION,
            },
        )
        assert len(sync_rows) == 1
        assert (
            sync_rows[0]["cursor"]["loaded_at"]
            == (_AT + timedelta(minutes=1) if exclusive else _AT).isoformat()
        )
        receipt = await _readonly(
            admin,
            "SELECT * FROM ops.curation_provider_snapshot_receipts "
            "WHERE source_job_id=CAST(:child AS uuid)",
            {"child": child_id},
        )
        assert bool(receipt) is (not drift_before_seal)
        assert not await _readonly(
            admin,
            "SELECT 1 FROM ops.curation_provider_root_receipts "
            "WHERE root_job_id=CAST(:root AS uuid)",
            {"root": root_id},
        )
        tree = await _tree(admin, run_id)
        assert tree[1]["status"] == ("running" if drift_before_seal else "done")
        if not drift_before_seal:
            expected = captures[0][1]
            assert receipt[0]["provider_dataset_id"] == member.provider_dataset_id
            assert receipt[0]["sync_scope"] == member.sync_scope
            assert receipt[0]["operation_key"] == _OPERATION
            assert receipt[0]["input_member_count"] == expected.curation_input_member_count
            assert receipt[0]["source_input_set_hash"] == expected.curation_input_set_hash
            terminal = _tracking_record(
                operation_key=_OPERATION,
                run_id=run_id,
                status=DagsterRunStatus.SUCCESS,
                created_at=datetime(2026, 7, 16, 1, tzinfo=ZoneInfo("UTC")),
                started_at=datetime(2026, 7, 16, 1, 0, 1, tzinfo=ZoneInfo("UTC")),
                finished_at=datetime(2026, 7, 16, 1, 0, 2, tzinfo=ZoneInfo("UTC")),
                trigger_kind="manual",
            )
            # SUCCESS 관측은 root를 곧바로 완결하지 않는다. completion sweep을 별도로 태운다.
            await _apply_run_record(terminal, client)
            observed = await _tree(admin, run_id)
            assert observed[0]["status"] == "running"
            assert not await _readonly(
                admin,
                "SELECT 1 FROM ops.curation_provider_root_receipts "
                "WHERE root_job_id=CAST(:root AS uuid)",
                {"root": root_id},
            )
            await _apply_run_record(terminal, client, completion=True)
            tree = await _tree(admin, run_id)
            assert tree[0]["status"] == tree[1]["status"] == "done"
            root_receipt = await _readonly(
                admin,
                "SELECT child_receipt_count FROM ops.curation_provider_root_receipts "
                "WHERE root_job_id=CAST(:root AS uuid)",
                {"root": root_id},
            )
            assert len(root_receipt) == 1
            assert root_receipt[0]["child_receipt_count"] == 1
        assert runtime.pool.checkedout() == 0
    finally:
        await context.resources.krheritage_items.aclose()
        for session in sessions:
            await session.aclose()
