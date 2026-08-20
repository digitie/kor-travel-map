"""T-VN-40 admin-only theme candidate reads and typed commands."""

from __future__ import annotations

import base64
import binascii
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

__all__ = [
    "ThemeCandidatePage",
    "ThemeCandidateRecord",
    "ThemeCandidateTransitionPage",
    "ThemeCandidateTransitionRecord",
    "get_theme_candidate",
    "list_theme_candidate_transitions",
    "list_theme_candidates",
    "promote_theme_candidate",
    "reject_theme_candidate",
]

ReviewState = Literal["open", "promoted", "rejected"]


@dataclass(frozen=True, slots=True)
class ThemeCandidateRecord:
    candidate_id: str
    rule_id: str
    theme_id: str
    theme_slug: str
    theme_name: str
    source_id: str
    source_name: str
    provider_dataset_id: int
    source_entity_key: str
    feature_id: str
    feature_uuid: str
    feature_name: str
    feature_kind: str
    feature_category: str
    feature_detail: dict[str, Any]
    lifecycle_state: str
    publication_state: str
    quality_state: str
    source_record_key: str
    source_record_hash: str
    rule_row_revision: int
    rule_input_hash: str
    candidate_input_hash: str
    review_state: ReviewState
    eligibility_present: bool
    disposition: str
    rank_score: str
    proposal_title: str | None
    proposal_summary: str | None
    match_evidence: dict[str, Any]
    row_revision: int
    feature_row_revision: int
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class ThemeCandidatePage:
    items: tuple[ThemeCandidateRecord, ...]
    next_cursor: str | None


@dataclass(frozen=True, slots=True)
class ThemeCandidateTransitionRecord:
    transition_id: int
    candidate_id: str
    transition_kind: str
    from_review_state: str | None
    to_review_state: str
    from_eligibility_present: bool | None
    to_eligibility_present: bool
    candidate_row_revision: int
    generation_id: str | None
    command_id: int | None
    actor: str
    reason_code: str
    causation_ref: dict[str, Any]
    occurred_at: datetime


@dataclass(frozen=True, slots=True)
class ThemeCandidateTransitionPage:
    items: tuple[ThemeCandidateTransitionRecord, ...]
    next_cursor: int | None


_CANDIDATE_COLUMNS = """
candidate.candidate_id::text,
candidate.rule_id::text,
rule.theme_id::text,
theme.theme_slug,
theme.theme_name,
rule.source_id::text,
source.source_name,
source.provider_dataset_id,
candidate.source_entity_key,
candidate.feature_id,
core.feature_uuid::text,
core.name AS feature_name,
core.kind AS feature_kind,
core.category AS feature_category,
CASE core.kind
  WHEN 'place' THEN COALESCE(to_jsonb(place), '{}'::jsonb)
  WHEN 'event' THEN COALESCE(to_jsonb(event), '{}'::jsonb)
  -- valid_during is an internal generated projection, not part of the
  -- NoticeDetail/admin response contract.  Keep timestamptz values in the
  -- same KST representation as the public feature projection so the
  -- candidate representation ETag is independent of the session timezone.
  WHEN 'notice' THEN CASE WHEN notice.feature_id IS NULL THEN '{}'::jsonb ELSE
    jsonb_set(
      jsonb_set(
        to_jsonb(notice) - 'valid_during',
        '{valid_start_time}',
        to_jsonb(to_char(
          notice.valid_start_time AT TIME ZONE 'Asia/Seoul',
          CASE WHEN EXTRACT(microsecond FROM notice.valid_start_time)::bigint % 1000000 = 0
               THEN 'YYYY-MM-DD"T"HH24:MI:SS"+09:00"'
               ELSE 'YYYY-MM-DD"T"HH24:MI:SS.US"+09:00"' END
        ))
      ),
      '{valid_end_time}',
      to_jsonb(to_char(
        notice.valid_end_time AT TIME ZONE 'Asia/Seoul',
        CASE WHEN EXTRACT(microsecond FROM notice.valid_end_time)::bigint % 1000000 = 0
             THEN 'YYYY-MM-DD"T"HH24:MI:SS"+09:00"'
             ELSE 'YYYY-MM-DD"T"HH24:MI:SS.US"+09:00"' END
      ))
    )
  END
  WHEN 'route' THEN COALESCE(to_jsonb(route), '{}'::jsonb)
  WHEN 'area' THEN COALESCE(to_jsonb(area_row), '{}'::jsonb)
  ELSE '{}'::jsonb
END AS feature_detail,
core.lifecycle_state,
core.publication_state,
core.quality_state,
candidate.source_record_key,
candidate.source_record_hash,
candidate.rule_row_revision,
candidate.rule_input_hash,
candidate.candidate_input_hash,
candidate.review_state,
candidate.eligibility_present,
candidate.disposition,
candidate.rank_score::text,
candidate.proposal_title,
candidate.proposal_summary,
candidate.match_evidence,
candidate.row_revision,
core.row_revision AS feature_row_revision,
candidate.created_at,
candidate.updated_at
"""

_CANDIDATE_FROM = """
FROM feature.theme_feature_candidates AS candidate
JOIN feature.curated_source_rules AS rule ON rule.rule_id = candidate.rule_id
JOIN feature.curated_themes AS theme ON theme.theme_id = rule.theme_id
JOIN feature.curated_sources AS source ON source.source_id = rule.source_id
JOIN feature.features AS core ON core.feature_id = candidate.feature_id
LEFT JOIN feature.feature_places AS place ON place.feature_id = core.feature_id
LEFT JOIN feature.feature_events AS event ON event.feature_id = core.feature_id
LEFT JOIN feature.feature_notices AS notice ON notice.feature_id = core.feature_id
LEFT JOIN feature.feature_routes AS route ON route.feature_id = core.feature_id
LEFT JOIN feature.feature_areas AS area_row ON area_row.feature_id = core.feature_id
"""

_LIST_SQL = f"""
SELECT {_CANDIDATE_COLUMNS}
{_CANDIDATE_FROM}
WHERE candidate.disposition = 'active'
  AND (:rule_id IS NULL OR candidate.rule_id = CAST(:rule_id AS uuid))
  AND (:theme_id IS NULL OR rule.theme_id = CAST(:theme_id AS uuid))
  AND (:source_id IS NULL OR rule.source_id = CAST(:source_id AS uuid))
  AND (:review_state IS NULL OR candidate.review_state = :review_state)
  AND (:eligibility_present IS NULL
       OR candidate.eligibility_present = :eligibility_present)
  AND (:feature_id IS NULL OR candidate.feature_id = :feature_id)
  AND (
    :cursor_updated_at IS NULL
    OR (candidate.updated_at, candidate.candidate_id)
       < (CAST(:cursor_updated_at AS timestamptz), CAST(:cursor_candidate_id AS uuid))
  )
ORDER BY candidate.updated_at DESC, candidate.candidate_id DESC
LIMIT :limit_plus_one
"""

_GET_SQL = f"""
SELECT {_CANDIDATE_COLUMNS}
{_CANDIDATE_FROM}
WHERE candidate.candidate_id = CAST(:candidate_id AS uuid)
  AND candidate.disposition = 'active'
"""

_TRANSITIONS_SQL = """
SELECT transition_id, candidate_id::text, transition_kind,
       from_review_state, to_review_state,
       from_eligibility_present, to_eligibility_present,
       candidate_row_revision, generation_id::text, command_id,
       actor, reason_code, causation_ref, occurred_at
FROM feature.theme_feature_candidate_transitions
WHERE candidate_id = CAST(:candidate_id AS uuid)
  AND (:before_transition_id IS NULL OR transition_id < :before_transition_id)
ORDER BY transition_id DESC
LIMIT :limit_plus_one
"""


def _candidate(row: Any) -> ThemeCandidateRecord:
    return ThemeCandidateRecord(**dict(row._mapping))


def _encode_cursor(updated_at: datetime, candidate_id: str) -> str:
    payload = json.dumps(
        [updated_at.isoformat(), candidate_id], separators=(",", ":")
    ).encode()
    return base64.urlsafe_b64encode(payload).decode().rstrip("=")


def _decode_cursor(cursor: str | None) -> tuple[str | None, str | None]:
    if cursor is None:
        return None, None
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        value = json.loads(base64.urlsafe_b64decode(padded).decode())
        if not isinstance(value, list) or len(value) != 2:
            raise ValueError
        UUID(str(value[1]))
        datetime.fromisoformat(str(value[0]))
    except (binascii.Error, ValueError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("candidate cursor가 올바르지 않습니다.") from exc
    return str(value[0]), str(value[1])


async def list_theme_candidates(
    session: AsyncSession,
    *,
    rule_id: str | None,
    theme_id: str | None,
    source_id: str | None,
    review_state: ReviewState | None,
    eligibility_present: bool | None,
    feature_id: str | None,
    limit: int,
    cursor: str | None,
) -> ThemeCandidatePage:
    cursor_updated_at, cursor_candidate_id = _decode_cursor(cursor)
    rows = (
        await session.execute(
            text(_LIST_SQL),
            {
                "cursor_candidate_id": cursor_candidate_id,
                "cursor_updated_at": cursor_updated_at,
                "eligibility_present": eligibility_present,
                "feature_id": feature_id,
                "limit_plus_one": limit + 1,
                "review_state": review_state,
                "rule_id": rule_id,
                "source_id": source_id,
                "theme_id": theme_id,
            },
        )
    ).all()
    page = rows[:limit]
    next_cursor = None
    if len(rows) > limit and page:
        next_cursor = _encode_cursor(page[-1].updated_at, str(page[-1].candidate_id))
    return ThemeCandidatePage(tuple(_candidate(row) for row in page), next_cursor)


async def get_theme_candidate(
    session: AsyncSession, *, candidate_id: str
) -> ThemeCandidateRecord | None:
    row = (
        await session.execute(text(_GET_SQL), {"candidate_id": candidate_id})
    ).one_or_none()
    return None if row is None else _candidate(row)


async def list_theme_candidate_transitions(
    session: AsyncSession,
    *,
    candidate_id: str,
    before_transition_id: int | None,
    limit: int,
) -> ThemeCandidateTransitionPage:
    rows = (
        await session.execute(
            text(_TRANSITIONS_SQL),
            {
                "before_transition_id": before_transition_id,
                "candidate_id": candidate_id,
                "limit_plus_one": limit + 1,
            },
        )
    ).all()
    page = rows[:limit]
    records = tuple(
        ThemeCandidateTransitionRecord(**dict(row._mapping)) for row in page
    )
    next_cursor = records[-1].transition_id if len(rows) > limit and records else None
    return ThemeCandidateTransitionPage(records, next_cursor)


async def reject_theme_candidate(
    session: AsyncSession,
    *,
    candidate_id: str,
    expected_revision: int,
    command_id: int,
    reason_code: str,
    principal: str,
) -> tuple[str, int, int]:
    row = (
        await session.execute(
            text(
                """
                CALL feature.reject_theme_feature_candidate(
                  CAST(:candidate_id AS uuid), :expected_revision, :command_id,
                  :reason_code, :principal, NULL, NULL, NULL
                )
                """
            ),
            {
                "candidate_id": candidate_id,
                "command_id": command_id,
                "expected_revision": expected_revision,
                "principal": principal,
                "reason_code": reason_code,
            },
        )
    ).one()
    return str(row.o_candidate_id), int(row.o_candidate_revision), int(row.o_transition_id)


async def promote_theme_candidate(
    session: AsyncSession,
    *,
    candidate_id: str,
    collection_id: str,
    external_item_id: str,
    external_component_id: str,
    place_name: str,
    address_hint: str | None,
    item_title: str | None,
    item_summary: str | None,
    sort_order: int,
    curation_relation: str,
    reuse_policy: str,
    item_status: str,
    expected_candidate_revision: int,
    expected_collection_revision: int,
    expected_item_revision: int | None,
    command_id: int,
    reason_code: str,
    principal: str,
) -> tuple[str, int, str, int, int]:
    row = (
        await session.execute(
            text(
                """
                CALL feature.promote_theme_feature_candidate(
                  CAST(:candidate_id AS uuid), CAST(:collection_id AS uuid),
                  :external_item_id, :external_component_id, :place_name,
                  :address_hint, :item_title, :item_summary, :sort_order,
                  :curation_relation, :reuse_policy, :item_status,
                  :expected_candidate_revision, :expected_collection_revision,
                  :expected_item_revision, :command_id, :reason_code, :principal,
                  NULL, NULL, NULL, NULL, NULL
                )
                """
            ),
            {
                "address_hint": address_hint,
                "candidate_id": candidate_id,
                "collection_id": collection_id,
                "command_id": command_id,
                "curation_relation": curation_relation,
                "expected_candidate_revision": expected_candidate_revision,
                "expected_collection_revision": expected_collection_revision,
                "expected_item_revision": expected_item_revision,
                "external_component_id": external_component_id,
                "external_item_id": external_item_id,
                "item_status": item_status,
                "item_summary": item_summary,
                "item_title": item_title,
                "place_name": place_name,
                "principal": principal,
                "reason_code": reason_code,
                "reuse_policy": reuse_policy,
                "sort_order": sort_order,
            },
        )
    ).one()
    return (
        str(row.o_candidate_id),
        int(row.o_candidate_revision),
        str(row.o_curation_item_id),
        int(row.o_curation_item_revision),
        int(row.o_transition_id),
    )
