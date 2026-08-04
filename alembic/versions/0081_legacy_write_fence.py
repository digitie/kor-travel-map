"""Legacy write fence — alias map 잠금·identity 불변 강제 (T-VN-32C, ADR-068).

consumer-rollout-v1 T-VN-32 write_fence("32C에서 legacy-only write를 fence한다.
alias map 이관·checksum 검증 window 동안 fence 유지")와 removal manifest의
"feature.features legacy 문자열 feature_id PK 및 f_* 참조 FK 체인 —
fenced_by T-VN-32C"를 DB 층에서 착지한다. **제거는 전부 T-VN-39 소관**이다 —
본 revision은 어떤 legacy 구조물도 지우지 않는다.

세 가지를 잠근다 (fail-close by construction):

1. **alias map 불변** — ``feature.feature_aliases``는 32C 이관·checksum 대조의
   원본이다. UPDATE는 전면 거부, DELETE는 참조 feature 행이 이미 사라진
   경우(FK CASCADE 경유)만 허용한다. 직접 DELETE로 alias를 지우면 removal
   manifest의 "alias 유지" 계약과 PinVi 이관 대조가 조용히 갈라진다.
   INSERT는 기존 제약이 이미 canonical 쌍으로 고정한다 — FK(실존 feature) +
   PK(alias 유일) + 0080 파생 CHECK + 0079 AFTER 트리거의 원자 생성.
2. **identity 불변** — ``feature.features``의 ``feature_id``/``feature_uuid``
   UPDATE 거부. alias FK(NO ACTION)가 alias 있는 행의 PK 변경을 이미 막지만,
   36/39 사이 CHECK가 제거된 세계에서도 identity 재키잉이 불가능하도록 계약을
   트리거로 명시한다 (ADR-068: 수정 가능한 속성은 identity 입력이 아니다).
3. **legacy-only write** — uuid 없는 INSERT는 0079 BEFORE 트리거가 파생값으로
   채우고 0080 CHECK가 파생 일치를 강제하므로, **legacy-only 행이 저장되는
   경로는 구조적으로 존재하지 않는다**. 32B가 "32C 재평가"로 이월한 0079 트리거
   2종(fill/alias)은 **유지**로 결정한다: fill 트리거는 0080 CHECK가 요구하는
   유일값만 쓸 수 있어 우회로가 아니라 강제 메커니즘의 일부이고, AFTER alias
   트리거는 INV-068-01(모든 feature에 legacy alias ≥ 1)의 원자 보장이다.
   트리거 제거는 비파생 generator 채택(32C 잔여 — 양 저장소 checksum 일치
   뒤)과 함께 재평가한다. 그 시점 전까지 fill을 거부로 바꾸면 무결성 이득
   없이 raw SQL seed 경로만 깨진다(0079 docstring의 37개 파일 근거).

부속: alias-map 이관 표면(``/v1/service/feature-alias-maps``)의 keyset 조회가
canonical 순서(alias NFC UTF-8 byte 오름차순)로 index scan하도록
``COLLATE "C"`` index를 추가한다.

downgrade는 fence 트리거/함수/index만 제거한다 — 데이터 무변경, 무손실.

Revision ID: 0081_legacy_write_fence
Revises: 0080_uuid_dual_read
Create Date: 2026-08-04
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0081_legacy_write_fence"
down_revision: str | Sequence[str] | None = "0080_uuid_dual_read"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_CREATE_ALIAS_FENCE_FUNCTION_SQL = """
CREATE FUNCTION feature.fence_feature_aliases_write()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog
AS $$
BEGIN
    IF TG_OP = 'UPDATE' THEN
        RAISE EXCEPTION
            'T-VN-32C legacy write fence: feature_aliases 행은 불변입니다 '
            '(alias-map 이관·checksum 원본, ADR-068).';
    END IF;
    -- DELETE: 참조 feature가 이미 사라진 경우만(FK CASCADE 경유) 허용한다.
    IF EXISTS (
        SELECT 1 FROM feature.features WHERE feature_id = OLD.feature_id
    ) THEN
        RAISE EXCEPTION
            'T-VN-32C legacy write fence: alias 직접 DELETE 금지 — legacy '
            'alias는 T-VN-39 removal manifest 전까지 유지한다 (ADR-068).';
    END IF;
    RETURN OLD;
END;
$$
"""

_CREATE_IDENTITY_FENCE_FUNCTION_SQL = """
CREATE FUNCTION feature.fence_features_identity_update()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog
AS $$
BEGIN
    IF NEW.feature_id IS DISTINCT FROM OLD.feature_id
       OR NEW.feature_uuid IS DISTINCT FROM OLD.feature_uuid THEN
        RAISE EXCEPTION
            'T-VN-32C legacy write fence: feature identity(feature_id/'
            'feature_uuid)는 불변입니다 — 재키잉은 soft-delete + 신규 행으로 '
            '표현한다 (ADR-068).';
    END IF;
    RETURN NEW;
END;
$$
"""


def upgrade() -> None:
    op.execute(_CREATE_ALIAS_FENCE_FUNCTION_SQL)
    op.execute(
        "CREATE TRIGGER trg_feature_aliases_update_fence "
        "BEFORE UPDATE ON feature.feature_aliases "
        "FOR EACH ROW EXECUTE FUNCTION feature.fence_feature_aliases_write()"
    )
    op.execute(
        "CREATE TRIGGER trg_feature_aliases_delete_fence "
        "BEFORE DELETE ON feature.feature_aliases "
        "FOR EACH ROW EXECUTE FUNCTION feature.fence_feature_aliases_write()"
    )
    op.execute(_CREATE_IDENTITY_FENCE_FUNCTION_SQL)
    op.execute(
        "CREATE TRIGGER trg_features_identity_fence "
        "BEFORE UPDATE OF feature_id, feature_uuid ON feature.features "
        "FOR EACH ROW EXECUTE FUNCTION feature.fence_features_identity_update()"
    )
    # alias-map 이관 표면 keyset scan — canonical 순서(byte order)와 동일한
    # COLLATE "C" index. PK(alias)는 DB 기본 collation이라 별도로 둔다.
    op.execute(
        'CREATE INDEX idx_feature_aliases_alias_c '
        'ON feature.feature_aliases (alias COLLATE "C")'
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS feature.idx_feature_aliases_alias_c")
    op.execute(
        "DROP TRIGGER IF EXISTS trg_features_identity_fence ON feature.features"
    )
    op.execute("DROP FUNCTION IF EXISTS feature.fence_features_identity_update()")
    op.execute(
        "DROP TRIGGER IF EXISTS trg_feature_aliases_delete_fence "
        "ON feature.feature_aliases"
    )
    op.execute(
        "DROP TRIGGER IF EXISTS trg_feature_aliases_update_fence "
        "ON feature.feature_aliases"
    )
    op.execute("DROP FUNCTION IF EXISTS feature.fence_feature_aliases_write()")
