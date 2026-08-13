"""``0080_feature_uuid_shadow`` ~ ``0083_nonderived_uuid_generator`` 검증 (ADR-068).

기존 행이 있는 DB(0078까지 적용 + seed)에 head까지 적용해 검증한다:

① 전 행 ``feature_uuid`` 채움 + NOT NULL + UNIQUE(``uq_features_feature_uuid``)
   — backfill 세대(0080)는 **파생값 그대로 영구 보존**된다(0082 identity fence).
② alias 1:1 — 모든 feature가 ``alias = feature_id`` legacy alias를 정확히
   1행 가진다 (freeze INV-068-01 post-backfill 판정과 동일 논리 + 쌍 일치)
③ 결정론 — 같은 legacy id를 **별도 DB**에서 재-backfill해도 같은 UUID이고,
   Python 정본(``core.ids.feature_uuid_from_legacy``)과도 일치한다
④ 신규 feature write(provider 경로·raw INSERT 경로·명시 uuid 경로)가 같은
   transaction에서 uuid + alias를 원자 생성한다 — **0083부터 신규 값은 비파생
   UUIDv7**이고 명시 비파생 값도 수용된다(파생 CHECK 2종 해제)
⑤ 0083 복합 FK(``fk_feature_aliases_identity_pair``) — alias 사본이 정본 쌍과
   다르면 DB가 선언적으로 거부한다
⑥ downgrade 무손실 왕복 — shadow 구조물만 제거되고 기존 행은 그대로,
   재-upgrade 시 같은 파생 UUID가 재계산된다. 0083 downgrade는 파생 CHECK를
   ``NOT VALID``로 복원해 신규 INSERT부터 파생 강제를 재개한다.

freeze 불변식 정합: ``contracts/vnext/target-invariants-v1.sql``의 INV-068-*를
그대로 실행해 0을 확인한다. 단 **INV-068-05는 제외** — 질의가
``provider_sync.source_entities.provider_dataset_id``(T-VN-33A 목표 컬럼)를
참조하는데 shadow 단계 현행 스키마에는 아직 없다(33A 소관).
"""

from __future__ import annotations

import asyncio
import re
import uuid as uuid_module
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
from kortravelmap.core.ids import feature_uuid_from_legacy, make_feature_uuid
from kortravelmap.infra.db import make_async_engine, normalize_async_dsn

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

pytestmark = pytest.mark.integration

_ROOT: Final = Path(__file__).resolve().parents[2]
_INVARIANTS_SQL: Final = _ROOT / "contracts" / "vnext" / "target-invariants-v1.sql"

_PREV_REVISION: Final = "0078_cache_target_gc_observe"

#: downgrade 왕복이 가능한 마지막 revision. 0089~0091(T-VN-33)은 forward-only이며
#: downgrade가 ``RuntimeError``로 fail-close한다("rebuild from final ETL"). ADR-068
#: shadow 구조물(0080~0083)의 무손실 왕복은 이 지점까지 올린 DB에서 판정한다 —
#: fence 위쪽 revision은 애초에 왕복 계약이 없으므로 검증 대상이 아니다.
_ROUNDTRIP_TOP_REVISION: Final = "0088_source_record_lineage_key"

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


def _sqlstate(error: BaseException) -> str | None:
    """DBAPIError에서 PostgreSQL SQLSTATE를 꺼낸다 (driver 표기 차이 흡수).

    문구 정규식 alternation으로 "아무거나 걸리면 통과"하는 느슨한 단언 대신
    제약 이름 + SQLSTATE를 정확히 단언하기 위한 헬퍼다 (32C 적대 리뷰 축).
    """
    for candidate in (getattr(error, "orig", None), error):
        for attribute in ("sqlstate", "pgcode"):
            value = getattr(candidate, attribute, None)
            if value:
                return str(value)
    return None


def _assert_nonderived_uuid_v7(value: object, *, feature_id: str) -> str:
    """0083 신규 행 정본 형태 단언 — canonical UUIDv7이고 파생값이 **아니다**."""
    text_value = str(value)
    parsed = uuid_module.UUID(text_value)
    assert str(parsed) == text_value, f"canonical 표기가 아님: {text_value!r}"
    assert parsed.version == 7, f"version 7이 아님: {text_value!r}"
    assert parsed.variant == uuid_module.RFC_4122
    assert (parsed.int >> 76) & 0xF == 0x7
    assert (parsed.int >> 62) & 0b11 == 0b10
    assert text_value != str(feature_uuid_from_legacy(feature_id)), (
        "0083 이후 신규 행은 legacy id 파생값이면 안 된다 (generator 미전환)."
    )
    return text_value


async def _upgrade(dsn: str, revision: str) -> None:
    # 배포와 같은 경로로 돈다 — bootstrap 후 migrator 자격으로 upgrade.
    from tests.integration._tvn34_migration_bootstrap import (
        alembic_schema_owner_role,
        bootstrapped_migrator_dsn,
    )

    migrator_dsn = await bootstrapped_migrator_dsn(dsn)
    with alembic_schema_owner_role():
        await asyncio.to_thread(
            command.upgrade, _alembic_config(migrator_dsn), revision
        )


async def _downgrade(dsn: str, revision: str) -> None:
    """downgrade도 upgrade와 **같은 principal**로 돌린다 (ADR-090).

    0095 이후 schema object의 owner는 ``ktm_feature_schema_owner``이고 배포는
    upgrade·downgrade 모두 migrator LOGIN → ``SET ROLE`` schema owner 한 경로로만
    돈다. 그런데 이 helper만 raw DSN(= DB 생성 계정, superuser)을 쓰고 있어서
    왕복 시나리오가 principal을 갈아탔다.

    superuser는 owner가 아니어도 DDL이 통과하므로 downgrade 자체는 성공하지만,
    0081 downgrade는 ``DROP VIEW`` + ``CREATE VIEW``로 ``feature.public_features``를
    **재생성**한다 — 새 view의 owner는 그때의 current_user, 즉 superuser가 된다.
    그 뒤 재-upgrade는 schema owner 자격으로 0081의
    ``CREATE OR REPLACE VIEW feature.public_features``를 걸고, PostgreSQL은
    REPLACE에 소유권을 요구하므로 ``must be owner of view public_features``
    (42501)로 죽는다. 즉 실패 원인은 legacy 컬럼(``status``/``deleted_at``)이
    아니라 왕복 도중 뒤바뀐 소유권이며, 0081의 legacy 술어는 그 세대의 정본이라
    그대로 두는 것이 맞다.

    downgrade를 upgrade와 같은 자격으로 돌리면 재생성된 view의 owner가 계속
    schema owner라 소유권이 왕복 내내 보존된다.
    """
    from tests.integration._tvn34_migration_bootstrap import (
        alembic_schema_owner_role,
        bootstrapped_migrator_dsn,
    )

    migrator_dsn = await bootstrapped_migrator_dsn(dsn)
    with alembic_schema_owner_role():
        await asyncio.to_thread(
            command.downgrade, _alembic_config(migrator_dsn), revision
        )


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


#: kind별 필수 detail — T-VN-35(ADR-086)의 0084/0085 backfill은
#: ``place_kind``/``event_kind``/``notice_type`` 결측을 NOT NULL로 fail-close한다.
#: 0078 시점 seed가 detail 없이 들어가면 head 재적용 자체가 막히므로, 이 시점의
#: core ``detail``에 필수 값을 넣어 둔다(당시 스키마에는 detail 컬럼이 있다).
_SEED_REQUIRED_DETAIL: Final[dict[str, str]] = {
    "place": '{"place_kind": "attraction"}',
    "event": '{"event_kind": "festival"}',
    "notice": '{"notice_type": "advisory"}',
}


async def _seed_features(dsn: str) -> None:
    """0078 시점 스키마에 seed 행을 넣는다 (soft-deleted 1행 포함)."""
    engine = make_async_engine(dsn)
    try:
        async with engine.begin() as connection:
            for feature_id, kind, name in _SEED_ROWS:
                await connection.execute(
                    text(
                        "INSERT INTO feature.features "
                        "(feature_id, kind, name, category, detail) "
                        "VALUES (:fid, :kind, :name, '01070100', CAST(:detail AS jsonb))"
                    ),
                    {
                        "fid": feature_id,
                        "kind": kind,
                        "name": name,
                        "detail": _SEED_REQUIRED_DETAIL.get(kind, "{}"),
                    },
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


async def _build_shadow_db(
    pg_container: Any,
    prefix: str,
    *,
    target: str = "head",
) -> tuple[str, str, str]:
    """새 DB에 0078 → seed → ``target``을 적용하고 (admin_dsn, dsn, database)를 반환."""
    admin_dsn = normalize_async_dsn(pg_container.get_connection_url())
    database = f"{prefix}_{uuid4().hex}"
    dsn = make_url(admin_dsn).set(database=database).render_as_string(hide_password=False)
    await _create_database(admin_dsn, database)
    await _upgrade(dsn, _PREV_REVISION)
    await _seed_features(dsn)
    await _upgrade(dsn, target)
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


async def test_0083_replaces_derivation_checks_with_declarative_copy_constraints(
    shadow_engine: AsyncEngine,
) -> None:
    """head(0083)에서 파생 CHECK 2종은 사라지고 복합 UNIQUE/FK가 대신 선다."""
    async with shadow_engine.connect() as connection:
        rows = list(
            await connection.execute(
                text(
                    "SELECT con.conname, con.confdeltype "
                    "FROM pg_catalog.pg_constraint AS con "
                    "JOIN pg_catalog.pg_class AS rel ON rel.oid = con.conrelid "
                    "JOIN pg_catalog.pg_namespace AS ns ON ns.oid = rel.relnamespace "
                    "WHERE ns.nspname = 'feature' "
                    "AND rel.relname IN ('features', 'feature_aliases')"
                )
            )
        )
        names = {row.conname for row in rows}
        deltype = {row.conname: row.confdeltype for row in rows}
        v7_function = (
            await connection.execute(
                text("SELECT to_regprocedure('feature.uuid_generate_v7()')")
            )
        ).scalar_one()
    assert "ck_features_feature_uuid_dual_derivation" not in names
    assert "ck_feature_aliases_uuid_dual_derivation" not in names
    assert "uq_features_identity_pair" in names
    assert "fk_feature_aliases_identity_pair" in names
    # H1 회귀 방어(재판정 M6) — 복합 FK는 반드시 CASCADE여야 한다. NO ACTION
    # 이면 기존 CASCADE FK와의 RI 트리거 이름순서 의존이 되살아나는데, CI의
    # 신선한 DB는 항상 정순이라 삭제 경로 테스트로는 잡히지 않는다.
    observed_deltype = deltype["fk_feature_aliases_identity_pair"]
    if isinstance(observed_deltype, bytes):  # asyncpg는 "char"를 bytes로 준다
        observed_deltype = observed_deltype.decode()
    assert observed_deltype == "c"
    # 파생 함수는 역사/downgrade 참조로 존속, v7 generator가 새로 선다.
    assert "ck_feature_aliases_legacy_identity" in names
    assert v7_function is not None


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
    admin_dsn, dsn, database = await _build_shadow_db(
        pg_container, "uuid_shadow_replay", target=_ROUNDTRIP_TOP_REVISION
    )
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
                        "'ensure_features_legacy_alias', 'uuid_generate_v7')"
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
        await _upgrade(dsn, _ROUNDTRIP_TOP_REVISION)
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

    0083 이후 fill 트리거의 산출은 파생값이 아니라 ``feature.uuid_generate_v7()``
    이다 — raw SQL 경로가 파생값을 받으면 app(v7)과 generator가 이원화된다.
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
    stored = _assert_nonderived_uuid_v7(row.feature_uuid, feature_id=feature_id)
    # AFTER 트리거의 alias 사본은 정본과 같은 값이다 (INV-068-01).
    assert str(row.alias_uuid) == stored
    assert row.alias == feature_id
    assert row.alias_kind == "legacy_feature_id"


async def test_sql_v7_generator_matches_app_generator_layout(
    migrated_session: AsyncSession,
) -> None:
    """``feature.uuid_generate_v7()``와 ``core.ids.make_feature_uuid()``의 레이아웃 동일성.

    fill 트리거(raw SQL 경로 안전망)와 app writer가 서로 다른 세대를 만들면
    generator 이원화이므로, version/variant 비트와 상위 48bit 타임스탬프의
    현실성을 양쪽에서 같은 축으로 단언한다.
    """
    sql_values = [
        str(
            (
                await migrated_session.execute(text("SELECT feature.uuid_generate_v7()"))
            ).scalar_one()
        )
        for _ in range(8)
    ]
    app_values = [str(make_feature_uuid()) for _ in range(8)]

    now_ms = int(
        (
            await migrated_session.execute(
                text("SELECT (extract(epoch FROM clock_timestamp()) * 1000)::bigint")
            )
        ).scalar_one()
    )
    for value in (*sql_values, *app_values):
        parsed = uuid_module.UUID(value)
        assert str(parsed) == value
        assert parsed.version == 7
        assert parsed.variant == uuid_module.RFC_4122
        assert (parsed.int >> 76) & 0xF == 0x7
        assert (parsed.int >> 62) & 0b11 == 0b10
        # 상위 48bit는 unix-ms — 같은 시각 축(하루 여유)에 놓인다.
        assert abs((parsed.int >> 80) - now_ms) < 86_400_000
    # 비파생·비결정 — 호출마다 다르다(양쪽 모두).
    assert len(set(sql_values)) == len(sql_values)
    assert len(set(app_values)) == len(app_values)


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
    # 0083 정본 generator — writer가 명시 바인드한 비파생 v7 후보가 저장된다.
    stored = _assert_nonderived_uuid_v7(feature_uuid, feature_id=feature_id)
    assert alias_count == 1

    # 재적재(ON CONFLICT DO UPDATE 경로) — uuid 불변·alias 중복 없음. DTO를
    # 변형하지 않고 같은 feature를 다시 upsert해도 UPDATE 분기가 실행된다
    # (upsert SQL은 feature_uuid를 SET 목록에 두지 않으므로 **버려진 새 후보**가
    # 아니라 기존 저장값이 정본으로 남는다 — 32C verify의 inserted=False 축).
    inserted_again = await feature_repo.upsert_feature(
        migrated_session,
        bundle.feature,
        provider_dataset_id=await feature_repo.resolve_active_provider_dataset_id(
            migrated_session,
            provider=bundle.source_record.provider,
            dataset_key=bundle.source_record.dataset_key,
        ),
        source_membership=feature_repo._ProviderSourceMembership(
            source_entity_key=feature_repo._make_source_entity_key(
                provider=bundle.source_record.provider,
                dataset_key=bundle.source_record.dataset_key,
                source_entity_type=bundle.source_record.source_entity_type,
                source_entity_id=bundle.source_record.source_entity_id,
            ),
            source_record_key=bundle.source_record.source_record_key,
        ),
    )
    assert inserted_again is False
    feature_uuid_after, alias_count_after = await _pair()
    assert feature_uuid_after == stored
    assert alias_count_after == 1


async def test_explicit_nonderived_feature_uuid_is_accepted_and_mirrored(
    migrated_session: AsyncSession,
) -> None:
    """0083 반전 계약 — 명시 **비파생** canonical uuid INSERT가 수용된다.

    32B는 파생 CHECK(``ck_features_feature_uuid_dual_derivation``)로 비파생
    명시 값을 23514로 거부했다. 0083이 그 CHECK를 세트로 해제했으므로 이제
    writer가 만든 v7 후보가 그대로 저장되고, AFTER 트리거가 같은 값을 alias
    행에 원자 복사한다(INV-068-01은 유지).
    """
    feature_id = "f_global_p_shadow_explicit_01"
    explicit = str(make_feature_uuid())
    assert explicit != str(feature_uuid_from_legacy(feature_id))

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
                "SELECT CAST(f.feature_uuid AS text) AS feature_uuid, "
                "       CAST(a.feature_uuid AS text) AS alias_uuid, "
                "       a.alias AS alias, a.alias_kind AS alias_kind "
                "FROM feature.features AS f "
                "JOIN feature.feature_aliases AS a ON a.feature_id = f.feature_id "
                "WHERE f.feature_id = :fid"
            ),
            {"fid": feature_id},
        )
    ).one()
    # 명시 값 존중 — 트리거는 NULL일 때만 채운다(0083도 이 분기는 유지).
    assert row.feature_uuid == explicit
    assert row.alias_uuid == explicit
    assert row.alias == feature_id
    assert row.alias_kind == "legacy_feature_id"

    # 파생값을 명시해도 여전히 합법이다 — 0083은 "파생 금지"가 아니라
    # "파생 강제 해제"다(기존 731,600행 세대와의 공존 전제).
    legacy_style = "f_global_p_shadow_explicit_02"
    derived = str(feature_uuid_from_legacy(legacy_style))
    await migrated_session.execute(
        text(
            "INSERT INTO feature.features (feature_id, feature_uuid, kind, name, category) "
            "VALUES (:fid, CAST(:uuid AS uuid), 'place', 'derived uuid', '01070100')"
        ),
        {"fid": legacy_style, "uuid": derived},
    )
    stored = (
        await migrated_session.execute(
            text(
                "SELECT CAST(feature_uuid AS text) FROM feature.features "
                "WHERE feature_id = :fid"
            ),
            {"fid": legacy_style},
        )
    ).scalar_one()
    assert stored == derived


# ── ⑤ 복합 FK — alias 사본 불일치의 선언적 차단 ────────────────────────────


async def test_alias_copy_mismatch_is_rejected_by_identity_pair_fk(
    migrated_session: AsyncSession,
) -> None:
    """0083 복합 FK — alias 행의 uuid가 정본 쌍과 다르면 INSERT가 23503으로 죽는다.

    0082 fence는 alias UPDATE/DELETE만 막고 **INSERT는 막지 않는다**. 파생
    CHECK 2종이 사라진 뒤 이 축을 지키는 것은
    ``fk_feature_aliases_identity_pair`` 하나이므로 직접 INSERT로 실측한다.
    AFTER 트리거를 잠시 끄고 alias 없는 feature 행을 만들어(alias PK 충돌을
    피해) FK 축만 남긴다 — transaction rollback으로 원복된다.
    """
    from sqlalchemy.exc import DBAPIError

    feature_id = "f_global_p_shadow_fk_probe_1"
    await migrated_session.execute(
        text(
            "ALTER TABLE feature.features DISABLE TRIGGER trg_features_legacy_alias"
        )
    )
    await migrated_session.execute(
        text(
            "INSERT INTO feature.features (feature_id, kind, name, category) "
            "VALUES (:fid, 'place', 'fk probe', '01070100')"
        ),
        {"fid": feature_id},
    )
    await migrated_session.execute(
        text("ALTER TABLE feature.features ENABLE TRIGGER trg_features_legacy_alias")
    )
    canonical = (
        await migrated_session.execute(
            text(
                "SELECT CAST(feature_uuid AS text) FROM feature.features "
                "WHERE feature_id = :fid"
            ),
            {"fid": feature_id},
        )
    ).scalar_one()

    # ① 정본과 **다른** canonical uuid 사본 — 복합 FK가 유일한 방어선이다.
    with pytest.raises(DBAPIError) as excinfo:
        async with migrated_session.begin_nested():
            await migrated_session.execute(
                text(
                    "INSERT INTO feature.feature_aliases "
                    "(alias, feature_id, feature_uuid, alias_kind) VALUES "
                    "(:fid, :fid, CAST(:uuid AS uuid), 'legacy_feature_id')"
                ),
                {"fid": feature_id, "uuid": str(make_feature_uuid())},
            )
    assert "fk_feature_aliases_identity_pair" in str(excinfo.value)
    assert _sqlstate(excinfo.value) == "23503"

    # ② 정본과 같은 쌍이면 통과한다 (FK가 사본 일치만 강제한다는 증거).
    async with migrated_session.begin_nested():
        await migrated_session.execute(
            text(
                "INSERT INTO feature.feature_aliases "
                "(alias, feature_id, feature_uuid, alias_kind) VALUES "
                "(:fid, :fid, CAST(:uuid AS uuid), 'legacy_feature_id')"
            ),
            {"fid": feature_id, "uuid": canonical},
        )


# ── ⑥ 0083 downgrade — 파생 강제 재개(NOT VALID) ───────────────────────────


async def test_0083_downgrade_restores_not_valid_derivation_checks_and_reupgrades(
    pg_container: Any,
) -> None:
    """0083 downgrade는 파생 CHECK를 ``NOT VALID``로 복원하고 신규 INSERT를 다시 막는다."""
    from sqlalchemy.exc import DBAPIError

    admin_dsn, dsn, database = await _build_shadow_db(
        pg_container, "uuid_shadow_0083", target=_ROUNDTRIP_TOP_REVISION
    )
    engine = None
    try:
        await _downgrade(dsn, "0082_legacy_write_fence")
        engine = make_async_engine(dsn)
        async with engine.connect() as connection:
            constraints = {
                row.conname: row.convalidated
                for row in await connection.execute(
                    text(
                        "SELECT con.conname, con.convalidated "
                        "FROM pg_catalog.pg_constraint AS con "
                        "JOIN pg_catalog.pg_class AS rel ON rel.oid = con.conrelid "
                        "JOIN pg_catalog.pg_namespace AS ns ON ns.oid = rel.relnamespace "
                        "WHERE ns.nspname = 'feature' "
                        "AND con.conname IN ("
                        "'ck_features_feature_uuid_dual_derivation', "
                        "'ck_feature_aliases_uuid_dual_derivation', "
                        "'uq_features_identity_pair', "
                        "'fk_feature_aliases_identity_pair')"
                    )
                )
            }
            v7_function = (
                await connection.execute(
                    text("SELECT to_regprocedure('feature.uuid_generate_v7()')")
                )
            ).scalar_one()
        # 파생 CHECK 2종이 NOT VALID로 복원되고, 0083 대체물은 사라진다.
        assert constraints["ck_features_feature_uuid_dual_derivation"] is False
        assert constraints["ck_feature_aliases_uuid_dual_derivation"] is False
        assert "uq_features_identity_pair" not in constraints
        assert "fk_feature_aliases_identity_pair" not in constraints
        assert v7_function is None

        # NOT VALID여도 **신규 INSERT는 검사된다** — 파생 강제 재개.
        async with engine.connect() as connection:
            with pytest.raises(DBAPIError) as excinfo:
                await connection.execute(
                    text(
                        "INSERT INTO feature.features "
                        "(feature_id, feature_uuid, kind, name, category) VALUES "
                        "(:fid, CAST(:uuid AS uuid), 'place', 'post-downgrade', "
                        "'01070100')"
                    ),
                    {
                        "fid": "f_global_p_shadow_dg_probe",
                        "uuid": str(make_feature_uuid()),
                    },
                )
            assert "ck_features_feature_uuid_dual_derivation" in str(excinfo.value)
            assert _sqlstate(excinfo.value) == "23514"
            await connection.rollback()

        # 파생값 INSERT는 통과하고 fill 트리거도 파생판으로 되돌아왔다.
        derived_id = "f_global_p_shadow_dg_derived"
        async with engine.connect() as connection:
            await connection.execute(
                text(
                    "INSERT INTO feature.features (feature_id, kind, name, category) "
                    "VALUES (:fid, 'place', 'post-downgrade fill', '01070100')"
                ),
                {"fid": derived_id},
            )
            filled = (
                await connection.execute(
                    text(
                        "SELECT CAST(feature_uuid AS text) FROM feature.features "
                        "WHERE feature_id = :fid"
                    ),
                    {"fid": derived_id},
                )
            ).scalar_one()
            assert filled == str(feature_uuid_from_legacy(derived_id))
            await connection.rollback()
        await engine.dispose()
        engine = None

        # 재-upgrade — 0083이 다시 적용되고 비파생 INSERT가 되살아난다.
        await _upgrade(dsn, _ROUNDTRIP_TOP_REVISION)
        engine = make_async_engine(dsn)
        async with engine.begin() as connection:
            reupgraded = "f_global_p_shadow_reupgrade"
            await connection.execute(
                text(
                    "INSERT INTO feature.features (feature_id, kind, name, category) "
                    "VALUES (:fid, 'place', 're-upgrade', '01070100')"
                ),
                {"fid": reupgraded},
            )
            value = (
                await connection.execute(
                    text(
                        "SELECT CAST(feature_uuid AS text) FROM feature.features "
                        "WHERE feature_id = :fid"
                    ),
                    {"fid": reupgraded},
                )
            ).scalar_one()
            _assert_nonderived_uuid_v7(value, feature_id=reupgraded)
    finally:
        if engine is not None:
            await engine.dispose()
        await _drop_database(admin_dsn, database)
