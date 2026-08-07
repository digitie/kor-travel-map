"""``0082_legacy_write_fence`` + alias-map 이관 표면 검증 (T-VN-32C, ADR-068).

consumer-rollout-v1 T-VN-32 write_fence의 DB 층 착지를 회귀 고정한다:

① alias map 불변 — ``feature_aliases`` UPDATE 전면 거부, 직접 DELETE 거부,
   feature 행 삭제의 FK CASCADE 경유 삭제만 허용
② identity 불변 — ``features.feature_id``/``feature_uuid`` UPDATE 거부
③ legacy-only write는 여전히 구조적으로 불가능 — uuid 없는 raw INSERT는
   0080 fill/alias 트리거가 완결한다. **0083부터 채움 값은 파생이 아니라
   비파생 UUIDv7**이고, alias 사본 일치는 복합 FK가 선언적으로 강제한다.
④ alias-map 이관 표면 — checksum(merkle root) 독립 재계산 일치 + canonical
   순서 keyset 페이지 완전 순회 (재계산 기준은 **저장된 uuid** — 0083 이후
   파생 재계산은 계약이 아니다)
⑤ fail-close — 사본 불일치는 트리거 우회(보장 붕괴 시나리오)에도 복합 FK가
   막고, 비-NFC alias가 저장 층에 존재하면 페이지/checksum 대신
   :class:`FeatureAliasMapIntegrityError`
⑥ downgrade 왕복 — fence 구조물만 제거·복원되고 데이터 무변경
"""

from __future__ import annotations

import asyncio
import uuid as uuid_module
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

# T-VN-33(0089~0091) downgrade는 forward-only fence로 막혀 있다. fence 구조물
# 왕복 회귀는 그 아래 마지막 되돌릴 수 있는 revision을 상단으로 쓴다.
_FENCE_ROUNDTRIP_TOP: Final = "0088_source_record_lineage_key"

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
    """head 스키마에 raw INSERT — 0080 fill/alias 트리거가 uuid·alias를 채운다.

    0083 이후 채움 값은 ``feature.uuid_generate_v7()`` 산출(비파생)이다.
    """
    async with engine.begin() as connection:
        for feature_id in feature_ids:
            await connection.execute(
                text(
                    "INSERT INTO feature.features (feature_id, kind, name, category) "
                    "VALUES (:fid, 'place', :name, '01070100')"
                ),
                {"fid": feature_id, "name": f"fence-{feature_id[:24]}"},
            )


async def _seed_features_with_derived_uuid(
    engine: AsyncEngine, feature_ids: tuple[str, ...]
) -> None:
    """0080 backfill 세대를 재현하는 seed — ``feature_uuid``를 파생값으로 명시한다.

    0083 downgrade가 파생 CHECK를 ``NOT VALID``로 복원하면 **그 뒤의
    INSERT/UPDATE는 검사된다**. downgrade 왕복 회귀는 fence 구조물만 보려는
    것이므로, 파생 세대 행으로 seed해 파생 축과 무관하게 만든다.
    """
    async with engine.begin() as connection:
        for feature_id in feature_ids:
            await connection.execute(
                text(
                    "INSERT INTO feature.features "
                    "(feature_id, feature_uuid, kind, name, category) VALUES "
                    "(:fid, CAST(:uuid AS uuid), 'place', :name, '01070100')"
                ),
                {
                    "fid": feature_id,
                    "uuid": str(feature_uuid_from_legacy(feature_id)),
                    "name": f"fence-{feature_id[:24]}",
                },
            )
            # T-VN-35(ADR-086): place 값의 정본은 ``feature_places``이고
            # ``place_kind``는 NOT NULL이다. subtype 없는 core place 행은
            # downgrade(0086 역조립 → place_kind NULL) 후 재upgrade 시 0084
            # backfill의 NOT NULL로 fail-close된다 — seed도 정본을 갖춰야 한다.
            await connection.execute(
                text(
                    "INSERT INTO feature.feature_places "
                    "(feature_id, feature_uuid, kind, place_kind) VALUES "
                    "(:fid, CAST(:uuid AS uuid), 'place', 'attraction')"
                ),
                {
                    "fid": feature_id,
                    "uuid": str(feature_uuid_from_legacy(feature_id)),
                },
            )


def _sqlstate(error: BaseException) -> str | None:
    """DBAPIError에서 PostgreSQL SQLSTATE를 꺼낸다 (driver 표기 차이 흡수)."""
    for candidate in (getattr(error, "orig", None), error):
        for attribute in ("sqlstate", "pgcode"):
            value = getattr(candidate, attribute, None)
            if value:
                return str(value)
    return None


async def _stored_alias_rows(engine: AsyncEngine) -> list[FeatureAliasMapRowV1]:
    """저장된 alias 행을 그대로 읽어 재계산 기준으로 쓴다.

    0083 이후 신규 행의 ``feature_uuid``는 비파생이므로, 독립 재계산의 기준을
    ``feature_uuid_from_legacy(alias)``로 둘 수 없다. **정본(features) 쪽 값**을
    읽어 alias 사본과 대조하고, 그 값으로 merkle을 재계산한다.
    """
    async with engine.connect() as connection:
        records = (
            await connection.execute(
                text(
                    "SELECT a.alias AS alias, a.alias_kind AS alias_kind, "
                    "       CAST(f.feature_uuid AS text) AS feature_uuid, "
                    "       CAST(a.feature_uuid AS text) AS alias_uuid "
                    "FROM feature.feature_aliases AS a "
                    "JOIN feature.features AS f ON f.feature_id = a.feature_id"
                )
            )
        ).mappings().all()
    rows: list[FeatureAliasMapRowV1] = []
    for record in records:
        # 사본 일치는 0083 복합 FK의 계약 — 재계산 전에 실측 확인한다.
        assert record["alias_uuid"] == record["feature_uuid"]
        rows.append(
            FeatureAliasMapRowV1(
                alias=record["alias"],
                feature_uuid=record["feature_uuid"],
                alias_kind=record["alias_kind"],
            )
        )
    return rows


async def _build_fence_db(
    pg_container: Any, prefix: str, *, revision: str = "head"
) -> tuple[str, str, str]:
    admin_dsn = normalize_async_dsn(pg_container.get_connection_url())
    database = f"{prefix}_{uuid4().hex}"
    dsn = make_url(admin_dsn).set(database=database).render_as_string(hide_password=False)
    await _create_database(admin_dsn, database)
    await _upgrade(dsn, revision)
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


# ── ① alias map 불변 ───────────────────────────────────────────────────────


async def test_alias_update_is_rejected(fence_engine: AsyncEngine) -> None:
    # UPDATE 분기 고유 문구로 단언 — DELETE fence와 구분 (32C 적대 리뷰 L6).
    async with fence_engine.connect() as connection:
        with pytest.raises(DBAPIError, match="행은 불변입니다"):
            await connection.execute(
                text(
                    "UPDATE feature.feature_aliases SET created_at = now() "
                    "WHERE alias = :alias"
                ),
                {"alias": _SEED_IDS[0]},
            )


async def test_alias_truncate_is_rejected(fence_engine: AsyncEngine) -> None:
    """row 트리거는 TRUNCATE에 발화하지 않는다 — statement 트리거 fence (M3)."""
    async with fence_engine.connect() as connection:
        with pytest.raises(DBAPIError, match="TRUNCATE 금지"):
            await connection.execute(text("TRUNCATE feature.feature_aliases"))


async def test_poison_alias_rows_are_rejected_by_db_checks(
    fence_engine: AsyncEngine,
) -> None:
    """H1 독성 행 회귀 — ``alias ≠ feature_id`` INSERT는 legacy identity CHECK가 막는다.

    초판 0080은 파생 CHECK를 FK 컬럼(feature_id) 축으로 걸어
    ``(alias='x', feature_id='y', uuid=f(y))`` 독성 행이 DB를 통과했고, 통과한
    순간 checksum/페이지 전체가 영구 fail-close되며 0082 fence가 그 행 삭제까지
    막았다(적대 리뷰 H1 실측).

    0083이 파생 CHECK 2종을 해제한 뒤 이 축을 지키는 것은
    ``ck_feature_aliases_legacy_identity``(``alias = feature_id``) **단독**이다.
    파생 CHECK가 함께 발화할 여지가 없어졌으므로 정규식 alternation이 아니라
    제약 이름 + SQLSTATE를 정확히 단언한다(우연 통과 차단).
    """
    host_id = _SEED_IDS[0]

    async def _insert(alias: str, feature_uuid: str) -> None:
        async with fence_engine.connect() as connection:
            await connection.execute(
                text(
                    "INSERT INTO feature.feature_aliases "
                    "(alias, feature_id, feature_uuid, alias_kind) VALUES "
                    "(:alias, :fid, CAST(:feature_uuid AS uuid), "
                    "'legacy_feature_id')"
                ),
                {"alias": alias, "fid": host_id, "feature_uuid": feature_uuid},
            )
            await connection.commit()

    async with fence_engine.connect() as connection:
        host_uuid = (
            await connection.execute(
                text(
                    "SELECT CAST(feature_uuid AS text) FROM feature.features "
                    "WHERE feature_id = :fid"
                ),
                {"fid": host_id},
            )
        ).scalar_one()

    # ① H1 원판 독성 행: uuid는 host의 **저장된 정본값** — 복합 FK는 만족하지만
    #    alias ≠ feature_id이므로 legacy identity CHECK가 거부한다.
    with pytest.raises(DBAPIError) as old_axis:
        await _insert("f_global_p_poison_old_axis", host_uuid)
    assert "ck_feature_aliases_legacy_identity" in str(old_axis.value)
    assert _sqlstate(old_axis.value) == "23514"
    # ② uuid가 임의 파생값이어도 마찬가지 — 축은 alias 동일성 하나다.
    poison_alias = "f_global_p_poison_identity"
    with pytest.raises(DBAPIError) as identity_axis:
        await _insert(poison_alias, str(feature_uuid_from_legacy(poison_alias)))
    assert "ck_feature_aliases_legacy_identity" in str(identity_axis.value)
    assert _sqlstate(identity_axis.value) == "23514"
    # 어느 독성 행도 저장되지 않았다.
    async with fence_engine.connect() as connection:
        poison_count = (
            await connection.execute(
                text(
                    "SELECT count(*) FROM feature.feature_aliases "
                    "WHERE alias LIKE 'f_global_p_poison_%'"
                )
            )
        ).scalar_one()
    assert poison_count == 0




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


# ── ③ legacy-only write는 구조적으로 불가능 (0080 fill/alias 트리거 유지) ──


async def test_raw_insert_without_uuid_is_still_completed_atomically(
    fence_engine: AsyncEngine,
) -> None:
    """uuid 없는 raw INSERT도 uuid+alias 쌍으로 완결된다 — 0083부터 값은 v7이다."""
    probe = "f_global_p_fence_fill_probe"
    await _seed_features(fence_engine, (probe,))
    async with fence_engine.connect() as connection:
        row = (
            await connection.execute(
                text(
                    "SELECT CAST(f.feature_uuid AS text) AS feature_uuid, "
                    "       CAST(a.feature_uuid AS text) AS alias_uuid, "
                    "       a.alias_kind "
                    "FROM feature.features AS f "
                    "JOIN feature.feature_aliases AS a ON a.feature_id = f.feature_id "
                    "WHERE f.feature_id = :fid"
                ),
                {"fid": probe},
            )
        ).mappings().one()
    filled = uuid_module.UUID(row["feature_uuid"])
    assert str(filled) == row["feature_uuid"]
    assert filled.version == 7
    assert filled.variant == uuid_module.RFC_4122
    assert (filled.int >> 76) & 0xF == 0x7
    assert (filled.int >> 62) & 0b11 == 0b10
    # 파생 generator로 되돌아가면(이원화) 여기서 죽는다.
    assert row["feature_uuid"] != str(feature_uuid_from_legacy(probe))
    # AFTER 트리거의 alias 사본은 정본과 같은 값이다 (INV-068-01 원자성).
    assert row["alias_uuid"] == row["feature_uuid"]
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
    """독립 재계산 기준은 **정본(features)에 저장된 uuid**다 (파생 재계산 아님)."""
    async with fence_engine.connect() as connection:
        session_like = connection  # AsyncConnection도 execute 계약 동일
        checksum = await compute_feature_alias_map_checksum(session_like)  # type: ignore[arg-type]
    expected = await _stored_alias_rows(fence_engine)
    assert checksum.alias_count == len(_SEED_IDS)
    assert len(expected) == len(_SEED_IDS)
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
    # 페이지가 내보내는 uuid는 정본 저장값과 정확히 같다 (파생 재계산 아님).
    stored = {row.alias: row.feature_uuid for row in await _stored_alias_rows(fence_engine)}
    for row in collected:
        assert row.feature_uuid == stored[row.alias]
        assert uuid_module.UUID(row.feature_uuid).version == 7


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


async def test_alias_copy_mismatch_survives_trigger_bypass_via_composite_fk(
    corrupt_engine: AsyncEngine,
) -> None:
    """0083 선언적 대체의 핵심 — 트리거를 꺼도 사본 불일치는 FK가 막는다.

    32B까지는 사본 일치가 파생 CHECK 2종의 **부수 효과**였다. 0083이 그 둘을
    해제하면서 ``fk_feature_aliases_identity_pair``를 넣은 이유가 바로 이것:
    fence 트리거는 ``DISABLE TRIGGER``(또는 ``session_replication_role``)로
    우회 가능한 **절차적** 보장이지만 FK는 그렇지 않다.

    보장 붕괴 시뮬레이션으로 update fence를 끄고 alias uuid를 바꿔 본다 —
    23503으로 죽어야 하고, checksum은 그대로 성립해야 한다.
    """
    async with corrupt_engine.begin() as connection:
        await connection.execute(
            text(
                "ALTER TABLE feature.feature_aliases "
                "DISABLE TRIGGER trg_feature_aliases_update_fence"
            )
        )
    try:
        with pytest.raises(DBAPIError) as excinfo:
            async with corrupt_engine.begin() as connection:
                await connection.execute(
                    text(
                        "UPDATE feature.feature_aliases "
                        "SET feature_uuid = "
                        "CAST('00000000-0000-7000-8000-000000000000' AS uuid)"
                    )
                )
        assert "fk_feature_aliases_identity_pair" in str(excinfo.value)
        assert _sqlstate(excinfo.value) == "23503"
    finally:
        async with corrupt_engine.begin() as connection:
            await connection.execute(
                text(
                    "ALTER TABLE feature.feature_aliases "
                    "ENABLE TRIGGER trg_feature_aliases_update_fence"
                )
            )

    # 사본이 온전하므로 checksum은 정상 계산된다 (fail-close 오탐 없음).
    async with corrupt_engine.connect() as connection:
        checksum = await compute_feature_alias_map_checksum(connection)  # type: ignore[arg-type]
    expected = await _stored_alias_rows(corrupt_engine)
    assert checksum.merkle_root == feature_alias_map_merkle_root(expected)


async def test_checksum_fails_close_on_non_nfc_alias(
    corrupt_engine: AsyncEngine,
) -> None:
    """shape 축 fail-close — 비-NFC alias는 checksum 경로에서도 즉시 실패한다.

    0083 이후 "검증된 alias map"의 조건에서 파생 등식은 빠졌지만 shape 검증은
    남는다 — 그 축의 회귀를 checksum 쪽에도 고정한다(페이지 쪽은 아래 테스트).
    """
    await _seed_features(corrupt_engine, ("feature:é-nfd-checksum",))
    async with corrupt_engine.connect() as connection:
        with pytest.raises(FeatureAliasMapIntegrityError, match="NFC"):
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
    """fence 구조물만 제거·복원된다 (0083 복합 FK도 왕복 후 되돌아온다).

    seed는 **파생 세대**로 만든다 — 0083 downgrade가 파생 CHECK를 ``NOT VALID``로
    복원하면 그 뒤의 UPDATE는 검사되므로, 비파생 v7 행이면 fence와 무관하게
    23514로 죽어 이 회귀의 관측 축이 흐려진다.

    T-VN-33(0089~0091)은 forward-only라 downgrade가 ``RuntimeError``다. 이 왕복
    회귀가 보는 축은 0082/0083 fence 구조물뿐이므로, T-VN-33 직전이면서 아직
    되돌릴 수 있는 마지막 revision(:data:`_FENCE_ROUNDTRIP_TOP`)을 왕복 상단으로
    쓴다.
    """
    admin_dsn, dsn, database = await _build_fence_db(
        pg_container, "fence_roundtrip", revision=_FENCE_ROUNDTRIP_TOP
    )
    engine = make_async_engine(dsn)
    try:
        await _seed_features_with_derived_uuid(engine, (_SEED_IDS[0],))
        await engine.dispose()
        await _downgrade(dsn, "0081_uuid_dual_read")
        engine = make_async_engine(dsn)
        async with engine.begin() as connection:
            # fence 제거 후에는 alias touch가 허용된다 (파생 CHECK는 created_at 무관심).
            await connection.execute(
                text("UPDATE feature.feature_aliases SET created_at = now()")
            )
        await engine.dispose()
        await _upgrade(dsn, _FENCE_ROUNDTRIP_TOP)
        engine = make_async_engine(dsn)
        async with engine.connect() as connection:
            with pytest.raises(DBAPIError, match="행은 불변입니다"):
                await connection.execute(
                    text("UPDATE feature.feature_aliases SET created_at = now()")
                )
        async with engine.connect() as connection:
            restored = {
                row.conname
                for row in await connection.execute(
                    text(
                        "SELECT con.conname FROM pg_catalog.pg_constraint AS con "
                        "JOIN pg_catalog.pg_class AS rel ON rel.oid = con.conrelid "
                        "JOIN pg_catalog.pg_namespace AS ns "
                        "  ON ns.oid = rel.relnamespace "
                        "WHERE ns.nspname = 'feature' "
                        "AND rel.relname IN ('features', 'feature_aliases')"
                    )
                )
            }
        assert "uq_features_identity_pair" in restored
        assert "fk_feature_aliases_identity_pair" in restored
        assert "ck_features_feature_uuid_dual_derivation" not in restored
        assert "ck_feature_aliases_uuid_dual_derivation" not in restored
    finally:
        await engine.dispose()
        await _drop_database(admin_dsn, database)
