"""``0079_feature_uuid_shadow`` migration 검증 (T-VN-32A, ADR-068).

기존 행이 있는 DB(0078까지 적용 + seed)에 0079를 적용해 검증한다:

① 전 행 ``feature_uuid`` 채움 + NOT NULL + UNIQUE(``uq_features_feature_uuid``)
② alias 1:1 — 모든 feature가 ``alias = feature_id`` legacy alias를 정확히
   1행 가진다 (freeze INV-068-01 post-backfill 판정과 동일 논리 + 쌍 일치)
③ 결정론 — 같은 legacy id를 **별도 DB**에서 재-backfill해도 같은 UUID이고,
   Python 정본(``core.ids.feature_uuid_from_legacy``)과도 일치한다
④ 신규 feature upsert(provider 경로·raw INSERT 경로)가 같은 transaction에서
   uuid + alias를 원자 생성한다
⑤ downgrade 무손실 왕복 — shadow 구조물만 제거되고 기존 행은 그대로,
   재-upgrade 시 같은 UUID가 재계산된다

freeze 불변식 정합: ``contracts/vnext/target-invariants-v1.sql``의 INV-068-*를
그대로 실행해 0을 확인한다. 단 **INV-068-05는 제외** — 질의가
``provider_sync.source_entities.provider_dataset_id``(T-VN-33A 목표 컬럼)를
참조하는데 shadow 단계 현행 스키마에는 아직 없다(33A 소관).
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final
from uuid import uuid4

import pytest
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.engine import make_url

from alembic import command
from kortravelmap.core.ids import feature_uuid_from_legacy
from kortravelmap.infra.db import make_async_engine, normalize_async_dsn

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

pytestmark = pytest.mark.integration

_ROOT: Final = Path(__file__).resolve().parents[2]
_INVARIANTS_SQL: Final = _ROOT / "contracts" / "vnext" / "target-invariants-v1.sql"

_PREV_REVISION: Final = "0078_cache_target_gc_observe"

# 33A 목표 컬럼(provider_dataset_id)을 참조해 shadow 스키마에서 실행 불가.
_INVARIANTS_NOT_RUNNABLE_ON_SHADOW: Final = frozenset({"INV-068-05"})

_KST: Final = timezone(timedelta(hours=9))


@dataclass(frozen=True)
class _Festival:
    """``CulturalFestivalItem`` Protocol 만족 (test_feature_repo_load와 동일 shape).

    cross-test-module import 대신 로컬 정의 — pytest rootdir import 모드에
    의존하지 않는다.
    """

    fstvl_nm: str | None
    opar: str | None = None
    fstvl_start_date: date | None = None
    fstvl_end_date: date | None = None
    fstvl_co: str | None = None
    mnnst_nm: str | None = None
    auspc_instt_nm: str | None = None
    suprt_instt_nm: str | None = None
    phone_number: str | None = None
    homepage_url: str | None = None
    relate_info: str | None = None
    rdnmadr: str | None = None
    lnmadr: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    reference_date: date | None = None
    instt_code: str | None = None
    instt_nm: str | None = None


# seed — 단위 테스트 고정 벡터 2개 + 비-ASCII id + soft-deleted 행.
_SEED_ROWS: Final[tuple[tuple[str, str, str], ...]] = (
    ("f_1168010100_p_3c0c2820e96d28d3", "place", "문서 예제 장소"),
    ("f_global_e_0123456789abcdef", "event", "고정 벡터 이벤트"),
    ("feature:레거시-한글-id", "place", "한글 legacy id"),
    ("f_global_n_deadbeef00000000", "notice", "삭제된 공지"),
)
_SOFT_DELETED_ID: Final = "f_global_n_deadbeef00000000"


def _alembic_config(dsn: str) -> Config:
    config = Config(str(_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(_ROOT / "alembic"))
    config.set_main_option("sqlalchemy.url", dsn)
    return config


async def _upgrade(dsn: str, revision: str) -> None:
    await asyncio.to_thread(command.upgrade, _alembic_config(dsn), revision)


async def _downgrade(dsn: str, revision: str) -> None:
    await asyncio.to_thread(command.downgrade, _alembic_config(dsn), revision)


async def _create_database(admin_dsn: str, database: str) -> None:
    admin_engine = make_async_engine(admin_dsn)
    try:
        async with admin_engine.connect() as connection:
            autocommit = await connection.execution_options(isolation_level="AUTOCOMMIT")
            await autocommit.execute(text(f'CREATE DATABASE "{database}"'))
    finally:
        await admin_engine.dispose()


async def _drop_database(admin_dsn: str, database: str) -> None:
    admin_engine = make_async_engine(admin_dsn)
    try:
        async with admin_engine.connect() as connection:
            autocommit = await connection.execution_options(isolation_level="AUTOCOMMIT")
            await autocommit.execute(text(f'DROP DATABASE IF EXISTS "{database}" WITH (FORCE)'))
    finally:
        await admin_engine.dispose()


async def _seed_features(dsn: str) -> None:
    """0078 시점 스키마에 seed 행을 넣는다 (soft-deleted 1행 포함)."""
    engine = make_async_engine(dsn)
    try:
        async with engine.begin() as connection:
            for feature_id, kind, name in _SEED_ROWS:
                await connection.execute(
                    text(
                        "INSERT INTO feature.features (feature_id, kind, name, category) "
                        "VALUES (:fid, :kind, :name, '01070100')"
                    ),
                    {"fid": feature_id, "kind": kind, "name": name},
                )
            await connection.execute(
                text(
                    "UPDATE feature.features "
                    "SET status = 'deleted', deleted_at = now() "
                    "WHERE feature_id = :fid"
                ),
                {"fid": _SOFT_DELETED_ID},
            )
    finally:
        await engine.dispose()


async def _build_shadow_db(pg_container: Any, prefix: str) -> tuple[str, str, str]:
    """새 DB에 0078 → seed → head를 적용하고 (admin_dsn, dsn, database)를 반환."""
    admin_dsn = normalize_async_dsn(pg_container.get_connection_url())
    database = f"{prefix}_{uuid4().hex}"
    dsn = make_url(admin_dsn).set(database=database).render_as_string(hide_password=False)
    await _create_database(admin_dsn, database)
    await _upgrade(dsn, _PREV_REVISION)
    await _seed_features(dsn)
    await _upgrade(dsn, "head")
    return admin_dsn, dsn, database


@pytest.fixture(scope="module")
async def shadow_engine(pg_container: Any) -> AsyncIterator[AsyncEngine]:
    """0078 + seed + head가 적용된 module 전용 DB engine."""
    admin_dsn, dsn, database = await _build_shadow_db(pg_container, "uuid_shadow")
    engine = make_async_engine(dsn)
    try:
        yield engine
    finally:
        await engine.dispose()
        await _drop_database(admin_dsn, database)


def _load_inv_068_queries() -> list[tuple[str, str, str]]:
    """target-invariants-v1.sql에서 (식별자, 질의, phase)를 파싱한다 (INV-068-*)."""
    content = _INVARIANTS_SQL.read_text(encoding="utf-8")
    parsed = re.findall(
        r"(?ms)^-- \[(INV-068-\d+)\][^\n]*\n(?:^--[^\n]*\n)*"
        r"(SELECT .*?); -- expect: 0 -- phase: (pre-backfill|post-backfill|both)$",
        content,
    )
    if not parsed:
        raise AssertionError("INV-068-* assertion 파싱 실패 — freeze artifact 형식 변경?")
    return [(identifier, query, phase) for identifier, query, phase in parsed]


# ── ① backfill 완전성 + UNIQUE/NOT NULL ────────────────────────────────────


async def test_backfill_fills_every_row_with_deterministic_uuid(
    shadow_engine: AsyncEngine,
) -> None:
    async with shadow_engine.connect() as connection:
        rows = (
            await connection.execute(text("SELECT feature_id, feature_uuid FROM feature.features"))
        ).all()
    assert len(rows) == len(_SEED_ROWS)
    for feature_id, feature_uuid in rows:
        assert feature_uuid is not None
        # soft-deleted 행 포함 전 행이 Python 정본과 같은 파생값이다.
        assert str(feature_uuid) == str(feature_uuid_from_legacy(feature_id))


async def test_feature_uuid_is_not_null_and_unique_constraint_attached(
    shadow_engine: AsyncEngine,
) -> None:
    async with shadow_engine.connect() as connection:
        not_null = (
            await connection.execute(
                text(
                    "SELECT is_nullable FROM information_schema.columns "
                    "WHERE table_schema = 'feature' AND table_name = 'features' "
                    "AND column_name = 'feature_uuid'"
                )
            )
        ).scalar_one()
        constraint_type = (
            await connection.execute(
                text(
                    "SELECT con.contype FROM pg_catalog.pg_constraint AS con "
                    "JOIN pg_catalog.pg_class AS rel ON rel.oid = con.conrelid "
                    "JOIN pg_catalog.pg_namespace AS ns ON ns.oid = rel.relnamespace "
                    "WHERE ns.nspname = 'feature' AND rel.relname = 'features' "
                    "AND con.conname = 'uq_features_feature_uuid'"
                )
            )
        ).scalar_one()
    assert not_null == "NO"
    raw_type = (
        constraint_type.decode("ascii")
        if isinstance(constraint_type, bytes)
        else str(constraint_type)
    )
    assert raw_type == "u"


# ── ② alias 1:1 (INV-068-01 post-backfill 논리 + 쌍 일치) ──────────────────


async def test_alias_backfill_is_one_to_one_with_matching_pairs(
    shadow_engine: AsyncEngine,
) -> None:
    async with shadow_engine.connect() as connection:
        # INV-068-01과 동일 논리 — alias 없는 feature 0.
        missing = (
            await connection.execute(
                text(
                    "SELECT count(*) FROM feature.features AS f "
                    "LEFT JOIN feature.feature_aliases AS a ON a.feature_id = f.feature_id "
                    "WHERE a.alias IS NULL"
                )
            )
        ).scalar_one()
        # 1:1 — legacy alias는 feature당 정확히 1행이고 쌍이 전부 일치한다.
        mismatched = (
            await connection.execute(
                text(
                    "SELECT count(*) FROM feature.feature_aliases AS a "
                    "JOIN feature.features AS f ON f.feature_id = a.feature_id "
                    "WHERE a.alias <> a.feature_id "
                    "   OR a.feature_uuid <> f.feature_uuid "
                    "   OR a.alias_kind <> 'legacy_feature_id'"
                )
            )
        ).scalar_one()
        alias_count = (
            await connection.execute(text("SELECT count(*) FROM feature.feature_aliases"))
        ).scalar_one()
    assert missing == 0
    assert mismatched == 0
    assert alias_count == len(_SEED_ROWS)


async def test_freeze_inv_068_invariants_hold_on_shadow_schema(
    shadow_engine: AsyncEngine,
) -> None:
    """INV-068-*를 freeze artifact에서 그대로 실행한다 (05는 33A 컬럼 참조로 제외)."""
    queries = _load_inv_068_queries()
    identifiers = {identifier for identifier, _, _ in queries}
    assert {"INV-068-01", "INV-068-02", "INV-068-03", "INV-068-04"} <= identifiers
    async with shadow_engine.connect() as connection:
        for identifier, query, phase in queries:
            if identifier in _INVARIANTS_NOT_RUNNABLE_ON_SHADOW:
                continue
            observed = (await connection.execute(text(query))).scalar_one()
            assert observed == 0, f"{identifier} 위반 (phase {phase}): {observed}"


# ── ③ 결정론 (별도 DB) + ⑤ downgrade 무손실 왕복 ───────────────────────────


async def test_determinism_across_databases_and_lossless_downgrade_roundtrip(
    pg_container: Any,
    shadow_engine: AsyncEngine,
) -> None:
    admin_dsn, dsn, database = await _build_shadow_db(pg_container, "uuid_shadow_replay")
    engine = None
    try:
        # ③ 같은 legacy id → 별도 DB에서도 같은 UUID (snapshot 재실행 결정성).
        async with shadow_engine.connect() as connection:
            baseline = {
                row.feature_id: str(row.feature_uuid)
                for row in await connection.execute(
                    text("SELECT feature_id, feature_uuid FROM feature.features")
                )
            }
        engine = make_async_engine(dsn)
        async with engine.connect() as connection:
            replay = {
                row.feature_id: str(row.feature_uuid)
                for row in await connection.execute(
                    text("SELECT feature_id, feature_uuid FROM feature.features")
                )
            }
            # DB SQL 함수와 Python 정본의 상호 일치(고정 벡터 포함 전 seed).
            for feature_id, _, _ in _SEED_ROWS:
                db_value = (
                    await connection.execute(
                        text("SELECT feature.feature_uuid_from_legacy(:fid)"),
                        {"fid": feature_id},
                    )
                ).scalar_one()
                assert str(db_value) == str(feature_uuid_from_legacy(feature_id))
        assert replay == baseline
        await engine.dispose()
        engine = None

        # ⑤ downgrade — shadow 구조물만 사라지고 기존 행은 무손실.
        await _downgrade(dsn, _PREV_REVISION)
        engine = make_async_engine(dsn)
        async with engine.connect() as connection:
            shadow_column = (
                await connection.execute(
                    text(
                        "SELECT count(*) FROM information_schema.columns "
                        "WHERE table_schema = 'feature' AND table_name = 'features' "
                        "AND column_name = 'feature_uuid'"
                    )
                )
            ).scalar_one()
            alias_table = (
                await connection.execute(text("SELECT to_regclass('feature.feature_aliases')"))
            ).scalar_one()
            leftover_functions = (
                await connection.execute(
                    text(
                        "SELECT count(*) FROM pg_catalog.pg_proc AS proc "
                        "JOIN pg_catalog.pg_namespace AS ns ON ns.oid = proc.pronamespace "
                        "WHERE ns.nspname = 'feature' AND proc.proname IN ("
                        "'feature_uuid_from_legacy', 'fill_features_feature_uuid', "
                        "'ensure_features_legacy_alias')"
                    )
                )
            ).scalar_one()
            surviving = {
                row.feature_id: row.name
                for row in await connection.execute(
                    text("SELECT feature_id, name FROM feature.features")
                )
            }
        assert shadow_column == 0
        assert alias_table is None
        assert leftover_functions == 0
        assert surviving == {feature_id: name for feature_id, _, name in _SEED_ROWS}
        await engine.dispose()
        engine = None

        # 재-upgrade — 같은 UUID가 재계산된다 (파생값 왕복 결정성).
        await _upgrade(dsn, "head")
        engine = make_async_engine(dsn)
        async with engine.connect() as connection:
            recomputed = {
                row.feature_id: str(row.feature_uuid)
                for row in await connection.execute(
                    text("SELECT feature_id, feature_uuid FROM feature.features")
                )
            }
        assert recomputed == baseline
    finally:
        if engine is not None:
            await engine.dispose()
        await _drop_database(admin_dsn, database)


# ── ④ 신규 feature write가 uuid + alias를 원자 생성 ────────────────────────


async def test_new_feature_raw_insert_gets_uuid_and_alias_atomically(
    migrated_session: AsyncSession,
) -> None:
    """raw INSERT(admin add·테스트 seed와 동일 경로)에서 트리거가 쌍을 만든다.

    ``migrated_session``은 commit하지 않으므로, 같은 transaction 안에서 보이는
    것 자체가 원자성(같은 tx) 증거다.
    """
    feature_id = "f_global_p_shadow_insert_01"
    await migrated_session.execute(
        text(
            "INSERT INTO feature.features (feature_id, kind, name, category) "
            "VALUES (:fid, 'place', 'shadow insert', '01070100')"
        ),
        {"fid": feature_id},
    )
    row = (
        await migrated_session.execute(
            text(
                "SELECT f.feature_uuid AS feature_uuid, a.alias AS alias, "
                "a.alias_kind AS alias_kind, a.feature_uuid AS alias_uuid "
                "FROM feature.features AS f "
                "JOIN feature.feature_aliases AS a ON a.feature_id = f.feature_id "
                "WHERE f.feature_id = :fid"
            ),
            {"fid": feature_id},
        )
    ).one()
    expected = str(feature_uuid_from_legacy(feature_id))
    assert str(row.feature_uuid) == expected
    assert str(row.alias_uuid) == expected
    assert row.alias == feature_id
    assert row.alias_kind == "legacy_feature_id"


async def test_provider_upsert_creates_uuid_and_alias_and_is_idempotent(
    migrated_session: AsyncSession,
) -> None:
    """provider bundle 적재 경로(upsert_feature)의 원자 생성 + 재적재 안정성."""
    from kortravelmap.infra import feature_repo
    from kortravelmap.providers.standard_data import cultural_festivals_to_bundles

    item = _Festival(
        fstvl_nm="UUID shadow 축제",
        rdnmadr="서울특별시 영등포구 여의공원로 120 (uuid-shadow)",
        latitude=37.5263,
        longitude=126.9239,
        reference_date=date(2026, 3, 1),
        instt_nm="서울특별시 영등포구",
    )
    bundle = (
        await cultural_festivals_to_bundles(
            [item],  # type: ignore[list-item]
            fetched_at=datetime(2026, 8, 1, 12, 0, tzinfo=_KST),
        )
    )[0]
    result = await feature_repo.load_bundle(migrated_session, bundle)
    assert result.features_inserted == 1

    feature_id = bundle.feature.feature_id
    expected = str(feature_uuid_from_legacy(feature_id))

    async def _pair() -> tuple[str, int]:
        feature_uuid = (
            await migrated_session.execute(
                text("SELECT feature_uuid FROM feature.features WHERE feature_id = :fid"),
                {"fid": feature_id},
            )
        ).scalar_one()
        alias_count = (
            await migrated_session.execute(
                text(
                    "SELECT count(*) FROM feature.feature_aliases "
                    "WHERE feature_id = :fid AND alias = :fid "
                    "AND alias_kind = 'legacy_feature_id'"
                ),
                {"fid": feature_id},
            )
        ).scalar_one()
        return str(feature_uuid), int(alias_count)

    feature_uuid, alias_count = await _pair()
    assert feature_uuid == expected
    assert alias_count == 1

    # 재적재(ON CONFLICT DO UPDATE 경로) — uuid 불변·alias 중복 없음. DTO를
    # 변형하지 않고 같은 feature를 다시 upsert해도 UPDATE 분기가 실행된다
    # (upsert SQL은 feature_uuid를 SET 목록에 두지 않아 파생값이 유지된다).
    inserted_again = await feature_repo.upsert_feature(migrated_session, bundle.feature)
    assert inserted_again is False
    feature_uuid_after, alias_count_after = await _pair()
    assert feature_uuid_after == expected
    assert alias_count_after == 1


async def test_explicitly_provided_feature_uuid_is_respected(
    migrated_session: AsyncSession,
) -> None:
    """트리거는 NULL일 때만 채운다 — 32B writer의 명시 값 전달과 호환."""
    feature_id = "f_global_p_shadow_explicit_01"
    explicit = "00000000-0000-4000-8000-000000000001"
    await migrated_session.execute(
        text(
            "INSERT INTO feature.features (feature_id, feature_uuid, kind, name, category) "
            "VALUES (:fid, CAST(:uuid AS uuid), 'place', 'explicit uuid', '01070100')"
        ),
        {"fid": feature_id, "uuid": explicit},
    )
    row = (
        await migrated_session.execute(
            text(
                "SELECT f.feature_uuid AS feature_uuid, a.feature_uuid AS alias_uuid "
                "FROM feature.features AS f "
                "JOIN feature.feature_aliases AS a ON a.feature_id = f.feature_id "
                "WHERE f.feature_id = :fid"
            ),
            {"fid": feature_id},
        )
    ).one()
    assert str(row.feature_uuid) == explicit
    assert str(row.alias_uuid) == explicit
