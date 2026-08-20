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
2. **terminal audit item compaction.** 끝난 reconciliation의 item 1,000,000행은 더
   페이징되지 않지만 root/count는 감사 증거로 남아야 한다. header와 item이 같은 생애를
   공유하면 "item만 지우고 receipt는 남긴다"를 표현할 수 없다.

무엇. material 표와 material item 표를 만들고, 기존 snapshot을 receipt로 좁힌다. item의
PK/FK는 `(material_id, row_number)`로 옮긴다. 같은 identity에 root/count/item이 **정확히**
같은 snapshot 그룹만 material 하나로 합친다.

초안(`docs/reports/tvn41s/snapshot-material-schema.sql.draft`)과 다른 점 셋. 근거를 남긴다.

- **identity UNIQUE를 partial로 바꿨다.** 초안은 `(external_system, restore_epoch,
  material_high_watermark_relay_order)`에 평범한 UNIQUE를 걸었다. 그러면 compaction된
  material이 그 identity를 영구 점유해서, 같은 source 상태가 다시 필요해졌을 때 새
  material을 만들 수 없다. `WHERE compacted_at IS NULL` partial unique로 "살아 있는
  material은 identity마다 하나"만 강제한다.
- **`safe_high_watermark_relay_order`를 두지 않았다.** membership을 정하는 것은
  `cache_target.state_applied` event의 relay order뿐이고, 재사용 시점에 그 값의 동일성을
  `FOR SHARE OF stream` 아래에서 다시 확인한다. 그 사이에 낀 비-membership event는
  membership을 바꾸지 않으므로, 재사용 receipt는 자기 시점의 더 높은 cursor를 그대로
  쓰는 것이 안전하고 더 정확하다. 쓰이지 않을 보수적 하한을 열로 박지 않는다.
- **`material_bytes`는 NULL을 허용한다.** canonical leaf byte 수는 core의 leaf 인코딩
  (`_leaf_material`)이 정한다. 이 migration이 그 인코딩을 SQL로 옮겨 적으면 두 정의가
  갈라진다. 0230 이전 material에는 실측이 없으므로 **발명하지 않고 NULL로 둔다**.

receipt에 남긴 열의 기준. `external_system`은 stream FK와 거의 모든 조회 술어가 쓰므로
남긴다. `material_high_watermark_relay_order`는 기존 CHECK
(`high_watermark_relay_order >= material_high_watermark_relay_order`)를 정규화 과정에서
조용히 잃지 않기 위해 남기고, 복합 FK로 material의 값과 묶어 denormalization이 갈라질
수 없게 한다. `restore_epoch`/`item_count`/`merkle_root`는 그 둘 중 어느 역할도 하지
않으므로 material에서만 읽는다.

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

#: material은 `compacted_at`을 NULL에서 한 번 채우는 것 외에는 다시 쓰지 않는다.
_RECEIPT_FENCE_TRIGGER: Final[str] = "trg_poi_cache_target_snapshots_append_only"

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
      NEW.material_high_watermark_relay_order, NEW.item_count,
      NEW.material_bytes, NEW.merkle_root, NEW.materialized_at)
     IS DISTINCT FROM
     (OLD.material_id, OLD.external_system, OLD.restore_epoch,
      OLD.material_high_watermark_relay_order, OLD.item_count,
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
                    UNIQUE (material_id, external_system,
                            material_high_watermark_relay_order),
                CONSTRAINT ck_poi_cache_target_snapshot_materials_counts
                    CHECK (restore_epoch > 0
                           AND material_high_watermark_relay_order >= 0
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
    op.execute(
        text(
            f"""
            CREATE INDEX idx_cache_target_snapshot_materials_compaction
                ON {_MATERIALS} (materialized_at, material_id)
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
                material_high_watermark_relay_order, item_count, material_bytes,
                merkle_root, materialized_at
            )
            SELECT CAST(min(CAST(snapshot_id AS text)) AS uuid),
                   external_system, restore_epoch,
                   material_high_watermark_relay_order, min(item_count), NULL,
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
    op.execute(
        text(f"ALTER TABLE {_RECEIPTS} ENABLE TRIGGER {_RECEIPT_FENCE_TRIGGER}")
    )
    enabled = (
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
    if enabled != "O":
        raise RuntimeError(
            f"0230: receipt append-only fence가 다시 켜지지 않았습니다(tgenabled={enabled!r})."
        )


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
                ADD CONSTRAINT ck_poi_cache_target_snapshots_receipt_kind
                    CHECK (receipt_kind IN ('generic','reconciliation')),
                ADD CONSTRAINT ck_poi_cache_target_snapshots_cursor
                    CHECK (material_high_watermark_relay_order >= 0
                           AND high_watermark_relay_order
                               >= material_high_watermark_relay_order),
                ADD CONSTRAINT fk_cache_target_snapshots_material
                    FOREIGN KEY (material_id, external_system,
                                 material_high_watermark_relay_order)
                    REFERENCES {_MATERIALS} (material_id, external_system,
                                             material_high_watermark_relay_order)
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
    op.execute(text(f"DROP TABLE {_LEGACY_ITEMS}"))


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
