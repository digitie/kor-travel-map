"""T-VN-40-mapping — `0223_tvn40_identity_mappings` loader 실측.

설계 `docs/reports/t-vn-40-identity-mapping-loader-design-2026-08-18.md` §6.

두 층으로 본다.
1. **dedicated DB** — baseline → `stamp 0104` → legacy seed → `upgrade head`. 진짜 migrator 경로
   (`SET ROLE ktm_feature_schema_owner`)와 "0223이 한 트랜잭션 안에서 적재한다"를 실측한다.
   seed 없이는 0건, seed 있으면 bucket B 1건이고 service export의 Merkle root가 core 함수와 같다.
2. **`migrated_session` + `_run_loader`** — bucket 단위. legacy row를 심으면 0045 trigger가
   projection item을 자동 생성하므로(=bucket B) C/D/E 형태는 `session_replication_role = replica`로
   trigger·FK trigger를 끄고 item/collection을 직접 만든다. 각 중단 사유가 예외를 내고 표는 0행이다.

loader SQL은 migration 모듈의 상수다. runtime(`src/kortravelmap`)에는 두지 않는다 — runtime은
이 표에 SELECT만이다. 테스트는 importlib로 migration 파일을 읽는다(선례
`tests/unit/test_migration_forward_only.py`).
"""

from __future__ import annotations

import asyncio
import hashlib
import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import Any
from uuid import UUID

import pytest
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine

from alembic import command
from kortravelmap.core.curation_cutover_mapping import (
    CurationCutoverIdentityMappingDigestInput,
    curation_cutover_identity_mapping_root,
)
from kortravelmap.infra import curated_repo, curation_repo
from tests.integration import (
    test_alembic_metadata_consistency as _alembic_gate_tests,
)
from tests.integration import test_merge_repo as _merge_repo_tests
from tests.integration.test_curated_repo import (
    _curated_source_for_catalog_display,
    _load_seoul_bookstore,
    _seed_legacy_curated_row,
)

pytestmark = pytest.mark.integration

# dedicated DB fixture 재사용 — 모듈 속성으로 재바인딩하는 것이 pytest의 cross-module fixture
# 형식이다(`from ... import gate_alembic_config`는 아래 테스트 인자와 이름이 겹쳐 F811).
gate_alembic_config = _alembic_gate_tests.gate_alembic_config
# merge guard 테스트용 — test_merge_repo의 `seeded`(master/loser + same-theme legacy conflict,
# teardown 정리)
seeded = _merge_repo_tests.seeded

_ROOT = Path(__file__).resolve().parents[2]
_MIGRATION = _ROOT / "alembic" / "versions" / "0223_tvn40_identity_mappings.py"


def _load_migration_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "_tvn40_identity_mappings_0223", _MIGRATION
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


_MIG = _load_migration_module()


async def _run_loader(session: AsyncSession) -> None:
    await session.execute(text(_MIG.LOADER_SQL))


def _python_source_row_hash(row: dict[str, Any]) -> str:
    """migration의 SOURCE_ROW_HASH_SQL과 같은 식 — 9필드 '|' 결합, NULL→''."""
    parts = [
        str(row["curated_feature_id"]),
        str(row["theme_id"]),
        row["feature_id"],
        "" if row["source_id"] is None else str(row["source_id"]),
        "" if row["source_record_key"] is None else row["source_record_key"],
        row["curation_status"],
        row["curation_relation"],
        row["reuse_policy"],
        row["selection_origin"],
    ]
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


async def _legacy_row(session: AsyncSession, legacy_id: str) -> dict[str, Any]:
    fields = ", ".join(_MIG.SOURCE_ROW_HASH_FIELDS)
    row = (
        await session.execute(
            text(
                f"SELECT {fields} FROM feature.curated_features "
                "WHERE curated_feature_id = CAST(:id AS uuid)"
            ),
            {"id": legacy_id},
        )
    ).mappings().one()
    return dict(row)


async def _mapping_rows(session: AsyncSession) -> list[dict[str, Any]]:
    rows = (
        await session.execute(
            text(
                "SELECT legacy_curated_feature_id, collection_id, curation_item_id, "
                "mapping_kind, source_row_hash FROM ops.curation_cutover_identity_mappings "
                "ORDER BY legacy_curated_feature_id"
            )
        )
    ).mappings().all()
    return [dict(r) for r in rows]


async def _seed_b_row(session: AsyncSession) -> str:
    """legacy row 하나 — 0045 trigger가 projection item(bucket B)을 만든다."""
    feature_id = await _load_seoul_bookstore(session)
    themes = await curated_repo.list_curated_themes(session, limit=50)
    source = await _curated_source_for_catalog_display(
        session, provider="python-datagokr-api", dataset_key="datagokr_seoul_bookstores"
    )
    return await _seed_legacy_curated_row(
        session,
        theme_id=themes[0].theme_id,
        feature_id=feature_id,
        source_id=source.source_id,
    )


# ── 1. bucket B + hash + export root (migrated_session, _run_loader) ─────────


async def test_loader_maps_projection_row_and_hash_matches(
    migrated_session: AsyncSession,
) -> None:
    legacy_id = await _seed_b_row(migrated_session)
    await _run_loader(migrated_session)

    rows = await _mapping_rows(migrated_session)
    by_legacy = {str(r["legacy_curated_feature_id"]): r for r in rows}
    assert legacy_id in by_legacy, "seeded legacy row was not mapped"
    mapped = by_legacy[legacy_id]
    assert mapped["mapping_kind"] == "legacy_projection"
    # 0045 sync는 projection item UUID = legacy UUID로 만든다 — 그것이 identity다.
    assert str(mapped["curation_item_id"]) == legacy_id
    # collection_id는 item.collection_id다 (legacy theme에서 유도하지 않는다)
    item_collection = (
        await migrated_session.execute(
            text(
                "SELECT collection_id FROM feature.curation_items "
                "WHERE curation_item_id = CAST(:id AS uuid)"
            ),
            {"id": legacy_id},
        )
    ).scalar_one()
    assert mapped["collection_id"] == item_collection

    # 사후조건: 적재 수 = legacy 행 수 (같은 트랜잭션 안의 seed 포함)
    legacy_count = (
        await migrated_session.execute(text("SELECT count(*) FROM feature.curated_features"))
    ).scalar_one()
    assert len(rows) == legacy_count

    # hash — Python 재계산과 일치
    legacy = await _legacy_row(migrated_session, legacy_id)
    assert mapped["source_row_hash"] == _python_source_row_hash(legacy)
    # '|'가 어떤 필드에도 없어야 concat_ws 결합이 유일하다 (설계 §4)
    for key, value in legacy.items():
        assert "|" not in str(value), (key, value)

    # service export의 root = core 함수 root (같은 세션 — 트랜잭션 안이라 HTTP로는 안 보인다)
    export = await curation_repo.get_curation_cutover_identity_mapping_export(migrated_session)
    assert export.mapping_count == len(rows)
    expected_root = curation_cutover_identity_mapping_root(
        CurationCutoverIdentityMappingDigestInput(
            legacy_curated_feature_id=UUID(str(r["legacy_curated_feature_id"])),
            collection_id=UUID(str(r["collection_id"])),
            curation_item_id=UUID(str(r["curation_item_id"])),
            mapping_kind=str(r["mapping_kind"]),
            source_row_hash=str(r["source_row_hash"]),
        )
        for r in rows
    )
    assert export.mapping_root == expected_root


async def test_loader_refuses_to_run_twice(migrated_session: AsyncSession) -> None:
    await _seed_b_row(migrated_session)
    await _run_loader(migrated_session)
    # pytest.raises가 바깥이어야 한다 — 안쪽이면 aborted subtransaction에서
    # RELEASE SAVEPOINT를 시도한다.
    with pytest.raises(DBAPIError) as info:
        async with migrated_session.begin_nested():
            await _run_loader(migrated_session)
    assert "already has" in str(info.value.orig)


# ── 2. C/D/E — trigger를 끄고 직접 형태를 만든다 ────────────────────────────


async def _seed_shape(
    session: AsyncSession,
    *,
    with_projection: bool = False,
    membership_items: int = 0,
    membership_evidence: str = "import",
    detached: bool = False,
    extra_legacy_archived_same_item: bool = False,
) -> tuple[str, list[str]]:
    """replica 모드에서 legacy row + item 형태를 원하는 대로 심는다.

    반환: (legacy_id, [item_id...]). `membership_evidence` ∈ {"import","admin","none"}.
    """
    feature_id = await _load_seoul_bookstore(session)
    themes = await curated_repo.list_curated_themes(session, limit=50)
    theme_id = themes[0].theme_id
    source = await _curated_source_for_catalog_display(
        session, provider="python-datagokr-api", dataset_key="datagokr_seoul_bookstores"
    )
    await session.execute(text("SET LOCAL session_replication_role = replica"))
    try:
        legacy_id = await _seed_legacy_curated_row(
            session, theme_id=theme_id, feature_id=feature_id, source_id=source.source_id
        )
        if detached:
            await session.execute(
                text(
                    "UPDATE feature.curated_features SET metadata = metadata || "
                    "'{\"merge_projection_detached\": true}'::jsonb "
                    "WHERE curated_feature_id = CAST(:id AS uuid)"
                ),
                {"id": legacy_id},
            )
        item_ids: list[str] = []
        for i in range(max(membership_items, 1 if with_projection else 0)):
            collection_id = (
                await session.execute(
                    text(
                        "INSERT INTO feature.curation_collections "
                        "(collection_key, theme_id, source_id, title, edition_key, "
                        " description, status, visibility, metadata) VALUES "
                        "(:key, CAST(:theme AS uuid), CAST(:source AS uuid), :title, '', "
                        " NULL, 'published', 'admin_only', '{}'::jsonb) "
                        "RETURNING collection_id::text"
                    ),
                    {
                        "key": f"tvn40-map-{legacy_id[:8]}-{i}",
                        "theme": theme_id,
                        "source": source.source_id,
                        "title": f"tvn40 mapping shape {i}",
                    },
                )
            ).scalar_one()
            evidence_sql = {
                "import": ", current_import_row_id = x_extension.gen_random_uuid()",
                "admin": ", created_by = 'tvn40-admin'",
                "none": "",
            }[membership_evidence]
            item_id = (
                await session.execute(
                    text(
                        "INSERT INTO feature.curation_items "
                        "(collection_id, feature_id, external_item_id, place_name, status, "
                        " legacy_projection_id, source_present) VALUES "
                        "(CAST(:collection AS uuid), :feature, :ext, 'tvn40 shape', 'included', "
                        " CASE WHEN CAST(:proj AS boolean) THEN CAST(:legacy AS uuid) END, true) "
                        "RETURNING curation_item_id::text"
                    ),
                    {
                        "collection": collection_id,
                        "feature": feature_id,
                        "ext": f"tvn40-ext-{legacy_id[:8]}-{i}",
                        "proj": with_projection and i == 0,
                        "legacy": legacy_id,
                    },
                )
            ).scalar_one()
            if evidence_sql and not (with_projection and i == 0):
                await session.execute(
                    text(
                        "UPDATE feature.curation_items SET updated_at = now()"
                        f"{evidence_sql} WHERE curation_item_id = CAST(:id AS uuid)"
                    ),
                    {"id": item_id},
                )
            item_ids.append(item_id)
        if extra_legacy_archived_same_item:
            # 같은 theme·feature의 두 번째 legacy row — `uq_curated_features_theme_feature_active`
            # (partial UNIQUE, archived_at IS NULL)를 피하려면 처음부터 archived로 심어야 한다.
            await session.execute(
                text(
                    "INSERT INTO feature.curated_features ("
                    " theme_id, feature_id, source_id, curation_status, selection_origin,"
                    " curation_relation, reuse_policy, metadata, archived_at, updated_at"
                    ") VALUES ("
                    " CAST(:theme AS uuid), :feature, CAST(:source AS uuid), 'archived', 'admin',"
                    " 'nearby_option', 'manual_review', '{}'::jsonb, now(), now())"
                ),
                {"theme": theme_id, "feature": feature_id, "source": source.source_id},
            )
    finally:
        await session.execute(text("SET LOCAL session_replication_role = DEFAULT"))
    return legacy_id, item_ids


async def _expect_abort(session: AsyncSession, needle: str) -> None:
    with pytest.raises(DBAPIError) as info:
        async with session.begin_nested():
            await _run_loader(session)
    message = str(info.value.orig)
    assert needle in message, message[:300]
    count = (
        await session.execute(text("SELECT count(*) FROM ops.curation_cutover_identity_mappings"))
    ).scalar_one()
    assert count == 0, "abort must leave the immutable table empty"


async def test_official_membership_maps_when_projection_is_absent(
    migrated_session: AsyncSession,
) -> None:
    legacy_id, items = await _seed_shape(
        migrated_session, membership_items=1, membership_evidence="import"
    )
    await _run_loader(migrated_session)
    rows = {str(r["legacy_curated_feature_id"]): r for r in await _mapping_rows(migrated_session)}
    assert rows[legacy_id]["mapping_kind"] == "official_membership"
    assert str(rows[legacy_id]["curation_item_id"]) == items[0]


async def test_manual_membership_maps_when_only_admin_evidence(
    migrated_session: AsyncSession,
) -> None:
    legacy_id, items = await _seed_shape(
        migrated_session, membership_items=1, membership_evidence="admin"
    )
    await _run_loader(migrated_session)
    rows = {str(r["legacy_curated_feature_id"]): r for r in await _mapping_rows(migrated_session)}
    assert rows[legacy_id]["mapping_kind"] == "manual_membership"
    assert str(rows[legacy_id]["curation_item_id"]) == items[0]


async def test_abort_on_detached_legacy_row(migrated_session: AsyncSession) -> None:
    await _seed_shape(migrated_session, with_projection=True, detached=True)
    await _expect_abort(migrated_session, "detached=1")


async def test_abort_when_no_candidate(migrated_session: AsyncSession) -> None:
    await _seed_shape(migrated_session, membership_items=0)
    await _expect_abort(migrated_session, "no_candidate=1")


async def test_abort_when_multiple_candidates(migrated_session: AsyncSession) -> None:
    await _seed_shape(migrated_session, membership_items=2, membership_evidence="import")
    await _expect_abort(migrated_session, "multi_candidate=1")


async def test_abort_when_candidate_has_no_evidence(migrated_session: AsyncSession) -> None:
    await _seed_shape(migrated_session, membership_items=1, membership_evidence="none")
    await _expect_abort(migrated_session, "no_evidence=1")


async def test_abort_when_one_item_is_claimed_by_two_legacy_rows(
    migrated_session: AsyncSession,
) -> None:
    await _seed_shape(
        migrated_session,
        membership_items=1,
        membership_evidence="import",
        extra_legacy_archived_same_item=True,
    )
    await _expect_abort(migrated_session, "item_claimed_twice=1")


# ── 3. FK 불변식 — mapping이 잡은 item은 rekey할 수 없다 ────────────────────


async def test_mapped_item_cannot_be_rekeyed(migrated_session: AsyncSession) -> None:
    legacy_id = await _seed_b_row(migrated_session)
    await _run_loader(migrated_session)
    with pytest.raises(DBAPIError) as info:
        async with migrated_session.begin_nested():
            await migrated_session.execute(
                text(
                    "UPDATE feature.curation_items "
                    "SET curation_item_id = x_extension.gen_random_uuid() "
                    "WHERE curation_item_id = CAST(:id AS uuid)"
                ),
                {"id": legacy_id},
            )
    assert getattr(info.value.orig, "sqlstate", None) == "23503", repr(info.value.orig)[:200]


# ── 4. dedicated DB — 진짜 migrator 경로로 0104 → head ─────────────────────


async def _admin_engine(cfg: Config) -> AsyncEngine:
    admin_dsn = cfg.get_main_option("sqlalchemy.url")
    assert admin_dsn is not None
    return create_async_engine(admin_dsn, pool_size=1)


async def test_upgrade_from_0104_loads_seeded_legacy_row(gate_alembic_config: Config) -> None:
    """baseline → stamp 0104 → (0222까지) → legacy seed → upgrade head(0223) → mapping 1건."""
    from tests.integration._tvn34_migration_bootstrap import (
        alembic_schema_owner_role,
        bootstrapped_migrator_dsn,
    )

    cfg = gate_alembic_config
    admin_engine = await _admin_engine(cfg)
    try:
        admin_dsn = cfg.get_main_option("sqlalchemy.url")
        assert admin_dsn is not None
        cfg.set_main_option("sqlalchemy.url", await bootstrapped_migrator_dsn(admin_dsn))
        with alembic_schema_owner_role():
            await asyncio.to_thread(command.upgrade, cfg, "0200_schema_baseline")
            await asyncio.to_thread(command.stamp, cfg, "0104_tvn36_final_fence")
            await asyncio.to_thread(command.upgrade, cfg, "0222_tvn40a_merge_runtime_role")

        # 0222 head에서 legacy row를 하나 심는다 (0045 trigger가 projection을 만든다).
        async with AsyncSession(admin_engine) as session, session.begin():
            legacy_id = await _seed_b_row(session)

        with alembic_schema_owner_role():
            await asyncio.to_thread(command.upgrade, cfg, "head")

        async with AsyncSession(admin_engine) as session:
            head = (
                await session.execute(text("SELECT version_num FROM public.alembic_version"))
            ).scalar_one()
            assert head == "0224_c7_external_system_scope"
            rows = await _mapping_rows(session)
            assert [str(r["legacy_curated_feature_id"]) for r in rows] == [legacy_id]
            assert rows[0]["mapping_kind"] == "legacy_projection"
            legacy = await _legacy_row(session, legacy_id)
            assert rows[0]["source_row_hash"] == _python_source_row_hash(legacy)
    finally:
        await admin_engine.dispose()


# ── 5. merge guard — mapping이 잡은 item은 merge detach가 명시적으로 막는다 ──


async def test_merge_refuses_to_rekey_mapped_legacy_conflict_item(
    seeded: str,
    migrated_engine: AsyncEngine,
) -> None:
    """같은 theme legacy conflict merge는 loser projection item을 rekey한다 — mapping 뒤엔 금지.

    raw FK 23503이 아니라 `MergeConflictError`가 먼저 나야 한다(merge_repo
    `_PINNED_LEGACY_CONFLICT_ITEMS_SQL`). 실제 API runtime role로 merge를 돌린다.
    """
    from kortravelmap.infra.merge_repo import MergeConflictError, apply_feature_merge
    from tests.integration.conftest import as_api_runtime

    async with AsyncSession(migrated_engine) as session, session.begin():
        await _run_loader(session)  # seeded pair의 legacy row들이 mapping에 잡힌다
        pinned = (
            await session.execute(
                text(
                    "SELECT count(*) FROM ops.curation_cutover_identity_mappings AS m "
                    "JOIN feature.curation_items AS i ON i.curation_item_id = m.curation_item_id "
                    "WHERE i.feature_id IN ('f_master', 'f_loser')"
                )
            )
        ).scalar_one()
        assert pinned >= 2, "seeded legacy pair must be mapped before the merge"
        with pytest.raises(MergeConflictError, match="pinned"):
            async with session.begin_nested(), as_api_runtime(session):
                await apply_feature_merge(
                    session,
                    master_id="f_master",
                    loser_id="f_loser",
                    review_id=seeded,
                    merged_by="mapping-guard-test",
                )
        await session.rollback()


# ── 6. dedicated DB — 0104에서 seed된 중단 형태는 전체 체인을 롤백시킨다 ────────


async def test_upgrade_from_0104_aborts_whole_chain_on_detached_row(
    gate_alembic_config: Config,
) -> None:
    """prod ① 시나리오: 0104 head에 매핑 불가 legacy row가 있으면 `upgrade head`가 0223에서
    RAISE하고 0202~0223 **전부** 롤백된다 — head 0104 유지, 표도 안 생긴다.

    중단 사유는 `no_candidate`로 만든다(0045 trigger를 replica 모드로 끄고 legacy row만 심어
    projection item이 없게). detached marker는 0104 스키마의 reserved-metadata 가드가 직접
    쓰기를 막아 seed에 쓸 수 없다.
    """
    from tests.integration._tvn34_migration_bootstrap import (
        alembic_schema_owner_role,
        bootstrapped_migrator_dsn,
    )

    cfg = gate_alembic_config
    admin_engine = await _admin_engine(cfg)
    try:
        admin_dsn = cfg.get_main_option("sqlalchemy.url")
        assert admin_dsn is not None
        cfg.set_main_option("sqlalchemy.url", await bootstrapped_migrator_dsn(admin_dsn))
        with alembic_schema_owner_role():
            await asyncio.to_thread(command.upgrade, cfg, "0200_schema_baseline")
            await asyncio.to_thread(command.stamp, cfg, "0104_tvn36_final_fence")

        async with AsyncSession(admin_engine) as session, session.begin():
            # 0104 스키마에는 T-VN-40 열(row_revision 등)이 없어 repo helper 대신 raw로 심는다.
            feature_id = await _load_seoul_bookstore(session)
            theme_id = (
                await session.execute(
                    text(
                        "SELECT theme_id::text FROM feature.curated_themes "
                        "ORDER BY theme_slug LIMIT 1"
                    )
                )
            ).scalar_one()
            source_id = (
                await session.execute(
                    text(
                        "SELECT source_id::text FROM feature.curated_sources "
                        "ORDER BY source_id LIMIT 1"
                    )
                )
            ).scalar_one()
            await session.execute(text("SET LOCAL session_replication_role = replica"))
            await _seed_legacy_curated_row(
                session, theme_id=theme_id, feature_id=feature_id, source_id=source_id
            )
            await session.execute(text("SET LOCAL session_replication_role = DEFAULT"))

        with alembic_schema_owner_role(), pytest.raises(Exception, match="no_candidate=1"):
            await asyncio.to_thread(command.upgrade, cfg, "head")

        async with AsyncSession(admin_engine) as session:
            head = (
                await session.execute(text("SELECT version_num FROM public.alembic_version"))
            ).scalar_one()
            assert head == "0104_tvn36_final_fence"
            assert (
                await session.execute(
                    text("SELECT to_regclass('ops.curation_cutover_identity_mappings') IS NULL")
                )
            ).scalar_one() is True
            assert (
                await session.execute(
                    text("SELECT to_regclass('feature.theme_feature_candidates') IS NULL")
                )
            ).scalar_one() is True
    finally:
        await admin_engine.dispose()
