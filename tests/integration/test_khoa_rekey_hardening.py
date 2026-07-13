"""``test_khoa_rekey_hardening`` — alembic 0029 stable-identity re-key 정리 검증.

issue #509 회귀. 0027(``KHOA_RECATEGORIZE_CLEANUP_SQL``)은 old/new를 **동일
``source_record_key``** 로 매칭하는데, ``source_record_key``는 ``raw_payload_hash``를
포함한다(``uq_source_records`` — alembic 0002). 재수집 payload가 달라지면 같은 안정
식별자인데도 새 source_record가 발급되어 old/new가 서로 다른 source_record에 매달리고,
0027 join이 깨져 구 ``01020300`` feature가 active로 남는다.

0029(``KHOA_REKEY_CLEANUP_SQL`` + ``KHOA_REKEY_DEMOTE_PRIMARY_SQL``)는 old/new를
``source_records``의 안정 식별자 ``(provider, dataset_key, source_entity_type,
source_entity_id)``로 join해 ``raw_payload_hash`` drift를 견딘다.

검증:
- A(회귀): old(01020300)+new(01050100)가 **다른 raw_payload_hash → 다른
  source_record_key**(같은 안정 식별자) → old가 inactive+deleted_at. 0027 SQL이라면
  active로 남았을 케이스를 함께 단언(대조군).
- B(primary 강등): 정리 후 구 feature의 primary link가 false로 강등.
- D(no-op 가드): old만 존재(신 sibling 없음) → active 유지(가용성 공백 방지).

Docker / testcontainers 미설치 환경에서는 conftest fixture가 ``pytest.skip``.
0044 이후 head 스키마에서는 역사 migration 상수의 의도를 확인한 뒤
``source_entity_key`` 동등 SQL로 실행한다.
"""

from __future__ import annotations

import importlib.util
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import text

from kortravelmap.infra.feature_repo import _make_source_entity_key
from kortravelmap.infra.models import SourceEntityRow, SourceLinkRow, SourceRecordRow

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
    JOIN provider_sync.source_links AS new_sl
      ON new_sl.source_entity_key = old_sl.source_entity_key
     AND new_sl.is_primary_source
    JOIN feature.features AS nf
      ON nf.feature_id = new_sl.feature_id
    WHERE old_sl.feature_id = f.feature_id
      AND old_sl.is_primary_source
      AND se.provider = 'python-khoa-api'
      AND se.dataset_key = 'khoa_beaches'
      AND se.source_entity_type = 'beach'
      AND nf.category = '01050100'
      AND nf.status = 'active'
      AND nf.deleted_at IS NULL
      AND nf.feature_id <> f.feature_id
  )
"""

_HEAD_DEMOTE_SQL = """
UPDATE provider_sync.source_links AS sl
SET is_primary_source = false
FROM provider_sync.source_entities AS se,
     feature.features AS f
WHERE sl.source_entity_key = se.source_entity_key
  AND sl.feature_id = f.feature_id
  AND sl.is_primary_source
  AND se.provider = 'python-khoa-api'
  AND se.dataset_key = 'khoa_beaches'
  AND se.source_entity_type = 'beach'
  AND f.category = '01020300'
  AND f.status = 'inactive'
  AND f.deleted_at IS NOT NULL
"""


def _load_migration() -> object:
    """0030 migration 모듈을 로드(SQL 단일 정본 유지)."""
    path = (
        Path(__file__).resolve().parents[2]
        / "alembic"
        / "versions"
        / "0030_khoa_rekey_hardening.py"
    )
    spec = importlib.util.spec_from_file_location("_mig_0030_rekey", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _cleanup_sql() -> str:
    sql = _load_migration().KHOA_REKEY_CLEANUP_SQL  # type: ignore[attr-defined]
    assert isinstance(sql, str)
    assert "source_record_key" in sql
    return _HEAD_CLEANUP_SQL


def _demote_sql() -> str:
    sql = _load_migration().KHOA_REKEY_DEMOTE_PRIMARY_SQL  # type: ignore[attr-defined]
    assert isinstance(sql, str)
    assert "source_record_key" in sql
    return _HEAD_DEMOTE_SQL


def _old_0027_sql() -> str:
    """0027 (구) SQL — source_record_key equality join. 대조군 단언용."""
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
    return sql


async def _insert_feature(
    session: AsyncSession,
    *,
    feature_id: str,
    category: str,
    status: str = "active",
    data_origin: str = "provider",
) -> None:
    await session.execute(
        text(
            "INSERT INTO feature.features "
            "(feature_id, kind, name, category, status, data_origin) "
            "VALUES (:fid, 'place', :name, :category, :status, :data_origin)"
        ),
        {
            "fid": feature_id,
            "name": "월정리해수욕장",
            "category": category,
            "status": status,
            "data_origin": data_origin,
        },
    )


async def _insert_source_record(
    session: AsyncSession,
    *,
    key: str,
    provider: str,
    entity_id: str,
    payload_hash: str,
    dataset_key: str = "khoa_beaches",
    entity_type: str = "beach",
) -> None:
    source_entity_key = _make_source_entity_key(
        provider=provider,
        dataset_key=dataset_key,
        source_entity_type=entity_type,
        source_entity_id=entity_id,
    )
    entity = await session.get(SourceEntityRow, source_entity_key)
    if entity is None:
        entity = SourceEntityRow(
            source_entity_key=source_entity_key,
            provider=provider,
            dataset_key=dataset_key,
            source_entity_type=entity_type,
            source_entity_id=entity_id,
            current_source_record_key=None,
            first_seen_at=_NOW,
            last_seen_at=_NOW,
        )
        session.add(entity)
        await session.flush()
    session.add(
        SourceRecordRow(
            source_record_key=key,
            source_entity_key=source_entity_key,
            provider=provider,
            dataset_key=dataset_key,
            source_entity_type=entity_type,
            source_entity_id=entity_id,
            raw_payload_hash=payload_hash,
            fetched_at=_NOW,
        )
    )
    await session.flush()
    entity.current_source_record_key = key
    entity.last_seen_at = _NOW
    await session.flush()


async def _link_primary(
    session: AsyncSession, *, feature_id: str, record_key: str
) -> None:
    record = await session.get(SourceRecordRow, record_key)
    assert record is not None
    session.add(
        SourceLinkRow(
            feature_id=feature_id,
            source_entity_key=record.source_entity_key,
            source_role="primary",
            match_method="khoa_beach",
            confidence=100,
            is_primary_source=True,
        )
    )
    await session.flush()


async def _status(session: AsyncSession, feature_id: str) -> str:
    row = await session.execute(
        text("SELECT status FROM feature.features WHERE feature_id = :fid"),
        {"fid": feature_id},
    )
    return str(row.scalar_one())


async def _is_primary(
    session: AsyncSession, *, feature_id: str, record_key: str
) -> bool:
    record = await session.get(SourceRecordRow, record_key)
    assert record is not None
    link = await session.get(
        SourceLinkRow,
        {"feature_id": feature_id, "source_entity_key": record.source_entity_key},
    )
    assert link is not None
    return link.is_primary_source


async def test_rekey_cleanup_survives_payload_hash_drift(
    migrated_session: AsyncSession,
) -> None:
    """A: old/new가 다른 raw_payload_hash(다른 source_record_key)여도 안정 식별자로
    매칭해 old를 inactive 처리. 0027 구 SQL이라면 active로 남았을 케이스(대조군)."""
    session = migrated_session

    entity = "월정리::제주::구좌읍"
    # 같은 안정 식별자, 다른 raw_payload_hash → 다른 source_record_key.
    await _insert_source_record(
        session,
        key="sr_old",
        provider="python-khoa-api",
        entity_id=entity,
        payload_hash="sha1:OLD",
    )
    await _insert_source_record(
        session,
        key="sr_new",
        provider="python-khoa-api",
        entity_id=entity,
        payload_hash="sha1:NEW",
    )
    await _insert_feature(session, feature_id="f_old", category="01020300")
    await _insert_feature(session, feature_id="f_new", category="01050100")
    await _link_primary(session, feature_id="f_old", record_key="sr_old")
    await _link_primary(session, feature_id="f_new", record_key="sr_new")
    await session.flush()

    # 0027 역사 SQL은 version key 동일성에 의존했음을 보존 확인한다.
    assert "new_sl.source_record_key = old_sl.source_record_key" in _old_0027_sql()

    # head equivalent: stable source_entity join → payload version drift와 무관하게 old 비활성화.
    await session.execute(text(_cleanup_sql()))
    assert await _status(session, "f_old") == "inactive"
    assert await _status(session, "f_new") == "active"

    # 멱등 — 두 번째 실행도 동일.
    await session.execute(text(_cleanup_sql()))
    assert await _status(session, "f_old") == "inactive"
    assert await _status(session, "f_new") == "active"


async def test_rekey_demotes_stale_old_primary_link(
    migrated_session: AsyncSession,
) -> None:
    """B: 정리 후 구 feature의 primary link가 false로 강등."""
    session = migrated_session

    entity = "협재::제주::한림읍"
    await _insert_source_record(
        session,
        key="sr_old2",
        provider="python-khoa-api",
        entity_id=entity,
        payload_hash="sha1:OLD2",
    )
    await _insert_source_record(
        session,
        key="sr_new2",
        provider="python-khoa-api",
        entity_id=entity,
        payload_hash="sha1:NEW2",
    )
    await _insert_feature(session, feature_id="f_old2", category="01020300")
    await _insert_feature(session, feature_id="f_new2", category="01050100")
    await _link_primary(session, feature_id="f_old2", record_key="sr_old2")
    await _link_primary(session, feature_id="f_new2", record_key="sr_new2")
    await session.flush()

    await session.execute(text(_cleanup_sql()))
    await session.execute(text(_demote_sql()))

    assert await _status(session, "f_old2") == "inactive"
    # 구 primary link는 강등, 신 primary link는 유지.
    assert (
        await _is_primary(session, feature_id="f_old2", record_key="sr_old2")
    ) is False
    assert (
        await _is_primary(session, feature_id="f_new2", record_key="sr_new2")
    ) is True

    # 멱등 — 두 번째 demote도 동일(이미 false).
    await session.execute(text(_demote_sql()))
    assert (
        await _is_primary(session, feature_id="f_old2", record_key="sr_old2")
    ) is False


async def test_rekey_noop_when_only_old_exists(
    migrated_session: AsyncSession,
) -> None:
    """D: 신 sibling 없음(재import 미완료) → old active 유지(가용성 공백 방지)."""
    session = migrated_session

    await _insert_source_record(
        session,
        key="sr_lonely",
        provider="python-khoa-api",
        entity_id="함덕::제주::조천읍",
        payload_hash="sha1:LONELY",
    )
    await _insert_feature(session, feature_id="f_lonely_old", category="01020300")
    await _link_primary(session, feature_id="f_lonely_old", record_key="sr_lonely")
    await session.flush()

    await session.execute(text(_cleanup_sql()))
    await session.execute(text(_demote_sql()))

    assert await _status(session, "f_lonely_old") == "active"
    assert (
        await _is_primary(session, feature_id="f_lonely_old", record_key="sr_lonely")
    ) is True
