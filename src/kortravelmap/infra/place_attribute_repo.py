"""``kortravelmap.infra.place_attribute_repo`` — 장소 속성 catalog·붙임 판정 읽기(ADR-121).

설계 정본은 ``docs/architecture/place-theme-attributes.md`` §4.1·§7이다. 속성은 저장된
상태가 아니라 Feature의 ``primary``/``enrichment`` source link에서 유도한다 — 목록·검색·
주변 조회의 필터와 ``attribute_codes``는 ``feature_repo.place_attribute_filter_sql``·
``place_attribute_codes_sql`` 두 fragment가 맡고, 이 모듈은 그 밖의 읽기만 둔다.

- 공개 catalog(``feature.place_attributes``) — ``GET /v1/place-attributes``와 요청 코드 검증.
- Feature 하나의 속성(라벨·묶음 포함) — 공개 상세 응답과 상세 ETag.
- 붙임 판정(``provider_sync.theme_attach_decisions``) — 관리자 읽기 전용 목록.

쓰기는 없다. 판정은 ``theme_attach_repo``가 적재 중에 쓴다.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any, Final, Literal

from sqlalchemy import text

from kortravelmap.infra.feature_repo import PLACE_ATTRIBUTE_LINK_ROLES

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

__all__ = [
    "THEME_ATTACH_DECISION_STATES",
    "PlaceAttribute",
    "ThemeAttachDecision",
    "ThemeAttachDecisionCursorError",
    "ThemeAttachDecisionPage",
    "ThemeAttachDecisionState",
    "list_feature_place_attributes",
    "list_place_attributes",
    "list_theme_attach_decisions",
    "place_attribute_digest",
]

ThemeAttachDecisionState = Literal[
    "owner", "matched", "sticky", "redirected", "created", "ambiguous", "unresolved"
]
#: migration 446 ``ck_theme_attach_decisions_state``와 같은 집합.
THEME_ATTACH_DECISION_STATES: Final[tuple[str, ...]] = (
    "owner",
    "matched",
    "sticky",
    "redirected",
    "created",
    "ambiguous",
    "unresolved",
)

_ROLES_SQL: Final[str] = ", ".join(f"'{role}'" for role in PLACE_ATTRIBUTE_LINK_ROLES)


@dataclass(frozen=True, slots=True)
class PlaceAttribute:
    """장소 속성 catalog 1건."""

    code: str
    label: str
    group: str
    visibility: str
    sort_order: int

    @property
    def is_public(self) -> bool:
        return self.visibility == "public"


_LIST_PLACE_ATTRIBUTES_SQL: Final[str] = """
SELECT attribute_code, label_ko, attribute_group, visibility, sort_order
FROM feature.place_attributes
WHERE (CAST(:public_only AS boolean) IS NOT TRUE OR visibility = 'public')
ORDER BY sort_order ASC, attribute_code ASC
"""

# Feature 하나의 속성 — 필터·목록 fragment와 같은 유도 규칙(link 역할·dataset 묶음)이다.
_LIST_FEATURE_PLACE_ATTRIBUTES_SQL: Final[str] = f"""
SELECT DISTINCT
    catalog.attribute_code,
    catalog.label_ko,
    catalog.attribute_group,
    catalog.visibility,
    catalog.sort_order
FROM provider_sync.source_links AS attr_link
JOIN provider_sync.source_entities AS attr_entity
  ON attr_entity.source_entity_key = attr_link.source_entity_key
JOIN feature.dataset_place_attributes AS attr_map
  ON attr_map.provider_dataset_id = attr_entity.provider_dataset_id
 AND attr_map.source_entity_type = attr_entity.source_entity_type
JOIN feature.place_attributes AS catalog
  ON catalog.attribute_code = attr_map.attribute_code
WHERE attr_link.feature_id = CAST(:feature_id AS uuid)
  AND attr_link.source_role IN ({_ROLES_SQL})
  AND (CAST(:public_only AS boolean) IS NOT TRUE OR catalog.visibility = 'public')
ORDER BY catalog.sort_order ASC, catalog.attribute_code ASC
"""


def _place_attribute(row: Any) -> PlaceAttribute:
    return PlaceAttribute(
        code=str(row["attribute_code"]),
        label=str(row["label_ko"]),
        group=str(row["attribute_group"]),
        visibility=str(row["visibility"]),
        sort_order=int(row["sort_order"]),
    )


async def list_place_attributes(
    session: AsyncSession, *, public_only: bool = False
) -> tuple[PlaceAttribute, ...]:
    """속성 catalog 전체(``sort_order``, 코드 순). ``public_only``면 공개 코드만."""
    rows = (
        await session.execute(text(_LIST_PLACE_ATTRIBUTES_SQL), {"public_only": public_only})
    ).mappings().all()
    return tuple(_place_attribute(row) for row in rows)


async def list_feature_place_attributes(
    session: AsyncSession, feature_id: str, *, public_only: bool = True
) -> tuple[PlaceAttribute, ...]:
    """Feature 하나가 가진 속성(``sort_order``, 코드 순). 공개 상세는 ``public_only``다."""
    rows = (
        await session.execute(
            text(_LIST_FEATURE_PLACE_ATTRIBUTES_SQL),
            {"feature_id": str(feature_id), "public_only": public_only},
        )
    ).mappings().all()
    return tuple(_place_attribute(row) for row in rows)


# ─── 붙임 판정 (관리자 읽기) ──────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class ThemeAttachDecision:
    """MCST 행 하나의 붙임 판정(근거 보관용 — link가 정본)."""

    provider_dataset_id: int
    provider: str
    dataset_key: str
    natural_key: str
    state: str
    target_feature_id: str | None
    rule_version: str
    evidence: dict[str, Any]
    decided_at: datetime


@dataclass(frozen=True, slots=True)
class ThemeAttachDecisionPage:
    items: tuple[ThemeAttachDecision, ...]
    next_cursor: str | None


#: keyset은 PK ``(provider_dataset_id, natural_key)`` 오름차순이다.
_LIST_THEME_ATTACH_DECISIONS_SQL: Final[str] = """
SELECT
    decision.provider_dataset_id,
    dataset.provider,
    dataset.dataset_key,
    decision.natural_key,
    decision.state,
    CAST(decision.target_feature_id AS text) AS target_feature_id,
    decision.rule_version,
    decision.evidence,
    decision.decided_at
FROM provider_sync.theme_attach_decisions AS decision
JOIN provider_sync.provider_datasets AS dataset
  ON dataset.provider_dataset_id = decision.provider_dataset_id
WHERE (CAST(:dataset_key AS text) IS NULL OR dataset.dataset_key = CAST(:dataset_key AS text))
  AND (CAST(:state AS text) IS NULL OR decision.state = CAST(:state AS text))
  AND (
    CAST(:cursor_dataset_id AS bigint) IS NULL
    OR (decision.provider_dataset_id, decision.natural_key) > (
        CAST(:cursor_dataset_id AS bigint),
        CAST(:cursor_natural_key AS text)
    )
  )
ORDER BY decision.provider_dataset_id ASC, decision.natural_key ASC
LIMIT :limit_plus_one
"""

_DECISION_CURSOR_KIND: Final[str] = "theme_attach_decisions"


class ThemeAttachDecisionCursorError(ValueError):
    """판정 목록 cursor 형식 오류."""


_BIGINT_MAX: Final[int] = 2**63 - 1


def _encode_decision_cursor(item: ThemeAttachDecision) -> str:
    raw = json.dumps(
        {
            "kind": _DECISION_CURSOR_KIND,
            "provider_dataset_id": item.provider_dataset_id,
            "natural_key": item.natural_key,
        },
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decision_cursor_params(cursor: str | None) -> dict[str, Any]:
    if cursor is None:
        return {"cursor_dataset_id": None, "cursor_natural_key": None}
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded).decode("utf-8"))
    except (ValueError, binascii.Error, UnicodeDecodeError) as exc:
        raise ThemeAttachDecisionCursorError("invalid theme attach decision cursor") from exc
    if not isinstance(payload, dict) or payload.get("kind") != _DECISION_CURSOR_KIND:
        raise ThemeAttachDecisionCursorError("invalid theme attach decision cursor")
    dataset_id = payload.get("provider_dataset_id")
    natural_key = payload.get("natural_key")
    if (
        type(dataset_id) is not int
        or not 0 < dataset_id <= _BIGINT_MAX
        or not isinstance(natural_key, str)
    ):
        raise ThemeAttachDecisionCursorError("invalid theme attach decision cursor")
    return {"cursor_dataset_id": dataset_id, "cursor_natural_key": natural_key}


def _json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, str):
        value = json.loads(value)
    return dict(value) if isinstance(value, dict) else {}


def _decision(row: Any) -> ThemeAttachDecision:
    target = row["target_feature_id"]
    return ThemeAttachDecision(
        provider_dataset_id=int(row["provider_dataset_id"]),
        provider=str(row["provider"]),
        dataset_key=str(row["dataset_key"]),
        natural_key=str(row["natural_key"]),
        state=str(row["state"]),
        target_feature_id=str(target) if target is not None else None,
        rule_version=str(row["rule_version"]),
        evidence=_json_object(row["evidence"]),
        decided_at=row["decided_at"],
    )


async def list_theme_attach_decisions(
    session: AsyncSession,
    *,
    dataset_key: str | None = None,
    state: str | None = None,
    page_size: int = 50,
    cursor: str | None = None,
) -> ThemeAttachDecisionPage:
    """붙임 판정을 PK keyset으로 읽는다. ``dataset_key``·``state``는 선택 필터다."""
    if page_size <= 0:
        raise ValueError("page_size must be greater than 0")
    if state is not None and state not in THEME_ATTACH_DECISION_STATES:
        raise ValueError("unknown theme attach decision state")
    effective_limit = min(page_size, 200)
    rows = (
        await session.execute(
            text(_LIST_THEME_ATTACH_DECISIONS_SQL),
            {
                "dataset_key": dataset_key,
                "state": state,
                "limit_plus_one": effective_limit + 1,
                **_decision_cursor_params(cursor),
            },
        )
    ).mappings().all()
    items = tuple(_decision(row) for row in rows[:effective_limit])
    next_cursor = (
        _encode_decision_cursor(items[-1]) if len(rows) > effective_limit and items else None
    )
    return ThemeAttachDecisionPage(items=items, next_cursor=next_cursor)


def place_attribute_digest(attributes: Sequence[PlaceAttribute]) -> str | None:
    """상세 응답 ``attributes``의 짧은 digest(상세 ETag용). 비면 ``None``.

    응답에 실리는 것 전부(코드·라벨·묶음·순서)를 접는다 — 라벨이나 순서만 바뀌어도 본문이
    바뀌므로 strong ETag도 바뀌어야 한다(적대 리뷰).
    """
    if not attributes:
        return None
    rows = "
".join(
        f"{item.code}	{item.label}	{item.group}	{item.sort_order}"
        for item in sorted(attributes, key=lambda item: (item.sort_order, item.code))
    )
    return hashlib.sha256(rows.encode("utf-8")).hexdigest()[:16]
