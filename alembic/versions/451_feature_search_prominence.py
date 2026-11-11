"""검색 인지도 표를 만든다 — 2026-11-11 검색 순위 점검 P6.

Revision ID: 451_feature_search_prominence
Revises: 450_incheon_airport_search_alias

왜 필요한가. 검색 순위의 모든 자리가 같은 행(같은 분류·같은 이름 일치)은 종전에 trigram 유사도와
``feature_id``가 갈랐다 — "신륵사"의 1위가 제천 신륵사였고 "강화 펜션"은 MOIS 인허가 대장에만 있는
펜션이 TourAPI·MCST가 소개한 펜션 앞에 섰다. 검색 인지도(0~9)를 Feature마다 미리 계산해 두고 검색
순위의 마지막 자리(유사도보다 앞)로 쓴다. 계산 규칙은 ``infra/search_prominence_repo.py``가
정본이다.

무엇을 하는가.

- ``feature.feature_search_prominence(feature_id PK, prominence 0~9, dataset_count, heritage_items,
  computed_at)``. 소유자 ``ktm_feature_schema_owner``. 런타임 권한(SELECT·INSERT·UPDATE·DELETE)은
  배포 조정기(``infra/runtime_privileges.py`` ``_FEATURE_TABLE_PRIVILEGES``)가 건다.
  ``feature.features`` FK는 두지 않는다 — Feature 쓰기·삭제 경로와 잠금을 엮지 않는다.
  사라진 Feature의 행은 다음 갱신이 지운다(검색은 공개 Feature만 읽으므로 남은 행은 영향이
  없다).
- receipt head CHECK에 이 revision을 더한다.

기존 행 채우기(backfill) — **이 migration은 표만 만든다.** 계산은 공개 place 전부(prod 2026-11-11
약 34만 행)를 읽는 집계라 migration의 ``statement_timeout``(30초) 안에 끝난다고 보장할 수 없다.

1. 배포 직후: 표가 비어 있으면 검색은 모든 행을 ``SEARCH_PROMINENCE_DEFAULT``(1)로 본다 — 인지도
   자리가 모든 행에서 같으므로 순위는 이 revision 전과 같다(안전한 퇴화).
2. 채우기: Dagster ``consistency_dedup_refresh`` job(매일 05:45 KST, dedup 갱신 뒤
   ``refresh_search_prominence`` op)이 채운다. 배포 뒤 바로 채우려면 그 job을 한 번 수동 실행한다.
3. 잠금·시간: ``feature.features``·``provider_sync.*``는 읽기만 한다(ACCESS SHARE — 적재·Feature
   쓰기를 막지 않는다). 쓰기는 이 표에만(첫 실행 약 34만 행 INSERT, 이후는 값이 바뀐 행만).
   prod 실측 계산 시간은 PR 본문·``docs/journal.md``에 적는다. op는 문장 상한 15분이다.

잠금(이 migration). 새 표를 만들 뿐 기존 표를 잠그지 않는다. receipt 표 CHECK 교체만
``ACCESS EXCLUSIVE``(작은 표)를 잡으므로 ``lock_timeout`` 1초, ``statement_timeout`` 30초로 묶는다.
마지막 문장은 ``SET ROLE ktm_feature_schema_owner``다(alembic_version UPDATE가 그 롤로 돈다).

forward-only. 되돌릴 일이 생기면 forward revision으로 표를 지운다 — 검색은 인지도 없는 순위로
돌아간다.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Final

from sqlalchemy import text

from alembic import op

revision: str = "451_feature_search_prominence"
down_revision: str | Sequence[str] | None = "450_incheon_airport_search_alias"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SCHEMA_OWNER: Final[str] = "ktm_feature_schema_owner"

_CREATE_PROMINENCE_SQL: Final[str] = """
CREATE TABLE feature.feature_search_prominence (
    feature_id uuid NOT NULL,
    prominence smallint NOT NULL,
    dataset_count smallint DEFAULT 0 NOT NULL,
    heritage_items smallint DEFAULT 0 NOT NULL,
    computed_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT pk_feature_search_prominence PRIMARY KEY (feature_id),
    CONSTRAINT ck_feature_search_prominence_range CHECK (prominence BETWEEN 0 AND 9),
    CONSTRAINT ck_feature_search_prominence_counts CHECK (
        dataset_count >= 0 AND heritage_items >= 0
    )
)
"""

_OWNER_PROMINENCE_SQL: Final[str] = (
    "ALTER TABLE feature.feature_search_prominence OWNER TO " + _SCHEMA_OWNER
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
        '451_feature_search_prominence'
    ))
"""


#: 실행 순서대로의 upgrade 문장. 창은 소유자 롤로 열고 같은 롤로 끝난다(436과 같다).
_UPGRADE_STATEMENTS: Final[tuple[str, ...]] = (
    "SET ROLE " + _SCHEMA_OWNER,
    _CREATE_PROMINENCE_SQL,
    _OWNER_PROMINENCE_SQL,
    _RECEIPT_HEAD_CHECK_SQL,
    "SET ROLE " + _SCHEMA_OWNER,
)


def upgrade() -> None:
    """검색 인지도 표를 만들고 receipt head CHECK에 451을 더한다(채우기는 maintenance job)."""
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
    """되돌리지 않는다 — 인지도 표는 forward revision으로만 걷는다."""
    raise RuntimeError(
        "451_feature_search_prominence is forward-only: 인지도 표는 forward revision으로만 걷는다."
    )
