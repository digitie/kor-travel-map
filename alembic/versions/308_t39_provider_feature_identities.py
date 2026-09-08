"""T-VN-39 ① — provider Feature identity를 담을 자리를 만든다.

Revision ID: 308_t39_provider_feature_identities
Revises: 307_m02_truncate_fence

## 재키의 본체는 재타입이 아니라 멱등 앵커 교체다

``feature.features.feature_id``를 uuid로 바꾸면 **둘 중 하나가 반드시 일어난다**:
provider가 계산한 ``f_*``를 그대로 보내면 22P02, 새 UUIDv7을 보내면
``create_feature_with_initial_state``의 ``ON CONFLICT (feature_id) DO NOTHING``이
**영원히 걸리지 않아** 매 ETL마다 중복 Feature가 생긴다. DDL은 초록이고, 1회 적재만
하는 테스트는 전부 초록이며, 증상은 두 번째 ETL에서 처음 나온다.

그래서 identity 해석 재설계는 재키의 부수 효과가 아니라 **본체**다. 이 revision은 그
대체 앵커가 앉을 자리를 만든다.

## 축을 두 번 틀렸고 두 번 다 실측이 잡았다

**1차 (2026-09-08)**: ``provider_sync.source_links``의 ``source_role='primary'``에
``UNIQUE (source_entity_key)``를 심었다. 통합 1179건 중 **17건이 빨개졌다** —
identity 이행 중에는 구·신 Feature가 둘 다 primary이기 때문이다
(``tests/integration/test_notice_lifecycle.py``가 그 형태를 의도적으로 재현한다).

**2차 (2026-09-09)**: 되돌린 뒤 조사가 **축 자체가 틀렸다**는 것을 보였다.
``src/kortravelmap/providers/opinet.py``를 보면::

    source_entity_id  = f"{item.uni_id}:{prodcd}"   # 제품별 N개  (:689)
    source_natural_key = item.uni_id                # 주유소별 1개 (:697)

그리고 그 경로의 docstring이 "단일 제품 가격을 **같은 price anchor feature에 누적**"
이라 명시한다(:762-765). 즉 entity → Feature는 정당하게 **N:1**이다. entity를
identity 축으로 삼으면 새 제품코드가 등장할 때마다 새 price Feature가 주조된다 —
재키가 고치려던 중복을 재키가 만든다.

## 올바른 축

``(provider_dataset_id, feature_kind, natural_key)``.

이것은 ``src/kortravelmap/core/ids.py``의 ``make_feature_id`` 입력
(``bjd_code|kind|category|source_type|source_natural_key``)에서 **ADR-068 결정 2가
배제하라고 한 것만 뺀 것**이다:

> provider identity는 ``(provider_dataset_id, source_entity_type, source_entity_id)``의
> ``UNIQUE``로 보장한다. ``bjd_code``, ``category``, 이름과 좌표는 identity 입력이 아니다.

``bjd_code``는 reverse geocoder가 준다. geocoder revision이나 좌표 보정이 그 값을
바꾸면 오늘은 **새 Feature가 주조된다** — ``core/ids.py``의 모듈 docstring이 그것을
"의도된 동작"이라 적어 뒀다. 이 축이 착지하면 그 문장이 거짓이 되고, 재분류·행정구역
변경이 제자리 갱신이 된다.

## 왜 `feature_aliases`를 재활용하지 않는가

``fk_feature_aliases_feature``가 plain FK라 claim-before-create가 성립하지 않는다
(Feature 행이 없는 상태에서 alias를 먼저 심을 수 없다). ``feature.features``로 가는
FK가 **아예 없는** ``feature.manual_feature_identity_claims``가 manual 경로에서 정확히
같은 이유로 그 모양이고, 이 표는 그 대칭을 따른다 — provider가 네 번째 형제를 갖는다.

## 이 revision은 writer를 바꾸지 않는다

표만 만든다. 백필과 wrapper 프로시저, writer 전환은 재키와 **같은 트랜잭션**이어야
한다 — 재키가 멱등을 부수는 그 순간에 대체가 있어야 하고, 별도 revision으로 미루면
"멱등 앵커 없는 head"가 배포 가능해진다.

## 계약 영향 0

이 표는 ``tests/integration/test_vnext_target_freeze.py``의 ``_TARGET_TABLES``에 없다.
``contracts/vnext/target-schema-v1.sql``을 건드리지 않으므로 5단 sha 사슬이 발동하지
않는다.
"""

from __future__ import annotations

from typing import Final

from alembic import op

# ruff: noqa: E501

revision: Final[str] = "308_t39_provider_feature_identities"
down_revision: Final[str] = "307_m02_truncate_fence"
branch_labels: None = None
depends_on: None = None


#: **``feature.features``로 가는 FK를 두지 않는다.** claim이 Feature보다 먼저 서야
#: 하기 때문이고, 그것이 `manual_feature_identity_claims`가 같은 모양인 이유다.
#: 대신 `idx_..._feature`가 역방향 조회를 받고, 고아 claim은 재키 뒤 정합성 검사가 센다.
_CREATE_TABLE: Final[str] = """
CREATE TABLE provider_sync.provider_feature_identities (
    provider_dataset_id bigint NOT NULL,
    feature_kind text NOT NULL,
    natural_key text NOT NULL,
    feature_id uuid NOT NULL,
    bound_by_operation text NOT NULL,
    bound_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    CONSTRAINT pk_provider_feature_identities
        PRIMARY KEY (provider_dataset_id, feature_kind, natural_key),
    CONSTRAINT ck_provider_feature_identities_kind
        CHECK (feature_kind = ANY (ARRAY[
            'place'::text, 'event'::text, 'notice'::text, 'price'::text,
            'weather'::text, 'route'::text, 'area'::text])),
    CONSTRAINT ck_provider_feature_identities_natural_key
        CHECK (btrim(natural_key) = natural_key
               AND natural_key <> ''
               AND "position"(natural_key, '|') = 0),
    CONSTRAINT ck_provider_feature_identities_operation
        CHECK (btrim(bound_by_operation) = bound_by_operation
               AND bound_by_operation <> '')
)
"""

#: `natural_key`에 `|`를 금지하는 이유는 ADR-009의 구분자 규약을 승계하기 때문이다 —
#: `make_feature_id`가 `bjd|kind|category|source_type|natural_key`를 이어 붙이므로
#: 구분자가 들어가면 서로 다른 입력이 같은 키가 될 수 있다. `core/ids.py`의
#: `_validate_component`가 같은 검사를 앱 층에서 한다.
_CREATE_DATASET_FK: Final[str] = (
    "ALTER TABLE provider_sync.provider_feature_identities"
    " ADD CONSTRAINT fk_provider_feature_identities_dataset"
    " FOREIGN KEY (provider_dataset_id)"
    " REFERENCES provider_sync.provider_datasets(provider_dataset_id)"
    " ON DELETE RESTRICT"
)

#: Feature 하나가 어떤 claim들에 물려 있는지 묻는 역방향. 재키 뒤 정합성 검사와
#: purge 경로가 쓴다.
_CREATE_FEATURE_INDEX: Final[str] = (
    "CREATE INDEX idx_provider_feature_identities_feature"
    " ON provider_sync.provider_feature_identities (feature_id)"
)

_OWNER: Final[str] = (
    "ALTER TABLE provider_sync.provider_feature_identities"
    " OWNER TO ktm_feature_schema_owner"
)

_DROP_TABLE: Final[str] = "DROP TABLE provider_sync.provider_feature_identities"

_RECEIPT_HEAD_WIDEN: Final[str] = (
    "ALTER TABLE ops.application_schema_operation_receipts"
    " DROP CONSTRAINT ck_application_schema_operation_receipts_head,"
    " ADD CONSTRAINT ck_application_schema_operation_receipts_head"
    " CHECK (destination_head IN ('300', '301_m03_import_children',"
    " '302_m03_child_issuance', '303_m05_payload_hash_domain',"
    " '304_m05_detector_manuals', '305_m05_relitigation_fence',"
    " '306_m02_manual_feature_purge', '307_m02_truncate_fence',"
    " '308_t39_provider_feature_identities'))"
)

_RECEIPT_HEAD_NARROW: Final[str] = (
    "ALTER TABLE ops.application_schema_operation_receipts"
    " DROP CONSTRAINT ck_application_schema_operation_receipts_head,"
    " ADD CONSTRAINT ck_application_schema_operation_receipts_head"
    " CHECK (destination_head IN ('300', '301_m03_import_children',"
    " '302_m03_child_issuance', '303_m05_payload_hash_domain',"
    " '304_m05_detector_manuals', '305_m05_relitigation_fence',"
    " '306_m02_manual_feature_purge', '307_m02_truncate_fence'))"
)


_UPGRADE_STATEMENTS: Final[tuple[str, ...]] = (
    "SET ROLE ktm_feature_schema_owner",
    _CREATE_TABLE,
    _CREATE_DATASET_FK,
    _CREATE_FEATURE_INDEX,
    _OWNER,
    _RECEIPT_HEAD_WIDEN,
)

_DOWNGRADE_STATEMENTS: Final[tuple[str, ...]] = (
    "SET ROLE ktm_feature_schema_owner",
    _RECEIPT_HEAD_NARROW,
    _DROP_TABLE,
)


def upgrade() -> None:
    for statement in _UPGRADE_STATEMENTS:
        op.execute(statement)


def downgrade() -> None:
    for statement in _DOWNGRADE_STATEMENTS:
        op.execute(statement)
