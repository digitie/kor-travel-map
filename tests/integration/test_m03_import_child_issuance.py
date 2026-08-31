"""T-VN-M03 — import 행별 manual Feature child 발급의 실제 DB 경계(302).

plan 생성 → claim → `import_curation_rows`(parent identity 결박)의 실경로로
manual 행 하나가 child command·Feature·item·decision·`301` linkage를 한
transaction에서 확정하는지 검증한다. 격리 수준·role 경계는 실제 LOGIN
(ktm_feature_api_runtime)으로 exercised된다.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from kortravelmap.curation_import import manual_feature_payload_sha256
from kortravelmap.curation_import_children import (
    ParentCommandIdentity,
    derive_child_command_identity,
)
from kortravelmap.infra.curation_repo import (
    CurationImportRevisionExpectation,
    ResolvedCurationImportRow,
    build_curation_import_revision_vector,
    claim_curation_import_plan_command,
    create_curation_import_plan_command,
    import_curation_rows,
)
from kortravelmap.infra.db import make_async_engine

pytestmark = pytest.mark.integration

_RUNTIME_PASSWORD = "tvn40-test-only-runtime-password"


def _runtime_engine(engine: AsyncEngine, *, login: str) -> AsyncEngine:
    dsn = engine.url.set(username=login, password=_RUNTIME_PASSWORD).render_as_string(
        hide_password=False
    )
    return make_async_engine(dsn, pool_size=1)


async def _domain_command(
    engine: AsyncEngine,
    *,
    actor: str,
    operation: str,
    idempotency_key: str,
    request_fingerprint: str,
) -> int:
    async with engine.begin() as connection:
        return int(
            await connection.scalar(
                text(
                    """
                    INSERT INTO ops.domain_commands (
                      actor, operation, idempotency_key, request_fingerprint
                    ) VALUES (
                      :actor, :operation, CAST(:idempotency_key AS uuid),
                      :request_fingerprint
                    ) RETURNING command_id
                    """
                ),
                {
                    "actor": actor,
                    "operation": operation,
                    "idempotency_key": idempotency_key,
                    "request_fingerprint": request_fingerprint,
                },
            )
        )


async def _seed_dataset(engine: AsyncEngine, *, suffix: str) -> int:
    async with engine.begin() as connection:
        dataset_id = int(
            await connection.scalar(
                text(
                    """
                    INSERT INTO provider_sync.provider_datasets (
                      provider, dataset_key, display_name, source_kind,
                      is_active, capabilities
                    ) VALUES (
                      'm03-child-test', :dataset_key, 'M03 child import',
                      'manual', true, CAST(:capabilities AS jsonb)
                    ) RETURNING provider_dataset_id
                    """
                ),
                {
                    "dataset_key": f"child-{suffix}",
                    "capabilities": '{"schema_version":1,"produces":[],"extensions":{}}',
                },
            )
        )
        await connection.execute(
            text(
                """
                INSERT INTO feature.curated_themes (
                  theme_slug, theme_name, theme_group, visibility,
                  metadata, owner_kind
                ) VALUES (
                  :slug, 'M03 child theme', 'test', 'admin_only',
                  '{}'::jsonb, 'operator'
                )
                """
            ),
            {"slug": f"m03-child-{suffix}"},
        )
        await connection.execute(
            text(
                """
                INSERT INTO feature.curated_sources (
                  provider_dataset_id, source_name, source_kind,
                  update_cycle, provider_status, metadata
                ) VALUES (
                  :dataset_id, 'M03 child source', 'manual', 'unknown',
                  'manual_only', '{}'::jsonb
                )
                """
            ),
            {"dataset_id": dataset_id},
        )
    return dataset_id


def _row(
    *,
    suffix: str,
    dataset_id: int,
    row_number: int,
    source_item_key: str,
    place_name: str,
    manual_feature: dict[str, object] | None = None,
) -> ResolvedCurationImportRow:
    return ResolvedCurationImportRow(
        row_number=row_number,
        collection_key=f"m03-child-{suffix}",
        theme_slug=f"m03-child-{suffix}",
        theme_name="M03 child theme",
        theme_group="test",
        title="M03 child collection",
        edition_key="2026",
        provider_dataset_id=dataset_id,
        source_name="M03 child source",
        source_url=None,
        source_item_key=source_item_key,
        feature_id=None,
        place_name=place_name,
        address_hint=None,
        sort_order=row_number,
        item_title=None,
        item_summary=None,
        metadata={"version": 1},
        manual_feature=dict(manual_feature) if manual_feature is not None else None,
        manual_feature_sha256=(
            manual_feature_payload_sha256(manual_feature)
            if manual_feature is not None
            else None
        ),
    )


async def test_manual_row_issues_child_and_binds_the_301_linkage(
    migrated_engine: AsyncEngine,
) -> None:
    suffix = uuid4().hex[:12]
    actor = f"admin:m03-child-{suffix}"
    dataset_id = await _seed_dataset(migrated_engine, suffix=suffix)
    manual_payload: dict[str, object] = {
        "kind": "place",
        "category": "12010000",
        "coord": {"lon": "126.99100", "lat": "37.57960"},
    }
    plain = _row(
        suffix=suffix,
        dataset_id=dataset_id,
        row_number=2,
        source_item_key="plain-1",
        place_name="일반 행",
    )
    manual = _row(
        suffix=suffix,
        dataset_id=dataset_id,
        row_number=3,
        source_item_key="manual-1",
        place_name="수동 생성 장소",
        manual_feature=manual_payload,
    )
    rows = (plain, manual)

    api = _runtime_engine(migrated_engine, login="ktm_feature_api_runtime")
    session_factory = async_sessionmaker(api, expire_on_commit=False)
    try:
        preview_command = await _domain_command(
            migrated_engine,
            actor=actor,
            operation="admin.curation-import.preview",
            idempotency_key=str(uuid4()),
            request_fingerprint="c" * 64,
        )
        import_plan_id = str(uuid4())
        content_sha256 = uuid4().hex + uuid4().hex
        plan_sha256 = uuid4().hex + uuid4().hex
        async with session_factory() as session, session.begin():
            await session.execute(
                text("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE")
            )
            revisions: tuple[CurationImportRevisionExpectation, ...] = (
                await build_curation_import_revision_vector(session, rows=rows)
            )
            await create_curation_import_plan_command(
                session,
                import_plan_id=import_plan_id,
                content_sha256=content_sha256,
                provenance_sha256=None,
                plan_sha256=plan_sha256,
                summary={"has_errors": False, "valid": len(rows)},
                rows=rows,
                response_rows=tuple(
                    {"row_number": row.row_number, "valid": True} for row in rows
                ),
                revisions=revisions,
                expires_at=datetime.now(UTC) + timedelta(hours=1),
                command_id=preview_command,
                principal=actor,
            )

        parent_key = str(uuid4())
        parent_fingerprint = "d" * 64
        parent_command = await _domain_command(
            migrated_engine,
            actor=actor,
            operation="admin.curation.import",
            idempotency_key=parent_key,
            request_fingerprint=parent_fingerprint,
        )
        parent = ParentCommandIdentity(
            actor=actor,
            operation="admin.curation.import",
            idempotency_key=parent_key,
            request_fingerprint=parent_fingerprint,
        )

        async with session_factory() as session, session.begin():
            await session.execute(
                text("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE")
            )
            claimed_sha, stored_rows, _summary, _response, _expires = (
                await claim_curation_import_plan_command(
                    session,
                    import_plan_id=import_plan_id,
                    plan_sha256=plan_sha256,
                    command_id=parent_command,
                    principal=actor,
                )
            )
            result = await import_curation_rows(
                session,
                rows=stored_rows,
                actor=actor,
                source_content_sha256=claimed_sha,
                batch_kind="csv_upload",
                command_id=parent_command,
                parent_identity=parent,
                import_plan_id=import_plan_id,
                plan_sha256=plan_sha256,
            )

        # ── 부모 summary는 transaction 확정값이다 ─────────────────────────
        assert len(result["manual_children"]) == 1
        child = result["manual_children"][0]
        assert child.row_number == 3
        expected_identity = derive_child_command_identity(
            parent=parent,
            import_plan_id=import_plan_id,
            plan_sha256=plan_sha256,
            plan_row_number=3,
            manual_payload_sha256=manual.manual_feature_sha256 or "",
        )

        # ── 행별 좌표는 두 행 모두 돌아온다 ───────────────────────────────
        receipts = {receipt.row_number: receipt for receipt in result["row_receipts"]}
        assert set(receipts) == {2, 3}
        assert receipts[3].curation_item_id == child.curation_item_id
        assert receipts[3].accepted_link_decision_id is not None

        async with migrated_engine.connect() as connection:
            # child command는 유도된 결정적 identity로 발급됐다.
            child_command = (
                await connection.execute(
                    text(
                        "SELECT actor, operation, idempotency_key::text AS key, "
                        "request_fingerprint FROM ops.domain_commands "
                        "WHERE command_id = :command_id"
                    ),
                    {"command_id": child.child_command_id},
                )
            ).mappings().one()
            assert child_command["operation"] == expected_identity.operation
            assert child_command["key"] == str(expected_identity.idempotency_key)
            assert (
                child_command["request_fingerprint"]
                == expected_identity.request_fingerprint
            )

            # Feature는 place_name을 이름으로, typed category로 만들어졌다.
            feature = (
                await connection.execute(
                    text(
                        "SELECT name, category FROM feature.features "
                        "WHERE feature_uuid = CAST(:feature_uuid AS uuid)"
                    ),
                    {"feature_uuid": child.feature_uuid},
                )
            ).mappings().one()
            assert feature["name"] == "수동 생성 장소"
            assert feature["category"] == "12010000"
            origin_kind = await connection.scalar(
                text(
                    # origins 표의 feature_id 열은 UUID(3축 identity의 physical key)다.
                    "SELECT origin_kind FROM feature.feature_creation_origins "
                    "WHERE feature_id = CAST(:feature_uuid AS uuid)"
                ),
                {"feature_uuid": child.feature_uuid},
            )
            assert origin_kind == "manual_curation"

            # `301` linkage가 다섯 축을 전부 결박했다(FK 일곱이 정합을 강제).
            linkage = (
                await connection.execute(
                    text(
                        "SELECT plan_sha256, manual_payload_sha256, "
                        "child_command_id, feature_uuid::text AS feature_uuid, "
                        "import_row_id::text AS import_row_id, "
                        "curation_item_id::text AS curation_item_id "
                        "FROM ops.curation_import_manual_feature_children "
                        "WHERE import_plan_id = CAST(:plan_id AS uuid) "
                        "AND plan_row_number = 3"
                    ),
                    {"plan_id": import_plan_id},
                )
            ).mappings().one()
            assert linkage["plan_sha256"] == plan_sha256
            assert linkage["manual_payload_sha256"] == manual.manual_feature_sha256
            assert linkage["child_command_id"] == child.child_command_id
            assert linkage["feature_uuid"] == child.feature_uuid
            assert linkage["import_row_id"] == receipts[3].import_row_id
            assert linkage["curation_item_id"] == child.curation_item_id

            # import decision은 accepted/manual_feature_child로 남았다 — writer의
            # feature 결박이 'revoked'로 강등되지 않는다(302 decisions 분기).
            decision = (
                await connection.execute(
                    text(
                        "SELECT decision_kind, match_basis, feature_id "
                        "FROM feature.curation_link_decisions "
                        "WHERE decision_id = CAST(:decision_id AS uuid)"
                    ),
                    {"decision_id": receipts[3].accepted_link_decision_id},
                )
            ).mappings().one()
            assert decision["decision_kind"] == "accepted"
            assert decision["match_basis"] == "manual_feature_child"
            assert decision["feature_id"] == child.feature_id

            # item은 writer가 만든 그대로이고 feature 결박이 살아 있다(302 skip).
            item = (
                await connection.execute(
                    text(
                        "SELECT feature_id, source_present "
                        "FROM feature.curation_items "
                        "WHERE curation_item_id = CAST(:item_id AS uuid)"
                    ),
                    {"item_id": child.curation_item_id},
                )
            ).mappings().one()
            assert item["feature_id"] == child.feature_id
            assert item["source_present"] is True

            # child terminal result가 원장에 남았다(§6.3의 마지막 소유물).
            child_result = (
                await connection.execute(
                    text(
                        "SELECT response_status, response_body "
                        "FROM ops.domain_command_results "
                        "WHERE command_id = :command_id"
                    ),
                    {"command_id": child.child_command_id},
                )
            ).mappings().one()
            assert child_result["response_status"] == 201
    finally:
        await api.dispose()


async def _run_import(
    engine: AsyncEngine,
    session_factory: async_sessionmaker[AsyncSession],
    *,
    actor: str,
    rows: tuple[ResolvedCurationImportRow, ...],
) -> tuple[dict[str, object], str, str]:
    """plan 생성→claim→import 한 사이클. (result, plan_id, plan_sha) 반환."""

    preview_command = await _domain_command(
        engine,
        actor=actor,
        operation="admin.curation-import.preview",
        idempotency_key=str(uuid4()),
        request_fingerprint="c" * 64,
    )
    import_plan_id = str(uuid4())
    plan_sha256 = uuid4().hex + uuid4().hex
    content_sha256 = uuid4().hex + uuid4().hex
    async with session_factory() as session, session.begin():
        await session.execute(text("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE"))
        revisions = await build_curation_import_revision_vector(session, rows=rows)
        await create_curation_import_plan_command(
            session,
            import_plan_id=import_plan_id,
            content_sha256=content_sha256,
            provenance_sha256=None,
            plan_sha256=plan_sha256,
            summary={"has_errors": False, "valid": len(rows)},
            rows=rows,
            response_rows=tuple(
                {"row_number": row.row_number, "valid": True} for row in rows
            ),
            revisions=revisions,
            expires_at=datetime.now(UTC) + timedelta(hours=1),
            command_id=preview_command,
            principal=actor,
        )
    parent_key = str(uuid4())
    parent_command = await _domain_command(
        engine,
        actor=actor,
        operation="admin.curation.import",
        idempotency_key=parent_key,
        request_fingerprint="d" * 64,
    )
    parent = ParentCommandIdentity(
        actor=actor,
        operation="admin.curation.import",
        idempotency_key=parent_key,
        request_fingerprint="d" * 64,
    )
    async with session_factory() as session, session.begin():
        await session.execute(text("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE"))
        claimed_sha, stored_rows, _summary, _response, _expires = (
            await claim_curation_import_plan_command(
                session,
                import_plan_id=import_plan_id,
                plan_sha256=plan_sha256,
                command_id=parent_command,
                principal=actor,
            )
        )
        result = await import_curation_rows(
            session,
            rows=stored_rows,
            actor=actor,
            source_content_sha256=claimed_sha,
            batch_kind="csv_upload",
            command_id=parent_command,
            parent_identity=parent,
            import_plan_id=import_plan_id,
            plan_sha256=plan_sha256,
        )
    return dict(result), import_plan_id, plan_sha256


async def test_reimporting_the_same_manual_row_reuses_the_child(
    migrated_engine: AsyncEngine,
) -> None:
    """재수렴(적대 리뷰 H2/F3): 같은 manual CSV의 재commit은 이전 child를 재사용한다.

    authoritative replace가 manual 행에서 영구히 깨지지 않아야 한다 — 새 child
    command·linkage를 만들지 않고, 계보는 원 생성의 linkage 하나로 유지된다.
    """
    suffix = uuid4().hex[:12]
    actor = f"admin:m03-reuse-{suffix}"
    dataset_id = await _seed_dataset(migrated_engine, suffix=suffix)
    manual = _row(
        suffix=suffix,
        dataset_id=dataset_id,
        row_number=2,
        source_item_key="manual-1",
        place_name="재수렴 장소",
        manual_feature={
            "kind": "place",
            "category": "12010000",
            "coord": {"lon": "127.10000", "lat": "37.40000"},
        },
    )
    api = _runtime_engine(migrated_engine, login="ktm_feature_api_runtime")
    session_factory = async_sessionmaker(api, expire_on_commit=False)
    try:
        first, _plan1, _sha1 = await _run_import(
            migrated_engine, session_factory, actor=actor, rows=(manual,)
        )
        first_children = first["manual_children"]
        assert len(first_children) == 1
        assert first_children[0].reused is False
        # H4: fresh 생성은 inserted다.
        assert first["inserted"] == 1

        second, _plan2, _sha2 = await _run_import(
            migrated_engine, session_factory, actor=actor, rows=(manual,)
        )
        second_children = second["manual_children"]
        assert len(second_children) == 1
        assert second_children[0].reused is True
        assert (
            second_children[0].child_command_id
            == first_children[0].child_command_id
        )
        assert second_children[0].feature_uuid == first_children[0].feature_uuid
        assert second["inserted"] == 0

        async with migrated_engine.connect() as connection:
            linkage_count = await connection.scalar(
                text(
                    "SELECT count(*) FROM ops.curation_import_manual_feature_children "
                    "WHERE child_command_id = :command_id"
                ),
                {"command_id": first_children[0].child_command_id},
            )
            assert linkage_count == 1
    finally:
        await api.dispose()


async def test_manual_row_is_rejected_outside_the_command_path(
    migrated_engine: AsyncEngine,
) -> None:
    suffix = uuid4().hex[:12]
    dataset_id = await _seed_dataset(migrated_engine, suffix=suffix)
    manual = _row(
        suffix=suffix,
        dataset_id=dataset_id,
        row_number=2,
        source_item_key="manual-1",
        place_name="수동 생성 장소",
        manual_feature={
            "kind": "place",
            "category": "12010000",
            "coord": {"lon": "127.0", "lat": "37.5"},
        },
    )
    api = _runtime_engine(migrated_engine, login="ktm_feature_api_runtime")
    session_factory = async_sessionmaker(api, expire_on_commit=False)
    try:
        async with session_factory() as session, session.begin():
            with pytest.raises(ValueError, match="command 경로"):
                await import_curation_rows(
                    session,
                    rows=(manual,),
                    actor=f"admin:m03-child-{suffix}",
                    batch_kind="normalized_rows",
                )
    finally:
        await api.dispose()
