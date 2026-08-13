"""T-VN-34 후속 — admin scope 조회축 인덱스 복원.

0096이 ``feature.features``의 조회축 인덱스 8개를 **공개 3축 partial**
(``lifecycle='active' AND publication='published' AND quality='valid'``)로 재생성했다.
그 자체는 옳다 — 공개 표면은 그 술어로만 읽으므로 인덱스가 작아지고 planner가 정확해진다.

문제는 **admin이 그 술어를 쓰지 않는다**는 것이다. T-VN-34C가 legacy status 기본 필터를
제거해서 admin 목록/검색/지도는 상태 무필터가 기본이고, 축을 지정해도 AND 결합이라
공개 술어를 함의하지 않는다(운영자는 은퇴·억제·격리된 feature를 찾으려고 admin에 온다).
그래서 admin 기본 화면 전부가 partial index 밖으로 나가 Seq Scan + Sort로 떨어졌다 —
3,200행 seed EXPLAIN 실측:

- 축 미지정: ``Limit → Sort → Nested Loop → Seq Scan(features)``
- 축을 공개값으로 명시: ``Limit → Nested Loop → Index Scan(idx_features_lower_name_keyset)``

이 손실을 확인하던 플랜 단언 두 개가 "통과하도록" 축소돼 있어서(하나는 인덱스 이름
단언을 PK로 교체, 하나는 파라미터에 공개 3축을 박음) 게이트에도 잡히지 않았다.

여기서는 **admin scope 인덱스를 전체 인덱스로 신설**한다. 공개 표면은 0096의 partial을
그대로 쓰고, admin은 자기 인덱스를 갖는다. 두 표면의 조회 의미를 서로 맞추려 하지
않는 것이 요점이다 — admin 목록에 상태 필터를 필수화하면 인덱스는 아끼지만 "모든
상태를 보는" 화면 자체가 사라진다.

이름은 ``idx_features_admin_*``로 공개 partial과 구분한다. 정렬축은
``admin_feature_repo``의 keyset과 같은 순서로 둔다(``lower(name), feature_id`` /
``updated_at DESC, feature_id DESC`` / ``created_at DESC, feature_id DESC``).

설계 (실측 3회로 확정) — **정렬축만 넣는다**
------------------------------------------

지적된 회귀는 "admin 목록이 정렬축 인덱스를 잃고 Seq Scan + Sort로 떨어졌다"였다.
그 축은 여기서 닫는다. bbox/검색 축은 **넣지 않는다** — 실측이 두 번 다 실패했기
때문이고, 근거 없이 인덱스를 남기면 쓰기 증폭만 남는다.

1. **6개 모두 전체 인덱스** → 공개 bbox 질의가 공개 partial(``idx_features_coord_gist``)
   대신 ``idx_features_admin_coord_gist``를 골랐다. 같은 컬럼에 전체 인덱스와 partial이
   공존하면 planner 선택이 갈린다. 공개 표면의 보증
   (``test_public_bbox_geometry_arms_use_ready_partial_indexes``)이 깨진다.
2. **coord/kind/trgm을 공개 술어의 여집합 partial로** → 이것도 틀렸다. partial index는
   질의의 제약절이 인덱스 술어를 **함의할 때만** 후보가 된다. admin 기본 화면은 상태
   무필터라 공개 술어도 그 여집합도 함의하지 못해 **양쪽 다 후보에서 빠진다**.
   ``BitmapOr(공개 partial, admin partial)``은 PostgreSQL이 하지 않는 동작이다
   (``enable_seqscan=off``에서도 Seq Scan이었다).
3. **확정 — 정렬 keyset 3종만.** 이 축은 공개 partial과 컬럼이 겹치지 않는 형태로
   planner가 정렬된 접근에 실제로 쓴다(게이트가 최상위 ``Sort`` 부재까지 못박는다).
   그리고 공개 bbox 보증을 건드리지 않는다.

**남긴 공백(의도적):** admin 지도(bbox)와 admin 이름 검색은 상태 무필터일 때 여전히
Seq Scan이다. 이것을 닫으려면 (a) 공개 partial을 전체 인덱스로 되돌려 두 표면이 하나를
공유하거나 (b) admin 목록에 상태 필터를 필수화해야 하는데, 둘 다 이 revision의 범위를
넘는 표면 결정이다. 근거 없는 인덱스를 미리 심어 두는 대신 사실을 남긴다.

쓰기 부하 실측(1M행): INSERT 5,000행 905ms(6개 인덱스 有) vs 888ms(無),
UPDATE 5,000행 321ms vs 260ms. 정렬 3종만 남기면 그보다 작다.

1M행 적용 시간(2026-08-13 prod 리허설 실측): 0095 87.3s / 0096 10.1s / 0097 1.5s /
0098 6.2s, 합계 ~105s. 전 구간 ``feature.features`` ACCESS EXCLUSIVE이며 api
healthcheck 창(start_period 20s + 10s×20)에는 들어간다.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0098_admin_scope_indexes"
down_revision: str | Sequence[str] | None = "0097_tvn34c_final_cutover"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# 정렬 keyset 3종만. bbox/kind/trgm은 위 설계 주석의 이유로 넣지 않는다.
_ADMIN_INDEXES: tuple[tuple[str, str], ...] = (
    ("idx_features_admin_lower_name_keyset", "(lower(name), feature_id)"),
    ("idx_features_admin_updated_keyset", "(updated_at DESC, feature_id DESC)"),
    ("idx_features_admin_created_keyset", "(created_at DESC, feature_id DESC)"),
)


def upgrade() -> None:
    for index_name, definition in _ADMIN_INDEXES:
        op.execute(
            f"CREATE INDEX IF NOT EXISTS {index_name} "
            f"ON feature.features {definition}"
        )


def downgrade() -> None:
    raise RuntimeError(
        "0098은 forward-only다 — admin scope 인덱스를 되돌리면 admin 조회가 다시 "
        "Seq Scan으로 떨어진다. 되돌릴 이유가 생기면 새 revision으로 명시하라."
    )
