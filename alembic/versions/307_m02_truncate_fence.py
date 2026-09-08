"""T-VN-M02-TRUNCATE-FENCE — 삭제 fence가 TRUNCATE에도 이름을 대게 한다.

Revision ID: 307_m02_truncate_fence
Revises: 306_m02_manual_feature_purge

## 원장 서술 둘이 틀렸고, 진짜 결함은 다른 것이었다

원장은 "`TRUNCATE feature.features CASCADE`가 hard-purge fence를 통째로 우회한다"고
적었다. **재실측하니 실제로는 중단된다** — `feature.features`만 TRUNCATE하는 것은 FK
때문에 불가능하고, `CASCADE`가 끌어오는 30-table 폐포 중 **열 개에 켜진 BEFORE TRUNCATE
가드**가 있다.

그래서 진짜 결함은 "뚫린다"가 아니라 **fence가 그 거부에 아무 기여도 하지 않고, 호출자가
받는 진단이 엉뚱한 이유를 댄다**는 것이다. 지금 나오는 문구는
`T-VN-32C legacy write fence: feature_aliases TRUNCATE 금지` — manual Feature와 무관하다.
운영자는 그것을 읽고 무엇을 해야 할지 정할 수 없다.

원장의 "통합 테스트 24곳" 역시 틀렸다. **14곳이고 비용은 0이었다** — 전부
`tests/integration/_db_cleanup.py`를 지나고 그 헬퍼가 `session_replication_role = replica`로
돌아 origin 트리거를 전부 억제한다.

## 그래서 `ENABLE ALWAYS`를 고른다

origin-enabled 트리거는 **보안 바닥을 0만큼 올린다.** 121개 표에서 TRUNCATE 권한을 가진
로그인 롤은 컨테이너 superuser 하나뿐이고, 그 행위자는 `SET session_replication_role`
한 줄로 기존 DELETE fence까지 똑같이 무력화한다. 정직한 위협 모델은 적대자가 아니라
**실수**이고, 실수를 막는 유일한 변형이 `ENABLE ALWAYS`다.

그 대가는 `_db_cleanup.py`가 이 트리거들을 **이름으로 명시해** 끄는 것이다. 그것은 비용이
아니라 개선이다 — 지금은 `replica` 한 줄이 무엇을 우회하는지 말하지 않은 채 전부 끄지만,
바뀐 뒤에는 무엇을 우회하는지가 코드에 적힌다.

**purge가 열린 뒤라 이 선택이 가능해졌다.** 306 이전이라면 더 강한 fence는 "지울 방법이
아예 없다"를 더 굳히는 것이었다. 이제는 감사되는 삭제 경로가 있으므로, TRUNCATE를 막는
것이 데이터를 가두는 것이 아니라 **감사되지 않는 경로만** 막는 것이 된다.

## `ops.feature_requests`가 원장이 몰랐던 더 큰 구멍이다

M04 외부 제출을 담는데 TRUNCATE 가드도 append-only row 가드도 **아예 없다**. 저장소
전체에 그 표를 지우는 제품 코드가 0건이므로 DELETE도 함께 막는다 — `UPDATE`는 라우터가
`status`/`resolved_at` 등으로 정당하게 하므로 건드리지 않는다.

`ops.feature_update_requests`·`_datasets`는 DELETE 가드가 있고 TRUNCATE 가드가 없으므로
TRUNCATE만 더한다.

## 변이 검증의 함정

"트리거 제거 → red"는 **공허하다** — 이웃 가드가 먼저 raise하므로 지금도 red다. 게이트는
새 트리거의 **고유 제약 이름**을 단언해야 한다.

DDL은 문장 하나씩 실행한다(asyncpg prepared statement 제약).
"""

from __future__ import annotations

from typing import Final

from alembic import op

# ruff: noqa: E501

revision: Final[str] = "307_m02_truncate_fence"
down_revision: Final[str] = "306_m02_manual_feature_purge"
branch_labels: None = None
depends_on: None = None


#: manual Feature 전용 진단. 기존 fence(`reject_manual_feature_hard_purge`)와 **같은
#: 어휘를 쓰지 않는다** — 그쪽은 행 하나의 claim 승인을 보는데, 이쪽은 표 전체를 지우는
#: 것이라 승인이라는 개념 자체가 없다.
_FEATURES_TRUNCATE_GUARD: Final[str] = """
CREATE FUNCTION feature.reject_manual_feature_truncate() RETURNS trigger
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog'
    AS $$
BEGIN
    RAISE EXCEPTION 'manual Feature evidence forbids TRUNCATE; purge one Feature at a time with feature.purge_manual_feature'
        USING ERRCODE = '23514',
            CONSTRAINT = 'ck_manual_feature_truncate_forbidden';
END
$$
"""

_FEATURES_TRUNCATE_GUARD_DROP: Final[str] = (
    "DROP FUNCTION feature.reject_manual_feature_truncate()"
)

_M04_REQUEST_GUARD: Final[str] = """
CREATE FUNCTION feature.reject_feature_request_evidence_mutation() RETURNS trigger
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog'
    AS $$
BEGIN
    -- **어느 표가 막았는지 말한다.** 세 표가 이 가드 하나를 공유하므로, 표 이름이
    -- 없으면 CASCADE 폐포 안에서 어느 것이 raise했는지 호출자도 게이트도 구별하지
    -- 못한다 — 그러면 이웃이 대신 raise해 준 것을 자기 축이 통과한 것으로 읽는다
    -- (조문이 경고한 함정이 게이트 안쪽에서 되살아난다, 2026-09-08 변이 검증).
    RAISE EXCEPTION 'feature request evidence is append-only: %', TG_TABLE_NAME
        USING ERRCODE = '42501',
            CONSTRAINT = 'ck_feature_request_evidence_append_only';
END
$$
"""

_M04_REQUEST_GUARD_DROP: Final[str] = (
    "DROP FUNCTION feature.reject_feature_request_evidence_mutation()"
)

#: **`ENABLE ALWAYS`**다. origin이면 `SET session_replication_role = replica` 한 줄로
#: 사라지고, 그러면 이 트리거가 막는 것이 사실상 없다(모듈 docstring 참조).
_FEATURES_TRUNCATE_TRIGGER: Final[str] = (
    "CREATE TRIGGER trg_features_manual_feature_truncate_fence"
    " BEFORE TRUNCATE ON feature.features"
    " FOR EACH STATEMENT EXECUTE FUNCTION feature.reject_manual_feature_truncate()"
)

_FEATURES_TRUNCATE_ALWAYS: Final[str] = (
    "ALTER TABLE feature.features"
    " ENABLE ALWAYS TRIGGER trg_features_manual_feature_truncate_fence"
)

_FEATURES_TRUNCATE_TRIGGER_DROP: Final[str] = (
    "DROP TRIGGER trg_features_manual_feature_truncate_fence ON feature.features"
)

_REQUESTS_TRUNCATE_TRIGGER: Final[str] = (
    "CREATE TRIGGER trg_feature_requests_no_truncate"
    " BEFORE TRUNCATE ON ops.feature_requests"
    " FOR EACH STATEMENT EXECUTE FUNCTION"
    " feature.reject_feature_request_evidence_mutation()"
)

_REQUESTS_TRUNCATE_ALWAYS: Final[str] = (
    "ALTER TABLE ops.feature_requests"
    " ENABLE ALWAYS TRIGGER trg_feature_requests_no_truncate"
)

_REQUESTS_TRUNCATE_TRIGGER_DROP: Final[str] = (
    "DROP TRIGGER trg_feature_requests_no_truncate ON ops.feature_requests"
)

#: `UPDATE`는 막지 않는다 — 라우터가 `status`/`resolved_at`/`resolved_by_actor`를
#: 정당하게 갱신한다(`_FEATURE_REQUEST_TABLE_ACL`이 그 컬럼만 GRANT한다).
#: `DELETE`는 저장소 전체에 제품 경로가 0건이라 막는다.
_REQUESTS_DELETE_TRIGGER: Final[str] = (
    "CREATE TRIGGER trg_feature_requests_no_delete"
    " BEFORE DELETE ON ops.feature_requests"
    " FOR EACH ROW EXECUTE FUNCTION feature.reject_feature_request_evidence_mutation()"
)

_REQUESTS_DELETE_ALWAYS: Final[str] = (
    "ALTER TABLE ops.feature_requests"
    " ENABLE ALWAYS TRIGGER trg_feature_requests_no_delete"
)

_REQUESTS_DELETE_TRIGGER_DROP: Final[str] = (
    "DROP TRIGGER trg_feature_requests_no_delete ON ops.feature_requests"
)

_UPDATE_REQUESTS_TRUNCATE_TRIGGER: Final[str] = (
    "CREATE TRIGGER trg_feature_update_requests_no_truncate"
    " BEFORE TRUNCATE ON ops.feature_update_requests"
    " FOR EACH STATEMENT EXECUTE FUNCTION"
    " feature.reject_feature_request_evidence_mutation()"
)

_UPDATE_REQUESTS_TRUNCATE_ALWAYS: Final[str] = (
    "ALTER TABLE ops.feature_update_requests"
    " ENABLE ALWAYS TRIGGER trg_feature_update_requests_no_truncate"
)

_UPDATE_REQUESTS_TRUNCATE_TRIGGER_DROP: Final[str] = (
    "DROP TRIGGER trg_feature_update_requests_no_truncate"
    " ON ops.feature_update_requests"
)

_UPDATE_DATASETS_TRUNCATE_TRIGGER: Final[str] = (
    "CREATE TRIGGER trg_feature_update_request_datasets_no_truncate"
    " BEFORE TRUNCATE ON ops.feature_update_request_datasets"
    " FOR EACH STATEMENT EXECUTE FUNCTION"
    " feature.reject_feature_request_evidence_mutation()"
)

_UPDATE_DATASETS_TRUNCATE_ALWAYS: Final[str] = (
    "ALTER TABLE ops.feature_update_request_datasets"
    " ENABLE ALWAYS TRIGGER trg_feature_update_request_datasets_no_truncate"
)

_UPDATE_DATASETS_TRUNCATE_TRIGGER_DROP: Final[str] = (
    "DROP TRIGGER trg_feature_update_request_datasets_no_truncate"
    " ON ops.feature_update_request_datasets"
)

_RECEIPT_HEAD_WIDEN: Final[str] = (
    "ALTER TABLE ops.application_schema_operation_receipts"
    " DROP CONSTRAINT ck_application_schema_operation_receipts_head,"
    " ADD CONSTRAINT ck_application_schema_operation_receipts_head"
    " CHECK (destination_head IN ('300', '301_m03_import_children',"
    " '302_m03_child_issuance', '303_m05_payload_hash_domain',"
    " '304_m05_detector_manuals', '305_m05_relitigation_fence',"
    " '306_m02_manual_feature_purge', '307_m02_truncate_fence'))"
)

_RECEIPT_HEAD_NARROW: Final[str] = (
    "ALTER TABLE ops.application_schema_operation_receipts"
    " DROP CONSTRAINT ck_application_schema_operation_receipts_head,"
    " ADD CONSTRAINT ck_application_schema_operation_receipts_head"
    " CHECK (destination_head IN ('300', '301_m03_import_children',"
    " '302_m03_child_issuance', '303_m05_payload_hash_domain',"
    " '304_m05_detector_manuals', '305_m05_relitigation_fence',"
    " '306_m02_manual_feature_purge'))"
)


_UPGRADE_STATEMENTS: Final[tuple[str, ...]] = (
    # **두 guard function의 소유자는 audit writer다.** trigger function은 발화 시
    # EXECUTE 권한을 보지 않으므로 회수해도 fence는 그대로 돈다. 그런데 회수하지 않으면
    # `db.py`의 startup preflight가 "unexpected SECURITY DEFINER function"으로 배포를
    # 막고, 회수는 **소유자만** 할 수 있다 — schema owner 소유로 두면 다른 grantor가
    # owner ACL을 못 지운다(기존 `reject_manual_feature_evidence_mutation` 주석이 같은
    # 함정을 적어 뒀고, 2026-09-08 실측이 그것을 다시 확인했다).
    "SET ROLE ktm_feature_audit_writer",
    _FEATURES_TRUNCATE_GUARD,
    _M04_REQUEST_GUARD,
    "SET ROLE ktm_feature_schema_owner",
    _FEATURES_TRUNCATE_TRIGGER,
    _FEATURES_TRUNCATE_ALWAYS,
    _REQUESTS_TRUNCATE_TRIGGER,
    _REQUESTS_TRUNCATE_ALWAYS,
    _REQUESTS_DELETE_TRIGGER,
    _REQUESTS_DELETE_ALWAYS,
    _UPDATE_REQUESTS_TRUNCATE_TRIGGER,
    _UPDATE_REQUESTS_TRUNCATE_ALWAYS,
    _UPDATE_DATASETS_TRUNCATE_TRIGGER,
    _UPDATE_DATASETS_TRUNCATE_ALWAYS,
    _RECEIPT_HEAD_WIDEN,
)

_DOWNGRADE_STATEMENTS: Final[tuple[str, ...]] = (
    _RECEIPT_HEAD_NARROW,
    _UPDATE_DATASETS_TRUNCATE_TRIGGER_DROP,
    _UPDATE_REQUESTS_TRUNCATE_TRIGGER_DROP,
    _REQUESTS_DELETE_TRIGGER_DROP,
    _REQUESTS_TRUNCATE_TRIGGER_DROP,
    _FEATURES_TRUNCATE_TRIGGER_DROP,
    "SET ROLE ktm_feature_audit_writer",
    _M04_REQUEST_GUARD_DROP,
    _FEATURES_TRUNCATE_GUARD_DROP,
    "SET ROLE ktm_feature_schema_owner",
)


def upgrade() -> None:
    for statement in _UPGRADE_STATEMENTS:
        op.execute(statement)


def downgrade() -> None:
    for statement in _DOWNGRADE_STATEMENTS:
        op.execute(statement)
