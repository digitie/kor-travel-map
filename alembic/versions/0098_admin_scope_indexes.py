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

설계 보정 (실측 후)
-------------------

처음에는 6개를 전부 **전체 인덱스**로 만들었다. 그랬더니 공개 bbox 질의가 공개 partial
(``idx_features_coord_gist``) 대신 ``idx_features_admin_coord_gist``를 골랐다 — 작은
데이터셋에서 비용이 뒤집힌 것이고, 실데이터에서도 planner가 둘 사이에서 흔들릴 여지를
남긴다. 공개 표면이 자기 partial을 확실히 쓰게 하려면 **경쟁 자체를 없애야** 한다.

그래서 축별로 나눈다:

- **정렬 keyset 3종은 전체 인덱스**로 둔다. 여기서 필요한 것은 "정렬된 접근"인데,
  공개/비공개를 두 partial로 쪼개면 두 index scan을 하나의 정렬 스트림으로 합칠 수
  없어 Sort가 되살아난다. keyset은 공개 partial과 열 구성이 같지만 술어가 없어
  겹치는 비용을 감수한다.
- **coord/kind/trgm은 공개 술어의 여집합 partial**로 둔다. bitmap으로 결합되는
  축이라 admin 무필터 질의는 ``BitmapOr(공개 partial, admin partial)``로 덮이고,
  공개 질의는 admin partial의 술어가 거짓임이 증명되므로 **고를 수 없다**.
  결과적으로 두 표면이 같은 행을 두 번 색인하지 않는다.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0098_admin_scope_indexes"
down_revision: str | Sequence[str] | None = "0097_tvn34c_final_cutover"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_PUBLIC_STATE_PREDICATE = (
    "lifecycle_state = 'active' "
    "AND publication_state = 'published' "
    "AND quality_state = 'valid'"
)
_NON_PUBLIC_PREDICATE = f"WHERE NOT ({_PUBLIC_STATE_PREDICATE})"

# (이름, 정의, 술어) — 술어가 빈 문자열이면 전체 인덱스다.
_ADMIN_INDEXES: tuple[tuple[str, str, str], ...] = (
    # 정렬 keyset 3축: 전체 인덱스여야 정렬된 접근이 성립한다(위 주석 참조).
    ("idx_features_admin_lower_name_keyset", "(lower(name), feature_id)", ""),
    ("idx_features_admin_updated_keyset", "(updated_at DESC, feature_id DESC)", ""),
    ("idx_features_admin_created_keyset", "(created_at DESC, feature_id DESC)", ""),
    # bitmap 결합 축: 공개 술어의 여집합만 담아 공개 질의와 경쟁하지 않는다.
    ("idx_features_admin_coord_gist", "USING gist (coord)", _NON_PUBLIC_PREDICATE),
    (
        "idx_features_admin_kind_category",
        "(kind, category, feature_id)",
        _NON_PUBLIC_PREDICATE,
    ),
    (
        "idx_features_admin_name_trgm",
        "USING gin (name x_extension.gin_trgm_ops)",
        _NON_PUBLIC_PREDICATE,
    ),
)


def upgrade() -> None:
    for index_name, definition, predicate in _ADMIN_INDEXES:
        op.execute(
            f"CREATE INDEX IF NOT EXISTS {index_name} "
            f"ON feature.features {definition} {predicate}".rstrip()
        )


def downgrade() -> None:
    raise RuntimeError(
        "0098은 forward-only다 — admin scope 인덱스를 되돌리면 admin 조회가 다시 "
        "Seq Scan으로 떨어진다. 되돌릴 이유가 생기면 새 revision으로 명시하라."
    )
