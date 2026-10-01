"""Map의 KMA 적재 operation을 닫는다 — KMA는 kor-travel-weather가 소유한다(ADR-104).

Revision ID: 401_retire_map_kma_refresh
Revises: 400

왜 필요한가. 2026-10-01 소유자 결정으로 Map은 KMA(기상청) data.go.kr 오퍼레이션을
다시는 부르지 않는다. data.go.kr 키를 kor-travel-weather와 함께 쓰고, 오퍼레이션당
일일 한도가 빠듯하다. 코드에서는 KMA job·asset·schedule·runner spec·handler binding을
걷어냈다. 그런데 **실행 가능 집합의 정본은 DB 카탈로그다**(T-VN-33, ADR-088):
``provider_sync.provider_dataset_operations``에 enabled ``refresh`` 행이 남아 있으면

- ``GET /ops/datasets``가 그 dataset에 갱신 capability를 계속 내고,
- ``POST /ops/pipeline/requests``가 그 operation key를 membership으로 받아 큐에 넣고,
- 큐 runner는 handler가 없어 그 요청을 ``UnknownFeatureOperationHandlerError``로
  실패시킨다(호출은 나가지 않지만 화면과 큐가 거짓을 말한다).

그래서 provider가 ``python-kma-api``인 dataset의 적재 operation(``refresh``·
``feature_load``)을 ``is_enabled = false``로 내린다. 대상은 operation key 이름이 아니라
**provider 정체성**으로 고른다 — 이름을 나열하면 나열에서 빠진 operation이 조용히
남는다.

무엇을 바꾸지 않는가.

- **행을 지우지 않는다.** ``import_job_datasets``·``feature_update_request_datasets``·
  ``provider_sync_state``가 exact FK로 operation과 scope 행을 가리킨다. 지우면 이력이
  끊기거나 FK가 막는다. disable이면 활성 join(``operation.is_enabled``)에서만 빠진다.
- **dataset을 비활성화하지 않는다.** 이미 적재된 KMA feature·weather fact·notice는
  그대로 읽혀야 한다(읽기 경로는 dataset ``is_active``를 본다).
- **``preview`` operation은 그대로 둔다.** ``/ops/datasets/{id}/preview``는
  fixture-only이고 외부 호출 예산이 0이다(``api/etl_fixtures.py``).

사후 조건을 잰다: 이 provider에 enabled 적재 operation이 하나라도 남으면 중단한다 —
0행을 바꾸고 조용히 통과하면 카탈로그가 다시 KMA를 실행 가능하다고 말한다. 이미 꺼져
있는 DB(재적용)에서는 UPDATE가 0행이고 사후 조건은 그대로 성립한다.

부수 변경 하나: ``ops.application_schema_operation_receipts``의 head 값 열거 CHECK에 ``400``과
이 revision을 더한다(graph의 모든 revision을 받아야 한다는 lint 계약). 표는 비어 있다.

forward-only. downgrade는 두지 않는다(ADR-021) — 되살리는 것은 소유자 결정을 뒤집는
일이고 그때는 새 revision과 새 ADR로 한다.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Final

from sqlalchemy import text

from alembic import op

# ruff: noqa: E501

revision: str = "401_retire_map_kma_refresh"
down_revision: str | Sequence[str] | None = "400"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: KMA의 provider 정체성. ``kortravelmap.providers.kma.KMA_PROVIDER_NAME``과 같은 값이다.
#: migration은 import 시점 앱 코드에 기대지 않으므로 값을 여기 둔다.
KMA_PROVIDER: Final[str] = "python-kma-api"

_LOAD_OPERATION_KINDS_SQL: Final[str] = "('refresh', 'feature_load')"

_DISABLE_KMA_LOAD_OPERATIONS_SQL: Final[str] = f"""
UPDATE provider_sync.provider_dataset_operations AS operation
   SET is_enabled = false
  FROM provider_sync.provider_datasets AS dataset
 WHERE dataset.provider_dataset_id = operation.provider_dataset_id
   AND dataset.provider = '{KMA_PROVIDER}'
   AND operation.operation_kind IN {_LOAD_OPERATION_KINDS_SQL}
   AND operation.is_enabled
"""

_ENABLED_KMA_LOAD_OPERATIONS_SQL: Final[str] = f"""
SELECT operation.operation_key
  FROM provider_sync.provider_dataset_operations AS operation
  JOIN provider_sync.provider_datasets AS dataset
    ON dataset.provider_dataset_id = operation.provider_dataset_id
 WHERE dataset.provider = '{KMA_PROVIDER}'
   AND operation.operation_kind IN {_LOAD_OPERATION_KINDS_SQL}
   AND operation.is_enabled
 ORDER BY operation.operation_key
"""


#: ``ops.application_schema_operation_receipts.destination_head``의 값 열거 CHECK는 graph의
#: **모든** revision을 받아야 한다(``tests/lint/test_receipt_head_check_covers_the_graph_head.py``).
#: 400 스쿼시 이전 값(300~313)은 그대로 둔다 — 표에 남은 옛 행이 있으면 ``ADD CONSTRAINT``가
#: 실패하기 때문이다(2026-10-01 prod는 0행이지만 조건을 행 수에 걸지 않는다).
_RECEIPT_HEAD_CHECK_SQL: Final[str] = """
ALTER TABLE ops.application_schema_operation_receipts
    DROP CONSTRAINT ck_application_schema_operation_receipts_head,
    ADD CONSTRAINT ck_application_schema_operation_receipts_head CHECK (destination_head IN ('300', '301_m03_import_children', '302_m03_child_issuance', '303_m05_payload_hash_domain', '304_m05_detector_manuals', '305_m05_relitigation_fence', '306_m02_manual_feature_purge', '307_m02_truncate_fence', '308_t39_provider_identities', '309_t39_feature_id_rekey', '310_seoul_source_move', '311_seal_member_digest', '312_route_geometry_sidecar', '313_single_service_role', '400', '401_retire_map_kma_refresh'))
"""

#: 실행 순서대로의 upgrade 문장. 이 저장소 migration의 관례다 — lint 게이트가 이 tuple을
#: import해 실제로 실행되는 DDL을 읽는다.
_UPGRADE_STATEMENTS: Final[tuple[str, ...]] = (
    _DISABLE_KMA_LOAD_OPERATIONS_SQL,
    _RECEIPT_HEAD_CHECK_SQL,
)


def upgrade() -> None:
    """KMA 적재 operation을 끄고, 남은 것이 없는지 잰다."""
    bind = op.get_bind()
    for statement in _UPGRADE_STATEMENTS:
        bind.execute(text(statement))
    remaining = list(bind.execute(text(_ENABLED_KMA_LOAD_OPERATIONS_SQL)).scalars())
    if remaining:
        raise RuntimeError(
            f"401: {KMA_PROVIDER} enabled load operation이 남았다: {remaining!r}"
        )


def downgrade() -> None:
    """되돌리지 않는다 — KMA를 Map에 되살리는 것은 새 결정이다."""
    raise RuntimeError(
        "401_retire_map_kma_refresh is forward-only: Map은 KMA를 적재하지 않는다(ADR-104)."
    )
