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
상태로 수렴한다. 여기까지 21개 procedure/function.

**두 번째, 별도 층 — `session_user` 리터럴이 아니라 executor NOLOGIN role
membership으로 같은 상호 배타를 강제하는 procedure가 35개 더 있다**(n150
testcontainers round-trip이 실제로 `ensure_provider_feature_operation_command`를
호출하는 통합 테스트를 돌리기 전까지 안 보였다 — literal `session_user` 문자열
검색으로는 못 잡는다). 패턴은:

    IF NOT pg_has_role(session_user, 'ktm_curation_admin_executor', 'member')
       OR pg_has_role(session_user, 'ktm_curation_provider_executor', 'member') THEN
        RAISE EXCEPTION ...

즉 "admin executor 멤버이고, provider executor 멤버가 아니어야" 통과한다(역방향
패턴도 있다). `ktm_curation_admin_executor`는 옛 api_runtime 전용, `ktm_curation_
provider_executor`는 옛 dagster_runtime 전용 membership이었다 — `ktm_feature_service`는
**두 role 모두**의 member이므로, 통합 이후 이 게이트는 호출자가 누구든 무조건
거절한다(둘 다 만족 못 하는 게 아니라 "안 됨" 조건의 뒤쪽 절이 무조건 참이 됨).
21개짜리 층과 달리 이건 "role 이름 문자열 치환"이 아니라 **상호 배타 자체가
성립 불가능해진 것**이라 고정된 수정이 하나뿐이다 — `OR pg_has_role(<반대쪽>)`
절을 통째로 드롭해 "그 executor의 member이기만 하면 통과"로 좁힌다(admin 대신
provider를 쓰던 procedure는 반대로). 애플리케이션 코드가 실제로 어느 procedure를
호출하는지는 안 바뀌므로 이 완화가 새로 여는 경로는 없다 — 다만 이 게이트가
"당신은 그 반대가 아니어야 한다"까지 강제하던 것은 이제 못 한다(§3와 같은 종류의
trade-off, 범위만 훨씬 넓다). 35개 중 4개(`create_manual_curation_item_with_
initial_state`류의 4개와는 다른, `materialize_theme_candidate_generation` 등
21개짜리 층과 이름이 겹치는 4개)는 이미 있던 sidecar에 이 수정을 추가로 얹었다
(role 이름 치환 + 상호 배타 제거 둘 다). 총 56개 procedure/function
(21 + 35, 단 4개는 양쪽 세트에 다 속해 있으므로 sidecar 파일 기준으로는 21 + 31
= 52쌍).

**리터럴 문자열 치환 층(첫 21개)은 어느 procedure도 두 이름을 동시에 비교하지
않는다** — 각 procedure는 "이건 API 전용" 또는 "이건 Dagster 전용" 둘 중 하나만
검사했다. 그래서 그 층은 분기 로직을 합치는 판단이 필요 없는 순수 치환이었다
(원본/치환본 대조는 이 파일과 나란히 있는 `_313_*_original.sql` /
`_313_*_upgraded.sql` 사이드카 diff로 검증 가능).

`feature.feature_creation_origins`의 `ck_feature_creation_origins_roles` CHECK 제약도
같은 이유로 `invoker_role = 'ktm_feature_api_runtime'`를 세 번 검사한다(dagster_runtime은
애초에 여기 없었다 — manual 출처는 항상 API 경유였다). 이것도 단순 치환이다.

## 명시적으로 버리는 것 (ADR-100 §3, 확장)

통합 전에는 이 procedure들이 "호출자가 API 서버인지 Dagster인지"를 `session_user`
문자열 또는 admin/provider executor membership으로 구분해 거절할 수 있었다.
통합 후에는 두 경로 모두 `ktm_feature_service`로 접속하고 두 executor role 모두의
member이므로 이 구분은 사라진다 — API 전용이던 procedure를 Dagster 경로 코드가
호출해도(또는 그 반대도) 더는 막히지 않는다. 애플리케이션 코드가 어느 procedure를
호출하는지는 바뀌지 않으므로 **새로 열리는 호출 경로는 없다** — 다만 executor
membership 층이 강제하던 "그 반대가 아니어야 한다"는 이제 DB가 대신 확인해 주지
않는다. ADR-100이 명시적으로 승인한 trade-off이며, 범위는 최초 승인 시점(21개,
session_user 문자열만) 확인 이후 실제 round-trip 테스트로 35개가 더 있다는 게
드러나 확장됐다.

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
            "feature_apply_curation_import_items_command",
            "feature_archive_curated_source_command",
            "feature_archive_curated_source_rule_command",
            "feature_archive_curated_theme_command",
            "feature_archive_curation_collection_command",
            "feature_archive_curation_item_command",
            "feature_claim_curation_import_plan_command",
            "feature_create_curated_source_command",
            "feature_create_curated_source_rule_command",
            "feature_create_curated_theme_command",
            "feature_create_curation_collection_command",
            "feature_create_curation_import_plan_command",
            "feature_create_curation_item_command",
            "feature_finalize_provider_curation_receipts",
            "feature_merge_lock_curation_collections",
            "feature_patch_curated_source_command",
            "feature_patch_curated_source_rule_command",
            "feature_patch_curated_theme_command",
            "feature_patch_curation_collection_command",
            "feature_patch_curation_item_command",
            "feature_promote_theme_feature_candidate",
            "feature_reclassify_curation_quarantine_command",
            "feature_reject_theme_feature_candidate",
            "feature_resolve_curation_import_collection_command",
            "feature_seal_provider_curation_snapshot_receipt",
            "feature_sync_concierge_theme_catalog",
            "feature_touch_curation_import_collection_command",
            "ops_fill_provider_cancellation_starts_command",
            "ops_transition_provider_cancellation_job_command",
            "ops_record_curation_import_manual_feature_child",
            "ops_append_provider_feature_attempt_event_command",
            "ops_ensure_provider_feature_operation_command",
            "ops_finish_provider_feature_membership_command",
            "ops_transition_provider_feature_operation_terminal_command",
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
        "ops_append_provider_feature_attempt_event_command",
        "ops_ensure_provider_feature_operation_command",
        "ops_finish_provider_feature_membership_command",
        "ops_transition_provider_feature_operation_terminal_command",
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


#: 두 목록을 **모듈 import 시점에** 만든다. 늦게 만들면 세 lint가 이 파일을 보지
#: 못한다: `test_migration_sidecars_are_wired_into_their_migration`은
#: `Path.read_text`를 계측한 채 모듈을 import해 "실제로 열린 사이드카"를 세고,
#: 두 role-window lint는 module-level `_UPGRADE_STATEMENTS`/`_DOWNGRADE_STATEMENTS`를
#: 읽는다. 함수 호출로 남겨 두면 세 검사 모두 조용히 이 파일을 건너뛴다 — 313은
#: role을 여섯 번 바꾸는 유일한 마이그레이션이라 그 사각지대가 가장 비싼 자리다.
#: 마이그레이션은 SET ROLE을 켠 채로 끝나야 한다(RESET ROLE 금지) — alembic의 마지막
#: `UPDATE alembic_version`이 그 role로 실행돼야 하고, `ktm_curation_command_owner`
#: 같은 다른 owner로 끝나면 `permission denied for table alembic_version`으로 죽는다.
#:
#: 원래 이 파일은 "`_PROCEDURES_BY_OWNER`의 마지막 그룹이 schema owner다"에 기대고
#: 있었다. 그건 **정렬 순서에 대한 의존**이라, 누가 가독성을 위해 그룹 순서를 바꾸면
#: 조용히 깨진다. 게다가 두 role-window lint는 이 파일을 보지 못한다 —
#: `_executed_statements`가 `ast.For`의 `iter`가 `ast.Name`일 때만 풀 수 있는데 여기는
#: 함수 호출이다. 그래서 순서에 기대지 않고 **명시적으로** 되돌린다.
_FINAL_ROLE: Final[str] = "SET ROLE ktm_feature_schema_owner"


#: `feature.feature_creation_origins`는 schema owner가 소유한다 — 마지막 owner 그룹과
#: 같은 role이므로 role 전환 없이 이어서 실행한다.
#:
#: upgrade 형태는 **두 이름을 모두 받는다.** 이 표는 append-only다 —
#: `trg_feature_creation_origins_append_only`가 UPDATE/DELETE를 거절하므로 기존 행을
#: 새 형태에 맞게 고쳐 쓸 방법이 없고, 고쳐 쓰는 것이 옳지도 않다: 그 행들은 그
#: 시점에 실제로 존재하던 role 이름을 기록한 provenance다. `ktm_feature_service`만
#: 받는 형태로 걸면 PostgreSQL이 기존 행을 스캔해 23514로 거절하고, env.py가 전체
#: 실행을 한 트랜잭션으로 감싸므로 **upgrade 전체가 롤백된다** — 이미 manual Feature를
#: 만든 적이 있는 모든 DB에서.
#:
#: `NOT VALID`도 쓸 수 없다: SQLAlchemy 리플렉션이 그것을 `dialect_options`로 돌려
#: `test_fresh_300_upgrade_is_metadata_clean`이 SAWarning으로 터진다. 두 이름을 받는
#: 형태는 검증을 통과하면서도 제약을 유지한다 — 새 행의 `invoker_role`은 언제나
#: `session_user`이고 그 값은 이제 `ktm_feature_service`뿐이라 옛 이름은 과거 행에만
#: 남고 다시 생기지 않는다.
#:
#: downgrade는 312의 형태를 그대로 복원한다(옛 이름만). 통합 이후에 쓰인 행이 있으면
#: 그 복원은 23514로 선다 — upgrade 직후의 롤백에는 그런 행이 없다는 전제다.
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

#: 통합된 이름과 통합 전 이름을 함께 받는다 — 위 근거 참조.
_UPGRADED_INVOKERS: Final[str] = (
    "(invoker_role = ANY (ARRAY['ktm_feature_service'::text,"
    " 'ktm_feature_api_runtime'::text]))"
)

_ORIGIN_ROLES_CHECK_ADD_UPGRADED: Final[str] = (
    "ALTER TABLE feature.feature_creation_origins"
    " ADD CONSTRAINT ck_feature_creation_origins_roles"
    f" CHECK ((((origin_kind = 'manual_admin'::text) AND {_UPGRADED_INVOKERS}"
    " AND (procedure_definer = 'ktm_manual_feature_procedure_owner'::text))"
    f" OR ((origin_kind = 'manual_curation'::text) AND {_UPGRADED_INVOKERS}"
    " AND (procedure_definer = 'ktm_curation_command_owner'::text))"
    f" OR ((origin_kind = 'manual_request'::text) AND {_UPGRADED_INVOKERS}"
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


#: 뒤따르는 CHECK/receipt-head 문장도 같은 튜플에 담는다. 밖에 두면
#: `test_receipt_head_check_covers_the_graph_head`가 이 파일에서 receipt-head
#: 문장을 찾지 못한다 — 그 검사는 `_UPGRADE_STATEMENTS`만 읽는다.
_UPGRADE_STATEMENTS: Final[tuple[str, ...]] = (
    *_procedure_statements("upgraded"),
    _FINAL_ROLE,
    _ORIGIN_ROLES_CHECK_DROP,
    _ORIGIN_ROLES_CHECK_ADD_UPGRADED,
    _receipt_head_check((*_RECEIPT_HEADS, revision)),
)
_DOWNGRADE_STATEMENTS: Final[tuple[str, ...]] = (
    _FINAL_ROLE,
    _receipt_head_check(_RECEIPT_HEADS),
    _ORIGIN_ROLES_CHECK_DROP,
    _ORIGIN_ROLES_CHECK_ADD_ORIGINAL,
    *_procedure_statements("original"),
    _FINAL_ROLE,
)


def upgrade() -> None:
    for statement in _UPGRADE_STATEMENTS:
        op.execute(statement)


def downgrade() -> None:
    for statement in _DOWNGRADE_STATEMENTS:
        op.execute(statement)
