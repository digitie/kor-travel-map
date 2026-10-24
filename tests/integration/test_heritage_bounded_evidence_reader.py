"""실제 SDK 저장3shape와 source-only reader의 향후 격리 PG 수용 경로.

full source 두 리뷰 뒤 actual SDK3shape positive1 PASS를 확인했다.
optional SDK skip은 PASS가 아니다.
"""

from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from kortravelmap.dto import Address
from kortravelmap.infra import scoped_provider_batch as batch
from kortravelmap.infra.heritage_evidence_reader import read_heritage_evidence
from kortravelmap.providers.krheritage import heritage_items_to_bundles
from tests.integration.test_provider_field_scalar_projection import (
    scalar_container as scalar_container,
)
from tests.integration.test_provider_field_scalar_projection import scalar_engines as scalar_engines
from tests.integration.test_scoped_native_scalar_refresh import _TIME
from tests.integration.test_scoped_provider_batch import _entity, _plan, _seed_bundles

pytestmark = pytest.mark.integration


async def test_actual_sdk_three_shapes_and_old_nonname_r1_are_readable(scalar_engines):
    sdk = pytest.importorskip("krheritage.models", reason="actual public Heritage SDK required")
    old, new = [], []
    # 독립 소유 module DB에서 policy revision1을 한 번 등록하고 세 mode를 함께 확인한다.
    serial = int(uuid4().hex[:8], 16)
    address = Address(legal="서울특별시 영등포구 여의도동 8", bjd_code="1156011000")

    async def reverse(_coordinate):
        return address

    for index, mode in enumerate(("no_coord", "coord", "coord_geo")):
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
        assert current["non_name_base"] == previous["non_name_base"]
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
