"""T-VN-39 ① — provider 멱등 앵커를 DB가 강제하게 만든다.

Revision ID: 308_t39_provider_identity_anchor
Revises: 307_m02_truncate_fence

## 재키가 부수는 것은 컬럼 타입이 아니라 멱등성이다

T-VN-39는 ``feature.features.feature_id``를 text 업무키에서 uuid surrogate로 바꾼다.
그런데 **오늘 provider 적재의 멱등성을 지탱하는 유일한 축이 바로 그 text 업무키다**:

- writer는 매 호출 새 UUIDv7을 만든다
  (``src/kortravelmap/infra/feature_repo.py`` ``_feature_params``의
  ``candidate_feature_uuid()``). ``ON CONFLICT`` 경로에서 그 후보는 버려진다.
- 프로시저는 ``ON CONFLICT (feature_id) DO NOTHING``이고, 그 ``feature_id``가
  ``make_feature_id(...)``가 만든 결정적 ``f_*``다.

재키 후 ``feature_id``가 그 새 UUIDv7이 되면 **충돌이 영원히 걸리지 않는다.** DDL
오류도 타입 오류도 나지 않고, 같은 원천이 적재될 때마다 새 Feature 행이 생긴다.
대부분의 테스트는 1회만 적재하므로 CI는 전 구간 초록이고, 증상은 prod의 두 번째
ETL에서 처음 나타난다.

## 앵커를 legacy 문자열에 걸면 안 된다

``make_feature_id``는 ``bjd_code|kind|category|source_type|source_natural_key``를
sha1한다(``src/kortravelmap/core/ids.py``). ADR-068이 그 사실을 **결함으로 지목**하며
쓴 문장이 이것이다:

> 현행 `f_*` ID는 SHA-1 64-bit prefix이며 `bjd_code`와 `category` 같은 수정 가능한
> 속성을 입력으로 사용한다. … 장기 정본 PK로 사용할 수 없다.

그리고 결정 2가 대안을 이미 정했다:

> provider identity는 `(provider_dataset_id, source_entity_type, source_entity_id)`의
> `UNIQUE`로 보장한다. `bjd_code`, `category`, 이름과 좌표는 identity 입력이 아니다.

그 UNIQUE는 이미 있다 — ``uq_source_entities_provider_identity``. 거기서 나온
``source_entity_key``가 저장소에서 **유일하게 행정구역·분류 드리프트에 불변인**
provider-native 키다.

## 그런데 그 키가 Feature를 결정하지는 못하고 있었다

``pk_source_links``는 ``(feature_id, source_entity_key)``라 한 entity가 여러 Feature에
붙는 것을 막지 않는다. 그리고 ``idx_source_links_primary``는 ``(feature_id)`` 방향의
**비-유니크** 부분 인덱스다 — 방향이 반대라 entity → feature 1:1을 강제하지 못한다.

``src/kortravelmap/dto/source.py``의 ``SourceLink`` docstring이 그 불변식을 이미
**말로** 적어 뒀다("``source_role='primary'`` link는 한 SourceRecord당 최대 1건").
말로만 있고 DB에 없다. 이 revision이 그것을 선언으로 바꾼다.

## 왜 재키보다 **먼저** 심는가

앵커 전환과 타입 전환을 같은 revision에 넣으면, "중복 Feature가 생겼다"의 원인이
앵커인지 타입인지 구분할 수 없다. 여기서는 ``feature_id``가 아직 text이므로 기존
멱등 축이 그대로 살아 있고, 새 앵커가 **그 축과 동치인지**를 실측으로 증명할 수 있다.
writer에 넣는 tripwire가 그 증명을 한다.

## merge 경로와 양립한다 (실측)

``src/kortravelmap/infra/merge_repo.py``의 ``_MOVE_LINKS_SQL``은 loser의 link를
master로 옮기되 **master가 이미 가진 entity는 건너뛴다**. 남은 것은
``_DROP_LEFTOVER_LINKS_SQL``이 지운다. 그래서 어느 시점에도 한 entity에 primary link가
둘 생기지 않는다.

## 이 인덱스가 틀렸다면 어떻게 아는가

한 source entity가 정당하게 **두 Feature의 primary**가 되는 경로가 있다면 이 인덱스가
그것을 23505로 막는다. upgrade 앞의 preflight가 기존 위반을 먼저 세고, 통합 테스트
전량이 그 다음 판정자다. 조용히 통과시키지 않는다.
"""

from __future__ import annotations

from typing import Final

from alembic import op

# ruff: noqa: E501

revision: Final[str] = "308_t39_provider_identity_anchor"
down_revision: Final[str] = "307_m02_truncate_fence"
branch_labels: None = None
depends_on: None = None


#: 기존 위반을 **먼저 센다**. 인덱스 생성이 알아서 실패하게 두지 않는 이유는
#: 진단 때문이다 — 23505는 "어떤 행이" 걸렸는지 말하지 않는다. 여기서 세면 위반한
#: entity key와 그것을 공유하는 feature 수가 오류 메시지에 실린다.
_PREFLIGHT: Final[str] = """
DO $$
DECLARE
    offenders text;
BEGIN
    SELECT string_agg(
               format('%s → %s features', violation.source_entity_key, violation.n),
               ', ' ORDER BY violation.source_entity_key
           )
      INTO offenders
      FROM (
          SELECT link.source_entity_key, count(*) AS n
            FROM provider_sync.source_links AS link
           WHERE link.source_role = 'primary'
           GROUP BY link.source_entity_key
          HAVING count(*) > 1
      ) AS violation;

    IF offenders IS NOT NULL THEN
        RAISE EXCEPTION
            'T-VN-39 provider identity anchor: 한 source entity가 여러 Feature의 '
            'primary로 붙어 있다 — 그 상태에서는 entity가 Feature를 결정하지 못한다. '
            '위반: %', offenders;
    END IF;
END
$$
"""

#: ADR-068 결정 2의 "provider identity"를 Feature 쪽에서 닫는 선언.
#: 방향이 요점이다 — 기존 `idx_source_links_primary`는 `(feature_id)`이고 비-유니크라
#: "이 Feature의 primary link들"만 빠르게 찾는다. 여기 필요한 것은 반대 방향,
#: "이 entity의 primary Feature는 하나"다.
_CREATE_INDEX: Final[str] = (
    "CREATE UNIQUE INDEX uq_source_links_primary_entity"
    " ON provider_sync.source_links (source_entity_key)"
    " WHERE source_role = 'primary'"
)

_DROP_INDEX: Final[str] = "DROP INDEX provider_sync.uq_source_links_primary_entity"

_RECEIPT_HEAD_WIDEN: Final[str] = (
    "ALTER TABLE ops.application_schema_operation_receipts"
    " DROP CONSTRAINT ck_application_schema_operation_receipts_head,"
    " ADD CONSTRAINT ck_application_schema_operation_receipts_head"
    " CHECK (destination_head IN ('300', '301_m03_import_children',"
    " '302_m03_child_issuance', '303_m05_payload_hash_domain',"
    " '304_m05_detector_manuals', '305_m05_relitigation_fence',"
    " '306_m02_manual_feature_purge', '307_m02_truncate_fence',"
    " '308_t39_provider_identity_anchor'))"
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
    _PREFLIGHT,
    _CREATE_INDEX,
    _RECEIPT_HEAD_WIDEN,
)

_DOWNGRADE_STATEMENTS: Final[tuple[str, ...]] = (
    "SET ROLE ktm_feature_schema_owner",
    _RECEIPT_HEAD_NARROW,
    _DROP_INDEX,
)


def upgrade() -> None:
    for statement in _UPGRADE_STATEMENTS:
        op.execute(statement)


def downgrade() -> None:
    for statement in _DOWNGRADE_STATEMENTS:
        op.execute(statement)
