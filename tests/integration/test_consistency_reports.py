"""``test_consistency_reports`` — ADR-033 F1~F6 정합성 검사 (testcontainers).

``run_consistency_checks``를 실 PostGIS(migrated_session, alembic head)에서 돌려
F1(orphan source_record)/F2(detail 누락)/F3(CRS drift) 검출 + ``ops.
feature_consistency_reports`` 영속화를 검증한다. F3는 STORED generated column이라
정상 데이터에서 위반 0건이어야 함을 확인한다. F5는 provider sync last_success SLA,
F6는 같은 요일 영업시간 period에서 open.time > close.time인 경우만 잡는다.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import text

from krtour.map.infra.consistency import run_consistency_checks
from krtour.map.infra.models import FeatureRow, SourceRecordRow

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.integration

_KST = timezone(timedelta(hours=9))
_FETCHED = datetime(2026, 5, 29, 12, 0, tzinfo=_KST)


def _clean_place(feature_id: str) -> FeatureRow:
    """detail 채워진 + 좌표 있는 정상 place feature (어떤 케이스에도 안 걸림)."""
    from geoalchemy2 import WKTElement

    return FeatureRow(
        feature_id=feature_id,
        kind="place",
        name="정상 장소",
        category="EAT.RESTAURANT",
        coord=WKTElement("POINT(126.9784 37.5665)", srid=4326),
        detail={"summary": "ok"},
    )


async def test_f1_f2_detected_and_report_persisted(
    migrated_session: AsyncSession,
) -> None:
    # 정상 feature (대조군)
    migrated_session.add(_clean_place("clean-1"))

    # F2 위반 — detail 비어 있는 place feature (server_default '{}')
    migrated_session.add(
        FeatureRow(
            feature_id="f2-violation",
            kind="place",
            name="detail 없는 장소",
            category="EAT.RESTAURANT",
        )
    )

    # F1 위반 — source_links 없는 orphan source_record
    migrated_session.add(
        SourceRecordRow(
            source_record_key="orphan-sr-1",
            provider="datagokr",
            dataset_key="cultural_festivals",
            source_entity_type="festival",
            source_entity_id="ORPHAN-1",
            raw_payload_hash="deadbeef",
            fetched_at=_FETCHED,
        )
    )
    await migrated_session.flush()

    report = await run_consistency_checks(
        migrated_session, batch_id="11111111-1111-1111-1111-111111111111"
    )

    by_code = {c.code: c for c in report.cases}
    assert by_code["F1"].count >= 1
    assert "orphan-sr-1" in by_code["F1"].sample_ids
    assert by_code["F2"].count >= 1
    assert "f2-violation" in by_code["F2"].sample_ids
    # F3는 generated column이라 정상 데이터에서 위반 없음.
    assert by_code["F3"].count == 0
    assert report.severity_max == "ERROR"

    # 리포트가 ops 테이블에 영속화됐는지 (같은 transaction 내).
    persisted = (
        await migrated_session.execute(
            text(
                "SELECT severity_max, summary FROM ops.feature_consistency_reports "
                "WHERE batch_id = :bid"
            ),
            {"bid": "11111111-1111-1111-1111-111111111111"},
        )
    ).one()
    assert persisted.severity_max == "ERROR"
    assert persisted.summary["by_code"]["F1"] >= 1


async def test_clean_data_reports_ok(migrated_session: AsyncSession) -> None:
    # 정상 feature + 그에 연결된 source_record (orphan 아님)
    migrated_session.add(_clean_place("clean-2"))
    migrated_session.add(
        SourceRecordRow(
            source_record_key="linked-sr-1",
            provider="datagokr",
            dataset_key="cultural_festivals",
            source_entity_type="festival",
            source_entity_id="LINKED-1",
            raw_payload_hash="cafef00d",
            fetched_at=_FETCHED,
        )
    )
    await migrated_session.flush()
    await migrated_session.execute(
        text(
            "INSERT INTO provider_sync.source_links "
            "(feature_id, source_record_key, source_role, match_method, "
            " confidence, is_primary_source) "
            "VALUES ('clean-2','linked-sr-1','primary','exact',100,true)"
        )
    )
    await migrated_session.flush()

    report = await run_consistency_checks(migrated_session, persist=False)

    assert report.severity_max == "OK"
    assert report.summary["total_violations"] == 0
    assert all(c.ok for c in report.cases)

    # persist=False면 행 없음.
    cnt = (
        await migrated_session.execute(text("SELECT count(*) FROM ops.feature_consistency_reports"))
    ).scalar_one()
    assert cnt == 0


# ── F4: dedup 백로그 baseline WARN (ADR-033 §2.3, Sprint 4b) ──────────────


async def _seed_pending_dedup(session: AsyncSession, n: int) -> None:
    """정상 feature 2건 + pending dedup_review_queue n쌍 적재(서로 다른 pair)."""
    session.add(_clean_place("f4-a"))
    session.add(_clean_place("f4-b"))
    for i in range(n):
        session.add(_clean_place(f"f4-x{i}"))
    await session.flush()
    for i in range(n):
        await session.execute(
            text(
                "INSERT INTO ops.dedup_review_queue "
                "(feature_id_a, feature_id_b, total_score, name_score, "
                " spatial_score, category_score, status) "
                "VALUES ('f4-a', :fb, 70, 70, 70, 70, 'pending')"
            ),
            {"fb": f"f4-x{i}"},
        )
    await session.flush()


async def test_f4_ok_below_threshold(migrated_session: AsyncSession) -> None:
    await _seed_pending_dedup(migrated_session, 3)
    report = await run_consistency_checks(
        migrated_session, persist=False, dedup_pending_threshold=10
    )
    by_code = {c.code: c for c in report.cases}
    assert "F4" in by_code
    assert by_code["F4"].count == 0  # 3 ≤ 10 → OK
    assert by_code["F4"].ok is True
    assert report.severity_max == "OK"


async def test_f4_warn_over_threshold(migrated_session: AsyncSession) -> None:
    await _seed_pending_dedup(migrated_session, 5)
    report = await run_consistency_checks(
        migrated_session, persist=False, dedup_pending_threshold=2
    )
    by_code = {c.code: c for c in report.cases}
    f4 = by_code["F4"]
    assert f4.severity == "WARN"
    assert f4.count == 5  # 5 > 2 → 위반(count=pending 수)
    assert len(f4.sample_ids) == 5  # pending review_key 샘플
    # 다른 위반(F1~F3) 없으면 severity_max는 WARN.
    assert report.severity_max == "WARN"
    assert report.summary["by_severity"]["WARN"] == 5


async def test_f4_warn_does_not_block_errors(migrated_session: AsyncSession) -> None:
    # F4 WARN + F1 ERROR 공존 → severity_max는 ERROR(F4가 ERROR를 가리지 않음).
    await _seed_pending_dedup(migrated_session, 3)
    migrated_session.add(
        SourceRecordRow(
            source_record_key="f4-orphan",
            provider="datagokr",
            dataset_key="d",
            source_entity_type="t",
            source_entity_id="o1",
            raw_payload_hash="h",
            fetched_at=_FETCHED,
        )
    )
    await migrated_session.flush()
    report = await run_consistency_checks(
        migrated_session, persist=False, dedup_pending_threshold=1
    )
    by_code = {c.code: c for c in report.cases}
    assert by_code["F4"].severity == "WARN"
    assert by_code["F4"].count == 3
    assert by_code["F1"].count >= 1
    assert report.severity_max == "ERROR"


# ── F5: provider last_success SLA WARN (ADR-033 Phase 2) ─────────────────


async def _seed_provider_sync_state(
    session: AsyncSession,
    *,
    provider: str,
    dataset_key: str,
    sync_scope: str = "system",
    last_success_at: datetime | None,
    status: str = "active",
) -> None:
    await session.execute(
        text(
            "INSERT INTO provider_sync.provider_sync_state "
            "(provider, dataset_key, sync_scope, status, last_success_at) "
            "VALUES (:provider, :dataset_key, :sync_scope, :status, :last_success_at)"
        ),
        {
            "provider": provider,
            "dataset_key": dataset_key,
            "sync_scope": sync_scope,
            "status": status,
            "last_success_at": last_success_at,
        },
    )
    await session.flush()


async def test_f5_warns_when_provider_last_success_sla_exceeded(
    migrated_session: AsyncSession,
) -> None:
    await _seed_provider_sync_state(
        migrated_session,
        provider="f5_never",
        dataset_key="dataset",
        last_success_at=None,
    )
    await _seed_provider_sync_state(
        migrated_session,
        provider="f5_stale",
        dataset_key="dataset",
        last_success_at=datetime.now(UTC) - timedelta(days=2),
    )
    await _seed_provider_sync_state(
        migrated_session,
        provider="f5_fresh",
        dataset_key="dataset",
        last_success_at=datetime.now(UTC),
    )

    report = await run_consistency_checks(migrated_session, persist=False)

    by_code = {c.code: c for c in report.cases}
    f5 = by_code["F5"]
    assert f5.severity == "WARN"
    assert f5.count == 2
    assert f5.sample_ids == ["f5_never:dataset:system", "f5_stale:dataset:system"]
    assert report.severity_max == "WARN"


async def test_f5_uses_policy_interval_and_skips_disabled_policy(
    migrated_session: AsyncSession,
) -> None:
    await migrated_session.execute(
        text(
            "INSERT INTO ops.provider_refresh_policies "
            "(provider, dataset_key, source_kind, system_interval_seconds, enabled) "
            "VALUES "
            "('f5_policy_stale', 'dataset', 'openapi', 3600, true), "
            "('f5_policy_disabled', 'dataset', 'openapi', 3600, false)"
        )
    )
    await _seed_provider_sync_state(
        migrated_session,
        provider="f5_policy_stale",
        dataset_key="dataset",
        last_success_at=datetime.now(UTC) - timedelta(hours=2),
    )
    await _seed_provider_sync_state(
        migrated_session,
        provider="f5_policy_disabled",
        dataset_key="dataset",
        last_success_at=datetime.now(UTC) - timedelta(hours=2),
    )

    report = await run_consistency_checks(migrated_session, persist=False)

    by_code = {c.code: c for c in report.cases}
    f5 = by_code["F5"]
    assert f5.count == 1
    assert f5.sample_ids == ["f5_policy_stale:dataset:system"]
    assert report.severity_max == "WARN"


# ── F6: opening_hours 모순 ERROR (ADR-033 Phase 2) ───────────────────────


async def test_f6_detects_same_day_opening_hours_conflict(
    migrated_session: AsyncSession,
) -> None:
    migrated_session.add(
        FeatureRow(
            feature_id="f6-violation",
            kind="place",
            name="영업시간 모순 장소",
            category="EAT.RESTAURANT",
            detail={
                "business_hours": {
                    "periods": [
                        {
                            "open": {"day": 1, "time": "1800"},
                            "close": {"day": 1, "time": "0900"},
                        }
                    ]
                }
            },
        )
    )
    await migrated_session.flush()

    report = await run_consistency_checks(migrated_session, persist=False)

    by_code = {c.code: c for c in report.cases}
    assert by_code["F6"].severity == "ERROR"
    assert by_code["F6"].count >= 1
    assert "f6-violation" in by_code["F6"].sample_ids
    assert report.severity_max == "ERROR"


async def test_f6_allows_normal_247_and_overnight_periods(
    migrated_session: AsyncSession,
) -> None:
    migrated_session.add(
        FeatureRow(
            feature_id="f6-clean",
            kind="place",
            name="정상 영업시간 장소",
            category="EAT.RESTAURANT",
            detail={
                "business_hours": {
                    "periods": [
                        {
                            "open": {"day": 1, "time": "0900"},
                            "close": {"day": 1, "time": "1800"},
                        },
                        {
                            "open": {"day": 5, "time": "2200"},
                            "close": {"day": 6, "time": "0200"},
                        },
                        {"open": {"day": 0, "time": "0000"}, "close": None},
                    ],
                    "special_days": [
                        {
                            "date": "2026-06-05",
                            "periods": [
                                {
                                    "open": {"day": 5, "time": "1000"},
                                    "close": {"day": 5, "time": "1200"},
                                }
                            ],
                        }
                    ],
                }
            },
        )
    )
    await migrated_session.flush()

    report = await run_consistency_checks(migrated_session, persist=False)

    by_code = {c.code: c for c in report.cases}
    assert by_code["F6"].count == 0
    assert report.severity_max == "OK"
