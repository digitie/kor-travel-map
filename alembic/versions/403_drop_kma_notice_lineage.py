"""``provider_sync.notice_lineage_key``에서 KMA 기상특보 분기를 걷어낸다(ADR-105).

Revision ID: 403_drop_kma_notice_lineage
Revises: 402_remove_map_weather_data

왜 필요한가. 402가 기상 출처 notice(provider ``python-kma-api``의 notice dataset)의
lineage를 전부 지우고 dataset을 비활성으로 내렸다. 그 뒤 DB 정본 계보 함수의 KMA 분기는
평가될 행이 없는 죽은 규칙이다. 그런데 그 함수를 애플리케이션 재계산 식
(``feature_repo._notice_lineage_sql``)이 글자 단위로 따라야 하므로
(``test_db_lineage_function_matches_frozen_replay_expression``) 죽은 분기가 두 벌로
남아 "Map이 기상특보를 다룬다"는 거짓을 말한다. 이 revision이 DB 쪽을, 같은 변경이
애플리케이션 쪽을 함께 걷어낸다.

무엇을 하는가. 함수를 ``CREATE OR REPLACE``로 다시 쓴다. KREX 교통 notice 분기와
fallback(``ELSE entity.source_entity_id``)·서명·``LANGUAGE sql STABLE``·본문의 나머지는
**글자 그대로** 둔다 — ``alembic/head-schema.sql``의 본문과 바이트가 같아야 한다.
``CREATE OR REPLACE``는 소유자와 ACL을 보존한다. 소유자는 head-schema가 말하는
``ktm_feature_schema_owner``이고, 그 창 안에서 실행한다(NOINHERIT라 창이 필수다).

막는 것(preflight). 지울 분기가 만든 계보 key를 저장한 head가 하나라도 있으면 중단한다.
계보 key는 write-once로 head에 물화되어 있다 — 규칙만 바꾸면 그 행은 새 규칙과 다른
값을 든 채 남고, 다음 재관측 때 값이 조용히 바뀐다. 402 뒤에는 0행이어야 한다(402가
그 dataset의 source lineage를 전부 지웠다). 조건은 지우는 분기의 술어 그 자체다.

forward-only. downgrade는 두지 않는다(ADR-021).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Final

from sqlalchemy import text

from alembic import op

# ruff: noqa: E501

revision: str = "403_drop_kma_notice_lineage"
down_revision: str | Sequence[str] | None = "402_remove_map_weather_data"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: 함수 소유자. ``alembic/head-schema.sql``의 ``ALTER FUNCTION ... OWNER TO``와 같다.
_OWNER_ROLE: Final[str] = "ktm_feature_schema_owner"

#: 지우는 분기의 술어로 고른 head — 그 분기가 계보 key를 만든 행.
_HEADS_FROM_REMOVED_BRANCH_SQL: Final[str] = """
SELECT head.source_entity_key
  FROM provider_sync.source_entity_heads AS head
  JOIN provider_sync.source_entities AS entity
    ON entity.source_entity_key = head.source_entity_key
  JOIN provider_sync.provider_datasets AS dataset
    ON dataset.provider_dataset_id = entity.provider_dataset_id
 WHERE dataset.provider = 'python-kma-api'
   AND dataset.dataset_key = 'kma_weather_alerts'
   AND entity.source_entity_type = 'weather_alert'
 ORDER BY head.source_entity_key
 LIMIT 10
"""

_SET_OWNER_ROLE_SQL: Final[str] = f"SET ROLE {_OWNER_ROLE}"

#: 본문은 head-schema의 함수 본문에서 KMA ``WHEN`` 분기만 뺀 것이다(바이트 동일).
_REPLACE_NOTICE_LINEAGE_KEY_SQL: Final[str] = """CREATE OR REPLACE FUNCTION provider_sync.notice_lineage_key(head provider_sync.source_entity_heads) RETURNS text
    LANGUAGE sql STABLE
    AS $$
            SELECT CASE
              WHEN dataset.provider = 'python-krex-api'
               AND dataset.dataset_key = 'krex_traffic_notices'
               AND entity.source_entity_type = 'traffic_notice'
              THEN COALESCE(
                NULLIF(
                  concat_ws(
                    '::',
                    NULLIF(lower(btrim(record.raw_data->>'occurred_date')), ''),
                    NULLIF(lower(btrim(record.raw_data->>'occurred_time')), ''),
                    NULLIF(lower(btrim(record.raw_data->>'route_no')), ''),
                    NULLIF(lower(btrim(record.raw_data->>'direction')), ''),
                    NULLIF(lower(btrim(record.raw_data->>'point_name')), ''),
                    NULLIF(
                      lower(btrim(record.raw_data->>'incident_type_code')), ''
                    )
                  ),
                  ''
                ),
                entity.source_entity_id
              )
              -- out-of-scope도 값을 갖는다. 읽는 쪽이
              -- COALESCE(head.lineage_key, entity.source_entity_id)로 물러나면
              -- **두 테이블에 걸친 식**이 되어 어떤 단일 인덱스도 받지 못한다.
              ELSE entity.source_entity_id
            END
            FROM provider_sync.source_entities AS entity
            JOIN provider_sync.provider_datasets AS dataset
              ON dataset.provider_dataset_id = entity.provider_dataset_id
            JOIN provider_sync.source_records AS record
              ON record.source_record_key = head.current_source_record_key
            WHERE entity.source_entity_key = head.source_entity_key
        $$"""

#: receipt head 값 열거 CHECK — graph의 **모든** revision(401과 같은 계약).
_RECEIPT_HEAD_CHECK_SQL: Final[str] = """
ALTER TABLE ops.application_schema_operation_receipts
    DROP CONSTRAINT ck_application_schema_operation_receipts_head,
    ADD CONSTRAINT ck_application_schema_operation_receipts_head CHECK (destination_head IN ('300', '301_m03_import_children', '302_m03_child_issuance', '303_m05_payload_hash_domain', '304_m05_detector_manuals', '305_m05_relitigation_fence', '306_m02_manual_feature_purge', '307_m02_truncate_fence', '308_t39_provider_identities', '309_t39_feature_id_rekey', '310_seoul_source_move', '311_seal_member_digest', '312_route_geometry_sidecar', '313_single_service_role', '400', '401_retire_map_kma_refresh', '402_remove_map_weather_data', '403_drop_kma_notice_lineage'))
"""

#: 실행 순서대로의 upgrade 문장. 창은 소유자 롤로 열고 같은 롤로 끝난다 — env가 켠
#: 스키마 소유자 롤과 같으므로 alembic의 ``UPDATE alembic_version``도 그대로 산다.
_UPGRADE_STATEMENTS: Final[tuple[str, ...]] = (
    _SET_OWNER_ROLE_SQL,
    _REPLACE_NOTICE_LINEAGE_KEY_SQL,
    _RECEIPT_HEAD_CHECK_SQL,
)


def upgrade() -> None:
    """지울 분기가 만든 계보가 없음을 확인하고, 함수를 다시 쓴다."""
    bind = op.get_bind()
    stale = [str(key) for key in bind.execute(text(_HEADS_FROM_REMOVED_BRANCH_SQL)).scalars()]
    if stale:
        raise RuntimeError(
            "403: head lineage computed by the removed KMA notice branch — "
            f"아무것도 바꾸지 않았다: {stale!r}"
        )
    for statement in _UPGRADE_STATEMENTS:
        bind.execute(text(statement))


def downgrade() -> None:
    """되돌리지 않는다 — Map은 기상특보를 적재하지 않는다."""
    raise RuntimeError(
        "403_drop_kma_notice_lineage is forward-only: Map은 기상 출처 notice를 갖지 않는다(ADR-105)."
    )
