"""geo 릴리스 재지오코딩 계획 표 ``ops.kor_travel_geo_releases``(+ items)를 만든다(ADR-109 결정 5).

Revision ID: 408_kor_travel_geo_releases
Revises: 407_feature_geocode_stamps

왜 필요한가. kor-travel-geo가 주소 DB를 새 릴리스(새 ``data_token``)로 바꾸면 Map은 geo 유도 값을
가진 dataset을 다시 적재해 스탬프가 낡은 행을 고쳐야 한다(ADR-109 결정 4 — 적재 경로의 stale
분기). "어느 토큰에 대해 어느 dataset을 어디까지 돌렸는가"를 Dagster 센서 커서나 run 태그가 아니라
DB에 두어야 센서(T-GR-05)와 운영 API ``POST /v1/ops/geo-releases/detect``가 **같은 함수**로 같은
계획을 보고, 재기동·롤백(A→B→A)에서도 계획이 이어진다.

무엇을 하는가.

- ``ops.kor_travel_geo_releases`` — 계획 1행 = ``(geo_data_token, plan_seq)``. ``state``는
  ``baseline|planned|running|done|superseded``다. ``baseline``은 소유자 결정(2026-10-15, ADR-109
  결정 5.1)의 기록이다 — 처음 관측한 토큰은 계획 없이 기준선으로만 남긴다. 그것을 DB 행으로 두어야
  센서 커서가 없는 API ``/detect``도 같은 판단을 한다. 같은 토큰의 활성(``planned|running``) 계획은
  하나뿐이다(부분 UNIQUE). ``sweep_started_at``은 완료 판정의 "잔여 1회 sweep"을 한 번만 하게 한다.
- ``ops.kor_travel_geo_release_items`` — 계획의 항목. **1행 = Dagster run 1개**다:
  ``(operation_key, run_config)``가 같은 dataset은 ``provider_dataset_ids`` 배열 하나로 묶인다(MCST는
  job 하나에 dataset 13개가 run 1개, KNPS는 dataset마다 run_config가 달라 항목 5개). ``position``이
  실행 순서다. ``run_config``는 그 dataset을 고르는 run_config(KNPS·datagokr fileData)와 replay
  지시(쿼터 민감)이고 NULL이면 job 기본값이다. ``attempt_seq``는 같은 행에서 단조 증가하고(재요청·
  sweep — run_key의 마지막 성분) UNIQUE에 넣지 않는다 — 시도 이력은 Dagster run tag가 갖는다.
  ``state_reason``은 고정 어휘(CHECK)다.
- **dataset FK는 없다.** ``provider_dataset_ids``는 배열이라 FK를 걸 수 없고, ON DELETE 동작도 없다.
  provider dataset은 지우지 않고 ``is_active``로 비활성화만 한다(저장소에 삭제 경로가 없다) — 계획
  이력의 id는 그 행을 계속 가리킨다.
- 토큰 형식 CHECK는 407과 같은 식이다(geo 계약 ``dv1-``/``dd1-`` + 32 lowercase hex).
- 소유자 ``ktm_feature_schema_owner``. 런타임 권한은 배포 조정기
  (``infra/runtime_privileges.py`` ``_OPS_TABLE_PRIVILEGES``)가 건다.
- receipt head CHECK에 이 revision을 더한다(401~407과 같은 계약).

forward-only(ADR-021·ADR-102 — ``alembic/env.py``가 모든 downgrade를 해석 전에 거부한다). 되돌릴
일이 생기면 forward revision으로 표를 지운다 — 지워지는 것은 계획 이력뿐이고, 스탬프가 정본이므로
다음 감지가 다시 계획한다.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Final

from sqlalchemy import text

from alembic import op

# ruff: noqa: E501

revision: str = "408_kor_travel_geo_releases"
down_revision: str | Sequence[str] | None = "407_feature_geocode_stamps"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: 스키마 소유자. env가 켠 롤이고, 마이그레이션은 이 롤로 끝나야 한다.
_SCHEMA_OWNER_ROLE: Final[str] = "ktm_feature_schema_owner"

_SET_OWNER_ROLE_SQL: Final[str] = f"SET ROLE {_SCHEMA_OWNER_ROLE}"

_CREATE_RELEASES_SQL: Final[str] = """
CREATE TABLE ops.kor_travel_geo_releases (
    plan_id bigint GENERATED ALWAYS AS IDENTITY,
    geo_data_token text NOT NULL,
    plan_seq integer DEFAULT 1 NOT NULL,
    geo_version_token text NOT NULL,
    activated_at timestamp with time zone,
    reference_months jsonb,
    state text NOT NULL,
    residual_stale integer,
    sweep_started_at timestamp with time zone,
    observed_at timestamp with time zone DEFAULT now() NOT NULL,
    completed_at timestamp with time zone,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT pk_kor_travel_geo_releases PRIMARY KEY (plan_id),
    CONSTRAINT uq_kor_travel_geo_releases_token_seq UNIQUE (geo_data_token, plan_seq),
    CONSTRAINT ck_kor_travel_geo_releases_state
        CHECK (state IN ('baseline', 'planned', 'running', 'done', 'superseded')),
    CONSTRAINT ck_kor_travel_geo_releases_plan_seq CHECK (plan_seq >= 1),
    CONSTRAINT ck_kor_travel_geo_releases_residual CHECK (residual_stale IS NULL OR residual_stale >= 0),
    CONSTRAINT ck_kor_travel_geo_releases_reference_months
        CHECK (reference_months IS NULL OR jsonb_typeof(reference_months) = 'object'),
    CONSTRAINT ck_kor_travel_geo_releases_version_token
        CHECK (geo_version_token ~ '^dv1-[0-9a-f]{32}$'),
    CONSTRAINT ck_kor_travel_geo_releases_data_token
        CHECK (geo_data_token ~ '^dd1-[0-9a-f]{32}$')
)
"""

_OWNER_RELEASES_SQL: Final[str] = (
    f"ALTER TABLE ops.kor_travel_geo_releases OWNER TO {_SCHEMA_OWNER_ROLE}"
)

#: 같은 토큰의 활성 계획은 하나다 — 센서와 ``/detect``가 동시에 감지해도 행이 둘 생기지 않는다.
_INDEX_ACTIVE_SQL: Final[str] = (
    "CREATE UNIQUE INDEX uq_kor_travel_geo_releases_active_token "
    "ON ops.kor_travel_geo_releases USING btree (geo_data_token) "
    "WHERE (state = ANY (ARRAY['planned'::text, 'running'::text]))"
)

_CREATE_ITEMS_SQL: Final[str] = """
CREATE TABLE ops.kor_travel_geo_release_items (
    plan_id bigint NOT NULL,
    "position" integer NOT NULL,
    operation_key text NOT NULL,
    provider_dataset_ids bigint[] NOT NULL,
    run_config jsonb,
    attempt_seq integer DEFAULT 1 NOT NULL,
    state text DEFAULT 'pending' NOT NULL,
    state_reason text,
    run_key text,
    dagster_run_id text,
    requested_at timestamp with time zone,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT pk_kor_travel_geo_release_items PRIMARY KEY (plan_id, "position"),
    CONSTRAINT uq_kor_travel_geo_release_items_run
        UNIQUE (plan_id, operation_key, provider_dataset_ids),
    CONSTRAINT fk_kor_travel_geo_release_items_plan FOREIGN KEY (plan_id)
        REFERENCES ops.kor_travel_geo_releases(plan_id) ON DELETE CASCADE,
    CONSTRAINT ck_kor_travel_geo_release_items_datasets
        CHECK (cardinality(provider_dataset_ids) >= 1),
    CONSTRAINT ck_kor_travel_geo_release_items_state
        CHECK (state IN ('pending', 'requested', 'done', 'failed', 'skipped')),
    CONSTRAINT ck_kor_travel_geo_release_items_state_reason
        CHECK (state_reason IS NULL OR state_reason IN (
            'disabled', 'no_geo_dependency', 'queue_only', 'operator', 'sweep',
            'run_not_launched', 'no_progress', 'run_failed'
        )),
    CONSTRAINT ck_kor_travel_geo_release_items_skip_reason
        CHECK (state <> 'skipped' OR state_reason IS NOT NULL),
    CONSTRAINT ck_kor_travel_geo_release_items_position CHECK ("position" >= 1),
    CONSTRAINT ck_kor_travel_geo_release_items_attempt CHECK (attempt_seq >= 1),
    CONSTRAINT ck_kor_travel_geo_release_items_run_config
        CHECK (run_config IS NULL OR jsonb_typeof(run_config) = 'object')
)
"""

_OWNER_ITEMS_SQL: Final[str] = (
    f"ALTER TABLE ops.kor_travel_geo_release_items OWNER TO {_SCHEMA_OWNER_ROLE}"
)

#: receipt head 값 열거 CHECK — graph의 **모든** revision(401과 같은 계약).
_RECEIPT_HEAD_CHECK_SQL: Final[str] = """
ALTER TABLE ops.application_schema_operation_receipts
    DROP CONSTRAINT ck_application_schema_operation_receipts_head,
    ADD CONSTRAINT ck_application_schema_operation_receipts_head CHECK (destination_head IN ('300', '301_m03_import_children', '302_m03_child_issuance', '303_m05_payload_hash_domain', '304_m05_detector_manuals', '305_m05_relitigation_fence', '306_m02_manual_feature_purge', '307_m02_truncate_fence', '308_t39_provider_identities', '309_t39_feature_id_rekey', '310_seoul_source_move', '311_seal_member_digest', '312_route_geometry_sidecar', '313_single_service_role', '400', '401_retire_map_kma_refresh', '402_remove_map_weather_data', '403_drop_kma_notice_lineage', '404_transport_provider_identity', '405_mois_freshness_sla', '406_feature_write_gate', '407_feature_geocode_stamps', '408_kor_travel_geo_releases'))
"""

#: 실행 순서대로의 upgrade 문장. 창은 소유자 롤로 열고 같은 롤로 끝난다 — env가 켠
#: 스키마 소유자 롤과 같으므로 alembic의 ``UPDATE alembic_version``도 그대로 산다.
_UPGRADE_STATEMENTS: Final[tuple[str, ...]] = (
    _SET_OWNER_ROLE_SQL,
    _CREATE_RELEASES_SQL,
    _OWNER_RELEASES_SQL,
    _INDEX_ACTIVE_SQL,
    _CREATE_ITEMS_SQL,
    _OWNER_ITEMS_SQL,
    _RECEIPT_HEAD_CHECK_SQL,
)


def upgrade() -> None:
    """계획 표·항목 표를 만들고 receipt head CHECK에 408을 더한다."""
    bind = op.get_bind()
    for statement in _UPGRADE_STATEMENTS:
        bind.execute(text(statement))


def downgrade() -> None:
    """되돌리지 않는다 — 계획 표는 forward revision으로만 걷는다."""
    raise RuntimeError(
        "408_kor_travel_geo_releases is forward-only: 계획 표는 forward revision으로만 걷는다(ADR-109)."
    )
