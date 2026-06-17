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


def _cleanup_sql() -> str:
    """0027 migration 모듈에서 정리 SQL 상수를 로드(SQL 단일 정본 유지)."""
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


async def _insert_source_record(
    session: AsyncSession,
    *,
    key: str,
    provider: str,
    entity_id: str,
    dataset_key: str = "khoa_beaches",
    entity_type: str = "beach",
) -> None:
    await session.execute(
        text(
            "INSERT INTO provider_sync.source_records "
            "(source_record_key, provider, dataset_key, source_entity_type, "
            " source_entity_id, raw_payload_hash, fetched_at) "
            "VALUES (:key, :provider, :dataset_key, :entity_type, :entity_id, "
            " 'sha1:test', now())"
        ),
        {
            "key": key,
            "provider": provider,
            "dataset_key": dataset_key,
            "entity_type": entity_type,
            "entity_id": entity_id,
        },
    )


async def _link_primary(session: AsyncSession, *, feature_id: str, record_key: str) -> None:
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
