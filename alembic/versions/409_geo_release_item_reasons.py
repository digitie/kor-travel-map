"""geo 릴리스 항목 ``state_reason``에 ``superseded``·``canceled``를 더한다(T-GR-05, ADR-109 결정 5.5).

Revision ID: 409_geo_release_item_reasons
Revises: 408_kor_travel_geo_releases

왜 필요한가. 릴리스 센서(T-GR-05)가 두 전이를 새로 남긴다 — (1) 새 계획이 옛 활성 계획을
``superseded``로 닫을 때 그 계획의 ``requested`` 항목은 ``failed(superseded)``가 된다(진행 중으로 남은
고아가 없어야 한 번에 run 1개 상한이 성립한다); (2) 운영자가 취소한 run(CANCELED)은 재요청하지 않고
``failed(canceled)``로 끝낸다(운영자의 취소를 존중한다). 408의 ``state_reason`` CHECK 어휘에 둘을 더한다.

408을 고치지 않고 새 revision인 이유: 408은 이미 배포 경로에 있다(forward-only — ADR-021·102).

forward-only. downgrade는 두지 않는다(``alembic/env.py``가 모든 downgrade를 해석 전에 거부한다).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Final

from sqlalchemy import text

from alembic import op

# ruff: noqa: E501

revision: str = "409_geo_release_item_reasons"
down_revision: str | Sequence[str] | None = "408_kor_travel_geo_releases"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: 스키마 소유자. env가 켠 롤이고, 마이그레이션은 이 롤로 끝나야 한다.
_SCHEMA_OWNER_ROLE: Final[str] = "ktm_feature_schema_owner"

_SET_OWNER_ROLE_SQL: Final[str] = f"SET ROLE {_SCHEMA_OWNER_ROLE}"

_REASON_CHECK_SQL: Final[str] = """
ALTER TABLE ops.kor_travel_geo_release_items
    DROP CONSTRAINT ck_kor_travel_geo_release_items_state_reason,
    ADD CONSTRAINT ck_kor_travel_geo_release_items_state_reason
        CHECK (state_reason IS NULL OR state_reason IN (
            'disabled', 'no_geo_dependency', 'queue_only', 'operator', 'sweep',
            'run_not_launched', 'no_progress', 'run_failed', 'superseded', 'canceled'
        ))
"""

_RECEIPT_HEAD_CHECK_SQL: Final[str] = """
ALTER TABLE ops.application_schema_operation_receipts
    DROP CONSTRAINT ck_application_schema_operation_receipts_head,
    ADD CONSTRAINT ck_application_schema_operation_receipts_head CHECK (destination_head IN ('300', '301_m03_import_children', '302_m03_child_issuance', '303_m05_payload_hash_domain', '304_m05_detector_manuals', '305_m05_relitigation_fence', '306_m02_manual_feature_purge', '307_m02_truncate_fence', '308_t39_provider_identities', '309_t39_feature_id_rekey', '310_seoul_source_move', '311_seal_member_digest', '312_route_geometry_sidecar', '313_single_service_role', '400', '401_retire_map_kma_refresh', '402_remove_map_weather_data', '403_drop_kma_notice_lineage', '404_transport_provider_identity', '405_mois_freshness_sla', '406_feature_write_gate', '407_feature_geocode_stamps', '408_kor_travel_geo_releases', '409_geo_release_item_reasons'))
"""

#: 실행 순서대로의 upgrade 문장. 창은 소유자 롤로 열고 같은 롤로 끝난다.
_UPGRADE_STATEMENTS: Final[tuple[str, ...]] = (
    _SET_OWNER_ROLE_SQL,
    _REASON_CHECK_SQL,
    _RECEIPT_HEAD_CHECK_SQL,
)


def upgrade() -> None:
    """항목 ``state_reason`` 어휘에 ``superseded``·``canceled``를 더하고 receipt head CHECK에 409를 더한다."""
    bind = op.get_bind()
    for statement in _UPGRADE_STATEMENTS:
        bind.execute(text(statement))


def downgrade() -> None:
    """되돌리지 않는다."""
    raise RuntimeError(
        "409_geo_release_item_reasons is forward-only: CHECK 어휘는 forward revision으로만 바꾼다."
    )
