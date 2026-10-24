"""PG transport 유가·돌발 적재를 닫고 그 Feature를 퇴역(soft-delete)한다(ADR-114 결정 7, 1단계).

Revision ID: 417_retire_pg_transport_values
Revises: 416_field_override_protocol

왜 필요한가. ADR-114로 transport의 **현재 상태**(주유소·휴게소 유가, 고속도로 돌발 활성 집합 등)는
Map Valkey 세대(`transport_state_*` job, `/v1/service/transport/*`)가 들고, PinVi는 그 REST로
교통 레이어를 읽는다(2026-10-24 prod: Valkey 다섯 데이터셋 모두 `loaded=true`·`stale=false`,
PinVi `PINVI_KOR_TRAVEL_MAP_TRANSPORT_ENABLED` 켜짐). 소유자 결정은 "과거 데이터는 Map에 남기지
않는다"이다 — 그런데 PG 유가 적재는 가격이 그대로여도 주유소 전부에 새 가격 fact를 쌓고, PG 돌발
적재는 10분마다 source record를 쌓는다. 코드에서는 유가 둘·돌발 하나의 Dagster asset·job·
schedule·큐 runner spec·handler binding·preview fixture를 걷어냈다. **실행 가능 집합의 정본은 DB
카탈로그다**(T-VN-33, ADR-088) — 그래서 여기서 그 operation을 끈다(401과 같은 이유).

1단계 범위 — **시간에 민감한 값만**. 적재가 멈춘 뒤에도 남겨 두면 틀린 값을 보여 주는 것:

- 유가 price Feature(주유소·휴게소 주유소). 지도 API는 오래된 관측도 날짜와 함께 그린다.
- 돌발 notice Feature. 원천 종료 시각이 없는 활성 돌발(2026-10-24 prod 320건)은 다음 적재가
  닫아 주지 않으면 **영원히 진행 중**으로 보인다.

장소(주유소·휴게소·공항 place)는 **이 revision이 건드리지 않는다** — 적재도 계속 돈다. 아직 그것에
기대는 소비자가 있다: PinVi 일반 지도·검색·근처(`/v1/features/{in-bounds,search,nearby}`)가 이
장소를 돌려주고(Valkey 표면에는 이름 검색이 없다), C7 운영 게이트가 공항 job을 "외부 호출 0"의
안전한 schedule·갱신 요청 대상으로 쓴다. 장소 퇴역과 물리 삭제는 ADR-114 결정 7의 다음 단계다.

대상은 이름이 아니라 **정체성**으로 고른다(401·402와 같다 — 이름을 나열하면 빠진 것이 조용히 남는다).

- 대상 dataset = provider ``kor-travel-transport`` 이고 ``capabilities -> 'produces'`` 에 ``price``
  또는 ``notice`` 가 있는 것. 그 집합이 :data:`EXPECTED_TARGET_DATASET_KEYS` 셋과 **정확히** 같지
  않으면 멈춘다(fail closed — 카탈로그가 이 revision이 잰 것과 다르다).
- 대상 Feature = 대상 dataset의 source entity에 ``primary`` link로 묶인 ``active`` Feature.
- 옛 provider(``python-opinet-api``·``python-krex-api``, 404가 비활성화)의 price·notice dataset에
  아직 ``active`` Feature가 묶여 있으면 멈춘다. 404 preflight가 그 dataset에서 새 dataset으로 옮길
  것이 없음을 확인했고(2026-10-02 prod 0행) 그 뒤로는 비활성이라 쓰기가 막혀 있다 — 남아 있다면 이
  revision이 모르는 상태이므로 퇴역 대상에 몰래 넣지 않고 사람이 본다.

무엇을 하는가(실행 순서 = ``_UPGRADE_STATEMENTS``, 사이의 검사는 :func:`upgrade`)
-----------------------------------------------------------------------------------

0. 함수 소유자 롤 창을 연다(404와 같다).
1. **같은 트랜잭션 거부**(아래 "트랜잭션"). 퇴역할 Feature가 있는데 이 트랜잭션에서 앞선 revision이
   이미 적용됐으면(``alembic_version`` 행이 이 트랜잭션에서 쓰였으면) 멈춘다.
1a. ADR-115 scoped write 프로토콜 gate(``ops.lock_scoped_feature_write_protocol(true)``, 배타)를 **먼저**
   잡는다(``lock_timeout`` 30초). ``transition_feature_state``가 415부터 루프마다 같은 gate를 배타로 잡는다 — 그
   첫 획득이 member 표 잠금 **뒤**에 오면, gate 공유 몫을 쥔 채 member를 쓰려는 writer와 교착할 수 있다. 그래서
   gate → member 표 순서로 잡는다. gate는 다른 Map Feature 쓰기와 상호 배제이므로, 돌고 있는 적재가 있으면 30초 안에
   얻지 못해 아무것도 바꾸지 않고 실패한다(runbook: 큐 sensor 정지·진행 중 run 종료 뒤 배포). 이 코드는 gate를 정의하지
   않고 부르기만 한다(ADR-115 소유).
2. member 표 둘(``ops.import_job_datasets``·``ops.feature_update_request_datasets``)을 ``SHARE`` 모드로
   잠근다(``lock_timeout`` 5초). member INSERT는 문장 시작에서 ``ROW EXCLUSIVE``를 잡아야 하므로 이
   트랜잭션이 끝날 때까지 **BEFORE 활성 가드보다 먼저** 기다리고, 끝난 뒤 가드
   (``reject_inactive_import_job_dataset_membership``·``…_feature_update_request_…``, plain SELECT로
   ``operation.is_enabled``를 읽는다)가 commit된 꺼진 operation을 보고 거부한다. 이미 미완인 member
   INSERT가 있으면 이 잠금을 5초 안에 얻지 못해 아무것도 바꾸지 않고 실패한다. 행 단위(FK 대상 scope
   행 ``FOR UPDATE``)로는 닫히지 않는다 — 가드가 FK 대기보다 먼저 돌아 켜진 operation을 보고 통과한
   INSERT가 FK에서 기다렸다가 commit 뒤 성공한다(2026-10-24 재리뷰). 대가: 이 트랜잭션 동안 **모든**
   dataset의 새 job member 쓰기가 기다린다(퇴역 수십 초~수 분 — runbook에 적는다). 그 잠금을 쥔 **뒤에**
   preflight를 잰다.
3. 대상 dataset의 operation을 **종류 불문**(``refresh``·``feature_load``·``preview``) **먼저** 끈다.
   행은 지우지 않는다 — ``import_job_datasets``·``feature_update_request_datasets``·
   ``provider_sync_state``가 exact FK로 가리키는 이력이다.
4. 대상 Feature를 **퇴역**한다 — ``feature.transition_feature_state``(감사·불변 trail이 있는 정본
   상태 전이)를 ``transition_kind = 'system'``으로 부른다. 결과는 ``lifecycle_state = 'retired'``·
   ``publication_state = 'suppressed'``이고, 프로시저가 같은 전이에 붙여 lifecycle override
   (``prevent_provider_reactivation = true``)를 쓴다 — provider 부재가 아니라 소유자 결정이므로
   provider tombstone(``provider_sync``)으로 위장하지 않고, 실수로 적재가 되살아나도 이 Feature가
   다시 켜지지 않는다. 프로시저 EXECUTE는 소유자(``ktm_feature_state_procedure_owner``)와 런타임
   그룹(``ktm_feature_runtime``)에게만 있고 스키마 소유자에게는 없으므로 소유자 롤로 잠시 바꿨다가(410과
   같은 창) 스키마 소유자 롤로 돌아온다 — ``RESET ROLE``이 아니다
   (``tests/lint/test_migrations_keep_the_schema_owner_role.py``). 프로시저는 advisory lock을 잡지
   않는다(행 잠금만) — 수만 건을 한 트랜잭션에서 돌려도 공유 lock table을 쓰지 않는다(ADR-111). 이
   블록만 ``statement_timeout = 0``·``lock_timeout`` 60초다(prod 약 1.4만 호출 — member 표 잠금을 쥔 채 행 잠금에서 무한히 서지 않게). 끝나면 프로시저가 남긴 상태 문맥 GUC
   (``feature.state_transition_context``·``feature.state_procedure_definer``)를 비운다 — 같은
   트랜잭션의 뒤 revision이 그 문맥으로 상태를 바꿀 수 없게.
5. receipt head CHECK에 이 revision을 더한다(401~416과 같은 계약). 이 ``ALTER TABLE``만
   ``lock_timeout`` 1초다(410과 같은 상한). 끝나면 두 timeout을 진입 값으로 되돌린다.

**dataset은 비활성화하지 않는다**(401과 같다 — 그것은 물리 삭제 단계의 일이다, 402·404). 활성 가드
(``reject_inactive_source_entity_dataset`` 등)는 비활성 dataset의 lineage를 지우는 DELETE까지 막으므로,
다음 단계가 지울 때 다시 켜야 한다. 그리고 notice 계보·가격 표시 같은 공용 라이브러리 경로가 이
dataset을 실제 카탈로그 행으로 쓰는 검사가 있다. operation이 꺼지면 큐·``/ops/datasets``의 갱신
capability·exact-set handler 대조에서 빠진다(활성 join은 ``operation.is_enabled``다).

**남기는 것(이력)**: Feature 행·source entity/record/head/link·가격 fact(``feature_price_values``·
``current_price_summary``)·notice 계보·상태 전이 감사·alias는 지우지 않는다. 물리 삭제는 비가역이라
관찰 기간 뒤 별도 revision(ADR-114 결정 7 다음 단계, 402와 같은 모양)으로 한다. 되돌리기는 admin
재활성화(``reactivation_evidence``)나 새 revision으로 한다 — transport 자체의 이력(transport 저장소)은
이 revision과 무관하다.

**seal**(ADR-114 기각 대안의 첫 함정 — "seal 직전이 아닌 곳에서 정리하면 seal 대조가 깨진다"). 상태
전이는 ``feature.current_provider_curation_input_set``의 입력(lifecycle·publication·override)을 바꾼다
— **그 Feature에 link가 있는 모든 dataset**의 입력이다(역할 무관). 그래서 (가) 아직 끝나지 않은 대상
dataset 적재는 preflight가 막고, (나) 대상 Feature에 대상 밖 dataset의 link(어떤 역할이든)가 있으면
멈춘다 — 그 dataset의 seal이 이 revision 때문에 바뀌면 안 된다. 이미 실패로 끝난 root의 미완 영수증
(2026-10-24 prod 돌발 3건)은 다시 대조되지 않는다. 대상 dataset은 이 revision 뒤 다시 적재되지 않는다.

막는 것(preflight, 하나라도 있으면 아무것도 바꾸지 않고 중단)
--------------------------------------------------------------

- 같은 트랜잭션에서 앞선 revision이 적용됐는데 퇴역할 Feature가 있다(아래).
- 대상 dataset 집합이 기대 셋과 다르다 / 옛 provider price·notice dataset에 active Feature가 있다.
- 대상 operation(종류 불문)을 member로 둔 queued/running job(401·404와 같은 이유 — operation이
  꺼지면 그 job은 영영 종결로 갈 수 없고, 위 seal 대조도 깨진다). 배포 전에 유가·돌발의 갱신 정책을
  끄고 진행 중 run이 끝나기를 기다린다(runbook: ADR-114 결정 7).
- 대상 Feature가 대상이 아닌 dataset에도 link(역할 무관)를 가진다(2026-10-24 prod 0건).
- 대상 Feature에 활성 lifecycle override가 있다 — 운영자 결정이 이미 있으므로 덮어쓰지 않는다
  (2026-10-24 prod 0건).

사후 조건: 대상 dataset에 켜진 operation·``active`` Feature·queued/running job이 남으면 중단한다.
퇴역 전이 수는 preflight에서 센 대상 수와 같아야 한다.

트랜잭션. env.py는 밀린 revision 전부를 **한 트랜잭션**으로 돈다. prod가 409에서 이 revision까지 한
번에 오르면 410~416(ADR-115 shadow 원장·scoped write 프로토콜)의 FK·DDL이 ``feature.features``·``provider_sync.source_entities``·
``source_records``·``provider_datasets``·``ops.feature_override_field_paths``에 잡은 SHARE ROW EXCLUSIVE를
이 revision의 약 1.4만 호출 내내 쥐게 된다 — DB 전체 쓰기 정지다. env.py의 의미는 바꾸지 않고, 이
revision이 **퇴역할 Feature가 있을 때만** 같은 트랜잭션을 거부한다(``alembic_version`` 행의 ``xmin``이
지금 트랜잭션 id면 앞선 revision이 이 트랜잭션에서 적용된 것이다). 운영은 두 번에 나눈다: (A) head가 416인
pair로 배포(410~416 commit) → (B) 이 revision이 든 pair로 배포. 빈 DB(fresh bootstrap·CI)는 퇴역할
Feature가 0이라 한 번에 오른다. 거부되면 같은 트랜잭션의 앞선 revision도 함께 되돌아가 DB는 진입 revision(prod 409)
그대로다.

forward-only. downgrade는 두지 않는다(ADR-021) — PG 유가·돌발 적재를 되살리는 것은 새 결정이다.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Final

from sqlalchemy import text

from alembic import op

# ruff: noqa: E501

revision: str = "417_retire_pg_transport_values"
down_revision: str | Sequence[str] | None = "416_field_override_protocol"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TRANSPORT_PROVIDER: Final[str] = "kor-travel-transport"

#: 정체성 규칙이 골라야 하는 dataset — 이 셋과 다르면 멈춘다(fail closed).
EXPECTED_TARGET_DATASET_KEYS: Final[frozenset[str]] = frozenset(
    {"transport_fuel_prices", "transport_rest_area_fuel_prices", "transport_highway_incidents"}
)

#: 404가 비활성화한 옛 provider. 그 price·notice dataset에 active Feature가 남아 있으면 멈춘다.
LEGACY_PROVIDERS: Final[tuple[str, ...]] = ("python-opinet-api", "python-krex-api")

#: 퇴역 전이의 감사 문맥. ``prepare_feature_state_context``가 받는 키만 쓴다.
#: SQLAlchemy ``text()``가 ``:이름``을 bind로 읽으므로 값에 콜론을 넣지 않는다.
RETIRE_REASON_CODE: Final[str] = "adr114_transport_state_moved_to_valkey"
RETIRE_PRINCIPAL: Final[str] = "system/alembic-417_retire_pg_transport_values"
RETIRE_CAUSATION_REF: Final[str] = "ADR-114 decision 7 phase 1"

#: ADR-115 scoped write 프로토콜 gate 배타 획득 대기 상한(ms). 돌고 있는 Feature 쓰기가 있으면 실패한다.
PROTOCOL_LOCK_TIMEOUT_MS: Final[int] = 30000
#: member 표 SHARE 잠금 대기 상한(ms). 미완 member 쓰기가 있으면 기다리지 않고 실패한다.
MEMBER_LOCK_TIMEOUT_MS: Final[int] = 5000
#: 퇴역 루프의 행 잠금 대기 상한(ms). member 표 잠금을 쥔 채 무한히 서지 않게 한다.
RETIRE_LOCK_TIMEOUT_MS: Final[int] = 60000
#: receipt CHECK ``ALTER TABLE`` 잠금 대기 상한(ms) — 410과 같다.
DDL_LOCK_TIMEOUT_MS: Final[int] = 1000

_PRICE_OR_NOTICE_SQL: Final[str] = """((dataset.capabilities -> 'produces') @> '["price"]'::jsonb
        OR (dataset.capabilities -> 'produces') @> '["notice"]'::jsonb)"""

_TARGET_DATASETS_SQL: Final[str] = f"""
SELECT dataset.provider_dataset_id
  FROM provider_sync.provider_datasets AS dataset
 WHERE dataset.provider = '{TRANSPORT_PROVIDER}'
   AND {_PRICE_OR_NOTICE_SQL}
"""

_TARGET_DATASET_KEYS_SQL: Final[str] = f"""
SELECT dataset.dataset_key
  FROM provider_sync.provider_datasets AS dataset
 WHERE dataset.provider = '{TRANSPORT_PROVIDER}'
   AND {_PRICE_OR_NOTICE_SQL}
 ORDER BY 1
"""

_TARGET_FEATURES_SQL: Final[str] = f"""
SELECT DISTINCT core.feature_id
  FROM feature.features AS core
  JOIN provider_sync.source_links AS link
    ON link.feature_id = core.feature_id
   AND link.source_role = 'primary'
  JOIN provider_sync.source_entities AS entity
    ON entity.source_entity_key = link.source_entity_key
 WHERE entity.provider_dataset_id IN ({_TARGET_DATASETS_SQL})
   AND core.lifecycle_state = 'active'
"""

_LEGACY_ACTIVE_FEATURES_SQL: Final[str] = f"""
SELECT DISTINCT dataset.provider || '/' || dataset.dataset_key || ':' || core.feature_id::text
  FROM feature.features AS core
  JOIN provider_sync.source_links AS link
    ON link.feature_id = core.feature_id
  JOIN provider_sync.source_entities AS entity
    ON entity.source_entity_key = link.source_entity_key
  JOIN provider_sync.provider_datasets AS dataset
    ON dataset.provider_dataset_id = entity.provider_dataset_id
 WHERE dataset.provider IN ({", ".join(f"'{p}'" for p in LEGACY_PROVIDERS)})
   AND {_PRICE_OR_NOTICE_SQL}
   AND core.lifecycle_state = 'active'
 ORDER BY 1
 LIMIT 10
"""

#: alembic은 revision마다 ``alembic_version``을 갱신한다. 그 행이 지금 트랜잭션에서 쓰였으면 이
#: 트랜잭션에서 앞선 revision이 이미 적용됐다(xid는 32비트 — xid8을 같은 폭으로 접는다).
_EARLIER_REVISION_IN_THIS_TRANSACTION_SQL: Final[str] = """
SELECT EXISTS (
    SELECT 1
      FROM public.alembic_version AS version
     WHERE version.xmin::text::bigint = (pg_current_xact_id()::text::bigint % 4294967296)
)
"""

_SET_OWNER_ROLE_SQL: Final[str] = "SET ROLE ktm_feature_schema_owner"
_SET_STATE_PROCEDURE_OWNER_ROLE_SQL: Final[str] = "SET ROLE ktm_feature_state_procedure_owner"

_LOCK_WRITE_PROTOCOL_SQL: Final[str] = "SELECT ops.lock_scoped_feature_write_protocol(true)"

_LOCK_MEMBER_TABLES_SQL: Final[str] = (
    "LOCK TABLE ops.import_job_datasets, ops.feature_update_request_datasets IN SHARE MODE"
)

_DISABLE_TARGET_OPERATIONS_SQL: Final[str] = f"""
UPDATE provider_sync.provider_dataset_operations AS operation
   SET is_enabled = false
 WHERE operation.provider_dataset_id IN ({_TARGET_DATASETS_SQL})
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

#: 프로시저가 남긴 상태 문맥을 비운다. 빈 definer는 감사 트리거의 정본 문맥 검사를 통과하지 못한다.
_CLEAR_STATE_CONTEXT_SQL: Final[str] = """
SELECT set_config('feature.state_transition_context', '', true),
       set_config('feature.state_procedure_definer', '', true)
"""

#: receipt head 값 열거 CHECK — graph의 **모든** revision(401과 같은 계약).
_RECEIPT_HEAD_CHECK_SQL: Final[str] = """
ALTER TABLE ops.application_schema_operation_receipts
    DROP CONSTRAINT ck_application_schema_operation_receipts_head,
    ADD CONSTRAINT ck_application_schema_operation_receipts_head CHECK (destination_head IN ('300', '301_m03_import_children', '302_m03_child_issuance', '303_m05_payload_hash_domain', '304_m05_detector_manuals', '305_m05_relitigation_fence', '306_m02_manual_feature_purge', '307_m02_truncate_fence', '308_t39_provider_identities', '309_t39_feature_id_rekey', '310_seoul_source_move', '311_seal_member_digest', '312_route_geometry_sidecar', '313_single_service_role', '400', '401_retire_map_kma_refresh', '402_remove_map_weather_data', '403_drop_kma_notice_lineage', '404_transport_provider_identity', '405_mois_freshness_sla', '406_feature_write_gate', '407_feature_geocode_stamps', '408_kor_travel_geo_releases', '409_geo_release_item_reasons', '410_provider_field_shadow', '411_scoped_feature_write_kernel', '412_provider_scalar_projection', '413_legacy_sql_protocol_entry', '414_manual_dedup_protocol', '415_state_lifecycle_protocol', '416_field_override_protocol', '417_retire_pg_transport_values'))
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
         AND member.provider_dataset_id IN ({_TARGET_DATASETS_SQL})
      UNION
      SELECT job.job_id::text AS job_id
        FROM ops.feature_update_request_datasets AS member
        JOIN ops.feature_update_requests AS request
          ON request.request_id = member.request_id
        JOIN ops.import_jobs AS job
          ON job.job_id = request.job_id
       WHERE job.status IN ('queued', 'running')
         AND member.provider_dataset_id IN ({_TARGET_DATASETS_SQL})
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
   AND entity.provider_dataset_id NOT IN ({_TARGET_DATASETS_SQL})
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
 WHERE operation.provider_dataset_id IN ({_TARGET_DATASETS_SQL})
   AND operation.is_enabled
UNION ALL
SELECT 'active_feature', target.feature_id::text
  FROM ({_TARGET_FEATURES_SQL}) AS target
 LIMIT 10
"""

_UPGRADE_STATEMENTS: Final[tuple[str, ...]] = (
    _SET_OWNER_ROLE_SQL,
    _LOCK_WRITE_PROTOCOL_SQL,
    _LOCK_MEMBER_TABLES_SQL,
    _DISABLE_TARGET_OPERATIONS_SQL,
    _SET_STATE_PROCEDURE_OWNER_ROLE_SQL,
    _RETIRE_TARGET_FEATURES_SQL,
    _SET_OWNER_ROLE_SQL,
    _CLEAR_STATE_CONTEXT_SQL,
    _RECEIPT_HEAD_CHECK_SQL,
)


def _set_local(bind: object, name: str, value: str) -> None:
    bind.execute(text("SELECT set_config(:name, :value, true)"), {"name": name, "value": value})  # type: ignore[attr-defined]


def _scalars(bind: object, sql: str) -> list[str]:
    return [str(value) for value in bind.execute(text(sql)).scalars()]  # type: ignore[attr-defined]


def upgrade() -> None:
    """preflight를 통과하면 대상 적재를 먼저 끄고 대상 Feature를 퇴역한다."""
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
        receipt_check,
    ) = _UPGRADE_STATEMENTS
    bind.execute(text(set_owner))
    prior = dict(
        bind.execute(
            text("SELECT name, setting FROM pg_settings WHERE name IN ('lock_timeout', 'statement_timeout')")
        ).all()
    )

    expected = int(bind.execute(text(_COUNT_TARGET_FEATURES_SQL)).scalar_one())
    if expected and bool(bind.execute(text(_EARLIER_REVISION_IN_THIS_TRANSACTION_SQL)).scalar_one()):
        raise RuntimeError(
            "417: 아무것도 바꾸지 않았다 — 이 트랜잭션에서 앞선 revision(410~416 등)이 이미 적용됐는데 퇴역할 "
            f"Feature가 {expected}건이다. 한 트랜잭션으로 돌면 앞선 revision의 표 잠금을 퇴역 내내 쥐어 "
            "DB 쓰기가 멈춘다. 먼저 head가 416인 pair로 배포해 410~416을 commit하고, 그 뒤 이 revision이 든 "
            "pair로 배포하라(ADR-114 '①의 운영 runbook' A·B). 같은 트랜잭션의 앞선 revision도 함께 되돌아간다."
        )
    keys = set(_scalars(bind, _TARGET_DATASET_KEYS_SQL))
    if keys != EXPECTED_TARGET_DATASET_KEYS:
        raise RuntimeError(
            f"417: 아무것도 바꾸지 않았다 — 대상 dataset 집합이 기대와 다르다: {sorted(keys)!r} "
            f"(기대 {sorted(EXPECTED_TARGET_DATASET_KEYS)!r})"
        )
    legacy = _scalars(bind, _LEGACY_ACTIVE_FEATURES_SQL)
    if legacy:
        raise RuntimeError(
            "417: 아무것도 바꾸지 않았다 — 404가 비활성화한 옛 provider의 price/notice dataset에 active "
            f"Feature가 남아 있다(이 revision이 모르는 상태): {legacy!r}"
        )

    _set_local(bind, "lock_timeout", str(PROTOCOL_LOCK_TIMEOUT_MS))
    bind.execute(text(lock_protocol))
    _set_local(bind, "lock_timeout", str(MEMBER_LOCK_TIMEOUT_MS))
    bind.execute(text(lock_members))
    blockers: list[str] = []
    in_flight = _scalars(bind, _IN_FLIGHT_TARGET_JOBS_SQL)
    if in_flight:
        blockers.append(
            "queued/running job on a transport price/notice operation — disable the refresh policy, "
            f"stop the schedules and wait: {in_flight!r}"
        )
    shared = _scalars(bind, _SHARED_SOURCE_FEATURES_SQL)
    if shared:
        blockers.append(f"target Feature also has a source link outside the targets: {shared!r}")
    overridden = _scalars(bind, _LIFECYCLE_OVERRIDDEN_FEATURES_SQL)
    if overridden:
        blockers.append(f"target Feature has an active lifecycle override: {overridden!r}")
    if blockers:
        raise RuntimeError("417: 아무것도 바꾸지 않았다 — " + "; ".join(blockers))

    bind.execute(text(disable_operations))
    _set_local(bind, "statement_timeout", "0")
    _set_local(bind, "lock_timeout", str(RETIRE_LOCK_TIMEOUT_MS))
    bind.execute(text(set_state_owner))
    bind.execute(text(retire))
    bind.execute(text(restore_owner))
    bind.execute(text(clear_context))
    _set_local(bind, "statement_timeout", str(prior["statement_timeout"]))
    _set_local(bind, "lock_timeout", str(DDL_LOCK_TIMEOUT_MS))
    bind.execute(text(receipt_check))
    for name, value in prior.items():
        _set_local(bind, name, str(value))

    remaining = [f"{kind}:{name}" for kind, name in bind.execute(text(_REMAINING_SQL)).all()]
    if remaining:
        raise RuntimeError(f"417: 대상이 남았다: {remaining!r}")
    retired = int(bind.execute(text(_COUNT_RETIRED_BY_THIS_REVISION_SQL)).scalar_one())
    if retired != expected:
        raise RuntimeError(f"417: 퇴역 전이 수가 대상 수와 다르다: retired={retired}, expected={expected}")
    late = _scalars(bind, _IN_FLIGHT_TARGET_JOBS_SQL)
    if late:
        raise RuntimeError(f"417: 끄는 동안 대상 operation job이 생겼다: {late!r}")


def downgrade() -> None:
    """되돌리지 않는다 — PG 유가·돌발 적재를 되살리는 것은 새 결정이다(ADR-114)."""
    raise RuntimeError(
        "417_retire_pg_transport_values is forward-only: transport 현재 상태는 Valkey가 든다(ADR-114)."
    )
