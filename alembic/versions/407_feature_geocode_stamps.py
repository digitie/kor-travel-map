"""Feature별 지오코딩 스탬프 표 ``feature.feature_geocode_stamps``를 만든다(ADR-109 결정 1).

Revision ID: 407_feature_geocode_stamps
Revises: 406_feature_write_gate

왜 필요한가. Map은 kor-travel-geo가 유도한 주소 값(``address`` jsonb·``legal_dong_code`` 등)을
저장하지만 **어느 geo 데이터로 해석됐는지**는 어디에도 남기지 않는다. geo가 주소 DB를 새 릴리스로
바꿔도 Map은 알 수 없고, 알아도 어느 행을 다시 맞춰야 하는지 고를 수 없다. 이 표가 행마다
"어느 데이터 지문(``geo_data_token``, geo ADR-069의 ``dd1-``)으로 지오코딩했는가"를 기록한다.

왜 ``features``의 열이 아니라 별도 표인가. ``features`` 열이나 ``address`` jsonb 키로 두면 스탬프
갱신이 ``row_revision``을 전진시키고(``apply_provider_feature_field_patch``는 값이 같아도 +1),
``row_revision``은 ETag·``If-Match``·curation seal·PinVi cache target generation의 입력이다 — 값이
그대로인 재해석이 그 모두를 흔든다.

무엇을 하는가.

- ``feature.feature_geocode_stamps(feature_id uuid PK FK → features ON DELETE CASCADE,
  geo_version_token, geo_data_token, reverse_outcome, stamped_at)``. 두 토큰 열은 **NOT NULL**이다 —
  NULL 토큰 스탬프는 만들지 않는다(run의 현재 토큰이 없으면 쓰지도 덮지도 않는다, ADR-109 결정 1·2).
  토큰 형식은 geo 계약(``dv1-``/``dd1-`` + 32 lowercase hex)을 CHECK로 고정한다 — 형식이 틀린 값이
  비교 키로 들어가면 모든 행이 영구 stale이 된다.
- ``reverse_outcome``은 ``called|geocoded|not_called`` 셋이다(판정 규칙은
  ``docs/etl/address-geocoding.md`` §2).
- ``geo_data_token`` 인덱스 — 릴리스 계획(T-GR-04)이 "현재 토큰과 다른 행"을 고른다.
- 소유자 ``ktm_feature_schema_owner``. 런타임 권한은 이 마이그레이션이 아니라 배포 조정기
  (``infra/runtime_privileges.py`` ``_FEATURE_TABLE_PRIVILEGES``)가 건다.
- receipt head CHECK에 이 revision을 더한다(401~406과 같은 계약).

forward-only. downgrade는 두지 않는다(ADR-021·ADR-102 — ``alembic/env.py``가 모든 downgrade를
해석 전에 거부한다). 되돌릴 일이 생기면 forward revision으로 표를 지운다 — 지워지는 것은
스탬프뿐이고 스탬프 부재는 stale로 읽히므로(ADR-109 결정 1) 잃는 것이 없다.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Final

from sqlalchemy import text

from alembic import op

# ruff: noqa: E501

revision: str = "407_feature_geocode_stamps"
down_revision: str | Sequence[str] | None = "406_feature_write_gate"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: 스키마 소유자. env가 켠 롤이고, 마이그레이션은 이 롤로 끝나야 한다.
_SCHEMA_OWNER_ROLE: Final[str] = "ktm_feature_schema_owner"

_SET_OWNER_ROLE_SQL: Final[str] = f"SET ROLE {_SCHEMA_OWNER_ROLE}"

_CREATE_STAMPS_SQL: Final[str] = """
CREATE TABLE feature.feature_geocode_stamps (
    feature_id uuid NOT NULL,
    geo_version_token text NOT NULL,
    geo_data_token text NOT NULL,
    reverse_outcome text NOT NULL,
    stamped_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT pk_feature_geocode_stamps PRIMARY KEY (feature_id),
    CONSTRAINT fk_feature_geocode_stamps_feature FOREIGN KEY (feature_id)
        REFERENCES feature.features(feature_id) ON DELETE CASCADE,
    CONSTRAINT ck_feature_geocode_stamps_reverse_outcome
        CHECK (reverse_outcome IN ('called', 'geocoded', 'not_called')),
    CONSTRAINT ck_feature_geocode_stamps_version_token
        CHECK (geo_version_token ~ '^dv1-[0-9a-f]{32}$'),
    CONSTRAINT ck_feature_geocode_stamps_data_token
        CHECK (geo_data_token ~ '^dd1-[0-9a-f]{32}$')
)
"""

_OWNER_STAMPS_SQL: Final[str] = (
    f"ALTER TABLE feature.feature_geocode_stamps OWNER TO {_SCHEMA_OWNER_ROLE}"
)

_INDEX_DATA_TOKEN_SQL: Final[str] = (
    "CREATE INDEX idx_feature_geocode_stamps_data_token "
    "ON feature.feature_geocode_stamps USING btree (geo_data_token)"
)

#: receipt head 값 열거 CHECK — graph의 **모든** revision(401과 같은 계약).
_RECEIPT_HEAD_CHECK_SQL: Final[str] = """
ALTER TABLE ops.application_schema_operation_receipts
    DROP CONSTRAINT ck_application_schema_operation_receipts_head,
    ADD CONSTRAINT ck_application_schema_operation_receipts_head CHECK (destination_head IN ('300', '301_m03_import_children', '302_m03_child_issuance', '303_m05_payload_hash_domain', '304_m05_detector_manuals', '305_m05_relitigation_fence', '306_m02_manual_feature_purge', '307_m02_truncate_fence', '308_t39_provider_identities', '309_t39_feature_id_rekey', '310_seoul_source_move', '311_seal_member_digest', '312_route_geometry_sidecar', '313_single_service_role', '400', '401_retire_map_kma_refresh', '402_remove_map_weather_data', '403_drop_kma_notice_lineage', '404_transport_provider_identity', '405_mois_freshness_sla', '406_feature_write_gate', '407_feature_geocode_stamps'))
"""

#: 실행 순서대로의 upgrade 문장. 창은 소유자 롤로 열고 같은 롤로 끝난다 — env가 켠
#: 스키마 소유자 롤과 같으므로 alembic의 ``UPDATE alembic_version``도 그대로 산다.
_UPGRADE_STATEMENTS: Final[tuple[str, ...]] = (
    _SET_OWNER_ROLE_SQL,
    _CREATE_STAMPS_SQL,
    _OWNER_STAMPS_SQL,
    _INDEX_DATA_TOKEN_SQL,
    _RECEIPT_HEAD_CHECK_SQL,
)


def upgrade() -> None:
    """스탬프 표·인덱스를 만들고 receipt head CHECK에 407을 더한다."""
    bind = op.get_bind()
    for statement in _UPGRADE_STATEMENTS:
        bind.execute(text(statement))


def downgrade() -> None:
    """되돌리지 않는다 — 스탬프 표는 forward revision으로만 걷는다."""
    raise RuntimeError(
        "407_feature_geocode_stamps is forward-only: 스탬프 표는 forward revision으로만 걷는다(ADR-109)."
    )
