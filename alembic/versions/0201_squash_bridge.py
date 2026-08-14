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

## upgrade의 검증이 **닿는 범위** (오해하지 말 것)

여기 있는 relation 확인은 **새 DB 경로에서만 돈다.** `alembic_version`이 이미
`0104_tvn36_final_fence`인 DB는 current == head라 `alembic upgrade head`가 0스텝으로
끝나고 이 함수는 **호출되지 않는다.** 적대 리뷰 2인이 각각 그것을 지적했고, 한쪽은
relation 두 개를 DROP한 0104 DB에서 `upgrade head`가 exit 0으로 통과하는 것을 실측했다.

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
