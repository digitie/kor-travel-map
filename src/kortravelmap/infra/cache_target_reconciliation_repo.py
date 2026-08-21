"""Fixed cache-target snapshot, checksum reconciliation과 ops projection.

Repository 함수는 commit하지 않는다. Snapshot 생성은 stream row barrier를 잡은
같은 transaction에서 모든 natural-key head를 두 번 server-cursor scan하고, 두 scan의
count/byte/root가 일치할 때만 immutable header/items로 고정한다.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import json
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any, Literal, cast
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from kortravelmap.core.cache_target_stream import (
    SnapshotMerkleAccumulatorV1,
    SnapshotMerkleRowV1,
    validate_cache_target_external_system,
)
from kortravelmap.infra.advisory_lock import advisory_lock_key
from kortravelmap.infra.cache_target_outbox_repo import cache_target_event_cursor
from kortravelmap.infra.cache_target_stream_repo import (
    CacheTargetStreamConflict,
    cache_target_stream_entity_tag,
)
from kortravelmap.infra.domain_command_repo import canonical_domain_command_fingerprint

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

__all__ = [
    "CacheTargetOperation",
    "CacheTargetActiveReconciliation",
    "CacheTargetReconciliationRecord",
    "CacheTargetReconciliationResult",
    "CacheTargetSnapshotGcBacklog",
    "CacheTargetSnapshotGcBatchResult",
    "CacheTargetSnapshotItem",
    "CacheTargetSnapshotPage",
    "CacheTargetSnapshotStatus",
    "CacheTargetStreamStatus",
    "CacheTargetStreamStatusPage",
    "CacheTargetStreamDiscovery",
    "begin_cache_target_reconciliation",
    "cache_target_reconciliation_entity_tag",
    "complete_cache_target_reconciliation",
    "get_cache_target_operation",
    "get_cache_target_reconciliation",
    "get_cache_target_reconciliation_snapshot",
    "get_cache_target_snapshot",
    "get_cache_target_stream_discovery",
    "list_cache_target_stream_statuses",
    "observe_expired_cache_target_snapshot_backlog",
    "prune_expired_cache_target_snapshots_batch",
    "request_cache_target_reconciliation",
    "seal_cache_target_reconciliation",
]

_SNAPSHOT_TTL_SQL = "interval '2 hours'"
#: 재사용은 더 이상 만료 시각을 물려받지 않는다(receipt를 새로 만든다). 그래서
#: "재사용하려면 잔여 TTL이 75분 이상이어야 한다"는 문턱이 사라졌다. handoff floor는
#: 아래 `_SNAPSHOT_RETURN_MIN_TTL_SQL`로 남는다 — 그건 만든 시각이 아니라 **건네주는**
#: 시각을 재는 검사라서 여전히 뜻이 있다(빌드가 오래 끌면 새 receipt도 짧아진다).
_SNAPSHOT_RETURN_MIN_TTL_SQL = "interval '75 minutes'"
_SNAPSHOT_ITEM_PRUNE_LIMIT = 1000
_SNAPSHOT_HEADER_PRUNE_LIMIT = 100
#: terminal reconciliation의 item을 언제까지 붙잡아 둘 것인가. 감사에 필요한 것은
#: root/count이고 그건 material row에 남는다 — item은 그 기간이 지나면 되찾는다.
_MATERIAL_COMPACTION_RETENTION_SECONDS = 30 * 24 * 60 * 60
_GENERIC_SNAPSHOT_COPY_LIMIT = 2
_SNAPSHOT_CAPACITY_RETRY_AFTER_MAX_SECONDS = 7_200
_SNAPSHOT_BUILD_STATEMENT_TIMEOUT = "5min"
_SNAPSHOT_BUILD_TIMEOUT_SECONDS = 300.0
_SNAPSHOT_BARRIER_LOCK_TIMEOUT = "5s"
_SNAPSHOT_ITEM_LIMIT = 1_000_000
_SNAPSHOT_MATERIAL_BYTE_LIMIT = 512 * 1024 * 1024
_SNAPSHOT_STREAM_BATCH_SIZE = 1_000
_LOWERCASE_HEX = frozenset("0123456789abcdef")

_LOCK_SNAPSHOT_STREAM_SQL = """
SELECT pg_try_advisory_xact_lock(CAST(:lock_id AS bigint))
"""

_BARRIER_SNAPSHOT_STREAM_SQL = """
SELECT stream.external_system
FROM ops.poi_cache_target_streams AS stream
WHERE stream.external_system = :external_system
FOR SHARE OF stream
"""

_GET_SNAPSHOT_IDENTITY_SQL = """
SELECT stream.restore_epoch,
       COALESCE((
         SELECT max(event.relay_order)
         FROM ops.poi_cache_target_outbox_events AS event
         WHERE event.external_system = stream.external_system
           AND event.event_type = 'cache_target.state_applied'
       ), 0) AS material_high_watermark_relay_order
FROM ops.poi_cache_target_streams AS stream
WHERE stream.external_system = :external_system
"""

_CAPTURE_VIEW_SQL = """
SELECT stream.external_system, stream.restore_epoch,
       COALESCE((
         SELECT max(event.relay_order)
         FROM ops.poi_cache_target_outbox_events AS event
         WHERE event.external_system = stream.external_system
       ), 0) AS high_watermark_relay_order,
       COALESCE((
         SELECT max(event.relay_order)
         FROM ops.poi_cache_target_outbox_events AS event
         WHERE event.external_system = stream.external_system
           AND event.event_type = 'cache_target.state_applied'
       ), 0) AS material_high_watermark_relay_order,
       head.target_key, head.state, head.source_generation,
       head.source_payload_fingerprint
FROM ops.poi_cache_target_streams AS stream
LEFT JOIN LATERAL (
  SELECT source.target_key, source.state, source.source_generation,
         source.source_payload_fingerprint,
         convert_to(normalize(source.target_key, NFC), 'UTF8') AS sort_key
  FROM ops.poi_cache_target_source_heads AS source
  WHERE source.external_system = stream.external_system
  ORDER BY sort_key
) AS head ON true
WHERE stream.external_system = :external_system
ORDER BY head.sort_key
FOR SHARE OF stream
"""

_INSERT_MATERIAL_SQL = """
INSERT INTO ops.poi_cache_target_snapshot_materials (
    material_id, external_system, restore_epoch,
    material_high_watermark_relay_order, safe_high_watermark_relay_order,
    item_count, material_bytes, merkle_root, materialized_at
) VALUES (
    CAST(:material_id AS uuid), :external_system, :restore_epoch,
    :material_high_watermark_relay_order, :safe_high_watermark_relay_order,
    :item_count, :material_bytes, :merkle_root, clock_timestamp()
)
RETURNING materialized_at
"""

#: receipt는 자기 시점에 새로 만든다. 그래서 재사용해도 만료 시각을 물려받지 않고
#: 언제나 full TTL로 시작한다 — 앞판의 "최소 잔여 TTL" 검사가 필요 없어진 이유다.
#: replay cursor는 receipt가 아니라 material이 갖는다(`safe_high_watermark_relay_order`).
_INSERT_RECEIPT_SQL = f"""
INSERT INTO ops.poi_cache_target_snapshots (
    snapshot_id, material_id, receipt_kind, external_system,
    created_at, expires_at
)
SELECT
    CAST(:snapshot_id AS uuid), CAST(:material_id AS uuid), :receipt_kind,
    :external_system, issued_at, issued_at + {_SNAPSHOT_TTL_SQL}
FROM (SELECT clock_timestamp() AS issued_at) AS clock
RETURNING created_at, expires_at
"""

_CHECK_SNAPSHOT_RETURN_TTL_SQL = f"""
SELECT CAST(:expires_at AS timestamptz)
       >= clock_timestamp() + {_SNAPSHOT_RETURN_MIN_TTL_SQL}
"""

_INSERT_MATERIAL_ITEM_SQL = """
INSERT INTO ops.poi_cache_target_snapshot_material_items (
    material_id, row_number, target_key, state,
    source_generation, source_payload_fingerprint
) VALUES (
    CAST(:material_id AS uuid), :row_number, :target_key,
    :state, :source_generation, :source_payload_fingerprint
)
"""

#: receipt와 그 material을 함께 잡는다. ``FOR SHARE OF material``은 compaction과
#: 겹치지 않게 한다 — page reader는 정상 page 또는 typed 410 중 하나만 보고 부분
#: page를 보지 않는다.
_GET_SNAPSHOT_SQL = """
SELECT snapshot.snapshot_id, snapshot.material_id, snapshot.receipt_kind,
       snapshot.external_system, snapshot.created_at, snapshot.expires_at,
       snapshot.expires_at > now() AS valid,
       material.restore_epoch, material.item_count, material.merkle_root,
       material.material_high_watermark_relay_order,
       material.safe_high_watermark_relay_order
         AS high_watermark_relay_order,
       material.compacted_at
FROM ops.poi_cache_target_snapshots AS snapshot
JOIN ops.poi_cache_target_snapshot_materials AS material
  ON material.material_id = snapshot.material_id
WHERE snapshot.snapshot_id = CAST(:snapshot_id AS uuid)
FOR SHARE OF snapshot, material
"""

#: 앞판에는 재사용 질의가 둘이었다. generic은 reconciliation이 참조한 snapshot을
#: 쓰지 못했고(`NOT EXISTS (... requests ...)`), reconciliation만 generic을 물려받을 수
#: 있었다. 물려받으면 만료 시각까지 함께 물려받기 때문이고, 그건 header 하나가 material과
#: receipt를 겸했기 때문이다. 이제 둘 다 **같은 material**을 찾아 **각자 receipt**를
#: 만들므로 질의 하나로 충분하고 공유가 양방향이 된다.
#:
#: partial unique(`compacted_at IS NULL`)가 identity마다 살아 있는 material을 하나로
#: 강제하므로 정렬·LIMIT이 필요 없다. 둘 이상 나오면 그것이 사고이므로 그대로 터진다.
#:
#: **receipt 존재를 보지 않는 이유.** "item이 온전한가"의 권한은 `compacted_at` 하나다 —
#: 배출은 표시된 material만 건드리므로(`_PRUNE_ORPHANED_MATERIAL_ITEMS_SQL`) 표시가 없다는
#: 것이 곧 온전하다는 뜻이다. receipt가 없는 orphan이어도 아직 표시되지 않았다면 item은
#: 그대로이고 재사용해도 된다.
#:
#: 그런 상태는 실제로 존재한다 — 표시는 batch당 `header_limit`(기본 100)로 bounded라
#: 후보가 더 많으면 남는다. 그러니 "표시 뒤에는 orphan이 없다"는 식으로 읽고
#: `_PRUNE_ORPHANED_MATERIAL_ITEMS_SQL`에 `OR NOT EXISTS(receipt)`를 되돌리면 안 된다.
#: 그것이 부분 배출된 material을 재사용 가능하게 만든 구멍이었다.
_GET_REUSABLE_MATERIAL_SQL = """
SELECT material.material_id, material.external_system, material.restore_epoch,
       material.material_high_watermark_relay_order,
       material.safe_high_watermark_relay_order AS high_watermark_relay_order,
       material.item_count, material.material_bytes, material.merkle_root,
       material.materialized_at
FROM ops.poi_cache_target_snapshot_materials AS material
WHERE material.external_system = :external_system
  AND material.restore_epoch = :restore_epoch
  AND material.material_high_watermark_relay_order
      = :material_high_watermark_relay_order
  AND material.compacted_at IS NULL
FOR SHARE OF material
"""

#: 상한이 막는 것은 **item 사본의 수**다. 앞판에서는 사본 하나에 receipt 하나였으므로
#: 미만료 generic receipt를 셌다. 이제 receipt N개가 material 하나를 공유하므로 receipt를
#: 세면 저장 비용과 무관한 수를 세게 된다 — 살아 있는 material을 센다.
#:
#: `oldest_expires_at`은 그 material을 붙잡고 있는 receipt 중 가장 늦게 만료되는 것이다.
#: 그 시각이 지나야 material이 orphan이 되어 GC 대상이 되기 때문이다.
_GET_GENERIC_SNAPSHOT_CAPACITY_SQL = f"""
WITH candidates AS MATERIALIZED (
  SELECT (
    SELECT max(receipt.expires_at)
    FROM ops.poi_cache_target_snapshots AS receipt
    WHERE receipt.material_id = material.material_id
  ) AS expires_at
  FROM ops.poi_cache_target_snapshot_materials AS material
  WHERE material.external_system = :external_system
    AND material.compacted_at IS NULL
    AND EXISTS (
      SELECT 1
      FROM ops.poi_cache_target_snapshots AS receipt
      WHERE receipt.material_id = material.material_id
        AND receipt.expires_at > clock_timestamp()
    )
    -- reconciliation이 잡고 있는 material은 세지 않는다. 세면 오래 걸리는
    -- reconciliation 하나가 그 stream의 generic paging을 상한으로 영구히 막는다.
    -- 앞판의 `NOT EXISTS (... requests ...)`가 지키던 성질이다.
    AND NOT EXISTS (
      SELECT 1
      FROM ops.poi_cache_target_snapshots AS receipt
      JOIN ops.poi_cache_target_reconciliation_requests AS request
        ON request.snapshot_id = receipt.snapshot_id
      WHERE receipt.material_id = material.material_id
    )
  ORDER BY 1, material.material_id
  LIMIT {_GENERIC_SNAPSHOT_COPY_LIMIT}
), capacity AS (
  SELECT count(*) AS snapshot_count,
         min(expires_at) AS oldest_expires_at
  FROM candidates
)
SELECT snapshot_count, oldest_expires_at,
       GREATEST(
         1,
         LEAST(
           {_SNAPSHOT_CAPACITY_RETRY_AFTER_MAX_SECONDS},
           ceil(extract(epoch FROM oldest_expires_at - clock_timestamp()))::integer
         )
       ) AS retry_after_seconds
FROM capacity
"""

_SET_SNAPSHOT_BARRIER_TIMEOUTS_SQL = """
SELECT set_config('lock_timeout', :lock_timeout, true),
       set_config('statement_timeout', :statement_timeout, true)
"""

_RESET_SNAPSHOT_BARRIER_LOCK_TIMEOUT_SQL = """
SELECT set_config('lock_timeout', '0', true)
"""

#: 0231 뒤 GC 순서는 **receipt -> orphan material item -> orphan material**이다.
#: receipt를 먼저 지워야 material이 orphan이 되고, item은 그 다음이다. item 삭제를
#: material CASCADE에 맡기지 않는 이유는 1,000,000행짜리 material 하나가 transaction
#: 하나를 통째로 삼키기 때문이다 — 앞판이 item을 따로 bounded 삭제하던 이유와 같다.
_PRUNE_EXPIRED_SNAPSHOT_HEADERS_SQL = """
WITH candidates AS (
  SELECT snapshot.snapshot_id
  FROM ops.poi_cache_target_snapshots AS snapshot
  WHERE snapshot.external_system = :external_system
    AND snapshot.expires_at <= now()
    AND NOT EXISTS (
      SELECT 1
      FROM ops.poi_cache_target_reconciliation_requests AS request
      WHERE request.snapshot_id = snapshot.snapshot_id
    )
  ORDER BY snapshot.expires_at, snapshot.snapshot_id
  LIMIT :limit
  FOR UPDATE OF snapshot SKIP LOCKED
)
DELETE FROM ops.poi_cache_target_snapshots AS snapshot
USING candidates
WHERE snapshot.snapshot_id = candidates.snapshot_id
RETURNING snapshot.snapshot_id
"""

#: **되찾기 후보**의 논리 조건. `compacted_at`은 "이 material의 item을 되찾기
#: **시작**했다"는 표시이고, item은 **표시된 뒤에만** 지운다. 그래서 재사용 쪽의
#: `compacted_at IS NULL` 하나가 "item이 온전하다"의 충분조건이 된다.
#:
#: 그 결합이 없으면 이런 일이 난다. GC가 orphan material의 item을 1,000행씩 지우는
#: 도중(commit된 상태)에 그 material이 그대로 재사용 가능해서, consumer가 5,000을
#: 말하는 root/count와 함께 4,000행을 받는다. receipt가 붙는 순간 orphan이 아니게 되어
#: 배출도 멈추므로 손상이 영구가 된다. `0231` 이전에는 재사용이 "만료까지 75분 이상"을,
#: item 정리가 "만료됨"을 봐서 두 술어가 만료를 축으로 상보적이었다 — 정규화하면서
#: 그 결합이 사라졌고, 이 표시가 그것을 대신한다.
#:
#: 공통 조건 둘.
#:
#: 1. 아직 표시되지 않았다.
#: 2. item이 실제로 있다. 빈 material을 표시하면 되찾는 byte는 0인데 그 receipt의
#:    정상적인 빈 page가 410으로 바뀐다.
#:
#: 그리고 아래 둘 중 하나다.
#:
#: - **orphan** — 붙잡은 receipt가 하나도 없다. 표를 비운 뒤 행째 사라진다(phase 4).
#: - **terminal audit** — reconciliation이 참조하는 receipt가 있고, 미만료 receipt는
#:   없으며, 참조하는 **모든** reconciliation이 terminal이고 `completed_at`이 보존
#:   기간보다 오래됐다. 이쪽은 표시가 영구히 남는다 — root/count가 감사 증거이고
#:   그 receipt의 page는 typed 410이 된다.
_COMPACTION_CANDIDATE_PREDICATE = """
  material.compacted_at IS NULL
  AND EXISTS (
    SELECT 1
    FROM ops.poi_cache_target_snapshot_material_items AS item
    WHERE item.material_id = material.material_id
  )
  AND (
    NOT EXISTS (
      SELECT 1
      FROM ops.poi_cache_target_snapshots AS receipt
      WHERE receipt.material_id = material.material_id
    )
    OR (
      EXISTS (
        SELECT 1
        FROM ops.poi_cache_target_snapshots AS receipt
        JOIN ops.poi_cache_target_reconciliation_requests AS request
          ON request.snapshot_id = receipt.snapshot_id
        WHERE receipt.material_id = material.material_id
      )
      AND NOT EXISTS (
        SELECT 1
        FROM ops.poi_cache_target_snapshots AS receipt
        WHERE receipt.material_id = material.material_id
          AND receipt.expires_at > now()
      )
      AND NOT EXISTS (
        SELECT 1
        FROM ops.poi_cache_target_snapshots AS receipt
        JOIN ops.poi_cache_target_reconciliation_requests AS request
          ON request.snapshot_id = receipt.snapshot_id
        WHERE receipt.material_id = material.material_id
          AND (
            request.status IN ('preparing','running')
            OR request.completed_at IS NULL
            OR request.completed_at
               > now() - make_interval(
                   secs => CAST(:compaction_retention_seconds AS double precision)
                 )
          )
      )
    )
  )
"""

#: 먼저 표시하고 나중에 비운다. 반대로 하면 1,000,000행을 한 transaction에 지우거나,
#: 부분적으로 비운 material을 표시되지 않은 채 남겨 다음 batch가 다시 후보로 잡는다.
#: 표시가 곧 reader의 410 전환 시점이고, 그 시점부터 item은 계약상 없는 것이다.
_MARK_COMPACTED_MATERIALS_SQL = f"""
WITH candidates AS (
  SELECT material.material_id
  FROM ops.poi_cache_target_snapshot_materials AS material
  WHERE material.external_system = :external_system
    AND {_COMPACTION_CANDIDATE_PREDICATE.strip()}
  ORDER BY material.materialized_at, material.material_id
  LIMIT :limit
  FOR UPDATE OF material SKIP LOCKED
)
UPDATE ops.poi_cache_target_snapshot_materials AS material
SET compacted_at = clock_timestamp()
FROM candidates
WHERE material.material_id = candidates.material_id
RETURNING material.material_id
"""

#: **표시된** material의 item만 지운다. orphan도 표시를 먼저 받으므로 여기서 따로
#: 보지 않는다 — `NOT EXISTS(receipt)`를 여기 두면 표시 없이 지우는 경로가 살아나고,
#: 그것이 부분 배출된 material을 재사용 가능하게 만든 구멍이었다.
_PRUNE_ORPHANED_MATERIAL_ITEMS_SQL = """
WITH candidates AS (
  SELECT item.material_id, item.row_number
  FROM ops.poi_cache_target_snapshot_material_items AS item
  JOIN ops.poi_cache_target_snapshot_materials AS material
    ON material.material_id = item.material_id
  WHERE material.external_system = :external_system
    AND material.compacted_at IS NOT NULL
  ORDER BY item.material_id, item.row_number
  LIMIT :limit
  FOR UPDATE OF material, item SKIP LOCKED
)
DELETE FROM ops.poi_cache_target_snapshot_material_items AS item
USING candidates
WHERE item.material_id = candidates.material_id
  AND item.row_number = candidates.row_number
RETURNING item.material_id, item.row_number
"""

_PRUNE_ORPHANED_MATERIALS_SQL = """
WITH candidates AS (
  SELECT material.material_id
  FROM ops.poi_cache_target_snapshot_materials AS material
  WHERE material.external_system = :external_system
    AND NOT EXISTS (
      SELECT 1
      FROM ops.poi_cache_target_snapshots AS receipt
      WHERE receipt.material_id = material.material_id
    )
    AND NOT EXISTS (
      SELECT 1
      FROM ops.poi_cache_target_snapshot_material_items AS item
      WHERE item.material_id = material.material_id
    )
  ORDER BY material.materialized_at, material.material_id
  LIMIT :limit
  FOR UPDATE OF material SKIP LOCKED
)
DELETE FROM ops.poi_cache_target_snapshot_materials AS material
USING candidates
WHERE material.material_id = candidates.material_id
RETURNING material.material_id
"""

#: backlog가 있는 system은 넷 중 하나다 — 지울 수 있는 만료 receipt가 있거나,
#: receipt가 사라져 orphan이 된 material이 있거나, 이미 compaction으로 표시됐지만
#: item이 남은 material이 있거나, 새로 표시할 compaction 후보가 있거나.
#: 앞의 것만 보면 마지막 receipt를 지운 batch 뒤 나머지가 영원히 남는다.
_SELECT_EXPIRED_SNAPSHOT_GC_SYSTEM_SQL = f"""
SELECT external_system
FROM (
  SELECT snapshot.external_system
  FROM ops.poi_cache_target_snapshots AS snapshot
  WHERE snapshot.expires_at <= now()
    AND NOT EXISTS (
      SELECT 1
      FROM ops.poi_cache_target_reconciliation_requests AS request
      WHERE request.snapshot_id = snapshot.snapshot_id
    )
  UNION
  SELECT material.external_system
  FROM ops.poi_cache_target_snapshot_materials AS material
  WHERE NOT EXISTS (
    SELECT 1
    FROM ops.poi_cache_target_snapshots AS receipt
    WHERE receipt.material_id = material.material_id
  )
  UNION
  SELECT material.external_system
  FROM ops.poi_cache_target_snapshot_materials AS material
  WHERE material.compacted_at IS NOT NULL
    AND EXISTS (
      SELECT 1
      FROM ops.poi_cache_target_snapshot_material_items AS item
      WHERE item.material_id = material.material_id
    )
  UNION
  SELECT material.external_system
  FROM ops.poi_cache_target_snapshot_materials AS material
  WHERE {_COMPACTION_CANDIDATE_PREDICATE.strip()}
) AS backlog
WHERE CAST(:after_external_system AS text) IS NULL
   OR external_system COLLATE "C"
      > CAST(:after_external_system AS text) COLLATE "C"
GROUP BY external_system
ORDER BY external_system COLLATE "C"
LIMIT 1
"""

_HAS_EXPIRED_SNAPSHOT_GC_BACKLOG_SQL = f"""
SELECT EXISTS (
  SELECT 1
  FROM ops.poi_cache_target_snapshots AS snapshot
  WHERE snapshot.expires_at <= now()
    AND NOT EXISTS (
      SELECT 1
      FROM ops.poi_cache_target_reconciliation_requests AS request
      WHERE request.snapshot_id = snapshot.snapshot_id
    )
) OR EXISTS (
  SELECT 1
  FROM ops.poi_cache_target_snapshot_materials AS material
  WHERE NOT EXISTS (
    SELECT 1
    FROM ops.poi_cache_target_snapshots AS receipt
    WHERE receipt.material_id = material.material_id
  )
) OR EXISTS (
  SELECT 1
  FROM ops.poi_cache_target_snapshot_materials AS material
  WHERE material.compacted_at IS NOT NULL
    AND EXISTS (
      SELECT 1
      FROM ops.poi_cache_target_snapshot_material_items AS item
      WHERE item.material_id = material.material_id
    )
) OR EXISTS (
  SELECT 1
  FROM ops.poi_cache_target_snapshot_materials AS material
  WHERE {_COMPACTION_CANDIDATE_PREDICATE.strip()}
) AS has_more
"""

_OBSERVE_EXPIRED_SNAPSHOT_GC_BACKLOG_SQL = """
WITH snapshot_inventory AS MATERIALIZED (
  SELECT snapshot.snapshot_id,
         snapshot.expires_at <= now() AS expired,
         EXISTS (
           SELECT 1
           FROM ops.poi_cache_target_reconciliation_requests AS request
           WHERE request.snapshot_id = snapshot.snapshot_id
         ) AS referenced
  FROM ops.poi_cache_target_snapshots AS snapshot
), header_counts AS (
  SELECT count(*) AS total_headers,
         count(*) FILTER (WHERE expired AND NOT referenced) AS remaining_headers,
         count(*) FILTER (WHERE NOT expired AND NOT referenced)
           AS unexpired_unreferenced_headers,
         count(*) FILTER (WHERE referenced) AS referenced_headers
  FROM snapshot_inventory
), material_inventory AS MATERIALIZED (
  -- item의 분류 축은 이제 receipt가 아니라 material이다. receipt N개가 material
  -- 하나를 공유하므로 "이 item이 만료됐는가"를 receipt 하나로 물을 수 없다.
  --
  --   reclaimable = 되찾기가 표시됐거나 붙잡은 receipt가 없다 -> **GC가 지울 item**
  --   referenced  = 그 외 중 reconciliation이 참조하는 receipt가 있다
  --   그 외       = 살아 있는 receipt가 붙잡고 있다
  --
  -- `reclaimable`을 orphan만으로 정의하면 표시된 audit material의 item이 어느 축에도
  -- 잡히지 않아, drain이 남아 있는데 `remaining_items = 0`이 된다(적대 리뷰 지적).
  -- 세 축은 서로 겹치지 않아야 합계가 맞으므로 우선순위를 둔다.
  SELECT material.material_id,
         (
           material.compacted_at IS NOT NULL
           OR NOT EXISTS (
             SELECT 1
             FROM ops.poi_cache_target_snapshots AS receipt
             WHERE receipt.material_id = material.material_id
           )
         ) AS reclaimable,
         EXISTS (
           SELECT 1
           FROM ops.poi_cache_target_snapshots AS receipt
           JOIN ops.poi_cache_target_reconciliation_requests AS request
             ON request.snapshot_id = receipt.snapshot_id
           WHERE receipt.material_id = material.material_id
         ) AS referenced
  FROM ops.poi_cache_target_snapshot_materials AS material
), item_counts AS (
  SELECT count(*) AS total_items,
         count(*) FILTER (WHERE inventory.reclaimable) AS remaining_items,
         count(*) FILTER (WHERE NOT inventory.reclaimable AND NOT inventory.referenced)
           AS unexpired_unreferenced_items,
         count(*) FILTER (WHERE NOT inventory.reclaimable AND inventory.referenced)
           AS referenced_items
  FROM ops.poi_cache_target_snapshot_material_items AS item
  JOIN material_inventory AS inventory
    ON inventory.material_id = item.material_id
), relation_stats AS (
  SELECT COALESCE(sum(pg_table_size(relation.oid)), 0)::bigint
           AS snapshot_table_bytes,
         COALESCE(sum(pg_indexes_size(relation.oid)), 0)::bigint
           AS snapshot_index_bytes,
         COALESCE(sum(statistics.n_dead_tup), 0)::bigint
           AS snapshot_dead_tuples,
         CASE
           WHEN count(*) FILTER (
             WHERE statistics.last_vacuum IS NULL
               AND statistics.last_autovacuum IS NULL
           ) > 0 THEN NULL
           ELSE ceil(max(extract(epoch FROM clock_timestamp() - CASE
             WHEN statistics.last_vacuum IS NULL THEN statistics.last_autovacuum
             WHEN statistics.last_autovacuum IS NULL THEN statistics.last_vacuum
             ELSE greatest(statistics.last_vacuum, statistics.last_autovacuum)
           END)))::bigint
         END AS snapshot_vacuum_lag_seconds
  FROM pg_class AS relation
  JOIN pg_namespace AS namespace
    ON namespace.oid = relation.relnamespace
  LEFT JOIN pg_stat_user_tables AS statistics
    ON statistics.relid = relation.oid
  WHERE namespace.nspname = 'ops'
    AND relation.relname IN (
      'poi_cache_target_snapshots',
      'poi_cache_target_snapshot_materials',
      'poi_cache_target_snapshot_material_items'
    )
)
SELECT item_counts.remaining_items, header_counts.remaining_headers,
       item_counts.total_items, header_counts.total_headers,
       item_counts.unexpired_unreferenced_items,
       header_counts.unexpired_unreferenced_headers,
       item_counts.referenced_items, header_counts.referenced_headers,
       relation_stats.snapshot_table_bytes,
       relation_stats.snapshot_index_bytes,
       relation_stats.snapshot_dead_tuples,
       relation_stats.snapshot_vacuum_lag_seconds
FROM item_counts
CROSS JOIN header_counts
CROSS JOIN relation_stats
"""

#: `external_system`은 material이 소유한다. item 행마다 되풀이하지 않고 bind로 넘긴다 —
#: 호출자는 이미 receipt를 읽어 알고 있다.
_GET_SNAPSHOT_ITEMS_SQL = """
SELECT :external_system AS external_system, target_key, state, source_generation,
       source_payload_fingerprint, row_number
FROM ops.poi_cache_target_snapshot_material_items
WHERE material_id = CAST(:material_id AS uuid)
  AND row_number > :after_row_number
ORDER BY row_number
LIMIT :limit
"""

_GET_RECONCILIATION_SNAPSHOT_SQL = """
SELECT request.request_id, request.status AS reconciliation_status,
       request.phase_version,
       snapshot.snapshot_id, snapshot.external_system, material.restore_epoch,
       material.safe_high_watermark_relay_order AS high_watermark_relay_order,
       material.item_count,
       material.merkle_root, snapshot.created_at, snapshot.expires_at,
       stream.consumer_id, stream.control_version
FROM ops.poi_cache_target_reconciliation_requests AS request
LEFT JOIN ops.poi_cache_target_snapshots AS snapshot
  ON snapshot.snapshot_id = request.snapshot_id
LEFT JOIN ops.poi_cache_target_snapshot_materials AS material
  ON material.material_id = snapshot.material_id
JOIN ops.poi_cache_target_streams AS stream
  ON stream.external_system = request.external_system
WHERE request.request_id = CAST(:request_id AS uuid)
FOR SHARE OF request, stream
"""

_GET_RECONCILIATION_SQL = """
SELECT request.request_id, request.external_system, request.status,
       request.phase_version, request.snapshot_id,
       request.expected_merkle_root, request.actual_merkle_root, request.error_code,
       request.created_at, request.started_at, request.completed_at,
       stream.consumer_id, stream.restore_epoch AS stream_restore_epoch,
       stream.control_version,
       material.restore_epoch, material.restore_epoch AS snapshot_restore_epoch,
       material.safe_high_watermark_relay_order AS high_watermark_relay_order,
       material.item_count, material.merkle_root
FROM ops.poi_cache_target_reconciliation_requests AS request
JOIN ops.poi_cache_target_streams AS stream
  ON stream.external_system = request.external_system
LEFT JOIN ops.poi_cache_target_snapshots AS snapshot
  ON snapshot.snapshot_id = request.snapshot_id
LEFT JOIN ops.poi_cache_target_snapshot_materials AS material
  ON material.material_id = snapshot.material_id
WHERE request.request_id = CAST(:request_id AS uuid)
"""

_GET_STREAM_DISCOVERY_SQL = """
SELECT stream.external_system, stream.consumer_id, stream.restore_epoch,
       stream.control_version, stream.status, stream.blocked_event_id,
       stream.consumer_enabled, stream.created_at, stream.updated_at,
       active.request_id, active.reconciliation_status, active.phase_version,
       active.snapshot_id, active.snapshot_restore_epoch, active.item_count, active.merkle_root,
       active.high_watermark_relay_order, active.reconciliation_created_at
FROM ops.poi_cache_target_streams AS stream
LEFT JOIN LATERAL (
  SELECT request.request_id, request.status AS reconciliation_status,
         request.phase_version,
         snapshot.snapshot_id,
         material.restore_epoch AS snapshot_restore_epoch,
         material.item_count, material.merkle_root,
         material.safe_high_watermark_relay_order AS high_watermark_relay_order,
         request.created_at AS reconciliation_created_at
  FROM ops.poi_cache_target_reconciliation_requests AS request
  LEFT JOIN ops.poi_cache_target_snapshots AS snapshot
    ON snapshot.snapshot_id = request.snapshot_id
  LEFT JOIN ops.poi_cache_target_snapshot_materials AS material
    ON material.material_id = snapshot.material_id
  WHERE request.external_system = stream.external_system
    AND request.status IN ('preparing', 'running')
  ORDER BY request.created_at DESC, request.request_id DESC
  LIMIT 1
) AS active ON true
WHERE stream.external_system = :external_system
"""

_STREAM_STATUS_SQL = """
SELECT stream.external_system, stream.restore_epoch, stream.control_version,
       stream.consumer_enabled, stream.status, stream.blocked_event_id,
       stream.updated_at,
       count(delivery.event_id) FILTER (WHERE delivery.status = 'pending') AS pending_count,
       count(delivery.event_id) FILTER (WHERE delivery.status = 'leased') AS leased_count,
       count(delivery.event_id) FILTER (WHERE delivery.status = 'retry') AS retry_count,
       count(delivery.event_id) FILTER (WHERE delivery.status = 'dead') AS dead_count,
       count(delivery.event_id) FILTER (WHERE delivery.status = 'delivered') AS delivered_count,
       count(delivery.event_id) FILTER (WHERE delivery.status = 'superseded')
         AS superseded_count,
       snapshot.snapshot_id, snapshot.item_count, snapshot.merkle_root,
       snapshot.high_watermark_relay_order, snapshot.created_at AS snapshot_created_at
FROM ops.poi_cache_target_streams AS stream
LEFT JOIN ops.poi_cache_target_outbox_events AS event
  ON event.external_system = stream.external_system
LEFT JOIN ops.poi_cache_target_outbox_deliveries AS delivery
  ON delivery.event_id = event.event_id
LEFT JOIN LATERAL (
  SELECT fixed.snapshot_id, fixed_material.item_count, fixed_material.merkle_root,
         fixed_material.safe_high_watermark_relay_order
           AS high_watermark_relay_order,
         fixed.created_at
  FROM ops.poi_cache_target_snapshots AS fixed
  JOIN ops.poi_cache_target_snapshot_materials AS fixed_material
    ON fixed_material.material_id = fixed.material_id
  WHERE fixed.external_system = stream.external_system
  ORDER BY fixed.created_at DESC, fixed.snapshot_id DESC
  LIMIT 1
) AS snapshot ON true
WHERE (CAST(:after_external_system AS text) IS NULL
       OR stream.external_system > CAST(:after_external_system AS text))
GROUP BY stream.external_system, stream.restore_epoch, stream.control_version,
         stream.consumer_enabled, stream.status, stream.blocked_event_id,
         stream.updated_at, snapshot.snapshot_id, snapshot.item_count,
         snapshot.merkle_root, snapshot.high_watermark_relay_order,
         snapshot.created_at
ORDER BY stream.external_system
LIMIT :limit
"""

_GET_RECONCILIATION_BY_COMMAND_SQL = """
SELECT request.request_id, request.external_system, request.status,
       request.phase_version, request.snapshot_id,
       request.expected_merkle_root, request.actual_merkle_root, request.error_code,
       material.restore_epoch, material.item_count,
       stream.control_version,
       request.created_at, request.started_at, request.completed_at
FROM ops.poi_cache_target_reconciliation_requests AS request
JOIN ops.poi_cache_target_streams AS stream
  ON stream.external_system = request.external_system
LEFT JOIN ops.poi_cache_target_snapshots AS snapshot
  ON snapshot.snapshot_id = request.snapshot_id
LEFT JOIN ops.poi_cache_target_snapshot_materials AS material
  ON material.material_id = snapshot.material_id
WHERE request.command_id = :command_id
"""

_GET_ACTIVE_RECONCILIATION_SQL = """
SELECT request_id, status, snapshot_id
FROM ops.poi_cache_target_reconciliation_requests
WHERE external_system = :external_system AND status IN ('preparing', 'running')
ORDER BY created_at DESC, request_id DESC
LIMIT 1
FOR UPDATE
"""

_INSERT_RECONCILIATION_SQL = """
INSERT INTO ops.poi_cache_target_reconciliation_requests (
    request_id, external_system, command_id, reason, status, phase_version,
    snapshot_id, expected_merkle_root, started_at
) VALUES (
    CAST(:request_id AS uuid), :external_system, :command_id, :reason,
    'running', 2, CAST(:snapshot_id AS uuid), :expected_merkle_root, now()
)
RETURNING request_id, external_system, status, phase_version, snapshot_id,
          expected_merkle_root, actual_merkle_root, error_code,
          created_at, started_at, completed_at
"""

_INSERT_PREPARING_RECONCILIATION_SQL = """
INSERT INTO ops.poi_cache_target_reconciliation_requests (
    request_id, external_system, command_id, reason, status, phase_version,
    started_at
) VALUES (
    CAST(:request_id AS uuid), :external_system, :command_id, :reason,
    'preparing', 1, now()
)
RETURNING request_id, external_system, status, phase_version, snapshot_id,
          expected_merkle_root, actual_merkle_root, error_code,
          created_at, started_at, completed_at
"""

_CREATE_STREAM_SQL = """
INSERT INTO ops.poi_cache_target_streams (
    external_system, consumer_id, restore_epoch, control_version, status,
    consumer_enabled
) VALUES (
    :external_system, :consumer_id, 1, 1, 'fenced', false
)
ON CONFLICT (external_system) DO NOTHING
RETURNING external_system, consumer_id, restore_epoch, control_version, status,
          blocked_event_id, consumer_enabled
"""

_LOCK_STREAM_SQL = """
SELECT external_system, consumer_id, restore_epoch, control_version, status,
       blocked_event_id, consumer_enabled
FROM ops.poi_cache_target_streams
WHERE external_system = :external_system
FOR UPDATE
"""

_HALT_STREAM_SQL = """
UPDATE ops.poi_cache_target_streams
SET status = CASE WHEN status = 'ready' THEN 'fenced' ELSE status END,
    consumer_enabled = false, control_version = control_version + 1,
    updated_at = now()
WHERE external_system = :external_system
"""

_INVALIDATE_CLAIMS_SQL = """
UPDATE ops.poi_cache_target_outbox_claims
SET status = 'invalidated', completed_at = now()
WHERE external_system = :external_system AND status = 'active'
RETURNING claim_id
"""

_RELEASE_CLAIM_DELIVERIES_SQL = """
UPDATE ops.poi_cache_target_outbox_deliveries
SET status = 'retry', claim_id = NULL, lease_token = NULL,
    lease_expires_at = NULL, available_at = now(), updated_at = now()
WHERE status = 'leased' AND claim_id = ANY(CAST(:claim_ids AS uuid[]))
"""

_LOCK_RECONCILIATION_SQL = """
SELECT request.request_id, request.external_system, request.status,
       request.phase_version, request.snapshot_id, request.expected_merkle_root,
       request.actual_merkle_root, request.error_code,
       request.created_at, request.started_at, request.completed_at,
       material.restore_epoch, material.item_count,
       stream.control_version
FROM ops.poi_cache_target_reconciliation_requests AS request
JOIN ops.poi_cache_target_streams AS stream
  ON stream.external_system = request.external_system
LEFT JOIN ops.poi_cache_target_snapshots AS snapshot
  ON snapshot.snapshot_id = request.snapshot_id
LEFT JOIN ops.poi_cache_target_snapshot_materials AS material
  ON material.material_id = snapshot.material_id
WHERE request.request_id = CAST(:request_id AS uuid)
FOR UPDATE OF request
"""

_SEAL_RECONCILIATION_SQL = """
UPDATE ops.poi_cache_target_reconciliation_requests
SET status = 'running',
    phase_version = phase_version + 1,
    snapshot_id = CAST(:snapshot_id AS uuid),
    expected_merkle_root = :expected_merkle_root
WHERE request_id = CAST(:request_id AS uuid)
  AND status = 'preparing'
  AND phase_version = :expected_phase_version
RETURNING request_id, external_system, status, phase_version, snapshot_id,
          expected_merkle_root, actual_merkle_root, error_code,
          created_at, started_at, completed_at
"""

_COMPLETE_RECONCILIATION_SQL = """
UPDATE ops.poi_cache_target_reconciliation_requests
SET status = :status, actual_merkle_root = :actual_merkle_root,
    error_code = :error_code, completed_at = now(),
    phase_version = phase_version + 1
WHERE request_id = CAST(:request_id AS uuid)
RETURNING request_id, external_system, status, phase_version, snapshot_id,
          expected_merkle_root, actual_merkle_root, error_code,
          created_at, started_at, completed_at
"""

_COUNT_DEAD_SQL = """
SELECT count(*)
FROM ops.poi_cache_target_outbox_events AS event
JOIN ops.poi_cache_target_outbox_deliveries AS delivery
  ON delivery.event_id = event.event_id
WHERE event.external_system = :external_system AND delivery.status = 'dead'
  AND event.restore_epoch = :restore_epoch
"""

_RESUME_STREAM_SQL = """
UPDATE ops.poi_cache_target_streams
SET status = 'ready', blocked_event_id = NULL, consumer_enabled = true,
    control_version = control_version + 1, updated_at = now()
WHERE external_system = :external_system
"""

_INSERT_RECONCILED_EVENT_SQL = """
INSERT INTO ops.poi_cache_target_outbox_events (
    event_id, event_type, event_scope, external_system, target_key, target_id,
    restore_epoch, source_generation, target_sequence,
    source_payload_fingerprint, payload_fingerprint, payload,
    domain_command_id, reconciliation_request_id
)
SELECT CAST(:event_id AS uuid), 'cache_target.reconciled', 'stream',
       request.external_system, NULL, NULL, :restore_epoch, NULL, NULL,
       :source_payload_fingerprint, :payload_fingerprint, CAST(:payload AS jsonb),
       request.command_id, request.request_id
FROM ops.poi_cache_target_reconciliation_requests AS request
WHERE request.request_id = CAST(:request_id AS uuid)
RETURNING event_id
"""

_INSERT_DELIVERY_SQL = """
INSERT INTO ops.poi_cache_target_outbox_deliveries (event_id, status)
VALUES (CAST(:event_id AS uuid), 'pending')
"""

_GET_OPERATION_SQL = """
SELECT request_id, status, snapshot_id
FROM ops.poi_cache_target_reconciliation_requests
WHERE request_id = CAST(:operation_id AS uuid)
"""

_GET_DELIVERY_OPERATION_SQL = """
SELECT delivery.event_id, delivery.status
FROM ops.poi_cache_target_outbox_deliveries AS delivery
WHERE delivery.event_id = CAST(:operation_id AS uuid)
"""


@dataclass(frozen=True, slots=True)
class CacheTargetSnapshotItem:
    external_system: str
    target_key: str
    state: Literal["active", "deleted"]
    source_generation: int
    source_payload_fingerprint: str
    row_number: int


@dataclass(frozen=True, slots=True)
class _SnapshotMaterialScan:
    header: dict[str, Any]
    material_bytes: int


@dataclass(frozen=True, slots=True)
class CacheTargetSnapshotPage:
    snapshot_id: str
    external_system: str
    restore_epoch: int
    high_watermark_cursor: str
    count: int
    merkle_root: str
    items: tuple[CacheTargetSnapshotItem, ...]
    next_cursor: str | None
    created_at: datetime
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class CacheTargetSnapshotGcBatchResult:
    """만료 snapshot background GC 한 transaction의 결과."""

    external_system: str | None
    deleted_items: int
    deleted_headers: int
    #: 이 batch에서 compaction으로 표시한 material 수. item은 같은 batch에서 다
    #: 지워지지 않을 수 있다(bounded) — 남은 것은 다음 batch가 이어서 지운다.
    compacted_materials: int
    has_more: bool


@dataclass(frozen=True, slots=True)
class CacheTargetSnapshotGcBacklog:
    """background GC 종료 시점의 정확한 전역 backlog 관측값."""

    remaining_items: int
    remaining_headers: int
    total_items: int = 0
    total_headers: int = 0
    unexpired_unreferenced_items: int = 0
    unexpired_unreferenced_headers: int = 0
    referenced_items: int = 0
    referenced_headers: int = 0
    snapshot_table_bytes: int = 0
    snapshot_index_bytes: int = 0
    snapshot_dead_tuples: int = 0
    snapshot_vacuum_lag_seconds: int | None = None


@dataclass(frozen=True, slots=True)
class CacheTargetSnapshotStatus:
    snapshot_id: str
    count: int
    merkle_root: str
    high_watermark_cursor: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class CacheTargetActiveReconciliation:
    request_id: str
    external_system: str
    status: Literal["preparing", "running"]
    phase_version: int
    snapshot_id: str | None
    restore_epoch: int
    count: int | None
    merkle_root: str | None
    high_watermark_cursor: str | None
    stream_control_version: int
    created_at: datetime

    @property
    def entity_tag(self) -> str:
        return cache_target_reconciliation_entity_tag(
            self.request_id,
            self.phase_version,
        )

    @property
    def stream_entity_tag(self) -> str:
        return cache_target_stream_entity_tag(
            self.external_system,
            self.stream_control_version,
        )


@dataclass(frozen=True, slots=True)
class CacheTargetStreamDiscovery:
    external_system: str
    consumer_id: str
    restore_epoch: int
    control_version: int
    status: Literal["ready", "fenced", "blocked"]
    blocked_event_id: str | None
    consumer_enabled: bool
    active_reconciliation: CacheTargetActiveReconciliation | None
    created_at: datetime
    updated_at: datetime

    @property
    def entity_tag(self) -> str:
        return cache_target_stream_entity_tag(
            self.external_system,
            self.control_version,
        )


@dataclass(frozen=True, slots=True)
class CacheTargetStreamStatus:
    external_system: str
    restore_epoch: int
    control_version: int
    consumer_enabled: bool
    state: str
    pending_count: int
    leased_count: int
    retry_count: int
    dead_count: int
    delivered_count: int
    superseded_count: int
    blocked_event_id: str | None
    last_snapshot: CacheTargetSnapshotStatus | None
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class CacheTargetStreamStatusPage:
    items: tuple[CacheTargetStreamStatus, ...]
    next_cursor: str | None


@dataclass(frozen=True, slots=True)
class CacheTargetReconciliationRecord:
    request_id: str
    external_system: str
    consumer_id: str
    status: Literal["preparing", "running", "succeeded", "failed", "superseded"]
    phase_version: int
    snapshot_id: str | None
    restore_epoch: int
    stream_control_version: int
    item_count: int | None
    merkle_root: str | None

    @property
    def entity_tag(self) -> str:
        return cache_target_reconciliation_entity_tag(
            self.request_id,
            self.phase_version,
        )

    @property
    def stream_entity_tag(self) -> str:
        return cache_target_stream_entity_tag(
            self.external_system,
            self.stream_control_version,
        )


@dataclass(frozen=True, slots=True)
class CacheTargetReconciliationResult:
    request_id: str
    external_system: str
    status: Literal["preparing", "running", "succeeded", "failed", "superseded"]
    phase_version: int
    snapshot_id: str | None
    expected_merkle_root: str | None
    actual_merkle_root: str | None
    error_code: str | None
    restore_epoch: int | None
    item_count: int | None
    stream_control_version: int | None
    created_at: datetime
    started_at: datetime
    completed_at: datetime | None
    idempotent_replay: bool = False

    @property
    def operation_id(self) -> str:
        return self.request_id

    @property
    def status_url(self) -> str:
        return f"/v1/ops/cache-target-operations/{self.request_id}"

    @property
    def entity_tag(self) -> str:
        return cache_target_reconciliation_entity_tag(
            self.request_id,
            self.phase_version,
        )

    @property
    def stream_entity_tag(self) -> str | None:
        if self.stream_control_version is None:
            return None
        return cache_target_stream_entity_tag(
            self.external_system,
            self.stream_control_version,
        )

    @property
    def retry_after_seconds(self) -> int | None:
        return 5 if self.status in ("preparing", "running") else None


@dataclass(frozen=True, slots=True)
class CacheTargetOperation:
    operation_id: str
    status: str
    snapshot_id: str | None = None

    @property
    def status_url(self) -> str:
        return f"/v1/ops/cache-target-operations/{self.operation_id}"


def _canonical_uuid(value: str, *, field: str) -> str:
    canonical = str(UUID(value))
    if value != canonical:
        raise ValueError(f"{field}는 lowercase canonical UUID여야 합니다.")
    return canonical


def _sha256(value: str, *, field: str) -> str:
    if len(value) != 64 or any(character not in _LOWERCASE_HEX for character in value):
        raise ValueError(f"{field}는 lowercase SHA-256 hex여야 합니다.")
    return value


def cache_target_reconciliation_entity_tag(request_id: str, phase_version: int) -> str:
    request_id = _canonical_uuid(request_id, field="request_id")
    if phase_version <= 0:
        raise ValueError("phase_version은 양수여야 합니다.")
    return f'"{request_id}:{phase_version}"'


def _snapshot_cursor(snapshot_id: str, row_number: int) -> str:
    raw = json.dumps(
        {
            "kind": "cache_target_snapshot",
            "row_number": row_number,
            "snapshot_id": snapshot_id,
            "v": 1,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("ascii")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _parse_snapshot_cursor(cursor: str) -> tuple[str, int]:
    padded = cursor + "=" * (-len(cursor) % 4)
    try:
        payload = json.loads(base64.urlsafe_b64decode(padded).decode("ascii"))
        snapshot_id = _canonical_uuid(str(payload["snapshot_id"]), field="snapshot_id")
        row_number = int(payload["row_number"])
    except (
        binascii.Error,
        KeyError,
        TypeError,
        ValueError,
        UnicodeDecodeError,
        json.JSONDecodeError,
    ) as exc:
        raise ValueError("유효하지 않은 snapshot cursor입니다.") from exc
    if (
        payload.get("kind") != "cache_target_snapshot"
        or payload.get("v") != 1
        or row_number <= 0
        or _snapshot_cursor(snapshot_id, row_number) != cursor
    ):
        raise ValueError("유효하지 않은 snapshot cursor입니다.")
    return snapshot_id, row_number


def _stream_cursor(external_system: str) -> str:
    raw = json.dumps(
        {"external_system": external_system, "kind": "cache_target_stream", "v": 1},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _parse_stream_cursor(cursor: str | None) -> str | None:
    if cursor is None:
        return None
    padded = cursor + "=" * (-len(cursor) % 4)
    try:
        payload = json.loads(base64.urlsafe_b64decode(padded).decode("utf-8"))
        external_system = str(payload["external_system"])
    except (
        binascii.Error,
        KeyError,
        UnicodeDecodeError,
        json.JSONDecodeError,
    ) as exc:
        raise ValueError("유효하지 않은 stream cursor입니다.") from exc
    if (
        payload.get("kind") != "cache_target_stream"
        or payload.get("v") != 1
        or not external_system
        or _stream_cursor(external_system) != cursor
    ):
        raise ValueError("유효하지 않은 stream cursor입니다.")
    return external_system


def _snapshot_item(row: Any) -> CacheTargetSnapshotItem:
    values = row._mapping
    state = str(values["state"])
    if state not in ("active", "deleted"):
        raise RuntimeError("snapshot item state가 유효하지 않습니다.")
    return CacheTargetSnapshotItem(
        external_system=str(values["external_system"]),
        target_key=str(values["target_key"]),
        state=cast('Literal["active", "deleted"]', state),
        source_generation=int(values["source_generation"]),
        source_payload_fingerprint=str(values["source_payload_fingerprint"]),
        row_number=int(values["row_number"]),
    )


def _enforce_snapshot_admission(*, item_count: int, material_bytes: int) -> None:
    if item_count > _SNAPSHOT_ITEM_LIMIT:
        raise CacheTargetStreamConflict(
            "snapshot_item_limit_exceeded",
            "snapshot item 수가 admission 상한을 초과했습니다.",
            current={
                "item_count_lower_bound": item_count,
                "item_limit": _SNAPSHOT_ITEM_LIMIT,
            },
        )
    if material_bytes > _SNAPSHOT_MATERIAL_BYTE_LIMIT:
        raise CacheTargetStreamConflict(
            "snapshot_byte_limit_exceeded",
            "snapshot canonical material byte 수가 admission 상한을 초과했습니다.",
            current={
                "material_bytes_lower_bound": material_bytes,
                "material_byte_limit": _SNAPSHOT_MATERIAL_BYTE_LIMIT,
            },
        )


def snapshot_build_budget_seconds() -> float:
    """build 예산(초). API가 `Retry-After`를 이 값에서 계산한다.

    상수를 API 쪽에 다시 적지 않는다 — 두 곳에 적으면 예산을 바꿀 때 한쪽이 남는다.
    """

    return _SNAPSHOT_BUILD_TIMEOUT_SECONDS


@asynccontextmanager
async def _snapshot_build_deadline() -> AsyncIterator[None]:
    """첫 stream lock부터 두 scan과 모든 INSERT까지의 단일 누적 예산."""

    deadline = asyncio.timeout(_SNAPSHOT_BUILD_TIMEOUT_SECONDS)
    try:
        async with deadline:
            yield
    except TimeoutError as exc:
        if not deadline.expired():
            raise
        raise CacheTargetStreamConflict(
            "snapshot_build_timeout",
            "snapshot materialization 누적 제한 시간이 초과되었습니다.",
        ) from exc


async def _barrier_snapshot_stream(
    session: AsyncSession,
    *,
    external_system: str,
) -> None:
    await session.execute(
        text(_SET_SNAPSHOT_BARRIER_TIMEOUTS_SQL),
        {
            "lock_timeout": _SNAPSHOT_BARRIER_LOCK_TIMEOUT,
            "statement_timeout": _SNAPSHOT_BUILD_STATEMENT_TIMEOUT,
        },
    )
    try:
        barrier = (
            await session.execute(
                text(_BARRIER_SNAPSHOT_STREAM_SQL),
                {"external_system": external_system},
            )
        ).one_or_none()
    except DBAPIError as exc:
        if getattr(exc.orig, "sqlstate", None) in {"55P03", "57014"}:
            raise CacheTargetStreamConflict(
                "snapshot_barrier_timeout",
                "snapshot stream writer barrier 대기 시간이 초과되었습니다.",
            ) from exc
        raise
    await session.execute(text(_RESET_SNAPSHOT_BARRIER_LOCK_TIMEOUT_SQL))
    if barrier is None:
        raise CacheTargetStreamConflict(
            "stream_not_found",
            "snapshot을 만들 cache target stream이 없습니다.",
        )


async def _lock_snapshot_stream_for_build(
    session: AsyncSession,
    *,
    external_system: str,
) -> Any | None:
    """Snapshot build의 첫 stream ``FOR UPDATE``에도 barrier 예산을 적용한다."""

    await session.execute(
        text(_SET_SNAPSHOT_BARRIER_TIMEOUTS_SQL),
        {
            "lock_timeout": _SNAPSHOT_BARRIER_LOCK_TIMEOUT,
            "statement_timeout": _SNAPSHOT_BUILD_STATEMENT_TIMEOUT,
        },
    )
    try:
        stream = (
            await session.execute(
                text(_LOCK_STREAM_SQL),
                {"external_system": external_system},
            )
        ).one_or_none()
    except DBAPIError as exc:
        if getattr(exc.orig, "sqlstate", None) in {"55P03", "57014"}:
            raise CacheTargetStreamConflict(
                "snapshot_barrier_timeout",
                "snapshot stream writer barrier 대기 시간이 초과되었습니다.",
            ) from exc
        raise
    await session.execute(text(_RESET_SNAPSHOT_BARRIER_LOCK_TIMEOUT_SQL))
    return stream


def _capture_snapshot_item(row: Any, *, row_number: int) -> CacheTargetSnapshotItem:
    values = row._mapping
    state = str(values["state"])
    if state not in ("active", "deleted"):
        raise RuntimeError("snapshot item state가 유효하지 않습니다.")
    return CacheTargetSnapshotItem(
        external_system=str(values["external_system"]),
        target_key=str(values["target_key"]),
        state=cast('Literal["active", "deleted"]', state),
        source_generation=int(values["source_generation"]),
        source_payload_fingerprint=str(values["source_payload_fingerprint"]),
        row_number=row_number,
    )


def _snapshot_merkle_row(item: CacheTargetSnapshotItem) -> SnapshotMerkleRowV1:
    return SnapshotMerkleRowV1(
        external_system=item.external_system,
        target_key=item.target_key,
        state=item.state,
        source_generation=item.source_generation,
        source_payload_fingerprint=item.source_payload_fingerprint,
    )


async def _stream_snapshot_capture(
    session: AsyncSession,
    *,
    external_system: str,
) -> AsyncIterator[Any]:
    result = None
    try:
        result = await session.stream(
            text(_CAPTURE_VIEW_SQL),
            {"external_system": external_system},
            execution_options={
                "stream_results": True,
                "yield_per": _SNAPSHOT_STREAM_BATCH_SIZE,
            },
        )
        async for row in result:
            yield row
    except DBAPIError as exc:
        if getattr(exc.orig, "sqlstate", None) == "57014":
            raise CacheTargetStreamConflict(
                "snapshot_build_timeout",
                "snapshot materialization query 제한 시간이 초과되었습니다.",
            ) from exc
        raise
    finally:
        if result is not None:
            await result.close()


async def _scan_snapshot_material(
    session: AsyncSession,
    *,
    external_system: str,
) -> _SnapshotMaterialScan:
    await _barrier_snapshot_stream(
        session,
        external_system=external_system,
    )
    first: Any | None = None
    accumulator = SnapshotMerkleAccumulatorV1()
    async for row in _stream_snapshot_capture(
        session,
        external_system=external_system,
    ):
        if first is None:
            first = row._mapping
        if row._mapping["target_key"] is None:
            continue
        item = _capture_snapshot_item(row, row_number=accumulator.count + 1)
        accumulator.add(_snapshot_merkle_row(item))
        _enforce_snapshot_admission(
            item_count=accumulator.count,
            material_bytes=accumulator.material_bytes,
        )
    if first is None:
        raise CacheTargetStreamConflict(
            "stream_not_found",
            "snapshot을 만들 cache target stream이 없습니다.",
        )
    return _SnapshotMaterialScan(
        header={
            "material_id": str(uuid4()),
            "external_system": external_system,
            "restore_epoch": int(first["restore_epoch"]),
            "high_watermark_relay_order": int(first["high_watermark_relay_order"]),
            "material_high_watermark_relay_order": int(
                first["material_high_watermark_relay_order"]
            ),
            "item_count": accumulator.count,
            "merkle_root": accumulator.hexdigest(),
        },
        material_bytes=accumulator.material_bytes,
    )


async def _mint_receipt(
    session: AsyncSession,
    *,
    material: Mapping[str, Any],
    receipt_kind: str,
) -> dict[str, Any]:
    """material 하나에 새 receipt를 붙인다.

    generic page와 reconciliation이 같은 material을 공유하는 지점이다. 각자 receipt를
    만들기 때문에 만료 시각을 물려받지 않고, 공유가 양방향이 된다.

    replay cursor는 여기서 정하지 않는다. material이 **처음 고정될 때** 관측한 값을
    쓴다 — 재사용 시점의 더 높은 값을 광고하면 그 사이에 낀 비-membership event를
    consumer가 건너뛴다.
    """

    snapshot_id = str(uuid4())
    issued = (
        await session.execute(
            text(_INSERT_RECEIPT_SQL),
            {
                "snapshot_id": snapshot_id,
                "material_id": material["material_id"],
                "receipt_kind": receipt_kind,
                "external_system": material["external_system"],
            },
        )
    ).one()
    return {
        **dict(material),
        "snapshot_id": snapshot_id,
        "receipt_kind": receipt_kind,
        "created_at": issued._mapping["created_at"],
        "expires_at": issued._mapping["expires_at"],
    }


async def _persist_snapshot_material(
    session: AsyncSession,
    *,
    scan: _SnapshotMaterialScan,
    receipt_kind: str,
    return_limit: int,
) -> tuple[Any, tuple[CacheTargetSnapshotItem, ...]]:
    header = scan.header
    try:
        await session.execute(
            text(_INSERT_MATERIAL_SQL),
            {
                "material_id": header["material_id"],
                "external_system": header["external_system"],
                "restore_epoch": header["restore_epoch"],
                "material_high_watermark_relay_order": header[
                    "material_high_watermark_relay_order"
                ],
                "safe_high_watermark_relay_order": header[
                    "high_watermark_relay_order"
                ],
                "item_count": header["item_count"],
                "material_bytes": scan.material_bytes,
                "merkle_root": header["merkle_root"],
            },
        )
        accumulator = SnapshotMerkleAccumulatorV1()
        batch: list[dict[str, object]] = []
        return_items: list[CacheTargetSnapshotItem] = []
        async for row in _stream_snapshot_capture(
            session,
            external_system=str(header["external_system"]),
        ):
            if row._mapping["target_key"] is None:
                continue
            item = _capture_snapshot_item(row, row_number=accumulator.count + 1)
            accumulator.add(_snapshot_merkle_row(item))
            if len(return_items) < return_limit:
                return_items.append(item)
            batch.append(
                {
                    "material_id": header["material_id"],
                    "row_number": item.row_number,
                    "target_key": item.target_key,
                    "state": item.state,
                    "source_generation": item.source_generation,
                    "source_payload_fingerprint": item.source_payload_fingerprint,
                }
            )
            if len(batch) < _SNAPSHOT_STREAM_BATCH_SIZE:
                continue
            await session.execute(
                text(_INSERT_MATERIAL_ITEM_SQL),
                batch,
            )
            batch = []
        if batch:
            await session.execute(text(_INSERT_MATERIAL_ITEM_SQL), batch)
    except DBAPIError as exc:
        if getattr(exc.orig, "sqlstate", None) == "57014":
            raise CacheTargetStreamConflict(
                "snapshot_build_timeout",
                "snapshot persistence query 제한 시간이 초과되었습니다.",
            ) from exc
        raise
    if (
        accumulator.count != int(header["item_count"])
        or accumulator.material_bytes != scan.material_bytes
        or accumulator.hexdigest() != str(header["merkle_root"])
    ):
        raise RuntimeError("snapshot 두 번째 material scan이 최초 checksum과 다릅니다.")
    # receipt는 item을 다 쓰고 검증한 **뒤에** 붙인다. 순서를 뒤집으면 검증 실패로
    # rollback되기 전 아주 짧은 창 동안 불완전한 material을 가리키는 receipt가 존재한다.
    return (
        await _mint_receipt(
            session,
            material=header,
            receipt_kind=receipt_kind,
        ),
        tuple(return_items),
    )


async def _create_snapshot(
    session: AsyncSession,
    *,
    external_system: str,
    receipt_kind: str,
    return_limit: int = 0,
) -> tuple[Any, tuple[CacheTargetSnapshotItem, ...]]:
    async with _snapshot_build_deadline():
        scan = await _scan_snapshot_material(
            session,
            external_system=external_system,
        )
        return await _persist_snapshot_material(
            session,
            scan=scan,
            receipt_kind=receipt_kind,
            return_limit=return_limit,
        )


async def _prune_expired_generic_snapshots(
    session: AsyncSession,
    *,
    external_system: str,
) -> None:
    await _prune_snapshot_generation(
        session,
        external_system=external_system,
        item_limit=_SNAPSHOT_ITEM_PRUNE_LIMIT,
        header_limit=_SNAPSHOT_HEADER_PRUNE_LIMIT,
    )


async def _snapshot_has_minimum_return_ttl(
    session: AsyncSession,
    *,
    expires_at: datetime,
) -> bool:
    return bool(
        (
            await session.execute(
                text(_CHECK_SNAPSHOT_RETURN_TTL_SQL),
                {"expires_at": expires_at},
            )
        ).scalar_one()
    )


async def _prune_snapshot_generation(
    session: AsyncSession,
    *,
    external_system: str,
    item_limit: int,
    header_limit: int,
    compaction_retention_seconds: float = _MATERIAL_COMPACTION_RETENTION_SECONDS,
) -> tuple[int, int, int]:
    """한 system의 snapshot 저장 공간을 bounded 4단계로 되찾는다.

    순서가 뜻을 갖는다.

    1. 만료·미참조 **receipt**를 지운다. 이래야 material이 orphan이 된다.
    2. 되찾을 material을 **표시**한다(orphan, 그리고 보존 기간을 넘긴 terminal audit).
       표시는 "item을 되찾기 시작했다"는 뜻이고, **재사용은 표시된 material을 잡지
       않는다**. audit material에서는 이 순간이 reader의 410 전환 시점이기도 하다.
    3. **표시된** material의 **item**을 지운다. 표시 없이 지우는 경로를 두면 부분
       배출된 material이 재사용 가능해진다(적대 리뷰가 잡은 구멍).
    4. item이 빈 orphan **material**을 지운다. audit material은 표시된 채로 남는다 —
       root/count가 감사 증거다.

    반환은 ``(지운 item 수, 지운 receipt 수, 표시한 material 수)``다.
    """

    deleted_headers = len(
        (
            await session.execute(
                text(_PRUNE_EXPIRED_SNAPSHOT_HEADERS_SQL),
                {"external_system": external_system, "limit": header_limit},
            )
        ).all()
    )
    compacted_materials = len(
        (
            await session.execute(
                text(_MARK_COMPACTED_MATERIALS_SQL),
                {
                    "external_system": external_system,
                    "limit": header_limit,
                    "compaction_retention_seconds": compaction_retention_seconds,
                },
            )
        ).all()
    )
    deleted_items = len(
        (
            await session.execute(
                text(_PRUNE_ORPHANED_MATERIAL_ITEMS_SQL),
                {"external_system": external_system, "limit": item_limit},
            )
        ).all()
    )
    await session.execute(
        text(_PRUNE_ORPHANED_MATERIALS_SQL),
        {"external_system": external_system, "limit": header_limit},
    )
    return deleted_items, deleted_headers, compacted_materials


async def prune_expired_cache_target_snapshots_batch(
    session: AsyncSession,
    *,
    after_external_system: str | None = None,
    item_limit: int = _SNAPSHOT_ITEM_PRUNE_LIMIT,
    header_limit: int = _SNAPSHOT_HEADER_PRUNE_LIMIT,
    compaction_retention_seconds: float = _MATERIAL_COMPACTION_RETENTION_SECONDS,
) -> CacheTargetSnapshotGcBatchResult:
    """만료·미참조 snapshot을 한 system/한 transaction 분량만 정리한다.

    system 선택은 ``COLLATE \"C\"`` exact keyset 순서이며 마지막 system 뒤에서는
    처음으로 한 번 wrap한다. 큰 단일 stream이 다른 stream의 GC를 독점하지 않도록
    호출 1회는 system 하나만 처리한다. item/header 삭제는 reader의 ``FOR SHARE``와
    충돌하면 ``SKIP LOCKED``하고, reconciliation request가 한 번이라도 참조한
    snapshot은 대상에서 영구 제외한다.

    transaction commit/rollback은 호출자 책임이다. ``has_more``는 index-friendly
    ``EXISTS`` 관측만 수행한다. 정확한 전역 count는 drain 종료 시
    :func:`observe_expired_cache_target_snapshot_backlog`를 별도 transaction에서 한 번
    호출해 구한다.
    """
    if not 0 < item_limit <= 10_000:
        raise ValueError("item_limit은 1 이상 10000 이하여야 합니다.")
    if not 0 < header_limit <= 1_000:
        raise ValueError("header_limit은 1 이상 1000 이하여야 합니다.")
    if compaction_retention_seconds <= 0:
        raise ValueError("compaction_retention_seconds는 0보다 커야 합니다.")

    select_params: dict[str, object] = {
        "after_external_system": after_external_system,
        "compaction_retention_seconds": compaction_retention_seconds,
    }
    system_row = (
        await session.execute(
            text(_SELECT_EXPIRED_SNAPSHOT_GC_SYSTEM_SQL),
            select_params,
        )
    ).one_or_none()
    if system_row is None and after_external_system is not None:
        system_row = (
            await session.execute(
                text(_SELECT_EXPIRED_SNAPSHOT_GC_SYSTEM_SQL),
                {**select_params, "after_external_system": None},
            )
        ).one_or_none()

    external_system: str | None = None
    deleted_items = 0
    deleted_headers = 0
    compacted_materials = 0
    if system_row is not None:
        external_system = str(system_row._mapping["external_system"])
        (
            deleted_items,
            deleted_headers,
            compacted_materials,
        ) = await _prune_snapshot_generation(
            session,
            external_system=external_system,
            item_limit=item_limit,
            header_limit=header_limit,
            compaction_retention_seconds=compaction_retention_seconds,
        )

    has_more = bool(
        (
            await session.execute(
                text(_HAS_EXPIRED_SNAPSHOT_GC_BACKLOG_SQL),
                {"compaction_retention_seconds": compaction_retention_seconds},
            )
        ).scalar_one()
    )
    return CacheTargetSnapshotGcBatchResult(
        external_system=external_system,
        deleted_items=deleted_items,
        deleted_headers=deleted_headers,
        compacted_materials=compacted_materials,
        has_more=has_more,
    )


async def observe_expired_cache_target_snapshot_backlog(
    session: AsyncSession,
) -> CacheTargetSnapshotGcBacklog:
    """만료·미참조 snapshot의 정확한 전역 item/header backlog를 관측한다.

    대규모 ``count(*)``는 batch마다 반복하지 않고 drain 종료/예산 도달 시 별도
    transaction에서 한 번만 호출한다. transaction commit/rollback은 호출자 책임이다.
    """
    row = (
        await session.execute(text(_OBSERVE_EXPIRED_SNAPSHOT_GC_BACKLOG_SQL))
    ).one()
    return CacheTargetSnapshotGcBacklog(
        remaining_items=int(row._mapping["remaining_items"]),
        remaining_headers=int(row._mapping["remaining_headers"]),
        total_items=int(row._mapping["total_items"]),
        total_headers=int(row._mapping["total_headers"]),
        unexpired_unreferenced_items=int(
            row._mapping["unexpired_unreferenced_items"]
        ),
        unexpired_unreferenced_headers=int(
            row._mapping["unexpired_unreferenced_headers"]
        ),
        referenced_items=int(row._mapping["referenced_items"]),
        referenced_headers=int(row._mapping["referenced_headers"]),
        snapshot_table_bytes=int(row._mapping["snapshot_table_bytes"]),
        snapshot_index_bytes=int(row._mapping["snapshot_index_bytes"]),
        snapshot_dead_tuples=int(row._mapping["snapshot_dead_tuples"]),
        snapshot_vacuum_lag_seconds=(
            int(row._mapping["snapshot_vacuum_lag_seconds"])
            if row._mapping["snapshot_vacuum_lag_seconds"] is not None
            else None
        ),
    )


async def _read_stream_identity(
    session: AsyncSession,
    *,
    external_system: str,
) -> dict[str, Any]:
    """`FOR SHARE OF stream` 아래에서 현재 material identity와 cursor를 읽는다."""

    await _barrier_snapshot_stream(session, external_system=external_system)
    identity_row = (
        await session.execute(
            text(_GET_SNAPSHOT_IDENTITY_SQL),
            {"external_system": external_system},
        )
    ).one_or_none()
    if identity_row is None:
        raise CacheTargetStreamConflict(
            "stream_not_found",
            "snapshot을 만들 cache target stream이 없습니다.",
        )
    return dict(identity_row._mapping)


async def _get_reusable_material(
    session: AsyncSession,
    *,
    identity: Mapping[str, Any],
    external_system: str,
) -> dict[str, Any] | None:
    """현재 source membership과 같은 **살아 있는** material을 찾는다.

    generic page와 reconciliation seal이 같은 이 함수를 쓴다. 앞판에서는 질의가 둘로
    갈려 공유가 단방향이었다(`0231` migration docstring 참조).
    """

    reusable = (
        await session.execute(
            text(_GET_REUSABLE_MATERIAL_SQL),
            {
                "external_system": external_system,
                "restore_epoch": int(identity["restore_epoch"]),
                "material_high_watermark_relay_order": int(
                    identity["material_high_watermark_relay_order"]
                ),
            },
        )
    ).one_or_none()
    return dict(reusable._mapping) if reusable is not None else None


async def _reuse_or_build_material(
    session: AsyncSession,
    *,
    external_system: str,
    receipt_kind: str,
    return_limit: int,
) -> tuple[dict[str, Any], tuple[CacheTargetSnapshotItem, ...]]:
    """살아 있는 material이 있으면 receipt만 붙이고, 없으면 새로 만든다."""

    identity = await _read_stream_identity(
        session,
        external_system=external_system,
    )
    material = await _get_reusable_material(
        session,
        identity=identity,
        external_system=external_system,
    )
    if material is None:
        return await _create_snapshot(
            session,
            external_system=external_system,
            receipt_kind=receipt_kind,
            return_limit=return_limit,
        )
    header = await _mint_receipt(
        session,
        material=material,
        receipt_kind=receipt_kind,
    )
    if return_limit <= 0:
        return header, ()
    item_rows = (
        await session.execute(
            text(_GET_SNAPSHOT_ITEMS_SQL),
            {
                "external_system": external_system,
                "material_id": header["material_id"],
                "after_row_number": 0,
                "limit": return_limit,
            },
        )
    ).all()
    return header, tuple(_snapshot_item(item) for item in item_rows)


async def _create_generic_snapshot(
    session: AsyncSession,
    *,
    external_system: str,
    limit: int,
) -> tuple[Any, tuple[CacheTargetSnapshotItem, ...]]:
    lock_id = advisory_lock_key(f"cache-target-snapshot:{external_system}")
    acquired = bool(
        (
            await session.execute(
                text(_LOCK_SNAPSHOT_STREAM_SQL),
                {"lock_id": lock_id},
            )
        ).scalar_one()
    )
    if not acquired:
        raise CacheTargetStreamConflict(
            "snapshot_busy",
            "같은 stream의 generic snapshot 생성이 이미 진행 중입니다.",
        )
    identity = await _read_stream_identity(
        session,
        external_system=external_system,
    )
    material = await _get_reusable_material(
        session,
        identity=identity,
        external_system=external_system,
    )
    if material is not None:
        # 새 receipt는 언제나 full TTL로 시작한다. 앞판이 재사용 전에 잔여 TTL을
        # 재던 검사(`_snapshot_has_minimum_return_ttl`)는 header 하나를 물려받아
        # 만료 시각까지 함께 물려받았기 때문에 필요했다 — 이제 필요 없다.
        header = await _mint_receipt(
            session,
            material=material,
            receipt_kind="generic",
        )
        item_rows = (
            await session.execute(
                text(_GET_SNAPSHOT_ITEMS_SQL),
                {
                    "external_system": external_system,
                    "material_id": header["material_id"],
                    "after_row_number": 0,
                    "limit": limit,
                },
            )
        ).all()
        return header, tuple(_snapshot_item(item) for item in item_rows)
    capacity_row = (
        await session.execute(
            text(_GET_GENERIC_SNAPSHOT_CAPACITY_SQL),
            {"external_system": external_system},
        )
    ).one()
    capacity = capacity_row._mapping
    if int(capacity["snapshot_count"] or 0) >= _GENERIC_SNAPSHOT_COPY_LIMIT:
        oldest_expires_at = cast(datetime, capacity["oldest_expires_at"])
        raise CacheTargetStreamConflict(
            "snapshot_capacity_exceeded",
            "미만료 generic snapshot copy 상한에 도달했습니다.",
            current={
                "snapshot_count": int(capacity["snapshot_count"]),
                "snapshot_limit": _GENERIC_SNAPSHOT_COPY_LIMIT,
                "oldest_expires_at": oldest_expires_at.isoformat(),
                "retry_after_seconds": int(capacity["retry_after_seconds"]),
            },
        )
    await _prune_expired_generic_snapshots(
        session,
        external_system=external_system,
    )
    header, items = await _create_snapshot(
        session,
        external_system=external_system,
        receipt_kind="generic",
        return_limit=limit,
    )
    # 재사용 경로에는 걸지 않는다. 거기 receipt는 방금 만들어져 언제나 full TTL이고,
    # 검사해도 통과만 하는 게이트가 된다. 여기서만 뜻이 있다 — 두 번의 scan과
    # 1,000,000행 INSERT가 handoff floor를 먹어치울 수 있는 유일한 경로다.
    if not await _snapshot_has_minimum_return_ttl(
        session,
        expires_at=cast(datetime, header["expires_at"]),
    ):
        raise CacheTargetStreamConflict(
            "snapshot_ttl_too_short",
            "새 snapshot의 서버 handoff 시점 TTL이 75분 미만입니다.",
        )
    return header, items[:limit]


async def get_cache_target_snapshot(
    session: AsyncSession,
    *,
    external_system: str,
    limit: int = 500,
    cursor: str | None = None,
) -> CacheTargetSnapshotPage:
    """첫 page에서 snapshot을 고정하고 후속 page는 immutable item만 읽는다."""

    if not 0 < limit <= 1000:
        raise ValueError("limit은 1 이상 1000 이하여야 합니다.")
    if cursor is None:
        async with _snapshot_build_deadline():
            header, items = await _create_generic_snapshot(
                session,
                external_system=external_system,
                limit=limit,
            )
        after_row_number = 0
    else:
        snapshot_id, after_row_number = _parse_snapshot_cursor(cursor)
        row = (
            await session.execute(
                text(_GET_SNAPSHOT_SQL),
                {"snapshot_id": snapshot_id},
            )
        ).one_or_none()
        if row is None or str(row._mapping["external_system"]) != external_system:
            raise CacheTargetStreamConflict(
                "snapshot_not_found",
                "요청한 stream의 fixed snapshot이 없습니다.",
            )
        header = dict(row._mapping)
        # compaction을 만료보다 **먼저** 본다. compaction 후보는 정의상 미만료
        # receipt가 없으므로, 만료를 먼저 보면 410은 영원히 도달하지 않는다.
        # 둘 다 참일 때 더 구체적인 쪽을 답한다 — 410은 보존된 receipt 값(개수·root·
        # compaction 시각)을 함께 실어 주고, 만료는 "다시 받아라"만 말한다.
        _reject_compacted_material(header)
        if not bool(row._mapping["valid"]):
            raise CacheTargetStreamConflict(
                "snapshot_expired",
                "fixed snapshot이 만료됐습니다.",
            )
        item_rows = (
            await session.execute(
                text(_GET_SNAPSHOT_ITEMS_SQL),
                {
                    "external_system": external_system,
                    "material_id": header["material_id"],
                    "after_row_number": after_row_number,
                    "limit": limit,
                },
            )
        ).all()
        items = tuple(_snapshot_item(item) for item in item_rows)

    return _snapshot_page(header=header, items=tuple(items), after_row_number=after_row_number)


def _reject_compacted_material(header: Mapping[str, Any]) -> None:
    """terminal compaction된 material을 typed 410으로 돌린다.

    `_GET_SNAPSHOT_SQL`이 receipt와 material을 함께 `FOR SHARE`로 잡으므로, 이 판정을
    통과한 뒤 compaction이 끼어들 수 없다 — reader는 정상 page 또는 410 중 하나만 보고
    부분 page를 보지 않는다.
    """

    compacted_at = header.get("compacted_at")
    if compacted_at is None:
        return
    raise CacheTargetStreamConflict(
        "snapshot_material_compacted",
        "snapshot material이 보존 기간을 지나 compaction됐습니다.",
        current={
            "snapshot_id": str(header["snapshot_id"]),
            "item_count": int(header["item_count"]),
            "merkle_root": str(header["merkle_root"]),
            "compacted_at": cast(datetime, compacted_at).isoformat(),
        },
    )


def _snapshot_page(
    *,
    header: Any,
    items: tuple[CacheTargetSnapshotItem, ...],
    after_row_number: int,
) -> CacheTargetSnapshotPage:
    count = int(header["item_count"])
    final_row = items[-1].row_number if items else after_row_number
    next_cursor = (
        _snapshot_cursor(str(header["snapshot_id"]), final_row)
        if final_row < count
        else None
    )
    return CacheTargetSnapshotPage(
        snapshot_id=str(header["snapshot_id"]),
        external_system=str(header["external_system"]),
        restore_epoch=int(header["restore_epoch"]),
        high_watermark_cursor=cache_target_event_cursor(
            int(header["high_watermark_relay_order"])
        ),
        count=count,
        merkle_root=str(header["merkle_root"]),
        items=items,
        next_cursor=next_cursor,
        created_at=header["created_at"],
        expires_at=header["expires_at"],
    )


async def get_cache_target_reconciliation_snapshot(
    session: AsyncSession,
    *,
    request_id: str,
    consumer_id: str,
    limit: int = 500,
    cursor: str | None = None,
) -> CacheTargetSnapshotPage:
    """Reconciliation request에 이미 결박된 immutable snapshot을 page한다."""

    request_id = _canonical_uuid(request_id, field="request_id")
    if not 0 < limit <= 1000:
        raise ValueError("limit은 1 이상 1000 이하여야 합니다.")
    header_row = (
        await session.execute(
            text(_GET_RECONCILIATION_SNAPSHOT_SQL),
            {"request_id": request_id},
        )
    ).one_or_none()
    if header_row is None:
        raise CacheTargetStreamConflict(
            "reconciliation_not_found",
            "reconciliation request가 없습니다.",
        )
    header = dict(header_row._mapping)
    if str(header["consumer_id"]) != consumer_id:
        raise CacheTargetStreamConflict(
            "consumer_mismatch",
            "service principal consumer_id가 stream binding과 다릅니다.",
        )
    if str(header["reconciliation_status"]) == "superseded":
        raise CacheTargetStreamConflict(
            "reconciliation_superseded",
            "restore fence가 reconciliation request를 대체했습니다.",
        )
    if str(header["reconciliation_status"]) != "running":
        raise CacheTargetStreamConflict(
            "reconciliation_not_sealed",
            "reconciliation request가 아직 fixed snapshot으로 seal되지 않았습니다.",
        )
    if header["snapshot_id"] is None:
        raise RuntimeError("running reconciliation request에 snapshot_id가 없습니다.")
    snapshot_id = str(header["snapshot_id"])
    snapshot_row = (
        await session.execute(
            text(_GET_SNAPSHOT_SQL),
            {"snapshot_id": snapshot_id},
        )
    ).one_or_none()
    if snapshot_row is None:
        raise RuntimeError("running reconciliation request의 snapshot이 없습니다.")
    header.update(dict(snapshot_row._mapping))
    # 지금 계약에서는 도달하지 않는다 — compaction 후보는 참조 reconciliation이 전부
    # terminal이어야 하고, 위에서 `running`이 아니면 이미 막힌다. 그래도 둔다. 그
    # 불변이 깨지면 부분 page 대신 typed 410이 나가야 한다.
    _reject_compacted_material(header)
    after_row_number = 0
    if cursor is not None:
        cursor_snapshot_id, after_row_number = _parse_snapshot_cursor(cursor)
        if cursor_snapshot_id != snapshot_id:
            raise CacheTargetStreamConflict(
                "reconciliation_precondition_failed",
                "cursor snapshot이 reconciliation request와 다릅니다.",
                current={"snapshot_id": snapshot_id},
            )
    item_rows = (
        await session.execute(
            text(_GET_SNAPSHOT_ITEMS_SQL),
            {
                "external_system": str(header["external_system"]),
                "material_id": header["material_id"],
                "after_row_number": after_row_number,
                "limit": limit,
            },
        )
    ).all()
    items = tuple(_snapshot_item(item) for item in item_rows)
    return _snapshot_page(
        header=header,
        items=items,
        after_row_number=after_row_number,
    )


async def get_cache_target_stream_discovery(
    session: AsyncSession,
    *,
    external_system: str,
    consumer_id: str,
) -> CacheTargetStreamDiscovery | None:
    """Stream control과 현재 running reconciliation을 한 projection으로 읽는다."""

    row = (
        await session.execute(
            text(_GET_STREAM_DISCOVERY_SQL),
            {"external_system": external_system},
        )
    ).one_or_none()
    if row is None:
        return None
    values = row._mapping
    if str(values["consumer_id"]) != consumer_id:
        raise CacheTargetStreamConflict(
            "consumer_mismatch",
            "service principal consumer_id가 stream binding과 다릅니다.",
        )
    active = None
    if values["request_id"] is not None:
        reconciliation_status = str(values["reconciliation_status"])
        if reconciliation_status not in ("preparing", "running"):
            raise RuntimeError("active reconciliation status가 유효하지 않습니다.")
        if reconciliation_status == "running" and values["snapshot_id"] is None:
            raise RuntimeError("running reconciliation request에 snapshot_id가 없습니다.")
        active = CacheTargetActiveReconciliation(
            request_id=str(values["request_id"]),
            external_system=str(values["external_system"]),
            status=cast('Literal["preparing", "running"]', reconciliation_status),
            phase_version=int(values["phase_version"]),
            snapshot_id=(
                str(values["snapshot_id"])
                if values["snapshot_id"] is not None
                else None
            ),
            restore_epoch=(
                int(values["snapshot_restore_epoch"])
                if values["snapshot_restore_epoch"] is not None
                else int(values["restore_epoch"])
            ),
            count=(
                int(values["item_count"]) if values["item_count"] is not None else None
            ),
            merkle_root=(
                str(values["merkle_root"]) if values["merkle_root"] is not None else None
            ),
            high_watermark_cursor=(
                cache_target_event_cursor(int(values["high_watermark_relay_order"]))
                if values["high_watermark_relay_order"] is not None
                else None
            ),
            stream_control_version=int(values["control_version"]),
            created_at=values["reconciliation_created_at"],
        )
    status = str(values["status"])
    if status not in ("ready", "fenced", "blocked"):
        raise RuntimeError("cache target stream status가 유효하지 않습니다.")
    return CacheTargetStreamDiscovery(
        external_system=str(values["external_system"]),
        consumer_id=str(values["consumer_id"]),
        restore_epoch=int(values["restore_epoch"]),
        control_version=int(values["control_version"]),
        status=cast('Literal["ready", "fenced", "blocked"]', status),
        blocked_event_id=(
            str(values["blocked_event_id"])
            if values["blocked_event_id"] is not None
            else None
        ),
        consumer_enabled=bool(values["consumer_enabled"]),
        active_reconciliation=active,
        created_at=values["created_at"],
        updated_at=values["updated_at"],
    )


def _stream_status(row: Any) -> CacheTargetStreamStatus:
    values = row._mapping
    snapshot = None
    if values["snapshot_id"] is not None:
        snapshot = CacheTargetSnapshotStatus(
            snapshot_id=str(values["snapshot_id"]),
            count=int(values["item_count"]),
            merkle_root=str(values["merkle_root"]),
            high_watermark_cursor=cache_target_event_cursor(
                int(values["high_watermark_relay_order"])
            ),
            created_at=values["snapshot_created_at"],
        )
    return CacheTargetStreamStatus(
        external_system=str(values["external_system"]),
        restore_epoch=int(values["restore_epoch"]),
        control_version=int(values["control_version"]),
        consumer_enabled=bool(values["consumer_enabled"]),
        state=str(values["status"]),
        pending_count=int(values["pending_count"]),
        leased_count=int(values["leased_count"]),
        retry_count=int(values["retry_count"]),
        dead_count=int(values["dead_count"]),
        delivered_count=int(values["delivered_count"]),
        superseded_count=int(values["superseded_count"]),
        blocked_event_id=(
            str(values["blocked_event_id"])
            if values["blocked_event_id"] is not None
            else None
        ),
        last_snapshot=snapshot,
        updated_at=values["updated_at"],
    )


async def list_cache_target_stream_statuses(
    session: AsyncSession,
    *,
    limit: int = 100,
    cursor: str | None = None,
) -> CacheTargetStreamStatusPage:
    if not 0 < limit <= 500:
        raise ValueError("limit은 1 이상 500 이하여야 합니다.")
    after = _parse_stream_cursor(cursor)
    rows = (
        await session.execute(
            text(_STREAM_STATUS_SQL),
            {"after_external_system": after, "limit": limit + 1},
        )
    ).all()
    items = tuple(_stream_status(row) for row in rows[:limit])
    next_cursor = (
        _stream_cursor(items[-1].external_system)
        if len(rows) > limit and items
        else None
    )
    return CacheTargetStreamStatusPage(items=items, next_cursor=next_cursor)


def _reconciliation(row: Any, *, replay: bool) -> CacheTargetReconciliationResult:
    values = row._mapping
    status = str(values["status"])
    if status not in ("preparing", "running", "succeeded", "failed", "superseded"):
        raise RuntimeError("reconciliation status가 유효하지 않습니다.")
    return CacheTargetReconciliationResult(
        request_id=str(values["request_id"]),
        external_system=str(values["external_system"]),
        status=cast(
            'Literal["preparing", "running", "succeeded", "failed", "superseded"]',
            status,
        ),
        phase_version=int(values["phase_version"]),
        snapshot_id=(
            str(values["snapshot_id"])
            if values["snapshot_id"] is not None
            else None
        ),
        expected_merkle_root=(
            str(values["expected_merkle_root"])
            if values["expected_merkle_root"] is not None
            else None
        ),
        actual_merkle_root=(
            str(values["actual_merkle_root"])
            if values["actual_merkle_root"] is not None
            else None
        ),
        error_code=(str(values["error_code"]) if values["error_code"] is not None else None),
        restore_epoch=(
            int(values["restore_epoch"]) if values.get("restore_epoch") is not None else None
        ),
        item_count=(
            int(values["item_count"]) if values.get("item_count") is not None else None
        ),
        stream_control_version=(
            int(values["control_version"])
            if values.get("control_version") is not None
            else None
        ),
        created_at=values["created_at"],
        started_at=values["started_at"],
        completed_at=values["completed_at"],
        idempotent_replay=replay,
    )


def _reconciliation_record(row: Any) -> CacheTargetReconciliationRecord:
    values = row._mapping
    status = str(values["status"])
    if status not in ("preparing", "running", "succeeded", "failed", "superseded"):
        raise RuntimeError("reconciliation status가 유효하지 않습니다.")
    restore_epoch = (
        int(values["snapshot_restore_epoch"])
        if values["snapshot_restore_epoch"] is not None
        else int(values["stream_restore_epoch"])
    )
    return CacheTargetReconciliationRecord(
        request_id=str(values["request_id"]),
        external_system=str(values["external_system"]),
        consumer_id=str(values["consumer_id"]),
        status=cast(
            'Literal["preparing", "running", "succeeded", "failed", "superseded"]',
            status,
        ),
        phase_version=int(values["phase_version"]),
        snapshot_id=(
            str(values["snapshot_id"])
            if values["snapshot_id"] is not None
            else None
        ),
        restore_epoch=restore_epoch,
        stream_control_version=int(values["control_version"]),
        item_count=(
            int(values["item_count"]) if values["item_count"] is not None else None
        ),
        merkle_root=(
            str(values["merkle_root"]) if values["merkle_root"] is not None else None
        ),
    )


async def get_cache_target_reconciliation(
    session: AsyncSession,
    *,
    request_id: str,
) -> CacheTargetReconciliationRecord:
    """Reconciliation request metadata만 읽는다. Snapshot item은 읽지 않는다."""

    request_id = _canonical_uuid(request_id, field="request_id")
    row = (
        await session.execute(
            text(_GET_RECONCILIATION_SQL),
            {"request_id": request_id},
        )
    ).one_or_none()
    if row is None:
        raise CacheTargetStreamConflict(
            "reconciliation_not_found",
            "reconciliation request가 없습니다.",
        )
    return _reconciliation_record(row)


async def _lock_stream_for_reconciliation_begin(
    session: AsyncSession,
    *,
    external_system: str,
    consumer_id: str,
    expected_restore_epoch: int,
    expected_control_version: int | None,
    create_only: bool,
) -> Any:
    if create_only:
        stream = (
            await session.execute(
                text(_CREATE_STREAM_SQL),
                {"external_system": external_system, "consumer_id": consumer_id},
            )
        ).one_or_none()
        if stream is None:
            current = (
                await session.execute(
                    text(_LOCK_STREAM_SQL),
                    {"external_system": external_system},
                )
            ).one()
            current_values = current._mapping
            raise CacheTargetStreamConflict(
                "reconciliation_precondition_failed",
                "If-None-Match create에 이미 stream이 존재합니다.",
                current={
                    "entity_tag": cache_target_stream_entity_tag(
                        external_system,
                        int(current_values["control_version"]),
                    ),
                    "restore_epoch": int(current_values["restore_epoch"]),
                },
            )
        values = stream._mapping
    else:
        stream = (
            await session.execute(
                text(_LOCK_STREAM_SQL),
                {"external_system": external_system},
            )
        ).one_or_none()
        if stream is None:
            raise CacheTargetStreamConflict(
                "stream_not_found",
                "cache target stream이 없습니다.",
            )
        values = stream._mapping
        if expected_control_version is None:
            raise ValueError("expected_control_version은 If-Match begin에 필요합니다.")
        if int(values["control_version"]) != expected_control_version:
            raise CacheTargetStreamConflict(
                "reconciliation_precondition_failed",
                "stream ETag가 현재 control version과 다릅니다.",
                current={
                    "entity_tag": cache_target_stream_entity_tag(
                        external_system,
                        int(values["control_version"]),
                    ),
                    "restore_epoch": int(values["restore_epoch"]),
                },
            )
    if str(values["consumer_id"]) != consumer_id:
        raise CacheTargetStreamConflict(
            "consumer_mismatch",
            "service principal consumer_id가 stream binding과 다릅니다.",
            current={"consumer_id": str(values["consumer_id"])},
        )
    if int(values["restore_epoch"]) != expected_restore_epoch:
        raise CacheTargetStreamConflict(
            "reconciliation_precondition_failed",
            "expected_restore_epoch이 현재 stream epoch와 다릅니다.",
            current={
                "restore_epoch": int(values["restore_epoch"]),
                "entity_tag": cache_target_stream_entity_tag(
                    external_system,
                    int(values["control_version"]),
                ),
            },
        )
    return stream


async def _invalidate_reconciliation_claims(
    session: AsyncSession,
    *,
    external_system: str,
) -> None:
    invalidated = (
        await session.execute(
            text(_INVALIDATE_CLAIMS_SQL),
            {"external_system": external_system},
        )
    ).all()
    claim_ids = [str(row._mapping["claim_id"]) for row in invalidated]
    if claim_ids:
        await session.execute(
            text(_RELEASE_CLAIM_DELIVERIES_SQL),
            {"claim_ids": claim_ids},
        )


async def begin_cache_target_reconciliation(
    session: AsyncSession,
    *,
    command_id: int,
    external_system: str,
    consumer_id: str,
    expected_restore_epoch: int,
    expected_control_version: int | None,
    create_only: bool,
    reason: str,
) -> CacheTargetReconciliationResult:
    """Stream을 fenced 상태로 만들고 snapshot 없는 preparing request를 시작한다."""

    validate_cache_target_external_system(external_system)
    if command_id <= 0:
        raise ValueError("command_id는 양수여야 합니다.")
    if not reason or reason != reason.strip() or len(reason) > 1000:
        raise ValueError("reason은 trim된 1~1000자 문자열이어야 합니다.")
    existing = (
        await session.execute(
            text(_GET_RECONCILIATION_BY_COMMAND_SQL),
            {"command_id": command_id},
        )
    ).one_or_none()
    if existing is not None:
        if str(existing._mapping["external_system"]) != external_system:
            raise CacheTargetStreamConflict(
                "reconciliation_command_mismatch",
                "command가 다른 stream reconciliation에 연결돼 있습니다.",
            )
        return _reconciliation(existing, replay=True)

    stream = await _lock_stream_for_reconciliation_begin(
        session,
        external_system=external_system,
        consumer_id=consumer_id,
        expected_restore_epoch=expected_restore_epoch,
        expected_control_version=expected_control_version,
        create_only=create_only,
    )
    active = (
        await session.execute(
            text(_GET_ACTIVE_RECONCILIATION_SQL),
            {"external_system": external_system},
        )
    ).one_or_none()
    if active is not None:
        raise CacheTargetStreamConflict(
            "reconciliation_active",
            "stream에 이미 active reconciliation request가 있습니다.",
            current={
                "request_id": str(active._mapping["request_id"]),
                "status": str(active._mapping["status"]),
                "snapshot_id": (
                    str(active._mapping["snapshot_id"])
                    if active._mapping["snapshot_id"] is not None
                    else None
                ),
            },
        )
    await _invalidate_reconciliation_claims(session, external_system=external_system)
    if not create_only:
        await session.execute(
            text(_HALT_STREAM_SQL),
            {"external_system": external_system},
        )
    request_id = str(uuid4())
    await session.execute(
        text(_INSERT_PREPARING_RECONCILIATION_SQL),
        {
            "request_id": request_id,
            "external_system": external_system,
            "command_id": command_id,
            "reason": reason,
        },
    )
    row = (
        await session.execute(
            text(_GET_RECONCILIATION_BY_COMMAND_SQL),
            {"command_id": command_id},
        )
    ).one()
    # ``stream`` keeps the row locked until transaction end; re-query above reads
    # the post-halt control_version for the response ETag.
    _ = stream
    return _reconciliation(row, replay=False)


async def seal_cache_target_reconciliation(
    session: AsyncSession,
    *,
    request_id: str,
    external_system: str,
    consumer_id: str,
    expected_phase_version: int,
    expected_restore_epoch: int,
    expected_item_count: int,
    expected_merkle_root: str,
) -> CacheTargetReconciliationResult:
    """첫 stream lock부터 seal 결과 조회까지 단일 누적 deadline을 적용한다."""

    async with _snapshot_build_deadline():
        return await _seal_cache_target_reconciliation(
            session,
            request_id=request_id,
            external_system=external_system,
            consumer_id=consumer_id,
            expected_phase_version=expected_phase_version,
            expected_restore_epoch=expected_restore_epoch,
            expected_item_count=expected_item_count,
            expected_merkle_root=expected_merkle_root,
        )


async def _seal_cache_target_reconciliation(
    session: AsyncSession,
    *,
    request_id: str,
    external_system: str,
    consumer_id: str,
    expected_phase_version: int,
    expected_restore_epoch: int,
    expected_item_count: int,
    expected_merkle_root: str,
) -> CacheTargetReconciliationResult:
    """Preparing request를 expected checksum과 같은 snapshot으로만 running 전환한다."""

    request_id = _canonical_uuid(request_id, field="request_id")
    expected_merkle_root = _sha256(expected_merkle_root, field="expected_merkle_root")
    if expected_phase_version <= 0:
        raise ValueError("expected_phase_version은 양수여야 합니다.")
    if expected_restore_epoch <= 0:
        raise ValueError("expected_restore_epoch은 양수여야 합니다.")
    if expected_item_count < 0:
        raise ValueError("expected_item_count는 0 이상이어야 합니다.")
    stream = await _lock_snapshot_stream_for_build(
        session,
        external_system=external_system,
    )
    if stream is None:
        raise CacheTargetStreamConflict(
            "reconciliation_precondition_failed",
            "reconciliation request의 stream binding이 다릅니다.",
        )
    if str(stream._mapping["consumer_id"]) != consumer_id:
        raise CacheTargetStreamConflict(
            "consumer_mismatch",
            "service principal consumer_id가 stream binding과 다릅니다.",
        )
    row = (
        await session.execute(
            text(_LOCK_RECONCILIATION_SQL),
            {"request_id": request_id},
        )
    ).one_or_none()
    if row is None:
        raise CacheTargetStreamConflict(
            "reconciliation_not_found",
            "reconciliation request가 없습니다.",
        )
    values = row._mapping
    if str(values["external_system"]) != external_system:
        raise CacheTargetStreamConflict(
            "reconciliation_precondition_failed",
            "reconciliation request의 stream binding이 다릅니다.",
            current={
                "external_system": str(values["external_system"]),
                "entity_tag": cache_target_reconciliation_entity_tag(
                    request_id,
                    int(values["phase_version"]),
                ),
            },
        )
    if str(values["status"]) == "superseded":
        raise CacheTargetStreamConflict(
            "reconciliation_superseded",
            "restore fence가 reconciliation request를 대체했습니다.",
            current={
                "status": "superseded",
                "entity_tag": cache_target_reconciliation_entity_tag(
                    request_id,
                    int(values["phase_version"]),
                ),
            },
        )
    if int(values["phase_version"]) != expected_phase_version:
        raise CacheTargetStreamConflict(
            "reconciliation_precondition_failed",
            "reconciliation request ETag가 현재 phase version과 다릅니다.",
            current={
                "entity_tag": cache_target_reconciliation_entity_tag(
                    request_id,
                    int(values["phase_version"]),
                ),
            },
        )
    if str(values["status"]) != "preparing":
        raise CacheTargetStreamConflict(
            "reconciliation_precondition_failed",
            "reconciliation request가 preparing 상태가 아닙니다.",
            current={
                "status": str(values["status"]),
                "entity_tag": cache_target_reconciliation_entity_tag(
                    request_id,
                    int(values["phase_version"]),
                ),
            },
        )
    identity = await _read_stream_identity(
        session,
        external_system=external_system,
    )
    header = await _get_reusable_material(
        session,
        identity=identity,
        external_system=external_system,
    )
    scan = None
    if header is None:
        scan = await _scan_snapshot_material(
            session,
            external_system=external_system,
        )
        header = scan.header
    # 검사를 **쓰기 전에** 한다. `_reuse_or_build_material`을 쓰면 checksum이 어긋난
    # 경우에도 receipt를 먼저 붙였다가 되감게 된다.
    actual = {
        "restore_epoch": int(header["restore_epoch"]),
        "item_count": int(header["item_count"]),
        "merkle_root": str(header["merkle_root"]),
    }
    if actual != {
        "restore_epoch": expected_restore_epoch,
        "item_count": expected_item_count,
        "merkle_root": expected_merkle_root,
    }:
        raise CacheTargetStreamConflict(
            "reconciliation_precondition_failed",
            "seal expected checksum이 현재 Map source heads와 다릅니다.",
            current=actual,
        )
    if scan is not None:
        persisted, _ = await _persist_snapshot_material(
            session,
            scan=scan,
            receipt_kind="reconciliation",
            return_limit=0,
        )
    else:
        persisted = await _mint_receipt(
            session,
            material=header,
            receipt_kind="reconciliation",
        )
    await session.execute(
        text(_SEAL_RECONCILIATION_SQL),
        {
            "request_id": request_id,
            "expected_phase_version": expected_phase_version,
            "snapshot_id": persisted["snapshot_id"],
            "expected_merkle_root": persisted["merkle_root"],
        },
    )
    sealed = (
        await session.execute(
            text(_GET_RECONCILIATION_SQL),
            {"request_id": request_id},
        )
    ).one()
    return _reconciliation(sealed, replay=False)


async def request_cache_target_reconciliation(
    session: AsyncSession,
    *,
    command_id: int,
    external_system: str,
    reason: str,
) -> CacheTargetReconciliationResult:
    """첫 stream lock부터 snapshot 결박까지 단일 누적 deadline을 적용한다."""

    async with _snapshot_build_deadline():
        return await _request_cache_target_reconciliation(
            session,
            command_id=command_id,
            external_system=external_system,
            reason=reason,
        )


async def _request_cache_target_reconciliation(
    session: AsyncSession,
    *,
    command_id: int,
    external_system: str,
    reason: str,
) -> CacheTargetReconciliationResult:
    """Stream을 halt하고 fixed snapshot checksum 비교 operation을 시작한다."""

    if command_id <= 0:
        raise ValueError("command_id는 양수여야 합니다.")
    if not reason or reason != reason.strip() or len(reason) > 1000:
        raise ValueError("reason은 trim된 1~1000자 문자열이어야 합니다.")
    existing = (
        await session.execute(
            text(_GET_RECONCILIATION_BY_COMMAND_SQL),
            {"command_id": command_id},
        )
    ).one_or_none()
    if existing is not None:
        if str(existing._mapping["external_system"]) != external_system:
            raise CacheTargetStreamConflict(
                "reconciliation_command_mismatch",
                "command가 다른 stream reconciliation에 연결돼 있습니다.",
            )
        return _reconciliation(existing, replay=True)

    stream = await _lock_snapshot_stream_for_build(
        session,
        external_system=external_system,
    )
    if stream is None:
        raise CacheTargetStreamConflict("stream_not_found", "cache target stream이 없습니다.")
    active = (
        await session.execute(
            text(_GET_ACTIVE_RECONCILIATION_SQL),
            {"external_system": external_system},
        )
    ).one_or_none()
    if active is not None:
        raise CacheTargetStreamConflict(
            "reconciliation_active",
            "stream에 이미 active reconciliation request가 있습니다.",
            current={
                "request_id": str(active._mapping["request_id"]),
                "status": str(active._mapping["status"]),
                "snapshot_id": (
                    str(active._mapping["snapshot_id"])
                    if active._mapping["snapshot_id"] is not None
                    else None
                ),
            },
        )
    await _invalidate_reconciliation_claims(session, external_system=external_system)
    await session.execute(
        text(_HALT_STREAM_SQL),
        {"external_system": external_system},
    )
    header, _ = await _reuse_or_build_material(
        session,
        external_system=external_system,
        receipt_kind="reconciliation",
        return_limit=0,
    )
    request_id = str(uuid4())
    inserted = (
        await session.execute(
            text(_INSERT_RECONCILIATION_SQL),
            {
                "request_id": request_id,
                "external_system": external_system,
                "command_id": command_id,
                "reason": reason,
                "snapshot_id": header["snapshot_id"],
                "expected_merkle_root": header["merkle_root"],
            },
        )
    ).one()
    row = (
        await session.execute(
            text(_GET_RECONCILIATION_BY_COMMAND_SQL),
            {"command_id": command_id},
        )
    ).one()
    _ = inserted
    _ = stream
    return _reconciliation(row, replay=False)


async def complete_cache_target_reconciliation(
    session: AsyncSession,
    *,
    request_id: str,
    external_system: str,
    consumer_id: str,
    snapshot_id: str,
    expected_restore_epoch: int,
    actual_merkle_root: str,
) -> CacheTargetReconciliationResult:
    """결박된 consumer의 exact snapshot receipt만 stream을 enable한다."""

    request_id = _canonical_uuid(request_id, field="request_id")
    snapshot_id = _canonical_uuid(snapshot_id, field="snapshot_id")
    if expected_restore_epoch <= 0:
        raise ValueError("expected_restore_epoch은 양수여야 합니다.")
    actual_merkle_root = _sha256(actual_merkle_root, field="actual_merkle_root")
    stream = (
        await session.execute(
            text(_LOCK_STREAM_SQL),
            {"external_system": external_system},
        )
    ).one_or_none()
    if stream is None:
        raise CacheTargetStreamConflict(
            "reconciliation_precondition_failed",
            "reconciliation request의 stream binding이 다릅니다.",
        )
    if str(stream._mapping["consumer_id"]) != consumer_id:
        raise CacheTargetStreamConflict(
            "consumer_mismatch",
            "service principal consumer_id가 stream binding과 다릅니다.",
        )
    row = (
        await session.execute(
            text(_LOCK_RECONCILIATION_SQL),
            {"request_id": request_id},
        )
    ).one_or_none()
    if row is None:
        raise CacheTargetStreamConflict(
            "reconciliation_precondition_failed",
            "reconciliation request가 현재 active request와 다릅니다.",
        )
    values = row._mapping
    if str(values["external_system"]) != external_system:
        raise CacheTargetStreamConflict(
            "reconciliation_precondition_failed",
            "reconciliation request의 stream binding이 다릅니다.",
            current={"external_system": str(values["external_system"])},
        )
    if str(values["status"]) == "superseded":
        raise CacheTargetStreamConflict(
            "reconciliation_superseded",
            "restore fence가 reconciliation request를 대체했습니다.",
            current={
                "status": "superseded",
                "entity_tag": cache_target_reconciliation_entity_tag(
                    request_id,
                    int(values["phase_version"]),
                ),
            },
        )
    if str(values["status"]) == "preparing":
        raise CacheTargetStreamConflict(
            "reconciliation_not_sealed",
            "reconciliation request가 아직 fixed snapshot으로 seal되지 않았습니다.",
        )
    if values["snapshot_id"] is None or values["expected_merkle_root"] is None:
        raise RuntimeError("sealed reconciliation request에 snapshot/root가 없습니다.")
    if (
        str(values["external_system"]) != external_system
        or str(values["snapshot_id"]) != snapshot_id
        or int(values["restore_epoch"]) != expected_restore_epoch
    ):
        raise CacheTargetStreamConflict(
            "reconciliation_precondition_failed",
            "reconciliation request의 stream, snapshot 또는 restore epoch이 다릅니다.",
            current={
                "external_system": str(values["external_system"]),
                "snapshot_id": str(values["snapshot_id"]),
                "restore_epoch": int(values["restore_epoch"]),
            },
        )
    if str(values["status"]) in ("succeeded", "failed"):
        if str(values["actual_merkle_root"]) != actual_merkle_root:
            raise CacheTargetStreamConflict(
                "reconciliation_receipt_mismatch",
                "terminal reconciliation에 다른 checksum을 재사용할 수 없습니다.",
            )
        return _reconciliation(row, replay=True)

    expected = str(values["expected_merkle_root"])
    exact_match = expected == actual_merkle_root
    if exact_match:
        if int(stream._mapping["restore_epoch"]) != int(values["restore_epoch"]):
            raise CacheTargetStreamConflict(
                "reconciliation_epoch_changed",
                "snapshot 뒤 restore epoch이 바뀌어 stream을 enable할 수 없습니다.",
            )
        dead_count = int(
            (
                await session.execute(
                    text(_COUNT_DEAD_SQL),
                    {
                        "external_system": external_system,
                        "restore_epoch": int(values["restore_epoch"]),
                    },
                )
            ).scalar_one()
        )
        if dead_count:
            raise CacheTargetStreamConflict(
                "reconciliation_dead_letters_remain",
                "dead-letter가 남아 있어 stream을 enable할 수 없습니다.",
                current={"dead_count": dead_count},
            )
        await session.execute(
            text(_RESUME_STREAM_SQL),
            {"external_system": external_system},
        )
        status = "succeeded"
        error_code = None
    else:
        await session.execute(
            text(_HALT_STREAM_SQL),
            {"external_system": external_system},
        )
        status = "failed"
        error_code = "checksum_mismatch"
    completed = (
        await session.execute(
            text(_COMPLETE_RECONCILIATION_SQL),
            {
                "request_id": request_id,
                "status": status,
                "actual_merkle_root": actual_merkle_root,
                "error_code": error_code,
            },
        )
    ).one()
    if exact_match:
        event_id = str(uuid4())
        payload = {
            "request_id": request_id,
            "actual_merkle_root": actual_merkle_root,
            "expected_merkle_root": expected,
            "snapshot_id": str(values["snapshot_id"]),
            "status": "succeeded",
            "version": "cache-target-reconciliation-v1",
        }
        inserted_event_id = str(
            (
                await session.execute(
                    text(_INSERT_RECONCILED_EVENT_SQL),
                    {
                        "event_id": event_id,
                        "request_id": request_id,
                        "restore_epoch": int(values["restore_epoch"]),
                        "source_payload_fingerprint": expected,
                        "payload_fingerprint": canonical_domain_command_fingerprint(
                            payload
                        ),
                        "payload": json.dumps(
                            payload,
                            ensure_ascii=False,
                            allow_nan=False,
                            sort_keys=True,
                            separators=(",", ":"),
                        ),
                    },
                )
            ).scalar_one()
        )
        await session.execute(
            text(_INSERT_DELIVERY_SQL),
            {"event_id": inserted_event_id},
        )
    _ = completed
    refreshed = (
        await session.execute(
            text(_GET_RECONCILIATION_SQL),
            {"request_id": request_id},
        )
    ).one()
    return _reconciliation(refreshed, replay=False)


async def get_cache_target_operation(
    session: AsyncSession,
    *,
    operation_id: str,
) -> CacheTargetOperation | None:
    operation_id = _canonical_uuid(operation_id, field="operation_id")
    row = (
        await session.execute(
            text(_GET_OPERATION_SQL),
            {"operation_id": operation_id},
        )
    ).one_or_none()
    if row is not None:
        return CacheTargetOperation(
            operation_id=str(row._mapping["request_id"]),
            status=str(row._mapping["status"]),
            snapshot_id=(
                str(row._mapping["snapshot_id"])
                if row._mapping["snapshot_id"] is not None
                else None
            ),
        )
    delivery = (
        await session.execute(
            text(_GET_DELIVERY_OPERATION_SQL),
            {"operation_id": operation_id},
        )
    ).one_or_none()
    if delivery is None:
        return None
    return CacheTargetOperation(
        operation_id=str(delivery._mapping["event_id"]),
        status=str(delivery._mapping["status"]),
    )
