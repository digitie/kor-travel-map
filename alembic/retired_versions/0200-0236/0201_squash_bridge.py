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

- **기존 DB**(prod, `0104`): 문자열이 그대로 해석된다. 이 bridge 노드 자체는 이미 적용된
  것으로 보므로 다시 실행하지 않고, `upgrade head`는 후속 `0202`부터 현재 head `0220`까지
  적용한다.
- **새 DB**: `0200`이 스키마를 세우고 이 노드를 no-op으로 통과한 뒤 같은 `0202`~`0220`
  후속 migration을 적용한다.

두 경로가 **같은 현재 head `0220`**으로 수렴하는 것이 요점이다. 배포 순서에 stamp나
손수술은 들어가지 않으며 expected-head 핀은 배포 대상인 현재 head를 가리킨다.

## upgrade의 검증이 **닿는 범위** (오해하지 말 것)

여기 있는 relation 확인은 **새 DB 경로에서만 돈다.** `alembic_version`이 이미
`0104_tvn36_final_fence`인 DB는 이 bridge revision을 이미 적용한 것으로 간주하므로 이
함수는 **호출되지 않는다.** 전체 `upgrade head`는 0스텝이 아니라 후속 `0202`~`0220`을
적용한다. 따라서 여기 relation 검사는 기존 0104 DB를 검증하거나 복구하지 않는다.

그러니 이 검사를 "손수술·부분 복원·옛 dump로 어긋난 DB를 구제한다"고 읽으면 안 된다.
그 축은 alembic 밖에 있어야 한다 — 지금은 `docker/api-entrypoint.sh`가 DB revision이
아카이브 세대일 때를 가려 진단한다.

그래도 남겨 두는 이유는 하나다: `0200`이 방금 만든 것을 **같은 트랜잭션 안에서**
확인하므로, `schema.sql`이 어떤 이유로든 두 relation을 만들지 못한 채 성공한 경우를
잡는다. 신규 DB 경로의 사후 확인이지 기존 DB의 구제 장치가 아니다.
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
