"""복원된 데이터베이스의 M05 delivery 상태를 점검하고 수리한다 (T-VN-M05-2 D단계).

## 왜 A·B로는 안 되는가

A단계는 evidence를 canonical JSONL로 뽑고, B단계는 그 **번들**을 검증한다. 둘 다
artifact만 본다. 그런데 조문이 요구하는 다섯 단계 중 둘은 artifact가 아니라
**복원된 데이터베이스**를 가리킨다.

`pg_dump`는 스키마 전체를 담는다. 그래서 복원본에는
`ops.feature_reference_reconciliation_leases`가 dump 시점의 `worker_id`·`lease_epoch`·
`lease_expires_at`을 달고 **그대로 살아 돌아온다**. B단계가 "lease를 evidence root에
담지 않으므로 fencing token이 되살아날 자리가 없다"고 말할 수 있는 것은 번들에
대해서일 뿐이고, 복원본에 대해서는 거짓이다.

무효화하지 않으면 어떻게 되는가. `ack` 프로시저는 ``worker_id = p_worker_id AND
lease_epoch = p_lease_epoch AND lease_expires_at > now()``일 때만 cursor를 전진시킨다.
복원본은 원본의 **사본**이므로 같은 ``(worker_id, lease_epoch)`` 쌍이 양쪽에서 동시에
유효하다 — 원본을 향해 돌던 worker가 복원본에도 ack할 수 있다. 그것이 split-brain이다.

그리고 `acked_through_sequence`는 바로 그 mutable 행의 컬럼이다(`subscriptions`가
아니다). B단계는 그 값을 Python으로 계산하지만 복원본에 쓰지 않는다.

## 무엇을 어떤 순서로 하는가

1. **preflight** — 복원본의 evidence 그래프가 자기모순이 없는지, 그리고 그 그래프를
   지키는 **트리거가 살아 있는지** 본다. Manager의 카탈로그 지문(소유자·ACL·
   `prosecdef`·extension)과 겹치지 않는 축이다: 그쪽은 카탈로그를 보고 이쪽은 행과
   트리거 상태를 본다.

   트리거 축이 왜 필요한가. `pg_restore --disable-triggers`나 data-only 복원은
   트리거를 **지우지 않고 꺼 둔 채로** 남길 수 있다. 그러면 append-only 보호가
   사라진 DB가 겉보기에는 멀쩡하다 — 행도 다 있고 카탈로그에 트리거도 있다.
   `tgenabled`를 봐야 드러난다. 이름 목록을 박지 않고 필수 relation에 달린
   **모든** 트리거를 훑는 이유는, 목록을 박으면 트리거가 늘 때마다 조용히 구멍이
   생기기 때문이다(AGENTS.md DO NOT 15).
2. **cursor 재구축** — 불변 ACK/event의 **연속 prefix**에서 `acked_through_sequence`를
   다시 만든다. ack 프로시저가 ack 행 INSERT와 cursor UPDATE를 한 블록에서 하므로
   **정합한 스냅숏에는 drift가 0이어야 한다.** 어느 방향이든 drift는 실패다.
3. **lease 무효화** — `worker_id`와 `lease_expires_at`을 지우고 `lease_epoch`을 **올린다.**
   epoch을 올리는 것이 핵심이다. holder만 지우면 원본을 향해 돌던 worker가 복원본에서
   같은 epoch으로 다시 lease를 잡을 수 있다.

`apply=False`면 아무것도 쓰지 않고 무엇을 하려 했는지만 돌려준다.

**preflight가 실패하면 수리하지 않는다.** 검증되지 않은 상태를 수리하는 것은 손상을
되돌릴 수 없는 쪽으로 확정하는 일이다.

## 무엇을 하지 않는가

evidence root 밖 relation, RustFS 실물, 그리고 복원 자체(`pg_restore` 실행)는 다루지
않는다. 이 모듈은 **이미 복원된** 연결을 받아 M05 delivery 상태만 본다.

ADR 참조: ADR-002 async-only · ADR-004 raw SQL ``text()`` · ADR-097 §후속 1 후단
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Final

from sqlalchemy import text

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncConnection

__all__ = [
    "CursorRebuild",
    "LeaseInvalidation",
    "RestoreRepairReport",
    "invalidate_leases",
    "preflight_evidence_graph",
    "rebuild_acked_through",
    "repair_restored_database",
]

#: 복원본에 반드시 있어야 하는 relation. 없으면 나머지 점검이 `UndefinedTable`로
#: 죽으므로 **가장 먼저** 본다.
_REQUIRED_RELATIONS: Final[tuple[str, ...]] = (
    "feature.feature_creation_origins",
    "feature.manual_feature_identity_claims",
    "ops.domain_commands",
    "ops.domain_command_results",
    "ops.feature_requests",
    "ops.manual_provider_dedup_cases",
    "ops.manual_provider_dedup_resolutions",
    "ops.feature_reference_reconciliation_events",
    "ops.feature_reference_reconciliation_acks",
    "ops.feature_reference_reconciliation_subscriptions",
    "ops.feature_reference_reconciliation_leases",
)

#: 필수 relation에 달린 트리거 중 **꺼져 있는** 것을 찾는다.
#:
#: 이름을 열거하지 않고 relation에서 유도한다. `tgisinternal`을 빼는 이유는 그것이
#: 제약이 만든 내부 트리거(FK 등)라 `tgenabled`가 사용자 트리거와 다른 뜻이기
#: 때문이다. `'O'`는 origin — 정상 상태다. `'D'`는 꺼짐, `'R'`/`'A'`는 replica 전용이라
#: origin 세션의 쓰기를 막지 못한다.
_DISABLED_TRIGGER_SQL: Final[str] = """
SELECT (relation.relnamespace::regnamespace)::text || '.' || relation.relname
           AS relation_name,
       trigger_row.tgname AS trigger_name,
       trigger_row.tgenabled AS enabled_flag
FROM pg_catalog.pg_trigger AS trigger_row
JOIN pg_catalog.pg_class AS relation ON relation.oid = trigger_row.tgrelid
WHERE NOT trigger_row.tgisinternal
  AND trigger_row.tgenabled <> 'O'
  AND (relation.relnamespace::regnamespace)::text || '.' || relation.relname
      = ANY(CAST(:relations AS text[]))
ORDER BY relation_name, trigger_name
"""

#: 행 수준 그래프 점검. 각 항목은 **위반 행을 세는** SQL이라 0이 아니면 실패다.
#: dump가 relation 사이에서 시점이 갈리면 정확히 이 모양으로 드러난다.
_GRAPH_CHECKS: Final[tuple[tuple[str, str], ...]] = (
    (
        "event를 가리키지 않는 ACK",
        "SELECT count(*) FROM ops.feature_reference_reconciliation_acks AS ack"
        " WHERE NOT EXISTS (SELECT 1 FROM"
        " ops.feature_reference_reconciliation_events AS event"
        " WHERE event.event_id = ack.event_id)",
    ),
    (
        "subscription이 없는 lease",
        "SELECT count(*) FROM ops.feature_reference_reconciliation_leases AS lease"
        " WHERE NOT EXISTS (SELECT 1 FROM"
        " ops.feature_reference_reconciliation_subscriptions AS subscription"
        " WHERE subscription.principal_id = lease.principal_id)",
    ),
    (
        "subscription cursor보다 뒤에 있는 lease cursor",
        "SELECT count(*) FROM ops.feature_reference_reconciliation_leases AS lease"
        " JOIN ops.feature_reference_reconciliation_subscriptions AS subscription"
        " ON subscription.principal_id = lease.principal_id"
        " WHERE lease.acked_through_sequence < subscription.initial_event_sequence",
    ),
    (
        "중복된 event_sequence",
        "SELECT coalesce(sum(duplicates.tally - 1), 0) FROM ("
        " SELECT count(*) AS tally FROM"
        " ops.feature_reference_reconciliation_events"
        " GROUP BY event_sequence HAVING count(*) > 1) AS duplicates",
    ),
    (
        "command가 없는 manual origin",
        "SELECT count(*) FROM feature.feature_creation_origins AS origin"
        " WHERE origin.command_id IS NOT NULL AND NOT EXISTS ("
        " SELECT 1 FROM ops.domain_commands AS command"
        " WHERE command.command_id = origin.command_id)",
    ),
)

#: 옛 검증기의 LATERAL 둘을 그대로 옮긴 것이다. 첫 lateral이 ACK가 **없는** 첫
#: event를 찾고, 둘째가 그보다 **작은** event만으로 최댓값을 취한다. 최댓값이 아니라
#: **연속 prefix의** 최댓값이라야 한다 — 끊긴 뒤의 ack로 cursor를 밀면 그 사이 event를
#: 영영 건너뛴다.
_REBUILD_SQL: Final[str] = """
SELECT lease.principal_id,
       lease.acked_through_sequence AS stored_sequence,
       coalesce(prefix.rebuilt_sequence, subscription.initial_event_sequence)
           AS rebuilt_sequence,
       gap.first_missing_sequence
FROM ops.feature_reference_reconciliation_leases AS lease
JOIN ops.feature_reference_reconciliation_subscriptions AS subscription
  ON subscription.principal_id = lease.principal_id
LEFT JOIN LATERAL (
    SELECT min(event.event_sequence) AS first_missing_sequence
    FROM ops.feature_reference_reconciliation_events AS event
    WHERE event.event_sequence > subscription.initial_event_sequence
      AND NOT EXISTS (
          SELECT 1 FROM ops.feature_reference_reconciliation_acks AS ack
          WHERE ack.event_id = event.event_id
            AND ack.principal_id = lease.principal_id
      )
) AS gap ON TRUE
LEFT JOIN LATERAL (
    SELECT max(event.event_sequence) AS rebuilt_sequence
    FROM ops.feature_reference_reconciliation_events AS event
    WHERE event.event_sequence > subscription.initial_event_sequence
      AND (gap.first_missing_sequence IS NULL
           OR event.event_sequence < gap.first_missing_sequence)
      AND EXISTS (
          SELECT 1 FROM ops.feature_reference_reconciliation_acks AS ack
          WHERE ack.event_id = event.event_id
            AND ack.principal_id = lease.principal_id
      )
) AS prefix ON TRUE
ORDER BY lease.principal_id
"""

#: lease 행을 **읽고 잠근다.** 무효화는 읽은 값(이전 holder·epoch)을 receipt에 실어야
#: 하는데 `UPDATE ... RETURNING`으로는 이전 값을 읽을 수 없다.
_READ_LEASES_SQL: Final[str] = (
    "SELECT principal_id, worker_id, lease_epoch"
    " FROM ops.feature_reference_reconciliation_leases"
    " ORDER BY principal_id"
)
_LOCK_LEASES_SQL: Final[str] = f"{_READ_LEASES_SQL} FOR UPDATE"


@dataclass(frozen=True)
class LeaseInvalidation:
    """한 principal의 lease 무효화 결과."""

    principal_id: str
    cleared_worker_id: str | None
    previous_lease_epoch: int
    lease_epoch: int

    @property
    def held(self) -> bool:
        """dump 시점에 **holder가 있었나.** 있었으면 split-brain 후보다."""

        return self.cleared_worker_id is not None


@dataclass(frozen=True)
class CursorRebuild:
    """한 principal의 cursor 재구축 결과."""

    principal_id: str
    stored_sequence: int
    rebuilt_sequence: int
    first_missing_sequence: int | None

    @property
    def drifted(self) -> bool:
        return self.stored_sequence != self.rebuilt_sequence

    @property
    def direction(self) -> str:
        """`ahead`는 ACK 행을 잃은 것, `behind`는 cursor를 잃은 것이다."""

        if self.stored_sequence > self.rebuilt_sequence:
            return "ahead"
        if self.stored_sequence < self.rebuilt_sequence:
            return "behind"
        return "aligned"


@dataclass
class RestoreRepairReport:
    """무엇을 봤고 무엇을 고쳤는지. **실패도 담는다.**"""

    preflight_failures: list[str] = field(default_factory=list)
    rebuilt: list[CursorRebuild] = field(default_factory=list)
    invalidated: list[LeaseInvalidation] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)
    applied: bool = False

    @property
    def ok(self) -> bool:
        return not self.preflight_failures and not self.failures


async def preflight_evidence_graph(connection: AsyncConnection) -> list[str]:
    """복원본의 evidence 그래프가 자기모순이 없는지 본다.

    relation 존재를 **먼저** 확인한다 — 없는 relation을 향해 행 점검을 돌리면
    `UndefinedTable`로 죽고, 그러면 "무엇이 없는지"를 말하지 못한다.
    """

    failures: list[str] = []
    missing = [
        relation
        for relation in _REQUIRED_RELATIONS
        if await connection.scalar(
            text("SELECT to_regclass(:relation) IS NULL"), {"relation": relation}
        )
    ]
    failures.extend(f"relation이 없다: {relation}" for relation in missing)
    if missing:
        # 그래프 점검은 relation이 다 있어야 의미가 있다. 여기서 멈춘다.
        return failures

    disabled = (
        await connection.execute(
            text(_DISABLED_TRIGGER_SQL), {"relations": list(_REQUIRED_RELATIONS)}
        )
    ).mappings().all()
    failures.extend(
        f"트리거가 꺼져 있다: {row['relation_name']}.{row['trigger_name']}"
        f" (tgenabled={row['enabled_flag']})"
        for row in disabled
    )

    for label, sql in _GRAPH_CHECKS:
        violations = int(await connection.scalar(text(sql)) or 0)
        if violations:
            failures.append(f"{label}: {violations}건")
    return failures


async def rebuild_acked_through(
    connection: AsyncConnection, *, apply: bool
) -> tuple[list[CursorRebuild], list[str]]:
    """불변 ACK/event의 연속 prefix에서 `acked_through_sequence`를 다시 만든다.

    **어느 방향이든 drift는 실패다.** ack 프로시저가 ack 행 INSERT와 cursor UPDATE를
    한 블록에서 하므로, 정합한 스냅숏이라면 저장된 값과 재구축한 값이 같아야 한다.
    앞서 있으면 ACK 행을 잃은 것이고 뒤처져 있으면 cursor를 잃은 것이다 — 둘 다 dump가
    relation 사이에서 시점이 갈렸다는 신호라 조용히 고치고 넘어가면 안 된다.
    """

    rows = (await connection.execute(text(_REBUILD_SQL))).mappings().all()
    rebuilt = [
        CursorRebuild(
            principal_id=str(row["principal_id"]),
            stored_sequence=int(row["stored_sequence"]),
            rebuilt_sequence=int(row["rebuilt_sequence"]),
            first_missing_sequence=(
                None
                if row["first_missing_sequence"] is None
                else int(row["first_missing_sequence"])
            ),
        )
        for row in rows
    ]

    failures = [
        f"cursor drift({cursor.direction}): {cursor.principal_id}"
        f" stored={cursor.stored_sequence} rebuilt={cursor.rebuilt_sequence}"
        for cursor in rebuilt
        if cursor.drifted
    ]

    if apply:
        for cursor in rebuilt:
            if not cursor.drifted:
                continue
            await connection.execute(
                text(
                    "UPDATE ops.feature_reference_reconciliation_leases"
                    " SET acked_through_sequence = :rebuilt,"
                    "     updated_at = clock_timestamp()"
                    " WHERE principal_id = :principal_id"
                ),
                {
                    "rebuilt": cursor.rebuilt_sequence,
                    "principal_id": cursor.principal_id,
                },
            )
    return rebuilt, failures


async def invalidate_leases(
    connection: AsyncConnection, *, apply: bool
) -> list[LeaseInvalidation]:
    """dump 시점의 holder와 fencing token을 무효화한다.

    `worker_id`·`lease_expires_at`을 지우는 것만으로는 부족하다. **`lease_epoch`을
    올려야 한다** — 복원본은 원본의 사본이므로, epoch이 그대로면 원본을 향해 돌던
    worker가 들고 있는 ``(worker_id, lease_epoch)``가 복원본에서도 유효하다. epoch은
    lease 프로시저가 오직 증가만 시키므로 올리는 방향이 단조롭고 안전하다.
    """

    # apply할 때만 잠근다. 읽기만 하는 호출이 행을 잠그면 dry-run이 운영을 막는다.
    statement = _LOCK_LEASES_SQL if apply else _READ_LEASES_SQL
    rows = (await connection.execute(text(statement))).mappings().all()
    invalidated = [
        LeaseInvalidation(
            principal_id=str(row["principal_id"]),
            cleared_worker_id=(
                None if row["worker_id"] is None else str(row["worker_id"])
            ),
            previous_lease_epoch=int(row["lease_epoch"]),
            lease_epoch=int(row["lease_epoch"]) + 1,
        )
        for row in rows
    ]

    if apply:
        await connection.execute(
            text(
                "UPDATE ops.feature_reference_reconciliation_leases"
                " SET worker_id = NULL,"
                "     lease_expires_at = NULL,"
                "     lease_epoch = lease_epoch + 1,"
                "     updated_at = clock_timestamp()"
            )
        )
    return invalidated


async def repair_restored_database(
    connection: AsyncConnection, *, apply: bool
) -> RestoreRepairReport:
    """복원본을 점검하고, preflight가 통과했을 때만 수리한다.

    **순서가 규약이다.** preflight → cursor 재구축 → lease 무효화. cursor를 먼저
    고치는 이유는 그 값이 lease 행에 있어서다 — lease를 먼저 건드리면 같은 행을 두 번
    쓰게 되고, receipt에서 무엇이 왜 바뀌었는지가 갈라지지 않는다.
    """

    report = RestoreRepairReport()
    report.preflight_failures = await preflight_evidence_graph(connection)
    if report.preflight_failures:
        # 검증되지 않은 상태를 수리하면 손상을 되돌릴 수 없게 확정한다.
        return report

    report.rebuilt, cursor_failures = await rebuild_acked_through(
        connection, apply=apply
    )
    report.failures.extend(cursor_failures)
    report.invalidated = await invalidate_leases(connection, apply=apply)
    report.applied = apply
    return report
