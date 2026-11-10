"""축제 원천을 TourAPI로 바꾼다 — 표준데이터 축제·TourAPI 축제 보강을 퇴역하고 TourAPI 축제를 넣는다.

Revision ID: 449_tourapi_festivals_primary
Revises: 448_mcst_theme_transition

왜 필요한가. 2026-11-10 소유자 결정: "datagokr 축제데이터는 로드 끄고 다른 소스 쓰자", 이어
"datagokr 축제 소스는 아예 쓰지마". data.go.kr 전국문화축제표준데이터(``tn_pubr_public_cltur_fstvl_api``)
키는 403 ``SERVICE_KEY_IS_NOT_REGISTERED_ERROR``이고 마지막 성공은 2026-10-31이다. 축제는 이제
TourAPI(KorService2 ``searchFestival2``, contentTypeId 15)가 **유일한 원천**이고 그 적재는 1차
event Feature를 만든다(``docs/etl/event-feature-etl.md``). 코드에서는 표준데이터 축제의 asset·job·
schedule·큐 runner spec·handler binding·preview fixture·변환기와, TourAPI 축제를 표준데이터 축제에
이름으로 잇던 enrichment(asset·job·매처·검토 분류)를 걷어냈다. **실행 가능 집합의 정본은 DB
카탈로그다**(T-VN-33, ADR-088) — 그래서 여기서 그 operation을 끄고 새 operation을 넣는다(419와
같은 이유).

대상은 이름이 아니라 **정체성**으로 고른다 — 퇴역 dataset 둘(:data:`RETIRED_DATASETS`)의 행이
정확히 둘이 아니면 멈춘다.

무엇을 하는가(실행 순서 = :func:`upgrade`)
------------------------------------------

0. 스키마 소유자 롤로 연다.
1. ADR-115 scoped write 프로토콜 gate(배타, ``lock_timeout`` 30초)를 **먼저**, 그다음 member 표 둘
   (``ops.import_job_datasets``·``ops.feature_update_request_datasets``)을 ``SHARE``로 잠근다(5초) —
   419와 같은 순서·같은 이유(gate → member 표, member INSERT가 꺼진 operation을 보고 거부되게).
   카탈로그 모양 검사(퇴역 dataset 둘·새 dataset 부재)는 잠금 전에, job·link·override preflight는
   잠금을 쥔 **뒤에** 잰다.
2. 퇴역 dataset 둘의 operation을 **종류 불문**(``refresh``·``preview``) 끈다. 행은 지우지 않는다(이력 FK).
3. 표준데이터 축제 dataset에 ``primary`` link로 묶인 ``active`` Feature를 **퇴역**한다 —
   ``feature.transition_feature_state``를 ``transition_kind = 'system'``으로(419와 같다: 결과는
   ``retired``·``suppressed``, 프로시저가 재활성화를 막는 lifecycle override를 함께 쓴다). 2026-11-10
   prod 1,296건(그중 1,245건은 이미 끝난 행사, 240건은 좌표 없음). **병합하지 않는다** — 소유자
   결정이 "그 원천을 쓰지 않는다"이므로 표준데이터 행의 값(본문·주관기관)을 TourAPI Feature로
   옮기지도 않는다. TourAPI 쪽 같은 축제는 새 적재가 자기 Feature로 만든다(2026-11-10 실측: 이름이
   맞는 행 314/1,296).
4. TourAPI 축제 보강 검토 큐(``ops.enrichment_review_queue``) 중 퇴역 보강 dataset 원천의 ``pending``
   행을 ``ignored``로 닫는다 — 대상 Feature가 퇴역해 판정할 것이 없다(dataset을 끄면 그 표 쓰기가
   막혀 영영 닫을 수 없게 된다).
5. TourAPI 축제 dataset(``python-visitkorea-api`` / ``visitkorea_festivals``, ``openapi``, 활성,
   ``produces: ["event"]``)과 ``refresh`` operation ``feature_event_visitkorea_festivals_job``·fixture
   ``preview``·``dataset_wide`` scope를 넣는다(441과 같은 모양).
6. 퇴역 dataset 둘을 ``is_active = false``로 내린다(402·404와 같다 — 카탈로그 행은 이력 FK라 남긴다).
   **물리 삭제 revision은 먼저 두 dataset을 그 트랜잭션 안에서 다시 켜야 한다**(402 0단계와 같다) —
   활성 가드가 lineage DELETE도 막는다.
   **3·4가 먼저다** — 퇴역 전이의 근거 잠금(``lock_current_provider_source_evidence``)과 검토 큐 쓰기
   가드가 활성 dataset을 요구한다. 이 뒤로는 그 lineage에 쓰기가 막힌다(되살리는 것은 새 결정이다).
7. receipt head CHECK에 이 revision을 더한다(``lock_timeout`` 1초).

**남기는 것(이력)**: Feature 행·source entity/record/head/link·상태 전이 감사·검토 큐 행은 지우지
않는다. 물리 삭제는 관찰 기간 뒤 별도 revision이다(402 모양).

**PinVi 참조**(2026-11-10 PinVi DB 읽기 전용 실측, feature_id 1,296개 대조): ``trip_day_pois`` 45행
(feature 32개)은 전부 고정 시험 계정 한 명의 **삭제·보관된** 여행 41건이고, ``curated_plan_pois``는
0행, ``weather_location_links`` 33행은 feature→날씨 지점 캐시다. 살아 있는 사용자 참조가 0이라 M05
``rebind``/``detach`` 사건을 남기지 않는다 — 퇴역 id는 PinVi에서 지금처럼 ``retired``(batch)/404(단건)
+ ``feature_snapshot`` 대체 표시가 된다.

**seal**: 상태 전이는 그 Feature에 link가 있는 **모든** dataset의 curation 입력을 바꾼다. 대상 Feature에
퇴역 dataset 둘 밖의 link(역할 무관)가 있으면 멈춘다(2026-11-10 prod 0건 — link는 표준데이터
``primary`` 1,296과 TourAPI 보강 ``enrichment`` 212뿐이다). 퇴역 dataset은 다시 적재되지 않는다.

**트랜잭션**: 419와 달리 앞선 revision(prod는 446~448과 함께 오른다)과 같은 트랜잭션을 거부하지 않는다 —
전이는 약 1,300 호출이다. 419는 약 1.4만 호출을 수 분에 돌았으므로 이것은 수십 초 안쪽으로 본다
(실측 아님 — 배포 로그로 확인한다).

막는 것(preflight, 하나라도 있으면 아무것도 바꾸지 않고 중단)
--------------------------------------------------------------

- 퇴역 dataset 행이 둘이 아니다 / TourAPI 축제 dataset이 이미 있다(일부만 적용된 DB).
- 퇴역 dataset operation을 member로 둔 queued/running job(operation이 꺼지면 그 job은 종결로 갈 수 없다).
- 대상 Feature가 퇴역 dataset 밖에도 link를 가진다 / 대상 Feature에 활성 lifecycle override가 있다.

사후 조건: 퇴역 dataset에 켜진 operation·``active`` Feature·활성 dataset이 남거나, 퇴역 전이 수가 대상
수와 다르거나, 끄는 동안 대상 job이 생기면 중단한다.

forward-only. downgrade는 두지 않는다(ADR-021) — 표준데이터 축제를 되살리는 것은 새 결정이다.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Final

from sqlalchemy import text

from alembic import op

# ruff: noqa: E501

revision: str = "449_tourapi_festivals_primary"
down_revision: str | Sequence[str] | None = "448_mcst_theme_transition"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: migration은 import 시점 앱 코드에 기대지 않으므로 값을 여기 둔다.
STANDARD_PROVIDER: Final[str] = "data.go.kr-standard"
STANDARD_FESTIVAL_DATASET_KEY: Final[str] = "datagokr_cultural_festivals"
VISITKOREA_PROVIDER: Final[str] = "python-visitkorea-api"
LEGACY_ENRICHMENT_DATASET_KEY: Final[str] = "visitkorea_festival_events"

#: 퇴역 dataset — (provider, dataset_key). 이 둘이 카탈로그에 정확히 있어야 한다.
RETIRED_DATASETS: Final[tuple[tuple[str, str], ...]] = (
    (STANDARD_PROVIDER, STANDARD_FESTIVAL_DATASET_KEY),
    (VISITKOREA_PROVIDER, LEGACY_ENRICHMENT_DATASET_KEY),
)

#: 새 1차 축제 dataset (``kortravelmap.providers.visitkorea.DATASET_KEY_VISITKOREA_FESTIVALS``와 같은 값).
FESTIVAL_DATASET_KEY: Final[str] = "visitkorea_festivals"
FESTIVAL_DISPLAY_NAME: Final[str] = "TourAPI 축제·공연·행사(국문 관광정보 서비스, contentTypeId 15)"
FESTIVAL_OPERATION_KEY: Final[str] = "feature_event_visitkorea_festivals_job"

#: 퇴역 전이의 감사 문맥. ``prepare_feature_state_context``가 받는 키만 쓴다. 값에 콜론을 넣지 않는다.
RETIRE_REASON_CODE: Final[str] = "festival_source_moved_to_tourapi"
RETIRE_PRINCIPAL: Final[str] = "system/alembic-449_tourapi_festivals_primary"
RETIRE_CAUSATION_REF: Final[str] = "owner decision 2026-11-10 festival source"

#: 검토 큐를 닫는 사유(``ops.enrichment_review_queue.decision_reason``).
REVIEW_CLOSE_REASON: Final[str] = "festival_source_moved_to_tourapi"
REVIEW_CLOSE_ACTOR: Final[str] = "system/alembic-449"

PROTOCOL_LOCK_TIMEOUT_MS: Final[int] = 30000
MEMBER_LOCK_TIMEOUT_MS: Final[int] = 5000
RETIRE_LOCK_TIMEOUT_MS: Final[int] = 60000
DDL_LOCK_TIMEOUT_MS: Final[int] = 1000

_RETIRED_DATASETS_SQL: Final[str] = f"""
SELECT dataset.provider_dataset_id
  FROM provider_sync.provider_datasets AS dataset
 WHERE (dataset.provider, dataset.dataset_key) IN (
       ('{STANDARD_PROVIDER}', '{STANDARD_FESTIVAL_DATASET_KEY}'),
       ('{VISITKOREA_PROVIDER}', '{LEGACY_ENRICHMENT_DATASET_KEY}'))
"""

_STANDARD_FESTIVAL_DATASET_SQL: Final[str] = f"""
SELECT dataset.provider_dataset_id
  FROM provider_sync.provider_datasets AS dataset
 WHERE dataset.provider = '{STANDARD_PROVIDER}'
   AND dataset.dataset_key = '{STANDARD_FESTIVAL_DATASET_KEY}'
"""

_LEGACY_ENRICHMENT_DATASET_SQL: Final[str] = f"""
SELECT dataset.provider_dataset_id
  FROM provider_sync.provider_datasets AS dataset
 WHERE dataset.provider = '{VISITKOREA_PROVIDER}'
   AND dataset.dataset_key = '{LEGACY_ENRICHMENT_DATASET_KEY}'
"""

_FESTIVAL_DATASET_SQL: Final[str] = f"""
SELECT dataset.provider_dataset_id
  FROM provider_sync.provider_datasets AS dataset
 WHERE dataset.provider = '{VISITKOREA_PROVIDER}' AND dataset.dataset_key = '{FESTIVAL_DATASET_KEY}'
"""

_TARGET_FEATURES_SQL: Final[str] = f"""
SELECT DISTINCT core.feature_id
  FROM feature.features AS core
  JOIN provider_sync.source_links AS link
    ON link.feature_id = core.feature_id
   AND link.source_role = 'primary'
  JOIN provider_sync.source_entities AS entity
    ON entity.source_entity_key = link.source_entity_key
 WHERE entity.provider_dataset_id IN ({_STANDARD_FESTIVAL_DATASET_SQL})
   AND core.lifecycle_state = 'active'
"""

_SET_OWNER_ROLE_SQL: Final[str] = "SET ROLE ktm_feature_schema_owner"
_SET_STATE_PROCEDURE_OWNER_ROLE_SQL: Final[str] = "SET ROLE ktm_feature_state_procedure_owner"
_LOCK_WRITE_PROTOCOL_SQL: Final[str] = "SELECT ops.lock_scoped_feature_write_protocol(true)"
_LOCK_MEMBER_TABLES_SQL: Final[str] = (
    "LOCK TABLE ops.import_job_datasets, ops.feature_update_request_datasets IN SHARE MODE"
)

_DISABLE_RETIRED_OPERATIONS_SQL: Final[str] = f"""
UPDATE provider_sync.provider_dataset_operations AS operation
   SET is_enabled = false
 WHERE operation.provider_dataset_id IN ({_RETIRED_DATASETS_SQL})
   AND operation.is_enabled
"""

_RETIRE_TARGET_FEATURES_SQL: Final[str] = f"""
DO $retire$
DECLARE
    v_target record;
    v_out_feature_id uuid;
    v_out_row_revision bigint;
BEGIN
    FOR v_target IN
        SELECT core.feature_id, core.row_revision, core.quality_state
          FROM feature.features AS core
         WHERE core.feature_id IN ({_TARGET_FEATURES_SQL})
         ORDER BY core.feature_id
    LOOP
        CALL feature.transition_feature_state(
            v_target.feature_id,
            'retired',
            'suppressed',
            v_target.quality_state,
            v_target.row_revision,
            jsonb_build_object(
                'transition_kind', 'system',
                'reason_code', '{RETIRE_REASON_CODE}',
                'principal', '{RETIRE_PRINCIPAL}',
                'causation_ref', '{RETIRE_CAUSATION_REF}'
            ),
            v_out_feature_id,
            v_out_row_revision
        );
    END LOOP;
END
$retire$
"""

#: 프로시저가 남긴 상태 문맥을 비운다(419와 같다).
_CLEAR_STATE_CONTEXT_SQL: Final[str] = """
SELECT set_config('feature.state_transition_context', '', true),
       set_config('feature.state_procedure_definer', '', true)
"""

_CLOSE_PENDING_REVIEWS_SQL: Final[str] = f"""
UPDATE ops.enrichment_review_queue AS review
   SET status = 'ignored',
       decision_reason = '{REVIEW_CLOSE_REASON}',
       reviewed_by = '{REVIEW_CLOSE_ACTOR}',
       reviewed_at = now()
  FROM provider_sync.source_entities AS entity
 WHERE entity.source_entity_key = review.source_entity_key
   AND entity.provider_dataset_id IN ({_LEGACY_ENRICHMENT_DATASET_SQL})
   AND review.status = 'pending'
"""

_INSERT_FESTIVAL_DATASET_SQL: Final[str] = (
    "INSERT INTO provider_sync.provider_datasets (provider, dataset_key, display_name, source_kind, is_active, capabilities) VALUES "
    f"('{VISITKOREA_PROVIDER}', '{FESTIVAL_DATASET_KEY}', '{FESTIVAL_DISPLAY_NAME}', 'openapi', true, "
    """'{"produces": ["event"], "extensions": {}, "schema_version": 1}'::jsonb)"""
)

_INSERT_FESTIVAL_OPERATIONS_SQL: Final[str] = f"""
INSERT INTO provider_sync.provider_dataset_operations (provider_dataset_id, operation_key, operation_kind, is_enabled, config)
SELECT dataset.provider_dataset_id, '{FESTIVAL_OPERATION_KEY}', 'refresh', true, '{{}}'::jsonb
  FROM ({_FESTIVAL_DATASET_SQL}) AS dataset
UNION ALL
SELECT dataset.provider_dataset_id, '{FESTIVAL_OPERATION_KEY}.preview', 'preview', true, '{{"handler": "fixture"}}'::jsonb
  FROM ({_FESTIVAL_DATASET_SQL}) AS dataset
"""

_INSERT_FESTIVAL_OPERATION_SCOPES_SQL: Final[str] = f"""
INSERT INTO provider_sync.provider_dataset_operation_scopes (provider_dataset_id, sync_scope, operation_key, operation_kind)
SELECT dataset.provider_dataset_id, 'dataset_wide', '{FESTIVAL_OPERATION_KEY}', 'refresh'
  FROM ({_FESTIVAL_DATASET_SQL}) AS dataset
"""

_DEACTIVATE_RETIRED_DATASETS_SQL: Final[str] = f"""
UPDATE provider_sync.provider_datasets AS dataset
   SET is_active = false
 WHERE dataset.provider_dataset_id IN ({_RETIRED_DATASETS_SQL})
   AND dataset.is_active
"""

#: receipt head 값 열거 CHECK — graph의 **모든** revision(401과 같은 계약).
_RECEIPT_HEAD_CHECK_SQL: Final[str] = """
ALTER TABLE ops.application_schema_operation_receipts
    DROP CONSTRAINT ck_application_schema_operation_receipts_head,
    ADD CONSTRAINT ck_application_schema_operation_receipts_head CHECK(destination_head IN (
        '300',
        '301_m03_import_children',
        '302_m03_child_issuance',
        '303_m05_payload_hash_domain',
        '304_m05_detector_manuals',
        '305_m05_relitigation_fence',
        '306_m02_manual_feature_purge',
        '307_m02_truncate_fence',
        '308_t39_provider_identities',
        '309_t39_feature_id_rekey',
        '310_seoul_source_move',
        '311_seal_member_digest',
        '312_route_geometry_sidecar',
        '313_single_service_role',
        '400',
        '401_retire_map_kma_refresh',
        '402_remove_map_weather_data',
        '403_drop_kma_notice_lineage',
        '404_transport_provider_identity',
        '405_mois_freshness_sla',
        '406_feature_write_gate',
        '407_feature_geocode_stamps',
        '408_kor_travel_geo_releases',
        '409_geo_release_item_reasons',
        '410_provider_field_shadow',
        '411_scoped_feature_write_kernel',
        '412_provider_scalar_projection',
        '413_legacy_sql_protocol_entry',
        '414_manual_dedup_protocol',
        '415_state_lifecycle_protocol',
        '416_field_override_protocol',
        '417_protocol_ex_reentry',
        '418_creation_protocol',
        '419_retire_pg_transport_values',
        '420_exclusive_provider_refresh',
        '421_stamp_writer_boundary',
        '422_heritage_evidence_reader',
        '423_exclusive_context_select',
        '424_tracking_protocol_prefix',
        '425_provider_base_update_first',
        '426_provider_patch_protocol',
        '427_transport_airport_reader',
        '428_bounded_curation_capture',
        '429_strict_sh_data_guards',
        '430_provider_snapshot_recovery',
        '431_transport_rest_reader',
        '432_rest_snapshot_atomic',
        '433_snapshot_ready_plan_reset',
        '434_protocol_entry_narrowing',
        '435_retire_sh_snapshot_path',
        '436_feature_search_aliases',
        '437_feature_command_fingerprints',
        '438_transport_reference_places',
        '439_traditional_market_dataset',
        '441_tourapi_attraction_dataset',
        '442_mois_brand_search_aliases',
        '444_trip_search_aliases',
        '446_mcst_place_attributes',
        '447_admin_search_trgm_indexes',
        '448_mcst_theme_transition',
        '449_tourapi_festivals_primary'
    ))
"""

# ---------------------------------------------------------------------------
# preflight / postcondition
# ---------------------------------------------------------------------------

_IN_FLIGHT_TARGET_JOBS_SQL: Final[str] = f"""
SELECT in_flight.job_id
  FROM (
      SELECT job.job_id::text AS job_id
        FROM ops.import_jobs AS job
        JOIN ops.import_job_datasets AS member
          ON member.job_id = job.job_id
       WHERE job.status IN ('queued', 'running')
         AND member.provider_dataset_id IN ({_RETIRED_DATASETS_SQL})
      UNION
      SELECT job.job_id::text AS job_id
        FROM ops.feature_update_request_datasets AS member
        JOIN ops.feature_update_requests AS request
          ON request.request_id = member.request_id
        JOIN ops.import_jobs AS job
          ON job.job_id = request.job_id
       WHERE job.status IN ('queued', 'running')
         AND member.provider_dataset_id IN ({_RETIRED_DATASETS_SQL})
  ) AS in_flight
 ORDER BY in_flight.job_id
 LIMIT 10
"""

_SHARED_SOURCE_FEATURES_SQL: Final[str] = f"""
SELECT DISTINCT link.feature_id::text || ' <- ' || link.source_role || ' ' || dataset.provider || '/' || dataset.dataset_key
  FROM provider_sync.source_links AS link
  JOIN provider_sync.source_entities AS entity
    ON entity.source_entity_key = link.source_entity_key
  JOIN provider_sync.provider_datasets AS dataset
    ON dataset.provider_dataset_id = entity.provider_dataset_id
 WHERE link.feature_id IN ({_TARGET_FEATURES_SQL})
   AND entity.provider_dataset_id NOT IN ({_RETIRED_DATASETS_SQL})
 ORDER BY 1
 LIMIT 10
"""

_LIFECYCLE_OVERRIDDEN_FEATURES_SQL: Final[str] = f"""
SELECT override.feature_id::text
  FROM ops.feature_overrides AS override
 WHERE override.field_path = 'lifecycle_state'
   AND override.status = 'active'
   AND override.feature_id IN ({_TARGET_FEATURES_SQL})
 ORDER BY 1
 LIMIT 10
"""

_COUNT_RETIRED_DATASETS_SQL: Final[str] = f"SELECT count(*) FROM ({_RETIRED_DATASETS_SQL}) AS target"
_COUNT_FESTIVAL_DATASET_SQL: Final[str] = f"SELECT count(*) FROM ({_FESTIVAL_DATASET_SQL}) AS target"
_COUNT_TARGET_FEATURES_SQL: Final[str] = f"SELECT count(*) FROM ({_TARGET_FEATURES_SQL}) AS target"

_COUNT_RETIRED_BY_THIS_REVISION_SQL: Final[str] = f"""
SELECT count(*)
  FROM feature.feature_state_transitions AS transition
 WHERE transition.to_lifecycle_state = 'retired'
   AND transition.transition_kind = 'system'
   AND transition.reason_code = '{RETIRE_REASON_CODE}'
   AND transition.principal = '{RETIRE_PRINCIPAL}'
"""

_REMAINING_SQL: Final[str] = f"""
SELECT 'enabled_operation' AS kind, operation.operation_key AS name
  FROM provider_sync.provider_dataset_operations AS operation
 WHERE operation.provider_dataset_id IN ({_RETIRED_DATASETS_SQL})
   AND operation.is_enabled
UNION ALL
SELECT 'active_dataset', dataset.dataset_key
  FROM provider_sync.provider_datasets AS dataset
 WHERE dataset.provider_dataset_id IN ({_RETIRED_DATASETS_SQL})
   AND dataset.is_active
UNION ALL
SELECT 'active_feature', target.feature_id::text
  FROM ({_TARGET_FEATURES_SQL}) AS target
 LIMIT 10
"""


_UPGRADE_STATEMENTS: Final[tuple[str, ...]] = (
    _SET_OWNER_ROLE_SQL,
    _LOCK_WRITE_PROTOCOL_SQL,
    _LOCK_MEMBER_TABLES_SQL,
    _DISABLE_RETIRED_OPERATIONS_SQL,
    _SET_STATE_PROCEDURE_OWNER_ROLE_SQL,
    _RETIRE_TARGET_FEATURES_SQL,
    _SET_OWNER_ROLE_SQL,
    _CLEAR_STATE_CONTEXT_SQL,
    _CLOSE_PENDING_REVIEWS_SQL,
    _INSERT_FESTIVAL_DATASET_SQL,
    _INSERT_FESTIVAL_OPERATIONS_SQL,
    _INSERT_FESTIVAL_OPERATION_SCOPES_SQL,
    _DEACTIVATE_RETIRED_DATASETS_SQL,
    _RECEIPT_HEAD_CHECK_SQL,
)
"""실행 순서대로의 upgrade 문장(사이의 검사·timeout 조정은 :func:`upgrade`). 소유자 롤로 열고 같은 롤로
끝난다 — 프로시저 소유자 창은 퇴역 루프 하나뿐이다(419와 같다)."""


def _set_local(bind: object, name: str, value: str) -> None:
    bind.execute(text("SELECT set_config(:name, :value, true)"), {"name": name, "value": value})  # type: ignore[attr-defined]


def _scalars(bind: object, sql: str) -> list[str]:
    return [str(value) for value in bind.execute(text(sql)).scalars()]  # type: ignore[attr-defined]


def _count(bind: object, sql: str) -> int:
    return int(bind.execute(text(sql)).scalar_one())  # type: ignore[attr-defined]


def upgrade() -> None:
    """preflight를 통과하면 옛 축제 적재를 끄고, 그 Feature를 퇴역하고, TourAPI 축제를 넣는다."""
    bind = op.get_bind()
    (
        set_owner,
        lock_protocol,
        lock_members,
        disable_operations,
        set_state_owner,
        retire,
        restore_owner,
        clear_context,
        close_reviews,
        insert_dataset,
        insert_operations,
        insert_scopes,
        deactivate_datasets,
        receipt_check,
    ) = _UPGRADE_STATEMENTS
    bind.execute(text(set_owner))
    prior = dict(
        bind.execute(
            text("SELECT name, setting FROM pg_settings WHERE name IN ('lock_timeout', 'statement_timeout')")
        ).all()
    )

    retired_datasets = _count(bind, _COUNT_RETIRED_DATASETS_SQL)
    if retired_datasets != len(RETIRED_DATASETS):
        raise RuntimeError(
            f"449: 아무것도 바꾸지 않았다 — 퇴역 dataset이 {retired_datasets}개다"
            f"(기대 {len(RETIRED_DATASETS)}: {RETIRED_DATASETS!r})."
        )
    if _count(bind, _COUNT_FESTIVAL_DATASET_SQL):
        raise RuntimeError(
            f"449: 아무것도 바꾸지 않았다 — {VISITKOREA_PROVIDER}/{FESTIVAL_DATASET_KEY}가 이미 있다"
            " — 일부만 적용된 DB다. 사람이 확인한 뒤 다시 돌린다."
        )

    _set_local(bind, "lock_timeout", str(PROTOCOL_LOCK_TIMEOUT_MS))
    bind.execute(text(lock_protocol))
    _set_local(bind, "lock_timeout", str(MEMBER_LOCK_TIMEOUT_MS))
    bind.execute(text(lock_members))

    expected = _count(bind, _COUNT_TARGET_FEATURES_SQL)
    blockers: list[str] = []
    in_flight = _scalars(bind, _IN_FLIGHT_TARGET_JOBS_SQL)
    if in_flight:
        blockers.append(
            "queued/running job on a retired festival operation — wait for it to finish: "
            f"{in_flight!r}"
        )
    shared = _scalars(bind, _SHARED_SOURCE_FEATURES_SQL)
    if shared:
        blockers.append(f"target Feature also has a source link outside the retired datasets: {shared!r}")
    overridden = _scalars(bind, _LIFECYCLE_OVERRIDDEN_FEATURES_SQL)
    if overridden:
        blockers.append(f"target Feature has an active lifecycle override: {overridden!r}")
    if blockers:
        raise RuntimeError("449: 아무것도 바꾸지 않았다 — " + "; ".join(blockers))

    bind.execute(text(disable_operations))
    _set_local(bind, "statement_timeout", "0")
    _set_local(bind, "lock_timeout", str(RETIRE_LOCK_TIMEOUT_MS))
    bind.execute(text(set_state_owner))
    bind.execute(text(retire))
    bind.execute(text(restore_owner))
    bind.execute(text(clear_context))
    bind.execute(text(close_reviews))
    bind.execute(text(insert_dataset))
    bind.execute(text(insert_operations))
    bind.execute(text(insert_scopes))
    bind.execute(text(deactivate_datasets))
    _set_local(bind, "statement_timeout", str(prior["statement_timeout"]))
    _set_local(bind, "lock_timeout", str(DDL_LOCK_TIMEOUT_MS))
    bind.execute(text(receipt_check))
    for name, value in prior.items():
        _set_local(bind, name, str(value))

    remaining = [f"{kind}:{name}" for kind, name in bind.execute(text(_REMAINING_SQL)).all()]
    if remaining:
        raise RuntimeError(f"449: 대상이 남았다: {remaining!r}")
    retired = _count(bind, _COUNT_RETIRED_BY_THIS_REVISION_SQL)
    if retired != expected:
        raise RuntimeError(f"449: 퇴역 전이 수가 대상 수와 다르다: retired={retired}, expected={expected}")
    late = _scalars(bind, _IN_FLIGHT_TARGET_JOBS_SQL)
    if late:
        raise RuntimeError(f"449: 끄는 동안 대상 operation job이 생겼다: {late!r}")


def downgrade() -> None:
    """되돌리지 않는다 — 표준데이터 축제를 되살리는 것은 새 결정이다."""
    raise RuntimeError(
        "449_tourapi_festivals_primary is forward-only: 축제 원천은 TourAPI다(2026-11-10 소유자 결정)."
    )
