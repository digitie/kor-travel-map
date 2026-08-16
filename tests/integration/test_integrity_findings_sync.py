"""``sync_integrity_findings`` 통합 테스트 (T-VN-H30A).

hand-written SQL이라 단위 테스트로는 ON CONFLICT 추론·sweep 범위·배열 캐스팅을 확인할 수
없다. 실 Postgres에 걸어 검증한다.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from kortravelmap.client import (
    AddressValidationFinding,
    AsyncKorTravelMapClient,
)
from kortravelmap.core.ids import make_integrity_finding_key
from kortravelmap.infra.integrity_violation_repo import (
    IntegrityObservationReceipt,
    close_stale_integrity_findings,
    purge_resolved_integrity_findings,
    sync_integrity_findings,
)

pytestmark = [pytest.mark.integration]

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine

_PROVIDER = "test-provider-h30a"
_DATASET = "test_dataset_h30a"


async def _named_dataset_id(session: AsyncSession, dataset_key: str) -> int:
    """이름을 지정해 fixture catalog 행을 만들고 canonical id를 돌려준다."""

    return int(
        (
            await session.execute(
                text(
                    """
                    INSERT INTO provider_sync.provider_datasets (
                        provider, dataset_key, display_name, source_kind,
                        is_active, capabilities
                    )
                    SELECT :provider, :dataset_key, :provider, 'system', true,
                           jsonb_build_object('schema_version', 1,
                                              'produces', '[]'::jsonb,
                                              'extensions', '{}'::jsonb)
                    ON CONFLICT (provider, dataset_key) DO UPDATE
                        SET display_name = EXCLUDED.display_name
                    RETURNING provider_dataset_id
                    """
                ),
                {"provider": _PROVIDER, "dataset_key": dataset_key},
            )
        ).scalar_one()
    )


async def _dataset_id(session: AsyncSession) -> int:
    """fixture 전용 catalog 행을 만들고 canonical id를 돌려준다.

    T-VN-33 이후 integrity finding은 ``provider_dataset_id``로 기록된다 —
    자연키는 표시용 projection일 뿐 identity가 아니다.
    """

    return int(
        (
            await session.execute(
                text(
                    """
                    INSERT INTO provider_sync.provider_datasets (
                        provider, dataset_key, display_name, source_kind,
                        is_active, capabilities
                    )
                    SELECT :provider, :dataset_key, :provider, 'system', true,
                           jsonb_build_object('schema_version', 1,
                                              'produces', '[]'::jsonb,
                                              'extensions', '{}'::jsonb)
                    ON CONFLICT (provider, dataset_key) DO UPDATE
                        SET display_name = EXCLUDED.display_name
                    RETURNING provider_dataset_id
                    """
                ),
                {"provider": _PROVIDER, "dataset_key": _DATASET},
            )
        ).scalar_one()
    )

def _finding(
    entity_id: str,
    code: str = "reverse_geocode_unavailable",
    *,
    entity_type: str = "license",
) -> dict[str, Any]:
    return {
        "provider": _PROVIDER,
        "dataset_key": _DATASET,
        "source_record_key": None,
        "feature_id": None,
        "violation_type": code,
        "severity": "warning",
        "message": f"{code} for {entity_id}",
        "payload": {
            "dedupe_key": make_integrity_finding_key(
                provider=_PROVIDER,
                dataset_key=_DATASET,
                source_entity_type=entity_type,
                source_entity_id=entity_id,
                violation_type=code,
            ),
            "occurrence_count": 1,
            "provider_address": f"주소 {entity_id}",
        },
    }


async def _rows(session: AsyncSession) -> list[Any]:
    result = await session.execute(
        text(
            "select payload->>'dedupe_key' as k, status, "
            "(payload->>'occurrence_count')::int as n, "
            "payload->>'provider_address' as addr, violation_type, "
            "message, severity, detected_at, last_seen_at, "
            "source_record_key, feature_id "
            "from ops.data_integrity_violations "
            "where provider_dataset_id = :p order by k"
        ),
        {"p": await _dataset_id(session)},
    )
    return list(result.mappings())


async def test_batch_upsert_folds_reruns_and_counts_occurrences(
    migrated_session: AsyncSession,
) -> None:
    """같은 finding을 두 번 넣어도 한 행이며 occurrence_count만 오른다."""
    findings = [_finding("e1"), _finding("e2")]
    upserted = await sync_integrity_findings(
        migrated_session,
        provider_dataset_id=await _dataset_id(migrated_session),
        findings=findings,
    )
    assert upserted == 2
    rows = await _rows(migrated_session)
    assert len(rows) == 2
    assert {r["n"] for r in rows} == {1}
    detected_at = {r["k"]: r["detected_at"] for r in rows}

    await migrated_session.execute(
        text(
            "UPDATE ops.data_integrity_violations "
            "SET last_seen_at = detected_at - interval '1 day' "
            "WHERE provider_dataset_id = :provider_dataset_id"
        ),
        {"provider_dataset_id": await _dataset_id(migrated_session)},
    )

    await sync_integrity_findings(
        migrated_session,
        provider_dataset_id=await _dataset_id(migrated_session),
        findings=findings,
    )
    rows = await _rows(migrated_session)
    assert len(rows) == 2, "재실행이 새 행을 만들면 큐가 단조 증가한다"
    assert {r["n"] for r in rows} == {2}
    assert all(r["detected_at"] == detected_at[r["k"]] for r in rows)
    assert all(r["last_seen_at"] >= r["detected_at"] for r in rows)


async def test_null_payload_field_does_not_erase_prior_evidence(
    migrated_session: AsyncSession,
) -> None:
    """``jsonb ||``는 shallow merge라 null이 기존 값을 덮어쓴다 — strip_nulls로 막았다."""
    first = _finding("e1")
    await sync_integrity_findings(
        migrated_session,
        provider_dataset_id=await _dataset_id(migrated_session),
        findings=[first],
    )
    second = _finding("e1")
    second["payload"]["provider_address"] = None  # 2회차엔 단서가 없다
    await sync_integrity_findings(
        migrated_session,
        provider_dataset_id=await _dataset_id(migrated_session),
        findings=[second],
    )
    rows = await _rows(migrated_session)
    assert rows[0]["addr"] == "주소 e1", "1회차 증거가 지워지면 durable ledger의 의미가 없다"


async def test_older_overlapping_batch_cannot_replace_newer_evidence(
    migrated_session: AsyncSession,
) -> None:
    """lock 대기 뒤 적용된 오래된 statement는 최신 payload/FK 시각을 되돌리지 않는다."""
    current = _finding("overlap")
    await sync_integrity_findings(
        migrated_session,
        provider_dataset_id=await _dataset_id(migrated_session),
        findings=[current],
    )
    await migrated_session.execute(
        text(
            """
            UPDATE ops.data_integrity_violations
            SET last_seen_at = statement_timestamp() + interval '1 day',
                message = 'newer evidence',
                severity = 'error',
                payload = payload || '{"provider_address":"newer address"}'::jsonb
            WHERE provider_dataset_id = :provider_dataset_id
              AND payload ->> 'dedupe_key' = :dedupe_key
            """
        ),
        {
            "provider_dataset_id": await _dataset_id(migrated_session),
            "dedupe_key": current["payload"]["dedupe_key"],
        },
    )
    before = (await _rows(migrated_session))[0]

    stale = _finding("overlap")
    stale["message"] = "stale evidence"
    stale["payload"]["provider_address"] = "stale address"
    await sync_integrity_findings(
        migrated_session,
        provider_dataset_id=await _dataset_id(migrated_session),
        findings=[stale],
    )
    after = (await _rows(migrated_session))[0]

    assert after["last_seen_at"] == before["last_seen_at"]
    assert after["message"] == "newer evidence"
    assert after["severity"] == "error"
    assert after["addr"] == "newer address"
    assert after["n"] == 2


async def test_dedupe_survives_payload_change(
    migrated_session: AsyncSession,
) -> None:
    """provider payload가 바뀌어도 같은 문제는 한 행으로 접힌다 (T-VN-H30A 핵심 근거).

    이전 구현은 ``dedupe_key``를 ``source_record_key``에 걸었는데 그 키는
    ``raw_payload_hash`` 파생이라, export에서 무관한 필드 하나만 바뀌어도 **새 열린 행**이
    생기고 기존 행은 영원히 열려 있었다(MOIS 977k 규모에서 큐 단조 증가).
    ``source_entity_id`` 기반이면 payload 변경과 무관하게 안정적이어야 한다.

    여기서는 그 불변식을 직접 고정한다 — 같은 entity의 같은 code인데 다른 부수 정보를
    실어 보내도 행 수가 늘지 않아야 한다.
    """
    first = _finding("e1")
    first["source_record_key"] = None
    first["payload"]["provider_address"] = "옛 주소"
    await sync_integrity_findings(
        migrated_session,
        provider_dataset_id=await _dataset_id(migrated_session),
        findings=[first],
    )

    # payload가 바뀐 재-export: 부수 정보가 달라졌지만 같은 entity의 같은 문제다.
    second = _finding("e1")
    second["source_record_key"] = None
    second["payload"]["provider_address"] = "새 주소"
    second["message"] = "같은 문제, 새 payload"
    await sync_integrity_findings(
        migrated_session,
        provider_dataset_id=await _dataset_id(migrated_session),
        findings=[second],
    )

    rows = await _rows(migrated_session)
    assert len(rows) == 1, "payload 변경이 새 행을 만들면 큐가 export마다 자란다"
    assert rows[0]["n"] == 2, "같은 문제의 재발이므로 occurrence_count가 올라야 한다"
    assert rows[0]["addr"] == "새 주소", "최신 단서로 갱신돼야 한다"
    assert rows[0]["status"] == "open"


async def test_source_entity_type_is_part_of_dedupe_identity(
    migrated_session: AsyncSession,
) -> None:
    await sync_integrity_findings(
        migrated_session,
        provider_dataset_id=await _dataset_id(migrated_session),
        findings=[
            _finding("shared-id", entity_type="license"),
            _finding("shared-id", entity_type="closed_license"),
        ],
    )

    rows = await _rows(migrated_session)
    assert len(rows) == 2
    assert rows[0]["k"] != rows[1]["k"]


async def test_client_reports_observed_unique_and_upserted_counts(
    migrated_engine: Any,
) -> None:
    key = make_integrity_finding_key(
        provider="test-provider-h30a-result",
        dataset_key="dataset",
        source_entity_type="license",
        source_entity_id="same",
        violation_type="missing_address",
    )
    finding = AddressValidationFinding(
        dedupe_key=key,
        violation_type="missing_address",
        severity="warning",
        message="주소 없음",
        provider="test-provider-h30a-result",
        dataset_key="dataset",
    )
    async with migrated_engine.begin() as connection:
        await connection.execute(
            text(
                """
                INSERT INTO provider_sync.provider_datasets (
                    provider, dataset_key, display_name, source_kind,
                    is_active, capabilities
                ) VALUES (
                    'test-provider-h30a-result', 'dataset', 'fixture', 'system', true,
                    jsonb_build_object('schema_version', 1, 'produces', '[]'::jsonb,
                                       'extensions', '{}'::jsonb)
                ) ON CONFLICT (provider, dataset_key) DO NOTHING
                """
            )
        )
    client = AsyncKorTravelMapClient(migrated_engine)

    try:
        result = await client.record_address_validation_findings(
            [finding, finding],
            provider="test-provider-h30a-result",
            dataset_key="dataset",
        )
    finally:
        async with migrated_engine.begin() as connection:
            await connection.execute(
                text(
                    "DELETE FROM ops.data_integrity_violations "
                    "WHERE provider_dataset_id IN ("
                    "  SELECT provider_dataset_id FROM provider_sync.provider_datasets"
                    "  WHERE provider = 'test-provider-h30a-result')"
                )
            )

    assert result.observed_count == 2
    assert result.unique_count == 1
    assert result.upserted_count == 1
    assert result.unrecorded_count == 0


# --- T-VN-H32R immutable observation generation close -------------------------


def _receipt(
    *,
    source_observations: int = 1,
    findings_observed: int = 0,
    findings_unique: int = 0,
    findings_upserted: int = 0,
    authoritative_snapshot_complete: bool = True,
    finding_persistence_complete: bool = True,
) -> IntegrityObservationReceipt:
    return IntegrityObservationReceipt(
        authoritative_snapshot_complete=authoritative_snapshot_complete,
        source_observations=source_observations,
        findings_observed=findings_observed,
        findings_unique=findings_unique,
        findings_upserted=findings_upserted,
        finding_persistence_complete=finding_persistence_complete,
    )


async def _observe(
    session: AsyncSession,
    run_id: str,
    entity_ids: list[str],
) -> None:
    await sync_integrity_findings(
        session,
        provider_dataset_id=await _dataset_id(session),
        findings=[_finding(entity_id) for entity_id in entity_ids],
        external_run_id=run_id,
    )


async def _close(
    session: AsyncSession,
    run_id: str,
    *,
    finding_count: int,
) -> int:
    return await close_stale_integrity_findings(
        session,
        provider_dataset_id=await _dataset_id(session),
        run_id=run_id,
        receipt=_receipt(
            findings_observed=finding_count,
            findings_unique=finding_count,
            findings_upserted=finding_count,
        ),
    )


async def _statuses(session: AsyncSession) -> dict[str, str]:
    result = await session.execute(
        text(
            "select payload->>'dedupe_key' as k, status "
            "from ops.data_integrity_violations where provider_dataset_id = :p"
        ),
        {"p": await _dataset_id(session)},
    )
    return {r["k"]: r["status"] for r in result.mappings()}


async def test_close_spares_findings_observed_in_this_run(
    migrated_session: AsyncSession,
) -> None:
    await _observe(migrated_session, "run-1", ["a", "b"])
    closed = await _close(migrated_session, "run-1", finding_count=2)

    assert closed == 0
    assert set((await _statuses(migrated_session)).values()) == {"open"}


async def test_close_targets_only_findings_this_run_did_not_observe(
    migrated_session: AsyncSession,
) -> None:
    """run 2가 a만 다시 관측하면 b만 닫힌다."""
    await _observe(migrated_session, "run-1", ["a", "b"])
    await _close(migrated_session, "run-1", finding_count=2)
    await _observe(migrated_session, "run-2", ["a"])
    closed = await _close(migrated_session, "run-2", finding_count=1)

    assert closed == 1
    assert sorted((await _statuses(migrated_session)).values()) == ["open", "resolved"]


async def test_clean_step_retry_closes_failed_attempt_findings(
    migrated_session: AsyncSession,
) -> None:
    """같은 Dagster run의 retry는 독립 observation set으로 stale을 닫는다."""
    await _observe(migrated_session, "run-retry", ["failed-attempt"])
    await _close(migrated_session, "run-retry", finding_count=1)
    await sync_integrity_findings(
        migrated_session,
        provider_dataset_id=await _dataset_id(migrated_session),
        findings=[],
        external_run_id="run-retry::retry:1",
    )
    closed = await _close(
        migrated_session,
        "run-retry::retry:1",
        finding_count=0,
    )

    assert closed == 1
    assert set((await _statuses(migrated_session)).values()) == {"resolved"}
    observation_count = await migrated_session.scalar(
        text(
            """
            SELECT count(*)
            FROM ops.integrity_finding_observations AS observation
            JOIN ops.integrity_observation_runs AS run
              ON run.observation_run_id = observation.observation_run_id
            WHERE run.external_run_id = 'run-retry::retry:1'
            """
        )
    )
    assert observation_count == 0


async def test_older_clean_run_does_not_close_newer_strict_failure(
    migrated_session: AsyncSession,
) -> None:
    """실패 attempt가 run-bound면 앞서 시작한 clean sweep이 증거를 닫지 못한다."""
    await sync_integrity_findings(
        migrated_session,
        provider_dataset_id=await _dataset_id(migrated_session),
        findings=[],
        external_run_id="older-clean",
    )
    await _observe(migrated_session, "newer-strict", ["newer-failure"])

    closed = await _close(migrated_session, "older-clean", finding_count=0)

    assert closed == 0
    assert set((await _statuses(migrated_session)).values()) == {"open"}


async def test_overlapping_run_cannot_overwrite_observation_evidence(
    migrated_session: AsyncSession,
) -> None:
    """A upsert → B upsert → A close에서도 A가 본 X는 열린 상태다 (#912)."""

    await _observe(migrated_session, "run-a", ["x"])
    await _observe(migrated_session, "run-b", ["x"])

    assert await _close(migrated_session, "run-a", finding_count=1) == 0
    assert set((await _statuses(migrated_session)).values()) == {"open"}


async def test_newer_partial_run_evidence_is_preserved_by_older_authoritative_run(
    migrated_session: AsyncSession,
) -> None:
    """더 새 partial run은 close 권한이 없지만, 이미 남긴 증거는 과거 sweep이 못 지운다."""

    await _observe(migrated_session, "baseline", ["x", "stale"])
    await _close(migrated_session, "baseline", finding_count=2)
    await _observe(migrated_session, "run-a", ["x"])
    await _observe(migrated_session, "run-b-partial", ["newer"])

    assert await _close(migrated_session, "run-a", finding_count=1) == 1
    statuses = await _statuses(migrated_session)
    assert statuses[_finding("x")["payload"]["dedupe_key"]] == "open"
    assert statuses[_finding("newer")["payload"]["dedupe_key"]] == "open"
    assert statuses[_finding("stale")["payload"]["dedupe_key"]] == "resolved"


async def test_older_run_is_superseded_after_newer_authoritative_close(
    migrated_session: AsyncSession,
) -> None:
    """B close → A close 순서에서는 오래된 A가 새 B finding을 쓸지 못한다."""

    await _observe(migrated_session, "run-a", ["a"])
    await _observe(migrated_session, "run-b", ["b"])
    assert await _close(migrated_session, "run-b", finding_count=1) == 1
    assert await _close(migrated_session, "run-a", finding_count=1) == 0

    statuses = await _statuses(migrated_session)
    assert statuses[_finding("a")["payload"]["dedupe_key"]] == "resolved"
    assert statuses[_finding("b")["payload"]["dedupe_key"]] == "open"
    run_statuses = (
        (
            await migrated_session.execute(
                text(
                    "SELECT run.external_run_id, run.status "
                    "FROM ops.integrity_observation_runs AS run "
                    "JOIN ops.integrity_observation_scopes AS scope "
                    "  ON scope.integrity_observation_scope_id "
                    "     = run.integrity_observation_scope_id "
                    "WHERE scope.provider_dataset_id = :provider_dataset_id"
                ),
                {"provider_dataset_id": await _dataset_id(migrated_session)},
            )
        )
        .mappings()
        .all()
    )
    assert {row["external_run_id"]: row["status"] for row in run_statuses} == {
        "run-a": "superseded",
        "run-b": "authoritative",
    }


async def test_concurrent_scope_allocation_assigns_unique_monotonic_generations(
    migrated_engine: AsyncEngine,
) -> None:
    """서로 다른 DB connection도 scope row fence에서 generation을 직렬화한다."""

    dataset = f"generation-allocation-{uuid4().hex}"

    async def allocate(run_id: str) -> None:
        async with AsyncSession(migrated_engine) as session, session.begin():
            await sync_integrity_findings(
                session,
                provider_dataset_id=await _named_dataset_id(session, dataset),
                findings=[],
                external_run_id=run_id,
            )

    await asyncio.gather(allocate("run-a"), allocate("run-b"))
    async with AsyncSession(migrated_engine) as session, session.begin():
        generations = (
            (
                await session.execute(
                    text(
                        "SELECT run.generation "
                        "FROM ops.integrity_observation_runs AS run "
                        "JOIN ops.integrity_observation_scopes AS scope "
                        "  ON scope.integrity_observation_scope_id "
                        "     = run.integrity_observation_scope_id "
                        "WHERE scope.provider_dataset_id = :provider_dataset_id "
                        "ORDER BY run.generation"
                    ),
                    {"provider_dataset_id": await _named_dataset_id(session, dataset)},
                )
            )
            .scalars()
            .all()
        )
        assert generations == [1, 2]
        await session.execute(
            text(
                "DELETE FROM ops.integrity_observation_scopes "
                "WHERE provider_dataset_id = :provider_dataset_id"
            ),
            {"provider_dataset_id": await _named_dataset_id(session, dataset)},
        )


async def test_close_never_touches_acknowledged(
    migrated_session: AsyncSession,
) -> None:
    """``acknowledged``는 사람이 인지한 표시라 기계가 닫지 않는다."""
    await _observe(migrated_session, "run-1", ["a"])
    await _observe(migrated_session, "run-2", [])
    await migrated_session.execute(
        text(
            "update ops.data_integrity_violations set status='acknowledged' "
            "where provider_dataset_id = :p"
        ),
        {"p": await _dataset_id(migrated_session)},
    )
    closed = await _close(migrated_session, "run-2", finding_count=0)
    assert closed == 0
    assert set((await _statuses(migrated_session)).values()) == {"acknowledged"}


async def test_close_does_not_sweep_other_subsystem_findings(
    migrated_session: AsyncSession,
) -> None:
    """같은 provider/dataset에 다른 subsystem이 남긴 finding은 건드리지 않는다.

    ``dedupe_key``가 ``av2_`` 계열이 아니면 ``sync_integrity_findings``가 만든 것이 아니다
    (예: curation mislink는 ``curation_mislink:...``). 그걸 쓸어버리면 안 된다.
    """
    await migrated_session.execute(
        text(
            "insert into ops.data_integrity_violations "
            "(provider_dataset_id, violation_type, severity, message, payload) "
            "values (:p, 'curation_feature_region_mismatch', 'warning', 'x', "
            "jsonb_build_object('dedupe_key', 'curation_mislink:foo:bar'))"
        ),
        {"p": await _dataset_id(migrated_session)},
    )
    await _observe(migrated_session, "run-9", [])
    closed = await _close(migrated_session, "run-9", finding_count=0)
    assert closed == 0
    assert set((await _statuses(migrated_session)).values()) == {"open"}


async def test_close_respects_provider_and_dataset_boundary(
    migrated_session: AsyncSession,
) -> None:
    """provider 경계를 넘지 않는다."""
    await sync_integrity_findings(
        migrated_session,
        provider_dataset_id=await _dataset_id(migrated_session),
        findings=[_finding("a")],
    )
    other_dataset_id = await _named_dataset_id(migrated_session, "another_dataset")
    await sync_integrity_findings(
        migrated_session,
        provider_dataset_id=other_dataset_id,
        findings=[],
        external_run_id="run-2",
    )
    closed_other = await close_stale_integrity_findings(
        migrated_session,
        provider_dataset_id=other_dataset_id,
        run_id="run-2",
        receipt=_receipt(),
    )
    assert closed_other == 0
    assert set((await _statuses(migrated_session)).values()) == {"open"}


async def test_close_rejects_empty_run_id(migrated_session: AsyncSession) -> None:
    """빈 ``run_id``는 술어가 모든 행에 참이 되어 큐 전체를 닫는다 — fail-closed."""
    with pytest.raises(ValueError, match="run_id"):
        await close_stale_integrity_findings(
            migrated_session,
            provider_dataset_id=await _dataset_id(migrated_session),
            run_id="",
            receipt=_receipt(),
        )


@pytest.mark.parametrize(
    "receipt",
    [
        _receipt(source_observations=0),
        _receipt(authoritative_snapshot_complete=False),
        _receipt(
            findings_observed=1,
            findings_unique=1,
            findings_upserted=0,
        ),
        _receipt(finding_persistence_complete=False),
    ],
)
async def test_close_rejects_incomplete_receipt(
    migrated_session: AsyncSession,
    receipt: IntegrityObservationReceipt,
) -> None:
    await _observe(migrated_session, "run-incomplete", [])
    with pytest.raises(ValueError, match="receipt"):
        await close_stale_integrity_findings(
            migrated_session,
            provider_dataset_id=await _dataset_id(migrated_session),
            run_id="run-incomplete",
            receipt=receipt,
        )


async def test_close_stamps_resolution_and_is_idempotent(
    migrated_session: AsyncSession,
) -> None:
    """기계가 닫았음을 ``payload.resolution``에 남기고, 재실행해도 더 닫지 않는다."""
    await _observe(migrated_session, "run-1", ["a"])
    await _observe(migrated_session, "run-2", [])
    first = await _close(migrated_session, "run-2", finding_count=0)
    second = await _close(migrated_session, "run-2", finding_count=0)
    assert (first, second) == (1, 0)

    result = await migrated_session.execute(
        text(
            "select payload->'resolution'->>'closed_by' as closed_by, "
            "payload->'resolution'->>'run_id' as rid, resolved_at "
            "from ops.data_integrity_violations where provider_dataset_id = :p"
        ),
        {"p": await _dataset_id(migrated_session)},
    )
    row = result.mappings().one()
    assert row["closed_by"] == "observation_generation_sweep"
    assert row["rid"] == "run-2"
    assert row["resolved_at"] is not None


async def test_purge_removes_only_aged_resolved_rows(
    migrated_session: AsyncSession,
) -> None:
    """retention이 지난 ``resolved``만 삭제하고 ``acknowledged``/``open``은 남긴다."""
    await sync_integrity_findings(
        migrated_session,
        provider_dataset_id=await _dataset_id(migrated_session),
        findings=[
            _finding("a"),
            _finding("b"),
            _finding("c"),
        ],
    )
    keys = sorted((await _statuses(migrated_session)).keys())
    await migrated_session.execute(
        text(
            "update ops.data_integrity_violations "
            "set status='resolved', resolved_at = now() - interval '200 days' "
            "where provider_dataset_id = :p and payload->>'dedupe_key' = :k"
        ),
        {"p": await _dataset_id(migrated_session), "k": keys[0]},
    )
    await migrated_session.execute(
        text(
            "update ops.data_integrity_violations set status='acknowledged' "
            "where provider_dataset_id = :p and payload->>'dedupe_key' = :k"
        ),
        {"p": await _dataset_id(migrated_session), "k": keys[1]},
    )

    purged = await purge_resolved_integrity_findings(
        migrated_session, retention="90 days"
    )
    assert purged == 1
    assert sorted((await _statuses(migrated_session)).values()) == [
        "acknowledged",
        "open",
    ]


async def test_purge_keeps_recent_resolved(migrated_session: AsyncSession) -> None:
    """보존 기간 안의 ``resolved``는 남긴다 — 삭제 기준이 무조건 참이면 안 된다."""
    await _observe(migrated_session, "run-1", ["a"])
    await _observe(migrated_session, "run-2", [])
    await _close(migrated_session, "run-2", finding_count=0)
    purged = await purge_resolved_integrity_findings(
        migrated_session, retention="90 days"
    )
    assert purged == 0
    assert set((await _statuses(migrated_session)).values()) == {"resolved"}
