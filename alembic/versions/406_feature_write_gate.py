"""Feature advisory fence를 "Feature마다 하나"에서 "전역 gate 하나"로 바꾼다(ADR-111).

Revision ID: 406_feature_write_gate
Revises: 405_mois_freshness_sla

왜 필요한가. 다수 Feature를 건드리는 프로시저 아홉이 대상 Feature마다
``pg_advisory_xact_lock(hashtextextended('feature-write:' || id, 0))``을 잡았다. advisory
lock은 트랜잭션이 끝날 때까지 공유 lock table의 한 칸을 차지하고, 그 표의 크기는
``max_locks_per_transaction × (max_connections + …)``로 **cluster 전체가 함께 쓴다.**
2026-10-12 n150 공용 PostgreSQL(``max_locks_per_transaction=64``)에서
``finalize_provider_curation_root``가 dataset 99(11,820 Feature)의 root를 완결하려다
SQLSTATE 53200 ``out of shared memory``로 죽었다 — 그 한 트랜잭션이 표를 다 쓰는 동안
같은 cluster의 다른 tenant도 lock을 못 잡았다. 설정을 올리는 것은 상수를 바꿀 뿐이다
(MOIS는 수십만 행이다).

무엇을 하는가. 잠금 하나를 더한다: ``feature-write-all``.

- **대량 writer**(여덟): Feature별 잠금 대신 ``feature-write-all``을 **배타**로 한 번 잡는다.
  잡는 자리는 종전 Feature 잠금 루프가 있던 자리 그대로다(``curation-catalog-write`` 직전).
  그 루프를 덮던 "잠그는 동안 범위가 바뀌었나" 재검사(두 번의 scan + 40001)는 gate가 전부를
  덮으므로 지운다. ``finalize_provider_curation_root``만은 ``feature-curation-write``를 든 채라
  기다리지 않고 ``pg_try_advisory_xact_lock``으로 한 번 시도하고, 바쁘면 55P03으로 끝난다
  (reconcile sensor가 다음 tick에 다시 한다).
- **단건 writer**(여섯): ``feature-write:<id>`` 바로 앞에서 ``feature-write-all``을
  **공유**로 잡는다. 단건끼리는 종전처럼 서로 막지 않고, 대량 writer와는 서로 막는다.
  API 엔진에는 ``lock_timeout``이 없으므로 이 여섯은 루틴 설정으로 ``lock_timeout = 5s``를
  갖는다(API는 55P03을 503 ``LOCK_TIMEOUT``으로 돌려준다).

종전의 "Feature별 잠금이 서로 겹치면 직렬화" 보장은 그대로다 — 대량 writer는 모든
Feature를 덮는 하나의 배타 잠금을 들고, 단건 writer는 그 잠금의 공유 몫을 먼저 든다.
잡는 순서는 ``kortravelmap:curation-import`` → ``feature-curation-write`` →
``feature-write-all`` → ``feature-write:<id>`` → ``curation-catalog-write``이고
``tests/lint/test_feature_write_lock_order.py``가 head 스키마의 모든 루틴(중첩 CALL을
펼쳐서)에서 그것을 센다.

본문은 ``alembic/versions/_406_<루틴>.sql`` 사이드카다. 각 파일은 head-schema.sql 원문에서
잠금 몇 줄만 바꾼 사본이다(나머지는 바이트 동일).

``finalize_provider_curation_receipts``는 호출자가 없고(0209가 root 완결로 대체) gate 앞에서
``ops.import_jobs`` 행을 갱신한다 — 고치지 않고 걷어낸다.

receipt head CHECK에 이 revision을 더한다(401~405와 같은 계약).

forward-only. downgrade는 두지 않는다(ADR-021) — 되돌리면 lock table 고갈이 돌아온다.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Final

from sqlalchemy import text

from alembic import op

# ruff: noqa: E501

revision: str = "406_feature_write_gate"
down_revision: str | Sequence[str] | None = "405_mois_freshness_sla"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_VERSIONS_DIR: Final[Path] = Path(__file__).resolve().parent

#: 스키마 소유자. env가 켠 롤이고, 마이그레이션은 이 롤로 끝나야 한다.
_SCHEMA_OWNER_ROLE: Final[str] = "ktm_feature_schema_owner"
#: 아래 루틴 열셋(과 걷어낼 하나)의 소유자(``alembic/head-schema.sql``의 ``ALTER PROCEDURE ... OWNER TO``).
_CURATION_OWNER_ROLE: Final[str] = "ktm_curation_command_owner"
#: ``approve_feature_request_with_initial_state``의 소유자.
_FEATURE_REQUEST_OWNER_ROLE: Final[str] = "ktm_feature_request_procedure_owner"

#: 대량 writer — Feature별 잠금 대신 ``feature-write-all`` 배타 한 번.
BULK_WRITERS: Final[tuple[str, ...]] = (
    "archive_curated_source_command",
    "archive_curated_source_rule_command",
    "archive_curated_theme_command",
    "create_curated_source_rule_command",
    "finalize_provider_curation_root",
    "materialize_theme_candidate_generation",
    "patch_curated_source_rule_command",
    "patch_curated_theme_command",
)
#: 단건 writer — ``feature-write:<id>`` 앞에 ``feature-write-all`` 공유.
SINGLE_WRITERS: Final[tuple[str, ...]] = (
    "archive_curation_item_command",
    "create_curation_item_command",
    "create_manual_curation_item_with_feature_command",
    "patch_curation_item_command",
    "promote_theme_feature_candidate",
)
_FEATURE_REQUEST_WRITER: Final[str] = "approve_feature_request_with_initial_state"


#: 호출자가 없다(0209가 root 완결로 대체). 같은 Feature별 잠금 패턴에 더해 gate 앞에서
#: ``ops.import_jobs`` 행을 갱신하므로, 고치는 대신 걷어낸다(ADR-111 결정 5).
_DROP_RETIRED_RECEIPTS_SQL: Final[str] = (
    "DROP PROCEDURE feature.finalize_provider_curation_receipts(bigint, uuid, text, text)"
)


def _sidecar(routine: str) -> str:
    return (_VERSIONS_DIR / f"_406_{routine}.sql").read_text(encoding="utf-8")


#: receipt head 값 열거 CHECK — graph의 **모든** revision(401과 같은 계약).
_RECEIPT_HEAD_CHECK_SQL: Final[str] = """
ALTER TABLE ops.application_schema_operation_receipts
    DROP CONSTRAINT ck_application_schema_operation_receipts_head,
    ADD CONSTRAINT ck_application_schema_operation_receipts_head CHECK (destination_head IN ('300', '301_m03_import_children', '302_m03_child_issuance', '303_m05_payload_hash_domain', '304_m05_detector_manuals', '305_m05_relitigation_fence', '306_m02_manual_feature_purge', '307_m02_truncate_fence', '308_t39_provider_identities', '309_t39_feature_id_rekey', '310_seoul_source_move', '311_seal_member_digest', '312_route_geometry_sidecar', '313_single_service_role', '400', '401_retire_map_kma_refresh', '402_remove_map_weather_data', '403_drop_kma_notice_lineage', '404_transport_provider_identity', '405_mois_freshness_sla', '406_feature_write_gate'))
"""

#: 실행 순서대로의 upgrade 문장. 루틴마다 소유자 롤 창에서 다시 쓰고, 스키마 소유자
#: 롤로 돌아와 끝난다 — alembic의 ``UPDATE alembic_version``이 그 롤로 나간다.
_UPGRADE_STATEMENTS: Final[tuple[str, ...]] = (
    f"SET ROLE {_CURATION_OWNER_ROLE}",
    _DROP_RETIRED_RECEIPTS_SQL,
    *(_sidecar(routine) for routine in (*BULK_WRITERS, *SINGLE_WRITERS)),
    f"SET ROLE {_FEATURE_REQUEST_OWNER_ROLE}",
    _sidecar(_FEATURE_REQUEST_WRITER),
    f"SET ROLE {_SCHEMA_OWNER_ROLE}",
    _RECEIPT_HEAD_CHECK_SQL,
)


def upgrade() -> None:
    """Feature advisory fence를 전역 gate로 바꾼 루틴 열넷을 다시 쓰고 하나를 걷어낸다."""
    bind = op.get_bind()
    for statement in _UPGRADE_STATEMENTS:
        bind.execute(text(statement))


def downgrade() -> None:
    """되돌리지 않는다 — Feature별 잠금은 공유 lock table을 고갈시킨다."""
    raise RuntimeError(
        "406_feature_write_gate is forward-only: Feature별 advisory lock은 "
        "공유 lock table을 고갈시킨다(ADR-111)."
    )
