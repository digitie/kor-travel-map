"""소유된 관리 RW savepoint의 직접 SQL guard. Python RR 경로 수용과 구분한다.

정본 EX claim/seal/begin 뒤 CHECK/FK를 만족하는 관리 SQL의 중간 상태만 읽고
각 savepoint를 rollback한다. deferred projection 상태를 commit하거나 trigger를 끄지 않는다.
"""

from __future__ import annotations

import hashlib
import json

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from kortravelmap.infra import scoped_provider_batch as batch
from kortravelmap.infra.scoped_feature_writes import begin_scoped_feature_write
from tests.integration.test_exclusive_provider_full_refresh import _full_plan
from tests.integration.test_provider_field_scalar_projection import (
    scalar_container as scalar_container,
)
from tests.integration.test_provider_field_scalar_projection import scalar_engines as scalar_engines
from tests.integration.test_transport_rest_evidence_reader import _bundle, _context, _read, _seed

pytestmark = [pytest.mark.integration, pytest.mark.timeout(40)]

_READ = text("SELECT feature.read_transport_rest_snapshot_evidence(:dataset)")


async def _direct(session, dataset):
    await session.execute(text("SET LOCAL ROLE ktm_feature_service"))
    assert await session.scalar(text("SELECT current_user::text")) == "ktm_feature_service"
    # RW 관리 fault와 같은 snapshot의 SQL 분기만 검사한다. Python RR wrapper를 부르지 않는다.
    return await session.scalar(_READ, {"dataset": dataset})


def _whole_rejected(value, reason):
    assert value["evidence_complete"] is False
    assert value["db_scope_eof"] is False
    assert value["reason"] == reason
    assert value["items"] == []
    assert value["policy_epoch"] is None


async def test_actual_rest_sql_guards_restore_original_positive_after_each_savepoint(
    scalar_engines, request
):
    admin, runtime = scalar_engines
    bundles = [await _bundle(i) for i in range(2)]
    dataset, ids = await _seed(admin, runtime, bundles)
    incoming = [await _bundle(i, observed=3) for i in range(2)]
    positive = await _read(runtime, dataset, incoming)
    assert positive.eligible
    assert len(positive.evidence.items) == 2
    items = [
        batch.ProviderScalarRefreshItem(fid, bundle)
        for fid, bundle in zip(ids, bundles, strict=True)
    ]
    _, plan = await _full_plan(runtime, dataset, items, geo=_context())
    params = {"dataset": dataset, "feature": ids[0]}
    cases = [
        (
            "policy_subset",
            """UPDATE feature.provider_field_active_policies
            SET field_paths=ARRAY['core.name']::text[] WHERE feature_id=:feature""",
            "policy_unsupported",
        ),
        (
            "duplicate_candidate_group",
            """INSERT INTO feature.provider_field_shadow_candidates(
            feature_id,policy_revision,provider_dataset_id,field_path,source_entity_key,
            value_source_record_key,value_source_hash,validated_source_record_key,
            validated_source_hash,value_json,value_geometry,availability,reason,
            value_observed_at,validated_at,normalizer_revision)
            SELECT feature_id,policy_revision,provider_dataset_id,field_path,
              (SELECT source_entity_key FROM provider_sync.source_links
               WHERE feature_id=:other AND source_role='primary'),
              value_source_record_key,value_source_hash,validated_source_record_key,
              validated_source_hash,value_json,value_geometry,availability,reason,
              value_observed_at,validated_at,normalizer_revision
            FROM feature.provider_field_shadow_candidates
            WHERE feature_id=:feature AND field_path='core.name'""",
            "policy_unsupported",
        ),
        (
            "validated_source_hash",
            """UPDATE feature.provider_field_shadow_candidates
            SET validated_source_hash=:wrong_hash
            WHERE feature_id=:feature AND field_path='core.name'""",
            "lineage_incomplete",
        ),
        (
            "geo_base_address",
            """UPDATE feature.feature_base_field_values
            SET value_json=jsonb_set(value_json,'{legal}',to_jsonb('owned different address'::text))
            WHERE feature_id=:feature AND field_path='core.address'""",
            "geo_evidence_unsupported",
        ),
        (
            "stored_datum_bound",
            """UPDATE feature.provider_field_shadow_candidates SET value_json=CAST(:large AS jsonb)
            WHERE feature_id=:feature AND field_path='core.name'""",
            "storage_unsupported",
        ),
    ]
    large = "".join(hashlib.sha256(str(i).encode()).hexdigest() for i in range(160))
    try:
        async with AsyncSession(admin) as session:
            await session.execute(text("SET LOCAL statement_timeout='3s'"))
            await session.execute(text("SET LOCAL lock_timeout='1s'"))
            await begin_scoped_feature_write(
                session,
                attempt_id=plan["attempt_id"],
                owner=plan["owner"],
                manifest_digest=plan["manifest_digest"],
            )
            baseline = await _direct(session, dataset)
            assert baseline["evidence_complete"]
            assert len(baseline["items"]) == 2
            for name, statement, reason in cases:
                await session.execute(text("SET LOCAL ROLE ktm_feature_schema_owner"))
                savepoint = await session.begin_nested()
                try:
                    if name == "validated_source_hash":
                        actual = await session.scalar(
                            text("""SELECT validated_source_hash
                            FROM feature.provider_field_shadow_candidates
                            WHERE feature_id=:feature AND field_path='core.name'"""),
                            params,
                        )
                        assert actual != "f" * 32
                    await session.execute(
                        text(statement),
                        {
                            **params,
                            "other": ids[1],
                            "wrong_hash": "f" * 32,
                            "large": json.dumps(large),
                        },
                    )
                    if name == "stored_datum_bound":
                        size, compressed = (
                            await session.execute(
                                text("""SELECT pg_column_size(value_json),
                                pg_column_compression(value_json) IS NOT NULL
                                FROM feature.provider_field_shadow_candidates
                                WHERE feature_id=:feature AND field_path='core.name'"""),
                                params,
                            )
                        ).one()
                        assert compressed or size > 8192
                        request.node.user_properties.append(
                            ("datum_size_or_compression", [size, compressed])
                        )
                    value = await _direct(session, dataset)
                    _whole_rejected(value, reason)
                    request.node.user_properties.append(("direct_sql_" + name, reason))
                finally:
                    await savepoint.rollback()
                assert await _direct(session, dataset) == baseline
            # 동일 PK는 DB domain 제약 부정이다. reader 거부로 세지 않는다.
            await session.execute(text("SET LOCAL ROLE ktm_feature_schema_owner"))
            savepoint = await session.begin_nested()
            try:
                with pytest.raises(DBAPIError) as caught:
                    await session.execute(
                        text("""INSERT INTO feature.feature_base_field_values
                        SELECT * FROM feature.feature_base_field_values
                        WHERE feature_id=:feature AND field_path='core.name'"""),
                        params,
                    )
                assert caught.value.orig.sqlstate == "23505"
                assert caught.value.orig.__cause__.constraint_name == "pk_feature_base_field_values"
                request.node.user_properties.append(
                    ("domain_duplicate_PK", "23505:pk_feature_base_field_values")
                )
            finally:
                await savepoint.rollback()
            assert await _direct(session, dataset) == baseline
            await session.rollback()
    finally:
        async with AsyncSession(runtime) as session, session.begin():
            await session.execute(text("SET LOCAL statement_timeout='3s'"))
            await session.execute(text("SET LOCAL lock_timeout='1s'"))
            assert await session.scalar(
                text("SELECT ops.cancel_scoped_feature_write(:attempt,:owner)"),
                {"attempt": plan["attempt_id"], "owner": plan["owner"]},
            )
    restored = await _read(runtime, dataset, incoming)
    assert restored.evidence == positive.evidence
    assert restored.eligible
    request.node.user_properties.append(("Python_RR_positive_before_after_only", True))
