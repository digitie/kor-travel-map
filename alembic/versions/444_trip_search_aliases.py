"""여행지 통칭을 검색 별칭으로 더한다 — #1459 여행 시나리오 후속.

Revision ID: 444_trip_search_aliases
Revises: 442_mois_brand_search_aliases

왜 필요한가. 사람들이 부르는 이름과 원천의 이름이 다르다(2026-11-08 PinVi 여행 시나리오
검증, #1459). 436이 만든 ``feature.feature_search_aliases``에 그 통칭을 더한다. 별칭은 Feature id가
아니라 **이름**을
가리키므로(436) 대상이 아직 적재되지 않았거나 이름이 바뀌면 조용히 아무것도 더하지 않는다.

정본 이름의 근거(2026-11-10 실측 — prod Map 읽기 전용, TourAPI KorService2 ``searchKeyword2``):

- 리움·리움미술관 → "삼성미술관 Leeum": prod ``datagokr_museums``·MCST 반려동물(서울 용산 11170).
  TourAPI는 "리움미술관"(문화시설 14)이라 그 원천이 적재되면 이름 검색만으로도 찾는다.
- 수성못 → "수성유원지": prod MCST 4개 dataset(대구 수성구 27260). TourAPI는 "수성못 유원지"(12).
- 김포공항 → "김포국제공항": prod ``transport_airports``(06050000, 서울 강서구 11500).
- 퍼플섬 → "반월도·박지도": TourAPI 관광지(12) contentid 578024, 신안군 안좌면. #1465
  (``visitkorea_attractions``) 적재 뒤에 닿는다 — 제목은 ``normalize_korean_text`` 그대로다.
- 사천바다케이블카·사천케이블카 → "사천바다 케이블카": TourAPI 관광지(12) contentid 2606216, 사천시
  사천대로 18. 같은 TourAPI 적재 뒤에 닿는다. "사천케이블카"만으로는 "사천케이블카자연휴양림"이
  먼저 걸리던 것을 케이블카 자체로 돌린다(휴양림은 이름이 검색어를 품으므로 여전히 결과에 있다).

**덧붙이기만 한다.** ``ON CONFLICT (alias) DO NOTHING`` — 다른 revision이 같은 검색어를 이미 다른
이름에 묶었으면 그쪽을 존중한다.

번호. 443은 TourAPI 문화시설·레포츠 적재가 잡는다(2026-11-10 조율) — 이 revision은 444이고 머지
시점의
main head에 잇는다.

잠금. 별칭 표 INSERT(행 잠금)와 receipt 표 CHECK 교체(``ACCESS EXCLUSIVE``)뿐이다 — 436·442와 같이
``lock_timeout`` 1초, ``statement_timeout`` 30초로 묶는다. Feature 표는 건드리지 않는다.

forward-only. 별칭을 걷을 일이 생기면 forward revision으로 지운다.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Final

from sqlalchemy import text

from alembic import op

revision: str = "444_trip_search_aliases"
down_revision: str | Sequence[str] | None = "442_mois_brand_search_aliases"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SCHEMA_OWNER: Final[str] = "ktm_feature_schema_owner"

#: (정규화한 검색어, 정식 이름, 메모). 검색어는 ``feature_repo.search_alias_key`` 형식이다
#: (436 CHECK).
TRIP_ALIASES: Final[tuple[tuple[str, str, str], ...]] = (
    ("리움", "삼성미술관 Leeum", "통칭. 서울 용산 이태원로55길 60-16"),
    ("리움미술관", "삼성미술관 Leeum", "통칭. TourAPI 제목은 리움미술관"),
    ("수성못", "수성유원지", "통칭. 대구 수성구 두산동"),
    ("김포공항", "김포국제공항", "통칭. 서울 강서구"),
    ("퍼플섬", "반월도·박지도", "통칭. 신안 안좌면, TourAPI 578024"),
    ("사천바다케이블카", "사천바다 케이블카", "TourAPI 2606216 제목의 붙여 쓴 형태"),
    ("사천케이블카", "사천바다 케이블카", "통칭. 사천케이블카자연휴양림과 다른 시설"),
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
        for alias, name, note in TRIP_ALIASES
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
        '444_trip_search_aliases'
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
    """여행지 통칭 별칭을 덧붙이고 receipt head CHECK에 444를 더한다."""
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
        "444_trip_search_aliases is forward-only: 별칭은 forward revision으로만 걷는다."
    )
