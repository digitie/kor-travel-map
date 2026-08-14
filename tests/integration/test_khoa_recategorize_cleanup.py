"""``test_khoa_recategorize_cleanup`` — alembic 0027 KHOA 해수욕장 re-key 정리 검증.

issue #452 / #445 회귀. DA-D-07에서 KHOA 해수욕장 category가 ``01020300``→
``01050100``으로 바뀌며 feature_id가 re-key됐고(``category``는 feature_id 해시
입력), 구 ``01020300`` feature가 신 ``01050100`` feature와 중복으로 ``active``하게
남는다. 0027 migration의 ``KHOA_RECATEGORIZE_CLEANUP_SQL``이 구 feature만 골라
``inactive`` 처리하는지 확인한다.

가드 검증:
- A: 재import 완료(old+new 동일 source_record) → old만 회수, new는 공개 유지.
- B: 재import 미완료(old만, sibling 없음) → 공개 유지(가용성 공백 방지).
- C: 타 provider의 정당한 ``01020300`` 해안/섬 feature → 공개 유지(KHOA 한정).
- D(폐기): 원본 0027은 ``data_origin='user_request'`` 사용자 생성분을 제외했다.
  T-VN-36D(``0104``)가 그 whole-row origin flag를 물리 삭제했고 field override
  세대에는 행 단위 소유권 개념이 없어 head 동등 술어가 존재하지 않는다 — 그래서
  이 가드는 재현하지 않는다(없는 술어를 흉내 내면 계약이 아니라 거짓말이 된다).
- 멱등: 두 번째 실행은 0 row(이미 회수된 feature는 다시 걸리지 않는다).

Docker / testcontainers 미설치 환경에서는 conftest fixture가 ``pytest.skip``.
0044 이후 head 스키마에서는 역사 migration 상수의 의도를 확인한 뒤
``source_entity_key`` 동등 SQL로 실행한다. T-VN-33 이후 provider/dataset 자연키
사본이 사라졌으므로 provider 한정 술어는 ``provider_datasets`` 조인으로,
primary 판정은 ``source_role = 'primary'``로 표현한다.

T-VN-34(0097)에서 ``status``/``deleted_at``이 물리 삭제되고 상태가 lifecycle ·
publication · quality 3축으로 분해됐다. 이 테스트가 확인하려는 것은 "0027이
구 feature만 골라 회수하는가"라는 **선별 의미**지 특정 컬럼값이 아니므로, 0095
backfill(정본 mapping)을 따라 의미를 그대로 옮겼다:

- 술어 ``deleted_at IS NULL``("아직 살아있는 행")은 ``lifecycle_state='active'``다.
  0095는 ``deleted_at``이 있으면 무조건 ``retired``로 접었으므로 역도 성립한다.
- 결과 ``status='inactive' + deleted_at=now()``는 둘 다 같은 지점 —
  ``lifecycle_state='retired'`` + ``publication_state='suppressed'`` — 으로 접힌다
  (0095 mapping, 그리고 ``ck_features_state_tuple``이 retired면 suppressed를 강제).
  category re-key는 데이터 하자가 아니라 수명 종료이므로 ``quality_state``는
  ``'valid'`` 그대로 두는 것이 옳다.
- 가드 B/C/D가 지키려는 것은 "축 값"이 아니라 **가용성** — 즉 이 feature가 공개
  표면에 계속 보여야 한다는 것 — 이므로 3축을 낱개로 읽는 대신
  ``feature.public_features`` 실재로 단언한다. 이 view의 술어가 곧
  active+published+valid(구 ``status='active'``)라 등가이면서, 공개 계약이 깨지면
  같이 깨지는 편이 회귀 방어에 낫다.
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
SET lifecycle_state = 'retired',
    publication_state = 'suppressed',
    updated_at = now()
WHERE f.lifecycle_state = 'active'
  AND f.category = '01020300'
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
      AND nf.lifecycle_state = 'active'
      AND nf.feature_id <> f.feature_id
  )
"""


def _cleanup_sql() -> str:
    """0027 상수 의도를 확인하고 head source-entity 동등 SQL을 반환."""
    path = (
        Path(__file__).resolve().parents[2]
        / "alembic"
        # squash(`0200`) 이후 체인은 아카이브다 — `alembic/legacy_versions/README.md`.
        / "legacy_versions"
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
) -> None:
    await session.execute(
        text(
            "INSERT INTO feature.features "
            "(feature_id, kind, name, category) "
            "VALUES (:fid, 'place', :name, :category)"
        ),
        {
            "fid": feature_id,
            "name": "월정리해수욕장",
            "category": category,
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


async def _state(session: AsyncSession, feature_id: str) -> tuple[str, str, str]:
    """회수된 feature가 **어느 축으로** 접혔는지 확인한다(구 ``status`` 단일값 대체)."""

    row = (
        await session.execute(
            text(
                "SELECT lifecycle_state, publication_state, quality_state "
                "FROM feature.features WHERE feature_id = :fid"
            ),
            {"fid": feature_id},
        )
    ).one()
    return (str(row[0]), str(row[1]), str(row[2]))


async def _is_public(session: AsyncSession, feature_id: str) -> bool:
    """공개 표면에 보이는가 — 구 ``status='active'``와 등가인 정본 술어.

    ``feature.public_features``가 active+published+valid를 걸러내므로, 가드가
    지키려는 가용성을 축 값 재현 없이 view 계약 그대로 확인할 수 있다.
    """

    row = await session.execute(
        text("SELECT 1 FROM feature.public_features WHERE feature_id = :fid"),
        {"fid": feature_id},
    )
    return row.first() is not None


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

    await session.flush()

    cleanup_sql = _cleanup_sql()
    first = await session.execute(text(cleanup_sql))

    # 정리 대상은 f_a_old 하나뿐 — 나머지는 가드(타 provider/미재import)로 보존.
    assert first.rowcount == 1
    # 구 status='inactive' + deleted_at 은 retired+suppressed 한 지점으로 접힌다.
    # quality는 건드리지 않는다 — re-key는 하자가 아니라 수명 종료다.
    assert await _state(session, "f_a_old") == ("retired", "suppressed", "valid")
    assert not await _is_public(session, "f_a_old")  # 중복 노출 제거가 이 정리의 목적
    assert await _is_public(session, "f_a_new")
    assert await _is_public(session, "f_b_old")  # 재import 미완료 → 보존
    assert await _is_public(session, "f_c_coast")  # 타 provider → 보존

    # 멱등 — f_a_old는 이미 retired라 lifecycle_state='active' 술어에 다시 걸리지
    # 않는다(구 ``deleted_at IS NULL`` 술어가 하던 재진입 차단과 같은 역할).
    second = await session.execute(text(cleanup_sql))
    assert second.rowcount == 0
    assert await _state(session, "f_a_old") == ("retired", "suppressed", "valid")
    assert await _is_public(session, "f_a_new")
    assert await _is_public(session, "f_b_old")
