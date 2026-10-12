"""MOIS bulk dataset에 freshness SLA(``stale_after_minutes``)를 심는다(ADR-108).

Revision ID: 405_mois_freshness_sla
Revises: 404_transport_provider_identity

왜 필요한가. MOIS 재개형 적재는 역지오코딩 부분 장애를 보면 run을 실패시키지 않고 **degraded**로
끝내며 봉인·provider sync 성공을 남기지 않는다(같은 장애가 두 전체 run 연속이면 그때는 붉은
run이다). 그러면 sync 성공 시각이 멈추는데, 운영 화면(``/v1/ops/datasets``)은 dataset의
``ops.provider_refresh_policies.stale_after_minutes``가 있어야 그것을 **overdue**로 보인다. 지금
baseline seed에는 policy 행이 하나도 없다 — MOIS가 몇 달 동안 봉인되지 않아도 아무 화면도 붉어지지
않는다.

무엇을 하는가. ``python-mois-api``/``mois_license_features_bulk`` dataset의 policy에
``stale_after_minutes = 57600``(40일 = 월간 schedule + 이어 달리기·재시도 여유)을 둔다.

- 행이 없으면 만든다. ``source_kind``는 dataset의 값(``filedata``)을 그대로 쓰고 나머지는 열
  기본값이다 — ``targeted_policy``는 기본 ``follow_system``이지만 MOIS는 어떤 policy로도 큐에서
  돌지 않는다(``DEDICATED_JOB_ONLY_OPERATION_KEYS``).
- 행이 있고 ``stale_after_minutes``가 비어 있으면 그 값만 채우고 ``revision``을 올린다.
- 운영자가 이미 정한 값은 **바꾸지 않는다**.
- dataset이 비활성이면 아무것도 하지 않는다(policy trigger가 비활성 dataset 쓰기를 거부한다).

receipt head CHECK에 이 revision을 더한다(401~404와 같은 계약).

forward-only. downgrade는 두지 않는다(ADR-021) — SLA를 걷는 것은 운영 화면에서 한다.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Final

from sqlalchemy import text

from alembic import op

# ruff: noqa: E501

revision: str = "405_mois_freshness_sla"
down_revision: str | Sequence[str] | None = "404_transport_provider_identity"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: 표 소유자. ``alembic/head-schema.sql``의 ``ALTER TABLE ... OWNER TO``와 같다.
_OWNER_ROLE: Final[str] = "ktm_feature_schema_owner"

#: 40일. 월간 schedule(매월 2일) 한 주기 + 이어 달리기·재시도·degraded 재실행 여유.
MOIS_STALE_AFTER_MINUTES: Final[int] = 40 * 24 * 60

_SET_OWNER_ROLE_SQL: Final[str] = f"SET ROLE {_OWNER_ROLE}"

_SEED_MOIS_SLA_SQL: Final[str] = f"""
INSERT INTO ops.provider_refresh_policies AS policy (
    provider_dataset_id, source_kind, stale_after_minutes
)
SELECT dataset.provider_dataset_id, dataset.source_kind, {MOIS_STALE_AFTER_MINUTES}
  FROM provider_sync.provider_datasets AS dataset
 WHERE dataset.provider = 'python-mois-api'
   AND dataset.dataset_key = 'mois_license_features_bulk'
   AND dataset.is_active
ON CONFLICT (provider_dataset_id) DO UPDATE
   SET stale_after_minutes = EXCLUDED.stale_after_minutes,
       revision = policy.revision + 1,
       updated_at = now()
 WHERE policy.stale_after_minutes IS NULL
"""

#: receipt head 값 열거 CHECK — graph의 **모든** revision(401과 같은 계약).
_RECEIPT_HEAD_CHECK_SQL: Final[str] = """
ALTER TABLE ops.application_schema_operation_receipts
    DROP CONSTRAINT ck_application_schema_operation_receipts_head,
    ADD CONSTRAINT ck_application_schema_operation_receipts_head CHECK (destination_head IN ('300', '301_m03_import_children', '302_m03_child_issuance', '303_m05_payload_hash_domain', '304_m05_detector_manuals', '305_m05_relitigation_fence', '306_m02_manual_feature_purge', '307_m02_truncate_fence', '308_t39_provider_identities', '309_t39_feature_id_rekey', '310_seoul_source_move', '311_seal_member_digest', '312_route_geometry_sidecar', '313_single_service_role', '400', '401_retire_map_kma_refresh', '402_remove_map_weather_data', '403_drop_kma_notice_lineage', '404_transport_provider_identity', '405_mois_freshness_sla'))
"""

#: 실행 순서대로의 upgrade 문장. 창은 소유자 롤로 열고 같은 롤로 끝난다 — env가 켠
#: 스키마 소유자 롤과 같으므로 alembic의 ``UPDATE alembic_version``도 그대로 산다.
_UPGRADE_STATEMENTS: Final[tuple[str, ...]] = (
    _SET_OWNER_ROLE_SQL,
    _SEED_MOIS_SLA_SQL,
    _RECEIPT_HEAD_CHECK_SQL,
)


def upgrade() -> None:
    """MOIS bulk dataset policy에 SLA를 채운다(운영자가 정한 값은 보존)."""
    bind = op.get_bind()
    for statement in _UPGRADE_STATEMENTS:
        bind.execute(text(statement))


def downgrade() -> None:
    """되돌리지 않는다 — SLA는 운영 화면에서 바꾼다."""
    raise RuntimeError(
        "405_mois_freshness_sla is forward-only: SLA는 운영 화면에서 바꾼다(ADR-108)."
    )
