"""Map에서 weather 기능의 데이터와 weather 전용 스키마를 지운다(ADR-105).

Revision ID: 402_remove_map_weather_data
Revises: 401_retire_map_kma_refresh

왜 필요한가. 2026-10-01 소유자 결정으로 Map은 ``weather`` kind Feature의 기능을 전부
내려놓는다(출처 무관 — KMA·AirKorea·KREX 휴게소 기상·산림청 산악기상·산불위험 예보).
날씨는 kor-travel-weather가 소유하고 PinVi는 이미 그쪽에서 받는다(ADR-068). 기상 출처
notice(= provider ``python-kma-api``가 내는 notice, 즉 기상특보)도 함께 내려놓는다.
**정의는 남긴다** — kind/category 값(``weather``), DTO, ``ck_features_ck_features_kind``·
``ck_provider_feature_identities_kind``·capabilities 검사의 ``weather``는 그대로다.

대상은 이름이 아니라 **정체성**으로 고른다(이름을 나열하면 빠진 것이 조용히 남는다).

- weather dataset = ``capabilities -> 'produces'``에 ``"weather"``가 있는 dataset.
- 기상 notice dataset = ``produces``에 ``"notice"``가 있고 provider가 ``python-kma-api``.
- 대상 Feature = ``kind = 'weather'`` 전부 + 기상 notice dataset에 identity claim
  또는 ``primary`` source link로 묶인 ``kind = 'notice'``.

산림청 산사태 예보(``krforest_landslide_forecast_issues``)와 KREX 교통 공지는 기상
출처가 아니므로 대상이 아니다.

무엇을 하는가(실행 순서 = ``_UPGRADE_STATEMENTS``)
--------------------------------------------------

0. 대상 dataset 중 이미 비활성인 것을 이 트랜잭션 안에서만 다시 켠다. 아래 삭제가
   지나가는 활성 가드(``reject_inactive_source_entity_dataset`` 등)는 **DELETE에도**
   dataset 활성을 요구하고, operation UPDATE도 활성 dataset만 받는다. 마지막 단계가
   대상 전부를 다시 끄므로 밖에서는 이 중간 상태가 보이지 않는다.
1. 대상 dataset의 operation을 **종류 불문**(``refresh``·``feature_load``·``preview``)
   ``is_enabled = false``로 내린다. 행은 지우지 않는다 — ``import_job_datasets``·
   ``feature_update_request_datasets``·``provider_sync_state``가 exact FK로 가리키는
   이력이다.
2. weather 전용 객체를 DROP한다(아래 "무엇이 weather 전용인가"). 표를 **먼저** 지우는
   이유: ``feature_weather_values``는 행마다 불변 트리거와 source record로의
   ``ON DELETE RESTRICT`` FK를 갖는다 — 남겨 두면 source lineage를 지울 수 없다. 그리고
   ``current_weather_summary``의 FK가 사라져야 weather summary run을 지울 수 있다.
3. 대상 Feature를 지운다. 의존 행은 스키마가 선언한 FK 동작이 처리한다(CASCADE:
   subtype·alias·base field·override·dedup/enrichment 큐·merge 이력·POI cache 링크·
   source link, SET NULL: curation item·integrity violation·자식 Feature의 부모).
   ``feature.purge_manual_feature``가 같은 규율로 산다 — c/n은 따라가고 r/a는 막는다.
4. 대상 dataset의 identity claim·source lineage(link → enrichment 큐 → notice lifecycle
   scope/lineage → head → record → entity)를 지운다.
5. weather current-summary run 영수증을 지운다. 종결 영수증은 불변 트리거가 막으므로
   0236(``alembic/retired_versions``)의 선례대로 **이 트랜잭션 안에서만** 트리거를 끄고
   즉시 다시 켠다(전후 모드를 잰다). 그 뒤 ``ck_current_summary_runs_projection_kind``를
   ``'price'``로 좁힌다 — 표는 price가 함께 쓰므로 남긴다.
6. 대상 dataset을 ``is_active = false``로 내린다. 카탈로그 행은 지우지 않는다(이력 FK).
7. receipt head CHECK에 이 revision을 더한다(401과 같은 계약).

무엇이 weather 전용인가(``alembic/head-schema.sql`` 전수 검색으로 확인)
-------------------------------------------------------------------

- ``feature.feature_weather_values`` — 참조자는 ``fk_current_weather_summary_fact``
  하나뿐이고 그 표도 함께 지운다. 뷰·함수 본문 어디에서도 읽지 않는다.
- ``feature.current_weather_summary`` — 참조자 없음.
- ``feature.reject_weather_value_mutation()`` — 호출자는
  ``trg_feature_weather_values_immutable`` 하나뿐이다(표와 함께 사라진다).
- ``feature.idx_features_public_weather_coord_5179_gist`` — ``kind = 'weather'`` 부분
  index. 이 술어를 쓰던 nearest-weather 조회가 사라진다.

**남기는 것**: ``ops.current_summary_runs``(price 공유), kind/capabilities CHECK의
``weather``(정의), ``source_links`` role ``weather_context``(정의 값), 그리고
``provider_sync.notice_lineage_key``의 KMA 분기. 그 분기는 KMA head가 0행이고 dataset이
비활성이라(쓰기 불가) 다시 평가될 수 없다 — 지우려면 모든 notice head 쓰기가 지나가는
함수를 다시 써야 하는데 얻는 정확성이 없다.

**남는 이력**: append-only 증거 표의 soft reference(``feature_state_transitions``·
``curation_link_decisions``·``import_job_events``·theme candidate observation 등)는
지우지 않는다. ``purge_manual_feature``와 같은 규율이다 — 그 표들은 무엇이 있었는지의
기록이고, 지우려면 fence를 꺼야 한다.

막는 것(preflight, 하나라도 있으면 아무것도 바꾸지 않고 중단)
--------------------------------------------------------------

삭제가 append-only 증거를 지우거나 남는 데이터를 조용히 깨는 경우다. 2026-10-01 prod는
Feature 0행이라 전부 0이다 — 그래도 조건을 행 수에 걸지 않는다.

- 대상 Feature/entity를 ``RESTRICT``·``NO ACTION``으로 붙든 불변 증거
  (theme candidate·manual/provider dedup case·reference reconciliation event·
  feature request의 ``resolved_feature_id``·대상 entity를 출처로 둔 price fact)와
  purge되지 않은 manual identity claim.
- 대상 dataset에 identity/primary link/base field로 묶였는데 대상이 아닌 Feature —
  지우면 남는 Feature의 lineage가 끊긴다.
- 대상 dataset의 **아직 켜진** operation을 member로 둔 queued/running job — dataset을
  끄면 그 job은 영영 종결로 갈 수 없다(``assert_import_job_members_active``).

트랜잭션. env.py가 전 revision을 한 트랜잭션으로 돈다. 전부 되거나 전부 안 된다 —
중간 상태(표는 지웠는데 dataset은 켜진)가 남지 않는다. ``DROP INDEX``가
``feature.features``에 ACCESS EXCLUSIVE를 잡으므로 배포 중 weather 적재·summary
schedule이 돌고 있으면 서로 기다린다(교착이면 PostgreSQL이 한쪽을 끊는다) — 배포 전에
멈춰 두는 것이 맞다.

백업 단계는 두지 않는다 — 소유자가 명시적으로 면제했다(2026-10-01).

forward-only. downgrade는 두지 않는다(ADR-021) — 지운 데이터는 되살릴 수 없고, weather를
Map에 되살리는 것은 새 결정이다.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Final

from sqlalchemy import text
from sqlalchemy.engine import Connection

from alembic import op

# ruff: noqa: E501

revision: str = "402_remove_map_weather_data"
down_revision: str | Sequence[str] | None = "401_retire_map_kma_refresh"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: KMA의 provider 정체성(401과 같은 값). 기상 notice를 가르는 축이다.
KMA_PROVIDER: Final[str] = "python-kma-api"

#: 대상 dataset — weather를 내거나, KMA가 내는 notice.
_TARGET_DATASETS_SQL: Final[str] = f"""
SELECT dataset.provider_dataset_id
  FROM provider_sync.provider_datasets AS dataset
 WHERE (dataset.capabilities -> 'produces') @> '["weather"]'::jsonb
    OR ((dataset.capabilities -> 'produces') @> '["notice"]'::jsonb
        AND dataset.provider = '{KMA_PROVIDER}')
"""

#: 기상 notice dataset — 대상 notice Feature를 가르는 쪽만.
_WEATHER_NOTICE_DATASETS_SQL: Final[str] = f"""
SELECT notice_dataset.provider_dataset_id
  FROM provider_sync.provider_datasets AS notice_dataset
 WHERE (notice_dataset.capabilities -> 'produces') @> '["notice"]'::jsonb
   AND notice_dataset.provider = '{KMA_PROVIDER}'
"""

#: 대상 dataset의 source entity.
_TARGET_ENTITIES_SQL: Final[str] = f"""
SELECT target_entity.source_entity_key
  FROM provider_sync.source_entities AS target_entity
 WHERE target_entity.provider_dataset_id IN ({_TARGET_DATASETS_SQL})
"""

#: 대상 Feature 술어. ``feature``라는 별칭의 ``feature.features`` 행에 건다.
#: identity claim과 primary link를 **삭제 전에** 읽어야 하므로 Feature 삭제가
#: identity·link 삭제보다 앞선다.
_TARGET_FEATURE_PREDICATE: Final[str] = f"""(
    feature.kind = 'weather'
    OR (
        feature.kind = 'notice'
        AND (
            EXISTS (
                SELECT 1
                  FROM provider_sync.provider_feature_identities AS identity
                 WHERE identity.feature_id = feature.feature_id
                   AND identity.provider_dataset_id IN ({_WEATHER_NOTICE_DATASETS_SQL})
            )
            OR EXISTS (
                SELECT 1
                  FROM provider_sync.source_links AS link
                  JOIN provider_sync.source_entities AS link_entity
                    ON link_entity.source_entity_key = link.source_entity_key
                 WHERE link.feature_id = feature.feature_id
                   AND link.source_role = 'primary'
                   AND link_entity.provider_dataset_id IN ({_WEATHER_NOTICE_DATASETS_SQL})
            )
        )
    )
)"""

_TARGET_FEATURES_SQL: Final[str] = f"""
SELECT feature.feature_id
  FROM feature.features AS feature
 WHERE {_TARGET_FEATURE_PREDICATE}
"""

#: 불변 트리거. 이름이 아니라 head-schema가 선언한 그대로다.
_SUMMARY_RUN_FENCE: Final[str] = "trg_current_summary_runs_terminal_immutable"

_SUMMARY_RUN_FENCE_MODE_SQL: Final[str] = f"""
SELECT tgenabled::text
  FROM pg_catalog.pg_trigger
 WHERE tgrelid = 'ops.current_summary_runs'::regclass
   AND tgname = '{_SUMMARY_RUN_FENCE}'
"""

# ---------------------------------------------------------------------------
# preflight — 하나라도 행을 내면 중단한다. 각 질의는 사람이 읽을 식별자를 낸다.
# ---------------------------------------------------------------------------

_PREFLIGHT_BLOCKERS: Final[tuple[tuple[str, str], ...]] = (
    (
        "feature.theme_feature_candidates (RESTRICT + no-delete fence)",
        f"""
        SELECT candidate.candidate_id::text
          FROM feature.theme_feature_candidates AS candidate
         WHERE candidate.feature_id IN ({_TARGET_FEATURES_SQL})
            OR candidate.source_entity_key IN ({_TARGET_ENTITIES_SQL})
         LIMIT 10
        """,
    ),
    (
        "ops.manual_provider_dedup_cases (RESTRICT + append-only)",
        f"""
        SELECT dedup_case.case_id::text
          FROM ops.manual_provider_dedup_cases AS dedup_case
         WHERE dedup_case.manual_feature_id IN ({_TARGET_FEATURES_SQL})
            OR dedup_case.provider_feature_id IN ({_TARGET_FEATURES_SQL})
            OR dedup_case.source_entity_key IN ({_TARGET_ENTITIES_SQL})
         LIMIT 10
        """,
    ),
    (
        "ops.feature_reference_reconciliation_events (RESTRICT + append-only)",
        f"""
        SELECT reconciliation.event_id::text
          FROM ops.feature_reference_reconciliation_events AS reconciliation
         WHERE reconciliation.old_feature_id IN ({_TARGET_FEATURES_SQL})
            OR reconciliation.replacement_feature_id IN ({_TARGET_FEATURES_SQL})
         LIMIT 10
        """,
    ),
    (
        "ops.feature_requests.resolved_feature_id (NO ACTION + no-delete fence)",
        f"""
        SELECT request.request_id::text
          FROM ops.feature_requests AS request
         WHERE request.resolved_feature_id IN ({_TARGET_FEATURES_SQL})
         LIMIT 10
        """,
    ),
    (
        "feature.manual_feature_identity_claims (manual Feature needs purge_manual_feature)",
        f"""
        SELECT claim.feature_id::text
          FROM feature.manual_feature_identity_claims AS claim
         WHERE claim.feature_id IN ({_TARGET_FEATURES_SQL})
           AND claim.purged_by_command_id IS NULL
         LIMIT 10
        """,
    ),
    (
        "feature.feature_price_values sourced from a target entity (RESTRICT)",
        f"""
        SELECT price.price_value_key
          FROM feature.feature_price_values AS price
         WHERE price.source_entity_key IN ({_TARGET_ENTITIES_SQL})
         LIMIT 10
        """,
    ),
    (
        "non-target Feature bound to a target dataset (lineage would be cut)",
        f"""
        SELECT feature.feature_id::text
          FROM feature.features AS feature
         WHERE NOT {_TARGET_FEATURE_PREDICATE}
           AND (
               EXISTS (
                   SELECT 1
                     FROM provider_sync.provider_feature_identities AS bound_identity
                    WHERE bound_identity.feature_id = feature.feature_id
                      AND bound_identity.provider_dataset_id IN ({_TARGET_DATASETS_SQL})
               )
               OR EXISTS (
                   SELECT 1
                     FROM provider_sync.source_links AS bound_link
                    WHERE bound_link.feature_id = feature.feature_id
                      AND bound_link.source_role = 'primary'
                      AND bound_link.source_entity_key IN ({_TARGET_ENTITIES_SQL})
               )
               OR EXISTS (
                   SELECT 1
                     FROM feature.feature_base_field_values AS bound_value
                    WHERE bound_value.feature_id = feature.feature_id
                      AND bound_value.source_entity_key IN ({_TARGET_ENTITIES_SQL})
               )
           )
         LIMIT 10
        """,
    ),
    (
        "queued/running job on a still-enabled target operation (would freeze)",
        f"""
        SELECT in_flight.job_id
          FROM (
              SELECT job.job_id::text AS job_id
                FROM ops.import_jobs AS job
                JOIN ops.import_job_datasets AS member
                  ON member.job_id = job.job_id
                JOIN provider_sync.provider_dataset_operations AS operation
                  ON operation.provider_dataset_id = member.provider_dataset_id
                 AND operation.operation_key = member.operation_key
               WHERE job.status IN ('queued', 'running')
                 AND operation.is_enabled
                 AND member.provider_dataset_id IN ({_TARGET_DATASETS_SQL})
              UNION
              SELECT job.job_id::text AS job_id
                FROM ops.feature_update_request_datasets AS member
                JOIN ops.feature_update_requests AS request
                  ON request.request_id = member.request_id
                JOIN ops.import_jobs AS job
                  ON job.job_id = request.job_id
                JOIN provider_sync.provider_dataset_operations AS operation
                  ON operation.provider_dataset_id = member.provider_dataset_id
                 AND operation.operation_key = member.operation_key
               WHERE job.status IN ('queued', 'running')
                 AND operation.is_enabled
                 AND member.provider_dataset_id IN ({_TARGET_DATASETS_SQL})
          ) AS in_flight
         ORDER BY in_flight.job_id
         LIMIT 10
        """,
    ),
)

# ---------------------------------------------------------------------------
# upgrade 문장 — 실행 순서 그대로.
# ---------------------------------------------------------------------------

#: 0. 이미 꺼진 대상 dataset을 이 트랜잭션 안에서만 켠다(6에서 다시 끈다).
_REACTIVATE_FOR_CLEANUP_SQL: Final[str] = f"""
UPDATE provider_sync.provider_datasets AS dataset
   SET is_active = true
 WHERE dataset.provider_dataset_id IN ({_TARGET_DATASETS_SQL})
   AND NOT dataset.is_active
"""

#: 1. 대상 dataset의 operation을 종류 불문하고 끈다.
_DISABLE_TARGET_OPERATIONS_SQL: Final[str] = f"""
UPDATE provider_sync.provider_dataset_operations AS operation
   SET is_enabled = false
 WHERE operation.provider_dataset_id IN ({_TARGET_DATASETS_SQL})
   AND operation.is_enabled
"""

#: 2. weather 전용 객체. CASCADE를 쓰지 않는다 — 모르는 의존자가 있으면 멈춰야 한다.
_DROP_CURRENT_WEATHER_SUMMARY_SQL: Final[str] = "DROP TABLE feature.current_weather_summary"
_DROP_WEATHER_VALUES_SQL: Final[str] = "DROP TABLE feature.feature_weather_values"
_DROP_WEATHER_VALUE_FENCE_SQL: Final[str] = (
    "DROP FUNCTION feature.reject_weather_value_mutation()"
)
_DROP_WEATHER_COORD_INDEX_SQL: Final[str] = (
    "DROP INDEX feature.idx_features_public_weather_coord_5179_gist"
)

#: 3a. 대상 Feature·dataset의 integrity finding. FK가 SET NULL로 남기면 주인 없는
#: finding이 되고, dataset을 끈 뒤에는 그 행을 고칠 수도 지울 수도 없다.
_DELETE_INTEGRITY_VIOLATIONS_SQL: Final[str] = f"""
DELETE FROM ops.data_integrity_violations AS violation
 WHERE violation.feature_id IN ({_TARGET_FEATURES_SQL})
    OR violation.provider_dataset_id IN ({_TARGET_DATASETS_SQL})
"""

#: 3b. 대상 Feature. 의존 행은 선언된 FK 동작이 처리한다.
_DELETE_TARGET_FEATURES_SQL: Final[str] = f"""
DELETE FROM feature.features AS feature
 WHERE {_TARGET_FEATURE_PREDICATE}
"""

#: 4. identity claim — soft reference(FK 없음)라 Feature 삭제가 따라오지 않는다.
_DELETE_IDENTITY_CLAIMS_SQL: Final[str] = f"""
DELETE FROM provider_sync.provider_feature_identities AS identity
 WHERE identity.provider_dataset_id IN ({_TARGET_DATASETS_SQL})
    OR identity.feature_kind = 'weather'
"""

#: 4. 남은 Feature(예: place)가 weather entity를 가리키던 link(``weather_context`` 등).
_DELETE_TARGET_SOURCE_LINKS_SQL: Final[str] = f"""
DELETE FROM provider_sync.source_links AS link
 WHERE link.source_entity_key IN ({_TARGET_ENTITIES_SQL})
"""

_DELETE_TARGET_ENRICHMENT_REVIEWS_SQL: Final[str] = f"""
DELETE FROM ops.enrichment_review_queue AS review
 WHERE review.source_entity_key IN ({_TARGET_ENTITIES_SQL})
"""

#: lineage state는 ``fk_notice_lineage_states_scope ON DELETE CASCADE``로 함께 간다.
_DELETE_TARGET_NOTICE_SCOPES_SQL: Final[str] = f"""
DELETE FROM provider_sync.notice_lifecycle_scopes AS scope
 WHERE scope.provider_dataset_id IN ({_TARGET_DATASETS_SQL})
"""

_DELETE_TARGET_SOURCE_HEADS_SQL: Final[str] = f"""
DELETE FROM provider_sync.source_entity_heads AS head
 WHERE head.source_entity_key IN ({_TARGET_ENTITIES_SQL})
"""

_DELETE_TARGET_SOURCE_RECORDS_SQL: Final[str] = f"""
DELETE FROM provider_sync.source_records AS record
 WHERE record.source_entity_key IN ({_TARGET_ENTITIES_SQL})
"""

_DELETE_TARGET_SOURCE_ENTITIES_SQL: Final[str] = f"""
DELETE FROM provider_sync.source_entities AS entity
 WHERE entity.provider_dataset_id IN ({_TARGET_DATASETS_SQL})
"""

#: 5. weather summary run 영수증. 종결 영수증은 불변이라 fence를 이 트랜잭션 안에서만 끈다.
_DISABLE_SUMMARY_RUN_FENCE_SQL: Final[str] = (
    f"ALTER TABLE ops.current_summary_runs DISABLE TRIGGER {_SUMMARY_RUN_FENCE}"
)
_DELETE_WEATHER_SUMMARY_RUNS_SQL: Final[str] = """
DELETE FROM ops.current_summary_runs AS run
 WHERE run.projection_kind = 'weather'
"""
_ENABLE_SUMMARY_RUN_FENCE_SQL: Final[str] = (
    f"ALTER TABLE ops.current_summary_runs ENABLE TRIGGER {_SUMMARY_RUN_FENCE}"
)
_NARROW_SUMMARY_PROJECTION_KIND_SQL: Final[str] = """
ALTER TABLE ops.current_summary_runs
    DROP CONSTRAINT ck_current_summary_runs_projection_kind,
    ADD CONSTRAINT ck_current_summary_runs_projection_kind CHECK (projection_kind = 'price')
"""

#: 6. 대상 dataset을 끈다. 카탈로그 행은 남는다(이력 FK).
_DEACTIVATE_TARGET_DATASETS_SQL: Final[str] = f"""
UPDATE provider_sync.provider_datasets AS dataset
   SET is_active = false
 WHERE dataset.provider_dataset_id IN ({_TARGET_DATASETS_SQL})
   AND dataset.is_active
"""

#: 7. receipt head 값 열거 CHECK — graph의 **모든** revision(401과 같은 계약).
_RECEIPT_HEAD_CHECK_SQL: Final[str] = """
ALTER TABLE ops.application_schema_operation_receipts
    DROP CONSTRAINT ck_application_schema_operation_receipts_head,
    ADD CONSTRAINT ck_application_schema_operation_receipts_head CHECK (destination_head IN ('300', '301_m03_import_children', '302_m03_child_issuance', '303_m05_payload_hash_domain', '304_m05_detector_manuals', '305_m05_relitigation_fence', '306_m02_manual_feature_purge', '307_m02_truncate_fence', '308_t39_provider_identities', '309_t39_feature_id_rekey', '310_seoul_source_move', '311_seal_member_digest', '312_route_geometry_sidecar', '313_single_service_role', '400', '401_retire_map_kma_refresh', '402_remove_map_weather_data'))
"""

#: 실행 순서대로의 upgrade 문장. 이 저장소 migration의 관례다 — lint 게이트가 이 tuple을
#: import해 실제로 실행되는 DDL을 읽는다.
_UPGRADE_STATEMENTS: Final[tuple[str, ...]] = (
    _REACTIVATE_FOR_CLEANUP_SQL,
    _DISABLE_TARGET_OPERATIONS_SQL,
    _DROP_CURRENT_WEATHER_SUMMARY_SQL,
    _DROP_WEATHER_VALUES_SQL,
    _DROP_WEATHER_VALUE_FENCE_SQL,
    _DROP_WEATHER_COORD_INDEX_SQL,
    _DELETE_INTEGRITY_VIOLATIONS_SQL,
    _DELETE_TARGET_FEATURES_SQL,
    _DELETE_IDENTITY_CLAIMS_SQL,
    _DELETE_TARGET_SOURCE_LINKS_SQL,
    _DELETE_TARGET_ENRICHMENT_REVIEWS_SQL,
    _DELETE_TARGET_NOTICE_SCOPES_SQL,
    _DELETE_TARGET_SOURCE_HEADS_SQL,
    _DELETE_TARGET_SOURCE_RECORDS_SQL,
    _DELETE_TARGET_SOURCE_ENTITIES_SQL,
    _DISABLE_SUMMARY_RUN_FENCE_SQL,
    _DELETE_WEATHER_SUMMARY_RUNS_SQL,
    _ENABLE_SUMMARY_RUN_FENCE_SQL,
    _NARROW_SUMMARY_PROJECTION_KIND_SQL,
    _DEACTIVATE_TARGET_DATASETS_SQL,
    _RECEIPT_HEAD_CHECK_SQL,
)

# ---------------------------------------------------------------------------
# 사후 조건 — 하나라도 0이 아니면 중단한다(트랜잭션 전체가 되돌아간다).
# ---------------------------------------------------------------------------

_POSTCONDITIONS: Final[tuple[tuple[str, str], ...]] = (
    (
        "weather Feature",
        "SELECT count(*) FROM feature.features WHERE kind = 'weather'",
    ),
    (
        "target dataset identity claim",
        f"""
        SELECT count(*)
          FROM provider_sync.provider_feature_identities AS identity
         WHERE identity.provider_dataset_id IN ({_TARGET_DATASETS_SQL})
            OR identity.feature_kind = 'weather'
        """,
    ),
    (
        "target dataset source entity",
        f"SELECT count(*) FROM ({_TARGET_ENTITIES_SQL}) AS remaining",
    ),
    (
        "target dataset notice lifecycle scope",
        f"""
        SELECT count(*)
          FROM provider_sync.notice_lifecycle_scopes AS scope
         WHERE scope.provider_dataset_id IN ({_TARGET_DATASETS_SQL})
        """,
    ),
    (
        "enabled target operation",
        f"""
        SELECT count(*)
          FROM provider_sync.provider_dataset_operations AS operation
         WHERE operation.provider_dataset_id IN ({_TARGET_DATASETS_SQL})
           AND operation.is_enabled
        """,
    ),
    (
        "active target dataset",
        f"""
        SELECT count(*)
          FROM provider_sync.provider_datasets AS dataset_row
         WHERE dataset_row.provider_dataset_id IN ({_TARGET_DATASETS_SQL})
           AND dataset_row.is_active
        """,
    ),
    (
        "weather summary run",
        "SELECT count(*) FROM ops.current_summary_runs WHERE projection_kind = 'weather'",
    ),
    (
        "surviving weather-only object",
        """
        SELECT (to_regclass('feature.feature_weather_values') IS NOT NULL)::int
             + (to_regclass('feature.current_weather_summary') IS NOT NULL)::int
             + (to_regclass('feature.idx_features_public_weather_coord_5179_gist') IS NOT NULL)::int
             + (to_regprocedure('feature.reject_weather_value_mutation()') IS NOT NULL)::int
        """,
    ),
)


def _fence_mode(bind: Connection) -> str:
    return str(bind.execute(text(_SUMMARY_RUN_FENCE_MODE_SQL)).scalar_one())


def upgrade() -> None:
    """막는 것이 없음을 확인하고, 지우고, 남은 것이 없는지 잰다."""
    bind = op.get_bind()

    blocked: list[str] = []
    for label, statement in _PREFLIGHT_BLOCKERS:
        rows = [str(value) for value in bind.execute(text(statement)).scalars()]
        if rows:
            blocked.append(f"{label}: {rows!r}")
    if blocked:
        raise RuntimeError(
            "402: weather 제거를 막는 행이 있다 — 아무것도 바꾸지 않았다:\n  "
            + "\n  ".join(blocked)
        )

    # ``ENABLE TRIGGER``는 기본 모드('O')로 되돌린다. 다른 모드였다면 되돌린 결과가
    # 원래와 달라지므로 손대기 전에 멈춘다.
    before = _fence_mode(bind)
    if before != "O":
        raise RuntimeError(
            f"402: {_SUMMARY_RUN_FENCE} 모드가 {before!r}다 — 'O'(기본)에서만 끄고 되돌린다"
        )

    for statement in _UPGRADE_STATEMENTS:
        bind.execute(text(statement))

    after = _fence_mode(bind)
    if after != before:
        raise RuntimeError(
            f"402: {_SUMMARY_RUN_FENCE}를 원래 모드로 되돌리지 못했다: {before!r} -> {after!r}"
        )

    remaining = [
        f"{label}={count}"
        for label, statement in _POSTCONDITIONS
        if (count := int(bind.execute(text(statement)).scalar_one())) != 0
    ]
    if remaining:
        raise RuntimeError(f"402: weather 제거 뒤에 남은 것이 있다: {remaining}")


def downgrade() -> None:
    """되돌리지 않는다 — 지운 데이터는 되살릴 수 없다."""
    raise RuntimeError(
        "402_remove_map_weather_data is forward-only: Map은 weather 기능을 갖지 않는다(ADR-105)."
    )
