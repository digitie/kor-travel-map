"""TVN-C05 — 산림청 C05A~D provider catalog를 기존 DB에도 선언한다.

Revision ID: 0226_tvn_c05_krforest_datasets
Revises: 0225_tvn40c_physical_removal

baseline seed에는 이미 같은 catalog가 포함되지만, 0225 이후 기존 DB는 seed.sql을
재실행하지 않는다. 따라서 C05A~D의 provider dataset·operation·dataset_wide scope를
forward migration으로 보충한다. ID가 이미 존재할 때는 provider/dataset 계약이
다르면 조용히 넘어가지 않고 중단한다.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0226_tvn_c05_krforest_datasets"
down_revision: str | Sequence[str] | None = "0225_tvn40c_physical_removal"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_CATALOG_CHECK_SQL = """
DO $tvn_c05_catalog_check$
DECLARE
    expected RECORD;
    actual RECORD;
BEGIN
    FOR expected IN
        SELECT * FROM (VALUES
            (70, 'python-krforest-api', 'krforest_mountain_trails'),
            (71, 'python-krforest-api', 'krforest_dulle_trails'),
            (72, 'python-krforest-api', 'krforest_mountain_weather'),
            (73, 'python-krforest-api', 'krforest_wildfire_risk_forecast'),
            (74, 'python-krforest-api', 'krforest_landslide_forecast_issues')
        ) AS values_table(provider_dataset_id, provider, dataset_key)
    LOOP
        SELECT dataset.provider, dataset.dataset_key
          INTO actual
          FROM provider_sync.provider_datasets AS dataset
         WHERE dataset.provider_dataset_id = expected.provider_dataset_id;
        IF FOUND AND (actual.provider, actual.dataset_key)
            IS DISTINCT FROM (expected.provider, expected.dataset_key) THEN
            RAISE EXCEPTION
                'TVN-C05 provider_dataset_id % is already assigned to %/%; expected %/%',
                expected.provider_dataset_id,
                actual.provider,
                actual.dataset_key,
                expected.provider,
                expected.dataset_key
                USING ERRCODE = '23505';
        END IF;
    END LOOP;
END
$tvn_c05_catalog_check$;
"""

_DATASET_INSERT_SQL = """
INSERT INTO provider_sync.provider_datasets
    (provider_dataset_id, provider, dataset_key, display_name, source_kind,
     is_active, capabilities, created_at, updated_at)
OVERRIDING SYSTEM VALUE
VALUES
    (70, 'python-krforest-api', 'krforest_mountain_trails',
     '산림청 등산로(PBD0000041) route', 'openapi', true,
     '{"produces": ["route"], "extensions": {}, "schema_version": 1}',
     '2026-08-20 00:00:00+00', '2026-08-20 00:00:00+00'),
    (71, 'python-krforest-api', 'krforest_dulle_trails',
     '산림청 둘레길(PBD0000031) route', 'openapi', true,
     '{"produces": ["route"], "extensions": {}, "schema_version": 1}',
     '2026-08-20 00:00:00+00', '2026-08-20 00:00:00+00'),
    (72, 'python-krforest-api', 'krforest_mountain_weather',
     '산림청 산악기상 관측(15084696)', 'openapi', true,
     '{"produces": ["weather"], "extensions": {}, "schema_version": 1}',
     '2026-08-20 00:00:00+00', '2026-08-20 00:00:00+00'),
    (73, 'python-krforest-api', 'krforest_wildfire_risk_forecast',
     '산림청 산불위험 V2 예보(15084817)', 'openapi', true,
     '{"produces": ["weather"], "extensions": {}, "schema_version": 1}',
     '2026-08-20 00:00:00+00', '2026-08-20 00:00:00+00'),
    (74, 'python-krforest-api', 'krforest_landslide_forecast_issues',
     '산림청 산사태 예보발령·해제(15074798)', 'openapi', true,
     '{"produces": ["notice"], "extensions": {}, "schema_version": 1}',
     '2026-08-20 00:00:00+00', '2026-08-20 00:00:00+00')
ON CONFLICT (provider_dataset_id) DO NOTHING;
"""

_OPERATION_INSERT_SQL = """
INSERT INTO provider_sync.provider_dataset_operations
    (provider_dataset_id, operation_key, operation_kind, is_enabled, config,
     created_at, updated_at)
VALUES
    (70, 'feature_route_krforest_mountain_trails_job', 'refresh', true, '{}',
     '2026-08-20 00:00:00+00', '2026-08-20 00:00:00+00'),
    (70, 'feature_route_krforest_mountain_trails_job.preview', 'preview', true,
     '{"handler": "fixture"}', '2026-08-20 00:00:00+00', '2026-08-20 00:00:00+00'),
    (71, 'feature_route_krforest_dulle_trails_job', 'refresh', true, '{}',
     '2026-08-20 00:00:00+00', '2026-08-20 00:00:00+00'),
    (71, 'feature_route_krforest_dulle_trails_job.preview', 'preview', true,
     '{"handler": "fixture"}', '2026-08-20 00:00:00+00', '2026-08-20 00:00:00+00'),
    (72, 'feature_weather_krforest_mountain_weather_job', 'refresh', true, '{}',
     '2026-08-20 00:00:00+00', '2026-08-20 00:00:00+00'),
    (72, 'feature_weather_krforest_mountain_weather_job.preview', 'preview', true,
     '{"handler": "fixture"}', '2026-08-20 00:00:00+00', '2026-08-20 00:00:00+00'),
    (73, 'feature_weather_krforest_wildfire_risk_forecast_job', 'refresh', true, '{}',
     '2026-08-20 00:00:00+00', '2026-08-20 00:00:00+00'),
    (73, 'feature_weather_krforest_wildfire_risk_forecast_job.preview', 'preview', true,
     '{"handler": "fixture"}', '2026-08-20 00:00:00+00', '2026-08-20 00:00:00+00'),
    (74, 'feature_notice_krforest_landslide_forecast_issues_job', 'refresh', true, '{}',
     '2026-08-20 00:00:00+00', '2026-08-20 00:00:00+00'),
    (74, 'feature_notice_krforest_landslide_forecast_issues_job.preview', 'preview', true,
     '{"handler": "fixture"}', '2026-08-20 00:00:00+00', '2026-08-20 00:00:00+00')
ON CONFLICT (provider_dataset_id, operation_key) DO NOTHING;
"""

_SCOPE_INSERT_SQL = """
INSERT INTO provider_sync.provider_dataset_operation_scopes
    (provider_dataset_id, sync_scope, operation_key, operation_kind)
VALUES
    (70, 'dataset_wide', 'feature_route_krforest_mountain_trails_job', 'refresh'),
    (71, 'dataset_wide', 'feature_route_krforest_dulle_trails_job', 'refresh'),
    (72, 'dataset_wide', 'feature_weather_krforest_mountain_weather_job', 'refresh'),
    (73, 'dataset_wide', 'feature_weather_krforest_wildfire_risk_forecast_job', 'refresh'),
    (74, 'dataset_wide', 'feature_notice_krforest_landslide_forecast_issues_job', 'refresh')
ON CONFLICT (provider_dataset_id, sync_scope, operation_key) DO NOTHING;
"""

_SEQUENCE_SQL = """
SELECT setval(
    'provider_sync.provider_datasets_provider_dataset_id_seq',
    GREATEST((SELECT COALESCE(max(provider_dataset_id), 1)
                FROM provider_sync.provider_datasets), 1),
    true
);
"""


def upgrade() -> None:
    op.execute("SET ROLE ktm_feature_schema_owner")
    # asyncpg prepared statements do not accept multiple SQL commands. Keep each
    # statement separate while Alembic still wraps the migration transactionally.
    for statement in (
        _CATALOG_CHECK_SQL,
        _DATASET_INSERT_SQL,
        _OPERATION_INSERT_SQL,
        _SCOPE_INSERT_SQL,
        _SEQUENCE_SQL,
    ):
        op.execute(statement)


def downgrade() -> None:
    raise RuntimeError(
        "0226_tvn_c05_krforest_datasets is forward-only; "
        "이미 기록된 C05A~D source/operation state를 안전하게 되돌릴 수 없음"
    )
