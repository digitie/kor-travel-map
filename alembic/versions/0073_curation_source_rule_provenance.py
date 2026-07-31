"""concierge source-rule projection에 검증된 link provenance를 부여한다 (T-VN-H40).

## 왜 필요한가

`0072_curation_provenance`가 `_trusted_link_sql()`에 fail-close를 넣으면서 기존 link를 전부
`match_basis='legacy_unattributed'`로 이관했다. 그 술어는 그 값을 신뢰하지 않으므로 공개
curation 표면이 전멸한다 — 격리 restore clone 실측(prod 백업 `20260731T065308Z`,
`0064~0072` 적용): 배포 전 trusted link **3,266** → 배포 후 **0**
(`docs/reports/h40-surface-restore-clone-2026-07-31.txt`).

그런데 `0072` backfill의 evidence 문구("기존 link의 선택 근거를 안전하게 복구할 수 없음")는
**concierge source-rule projection에는 사실이 아니다.** prod 실측(2026-07-31):

```
curated_features 3,044건 — 결손 0
  source_record_key  100%  → provider_sync.source_records 도달 100%
  selection_origin   100%  → source_rule 3,043 / admin 1
  content_version    100%
```

각 link에 대해 "이 provider record에서 이 rule로 나왔다"가 **완전히 재구성된다.**
`0072`가 틀린 게 아니라 범위를 넓게 잡아(`feature_id IS NOT NULL`이면 무조건) 근거가 완전한
것까지 함께 이관했다.

## 무엇을 하는가

1. `match_basis`에 **`source_rule`** 을 추가한다. 기존 4값 어디에도 해당하지 않는 근거다.
   `forward_recovery`를 재사용하지 **않는다** — 그 값은 merge 경로에서 "합쳐진 대상의 결정을
   이어받는다"는 뜻이고(`merge_repo._MOVE_CURATION_ITEMS_SQL`), projection은 merge와 무관하다.
2. **검증을 통과한 것만** `source_rule` decision을 append하고 포인터를 옮긴다.
3. 앞으로 생기는 link에도 같은 decision이 붙게 트리거를 단다. ②만 하면 배포 후 새로 만들어지는
   projection이 같은 문제를 반복해 일회성 땜질이 된다.

## 검증 술어 — fail-close를 지키는 지점

link 하나를 승격하려면 **넷 다** 참이어야 한다:

- projection의 `selection_origin = 'source_rule'`
- projection의 `feature_id`가 item의 `feature_id`와 **같다** (근거가 그 link를 가리킨다)
- projection의 `source_record_key`가 item의 것과 같다
- 그 `source_record_key`가 `provider_sync.source_records`에 **실제로 도달**한다

하나라도 실패하면 승격하지 않고 `legacy_unattributed`로 남긴다. 실측상 3,044건 전부
통과하지만 **조건 없이 통과시키지 않고 실제로 검사한다** — 그러지 않으면 fail-close가
무의미해진다.

## 트리거를 `curation_items`에 다는 이유

link을 만드는 곳은 `sync_curated_feature_collection()` 안에 **둘**이다: 신규 item INSERT와
`source_change` 시 `feature_id` UPDATE. 그 함수는 merge/detach 불변식이 얽힌 800줄이라
두 지점을 각각 손대면 회귀 위험이 크다. 대신 불변식이 실제로 사는 자리 —
"feature_id를 가진 item에는 근거가 있어야 한다" — 인 `curation_items`에 트리거를 단다.
두 지점을 모두 덮고, 앞으로 생길 writer도 자동으로 덮는다.

재진입은 유한하다: 포인터 UPDATE가 트리거를 한 번 더 부르지만 그때는 이미 신뢰 근거가
있으므로 첫 EXISTS에서 멈춘다(깊이 2 고정). 회귀 테스트로 고정한다.

Revision ID: 0073_curation_source_rule
Revises: 0072_curation_provenance
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0073_curation_source_rule"
down_revision: str | Sequence[str] | None = "0072_curation_provenance"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# 물리 이름은 naming convention(`ck_%(table_name)s_%(constraint_name)s`,
# `infra/models.py:139`)이 접두사를 한 번 더 붙여 이름이 겹쳐진 형태다.
# 논리 이름으로 쓰면 DROP이 UndefinedObject로 죽는다.
_BASIS_CHECK = "ck_curation_link_decisions_ck_curation_link_decisions_basis"

_OLD_BASIS = (
    "match_basis IN ("
    "'csv_explicit_feature_id','admin_review','legacy_unattributed',"
    "'forward_recovery'"
    ")"
)
_NEW_BASIS = (
    "match_basis IN ("
    "'csv_explicit_feature_id','admin_review','legacy_unattributed',"
    "'forward_recovery','source_rule'"
    ")"
)

_TRIGGER_NAME = "trg_curation_items_source_rule_decision"
_FUNCTION_NAME = "feature.issue_curation_source_rule_decision"

# item ↔ projection 연결. stable-identity 경로에서는 `curation_item_id`가
# `curated_feature_id`와 다를 수 있고 그때 `legacy_projection_id`가 정본이다(0065).
_PROJECTION_JOIN = (
    "cf.curated_feature_id = COALESCE(item.legacy_projection_id, item.curation_item_id)"
)

_BACKFILL_SQL = f"""
WITH promoted AS (
    INSERT INTO feature.curation_link_decisions (
        curation_item_id, feature_id, decision_kind, match_basis,
        resolver_version, evidence, actor, decided_at, supersedes_decision_id
    )
    SELECT
        item.curation_item_id,
        item.feature_id,
        'accepted',
        'source_rule',
        -- content_version은 INTEGER NOT NULL(>= 1)이다. resolver_version CHECK가
        -- 빈 문자열을 막으므로 자기 설명적인 접두사를 붙여 텍스트로 만든다.
        'source-rule-v' || cf.content_version::text,
        jsonb_build_object(
            'migration', '0073_curation_source_rule',
            'source_record_key', cf.source_record_key,
            'selection_origin', cf.selection_origin,
            'content_version', cf.content_version,
            'provider', sr.provider,
            'dataset_key', sr.dataset_key,
            'verified', jsonb_build_array(
                'selection_origin = source_rule',
                'projection.feature_id = item.feature_id',
                'projection.source_record_key = item.source_record_key',
                'source_record_key resolves in provider_sync.source_records'
            )
        ),
        COALESCE(NULLIF(btrim(cf.selected_by), ''), 'source_rule:' || sr.provider),
        COALESCE(cf.updated_at, cf.created_at, now()),
        item.accepted_link_decision_id
    FROM feature.curation_items AS item
    JOIN feature.curated_features AS cf
      ON {_PROJECTION_JOIN}
    JOIN provider_sync.source_records AS sr
      ON sr.source_record_key = cf.source_record_key
    -- 이미 신뢰 근거가 있는 link은 건드리지 않는다(멱등·재실행 안전).
    LEFT JOIN feature.curation_link_decisions AS current_decision
      ON current_decision.decision_id = item.accepted_link_decision_id
    WHERE item.feature_id IS NOT NULL
      AND cf.selection_origin = 'source_rule'
      AND cf.feature_id = item.feature_id
      AND cf.source_record_key IS NOT DISTINCT FROM item.source_record_key
      AND COALESCE(current_decision.match_basis, 'legacy_unattributed')
              = 'legacy_unattributed'
    RETURNING decision_id, curation_item_id
)
UPDATE feature.curation_items AS item
   SET accepted_link_decision_id = promoted.decision_id
  FROM promoted
 WHERE promoted.curation_item_id = item.curation_item_id
"""

_TRIGGER_FN = f"""
CREATE OR REPLACE FUNCTION {_FUNCTION_NAME}()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    projection feature.curated_features%ROWTYPE;
    source_provider text;
    source_dataset text;
    new_decision_id uuid;
BEGIN
    -- 이 (item, feature) 조합에 이미 신뢰 근거가 있으면 아무것도 하지 않는다.
    -- 아래 포인터 UPDATE로 재진입할 때 여기서 멈춘다 → 재귀 깊이 2 고정.
    IF EXISTS (
        SELECT 1
        FROM feature.curation_link_decisions AS existing
        WHERE existing.decision_id = NEW.accepted_link_decision_id
          AND existing.curation_item_id = NEW.curation_item_id
          AND existing.feature_id = NEW.feature_id
          AND existing.decision_kind = 'accepted'
          AND existing.match_basis <> 'legacy_unattributed'
    ) THEN
        RETURN NULL;
    END IF;

    SELECT * INTO projection
      FROM feature.curated_features AS cf
     WHERE cf.curated_feature_id =
           COALESCE(NEW.legacy_projection_id, NEW.curation_item_id);
    IF NOT FOUND THEN
        RETURN NULL;
    END IF;

    -- 검증 술어. 통과하지 못하면 decision을 만들지 않는다 — 그 link은 trusted가 되지
    -- 않고 운영자 검토 대상으로 남는다(fail-close 유지).
    IF projection.selection_origin IS DISTINCT FROM 'source_rule'
       OR projection.feature_id IS DISTINCT FROM NEW.feature_id
       OR projection.source_record_key IS DISTINCT FROM NEW.source_record_key
    THEN
        RETURN NULL;
    END IF;

    SELECT sr.provider, sr.dataset_key
      INTO source_provider, source_dataset
      FROM provider_sync.source_records AS sr
     WHERE sr.source_record_key = projection.source_record_key;
    IF source_provider IS NULL THEN
        RETURN NULL;
    END IF;

    INSERT INTO feature.curation_link_decisions (
        curation_item_id, feature_id, decision_kind, match_basis,
        resolver_version, evidence, actor, decided_at, supersedes_decision_id
    )
    VALUES (
        NEW.curation_item_id,
        NEW.feature_id,
        'accepted',
        'source_rule',
        'source-rule-v' || projection.content_version::text,
        jsonb_build_object(
            'writer', 'issue_curation_source_rule_decision',
            'source_record_key', projection.source_record_key,
            'selection_origin', projection.selection_origin,
            'content_version', projection.content_version,
            'provider', source_provider,
            'dataset_key', source_dataset
        ),
        COALESCE(
            NULLIF(btrim(projection.selected_by), ''),
            'source_rule:' || source_provider
        ),
        COALESCE(NEW.updated_at, now()),
        -- 직전 결정을 잇는다. 근거가 바뀐 이력이 끊기지 않게 한다.
        NEW.accepted_link_decision_id
    )
    RETURNING decision_id INTO new_decision_id;

    UPDATE feature.curation_items
       SET accepted_link_decision_id = new_decision_id
     WHERE curation_item_id = NEW.curation_item_id;

    RETURN NULL;
END;
$$
"""

# `source_record_key`가 없는 item(운영자 CSV 등)은 애초에 source-rule 근거가 될 수 없다.
# WHEN에서 걸러 트리거 본문 진입 자체를 막는다.
_TRIGGER = f"""
CREATE TRIGGER {_TRIGGER_NAME}
AFTER INSERT OR UPDATE ON feature.curation_items
FOR EACH ROW
WHEN (NEW.feature_id IS NOT NULL AND NEW.source_record_key IS NOT NULL)
EXECUTE FUNCTION {_FUNCTION_NAME}()
"""


def upgrade() -> None:
    op.execute(f"ALTER TABLE feature.curation_link_decisions DROP CONSTRAINT {_BASIS_CHECK}")
    op.execute(
        f"ALTER TABLE feature.curation_link_decisions "
        f"ADD CONSTRAINT {_BASIS_CHECK} CHECK ({_NEW_BASIS})"
    )
    # 트리거를 달기 전에 backfill한다. 순서가 바뀌어도 결과는 같지만(트리거가 멱등),
    # backfill 한 문장이 item마다 트리거를 부르는 비용을 피한다.
    op.execute(_BACKFILL_SQL)
    op.execute(_TRIGGER_FN)
    op.execute(_TRIGGER)


def downgrade() -> None:
    op.execute(f"DROP TRIGGER IF EXISTS {_TRIGGER_NAME} ON feature.curation_items")
    op.execute(f"DROP FUNCTION IF EXISTS {_FUNCTION_NAME}()")

    # decision 이력은 append-only다. 포인터를 직전 결정으로 되돌려 `source_rule`이
    # 공개 승인 근거로 쓰이지 않게 한 뒤, CHECK를 좁히기 위해 그 행들을 제거한다.
    op.execute(
        """
        UPDATE feature.curation_items AS item
           SET accepted_link_decision_id = decision.supersedes_decision_id
          FROM feature.curation_link_decisions AS decision
         WHERE decision.decision_id = item.accepted_link_decision_id
           AND decision.match_basis = 'source_rule'
        """
    )
    # append-only 트리거가 DELETE를 막는다. downgrade 전용으로 잠시 비활성화한다.
    op.execute(
        "ALTER TABLE feature.curation_link_decisions "
        "DISABLE TRIGGER trg_curation_link_decisions_append_only"
    )
    op.execute("DELETE FROM feature.curation_link_decisions WHERE match_basis = 'source_rule'")
    op.execute(
        "ALTER TABLE feature.curation_link_decisions "
        "ENABLE TRIGGER trg_curation_link_decisions_append_only"
    )
    op.execute(f"ALTER TABLE feature.curation_link_decisions DROP CONSTRAINT {_BASIS_CHECK}")
    op.execute(
        f"ALTER TABLE feature.curation_link_decisions "
        f"ADD CONSTRAINT {_BASIS_CHECK} CHECK ({_OLD_BASIS})"
    )
