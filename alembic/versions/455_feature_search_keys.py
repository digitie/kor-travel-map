"""검색 비교 키 표를 만든다 — 읽기 성능 계획 T-READ-06.

Revision ID: 455_feature_search_keys
Revises: 454_route_cluster_markers

왜 필요한가. 검색 순위(``infra/feature_repo.py`` ``_feature_search_score_cte``)는 후보 행마다 보이는
이름을 정규화해 비교 키 여섯 개(NFC·공백 제거·소문자·끝 괄호 변형)와 실효 검색 그룹(이름 끝말
정규식)을 만든다. prod 2026-11-19 조용한 창 기준선(``jit=off``, 30회 p50)에서 그 식을 빼고 잰 비중이
"부산 맛집" 37%·"서울 맛집" 56%였다(채택 문턱 30%). 같은 키를 Feature마다 미리 계산해 둔다.

무엇을 하는가.

- ``feature.feature_search_keys(feature_id PK, keys_version, server_fingerprint, name, category,
  compact_* 여섯,
  search_group, computed_at)``. 소유자 ``ktm_feature_schema_owner``. 런타임 권한
  (SELECT·INSERT·UPDATE·DELETE)은 배포 조정기(``infra/runtime_privileges.py``)가 건다.
  ``feature.features`` FK·트리거는 두지 않는다 — Feature 쓰기 경로(적재·관리 편집)와
  잠금·쓰기 비용을 엮지 않는다. 색인은 PK 하나다.
- 검색은 ``keys_version``(키 식의 지문)·``server_fingerprint``(PostgreSQL 판과 DB의 ctype·
  collation 판)·``name``·``category``가 지금과 **모두 같을 때만**
  저장 키를 쓰고, 아니면 종전 식으로 계산한다. 그래서 표가 비었거나 묵어도(새 행·이름이
  바뀐 행·키 식이 바뀐 배포) 순위는 이 revision 전과 같다 — 빨라지지 않을 뿐이다.
- receipt head CHECK에 이 revision을 더한다.

기존 행 채우기(backfill) — **이 migration은 표만 만든다.** 계산은 공개 Feature 전부(prod 약 42만
행)의 정규화라 migration ``statement_timeout``(30초) 안에 끝난다고 보장할 수 없다.

1. 배포 직후: 표가 비어 있으므로 검색은 종전 식으로 계산한다(안전한 퇴화, 속도도 종전과 같다).
2. 채우기: Dagster ``consistency_dedup_refresh`` job(매일 05:45 KST)의 ``refresh_search_keys`` op가
   채운다. 배포 뒤 바로 채우려면 그 job을 한 번 수동 실행한다. 다음부터는 키가 없거나 맞지 않는 행만
   계산해 쓴다.
3. 잠금·시간: ``feature.features``는 읽기만 한다(ACCESS SHARE — 적재·Feature 쓰기를 막지 않는다).
   쓰기는 이 표에만. op는 문장 상한 15분이다. 실측 시간은 PR 본문·``docs/journal.md``에 적는다.

잠금(이 migration). 새 표를 만들 뿐 기존 표를 잠그지 않는다. receipt 표 CHECK 교체만
``ACCESS EXCLUSIVE``(작은 표)를 잡으므로 ``lock_timeout`` 1초, ``statement_timeout`` 30초로 묶는다.
마지막 문장은 ``SET ROLE ktm_feature_schema_owner``다(alembic_version UPDATE가 그 롤로 돈다 —
RESET ROLE 금지).

forward-only. 되돌릴 일이 생기면 forward revision으로 표를 지운다 — 그 전에 검색 코드가 표를 읽지
않게 먼저 바꿔야 한다(표가 없으면 검색 SQL이 실패한다).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Final

from sqlalchemy import text

from alembic import op

revision: str = "455_feature_search_keys"
down_revision: str | Sequence[str] | None = "454_route_cluster_markers"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SCHEMA_OWNER: Final[str] = "ktm_feature_schema_owner"

_CREATE_SEARCH_KEYS_SQL: Final[str] = """
CREATE TABLE feature.feature_search_keys (
    feature_id uuid NOT NULL,
    keys_version bigint NOT NULL,
    server_fingerprint text NOT NULL,
    name text NOT NULL,
    category text NOT NULL,
    compact_name text,
    compact_raw_name text,
    compact_tail text,
    compact_base_name text,
    compact_paren_base_name text,
    compact_bracket_name text,
    search_group smallint NOT NULL,
    computed_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT pk_feature_search_keys PRIMARY KEY (feature_id),
    CONSTRAINT ck_feature_search_keys_group CHECK (search_group BETWEEN 0 AND 9)
)
"""

_OWNER_SEARCH_KEYS_SQL: Final[str] = (
    "ALTER TABLE feature.feature_search_keys OWNER TO " + _SCHEMA_OWNER
)

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
        '449_tourapi_festivals_primary',
        '450_incheon_airport_search_alias',
        '451_feature_search_prominence',
        '452_lotte_hotel_search_alias',
        '453_features_autovacuum',
        '454_route_cluster_markers',
        '455_feature_search_keys'
    ))
"""


#: 실행 순서대로의 upgrade 문장. 창은 소유자 롤로 열고 같은 롤로 끝난다(451과 같다).
_UPGRADE_STATEMENTS: Final[tuple[str, ...]] = (
    "SET ROLE " + _SCHEMA_OWNER,
    _CREATE_SEARCH_KEYS_SQL,
    _OWNER_SEARCH_KEYS_SQL,
    _RECEIPT_HEAD_CHECK_SQL,
    "SET ROLE " + _SCHEMA_OWNER,
)


def upgrade() -> None:
    """검색 비교 키 표를 만들고 receipt head CHECK에 455를 더한다(채우기는 maintenance job)."""
    bind = op.get_bind()
    settings = {
        str(name): str(value)
        for name, value in bind.execute(
            text(
                "SELECT name,setting FROM pg_settings "
                "WHERE name IN ('lock_timeout','statement_timeout')"
            )
        ).all()
    }
    for name, cap in (("lock_timeout", 1000), ("statement_timeout", 30000)):
        prior = int(settings[name])
        bind.execute(
            text("SELECT set_config(:name,:value,true)"),
            {"name": name, "value": str(min(prior, cap) if prior else cap)},
        )
    for statement in _UPGRADE_STATEMENTS:
        bind.execute(text(statement))
    for name, value in settings.items():
        bind.execute(text("SELECT set_config(:name,:value,true)"), {"name": name, "value": value})
    bind.execute(text("SET ROLE " + _SCHEMA_OWNER))


def downgrade() -> None:
    """되돌리지 않는다 — 비교 키 표는 forward revision으로만 걷는다."""
    raise RuntimeError(
        "455_feature_search_keys is forward-only: 비교 키 표는 forward revision으로만 걷는다."
    )
