"""squash baseline — 0001~0104 체인이 만들던 최종 스키마를 한 번에 세운다.

Revision ID: 0200_schema_baseline
Revises: (없음 — 그래프 root)

## 왜 squash했나

prod cutover가 **폐기·재생성 + 재적재**가 아니라 in-place로 끝났고(2026-08-13,
`0087` -> `0104`), 그 뒤 prod는 `0104`에 있다. 즉 `0001~0104` 체인은 앞으로 **어떤
DB에서도 실행되지 않는다** — 새 DB는 이 baseline에서 시작하고, prod는 이미 지나왔다.

그 체인이 지고 있던 것은 순수한 부채였다:
- migration이 서로를 sha로 잠그고 import한다(`0104`가 `0102`를, `0102`가
  `0098/0099/0100`을). 한 파일을 고치면 연쇄로 sha를 갱신해야 한다.
- 존재하지 않을 데이터를 위한 backfill·fence·replay가 전부 살아 있다.
- 2026-08-13 하루에 나온 P1 3건이 **전부** 이 구조에서 나왔다 — anchor가 조용히
  빗나가도 sha는 그대로라 아무도 몰랐다.

## 무엇을 재현하고 무엇을 재현하지 않나

재현: `feature` / `provider_sync` / `ops` 세 스키마의 relation·routine·trigger·
제약·인덱스·**소유권**·ACL, 그리고 체인이 넣던 seed 행 전량.

재현하지 않음: role / schema / extension. 그건 체인 밖 **bootstrap이 정본**이다
(`docker/postgres-role-bootstrap.sh`, `tests/integration/_tvn34_migration_bootstrap.py`).
baseline이 그것까지 떠안으면 손으로 관리하는 prologue가 생기고, 그게 이 작업의 최대
위험 표면이 된다. 아래 DO block은 그 전제가 실제로 갖춰졌는지 **검증만** 한다.

## 동등성 증명

`alembic/baseline/*.sql`은 손으로 쓰지 않았다 — `scripts/build-baseline.sh`가
체인으로 만든 DB에서 뽑고 결정론적으로 정규화한다. 증명은
`scripts/compare-schema-catalogs.sh`(변조 7종 주입으로 자체 검증한 오라클)로 했고,
서로 다른 DB에서 두 번 재현했다: 카탈로그 2486행 동일(sha256 `741b355a…`),
seed 9개 표 328행 항목별 일치.

## ACL은 소유자로 부여한다 (그리고 그게 먹었는지 스스로 확인한다)

GRANT/REVOKE는 **객체 소유자만** 할 수 있다. baseline은 전 구간을
`ktm_feature_schema_owner` 하나로 돌리는데, ADR-090의 role은 `NOINHERIT`이라
membership이 있어도 권한이 승계되지 않는다. 그리고 소유자가 아닌 GRANT는 **오류가
아니라 경고 후 무시**다 — 첫 시도가 정확히 그렇게 exit 0으로 통과하면서 routine
10개가 PUBLIC EXECUTE로 남았다(체인 102 → baseline 112). 생성기가 ACL 블록마다
소유자로 `SET LOCAL ROLE` 하도록 고쳤다.

적용 성공이 ACL 적용의 증거가 되지 못하므로, `schema.sql` 끝에 routine ACL digest
자기검증이 붙는다(기대값도 생성기가 박는다). 그 검증이 실제로 무는지는 role 전환을
제거한 변조본으로 확인했다 — `exit 1`, `alembic_version` 미기록.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from pathlib import Path
from typing import Final

from sqlalchemy.util.concurrency import await_only

from alembic import op

revision: str = "0200_schema_baseline"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: sidecar SQL의 byte freeze. 손으로 고치면 여기서 막힌다 — baseline은 생성기의
#: 산출물이지 편집 대상이 아니다.
#:
#: **갱신 절차** (이 값을 바꿔야 할 때):
#:
#: 1. `0201`+ migration을 정상적으로 추가해 head를 전진시킨다. baseline은 그 자체로
#:    갱신하지 않는다 — 갱신은 "새 세대를 접었다"는 별도 결정이다.
#: 2. 접기로 했다면: **직전 baseline + 그 뒤 migration**으로 세운 DB에서
#:    `scripts/build-baseline.sh`를 돌려 새 sidecar를 뽑고,
#: 3. `scripts/compare-schema-catalogs.sh`로 그 DB와 **새 baseline만 적용한 DB**를
#:    대조한다. 두 DB는 서로 다른 경로로 만든 것이라야 대조가 의미를 갖는다.
#: 4. 이 상수와 sidecar를 한 PR에서 함께 갱신한다.
#:
#: ⚠️ `0001~0104` 체인으로는 이 절차를 돌릴 수 없다. 그 체인은
#: `alembic/legacy_versions/`에 있고 `versions/`로 되돌리면 root가 둘로 갈라진다.
#: 최초 생성 때의 "체인 DB vs baseline DB" 대조는 squash 이전 트리에서만 재현된다.
_SCHEMA_SHA256: Final[str] = "b5883a4556ac16d03885b0e849d5c35a91fab9155c9e86cb8b2a508b9c77ea0c"
_SEED_SHA256: Final[str] = "056de28cee0f0bbc2218e49afdf74aacd36b6e21e64c6524b2683a92bed956ec"

_BASELINE_DIR: Final[Path] = Path(__file__).resolve().parents[1] / "baseline"


def _read_sidecar(name: str, expected_sha256: str) -> str:
    path = _BASELINE_DIR / name
    raw = path.read_bytes()
    observed = hashlib.sha256(raw).hexdigest()
    if observed != expected_sha256:
        raise RuntimeError(
            f"alembic/baseline/{name} bytes drift — 생성기로 다시 만들고 동등성을"
            f" 재증명한 뒤 상수를 {observed}로 갱신하라"
        )
    return raw.decode("utf-8")


def _execute_sql_script(sql: str) -> None:
    """복수 statement를 현재 transaction에서 실행한다.

    asyncpg는 extended protocol의 prepared statement를 쓰므로 세미콜론으로 이어진
    복수 DDL을 거부한다. 체인이 같은 이유로 쓰던 헬퍼를 그대로 가져왔다
    (`0089`~`0093`의 여섯 파일, `0091`은 한 호출에 약 40문을 담는다).
    SQL을 문장 단위로 쪼개는 파서를 새로 쓰지 않는 이유이기도 하다 — `$$` 안의
    세미콜론 때문에 그 파서 자체가 결함 생산기가 된다.
    """
    raw_connection = op.get_bind().connection.driver_connection
    await_only(raw_connection.execute(sql))


def upgrade() -> None:
    # ── bootstrap 전제 검증 ────────────────────────────────────────────────
    # 앞부분(role 존재·membership)은 `0095`에서 그대로 가져왔다. role **생성**이 아니라
    # "bootstrap 없이 돌리면 fail-closed"라는 검증이 본체다. 뒤의 두 검사
    # (`x_extension`+postgis, runtime USAGE)는 squash가 만든 새 실패 양식을 막으려고
    # **여기서 추가한 것**이다 — 아래 주석 참조.
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT (SELECT rolsuper OR rolcreaterole FROM pg_catalog.pg_roles WHERE rolname = current_user)
               AND (
                   NOT EXISTS (SELECT 1 FROM pg_catalog.pg_roles WHERE rolname = 'ktm_feature_schema_owner')
                   OR NOT EXISTS (SELECT 1 FROM pg_catalog.pg_roles WHERE rolname = 'ktm_feature_state_procedure_owner')
                   OR NOT EXISTS (SELECT 1 FROM pg_catalog.pg_roles WHERE rolname = 'ktm_feature_audit_writer')
                   OR NOT EXISTS (SELECT 1 FROM pg_catalog.pg_roles WHERE rolname = 'ktm_feature_runtime')
               ) THEN
                RAISE EXCEPTION
                    'baseline requires CREATEROLE or pre-provisioned ktm_feature_* roles'
                    USING ERRCODE = '42501';
            END IF;
            IF NOT EXISTS (SELECT 1 FROM pg_catalog.pg_roles WHERE rolname = 'ktm_feature_schema_owner') THEN
                CREATE ROLE ktm_feature_schema_owner NOLOGIN NOINHERIT;
            END IF;
            IF NOT EXISTS (SELECT 1 FROM pg_catalog.pg_roles WHERE rolname = 'ktm_feature_state_procedure_owner') THEN
                CREATE ROLE ktm_feature_state_procedure_owner NOLOGIN NOINHERIT;
            END IF;
            IF NOT EXISTS (SELECT 1 FROM pg_catalog.pg_roles WHERE rolname = 'ktm_feature_audit_writer') THEN
                CREATE ROLE ktm_feature_audit_writer NOLOGIN NOINHERIT;
            END IF;
            IF NOT EXISTS (SELECT 1 FROM pg_catalog.pg_roles WHERE rolname = 'ktm_feature_runtime') THEN
                CREATE ROLE ktm_feature_runtime NOLOGIN NOINHERIT;
            END IF;
            -- Dedicated migrator runs ``SET LOCAL ROLE ktm_feature_schema_owner``.
            -- That restricted role has no ADMIN OPTION over routine owners. Bootstrap
            -- must establish membership before Alembic; the baseline never self-grants it.
            IF NOT EXISTS (
                SELECT 1
                FROM pg_catalog.pg_auth_members AS membership
                JOIN pg_catalog.pg_roles AS granted_role ON granted_role.oid = membership.roleid
                JOIN pg_catalog.pg_roles AS member_role ON member_role.oid = membership.member
                WHERE granted_role.rolname = 'ktm_feature_state_procedure_owner'
                  AND member_role.rolname = 'ktm_feature_schema_owner'
            ) OR NOT EXISTS (
                SELECT 1
                FROM pg_catalog.pg_auth_members AS membership
                JOIN pg_catalog.pg_roles AS granted_role ON granted_role.oid = membership.roleid
                JOIN pg_catalog.pg_roles AS member_role ON member_role.oid = membership.member
                WHERE granted_role.rolname = 'ktm_feature_audit_writer'
                  AND member_role.rolname = 'ktm_feature_schema_owner'
            ) THEN
                RAISE EXCEPTION
                    'baseline requires bootstrap membership of schema owner in state/audit owners'
                    USING ERRCODE = '42501';
            END IF;
            -- 아래 두 검사는 `0095`에 없던 것이다. squash가 만든 새 실패 양식을 막는다.
            --
            -- ① `x_extension` + postgis 부재: `schema.sql`이 6천 줄쯤에서 relation 오류로
            --    죽는다. fail-loud지만 원인이 6천 줄 뒤에 있다.
            -- ② runtime의 `x_extension` USAGE 부재: **조용하다.** baseline은 성공하고
            --    카탈로그 오라클도 3개 스키마만 보므로 초록인데, runtime의 평범한 core
            --    update SQL이 typed coordinate expression parse에서 죽는다. 체인에서는
            --    `0095`가 그 GRANT를 줬고 지금은 bootstrap이 준다 —— bootstrap이 낡으면
            --    여기서 서야 한다(2026-08-14 적대 리뷰 실측 결함).
            IF to_regnamespace('x_extension') IS NULL
               OR NOT EXISTS (
                   SELECT 1
                   FROM pg_catalog.pg_extension AS installed
                   JOIN pg_catalog.pg_namespace AS home ON home.oid = installed.extnamespace
                   WHERE installed.extname = 'postgis' AND home.nspname = 'x_extension'
               ) THEN
                RAISE EXCEPTION
                    'baseline requires bootstrap-provisioned x_extension schema with postgis'
                    USING ERRCODE = '42P01';
            END IF;
            IF NOT has_schema_privilege('ktm_feature_runtime', 'x_extension', 'USAGE') THEN
                RAISE EXCEPTION
                    'baseline requires bootstrap GRANT USAGE ON SCHEMA x_extension TO ktm_feature_runtime'
                    USING ERRCODE = '42501';
            END IF;
        END;
        $$
        """
    )

    # ── 스키마 ────────────────────────────────────────────────────────────
    _execute_sql_script(_read_sidecar("schema.sql", _SCHEMA_SHA256))

    # ── seed ──────────────────────────────────────────────────────────────
    # `--column-inserts`로 뽑았다. `COPY ... FROM stdin`은 이 실행 경로로 돌릴 수 없다.
    _execute_sql_script(_read_sidecar("seed.sql", _SEED_SHA256))


def downgrade() -> None:
    raise RuntimeError(
        "baseline은 forward-only다 — 되돌리려면 DB를 폐기하고 다시 만들어라"
    )
