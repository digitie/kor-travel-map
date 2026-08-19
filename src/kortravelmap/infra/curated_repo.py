"""``feature.curated_*`` repository (T-223c-1).

테마형 큐레이션은 ``feature.features``를 복제하지 않는 overlay다. 본 모듈은
raw SQL만 제공하고, HTTP envelope/DTO는 admin 패키지 라우터에서 담당한다.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Final, Literal

from sqlalchemy import text

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

__all__ = [
    "CuratedSource",
    "CuratedSourceRule",
    "CuratedTheme",
    "create_curated_source_rule_command",
    "get_curated_source_rule",
    "list_curated_source_rules",
    "list_curated_sources",
    "list_curated_themes",
    "patch_curated_source_rule_command",
    "archive_curated_source_rule_command",
]

CursorKind = Literal["curated_features"]

_CURATION_STATUSES: Final[frozenset[str]] = frozenset(
    {"candidate", "curated", "rejected", "archived"}
)
_SELECTION_ORIGINS: Final[frozenset[str]] = frozenset(
    {"source_rule", "admin", "external_api"}
)
_CURATION_RELATIONS: Final[frozenset[str]] = frozenset(
    {
        "primary_stop",
        "food_stop",
        "cafe_stop",
        "bookstore_stop",
        "nearby_option",
        "accessibility_support",
        "pet_support",
        "family_support",
        "theme_area_anchor",
    }
)
_REUSE_POLICIES: Final[frozenset[str]] = frozenset(
    {"allowed", "blocked", "manual_review"}
)
_THEME_VISIBILITIES: Final[frozenset[str]] = frozenset(
    {"admin_only", "public"}
)
_SOURCE_KINDS: Final[frozenset[str]] = frozenset(
    {"openapi", "filedata", "standard", "internal", "manual"}
)
_UPDATE_CYCLES: Final[frozenset[str]] = frozenset(
    {"realtime", "daily", "weekly", "monthly", "annual", "one_time", "unknown"}
)
_PROVIDER_STATUSES: Final[frozenset[str]] = frozenset(
    {"implemented", "provider_needed", "manual_only", "deprecated"}
)
_RULE_ACTIONS: Final[frozenset[str]] = frozenset(
    {"candidate", "curated", "ignore"}
)
_TYPED_RULE_ACTIONS: Final[frozenset[str]] = frozenset({"candidate", "ignore"})
_MAX_PAGE_SIZE: Final[int] = 200
_MAX_LIST_LIMIT: Final[int] = 500
_CONCIERGE_PROVIDER: Final[str] = "kor-travel-concierge-youtube"
_CONCIERGE_DATASET_KEY: Final[str] = "youtube_place_candidates"
_PROVIDER_TITLE_SOURCE_PROVIDERS: Final[frozenset[str]] = frozenset(
    {
        "data.go.kr-standard",
        "python-airkorea-api",
        "python-datagokr-api",
        "python-kasi-api",
        "python-khoa-api",
        "python-kma-api",
        "python-knps-api",
        "python-krairport-api",
        "python-krex-api",
        "python-krforest-api",
        "python-krheritage-api",
        "python-mcst-api",
        "python-mois-api",
        "python-opinet-api",
        "python-visitkorea-api",
    }
)


@dataclass(frozen=True)
class CuratedTheme:
    """``feature.curated_themes`` projection."""

    theme_id: str
    theme_slug: str
    theme_name: str
    theme_description: str
    theme_group: str
    visibility: str
    metadata: dict[str, Any]
    created_at: datetime
    updated_at: datetime
    row_revision: int = 1
    archived_at: datetime | None = None
    owner_kind: str | None = None
    owner_provider_dataset_id: int | None = None


@dataclass(frozen=True)
class CuratedSource:
    """``feature.curated_sources`` projection."""

    source_id: str
    provider_dataset_id: int
    provider: str
    dataset_key: str
    source_name: str
    source_url: str | None
    source_kind: str
    license: str | None
    update_cycle: str
    last_source_modified_at: date | None
    last_checked_at: datetime | None
    next_expected_at: date | None
    row_count: int | None
    freshness_note: str | None
    provider_status: str
    metadata: dict[str, Any]
    created_at: datetime
    updated_at: datetime
    row_revision: int = 1
    observation_revision: int = 1
    archived_at: datetime | None = None


@dataclass(frozen=True)
class CuratedSourceRule:
    """``feature.curated_source_rules`` projection."""

    rule_id: str
    theme_id: str
    theme_slug: str
    source_id: str
    provider_dataset_id: int
    provider: str
    dataset_key: str
    place_kind: str | None
    category: str | None
    region_scope: dict[str, Any]
    detail_selector: dict[str, Any] | None
    default_action: str
    priority: int
    enabled: bool
    metadata: dict[str, Any]
    created_at: datetime
    updated_at: datetime
    row_revision: int = 1
    archived_at: datetime | None = None
    owner_kind: str | None = None
    owner_provider_dataset_id: int | None = None







_THEME_COLUMNS: Final[str] = (
    "theme_id::text AS theme_id, theme_slug, theme_name, theme_description, "
    "theme_group, visibility, metadata, created_at, updated_at, row_revision, "
    "archived_at, owner_kind, owner_provider_dataset_id"
)
_SOURCE_COLUMNS: Final[str] = (
    "s.source_id::text AS source_id, s.provider_dataset_id, pd.provider, pd.dataset_key, "
    "s.source_name, s.source_url, s.source_kind, s.license, s.update_cycle, "
    "s.last_source_modified_at, s.last_checked_at, s.next_expected_at, s.row_count, "
    "s.freshness_note, s.provider_status, s.metadata, s.created_at, s.updated_at, "
    "s.row_revision, s.observation_revision, s.archived_at"
)
_RULE_COLUMNS: Final[str] = (
    "r.rule_id::text AS rule_id, r.theme_id::text AS theme_id, t.theme_slug, "
    "r.source_id::text AS source_id, s.provider_dataset_id, pd.provider, pd.dataset_key, "
    "r.place_kind, "
    "r.category, r.region_scope, r.detail_selector, r.default_action, "
    "r.priority, r.enabled, r.metadata, r.created_at, r.updated_at, "
    "r.row_revision, r.archived_at, r.owner_kind, r.owner_provider_dataset_id"
)
_FEATURE_COLUMNS: Final[str] = """
    cf.curated_feature_id::text AS curated_feature_id,
    cf.theme_id::text AS theme_id,
    t.theme_slug,
    t.theme_name,
    t.theme_group,
    cf.feature_id,
    CAST(f.feature_uuid AS text) AS feature_uuid,
    f.name AS feature_name,
    f.category AS feature_category,
    f.kind AS feature_kind,
    x_extension.ST_X(f.coord) AS lon,
    x_extension.ST_Y(f.coord) AS lat,
    f.sido_code,
    f.sigungu_code,
    f.legal_dong_code,
    f.address,
    typed.detail,
    cf.source_id::text AS source_id,
    s.provider_dataset_id,
    pd.provider,
    pd.dataset_key,
    s.source_name,
    s.source_url,
    cf.source_record_key,
    cf.curation_status,
    cf.selection_origin,
    cf.selected_by,
    cf.selected_at,
    cf.rejected_by,
    cf.rejected_at,
    cf.rejection_reason,
    cf.rank_score,
    cf.display_title,
    cf.display_summary,
    cf.curation_relation,
    cf.reuse_policy,
    cf.content_version,
    cf.metadata,
    cf.created_at,
    cf.updated_at,
    cf.archived_at
"""
# 공개 read는 ADR-067 단일 공개 projection(``feature.public_features``)만 조인해
# 비공개(draft/broken/hidden/inactive/soft-deleted) feature의 큐레이션 노출을 막는다
# (T-VN-04, F-1). admin read는 기존대로 base table을 조인해 전 상태를 본다 —
# legacy overlay 상태와 무관하게 공개 read가 새지 않는다.
# admin reader는 core와 모든 typed subtype을 직접 LEFT JOIN해 detail을 조립한다.
# public reader도 같은 ``typed`` alias를 제공해 두 select의 projection을 공유한다.



_LIST_THEMES_SQL: Final[str] = f"""
SELECT {_THEME_COLUMNS}
FROM feature.curated_themes
WHERE (CAST(:include_archived AS boolean) OR archived_at IS NULL)
  AND (CAST(:visibility AS text) IS NULL OR visibility = CAST(:visibility AS text))
  AND (CAST(:theme_group AS text) IS NULL OR theme_group = CAST(:theme_group AS text))
ORDER BY theme_group, theme_slug
LIMIT :limit
"""

_LIST_SOURCES_SQL: Final[str] = f"""
SELECT {_SOURCE_COLUMNS}
FROM feature.curated_sources AS s
JOIN provider_sync.provider_datasets AS pd
  ON pd.provider_dataset_id = s.provider_dataset_id
WHERE (
    CAST(:include_archived AS boolean) OR s.archived_at IS NULL
)
  AND (
    CAST(:provider_dataset_id AS bigint) IS NULL
    OR s.provider_dataset_id = CAST(:provider_dataset_id AS bigint)
)
  AND (
    CAST(:provider_status AS text) IS NULL
    OR provider_status = CAST(:provider_status AS text)
  )
ORDER BY pd.provider, pd.dataset_key
LIMIT :limit
"""

_GET_SOURCE_SQL: Final[str] = f"""
SELECT {_SOURCE_COLUMNS}
FROM feature.curated_sources AS s
JOIN provider_sync.provider_datasets AS pd
  ON pd.provider_dataset_id = s.provider_dataset_id
WHERE s.source_id = CAST(:source_id AS uuid)
"""

_LIST_RULES_SQL: Final[str] = f"""
SELECT {_RULE_COLUMNS}
FROM feature.curated_source_rules AS r
JOIN feature.curated_themes AS t ON t.theme_id = r.theme_id
JOIN feature.curated_sources AS s ON s.source_id = r.source_id
JOIN provider_sync.provider_datasets AS pd
  ON pd.provider_dataset_id = s.provider_dataset_id
WHERE (CAST(:theme_id AS uuid) IS NULL OR r.theme_id = CAST(:theme_id AS uuid))
  AND (
    CAST(:include_archived AS boolean)
    OR (r.archived_at IS NULL AND t.archived_at IS NULL AND s.archived_at IS NULL)
  )
  AND (
    CAST(:theme_slug AS text) IS NULL
    OR t.theme_slug = CAST(:theme_slug AS text)
  )
  AND (CAST(:source_id AS uuid) IS NULL OR r.source_id = CAST(:source_id AS uuid))
  AND (
    CAST(:provider_dataset_id AS bigint) IS NULL
    OR s.provider_dataset_id = CAST(:provider_dataset_id AS bigint)
  )
  AND (CAST(:enabled AS boolean) IS NULL OR r.enabled = CAST(:enabled AS boolean))
ORDER BY t.theme_slug, pd.provider, pd.dataset_key, r.priority DESC, r.rule_id
LIMIT :limit
"""

# 필터(커서 제외) — 일반/dedup 두 변형이 공유한다.

# keyset 커서 — 일반 변형(원본 cf 컬럼, uuid 비교).



# 물리 feature당 1행 dedup 변형(지도 경로). 같은 feature가 여러 테마로 큐레이션되면
# `/v1/admin/features/curated`가 같은 feature_id를 테마 수만큼 반환한다(부분 UNIQUE 인덱스가
# (theme_id, feature_id)만 강제 → cross-theme 중복 허용). 지도는 물리 feature당 마커 1개여야
# 하므로, feature_id별로 rank_score 최고(동점 시 최신 updated_at) 큐레이션 1건만 남긴다.
# DISTINCT ON은 서브쿼리 안에서 (feature_id, rank_score DESC …)로 수행하고, 바깥에서 keyset
# 커서 정렬을 적용해 페이지네이션 정합성을 유지한다(curated_feature_id는 서브쿼리에서 text로
# alias돼 있어 커서 비교도 text — 표준 uuid는 text 정렬이 uuid 정렬과 일치).
# 관리자 per-curation 목록은 이 변형을 쓰지 않아 모든 큐레이션을 그대로 본다.






def _json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        loaded = json.loads(value)
        if isinstance(loaded, dict):
            return loaded
    return {}


def _json_dumps(value: Mapping[str, Any] | None) -> str:
    return json.dumps(
        dict(value) if value else {},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _decimal_to_float(value: Any) -> float:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, int | float):
        return float(value)
    return 0.0


def _text(value: Any) -> str | None:
    if value is None:
        return None
    text_value = str(value).strip()
    return text_value or None


def _validate_choice(value: str, allowed: frozenset[str], field_name: str) -> None:
    if value not in allowed:
        raise ValueError(f"{field_name} must be one of {sorted(allowed)}")


def _safe_limit(limit: int, max_limit: int = _MAX_LIST_LIMIT) -> int:
    return max(1, min(limit, max_limit))


def _q_pattern(q: str | None) -> str | None:
    stripped = _text(q)
    return f"%{stripped}%" if stripped else None










def _theme(row: Any) -> CuratedTheme:
    return CuratedTheme(
        theme_id=str(row["theme_id"]),
        theme_slug=str(row["theme_slug"]),
        theme_name=str(row["theme_name"]),
        theme_description=str(row["theme_description"]),
        theme_group=str(row["theme_group"]),
        visibility=str(row["visibility"]),
        metadata=_json_object(row["metadata"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        row_revision=int(row["row_revision"]),
        archived_at=row["archived_at"],
        owner_kind=_text(row["owner_kind"]),
        owner_provider_dataset_id=(
            int(row["owner_provider_dataset_id"])
            if row["owner_provider_dataset_id"] is not None
            else None
        ),
    )


def _source(row: Any) -> CuratedSource:
    return CuratedSource(
        source_id=str(row["source_id"]),
        provider_dataset_id=int(row["provider_dataset_id"]),
        provider=str(row["provider"]),
        dataset_key=str(row["dataset_key"]),
        source_name=str(row["source_name"]),
        source_url=row["source_url"],
        source_kind=str(row["source_kind"]),
        license=row["license"],
        update_cycle=str(row["update_cycle"]),
        last_source_modified_at=row["last_source_modified_at"],
        last_checked_at=row["last_checked_at"],
        next_expected_at=row["next_expected_at"],
        row_count=row["row_count"],
        freshness_note=row["freshness_note"],
        provider_status=str(row["provider_status"]),
        metadata=_json_object(row["metadata"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        row_revision=int(row["row_revision"]),
        observation_revision=int(row["observation_revision"]),
        archived_at=row["archived_at"],
    )


def _rule(row: Any) -> CuratedSourceRule:
    return CuratedSourceRule(
        rule_id=str(row["rule_id"]),
        theme_id=str(row["theme_id"]),
        theme_slug=str(row["theme_slug"]),
        source_id=str(row["source_id"]),
        provider_dataset_id=int(row["provider_dataset_id"]),
        provider=str(row["provider"]),
        dataset_key=str(row["dataset_key"]),
        place_kind=row["place_kind"],
        category=row["category"],
        region_scope=_json_object(row["region_scope"]),
        detail_selector=(
            _json_object(row["detail_selector"])
            if row["detail_selector"] is not None
            else None
        ),
        default_action=str(row["default_action"]),
        priority=int(row["priority"]),
        enabled=bool(row["enabled"]),
        metadata=_json_object(row["metadata"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        row_revision=int(row.get("row_revision", 1)),
        archived_at=row.get("archived_at"),
        owner_kind=_text(row.get("owner_kind")),
        owner_provider_dataset_id=(
            int(row["owner_provider_dataset_id"])
            if row.get("owner_provider_dataset_id") is not None
            else None
        ),
    )



















async def list_curated_themes(
    session: AsyncSession,
    *,
    visibility: str | None = None,
    theme_group: str | None = None,
    include_archived: bool = False,
    limit: int = 200,
) -> tuple[CuratedTheme, ...]:
    """curated theme 목록을 조회한다."""

    if visibility is not None:
        _validate_choice(visibility, _THEME_VISIBILITIES, "visibility")
    rows = (
        await session.execute(
            text(_LIST_THEMES_SQL),
            {
                "visibility": visibility,
                "theme_group": theme_group,
                "include_archived": include_archived,
                "limit": _safe_limit(limit),
            },
        )
    ).mappings().all()
    return tuple(_theme(row) for row in rows)


async def get_curated_theme(
    session: AsyncSession,
    *,
    theme_id: str,
) -> CuratedTheme | None:
    """retained theme 단건을 revision/owner 축과 함께 조회한다."""

    row = (
        await session.execute(
            text(
                f"""
                SELECT {_THEME_COLUMNS}
                FROM feature.curated_themes
                WHERE theme_id = CAST(:theme_id AS uuid)
                """
            ),
            {"theme_id": theme_id},
        )
    ).mappings().first()
    return _theme(row) if row is not None else None


async def list_curated_sources(
    session: AsyncSession,
    *,
    provider_dataset_id: int | None = None,
    provider_status: str | None = None,
    include_archived: bool = False,
    limit: int = 200,
) -> tuple[CuratedSource, ...]:
    """curated source metadata 목록을 조회한다."""

    if provider_status is not None:
        _validate_choice(provider_status, _PROVIDER_STATUSES, "provider_status")
    rows = (
        await session.execute(
            text(_LIST_SOURCES_SQL),
            {
                "provider_dataset_id": provider_dataset_id,
                "provider_status": provider_status,
                "include_archived": include_archived,
                "limit": _safe_limit(limit),
            },
        )
    ).mappings().all()
    return tuple(_source(row) for row in rows)


async def get_curated_source(
    session: AsyncSession, *, source_id: str
) -> CuratedSource | None:
    """retained source 단건을 operator/observation revision과 함께 조회한다."""

    row = (
        await session.execute(text(_GET_SOURCE_SQL), {"source_id": source_id})
    ).mappings().first()
    return _source(row) if row is not None else None


async def list_curated_source_rules(
    session: AsyncSession,
    *,
    theme_id: str | None = None,
    theme_slug: str | None = None,
    source_id: str | None = None,
    provider_dataset_id: int | None = None,
    enabled: bool | None = None,
    include_archived: bool = False,
    limit: int = 200,
) -> tuple[CuratedSourceRule, ...]:
    """curated source rule 목록을 조회한다."""

    rows = (
        await session.execute(
            text(_LIST_RULES_SQL),
            {
                "theme_id": theme_id,
                "theme_slug": theme_slug,
                "source_id": source_id,
                "provider_dataset_id": provider_dataset_id,
                "enabled": enabled,
                "include_archived": include_archived,
                "limit": _safe_limit(limit),
            },
        )
    ).mappings().all()
    return tuple(_rule(row) for row in rows)


async def get_curated_source_rule(
    session: AsyncSession,
    *,
    rule_id: str,
) -> CuratedSourceRule | None:
    """retained source rule 단건을 조회한다."""

    return await _get_rule(session, rule_id)



















async def create_curated_theme_command(
    session: AsyncSession,
    *,
    theme_slug: str,
    theme_name: str,
    theme_description: str,
    theme_group: str,
    visibility: str,
    metadata: Mapping[str, Any] | None,
    command_id: int,
    principal: str,
) -> CuratedTheme:
    """domain command에 결박된 retained theme create를 실행한다."""

    _validate_choice(visibility, _THEME_VISIBILITIES, "visibility")
    result = (
        await session.execute(
            text(
                """
                CALL feature.create_curated_theme_command(
                  :theme_slug, :theme_name, :theme_description, :theme_group,
                  :visibility, CAST(:metadata_json AS jsonb), :command_id,
                  :principal, NULL, NULL
                )
                """
            ),
            {
                "command_id": command_id,
                "metadata_json": _json_dumps(metadata),
                "principal": principal,
                "theme_description": theme_description,
                "theme_group": theme_group,
                "theme_name": theme_name,
                "theme_slug": theme_slug,
                "visibility": visibility,
            },
        )
    ).mappings().one()
    theme = await get_curated_theme(session, theme_id=str(result["o_theme_id"]))
    if theme is None:
        raise RuntimeError("created curated theme could not be read")
    return theme


async def patch_curated_theme_command(
    session: AsyncSession,
    *,
    theme_id: str,
    expected_revision: int,
    updates: Mapping[str, Any],
    command_id: int,
    principal: str,
) -> CuratedTheme | None:
    """현재 theme를 full desired input으로 만들어 strong CAS patch한다."""

    allowed = {
        "theme_slug",
        "theme_name",
        "theme_description",
        "theme_group",
        "visibility",
        "metadata",
    }
    unknown = set(updates) - allowed
    if unknown:
        raise ValueError(f"unsupported update fields: {sorted(unknown)}")
    current = await get_curated_theme(session, theme_id=theme_id)
    if current is None:
        return None
    desired: dict[str, Any] = {
        "theme_slug": current.theme_slug,
        "theme_name": current.theme_name,
        "theme_description": current.theme_description,
        "theme_group": current.theme_group,
        "visibility": current.visibility,
        "metadata": current.metadata,
    }
    desired.update(updates)
    for field_name in (
        "theme_slug",
        "theme_name",
        "theme_description",
        "theme_group",
        "visibility",
        "metadata",
    ):
        if desired[field_name] is None:
            raise ValueError(f"{field_name} must not be null")
    _validate_choice(str(desired["visibility"]), _THEME_VISIBILITIES, "visibility")
    result = (
        await session.execute(
            text(
                """
                CALL feature.patch_curated_theme_command(
                  CAST(:theme_id AS uuid), :expected_revision, :theme_slug,
                  :theme_name, :theme_description, :theme_group, :visibility,
                  CAST(:metadata_json AS jsonb), :command_id, :principal,
                  NULL, NULL, NULL
                )
                """
            ),
            {
                "command_id": command_id,
                "expected_revision": expected_revision,
                "metadata_json": _json_dumps(desired["metadata"]),
                "principal": principal,
                "theme_description": desired["theme_description"],
                "theme_group": desired["theme_group"],
                "theme_id": theme_id,
                "theme_name": desired["theme_name"],
                "theme_slug": desired["theme_slug"],
                "visibility": desired["visibility"],
            },
        )
    ).mappings().one()
    updated = await get_curated_theme(session, theme_id=str(result["o_theme_id"]))
    if updated is None:
        raise RuntimeError("patched curated theme could not be read")
    return updated


async def archive_curated_theme_command(
    session: AsyncSession,
    *,
    theme_id: str,
    expected_revision: int,
    command_id: int,
    reason_code: str,
    principal: str,
) -> CuratedTheme | None:
    """retained theme를 archive하고 affected rule을 원자 reconcile한다."""

    if await get_curated_theme(session, theme_id=theme_id) is None:
        return None
    result = (
        await session.execute(
            text(
                """
                CALL feature.archive_curated_theme_command(
                  CAST(:theme_id AS uuid), :expected_revision, :command_id,
                  :reason_code, :principal, NULL, NULL, NULL
                )
                """
            ),
            {
                "command_id": command_id,
                "expected_revision": expected_revision,
                "principal": principal,
                "reason_code": reason_code,
                "theme_id": theme_id,
            },
        )
    ).mappings().one()
    archived = await get_curated_theme(session, theme_id=str(result["o_theme_id"]))
    if archived is None:
        raise RuntimeError("archived curated theme could not be read")
    return archived


async def create_curated_source_command(
    session: AsyncSession,
    *,
    provider_dataset_id: int,
    source_name: str,
    source_url: str | None = None,
    source_kind: str,
    license: str | None = None,
    update_cycle: str = "unknown",
    freshness_note: str | None = None,
    provider_status: str = "implemented",
    metadata: Mapping[str, Any] | None = None,
    command_id: int,
    principal: str,
) -> CuratedSource:
    """operator source catalog row를 typed command로 생성한다."""

    _validate_choice(source_kind, _SOURCE_KINDS, "source_kind")
    _validate_choice(update_cycle, _UPDATE_CYCLES, "update_cycle")
    _validate_choice(provider_status, _PROVIDER_STATUSES, "provider_status")
    result = (
        await session.execute(
            text(
                """
                CALL feature.create_curated_source_command(
                  :provider_dataset_id, :source_name, :source_url, :source_kind,
                  :license, :update_cycle, :freshness_note, :provider_status,
                  CAST(:metadata_json AS jsonb), :command_id, :principal,
                  NULL, NULL, NULL
                )
                """
            ),
            {
                "command_id": command_id,
                "freshness_note": freshness_note,
                "license": license,
                "metadata_json": _json_dumps(metadata),
                "principal": principal,
                "provider_dataset_id": provider_dataset_id,
                "provider_status": provider_status,
                "source_kind": source_kind,
                "source_name": source_name,
                "source_url": source_url,
                "update_cycle": update_cycle,
            },
        )
    ).mappings().one()
    created = await get_curated_source(
        session, source_id=str(result["o_source_id"])
    )
    if created is None:
        raise RuntimeError("created curated source could not be read")
    return created


async def patch_curated_source_command(
    session: AsyncSession,
    *,
    source_id: str,
    expected_revision: int,
    updates: Mapping[str, Any],
    command_id: int,
    principal: str,
) -> CuratedSource | None:
    """operator source fields만 CAS patch하고 observation 필드는 보존한다."""

    allowed = {
        "source_name",
        "source_url",
        "source_kind",
        "license",
        "update_cycle",
        "freshness_note",
        "provider_status",
        "metadata",
    }
    unknown = set(updates) - allowed
    if unknown:
        raise ValueError(f"unsupported update fields: {sorted(unknown)}")
    current = await get_curated_source(session, source_id=source_id)
    if current is None:
        return None
    desired: dict[str, Any] = {
        "source_name": current.source_name,
        "source_url": current.source_url,
        "source_kind": current.source_kind,
        "license": current.license,
        "update_cycle": current.update_cycle,
        "freshness_note": current.freshness_note,
        "provider_status": current.provider_status,
        "metadata": current.metadata,
    }
    desired.update(updates)
    _validate_choice(str(desired["source_kind"]), _SOURCE_KINDS, "source_kind")
    _validate_choice(str(desired["update_cycle"]), _UPDATE_CYCLES, "update_cycle")
    _validate_choice(
        str(desired["provider_status"]), _PROVIDER_STATUSES, "provider_status"
    )
    result = (
        await session.execute(
            text(
                """
                CALL feature.patch_curated_source_command(
                  CAST(:source_id AS uuid), :expected_revision,
                  :source_name, :source_url, :source_kind, :license,
                  :update_cycle, :freshness_note, :provider_status,
                  CAST(:metadata_json AS jsonb), :command_id, :principal,
                  NULL, NULL, NULL
                )
                """
            ),
            {
                "command_id": command_id,
                "expected_revision": expected_revision,
                "freshness_note": desired["freshness_note"],
                "license": desired["license"],
                "metadata_json": _json_dumps(desired["metadata"]),
                "principal": principal,
                "provider_status": desired["provider_status"],
                "source_id": source_id,
                "source_kind": desired["source_kind"],
                "source_name": desired["source_name"],
                "source_url": desired["source_url"],
                "update_cycle": desired["update_cycle"],
            },
        )
    ).mappings().one()
    patched = await get_curated_source(
        session, source_id=str(result["o_source_id"])
    )
    if patched is None:
        raise RuntimeError("patched curated source could not be read")
    return patched


async def archive_curated_source_command(
    session: AsyncSession,
    *,
    source_id: str,
    expected_revision: int,
    command_id: int,
    reason_code: str,
    principal: str,
) -> CuratedSource | None:
    """source archive와 dependent candidate reconcile을 원자 수행한다."""

    if await get_curated_source(session, source_id=source_id) is None:
        return None
    result = (
        await session.execute(
            text(
                """
                CALL feature.archive_curated_source_command(
                  CAST(:source_id AS uuid), :expected_revision, :command_id,
                  :reason_code, :principal, NULL, NULL, NULL, NULL
                )
                """
            ),
            {
                "command_id": command_id,
                "expected_revision": expected_revision,
                "principal": principal,
                "reason_code": reason_code,
                "source_id": source_id,
            },
        )
    ).mappings().one()
    archived = await get_curated_source(
        session, source_id=str(result["o_source_id"])
    )
    if archived is None:
        raise RuntimeError("archived curated source could not be read")
    return archived


async def create_curated_source_rule_command(
    session: AsyncSession,
    *,
    theme_id: str,
    source_id: str,
    place_kind: str | None = None,
    category: str | None = None,
    region_scope: Mapping[str, Any] | None = None,
    detail_selector: Mapping[str, Any] | None = None,
    default_action: str = "candidate",
    priority: int = 0,
    enabled: bool = True,
    metadata: Mapping[str, Any] | None = None,
    command_id: int,
    principal: str,
) -> CuratedSourceRule:
    """domain command에 결박된 retained source rule create를 실행한다."""

    _validate_choice(default_action, _TYPED_RULE_ACTIONS, "default_action")
    result = (
        await session.execute(
            text(
                """
                CALL feature.create_curated_source_rule_command(
                  CAST(:theme_id AS uuid), CAST(:source_id AS uuid),
                  :place_kind, :category, CAST(:region_scope_json AS jsonb),
                  CAST(:detail_selector_json AS jsonb), :default_action,
                  :priority, :enabled, CAST(:metadata_json AS jsonb),
                  :command_id, :principal, NULL, NULL, NULL
                )
                """
            ),
            {
                "theme_id": theme_id,
                "source_id": source_id,
                "place_kind": place_kind,
                "category": category,
                "region_scope_json": _json_dumps(region_scope),
                "detail_selector_json": (
                    _json_dumps(detail_selector)
                    if detail_selector is not None
                    else None
                ),
                "default_action": default_action,
                "priority": priority,
                "enabled": enabled,
                "metadata_json": _json_dumps(metadata),
                "command_id": command_id,
                "principal": principal,
            },
        )
    ).mappings().one()
    rule = await _get_rule(session, str(result["o_rule_id"]))
    if rule is None:
        raise RuntimeError("created curated source rule could not be read")
    return rule


async def patch_curated_source_rule_command(
    session: AsyncSession,
    *,
    rule_id: str,
    expected_revision: int,
    updates: Mapping[str, Any],
    command_id: int,
    principal: str,
) -> CuratedSourceRule | None:
    """현재 row를 full desired command input으로 만든 뒤 CAS patch한다."""

    allowed = {
        "place_kind",
        "category",
        "region_scope",
        "detail_selector",
        "default_action",
        "priority",
        "enabled",
        "metadata",
    }
    unknown = set(updates) - allowed
    if unknown:
        raise ValueError(f"unsupported update fields: {sorted(unknown)}")
    current = await _get_rule(session, rule_id)
    if current is None:
        return None
    desired: dict[str, Any] = {
        "place_kind": current.place_kind,
        "category": current.category,
        "region_scope": current.region_scope,
        "detail_selector": current.detail_selector,
        "default_action": current.default_action,
        "priority": current.priority,
        "enabled": current.enabled,
        "metadata": current.metadata,
    }
    desired.update(updates)
    default_action = desired["default_action"]
    if not isinstance(default_action, str):
        raise ValueError("default_action must not be null")
    _validate_choice(default_action, _TYPED_RULE_ACTIONS, "default_action")
    result = (
        await session.execute(
            text(
                """
                CALL feature.patch_curated_source_rule_command(
                  CAST(:rule_id AS uuid), :expected_revision,
                  :place_kind, :category, CAST(:region_scope_json AS jsonb),
                  CAST(:detail_selector_json AS jsonb), :default_action,
                  :priority, :enabled, CAST(:metadata_json AS jsonb),
                  :command_id, :principal, NULL, NULL, NULL
                )
                """
            ),
            {
                "rule_id": rule_id,
                "expected_revision": expected_revision,
                "place_kind": desired["place_kind"],
                "category": desired["category"],
                "region_scope_json": _json_dumps(desired["region_scope"]),
                "detail_selector_json": (
                    _json_dumps(desired["detail_selector"])
                    if desired["detail_selector"] is not None
                    else None
                ),
                "default_action": default_action,
                "priority": desired["priority"],
                "enabled": desired["enabled"],
                "metadata_json": _json_dumps(desired["metadata"]),
                "command_id": command_id,
                "principal": principal,
            },
        )
    ).mappings().one()
    updated = await _get_rule(session, str(result["o_rule_id"]))
    if updated is None:
        raise RuntimeError("patched curated source rule could not be read")
    return updated


async def archive_curated_source_rule_command(
    session: AsyncSession,
    *,
    rule_id: str,
    expected_revision: int,
    command_id: int,
    reason_code: str,
    principal: str,
) -> CuratedSourceRule | None:
    """retained source rule을 CAS archive하고 candidate reconcile을 완료한다."""

    if await _get_rule(session, rule_id) is None:
        return None
    result = (
        await session.execute(
            text(
                """
                CALL feature.archive_curated_source_rule_command(
                  CAST(:rule_id AS uuid), :expected_revision, :command_id,
                  :reason_code, :principal, NULL, NULL, NULL
                )
                """
            ),
            {
                "rule_id": rule_id,
                "expected_revision": expected_revision,
                "command_id": command_id,
                "reason_code": reason_code,
                "principal": principal,
            },
        )
    ).mappings().one()
    archived = await _get_rule(session, str(result["o_rule_id"]))
    if archived is None:
        raise RuntimeError("archived curated source rule could not be read")
    return archived


async def _get_rule(session: AsyncSession, rule_id: str) -> CuratedSourceRule | None:
    rows = (
        await session.execute(
            text(
                f"""
                SELECT {_RULE_COLUMNS}
                FROM feature.curated_source_rules AS r
                JOIN feature.curated_themes AS t ON t.theme_id = r.theme_id
                JOIN feature.curated_sources AS s ON s.source_id = r.source_id
                JOIN provider_sync.provider_datasets AS pd
                  ON pd.provider_dataset_id = s.provider_dataset_id
                WHERE r.rule_id = CAST(:rule_id AS uuid)
                """
            ),
            {"rule_id": rule_id},
        )
    ).mappings().first()
    return _rule(rows) if rows is not None else None


async def _update_simple(
    session: AsyncSession,
    *,
    table: str,
    id_column: str,
    id_value: str,
    updates: Mapping[str, Any],
    allowed: set[str],
    choice_fields: Mapping[str, frozenset[str]],
    returning: str,
) -> Any | None:
    set_parts: list[str] = []
    params: dict[str, Any] = {"id_value": id_value}
    for key, value in updates.items():
        if key not in allowed:
            raise ValueError(f"unsupported update field: {key}")
        if key in choice_fields:
            _validate_choice(str(value), choice_fields[key], key)
        if key in {"metadata", "region_scope", "detail_selector"}:
            param_name = f"{key}_json"
            set_parts.append(f"{key} = CAST(:{param_name} AS jsonb)")
            params[param_name] = (
                None
                if key == "detail_selector" and value is None
                else _json_dumps(value)
            )
        else:
            set_parts.append(f"{key} = :{key}")
            params[key] = value
    if not set_parts:
        return None
    set_parts.append("updated_at = now()")
    return (
        await session.execute(
            text(
                f"""
                UPDATE {table}
                SET {", ".join(set_parts)}
                WHERE {id_column} = CAST(:id_value AS uuid)
                RETURNING {returning}
                """
            ),
            params,
        )
    ).mappings().first()
