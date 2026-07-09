"""통합: ``list_managed_files`` 목록 쿼리 회귀 가드 (실 PostGIS).

#638 file registry의 list 쿼리가 nullable scalar 필터(provider/location/registered_by/
q/min_age_days/max_age_days)를 ``CAST`` 없이 ``:x IS NULL OR col = :x`` 로 써서, 필터가
전부 None인 **기본 뷰**에서 asyncpg가 파라미터 타입을 못 정하고
``AmbiguousParameterError`` → ``/v1/admin/files`` 500이 났다. 단위 테스트는 가짜 세션이라
SQL prepare 오류를 못 잡았으므로, 실 PostGIS로 기본 뷰 + 각 필터 경로를 검증한다.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from sqlalchemy import text

from kortravelmap.infra import file_registry

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.integration


async def _seed(session: AsyncSession) -> None:
    await session.execute(
        text(
            """
            INSERT INTO ops.managed_files
              (storage_backend, location, path, is_directory, kind, provider,
               dataset_key, status, registered_by, byte_size,
               downloaded_at, last_seen_at, meta)
            VALUES
              ('filesystem', 'backup_root', 'backups/a.dump', false, 'backup',
               NULL, NULL, 'active', 'scan', 100,
               now() - interval '2 days', now(), '{}'::jsonb),
              ('s3', 'object_store', 'uploads/b.csv', false, 'upload',
               'python-mois-api', 'mois_x', 'active', 'hook', 200,
               now() - interval '10 days', now(), '{}'::jsonb)
            """
        )
    )


@pytest.mark.asyncio
async def test_list_managed_files_default_view_no_filters(
    migrated_session: AsyncSession,
) -> None:
    """기본 뷰(필터 전부 None) — 예전엔 asyncpg AmbiguousParameterError로 500."""
    await _seed(migrated_session)
    page = await file_registry.list_managed_files(
        migrated_session, sort="downloaded_at", limit=50, offset=0
    )
    assert page.total_count == 2
    assert {f.path for f in page.items} == {"backups/a.dump", "uploads/b.csv"}
    # 실 row → ManagedFile 매핑도 함께 검증(meta/시각 필드 포함).
    by_path = {f.path: f for f in page.items}
    assert by_path["uploads/b.csv"].provider == "python-mois-api"
    assert by_path["backups/a.dump"].meta == {}


@pytest.mark.asyncio
async def test_list_managed_files_scalar_filters_all_cast(
    migrated_session: AsyncSession,
) -> None:
    """각 nullable scalar 필터가 CAST로 asyncpg 타입 추론되는지(개별 경로)."""
    await _seed(migrated_session)

    by_provider = await file_registry.list_managed_files(
        migrated_session, provider="python-mois-api"
    )
    assert [f.path for f in by_provider.items] == ["uploads/b.csv"]

    by_location = await file_registry.list_managed_files(
        migrated_session, location="backup_root"
    )
    assert [f.path for f in by_location.items] == ["backups/a.dump"]

    by_registered = await file_registry.list_managed_files(
        migrated_session, registered_by="hook"
    )
    assert [f.path for f in by_registered.items] == ["uploads/b.csv"]

    by_q = await file_registry.list_managed_files(migrated_session, q="a.dump")
    assert [f.path for f in by_q.items] == ["backups/a.dump"]

    by_q_provider = await file_registry.list_managed_files(
        migrated_session, q="python-mois"
    )
    assert [f.path for f in by_q_provider.items] == ["uploads/b.csv"]

    by_q_dataset = await file_registry.list_managed_files(migrated_session, q="mois_x")
    assert [f.path for f in by_q_dataset.items] == ["uploads/b.csv"]

    # min_age_days=5 → downloaded_at <= now()-5d → 10일 된 것만.
    older = await file_registry.list_managed_files(migrated_session, min_age_days=5)
    assert [f.path for f in older.items] == ["uploads/b.csv"]

    # max_age_days=5 → downloaded_at >= now()-5d → 2일 된 것만.
    newer = await file_registry.list_managed_files(migrated_session, max_age_days=5)
    assert [f.path for f in newer.items] == ["backups/a.dump"]


@pytest.mark.asyncio
async def test_register_file_records_reappeared_from_orphan(
    migrated_session: AsyncSession,
) -> None:
    """orphan 파일이 다시 정상 파일로 확인되면 감사 이력에 복귀 이벤트를 남긴다."""
    registered = await file_registry.register_file(
        migrated_session,
        storage_backend="filesystem",
        location="backup_root",
        path="backups/orphan-then-active.dump",
        kind="backup",
        registered_by="scan",
    )
    changed = await file_registry.mark_orphan(
        migrated_session,
        file_id=registered.file_id,
        reason="scan_unregistered",
        actor="scan:test",
    )
    assert changed is True

    revived = await file_registry.register_file(
        migrated_session,
        storage_backend="filesystem",
        location="backup_root",
        path="backups/orphan-then-active.dump",
        kind="backup",
        registered_by="scan",
        actor="scan:test",
    )

    assert revived.status == "active"
    assert revived.orphan_reason is None
    events = await file_registry.list_managed_file_events(
        migrated_session, file_id=registered.file_id, limit=10
    )
    event_by_kind = {event.event_kind: event for event in events}
    assert "reappeared" in event_by_kind
    assert event_by_kind["reappeared"].detail == {"prior_status": "orphan"}
