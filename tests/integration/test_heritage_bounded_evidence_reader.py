"""실제 SDK 저장3shape와 source-only reader의 향후 격리 PG 수용 경로.

full source 두 리뷰 뒤 actual SDK3shape positive1 PASS를 확인했다.
optional SDK skip은 PASS가 아니다.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
from datetime import timedelta
from time import monotonic
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from kortravelmap.core.ids import make_payload_hash, make_source_record_key
from kortravelmap.dto import Address, SourceRecord
from kortravelmap.infra import scoped_provider_batch as batch
from kortravelmap.infra.heritage_evidence_reader import (
    decode_heritage_evidence,
    read_heritage_evidence,
    validate_heritage_evidence_request,
)
from kortravelmap.providers.krheritage import heritage_items_to_bundles
from tests.integration.test_provider_field_scalar_projection import (
    scalar_container as scalar_container,
)
from tests.integration.test_provider_field_scalar_projection import scalar_engines as scalar_engines
from tests.integration.test_scoped_native_scalar_refresh import _TIME
from tests.integration.test_scoped_provider_batch import _entity, _plan, _seed_bundles

pytestmark = pytest.mark.integration


def _base_by_path(item):
    """base24의 배열 순서는 계약이 아니다. 값과 모든 provenance/clock은 그대로 비교한다."""
    rows = item["non_name_base"]
    by_path = {row["field_path"]: row for row in rows}
    assert len(rows) == len(by_path) == 24
    return by_path


def _semantic_evidence(envelope):
    return (
        envelope.request,
        envelope.evidence_complete,
        envelope.reason,
        envelope.policy_epoch,
        tuple({**item, "non_name_base": _base_by_path(item)} for item in envelope.items),
    )


async def _sdk_bundles(modes):
    sdk = pytest.importorskip("krheritage.models", reason="actual public Heritage SDK required")
    old, new = [], []
    serial = int(uuid4().hex[:8], 16)
    address = Address(legal="서울특별시 영등포구 여의도동 8", bjd_code="1156011000")

    async def reverse(_coordinate):
        return address

    for index, mode in enumerate(modes):
        raw = {
            "key": {"ccbaKdcd": "11", "ccbaAsno": str(serial + index), "ccbaCtcd": "11"},
            "ccbaMnm1": f"기준 유산 {index}",
            "ccmaName": "문화유산",
            "ccbaAdmin": "관리기관",
            "ccbaLcad": "서울특별시 영등포구 여의도동 8",
        }
        if mode != "no_coord":
            raw.update(longitude=126.9239, latitude=37.5263)
        for output, name, at in (
            (old, f"기준 유산 {index}", _TIME - timedelta(days=1)),
            (new, f"변경 유산 {index}", _TIME),
        ):
            model = sdk.HeritageDetail.model_validate(raw | {"ccbaMnm1": name})
            bundle = (
                await heritage_items_to_bundles(
                    [model],
                    fetched_at=at,
                    reverse_geocoder=reverse if mode == "coord_geo" else None,
                )
            )[0]
            output.append(
                bundle.model_copy(
                    update={
                        "source_record": bundle.source_record.model_copy(update={"imported_at": at})
                    }
                )
            )
    return old, new


async def test_actual_sdk_three_shapes_and_old_nonname_r1_are_readable(scalar_engines):
    old, new = await _sdk_bundles(("no_coord", "coord", "coord_geo"))
    admin, runtime = scalar_engines
    dataset, items = await _seed_bundles(admin, runtime, old, new)
    keys = [_entity(bundle) for bundle in old]
    async with AsyncSession(admin) as session, session.begin():
        rows = (
            await session.execute(
                text("""SELECT source_entity_key,
            pg_column_size(source_entity_key),pg_column_size(current_source_record_key)
            FROM provider_sync.source_entity_heads
            WHERE source_entity_key=ANY(CAST(:keys AS text[]))"""),
                {"keys": keys},
            )
        ).all()
        assert len(rows) == 3
        assert all(
            67 < entity_size <= 128 and 23 < record_size <= 64
            for _, entity_size, record_size in rows
        )
    async with AsyncSession(runtime) as session, session.begin():
        await session.execute(text("SET TRANSACTION READ ONLY"))
        await session.execute(text("SET LOCAL statement_timeout='2s'"))
        before = await read_heritage_evidence(session, dataset, keys)
        assert before.evidence_complete
        assert before.reason is None
        assert len(before.items) == 3
    plan, _ = await _plan(runtime, dataset, items)
    async with AsyncSession(runtime) as session, session.begin():
        result = await batch.refresh_scoped_provider_scalars_batch(session, items, **plan)
        assert result["status"] == "completed"
    async with AsyncSession(runtime) as session, session.begin():
        await session.execute(text("SET TRANSACTION READ ONLY"))
        await session.execute(text("SET LOCAL statement_timeout='2s'"))
        after = await read_heritage_evidence(session, dataset, keys)
        assert after.evidence_complete
    for previous, current, bundle in zip(before.items, after.items, new, strict=True):
        assert _base_by_path(current) == _base_by_path(previous)
        assert current["base_record"] == previous["base_record"]
        assert (
            current["name_candidate"]["value_source_record_key"]
            == bundle.source_record.source_record_key
        )
        assert (
            current["current_record"]["source_record_key"] == bundle.source_record.source_record_key
        )


@pytest.mark.parametrize(
    "statement",
    [
        "SELECT feature._heritage_evidence_metadata_bytes("
        "NULL::bigint[],NULL::boolean[],NULL::integer[],NULL::boolean[])",
        "SELECT feature._heritage_evidence_string_object(NULL::jsonb,NULL::text[])",
        "SELECT feature._heritage_evidence_shape("
        "NULL::jsonb,NULL::jsonb,NULL::jsonb,NULL::x_extension.geometry)",
        "SELECT feature._heritage_evidence_inventory(1,NULL::text[])",
        "SELECT feature._heritage_evidence_retire0(1)",
        "SELECT feature_id FROM feature.feature_base_field_values LIMIT 0",
    ],
    ids=["metadata", "string-object", "shape", "inventory", "retire", "private-base-table"],
)
async def test_runtime_cannot_bypass_public_reader_boundary(scalar_engines, statement):
    """실제 service 권한으로 private 진입을 거부한다. owner sandbox 주장은 없다."""
    from sqlalchemy.exc import DBAPIError

    _, runtime = scalar_engines
    async with AsyncSession(runtime) as session:
        await session.execute(text("SET TRANSACTION READ ONLY"))
        await session.execute(text("SET LOCAL statement_timeout='2s'"))
        assert (await session.execute(text("SELECT session_user,current_user"))).one() == (
            "ktm_feature_service",
            "ktm_feature_service",
        )
        with pytest.raises(DBAPIError) as failure:
            await session.execute(text(statement))
        assert getattr(failure.value.orig, "sqlstate", None) == "42501"
    # 예외 TX는 rollback하고 새 TX에서 공개 reader가 정상 응답하는지 확인한다.
    async with AsyncSession(runtime) as session, session.begin():
        await session.execute(text("SET TRANSACTION READ ONLY"))
        result = await read_heritage_evidence(
            session, 9_223_372_036_854_775_807, ["se_" + "1" * 64]
        )
        assert not result.evidence_complete
        assert result.reason == "scope_unsupported"
        assert result.items == ()


@pytest.mark.parametrize(
    ("dataset", "keys"),
    [
        (None, ["se_" + "1" * 64]),
        (0, ["se_" + "1" * 64]),
        (1, None),
        (1, []),
        (1, [["se_" + "1" * 64], ["se_" + "2" * 64]]),
        (1, ["se_" + "1" * 64, "se_" + "1" * 64]),
        (1, [None]),
        (1, ["sx_" + "1" * 64]),
        (1, ["se_" + "1" * 10_000]),
        (1, ["se_" + f"{index:064x}" for index in range(2731)]),
    ],
    ids=[
        "null-dataset",
        "zero-dataset",
        "null-array",
        "empty-array",
        "multidimensional",
        "duplicate",
        "null-key",
        "wrong-key-format",
        "oversize-key",
        "max-plus-one",
    ],
)
async def test_public_sql_rejects_invalid_server_input(scalar_engines, dataset, keys):
    """Python validator를 거치지 않는 고정 공개 SQL로 서버의 실제 검사를 확인한다."""
    from sqlalchemy.exc import DBAPIError

    _, runtime = scalar_engines
    async with AsyncSession(runtime) as session:
        await session.execute(text("SET TRANSACTION READ ONLY"))
        await session.execute(text("SET LOCAL statement_timeout='2s'"))
        with pytest.raises(DBAPIError) as failure:
            await session.execute(
                text(
                    "SELECT feature.read_heritage_name_refresh_evidence("
                    "CAST(:dataset AS bigint),CAST(:keys AS text[]))"
                ),
                {"dataset": dataset, "keys": keys},
            )
        assert getattr(failure.value.orig, "sqlstate", None) == "22023"


async def test_server_array_physical_budget_precedes_unbounded_enumeration(scalar_engines):
    """이미 생성된 caller 배열의 메모리까지 제한한다는 뜻은 아니다."""
    _, runtime = scalar_engines
    keys = ["se_" + f"{index:064x}" for index in range(5000)]
    async with AsyncSession(runtime) as session, session.begin():
        await session.execute(text("SET TRANSACTION READ ONLY"))
        await session.execute(text("SET LOCAL statement_timeout='2s'"))
        size = await session.scalar(
            text("SELECT pg_column_size(CAST(:keys AS text[]))"), {"keys": keys}
        )
        assert size > 262_144
        result = await session.scalar(
            text("SELECT feature.read_heritage_name_refresh_evidence(1,CAST(:keys AS text[]))"),
            {"keys": keys},
        )
        assert result == {
            "version": 1,
            "evidence_complete": False,
            "reason": "budget_exceeded",
            "dataset_id": 1,
            "policy_epoch": None,
            "items": [],
        }


async def test_repeatable_read_keeps_old_evidence_after_actual_batch_commit(
    scalar_engines, request
):
    admin, runtime = scalar_engines
    old, new = await _sdk_bundles(("no_coord",))
    dataset, items = await _seed_bundles(admin, runtime, old, new)
    keys = [_entity(old[0])]
    async with AsyncSession(runtime) as reader:
        await reader.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"))
        await reader.execute(text("SET LOCAL statement_timeout='2s'"))
        reader_pid = await reader.scalar(text("SELECT pg_backend_pid()"))
        before = await read_heritage_evidence(reader, dataset, keys)
        assert before.evidence_complete
        plan, _ = await _plan(runtime, dataset, items)
        async with AsyncSession(runtime) as writer, writer.begin():
            writer_pid = await writer.scalar(text("SELECT pg_backend_pid()"))
            assert reader_pid != writer_pid
            result = await batch.refresh_scoped_provider_scalars_batch(writer, items, **plan)
            assert result["status"] == "completed"
        repeated = await read_heritage_evidence(reader, dataset, keys)
        assert _semantic_evidence(repeated) == _semantic_evidence(before)
    async with AsyncSession(runtime) as fresh, fresh.begin():
        await fresh.execute(text("SET TRANSACTION READ ONLY"))
        current = await read_heritage_evidence(fresh, dataset, keys)
    assert current.evidence_complete
    assert (
        current.items[0]["current_record"]["source_record_key"]
        == new[0].source_record.source_record_key
    )
    assert (
        before.items[0]["current_record"]["source_record_key"]
        == old[0].source_record.source_record_key
    )
    assert _base_by_path(current.items[0]) == _base_by_path(before.items[0])
    assert current.items[0]["base_record"] == before.items[0]["base_record"]
    request.node.user_properties.extend(
        [
            ("snapshot_kind", "repeatable_read_transaction"),
            ("reader_pid", reader_pid),
            ("writer_pid", writer_pid),
            ("actual_batch_committed", True),
        ]
    )


async def test_stable_reader_uses_statement_snapshot_before_controller_release(
    scalar_engines, request
):
    """호출 전 snapshot 증거이며 metadata/payload 중간 interleave의 증거는 아니다."""
    admin, runtime = scalar_engines
    old, new = await _sdk_bundles(("no_coord",))
    dataset, items = await _seed_bundles(admin, runtime, old, new)
    keys = [_entity(old[0])]
    async with AsyncSession(runtime) as previous, previous.begin():
        before = await read_heritage_evidence(previous, dataset, keys)
        assert before.evidence_complete
    gate = uuid4().int & ((1 << 63) - 1)
    # C와 observer는 별도 admin pool, A와 B는 runtime pool의 독립 연결을 사용한다.
    async with AsyncSession(admin) as controller, AsyncSession(admin) as observer:
        await controller.execute(text("SET LOCAL statement_timeout='2s'"))
        controller_pid = await controller.scalar(text("SELECT pg_backend_pid()"))
        await controller.execute(
            text("SELECT pg_advisory_xact_lock(CAST(:gate AS bigint))"), {"gate": gate}
        )
        await observer.execute(text("SET TRANSACTION READ ONLY"))
        await observer.execute(text("SET LOCAL statement_timeout='500ms'"))
        observer_pid = await observer.scalar(text("SELECT pg_backend_pid()"))
        async with AsyncSession(runtime) as reader:
            await reader.execute(text("SET TRANSACTION READ ONLY"))
            await reader.execute(text("SET LOCAL statement_timeout='3s'"))
            reader_pid = await reader.scalar(text("SELECT pg_backend_pid()"))
            assert len({reader_pid, controller_pid, observer_pid}) == 3
            task = asyncio.create_task(
                reader.execute(
                    text("""WITH barrier AS MATERIALIZED (
                SELECT pg_advisory_xact_lock(CAST(:gate AS bigint)) AS held)
                SELECT feature.read_heritage_name_refresh_evidence(
                    :dataset,CAST(:keys AS text[])) AS evidence,barrier.held
                FROM barrier"""),
                    {"gate": gate, "dataset": dataset, "keys": keys},
                )
            )
            try:
                deadline = monotonic() + 1
                while True:
                    if task.done():
                        task.result()  # 조기 SQL 실패를 일반 barrier timeout으로 가리지 않는다.
                        raise AssertionError("reader completed before the observed controller gate")
                    blockers = await observer.scalar(
                        text("SELECT pg_blocking_pids(CAST(:pid AS integer))"), {"pid": reader_pid}
                    )
                    if controller_pid in blockers:
                        break
                    if monotonic() >= deadline:
                        raise AssertionError("reader never waited for its exact controller")
                    await asyncio.sleep(0.01)
                plan, _ = await _plan(runtime, dataset, items)
                async with AsyncSession(runtime) as writer, writer.begin():
                    writer_pid = await writer.scalar(text("SELECT pg_backend_pid()"))
                    assert len({reader_pid, writer_pid, controller_pid, observer_pid}) == 4
                    result = await batch.refresh_scoped_provider_scalars_batch(
                        writer, items, **plan
                    )
                    assert result["status"] == "completed"
                async with AsyncSession(runtime) as fresh, fresh.begin():
                    await fresh.execute(text("SET TRANSACTION READ ONLY"))
                    current = await read_heritage_evidence(fresh, dataset, keys)
                    assert current.evidence_complete
                    assert (
                        current.items[0]["current_record"]["source_record_key"]
                        == new[0].source_record.source_record_key
                    )
                await asyncio.wait_for(controller.rollback(), timeout=2)
                raw = (await asyncio.wait_for(task, timeout=4)).one().evidence
                actual = decode_heritage_evidence(
                    validate_heritage_evidence_request(dataset, keys), raw
                )
                assert _semantic_evidence(actual) == _semantic_evidence(before)
                request.node.user_properties.extend(
                    [
                        ("snapshot_kind", "statement_before_function"),
                        ("reader_pid", reader_pid),
                        ("writer_pid", writer_pid),
                        ("controller_pid", controller_pid),
                        ("observer_pid", observer_pid),
                        ("exact_blocker_observed", True),
                        ("actual_batch_committed_before_release", True),
                    ]
                )
            finally:
                await asyncio.wait_for(controller.rollback(), timeout=2)
                if not task.done():
                    task.cancel()
                await asyncio.wait_for(asyncio.gather(task, return_exceptions=True), timeout=2)


@pytest.mark.parametrize(
    ("mode", "expected"),
    [
        ("small-extra", "shape_unsupported"),
        ("compressed", "storage_unsupported"),
        ("uncompressed-oversize", "storage_unsupported"),
    ],
)
async def test_unsupported_legacy_raw_is_rejected_whole(scalar_engines, request, mode, expected):
    """실제 SDK의 출력 성공이 아닌 합법 legacy 저장의 synthetic 부정 사례다."""
    admin, runtime = scalar_engines
    old, _ = await _sdk_bundles(("no_coord",))
    original = old[0]
    if mode == "small-extra":
        padding = "unsupported extra field"
    elif mode == "compressed":
        padding = "x" * 32_768
    else:
        # 결정적 고엔트로피 ASCII다. 실제 압축 여부는 DB metadata로 별도 확인한다.
        padding = base64.b85encode(
            hashlib.shake_256(b"reader-oversize-fixture").digest(16_384)
        ).decode()
    raw = original.source_record.raw_data | {"unsupported_extra": padding}
    raw_hash = make_payload_hash(raw)
    key = make_source_record_key(
        provider=original.source_record.provider,
        dataset_key=original.source_record.dataset_key,
        source_entity_type=original.source_record.source_entity_type,
        source_entity_id=original.source_record.source_entity_id,
        raw_payload_hash=raw_hash,
    )
    record = SourceRecord.model_validate(
        original.source_record.model_dump()
        | {"raw_data": raw, "raw_payload_hash": raw_hash, "source_record_key": key}
    )
    unsupported = original.model_copy(
        update={
            "source_record": record,
            "source_link": original.source_link.model_copy(update={"source_record_key": key}),
        }
    )
    assert unsupported.provider_field_presence == original.provider_field_presence
    # 기존 immutable raw UPDATE/trigger 해제/임의 GRANT 없이 정본 EX loader로 새 원천을 저장한다.
    dataset, _ = await _seed_bundles(admin, runtime, [unsupported], [unsupported])
    async with AsyncSession(admin) as observer, observer.begin():
        await observer.execute(text("SET TRANSACTION READ ONLY"))
        physical, compression = (
            await observer.execute(
                text("""SELECT pg_column_size(raw_data),pg_column_compression(raw_data)
            FROM provider_sync.source_records WHERE source_record_key=:key"""),
                {"key": key},
            )
        ).one()
    if mode == "compressed":
        assert compression is not None
    elif mode == "uncompressed-oversize":
        assert compression is None
        assert physical > 8192
    else:
        assert compression is None
        assert physical <= 8192
    async with AsyncSession(runtime) as reader, reader.begin():
        await reader.execute(text("SET TRANSACTION READ ONLY"))
        await reader.execute(text("SET LOCAL statement_timeout='2s'"))
        result = await read_heritage_evidence(reader, dataset, [_entity(unsupported)])
    assert not result.evidence_complete
    assert result.reason == expected
    assert result.items == ()
    request.node.user_properties.extend(
        [
            ("stored_raw_case", mode),
            ("raw_physical_bytes", physical),
            ("raw_compression", compression or "none"),
            ("known_reason", result.reason.value),
        ]
    )
