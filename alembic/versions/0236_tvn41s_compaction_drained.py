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

두 시각은 각각 **한 방향**이다. ``compacted_at``은 "회수를 시작했다", ``compaction_drained_at``
은 "item을 다 비웠다"이고 둘 다 NULL에서 한 번만 채워진다. 그래서 append-only fence를
새로 쓴다 — 예전 fence는 ``OLD.compacted_at IS NOT NULL``이면 무조건 거부해서 배출 표시
자체가 불가능했다.

forward-only. 되돌리려면 배출 완료 사실을 잃고 GC가 이미 빈 material을 영원히 다시
훑게 된다.
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
    ADD COLUMN compaction_drained_at timestamptz
"""

#: 배출은 표시 이후에만 있을 수 있고, 표시보다 앞설 수 없다. 두 시각의 순서를 DB가 쥔다.
_ADD_CHECK_SQL = """
ALTER TABLE ops.poi_cache_target_snapshot_materials
    ADD CONSTRAINT ck_poi_cache_target_snapshot_materials_drained_after_compacted
    CHECK (
        compaction_drained_at IS NULL
        OR (compacted_at IS NOT NULL AND compaction_drained_at >= compacted_at)
    )
"""

#: 이 index가 이 migration의 목적이다. "표시됐지만 아직 배출 중"만 담으므로 배출이 끝난
#: material은 빠진다 — 그래서 audit material이 아무리 쌓여도 backlog 판정이 커지지 않는다.
_ADD_INDEX_SQL = """
CREATE INDEX idx_poi_cache_target_snapshot_materials_draining
    ON ops.poi_cache_target_snapshot_materials (material_id)
    WHERE compacted_at IS NOT NULL AND compaction_drained_at IS NULL
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
  IF OLD.compacted_at IS NOT NULL AND NEW.compaction_drained_at IS NULL THEN
    RAISE EXCEPTION 'snapshot material is already compacted'
      USING ERRCODE = '55000';
  END IF;

  RETURN NEW;
END;
$reject_snapshot_material_mutation$
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
    finally:
        op.execute(
            "ALTER TABLE ops.poi_cache_target_snapshot_materials "
            f"ENABLE {'ALWAYS ' if before_mode == 'A' else ''}"
            f"{'REPLICA ' if before_mode == 'R' else ''}"
            "TRIGGER trg_poi_cache_target_snapshot_materials_compaction_only"
        )

    after = connection.exec_driver_sql(_CAPTURE_TRIGGER_MODE_SQL).scalar_one()
    after_mode = after.decode() if isinstance(after, bytes) else str(after)
    if after_mode != before_mode:
        raise RuntimeError(
            "material append-only fence를 원래 모드로 되돌리지 못했다: "
            f"{before_mode!r} -> {after_mode!r}"
        )

    # index는 backfill 뒤에 만든다. 앞에서 만들면 곧 빠질 행까지 전부 색인한다.
    op.execute(_ADD_INDEX_SQL)

    print(  # noqa: T201 — migration 로그는 배포 로그로 남는다.
        f"0236 tvn41s compaction drained: 이미 비어 있던 material {drained}건을 "
        "배출 완료로 표시했다"
    )


def downgrade() -> None:
    raise RuntimeError(
        "0236_tvn41s_compaction_drained is forward-only; "
        "배출 완료 사실을 잃으면 GC가 이미 빈 material을 영원히 다시 훑는다"
    )
