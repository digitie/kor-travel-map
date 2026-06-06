"""``test_consistency_reports`` — ADR-033 F1~F8 정합성 검사 (testcontainers).

``run_consistency_checks``를 실 PostGIS(migrated_session, alembic head)에서 돌려
F1(orphan source_record)/F2(detail 누락)/F3(CRS drift) 검출 + ``ops.
feature_consistency_reports`` 영속화를 검증한다. F3는 STORED generated column이라
정상 데이터에서 위반 0건이어야 함을 확인한다. F5는 provider sync last_success SLA,
F6는 같은 요일 영업시간 period에서 open.time > close.time인 경우만 잡는다. F7은
dedup queue baseline 대비 현재 ``core.scoring`` 점수 회귀를 WARN으로 관측한다. F8은
``feature_files`` metadata와 객체 저장소 스냅샷 불일치를 WARN으로 관측한다.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import text

from krtour.map.infra.consistency import FileObjectRef, run_consistency_checks
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
    assert by_code["F4"].metadata["pending_count"] == 3
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
    assert f4.count == 1  # 5 > 2 → 임계 초과 이벤트 1건
    assert f4.metadata == {
        "pending_count": 5,
        "threshold": 2,
        "over_threshold": True,
    }
    assert len(f4.sample_ids) == 5  # pending review_key 샘플
    # 다른 위반(F1~F3) 없으면 severity_max는 WARN.
    assert report.severity_max == "WARN"
    assert report.summary["by_severity"]["WARN"] == 1
    assert report.summary["case_metadata"]["F4"]["pending_count"] == 5


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
    assert by_code["F4"].count == 1
    assert by_code["F4"].metadata["pending_count"] == 3
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


# ── F7: cross-provider dedup score regression WARN (ADR-033 Phase 2) ──────


async def _seed_feature_with_primary_source(
    session: AsyncSession,
    *,
    feature_id: str,
    provider: str,
    dataset_key: str = "f7_dataset",
    name: str | None = None,
    category: str = "EAT.RESTAURANT",
    coord_wkt: str = "POINT(126.9784 37.5665)",
) -> None:
    from geoalchemy2 import WKTElement

    session.add(
        FeatureRow(
            feature_id=feature_id,
            kind="place",
            name=name or f"정상 장소 {feature_id}",
            category=category,
            coord=WKTElement(coord_wkt, srid=4326),
            detail={"summary": "ok"},
        )
    )
    source_record_key = f"sr-{feature_id}"
    session.add(
        SourceRecordRow(
            source_record_key=source_record_key,
            provider=provider,
            dataset_key=dataset_key,
            source_entity_type="place",
            source_entity_id=feature_id,
            raw_payload_hash=f"hash-{feature_id}",
            fetched_at=_FETCHED,
        )
    )
    await session.flush()
    await session.execute(
        text(
            "INSERT INTO provider_sync.source_links "
            "(feature_id, source_record_key, source_role, match_method, "
            " confidence, is_primary_source) "
            "VALUES (:feature_id, :source_record_key, 'primary', 'exact', 100, true)"
        ),
        {"feature_id": feature_id, "source_record_key": source_record_key},
    )
    await session.flush()


async def _seed_dedup_review(
    session: AsyncSession,
    *,
    feature_id_a: str,
    feature_id_b: str,
    total_score: float,
    status: str = "pending",
) -> str:
    row = (
        await session.execute(
            text(
                "INSERT INTO ops.dedup_review_queue "
                "(feature_id_a, feature_id_b, total_score, name_score, "
                " spatial_score, category_score, status) "
                "VALUES (:feature_id_a, :feature_id_b, :score, :score, "
                " :score, :score, :status) "
                "RETURNING review_key::text"
            ),
            {
                "feature_id_a": feature_id_a,
                "feature_id_b": feature_id_b,
                "score": total_score,
                "status": status,
            },
        )
    ).scalar_one()
    await session.flush()
    return str(row)


async def test_f7_warns_when_current_cross_provider_score_regresses_from_baseline(
    migrated_session: AsyncSession,
) -> None:
    await _seed_feature_with_primary_source(
        migrated_session,
        feature_id="f7-a",
        provider="provider-a",
        name="가나다",
        category="CAT.A",
    )
    await _seed_feature_with_primary_source(
        migrated_session,
        feature_id="f7-b",
        provider="provider-b",
        name="XYZ",
        category="CAT.B",
    )
    await _seed_feature_with_primary_source(
        migrated_session,
        feature_id="f7-c",
        provider="provider-a",
        name="가나다",
        category="CAT.A",
    )
    await _seed_feature_with_primary_source(
        migrated_session,
        feature_id="f7-d",
        provider="provider-a",
        name="XYZ",
        category="CAT.B",
    )
    regressed_key = await _seed_dedup_review(
        migrated_session,
        feature_id_a="f7-a",
        feature_id_b="f7-b",
        total_score=95.0,
    )
    await _seed_dedup_review(
        migrated_session,
        feature_id_a="f7-c",
        feature_id_b="f7-d",
        total_score=95.0,
    )

    report = await run_consistency_checks(migrated_session, persist=False)

    by_code = {c.code: c for c in report.cases}
    f7 = by_code["F7"]
    assert f7.severity == "WARN"
    assert f7.count == 1
    assert len(f7.sample_ids) == 1
    assert f7.sample_ids[0].startswith(f"{regressed_key}:f7-a:f7-b:95.00->")
    assert report.severity_max == "WARN"


async def test_f7_allows_current_score_within_baseline_delta(
    migrated_session: AsyncSession,
) -> None:
    await _seed_feature_with_primary_source(
        migrated_session,
        feature_id="f7-e",
        provider="provider-a",
        name="서울특별시청",
        category="CAT.A",
    )
    await _seed_feature_with_primary_source(
        migrated_session,
        feature_id="f7-f",
        provider="provider-b",
        name="서울특별시청",
        category="CAT.A",
    )
    await _seed_dedup_review(
        migrated_session,
        feature_id_a="f7-e",
        feature_id_b="f7-f",
        total_score=95.0,
    )

    report = await run_consistency_checks(migrated_session, persist=False)

    by_code = {c.code: c for c in report.cases}
    assert by_code["F7"].count == 0
    assert report.severity_max == "OK"


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


# ── F8: file object orphan WARN (ADR-033 Phase 2) ────────────────────────


async def test_f8_warns_for_feature_file_metadata_and_object_snapshot_mismatch(
    migrated_session: AsyncSession,
) -> None:
    active_feature = _clean_place("f8-active")
    deleted_feature = _clean_place("f8-deleted")
    deleted_feature.deleted_at = datetime.now(UTC)
    migrated_session.add(active_feature)
    migrated_session.add(deleted_feature)
    await migrated_session.flush()
    await migrated_session.execute(
        text(
            "CREATE TABLE IF NOT EXISTS feature.feature_files ("
            "file_id TEXT PRIMARY KEY, "
            "feature_id TEXT NOT NULL, "
            "file_type TEXT NOT NULL DEFAULT 'image', "
            "storage_backend TEXT NOT NULL DEFAULT 's3', "
            "bucket TEXT NOT NULL, "
            "object_key TEXT NOT NULL, "
            "role TEXT NOT NULL DEFAULT 'gallery', "
            "display_order INTEGER NOT NULL DEFAULT 0"
            ")"
        )
    )
    await migrated_session.execute(
        text(
            "INSERT INTO feature.feature_files "
            "(file_id, feature_id, file_type, storage_backend, bucket, object_key, role) "
            "VALUES "
            "('f8-missing-object', 'f8-active', 'image', 's3', 'krtour-map', "
            " 'missing-object.jpg', 'gallery'), "
            "('f8-deleted-feature', 'f8-deleted', 'image', 's3', 'krtour-map', "
            " 'deleted-feature.jpg', 'gallery')"
        )
    )
    await migrated_session.flush()

    report = await run_consistency_checks(
        migrated_session,
        persist=False,
        known_file_objects=[
            FileObjectRef(
                storage_backend="s3",
                bucket="krtour-map",
                object_key="deleted-feature.jpg",
            ),
            FileObjectRef(
                storage_backend="s3",
                bucket="krtour-map",
                object_key="object-without-metadata.jpg",
            ),
        ],
    )

    by_code = {c.code: c for c in report.cases}
    f8 = by_code["F8"]
    assert f8.severity == "WARN"
    assert f8.count == 3
    assert f8.metadata == {
        "metadata_file_issue_count": 2,
        "object_missing_metadata_count": 1,
    }
    assert any(sample.startswith("metadata_missing_object:") for sample in f8.sample_ids)
    assert any(sample.startswith("metadata_without_active_feature:") for sample in f8.sample_ids)
    assert any(sample.startswith("object_missing_metadata:") for sample in f8.sample_ids)
    assert report.severity_max == "WARN"
