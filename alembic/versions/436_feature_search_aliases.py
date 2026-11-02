"""검색 별칭 표 ``feature.feature_search_aliases``를 만들고 첫 별칭을 심는다.

Revision ID: 436_feature_search_aliases
Revises: 435_retire_sh_snapshot_path

왜 필요한가. 사람들이 부르는 이름과 공공 데이터의 정식 이름이 다르다 — "고씨동굴"은 국가유산
데이터에 "영월 고씨굴"로 있어 trigram 유사도가 문턱(0.2)에 겨우 걸리고, "하회마을"은 서울의 같은
이름 음식점 셋에 가린다(2026-11 PinVi live e2e). 이 표가 "이 검색어는 이 이름의 Feature를 뜻한다"를
담고, ``/v1/features/search``는 별칭이 가리키는 이름과 **정확히 같은** 공개 Feature를 맨 앞 순위로
후보에 더한다(``infra/feature_repo.py``).

왜 Feature id가 아니라 이름인가. Feature id(uuid)는 적재마다 새로 생기고 환경마다 다르며
병합·퇴역으로 바뀐다 — migration이 id를 심을 수 없다. 이름은 환경과 무관하고 재적재를 견딘다.
같은 이름의 공개 Feature가 여럿이면 모두 별칭 순위를 얻고, 그 안에서 분류·유사도 순이다.
대상 이름이 데이터에서 바뀌면 별칭은 조용히 아무것도 더하지 않는다
(검색 결과는 별칭이 없을 때와 같다).

``feature_aliases``(T-VN-32A)와 다른 표인 이유: 그쪽은 legacy ``f_*`` → uuid **식별자** 별칭이고
PinVi alias-map 체크섬 계약(``feature-alias-map-v1``)의 입력이다. 검색어를 섞으면 그 계약이 깨진다.

무엇을 하는가.

- ``alias``(PK): 정규화한 검색어 — NFC, 공백(Python ``str.isspace()`` 집합) 제거, 소문자.
  CHECK가 그 형식을 고정한다(형식이 틀린 행은 조회 키와 영영 같아지지 않아 조용히 죽는다).
  정규화 정본은 ``feature_repo.search_alias_key``다.
- ``canonical_name``: 별칭이 가리키는 ``features.name``(NFC, 앞뒤 공백 없음).
- 소유자 ``ktm_feature_schema_owner``. 런타임 SELECT는 배포 조정기
  (``infra/runtime_privileges.py`` ``_FEATURE_TABLE_PRIVILEGES``)가 건다.
- 첫 별칭 4개: 고씨동굴·영월고씨동굴 → "영월 고씨굴", 하회마을·하회민속마을 → "안동하회마을"
  (prod 2026-11-02 실측 이름).
- receipt head CHECK에 이 revision을 더한다.

잠금. 새 표를 만들 뿐 기존 Feature 표를 잠그지 않는다(FK 없음). receipt 표 CHECK 교체만
``ACCESS EXCLUSIVE``를 잡으므로 ``lock_timeout``을 1초, ``statement_timeout``을 30초로 묶는다.

forward-only. downgrade는 두지 않는다(``alembic/env.py``가 모든 downgrade를 해석 전에 거부한다).
되돌릴 일이 생기면 forward revision으로 표를 지운다 — 검색이 별칭 없는 순위로 돌아갈 뿐이다.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Final

from sqlalchemy import text

from alembic import op

revision: str = "436_feature_search_aliases"
down_revision: str | Sequence[str] | None = "435_retire_sh_snapshot_path"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: 스키마 소유자. env가 켠 롤이고, 마이그레이션은 이 롤로 끝나야 한다.
_SCHEMA_OWNER: Final[str] = "ktm_feature_schema_owner"

#: 별칭 키에 있으면 안 되는 공백 — Python ``str.isspace()``가 참인 문자 전부.
#: ``feature_repo.SEARCH_WHITESPACE_CODEPOINTS``와 같아야 한다(unit test가 대조한다). migration은
#: 앱 코드를 import하지 않으므로 값을 여기 고정한다.
_WHITESPACE_CODEPOINTS: Final[tuple[int, ...]] = (
    0x09, 0x0A, 0x0B, 0x0C, 0x0D, 0x1C, 0x1D, 0x1E, 0x1F, 0x20, 0x85, 0xA0, 0x1680,
    0x2000, 0x2001, 0x2002, 0x2003, 0x2004, 0x2005, 0x2006, 0x2007, 0x2008, 0x2009, 0x200A,
    0x2028, 0x2029, 0x202F, 0x205F, 0x3000,
)  # fmt: skip
_WHITESPACE_SQL: Final[str] = (
    "(" + " || ".join(f"chr({codepoint})" for codepoint in _WHITESPACE_CODEPOINTS) + ")"
)

_CREATE_ALIASES_SQL: Final[str] = f"""
CREATE TABLE feature.feature_search_aliases (
    alias text NOT NULL,
    canonical_name text NOT NULL,
    note text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT pk_feature_search_aliases PRIMARY KEY (alias),
    CONSTRAINT ck_feature_search_aliases_alias_key CHECK (
        alias <> ''
        AND char_length(alias) <= 200
        AND alias = translate(alias, {_WHITESPACE_SQL}, '')
        AND alias = lower(alias)
        AND alias IS NFC NORMALIZED
    ),
    CONSTRAINT ck_feature_search_aliases_canonical_name CHECK (
        canonical_name <> ''
        AND char_length(canonical_name) <= 500
        AND canonical_name = btrim(canonical_name, {_WHITESPACE_SQL})
        AND canonical_name IS NFC NORMALIZED
    )
)
"""

_OWNER_ALIASES_SQL: Final[str] = (
    "ALTER TABLE feature.feature_search_aliases OWNER TO " + _SCHEMA_OWNER
)

_SEED_ALIASES_SQL: Final[str] = """
INSERT INTO feature.feature_search_aliases (alias, canonical_name, note)
VALUES
    ('고씨동굴', '영월 고씨굴', '통칭. 국가유산 천연기념물 정식 명칭은 영월 고씨굴'),
    ('영월고씨동굴', '영월 고씨굴', '통칭. 국가유산 천연기념물 정식 명칭은 영월 고씨굴'),
    ('하회마을', '안동하회마을', '같은 이름 음식점보다 안동 하회마을을 먼저 보인다'),
    ('하회민속마을', '안동하회마을', '통칭')
"""

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
        '436_feature_search_aliases'
    ))
"""

#: 실행 순서대로의 upgrade 문장. 창은 소유자 롤로 열고 같은 롤로 끝난다 — env가 켠
#: 스키마 소유자 롤과 같으므로 alembic의 ``UPDATE alembic_version``도 그대로 산다.
_UPGRADE_STATEMENTS: Final[tuple[str, ...]] = (
    "SET ROLE " + _SCHEMA_OWNER,
    _CREATE_ALIASES_SQL,
    _OWNER_ALIASES_SQL,
    _SEED_ALIASES_SQL,
    _RECEIPT_HEAD_CHECK_SQL,
    "SET ROLE " + _SCHEMA_OWNER,
)


def upgrade() -> None:
    """별칭 표를 만들고 첫 별칭을 심은 뒤 receipt head CHECK에 436을 더한다."""
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
    """되돌리지 않는다 — 별칭 표는 forward revision으로만 걷는다."""
    raise RuntimeError(
        "436_feature_search_aliases is forward-only: 별칭 표는 forward revision으로만 걷는다."
    )
