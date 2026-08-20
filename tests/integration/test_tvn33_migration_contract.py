"""T-VN-33 catalog seed와 source-lineage final schema 회귀 검증."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from sqlalchemy import text

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


pytestmark = pytest.mark.integration


async def test_tvn33_fixture_preview_is_an_enabled_operation(
    migrated_session: AsyncSession,
) -> None:
    """Fixture preview는 refresh handler와 독립된 활성 operation으로 seed된다."""

    rows = (
        await migrated_session.execute(
            text(
                """
                SELECT dataset.provider, dataset.dataset_key,
                       operation.operation_key, operation.operation_kind,
                       operation.is_enabled, operation.config
                FROM provider_sync.provider_datasets AS dataset
                JOIN provider_sync.provider_dataset_operations AS operation
                  ON operation.provider_dataset_id = dataset.provider_dataset_id
                WHERE (dataset.provider, dataset.dataset_key) IN (
                    ('data.go.kr-standard', 'datagokr_cultural_festivals'),
                    ('python-airkorea-api', 'airkorea_stations')
                )
                  AND operation.operation_kind = 'preview'
                ORDER BY dataset.provider, dataset.dataset_key
                """
            )
        )
    ).mappings().all()

    assert [(row["provider"], row["dataset_key"]) for row in rows] == [
        ("data.go.kr-standard", "datagokr_cultural_festivals"),
        ("python-airkorea-api", "airkorea_stations"),
    ]
    assert all(row["is_enabled"] is True for row in rows)
    assert all(row["config"] == {"handler": "fixture"} for row in rows)


async def test_tvn33_final_schema_has_no_legacy_ownership_shadow_columns(
    migrated_session: AsyncSession,
) -> None:
    """모든 대상 table은 provider/dataset pair·array shadow를 실제로 제거한다."""

    rows = (
        await migrated_session.execute(
            text(
                """
                SELECT table_name, column_name
                FROM information_schema.columns
                WHERE (
                    (table_schema = 'provider_sync' AND table_name = 'source_entities'
                     AND column_name IN ('provider', 'dataset_key', 'current_source_record_key'))
                    OR (table_schema = 'provider_sync' AND table_name = 'source_records'
                        AND column_name IN (
                            'provider', 'dataset_key', 'source_entity_type',
                            'source_entity_id', 'source_version', 'raw_name',
                            'raw_address', 'raw_longitude', 'raw_latitude',
                            'last_seen_at', 'expires_at'
                        ))
                    OR (table_schema = 'provider_sync' AND table_name = 'source_links'
                        AND column_name = 'is_primary_source')
                    OR (table_schema = 'provider_sync' AND table_name = 'provider_sync_state'
                        AND column_name IN ('provider', 'dataset_key'))
                    OR (table_schema = 'provider_sync' AND table_name = 'notice_lifecycle_scopes'
                        AND column_name IN ('provider', 'dataset_key'))
                    OR (table_schema = 'provider_sync' AND table_name = 'notice_lineage_states'
                        AND column_name IN ('provider', 'dataset_key', 'source_entity_type'))
                    OR (table_schema = 'feature' AND table_name = 'curated_sources'
                        AND column_name IN ('provider', 'dataset_key'))
                    OR (table_schema = 'ops' AND table_name = 'enrichment_review_queue'
                        AND column_name IN (
                            'source_provider', 'source_dataset_key',
                            'source_entity_id', 'source_record'
                        ))
                    OR (table_schema = 'feature' AND table_name = 'curated_source_rules'
                        AND column_name = 'dataset_key')
                    OR (table_schema = 'ops' AND table_name = 'import_jobs'
                        AND column_name IN (
                            'provider', 'dataset_key', 'sync_scope',
                            'operation_registry_version'
                        ))
                    OR (table_schema = 'ops' AND table_name = 'import_job_events'
                        AND column_name IN ('provider', 'dataset_key', 'sync_scope'))
                    OR (table_schema = 'ops' AND table_name = 'feature_update_requests'
                        AND column_name IN ('providers', 'dataset_keys'))
                    OR (table_schema = 'ops' AND table_name = 'offline_uploads'
                        AND column_name IN ('provider', 'dataset_key'))
                    OR (table_schema = 'ops' AND table_name = 'provider_refresh_policies'
                        AND column_name IN ('provider', 'dataset_key'))
                    OR (table_schema = 'ops' AND table_name = 'integrity_observation_scopes'
                        AND column_name IN ('provider', 'dataset_key'))
                    OR (table_schema = 'ops' AND table_name = 'integrity_observation_runs'
                        AND column_name IN ('provider', 'dataset_key'))
                    OR (table_schema = 'ops' AND table_name = 'data_integrity_violations'
                        AND column_name IN ('provider', 'dataset_key'))
                    OR (table_schema = 'ops' AND table_name = 'poi_cache_target_feature_links'
                        AND column_name IN ('provider', 'dataset_key'))
                    OR (table_schema = 'ops' AND table_name = 'managed_files'
                        AND column_name IN ('provider', 'dataset_key'))
                )
                ORDER BY table_schema, table_name, column_name
                """
            )
        )
    ).all()

    assert rows == []


async def test_tvn33_final_schema_enforces_canonical_membership_links(
    migrated_session: AsyncSession,
) -> None:
    """event/request와 provider-owned row는 canonical ID 및 member FK만 사용한다."""

    rows = (
        await migrated_session.execute(
            text(
                """
                SELECT constraint_name
                FROM information_schema.table_constraints
                WHERE (table_schema, table_name, constraint_name) IN (
                    ('ops', 'import_jobs', 'ck_import_jobs_membership_mode'),
                    ('ops', 'import_jobs', 'ck_import_jobs_operation_key_shape'),
                    ('ops', 'import_job_datasets', 'fk_import_job_datasets_job'),
                    ('ops', 'import_job_datasets',
                     'fk_import_job_datasets_exact_operation_scope'),
                    ('ops', 'import_job_events', 'fk_import_job_events_job_member'),
                    ('ops', 'feature_update_requests',
                     'ck_feature_update_requests_membership_mode'),
                    ('ops', 'feature_update_request_datasets',
                     'fk_feature_update_request_datasets_request'),
                    ('ops', 'feature_update_request_datasets',
                     'fk_feature_update_request_datasets_exact_operation_scope'),
                    ('ops', 'offline_uploads',
                     'fk_offline_uploads_exact_operation_scope'),
                    ('ops', 'provider_refresh_policies',
                     'fk_provider_refresh_policies_dataset'),
                    ('ops', 'integrity_observation_scopes',
                     'fk_integrity_observation_scopes_dataset'),
                    ('ops', 'integrity_observation_runs',
                     'fk_integrity_observation_runs_scope'),
                    ('ops', 'data_integrity_violations',
                     'fk_data_integrity_violations_dataset'),
                    ('ops', 'poi_cache_target_feature_links',
                     'fk_poi_cache_target_feature_links_dataset'),
                    ('ops', 'managed_files', 'fk_managed_files_dataset')
                )
                ORDER BY constraint_name
                """
            )
        )
    ).scalars().all()

    assert rows == sorted(
        {
            "ck_feature_update_requests_membership_mode",
            "ck_import_jobs_membership_mode",
            "ck_import_jobs_operation_key_shape",
            "fk_data_integrity_violations_dataset",
            "fk_feature_update_request_datasets_request",
            "fk_feature_update_request_datasets_exact_operation_scope",
            "fk_import_job_datasets_job",
            "fk_import_job_datasets_exact_operation_scope",
            "fk_import_job_events_job_member",
            "fk_integrity_observation_runs_scope",
            "fk_integrity_observation_scopes_dataset",
            "fk_managed_files_dataset",
            "fk_offline_uploads_exact_operation_scope",
            "fk_poi_cache_target_feature_links_dataset",
            "fk_provider_refresh_policies_dataset",
        }
    )




async def test_offline_upload_guard_rejects_disabled_sibling_operation(
    migrated_session: AsyncSession,
) -> None:
    """offline upload 활성 가드는 **행 자신의 operation_key**까지 본다.

    0091은 실행 membership 4개 테이블 중 셋(provider_sync_state,
    import_job_datasets, feature_update_request_datasets)을 triple 가드로 승격하면서
    ``ops.offline_uploads``만 pair 시절 함수에 남겨 뒀다. 그 함수는 (dataset, scope)에
    enabled operation이 **하나라도** 있으면 통과시키므로, 형제 중 하나만 enabled면
    disabled operation에 결박된 upload가 들어왔다 — identity는 triple인데 강제는
    pair였다(적대 리뷰 10라운드, migrated head에서 재현).

    UPDATE 소유권 검사도 pair였다. operation_key만 바꾸면 upload가 **어느 실행에
    결박됐는지**가 조용히 갈렸다.
    """

    picked = (
        await migrated_session.execute(
            text(
                """
                SELECT scope.provider_dataset_id, scope.sync_scope, scope.operation_key
                FROM provider_sync.provider_dataset_operation_scopes AS scope
                JOIN provider_sync.provider_dataset_operations AS operation
                  ON operation.provider_dataset_id = scope.provider_dataset_id
                 AND operation.operation_key = scope.operation_key
                 AND operation.operation_kind = scope.operation_kind
                JOIN provider_sync.provider_datasets AS dataset
                  ON dataset.provider_dataset_id = scope.provider_dataset_id
                WHERE scope.operation_kind = 'refresh'
                  AND operation.is_enabled
                  AND dataset.is_active
                ORDER BY scope.provider_dataset_id, scope.sync_scope
                LIMIT 1
                """
            )
        )
    ).one()
    dataset_id = int(picked.provider_dataset_id)
    sync_scope = str(picked.sync_scope)
    sibling = f"{picked.operation_key}.disabled_sibling"

    # 스키마가 허용하는 상태다 — scope PK가 triple이라 형제 등록이 정상 write다.
    await migrated_session.execute(
        text(
            """
            INSERT INTO provider_sync.provider_dataset_operations (
                provider_dataset_id, operation_key, operation_kind, is_enabled
            ) VALUES (:dataset_id, :sibling, 'refresh', false)
            """
        ),
        {"dataset_id": dataset_id, "sibling": sibling},
    )
    await migrated_session.execute(
        text(
            """
            INSERT INTO provider_sync.provider_dataset_operation_scopes (
                provider_dataset_id, sync_scope, operation_key, operation_kind
            ) VALUES (:dataset_id, :sync_scope, :sibling, 'refresh')
            """
        ),
        {"dataset_id": dataset_id, "sync_scope": sync_scope, "sibling": sibling},
    )

    with pytest.raises(Exception, match="disabled for normal writes"):
        await migrated_session.execute(
            text(
                """
                INSERT INTO ops.offline_uploads (
                    provider_dataset_id, sync_scope, operation_key, original_filename,
                    storage_backend, storage_key, byte_size, checksum_sha256
                ) VALUES (
                    :dataset_id, :sync_scope, :sibling, 'guard-probe.json',
                    'object_store', 'guard/probe.json', 1,
                    repeat('a', 64)
                )
                """
            ),
            {"dataset_id": dataset_id, "sync_scope": sync_scope, "sibling": sibling},
        )
