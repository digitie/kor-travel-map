"""장소 속성 catalog와 MCST 테마 목록 붙임 판정 표(ADR-121).

Revision ID: 446_mcst_place_attributes
Revises: 444_trip_search_aliases

왜 필요한가. MCST 테마 목록(반려동물 동반·무장애·가족/영유아·서점 유형·세계음식)은 장소의
**속성**이다. ADR-121은 속성을 별도 상태로 두지 않고 source link에서 유도한다 — Feature에 걸린
``primary``/``enrichment`` link의 (dataset, entity 유형)이 속성에 묶여 있으면 그 속성을 가진다.
이 revision은 그 묶음과 공개 catalog, 그리고 apply 모드 적재가 남기는 행별 판정 표를 만든다.
Feature 표·link 표는 건드리지 않는다.

무엇을 하는가.

- ``feature.place_attributes``: 공개 속성 catalog(코드·라벨·묶음·공개 범위·순서). 8개를 심는다.
  런타임 SELECT는 배포 조정기(``infra/runtime_privileges.py`` ``_FEATURE_TABLE_PRIVILEGES``)가 건다.
- ``feature.dataset_place_attributes``: (provider_dataset_id, source_entity_type) →
  attribute_code. MCST 8개 dataset의 ``culture_place`` 유형을 심는다. dataset 행이 없는 환경이면
  그 묶음은 조용히 빠진다(``INSERT … SELECT``). 속성 소속을 정하는 표라 ``feature`` schema에 두고
  런타임은 SELECT만 받는다(``provider_sync``는 런타임 DML이 기본이다 — 적대 리뷰).
- ``provider_sync.theme_attach_decisions``: apply 모드 적재의 행별 판정(근거 보관용 — link가
  정본). dataset별 snapshot과 같이 움직인다.
- receipt head CHECK에 이 revision을 더한다.

촬영지(``mcst_media_famous_places_csv``)는 속성이 아니다(ADR-121 D3 — 큐레이션).

번호. 445는 TourAPI 문화시설·레포츠 적재(#1467)가 잡는다(2026-11-10 조율). 이 revision은 446이고
머지 시점의 main head에 잇는다.

잠금. 새 표 셋을 만들고 receipt 표 CHECK만 교체한다(``ACCESS EXCLUSIVE``) — ``lock_timeout`` 1초,
``statement_timeout`` 30초로 묶는다. 새 표의 FK는 ``provider_datasets``를 참조하므로 그 표에
``SHARE ROW EXCLUSIVE``를 잠깐 잡는다(작은 catalog 표).

forward-only. downgrade는 두지 않는다. 되돌릴 일이 생기면 forward revision으로 표를 지운다 —
속성 필터가 빈 결과를 낼 뿐 Feature는 그대로다.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Final

from sqlalchemy import text

from alembic import op

revision: str = "446_mcst_place_attributes"
down_revision: str | Sequence[str] | None = "444_trip_search_aliases"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SCHEMA_OWNER: Final[str] = "ktm_feature_schema_owner"

#: (코드, 라벨, 묶음, 순서). ``kortravelmap.providers.mcst.MCST_FILE_DATASETS``의
#: ``attribute_code``와 같아야 한다(unit test가 대조한다). migration은 앱 코드를 import하지
#: 않으므로 값을 여기 고정한다.
PLACE_ATTRIBUTES: Final[tuple[tuple[str, str, str, int], ...]] = (
    ("pet_friendly", "반려동물 동반 가능", "companion", 10),
    ("family_friendly", "영유아·가족 동반 편의", "companion", 20),
    ("barrier_free", "무장애 편의", "accessibility", 30),
    ("bookstore_independent", "독립서점", "bookstore", 40),
    ("bookstore_cafe", "북카페", "bookstore", 50),
    ("bookstore_children", "아동서점", "bookstore", 60),
    ("bookstore_used", "중고서점", "bookstore", 70),
    ("world_cuisine", "세계음식", "cuisine", 80),
)

#: (dataset_key, source_entity_type, attribute_code). provider는 ``python-mcst-api``.
DATASET_ATTRIBUTES: Final[tuple[tuple[str, str, str], ...]] = (
    ("mcst_pet_friendly_culture_facilities_csv", "culture_place", "pet_friendly"),
    ("mcst_family_infant_culture_facilities_csv", "culture_place", "family_friendly"),
    ("mcst_barrier_free_places_csv", "culture_place", "barrier_free"),
    ("mcst_independent_bookstores_csv", "culture_place", "bookstore_independent"),
    ("mcst_cafe_bookstores_csv", "culture_place", "bookstore_cafe"),
    ("mcst_children_bookstores_csv", "culture_place", "bookstore_children"),
    ("mcst_used_bookstores_csv", "culture_place", "bookstore_used"),
    ("mcst_world_restaurants_csv", "culture_place", "world_cuisine"),
)


def _literal(value: str) -> str:
    # 값은 위 상수뿐이다 — 따옴표·역슬래시·콜론(``text()`` bind 표식)이면 거부한다.
    if "'" in value or "\\" in value or ":" in value:
        raise ValueError(f"seed value is not SQL-literal safe: {value!r}")
    return f"'{value}'"


_CREATE_PLACE_ATTRIBUTES_SQL: Final[str] = """
CREATE TABLE feature.place_attributes (
    attribute_code text NOT NULL,
    label_ko text NOT NULL,
    attribute_group text NOT NULL,
    visibility text DEFAULT 'public' NOT NULL,
    sort_order integer DEFAULT 0 NOT NULL,
    CONSTRAINT pk_place_attributes PRIMARY KEY (attribute_code),
    CONSTRAINT ck_place_attributes_code CHECK (attribute_code ~ '^[a-z][a-z0-9_]{1,47}$'),
    CONSTRAINT ck_place_attributes_label CHECK (label_ko <> '' AND char_length(label_ko) <= 100),
    CONSTRAINT ck_place_attributes_group CHECK (
        attribute_group IN ('companion', 'accessibility', 'bookstore', 'cuisine')
    ),
    CONSTRAINT ck_place_attributes_visibility CHECK (visibility IN ('public', 'admin_only'))
)
"""

_CREATE_DATASET_ATTRIBUTES_SQL: Final[str] = """
CREATE TABLE feature.dataset_place_attributes (
    provider_dataset_id bigint NOT NULL,
    source_entity_type text NOT NULL,
    attribute_code text NOT NULL,
    CONSTRAINT pk_dataset_place_attributes
        PRIMARY KEY (provider_dataset_id, source_entity_type, attribute_code),
    CONSTRAINT fk_dataset_place_attributes_provider_dataset_id_provider_datasets
        FOREIGN KEY (provider_dataset_id)
        REFERENCES provider_sync.provider_datasets (provider_dataset_id) ON DELETE CASCADE,
    CONSTRAINT fk_dataset_place_attributes_attribute_code_place_attributes
        FOREIGN KEY (attribute_code)
        REFERENCES feature.place_attributes (attribute_code) ON DELETE CASCADE
)
"""

_CREATE_DECISIONS_SQL: Final[str] = """
CREATE TABLE provider_sync.theme_attach_decisions (
    provider_dataset_id bigint NOT NULL,
    natural_key text NOT NULL,
    state text NOT NULL,
    target_feature_id uuid,
    rule_version text NOT NULL,
    evidence jsonb DEFAULT '{}'::jsonb NOT NULL,
    decided_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT pk_theme_attach_decisions PRIMARY KEY (provider_dataset_id, natural_key),
    CONSTRAINT fk_theme_attach_decisions_provider_dataset_id_provider_datasets
        FOREIGN KEY (provider_dataset_id)
        REFERENCES provider_sync.provider_datasets (provider_dataset_id) ON DELETE CASCADE,
    CONSTRAINT ck_theme_attach_decisions_state CHECK (
        state IN ('owner', 'matched', 'sticky', 'redirected', 'created', 'ambiguous', 'unresolved')
    ),
    CONSTRAINT ck_theme_attach_decisions_target CHECK (
        (state IN ('ambiguous', 'unresolved')) = (target_feature_id IS NULL)
    ),
    CONSTRAINT ck_theme_attach_decisions_evidence CHECK (jsonb_typeof(evidence) = 'object')
)
"""

_OWNER_SQL: Final[tuple[str, ...]] = (
    "ALTER TABLE feature.place_attributes OWNER TO " + _SCHEMA_OWNER,
    "ALTER TABLE feature.dataset_place_attributes OWNER TO " + _SCHEMA_OWNER,
    "ALTER TABLE provider_sync.theme_attach_decisions OWNER TO " + _SCHEMA_OWNER,
)

_SEED_PLACE_ATTRIBUTES_SQL: Final[str] = (
    "INSERT INTO feature.place_attributes (attribute_code, label_ko, attribute_group, sort_order)\n"
    "VALUES\n"
    + ",\n".join(
        f"    ({_literal(code)}, {_literal(label)}, {_literal(group)}, {order})"
        for code, label, group, order in PLACE_ATTRIBUTES
    )
)

_SEED_DATASET_ATTRIBUTES_SQL: Final[str] = (
    "INSERT INTO feature.dataset_place_attributes "
    "(provider_dataset_id, source_entity_type, attribute_code)\n"
    "SELECT dataset.provider_dataset_id, seed.source_entity_type, seed.attribute_code\n"
    "FROM (VALUES\n"
    + ",\n".join(
        f"    ({_literal(key)}, {_literal(entity_type)}, {_literal(code)})"
        for key, entity_type, code in DATASET_ATTRIBUTES
    )
    + "\n) AS seed(dataset_key, source_entity_type, attribute_code)\n"
    "JOIN provider_sync.provider_datasets AS dataset\n"
    "  ON dataset.provider = 'python-mcst-api' AND dataset.dataset_key = seed.dataset_key"
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
        '446_mcst_place_attributes'
    ))
"""


#: 실행 순서대로의 upgrade 문장. 창은 소유자 롤로 열고 같은 롤로 끝난다(436과 같다).
_UPGRADE_STATEMENTS: Final[tuple[str, ...]] = (
    "SET ROLE " + _SCHEMA_OWNER,
    _CREATE_PLACE_ATTRIBUTES_SQL,
    _CREATE_DATASET_ATTRIBUTES_SQL,
    _CREATE_DECISIONS_SQL,
    *_OWNER_SQL,
    _SEED_PLACE_ATTRIBUTES_SQL,
    _SEED_DATASET_ATTRIBUTES_SQL,
    _RECEIPT_HEAD_CHECK_SQL,
    "SET ROLE " + _SCHEMA_OWNER,
)


def upgrade() -> None:
    """속성 catalog·dataset 묶음·판정 표를 만들고 receipt head CHECK에 446을 더한다."""
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
    """되돌리지 않는다 — 표는 forward revision으로만 지운다."""
    raise RuntimeError(
        "446_mcst_place_attributes is forward-only: 표는 forward revision으로만 지운다."
    )
