"""관리자 Feature 부분 검색용 비부분 trigram 인덱스 — #1475.

Revision ID: 445_admin_search_trgm_indexes
Revises: 444_trip_search_aliases

왜 필요한가. ``GET /v1/admin/features?q=…``가 유휴에 가까운 prod에서도 3~12 s 걸렸다(#1475,
D2 live acceptance cleanup이 이 호출을 쓴다). 계획은 ``lower(name)`` keyset 인덱스로 Feature
36만 행을 걸으며 행마다 ILIKE·상관 서브쿼리를 평가했고, 일치가 드문 q일수록 끝까지 갔다.
공개 ``idx_features_name_trgm``은 공개 3축 **부분** 인덱스라 상태 무필터인 admin 검색이 쓸 수
없다(0098 설계 주석). 그래서 admin 검색 갈래마다 **비부분** trigram 인덱스를 둔다 —
``admin_feature_repo``가 일치 후보를 이 인덱스로 먼저 모으고(드문 q), 후보가 많으면 종전처럼
훑는다(흔한 q).

인덱스 식은 ``admin_feature_repo._ADMIN_FEATURES_Q_*_ARMS``의 술어 식과 글자 그대로 같다.

- ``feature.features (lower(name))`` — 공개 부분 인덱스(``name``)와 식이 달라 공개 검색의
  계획 선택을 흔들지 않는다(0098이 전체/부분 공존으로 공개 보증이 깨진 선례를 남겼다).
- ``feature.features ((feature_id)::text)`` — uuid 조각 검색.
- ``feature.features ((address)::text)`` — 주소 jsonb 전체 text(종전 술어 그대로).
- ``feature.feature_aliases (alias)`` — legacy ``f_*`` 조각.
- ``provider_sync.source_entities (source_entity_id)``
- ``provider_sync.source_entity_heads (current_source_record_key)`` — 현재 record key는 head가
  들고 있다. 옛 record까지 담은 source_records에 두지 않는다.

원천 JSON 본문(``source_records.raw_data::text``)에는 두지 않는다 — 검색에서 그 갈래를 뺐다
(prod 505 MB, trigram 1.4억 posting 추정, 적재마다 쓰기 증폭).

잠금. ``CREATE INDEX``는 대상 표에 ``SHARE``를 잡는다 — 읽기는 막지 않고 쓰기만 빌드 동안
막는다. ``CONCURRENTLY``는 쓰지 않는다: 이 저장소 migration은 한 transaction이고(0083·0085
선례 — autocommit_block 중간 커밋은 재시도 불가한 반쪽 상태를 남긴다), 통합 fixture가 바깥
transaction 안에서 돈다. 여섯 인덱스의 ``SHARE``는 commit까지 이어지므로 네 표
(``features``·``feature_aliases``·``source_entities``·``source_entity_heads``)의 쓰기는 빌드
내내 기다린다 — 배포 동안 Feature 적재(큐)를 멈춰 두는 것이 안전하다.

``lock_timeout``은 60초다. ``SHARE``는 읽기(``ACCESS SHARE``)와 충돌하지 않으므로 줄을 서는
동안 막히는 것은 뒤따르는 쓰기뿐이다. 1초(444)로 묶으면 진행 중인 적재 transaction 하나에
배포가 실패한다. ``statement_timeout``은 빌드를 감당하도록 300초로 묶는다.

빌드 실측(prod 열 복사본 38만 행, n150 PG18 tmpfs, maintenance_work_mem 256 MB, 병렬 2):
``lower(name)`` 3.4 s, ``feature_id`` 3.2 s, ``address`` 12.6 s, alias 1.7 s, entity id 2.8 s,
record key 1.7 s — 합 25 s, 크기 합 272 MB. 디스크 위 prod는 2~3배(50~75 s)로 잡는다.

forward-only. downgrade는 두지 않는다(``alembic/env.py``가 모든 downgrade를 거부한다).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Final

from sqlalchemy import text

from alembic import op

revision: str = "445_admin_search_trgm_indexes"
down_revision: str | Sequence[str] | None = "444_trip_search_aliases"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: 스키마 소유자. env가 켠 롤이고, 마이그레이션은 이 롤로 끝나야 한다.
_SCHEMA_OWNER: Final[str] = "ktm_feature_schema_owner"

#: (인덱스 이름, 표, 인덱스 식). 식은 검색 SQL의 술어 식과 같아야 한다.
ADMIN_SEARCH_TRGM_INDEXES: Final[tuple[tuple[str, str, str], ...]] = (
    ("idx_features_admin_lower_name_trgm", "feature.features", "lower(name)"),
    ("idx_features_admin_feature_id_trgm", "feature.features", "(feature_id::text)"),
    ("idx_features_admin_address_trgm", "feature.features", "(address::text)"),
    ("idx_feature_aliases_alias_trgm", "feature.feature_aliases", "alias"),
    (
        "idx_source_entities_source_entity_id_trgm",
        "provider_sync.source_entities",
        "source_entity_id",
    ),
    (
        "idx_source_entity_heads_record_key_trgm",
        "provider_sync.source_entity_heads",
        "current_source_record_key",
    ),
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
        '445_admin_search_trgm_indexes'
    ))
"""


def _create_index_sql(name: str, table: str, expression: str) -> str:
    return (
        f"CREATE INDEX {name} ON {table} "
        f"USING gin ({expression} x_extension.gin_trgm_ops)"
    )


#: 실행 순서대로의 upgrade 문장. 창은 소유자 롤로 열고 같은 롤로 끝난다(436과 같다).
_UPGRADE_STATEMENTS: Final[tuple[str, ...]] = (
    "SET ROLE " + _SCHEMA_OWNER,
    *(_create_index_sql(*index) for index in ADMIN_SEARCH_TRGM_INDEXES),
    _RECEIPT_HEAD_CHECK_SQL,
    "SET ROLE " + _SCHEMA_OWNER,
)


def upgrade() -> None:
    """admin 검색 trigram 인덱스를 만들고 receipt head CHECK에 445를 더한다."""
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
    for name, cap in (("lock_timeout", 60000), ("statement_timeout", 300000)):
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
    """되돌리지 않는다 — 인덱스는 forward revision으로만 걷는다."""
    raise RuntimeError(
        "445_admin_search_trgm_indexes is forward-only: 인덱스는 forward revision으로만 걷는다."
    )
