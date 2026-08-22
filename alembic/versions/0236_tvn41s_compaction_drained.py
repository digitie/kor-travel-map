"""T-VN-41S 후속 — compacted material의 배출 완료를 상태로 기록한다.

Revision ID: 0236_tvn41s_compaction_drained
Revises: 0235_m05_reconciliation_delivery

GC batch의 backlog 판정에는 "표시됐고 item이 남은 material" 분기가 있다. 그것을
``compacted_at IS NOT NULL AND EXISTS(item)``으로 재면 **compacted material 하나마다
item 인덱스 probe 한 번**이다. audit material은 증거로 영구 보존되므로 그 수가 단조
증가하고, 비용이 가장 큰 때가 하필 **한가할 때**다 — backlog가 있으면 첫 hit에서 멈추지만
없으면 전부 훑고 나서 false를 낸다. 상한이 없다.

``compaction_drained_at``을 두어 그 질문을 상태 조회로 바꾼다. "표시됐지만 아직 배출
중"만 partial index에 들어가므로, backlog가 없을 때 판정이 상수 시간으로 떨어진다.
배출이 끝난 material은 색인에서 빠지고 다시는 훑이지 않는다.

orphan 갈래도 receipt anti-join을 backlog tick마다 반복하지 않는다. receipt가 마지막으로
삭제되는 순간 orphaned_at을 단방향으로 기록하고 orphan partial index에서만 읽는다.
표시된 material에는 새 receipt를 붙일 수 없게 해, 상태가 stale해지지 않는다는 것을
DB trigger가 보장한다.

두 시각은 각각 **한 방향**이다. ``compacted_at``은 "회수를 시작했다", ``compaction_drained_at``
은 "item을 다 비웠다"이고 둘 다 NULL에서 한 번만 채워진다. 그래서 append-only fence를
새로 쓴다 — 예전 fence는 ``OLD.compacted_at IS NOT NULL``이면 무조건 거부해서 배출 표시
자체가 불가능했다.

forward-only. 되돌리려면 배출 완료 사실을 잃고 GC가 이미 빈 material을 영원히 다시
훑게 된다.

**잠금 프로파일.** 이 migration은 `ADD COLUMN`부터 commit까지 `ACCESS EXCLUSIVE`를 쥐고,
그 안에서 검증형 `ADD CONSTRAINT ... CHECK`(전수 스캔)·전량 backfill·비-`CONCURRENTLY`
`CREATE INDEX`를 한다. 이 head에서 그 표는 prod 기준 0행이라 순간이다. 그러나 이 표는
설계상 **단조 증가**하므로, 행이 쌓인 DB(복원본·다른 환경·나중 baseline 재구축)에 이걸
그대로 다시 돌리면 snapshot 경로가 그 시간만큼 멈춘다. 그때는 `NOT VALID` + 별도
`VALIDATE`, batch backfill, autocommit block의 `CONCURRENTLY` index로 나눠야 한다.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0236_tvn41s_compaction_drained"
down_revision: str | Sequence[str] | None = "0235_m05_reconciliation_delivery"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_ADD_COLUMN_SQL = """
ALTER TABLE ops.poi_cache_target_snapshot_materials
    ADD COLUMN compaction_drained_at timestamptz,
    ADD COLUMN orphaned_at timestamptz
"""

#: 배출은 표시 이후에만 있을 수 있고, 표시보다 앞설 수 없다. 두 시각의 순서를 DB가 쥔다.
_ADD_CHECK_SQL = """
ALTER TABLE ops.poi_cache_target_snapshot_materials
    ADD CONSTRAINT ck_poi_cache_target_snapshot_materials_drained_after_compacted
    CHECK (
        compaction_drained_at IS NULL
        OR (compacted_at IS NOT NULL AND compaction_drained_at >= compacted_at)
    ),
    ADD CONSTRAINT ck_poi_cache_target_snapshot_materials_orphaned_at
    CHECK (orphaned_at IS NULL OR orphaned_at >= materialized_at)
"""

#: 이 index가 이 migration의 목적이다. "표시됐지만 아직 배출 중"만 담으므로 배출이 끝난
#: material은 빠진다 — 그래서 audit material이 아무리 쌓여도 backlog 판정이 커지지 않는다.
_ADD_INDEX_SQL = """
CREATE INDEX idx_poi_cache_target_snapshot_materials_draining
    ON ops.poi_cache_target_snapshot_materials (material_id)
    WHERE compacted_at IS NOT NULL AND compaction_drained_at IS NULL
"""

_DROP_SWEEP_INDEX_SQL = """
DROP INDEX ops.idx_cache_target_snapshot_materials_sweep
"""

_ADD_ORPHAN_INDEX_SQL = """
CREATE INDEX idx_cache_target_snapshot_materials_orphaned
    ON ops.poi_cache_target_snapshot_materials (external_system, materialized_at, material_id)
    WHERE orphaned_at IS NOT NULL
"""

#: 이미 비어 있는 compacted material을 배출 완료로 표시한다. 이것을 하지 않으면 기존
#: material이 전부 "배출 중"으로 남아 새 index가 옛 전수 스캔과 같은 크기가 된다 —
#: 즉 migration이 아무것도 고치지 않은 것과 같아진다.
_BACKFILL_SQL = """
UPDATE ops.poi_cache_target_snapshot_materials AS material
   SET compaction_drained_at = material.compacted_at
 WHERE material.compacted_at IS NOT NULL
   AND material.compaction_drained_at IS NULL
   AND NOT EXISTS (
     SELECT 1
     FROM ops.poi_cache_target_snapshot_material_items AS item
     WHERE item.material_id = material.material_id
   )
"""

_BACKFILL_ORPHANED_SQL = """
UPDATE ops.poi_cache_target_snapshot_materials AS material
   SET orphaned_at = COALESCE(material.compacted_at, clock_timestamp())
 WHERE material.orphaned_at IS NULL
   AND NOT EXISTS (
     SELECT 1
     FROM ops.poi_cache_target_snapshots AS receipt
     WHERE receipt.material_id = material.material_id
   )
"""

#: 예전 fence는 ``OLD.compacted_at IS NOT NULL``이면 무조건 거부했다. 배출 표시가 바로 그
#: 전이라 새로 쓴다. 두 시각 모두 NULL → NOT NULL 한 방향이고, 나머지 열은 여전히 불변이다.
_REPLACE_FENCE_SQL = """
CREATE OR REPLACE FUNCTION ops.reject_snapshot_material_mutation() RETURNS trigger
LANGUAGE plpgsql AS $reject_snapshot_material_mutation$
BEGIN
  -- 검사 **순서가 계약이다**. "표시가 아예 아니다"를 불변성보다 먼저 본다.
  -- 그래야 `SET item_count = 99`(표시 없이 내용만 바꿈)와
  -- `SET compacted_at = now(), merkle_root = ...`(표시를 구실로 내용도 바꿈)이
  -- 서로 다른 이유로 거부되고, 운영자가 어느 규칙에 걸렸는지 알 수 있다.
  -- 배출 전제 위반을 가장 먼저 본다. 뒤에 두면 "표시가 아니다"가 먼저 잡아
  -- 일반 문구로 거부되고, 무엇을 어겼는지가 메시지에서 사라진다.
  IF NEW.compaction_drained_at IS NOT NULL AND NEW.compacted_at IS NULL THEN
    RAISE EXCEPTION 'snapshot material cannot be drained before it is compacted'
      USING ERRCODE = '55000';
  END IF;

  IF NEW.orphaned_at IS NOT NULL
     AND OLD.orphaned_at IS NULL
     AND pg_trigger_depth() < 2 THEN
    RAISE EXCEPTION 'snapshot material orphan mark is managed by the receipt trigger'
      USING ERRCODE = '55000';
  END IF;

  IF OLD.orphaned_at IS NOT NULL
     AND NEW.orphaned_at IS DISTINCT FROM OLD.orphaned_at THEN
    RAISE EXCEPTION 'snapshot material orphan mark is one-way'
      USING ERRCODE = '55000';
  END IF;

  -- 배출 표시는 item이 모두 사라진 뒤에만 찍는다. 이 검사가 없으면
  -- `SET compacted_at = ..., compaction_drained_at = ...` 한 문장이나
  -- 이미 compacted된 행에 대한 직접 drained 표기가 partial index에서 빠지게 해
  -- 남은 item을 영구히 놓친다. item INSERT fence가 material 행 잠금으로
  -- 동시 삽입도 직렬화한다.
  IF NEW.compaction_drained_at IS NOT NULL
     AND OLD.compaction_drained_at IS NULL
     AND EXISTS (
       SELECT 1
       FROM ops.poi_cache_target_snapshot_material_items AS item
       WHERE item.material_id = NEW.material_id
     ) THEN
    RAISE EXCEPTION 'snapshot material cannot be marked drained while items remain'
      USING ERRCODE = '55000';
  END IF;

  IF NEW.compacted_at IS NULL THEN
    IF NOT (
      NEW.orphaned_at IS NOT DISTINCT FROM OLD.orphaned_at
      AND to_jsonb(NEW) - 'compacted_at' - 'compaction_drained_at' - 'orphaned_at'
        IS NOT DISTINCT FROM
      to_jsonb(OLD) - 'compacted_at' - 'compaction_drained_at' - 'orphaned_at'
      OR (
        NEW.orphaned_at IS NOT NULL
        AND OLD.orphaned_at IS NULL
        AND pg_trigger_depth() >= 2
        AND to_jsonb(NEW) - 'compacted_at' - 'compaction_drained_at' - 'orphaned_at'
          IS NOT DISTINCT FROM
        to_jsonb(OLD) - 'compacted_at' - 'compaction_drained_at' - 'orphaned_at'
      )
    ) THEN
      RAISE EXCEPTION 'snapshot material is append-only except compaction'
        USING ERRCODE = '55000';
    END IF;
  END IF;

  -- **열을 열거하지 않는다.** `0231` fence는 이미 표시된 행을 첫 문장에서 통째로
  -- 거부해서 닫힌 기본값이었다. 배출 표시를 허용하려면 그 문을 열어야 하는데, 열면서
  -- 불변 열을 손으로 열거하면 기본값이 **뒤집힌다** — 다음 migration이 이 표에 열을
  -- 더하는 순간 그 열은 아무 규칙도 보지 않아 compacted 행에서 조용히 쓰기 가능해지고,
  -- 어떤 테스트도 그것을 보지 못한다. 감사 증거를 지키는 fence에서 그 성질을 잃을 수
  -- 없으므로, 두 표시 열만 제외하고 **나머지 전부**를 비교한다.
  IF to_jsonb(NEW) - 'compacted_at' - 'compaction_drained_at' - 'orphaned_at'
     IS DISTINCT FROM
     to_jsonb(OLD) - 'compacted_at' - 'compaction_drained_at' - 'orphaned_at' THEN
    RAISE EXCEPTION 'snapshot material compaction must not change the material'
      USING ERRCODE = '55000';
  END IF;

  -- 두 표시는 각각 한 방향이다. 이미 찍힌 값을 바꾸거나 지우는 것을 막는다.
  IF OLD.compacted_at IS NOT NULL
     AND NEW.compacted_at IS DISTINCT FROM OLD.compacted_at THEN
    RAISE EXCEPTION 'snapshot material compaction mark is one-way'
      USING ERRCODE = '55000';
  END IF;

  IF OLD.compaction_drained_at IS NOT NULL
     AND NEW.compaction_drained_at IS DISTINCT FROM OLD.compaction_drained_at THEN
    RAISE EXCEPTION 'snapshot material drain mark is one-way'
      USING ERRCODE = '55000';
  END IF;

  -- 이미 표시된 행에 대한 UPDATE는 **배출 표시일 때만** 허용한다. 그 밖에는
  -- 예전과 같이 "이미 compaction됐다"로 거부한다.
  IF OLD.compacted_at IS NOT NULL
     AND NEW.compaction_drained_at IS NULL
     AND NEW.orphaned_at IS NOT DISTINCT FROM OLD.orphaned_at THEN
    RAISE EXCEPTION 'snapshot material is already compacted'
      USING ERRCODE = '55000';
  END IF;

  RETURN NEW;
END;
$reject_snapshot_material_mutation$
"""

_MATERIAL_ITEM_INSERT_FENCE_SQL = """
CREATE OR REPLACE FUNCTION ops.reject_snapshot_material_item_insert() RETURNS trigger
LANGUAGE plpgsql AS $reject_snapshot_material_item_insert$
DECLARE
  material_compacted_at timestamptz;
  material_drained_at timestamptz;
BEGIN
  -- compaction UPDATE와 item INSERT가 엇갈리지 않게 부모 material 행을 FOR UPDATE로
  -- 잠근다. (FOR KEY SHARE는 일반 UPDATE의 NO KEY UPDATE 잠금과 충돌하지 않는다.)
  -- UPDATE가 먼저면 여기서 terminal 상태를 보고 거부하고, INSERT가 먼저면
  -- compaction UPDATE가 잠금 해제 뒤 item 존재를 다시 보므로 drained 표기를 거부한다.
  SELECT material.compacted_at, material.compaction_drained_at
    INTO material_compacted_at, material_drained_at
    FROM ops.poi_cache_target_snapshot_materials AS material
   WHERE material.material_id = NEW.material_id
   FOR UPDATE;

  IF material_compacted_at IS NOT NULL OR material_drained_at IS NOT NULL THEN
    RAISE EXCEPTION 'snapshot material items cannot be inserted after compaction'
      USING ERRCODE = '55000';
  END IF;

  RETURN NEW;
END;
$reject_snapshot_material_item_insert$
"""

_RECEIPT_ORPHAN_GUARD_SQL = """
CREATE OR REPLACE FUNCTION ops.reject_snapshot_receipt_for_orphaned_material() RETURNS trigger
LANGUAGE plpgsql AS $reject_snapshot_receipt_for_orphaned_material$
DECLARE
  material_compacted_at timestamptz;
  material_orphaned_at timestamptz;
BEGIN
  IF TG_OP = 'UPDATE' AND NEW.material_id IS DISTINCT FROM OLD.material_id THEN
    RAISE EXCEPTION 'snapshot receipt material is immutable'
      USING ERRCODE = '55000';
  END IF;

  SELECT material.compacted_at, material.orphaned_at
    INTO material_compacted_at, material_orphaned_at
    FROM ops.poi_cache_target_snapshot_materials AS material
   WHERE material.material_id = NEW.material_id
   FOR SHARE;

  IF material_orphaned_at IS NOT NULL THEN
    RAISE EXCEPTION 'snapshot material is already orphaned'
      USING ERRCODE = '55000';
  END IF;

  IF material_compacted_at IS NOT NULL THEN
    RAISE EXCEPTION 'snapshot material is already compacted'
      USING ERRCODE = '55000';
  END IF;

  RETURN NEW;
END;
$reject_snapshot_receipt_for_orphaned_material$
"""

_MARK_ORPHANED_MATERIAL_SQL = """
CREATE OR REPLACE FUNCTION ops.mark_snapshot_material_orphaned() RETURNS trigger
LANGUAGE plpgsql AS $mark_snapshot_material_orphaned$
BEGIN
  -- material row lock과 새 receipt의 FOR SHARE를 먼저 직렬화한다. 마지막 receipt 삭제와
  -- 동시 receipt 발행이 엇갈려 orphan 표시가 stale해지는 것을 막는다.
  PERFORM 1
    FROM ops.poi_cache_target_snapshot_materials AS material
   WHERE material.material_id = OLD.material_id
   FOR UPDATE;

  IF NOT EXISTS (
    SELECT 1
    FROM ops.poi_cache_target_snapshots AS receipt
    WHERE receipt.material_id = OLD.material_id
  ) THEN
    UPDATE ops.poi_cache_target_snapshot_materials AS material
       SET orphaned_at = clock_timestamp()
     WHERE material.material_id = OLD.material_id
       AND material.orphaned_at IS NULL;
  END IF;

  RETURN OLD;
END;
$mark_snapshot_material_orphaned$
"""

#: backfill은 위 fence를 통과할 수 없다(배출 표시 자체가 fence가 막던 전이다). 같은
#: transaction 안에서 끄고 **원래 모드 그대로** 되돌린다. 끄기 전 상태를 읽어 두고 뒤에서
#: 대조한다 — 되살리지 못한 채 끝나면 그 표는 이후 아무 write에도 열려 버린다.
_CAPTURE_TRIGGER_MODE_SQL = """
SELECT tgenabled
FROM pg_trigger
WHERE tgrelid = 'ops.poi_cache_target_snapshot_materials'::regclass
  AND tgname = 'trg_poi_cache_target_snapshot_materials_compaction_only'
"""

_DISABLE_FENCE_SQL = """
ALTER TABLE ops.poi_cache_target_snapshot_materials
    DISABLE TRIGGER trg_poi_cache_target_snapshot_materials_compaction_only
"""


def upgrade() -> None:
    op.execute("SET ROLE ktm_feature_schema_owner")
    connection = op.get_bind()

    before = connection.exec_driver_sql(_CAPTURE_TRIGGER_MODE_SQL).scalar_one()
    before_mode = before.decode() if isinstance(before, bytes) else str(before)

    op.execute(_ADD_COLUMN_SQL)
    op.execute(_ADD_CHECK_SQL)
    op.execute(_REPLACE_FENCE_SQL)

    op.execute(_DISABLE_FENCE_SQL)
    try:
        drained = connection.exec_driver_sql(_BACKFILL_SQL).rowcount
        orphaned = connection.exec_driver_sql(_BACKFILL_ORPHANED_SQL).rowcount
    finally:
        if before_mode == "D":
            op.execute(
                "ALTER TABLE ops.poi_cache_target_snapshot_materials "
                "DISABLE TRIGGER trg_poi_cache_target_snapshot_materials_compaction_only"
            )
        else:
            trigger_mode = {"A": "ALWAYS ", "R": "REPLICA ", "O": ""}.get(
                before_mode
            )
            if trigger_mode is None:
                raise RuntimeError(f"알 수 없는 material fence trigger mode: {before_mode!r}")
            op.execute(
                "ALTER TABLE ops.poi_cache_target_snapshot_materials "
                f"ENABLE {trigger_mode}TRIGGER "
                "trg_poi_cache_target_snapshot_materials_compaction_only"
            )

    after = connection.exec_driver_sql(_CAPTURE_TRIGGER_MODE_SQL).scalar_one()
    after_mode = after.decode() if isinstance(after, bytes) else str(after)
    if after_mode != before_mode:
        raise RuntimeError(
            "material append-only fence를 원래 모드로 되돌리지 못했다: "
            f"{before_mode!r} -> {after_mode!r}"
        )

    op.execute(_RECEIPT_ORPHAN_GUARD_SQL)
    op.execute(_MARK_ORPHANED_MATERIAL_SQL)
    op.execute(
        "ALTER FUNCTION ops.reject_snapshot_receipt_for_orphaned_material() "
        "OWNER TO ktm_feature_schema_owner"
    )
    op.execute(
        "ALTER FUNCTION ops.mark_snapshot_material_orphaned() "
        "OWNER TO ktm_feature_schema_owner"
    )
    op.execute(_MATERIAL_ITEM_INSERT_FENCE_SQL)
    op.execute(
        "ALTER FUNCTION ops.reject_snapshot_material_item_insert() "
        "OWNER TO ktm_feature_schema_owner"
    )
    op.execute(
        """
        CREATE TRIGGER trg_poi_cache_target_snapshot_material_items_no_compacted_insert
            BEFORE INSERT ON ops.poi_cache_target_snapshot_material_items
            FOR EACH ROW
            EXECUTE FUNCTION ops.reject_snapshot_material_item_insert()
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_poi_cache_target_snapshots_no_orphaned_material
            BEFORE INSERT OR UPDATE OF material_id ON ops.poi_cache_target_snapshots
            FOR EACH ROW
            EXECUTE FUNCTION ops.reject_snapshot_receipt_for_orphaned_material()
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_poi_cache_target_snapshots_mark_material_orphaned
            AFTER DELETE ON ops.poi_cache_target_snapshots
            FOR EACH ROW
            EXECUTE FUNCTION ops.mark_snapshot_material_orphaned()
        """
    )

    # 0231의 전체 sweep index는 상태 partial index로 교체한다. backfill 뒤에 만들어
    # orphan 상태가 없는 행을 색인에 넣지 않는다.
    op.execute(_DROP_SWEEP_INDEX_SQL)
    op.execute(_ADD_INDEX_SQL)
    op.execute(_ADD_ORPHAN_INDEX_SQL)

    print(  # noqa: T201 — migration 로그는 배포 로그로 남는다.
        f"0236 tvn41s compaction drained: 이미 비어 있던 material {drained}건을 "
        f"배출 완료로 표시했고 orphan {orphaned}건을 상태화했다"
    )


def downgrade() -> None:
    raise RuntimeError(
        "0236_tvn41s_compaction_drained is forward-only; "
        "배출 완료 사실을 잃으면 GC가 이미 빈 material을 영원히 다시 훑는다"
    )
