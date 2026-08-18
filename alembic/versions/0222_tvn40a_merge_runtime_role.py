"""T-VN-40A — feature merge가 runtime role로 돌게 lock/mirror를 SECURITY DEFINER procedure로.

Revision ID: 0222_tvn40a_merge_runtime_role
Revises: 0221_tvn40_snapshot_text_bounds

배경. T-VN-40A legacy write fence(PR #994)가 `ktm_feature_runtime`에서 `feature.curated_features`의
write 권한을 뺐다. 그런데 `merge_repo.apply_feature_merge`가 legacy 표를 `FOR UPDATE`로 잠그고
UPDATE 3문으로 **mirror**한다 — canonical 병합 결과를 legacy read가 따라가게. PostgreSQL은
`FOR UPDATE`에도 UPDATE 권한을 요구하므로 merge가 42501로 죽는다. dedup 병합(`PATCH
/v1/admin/dedup-reviews/{id}`)과 `ktmctl dedup-merge` 둘 다.

CI가 못 잡은 이유: 모든 merge 통합 테스트가 superuser 세션으로 돈다.
`tests/integration/test_merge_under_runtime_role.py`가 runtime role로 실행해 red를 확인했다.

해결. mirror 4문을 `ktm_curation_command_owner` 소유 SECURITY DEFINER procedure로 옮긴다 —
`0214_tvn40_item_commands`가 canonical→legacy mirror에 쓰는 것과 같은 패턴이다. runtime은
표에 write 권한 없이 procedure만 EXECUTE한다. ACL 표(`runtime_privileges`)는 SELECT만 유지 —
fence의 "표에 없는 권한은 DB에 없다"가 그대로 성립한다.

4문을 procedure 하나로 합치지 않는다. 사이에 canonical 작업(collection lock·item reconcile·
history move)이 끼어 있어 **호출 순서**가 계약이다:
    lock → (canonical) → archive_conflicting → (canonical) → sync_master → (canonical) → move

legacy mirror 4문(①~④)은 40C가 legacy 표를 물리 삭제할 때 함께 사라진다 — 그때까지의 다리다.

⑤ canonical collections lock. 같은 테스트가 legacy 다음으로 `curation_collections`에서 42501을
냈다. merge가 영향 collection을 `FOR UPDATE`로 잠그는데(교착 방지 순서 계약 — import/admin
writer와 같은 UUID 순) runtime은 SELECT만 있다. **fence 이전부터의 결함**(20fa752d) — merge는
애초에 runtime role로 돌 수 없었고 superuser 테스트만 있어 CI가 못 잡았다. 0204/0214 패턴대로
runtime에 canonical lock 권한을 주지 않고 command_owner 소유 procedure 안에서 잠근다. 행 잠금은
트랜잭션 범위라 procedure 반환 뒤에도 유지된다. command_owner의 `curation_collections` column
UPDATE(=lock 권한)는 0204가 이미 부여했다. ⑤는 canonical이므로 40C 이후에도 남는다.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# Frozen PostgreSQL procedure text intentionally exceeds Python line length.
# ruff: noqa: E501

revision: str = "0222_tvn40a_merge_runtime_role"
down_revision: str | Sequence[str] | None = "0221_tvn40_snapshot_text_bounds"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _execute_commands(source: str) -> None:
    """Dollar-quoted routine bodies를 보존해 asyncpg statement를 분리한다 (0214와 동일)."""
    statements: list[str] = []
    start = 0
    index = 0
    quote: str | None = None
    dollar_tag: str | None = None
    while index < len(source):
        character = source[index]
        if dollar_tag is not None:
            if source.startswith(dollar_tag, index):
                index += len(dollar_tag)
                dollar_tag = None
                continue
            index += 1
            continue
        if quote is not None:
            if character == quote:
                quote = None
            index += 1
            continue
        if character in {"'", '"'}:
            quote = character
            index += 1
            continue
        if character == "$":
            end = source.find("$", index + 1)
            if end != -1:
                candidate = source[index : end + 1]
                inner = candidate[1:-1]
                if not inner or inner.replace("_", "a").isalnum():
                    dollar_tag = candidate
                    index = end + 1
                    continue
        if character == ";":
            statement = source[start:index].strip()
            if statement:
                statements.append(statement)
            start = index + 1
        index += 1
    trailing = source[start:].strip()
    if trailing:
        statements.append(trailing)
    for statement in statements:
        op.execute(statement)


_LOCK_SIG = "feature.merge_lock_legacy_curated_features(text, text)"
_ARCHIVE_SIG = "feature.merge_archive_conflicting_legacy_curated_features(text, text)"
_SYNC_SIG = "feature.merge_sync_master_legacy_curated_features(text)"
_MOVE_SIG = "feature.merge_move_legacy_curated_features(text, text)"
_LOCK_COLLECTIONS_SIG = "feature.merge_lock_curation_collections(text, text)"

_PROCEDURES_SQL = r"""
-- ① lock. merge는 Feature lifecycle을 먼저 고정한 뒤 legacy→collection→item 순서로 잠근다.
CREATE OR REPLACE PROCEDURE feature.merge_lock_legacy_curated_features(
    p_master text,
    p_loser text
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, feature, ops, x_extension
AS $$
BEGIN
    PERFORM legacy.curated_feature_id
    FROM feature.curated_features AS legacy
    WHERE legacy.feature_id IN (p_master, p_loser)
      AND NOT legacy.metadata @> '{"merge_projection_detached": true}'::jsonb
    ORDER BY legacy.curated_feature_id
    FOR UPDATE OF legacy;
END;
$$;

-- ② archive conflicting. UUID가 분리된 same-theme legacy conflict 또는 아직 이동하지 않은
--    loser UUID item과 같은 stored collection/external identity의 master canonical pair만 archive.
CREATE OR REPLACE PROCEDURE feature.merge_archive_conflicting_legacy_curated_features(
    p_master text,
    p_loser text
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, feature, ops, x_extension
AS $$
BEGIN
    UPDATE feature.curated_features AS loser_curated
    SET feature_id = p_master,
        curation_status = 'archived',
        metadata = loser_curated.metadata || jsonb_build_object(
            'merge_projection_detached',
            true
        ),
        archived_at = now(),
        updated_at = now()
    WHERE loser_curated.feature_id = p_loser
      AND loser_curated.archived_at IS NULL
      AND (
          (
              NOT EXISTS (
                  SELECT 1
                  FROM feature.curation_items AS direct_item
                  WHERE direct_item.legacy_projection_id =
                        loser_curated.curated_feature_id
                    AND direct_item.archived_at IS NULL
              )
              AND EXISTS (
                  SELECT 1
                  FROM feature.curated_features AS master_curated
                  WHERE master_curated.feature_id = p_master
                    AND master_curated.theme_id = loser_curated.theme_id
                    AND master_curated.archived_at IS NULL
                    AND NOT master_curated.metadata @>
                        '{"merge_projection_detached": true}'::jsonb
              )
          )
          OR EXISTS (
              SELECT 1
              FROM feature.curation_items AS loser_item
              JOIN feature.curation_items AS master_item
                ON master_item.collection_id = loser_item.collection_id
               AND master_item.external_item_id = loser_item.external_item_id
              WHERE master_item.feature_id = p_master
                AND loser_item.legacy_projection_id =
                    loser_curated.curated_feature_id
                AND master_item.curation_item_id <>
                    loser_item.curation_item_id
          )
      );
END;
$$;

-- ③ sync master. duplicate reconcile가 loser의 최신 operator state/tombstone을 master
--    canonical survivor에 반영했으면 master legacy projection도 같은 transaction에서 맞춘다.
CREATE OR REPLACE PROCEDURE feature.merge_sync_master_legacy_curated_features(
    p_master text
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, feature, ops, x_extension
AS $$
BEGIN
    UPDATE feature.curated_features AS legacy
    SET curation_status = CASE item.status
            WHEN 'included' THEN 'curated'
            ELSE item.status
        END,
        selection_origin = CASE
            WHEN item.operator_updated_at IS NOT NULL THEN 'admin'
            ELSE legacy.selection_origin
        END,
        selected_by = CASE
            WHEN item.status = 'included' THEN item.operator_updated_by
            ELSE legacy.selected_by
        END,
        selected_at = CASE
            WHEN item.status = 'included' THEN item.operator_updated_at
            ELSE legacy.selected_at
        END,
        rejected_by = CASE
            WHEN item.status = 'rejected' THEN item.operator_updated_by
            WHEN item.status IN ('included', 'candidate') THEN NULL
            ELSE legacy.rejected_by
        END,
        rejected_at = CASE
            WHEN item.status = 'rejected' THEN item.operator_updated_at
            WHEN item.status IN ('included', 'candidate') THEN NULL
            ELSE legacy.rejected_at
        END,
        rejection_reason = CASE
            WHEN item.status IN ('included', 'candidate') THEN NULL
            ELSE legacy.rejection_reason
        END,
        curation_relation = item.curation_relation,
        reuse_policy = item.reuse_policy,
        operator_updated_by = item.operator_updated_by,
        operator_updated_at = item.operator_updated_at,
        archived_at = item.archived_at,
        updated_at = clock_timestamp(),
        content_version = legacy.content_version + 1
    FROM feature.curation_items AS item
    WHERE item.feature_id = p_master
      AND legacy.feature_id = p_master
      AND legacy.archived_at IS NULL
      AND NOT legacy.metadata @> '{"merge_projection_detached": true}'::jsonb
      AND item.legacy_projection_id = legacy.curated_feature_id
      AND (
          legacy.curation_status,
          legacy.curation_relation,
          legacy.reuse_policy,
          legacy.operator_updated_by,
          legacy.operator_updated_at,
          legacy.archived_at
      ) IS DISTINCT FROM (
          CASE item.status
              WHEN 'included' THEN 'curated'
              ELSE item.status
          END,
          item.curation_relation,
          item.reuse_policy,
          item.operator_updated_by,
          item.operator_updated_at,
          item.archived_at
      );
END;
$$;

-- ④ move. 충돌을 정리한 뒤 남은 active/archived legacy row도 master로 옮긴다. 이 UPDATE로
--    0045 trigger가 다시 실행되어도 NEW.feature_id가 master이므로 병합이 되돌아가지 않는다.
CREATE OR REPLACE PROCEDURE feature.merge_move_legacy_curated_features(
    p_master text,
    p_loser text
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, feature, ops, x_extension
AS $$
BEGIN
    UPDATE feature.curated_features
    SET feature_id = p_master, updated_at = now()
    WHERE feature_id = p_loser;
END;
$$;

-- ⑤ canonical collections lock. Feature를 선잠근 merge와 legacy-backed writer는 legacy row를
--    거쳐 collection(parent)→item(child) 순서로 들어간다. 영향 collection은 UUID 순서로 잠가
--    import/admin writer와의 교착을 막는다. canonical — 40C 이후에도 남는다.
CREATE OR REPLACE PROCEDURE feature.merge_lock_curation_collections(
    p_master text,
    p_loser text
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, feature, ops, x_extension
AS $$
BEGIN
    PERFORM collection.collection_id
    FROM feature.curation_collections AS collection
    WHERE EXISTS (
        SELECT 1
        FROM feature.curation_items AS item
        WHERE item.collection_id = collection.collection_id
          AND item.feature_id IN (p_master, p_loser)
    )
    ORDER BY collection.collection_id
    FOR UPDATE OF collection;
END;
$$;
"""


def upgrade() -> None:
    _execute_commands(_PROCEDURES_SQL)
    for signature in (_LOCK_SIG, _ARCHIVE_SIG, _SYNC_SIG, _MOVE_SIG, _LOCK_COLLECTIONS_SIG):
        op.execute(f"ALTER PROCEDURE {signature} OWNER TO ktm_curation_command_owner")
    # 0214가 부여한 column-scoped UPDATE에 merge가 더 쓰는 두 컬럼을 추가한다.
    # `feature_id`(loser→master 이동)와 `metadata`(detached marker). SELECT는 lock에 필요.
    op.execute(
        "GRANT SELECT, UPDATE (feature_id, metadata) ON TABLE feature.curated_features "
        "TO ktm_curation_command_owner"
    )
    op.execute("SET ROLE ktm_curation_command_owner")
    for signature in (_LOCK_SIG, _ARCHIVE_SIG, _SYNC_SIG, _MOVE_SIG, _LOCK_COLLECTIONS_SIG):
        op.execute(f"REVOKE ALL ON PROCEDURE {signature} FROM PUBLIC")
        # merge는 runtime이 실행한다 (dedup review 라우터·CLI). 0214의 catalog command와
        # 달리 executor role이 따로 없다 — merge_repo가 runtime DSN에서 직접 CALL한다.
        op.execute(f"GRANT EXECUTE ON PROCEDURE {signature} TO ktm_feature_runtime")
    op.execute("SET ROLE ktm_feature_schema_owner")


def downgrade() -> None:
    raise RuntimeError(
        "0222_tvn40a_merge_runtime_role is forward-only; "
        "rebuild with the T-VN-40 release head"
    )
