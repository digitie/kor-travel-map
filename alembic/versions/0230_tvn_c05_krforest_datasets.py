"""TVN-C05 — 산림청 C05A~D provider catalog를 기존 DB에도 선언한다.

Revision ID: 0230_tvn_c05_krforest_datasets
Revises: 0229_tvn40b_source_rule_action

baseline seed에는 이미 같은 catalog가 포함되지만, 0225 이후 기존 DB는 seed.sql을
재실행하지 않는다. 따라서 C05A~D의 provider dataset·operation·dataset_wide scope를
forward migration으로 보충한다.

**catalog identity는 자연키 ``(provider, dataset_key)``다** —
``uq_provider_datasets_identity``가 그 정본이고 ``provider_dataset_id``는
``Identity(always=True)`` 대리키라 환경마다 번호가 다르다. 실제로 prod는
``python-datagokr-api/standard_special_streets``에 73번을 배정해 뒀는데 baseline
seed는 같은 자연키를 69번으로 매긴다. 그러므로 이 migration은 대리키를 **고정하지
않는다**: dataset은 identity sequence가 번호를 매기게 두고, operation·scope는
자연키 JOIN으로 그 번호를 되찾는다. 이렇게 하면 대리키가 이미 남에게 배정된
환경에서도 동작하고, 무엇보다 operation이 **엉뚱한 dataset에 붙는 경로가 구조적으로
없다** — 예전 판은 ``ON CONFLICT (provider_dataset_id) DO NOTHING``으로 dataset을
건너뛴 뒤 같은 숫자로 operation을 밀어 넣었기 때문에, 대리키 가드가 없었다면 남의
dataset에 붙었을 것이다.

forward-only.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0230_tvn_c05_krforest_datasets"
down_revision: str | Sequence[str] | None = "0229_tvn40b_source_rule_action"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# 대리키 없이 자연키로만 선언한다. 이미 있으면(baseline seed로 만든 DB) 건너뛴다.
_DATASET_INSERT_SQL = """
INSERT INTO provider_sync.provider_datasets
    (provider, dataset_key, display_name, source_kind,
     is_active, capabilities, created_at, updated_at)
VALUES
    ('python-krforest-api', 'krforest_mountain_trails',
     '산림청 등산로(PBD0000041) route', 'openapi', true,
     '{"produces": ["route"], "extensions": {}, "schema_version": 1}',
     '2026-08-20 00:00:00+00', '2026-08-20 00:00:00+00'),
    ('python-krforest-api', 'krforest_dulle_trails',
     '산림청 둘레길(PBD0000031) route', 'openapi', true,
     '{"produces": ["route"], "extensions": {}, "schema_version": 1}',
     '2026-08-20 00:00:00+00', '2026-08-20 00:00:00+00'),
    ('python-krforest-api', 'krforest_mountain_weather',
     '산림청 산악기상 관측(15084696)', 'openapi', true,
     '{"produces": ["weather"], "extensions": {}, "schema_version": 1}',
     '2026-08-20 00:00:00+00', '2026-08-20 00:00:00+00'),
    ('python-krforest-api', 'krforest_wildfire_risk_forecast',
     '산림청 산불위험 V2 예보(15084817)', 'openapi', true,
     '{"produces": ["weather"], "extensions": {}, "schema_version": 1}',
     '2026-08-20 00:00:00+00', '2026-08-20 00:00:00+00'),
    ('python-krforest-api', 'krforest_landslide_forecast_issues',
     '산림청 산사태 예보발령·해제(15074798)', 'openapi', true,
     '{"produces": ["notice"], "extensions": {}, "schema_version": 1}',
     '2026-08-20 00:00:00+00', '2026-08-20 00:00:00+00')
ON CONFLICT (provider, dataset_key) DO NOTHING;
"""

# provider_dataset_id는 위 INSERT가(또는 seed가) 정한 값을 JOIN으로 되찾는다.
# 숫자를 다시 적지 않으므로 남의 dataset에 붙을 수 없다.
_OPERATION_INSERT_SQL = """
INSERT INTO provider_sync.provider_dataset_operations
    (provider_dataset_id, operation_key, operation_kind, is_enabled, config,
     created_at, updated_at)
SELECT
    dataset.provider_dataset_id,
    declared.operation_key,
    declared.operation_kind,
    true,
    declared.config::jsonb,
    TIMESTAMPTZ '2026-08-20 00:00:00+00',
    TIMESTAMPTZ '2026-08-20 00:00:00+00'
FROM (VALUES
    ('krforest_mountain_trails',
     'feature_route_krforest_mountain_trails_job', 'refresh', '{}'),
    ('krforest_mountain_trails',
     'feature_route_krforest_mountain_trails_job.preview', 'preview',
     '{"handler": "fixture"}'),
    ('krforest_dulle_trails',
     'feature_route_krforest_dulle_trails_job', 'refresh', '{}'),
    ('krforest_dulle_trails',
     'feature_route_krforest_dulle_trails_job.preview', 'preview',
     '{"handler": "fixture"}'),
    ('krforest_mountain_weather',
     'feature_weather_krforest_mountain_weather_job', 'refresh', '{}'),
    ('krforest_mountain_weather',
     'feature_weather_krforest_mountain_weather_job.preview', 'preview',
     '{"handler": "fixture"}'),
    ('krforest_wildfire_risk_forecast',
     'feature_weather_krforest_wildfire_risk_forecast_job', 'refresh', '{}'),
    ('krforest_wildfire_risk_forecast',
     'feature_weather_krforest_wildfire_risk_forecast_job.preview', 'preview',
     '{"handler": "fixture"}'),
    ('krforest_landslide_forecast_issues',
     'feature_notice_krforest_landslide_forecast_issues_job', 'refresh', '{}'),
    ('krforest_landslide_forecast_issues',
     'feature_notice_krforest_landslide_forecast_issues_job.preview', 'preview',
     '{"handler": "fixture"}')
) AS declared(dataset_key, operation_key, operation_kind, config)
JOIN provider_sync.provider_datasets AS dataset
  ON dataset.provider = 'python-krforest-api'
 AND dataset.dataset_key = declared.dataset_key
ON CONFLICT (provider_dataset_id, operation_key) DO NOTHING;
"""

_SCOPE_INSERT_SQL = """
INSERT INTO provider_sync.provider_dataset_operation_scopes
    (provider_dataset_id, sync_scope, operation_key, operation_kind)
SELECT
    dataset.provider_dataset_id,
    'dataset_wide',
    declared.operation_key,
    'refresh'
FROM (VALUES
    ('krforest_mountain_trails',
     'feature_route_krforest_mountain_trails_job'),
    ('krforest_dulle_trails',
     'feature_route_krforest_dulle_trails_job'),
    ('krforest_mountain_weather',
     'feature_weather_krforest_mountain_weather_job'),
    ('krforest_wildfire_risk_forecast',
     'feature_weather_krforest_wildfire_risk_forecast_job'),
    ('krforest_landslide_forecast_issues',
     'feature_notice_krforest_landslide_forecast_issues_job')
) AS declared(dataset_key, operation_key)
JOIN provider_sync.provider_datasets AS dataset
  ON dataset.provider = 'python-krforest-api'
 AND dataset.dataset_key = declared.dataset_key
ON CONFLICT (provider_dataset_id, sync_scope, operation_key) DO NOTHING;
"""

# baseline seed는 identity 값을 직접 지정해 행을 넣고 자기 setval을 남기므로
# sequence가 max보다 뒤처지는 경우는 data-only 복사본 정도다. 그때만 앞으로 민다 —
# **되감지 않는다**. 예전 판은 무조건 ``setval(max(id))``라, sequence가 이미 앞서
# 있는 prod에서 103 → max로 되감았다.
#
# 이 문장은 dataset INSERT보다 **먼저** 돈다. 뒤처진 sequence를 고치는 것이 목적인데
# 뒤에 두면 정작 그 상황에서 INSERT가 먼저 죽는다 — nextval이 이미 쓰이는 id를
# 돌려줘 ``pk_provider_datasets`` 위반이 나고, ``ON CONFLICT (provider, dataset_key)``
# 는 자연키 arbiter라 대리키 충돌을 잡지 못한다. GREATEST의 결과는 항상 max(id)
# 이상이므로 다음 nextval은 반드시 비어 있는 번호다.
_SEQUENCE_SQL = """
SELECT setval(
    'provider_sync.provider_datasets_provider_dataset_id_seq',
    GREATEST(
        (SELECT COALESCE(max(provider_dataset_id), 1)
           FROM provider_sync.provider_datasets),
        (SELECT last_value
           FROM provider_sync.provider_datasets_provider_dataset_id_seq),
        1
    ),
    true
);
"""

# 아무것도 넣지 않고 통과하는 일이 없도록 선언한 catalog가 실제로 서 있는지 사후
# 확인한다. dataset이 이미 있었을 때 계약(source_kind/capabilities)이 선언과 다르면
# 조용히 넘어가지 않고 중단한다 — 예전 판의 의도를 자연키 위에서 되살린 것이다.
_CATALOG_ASSERT_SQL = """
DO $tvn_c05_catalog_assert$
DECLARE
    missing_datasets text;
    mismatched_datasets text;
    missing_operations text;
    disabled_operations text;
    missing_scopes text;
BEGIN
    WITH declared(dataset_key, source_kind, capabilities) AS (
        VALUES
            ('krforest_mountain_trails', 'openapi',
             '{"produces": ["route"], "extensions": {}, "schema_version": 1}'::jsonb),
            ('krforest_dulle_trails', 'openapi',
             '{"produces": ["route"], "extensions": {}, "schema_version": 1}'::jsonb),
            ('krforest_mountain_weather', 'openapi',
             '{"produces": ["weather"], "extensions": {}, "schema_version": 1}'::jsonb),
            ('krforest_wildfire_risk_forecast', 'openapi',
             '{"produces": ["weather"], "extensions": {}, "schema_version": 1}'::jsonb),
            ('krforest_landslide_forecast_issues', 'openapi',
             '{"produces": ["notice"], "extensions": {}, "schema_version": 1}'::jsonb)
    )
    SELECT
        string_agg(declared.dataset_key, ', ')
            FILTER (WHERE dataset.provider_dataset_id IS NULL),
        string_agg(
            format('%s(source_kind=%s, capabilities=%s)',
                   declared.dataset_key, dataset.source_kind, dataset.capabilities),
            ', '
        ) FILTER (
            WHERE dataset.provider_dataset_id IS NOT NULL
              AND (dataset.source_kind, dataset.capabilities)
                  IS DISTINCT FROM (declared.source_kind, declared.capabilities)
        )
      INTO missing_datasets, mismatched_datasets
      FROM declared
      LEFT JOIN provider_sync.provider_datasets AS dataset
        ON dataset.provider = 'python-krforest-api'
       AND dataset.dataset_key = declared.dataset_key;

    IF missing_datasets IS NOT NULL THEN
        RAISE EXCEPTION
            'TVN-C05 provider dataset이 선언되지 않았다: %', missing_datasets
            USING ERRCODE = '23502';
    END IF;
    IF mismatched_datasets IS NOT NULL THEN
        RAISE EXCEPTION
            'TVN-C05 provider dataset 계약이 선언과 다르다: %', mismatched_datasets
            USING ERRCODE = '23514';
    END IF;

    SELECT string_agg(
               format('%s/%s', declared.dataset_key, declared.operation_key), ', ')
      INTO missing_operations
      FROM (VALUES
        ('krforest_mountain_trails',
         'feature_route_krforest_mountain_trails_job', 'refresh'),
        ('krforest_mountain_trails',
         'feature_route_krforest_mountain_trails_job.preview', 'preview'),
        ('krforest_dulle_trails',
         'feature_route_krforest_dulle_trails_job', 'refresh'),
        ('krforest_dulle_trails',
         'feature_route_krforest_dulle_trails_job.preview', 'preview'),
        ('krforest_mountain_weather',
         'feature_weather_krforest_mountain_weather_job', 'refresh'),
        ('krforest_mountain_weather',
         'feature_weather_krforest_mountain_weather_job.preview', 'preview'),
        ('krforest_wildfire_risk_forecast',
         'feature_weather_krforest_wildfire_risk_forecast_job', 'refresh'),
        ('krforest_wildfire_risk_forecast',
         'feature_weather_krforest_wildfire_risk_forecast_job.preview', 'preview'),
        ('krforest_landslide_forecast_issues',
         'feature_notice_krforest_landslide_forecast_issues_job', 'refresh'),
        ('krforest_landslide_forecast_issues',
         'feature_notice_krforest_landslide_forecast_issues_job.preview', 'preview')
      ) AS declared(dataset_key, operation_key, operation_kind)
     WHERE NOT EXISTS (
        SELECT 1
          FROM provider_sync.provider_dataset_operations AS operation
          JOIN provider_sync.provider_datasets AS dataset
            ON dataset.provider_dataset_id = operation.provider_dataset_id
         WHERE dataset.provider = 'python-krforest-api'
           AND dataset.dataset_key = declared.dataset_key
           AND operation.operation_key = declared.operation_key
           AND operation.operation_kind = declared.operation_kind
     );

    IF missing_operations IS NOT NULL THEN
        RAISE EXCEPTION
            'TVN-C05 provider dataset operation이 선언되지 않았다: %', missing_operations
            USING ERRCODE = '23502';
    END IF;

    -- "선언됐다"와 "돌 수 있다"는 다르다. is_enabled가 꺼진 채로 통과하면 catalog는
    -- 서 있는데 refresh는 영영 돌지 않는다.
    SELECT string_agg(
               format('%s/%s', dataset.dataset_key, operation.operation_key), ', ')
      INTO disabled_operations
      FROM provider_sync.provider_dataset_operations AS operation
      JOIN provider_sync.provider_datasets AS dataset
        ON dataset.provider_dataset_id = operation.provider_dataset_id
     WHERE dataset.provider = 'python-krforest-api'
       AND dataset.dataset_key IN (
            'krforest_mountain_trails',
            'krforest_dulle_trails',
            'krforest_mountain_weather',
            'krforest_wildfire_risk_forecast',
            'krforest_landslide_forecast_issues'
       )
       AND NOT operation.is_enabled;

    IF disabled_operations IS NOT NULL THEN
        RAISE EXCEPTION
            'TVN-C05 provider dataset operation이 꺼져 있다: %', disabled_operations
            USING ERRCODE = '23514';
    END IF;

    SELECT string_agg(
               format('%s/%s', declared.dataset_key, declared.operation_key), ', ')
      INTO missing_scopes
      FROM (VALUES
        ('krforest_mountain_trails',
         'feature_route_krforest_mountain_trails_job'),
        ('krforest_dulle_trails',
         'feature_route_krforest_dulle_trails_job'),
        ('krforest_mountain_weather',
         'feature_weather_krforest_mountain_weather_job'),
        ('krforest_wildfire_risk_forecast',
         'feature_weather_krforest_wildfire_risk_forecast_job'),
        ('krforest_landslide_forecast_issues',
         'feature_notice_krforest_landslide_forecast_issues_job')
      ) AS declared(dataset_key, operation_key)
     WHERE NOT EXISTS (
        SELECT 1
          FROM provider_sync.provider_dataset_operation_scopes AS scope
          JOIN provider_sync.provider_datasets AS dataset
            ON dataset.provider_dataset_id = scope.provider_dataset_id
         WHERE dataset.provider = 'python-krforest-api'
           AND dataset.dataset_key = declared.dataset_key
           AND scope.operation_key = declared.operation_key
           AND scope.sync_scope = 'dataset_wide'
     );

    IF missing_scopes IS NOT NULL THEN
        RAISE EXCEPTION
            'TVN-C05 dataset_wide scope가 선언되지 않았다: %', missing_scopes
            USING ERRCODE = '23502';
    END IF;
END
$tvn_c05_catalog_assert$;
"""


def upgrade() -> None:
    op.execute("SET ROLE ktm_feature_schema_owner")
    # asyncpg prepared statements do not accept multiple SQL commands. Keep each
    # statement separate while Alembic still wraps the migration transactionally.
    for statement in (
        # sequence 보정이 맨 앞이다 — _SEQUENCE_SQL 주석 참조.
        _SEQUENCE_SQL,
        _DATASET_INSERT_SQL,
        _OPERATION_INSERT_SQL,
        _SCOPE_INSERT_SQL,
        _CATALOG_ASSERT_SQL,
    ):
        op.execute(statement)


def downgrade() -> None:
    raise RuntimeError(
        "0230_tvn_c05_krforest_datasets is forward-only; "
        "이미 기록된 C05A~D source/operation state를 안전하게 되돌릴 수 없음"
    )
