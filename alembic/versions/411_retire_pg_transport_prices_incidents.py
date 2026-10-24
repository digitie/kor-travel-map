"""PG transport 유가·돌발 적재를 닫고 그 Feature를 퇴역(soft-delete)한다(ADR-114 결정 7, 1단계).

Revision ID: 411_retire_pg_transport_prices_incidents
Revises: 410_provider_field_shadow

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
  또는 ``notice`` 가 있는 것(지금은 ``transport_fuel_prices``·``transport_rest_area_fuel_prices``·
  ``transport_highway_incidents``).
- 대상 Feature = 대상 dataset의 source entity에 ``primary`` link로 묶인 ``active`` Feature.

무엇을 하는가(실행 순서 = ``_UPGRADE_STATEMENTS``)
--------------------------------------------------

0. 함수 소유자 롤 창을 연다(404와 같다).
1. 대상 Feature를 **퇴역**한다 — ``feature.transition_feature_state``(감사·불변 trail이 있는 정본
   상태 전이)를 ``transition_kind = 'system'``으로 부른다. 결과는 ``lifecycle_state = 'retired'``·
   ``publication_state = 'suppressed'``이고, 프로시저가 같은 전이에 붙여 lifecycle override
   (``prevent_provider_reactivation = true``)를 쓴다 — provider 부재가 아니라 소유자 결정이므로
   provider tombstone(``provider_sync``)으로 위장하지 않고, 실수로 적재가 되살아나도 이 Feature가
   다시 켜지지 않는다. 프로시저 EXECUTE는 소유자(``ktm_feature_state_procedure_owner``)에게만
   있으므로 그 롤로 잠시 바꿨다가(410과 같은 창) 스키마 소유자 롤로 돌아온다 — ``RESET ROLE``이 아니다
   (``tests/lint/test_migrations_keep_the_schema_owner_role.py``). 프로시저는 advisory lock을 잡지
   않는다(행 잠금만) — 수만 건을 한 트랜잭션에서 돌려도 공유 lock table을 쓰지 않는다(ADR-111).
2. 대상 dataset의 operation을 **종류 불문**(``refresh``·``feature_load``·``preview``) 끈다. 행은 지우지
   않는다 — ``import_job_datasets``·``feature_update_request_datasets``·``provider_sync_state``가 exact
   FK로 가리키는 이력이다.
3. receipt head CHECK에 이 revision을 더한다(401~410과 같은 계약).

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
전이는 ``feature.current_provider_curation_input_set``의 입력(lifecycle·publication·override)을 바꾼다.
그래서 **아직 끝나지 않은** 대상 dataset 적재가 있으면 그 root가 끝날 때 ``stale_input``으로 실패한다.
아래 preflight가 그 job(queued/running)을 막는다. 이미 실패로 끝난 root의 미완 영수증(2026-10-24 prod
돌발 3건)은 다시 대조되지 않는다. 대상 dataset은 이 revision 뒤 다시 적재되지 않으므로 이후 대조도 없다.

막는 것(preflight, 하나라도 있으면 아무것도 바꾸지 않고 중단)
--------------------------------------------------------------

- 대상 operation(종류 불문)을 member로 둔 queued/running job(401·404와 같은 이유 — operation이
  꺼지면 그 job은 영영 종결로 갈 수 없고, 위 seal 대조도 깨진다). 배포 전에 유가·돌발 schedule을
  멈추고 진행 중 run이 끝나기를 기다린다(runbook: ADR-114 결정 7).
- 대상 Feature가 대상이 아닌 dataset에도 ``primary`` link를 가진다 — 퇴역하면 남는 출처의 Feature가
  같이 사라진다(2026-10-24 prod 0건).
- 대상 Feature에 활성 lifecycle override가 있다 — 운영자 결정이 이미 있으므로 덮어쓰지 않는다
  (2026-10-24 prod 0건).

사후 조건: 대상 dataset에 켜진 operation·``active`` Feature가 남으면 중단한다. 퇴역 수는
preflight에서 센 대상 수와 같아야 한다.

트랜잭션. env.py가 전 revision을 한 트랜잭션으로 돈다. 전부 되거나 전부 안 된다.

forward-only. downgrade는 두지 않는다(ADR-021) — PG 유가·돌발 적재를 되살리는 것은 새 결정이다.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Final

from sqlalchemy import text

from alembic import op

# ruff: noqa: E501

revision: str = "411_retire_pg_transport_prices_incidents"
down_revision: str | Sequence[str] | None = "410_provider_field_shadow"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TRANSPORT_PROVIDER: Final[str] = "kor-travel-transport"

#: 퇴역 전이의 감사 문맥. ``prepare_feature_state_context``가 받는 키만 쓴다.
#: SQLAlchemy ``text()``가 ``:이름``을 bind로 읽으므로 값에 콜론을 넣지 않는다.
RETIRE_REASON_CODE: Final[str] = "adr114_transport_state_moved_to_valkey"
RETIRE_PRINCIPAL: Final[str] = "system/alembic-411_retire_pg_transport_prices_incidents"
RETIRE_CAUSATION_REF: Final[str] = "ADR-114 decision 7 phase 1"

_TARGET_DATASETS_SQL: Final[str] = f"""
SELECT dataset.provider_dataset_id
  FROM provider_sync.provider_datasets AS dataset
 WHERE dataset.provider = '{TRANSPORT_PROVIDER}'
   AND ((dataset.capabilities -> 'produces') @> '["price"]'::jsonb
        OR (dataset.capabilities -> 'produces') @> '["notice"]'::jsonb)
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

_SET_OWNER_ROLE_SQL: Final[str] = "SET ROLE ktm_feature_schema_owner"
_SET_STATE_PROCEDURE_OWNER_ROLE_SQL: Final[str] = "SET ROLE ktm_feature_state_procedure_owner"

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

_DISABLE_TARGET_OPERATIONS_SQL: Final[str] = f"""
UPDATE provider_sync.provider_dataset_operations AS operation
   SET is_enabled = false
 WHERE operation.provider_dataset_id IN ({_TARGET_DATASETS_SQL})
   AND operation.is_enabled
"""

#: receipt head 값 열거 CHECK — graph의 **모든** revision(401과 같은 계약).
_RECEIPT_HEAD_CHECK_SQL: Final[str] = """
ALTER TABLE ops.application_schema_operation_receipts
    DROP CONSTRAINT ck_application_schema_operation_receipts_head,
    ADD CONSTRAINT ck_application_schema_operation_receipts_head CHECK (destination_head IN ('300', '301_m03_import_children', '302_m03_child_issuance', '303_m05_payload_hash_domain', '304_m05_detector_manuals', '305_m05_relitigation_fence', '306_m02_manual_feature_purge', '307_m02_truncate_fence', '308_t39_provider_identities', '309_t39_feature_id_rekey', '310_seoul_source_move', '311_seal_member_digest', '312_route_geometry_sidecar', '313_single_service_role', '400', '401_retire_map_kma_refresh', '402_remove_map_weather_data', '403_drop_kma_notice_lineage', '404_transport_provider_identity', '405_mois_freshness_sla', '406_feature_write_gate', '407_feature_geocode_stamps', '408_kor_travel_geo_releases', '409_geo_release_item_reasons', '410_provider_field_shadow', '411_retire_pg_transport_prices_incidents'))
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

_SHARED_PRIMARY_FEATURES_SQL: Final[str] = f"""
SELECT DISTINCT link.feature_id::text
  FROM provider_sync.source_links AS link
  JOIN provider_sync.source_entities AS entity
    ON entity.source_entity_key = link.source_entity_key
 WHERE link.source_role = 'primary'
   AND link.feature_id IN ({_TARGET_FEATURES_SQL})
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
   AND transition.context ->> 'reason_code' = '{RETIRE_REASON_CODE}'
   AND transition.context ->> 'principal' = '{RETIRE_PRINCIPAL}'
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
    _SET_STATE_PROCEDURE_OWNER_ROLE_SQL,
    _RETIRE_TARGET_FEATURES_SQL,
    _SET_OWNER_ROLE_SQL,
    _DISABLE_TARGET_OPERATIONS_SQL,
    _RECEIPT_HEAD_CHECK_SQL,
)


def upgrade() -> None:
    """preflight를 통과하면 대상 Feature를 퇴역하고 대상 적재를 닫는다."""
    bind = op.get_bind()
    blockers: list[str] = []
    in_flight = [str(job_id) for job_id in bind.execute(text(_IN_FLIGHT_TARGET_JOBS_SQL)).scalars()]
    if in_flight:
        blockers.append(
            "queued/running job on a transport price/notice operation — stop the schedules and "
            f"wait: {in_flight!r}"
        )
    shared = [str(key) for key in bind.execute(text(_SHARED_PRIMARY_FEATURES_SQL)).scalars()]
    if shared:
        blockers.append(f"target Feature also has a primary source outside the targets: {shared!r}")
    overridden = [str(key) for key in bind.execute(text(_LIFECYCLE_OVERRIDDEN_FEATURES_SQL)).scalars()]
    if overridden:
        blockers.append(f"target Feature has an active lifecycle override: {overridden!r}")
    if blockers:
        raise RuntimeError("411: 아무것도 바꾸지 않았다 — " + "; ".join(blockers))
    expected = int(bind.execute(text(_COUNT_TARGET_FEATURES_SQL)).scalar_one())
    for statement in _UPGRADE_STATEMENTS:
        bind.execute(text(statement))
    remaining = [f"{kind}:{name}" for kind, name in bind.execute(text(_REMAINING_SQL)).all()]
    if remaining:
        raise RuntimeError(f"411: 대상이 남았다: {remaining!r}")
    retired = int(bind.execute(text(_COUNT_RETIRED_BY_THIS_REVISION_SQL)).scalar_one())
    if retired != expected:
        raise RuntimeError(f"411: 퇴역 전이 수가 대상 수와 다르다: retired={retired}, expected={expected}")


def downgrade() -> None:
    """되돌리지 않는다 — PG 유가·돌발 적재를 되살리는 것은 새 결정이다(ADR-114)."""
    raise RuntimeError(
        "411_retire_pg_transport_prices_incidents is forward-only: transport 현재 상태는 Valkey가 든다(ADR-114)."
    )
