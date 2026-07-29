"""``sync_integrity_findings`` 통합 테스트 (T-VN-H30A).

hand-written SQL이라 단위 테스트로는 ON CONFLICT 추론·sweep 범위·배열 캐스팅을 확인할 수
없다. 실 Postgres에 걸어 검증한다.
"""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from kortravelmap.infra.integrity_violation_repo import sync_integrity_findings

pytestmark = [pytest.mark.integration]

_PROVIDER = "test-provider-h30a"
_DATASET = "test_dataset_h30a"
_MANAGED = ("reverse_geocode_unavailable", "admin_code_stale_sido")


def _finding(entity_id: str, code: str = "reverse_geocode_unavailable") -> dict[str, Any]:
    return {
        "provider": _PROVIDER,
        "dataset_key": _DATASET,
        "source_record_key": None,
        "feature_id": None,
        "violation_type": code,
        "severity": "warning",
        "message": f"{code} for {entity_id}",
        "payload": {
            "dedupe_key": f"address_validation:{_PROVIDER}:{_DATASET}:{code}:{entity_id}",
            "occurrence_count": 1,
            "provider_address": f"주소 {entity_id}",
        },
    }


async def _rows(session: AsyncSession) -> list[Any]:
    result = await session.execute(
        text(
            "select payload->>'dedupe_key' as k, status, "
            "(payload->>'occurrence_count')::int as n, "
            "payload->>'provider_address' as addr, violation_type "
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
    upserted, resolved = await sync_integrity_findings(
        migrated_session,
        provider=_PROVIDER,
        dataset_key=_DATASET,
        findings=findings,
        managed_violation_types=_MANAGED,
    )
    assert (upserted, resolved) == (2, 0)
    rows = await _rows(migrated_session)
    assert len(rows) == 2
    assert {r["n"] for r in rows} == {1}

    await sync_integrity_findings(
        migrated_session,
        provider=_PROVIDER,
        dataset_key=_DATASET,
        findings=findings,
        managed_violation_types=_MANAGED,
    )
    rows = await _rows(migrated_session)
    assert len(rows) == 2, "재실행이 새 행을 만들면 큐가 단조 증가한다"
    assert {r["n"] for r in rows} == {2}


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
        managed_violation_types=_MANAGED,
    )
    second = _finding("e1")
    second["payload"]["provider_address"] = None  # 2회차엔 단서가 없다
    await sync_integrity_findings(
        migrated_session,
        provider=_PROVIDER,
        dataset_key=_DATASET,
        findings=[second],
        managed_violation_types=_MANAGED,
    )
    rows = await _rows(migrated_session)
    assert rows[0]["addr"] == "주소 e1", "1회차 증거가 지워지면 durable ledger의 의미가 없다"


async def test_sweep_resolves_only_findings_no_longer_reported(
    migrated_session: AsyncSession,
) -> None:
    """이번 run이 보고하지 않는 finding만 닫힌다 — 나머지는 열린 채로 둔다."""
    await sync_integrity_findings(
        migrated_session,
        provider=_PROVIDER,
        dataset_key=_DATASET,
        findings=[_finding("e1"), _finding("e2")],
        managed_violation_types=_MANAGED,
    )
    # e2가 고쳐져 더 이상 보고되지 않는다.
    _, resolved = await sync_integrity_findings(
        migrated_session,
        provider=_PROVIDER,
        dataset_key=_DATASET,
        findings=[_finding("e1")],
        managed_violation_types=_MANAGED,
    )
    assert resolved == 1
    by_key = {r["k"].rsplit(":", 1)[-1]: r for r in await _rows(migrated_session)}
    assert by_key["e1"]["status"] == "open"
    assert by_key["e2"]["status"] == "resolved"


async def test_sweep_does_not_touch_acknowledged(
    migrated_session: AsyncSession,
) -> None:
    """운영자가 acknowledge한 이슈는 sweep이 건드리지 않는다."""
    await sync_integrity_findings(
        migrated_session,
        provider=_PROVIDER,
        dataset_key=_DATASET,
        findings=[_finding("e1")],
        managed_violation_types=_MANAGED,
    )
    await migrated_session.execute(
        text(
            "update ops.data_integrity_violations set status='acknowledged' "
            "where provider = :p"
        ),
        {"p": _PROVIDER},
    )
    _, resolved = await sync_integrity_findings(
        migrated_session,
        provider=_PROVIDER,
        dataset_key=_DATASET,
        findings=[],
        managed_violation_types=_MANAGED,
    )
    assert resolved == 0
    assert (await _rows(migrated_session))[0]["status"] == "acknowledged"


async def test_sweep_is_scoped_to_managed_codes(
    migrated_session: AsyncSession,
) -> None:
    """주소 검증이 소유하지 않는 code는 닫지 않는다 — 다른 주체의 큐를 건드리면 안 된다."""
    await sync_integrity_findings(
        migrated_session,
        provider=_PROVIDER,
        dataset_key=_DATASET,
        findings=[_finding("e1", code="some_other_subsystem_issue")],
        managed_violation_types=("some_other_subsystem_issue",),
    )
    _, resolved = await sync_integrity_findings(
        migrated_session,
        provider=_PROVIDER,
        dataset_key=_DATASET,
        findings=[],
        managed_violation_types=_MANAGED,  # 이 code는 여기 없다
    )
    assert resolved == 0
    assert (await _rows(migrated_session))[0]["status"] == "open"


async def test_empty_findings_sweeps_everything_managed(
    migrated_session: AsyncSession,
) -> None:
    """모든 문제가 해소된 run은 관리 code의 열린 이슈를 전부 닫는다.

    ``NOT (x = ANY('{}'))``가 어떻게 평가되는지에 결과가 갈리므로 명시적으로 고정한다.
    """
    await sync_integrity_findings(
        migrated_session,
        provider=_PROVIDER,
        dataset_key=_DATASET,
        findings=[_finding("e1"), _finding("e2")],
        managed_violation_types=_MANAGED,
    )
    _, resolved = await sync_integrity_findings(
        migrated_session,
        provider=_PROVIDER,
        dataset_key=_DATASET,
        findings=[],
        managed_violation_types=_MANAGED,
    )
    assert resolved == 2
    assert {r["status"] for r in await _rows(migrated_session)} == {"resolved"}


async def test_sweep_does_not_cross_provider_boundary(
    migrated_session: AsyncSession,
) -> None:
    """한 provider의 run이 다른 provider의 이슈를 닫으면 안 된다."""
    other = _finding("e1")
    other["provider"] = "other-provider-h30a"
    other["payload"]["dedupe_key"] = "address_validation:other-provider-h30a:x:y:e1"
    await sync_integrity_findings(
        migrated_session,
        provider="other-provider-h30a",
        dataset_key=_DATASET,
        findings=[other],
        managed_violation_types=_MANAGED,
    )
    _, resolved = await sync_integrity_findings(
        migrated_session,
        provider=_PROVIDER,
        dataset_key=_DATASET,
        findings=[],
        managed_violation_types=_MANAGED,
    )
    assert resolved == 0
