"""C7 인수 — KMA 초단기실황에 `external_system:c7-e2e` refresh scope를 선언한다.

Revision ID: 0224_c7_external_system_scope
Revises: 0223_tvn40_identity_mappings

왜 필요한가. ADR-088(#966) 이후 제출 가능한 `sync_scope` 집합의 정본은
`provider_sync.provider_dataset_operation_scopes`다 — API가 그 행을 exact join으로
요구하고(`infra/feature_update_repo.py` `_ACTIVE_DATASET_MEMBERSHIPS_SQL`), 요청·job·
sync state 표의 exact FK 4종이 구조로 강제한다. `external_system:*`도 예외가 아니다
(`api/ops_dataset_service.py::_scope_refresh_capability`: "external_system:*는 이제
scope 행으로 선언돼야 허용된다").

C7 prod live 인수(`ops-c7-kma-{active,cap,empty}-write`)는 **스케줄 job이 쓰는 정본
cursor를 건드리지 않고** KMA 격자 갱신을 끝까지 실행해야 한다. `target_grids`를 쓰면
(a) 실행 대상이 "모든 활성 cache target + extra points"라 PinVi가 target을 등록하는
순간 인수 게이트가 전체 대상에 provider I/O를 내고 `membership_fingerprint`가
비결정적이 되며, (b) `provider_sync_state(dataset, target_grids, operation)` 한 행을
스케줄과 공유해 인수 실행이 운영 cursor를 덮는다.

그래서 이 dataset이 external system 단위 갱신을 지원한다는 사실을 카탈로그에
**선언**하고, 인수 harness가 쓰는 이름 하나를 그 선언으로 고정한다. 실행 상태는
`provider_sync_state(7, external_system:c7-e2e, …)` 전용 행으로 갈라진다.

범위. 행 하나다. dataset은 `python-kma-api` / `kma_ultra_short_nowcast`, operation은
그 dataset의 enabled refresh operation이다. 두 개 이상이거나 없으면 중단한다 —
조용히 0행을 넣고 통과하면 인수 게이트가 다시 422로 죽고 원인이 감춰진다.

forward-only. downgrade는 두지 않는다(ADR-021).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Final

from sqlalchemy import text

from alembic import op

revision: str = "0224_c7_external_system_scope"
down_revision: str | Sequence[str] | None = "0223_tvn40_identity_mappings"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: C7 인수 harness가 등록하는 external system. 스펙 상수
#: (`e2e/live/_ops-c7-admin-api.ts`의 `C7_EXTERNAL_SYSTEM`)와 같은 값이어야 한다.
C7_EXTERNAL_SYSTEM: Final[str] = "c7-e2e"
C7_SYNC_SCOPE: Final[str] = f"external_system:{C7_EXTERNAL_SYSTEM}"
C7_PROVIDER: Final[str] = "python-kma-api"
C7_DATASET_KEY: Final[str] = "kma_ultra_short_nowcast"

_ACTIVE_DATASET_SQL: Final[str] = """
SELECT provider_dataset_id
  FROM provider_sync.provider_datasets
 WHERE provider = :provider AND dataset_key = :dataset_key AND is_active
"""

_ENABLED_REFRESH_OPERATIONS_SQL: Final[str] = """
SELECT operation_key
  FROM provider_sync.provider_dataset_operations
 WHERE provider_dataset_id = :provider_dataset_id
   AND operation_kind = 'refresh'
   AND is_enabled
 ORDER BY operation_key
"""

# 이미 있으면 그대로 둔다 — 이 행은 선언이고, 재적용이 의미를 바꾸면 안 된다.
_DECLARE_SCOPE_SQL: Final[str] = """
INSERT INTO provider_sync.provider_dataset_operation_scopes
    (provider_dataset_id, sync_scope, operation_key, operation_kind)
VALUES (:provider_dataset_id, :sync_scope, :operation_key, 'refresh')
ON CONFLICT ON CONSTRAINT pk_provider_dataset_operation_scopes DO NOTHING
"""

_DECLARED_SCOPE_COUNT_SQL: Final[str] = """
SELECT count(*)
  FROM provider_sync.provider_dataset_operation_scopes
 WHERE provider_dataset_id = :provider_dataset_id AND sync_scope = :sync_scope
"""


def upgrade() -> None:
    """선언 행 하나를 넣는다. 대상이 유일하지 않으면 중단한다.

    PL/pgSQL ``DO`` 블록을 쓰지 않는 이유: ``DO``는 파라미터를 받지 않고
    dollar-quoted 본문은 SQLAlchemy의 bind 치환과도 충돌한다. 검증을 Python에 두면
    실패 사유가 그대로 로그에 남고, alembic이 migration을 한 트랜잭션으로 돌리므로
    (``env.py``에 ``transaction_per_migration`` 없음) fail-closed 성질은 같다.
    """
    bind = op.get_bind()
    dataset_ids = list(
        bind.execute(
            text(_ACTIVE_DATASET_SQL).bindparams(
                provider=C7_PROVIDER, dataset_key=C7_DATASET_KEY
            )
        ).scalars()
    )
    if len(dataset_ids) != 1:
        raise RuntimeError(
            f"C7 acceptance scope: expected exactly 1 active dataset "
            f"{C7_PROVIDER}/{C7_DATASET_KEY}, found {len(dataset_ids)}"
        )
    provider_dataset_id = dataset_ids[0]

    operation_keys = list(
        bind.execute(
            text(_ENABLED_REFRESH_OPERATIONS_SQL).bindparams(
                provider_dataset_id=provider_dataset_id
            )
        ).scalars()
    )
    if len(operation_keys) != 1:
        # 형제 operation이 갈리면 어느 쪽에 선언할지 migration이 정할 수 없다.
        raise RuntimeError(
            f"C7 acceptance scope: expected exactly 1 enabled refresh operation for "
            f"{C7_PROVIDER}/{C7_DATASET_KEY}, found {operation_keys!r}"
        )

    bind.execute(
        text(_DECLARE_SCOPE_SQL).bindparams(
            provider_dataset_id=provider_dataset_id,
            sync_scope=C7_SYNC_SCOPE,
            operation_key=operation_keys[0],
        )
    )
    declared = bind.execute(
        text(_DECLARED_SCOPE_COUNT_SQL).bindparams(
            provider_dataset_id=provider_dataset_id, sync_scope=C7_SYNC_SCOPE
        )
    ).scalar_one()
    if declared != 1:
        raise RuntimeError(
            f"C7 acceptance scope: expected exactly 1 declared {C7_SYNC_SCOPE} row, "
            f"found {declared}"
        )


def downgrade() -> None:
    raise RuntimeError(
        "0224_c7_external_system_scope is forward-only; "
        "카탈로그 선언을 되돌리면 이미 그 scope로 쌓인 provider_sync_state·request 행이 "
        "exact FK로 남아 삭제도 막힌다"
    )
