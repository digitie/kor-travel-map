"""``0081_legacy_write_fence`` + alias-map 이관 표면 검증 (T-VN-32C, ADR-068).

consumer-rollout-v1 T-VN-32 write_fence의 DB 층 착지를 회귀 고정한다:

① alias map 불변 — ``feature_aliases`` UPDATE 전면 거부, 직접 DELETE 거부,
   feature 행 삭제의 FK CASCADE 경유 삭제만 허용
② identity 불변 — ``features.feature_id``/``feature_uuid`` UPDATE 거부
③ legacy-only write는 여전히 구조적으로 불가능 — uuid 없는 raw INSERT는
   0079 fill/alias 트리거 + 0080 파생 CHECK가 완결한다 (32C 재평가: 유지)
④ alias-map 이관 표면 — checksum(merkle root) 독립 재계산 일치 + canonical
   순서 keyset 페이지 완전 순회
⑤ fail-close — 파생 불일치·비-NFC alias가 저장 층에 존재하면(보장 붕괴 시나리오)
   페이지/checksum 대신 :class:`FeatureAliasMapIntegrityError`
⑥ downgrade 왕복 — fence 구조물만 제거·복원되고 데이터 무변경
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final
from uuid import uuid4

import pytest
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError

from alembic import command
from kortravelmap.core.feature_alias_map import (
    FeatureAliasMapRowV1,
    feature_alias_map_merkle_root,
)
from kortravelmap.core.ids import feature_uuid_from_legacy
from kortravelmap.infra.db import make_async_engine, normalize_async_dsn
from kortravelmap.infra.feature_alias_map_repo import (
    FeatureAliasMapIntegrityError,
    compute_feature_alias_map_checksum,
    fetch_feature_alias_map_page,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from sqlalchemy.ext.asyncio import AsyncEngine

pytestmark = pytest.mark.integration

_ROOT: Final = Path(__file__).resolve().parents[2]

# canonical 순서(UTF-8 byte 오름차순)가 ASCII → 비-ASCII로 갈리는 seed.
_SEED_IDS: Final[tuple[str, ...]] = (
    "f_1168010100_p_3c0c2820e96d28d3",
    "f_global_e_0123456789abcdef",
    "f_global_w_00ff00ff00ff00ff",
    "feature:레거시-한글-id",
)


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


async def _seed_features(engine: AsyncEngine, feature_ids: tuple[str, ...]) -> None:
    """head 스키마에 raw INSERT — 0079 fill/alias 트리거가 uuid·alias를 채운다."""
    async with engine.begin() as connection:
        for feature_id in feature_ids:
            await connection.execute(
                text(
                    "INSERT INTO feature.features (feature_id, kind, name, category) "
                    "VALUES (:fid, 'place', :name, '01070100')"
                ),
                {"fid": feature_id, "name": f"fence-{feature_id[:24]}"},
            )


async def _build_fence_db(pg_container: Any, prefix: str) -> tuple[str, str, str]:
    admin_dsn = normalize_async_dsn(pg_container.get_connection_url())
    database = f"{prefix}_{uuid4().hex}"
    dsn = make_url(admin_dsn).set(database=database).render_as_string(hide_password=False)
    await _create_database(admin_dsn, database)
    await _upgrade(dsn, "head")
    return admin_dsn, dsn, database


@pytest.fixture(scope="module")
async def fence_engine(pg_container: Any) -> AsyncIterator[AsyncEngine]:
    """head(0081 포함) + seed가 적용된 module 전용 DB engine."""
    admin_dsn, dsn, database = await _build_fence_db(pg_container, "legacy_fence")
    engine = make_async_engine(dsn)
    try:
        await _seed_features(engine, _SEED_IDS)
        yield engine
    finally:
        await engine.dispose()
        await _drop_database(admin_dsn, database)


def _expected_rows(feature_ids: tuple[str, ...]) -> list[FeatureAliasMapRowV1]:
    return [
        FeatureAliasMapRowV1(
            alias=feature_id,
            feature_uuid=str(feature_uuid_from_legacy(feature_id)),
            alias_kind="legacy_feature_id",
        )
        for feature_id in feature_ids
    ]


# ── ① alias map 불변 ───────────────────────────────────────────────────────


async def test_alias_update_is_rejected(fence_engine: AsyncEngine) -> None:
    async with fence_engine.connect() as connection:
        with pytest.raises(DBAPIError, match="legacy write fence"):
            await connection.execute(
                text(
                    "UPDATE feature.feature_aliases SET created_at = now() "
                    "WHERE alias = :alias"
                ),
                {"alias": _SEED_IDS[0]},
            )


async def test_alias_direct_delete_is_rejected(fence_engine: AsyncEngine) -> None:
    async with fence_engine.connect() as connection:
        with pytest.raises(DBAPIError, match="직접 DELETE 금지"):
            await connection.execute(
                text("DELETE FROM feature.feature_aliases WHERE alias = :alias"),
                {"alias": _SEED_IDS[0]},
            )


async def test_alias_cascade_delete_via_feature_purge_is_allowed(
    fence_engine: AsyncEngine,
) -> None:
    purged = "f_global_p_fence_cascade_probe"
    await _seed_features(fence_engine, (purged,))
    async with fence_engine.begin() as connection:
        await connection.execute(
            text("DELETE FROM feature.features WHERE feature_id = :fid"),
            {"fid": purged},
        )
    async with fence_engine.connect() as connection:
        remaining = (
            await connection.execute(
                text(
                    "SELECT count(*) FROM feature.feature_aliases WHERE alias = :alias"
                ),
                {"alias": purged},
            )
        ).scalar_one()
    assert remaining == 0


# ── ② identity 불변 ────────────────────────────────────────────────────────


async def test_feature_id_update_is_rejected(fence_engine: AsyncEngine) -> None:
    async with fence_engine.connect() as connection:
        with pytest.raises(DBAPIError, match="identity.*불변"):
            await connection.execute(
                text(
                    "UPDATE feature.features SET feature_id = 'f_global_p_rekeyed' "
                    "WHERE feature_id = :fid"
                ),
                {"fid": _SEED_IDS[1]},
            )


async def test_feature_uuid_update_is_rejected(fence_engine: AsyncEngine) -> None:
    async with fence_engine.connect() as connection:
        with pytest.raises(DBAPIError, match="identity.*불변"):
            await connection.execute(
                text(
                    "UPDATE feature.features "
                    "SET feature_uuid = '00000000-0000-4000-8000-000000000000' "
                    "WHERE feature_id = :fid"
                ),
                {"fid": _SEED_IDS[1]},
            )


async def test_same_value_identity_update_passes(fence_engine: AsyncEngine) -> None:
    """IS DISTINCT FROM — 값이 같은 SET은 재키잉이 아니므로 통과한다."""
    async with fence_engine.begin() as connection:
        result = await connection.execute(
            text(
                "UPDATE feature.features SET feature_id = feature_id, "
                "feature_uuid = feature_uuid WHERE feature_id = :fid "
                "RETURNING feature_id"
            ),
            {"fid": _SEED_IDS[1]},
        )
        assert result.scalar_one() == _SEED_IDS[1]


# ── ③ legacy-only write는 구조적으로 불가능 (0079/0080 유지 확인) ─────────


async def test_raw_insert_without_uuid_is_still_completed_atomically(
    fence_engine: AsyncEngine,
) -> None:
    probe = "f_global_p_fence_fill_probe"
    await _seed_features(fence_engine, (probe,))
    async with fence_engine.connect() as connection:
        row = (
            await connection.execute(
                text(
                    "SELECT CAST(f.feature_uuid AS text) AS feature_uuid, "
                    "       a.alias_kind "
                    "FROM feature.features AS f "
                    "JOIN feature.feature_aliases AS a ON a.feature_id = f.feature_id "
                    "WHERE f.feature_id = :fid"
                ),
                {"fid": probe},
            )
        ).mappings().one()
    assert row["feature_uuid"] == str(feature_uuid_from_legacy(probe))
    assert row["alias_kind"] == "legacy_feature_id"
    async with fence_engine.begin() as connection:
        await connection.execute(
            text("DELETE FROM feature.features WHERE feature_id = :fid"),
            {"fid": probe},
        )


# ── ④ alias-map 이관 표면 ──────────────────────────────────────────────────


async def test_alias_map_checksum_matches_independent_recompute(
    fence_engine: AsyncEngine,
) -> None:
    async with fence_engine.connect() as connection:
        session_like = connection  # AsyncConnection도 execute 계약 동일
        checksum = await compute_feature_alias_map_checksum(session_like)  # type: ignore[arg-type]
    expected = _expected_rows(_SEED_IDS)
    assert checksum.alias_count == len(_SEED_IDS)
    assert checksum.merkle_root == feature_alias_map_merkle_root(expected)


async def test_alias_map_keyset_pagination_covers_all_rows_in_canonical_order(
    fence_engine: AsyncEngine,
) -> None:
    collected: list[FeatureAliasMapRowV1] = []
    after: str | None = None
    pages = 0
    async with fence_engine.connect() as connection:
        while True:
            page = await fetch_feature_alias_map_page(
                connection,  # type: ignore[arg-type]
                after_alias=after,
                limit=2,
            )
            collected.extend(page.rows)
            pages += 1
            if not page.has_more:
                break
            after = page.rows[-1].alias
    assert pages == 2
    assert [row.alias for row in collected] == sorted(
        _SEED_IDS, key=lambda alias: alias.encode("utf-8")
    )
    for row in collected:
        assert row.feature_uuid == str(feature_uuid_from_legacy(row.alias))


# ── ⑤ fail-close — 저장 층 보장 붕괴 시나리오 ─────────────────────────────


@pytest.fixture
async def corrupt_engine(pg_container: Any) -> AsyncIterator[AsyncEngine]:
    """보장 붕괴를 시뮬레이션할 함수 scope 전용 DB (CHECK·fence 우회)."""
    admin_dsn, dsn, database = await _build_fence_db(pg_container, "fence_corrupt")
    engine = make_async_engine(dsn)
    try:
        await _seed_features(engine, (_SEED_IDS[0],))
        yield engine
    finally:
        await engine.dispose()
        await _drop_database(admin_dsn, database)


async def test_checksum_fails_close_on_derivation_mismatch(
    corrupt_engine: AsyncEngine,
) -> None:
    async with corrupt_engine.begin() as connection:
        await connection.execute(
            text(
                "ALTER TABLE feature.feature_aliases "
                "DISABLE TRIGGER trg_feature_aliases_update_fence"
            )
        )
        await connection.execute(
            text(
                "ALTER TABLE feature.feature_aliases "
                "DROP CONSTRAINT ck_feature_aliases_uuid_dual_derivation"
            )
        )
        await connection.execute(
            text(
                "UPDATE feature.feature_aliases "
                "SET feature_uuid = '00000000-0000-4000-8000-000000000000'"
            )
        )
    async with corrupt_engine.connect() as connection:
        with pytest.raises(FeatureAliasMapIntegrityError, match="파생"):
            await compute_feature_alias_map_checksum(connection)  # type: ignore[arg-type]


async def test_page_fails_close_on_non_nfc_alias(corrupt_engine: AsyncEngine) -> None:
    # NFD 결합 문자 legacy id — 0079 트리거가 alias를 그대로 복제하므로
    # 저장 층에 비-NFC alias가 생긴다(현행 DB CHECK는 NFC를 모름).
    await _seed_features(corrupt_engine, ("feature:e\u0301-nfd-probe",))
    async with corrupt_engine.connect() as connection:
        with pytest.raises(FeatureAliasMapIntegrityError, match="NFC"):
            await fetch_feature_alias_map_page(
                connection,  # type: ignore[arg-type]
                after_alias=None,
                limit=10,
            )


# ── ⑥ downgrade 왕복 ───────────────────────────────────────────────────────


async def test_downgrade_removes_fences_and_upgrade_restores(
    pg_container: Any,
) -> None:
    admin_dsn, dsn, database = await _build_fence_db(pg_container, "fence_roundtrip")
    engine = make_async_engine(dsn)
    try:
        await _seed_features(engine, (_SEED_IDS[0],))
        await engine.dispose()
        await _downgrade(dsn, "0080_uuid_dual_read")
        engine = make_async_engine(dsn)
        async with engine.begin() as connection:
            # fence 제거 후에는 alias touch가 허용된다 (0080 CHECK는 created_at 무관심).
            await connection.execute(
                text("UPDATE feature.feature_aliases SET created_at = now()")
            )
        await engine.dispose()
        await _upgrade(dsn, "head")
        engine = make_async_engine(dsn)
        async with engine.connect() as connection:
            with pytest.raises(DBAPIError, match="legacy write fence"):
                await connection.execute(
                    text("UPDATE feature.feature_aliases SET created_at = now()")
                )
    finally:
        await engine.dispose()
        await _drop_database(admin_dsn, database)
