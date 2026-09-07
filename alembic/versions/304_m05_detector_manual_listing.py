"""T-VN-M05-3 — detector가 manual origin 대상을 열거할 수 있게 한다.

Revision ID: 304_m05_detector_manuals
Revises: 303_m05_payload_hash_domain

M05는 쓰기 쪽만 설계돼 있었다. `feature.record_manual_provider_dedup_candidate`는
**이미 아는 쌍 하나**를 기록하고, 그것이 detector executor가 EXECUTE할 수 있는
유일한 routine이다. 그런데 그 쌍을 **찾는** 경로가 없다 —

- `feature.feature_creation_origins`와 `feature.manual_feature_identity_claims`는
  `runtime_privileges.py`가 `ktm_feature_dagster_runtime`을 **이름으로** REVOKE한다
  (`_MANUAL_FEATURE_TABLE_ACL`). manual origin을 증명하는 표가 정확히 이 둘이다.
- `feature.features`와 `provider_sync.*` 넷은 detector가 읽을 수 있다
  (`_CORE_FEATURE_GRANTS` / `_ORDINARY_SCHEMA_PRIVILEGES['provider_sync']`).

그래서 detector에게 없는 것은 **manual origin 목록** 하나뿐이다. 이 revision은
정확히 그것만 여는 좁은 reader를 추가한다. provider 쪽 질의와 점수 계산은 이미
읽을 수 있는 것으로 Python이 하고, 기록은 종전 procedure가 그대로 한다.

**왜 grant가 아니라 함수인가.** 두 표에 SELECT를 주면 detector는 manual Feature의
생성 command·principal·actor·시각까지 전부 보게 된다. 탐지에 필요한 것은 "어떤
feature_id가 manual origin인가"뿐이다. 이 함수는 그 판정만 돌려주고 증거 자체는
돌려주지 않는다. ADR-090 경계가 **한 비트도 안 움직인다고 말하지 않는다** — 움직인다.
새로 드러나는 사실은 "어느 Feature가 manual origin인가"이며, 그 이상은 아니다.

**STABLE인 이유는 약속이 아니라 강제다.** SECURITY DEFINER 함수가 owner 권한으로
쓰기를 하지 못하게 하는 방법은 주석이 아니다. `STABLE`이면 SPI가 read-only로
돌아 INSERT/UPDATE/DELETE/CALL이 엔진 층에서 거부된다.

**cursor는 쌍이 아니라 manual 자체로 잰다.** 함수가 쌍을 돌려주면 "이웃이 없는
manual"이 0행이 되어 다음 페이지 cursor가 사라지고, 그 뒤 manual은 영원히 스캔
대상에서 빠진다. 이 함수는 manual 한 건당 정확히 한 행을 돌려주므로 그 결함이
생기지 않는다 — 이웃 여부는 호출자가 따로 묻는다(설계의 "따로 읽는다").

DDL은 문장 하나씩 실행한다(asyncpg prepared statement 제약, 301~303과 동일).
"""

from __future__ import annotations

from typing import Final

from alembic import op

# ruff: noqa: E501

revision: Final[str] = "304_m05_detector_manuals"
down_revision: Final[str] = "303_m05_payload_hash_domain"
branch_labels: None = None
depends_on: None = None


#: manual origin 판정의 정본은 procedure의 `ck_m05_candidate_manual_origin`
#: (baseline `schema.sql` 8095~8108행)이다. 이 함수는 그 술어를 집합으로 뒤집은
#: 것이고, 둘이 어긋나면 detector가 조용히 비거나 23514 폭풍이 난다.
#: `test_the_listing_and_the_procedure_agree_on_manual_origin`이 그 둘을 결박한다
#: — 목록이 돌려준 Feature는 procedure가 반드시 받아야 하고, 목록이 뺀 Feature는
#: procedure가 반드시 `ck_m05_candidate_manual_origin`으로 거부해야 한다.
_LISTING_CREATE: Final[str] = """
CREATE FUNCTION feature.list_manual_provider_dedup_detector_manuals(
    p_after text DEFAULT NULL,
    p_limit integer DEFAULT 1000
) RETURNS TABLE (
    feature_id text,
    name text,
    category text,
    lon double precision,
    lat double precision
)
    LANGUAGE plpgsql STABLE SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'feature', 'ops', 'x_extension'
    AS $$
BEGIN
    IF session_user <> 'ktm_feature_dagster_runtime'
       OR NOT pg_has_role(session_user, 'ktm_manual_provider_dedup_detector_executor', 'member')
       OR pg_has_role(session_user, 'ktm_manual_provider_dedup_admin_executor', 'member')
       OR pg_has_role(session_user, 'ktm_feature_reference_reconciliation_service_executor', 'member') THEN
        RAISE EXCEPTION 'manual/provider dedup detector requires the Dagster-only executor'
            USING ERRCODE = '42501', CONSTRAINT = 'ck_m05_detector_manuals_executor';
    END IF;
    IF p_limit IS NULL OR p_limit < 1 OR p_limit > 10000 THEN
        RAISE EXCEPTION 'manual/provider dedup detector page size is outside its canonical range'
            USING ERRCODE = '22023', CONSTRAINT = 'ck_m05_detector_manuals_limit';
    END IF;
    RETURN QUERY
    SELECT f.feature_id, f.name, f.category,
           ST_X(f.coord) AS lon, ST_Y(f.coord) AS lat
    FROM feature.features AS f
    JOIN feature.feature_creation_origins AS o ON o.feature_id = f.feature_uuid
    WHERE o.origin_kind IN ('manual_admin', 'manual_curation', 'manual_request')
      AND EXISTS (
          SELECT 1 FROM feature.manual_feature_identity_claims AS c
          WHERE c.feature_id = f.feature_uuid
            AND c.claimed_by_command_id = o.creation_command_id
      )
      AND f.lifecycle_state = 'active'
      AND f.publication_state = 'published'
      AND f.quality_state = 'valid'
      AND f.coord IS NOT NULL
      AND (p_after IS NULL OR f.feature_id > p_after)
    ORDER BY f.feature_id
    LIMIT p_limit;
END
$$
"""

_LISTING_DROP: Final[str] = (
    "DROP FUNCTION feature.list_manual_provider_dedup_detector_manuals(text, integer)"
)

#: owner는 relation owner가 아니라 SECURITY DEFINER principal이다 — 이 함수가
#: 읽는 두 표의 SELECT를 이미 들고 있는 유일한 역할이다(`_M05_SCHEMA_OWNER_DEPENDENCY_ACL`).
_LISTING_OWNER: Final[str] = (
    "ALTER FUNCTION feature.list_manual_provider_dedup_detector_manuals(text, integer)"
    " OWNER TO ktm_manual_provider_dedup_procedure_owner"
)

#: EXECUTE는 detector executor 하나뿐이다. api runtime·admin executor·service
#: executor는 명시적으로 거부한다 — 함수 본문의 검사와 ACL이 **둘 다** 막아야
#: 하나가 지워졌을 때 다른 하나가 남는다.
_LISTING_REVOKE: Final[str] = (
    "REVOKE ALL ON FUNCTION feature.list_manual_provider_dedup_detector_manuals(text, integer)"
    " FROM PUBLIC, ktm_feature_runtime, ktm_feature_api_runtime,"
    " ktm_feature_dagster_runtime, ktm_manual_provider_dedup_admin_executor,"
    " ktm_feature_reference_reconciliation_service_executor"
)

_LISTING_GRANT: Final[str] = (
    "GRANT EXECUTE ON FUNCTION feature.list_manual_provider_dedup_detector_manuals(text, integer)"
    " TO ktm_manual_provider_dedup_detector_executor"
)

_RECEIPT_HEAD_WIDEN: Final[str] = (
    "ALTER TABLE ops.application_schema_operation_receipts"
    " DROP CONSTRAINT ck_application_schema_operation_receipts_head,"
    " ADD CONSTRAINT ck_application_schema_operation_receipts_head"
    " CHECK (destination_head IN ('300', '301_m03_import_children',"
    " '302_m03_child_issuance', '303_m05_payload_hash_domain',"
    " '304_m05_detector_manuals'))"
)

_RECEIPT_HEAD_NARROW: Final[str] = (
    # 되돌린 뒤 304 head receipt가 남아 있으면 실패한다 — 그게 맞다(301과 동일 원칙).
    "ALTER TABLE ops.application_schema_operation_receipts"
    " DROP CONSTRAINT ck_application_schema_operation_receipts_head,"
    " ADD CONSTRAINT ck_application_schema_operation_receipts_head"
    " CHECK (destination_head IN ('300', '301_m03_import_children',"
    " '302_m03_child_issuance', '303_m05_payload_hash_domain'))"
)

_UPGRADE_STATEMENTS: Final[tuple[str, ...]] = (
    _LISTING_CREATE,
    _LISTING_OWNER,
    _LISTING_REVOKE,
    _LISTING_GRANT,
    _RECEIPT_HEAD_WIDEN,
)

_DOWNGRADE_STATEMENTS: Final[tuple[str, ...]] = (
    _RECEIPT_HEAD_NARROW,
    _LISTING_DROP,
)


def upgrade() -> None:
    for statement in _UPGRADE_STATEMENTS:
        op.execute(statement)


def downgrade() -> None:
    for statement in _DOWNGRADE_STATEMENTS:
        op.execute(statement)
