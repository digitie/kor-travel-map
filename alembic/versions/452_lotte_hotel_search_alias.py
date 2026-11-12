"""롯데호텔 서울의 인허가 상호를 검색 별칭으로 더한다 — 2026-11-12 접기 회귀 후속.

Revision ID: 452_lotte_hotel_search_alias
Revises: 451_feature_search_prominence

왜 필요한가. 서울 중구 을지로의 롯데호텔은 MOIS 숙박 인허가(03010100)에 상호 "호텔롯데"로 실려
있어 "롯데호텔 서울"로 찾으면 MCST 촬영지 행(01000000, 관광)만 나왔다. 별칭이 그 숙박 행을 앞에
둔다. prod 2026-11-12 실측: 이름이 "호텔롯데"인 공개 행은 같은 자리(126.98109, 37.56481)의 숙박·
식음 두 행뿐이다(다른 도시 지점은 "롯데호텔 부산" 등 다른 이름) — 별칭이 엉뚱한 도시를 끌어오지
않는다. 두 행은 같은 이름·같은 자리라 검색 접기가 숙박 행 하나로 낸다.

**덧붙이기만 한다.** ``ON CONFLICT (alias) DO NOTHING``.

잠금. 별칭 표 INSERT(행 잠금)와 receipt 표 CHECK 교체(``ACCESS EXCLUSIVE``, 작은 표)뿐이다 —
``lock_timeout`` 1초, ``statement_timeout`` 30초. 마지막 문장은
``SET ROLE ktm_feature_schema_owner``다.

forward-only.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Final

from sqlalchemy import text

from alembic import op

revision: str = "452_lotte_hotel_search_alias"
down_revision: str | Sequence[str] | None = "451_feature_search_prominence"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SCHEMA_OWNER: Final[str] = "ktm_feature_schema_owner"

#: (정규화한 검색어, 정식 이름, 메모). 검색어는 ``feature_repo.search_alias_key`` 형식이다
#: (436 CHECK).
LOTTE_HOTEL_ALIASES: Final[tuple[tuple[str, str, str], ...]] = (
    ("롯데호텔서울", "호텔롯데", "통칭. MOIS 숙박 인허가 상호(서울 중구 을지로 30)"),
)


def _literal(value: str) -> str:
    # 값은 위 상수뿐이다 — 따옴표·역슬래시·콜론(``text()`` bind 표식)이면 거부한다.
    if "'" in value or "\\" in value or ":" in value:
        raise ValueError(f"alias seed value is not SQL-literal safe: {value!r}")
    return f"'{value}'"


_SEED_ALIASES_SQL: Final[str] = (
    "INSERT INTO feature.feature_search_aliases (alias, canonical_name, note)\nVALUES\n"
    + ",\n".join(
        f"    ({_literal(alias)}, {_literal(name)}, {_literal(note)})"
        for alias, name, note in LOTTE_HOTEL_ALIASES
    )
    + "\nON CONFLICT (alias) DO NOTHING"
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
        '452_lotte_hotel_search_alias'
    ))
"""


#: 실행 순서대로의 upgrade 문장. 창은 소유자 롤로 열고 같은 롤로 끝난다(436·444와 같다).
_UPGRADE_STATEMENTS: Final[tuple[str, ...]] = (
    "SET ROLE " + _SCHEMA_OWNER,
    _SEED_ALIASES_SQL,
    _RECEIPT_HEAD_CHECK_SQL,
    "SET ROLE " + _SCHEMA_OWNER,
)


def upgrade() -> None:
    """롯데호텔 서울 별칭을 덧붙이고 receipt head CHECK에 452를 더한다."""
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
    """되돌리지 않는다 — 별칭은 forward revision으로만 걷는다."""
    raise RuntimeError(
        "452_lotte_hotel_search_alias is forward-only: 별칭은 forward revision으로만 걷는다."
    )
