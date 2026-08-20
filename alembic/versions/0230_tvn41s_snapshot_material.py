"""T-VN-41S — snapshot header에서 material과 receipt를 분리한다.

왜. `ops.poi_cache_target_snapshots` 한 표가 두 가지를 동시에 하고 있었다. 하나는
**material**(어떤 source membership을 고정했는가 — `merkle_root`/`item_count`/
`material_high_watermark_relay_order`)이고, 다른 하나는 **receipt**(누가 언제 그것을
받아갔는가 — `snapshot_id`/`created_at`/`expires_at`)다. item FK도 `snapshot_id`를
직접 가리켰다. 그래서 두 가지가 불가능했다.

1. **양방향 공유.** 같은 material을 generic page와 reconciliation이 함께 쓰려면 한쪽이
   다른 쪽의 receipt를 통째로 물려받아야 했다. reconciliation seal은 generic snapshot을
   물려받을 수 있었지만(`_GET_REUSABLE_MATERIAL_SNAPSHOT_SQL`), 반대 방향은 막혀 있다
   (`_GET_REUSABLE_SNAPSHOT_SQL`의 `NOT EXISTS (... requests ...)`). 물려받으면 만료
   시각까지 함께 물려받기 때문이다. 단방향인 이유는 설계가 아니라 표가 하나여서였다.
2. **item 되찾기.** 더 이상 페이징되지 않는 item 1,000,000행을 지우면서 root/count는
   남겨야 하는 경우가 둘이다 — 끝난 reconciliation의 감사 증거(영구 보존), 그리고 아무
   receipt도 붙잡지 않게 된 orphan(행째 삭제). header와 item이 같은 생애를 공유하면
   "item만 지우고 나머지는 남긴다"를 표현할 수 없다.

무엇. material 표와 material item 표를 만들고, 기존 snapshot을 receipt로 좁힌다. item의
PK/FK는 `(material_id, row_number)`로 옮긴다. 같은 identity에 root/count/item이 **정확히**
같은 snapshot 그룹만 material 하나로 합친다.

초안(`docs/reports/tvn41s/snapshot-material-schema.sql.draft`)과 다른 점 셋. 근거를 남긴다.

- **정리용 인덱스를 하나 더 둔다.** 초안에는 identity partial unique 하나뿐이었다.
  compaction 후보 조회는 그것을 타지만(`compacted_at IS NULL` 술어를 그대로 쓴다), GC의
  orphan material 정리는 `compacted_at`을 보지 않으므로 그 partial index에 걸리지
  못한다. 그 질의는 `external_system` equality와 `materialized_at` 순서를 쓰는데 둘을
  함께 받는 인덱스가 없으면 **다른 stream의 material까지** 훑는다.
  `idx_cache_target_snapshot_materials_sweep (external_system, materialized_at,
  material_id)`를 비-partial로 둔다.

  한 번 지웠다가 되살렸다. 지웠을 때의 근거는 "planner가 고르는 것을 보이지 못했다"였는데,
  그 측정이 `enable_seqscan = off` 아래의 반증 불가능한 단언이었다(적대 리뷰 지적).
  근거가 없어진 것이지 인덱스가 불필요하다고 밝혀진 것이 아니었다.
- **identity UNIQUE를 partial로 바꿨다.** 초안은 `(external_system, restore_epoch,
  material_high_watermark_relay_order)`에 평범한 UNIQUE를 걸었다. 그러면 compaction된
  material이 그 identity를 영구 점유해서, 같은 source 상태가 다시 필요해졌을 때 새
  material을 만들 수 없다. `WHERE compacted_at IS NULL` partial unique로 "살아 있는
  material은 identity마다 하나"만 강제한다.
- **`safe_high_watermark_relay_order`는 초안대로 둔다.** 처음에는 뺐다 — "재사용
  시점의 더 높은 cursor가 더 정확하다"고 봤는데 틀렸다. material HWM과 전역 HWM 사이에
  낀 비-membership event는 membership을 바꾸지 않지만 **consumer가 아직 처리하지 않은
  event**다. 더 높은 cursor를 광고하면 consumer가 그것들을 건너뛴다.
  `test_generic_snapshot_reuse_ignores_nonmaterial_outbox_tail`이 그 자리를 잡았다.
  material이 처음 고정될 때 관측한 전역 HWM을 적고 모든 receipt가 그 값을 쓴다.
- **`compacted_at`의 뜻이 "감사용 compaction"보다 넓다.** 초안은 terminal audit만
  염두에 뒀지만, 실제로는 orphan material도 배출 **전에** 이 표시를 받는다. 그래야
  "표시되지 않았다 = item이 온전하다"가 성립하고 재사용이 부분 배출된 material을 잡지
  않는다. 표시 없이 지우는 경로를 하나라도 남기면 그 불변이 깨진다.
- **`material_bytes`는 NULL을 허용한다.** canonical leaf byte 수는 core의 leaf 인코딩
  (`_leaf_material`)이 정한다. 이 migration이 그 인코딩을 SQL로 옮겨 적으면 두 정의가
  갈라진다. 0230 이전 material에는 실측이 없으므로 **발명하지 않고 NULL로 둔다**.

receipt에 남긴 열의 기준. `external_system`만 남는다 — stream FK와 거의 모든 조회
술어가 쓰기 때문이고, 복합 FK로 material의 값과 묶어 사본이 갈라질 수 없게 한다. 두 HWM은
둘 다 material로 간다(위 참조). 그래서 기존 CHECK
`high_watermark_relay_order >= material_high_watermark_relay_order`는 사라지지 않고
material 안의 `safe_high_watermark_relay_order >= material_high_watermark_relay_order`가
된다. `restore_epoch`/`item_count`/`merkle_root`도 material에서만 읽는다.

fence. `ops.poi_cache_target_snapshots`와 `..._snapshot_items`에는
`ops.reject_cache_target_history_mutation()` append-only trigger가 걸려 있다. 두 가지를
한다.

- **backfill UPDATE 동안만 receipt fence를 끈다.** 0229는 fence를 끄지 않았는데, 그것은
  그 fence가 "비활성 dataset의 rule을 고치지 말라"는 **데이터 정합성** 규칙이라 막히는
  것 자체가 신호였기 때문이다. 여기 fence는 "receipt는 다시 쓰지 않는다"는 이력 규칙이고,
  이 migration은 그 이력을 **어디에 담을지**를 바꾸는 구조 변경이라 fence가 말할 것이
  없다. 같은 transaction 안에서 끄고 되켠다.
- **새 표에도 같은 fence를 건다.** 정규화하면서 조용히 append-only를 잃지 않게 한다.
  material item은 legacy item과 똑같이 UPDATE/TRUNCATE만 막는다(compaction DELETE는
  허용해야 한다). material은 `compacted_at`을 NULL에서 한 번 채우는 것만 허용하고 나머지
  열이 함께 바뀌면 막는 전용 fence를 쓴다 — root/count가 조용히 다시 쓰이면 감사 증거가
  증거가 아니게 된다.

forward-only. downgrade는 두지 않는다(ADR-021). 이 migration은 N개 receipt를 material
하나로 합치므로, 되돌리려면 합쳐진 item을 receipt 수만큼 **다시 복제**해야 한다. 그것은
이 migration이 없애려는 저장 형태 자체이고, compaction이 한 번이라도 돌면 item은 root와
count에서 복원할 수 없다.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Final

from sqlalchemy import text

from alembic import op

revision: str = "0230_tvn41s_snapshot_material"
down_revision: str | Sequence[str] | None = "0229_tvn40b_source_rule_action"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_MATERIALS: Final[str] = "ops.poi_cache_target_snapshot_materials"
_MATERIAL_ITEMS: Final[str] = "ops.poi_cache_target_snapshot_material_items"
_RECEIPTS: Final[str] = "ops.poi_cache_target_snapshots"
_LEGACY_ITEMS: Final[str] = "ops.poi_cache_target_snapshot_items"

_RECEIPT_FENCE_TRIGGER: Final[str] = "trg_poi_cache_target_snapshots_append_only"

#: `compacted_at`은 **"이 material의 item을 되찾기 시작했다"**는 한 방향 표시다.
#:
#: 이 fence가 지키는 것은 감사 증거만이 아니다. item은 표시된 뒤에만 지우고
#: (`_PRUNE_ORPHANED_MATERIAL_ITEMS_SQL`), 재사용은 표시된 material을 잡지 않으므로
#: (`_GET_REUSABLE_MATERIAL_SQL`), **"표시되지 않았다"가 곧 "item이 온전하다"**가 된다.
#: 그 불변을 성립시키는 것이 여기서 표시를 되돌릴 수 없게 만드는 일이다. 되돌릴 수 있으면
#: 부분 배출된 material이 다시 재사용 가능해지고, consumer가 실제보다 큰 count/root와
#: 함께 모자란 page를 받는다.
#:
#: 표시 대상은 둘이다 — 보존 기간을 넘긴 terminal audit material(표시가 영구히 남고 그
#: receipt의 page는 410이 된다)과 orphan material(표를 비운 뒤 행째 사라진다). 그래서
#: 이 표시를 "감사용 compaction"으로만 읽으면 안 된다.
_MATERIAL_FENCE_SQL: Final[str] = """
CREATE FUNCTION ops.reject_snapshot_material_mutation() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF OLD.compacted_at IS NOT NULL THEN
    RAISE EXCEPTION 'snapshot material is already compacted'
      USING ERRCODE = '55000';
  END IF;
  IF NEW.compacted_at IS NULL THEN
    RAISE EXCEPTION 'snapshot material is append-only except compaction'
      USING ERRCODE = '55000';
  END IF;
  IF (NEW.material_id, NEW.external_system, NEW.restore_epoch,
      NEW.material_high_watermark_relay_order,
      NEW.safe_high_watermark_relay_order, NEW.item_count,
      NEW.material_bytes, NEW.merkle_root, NEW.materialized_at)
     IS DISTINCT FROM
     (OLD.material_id, OLD.external_system, OLD.restore_epoch,
      OLD.material_high_watermark_relay_order,
      OLD.safe_high_watermark_relay_order, OLD.item_count,
      OLD.material_bytes, OLD.merkle_root, OLD.materialized_at) THEN
    RAISE EXCEPTION 'snapshot material compaction must not change the material'
      USING ERRCODE = '55000';
  END IF;
  RETURN NEW;
END;
$$
"""

#: 그룹 안에서 item이 정말 같은지 보는 지문. `target_key`에 구분자가 들어가도 갈라지지
#: 않도록 길이를 함께 넣는다.
_ITEM_FINGERPRINT_SQL: Final[str] = r"""
WITH receipt AS (
  SELECT snapshot_id, external_system, restore_epoch,
         material_high_watermark_relay_order AS material_order
  FROM ops.poi_cache_target_snapshots
),
fingerprint AS (
  SELECT receipt.external_system, receipt.restore_epoch, receipt.material_order,
         receipt.snapshot_id,
         md5(coalesce(string_agg(
           item.row_number::text || ':' ||
           octet_length(item.target_key)::text || ':' || item.target_key || ':' ||
           item.state || ':' || item.source_generation::text || ':' ||
           item.source_payload_fingerprint,
           E'\n' ORDER BY item.row_number
         ), '')) AS items_digest
  FROM receipt
  LEFT JOIN ops.poi_cache_target_snapshot_items AS item
    ON item.snapshot_id = receipt.snapshot_id
  GROUP BY receipt.external_system, receipt.restore_epoch, receipt.material_order,
           receipt.snapshot_id
)
SELECT external_system, restore_epoch, material_order,
       count(DISTINCT items_digest) AS variants
FROM fingerprint
GROUP BY external_system, restore_epoch, material_order
HAVING count(DISTINCT items_digest) > 1
ORDER BY external_system, restore_epoch, material_order
"""

_HEADER_DIVERGENCE_SQL: Final[str] = """
SELECT external_system, restore_epoch,
       material_high_watermark_relay_order AS material_order,
       count(DISTINCT merkle_root) AS roots,
       count(DISTINCT item_count) AS counts
FROM ops.poi_cache_target_snapshots
GROUP BY external_system, restore_epoch, material_high_watermark_relay_order
HAVING count(DISTINCT merkle_root) > 1 OR count(DISTINCT item_count) > 1
ORDER BY external_system, restore_epoch, material_high_watermark_relay_order
"""


def _assert_groups_are_mergeable() -> None:
    """합치기 전에 그룹이 정말 같은지 본다. 다르면 조용히 하나를 고르지 않고 선다."""

    bind = op.get_bind()
    divergent = bind.execute(text(_HEADER_DIVERGENCE_SQL)).all()
    if divergent:
        raise RuntimeError(
            "0230: 같은 material identity의 snapshot header가 서로 다른 "
            "merkle_root/item_count를 갖습니다 — 합치면 둘 중 하나를 조용히 "
            f"버리게 됩니다: {[tuple(row) for row in divergent]}"
        )
    mixed = bind.execute(text(_ITEM_FINGERPRINT_SQL)).all()
    if mixed:
        raise RuntimeError(
            "0230: 같은 material identity의 snapshot item 집합이 서로 다릅니다 — "
            "root가 같은데 item이 다르다면 그 자체가 조사 대상입니다: "
            f"{[tuple(row) for row in mixed]}"
        )


def _create_material_tables() -> None:
    op.execute(
        text(
            f"""
            CREATE TABLE {_MATERIALS} (
                material_id uuid NOT NULL
                    DEFAULT x_extension.gen_random_uuid(),
                external_system text NOT NULL,
                restore_epoch bigint NOT NULL,
                material_high_watermark_relay_order bigint NOT NULL,
                safe_high_watermark_relay_order bigint NOT NULL,
                item_count bigint NOT NULL,
                material_bytes bigint,
                merkle_root text NOT NULL,
                materialized_at timestamptz NOT NULL DEFAULT now(),
                compacted_at timestamptz,
                CONSTRAINT pk_poi_cache_target_snapshot_materials
                    PRIMARY KEY (material_id),
                CONSTRAINT fk_cache_target_snapshot_materials_stream
                    FOREIGN KEY (external_system)
                    REFERENCES ops.poi_cache_target_streams(external_system)
                    ON DELETE RESTRICT,
                CONSTRAINT uq_cache_target_snapshot_materials_receipt
                    UNIQUE (material_id, external_system),
                CONSTRAINT ck_poi_cache_target_snapshot_materials_counts
                    CHECK (restore_epoch > 0
                           AND material_high_watermark_relay_order >= 0
                           AND safe_high_watermark_relay_order
                               >= material_high_watermark_relay_order
                           AND item_count >= 0
                           AND (material_bytes IS NULL OR material_bytes >= 0)),
                CONSTRAINT ck_poi_cache_target_snapshot_materials_root
                    CHECK (merkle_root ~ '^[0-9a-f]{{64}}$'),
                CONSTRAINT ck_poi_cache_target_snapshot_materials_compaction
                    CHECK (compacted_at IS NULL OR compacted_at >= materialized_at)
            )
            """
        )
    )
    op.execute(
        text(
            f"""
            CREATE UNIQUE INDEX uq_cache_target_snapshot_materials_live_identity
                ON {_MATERIALS} (
                    external_system, restore_epoch,
                    material_high_watermark_relay_order
                )
                WHERE compacted_at IS NULL
            """
        )
    )
    op.execute(text(_MATERIAL_FENCE_SQL))
    op.execute(
        text(
            "ALTER FUNCTION ops.reject_snapshot_material_mutation() "
            "OWNER TO ktm_feature_schema_owner"
        )
    )
    op.execute(
        text(
            f"""
            CREATE TRIGGER trg_poi_cache_target_snapshot_materials_compaction_only
                BEFORE UPDATE ON {_MATERIALS}
                FOR EACH ROW
                EXECUTE FUNCTION ops.reject_snapshot_material_mutation()
            """
        )
    )
    op.execute(
        text(
            f"""
            CREATE TRIGGER trg_poi_cache_target_snapshot_materials_no_truncate
                BEFORE TRUNCATE ON {_MATERIALS}
                FOR EACH STATEMENT
                EXECUTE FUNCTION ops.reject_cache_target_history_mutation()
            """
        )
    )
    op.execute(
        text(
            f"""
            CREATE INDEX idx_cache_target_snapshot_materials_sweep
                ON {_MATERIALS} (external_system, materialized_at, material_id)
            """
        )
    )
    op.execute(
        text(
            f"""
            CREATE TABLE {_MATERIAL_ITEMS} (
                material_id uuid NOT NULL,
                row_number bigint NOT NULL,
                target_key text NOT NULL,
                state text NOT NULL,
                source_generation bigint NOT NULL,
                source_payload_fingerprint text NOT NULL,
                CONSTRAINT pk_poi_cache_target_snapshot_material_items
                    PRIMARY KEY (material_id, row_number),
                CONSTRAINT fk_cache_target_snapshot_material_items_material
                    FOREIGN KEY (material_id)
                    REFERENCES {_MATERIALS}(material_id)
                    ON DELETE CASCADE,
                CONSTRAINT uq_cache_target_snapshot_material_items_key
                    UNIQUE (material_id, target_key),
                CONSTRAINT ck_poi_cache_target_snapshot_material_items_bounds
                    CHECK (row_number > 0 AND source_generation > 0),
                CONSTRAINT ck_poi_cache_target_snapshot_material_items_state
                    CHECK (state IN ('active','deleted')),
                CONSTRAINT ck_poi_cache_target_snapshot_material_items_digest
                    CHECK (source_payload_fingerprint ~ '^[0-9a-f]{{64}}$')
            )
            """
        )
    )
    # legacy item 표와 같은 강도다. compaction DELETE는 허용해야 하므로 UPDATE와
    # TRUNCATE만 막는다.
    op.execute(
        text(
            f"""
            CREATE TRIGGER trg_poi_cache_target_snapshot_material_items_append_only
                BEFORE UPDATE ON {_MATERIAL_ITEMS}
                FOR EACH ROW
                EXECUTE FUNCTION ops.reject_cache_target_history_mutation()
            """
        )
    )
    op.execute(
        text(
            f"""
            CREATE TRIGGER trg_poi_cache_target_snapshot_material_items_no_truncate
                BEFORE TRUNCATE ON {_MATERIAL_ITEMS}
                FOR EACH STATEMENT
                EXECUTE FUNCTION ops.reject_cache_target_history_mutation()
            """
        )
    )


def _backfill_materials() -> None:
    # 그룹 대표는 `min(snapshot_id)`다 — 결정적이고, 어느 receipt에서 왔는지 나중에
    # 되짚을 수 있다. PostgreSQL에는 `min(uuid)` aggregate가 없어 canonical text로
    # 비교한다(자릿수가 고정이라 text 순서와 uuid 순서가 같다).
    # `material_bytes`는 위 docstring대로 실측이 없어 NULL이다.
    op.execute(
        text(
            f"""
            INSERT INTO {_MATERIALS} (
                material_id, external_system, restore_epoch,
                material_high_watermark_relay_order,
                safe_high_watermark_relay_order, item_count, material_bytes,
                merkle_root, materialized_at
            )
            SELECT CAST(min(CAST(snapshot_id AS text)) AS uuid),
                   external_system, restore_epoch,
                   material_high_watermark_relay_order,
                   -- receipt마다 값이 다를 수 있다. 보수적으로 **가장 낮은** 것을
                   -- 고른다 — cursor를 높게 잡으면 consumer가 event를 건너뛴다.
                   min(high_watermark_relay_order),
                   min(item_count), NULL,
                   min(merkle_root), min(created_at)
            FROM {_RECEIPTS}
            GROUP BY external_system, restore_epoch,
                     material_high_watermark_relay_order
            """
        )
    )
    op.execute(
        text(
            f"""
            INSERT INTO {_MATERIAL_ITEMS} (
                material_id, row_number, target_key, state,
                source_generation, source_payload_fingerprint
            )
            SELECT item.snapshot_id, item.row_number, item.target_key, item.state,
                   item.source_generation, item.source_payload_fingerprint
            FROM {_LEGACY_ITEMS} AS item
            JOIN {_MATERIALS} AS material
              ON material.material_id = item.snapshot_id
            """
        )
    )
    op.execute(
        text(
            f"""
            ALTER TABLE {_RECEIPTS}
                ADD COLUMN material_id uuid,
                ADD COLUMN receipt_kind text
            """
        )
    )
    # 아래 UPDATE 한 문장만을 위해 끈다. 켜는 것을 같은 함수 안에 둬서, 중간에
    # 실패하면 transaction이 통째로 되감기고 fence가 꺼진 채 남지 않는다.
    #
    # 끄기 **전** 상태를 잡아 둔다. 되켠 뒤에 `'O'` 리터럴과 비교하면 항진명제다
    # (`ENABLE TRIGGER`가 실패했다면 그 문장에서 이미 abort된다). 원래 `'A'`(ENABLE
    # ALWAYS)나 `'R'`였다면 되켜기가 조용히 `'O'`로 낮추는데, 리터럴 비교는 그것을
    # 통과시킨다(적대 리뷰 지적).
    before_fence = _receipt_fence_state()
    op.execute(
        text(f"ALTER TABLE {_RECEIPTS} DISABLE TRIGGER {_RECEIPT_FENCE_TRIGGER}")
    )
    op.execute(
        text(
            f"""
            UPDATE {_RECEIPTS} AS receipt
            SET material_id = material.material_id,
                receipt_kind = CASE
                    WHEN EXISTS (
                        SELECT 1
                        FROM ops.poi_cache_target_reconciliation_requests AS request
                        WHERE request.snapshot_id = receipt.snapshot_id
                    ) THEN 'reconciliation'
                    ELSE 'generic'
                END
            FROM {_MATERIALS} AS material
            WHERE material.external_system = receipt.external_system
              AND material.restore_epoch = receipt.restore_epoch
              AND material.material_high_watermark_relay_order
                  = receipt.material_high_watermark_relay_order
            """
        )
    )
    if before_fence == "D":
        raise RuntimeError(
            "0230: receipt append-only fence가 migration 시작 시점에 이미 꺼져 있었습니다."
        )
    enable_mode = {"A": "ENABLE ALWAYS", "R": "ENABLE REPLICA"}.get(
        before_fence, "ENABLE"
    )
    op.execute(
        text(
            f"ALTER TABLE {_RECEIPTS} {enable_mode} "
            f"TRIGGER {_RECEIPT_FENCE_TRIGGER}"
        )
    )
    after_fence = _receipt_fence_state()
    if after_fence != before_fence:
        raise RuntimeError(
            "0230: receipt append-only fence 상태가 바뀐 채 남았습니다"
            f"(before={before_fence!r} after={after_fence!r})."
        )


def _receipt_fence_state() -> str:
    """`pg_trigger.tgenabled`를 문자로 읽는다.

    asyncpg는 PostgreSQL ``char``를 bytes로 준다 — `str(b'O')`는 `"b'O'"`가 되어
    비교가 항상 어긋난다(`_runtime_relation_grants`의 relkind와 같은 자리다).
    """

    raw = (
        op.get_bind()
        .execute(
            text(
                """
                SELECT tgenabled
                FROM pg_trigger
                WHERE tgname = :trigger
                  AND tgrelid = 'ops.poi_cache_target_snapshots'::regclass
                """
            ),
            {"trigger": _RECEIPT_FENCE_TRIGGER},
        )
        .scalar_one()
    )
    return raw.decode("ascii") if isinstance(raw, bytes) else str(raw)


def _assert_backfill_lost_nothing() -> None:
    """legacy 표를 지우기 전에, 옮겨지지 않은 것이 하나도 없는지 센다."""

    bind = op.get_bind()
    unbound = bind.execute(
        text(f"SELECT count(*) FROM {_RECEIPTS} WHERE material_id IS NULL")
    ).scalar_one()
    if unbound:
        raise RuntimeError(
            f"0230: material에 묶이지 못한 snapshot receipt가 {unbound}건 남았습니다."
        )
    orphaned = bind.execute(
        text(
            f"""
            SELECT count(*)
            FROM {_LEGACY_ITEMS} AS item
            JOIN {_RECEIPTS} AS receipt
              ON receipt.snapshot_id = item.snapshot_id
            WHERE NOT EXISTS (
                SELECT 1
                FROM {_MATERIAL_ITEMS} AS moved
                WHERE moved.material_id = receipt.material_id
                  AND moved.row_number = item.row_number
                  AND moved.target_key = item.target_key
                  AND moved.state = item.state
                  AND moved.source_generation = item.source_generation
                  AND moved.source_payload_fingerprint
                      = item.source_payload_fingerprint
            )
            """
        )
    ).scalar_one()
    if orphaned:
        raise RuntimeError(
            f"0230: 새 material item으로 옮겨지지 않은 legacy item이 {orphaned}행 "
            "남았습니다 — legacy 표를 지우면 그만큼 잃습니다."
        )
    miscounted = bind.execute(
        text(
            f"""
            SELECT count(*)
            FROM {_MATERIALS} AS material
            WHERE material.item_count <> (
                SELECT count(*)
                FROM {_MATERIAL_ITEMS} AS moved
                WHERE moved.material_id = material.material_id
            )
            """
        )
    ).scalar_one()
    if miscounted:
        raise RuntimeError(
            f"0230: item_count와 실제 material item 수가 다른 material이 "
            f"{miscounted}건입니다."
        )


def _narrow_receipts() -> None:
    # legacy item 표를 먼저 지운다. 그 표의 FK가
    # `uq_cache_target_snapshots_stream` 인덱스에 걸려 있어, 순서를 바꾸면 아래
    # ALTER가 `DependentObjectsStillExistError`로 막힌다.
    op.execute(text(f"DROP TABLE {_LEGACY_ITEMS}"))
    op.execute(
        text(
            f"""
            ALTER TABLE {_RECEIPTS}
                ALTER COLUMN material_id SET NOT NULL,
                ALTER COLUMN receipt_kind SET NOT NULL,
                DROP CONSTRAINT
                    ck_poi_cache_target_snapshots_ck_cache_target_snapshots_0ecd,
                DROP CONSTRAINT
                    ck_poi_cache_target_snapshots_ck_cache_target_snapshots_counts,
                DROP CONSTRAINT uq_cache_target_snapshots_stream,
                DROP COLUMN restore_epoch,
                DROP COLUMN item_count,
                DROP COLUMN merkle_root,
                DROP COLUMN high_watermark_relay_order,
                DROP COLUMN material_high_watermark_relay_order,
                ADD CONSTRAINT ck_poi_cache_target_snapshots_receipt_kind
                    CHECK (receipt_kind IN ('generic','reconciliation')),
                ADD CONSTRAINT fk_cache_target_snapshots_material
                    FOREIGN KEY (material_id, external_system)
                    REFERENCES {_MATERIALS} (material_id, external_system)
                    ON DELETE RESTRICT
            """
        )
    )
    op.execute(
        text(
            f"""
            CREATE INDEX idx_cache_target_snapshots_material
                ON {_RECEIPTS} (material_id, expires_at, snapshot_id)
            """
        )
    )


def upgrade() -> None:
    _assert_groups_are_mergeable()
    _create_material_tables()
    _backfill_materials()
    _assert_backfill_lost_nothing()
    _narrow_receipts()

    bind = op.get_bind()
    materials = bind.execute(text(f"SELECT count(*) FROM {_MATERIALS}")).scalar_one()
    receipts = bind.execute(text(f"SELECT count(*) FROM {_RECEIPTS}")).scalar_one()
    print(
        "0230 tvn41s snapshot material/receipt split: "
        f"material {materials}건 · receipt {receipts}건"
    )


def downgrade() -> None:
    raise RuntimeError(
        "0230_tvn41s_snapshot_material is forward-only; "
        "receipt N개가 material 하나를 공유하므로 되돌리려면 item을 receipt 수만큼 "
        "다시 복제해야 하고, compaction 뒤에는 item을 root/count에서 복원할 수 "
        "없다(ADR-021)."
    )
