"""``test_khoa_recategorize_cleanup`` — alembic 0027 KHOA 해수욕장 re-key 정리 검증.

issue #452 / #445 회귀. DA-D-07에서 KHOA 해수욕장 category가 ``01020300``→
``01050100``으로 바뀌며 feature_id가 re-key됐고(``category``는 feature_id 해시
입력), 구 ``01020300`` feature가 신 ``01050100`` feature와 중복으로 ``active``하게
남는다. 0027 migration의 ``KHOA_RECATEGORIZE_CLEANUP_SQL``이 구 feature만 골라
``inactive`` 처리하는지 확인한다.

가드 검증:
- A: 재import 완료(old+new 동일 source_record) → old만 inactive, new는 active.
- B: 재import 미완료(old만, sibling 없음) → active 유지(가용성 공백 방지).
- C: 타 provider의 정당한 ``01020300`` 해안/섬 feature → active 유지(KHOA 한정).
- D: ``data_origin='user_request'`` 사용자 생성분 → active 유지.
- 멱등: 두 번째 실행은 0 row(이미 ``deleted_at``).

Docker / testcontainers 미설치 환경에서는 conftest fixture가 ``pytest.skip``.
0044 이후 head 스키마에서는 역사 migration 상수의 의도를 확인한 뒤
``source_entity_key`` 동등 SQL로 실행한다. T-VN-33 이후 provider/dataset 자연키
사본이 사라졌으므로 provider 한정 술어는 ``provider_datasets`` 조인으로,
primary 판정은 ``source_role = 'primary'``로 표현한다.
"""

from __future__ import annotations

import importlib.util
from datetime import UTC, datetime
from hashlib import md5
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import text

from kortravelmap.infra.feature_repo import _make_source_entity_key
from kortravelmap.infra.models import (
    SourceEntityHeadRow,
    SourceEntityRow,
    SourceLinkRow,
    SourceRecordRow,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


pytestmark = pytest.mark.integration
_NOW = datetime(2026, 7, 13, tzinfo=UTC)

_HEAD_CLEANUP_SQL = """
UPDATE feature.features AS f
SET status = 'inactive', deleted_at = now(), updated_at = now()
WHERE f.deleted_at IS NULL
  AND f.category = '01020300'
  AND COALESCE(f.data_origin, 'provider') <> 'user_request'
  AND EXISTS (
    SELECT 1
    FROM provider_sync.source_links AS old_sl
    JOIN provider_sync.source_entities AS se
      ON se.source_entity_key = old_sl.source_entity_key
    JOIN provider_sync.provider_datasets AS pd
      ON pd.provider_dataset_id = se.provider_dataset_id
    JOIN provider_sync.source_links AS new_sl
      ON new_sl.source_entity_key = old_sl.source_entity_key
     AND new_sl.source_role = 'primary'
    JOIN feature.features AS nf
      ON nf.feature_id = new_sl.feature_id
    WHERE old_sl.feature_id = f.feature_id
      AND old_sl.source_role = 'primary'
      AND pd.provider = 'python-khoa-api'
      AND pd.dataset_key = 'khoa_beaches'
      AND se.source_entity_type = 'beach'
      AND nf.category = '01050100'
      AND nf.deleted_at IS NULL
      AND nf.feature_id <> f.feature_id
  )
"""


def _cleanup_sql() -> str:
    """0027 상수 의도를 확인하고 head source-entity 동등 SQL을 반환."""
    path = (
        Path(__file__).resolve().parents[2]
        / "alembic"
        / "versions"
        / "0027_khoa_recategorize_cleanup.py"
    )
    spec = importlib.util.spec_from_file_location("_mig_0027_cleanup", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    sql = module.KHOA_RECATEGORIZE_CLEANUP_SQL
    assert isinstance(sql, str)
    assert "source_record_key" in sql
    return _HEAD_CLEANUP_SQL


async def _insert_feature(
    session: AsyncSession,
    *,
    feature_id: str,
    category: str,
    data_origin: str = "provider",
) -> None:
    await session.execute(
        text(
            "INSERT INTO feature.features "
            "(feature_id, kind, name, category, data_origin) "
            "VALUES (:fid, 'place', :name, :category, :data_origin)"
        ),
        {
            "fid": feature_id,
            "name": "월정리해수욕장",
            "category": category,
            "data_origin": data_origin,
        },
    )


async def _dataset_id(session: AsyncSession, *, provider: str, dataset_key: str) -> int:
    """T-VN-33: entity identity는 ``provider_dataset_id``다 — catalog 행을 확보한다."""

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


async def _insert_source_record(
    session: AsyncSession,
    *,
    key: str,
    provider: str,
    entity_id: str,
    dataset_key: str = "khoa_beaches",
    entity_type: str = "beach",
) -> None:
    source_entity_key = _make_source_entity_key(
        provider=provider,
        dataset_key=dataset_key,
        source_entity_type=entity_type,
        source_entity_id=entity_id,
    )
    dataset_id = await _dataset_id(session, provider=provider, dataset_key=dataset_key)
    session.add(
        SourceEntityRow(
            source_entity_key=source_entity_key,
            provider_dataset_id=dataset_id,
            source_entity_type=entity_type,
            source_entity_id=entity_id,
            first_seen_at=_NOW,
            last_seen_at=_NOW,
        )
    )
    await session.flush()
    session.add(
        SourceRecordRow(
            source_record_key=key,
            source_entity_key=source_entity_key,
            # ck_source_records_payload_hash_canonical = ^[0-9a-f]{1,64}$
            raw_payload_hash=md5(key.encode()).hexdigest(),
            raw_data={"source_record_key": key},
            fetched_at=_NOW,
        )
    )
    await session.flush()
    session.add(
        SourceEntityHeadRow(
            source_entity_key=source_entity_key,
            current_source_record_key=key,
            observed_at=_NOW,
        )
    )
    await session.flush()


async def _link_primary(session: AsyncSession, *, feature_id: str, record_key: str) -> None:
    record = await session.get(SourceRecordRow, record_key)
    assert record is not None
    session.add(
        SourceLinkRow(
            feature_id=feature_id,
            source_entity_key=record.source_entity_key,
            source_role="primary",
            match_method="khoa_beach",
            confidence=100,
        )
    )
    await session.flush()


async def _status(session: AsyncSession, feature_id: str) -> str:
    row = await session.execute(
        text("SELECT status FROM feature.features WHERE feature_id = :fid"),
        {"fid": feature_id},
    )
    return str(row.scalar_one())


async def test_khoa_recategorize_cleanup_inactivates_only_stale_duplicates(
    migrated_session: AsyncSession,
) -> None:
    session = migrated_session

    # A: 재import 완료 — old(01020300)+new(01050100)가 같은 source_record를 공유.
    await _insert_source_record(
        session, key="sr_a", provider="python-khoa-api", entity_id="월정리::제주::구좌읍"
    )
    await _insert_feature(session, feature_id="f_a_old", category="01020300")
    await _insert_feature(session, feature_id="f_a_new", category="01050100")
    await _link_primary(session, feature_id="f_a_old", record_key="sr_a")
    await _link_primary(session, feature_id="f_a_new", record_key="sr_a")

    # B: 재import 미완료 — old만, 신 sibling 없음.
    await _insert_source_record(
        session, key="sr_b", provider="python-khoa-api", entity_id="협재::제주::한림읍"
    )
    await _insert_feature(session, feature_id="f_b_old", category="01020300")
    await _link_primary(session, feature_id="f_b_old", record_key="sr_b")

    # C: 타 provider의 정당한 01020300 해안/섬 feature(KHOA 아님).
    await _insert_source_record(
        session,
        key="sr_c",
        provider="python-visitkorea-api",
        entity_id="어떤섬",
        dataset_key="visitkorea_areas",
        entity_type="area",
    )
    await _insert_feature(session, feature_id="f_c_coast", category="01020300")
    await _link_primary(session, feature_id="f_c_coast", record_key="sr_c")

    # D: 사용자 생성(data_origin='user_request') — re-key sibling 있어도 보존.
    await _insert_source_record(
        session, key="sr_d", provider="python-khoa-api", entity_id="함덕::제주::조천읍"
    )
    await _insert_feature(
        session, feature_id="f_d_old", category="01020300", data_origin="user_request"
    )
    await _insert_feature(session, feature_id="f_d_new", category="01050100")
    await _link_primary(session, feature_id="f_d_old", record_key="sr_d")
    await _link_primary(session, feature_id="f_d_new", record_key="sr_d")

    await session.flush()

    cleanup_sql = _cleanup_sql()
    await session.execute(text(cleanup_sql))

    # 정리 대상은 f_a_old 하나뿐 — 나머지는 가드(타 provider/미재import/user)로 보존.
    assert await _status(session, "f_a_old") == "inactive"
    assert await _status(session, "f_a_new") == "active"
    assert await _status(session, "f_b_old") == "active"  # 재import 미완료 → 보존
    assert await _status(session, "f_c_coast") == "active"  # 타 provider → 보존
    assert await _status(session, "f_d_old") == "active"  # 사용자 생성 → 보존

    # 멱등 — 두 번째 실행도 동일 상태(이미 deleted_at이라 추가 변경 없음).
    await session.execute(text(cleanup_sql))
    assert await _status(session, "f_a_old") == "inactive"
    assert await _status(session, "f_a_new") == "active"
    assert await _status(session, "f_b_old") == "active"
