"""T-VN-M03 — import 행별 manual Feature child command 발급 계약.

Revision ID: 302_m03_child_issuance
Revises: 301_m03_import_children

`301`이 linkage **표**를 만들었고, 본 revision은 그 표를 실제로 채울 수 있게
쓰기 계약 셋을 확장한다(설계 §6).

1. **writer 확장** — ``feature.create_manual_curation_item_with_feature_command``의
   operation 검사를 single-item operation 하나에서 import child operation
   (``admin.curation-import.manual-feature-row.create-v1``)까지 둘로 넓힌다.
   나머지 계약(SERIALIZABLE·admin executor·payload shape·exact conflict)은
   바이트 동일하다 — 본문은 baseline에서 기계 파생했다(sidecar `.sql`).
2. **apply 확장** — ``feature.apply_curation_import_items_command``가
   (a) manual 행을 item upsert에서 건너뛰고(child writer가 만든 item의
   feature 결박을 NULL로 덮지 않게), (b) manual 행마다 writer-생성 item의
   존재를 fail-closed로 검사하고, (c) manual 행의 link decision을
   ``accepted``/``manual_feature_child``로 기록하며, (d) 행별 immutable 좌표
   (``o_row_receipts``)를 돌려준다. OUT 추가는 시그니처 변경이므로 DROP 후
   재생성한다.
3. **linkage 기록기** — ``ops.record_curation_import_manual_feature_children``
   표의 유일한 쓰기 경로인 SECURITY DEFINER procedure. runtime은 표에 직접
   INSERT할 수 없고(301의 grant는 command owner 전용) 이 procedure만 실행한다.
4. **match_basis 확장** — ``manual_feature_child`` 값을 CHECK에 추가한다.

프로시저 본문은 ``alembic/baseline/schema.sql``에서 기계 파생한 sidecar
(`_302_*_upgraded.sql` / `_302_*_original.sql`)로 둔다 — diff가 수정 지점만
보이게 하고, downgrade가 원본 바이트로 정확히 복원되게 한다.

DDL은 문장 하나씩 실행한다(asyncpg prepared statement 제약, `301`과 동일).
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Final

from alembic import op

# ruff: noqa: E501

revision: str = "302_m03_child_issuance"
down_revision: str | Sequence[str] | None = "301_m03_import_children"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_HERE: Final = Path(__file__).resolve().parent


def _sidecar(name: str) -> str:
    return (_HERE / name).read_text(encoding="utf-8")


# `301`의 규약: migration마다 receipt head CHECK 열거에 자기 head를 더한다 —
# 형식 검사로 풀면 DB 층 fail-close 하나가 사라진다. 결손은
# `test_receipt_head_check_covers_the_graph_head`가 잡는다.
_RECEIPT_HEAD_WIDEN: Final = (
    "ALTER TABLE ops.application_schema_operation_receipts"
    " DROP CONSTRAINT ck_application_schema_operation_receipts_head,"
    " ADD CONSTRAINT ck_application_schema_operation_receipts_head"
    " CHECK (destination_head IN ('300', '301_m03_import_children',"
    " '302_m03_child_issuance'))"
)

_RECEIPT_HEAD_NARROW: Final = (
    # 되돌린 뒤 302 head receipt가 남아 있으면 실패한다 — 그게 맞다(301과 동일 원칙).
    "ALTER TABLE ops.application_schema_operation_receipts"
    " DROP CONSTRAINT ck_application_schema_operation_receipts_head,"
    " ADD CONSTRAINT ck_application_schema_operation_receipts_head"
    " CHECK (destination_head IN ('300', '301_m03_import_children'))"
)

_MATCH_BASIS_WIDEN: Final = (
    "ALTER TABLE feature.curation_link_decisions"
    " DROP CONSTRAINT ck_curation_link_decisions_ck_curation_link_decisions_basis,"
    " ADD CONSTRAINT ck_curation_link_decisions_ck_curation_link_decisions_basis"
    " CHECK (match_basis = ANY (ARRAY['csv_explicit_feature_id'::text,"
    " 'admin_review'::text, 'legacy_unattributed'::text, 'forward_recovery'::text,"
    " 'source_rule'::text, 'manual_feature_child'::text]))"
)

_MATCH_BASIS_NARROW: Final = (
    # 되돌린 뒤 manual_feature_child 행이 남아 있으면 이 문장이 실패한다 — 그게
    # 맞다. 조용히 넘어가면 CHECK가 거짓이 된 표를 남긴다(301 downgrade와 동일 원칙).
    "ALTER TABLE feature.curation_link_decisions"
    " DROP CONSTRAINT ck_curation_link_decisions_ck_curation_link_decisions_basis,"
    " ADD CONSTRAINT ck_curation_link_decisions_ck_curation_link_decisions_basis"
    " CHECK (match_basis = ANY (ARRAY['csv_explicit_feature_id'::text,"
    " 'admin_review'::text, 'legacy_unattributed'::text, 'forward_recovery'::text,"
    " 'source_rule'::text]))"
)

#: OUT 추가는 procedure 시그니처를 바꾸므로 DROP이 선행해야 한다. pg_dump 표기
#: 그대로의 전체 인자 목록으로 특정한다.
_DROP_APPLY_OLD: Final = (
    "DROP PROCEDURE feature.apply_curation_import_items_command("
    "IN p_items jsonb, IN p_content_sha256 text, IN p_batch_kind text,"
    " IN p_command_id bigint, IN p_principal text, OUT o_import_batch_id uuid,"
    " OUT o_inserted integer, OUT o_updated integer, OUT o_removed_item_ids uuid[])"
)

_DROP_APPLY_NEW: Final = (
    "DROP PROCEDURE feature.apply_curation_import_items_command("
    "IN p_items jsonb, IN p_content_sha256 text, IN p_batch_kind text,"
    " IN p_command_id bigint, IN p_principal text, OUT o_import_batch_id uuid,"
    " OUT o_inserted integer, OUT o_updated integer, OUT o_removed_item_ids uuid[],"
    " OUT o_row_receipts jsonb)"
)

_APPLY_ACL_TEMPLATE: Final = (
    "{verb} ON PROCEDURE feature.apply_curation_import_items_command("
    "IN p_items jsonb, IN p_content_sha256 text, IN p_batch_kind text,"
    " IN p_command_id bigint, IN p_principal text, OUT o_import_batch_id uuid,"
    " OUT o_inserted integer, OUT o_updated integer, OUT o_removed_item_ids uuid[]"
    "{extra}) {direction}"
)


def _apply_acl(*, with_receipts: bool) -> tuple[str, str]:
    extra = ", OUT o_row_receipts jsonb" if with_receipts else ""
    return (
        _APPLY_ACL_TEMPLATE.format(
            verb="REVOKE ALL", extra=extra, direction="FROM PUBLIC"
        ),
        _APPLY_ACL_TEMPLATE.format(
            verb="GRANT ALL", extra=extra, direction="TO ktm_curation_admin_executor"
        ),
    )


_RECORDER: Final = """
CREATE PROCEDURE ops.record_curation_import_manual_feature_child(
    IN p_import_plan_id uuid,
    IN p_plan_row_number integer,
    IN p_plan_sha256 text,
    IN p_manual_payload_sha256 text,
    IN p_child_command_id bigint,
    IN p_feature_uuid uuid,
    IN p_import_row_id uuid,
    IN p_curation_item_id uuid,
    IN p_link_decision_id uuid
)
LANGUAGE plpgsql SECURITY DEFINER
SET search_path TO 'pg_catalog', 'feature', 'ops', 'x_extension'
AS $$
DECLARE
    v_command ops.domain_commands%ROWTYPE;
BEGIN
    IF current_setting('transaction_isolation') <> 'serializable' THEN
        RAISE EXCEPTION 'import child linkage requires SERIALIZABLE'
            USING ERRCODE = '25001', CONSTRAINT = 'ck_m03_child_linkage_isolation';
    END IF;
    IF session_user <> 'ktm_feature_api_runtime'
       OR NOT pg_has_role(session_user, 'ktm_curation_admin_executor', 'member')
       OR pg_has_role(session_user, 'ktm_curation_provider_executor', 'member') THEN
        RAISE EXCEPTION 'import child linkage requires the admin executor'
            USING ERRCODE = '42501', CONSTRAINT = 'ck_m03_child_linkage_executor';
    END IF;
    SELECT command.* INTO v_command
    FROM ops.domain_commands AS command
    WHERE command.command_id = p_child_command_id
    FOR UPDATE;
    IF NOT FOUND
       OR v_command.operation <> 'admin.curation-import.manual-feature-row.create-v1'
       OR btrim(v_command.actor) = '' THEN
        RAISE EXCEPTION 'import child linkage command does not match the child operation'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_m03_child_linkage_command';
    END IF;
    IF p_plan_sha256 !~ '^[0-9a-f]{64}$'
       OR p_manual_payload_sha256 !~ '^[0-9a-f]{64}$' THEN
        RAISE EXCEPTION 'import child linkage digests are not canonical'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_m03_child_linkage_digest';
    END IF;
    -- 나머지 결박(plan claim/plan row/claim causation/receipt/decision evidence)은
    -- 전부 `301` FK가 원자적으로 강제한다 — 여기서 중복 검증하지 않는다.
    INSERT INTO ops.curation_import_manual_feature_children (
        import_plan_id, plan_row_number, plan_sha256, manual_payload_sha256,
        child_command_id, feature_uuid, import_row_id, curation_item_id,
        link_decision_id
    ) VALUES (
        p_import_plan_id, p_plan_row_number, p_plan_sha256, p_manual_payload_sha256,
        p_child_command_id, p_feature_uuid, p_import_row_id, p_curation_item_id,
        p_link_decision_id
    );
END
$$
"""

_RECORDER_SIGNATURE: Final = (
    "ops.record_curation_import_manual_feature_child("
    "IN p_import_plan_id uuid, IN p_plan_row_number integer, IN p_plan_sha256 text,"
    " IN p_manual_payload_sha256 text, IN p_child_command_id bigint,"
    " IN p_feature_uuid uuid, IN p_import_row_id uuid, IN p_curation_item_id uuid,"
    " IN p_link_decision_id uuid)"
)


_REVOKE_APPLY_NEW, _GRANT_APPLY_NEW = _apply_acl(with_receipts=True)
_REVOKE_APPLY_OLD, _GRANT_APPLY_OLD = _apply_acl(with_receipts=False)

_UPGRADE_STATEMENTS: Final[tuple[str, ...]] = (
    _RECEIPT_HEAD_WIDEN,
    _MATCH_BASIS_WIDEN,
    # procedure 소유자는 ktm_curation_command_owner다 — REPLACE/DROP/CREATE와
    # ACL은 소유자 role로 수행한다(0228과 같은 패턴, schema owner가 멤버십 보유).
    "SET ROLE ktm_curation_command_owner",
    _sidecar("_302_writer_upgraded.sql"),
    _DROP_APPLY_OLD,
    _sidecar("_302_apply_upgraded.sql"),
    _REVOKE_APPLY_NEW,
    _GRANT_APPLY_NEW,
    "SET ROLE ktm_feature_schema_owner",
    # command owner는 ops 스키마에 CREATE 권한이 없다 — schema owner가 만들고
    # 소유권을 이전한다(0228의 표 OWNER TO 패턴과 동일). 명시 ACL은 이전 후에도
    # 유지된다.
    _RECORDER,
    f"REVOKE ALL ON PROCEDURE {_RECORDER_SIGNATURE} FROM PUBLIC",
    f"GRANT ALL ON PROCEDURE {_RECORDER_SIGNATURE} TO ktm_curation_admin_executor",
    # 소유권 이전은 새 소유자가 담는 스키마의 CREATE 권한을 요구한다 — 이전
    # 동안만 잠깐 부여하고 즉시 회수한다(영구 CREATE는 role 설계 위반).
    "GRANT CREATE ON SCHEMA ops TO ktm_curation_command_owner",
    f"ALTER PROCEDURE {_RECORDER_SIGNATURE} OWNER TO ktm_curation_command_owner",
    "REVOKE CREATE ON SCHEMA ops FROM ktm_curation_command_owner",
)

_DOWNGRADE_STATEMENTS: Final[tuple[str, ...]] = (
    "SET ROLE ktm_curation_command_owner",
    f"DROP PROCEDURE {_RECORDER_SIGNATURE}",
    _DROP_APPLY_NEW,  # noqa: E501 — recorder DROP은 소유자(command owner)로 실행
    _sidecar("_302_apply_original.sql"),
    _REVOKE_APPLY_OLD,
    _GRANT_APPLY_OLD,
    _sidecar("_302_writer_original.sql"),
    "SET ROLE ktm_feature_schema_owner",
    _MATCH_BASIS_NARROW,
    _RECEIPT_HEAD_NARROW,
)


def upgrade() -> None:
    for statement in _UPGRADE_STATEMENTS:
        op.execute(statement)


def downgrade() -> None:
    for statement in _DOWNGRADE_STATEMENTS:
        op.execute(statement)
