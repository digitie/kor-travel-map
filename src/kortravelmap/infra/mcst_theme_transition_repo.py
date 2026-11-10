"""``kortravelmap.infra.mcst_theme_transition_repo`` — 기존 MCST Feature 전환 실행기(ADR-121 R4).

설계 정본은 ``docs/architecture/place-theme-attributes.md`` §8이다. 계획(``core.theme_attach.
plan_existing_features``)의 ``attach``·``collapse``는 master/생존자로 **병합**하고, ``retire``(반려
업종, D2)는 **퇴역**시킨다. Feature마다 같은 transaction에서:

1. 계획의 신선도를 다시 본다 — 퇴역 대상이 active이고 ``row_revision``이 계획과 같아야 하며,
   병합 대상(master/생존자)은 active·published여야 한다. 아니면 그 Feature는 건너뛴다(``stale``).
2. 되돌림 근거(``before_state``: 그 Feature의 link·상태·curation item)를 남긴다.
3. 병합은 :func:`~kortravelmap.infra.merge_repo.apply_feature_merge`(link 이동·MCST primary 강등·
   curation item 이동·퇴역·lifecycle override·병합 이력), 퇴역은
   ``feature.transition_admin_feature_state(..., 'retire')``(lifecycle override 포함).
4. 장부 ``ops.mcst_theme_transition_items``에 한 줄, 그리고
   ``feature.record_mcst_theme_transition_event``로 PinVi M05 사건(``rebind``/``detach``) 한 건.

batch 하나가 transaction 하나이고 domain command 하나다. 같은 계획의 같은 batch는 두 번 돌지
않는다(``(plan_sha256, batch_index)`` UNIQUE, 이미 있으면 건너뜀). Feature 하나가 실패하면 그
Feature만 savepoint로 되감고 다음으로 간다.

이 모듈은 commit하지 않는다 — 호출자가 commit(실행) 또는 rollback(리허설)한다.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from typing import TYPE_CHECKING, Any, Final, Literal

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from kortravelmap.infra.domain_command_repo import (
    canonical_domain_command_fingerprint,
    create_domain_command_claim,
    create_domain_command_record,
    lock_domain_command,
)
from kortravelmap.infra.feature_repo import lock_feature_curation_write
from kortravelmap.infra.merge_repo import MergeError, apply_feature_merge

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

__all__ = [
    "TRANSITION_ACTOR",
    "TRANSITION_OPERATION",
    "TransitionBatchResult",
    "TransitionItemOutcome",
    "TransitionPlan",
    "TransitionPlanItem",
    "build_transition_plan",
    "execute_transition_batch",
    "load_transition_plan",
]

TransitionAction = Literal["retire", "attach", "collapse"]
OutcomeStatus = Literal[
    "done", "stale_feature", "stale_revision", "stale_target", "already_done", "error"
]

TRANSITION_ACTOR: Final[str] = "system:mcst-theme-transition"
TRANSITION_OPERATION: Final[str] = "system.mcst-theme-transition.batch.v1"
_TRANSITION_ACTIONS: Final[frozenset[str]] = frozenset({"retire", "attach", "collapse"})
_RETIRE_REASON: Final[str] = "mcst-pet-business"
_IDEMPOTENCY_NAMESPACE: Final[uuid.UUID] = uuid.UUID("5b0f2c2e-1a21-4c1e-9b7e-2e4a1d0c7a21")


@dataclass(frozen=True, slots=True)
class TransitionPlanItem:
    feature_id: str
    dataset_key: str
    action: TransitionAction
    target_feature_id: str | None
    row_revision: int


@dataclass(frozen=True, slots=True)
class TransitionPlan:
    rule_version: str
    plan_sha256: str
    items: tuple[TransitionPlanItem, ...]

    def as_json(self) -> dict[str, Any]:
        return {
            "rule_version": self.rule_version,
            "plan_sha256": self.plan_sha256,
            "items": [asdict(item) for item in self.items],
        }


def _plan_sha256(rule_version: str, items: Sequence[TransitionPlanItem]) -> str:
    canonical = json.dumps(
        {"rule_version": rule_version, "items": [asdict(item) for item in items]},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def build_transition_plan(
    entries: Iterable[Any], *, revisions: Mapping[str, int], rule_version: str
) -> TransitionPlan:
    """계획 행(``PlanEntry``)에서 실행 계획을 만든다. ``keep``·``ambiguous``는 빠진다.

    순서는 결정적이다(action, dataset, feature_id) — 같은 입력이면 같은 ``plan_sha256``.
    """

    items = sorted(
        (
            TransitionPlanItem(
                feature_id=str(entry.feature_id),
                dataset_key=str(entry.dataset_key),
                action=entry.action,
                target_feature_id=(
                    None if entry.target_feature_id is None else str(entry.target_feature_id)
                ),
                row_revision=int(revisions[str(entry.feature_id)]),
            )
            for entry in entries
            if entry.action in _TRANSITION_ACTIONS
        ),
        key=lambda item: (item.action, item.dataset_key, item.feature_id),
    )
    return TransitionPlan(
        rule_version=rule_version,
        plan_sha256=_plan_sha256(rule_version, items),
        items=tuple(items),
    )


def load_transition_plan(payload: Mapping[str, Any]) -> TransitionPlan:
    """계획 파일을 읽고 ``plan_sha256``을 다시 계산해 대조한다(손으로 고친 계획을 거른다)."""

    rule_version = str(payload["rule_version"])
    items = tuple(
        TransitionPlanItem(
            feature_id=str(raw["feature_id"]),
            dataset_key=str(raw["dataset_key"]),
            action=raw["action"],
            target_feature_id=(
                None if raw["target_feature_id"] is None else str(raw["target_feature_id"])
            ),
            row_revision=int(raw["row_revision"]),
        )
        for raw in payload["items"]
    )
    for item in items:
        if item.action not in _TRANSITION_ACTIONS:
            raise ValueError(f"알 수 없는 전환 action: {item.action!r}")
        if (item.action == "retire") != (item.target_feature_id is None):
            raise ValueError(f"retire만 대상이 없다: {item.feature_id}")
        if item.row_revision < 1:
            raise ValueError(f"계획에 row_revision이 없다: {item.feature_id}")
    expected = _plan_sha256(rule_version, items)
    if expected != str(payload["plan_sha256"]):
        raise ValueError("계획 파일의 plan_sha256이 내용과 다르다")
    return TransitionPlan(rule_version=rule_version, plan_sha256=expected, items=items)


@dataclass(frozen=True, slots=True)
class TransitionItemOutcome:
    feature_id: str
    action: str
    status: OutcomeStatus
    detail: str | None = None
    event_id: str | None = None


@dataclass(frozen=True)
class TransitionBatchResult:
    batch_index: int
    skipped_batch: bool
    outcomes: tuple[TransitionItemOutcome, ...] = field(default_factory=tuple)

    def counts(self) -> dict[str, int]:
        return dict(Counter(f"{item.action}:{item.status}" for item in self.outcomes))


_BATCH_EXISTS_SQL = text(
    """
SELECT batch_id FROM ops.mcst_theme_transition_batches
 WHERE plan_sha256 = :plan_sha256 AND batch_index = :batch_index
"""
)

_INSERT_BATCH_SQL = text(
    """
INSERT INTO ops.mcst_theme_transition_batches (
    command_id, plan_sha256, rule_version, batch_index
) VALUES (:command_id, :plan_sha256, :rule_version, :batch_index)
RETURNING CAST(batch_id AS text)
"""
)

_LOCK_FEATURE_SQL = text(
    """
SELECT lifecycle_state, publication_state, row_revision
  FROM feature.features WHERE feature_id = CAST(:feature_id AS uuid)
 FOR UPDATE
"""
)

_ALREADY_TRANSITIONED_SQL = text(
    """
SELECT 1 FROM ops.mcst_theme_transition_items WHERE feature_id = CAST(:feature_id AS uuid)
"""
)

_BEFORE_STATE_SQL = text(
    """
SELECT jsonb_build_object(
    'lifecycle_state', f.lifecycle_state,
    'publication_state', f.publication_state,
    'quality_state', f.quality_state,
    'row_revision', f.row_revision,
    'links', COALESCE((
        SELECT jsonb_agg(jsonb_build_object(
                   'source_entity_key', sl.source_entity_key,
                   'source_role', sl.source_role,
                   'match_method', sl.match_method,
                   'confidence', sl.confidence)
               ORDER BY sl.source_entity_key)
          FROM provider_sync.source_links AS sl WHERE sl.feature_id = f.feature_id
    ), '[]'::jsonb),
    'curation_item_ids', COALESCE((
        SELECT jsonb_agg(CAST(item.curation_item_id AS text) ORDER BY item.curation_item_id)
          FROM feature.curation_items AS item WHERE item.feature_id = f.feature_id
    ), '[]'::jsonb)
) AS state
  FROM feature.features AS f WHERE f.feature_id = CAST(:feature_id AS uuid)
"""
)

_MERGE_TRANSITION_SQL = text(
    """
SELECT transition_id, row_revision
  FROM feature.feature_state_transitions
 WHERE feature_id = CAST(:feature_id AS uuid) AND transition_kind = 'merge'
   AND row_revision > :old_row_revision
 ORDER BY transition_id DESC
 LIMIT 1
"""
)

_RETIRE_SQL = text(
    """
CALL feature.transition_admin_feature_state(
    CAST(:feature_id AS uuid), NULL, NULL, NULL, CAST(:expected_row_revision AS bigint),
    CAST(:reason_code AS text), CAST(:principal AS text), 'retire', NULL, NULL, NULL
)
"""
)

_INSERT_ITEM_SQL = text(
    """
INSERT INTO ops.mcst_theme_transition_items (
    batch_id, feature_id, dataset_key, action, target_feature_id, old_row_revision,
    transition_id, row_revision_after, merge_id, before_state, evidence
) VALUES (
    CAST(:batch_id AS uuid), CAST(:feature_id AS uuid), :dataset_key, :action,
    CAST(:target_feature_id AS uuid), :old_row_revision, :transition_id,
    :row_revision_after, CAST(:merge_id AS uuid), CAST(:before_state AS jsonb),
    CAST(:evidence AS jsonb)
)
RETURNING CAST(item_id AS text)
"""
)

_RECORD_EVENT_SQL = text(
    """
CALL feature.record_mcst_theme_transition_event(CAST(:item_id AS uuid), NULL, NULL)
"""
)


def _batch_idempotency_key(plan_sha256: str, batch_index: int) -> str:
    return str(uuid.uuid5(_IDEMPOTENCY_NAMESPACE, f"{plan_sha256}:{batch_index}"))


async def _transition_one(
    session: AsyncSession,
    *,
    item: TransitionPlanItem,
    batch_id: str,
    rule_version: str,
) -> TransitionItemOutcome:
    if (
        await session.execute(_ALREADY_TRANSITIONED_SQL, {"feature_id": item.feature_id})
    ).first() is not None:
        return TransitionItemOutcome(item.feature_id, item.action, "already_done")
    state = (
        await session.execute(_LOCK_FEATURE_SQL, {"feature_id": item.feature_id})
    ).mappings().one_or_none()
    if state is None or state["lifecycle_state"] != "active":
        return TransitionItemOutcome(item.feature_id, item.action, "stale_feature")
    if int(state["row_revision"]) != item.row_revision:
        return TransitionItemOutcome(
            item.feature_id,
            item.action,
            "stale_revision",
            f"plan {item.row_revision} != current {int(state['row_revision'])}",
        )
    if item.target_feature_id is not None:
        target = (
            await session.execute(_LOCK_FEATURE_SQL, {"feature_id": item.target_feature_id})
        ).mappings().one_or_none()
        if (
            target is None
            or target["lifecycle_state"] != "active"
            or target["publication_state"] != "published"
        ):
            return TransitionItemOutcome(item.feature_id, item.action, "stale_target")
    before_state = (
        await session.execute(_BEFORE_STATE_SQL, {"feature_id": item.feature_id})
    ).scalar_one()

    merge_id: str | None = None
    if item.action == "retire":
        retired = (
            await session.execute(
                _RETIRE_SQL,
                {
                    "feature_id": item.feature_id,
                    "expected_row_revision": item.row_revision,
                    "reason_code": _RETIRE_REASON,
                    "principal": TRANSITION_ACTOR,
                },
            )
        ).mappings().one()
        transition_id = int(retired["o_transition_id"])
        row_revision_after = int(retired["o_row_revision"])
    else:
        assert item.target_feature_id is not None
        outcome = await apply_feature_merge(
            session,
            master_id=item.target_feature_id,
            loser_id=item.feature_id,
            merged_by=TRANSITION_ACTOR,
            reason=f"ADR-121 {item.action} ({rule_version})",
        )
        merge_id = outcome.merge_id
        transition = (
            await session.execute(
                _MERGE_TRANSITION_SQL,
                {"feature_id": item.feature_id, "old_row_revision": item.row_revision},
            )
        ).mappings().one()
        transition_id = int(transition["transition_id"])
        row_revision_after = int(transition["row_revision"])

    item_id = str(
        (
            await session.execute(
                _INSERT_ITEM_SQL,
                {
                    "batch_id": batch_id,
                    "feature_id": item.feature_id,
                    "dataset_key": item.dataset_key,
                    "action": item.action,
                    "target_feature_id": item.target_feature_id,
                    "old_row_revision": item.row_revision,
                    "transition_id": transition_id,
                    "row_revision_after": row_revision_after,
                    "merge_id": merge_id,
                    "before_state": json.dumps(before_state, ensure_ascii=False, default=str),
                    "evidence": json.dumps({"rule_version": rule_version}),
                },
            )
        ).scalar_one()
    )
    event = (
        await session.execute(_RECORD_EVENT_SQL, {"item_id": item_id})
    ).mappings().one()
    return TransitionItemOutcome(
        item.feature_id, item.action, "done", event_id=str(event["o_event_id"])
    )


async def execute_transition_batch(
    session: AsyncSession,
    *,
    plan: TransitionPlan,
    batch_index: int,
    items: Sequence[TransitionPlanItem],
) -> TransitionBatchResult:
    """계획의 한 batch를 현재 transaction에서 실행한다. commit은 호출자 몫이다."""

    await lock_feature_curation_write(session)
    if (
        await session.execute(
            _BATCH_EXISTS_SQL,
            {"plan_sha256": plan.plan_sha256, "batch_index": batch_index},
        )
    ).first() is not None:
        return TransitionBatchResult(batch_index=batch_index, skipped_batch=True)

    idempotency_key = _batch_idempotency_key(plan.plan_sha256, batch_index)
    await lock_domain_command(
        session,
        actor=TRANSITION_ACTOR,
        operation=TRANSITION_OPERATION,
        idempotency_key=idempotency_key,
    )
    claim = await create_domain_command_claim(
        session,
        actor=TRANSITION_ACTOR,
        operation=TRANSITION_OPERATION,
        idempotency_key=idempotency_key,
        request_fingerprint=canonical_domain_command_fingerprint(
            {
                "plan_sha256": plan.plan_sha256,
                "batch_index": batch_index,
                "feature_ids": [item.feature_id for item in items],
            }
        ),
    )
    batch_id = str(
        (
            await session.execute(
                _INSERT_BATCH_SQL,
                {
                    "command_id": claim.command_id,
                    "plan_sha256": plan.plan_sha256,
                    "rule_version": plan.rule_version,
                    "batch_index": batch_index,
                },
            )
        ).scalar_one()
    )
    outcomes: list[TransitionItemOutcome] = []
    for item in items:
        try:
            async with session.begin_nested():
                outcomes.append(
                    await _transition_one(
                        session, item=item, batch_id=batch_id, rule_version=plan.rule_version
                    )
                )
        except (MergeError, DBAPIError) as exc:
            sqlstate = getattr(getattr(exc, "orig", None), "sqlstate", None)
            outcomes.append(
                TransitionItemOutcome(
                    item.feature_id,
                    item.action,
                    "error",
                    f"{type(exc).__name__} sqlstate={sqlstate}"
                    if sqlstate
                    else type(exc).__name__ + ": " + str(exc)[:200],
                )
            )
    result = TransitionBatchResult(
        batch_index=batch_index, skipped_batch=False, outcomes=tuple(outcomes)
    )
    await create_domain_command_record(
        session,
        command_id=claim.command_id,
        response_status=200,
        response_body={"batch_id": batch_id, "counts": result.counts()},
        response_headers={},
    )
    return result
