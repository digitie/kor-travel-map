"""squash bridge — 이미 `0104`에 있는 DB가 baseline 그래프에서도 해석되게 한다.

Revision ID: 0104_tvn36_final_fence  (파일명 `0201_…`과 다르다 — 아래 참조)
Revises: 0200_schema_baseline

## 이 파일이 없으면 prod가 기동하지 못한다

alembic은 `public.alembic_version`에 적힌 문자열을 **script directory에서 찾아** 현재
위치를 정한다. prod는 `0104_tvn36_final_fence`에 있는데 squash로 그 파일이
`legacy_versions/`로 빠지면, 그 문자열을 아는 노드가 그래프에 하나도 없다:

    alembic current            -> CommandError: Can't locate revision '0104_tvn36_final_fence'
    alembic upgrade head       -> 같은 오류
    alembic stamp 0200         -> 같은 오류 (stamp도 **현재** revision을 먼저 해석한다)
    alembic stamp head|base    -> 같은 오류

즉 alembic 명령 전체가 막히고, 남는 복구 수단은 `UPDATE public.alembic_version` 손수술
하나인데 그건 `docs/deploy.md`가 명시적으로 금지한다. `docker/api-entrypoint.sh`의
선판정도 이 오류 문자열을 잡아 `exit 1` 하면서 **"이미지가 DB보다 뒤처졌다"**고
진단한다 — 사실과 반대라 새벽에 그 로그를 보는 사람은 롤백을 시도하게 된다.

## 그래서 revision id를 옛 head로 되돌려 놓는다

이 노드의 revision id는 새 번호가 아니라 **`0104_tvn36_final_fence` 그대로**다.
파일명만 정렬을 위해 `0201_…`이다(alembic은 파일명과 revision id를 묶지 않는다).
결과:

- **기존 DB**(prod, `0104`): 문자열이 그대로 해석되고, 이미 head이므로 `upgrade head`가
  no-op이다. `KOR_TRAVEL_MAP_MIGRATION_EXPECTED_HEAD` 핀도 손댈 필요가 없다.
- **새 DB**: `0200`이 스키마를 세우고 이 노드가 no-op으로 얹혀 같은 문자열에서 멈춘다.

두 경로가 **같은 head 문자열**로 수렴하는 것이 요점이다. 배포 순서에 stamp도, 핀
갱신도, 손수술도 들어가지 않는다 — 넣지 않아도 되는 절차는 넣지 않는 편이 안전하다.

## upgrade가 no-op이 아니라 검증인 이유

`0104`라고 적혀 있으면서 실제로는 그 세대가 아닌 DB가 있을 수 있다(손수술, 부분 복원,
옛 dump). 그런 DB를 조용히 head로 인정하면 결손이 런타임 SQL 오류로만 드러난다.
그래서 T-VN-36이 도입한 relation 두 개의 존재를 **확인만** 한다 — 없으면 여기서 선다.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0104_tvn36_final_fence"
down_revision: str | Sequence[str] | None = "0200_schema_baseline"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        DO $$
        DECLARE missing text;
        BEGIN
            SELECT string_agg(expected.name, ', ' ORDER BY expected.name)
              INTO missing
              FROM (VALUES
                        ('feature.feature_base_field_values'),
                        ('ops.feature_override_field_paths')
                   ) AS expected(name)
             WHERE to_regclass(expected.name) IS NULL;
            IF missing IS NOT NULL THEN
                RAISE EXCEPTION
                    'DB가 0104를 주장하지만 T-VN-36 relation이 없다 (%). alembic_version이'
                    ' 실제 스키마와 어긋나 있다 — 손으로 고치지 말고 복구점에서 다시 세워라',
                    missing
                    USING ERRCODE = '42P01';
            END IF;
        END;
        $$
        """
    )


def downgrade() -> None:
    raise RuntimeError(
        "squash bridge는 forward-only다 — 되돌리려면 DB를 폐기하고 다시 만들어라"
    )
