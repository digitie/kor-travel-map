"""ADR-100 — 3개 LOGIN role(migrator/api_runtime/dagster_runtime)을 하나로 접는다.

## 배경

`docker/postgres-role-bootstrap.sh`가 만드는 LOGIN 계정은 `ktm_feature_migrator`
(스키마 DDL, `SET ROLE`로만 `ktm_feature_schema_owner`에 접근) / `ktm_feature_api_runtime`
(API 서버) / `ktm_feature_dagster_runtime`(Dagster) 셋으로 나뉘어 있었다(ADR-090).
ADR-100은 이 셋을 단일 LOGIN role `ktm_feature_service`로 통합하기로 했다 — bootstrap
스크립트 쪽 role 생성/membership은 이미 그렇게 바뀌었다. 이 migration은 그 결정이
compiled catalog(baseline `schema.sql`)에 남긴 자국을 정리한다.

## 왜 `schema.sql`을 다시 만들지 않는가

`schema.sql`은 `scripts/build-baseline.sh`가 격리된 0236 참조 DB에서 기계 생성하고
digest로 봉인한 **과거** 상태 snapshot이다("기준선은 새 migration으로만 진화한다").
301~312가 이미 증명한 대로, baseline 위의 정상적인 전진 진화는 `CREATE OR REPLACE`로
얹는다 — 이번도 같은 패턴이다.

## 실제로 뭐가 바뀌는가

`schema.sql`(baseline `300`) 안에서 `session_user`를 `'ktm_feature_api_runtime'`/
`'ktm_feature_dagster_runtime'` 리터럴과 비교하는 지점은 정확히 19개 procedure/function
안에 있다(21회 api_runtime + 1회 dagster_runtime). 여기에 300 이후 두 개의 forward
migration이 자기 것으로 만든 procedure 2개가 더 있다 —
`302_m03_import_child_issuance`의 `ops.record_curation_import_manual_feature_child`
(api_runtime 1회)와 `304_m05_detector_manual_listing`의
`feature.list_manual_provider_dedup_detector_manuals`(dagster_runtime 1회) — 그
두 migration 자신은(302/304, 봉인 없음) 역사적 정의를 그대로 두고 REVOKE 대상
같은 blocking DDL만 직접 고쳤다(별도 커밋). procedure 본문의 role 검사는 여기,
313에서 마저 CREATE OR REPLACE한다 — 그래야 302/304를 처음부터 다시 도는 fresh
install과, 이미 302/304를 지나 313만 새로 받는 n150 같은 기존 환경이 같은 최종
상태로 수렴한다. 총 21개 procedure/function.

**어느 procedure도 두 이름을 동시에 비교하지 않는다** — 각 procedure는 "이건 API
전용" 또는 "이건 Dagster 전용" 둘 중 하나만 검사했다. 그래서 이건 분기 로직을
합치는 판단이 필요한 작업이 아니라, 리터럴 문자열 치환이다(원본/치환본 대조는 이
파일과 나란히 있는 `_313_*_original.sql` / `_313_*_upgraded.sql` 사이드카 diff로
검증 가능 — 각 procedure당 role 이름 한 줄만 다르다).

`feature.feature_creation_origins`의 `ck_feature_creation_origins_roles` CHECK 제약도
같은 이유로 `invoker_role = 'ktm_feature_api_runtime'`를 세 번 검사한다(dagster_runtime은
애초에 여기 없었다 — manual 출처는 항상 API 경유였다). 이것도 단순 치환이다.

## 명시적으로 버리는 것 (ADR-100 §3)

통합 전에는 이 21개 procedure가 "호출자가 API 서버인지 Dagster인지"를 `session_user`로
구분해 거절할 수 있었다. 통합 후에는 두 경로 모두 `ktm_feature_service`로 접속하므로 이
구분은 사라진다 — 예를 들어 API 전용이던 procedure를 Dagster 경로 코드가 호출해도 더는
`session_user` 비교로는 막히지 않는다. 애플리케이션 코드가 어느 procedure를 호출하는지는
바뀌지 않으므로 기능 회귀는 없지만, DB가 강제하던 이 출처 분리는 더 이상 존재하지 않는다
— ADR-100이 명시적으로 승인한 trade-off다.

## owner 순서

`CREATE OR REPLACE`는 소유자만 할 수 있다(302/305와 같은 규약). 21개 procedure는 5개
서로 다른 NOLOGIN owner에 흩어져 있어(schema_owner는 그대로 membership만 갖고, 실제
owner는 각 도메인별 procedure_owner) `SET ROLE`을 owner별로 묶어 5번만 전환한다.
"""

from __future__ import annotations

from pathlib import Path
from typing import Final

from alembic import op

# ruff: noqa: E501

revision: Final[str] = "313_single_service_role"
down_revision: Final[str] = "312_route_geometry_sidecar"
branch_labels: None = None
depends_on: None = None

_HERE: Final = Path(__file__).resolve().parent


def _sidecar(name: str) -> str:
    return (_HERE / name).read_text(encoding="utf-8")


#: (owner, [procedure sidecar base name, ...]) — SET ROLE 전환 횟수를 최소화하도록 owner로 묶는다.
_PROCEDURES_BY_OWNER: Final[tuple[tuple[str, tuple[str, ...]], ...]] = (
    (
        "ktm_manual_provider_dedup_procedure_owner",
        (
            "feature_ack_feature_reference_reconciliation_event",
            "feature_lease_feature_reference_reconciliation_event",
            "feature_list_manual_provider_dedup_cases",
            "feature_preflight_feature_reference_reconciliation_ack",
            "feature_provision_feature_reference_reconciliation_subscription",
            "feature_read_manual_provider_dedup_case",
            "feature_record_manual_provider_dedup_candidate",
            "feature_resolve_manual_provider_dedup_case",
            "feature_list_manual_provider_dedup_detector_manuals",
        ),
    ),
    (
        "ktm_feature_request_procedure_owner",
        (
            "feature_approve_feature_request_with_initial_state",
            "feature_reject_feature_request",
            "feature_submit_feature_request",
        ),
    ),
    (
        "ktm_manual_feature_procedure_owner",
        ("feature_create_admin_manual_feature_with_initial_state",),
    ),
    (
        "ktm_curation_command_owner",
        (
            "feature_create_manual_curation_item_with_feature_command",
            "feature_finalize_provider_curation_root",
            "feature_materialize_theme_candidate_generation",
            "feature_refresh_curated_source_observation",
            "ops_fill_provider_cancellation_starts_command",
            "ops_transition_provider_cancellation_job_command",
            "ops_record_curation_import_manual_feature_child",
        ),
    ),
    (
        "ktm_feature_schema_owner",
        ("ops_reject_provider_feature_operation_raw_dml",),
    ),
)


#: `ktm_curation_command_owner`는 `feature`/`provider_sync`에는 CREATE가 있지만
#: `ops`에는 USAGE만 있다(bootstrap 스크립트, `_309_record_curation_import_manual_
#: feature_child.sql`의 같은 함정 주석 — "302_m03_child_issuance.py:324-330이
#: 같은 함정을 만났다"). `CREATE OR REPLACE`는 이미 소유한 object를 바꿀 때도
#: PostgreSQL이 **schema CREATE**를 별도로 요구한다(object ownership과 무관한
#: 별개 권한 검사) — 그래서 이 owner가 `ops.*`를 CREATE OR REPLACE하려면 매번
#: 이 grant가 필요하다. 이미 있었다면 건드리지 않고, 없었다면 준 뒤 되돌린다
#: (멱등 — 이 migration을 두 번 돌려도 최종 권한 상태가 같다).
_OPS_CREATE_GRANT_IF_NEEDED: Final[str] = """
DO $ktm_313_ops_create_open$
BEGIN
    IF has_schema_privilege('ktm_curation_command_owner', 'ops', 'CREATE') THEN
        PERFORM set_config('ktm.i313_ops_create_was_granted', 'false', false);
    ELSE
        EXECUTE 'GRANT CREATE ON SCHEMA ops TO ktm_curation_command_owner';
        PERFORM set_config('ktm.i313_ops_create_was_granted', 'true', false);
    END IF;
END
$ktm_313_ops_create_open$;
"""

_OPS_CREATE_REVOKE_IF_GRANTED: Final[str] = """
DO $ktm_313_ops_create_close$
BEGIN
    IF current_setting('ktm.i313_ops_create_was_granted', true) = 'true' THEN
        EXECUTE 'REVOKE CREATE ON SCHEMA ops FROM ktm_curation_command_owner';
    END IF;
END
$ktm_313_ops_create_close$;
"""

#: 이 owner 그룹 안에서 실제로 `ops` 스키마 object인 sidecar 이름만 창을 두른다.
_CURATION_COMMAND_OWNER_OPS_NAMES: Final[frozenset[str]] = frozenset(
    {
        "ops_fill_provider_cancellation_starts_command",
        "ops_transition_provider_cancellation_job_command",
        "ops_record_curation_import_manual_feature_child",
    }
)


def _procedure_statements(suffix: str) -> tuple[str, ...]:
    statements: list[str] = []
    for owner, names in _PROCEDURES_BY_OWNER:
        ops_names = [name for name in names if name in _CURATION_COMMAND_OWNER_OPS_NAMES]
        other_names = [name for name in names if name not in _CURATION_COMMAND_OWNER_OPS_NAMES]

        statements.append(f"SET ROLE {owner}")
        statements.extend(_sidecar(f"_313_{name}_{suffix}.sql") for name in other_names)

        if ops_names:
            # GRANT/REVOKE ON SCHEMA는 스키마 소유자만 할 수 있다 — owner 자신이
            # 스스로에게 CREATE를 줄 수 없다. schema_owner로 열고/닫고, 그 사이
            # 창에서만 실제 owner로 돌아와 CREATE OR REPLACE한다.
            statements.append("SET ROLE ktm_feature_schema_owner")
            statements.append(_OPS_CREATE_GRANT_IF_NEEDED)
            statements.append(f"SET ROLE {owner}")
            statements.extend(_sidecar(f"_313_{name}_{suffix}.sql") for name in ops_names)
            statements.append("SET ROLE ktm_feature_schema_owner")
            statements.append(_OPS_CREATE_REVOKE_IF_GRANTED)
    return tuple(statements)


#: `feature.feature_creation_origins`는 schema owner가 소유한다 — 마지막 owner 그룹과
#: 같은 role이므로 role 전환 없이 이어서 실행한다.
_ORIGIN_ROLES_CHECK_DROP: Final[str] = (
    "ALTER TABLE feature.feature_creation_origins"
    " DROP CONSTRAINT ck_feature_creation_origins_roles"
)

_ORIGIN_ROLES_CHECK_ADD_ORIGINAL: Final[str] = (
    "ALTER TABLE feature.feature_creation_origins"
    " ADD CONSTRAINT ck_feature_creation_origins_roles"
    " CHECK ((((origin_kind = 'manual_admin'::text) AND (invoker_role = 'ktm_feature_api_runtime'::text)"
    " AND (procedure_definer = 'ktm_manual_feature_procedure_owner'::text))"
    " OR ((origin_kind = 'manual_curation'::text) AND (invoker_role = 'ktm_feature_api_runtime'::text)"
    " AND (procedure_definer = 'ktm_curation_command_owner'::text))"
    " OR ((origin_kind = 'manual_request'::text) AND (invoker_role = 'ktm_feature_api_runtime'::text)"
    " AND (procedure_definer = 'ktm_feature_request_procedure_owner'::text))))"
)

_ORIGIN_ROLES_CHECK_ADD_UPGRADED: Final[str] = (
    "ALTER TABLE feature.feature_creation_origins"
    " ADD CONSTRAINT ck_feature_creation_origins_roles"
    " CHECK ((((origin_kind = 'manual_admin'::text) AND (invoker_role = 'ktm_feature_service'::text)"
    " AND (procedure_definer = 'ktm_manual_feature_procedure_owner'::text))"
    " OR ((origin_kind = 'manual_curation'::text) AND (invoker_role = 'ktm_feature_service'::text)"
    " AND (procedure_definer = 'ktm_curation_command_owner'::text))"
    " OR ((origin_kind = 'manual_request'::text) AND (invoker_role = 'ktm_feature_service'::text)"
    " AND (procedure_definer = 'ktm_feature_request_procedure_owner'::text))))"
)


#: 300 이후 모든 head를 누적한다 — receipt gate가 이 목록 밖 head를 거절한다(301~312와 동일 규약).
_RECEIPT_HEADS: Final[tuple[str, ...]] = (
    "300",
    "301_m03_import_children",
    "302_m03_child_issuance",
    "303_m05_payload_hash_domain",
    "304_m05_detector_manuals",
    "305_m05_relitigation_fence",
    "306_m02_manual_feature_purge",
    "307_m02_truncate_fence",
    "308_t39_provider_identities",
    "309_t39_feature_id_rekey",
    "310_seoul_source_move",
    "311_seal_member_digest",
    "312_route_geometry_sidecar",
)


def _receipt_head_check(heads: tuple[str, ...]) -> str:
    listed = ", ".join(f"'{head}'" for head in heads)
    return (
        "ALTER TABLE ops.application_schema_operation_receipts"
        " DROP CONSTRAINT ck_application_schema_operation_receipts_head,"
        " ADD CONSTRAINT ck_application_schema_operation_receipts_head"
        f" CHECK (destination_head IN ({listed}))"
    )


def upgrade() -> None:
    # `_PROCEDURES_BY_OWNER`의 마지막 그룹은 `ktm_feature_schema_owner`다 — 이
    # 루프가 끝난 뒤 role 전환 없이 CHECK/receipt-head 변경으로 바로 이어진다.
    # 마이그레이션은 SET ROLE을 켠 채로 끝나야 한다(RESET ROLE 금지) — alembic의
    # 마지막 `UPDATE alembic_version`이 이 role로 실행돼야 하기 때문이다.
    for statement in _procedure_statements("upgraded"):
        op.execute(statement)
    op.execute(_ORIGIN_ROLES_CHECK_DROP)
    op.execute(_ORIGIN_ROLES_CHECK_ADD_UPGRADED)
    op.execute(_receipt_head_check((*_RECEIPT_HEADS, revision)))


def downgrade() -> None:
    op.execute("SET ROLE ktm_feature_schema_owner")
    op.execute(_receipt_head_check(_RECEIPT_HEADS))
    op.execute(_ORIGIN_ROLES_CHECK_DROP)
    op.execute(_ORIGIN_ROLES_CHECK_ADD_ORIGINAL)
    # 마지막 그룹이 다시 `ktm_feature_schema_owner`로 끝난다 — RESET ROLE 없이 종료.
    for statement in _procedure_statements("original"):
        op.execute(statement)
