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
from kortravelmap.infra.integrity_violation_repo import sync_integrity_findings

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
            "detected_at, last_seen_at, source_record_key, feature_id "
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
