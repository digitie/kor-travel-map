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
  source_record_key**(같은 안정 식별자) → old가 공개 표면에서 내려간다. 0027 SQL이라면
  active로 남았을 케이스를 함께 단언(대조군).
- B(primary 강등): 정리 후 구 feature의 primary link가 non-primary role로 강등.
- D(no-op 가드): old만 존재(신 sibling 없음) → 공개 유지(가용성 공백 방지).

Docker / testcontainers 미설치 환경에서는 conftest fixture가 ``pytest.skip``.
T-VN-33 이후 head 스키마에서는 안정 식별자가 ``source_entities``에
``(provider_dataset_id, source_entity_type, source_entity_id)``로 남고 현재 record
포인터는 ``source_entity_heads``가 소유하며, primary 판정은 ``source_role='primary'``
하나가 든다. 역사 migration 상수의 의도를 확인한 뒤 그 head 동등 SQL로 실행한다.

T-VN-34(alembic 0097)는 여기서 한 겹 더 간다. 0029가 쓰던 ``status``/``deleted_at``이
head에는 없고, 상태는 ``lifecycle_state``/``publication_state``/``quality_state`` 3축이다.
0029가 실제로 하려던 일은 품질 판정이 아니라 **"재분류된 구 feature를 공개 표면에서
내리는 것"** 이므로, 0095 backfill 매핑(``status IN ('inactive','deleted')`` 또는
``deleted_at IS NOT NULL`` → ``lifecycle_state='retired'`` + ``publication_state=
'suppressed'``)을 따라 은퇴 두 축만 옮기고 ``quality_state``는 건드리지 않는다.
읽기 쪽 단언은 축 값보다 ``feature.public_features`` 실재가 정본이다 — 이 테스트가
지키려는 불변식이 "구 feature가 사라지고 신 feature가 보인다"이기 때문이다.
"""

from __future__ import annotations

import hashlib
import importlib.util
from datetime import UTC, datetime, timedelta
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

#: 0029 ``KHOA_REKEY_CLEANUP_SQL``의 head 동등 SQL.
#:
#: 쓰기: 0029의 ``status='inactive', deleted_at=now()``는 한 가지 뜻이었다 — "이 feature를
#: 은퇴시켜 공개 표면에서 내린다". 3축에서 그 뜻은 ``lifecycle_state='retired'``이고,
#: ``ck_features_state_tuple``(retired면 publication은 반드시 suppressed)이 있으므로
#: ``publication_state='suppressed'``를 함께 써야 한 문장이 성립한다. 재분류는 데이터가
#: 깨졌다는 판정이 아니므로 ``quality_state``는 그대로 둔다.
#:
#: 대상 가드: ``f.deleted_at IS NULL``은 "아직 살아 있는 행"이었고 이는 정확히
#: ``lifecycle_state='active'``다(멱등도 이 술어가 준다 — 두 번째 실행은 이미 retired라
#: 아무 행도 잡지 않는다).
#:
#: 신 sibling 가드: ``nf.status='active' AND nf.deleted_at IS NULL``은 "새 feature가
#: 이미 공개 표면에 서 있다"는 확인이었다. head에서 그 술어는 3축 triple이고, 이는
#: ``feature.public_features``의 가시성 조건과 글자 그대로 같다 — 구 feature를 내리기
#: 전에 대체재가 실제로 보이는지 보는 것이 이 가드의 존재 이유다(D 케이스).
#: T-VN-36D(``0104``)가 ``data_origin``을 물리 삭제했다. 0029 원본의
#: ``COALESCE(data_origin,'provider') <> 'user_request'`` 제외 술어는 whole-row
#: origin flag에 기대던 것이라 head에는 등가 술어가 없다 — field override 세대의
#: 소유권은 행 단위가 아니라 field 단위이기 때문이다. 이 테스트가 지키는 A/B/D
#: 가드는 그 술어와 무관하므로 술어만 뺀다.
_HEAD_CLEANUP_SQL = """
UPDATE feature.features AS f
SET lifecycle_state = 'retired', publication_state = 'suppressed', updated_at = now()
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
      AND nf.publication_state = 'published'
      AND nf.quality_state = 'valid'
      AND nf.feature_id <> f.feature_id
  )
"""

#: 0029 ``KHOA_REKEY_DEMOTE_PRIMARY_SQL``의 head 동등 SQL.
#:
#: 0029의 ``f.status='inactive' AND f.deleted_at IS NOT NULL``은 두 값이 아니라 한 조건이었다
#: — "바로 위 cleanup이 방금 은퇴시킨 행". 3축에서 그 조건은 ``lifecycle_state='retired'``
#: 하나로 접힌다(0095 매핑에서 두 legacy 표현이 같은 축값으로 모이고,
#: ``ck_features_state_tuple``이 suppressed를 딸려 보장한다). 따라서 은퇴 여부만 보면
#: 되고, 강등 대상은 여전히 category/provider/dataset 가드가 좁힌다.
_HEAD_DEMOTE_SQL = """
UPDATE provider_sync.source_links AS sl
SET source_role = 'enrichment'
FROM provider_sync.source_entities AS se
     JOIN provider_sync.provider_datasets AS pd
       ON pd.provider_dataset_id = se.provider_dataset_id,
     feature.features AS f
WHERE sl.source_entity_key = se.source_entity_key
  AND sl.feature_id = f.feature_id
  AND sl.source_role = 'primary'
  AND pd.provider = 'python-khoa-api'
  AND pd.dataset_key = 'khoa_beaches'
  AND se.source_entity_type = 'beach'
  AND f.category = '01020300'
  AND f.lifecycle_state = 'retired'
"""


def _payload_hash(seed: str) -> str:
    """``ck_source_records_payload_hash_canonical``(^[0-9a-f]{1,64}$) 준수 hash."""
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()


def _load_migration() -> object:
    """0030 migration 모듈을 로드(SQL 단일 정본 유지)."""
    path = (
        Path(__file__).resolve().parents[2]
        / "alembic"
        # squash(`0200`) 이후 체인은 아카이브다 — `alembic/legacy_versions/README.md`.
        / "legacy_versions"
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
    return sql


async def _insert_feature(
    session: AsyncSession,
    *,
    feature_id: str,
    category: str,
) -> None:
    """공개 표면에 서 있는 provider feature를 심는다.

    이 테스트가 필요로 하는 출발 상태는 legacy ``status='active'`` 하나였고, 0095
    매핑에서 그것은 3축 triple ``('active', 'published', 'valid')``와 동치다(= 그대로
    ``feature.public_features``의 가시성 조건). ``status`` 인자를 남겨 두면 head에는
    없는 어휘를 다시 들여오는 셈이라 지운다 — 호출부도 기본값만 썼다.
    """
    await session.execute(
        text(
            "INSERT INTO feature.features "
            "(feature_id, kind, name, category, "
            " lifecycle_state, publication_state, quality_state) "
            "VALUES (:fid, 'place', :name, :category, "
            " 'active', 'published', 'valid')"
        ),
        {
            "fid": feature_id,
            "name": "월정리해수욕장",
            "category": category,
        },
    )


async def _provider_dataset_id(
    session: AsyncSession, *, provider: str, dataset_key: str
) -> int:
    """catalog canonical id — T-VN-33 이후 source entity의 dataset identity."""
    value = await session.scalar(
        text(
            "SELECT provider_dataset_id FROM provider_sync.provider_datasets "
            "WHERE provider = :provider AND dataset_key = :dataset_key"
        ),
        {"provider": provider, "dataset_key": dataset_key},
    )
    assert value is not None
    return int(value)


async def _insert_source_record(
    session: AsyncSession,
    *,
    key: str,
    provider: str,
    entity_id: str,
    payload_hash: str,
    dataset_key: str = "khoa_beaches",
    entity_type: str = "beach",
    observed_at: datetime = _NOW,
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
            provider_dataset_id=await _provider_dataset_id(
                session, provider=provider, dataset_key=dataset_key
            ),
            source_entity_type=entity_type,
            source_entity_id=entity_id,
            first_seen_at=_NOW,
            last_seen_at=observed_at,
        )
        session.add(entity)
        await session.flush()
    session.add(
        SourceRecordRow(
            source_record_key=key,
            source_entity_key=source_entity_key,
            raw_data={},
            raw_payload_hash=payload_hash,
            fetched_at=_NOW,
        )
    )
    await session.flush()
    # 현재 record 포인터는 head가 소유한다(lineage_key는 BEFORE INSERT 트리거가 채움).
    head = await session.get(SourceEntityHeadRow, source_entity_key)
    if head is None:
        session.add(
            SourceEntityHeadRow(
                source_entity_key=source_entity_key,
                current_source_record_key=key,
                observed_at=observed_at,
            )
        )
    else:
        head.current_source_record_key = key
        head.observed_at = observed_at
    entity.last_seen_at = observed_at
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
        )
    )
    await session.flush()


async def _is_public(session: AsyncSession, feature_id: str) -> bool:
    """공개 표면 실재 여부 — 이 테스트가 지키려는 불변식의 정본.

    "구 feature가 사용자에게 보이지 않는다 / 신 feature는 보인다"는 축 값 세 개를
    맞춰 보는 것보다 ``feature.public_features``에 있느냐로 묻는 편이 정확하다.
    공개 술어가 나중에 또 바뀌어도 이 단언의 뜻은 그대로 남는다.
    """
    row = await session.execute(
        text("SELECT 1 FROM feature.public_features WHERE feature_id = :fid"),
        {"fid": feature_id},
    )
    return row.scalar_one_or_none() is not None


async def _retirement(session: AsyncSession, feature_id: str) -> tuple[str, str]:
    """정리 SQL이 실제로 쓴 두 축 — legacy ``status``/``deleted_at``의 자리.

    ``_is_public``은 "보이지 않는다"만 말하므로(품질 격리로도 안 보일 수 있다),
    0029가 의도한 것이 **은퇴**임을 여기서 따로 못 박는다.
    """
    row = await session.execute(
        text(
            "SELECT lifecycle_state, publication_state "
            "FROM feature.features WHERE feature_id = :fid"
        ),
        {"fid": feature_id},
    )
    lifecycle, publication = row.one()
    return str(lifecycle), str(publication)


async def _is_primary(
    session: AsyncSession, *, feature_id: str, record_key: str
) -> bool:
    """raw SQL로 읽는다 — 정리 SQL이 ORM 뒤에서 role을 바꾸기 때문."""
    row = await session.execute(
        text(
            """
            SELECT sl.source_role
            FROM provider_sync.source_links AS sl
            JOIN provider_sync.source_records AS sr
              ON sr.source_entity_key = sl.source_entity_key
            WHERE sl.feature_id = :fid AND sr.source_record_key = :rk
            """
        ),
        {"fid": feature_id, "rk": record_key},
    )
    return str(row.scalar_one()) == "primary"


async def test_rekey_cleanup_survives_payload_hash_drift(
    migrated_session: AsyncSession,
) -> None:
    """A: old/new가 다른 raw_payload_hash(다른 source_record_key)여도 안정 식별자로
    매칭해 old를 은퇴 처리. 0027 구 SQL이라면 공개로 남았을 케이스(대조군)."""
    session = migrated_session

    entity = "월정리::제주::구좌읍"
    # 같은 안정 식별자, 다른 raw_payload_hash → 다른 source_record_key.
    await _insert_source_record(
        session,
        key="sr_old",
        provider="python-khoa-api",
        entity_id=entity,
        payload_hash=_payload_hash("OLD"),
    )
    await _insert_source_record(
        session,
        key="sr_new",
        provider="python-khoa-api",
        entity_id=entity,
        payload_hash=_payload_hash("NEW"),
        observed_at=_NOW + timedelta(hours=1),
    )
    await _insert_feature(session, feature_id="f_old", category="01020300")
    await _insert_feature(session, feature_id="f_new", category="01050100")
    await _link_primary(session, feature_id="f_old", record_key="sr_old")
    await _link_primary(session, feature_id="f_new", record_key="sr_new")
    await session.flush()

    # 0027 역사 SQL은 version key 동일성에 의존했음을 보존 확인한다.
    assert "new_sl.source_record_key = old_sl.source_record_key" in _old_0027_sql()

    # head equivalent: stable source_entity join → payload version drift와 무관하게
    # 재분류 대상이 공개 표면에서 교체된다.
    await session.execute(text(_cleanup_sql()))
    assert await _is_public(session, "f_old") is False
    assert await _is_public(session, "f_new") is True
    assert await _retirement(session, "f_old") == ("retired", "suppressed")
    assert await _retirement(session, "f_new") == ("active", "published")

    # 멱등 — 두 번째 실행도 동일(대상 가드가 이미 retired인 행을 다시 잡지 않는다).
    await session.execute(text(_cleanup_sql()))
    assert await _is_public(session, "f_old") is False
    assert await _is_public(session, "f_new") is True
    assert await _retirement(session, "f_old") == ("retired", "suppressed")


async def test_rekey_demotes_stale_old_primary_link(
    migrated_session: AsyncSession,
) -> None:
    """B: 정리 후 구 feature의 primary link가 non-primary role로 강등."""
    session = migrated_session

    entity = "협재::제주::한림읍"
    await _insert_source_record(
        session,
        key="sr_old2",
        provider="python-khoa-api",
        entity_id=entity,
        payload_hash=_payload_hash("OLD2"),
    )
    await _insert_source_record(
        session,
        key="sr_new2",
        provider="python-khoa-api",
        entity_id=entity,
        payload_hash=_payload_hash("NEW2"),
        observed_at=_NOW + timedelta(hours=1),
    )
    await _insert_feature(session, feature_id="f_old2", category="01020300")
    await _insert_feature(session, feature_id="f_new2", category="01050100")
    await _link_primary(session, feature_id="f_old2", record_key="sr_old2")
    await _link_primary(session, feature_id="f_new2", record_key="sr_new2")
    await session.flush()

    await session.execute(text(_cleanup_sql()))
    await session.execute(text(_demote_sql()))

    assert await _retirement(session, "f_old2") == ("retired", "suppressed")
    # 구 primary link는 강등, 신 primary link는 유지.
    assert (
        await _is_primary(session, feature_id="f_old2", record_key="sr_old2")
    ) is False
    assert (
        await _is_primary(session, feature_id="f_new2", record_key="sr_new2")
    ) is True

    # 멱등 — 두 번째 demote도 동일(이미 강등됨).
    await session.execute(text(_demote_sql()))
    assert (
        await _is_primary(session, feature_id="f_old2", record_key="sr_old2")
    ) is False


async def test_rekey_noop_when_only_old_exists(
    migrated_session: AsyncSession,
) -> None:
    """D: 신 sibling 없음(재import 미완료) → old가 공개 표면에 그대로(가용성 공백 방지)."""
    session = migrated_session

    await _insert_source_record(
        session,
        key="sr_lonely",
        provider="python-khoa-api",
        entity_id="함덕::제주::조천읍",
        payload_hash=_payload_hash("LONELY"),
    )
    await _insert_feature(session, feature_id="f_lonely_old", category="01020300")
    await _link_primary(session, feature_id="f_lonely_old", record_key="sr_lonely")
    await session.flush()

    await session.execute(text(_cleanup_sql()))
    await session.execute(text(_demote_sql()))

    assert await _is_public(session, "f_lonely_old") is True
    assert await _retirement(session, "f_lonely_old") == ("active", "published")
    assert (
        await _is_primary(session, feature_id="f_lonely_old", record_key="sr_lonely")
    ) is True
