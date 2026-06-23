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
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import text

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


pytestmark = pytest.mark.integration


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
    return sql


def _demote_sql() -> str:
    sql = _load_migration().KHOA_REKEY_DEMOTE_PRIMARY_SQL  # type: ignore[attr-defined]
    assert isinstance(sql, str)
    return sql


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
    await session.execute(
        text(
            "INSERT INTO provider_sync.source_records "
            "(source_record_key, provider, dataset_key, source_entity_type, "
            " source_entity_id, raw_payload_hash, fetched_at) "
            "VALUES (:key, :provider, :dataset_key, :entity_type, :entity_id, "
            " :payload_hash, now())"
        ),
        {
            "key": key,
            "provider": provider,
            "dataset_key": dataset_key,
            "entity_type": entity_type,
            "entity_id": entity_id,
            "payload_hash": payload_hash,
        },
    )


async def _link_primary(
    session: AsyncSession, *, feature_id: str, record_key: str
) -> None:
    await session.execute(
        text(
            "INSERT INTO provider_sync.source_links "
            "(feature_id, source_record_key, source_role, match_method, "
            " confidence, is_primary_source) "
            "VALUES (:fid, :key, 'primary', 'khoa_beach', 100, true)"
        ),
        {"fid": feature_id, "key": record_key},
    )


async def _status(session: AsyncSession, feature_id: str) -> str:
    row = await session.execute(
        text("SELECT status FROM feature.features WHERE feature_id = :fid"),
        {"fid": feature_id},
    )
    return str(row.scalar_one())


async def _is_primary(
    session: AsyncSession, *, feature_id: str, record_key: str
) -> bool:
    row = await session.execute(
        text(
            "SELECT is_primary_source FROM provider_sync.source_links "
            "WHERE feature_id = :fid AND source_record_key = :key"
        ),
        {"fid": feature_id, "key": record_key},
    )
    return bool(row.scalar_one())


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

    # 대조군: 0027 구 SQL은 source_record_key equality join이라 다른 key면 no-op.
    await session.execute(text(_old_0027_sql()))
    assert await _status(session, "f_old") == "active"  # 구 SQL은 못 잡는다

    # 신 0029 SQL: 안정 식별자 join → old 비활성화.
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
