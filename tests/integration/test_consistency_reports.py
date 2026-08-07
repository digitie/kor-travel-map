"""``test_consistency_reports`` — ADR-033 F1~F8 정합성 검사 (testcontainers).

``run_consistency_checks``를 실 PostGIS(migrated_session, alembic head)에서 돌려
F1(orphan source entity)/F2(detail 누락)/F3(CRS drift) 검출 + ``ops.
feature_consistency_reports`` 영속화를 검증한다. F3는 STORED generated column이라
정상 데이터에서 위반 0건이어야 함을 확인한다. F5는 provider sync last_success SLA,
F6는 같은 요일 영업시간 period에서 open.time > close.time인 경우만 잡는다. F7은
dedup queue baseline 대비 현재 ``core.scoring`` 점수 회귀를 WARN으로 관측한다. F8은
``feature_files`` metadata와 객체 저장소 스냅샷 불일치를 WARN으로 관측한다.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from hashlib import md5
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import text

from kortravelmap.infra.consistency import FileObjectRef, run_consistency_checks
from kortravelmap.infra.models import (
    FeatureRow,
    SourceEntityHeadRow,
    SourceEntityRow,
    SourceRecordRow,
)
from tests.integration._subtype_seed import seed_feature_subtype

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.integration

_KST = timezone(timedelta(hours=9))
_FETCHED = datetime(2026, 5, 29, 12, 0, tzinfo=_KST)


def _clean_place(feature_id: str) -> FeatureRow:
    """좌표 있는 정상 place **core** 행 (subtype은 ``_add_clean_place``가 채운다)."""
    from geoalchemy2 import WKTElement

    return FeatureRow(
        feature_id=feature_id,
        kind="place",
        name="정상 장소",
        category="EAT.RESTAURANT",
        coord=WKTElement("POINT(126.9784 37.5665)", srid=4326),
    )


async def _add_clean_place(session: AsyncSession, feature_id: str) -> FeatureRow:
    """어떤 케이스에도 걸리지 않는 정상 place — core + subtype 둘 다 (T-VN-35).

    subtype 행이 없으면 F2("subtype 결측")가 잡는다. 대조군은 그 축에서도
    깨끗해야 한다.
    """
    row = _clean_place(feature_id)
    session.add(row)
    await session.flush()
    await seed_feature_subtype(session, feature_id=feature_id, kind="place")
    return row


async def _dataset_id(
    session: AsyncSession, *, provider: str, dataset_key: str
) -> int:
    """catalog에 pair를 확보하고 canonical ``provider_dataset_id``를 돌려준다.

    T-VN-33 이후 source entity/record는 자연키 사본을 갖지 않는다 — provider와
    dataset_key는 ``provider_sync.provider_datasets``에만 산다.
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
                {"provider": provider, "dataset_key": dataset_key},
            )
        ).scalar_one()
    )


def _payload_hash(seed: str) -> str:
    """``ck_source_records_payload_hash_canonical`` = ``^[0-9a-f]{1,64}$``."""
    return md5(seed.encode("utf-8"), usedforsecurity=False).hexdigest()


async def _seed_orphan_source_entity(
    session: AsyncSession,
    *,
    entity_key: str,
    provider: str,
    dataset_key: str,
    entity_type: str,
    entity_id: str,
) -> None:
    """source_link가 없는 entity — F1이 잡아야 하는 위반."""
    session.add(
        SourceEntityRow(
            source_entity_key=entity_key,
            provider_dataset_id=await _dataset_id(
                session, provider=provider, dataset_key=dataset_key
            ),
            source_entity_type=entity_type,
            source_entity_id=entity_id,
            first_seen_at=_FETCHED,
            last_seen_at=_FETCHED,
        )
    )
    await session.flush()


async def _seed_source_entity_record(
    session: AsyncSession,
    *,
    entity_key: str,
    record_key: str,
    provider: str,
    dataset_key: str,
    entity_type: str,
    entity_id: str,
    raw_payload_seed: str,
) -> None:
    session.add(
        SourceEntityRow(
            source_entity_key=entity_key,
            provider_dataset_id=await _dataset_id(
                session, provider=provider, dataset_key=dataset_key
            ),
            source_entity_type=entity_type,
            source_entity_id=entity_id,
            first_seen_at=_FETCHED,
            last_seen_at=_FETCHED,
        )
    )
    await session.flush()
    session.add(
        SourceRecordRow(
            source_record_key=record_key,
            source_entity_key=entity_key,
            raw_data={},
            raw_payload_hash=_payload_hash(raw_payload_seed),
            fetched_at=_FETCHED,
        )
    )
    await session.flush()
    # 현재 record 포인터는 head가 소유한다(lineage_key는 트리거가 채운다).
    session.add(
        SourceEntityHeadRow(
            source_entity_key=entity_key,
            current_source_record_key=record_key,
            observed_at=_FETCHED,
        )
    )
    await session.flush()


async def test_f1_detected_and_report_persisted(
    migrated_session: AsyncSession,
) -> None:
    # 정상 feature (대조군)
    await _add_clean_place(migrated_session, "clean-1")

    # F2 후보 — subtype 행이 없는 place feature (T-VN-35 이후의 "detail 결측").
    migrated_session.add(
        FeatureRow(
            feature_id="f2-violation",
            kind="place",
            name="detail 없는 장소",
            category="EAT.RESTAURANT",
        )
    )

    # F1 위반 — source_links 없는 orphan source entity
    await _seed_orphan_source_entity(
        migrated_session,
        entity_key="orphan-se-1",
        provider="datagokr",
        dataset_key="cultural_festivals",
        entity_type="festival",
        entity_id="ORPHAN-1",
    )

    report = await run_consistency_checks(
        migrated_session, batch_id="11111111-1111-1111-1111-111111111111"
    )

    by_code = {c.code: c for c in report.cases}
    assert by_code["F1"].count >= 1
    assert "orphan-se-1" in by_code["F1"].sample_ids
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


async def test_f2_detects_feature_without_subtype_row(
    migrated_session: AsyncSession,
) -> None:
    """detail-bearing kind인데 subtype 행이 없는 feature를 F2가 잡아야 한다."""
    migrated_session.add(
        FeatureRow(
            feature_id="f2-violation-only",
            kind="place",
            name="subtype 없는 장소",
            category="EAT.RESTAURANT",
        )
    )
    await migrated_session.flush()

    report = await run_consistency_checks(migrated_session, persist=False)

    by_code = {c.code: c for c in report.cases}
    assert by_code["F2"].count >= 1
    assert "f2-violation-only" in by_code["F2"].sample_ids


async def test_clean_data_reports_ok(migrated_session: AsyncSession) -> None:
    # 정상 feature + 그에 연결된 source_record (orphan 아님)
    await _add_clean_place(migrated_session, "clean-2")
    await _seed_source_entity_record(
        migrated_session,
        entity_key="linked-se-1",
        record_key="linked-sr-1",
        provider="datagokr",
        dataset_key="cultural_festivals",
        entity_type="festival",
        entity_id="LINKED-1",
        raw_payload_seed="cafef00d",
    )
    await migrated_session.flush()
    await migrated_session.execute(
        text(
            "INSERT INTO provider_sync.source_links "
            "(feature_id, source_entity_key, source_role, match_method, "
            " confidence) "
            "VALUES ('clean-2','linked-se-1','primary','exact',100)"
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
    await _add_clean_place(session, "f4-a")
    await _add_clean_place(session, "f4-b")
    for i in range(n):
        await _add_clean_place(session, f"f4-x{i}")
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
    assert len(f4.sample_ids) == 5  # pending review_id 샘플
    # 다른 위반(F1~F3) 없으면 severity_max는 WARN.
    assert report.severity_max == "WARN"
    assert report.summary["by_severity"]["WARN"] == 1
    assert report.summary["case_metadata"]["F4"]["pending_count"] == 5


async def test_f4_warn_does_not_block_errors(migrated_session: AsyncSession) -> None:
    # F4 WARN + F1 ERROR 공존 → severity_max는 ERROR(F4가 ERROR를 가리지 않음).
    await _seed_pending_dedup(migrated_session, 3)
    await _seed_orphan_source_entity(
        migrated_session,
        entity_key="f4-orphan",
        provider="datagokr",
        dataset_key="d",
        entity_type="t",
        entity_id="o1",
    )
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


async def _catalog_operation_scope(
    session: AsyncSession, offset: int
) -> tuple[int, str, str]:
    """catalog에서 활성 (dataset, sync_scope, operation) triple 하나를 고른다.

    T-VN-33 이후 ``provider_sync_state`` PK는
    ``(provider_dataset_id, sync_scope, operation_key)``이고 세 열 전부
    ``provider_dataset_operation_scopes``를 FK로 참조한다 — 임의의 자연키
    문자열로 행을 만들 수 없다. 0089가 seed한 실제 triple을 쓴다.
    """
    row = (
        await session.execute(
            text(
                """
                SELECT scope.provider_dataset_id, scope.sync_scope,
                       scope.operation_key
                FROM provider_sync.provider_dataset_operation_scopes AS scope
                JOIN provider_sync.provider_datasets AS dataset
                  ON dataset.provider_dataset_id = scope.provider_dataset_id
                WHERE dataset.is_active
                ORDER BY scope.provider_dataset_id, scope.sync_scope,
                         scope.operation_key
                OFFSET :offset LIMIT 1
                """
            ),
            {"offset": offset},
        )
    ).one()
    return int(row.provider_dataset_id), str(row.sync_scope), str(row.operation_key)


async def _seed_provider_sync_state(
    session: AsyncSession,
    *,
    provider_dataset_id: int,
    sync_scope: str,
    operation_key: str,
    last_success_at: datetime | None,
    status: str = "active",
) -> str:
    """sync cursor 1건을 적재하고 F5 sample id(``<dataset_id>:<scope>``)를 돌려준다."""
    await session.execute(
        text(
            "INSERT INTO provider_sync.provider_sync_state "
            "(provider_dataset_id, sync_scope, operation_key, status, "
            " last_success_at) "
            "VALUES (:provider_dataset_id, :sync_scope, :operation_key, "
            " :status, :last_success_at)"
        ),
        {
            "provider_dataset_id": provider_dataset_id,
            "sync_scope": sync_scope,
            "operation_key": operation_key,
            "status": status,
            "last_success_at": last_success_at,
        },
    )
    await session.flush()
    return f"{provider_dataset_id}:{sync_scope}"


async def test_f5_warns_when_provider_last_success_sla_exceeded(
    migrated_session: AsyncSession,
) -> None:
    never_dataset, never_scope, never_operation = await _catalog_operation_scope(
        migrated_session, 0
    )
    stale_dataset, stale_scope, stale_operation = await _catalog_operation_scope(
        migrated_session, 1
    )
    fresh_dataset, fresh_scope, fresh_operation = await _catalog_operation_scope(
        migrated_session, 2
    )
    never_id = await _seed_provider_sync_state(
        migrated_session,
        provider_dataset_id=never_dataset,
        sync_scope=never_scope,
        operation_key=never_operation,
        last_success_at=None,
    )
    stale_id = await _seed_provider_sync_state(
        migrated_session,
        provider_dataset_id=stale_dataset,
        sync_scope=stale_scope,
        operation_key=stale_operation,
        last_success_at=datetime.now(UTC) - timedelta(days=2),
    )
    await _seed_provider_sync_state(
        migrated_session,
        provider_dataset_id=fresh_dataset,
        sync_scope=fresh_scope,
        operation_key=fresh_operation,
        last_success_at=datetime.now(UTC),
    )

    report = await run_consistency_checks(migrated_session, persist=False)

    by_code = {c.code: c for c in report.cases}
    f5 = by_code["F5"]
    assert f5.severity == "WARN"
    assert f5.count == 2
    # sample id는 자연키가 아니라 canonical dataset id + scope다 (T-VN-33).
    assert f5.sample_ids == [never_id, stale_id]
    assert report.severity_max == "WARN"


async def test_f5_uses_policy_interval_and_skips_disabled_policy(
    migrated_session: AsyncSession,
) -> None:
    stale_dataset, stale_scope, stale_operation = await _catalog_operation_scope(
        migrated_session, 0
    )
    disabled_dataset, disabled_scope, disabled_operation = (
        await _catalog_operation_scope(migrated_session, 1)
    )
    # refresh policy PK는 provider_dataset_id 하나다 (T-VN-33).
    await migrated_session.execute(
        text(
            "INSERT INTO ops.provider_refresh_policies "
            "(provider_dataset_id, source_kind, system_interval_seconds, enabled) "
            "VALUES "
            "(:stale_dataset, 'openapi', 3600, true), "
            "(:disabled_dataset, 'openapi', 3600, false)"
        ),
        {"stale_dataset": stale_dataset, "disabled_dataset": disabled_dataset},
    )
    stale_id = await _seed_provider_sync_state(
        migrated_session,
        provider_dataset_id=stale_dataset,
        sync_scope=stale_scope,
        operation_key=stale_operation,
        last_success_at=datetime.now(UTC) - timedelta(hours=2),
    )
    await _seed_provider_sync_state(
        migrated_session,
        provider_dataset_id=disabled_dataset,
        sync_scope=disabled_scope,
        operation_key=disabled_operation,
        last_success_at=datetime.now(UTC) - timedelta(hours=2),
    )

    report = await run_consistency_checks(migrated_session, persist=False)

    by_code = {c.code: c for c in report.cases}
    f5 = by_code["F5"]
    assert f5.count == 1
    assert f5.sample_ids == [stale_id]
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
        )
    )
    await session.flush()
    # T-VN-35: place는 subtype 행이 정본이다 — 없으면 F2가 이 대조군을 잡는다.
    await seed_feature_subtype(session, feature_id=feature_id, kind="place")
    source_record_key = f"sr-{feature_id}"
    source_entity_key = f"se-{feature_id}"
    await _seed_source_entity_record(
        session,
        entity_key=source_entity_key,
        record_key=source_record_key,
        provider=provider,
        dataset_key=dataset_key,
        entity_type="place",
        entity_id=feature_id,
        raw_payload_seed=f"hash-{feature_id}",
    )
    await session.flush()
    await session.execute(
        text(
            "INSERT INTO provider_sync.source_links "
            "(feature_id, source_entity_key, source_role, match_method, "
            " confidence) "
            "VALUES (:feature_id, :source_entity_key, 'primary', 'exact', 100)"
        ),
        {"feature_id": feature_id, "source_entity_key": source_entity_key},
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
                "RETURNING review_id::text"
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
        )
    )
    await migrated_session.flush()
    # T-VN-35(ADR-086): 영업시간 정본은 ``feature_places.business_hours``다.
    await seed_feature_subtype(
        migrated_session,
        feature_id="f6-violation",
        kind="place",
        detail={
            "place_kind": "restaurant",
            "business_hours": {
                "periods": [
                    {
                        "open": {"day": 1, "time": "1800"},
                        "close": {"day": 1, "time": "0900"},
                    }
                ]
            },
        },
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
        )
    )
    await migrated_session.flush()
    await seed_feature_subtype(
        migrated_session,
        feature_id="f6-clean",
        kind="place",
        detail={
            "place_kind": "restaurant",
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
            },
        },
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
    active_feature = await _add_clean_place(migrated_session, "f8-active")
    deleted_feature = await _add_clean_place(migrated_session, "f8-deleted")
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
            "('f8-missing-object', 'f8-active', 'image', 's3', 'kor-travel-map', "
            " 'missing-object.jpg', 'gallery'), "
            "('f8-deleted-feature', 'f8-deleted', 'image', 's3', 'kor-travel-map', "
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
                bucket="kor-travel-map",
                object_key="deleted-feature.jpg",
            ),
            FileObjectRef(
                storage_backend="s3",
                bucket="kor-travel-map",
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
