"""T-VN-M03 — explicit manual curation writer의 실제 LOGIN 경계."""

from __future__ import annotations

import json
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine

from kortravelmap.infra.db import make_async_engine

pytestmark = pytest.mark.integration

_RUNTIME_PASSWORD = "tvn40-test-only-runtime-password"
_OPERATION = "admin.curation-item.create.manual-feature-v1"


def _runtime_engine(engine: AsyncEngine, *, login: str) -> AsyncEngine:
    dsn = engine.url.set(username=login, password=_RUNTIME_PASSWORD).render_as_string(
        hide_password=False
    )
    return make_async_engine(dsn, pool_size=1)


async def _command(engine: AsyncEngine, *, actor: str, operation: str) -> int:
    async with engine.begin() as connection:
        return int(
            await connection.scalar(
                text(
                    """
                    INSERT INTO ops.domain_commands (
                      actor, operation, idempotency_key, request_fingerprint
                    ) VALUES (
                      :actor, :operation, x_extension.gen_random_uuid(),
                      encode(x_extension.digest(
                        convert_to(x_extension.gen_random_uuid()::text, 'UTF8'),
                        'sha256'
                      ), 'hex')
                    ) RETURNING command_id
                    """
                ),
                {"actor": actor, "operation": operation},
            )
        )


async def _collection(engine: AsyncEngine, *, actor: str, suffix: str) -> str:
    api = _runtime_engine(engine, login="ktm_feature_api_runtime")
    try:
        theme_command = await _command(
            engine, actor=actor, operation="admin.curated-theme.create"
        )
        async with api.begin() as connection:
            await connection.execute(text("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE"))
            theme_id = str(
                (
                    await connection.execute(
                        text(
                            """
                            CALL feature.create_curated_theme_command(
                              :slug, 'M03 theme', '', 'test', 'admin_only',
                              '{}'::jsonb, :command_id, :actor, NULL, NULL
                            )
                            """
                        ),
                        {"actor": actor, "command_id": theme_command, "slug": f"m03-{suffix}"},
                    )
                ).mappings().one()["o_theme_id"]
            )
        collection_command = await _command(
            engine, actor=actor, operation="admin.curation-collection.create"
        )
        async with api.begin() as connection:
            await connection.execute(text("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE"))
            return str(
                (
                    await connection.execute(
                        text(
                            """
                            CALL feature.create_curation_collection_command(
                              :collection_key, CAST(:theme_id AS uuid), NULL,
                              'M03 collection', '', NULL, 'draft', 'admin_only',
                              '{}'::jsonb, :command_id, :actor, NULL, NULL
                            )
                            """
                        ),
                        {
                            "actor": actor,
                            "collection_key": f"m03-{suffix}",
                            "command_id": collection_command,
                            "theme_id": theme_id,
                        },
                    )
                ).mappings().one()["o_collection_id"]
            )
    finally:
        await api.dispose()


async def test_manual_curation_writer_keeps_feature_claim_origin_and_item_atomic(
    migrated_engine: AsyncEngine,
) -> None:
    suffix = uuid4().hex
    actor = f"admin:tvn-m03-{suffix}"
    collection_id = await _collection(migrated_engine, actor=actor, suffix=suffix)
    api = _runtime_engine(migrated_engine, login="ktm_feature_api_runtime")
    dagster = _runtime_engine(migrated_engine, login="ktm_feature_dagster_runtime")
    # T-VN-39(alembic 309) + ADR-098 결정 6: manual curation writer가 받는 payload의
    # ``feature_id``는 **호출자가 정하는 정본 UUIDv7 하나**다(사이드카가 15번째 글자로
    # v7을 검사하고, core가 돌려준 키가 이 값과 다르면 23514로 선다). legacy ``f_*``
    # 짝은 사라졌다 — 이 경로는 주소를 발급하지 않으므로 payload에 실을 것도 없고,
    # 사이드카의 허용 키 목록에 ``feature_uuid``가 없어 넣으면 23514다.
    feature_id = "018f9f2b-1234-7def-8abc-1234567890ab"
    duplicate_feature_id = "018f9f2b-4321-7def-8abc-1234567890ab"
    feature_payload = {
        "feature_id": feature_id,
        "kind": "place",
        "name": "M03 원자 생성 장소",
        "category": "01070300",
        "lon": 127.101234,
        "lat": 37.501234,
        "coord_precision_digits": 6,
        "marker_icon": "marker",
        "marker_color": "P-02",
    }
    item_payload = {
        "collection_id": collection_id,
        "external_item_id": f"m03-{suffix}",
        "external_component_id": "primary",
        "place_name": None,
        "address_hint": None,
        "status": "included",
        "sort_order": 0,
        "item_title": None,
        "item_summary": None,
        "curation_relation": "nearby_option",
        "reuse_policy": "manual_review",
        "metadata": {},
        "source_record_key": None,
    }
    try:
        command_id = await _command(migrated_engine, actor=actor, operation=_OPERATION)
        async with api.begin() as connection:
            await connection.execute(text("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE"))
            created = (
                await connection.execute(
                    text(
                        """
                        CALL feature.create_manual_curation_item_with_feature_command(
                          CAST(:feature_payload AS jsonb), CAST(:item_payload AS jsonb),
                          -- OUT 일곱: outcome · feature_id(uuid) · feature_row_revision
                          -- · curation_item_id · item_row_revision
                          -- · collection_row_revision · existing_feature_id(uuid).
                          -- T-VN-39가 legacy 문자열 축을 없애 여덟에서 일곱이 됐다.
                          :command_id, NULL::text, NULL::uuid, NULL::bigint,
                          NULL::uuid, NULL::bigint, NULL::bigint, NULL::uuid
                        )
                        """
                    ),
                    {
                        "command_id": command_id,
                        "feature_payload": json.dumps(feature_payload),
                        "item_payload": json.dumps(item_payload),
                    },
                )
            ).mappings().one()
        assert created["o_outcome"] == "created"
        assert str(created["o_feature_id"]) == feature_id
        item_id = str(created["o_curation_item_id"])

        async with migrated_engine.connect() as connection:
            evidence = (
                await connection.execute(
                    text(
                        """
                        SELECT origin.origin_kind, origin.creation_command_id,
                               origin.creator_principal_id, origin.procedure_definer,
                               CAST(item.feature_id AS text) AS feature_id,
                               item.source_record_key,
                               item.accepted_link_decision_id IS NOT NULL AS linked
                        FROM feature.feature_creation_origins AS origin
                        JOIN feature.curation_items AS item
                          ON item.curation_item_id = CAST(:item_id AS uuid)
                        WHERE origin.feature_id = CAST(:feature_id AS uuid)
                        """
                    ),
                    {"feature_id": feature_id, "item_id": item_id},
                )
            ).mappings().one()
        assert evidence == {
            "origin_kind": "manual_curation",
            "creation_command_id": command_id,
            "creator_principal_id": "admin-ui-bff.manual-curation-feature-create.v1",
            "procedure_definer": "ktm_curation_command_owner",
            "feature_id": feature_id,
            "source_record_key": None,
            "linked": True,
        }

        duplicate_command = await _command(migrated_engine, actor=actor, operation=_OPERATION)
        duplicate_item_payload = item_payload | {"external_item_id": f"m03-duplicate-{suffix}"}
        async with api.begin() as connection:
            await connection.execute(text("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE"))
            duplicate = (
                await connection.execute(
                    text(
                        """
                        CALL feature.create_manual_curation_item_with_feature_command(
                          CAST(:feature_payload AS jsonb), CAST(:item_payload AS jsonb),
                          -- OUT 일곱: outcome · feature_id(uuid) · feature_row_revision
                          -- · curation_item_id · item_row_revision
                          -- · collection_row_revision · existing_feature_id(uuid).
                          -- T-VN-39가 legacy 문자열 축을 없애 여덟에서 일곱이 됐다.
                          :command_id, NULL::text, NULL::uuid, NULL::bigint,
                          NULL::uuid, NULL::bigint, NULL::bigint, NULL::uuid
                        )
                        """
                    ),
                    {
                        "command_id": duplicate_command,
                        "feature_payload": json.dumps(
                            # 같은 identity claim 축(kind·name·좌표)을 유지한 채
                            # 정본 키만 다르게 준다 — 그래야 exact_conflict 분기다.
                            feature_payload | {"feature_id": duplicate_feature_id}
                        ),
                        "item_payload": json.dumps(duplicate_item_payload),
                    },
                )
            ).mappings().one()
        assert duplicate["o_outcome"] == "exact_conflict"
        assert str(duplicate["o_existing_feature_id"]) == feature_id
        async with migrated_engine.connect() as connection:
            item_count = await connection.scalar(
                text(
                    "SELECT count(*) FROM feature.curation_items "
                    "WHERE collection_id = CAST(:collection_id AS uuid)"
                ),
                {"collection_id": collection_id},
            )
        assert item_count == 1

        denied_command = await _command(migrated_engine, actor=actor, operation=_OPERATION)
        async with dagster.begin() as connection:
            await connection.execute(text("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE"))
            with pytest.raises(DBAPIError) as denied:
                await connection.execute(
                    text(
                        """
                        CALL feature.create_manual_curation_item_with_feature_command(
                          CAST(:feature_payload AS jsonb), CAST(:item_payload AS jsonb),
                          -- OUT 일곱: outcome · feature_id(uuid) · feature_row_revision
                          -- · curation_item_id · item_row_revision
                          -- · collection_row_revision · existing_feature_id(uuid).
                          -- T-VN-39가 legacy 문자열 축을 없애 여덟에서 일곱이 됐다.
                          :command_id, NULL::text, NULL::uuid, NULL::bigint,
                          NULL::uuid, NULL::bigint, NULL::bigint, NULL::uuid
                        )
                        """
                    ),
                    {
                        "command_id": denied_command,
                        "feature_payload": json.dumps(feature_payload),
                        "item_payload": json.dumps(item_payload),
                    },
                )
        assert getattr(denied.value.orig, "sqlstate", None) == "42501"
    finally:
        await api.dispose()
        await dagster.dispose()
