"""``test_consistency_reports`` — ADR-033 Phase 1 F1~F3 정합성 검사 (testcontainers).

``run_consistency_checks``를 실 PostGIS(migrated_session, alembic head)에서 돌려
F1(orphan source_record)/F2(detail 누락)/F3(CRS drift) 검출 + ``ops.
feature_consistency_reports`` 영속화를 검증한다. F3는 STORED generated column이라
정상 데이터에서 위반 0건이어야 함을 확인한다.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
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
        await migrated_session.execute(
            text("SELECT count(*) FROM ops.feature_consistency_reports")
        )
    ).scalar_one()
    assert cnt == 0
