"""숙박 브랜드 통칭을 검색 별칭으로 더한다(MOIS 법인 상호 ↔ 사람이 부르는 이름).

Revision ID: 442_mois_brand_search_aliases
Revises: 441_tourapi_attraction_dataset

왜 필요한가. MOIS 인허가의 사업장명은 법인 표기다. 적재기가 법인 접두(``(주)``·``주식회사``·
큐레이션 모회사 접두)를 걷어 표시 이름을 만들지만(``core/business_name.py``), 통칭이 정식
상호와 아예 다른 시설은 규칙으로 풀 수 없다 — "신라호텔"의 사업장명은 "호텔신라"이고, 통칭
"현대호텔 목포"는 "(주)라한호텔목포"다(2026-11-09 원천 실측·소유자 감사). 436이 만든 표에 그 통칭을
더한다. 값의 정본은 ``kortravelmap.core.business_name.CURATED_BRAND_SEARCH_ALIASES``다 — migration은
앱 코드를 import하지 않으므로 같은 값을 여기 고정하고, unit test가 둘(별칭 키·정식 이름)을 대조한다.

**덧붙이기만 한다.** ``ON CONFLICT (alias) DO NOTHING`` — 다른 revision이 같은 검색어를 이미 다른
이름에 묶었으면 그쪽을 존중한다(검색 순위 계약을 이 revision이 몰래 바꾸지 않는다).

잠금. 별칭 표 INSERT(행 잠금)와 receipt 표 CHECK 교체(``ACCESS EXCLUSIVE``)뿐이다 — 436과 같이
``lock_timeout`` 1초, ``statement_timeout`` 30초로 묶는다. Feature 표는 건드리지 않는다.

forward-only. 별칭을 걷을 일이 생기면 forward revision으로 지운다(검색이 별칭 없는 순위로 돌아갈
뿐이다).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Final

from sqlalchemy import text

from alembic import op

revision: str = "442_mois_brand_search_aliases"
down_revision: str | Sequence[str] | None = "441_tourapi_attraction_dataset"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SCHEMA_OWNER: Final[str] = "ktm_feature_schema_owner"

#: (정규화한 검색어, 정식 이름, 메모) — ``CURATED_BRAND_SEARCH_ALIASES``와 같아야 한다(unit test).
BRAND_ALIASES: Final[tuple[tuple[str, str, str], ...]] = (
    ("신라호텔", "호텔신라", "서울 중구 동호로 249 관광호텔. 법인 상호가 곧 사업장명"),
    ("서울신라호텔", "호텔신라", "통칭 — 서울 중구 동호로 249"),
    ("현대호텔목포", "라한호텔목포", "영암 삼호읍 대불로 91 — 통칭 현대호텔 목포"),
    ("호텔현대목포", "라한호텔목포", "옛 통칭 — 영암 삼호읍 대불로 91"),
    ("조선팰리스", "조선팰리스강남", "서울 강남 테헤란로 231 — 브랜드 조선 팰리스 서울 강남"),
    ("조선팰리스서울강남", "조선팰리스강남", "브랜드 정식 표기"),
    ("켄싱턴호텔설악", "켄싱턴호텔설악 스타", "속초 설악산로 998 관광호텔"),
    ("jw메리어트서울", "JW메리어트호텔서울", "서울 서초 신반포로 176 관광호텔"),
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
        for alias, name, note in BRAND_ALIASES
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
        '442_mois_brand_search_aliases'
    ))
"""


#: 실행 순서대로의 upgrade 문장. 창은 소유자 롤로 열고 같은 롤로 끝난다(436과 같다).
_UPGRADE_STATEMENTS: Final[tuple[str, ...]] = (
    "SET ROLE " + _SCHEMA_OWNER,
    _SEED_ALIASES_SQL,
    _RECEIPT_HEAD_CHECK_SQL,
    "SET ROLE " + _SCHEMA_OWNER,
)


def upgrade() -> None:
    """브랜드 통칭 별칭을 덧붙이고 receipt head CHECK에 442를 더한다."""
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
        "442_mois_brand_search_aliases is forward-only: 별칭은 forward revision으로만 걷는다."
    )
