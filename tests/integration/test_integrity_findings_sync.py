"""``sync_integrity_findings`` 통합 테스트 (T-VN-H30A).

hand-written SQL이라 단위 테스트로는 ON CONFLICT 추론·sweep 범위·배열 캐스팅을 확인할 수
없다. 실 Postgres에 걸어 검증한다.
"""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from kortravelmap.client import (
    AddressValidationFinding,
    AsyncKorTravelMapClient,
)
from kortravelmap.core.ids import make_integrity_finding_key
from kortravelmap.infra.integrity_violation_repo import (
    close_stale_integrity_findings,
    purge_resolved_integrity_findings,
    sync_integrity_findings,
)

pytestmark = [pytest.mark.integration]

_PROVIDER = "test-provider-h30a"
_DATASET = "test_dataset_h30a"


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
            "where provider = :p order by k"
        ),
        {"p": _PROVIDER},
    )
    return list(result.mappings())


async def test_batch_upsert_folds_reruns_and_counts_occurrences(
    migrated_session: AsyncSession,
) -> None:
    """같은 finding을 두 번 넣어도 한 행이며 occurrence_count만 오른다."""
    findings = [_finding("e1"), _finding("e2")]
    upserted = await sync_integrity_findings(
        migrated_session,
        provider=_PROVIDER,
        dataset_key=_DATASET,
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
            "WHERE provider = :provider"
        ),
        {"provider": _PROVIDER},
    )

    await sync_integrity_findings(
        migrated_session,
        provider=_PROVIDER,
        dataset_key=_DATASET,
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
        provider=_PROVIDER,
        dataset_key=_DATASET,
        findings=[first],
    )
    second = _finding("e1")
    second["payload"]["provider_address"] = None  # 2회차엔 단서가 없다
    await sync_integrity_findings(
        migrated_session,
        provider=_PROVIDER,
        dataset_key=_DATASET,
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
        provider=_PROVIDER,
        dataset_key=_DATASET,
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
            WHERE provider = :provider
              AND payload ->> 'dedupe_key' = :dedupe_key
            """
        ),
        {
            "provider": _PROVIDER,
            "dedupe_key": current["payload"]["dedupe_key"],
        },
    )
    before = (await _rows(migrated_session))[0]

    stale = _finding("overlap")
    stale["message"] = "stale evidence"
    stale["payload"]["provider_address"] = "stale address"
    await sync_integrity_findings(
        migrated_session,
        provider=_PROVIDER,
        dataset_key=_DATASET,
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
        provider=_PROVIDER,
        dataset_key=_DATASET,
        findings=[first],
    )

    # payload가 바뀐 재-export: 부수 정보가 달라졌지만 같은 entity의 같은 문제다.
    second = _finding("e1")
    second["source_record_key"] = None
    second["payload"]["provider_address"] = "새 주소"
    second["message"] = "같은 문제, 새 payload"
    await sync_integrity_findings(
        migrated_session,
        provider=_PROVIDER,
        dataset_key=_DATASET,
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
        provider=_PROVIDER,
        dataset_key=_DATASET,
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
                    "WHERE provider = 'test-provider-h30a-result'"
                )
            )

    assert result.observed_count == 2
    assert result.unique_count == 1
    assert result.upserted_count == 1
    assert result.unrecorded_count == 0


# --- T-VN-H32 run marker 기반 close --------------------------------------------
#
# 1차 설계의 배치 sweep을 적대 리뷰가 실측으로 기각했다. 아래는 **그 3모드가 재현되지
# 않음**을 고정한다. 연결을 잘못하면 큐 전체를 닫으므로 안전망이 먼저다.


def _finding_with_run(entity_id: str, run_id: str) -> dict[str, Any]:
    """upsert가 ``observed_run_id``를 심은 finding."""
    row = _finding(entity_id)
    row["payload"] = {**row["payload"], "observed_run_id": run_id}
    return row


async def _statuses(session: AsyncSession) -> dict[str, str]:
    result = await session.execute(
        text(
            "select payload->>'dedupe_key' as k, status "
            "from ops.data_integrity_violations where provider = :p"
        ),
        {"p": _PROVIDER},
    )
    return {r["k"]: r["status"] for r in result.mappings()}


async def test_close_spares_findings_observed_in_this_run(
    migrated_session: AsyncSession,
) -> None:
    """**기각 모드 1** — 이번 run이 관측한 finding을 스스로 닫으면 안 된다.

    배치 sweep은 "이 배치에 없는 것"을 닫아 한 run이 자기 finding 대부분을 resolved
    처리했다. run marker를 쓰면 이번 run이 관측한 것은 marker가 일치해 걸리지 않는다.
    """
    await sync_integrity_findings(
        migrated_session,
        provider=_PROVIDER,
        dataset_key=_DATASET,
        findings=[_finding_with_run("a", "run-1"), _finding_with_run("b", "run-1")],
    )
    closed = await close_stale_integrity_findings(
        migrated_session, provider=_PROVIDER, dataset_key=_DATASET, run_id="run-1"
    )
    assert closed == 0
    assert set((await _statuses(migrated_session)).values()) == {"open"}


async def test_close_targets_only_findings_this_run_did_not_observe(
    migrated_session: AsyncSession,
) -> None:
    """run 2가 a만 다시 관측하면 b만 닫힌다."""
    await sync_integrity_findings(
        migrated_session,
        provider=_PROVIDER,
        dataset_key=_DATASET,
        findings=[_finding_with_run("a", "run-1"), _finding_with_run("b", "run-1")],
    )
    await sync_integrity_findings(
        migrated_session,
        provider=_PROVIDER,
        dataset_key=_DATASET,
        findings=[_finding_with_run("a", "run-2")],
    )
    closed = await close_stale_integrity_findings(
        migrated_session, provider=_PROVIDER, dataset_key=_DATASET, run_id="run-2"
    )
    assert closed == 1
    assert sorted((await _statuses(migrated_session)).values()) == ["open", "resolved"]


async def test_close_never_touches_acknowledged(
    migrated_session: AsyncSession,
) -> None:
    """``acknowledged``는 사람이 인지한 표시라 기계가 닫지 않는다."""
    await sync_integrity_findings(
        migrated_session,
        provider=_PROVIDER,
        dataset_key=_DATASET,
        findings=[_finding_with_run("a", "run-1")],
    )
    await migrated_session.execute(
        text(
            "update ops.data_integrity_violations set status='acknowledged' "
            "where provider = :p"
        ),
        {"p": _PROVIDER},
    )
    closed = await close_stale_integrity_findings(
        migrated_session, provider=_PROVIDER, dataset_key=_DATASET, run_id="run-2"
    )
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
            "(provider, dataset_key, violation_type, severity, message, payload) "
            "values (:p, :d, 'curation_feature_region_mismatch', 'warning', 'x', "
            "jsonb_build_object('dedupe_key', 'curation_mislink:foo:bar'))"
        ),
        {"p": _PROVIDER, "d": _DATASET},
    )
    closed = await close_stale_integrity_findings(
        migrated_session, provider=_PROVIDER, dataset_key=_DATASET, run_id="run-9"
    )
    assert closed == 0
    assert set((await _statuses(migrated_session)).values()) == {"open"}


async def test_close_respects_provider_and_dataset_boundary(
    migrated_session: AsyncSession,
) -> None:
    """provider 경계를 넘지 않는다."""
    await sync_integrity_findings(
        migrated_session,
        provider=_PROVIDER,
        dataset_key=_DATASET,
        findings=[_finding_with_run("a", "run-1")],
    )
    closed_other = await close_stale_integrity_findings(
        migrated_session,
        provider=_PROVIDER,
        dataset_key="another_dataset",
        run_id="run-2",
    )
    assert closed_other == 0
    assert set((await _statuses(migrated_session)).values()) == {"open"}


async def test_close_rejects_empty_run_id(migrated_session: AsyncSession) -> None:
    """빈 ``run_id``는 술어가 모든 행에 참이 되어 큐 전체를 닫는다 — fail-closed."""
    with pytest.raises(ValueError, match="run_id"):
        await close_stale_integrity_findings(
            migrated_session, provider=_PROVIDER, dataset_key=_DATASET, run_id=""
        )


async def test_close_stamps_resolution_and_is_idempotent(
    migrated_session: AsyncSession,
) -> None:
    """기계가 닫았음을 ``payload.resolution``에 남기고, 재실행해도 더 닫지 않는다."""
    await sync_integrity_findings(
        migrated_session,
        provider=_PROVIDER,
        dataset_key=_DATASET,
        findings=[_finding_with_run("a", "run-1")],
    )
    first = await close_stale_integrity_findings(
        migrated_session, provider=_PROVIDER, dataset_key=_DATASET, run_id="run-2"
    )
    second = await close_stale_integrity_findings(
        migrated_session, provider=_PROVIDER, dataset_key=_DATASET, run_id="run-2"
    )
    assert (first, second) == (1, 0)

    result = await migrated_session.execute(
        text(
            "select payload->'resolution'->>'closed_by' as closed_by, "
            "payload->'resolution'->>'run_id' as rid, resolved_at "
            "from ops.data_integrity_violations where provider = :p"
        ),
        {"p": _PROVIDER},
    )
    row = result.mappings().one()
    assert row["closed_by"] == "run_marker_sweep"
    assert row["rid"] == "run-2"
    assert row["resolved_at"] is not None


async def test_purge_removes_only_aged_resolved_rows(
    migrated_session: AsyncSession,
) -> None:
    """retention이 지난 ``resolved``만 삭제하고 ``acknowledged``/``open``은 남긴다."""
    await sync_integrity_findings(
        migrated_session,
        provider=_PROVIDER,
        dataset_key=_DATASET,
        findings=[
            _finding_with_run("a", "run-1"),
            _finding_with_run("b", "run-1"),
            _finding_with_run("c", "run-1"),
        ],
    )
    keys = sorted((await _statuses(migrated_session)).keys())
    await migrated_session.execute(
        text(
            "update ops.data_integrity_violations "
            "set status='resolved', resolved_at = now() - interval '200 days' "
            "where provider = :p and payload->>'dedupe_key' = :k"
        ),
        {"p": _PROVIDER, "k": keys[0]},
    )
    await migrated_session.execute(
        text(
            "update ops.data_integrity_violations set status='acknowledged' "
            "where provider = :p and payload->>'dedupe_key' = :k"
        ),
        {"p": _PROVIDER, "k": keys[1]},
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
    await sync_integrity_findings(
        migrated_session,
        provider=_PROVIDER,
        dataset_key=_DATASET,
        findings=[_finding_with_run("a", "run-1")],
    )
    await close_stale_integrity_findings(
        migrated_session, provider=_PROVIDER, dataset_key=_DATASET, run_id="run-2"
    )
    purged = await purge_resolved_integrity_findings(
        migrated_session, retention="90 days"
    )
    assert purged == 0
    assert set((await _statuses(migrated_session)).values()) == {"resolved"}
