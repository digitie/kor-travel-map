"""ADR115 기본 OFF shadow 후보 원장. winner/effective·잠금 세분화 활성화는 하지 않는다."""

from __future__ import annotations

from pathlib import Path
from typing import Final

from sqlalchemy import text
from sqlalchemy.util.concurrency import await_only

from alembic import op

revision = "410_provider_field_shadow"
down_revision = "409_geo_release_item_reasons"
branch_labels = None
depends_on = None

# ruff: noqa: E501
_RECEIPT_HEAD_CHECK_SQL: Final[str] = """
ALTER TABLE ops.application_schema_operation_receipts
    DROP CONSTRAINT ck_application_schema_operation_receipts_head,
    ADD CONSTRAINT ck_application_schema_operation_receipts_head CHECK (destination_head IN ('300', '301_m03_import_children', '302_m03_child_issuance', '303_m05_payload_hash_domain', '304_m05_detector_manuals', '305_m05_relitigation_fence', '306_m02_manual_feature_purge', '307_m02_truncate_fence', '308_t39_provider_identities', '309_t39_feature_id_rekey', '310_seoul_source_move', '311_seal_member_digest', '312_route_geometry_sidecar', '313_single_service_role', '400', '401_retire_map_kma_refresh', '402_remove_map_weather_data', '403_drop_kma_notice_lineage', '404_transport_provider_identity', '405_mois_freshness_sla', '406_feature_write_gate', '407_feature_geocode_stamps', '408_kor_travel_geo_releases', '409_geo_release_item_reasons', '410_provider_field_shadow'))
"""


def upgrade() -> None:
    """기존 짧은 DDL 대기 상한을 보존하고 additive shadow 구조를 만든다."""
    bind = op.get_bind()
    bind.execute(text("SET ROLE ktm_feature_schema_owner"))
    settings = dict(
        bind.execute(
            text(
                "SELECT name,setting FROM pg_settings WHERE name IN ('lock_timeout','statement_timeout')"
            )
        ).all()
    )
    for name, cap in (("lock_timeout", 1000), ("statement_timeout", 30000)):
        prior = int(settings[name])
        bind.execute(
            text("SELECT set_config(:name,:value,true)"),
            {"name": name, "value": str(min(prior, cap) if prior else cap)},
        )
    raw = Path(__file__).with_name("_410_provider_field_shadow.sql").read_text()
    # 400 baseline과 같은 asyncpg script 실행 경계로 dollar-quoted 본문을 보존한다.
    await_only(bind.connection.driver_connection.execute(raw))
    bind.execute(text(_RECEIPT_HEAD_CHECK_SQL))
    for name, prior in settings.items():
        bind.execute(text("SELECT set_config(:name,:value,true)"), {"name": name, "value": prior})


def downgrade() -> None:
    raise RuntimeError("forward-only migration")
