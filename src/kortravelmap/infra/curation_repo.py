"""큐레이션 collection/item 저장소.

물리 위치와 장소 본문은 ``feature.features``가 소유하고, 이 모듈은 테마형 묶음과
기존 Feature membership만 저장한다. 쿼리는 ADR-004에 따라 raw SQL만 사용한다.
"""

from __future__ import annotations

import base64
import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any, Final, Literal, TypedDict
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.engine import RowMapping

from kortravelmap.core import make_feature_id
from kortravelmap.core.address import normalize_korean_text
from kortravelmap.core.curation_address import (
    CURATION_ADDRESS_RESOLVER_VERSION,
    address_hint_matches,
)
from kortravelmap.core.curation_cutover_mapping import (
    CurationCutoverIdentityMappingDigestInput,
    curation_cutover_identity_mapping_root,
)
from kortravelmap.curation_import_children import (
    ParentCommandIdentity,
    derive_child_command_identity,
)
from kortravelmap.infra.curation_link_basis import trusted_basis_sql
from kortravelmap.infra.domain_command_repo import (
    create_domain_command_claim,
    create_domain_command_record,
    lock_domain_command,
)
from kortravelmap.infra.feature_identity import candidate_feature_uuid
from kortravelmap.infra.feature_repo import public_active_notice_filter_sql
from kortravelmap.infra.feature_subtype import write_subtype

if TYPE_CHECKING:
    from collections.abc import Sequence

    from sqlalchemy.ext.asyncio import AsyncSession

__all__ = [
    "CURATION_SERVICE_COLLECTION_MAX_ITEMS",
    "CurationCollection",
    "CurationImportBatch",
    "CurationImportPlan",
    "CurationImportRevisionExpectation",
    "CurationImportResult",
    "CurationImportRowReceipt",
    "CurationCutoverIdentityMapping",
    "CurationCutoverIdentityMappingExport",
    "CurationLinkAudit",
    "CurationItem",
    "CurationManualFeatureExactDuplicate",
    "CurationManualFeatureItem",
    "CurationServiceCollectionSnapshot",
    "CurationServiceItemSnapshot",
    "CurationQuarantineCollection",
    "CurationQuarantineItem",
    "CurationQuarantineItemsPreview",
    "CurationQuarantineMoveConflict",
    "CurationQuarantineMoveConflictError",
    "CurationQuarantineOriginalCollection",
    "CurationQuarantineSourceRef",
    "CurationQuarantineTargetArchivedError",
    "CurationQuarantineThemeRef",
    "FeatureCurationGroup",
    "FeatureMatch",
    "FeatureMatchRequest",
    "ResolvedCurationImportRow",
    "ResolvedCurationIdentityIssue",
    "add_curation_item",
    "archive_curation_item",
    "archive_curation_collection",
    "archive_curation_collection_command",
    "confirm_curation_quarantine_standalone",
    "create_curation_collection",
    "create_curation_collection_command",
    "create_manual_curation_item_with_feature_command",
    "get_curation_collection",
    "get_curation_import_batch",
    "get_curation_item",
    "get_curation_service_collection_snapshot",
    "get_curation_service_item_snapshot",
    "get_curation_cutover_identity_mapping_export",
    "get_current_curation_import_row",
    "get_feature_curation_group",
    "import_curation_rows",
    "build_curation_import_revision_vector",
    "claim_curation_import_plan_command",
    "complete_curation_import_plan_command",
    "create_curation_import_plan_command",
    "list_curation_collections",
    "list_curation_items_by_feature_ids",
    "list_curation_quarantine_collections",
    "list_curation_quarantine_items",
    "list_unattributed_curation_links",
    "list_unattributed_curation_links_page",
    "list_feature_curation_groups",
    "move_curation_quarantine_items",
    "preview_curation_import",
    "resolve_feature_match",
    "resolve_feature_matches",
    "upsert_curation_theme",
    "update_curation_item",
    "update_curation_collection",
    "patch_curation_collection_command",
    "validate_resolved_curation_identities",
]

CURATION_SERVICE_COLLECTION_MAX_ITEMS: Final = 2_000

CollectionStatus = Literal["draft", "published", "archived"]
CollectionVisibility = Literal["admin_only", "public"]
ItemStatus = Literal["candidate", "included", "rejected", "archived"]

_COLLECTION_STATUSES: Final = frozenset({"draft", "published", "archived"})
_VISIBILITIES: Final = frozenset({"admin_only", "public"})
_ITEM_STATUSES: Final = frozenset({"candidate", "included", "rejected", "archived"})
_RELATIONS: Final = frozenset(
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
_REUSE_POLICIES: Final = frozenset({"allowed", "blocked", "manual_review"})
_POSTGRES_INTEGER_MAX: Final = 2_147_483_647
_FEATURE_MATCH_NAME_CANDIDATE_LIMIT: Final = 100

# T-VN-H22 격리 conflict preview 분류. 이동은 ``collection_id``만 바꾸는 UPDATE라
# 위반 가능한 제약은 정확히 두 개다 — (A) ``uq_curation_items_component_identity``,
# (B) ``uq_curation_items_active_source_feature`` (partial). (A)가 우선한다.
QUARANTINE_CONFLICT_MOVABLE: Final = "movable"
QUARANTINE_CONFLICT_COMPONENT: Final = "component_identity_conflict"
QUARANTINE_CONFLICT_ACTIVE_FEATURE: Final = "active_source_feature_conflict"
QUARANTINE_CONFLICT_NO_TARGET: Final = "no_target"
QUARANTINE_CONFLICT_TARGET_MISSING: Final = "target_missing"


class CurationRevisionConflictError(ValueError):
    """canonical collection/item command의 expected revision이 stale이다."""


@dataclass(frozen=True)
class CurationManualFeatureExactDuplicate:
    """M03 exact claim winner 때문에 combined command가 중단된 결과."""

    existing_feature_uuid: str


@dataclass(frozen=True)
class CurationManualFeatureItem:
    """M03 one-command writer가 확정한 Feature와 curation item receipt."""

    feature_id: str
    feature_uuid: str
    feature_row_revision: int
    item: CurationItem


@dataclass(frozen=True)
class CurationCollection:
    collection_id: str
    collection_key: str
    theme_id: str
    theme_slug: str
    theme_name: str
    theme_group: str
    source_id: str | None
    provider_dataset_id: int | None
    provider: str | None
    dataset_key: str | None
    source_name: str | None
    source_url: str | None
    title: str
    edition_key: str
    description: str | None
    status: str
    visibility: str
    metadata: dict[str, Any]
    item_count: int
    public_item_count: int
    row_revision: int
    created_by: str | None
    updated_by: str | None
    created_at: datetime
    updated_at: datetime
    archived_at: datetime | None


@dataclass(frozen=True)
class CurationItem:
    curation_item_id: str
    collection_id: str
    collection_key: str
    title: str
    edition_key: str
    theme_slug: str
    theme_name: str
    theme_group: str
    provider_dataset_id: int | None
    provider: str | None
    dataset_key: str | None
    source_name: str | None
    source_url: str | None
    feature_id: str | None
    feature_name: str | None
    feature_kind: str | None
    feature_category: str | None
    lon: float | None
    lat: float | None
    address: dict[str, Any]
    source_record_key: str | None
    external_item_id: str
    external_component_id: str
    place_name: str
    address_hint: str | None
    source_present: bool
    status: str
    sort_order: int
    item_title: str | None
    item_summary: str | None
    curation_relation: str
    reuse_policy: str
    metadata: dict[str, Any]
    current_import_row_id: str | None
    accepted_link_decision_id: str | None
    link_match_basis: str | None
    link_resolver_version: str | None
    link_evidence: dict[str, Any]
    link_actor: str | None
    link_decided_at: datetime | None
    row_revision: int
    created_by: str | None
    updated_by: str | None
    created_at: datetime
    updated_at: datetime
    archived_at: datetime | None
    # T-VN-32C UUID 정본 병행 노출(additive) — feature 미연결/미해소면 None.
    feature_uuid: str | None = None


@dataclass(frozen=True)
class CurationServiceItemSnapshot:
    """PinVi service read가 소비하는 public canonical item projection."""

    curation_item_id: str
    collection_id: str
    row_revision: int
    updated_at: datetime
    theme_slug: str
    theme_name: str
    collection_title: str
    edition_key: str
    feature_uuid: str
    relation: str
    sort_order: int
    item_title: str | None
    item_summary: str | None
    feature_name: str
    feature_category: str
    feature_kind: str
    lon: float | None
    lat: float | None
    address: dict[str, Any]
    detail: dict[str, Any]
    source_record_key: str | None


@dataclass(frozen=True)
class CurationServiceCollectionSnapshot:
    """한 statement snapshot에서 읽은 collection receipt와 bounded public page."""

    collection_id: str
    row_revision: int
    updated_at: datetime
    theme_slug: str
    theme_name: str
    title: str
    edition_key: str
    item_count: int
    item_set_hash: str
    items: tuple[CurationServiceItemSnapshot, ...]


@dataclass(frozen=True)
class CurationCutoverIdentityMapping:
    """T-VN-40C legacy Map identity에서 canonical membership으로의 one-to-one row."""

    legacy_curated_feature_id: str
    collection_id: str
    curation_item_id: str
    mapping_kind: str
    source_row_hash: str


@dataclass(frozen=True)
class CurationCutoverIdentityMappingExport:
    """PinVi cutover가 전 페이지에서 대조하는 immutable mapping receipt."""

    mapping_count: int
    mapping_root: str
    mappings: tuple[CurationCutoverIdentityMapping, ...]


@dataclass(frozen=True)
class FeatureCurationGroup:
    feature_id: str
    name: str
    kind: str
    category: str
    lon: float | None
    lat: float | None
    address: dict[str, Any]
    lifecycle_state: str
    publication_state: str
    quality_state: str
    curations: tuple[CurationItem, ...]
    # T-VN-32C UUID 정본 병행 노출(additive).
    feature_uuid: str | None = None


@dataclass(frozen=True)
class FeatureMatch:
    feature_id: str
    name: str
    address: dict[str, Any]
    lon: float | None
    lat: float | None
    # T-VN-32C UUID 정본 병행 노출(additive).
    feature_uuid: str | None = None


@dataclass(frozen=True)
class FeatureMatchRequest:
    row_number: int
    feature_id: str | None
    place_name: str | None
    address_hint: str | None


@dataclass(frozen=True)
class CurationLinkAudit:
    """승인 근거가 없거나 legacy로만 귀속된 current Feature link."""

    curation_item_id: str
    collection_key: str
    external_item_id: str
    external_component_id: str
    feature_id: str
    place_name: str
    address_hint: str | None
    match_basis: str | None
    resolver_version: str | None
    decided_at: datetime | None


@dataclass(frozen=True)
class CurationQuarantineThemeRef:
    """격리/원본 collection이 가리키는 theme의 병렬 표시용 참조 (T-VN-H22A)."""

    theme_id: str
    theme_slug: str
    theme_name: str
    theme_group: str
    visibility: str


@dataclass(frozen=True)
class CurationQuarantineSourceRef:
    """격리/원본 collection이 가리키는 source의 병렬 표시용 참조 (T-VN-H22A)."""

    source_id: str
    provider_dataset_id: int | None
    provider: str | None
    dataset_key: str | None
    source_name: str | None


@dataclass(frozen=True)
class CurationQuarantineOriginalCollection:
    """`0065` marker가 기록한 원본 collection의 **현재** 상태.

    ``collection_id``는 marker(``metadata->>'original_collection_id'``) 기록값이고
    나머지는 그 uuid로 되짚은 현재 행이다 — 행이 사라졌으면 ``exists=False``에
    상태 필드는 전부 ``None``이다. target 추정·추천이 아니라 병렬 표시 전용이다.
    """

    collection_id: str
    row_revision: int | None
    title: str | None
    status: str | None
    visibility: str | None
    exists: bool
    theme: CurationQuarantineThemeRef | None
    source: CurationQuarantineSourceRef | None


@dataclass(frozen=True)
class CurationQuarantineCollection:
    """`0065` 격리 collection 목록 read model 한 건 (T-VN-H22A)."""

    collection_id: str
    row_revision: int
    collection_key: str
    title: str
    edition_key: str
    status: str
    visibility: str
    created_by: str | None
    item_count: int
    marker_intact: bool
    quarantine_theme: CurationQuarantineThemeRef | None
    quarantine_source: CurationQuarantineSourceRef | None
    original_collection: CurationQuarantineOriginalCollection | None


@dataclass(frozen=True)
class CurationQuarantineItem:
    """격리 item 한 건 + target 대비 conflict preview (T-VN-H22A)."""

    curation_item_id: str
    external_item_id: str
    external_component_id: str
    feature_id: str | None
    place_name: str
    status: str
    source_present: bool
    archived_at: datetime | None
    conflict_kind: str
    conflict_item_id: str | None


@dataclass(frozen=True)
class CurationQuarantineItemsPreview:
    """격리 item page와 적용된 target 해석 결과."""

    target_collection_id: str | None
    target_collection_revision: int | None
    target_missing: bool
    target_archived: bool
    items: tuple[CurationQuarantineItem, ...]


@dataclass(frozen=True)
class CurationQuarantineMoveConflict:
    """move가 위반할 unique 제약 충돌 한 건 (T-VN-H22B)."""

    curation_item_id: str
    conflict_kind: str
    conflict_item_id: str


class CurationQuarantineTargetArchivedError(Exception):
    """이동 target collection이 archive 상태라 move를 거부한다 (HTTP 409)."""


class CurationQuarantineMoveConflictError(Exception):
    """lock 하 재검사에서 충돌이 하나라도 있으면 전체를 원자적으로 거부한다 (409)."""

    def __init__(self, conflicts: tuple[CurationQuarantineMoveConflict, ...]) -> None:
        super().__init__("curation quarantine move가 unique 제약과 충돌합니다.")
        self.conflicts = conflicts


@dataclass(frozen=True)
class CurationImportBatch:
    """성공한 import transaction의 immutable receipt."""

    import_batch_id: str
    content_sha256: str
    batch_kind: str
    row_count: int
    actor: str
    metadata: dict[str, Any]
    imported_at: datetime


@dataclass(frozen=True)
class CurationImportRowReceipt:
    """batch 또는 item current pointer로 읽는 immutable source row."""

    import_row_id: str
    import_batch_id: str
    curation_item_id: str
    row_number: int
    source_row_sha256: str
    row_payload: dict[str, Any]
    provenance: dict[str, Any]
    imported_at: datetime


@dataclass(frozen=True)
class ResolvedCurationImportRow:
    """적재 대상 dataset identity는 스키마 세대마다 **정확히 하나**만 든다.

    현행 스키마에서는 ``provider_dataset_id`` surrogate가 정본이다(ADR-088).
    H35 cutover 리허설이 도는 0063~0079 고정 세대에는 ``provider_datasets``
    catalog 자체가 없고 ``feature.curated_sources``가 ``(provider, dataset_key)``
    자연키로 키를 잡으므로, 그 경로만 ``frozen_h35_dataset``을 든다. 둘 중
    하나만 채워야 하며 위반은 ``import_curation_rows``가 거절한다 — 옵셔널로
    풀어 둔 자리에 final 경로가 조용히 NULL을 흘리지 못하게 한다.
    """

    row_number: int
    collection_key: str
    theme_slug: str
    theme_name: str
    theme_group: str
    title: str
    edition_key: str
    provider_dataset_id: int | None
    source_name: str
    source_url: str | None
    source_item_key: str
    feature_id: str | None
    place_name: str
    address_hint: str | None
    sort_order: int
    item_title: str | None
    item_summary: str | None
    metadata: dict[str, Any]
    source_component_key: str = "primary"
    provenance: dict[str, Any] | None = None
    frozen_h35_dataset: tuple[str, str] | None = None
    manual_feature: dict[str, Any] | None = None
    """T-VN-M03 — 이 행이 만들 manual Feature의 typed payload. 지시가 없으면 ``None``.

    ``metadata``에 섞지 않는다. 설계 §6.1이 "``metadata_json``에 untyped input을 숨기지
    않는다"를 요구하므로 typed 자리를 따로 둔다.
    """

    manual_feature_sha256: str | None = None
    """``manual_feature``의 canonical SHA-256. child idempotency identity의 입력이다."""


@dataclass(frozen=True)
class ResolvedCurationIdentityIssue:
    """Feature 해소 뒤 드러난 authoritative item identity 충돌."""

    row_number: int
    code: str
    message: str


@dataclass(frozen=True)
class CurationImportPlan:
    """CSV authoritative replace가 만들 읽기 전용 변경 계획."""

    collections: int
    inserted: int
    updated: int
    removals: tuple[CurationItem, ...]


@dataclass(frozen=True)
class CurationImportRevisionExpectation:
    """preview가 고정한 catalog/membership optimistic revision 한 건."""

    resource_kind: Literal["theme", "source", "collection", "item", "feature"]
    resource_key: str
    expected_revision: int | None


@dataclass(frozen=True, slots=True)
class ManualImportChild:
    """import 행 하나가 발급한 manual Feature child command의 확정 좌표.

    부모 summary(설계 §6.3)는 요청 JSON이 아니라 이 값(그리고 `301` linkage 표)에서
    순서대로 구성한다.
    """

    row_number: int
    child_command_id: int
    feature_id: str
    feature_uuid: str
    curation_item_id: str
    #: 재수렴(re-import) — 이전 commit의 child linkage를 그대로 재사용했고 새
    #: child command를 발급하지 않았다(적대 리뷰 H2/F3: authoritative replace가
    #: manual 행에서 영구히 깨지던 결함의 해소 경로).
    reused: bool = False


@dataclass(frozen=True, slots=True)
class ImportRowReceipt:
    """provenance 단계가 한 행에 대해 확정한 immutable 좌표.

    `301` linkage(`ops.curation_import_manual_feature_children`)가 이 셋을 그대로
    결박한다 — `(import_row_id, curation_item_id)`는 import receipt를,
    `(link_decision_id, curation_item_id, import_row_id)`는 accepted decision을 가리킨다.

    종전에는 provenance가 이 값들을 만들어 놓고 `import_batch_id` 하나만 돌려줬다.
    그러면 linkage를 쓰려는 caller가 **DB를 다시 조회해 추론**해야 하는데, 같은
    transaction 안에서 방금 만든 것을 되찾는 조회는 결박이 아니라 추측이다.
    """

    row_number: int
    import_row_id: str
    curation_item_id: str
    accepted_link_decision_id: str | None


class CurationImportResult(TypedDict):
    """원자적 CSV replace가 실제 반영한 item 변화."""

    rows: int
    collections: int
    inserted: int
    updated: int
    removed: int
    removals: tuple[CurationItem, ...]
    import_batch_id: str | None
    row_receipts: tuple[ImportRowReceipt, ...]
    manual_children: tuple[ManualImportChild, ...]


_COLLECTION_COUNT_NOTICE_FILTER_SQL: Final[str] = public_active_notice_filter_sql("count_pf")
_COLLECTION_PUBLIC_COUNT_NOTICE_FILTER_SQL: Final[str] = public_active_notice_filter_sql(
    "public_count_pf"
)
_ITEM_PUBLIC_NOTICE_FILTER_SQL: Final[str] = public_active_notice_filter_sql("pf")


def _trusted_link_sql(item_alias: str) -> str:
    return f"""
    EXISTS (
        SELECT 1
        FROM feature.curation_link_decisions AS trusted_decision
        WHERE trusted_decision.decision_id =
                  {item_alias}.accepted_link_decision_id
          AND trusted_decision.curation_item_id =
                  {item_alias}.curation_item_id
          AND trusted_decision.feature_id = {item_alias}.feature_id
          AND trusted_decision.decision_kind = 'accepted'
          AND {trusted_basis_sql("trusted_decision.match_basis")}
    )
    """


_COLLECTION_SELECT: Final[str] = f"""
SELECT
    c.collection_id::text AS collection_id,
    c.collection_key,
    c.theme_id::text AS theme_id,
    t.theme_slug,
    t.theme_name,
    t.theme_group,
    c.source_id::text AS source_id,
    s.provider_dataset_id,
    pd.provider,
    pd.dataset_key,
    s.source_name,
    s.source_url,
    c.title,
    c.edition_key,
    c.description,
    c.status,
    c.visibility,
    c.metadata,
    (
        SELECT count(*)::integer
        FROM feature.curation_items AS count_item
        WHERE count_item.collection_id = c.collection_id
          AND count_item.archived_at IS NULL
          AND count_item.source_present
          AND (
              NOT CAST(:public_only AS boolean)
              OR (
                  count_item.feature_id IS NOT NULL
                  AND
                  {_trusted_link_sql("count_item")}
                  AND EXISTS (
                      SELECT 1
                      FROM feature.public_features AS count_pf
                      WHERE count_pf.feature_id = count_item.feature_id
                      {_COLLECTION_COUNT_NOTICE_FILTER_SQL}
                  )
              )
          )
    ) AS item_count,
    (
        SELECT count(*)::integer
        FROM feature.curation_items AS public_count_item
        WHERE public_count_item.collection_id = c.collection_id
          AND public_count_item.archived_at IS NULL
          AND public_count_item.source_present
          AND public_count_item.status = 'included'
          AND (
              NOT CAST(:public_only AS boolean)
              OR (
                  public_count_item.feature_id IS NOT NULL
                  AND
                  {_trusted_link_sql("public_count_item")}
                  AND EXISTS (
                      SELECT 1
                      FROM feature.public_features AS public_count_pf
                      WHERE public_count_pf.feature_id = public_count_item.feature_id
                      {_COLLECTION_PUBLIC_COUNT_NOTICE_FILTER_SQL}
                  )
              )
          )
    ) AS public_item_count,
    c.row_revision,
    c.created_by,
    c.updated_by,
    c.created_at,
    c.updated_at,
    c.archived_at
FROM feature.curation_collections AS c
JOIN feature.curated_themes AS t ON t.theme_id = c.theme_id
LEFT JOIN feature.curated_sources AS s ON s.source_id = c.source_id
LEFT JOIN provider_sync.provider_datasets AS pd
  ON pd.provider_dataset_id = s.provider_dataset_id
"""

_ITEM_SELECT_FIELDS: Final[str] = f"""
    i.curation_item_id::text AS curation_item_id,
    i.collection_id::text AS collection_id,
    c.collection_key,
    c.title,
    c.edition_key,
    t.theme_slug,
    t.theme_name,
    t.theme_group,
    s.provider_dataset_id,
    pd.provider,
    pd.dataset_key,
    s.source_name,
    s.source_url,
    i.feature_id,
    CAST(f.feature_uuid AS text) AS feature_uuid,
    f.name AS feature_name,
    f.kind AS feature_kind,
    f.category AS feature_category,
    x_extension.ST_X(f.coord) AS lon,
    x_extension.ST_Y(f.coord) AS lat,
    f.address,
    EXISTS (
        SELECT 1
        FROM feature.public_features AS pf
        WHERE pf.feature_id = i.feature_id
        {_ITEM_PUBLIC_NOTICE_FILTER_SQL}
    ) AS linked_feature_is_public,
    i.source_record_key,
    i.external_item_id,
    i.external_component_id,
    i.place_name,
    i.address_hint,
    i.source_present,
    i.status,
    i.sort_order,
    i.item_title,
    i.item_summary,
    i.curation_relation,
    i.reuse_policy,
    i.metadata,
    i.current_import_row_id::text AS current_import_row_id,
    i.accepted_link_decision_id::text AS accepted_link_decision_id,
    link_decision.match_basis AS link_match_basis,
    link_decision.resolver_version AS link_resolver_version,
    link_decision.evidence AS link_evidence,
    link_decision.actor AS link_actor,
    link_decision.decided_at AS link_decided_at,
    i.row_revision,
    i.created_by,
    i.updated_by,
    i.created_at,
    i.updated_at,
    i.archived_at
"""

_ITEM_SELECT: Final[str] = (
    """
SELECT
"""
    + _ITEM_SELECT_FIELDS
    + """
FROM feature.curation_items AS i
JOIN feature.curation_collections AS c ON c.collection_id = i.collection_id
JOIN feature.curated_themes AS t ON t.theme_id = c.theme_id
LEFT JOIN feature.curated_sources AS s ON s.source_id = c.source_id
LEFT JOIN provider_sync.provider_datasets AS pd
  ON pd.provider_dataset_id = s.provider_dataset_id
LEFT JOIN feature.features AS f ON f.feature_id = i.feature_id
LEFT JOIN feature.curation_link_decisions AS link_decision
  ON link_decision.decision_id = i.accepted_link_decision_id
"""
)

_LIST_COLLECTIONS_SQL: Final[str] = (
    _COLLECTION_SELECT
    + """
WHERE (:include_archived OR c.archived_at IS NULL)
  AND (
      NOT CAST(:public_only AS boolean)
      OR (
          c.status = 'published'
          AND c.visibility = 'public'
          AND t.visibility = 'public'
          AND t.archived_at IS NULL
          AND (c.source_id IS NULL OR s.archived_at IS NULL)
      )
  )
  AND (CAST(:status AS text) IS NULL OR c.status = CAST(:status AS text))
  AND (
      CAST(:visibility AS text) IS NULL
      OR c.visibility = CAST(:visibility AS text)
  )
  AND (
      CAST(:theme_slug AS text) IS NULL
      OR t.theme_slug = CAST(:theme_slug AS text)
  )
  AND (
      CAST(:edition_key AS text) IS NULL
      OR c.edition_key = CAST(:edition_key AS text)
  )
  AND (
      CAST(:provider_dataset_id AS bigint) IS NULL
      OR s.provider_dataset_id = CAST(:provider_dataset_id AS bigint)
  )
  AND (
      CAST(:q AS text) IS NULL
      OR c.title ILIKE CAST(:q AS text)
      OR c.collection_key ILIKE CAST(:q AS text)
      OR t.theme_name ILIKE CAST(:q AS text)
  )
  AND (
      CAST(:cursor_updated_at AS timestamptz) IS NULL
      OR (c.updated_at, c.collection_id) < (
          CAST(:cursor_updated_at AS timestamptz),
          CAST(:cursor_collection_id AS uuid)
      )
  )
ORDER BY c.updated_at DESC, c.collection_id DESC
LIMIT :limit
"""
)

_GET_COLLECTION_SQL: Final[str] = (
    _COLLECTION_SELECT
    + """
WHERE c.collection_id = CAST(:collection_id AS uuid)
  AND (:include_archived OR c.archived_at IS NULL)
  AND (
      NOT CAST(:public_only AS boolean)
      OR (
          c.status = 'published'
          AND c.visibility = 'public'
          AND t.visibility = 'public'
          AND t.archived_at IS NULL
          AND (c.source_id IS NULL OR s.archived_at IS NULL)
      )
  )
"""
)

_GET_COLLECTION_BY_KEY_SQL: Final[str] = (
    _COLLECTION_SELECT
    + """
WHERE c.collection_key = :collection_key
  AND (:include_archived OR c.archived_at IS NULL)
  AND (
      NOT CAST(:public_only AS boolean)
      OR (
          c.status = 'published'
          AND c.visibility = 'public'
          AND t.visibility = 'public'
          AND t.archived_at IS NULL
          AND (c.source_id IS NULL OR s.archived_at IS NULL)
      )
  )
"""
)

_LIST_COLLECTION_ITEMS_SQL: Final[str] = (
    _ITEM_SELECT
    + f"""
WHERE i.collection_id = CAST(:collection_id AS uuid)
  AND (
      :include_archived
      OR (i.archived_at IS NULL AND i.source_present)
  )
  AND (
      NOT CAST(:public_only AS boolean)
      OR (
          i.feature_id IS NOT NULL
          AND t.archived_at IS NULL
          AND (c.source_id IS NULL OR s.archived_at IS NULL)
          AND
          {_trusted_link_sql("i")}
          AND EXISTS (
              SELECT 1
              FROM feature.public_features AS pf
              WHERE pf.feature_id = i.feature_id
              {_ITEM_PUBLIC_NOTICE_FILTER_SQL}
          )
      )
  )
ORDER BY i.sort_order, i.curation_item_id
"""
)

_GET_COLLECTION_ITEM_SQL: Final[str] = (
    _ITEM_SELECT
    + """
WHERE i.collection_id = CAST(:collection_id AS uuid)
  AND i.curation_item_id = CAST(:curation_item_id AS uuid)
  AND (
      :include_archived
      OR (i.archived_at IS NULL AND i.source_present)
  )
"""
)


_SERVICE_SNAPSHOT_ELIGIBLE_ITEMS_SQL: Final[str] = f"""
SELECT
    i.curation_item_id::text AS curation_item_id,
    i.collection_id,
    i.row_revision,
    i.updated_at,
    c.theme_slug,
    c.theme_name,
    c.title AS collection_title,
    c.edition_key,
    pf.feature_uuid::text AS feature_uuid,
    i.curation_relation AS relation,
    i.sort_order,
    i.item_title,
    i.item_summary,
    pf.name AS feature_name,
    pf.category AS feature_category,
    pf.kind AS feature_kind,
    x_extension.ST_X(pf.coord) AS lon,
    x_extension.ST_Y(pf.coord) AS lat,
    pf.address,
    pf.detail,
    i.source_record_key
FROM feature.curation_items AS i
JOIN collection_row AS c ON c.collection_id = i.collection_id
JOIN feature.public_features AS pf ON pf.feature_id = i.feature_id
WHERE i.archived_at IS NULL
  AND i.source_present
  AND i.status = 'included'
  {_ITEM_PUBLIC_NOTICE_FILTER_SQL}
  AND {_trusted_link_sql("i")}
  AND (
      i.source_record_key IS NULL
      OR EXISTS (
          SELECT 1
          FROM provider_sync.source_records AS snapshot_record
          JOIN provider_sync.source_entity_heads AS snapshot_head
            ON snapshot_head.source_entity_key = snapshot_record.source_entity_key
           AND snapshot_head.current_source_record_key = snapshot_record.source_record_key
          JOIN provider_sync.source_links AS snapshot_link
            ON snapshot_link.source_entity_key = snapshot_record.source_entity_key
           AND snapshot_link.feature_id = i.feature_id
          WHERE snapshot_record.source_record_key = i.source_record_key
      )
  )
  AND (
      CAST(:curation_item_id AS uuid) IS NULL
      OR i.curation_item_id = CAST(:curation_item_id AS uuid)
  )
"""

_GET_SERVICE_CURATION_ITEM_SNAPSHOT_SQL: Final[str] = f"""
WITH collection_row AS (
    SELECT
        collection.collection_id,
        collection.row_revision,
        collection.updated_at,
        theme.theme_slug,
        theme.theme_name,
        collection.title,
        collection.edition_key
    FROM feature.curation_collections AS collection
    JOIN feature.curated_themes AS theme ON theme.theme_id = collection.theme_id
    LEFT JOIN feature.curated_sources AS source ON source.source_id = collection.source_id
    WHERE collection.archived_at IS NULL
      AND collection.status = 'published'
      AND collection.visibility = 'public'
      AND theme.visibility = 'public'
      AND theme.archived_at IS NULL
      AND (collection.source_id IS NULL OR source.archived_at IS NULL)
      AND (
          (
              CAST(:collection_id AS uuid) IS NOT NULL
              AND collection.collection_id = CAST(:collection_id AS uuid)
          )
          OR (
              CAST(:curation_item_id AS uuid) IS NOT NULL
              AND EXISTS (
                  SELECT 1
                  FROM feature.curation_items AS requested_item
                  WHERE requested_item.collection_id = collection.collection_id
                    AND requested_item.curation_item_id = CAST(:curation_item_id AS uuid)
              )
          )
      )
), eligible_item AS (
    {_SERVICE_SNAPSHOT_ELIGIBLE_ITEMS_SQL}
)
SELECT
    collection_row.collection_id::text AS collection_id,
    collection_row.row_revision AS collection_row_revision,
    collection_row.updated_at AS collection_updated_at,
    collection_row.theme_slug,
    collection_row.theme_name,
    collection_row.title AS collection_title,
    collection_row.edition_key,
    eligible_item.curation_item_id,
    eligible_item.row_revision AS item_row_revision,
    eligible_item.updated_at AS item_updated_at,
    eligible_item.feature_uuid,
    eligible_item.relation,
    eligible_item.sort_order,
    eligible_item.item_title,
    eligible_item.item_summary,
    eligible_item.feature_name,
    eligible_item.feature_category,
    eligible_item.feature_kind,
    eligible_item.lon,
    eligible_item.lat,
    eligible_item.address,
    eligible_item.detail,
    eligible_item.source_record_key
FROM collection_row
LEFT JOIN eligible_item ON eligible_item.collection_id = collection_row.collection_id
ORDER BY eligible_item.curation_item_id
"""

_GET_SERVICE_CURATION_COLLECTION_PAGE_SQL: Final[str] = f"""
WITH collection_row AS MATERIALIZED (
    SELECT
        collection.collection_id,
        collection.row_revision,
        collection.updated_at,
        theme.theme_slug,
        theme.theme_name,
        collection.title,
        collection.edition_key
    FROM feature.curation_collections AS collection
    JOIN feature.curated_themes AS theme ON theme.theme_id = collection.theme_id
    LEFT JOIN feature.curated_sources AS source ON source.source_id = collection.source_id
    WHERE collection.collection_id = CAST(:collection_id AS uuid)
      AND collection.archived_at IS NULL
      AND collection.status = 'published'
      AND collection.visibility = 'public'
      AND theme.visibility = 'public'
      AND theme.archived_at IS NULL
      AND (collection.source_id IS NULL OR source.archived_at IS NULL)
), bounded_eligible_item_key AS MATERIALIZED (
    SELECT item.curation_item_id
    FROM feature.curation_items AS item
    JOIN collection_row AS collection
      ON collection.collection_id = item.collection_id
    JOIN feature.curation_link_decisions AS trusted_decision
      ON trusted_decision.decision_id = item.accepted_link_decision_id
     AND trusted_decision.curation_item_id = item.curation_item_id
     AND trusted_decision.feature_id = item.feature_id
     AND trusted_decision.decision_kind = 'accepted'
     AND {trusted_basis_sql("trusted_decision.match_basis")}
    JOIN feature.public_features AS pf ON pf.feature_id = item.feature_id
    WHERE item.archived_at IS NULL
      AND item.source_present
      AND item.status = 'included'
      AND item.feature_id IS NOT NULL
      {_ITEM_PUBLIC_NOTICE_FILTER_SQL}
      AND (
          item.source_record_key IS NULL
          OR EXISTS (
              SELECT 1
              FROM provider_sync.source_records AS snapshot_record
              JOIN provider_sync.source_entity_heads AS snapshot_head
                ON snapshot_head.source_entity_key = snapshot_record.source_entity_key
               AND snapshot_head.current_source_record_key = snapshot_record.source_record_key
              JOIN provider_sync.source_links AS snapshot_link
                ON snapshot_link.source_entity_key = snapshot_record.source_entity_key
               AND snapshot_link.feature_id = item.feature_id
              WHERE snapshot_record.source_record_key = item.source_record_key
          )
      )
    ORDER BY item.curation_item_id
    LIMIT {CURATION_SERVICE_COLLECTION_MAX_ITEMS + 1}
), eligible_item AS MATERIALIZED (
    {_SERVICE_SNAPSHOT_ELIGIBLE_ITEMS_SQL}
      AND i.curation_item_id IN (
          SELECT bounded_key.curation_item_id
          FROM bounded_eligible_item_key AS bounded_key
      )
      AND (
          SELECT count(*) <= {CURATION_SERVICE_COLLECTION_MAX_ITEMS}
          FROM bounded_eligible_item_key
      )
), bounded_eligible_item AS (
    SELECT *
    FROM eligible_item
    ORDER BY eligible_item.curation_item_id::uuid
    LIMIT {CURATION_SERVICE_COLLECTION_MAX_ITEMS + 1}
), hashed_item AS (
    SELECT
        eligible_item.*,
        encode(
            x_extension.digest(
                convert_to(
                    jsonb_build_array(
                        eligible_item.curation_item_id,
                        eligible_item.collection_id,
                        eligible_item.row_revision,
                        eligible_item.updated_at,
                        eligible_item.theme_slug,
                        eligible_item.theme_name,
                        eligible_item.collection_title,
                        eligible_item.edition_key,
                        eligible_item.feature_uuid,
                        eligible_item.relation,
                        eligible_item.sort_order,
                        eligible_item.item_title,
                        eligible_item.item_summary,
                        eligible_item.feature_name,
                        eligible_item.feature_category,
                        eligible_item.feature_kind,
                        eligible_item.lon,
                        eligible_item.lat,
                        eligible_item.address,
                        eligible_item.detail,
                        eligible_item.source_record_key
                    )::text,
                    'UTF8'
                ),
                'sha256'
            ),
            'hex'
        ) AS item_payload_hash
    FROM bounded_eligible_item AS eligible_item
), item_set_receipt AS (
    SELECT
        CASE
            WHEN (
                SELECT count(*) > {CURATION_SERVICE_COLLECTION_MAX_ITEMS}
                FROM bounded_eligible_item_key
            )
            THEN {CURATION_SERVICE_COLLECTION_MAX_ITEMS + 1}::bigint
            ELSE count(*)::bigint
        END AS item_count,
        encode(
            x_extension.digest(
                convert_to(
                    COALESCE(
                        jsonb_agg(
                            jsonb_build_array(
                                hashed_item.curation_item_id,
                                hashed_item.row_revision,
                                hashed_item.item_payload_hash
                            )
                            ORDER BY hashed_item.curation_item_id
                        ),
                        '[]'::jsonb
                    )::text,
                    'UTF8'
                ),
                'sha256'
            ),
            'hex'
        ) AS item_set_hash
    FROM hashed_item
), page_item AS (
    SELECT *
    FROM hashed_item
    WHERE (
        CAST(:after_curation_item_id AS uuid) IS NULL
        OR hashed_item.curation_item_id::uuid
            > CAST(:after_curation_item_id AS uuid)
    )
    ORDER BY hashed_item.curation_item_id::uuid
    LIMIT CAST(:page_limit AS integer)
)
SELECT
    collection_row.collection_id::text AS collection_id,
    collection_row.row_revision AS collection_row_revision,
    collection_row.updated_at AS collection_updated_at,
    collection_row.theme_slug,
    collection_row.theme_name,
    collection_row.title AS collection_title,
    collection_row.edition_key,
    item_set_receipt.item_count,
    item_set_receipt.item_set_hash,
    page_item.curation_item_id,
    page_item.row_revision AS item_row_revision,
    page_item.updated_at AS item_updated_at,
    page_item.feature_uuid,
    page_item.relation,
    page_item.sort_order,
    page_item.item_title,
    page_item.item_summary,
    page_item.feature_name,
    page_item.feature_category,
    page_item.feature_kind,
    page_item.lon,
    page_item.lat,
    page_item.address,
    page_item.detail,
    page_item.source_record_key
FROM collection_row
CROSS JOIN item_set_receipt
LEFT JOIN page_item ON true
ORDER BY page_item.curation_item_id::uuid
"""

_LIST_FEATURE_ITEMS_SQL: Final[str] = (
    _ITEM_SELECT
    + f"""
WHERE i.feature_id = :feature_id
  AND i.archived_at IS NULL
  AND i.source_present
  AND c.archived_at IS NULL
  AND (
      :public_only = false
      OR (
          i.status = 'included'
          AND c.status = 'published'
          AND c.visibility = 'public'
          AND t.visibility = 'public'
          AND t.archived_at IS NULL
          AND (c.source_id IS NULL OR s.archived_at IS NULL)
          AND {_trusted_link_sql("i")}
      )
  )
ORDER BY c.edition_key DESC, c.title, i.sort_order, i.curation_item_id
"""
)

_LIST_FEATURE_ITEMS_BATCH_SQL: Final[str] = (
    _ITEM_SELECT
    + f"""
WHERE i.feature_id = ANY(CAST(:feature_ids AS text[]))
  AND i.archived_at IS NULL
  AND i.source_present
  AND c.archived_at IS NULL
  AND (
      :public_only = false
      OR (
          i.status = 'included'
          AND c.status = 'published'
          AND c.visibility = 'public'
          AND t.visibility = 'public'
          AND t.archived_at IS NULL
          AND (c.source_id IS NULL OR s.archived_at IS NULL)
          AND {_trusted_link_sql("i")}
      )
  )
ORDER BY i.feature_id, c.edition_key DESC, c.title, i.sort_order,
         i.curation_item_id
"""
)

# 공개 큐레이션 group read — feature 공개 여부는 ADR-067
# ``feature.public_features`` projection이 정본이다(T-VN-04, F-1). 과거의
# 과거 core visibility 술어 재구현은 공개되지 않아야 할 행을 노출했다.
# ``:public_only``는 collection/item 상태 필터에만 관여한다.
_LIST_GROUP_KEYS_SQL: Final[str] = f"""
SELECT f.feature_id
FROM feature.public_features AS f
WHERE (
      NOT CAST(:bbox_enabled AS boolean)
      OR (
          f.coord IS NOT NULL
          AND f.coord OPERATOR(x_extension.&&) x_extension.ST_MakeEnvelope(
              :min_lon, :min_lat, :max_lon, :max_lat, 4326
          )
      )
  )
  AND EXISTS (
      SELECT 1
      FROM feature.curation_items AS matched_item
      JOIN feature.curation_collections AS matched_collection
        ON matched_collection.collection_id = matched_item.collection_id
      JOIN feature.curated_themes AS matched_theme
        ON matched_theme.theme_id = matched_collection.theme_id
      LEFT JOIN feature.curated_sources AS matched_source
        ON matched_source.source_id = matched_collection.source_id
      WHERE matched_item.feature_id = f.feature_id
        AND matched_item.archived_at IS NULL
        AND matched_item.source_present
        AND matched_collection.archived_at IS NULL
        AND (
            NOT CAST(:public_only AS boolean)
            OR (
                matched_item.status = 'included'
                AND matched_collection.status = 'published'
                AND matched_collection.visibility = 'public'
                AND matched_theme.visibility = 'public'
                AND matched_theme.archived_at IS NULL
                AND (
                    matched_collection.source_id IS NULL
                    OR matched_source.archived_at IS NULL
                )
                AND {_trusted_link_sql("matched_item")}
            )
        )
        AND (
            CAST(:theme_slug AS text) IS NULL
            OR matched_theme.theme_slug = CAST(:theme_slug AS text)
        )
        AND (
            CAST(:edition_key AS text) IS NULL
            OR matched_collection.edition_key = CAST(:edition_key AS text)
        )
        AND (
            CAST(:provider_dataset_id AS bigint) IS NULL
            OR matched_source.provider_dataset_id = CAST(:provider_dataset_id AS bigint)
        )
        AND (
            CAST(:q AS text) IS NULL
            OR f.name ILIKE CAST(:q AS text)
            OR matched_collection.title ILIKE CAST(:q AS text)
            OR matched_theme.theme_name ILIKE CAST(:q AS text)
        )
  )
  AND (
      CAST(:cursor_feature_id AS text) IS NULL
      OR f.feature_id > CAST(:cursor_feature_id AS text)
  )
  {public_active_notice_filter_sql("f")}
ORDER BY f.feature_id
LIMIT :limit
"""

# 아래 두 질의의 공개 경계는 ``feature.public_features`` 소속 여부 그 자체다 —
# 0097 이후 이 view는 상태 3축을 **투영하지 않고** 자신의 WHERE로 고정한다
# (lifecycle=active AND publication=published AND quality=valid). 그래서 축 값을
# view에서 읽을 수 없고, 그렇다고 view 술어를 상수로 베껴 SELECT에 박으면 같은
# 사실의 정본이 둘이 되어 view가 바뀌는 순간 조용히 거짓말을 한다. 축의 정본은
# ``feature.features``이므로 PK로 되짚어 실제 값을 읽는다(공개 판정은 여전히
# view 하나가 소유한다).
_PUBLIC_FEATURE_STATE_JOIN_SQL: Final[str] = (
    "JOIN feature.features AS core ON core.feature_id = f.feature_id"
)

_GET_FEATURE_SQL: Final[str] = f"""
SELECT
    f.feature_id,
    CAST(f.feature_uuid AS text) AS feature_uuid,
    f.name,
    f.kind,
    f.category,
    x_extension.ST_X(f.coord) AS lon,
    x_extension.ST_Y(f.coord) AS lat,
    f.address,
    core.lifecycle_state,
    core.publication_state,
    core.quality_state
FROM feature.public_features AS f
{_PUBLIC_FEATURE_STATE_JOIN_SQL}
WHERE f.feature_id = :feature_id
{public_active_notice_filter_sql("f")}
"""

_GET_FEATURES_BY_IDS_SQL: Final[str] = f"""
SELECT
    f.feature_id,
    CAST(f.feature_uuid AS text) AS feature_uuid,
    f.name,
    f.kind,
    f.category,
    x_extension.ST_X(f.coord) AS lon,
    x_extension.ST_Y(f.coord) AS lat,
    f.address,
    core.lifecycle_state,
    core.publication_state,
    core.quality_state
FROM feature.public_features AS f
{_PUBLIC_FEATURE_STATE_JOIN_SQL}
WHERE f.feature_id = ANY(CAST(:feature_ids AS text[]))
{public_active_notice_filter_sql("f")}
"""

_CREATE_COLLECTION_SQL: Final[str] = """
INSERT INTO feature.curation_collections (
    collection_key, theme_id, source_id, title, edition_key, description,
    status, visibility, metadata, created_by, updated_by, updated_at
) VALUES (
    :collection_key, CAST(:theme_id AS uuid), CAST(:source_id AS uuid),
    :title, :edition_key, :description, :status, :visibility,
    CAST(:metadata AS jsonb), :actor, :actor, now()
)
RETURNING collection_id::text
"""

_UPSERT_ITEM_SQL: Final[str] = """
WITH written AS (
    INSERT INTO feature.curation_items (
        collection_id, feature_id, source_record_key, external_item_id,
        external_component_id,
        place_name, address_hint, source_present, source_updated_at, status,
        sort_order, item_title, item_summary, curation_relation, reuse_policy,
        metadata, created_by, updated_by, operator_updated_by,
        operator_updated_at, updated_at
    ) VALUES (
        CAST(:collection_id AS uuid), :feature_id, :source_record_key,
        :external_item_id, :external_component_id,
        :place_name, :address_hint, true, clock_timestamp(),
        :status, :sort_order, :item_title, :item_summary,
        :curation_relation, :reuse_policy, CAST(:metadata AS jsonb),
        :actor, :actor, :actor, clock_timestamp(), now()
    )
    ON CONFLICT (
        collection_id, external_item_id, external_component_id
    )
    DO UPDATE SET
        feature_id = EXCLUDED.feature_id,
        source_record_key = COALESCE(
            EXCLUDED.source_record_key,
            feature.curation_items.source_record_key
        ),
        place_name = EXCLUDED.place_name,
        address_hint = EXCLUDED.address_hint,
        source_present = true,
        source_updated_at = clock_timestamp(),
        status = EXCLUDED.status,
        sort_order = EXCLUDED.sort_order,
        item_title = EXCLUDED.item_title,
        item_summary = EXCLUDED.item_summary,
        curation_relation = EXCLUDED.curation_relation,
        reuse_policy = EXCLUDED.reuse_policy,
        metadata = EXCLUDED.metadata,
        updated_by = EXCLUDED.updated_by,
        operator_updated_by = EXCLUDED.operator_updated_by,
        operator_updated_at = clock_timestamp(),
        updated_at = now()
    WHERE (
        feature.curation_items.feature_id,
        feature.curation_items.source_record_key,
        feature.curation_items.place_name,
        feature.curation_items.address_hint,
        feature.curation_items.source_present,
        feature.curation_items.status,
        feature.curation_items.sort_order,
        feature.curation_items.item_title,
        feature.curation_items.item_summary,
        feature.curation_items.curation_relation,
        feature.curation_items.reuse_policy,
        feature.curation_items.metadata
    ) IS DISTINCT FROM (
        EXCLUDED.feature_id,
        COALESCE(EXCLUDED.source_record_key,
                 feature.curation_items.source_record_key),
        EXCLUDED.place_name,
        EXCLUDED.address_hint,
        true,
        EXCLUDED.status,
        EXCLUDED.sort_order,
        EXCLUDED.item_title,
        EXCLUDED.item_summary,
        EXCLUDED.curation_relation,
        EXCLUDED.reuse_policy,
        EXCLUDED.metadata
    )
    RETURNING curation_item_id::text, (xmax = 0) AS inserted
)
SELECT curation_item_id, inserted FROM written
UNION ALL
SELECT existing.curation_item_id::text, false
FROM feature.curation_items AS existing
WHERE existing.collection_id = CAST(:collection_id AS uuid)
  AND existing.external_item_id = :external_item_id
  AND existing.external_component_id = :external_component_id
  AND existing.archived_at IS NULL
  AND NOT EXISTS (SELECT 1 FROM written)
LIMIT 1
"""

_MARK_IMPORT_REMOVALS_SQL: Final[str] = (
    """
WITH incoming AS (
    SELECT *
    FROM jsonb_to_recordset(CAST(:items AS jsonb)) AS value(
        collection_id text,
        feature_id text,
        external_item_id text,
        external_component_id text
    )
), affected_collections AS (
    SELECT DISTINCT CAST(collection_id AS uuid) AS collection_id
    FROM incoming
), candidates AS MATERIALIZED (
    SELECT existing.*
    FROM feature.curation_items AS existing
    JOIN affected_collections
      ON affected_collections.collection_id = existing.collection_id
    WHERE existing.archived_at IS NULL
      AND existing.source_present
      AND NOT EXISTS (
          SELECT 1
          FROM incoming
          WHERE CAST(incoming.collection_id AS uuid) = existing.collection_id
            AND incoming.external_item_id = existing.external_item_id
            AND (
                incoming.external_component_id = existing.external_component_id
                OR (
                    incoming.feature_id IS NOT NULL
                    AND existing.feature_id = incoming.feature_id
                    AND existing.external_component_id LIKE 'legacy:%'
                    AND NOT EXISTS (
                        SELECT 1
                        FROM feature.curation_items AS exact_identity
                        WHERE exact_identity.collection_id =
                            existing.collection_id
                          AND exact_identity.external_item_id =
                              incoming.external_item_id
                          AND exact_identity.external_component_id =
                              incoming.external_component_id
                    )
                )
            )
      )
    FOR UPDATE OF existing
), marked AS (
    UPDATE feature.curation_items AS existing
    SET source_present = false,
        source_updated_at = clock_timestamp(),
        updated_by = :actor,
        row_revision = existing.row_revision + 1,
        updated_at = now()
    FROM candidates
    WHERE existing.curation_item_id = candidates.curation_item_id
    RETURNING candidates.*
)
SELECT
"""
    + _ITEM_SELECT_FIELDS
    + """
FROM marked AS i
JOIN feature.curation_collections AS c ON c.collection_id = i.collection_id
JOIN feature.curated_themes AS t ON t.theme_id = c.theme_id
LEFT JOIN feature.curated_sources AS s ON s.source_id = c.source_id
LEFT JOIN provider_sync.provider_datasets AS pd
  ON pd.provider_dataset_id = s.provider_dataset_id
LEFT JOIN feature.features AS f ON f.feature_id = i.feature_id
LEFT JOIN feature.curation_link_decisions AS link_decision
  ON link_decision.decision_id = i.accepted_link_decision_id
ORDER BY c.collection_key, i.sort_order, i.curation_item_id
"""
)

_LEGACY_IMPORT_ADOPTION_CONFLICTS_SQL: Final[str] = """
WITH incoming AS (
    SELECT *
    FROM jsonb_to_recordset(CAST(:items AS jsonb)) AS value(
        collection_key text,
        feature_id text,
        external_item_id text,
        external_component_id text
    )
), conflicts AS (
    SELECT
        incoming.collection_key,
        incoming.external_item_id,
        incoming.external_component_id,
        incoming.feature_id,
        array_agg(
            legacy.curation_item_id::text || ':' ||
            legacy.external_component_id || ':' ||
            CASE
                WHEN legacy.archived_at IS NULL THEN 'active'
                ELSE 'archived'
            END
            ORDER BY
                legacy.archived_at DESC NULLS LAST,
                legacy.curation_item_id
        ) AS candidates
    FROM incoming
    JOIN feature.curation_collections AS collection
      ON collection.collection_key = incoming.collection_key
    JOIN feature.curation_items AS legacy
      ON legacy.collection_id = collection.collection_id
     AND legacy.external_item_id = incoming.external_item_id
     AND legacy.feature_id = incoming.feature_id
     AND legacy.external_component_id LIKE 'legacy:%'
    WHERE incoming.feature_id IS NOT NULL
      AND NOT EXISTS (
          SELECT 1
          FROM feature.curation_items AS exact_identity
          WHERE exact_identity.collection_id = legacy.collection_id
            AND exact_identity.external_item_id = legacy.external_item_id
            AND exact_identity.external_component_id =
                incoming.external_component_id
      )
    GROUP BY
        incoming.collection_key,
        incoming.external_item_id,
        incoming.external_component_id,
        incoming.feature_id
    HAVING count(*) > 1
)
SELECT *
FROM conflicts
ORDER BY
    collection_key,
    external_item_id,
    external_component_id,
    feature_id
LIMIT 1
"""

_ADOPT_LEGACY_IMPORT_IDENTITIES_SQL: Final[str] = """
WITH incoming AS (
    SELECT *
    FROM jsonb_to_recordset(CAST(:items AS jsonb)) AS value(
        collection_id text,
        feature_id text,
        external_item_id text,
        external_component_id text,
        place_name text,
        address_hint text,
        sort_order integer,
        item_title text,
        item_summary text,
        metadata jsonb
    )
), matched AS MATERIALIZED (
    SELECT
        legacy.curation_item_id,
        incoming.external_component_id,
        incoming.place_name,
        incoming.address_hint,
        incoming.sort_order,
        incoming.item_title,
        incoming.item_summary,
        incoming.metadata,
        legacy.archived_at
    FROM incoming
    JOIN feature.curation_items AS legacy
      ON legacy.collection_id = CAST(incoming.collection_id AS uuid)
     AND legacy.external_item_id = incoming.external_item_id
     AND legacy.feature_id = incoming.feature_id
     AND legacy.external_component_id LIKE 'legacy:%'
    WHERE incoming.feature_id IS NOT NULL
      AND NOT EXISTS (
          SELECT 1
          FROM feature.curation_items AS exact_identity
          WHERE exact_identity.collection_id = legacy.collection_id
            AND exact_identity.external_item_id = legacy.external_item_id
            AND exact_identity.external_component_id =
                incoming.external_component_id
      )
    FOR UPDATE OF legacy
), written AS (
    UPDATE feature.curation_items AS legacy
    SET external_component_id = matched.external_component_id,
        place_name = CASE
            WHEN matched.archived_at IS NULL
            THEN matched.place_name
            ELSE legacy.place_name
        END,
        address_hint = CASE
            WHEN matched.archived_at IS NULL
            THEN matched.address_hint
            ELSE legacy.address_hint
        END,
        source_present = CASE
            WHEN matched.archived_at IS NULL
            THEN true
            ELSE legacy.source_present
        END,
        source_updated_at = CASE
            WHEN matched.archived_at IS NULL
            THEN clock_timestamp()
            ELSE legacy.source_updated_at
        END,
        sort_order = CASE
            WHEN matched.archived_at IS NULL
            THEN matched.sort_order
            ELSE legacy.sort_order
        END,
        item_title = CASE
            WHEN matched.archived_at IS NULL
            THEN matched.item_title
            ELSE legacy.item_title
        END,
        item_summary = CASE
            WHEN matched.archived_at IS NULL
            THEN matched.item_summary
            ELSE legacy.item_summary
        END,
        metadata = CASE
            WHEN matched.archived_at IS NULL
            THEN matched.metadata
            ELSE legacy.metadata
        END,
        updated_by = :actor,
        row_revision = legacy.row_revision + 1,
        updated_at = now()
    FROM matched
    WHERE legacy.curation_item_id = matched.curation_item_id
    RETURNING legacy.curation_item_id
)
SELECT count(*)::integer AS updated
FROM written
"""

_BULK_UPSERT_ITEMS_SQL: Final[str] = """
WITH incoming AS (
    SELECT *
    FROM jsonb_to_recordset(CAST(:items AS jsonb)) AS value(
        collection_id text,
        feature_id text,
        external_item_id text,
        external_component_id text,
        place_name text,
        address_hint text,
        sort_order integer,
        item_title text,
        item_summary text,
        metadata jsonb
    )
), written AS (
    INSERT INTO feature.curation_items (
        collection_id, feature_id, external_item_id, external_component_id,
        place_name, address_hint,
        source_present, source_updated_at, status, sort_order,
        item_title, item_summary, curation_relation, reuse_policy,
        metadata, created_by, updated_by, updated_at
    )
    SELECT
        CAST(incoming.collection_id AS uuid), incoming.feature_id,
        incoming.external_item_id, incoming.external_component_id,
        incoming.place_name, incoming.address_hint,
        true, clock_timestamp(), 'included', incoming.sort_order,
        incoming.item_title, incoming.item_summary, 'nearby_option',
        'manual_review', incoming.metadata, :actor, :actor, now()
    FROM incoming
    WHERE NOT EXISTS (
        SELECT 1
        FROM feature.curation_items AS tombstone
        WHERE tombstone.collection_id = CAST(incoming.collection_id AS uuid)
          AND tombstone.external_item_id = incoming.external_item_id
          AND tombstone.external_component_id = incoming.external_component_id
          AND tombstone.archived_at IS NOT NULL
    )
    ON CONFLICT (
        collection_id, external_item_id, external_component_id
    )
    -- status/curation_relation/reuse_policy는 CSV에 없는 하드코딩 default이며
    -- 운영자가 admin PATCH로 조정하는 override 필드다. authoritative 재적재가 이를
    -- 무조건 EXCLUDED default로 되돌리면 수동 큐레이션이 리셋되므로(#699), CONFLICT
    -- 경로에서는 이 3개를 갱신·비교에서 제외해 기존(운영자) 값을 보존한다.
    -- 반대로 제공자 파생 필드(place_name/address_hint/sort_order/item_title/item_summary/
    -- metadata)는 CSV가 정본이므로 운영자가 PATCH로 편집했더라도 재적재로 덮어쓴다(의도된 경계).
    DO UPDATE SET
        feature_id = EXCLUDED.feature_id,
        place_name = EXCLUDED.place_name,
        address_hint = EXCLUDED.address_hint,
        source_present = true,
        source_updated_at = clock_timestamp(),
        sort_order = EXCLUDED.sort_order,
        item_title = EXCLUDED.item_title,
        item_summary = EXCLUDED.item_summary,
        metadata = EXCLUDED.metadata,
        updated_by = EXCLUDED.updated_by,
        row_revision = feature.curation_items.row_revision + 1,
        updated_at = now()
    WHERE (
        feature.curation_items.feature_id,
        feature.curation_items.source_present,
        feature.curation_items.place_name,
        feature.curation_items.address_hint,
        feature.curation_items.sort_order,
        feature.curation_items.item_title,
        feature.curation_items.item_summary,
        feature.curation_items.metadata
    ) IS DISTINCT FROM (
        EXCLUDED.feature_id,
        true,
        EXCLUDED.place_name,
        EXCLUDED.address_hint,
        EXCLUDED.sort_order,
        EXCLUDED.item_title,
        EXCLUDED.item_summary,
        EXCLUDED.metadata
    )
    RETURNING (xmax = 0) AS inserted
)
SELECT
    count(*) FILTER (WHERE inserted)::integer AS inserted,
    count(*) FILTER (WHERE NOT inserted)::integer AS updated
FROM written
"""

_INSERT_IMPORT_BATCH_SQL: Final[str] = """
INSERT INTO feature.curation_import_batches (
    content_sha256, batch_kind, row_count, actor, metadata, command_id
) VALUES (
    :content_sha256, :batch_kind, :row_count, :actor, CAST(:metadata AS jsonb),
    :command_id
)
RETURNING import_batch_id::text
"""

_IMPORT_ITEM_IDENTITIES_SQL: Final[str] = """
WITH incoming AS (
    SELECT *
    FROM jsonb_to_recordset(CAST(:items AS jsonb)) AS value(
        row_number integer,
        collection_key text,
        external_item_id text,
        external_component_id text
    )
)
SELECT
    incoming.row_number,
    item.curation_item_id::text AS curation_item_id,
    item.feature_id,
    item.archived_at,
    item.accepted_link_decision_id::text AS accepted_link_decision_id,
    previous_decision.feature_id AS previous_decision_feature_id
FROM incoming
JOIN feature.curation_collections AS collection
  ON collection.collection_key = incoming.collection_key
JOIN feature.curation_items AS item
  ON item.collection_id = collection.collection_id
 AND item.external_item_id = incoming.external_item_id
 AND item.external_component_id = incoming.external_component_id
LEFT JOIN feature.curation_link_decisions AS previous_decision
  ON previous_decision.decision_id = item.accepted_link_decision_id
ORDER BY incoming.row_number
"""

_INSERT_IMPORT_ROWS_SQL: Final[str] = """
INSERT INTO feature.curation_import_rows (
    import_row_id, import_batch_id, curation_item_id, row_number,
    source_row_sha256, row_payload, provenance
)
SELECT
    CAST(value.import_row_id AS uuid),
    CAST(:import_batch_id AS uuid),
    CAST(value.curation_item_id AS uuid),
    value.row_number,
    value.source_row_sha256,
    value.row_payload,
    value.provenance
FROM jsonb_to_recordset(CAST(:rows AS jsonb)) AS value(
    import_row_id text,
    curation_item_id text,
    row_number integer,
    source_row_sha256 text,
    row_payload jsonb,
    provenance jsonb
)
"""

_INSERT_LINK_DECISIONS_SQL: Final[str] = """
INSERT INTO feature.curation_link_decisions (
    decision_id, curation_item_id, feature_id, import_row_id,
    decision_kind, match_basis, resolver_version, evidence, actor,
    supersedes_decision_id
)
SELECT
    CAST(value.decision_id AS uuid),
    CAST(value.curation_item_id AS uuid),
    value.feature_id,
    CAST(value.import_row_id AS uuid),
    value.decision_kind,
    value.match_basis,
    value.resolver_version,
    value.evidence,
    :actor,
    CAST(value.supersedes_decision_id AS uuid)
FROM jsonb_to_recordset(CAST(:decisions AS jsonb)) AS value(
    decision_id text,
    curation_item_id text,
    feature_id text,
    import_row_id text,
    decision_kind text,
    match_basis text,
    resolver_version text,
    evidence jsonb,
    supersedes_decision_id text
)
"""

_ADVANCE_IMPORT_POINTERS_SQL: Final[str] = """
WITH pointers AS (
    SELECT *
    FROM jsonb_to_recordset(CAST(:pointers AS jsonb)) AS value(
        curation_item_id text,
        import_row_id text,
        accepted_link_decision_id text
    )
)
UPDATE feature.curation_items AS item
SET current_import_row_id = CAST(pointers.import_row_id AS uuid),
    accepted_link_decision_id =
        CAST(pointers.accepted_link_decision_id AS uuid)
FROM pointers
WHERE item.curation_item_id = CAST(pointers.curation_item_id AS uuid)
"""

_INSERT_MANUAL_LINK_DECISION_SQL: Final[str] = """
INSERT INTO feature.curation_link_decisions (
    curation_item_id, feature_id, decision_kind, match_basis,
    resolver_version, evidence, actor, supersedes_decision_id
) VALUES (
    CAST(:curation_item_id AS uuid),
    :feature_id,
    :decision_kind,
    :match_basis,
    :resolver_version,
    CAST(:evidence AS jsonb),
    :actor,
    CAST(:supersedes_decision_id AS uuid)
)
RETURNING decision_id::text
"""

_LIST_UNATTRIBUTED_LINKS_SQL: Final[str] = """
SELECT
    collection.collection_id::text AS collection_id,
    item.curation_item_id::text AS curation_item_id,
    collection.collection_key,
    item.external_item_id,
    item.external_component_id,
    item.feature_id,
    item.place_name,
    item.address_hint,
    decision.match_basis,
    decision.resolver_version,
    decision.decided_at
FROM feature.curation_items AS item
JOIN feature.curation_collections AS collection
  ON collection.collection_id = item.collection_id
LEFT JOIN feature.curation_link_decisions AS decision
  ON decision.decision_id = item.accepted_link_decision_id
WHERE item.feature_id IS NOT NULL
  AND item.archived_at IS NULL
  AND item.source_present
  AND (
      CAST(:cursor_collection_id AS uuid) IS NULL
      OR (collection.collection_id, item.curation_item_id) > (
          CAST(:cursor_collection_id AS uuid),
          CAST(:cursor_curation_item_id AS uuid)
      )
  )
  AND (
      decision.decision_id IS NULL
      OR decision.decision_kind <> 'accepted'
      OR decision.match_basis = 'legacy_unattributed'
  )
ORDER BY collection.collection_id, item.curation_item_id
LIMIT :limit
"""

# `0065`가 quarantine collection에 박는 정본 marker 술어 그대로 읽는다
# (원래 `src/kortravelmap/cli/_h35_schema.py`의 `_QUARANTINE_COUNT_SQL`과 같은
#  질의였다. 그 모듈은 T-VN-C01(2026-08-18)에서 퇴역했고 여기가 정본이다.)
# `created_by`만 보면 `0065`가 만든 다른 행과 섞이므로 metadata marker를 함께 요구한다.
_QUARANTINE_MARKER_JSONB: Final[str] = """'{"migration_quarantine": "0065"}'::jsonb"""


def _quarantine_marker_sql(alias: str) -> str:
    return (
        f"{alias}.created_by = 'migration:0065' AND {alias}.metadata @> " + _QUARANTINE_MARKER_JSONB
    )


# item_count는 archived/source-absent를 포함한 물리 행 수다 — move는 행 전체를
# 옮기므로 격리가 실제로 붙들고 있는 수량이 운영자에게 맞는 값이다.
# marker_intact는 정본 술어로 잡힌 행에서 항상 true지만(운영자가 PATCH로 지운 행은
# 아예 안 잡힌다), original_collection 존재 여부와 함께 신뢰도 표시용으로 유지한다.
# original은 marker가 기록한 uuid 텍스트로 되짚은 **현재** 행이다 — 추천이 아니라
# 병렬 표시 전용이며 잘못된 기록값에도 cast 오류 없이 미존재로 떨어지도록 text 비교한다.
_LIST_QUARANTINE_COLLECTIONS_SQL: Final[str] = f"""
SELECT
    quarantine.collection_id::text AS collection_id,
    quarantine.row_revision,
    quarantine.collection_key,
    quarantine.title,
    quarantine.edition_key,
    quarantine.status,
    quarantine.visibility,
    quarantine.created_by,
    quarantine.metadata,
    (
        SELECT count(*)::integer
        FROM feature.curation_items AS quarantined_item
        WHERE quarantined_item.collection_id = quarantine.collection_id
    ) AS item_count,
    ({_quarantine_marker_sql("quarantine")}) AS marker_intact,
    quarantine_theme.theme_id::text AS quarantine_theme_id,
    quarantine_theme.theme_slug AS quarantine_theme_slug,
    quarantine_theme.theme_name AS quarantine_theme_name,
    quarantine_theme.theme_group AS quarantine_theme_group,
    quarantine_theme.visibility AS quarantine_theme_visibility,
    quarantine_source.source_id::text AS quarantine_source_id,
    quarantine_source.provider_dataset_id AS quarantine_provider_dataset_id,
    quarantine_dataset.provider AS quarantine_provider,
    quarantine_dataset.dataset_key AS quarantine_dataset_key,
    quarantine_source.source_name AS quarantine_source_name,
    original.collection_id::text AS original_collection_id,
    original.row_revision AS original_row_revision,
    original.title AS original_title,
    original.status AS original_status,
    original.visibility AS original_visibility,
    original_theme.theme_id::text AS original_theme_id,
    original_theme.theme_slug AS original_theme_slug,
    original_theme.theme_name AS original_theme_name,
    original_theme.theme_group AS original_theme_group,
    original_theme.visibility AS original_theme_visibility,
    original_source.source_id::text AS original_source_id,
    original_source.provider_dataset_id AS original_provider_dataset_id,
    original_dataset.provider AS original_provider,
    original_dataset.dataset_key AS original_dataset_key,
    original_source.source_name AS original_source_name
FROM feature.curation_collections AS quarantine
JOIN feature.curated_themes AS quarantine_theme
  ON quarantine_theme.theme_id = quarantine.theme_id
LEFT JOIN feature.curated_sources AS quarantine_source
  ON quarantine_source.source_id = quarantine.source_id
LEFT JOIN provider_sync.provider_datasets AS quarantine_dataset
  ON quarantine_dataset.provider_dataset_id = quarantine_source.provider_dataset_id
LEFT JOIN feature.curation_collections AS original
  ON original.collection_id::text = quarantine.metadata ->> 'original_collection_id'
LEFT JOIN feature.curated_themes AS original_theme
  ON original_theme.theme_id = original.theme_id
LEFT JOIN feature.curated_sources AS original_source
  ON original_source.source_id = original.source_id
LEFT JOIN provider_sync.provider_datasets AS original_dataset
  ON original_dataset.provider_dataset_id = original_source.provider_dataset_id
WHERE {_quarantine_marker_sql("quarantine")}
  AND (
      CAST(:cursor_collection_id AS uuid) IS NULL
      OR quarantine.collection_id > CAST(:cursor_collection_id AS uuid)
  )
ORDER BY quarantine.collection_id
LIMIT :limit
"""

_GET_QUARANTINE_COLLECTION_SQL: Final[str] = f"""
SELECT
    quarantine.collection_id::text AS collection_id,
    quarantine.metadata
FROM feature.curation_collections AS quarantine
WHERE quarantine.collection_id = CAST(:collection_id AS uuid)
  AND {_quarantine_marker_sql("quarantine")}
"""


def _quarantine_conflict_lateral_sql(item_alias: str) -> str:
    """(A)/(B) 두 unique 제약을 target collection에 대해 선검사하는 LATERAL 2개.

    - (A) ``uq_curation_items_component_identity``는 **partial이 아니다** — 상대의
      archived/source_present와 무관하게 걸리므로 어떤 필터도 붙이면 안 된다.
    - (B) ``uq_curation_items_active_source_feature``는 partial unique — **양쪽 다**
      ``source_present AND archived_at IS NULL AND feature_id IS NOT NULL``일 때만
      걸린다 (``occupant.feature_id = item.feature_id`` 등호가 NOT NULL을 함의).
    """

    return f"""
LEFT JOIN LATERAL (
    SELECT occupant.curation_item_id
    FROM feature.curation_items AS occupant
    WHERE occupant.collection_id = CAST(:target_collection_id AS uuid)
      AND occupant.external_item_id = {item_alias}.external_item_id
      AND occupant.external_component_id = {item_alias}.external_component_id
    LIMIT 1
) AS component_conflict ON true
LEFT JOIN LATERAL (
    SELECT occupant.curation_item_id
    FROM feature.curation_items AS occupant
    WHERE {item_alias}.source_present
      AND {item_alias}.archived_at IS NULL
      AND occupant.collection_id = CAST(:target_collection_id AS uuid)
      AND occupant.external_item_id = {item_alias}.external_item_id
      AND occupant.feature_id = {item_alias}.feature_id
      AND occupant.source_present
      AND occupant.archived_at IS NULL
    LIMIT 1
) AS active_feature_conflict ON true
"""


_LIST_QUARANTINE_ITEMS_SQL: Final[str] = f"""
SELECT
    quarantined.curation_item_id::text AS curation_item_id,
    quarantined.external_item_id,
    quarantined.external_component_id,
    quarantined.feature_id,
    quarantined.place_name,
    quarantined.status,
    quarantined.source_present,
    quarantined.archived_at,
    component_conflict.curation_item_id::text AS component_conflict_item_id,
    active_feature_conflict.curation_item_id::text AS active_feature_conflict_item_id
FROM feature.curation_items AS quarantined
{_quarantine_conflict_lateral_sql("quarantined")}
WHERE quarantined.collection_id = CAST(:collection_id AS uuid)
  AND (
      CAST(:cursor_curation_item_id AS uuid) IS NULL
      OR quarantined.curation_item_id > CAST(:cursor_curation_item_id AS uuid)
  )
ORDER BY quarantined.curation_item_id
LIMIT :limit
"""

_QUARANTINE_MOVE_CONFLICTS_SQL: Final[str] = f"""
SELECT
    quarantined.curation_item_id::text AS curation_item_id,
    component_conflict.curation_item_id::text AS component_conflict_item_id,
    active_feature_conflict.curation_item_id::text AS active_feature_conflict_item_id
FROM feature.curation_items AS quarantined
{_quarantine_conflict_lateral_sql("quarantined")}
WHERE quarantined.curation_item_id = ANY(CAST(:item_ids AS uuid[]))
  AND (
      component_conflict.curation_item_id IS NOT NULL
      OR active_feature_conflict.curation_item_id IS NOT NULL
  )
ORDER BY quarantined.curation_item_id
"""

_LOCK_QUARANTINE_AND_TARGET_SQL: Final[str] = """
SELECT
    locked.collection_id::text AS collection_id,
    locked.created_by,
    locked.metadata,
    locked.archived_at
FROM feature.curation_collections AS locked
WHERE locked.collection_id = ANY(CAST(:collection_ids AS uuid[]))
ORDER BY locked.collection_id
FOR UPDATE OF locked
"""

_GET_IMPORT_BATCH_SQL: Final[str] = """
SELECT
    import_batch_id::text AS import_batch_id,
    content_sha256,
    batch_kind,
    row_count,
    actor,
    metadata,
    imported_at
FROM feature.curation_import_batches
WHERE import_batch_id = CAST(:import_batch_id AS uuid)
"""

_LIST_IMPORT_BATCH_ROWS_SQL: Final[str] = """
SELECT
    import_row_id::text AS import_row_id,
    import_batch_id::text AS import_batch_id,
    curation_item_id::text AS curation_item_id,
    row_number,
    source_row_sha256,
    row_payload,
    provenance,
    imported_at
FROM feature.curation_import_rows
WHERE import_batch_id = CAST(:import_batch_id AS uuid)
ORDER BY row_number, import_row_id
"""

_GET_CURRENT_IMPORT_ROW_SQL: Final[str] = """
SELECT
    import_row.import_row_id::text AS import_row_id,
    import_row.import_batch_id::text AS import_batch_id,
    import_row.curation_item_id::text AS curation_item_id,
    import_row.row_number,
    import_row.source_row_sha256,
    import_row.row_payload,
    import_row.provenance,
    import_row.imported_at
FROM feature.curation_items AS item
JOIN feature.curation_import_rows AS import_row
  ON import_row.import_row_id = item.current_import_row_id
 AND import_row.curation_item_id = item.curation_item_id
WHERE item.curation_item_id = CAST(:curation_item_id AS uuid)
"""

_PREVIEW_IMPORT_COUNTS_SQL: Final[str] = """
WITH incoming AS (
    SELECT *
    FROM jsonb_to_recordset(CAST(:items AS jsonb)) AS value(
        collection_key text,
        feature_id text,
        external_item_id text,
        external_component_id text,
        place_name text,
        address_hint text,
        sort_order integer,
        item_title text,
        item_summary text,
        metadata jsonb
    )
), classified AS (
    SELECT
        (
            existing.curation_item_id IS NOT NULL
            OR EXISTS (
                SELECT 1
                FROM feature.curation_items AS tombstone
                WHERE tombstone.collection_id = collection.collection_id
                  AND tombstone.external_item_id = incoming.external_item_id
                  AND tombstone.external_component_id =
                      incoming.external_component_id
                  AND tombstone.archived_at IS NOT NULL
            )
        ) AS already_exists,
        existing.curation_item_id IS NOT NULL
        -- 실제 upsert가 CONFLICT에서 status/curation_relation/reuse_policy를 보존하므로
        -- (#699) dry-run preview도 이 3개를 needs_update 비교에서 제외해 "updated" 카운트를
        -- 실제 동작과 일치시킨다(운영자 편집만 다른 행을 updated로 오표시하지 않음).
        AND (
            existing.external_component_id IS DISTINCT FROM
                incoming.external_component_id
            OR existing.feature_id IS DISTINCT FROM incoming.feature_id
            OR NOT existing.source_present
            OR (
                existing.place_name,
                existing.address_hint,
                existing.sort_order,
                existing.item_title,
                existing.item_summary,
                existing.metadata
            ) IS DISTINCT FROM (
                incoming.place_name,
                incoming.address_hint,
                incoming.sort_order,
                incoming.item_title,
                incoming.item_summary,
                incoming.metadata
            )
        ) AS needs_update
    FROM incoming
    LEFT JOIN feature.curation_collections AS collection
      ON collection.collection_key = incoming.collection_key
    LEFT JOIN LATERAL (
        SELECT candidate.*
        FROM feature.curation_items AS candidate
        WHERE candidate.collection_id = collection.collection_id
          AND candidate.external_item_id = incoming.external_item_id
          AND (
              (
                  candidate.external_component_id =
                      incoming.external_component_id
                  AND candidate.archived_at IS NULL
              )
              OR (
                  incoming.feature_id IS NOT NULL
                  AND candidate.feature_id = incoming.feature_id
                  AND candidate.external_component_id LIKE 'legacy:%'
                  AND NOT EXISTS (
                      SELECT 1
                      FROM feature.curation_items AS exact_identity
                      WHERE exact_identity.collection_id =
                          collection.collection_id
                        AND exact_identity.external_item_id =
                            incoming.external_item_id
                        AND exact_identity.external_component_id =
                            incoming.external_component_id
                  )
              )
          )
        ORDER BY
            (
                candidate.external_component_id =
                incoming.external_component_id
            ) DESC
        LIMIT 1
    ) AS existing ON true
)
SELECT
    count(*) FILTER (WHERE NOT already_exists)::integer AS inserted,
    count(*) FILTER (WHERE needs_update)::integer AS updated
FROM classified
"""


def _replace_once(sql: str, old: str, new: str) -> str:
    """고정-세대 변형이 **조용히 no-op** 되는 것을 import 시점에 차단한다.

    ``str.replace``는 needle 표기가 drift하면 원본을 그대로 돌려주고, 그 실패는
    0063~0079 고정 세대를 실제로 띄우는 h35 리허설에서만 UndefinedColumn /
    UndefinedTable로 뒤늦게 드러난다(적대 리뷰 2 권고).
    """

    if sql.count(old) != 1:
        raise RuntimeError(f"고정-세대 SQL 변형 needle이 정확히 1회가 아닙니다: {old!r}")
    return sql.replace(old, new, 1)


# h35 cutover CLI 전용 — 0063 고정(pre-0080, feature_uuid column 부재) 스키마
# 세대에서 같은 import 경로를 돌린다 (역사 표면 보존, ADR-075).
_MARK_IMPORT_REMOVALS_PRE_UUID_SQL: Final[str] = _replace_once(
    _replace_once(
        _replace_once(
            _replace_once(
                _MARK_IMPORT_REMOVALS_SQL,
                "CAST(f.feature_uuid AS text) AS feature_uuid",
                "NULL::text AS feature_uuid",
            ),
            # 0085가 신설한 ``feature.feature_notices``도 그 세대엔 없다 — 당시의
            # detail 문자열 판정으로 되돌린다(T-VN-35).
            #
            # ``_PREVIEW_IMPORT_REMOVALS_SQL``에는 같은 변형을 두지 않는다. preview는
            # h35 replay 경로(``run_csv5``)에서 호출되지 않고 현행 스키마에서만 도므로,
            # 고정-세대 변형을 만들면 아무도 실행하지 않는 두 번째 SQL이 생긴다.
            _ITEM_PUBLIC_NOTICE_FILTER_SQL,
            public_active_notice_filter_sql("pf", frozen_h35_schema=True),
        ),
        # T-VN-33은 자연키를 ``provider_sync.provider_datasets`` projection으로
        # 옮겼지만, 그 catalog를 만드는 것은 0089다. 고정 세대에서 자연키는
        # ``feature.curated_sources``에 그대로 있고 surrogate는 존재하지 않는다.
        "    s.provider_dataset_id,\n    pd.provider,\n    pd.dataset_key,",
        "    NULL::bigint AS provider_dataset_id,\n    s.provider,\n    s.dataset_key,",
    ),
    "LEFT JOIN provider_sync.provider_datasets AS pd\n"
    "  ON pd.provider_dataset_id = s.provider_dataset_id\n",
    "",
)
_MARK_IMPORT_REMOVALS_PRE_UUID_NO_REVISION_SQL: Final[str] = _replace_once(
    _MARK_IMPORT_REMOVALS_PRE_UUID_SQL,
    "        row_revision = existing.row_revision + 1,\n",
    "",
)
_ADOPT_LEGACY_IMPORT_IDENTITIES_PRE_REVISION_SQL: Final[str] = _replace_once(
    _ADOPT_LEGACY_IMPORT_IDENTITIES_SQL,
    "        row_revision = legacy.row_revision + 1,\n",
    "",
)
_BULK_UPSERT_ITEMS_PRE_REVISION_SQL: Final[str] = _replace_once(
    _BULK_UPSERT_ITEMS_SQL,
    "        row_revision = feature.curation_items.row_revision + 1,\n",
    "",
)

_PREVIEW_IMPORT_REMOVALS_SQL: Final[str] = (
    _ITEM_SELECT
    + """
WHERE i.archived_at IS NULL
  AND i.source_present
  AND EXISTS (
      SELECT 1
      FROM jsonb_to_recordset(CAST(:items AS jsonb)) AS incoming(
          collection_key text,
          feature_id text,
          external_item_id text,
          external_component_id text
      )
      WHERE incoming.collection_key = c.collection_key
  )
  AND NOT EXISTS (
      SELECT 1
      FROM jsonb_to_recordset(CAST(:items AS jsonb)) AS incoming(
          collection_key text,
          feature_id text,
          external_item_id text,
          external_component_id text
      )
      WHERE incoming.collection_key = c.collection_key
        AND incoming.external_item_id = i.external_item_id
        AND (
            incoming.external_component_id = i.external_component_id
            OR (
                incoming.feature_id IS NOT NULL
                AND i.feature_id = incoming.feature_id
                AND i.external_component_id LIKE 'legacy:%'
                AND NOT EXISTS (
                    SELECT 1
                    FROM feature.curation_items AS exact_identity
                    WHERE exact_identity.collection_id = i.collection_id
                      AND exact_identity.external_item_id =
                          incoming.external_item_id
                      AND exact_identity.external_component_id =
                          incoming.external_component_id
                )
            )
        )
  )
ORDER BY c.collection_key, i.sort_order, i.curation_item_id
"""
)

_RESOLVE_THEME_SQL: Final[str] = """
SELECT theme_id::text
FROM feature.curated_themes
WHERE theme_slug = :theme_slug
  AND theme_name = :theme_name
  AND theme_group = :theme_group
  AND archived_at IS NULL
"""

_RESOLVE_SOURCE_SQL: Final[str] = """
SELECT source_id::text
FROM feature.curated_sources
WHERE provider_dataset_id = :provider_dataset_id
  AND source_name = :source_name
  AND source_url IS NOT DISTINCT FROM :source_url
  AND archived_at IS NULL
"""

_UPSERT_COLLECTION_SQL: Final[str] = """
WITH written AS (
    INSERT INTO feature.curation_collections (
        collection_key, theme_id, source_id, title, edition_key, status,
        visibility, metadata, created_by, updated_by, updated_at
    ) VALUES (
        :collection_key, CAST(:theme_id AS uuid), CAST(:source_id AS uuid),
        :title, :edition_key, 'published', 'public', '{}'::jsonb,
        :actor, :actor, now()
    )
    ON CONFLICT (collection_key) DO UPDATE SET
        theme_id = EXCLUDED.theme_id,
        source_id = EXCLUDED.source_id,
        title = EXCLUDED.title,
        edition_key = EXCLUDED.edition_key,
        status = 'published',
        visibility = 'public',
        updated_by = EXCLUDED.updated_by,
        updated_at = now(),
        archived_at = NULL
    WHERE (
        feature.curation_collections.theme_id,
        feature.curation_collections.source_id,
        feature.curation_collections.title,
        feature.curation_collections.edition_key,
        feature.curation_collections.status,
        feature.curation_collections.visibility,
        feature.curation_collections.archived_at IS NULL
    ) IS DISTINCT FROM (
        EXCLUDED.theme_id,
        EXCLUDED.source_id,
        EXCLUDED.title,
        EXCLUDED.edition_key,
        'published'::text,
        'public'::text,
        true
    )
    RETURNING collection_id::text
)
SELECT collection_id FROM written
UNION ALL
SELECT existing.collection_id::text
FROM feature.curation_collections AS existing
WHERE existing.collection_key = :collection_key
  AND NOT EXISTS (SELECT 1 FROM written)
LIMIT 1
"""

# h35 cutover CLI 전용 — 0063~0079 고정 세대의 ``feature.curated_sources``는
# ``(provider, dataset_key)`` 자연키가 곧 identity이고 ``provider_dataset_id``
# 열도 그 열을 채울 ``provider_sync.provider_datasets`` catalog도 없다(둘 다
# 0089/0090이 만든다). 그 세대의 write 표면을 **바이트로 고정**해 보존한다
# (역사 표면 보존, ADR-075 — ``feature_repo._frozen_h35_*``와 같은 규약).
_FROZEN_H35_UPSERT_SOURCE_SQL: Final[str] = """
WITH written AS (
    INSERT INTO feature.curated_sources (
        provider, dataset_key, source_name, source_url, source_kind,
        update_cycle, provider_status, metadata, updated_at
    ) VALUES (
        :provider, :dataset_key, :source_name, :source_url, 'manual',
        'unknown', 'manual_only', '{}'::jsonb, now()
    )
    ON CONFLICT (provider, dataset_key) DO UPDATE SET
        source_name = EXCLUDED.source_name,
        source_url = COALESCE(
            EXCLUDED.source_url,
            feature.curated_sources.source_url
        ),
        updated_at = now()
    WHERE (
        feature.curated_sources.source_name,
        feature.curated_sources.source_url
    ) IS DISTINCT FROM (
        EXCLUDED.source_name,
        COALESCE(EXCLUDED.source_url, feature.curated_sources.source_url)
    )
    RETURNING source_id::text
)
SELECT source_id FROM written
UNION ALL
SELECT existing.source_id::text
FROM feature.curated_sources AS existing
WHERE existing.provider = :provider
  AND existing.dataset_key = :dataset_key
  AND NOT EXISTS (SELECT 1 FROM written)
LIMIT 1
"""

_FROZEN_H35_GET_SOURCE_ID_BY_KEY_SQL: Final[str] = """
SELECT source_id::text
FROM feature.curated_sources
WHERE provider = :provider
  AND dataset_key = :dataset_key
"""

_GET_COLLECTION_ID_BY_KEY_SQL: Final[str] = """
SELECT collection_id::text
FROM feature.curation_collections
WHERE collection_key = :collection_key
"""


def _active_feature_state_sql(feature_alias: str, *, frozen_h35_schema: bool = False) -> str:
    """큐레이션이 "붙일 수 있는 Feature"로 보는 상태 술어를 반환한다.

    이 규칙의 내용은 "은퇴하지 않았고, 감춰지지도 않았다"이다. draft와 broken은
    후보에서 빼지 않는다 — 큐레이터가 손대는 대상이 바로 그런 행이기 때문이다.

    ``frozen_h35_schema``: H35 cutover 리허설 전용. 그 경로는 **0063~0079로 고정된
    과거 스키마**를 재생하는데, 3축 column은 0095가 처음 만든 것이라 그 세대에는
    존재하지 않는다. 같은 규칙을 그 세대의 정본 column으로 적는다. 두 표기가 같은
    집합을 고른다는 것은 0095 backfill이 정의한 바 그대로다 —
    ``deleted_at IS NOT NULL``이 lifecycle ``retired``가 되었고
    ``status IN ('deleted','hidden')``이 publication ``suppressed``가 되었으므로,
    각각의 부정인 ``deleted_at IS NULL``과 ``status NOT IN ('deleted','hidden')``이
    ``lifecycle='active'``와 ``publication <> 'suppressed'``에 그대로 대응한다.
    """

    if not feature_alias.isidentifier():
        raise ValueError("feature alias must be a SQL identifier")
    if frozen_h35_schema:
        return (
            f"{feature_alias}.deleted_at IS NULL "
            f"AND {feature_alias}.status NOT IN ('deleted', 'hidden')"
        )
    return (
        f"{feature_alias}.lifecycle_state = 'active' "
        f"AND {feature_alias}.publication_state <> 'suppressed'"
    )

# T-VN-32C PR-2 — 응답 후보 표시에 feature_uuid가 필요하지만, h35 cutover CLI는
# 0063 고정(pre-feature_uuid) 스키마에서 같은 matcher를 돌린다(역사 표면 보존,
# ADR-075). column 참조를 template slot으로 분리해 두 스키마 세대를 모두 지원한다.
#
# T-VN-34 이식 정정 — 이 matcher와 아래 세 가드의 legacy 술어는
# ``deleted_at IS NULL AND status NOT IN ('deleted','hidden')``이었다. 0095 backfill로
# 환산하면 ``lifecycle_state='active' AND publication_state <> 'suppressed'``다.
# ``deleted_at IS NULL``이 lifecycle 축을, ``NOT IN ('deleted','hidden')``이 publication
# 축을 각각 담당한다. 전환이 publication을 quality로 바꿔치기해 두었는데 그것은 두
# 방향으로 틀렸다 — 감춰진(suppressed) feature가 큐레이션 후보·연결 대상으로 다시
# 올라오고, legacy가 허용하던 broken(=quarantined) feature는 반대로 배제됐다.
# 6976e875가 curated_repo의 같은 술어를 "publication<>'suppressed', quality 무제약"으로
# 정정한 것과 같은 규칙을 여기에도 적용한다.
#
# 그 3축 표기는 **현행(0095~) 세대에서만** 성립한다. 위 h35 고정 세대는 0095 이전이라
# 3축 column 자체가 없으므로, 같은 의미를 그 세대의 정본 column으로 적은 변형이 따로
# 필요하다 — `_active_feature_state_sql`이 두 세대를 한 곳에서 관리한다.
_RESOLVE_FEATURES_BATCH_SQL_TEMPLATE: Final[str] = """
WITH requested AS (
    SELECT *
    FROM jsonb_to_recordset(CAST(:requests AS jsonb)) AS value(
        row_number integer,
        feature_id text,
        place_name text,
        address_hint text
    )
)
SELECT
    requested.row_number,
    matched.feature_id,
    matched.feature_uuid,
    matched.name,
    matched.address,
    matched.lon,
    matched.lat,
    matched.name_candidate_count
FROM requested
CROSS JOIN LATERAL (
    (
        SELECT
            f.feature_id,
            {feature_uuid_select} AS feature_uuid,
            f.name,
            f.address,
            x_extension.ST_X(f.coord) AS lon,
            x_extension.ST_Y(f.coord) AS lat,
            1::bigint AS name_candidate_count
        FROM feature.features AS f
        WHERE requested.feature_id IS NOT NULL
          AND f.feature_id = requested.feature_id
          AND {active_feature_state}
    )
    UNION ALL
    (
        SELECT
            f.feature_id,
            {feature_uuid_select} AS feature_uuid,
            f.name,
            f.address,
            x_extension.ST_X(f.coord) AS lon,
            x_extension.ST_Y(f.coord) AS lat,
            count(*) OVER () AS name_candidate_count
        FROM feature.features AS f
        WHERE requested.feature_id IS NULL
          AND requested.place_name IS NOT NULL
          AND lower(f.name) = lower(requested.place_name)
          AND {active_feature_state}
        ORDER BY f.feature_id
        LIMIT 101
    )
) AS matched
ORDER BY requested.row_number, matched.feature_id
"""

_RESOLVE_FEATURES_BATCH_SQL: Final[str] = _RESOLVE_FEATURES_BATCH_SQL_TEMPLATE.format(
    feature_uuid_select="CAST(f.feature_uuid AS text)",
    active_feature_state=_active_feature_state_sql("f"),
)

# h35 CLI 전용 — feature_uuid column(0080)도 상태 3축 column(0095)도 없는 고정 세대.
_RESOLVE_FEATURES_BATCH_PRE_UUID_SQL: Final[str] = _RESOLVE_FEATURES_BATCH_SQL_TEMPLATE.format(
    feature_uuid_select="NULL::text",
    active_feature_state=_active_feature_state_sql("f", frozen_h35_schema=True),
)


async def _upsert_id_with_fallback(
    session: AsyncSession,
    *,
    upsert_sql: str,
    lookup_sql: str,
    params: Mapping[str, Any],
    entity: str,
) -> str:
    """동시 insert가 현재 statement snapshot에 없을 때 새 snapshot으로 재조회한다."""

    value = (await session.execute(text(upsert_sql), dict(params))).scalar_one_or_none()
    if value is None:
        # PostgreSQL ON CONFLICT는 statement 시작 뒤 commit된 conflict row를 처리할 수
        # 있지만, 같은 statement의 UNION SELECT snapshot에서는 그 row가 안 보인다.
        value = (await session.execute(text(lookup_sql), dict(params))).scalar_one_or_none()
    if value is None:
        raise RuntimeError(f"concurrent {entity} upsert row disappeared")
    return str(value)


def _object(value: Any) -> dict[str, Any]:
    if isinstance(value, str):
        value = json.loads(value)
    return dict(value) if isinstance(value, Mapping) else {}


def _collection(row: RowMapping | Mapping[str, Any]) -> CurationCollection:
    return CurationCollection(
        collection_id=str(row["collection_id"]),
        collection_key=str(row["collection_key"]),
        theme_id=str(row["theme_id"]),
        theme_slug=str(row["theme_slug"]),
        theme_name=str(row["theme_name"]),
        theme_group=str(row["theme_group"]),
        source_id=str(row["source_id"]) if row["source_id"] else None,
        provider_dataset_id=(
            int(row["provider_dataset_id"])
            if row["provider_dataset_id"] is not None
            else None
        ),
        provider=row["provider"],
        dataset_key=row["dataset_key"],
        source_name=row["source_name"],
        source_url=row["source_url"],
        title=str(row["title"]),
        edition_key=str(row["edition_key"]),
        description=row["description"],
        status=str(row["status"]),
        visibility=str(row["visibility"]),
        metadata=_object(row["metadata"]),
        item_count=int(row["item_count"]),
        public_item_count=int(row["public_item_count"]),
        row_revision=int(row["row_revision"]),
        created_by=row["created_by"],
        updated_by=row["updated_by"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        archived_at=row["archived_at"],
    )


def _item(row: RowMapping | Mapping[str, Any]) -> CurationItem:
    return CurationItem(
        curation_item_id=str(row["curation_item_id"]),
        collection_id=str(row["collection_id"]),
        collection_key=str(row["collection_key"]),
        title=str(row["title"]),
        edition_key=str(row["edition_key"]),
        theme_slug=str(row["theme_slug"]),
        theme_name=str(row["theme_name"]),
        theme_group=str(row["theme_group"]),
        provider_dataset_id=(
            int(row["provider_dataset_id"])
            if row["provider_dataset_id"] is not None
            else None
        ),
        provider=row["provider"],
        dataset_key=row["dataset_key"],
        source_name=row["source_name"],
        source_url=row["source_url"],
        feature_id=str(row["feature_id"]) if row["feature_id"] else None,
        feature_name=str(row["feature_name"]) if row["feature_name"] else None,
        feature_kind=str(row["feature_kind"]) if row["feature_kind"] else None,
        feature_category=(str(row["feature_category"]) if row["feature_category"] else None),
        lon=float(row["lon"]) if row["lon"] is not None else None,
        lat=float(row["lat"]) if row["lat"] is not None else None,
        address=_object(row["address"]),
        source_record_key=row["source_record_key"],
        external_item_id=str(row["external_item_id"]),
        external_component_id=str(row["external_component_id"]),
        place_name=str(row["place_name"]),
        address_hint=row["address_hint"],
        source_present=bool(row["source_present"]),
        status=str(row["status"]),
        sort_order=int(row["sort_order"]),
        item_title=row["item_title"],
        item_summary=row["item_summary"],
        curation_relation=str(row["curation_relation"]),
        reuse_policy=str(row["reuse_policy"]),
        metadata=_object(row["metadata"]),
        current_import_row_id=(str(value) if (value := row.get("current_import_row_id")) else None),
        accepted_link_decision_id=(
            str(value) if (value := row.get("accepted_link_decision_id")) else None
        ),
        link_match_basis=(str(value) if (value := row.get("link_match_basis")) else None),
        link_resolver_version=(str(value) if (value := row.get("link_resolver_version")) else None),
        link_evidence=_object(row.get("link_evidence")),
        link_actor=str(value) if (value := row.get("link_actor")) else None,
        link_decided_at=row.get("link_decided_at"),
        row_revision=int(row["row_revision"]),
        created_by=row["created_by"],
        updated_by=row["updated_by"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        archived_at=row["archived_at"],
        feature_uuid=(str(value) if (value := row.get("feature_uuid")) else None),
    )


def _service_item_snapshot(
    row: RowMapping | Mapping[str, Any],
) -> CurationServiceItemSnapshot:
    return CurationServiceItemSnapshot(
        curation_item_id=str(row["curation_item_id"]),
        collection_id=str(row["collection_id"]),
        row_revision=int(row["item_row_revision"]),
        updated_at=row["item_updated_at"],
        theme_slug=str(row["theme_slug"]),
        theme_name=str(row["theme_name"]),
        collection_title=str(row["collection_title"]),
        edition_key=str(row["edition_key"]),
        feature_uuid=str(row["feature_uuid"]),
        relation=str(row["relation"]),
        sort_order=int(row["sort_order"]),
        item_title=row["item_title"],
        item_summary=row["item_summary"],
        feature_name=str(row["feature_name"]),
        feature_category=str(row["feature_category"]),
        feature_kind=str(row["feature_kind"]),
        lon=float(row["lon"]) if row["lon"] is not None else None,
        lat=float(row["lat"]) if row["lat"] is not None else None,
        address=_object(row["address"]),
        detail=_object(row["detail"]),
        source_record_key=row["source_record_key"],
    )


def _feature_match(row: RowMapping | Mapping[str, Any]) -> FeatureMatch:
    return FeatureMatch(
        feature_id=str(row["feature_id"]),
        name=str(row["name"]),
        address=_object(row["address"]),
        lon=float(row["lon"]) if row["lon"] is not None else None,
        lat=float(row["lat"]) if row["lat"] is not None else None,
        feature_uuid=(str(value) if (value := row.get("feature_uuid")) else None),
    )


def _import_batch(row: RowMapping | Mapping[str, Any]) -> CurationImportBatch:
    return CurationImportBatch(
        import_batch_id=str(row["import_batch_id"]),
        content_sha256=str(row["content_sha256"]),
        batch_kind=str(row["batch_kind"]),
        row_count=int(row["row_count"]),
        actor=str(row["actor"]),
        metadata=_object(row["metadata"]),
        imported_at=row["imported_at"],
    )


def _import_row_receipt(
    row: RowMapping | Mapping[str, Any],
) -> CurationImportRowReceipt:
    return CurationImportRowReceipt(
        import_row_id=str(row["import_row_id"]),
        import_batch_id=str(row["import_batch_id"]),
        curation_item_id=str(row["curation_item_id"]),
        row_number=int(row["row_number"]),
        source_row_sha256=str(row["source_row_sha256"]),
        row_payload=_object(row["row_payload"]),
        provenance=_object(row["provenance"]),
        imported_at=row["imported_at"],
    )


def _link_audit(row: RowMapping | Mapping[str, Any]) -> CurationLinkAudit:
    return CurationLinkAudit(
        curation_item_id=str(row["curation_item_id"]),
        collection_key=str(row["collection_key"]),
        external_item_id=str(row["external_item_id"]),
        external_component_id=str(row["external_component_id"]),
        feature_id=str(row["feature_id"]),
        place_name=str(row["place_name"]),
        address_hint=row["address_hint"],
        match_basis=str(row["match_basis"]) if row["match_basis"] else None,
        resolver_version=(str(row["resolver_version"]) if row["resolver_version"] else None),
        decided_at=row["decided_at"],
    )


def _quarantine_original_collection_id(metadata: Mapping[str, Any]) -> str | None:
    """marker가 기록한 원본 collection uuid — 없거나 uuid가 아니면 ``None``."""

    value = metadata.get("original_collection_id")
    if not isinstance(value, str):
        return None
    try:
        return str(UUID(value))
    except ValueError:
        return None


def _quarantine_theme(
    row: RowMapping | Mapping[str, Any], prefix: str
) -> CurationQuarantineThemeRef | None:
    theme_id = row[f"{prefix}_theme_id"]
    if not theme_id:
        return None
    return CurationQuarantineThemeRef(
        theme_id=str(theme_id),
        theme_slug=str(row[f"{prefix}_theme_slug"]),
        theme_name=str(row[f"{prefix}_theme_name"]),
        theme_group=str(row[f"{prefix}_theme_group"]),
        visibility=str(row[f"{prefix}_theme_visibility"]),
    )


def _quarantine_source(
    row: RowMapping | Mapping[str, Any], prefix: str
) -> CurationQuarantineSourceRef | None:
    source_id = row[f"{prefix}_source_id"]
    if not source_id:
        return None
    return CurationQuarantineSourceRef(
        source_id=str(source_id),
        provider_dataset_id=(
            int(row[f"{prefix}_provider_dataset_id"])
            if row[f"{prefix}_provider_dataset_id"] is not None
            else None
        ),
        provider=row[f"{prefix}_provider"],
        dataset_key=row[f"{prefix}_dataset_key"],
        source_name=row[f"{prefix}_source_name"],
    )


def _quarantine_collection(
    row: RowMapping | Mapping[str, Any],
) -> CurationQuarantineCollection:
    metadata = _object(row["metadata"])
    recorded_original_id = _quarantine_original_collection_id(metadata)
    original: CurationQuarantineOriginalCollection | None = None
    if recorded_original_id is not None:
        exists = row["original_collection_id"] is not None
        original = CurationQuarantineOriginalCollection(
            collection_id=recorded_original_id,
            row_revision=(int(row["original_row_revision"]) if exists else None),
            title=row["original_title"] if exists else None,
            status=row["original_status"] if exists else None,
            visibility=row["original_visibility"] if exists else None,
            exists=exists,
            theme=_quarantine_theme(row, "original") if exists else None,
            source=_quarantine_source(row, "original") if exists else None,
        )
    return CurationQuarantineCollection(
        collection_id=str(row["collection_id"]),
        row_revision=int(row["row_revision"]),
        collection_key=str(row["collection_key"]),
        title=str(row["title"]),
        edition_key=str(row["edition_key"]),
        status=str(row["status"]),
        visibility=str(row["visibility"]),
        created_by=row["created_by"],
        item_count=int(row["item_count"]),
        marker_intact=bool(row["marker_intact"]),
        quarantine_theme=_quarantine_theme(row, "quarantine"),
        quarantine_source=_quarantine_source(row, "quarantine"),
        original_collection=original,
    )


def _quarantine_item(
    row: RowMapping | Mapping[str, Any],
    *,
    unresolved_kind: str | None,
) -> CurationQuarantineItem:
    component_conflict_id = row["component_conflict_item_id"]
    active_conflict_id = row["active_feature_conflict_item_id"]
    conflict_item_id: str | None
    if unresolved_kind is not None:
        conflict_kind = unresolved_kind
        conflict_item_id = None
    elif component_conflict_id:
        conflict_kind = QUARANTINE_CONFLICT_COMPONENT
        conflict_item_id = str(component_conflict_id)
    elif active_conflict_id:
        conflict_kind = QUARANTINE_CONFLICT_ACTIVE_FEATURE
        conflict_item_id = str(active_conflict_id)
    else:
        conflict_kind = QUARANTINE_CONFLICT_MOVABLE
        conflict_item_id = None
    return CurationQuarantineItem(
        curation_item_id=str(row["curation_item_id"]),
        external_item_id=str(row["external_item_id"]),
        external_component_id=str(row["external_component_id"]),
        feature_id=str(row["feature_id"]) if row["feature_id"] else None,
        place_name=str(row["place_name"]),
        status=str(row["status"]),
        source_present=bool(row["source_present"]),
        archived_at=row["archived_at"],
        conflict_kind=conflict_kind,
        conflict_item_id=conflict_item_id,
    )


def encode_collection_cursor(updated_at: datetime, collection_id: str) -> str:
    raw = json.dumps(
        {"updated_at": updated_at.isoformat(), "collection_id": collection_id},
        separators=(",", ":"),
    )
    return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")


def decode_collection_cursor(cursor: str | None) -> tuple[datetime, str] | None:
    if cursor is None:
        return None
    try:
        raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4))
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            raise ValueError
        updated_at = payload.get("updated_at")
        collection_id = payload.get("collection_id")
        if not isinstance(updated_at, str) or not isinstance(collection_id, str):
            raise ValueError
        parsed_updated_at = datetime.fromisoformat(updated_at)
        if parsed_updated_at.tzinfo is None:
            raise ValueError
        UUID(collection_id)
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError("invalid curation collection cursor") from exc
    if not updated_at or not collection_id:
        raise ValueError("invalid curation collection cursor")
    return parsed_updated_at, collection_id


def encode_group_cursor(feature_id: str) -> str:
    raw = json.dumps({"feature_id": feature_id}, separators=(",", ":"))
    return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")


def decode_group_cursor(cursor: str | None) -> str | None:
    if cursor is None:
        return None
    try:
        raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4))
        payload = json.loads(raw)
    except (ValueError, json.JSONDecodeError) as exc:
        raise ValueError("invalid curation group cursor") from exc
    feature_id = payload.get("feature_id") if isinstance(payload, dict) else None
    if not isinstance(feature_id, str) or not feature_id:
        raise ValueError("invalid curation group cursor")
    return feature_id


def encode_link_audit_cursor(collection_id: str, curation_item_id: str) -> str:
    """audit total order key를 versioned opaque cursor로 직렬화한다."""

    payload = json.dumps(
        {
            "v": 1,
            "collection_id": str(UUID(collection_id)),
            "curation_item_id": str(UUID(curation_item_id)),
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return base64.urlsafe_b64encode(payload).decode().rstrip("=")


def decode_link_audit_cursor(cursor: str | None) -> tuple[str, str] | None:
    if cursor is None:
        return None
    try:
        raw = base64.b64decode(
            cursor + "=" * (-len(cursor) % 4),
            altchars=b"-_",
            validate=True,
        )
        value = json.loads(raw)
        if (
            not isinstance(value, dict)
            or set(value) != {"v", "collection_id", "curation_item_id"}
            or value["v"] != 1
        ):
            raise ValueError
        collection_id = str(UUID(value["collection_id"]))
        curation_item_id = str(UUID(value["curation_item_id"]))
    except (TypeError, ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("invalid curation link audit cursor") from exc
    return collection_id, curation_item_id


def encode_quarantine_collection_cursor(collection_id: str) -> str:
    """격리 collection keyset(collection_id 오름차순)을 versioned cursor로 직렬화한다."""

    payload = json.dumps(
        {"v": 1, "collection_id": str(UUID(collection_id))},
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return base64.urlsafe_b64encode(payload).decode().rstrip("=")


def decode_quarantine_collection_cursor(cursor: str | None) -> str | None:
    if cursor is None:
        return None
    try:
        raw = base64.b64decode(
            cursor + "=" * (-len(cursor) % 4),
            altchars=b"-_",
            validate=True,
        )
        value = json.loads(raw)
        if not isinstance(value, dict) or set(value) != {"v", "collection_id"} or value["v"] != 1:
            raise ValueError
        collection_id = str(UUID(value["collection_id"]))
    except (TypeError, ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("invalid curation quarantine cursor") from exc
    return collection_id


def encode_quarantine_item_cursor(curation_item_id: str) -> str:
    """격리 item keyset(curation_item_id 오름차순)을 versioned cursor로 직렬화한다."""

    payload = json.dumps(
        {"v": 1, "curation_item_id": str(UUID(curation_item_id))},
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return base64.urlsafe_b64encode(payload).decode().rstrip("=")


def decode_quarantine_item_cursor(cursor: str | None) -> str | None:
    if cursor is None:
        return None
    try:
        raw = base64.b64decode(
            cursor + "=" * (-len(cursor) % 4),
            altchars=b"-_",
            validate=True,
        )
        value = json.loads(raw)
        if (
            not isinstance(value, dict)
            or set(value) != {"v", "curation_item_id"}
            or value["v"] != 1
        ):
            raise ValueError
        curation_item_id = str(UUID(value["curation_item_id"]))
    except (TypeError, ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("invalid curation quarantine item cursor") from exc
    return curation_item_id


async def list_curation_collections(
    session: AsyncSession,
    *,
    status: str | None = None,
    visibility: str | None = None,
    theme_slug: str | None = None,
    edition_key: str | None = None,
    provider_dataset_id: int | None = None,
    q: str | None = None,
    include_archived: bool = False,
    public_only: bool = False,
    limit: int = 200,
    cursor: str | None = None,
) -> tuple[tuple[CurationCollection, ...], str | None]:
    if status is not None and status not in _COLLECTION_STATUSES:
        raise ValueError("invalid curation collection status")
    if visibility is not None and visibility not in _VISIBILITIES:
        raise ValueError("invalid curation collection visibility")
    decoded_cursor = decode_collection_cursor(cursor)
    effective_limit = max(1, min(limit, 500))
    rows = (
        (
            await session.execute(
                text(_LIST_COLLECTIONS_SQL),
                {
                    "status": status,
                    "visibility": visibility,
                    "theme_slug": theme_slug,
                    "edition_key": edition_key,
                    "provider_dataset_id": provider_dataset_id,
                    "q": f"%{q.strip()}%" if q and q.strip() else None,
                    "include_archived": include_archived,
                    "public_only": public_only,
                    "cursor_updated_at": decoded_cursor[0] if decoded_cursor else None,
                    "cursor_collection_id": (decoded_cursor[1] if decoded_cursor else None),
                    "limit": effective_limit + 1,
                },
            )
        )
        .mappings()
        .all()
    )
    page = tuple(_collection(row) for row in rows[:effective_limit])
    next_cursor = (
        encode_collection_cursor(page[-1].updated_at, page[-1].collection_id)
        if len(rows) > effective_limit and page
        else None
    )
    return page, next_cursor


async def get_curation_collection(
    session: AsyncSession,
    *,
    collection_id: str,
    include_archived: bool = False,
    public_only: bool = False,
) -> tuple[CurationCollection, tuple[CurationItem, ...]] | None:
    row = (
        (
            await session.execute(
                text(_GET_COLLECTION_SQL),
                {
                    "collection_id": collection_id,
                    "include_archived": include_archived,
                    "public_only": public_only,
                },
            )
        )
        .mappings()
        .first()
    )
    if row is None:
        return None
    item_rows = (
        (
            await session.execute(
                text(_LIST_COLLECTION_ITEMS_SQL),
                {
                    "collection_id": collection_id,
                    "include_archived": include_archived,
                    "public_only": public_only,
                },
            )
        )
        .mappings()
        .all()
    )
    return _collection(row), tuple(_item(item_row) for item_row in item_rows)


async def get_curation_item(
    session: AsyncSession,
    *,
    collection_id: str,
    curation_item_id: str,
    include_archived: bool = False,
) -> CurationItem | None:
    row = (
        (
            await session.execute(
                text(_GET_COLLECTION_ITEM_SQL),
                {
                    "collection_id": collection_id,
                    "curation_item_id": curation_item_id,
                    "include_archived": include_archived,
                },
            )
        )
        .mappings()
        .first()
    )
    return _item(row) if row is not None else None


async def get_curation_service_collection_snapshot(
    session: AsyncSession,
    *,
    collection_id: str,
    after_curation_item_id: str | None = None,
    page_limit: int = 101,
) -> CurationServiceCollectionSnapshot | None:
    """PinVi용 exact set receipt와 bounded public item page를 한 statement로 읽는다."""

    if not 1 <= page_limit <= 201:
        raise ValueError("page_limit must be between 1 and 201")
    rows = (
        (
            await session.execute(
                text(_GET_SERVICE_CURATION_COLLECTION_PAGE_SQL),
                {
                    "collection_id": collection_id,
                    "curation_item_id": None,
                    "after_curation_item_id": after_curation_item_id,
                    "page_limit": page_limit,
                },
            )
        )
        .mappings()
        .all()
    )
    if not rows:
        return None
    first = rows[0]
    items = tuple(
        _service_item_snapshot(row)
        for row in rows
        if row["curation_item_id"] is not None
    )
    return CurationServiceCollectionSnapshot(
        collection_id=str(first["collection_id"]),
        row_revision=int(first["collection_row_revision"]),
        updated_at=first["collection_updated_at"],
        theme_slug=str(first["theme_slug"]),
        theme_name=str(first["theme_name"]),
        title=str(first["collection_title"]),
        edition_key=str(first["edition_key"]),
        item_count=int(first["item_count"]),
        item_set_hash=str(first["item_set_hash"]),
        items=items,
    )


async def get_curation_service_item_snapshot(
    session: AsyncSession,
    *,
    curation_item_id: str,
) -> CurationServiceItemSnapshot | None:
    """PinVi용 public/trusted canonical item 한 건을 읽는다."""

    row = (
        (
            await session.execute(
                text(_GET_SERVICE_CURATION_ITEM_SNAPSHOT_SQL),
                {
                    "collection_id": None,
                    "curation_item_id": curation_item_id,
                },
            )
        )
        .mappings()
        .first()
    )
    if row is None or row["curation_item_id"] is None:
        return None
    return _service_item_snapshot(row)


_LIST_CUTOVER_IDENTITY_MAPPINGS_SQL = """
SELECT
  legacy_curated_feature_id,
  collection_id,
  curation_item_id,
  mapping_kind,
  source_row_hash
FROM ops.curation_cutover_identity_mappings
ORDER BY legacy_curated_feature_id
"""


async def get_curation_cutover_identity_mapping_export(
    session: AsyncSession,
) -> CurationCutoverIdentityMappingExport:
    """Return the complete immutable cutover map and its closed Merkle receipt.

    This is intentionally a maintenance-window read.  The HTTP layer exposes
    it through a signed keyset cursor, while this single relation snapshot is
    used to calculate the root that every page must carry.  Runtime has SELECT
    only; writes remain schema-owner/migration-only and append-only.
    """

    rows = (
        (
            await session.execute(text(_LIST_CUTOVER_IDENTITY_MAPPINGS_SQL))
        )
        .mappings()
        .all()
    )
    mappings = tuple(
        CurationCutoverIdentityMapping(
            legacy_curated_feature_id=str(row["legacy_curated_feature_id"]),
            collection_id=str(row["collection_id"]),
            curation_item_id=str(row["curation_item_id"]),
            mapping_kind=str(row["mapping_kind"]),
            source_row_hash=str(row["source_row_hash"]),
        )
        for row in rows
    )
    root = curation_cutover_identity_mapping_root(
        CurationCutoverIdentityMappingDigestInput(
            legacy_curated_feature_id=UUID(mapping.legacy_curated_feature_id),
            collection_id=UUID(mapping.collection_id),
            curation_item_id=UUID(mapping.curation_item_id),
            mapping_kind=mapping.mapping_kind,
            source_row_hash=mapping.source_row_hash,
        )
        for mapping in mappings
    )
    return CurationCutoverIdentityMappingExport(
        mapping_count=len(mappings),
        mapping_root=root,
        mappings=mappings,
    )


async def get_curation_import_batch(
    session: AsyncSession,
    *,
    import_batch_id: str,
) -> tuple[CurationImportBatch, tuple[CurationImportRowReceipt, ...]] | None:
    """한 import receipt와 exact row evidence를 batch row 순서로 읽는다."""

    batch_row = (
        (
            await session.execute(
                text(_GET_IMPORT_BATCH_SQL),
                {"import_batch_id": import_batch_id},
            )
        )
        .mappings()
        .first()
    )
    if batch_row is None:
        return None
    row_rows = (
        (
            await session.execute(
                text(_LIST_IMPORT_BATCH_ROWS_SQL),
                {"import_batch_id": import_batch_id},
            )
        )
        .mappings()
        .all()
    )
    return _import_batch(batch_row), tuple(_import_row_receipt(row) for row in row_rows)


async def get_current_curation_import_row(
    session: AsyncSession,
    *,
    curation_item_id: str,
) -> CurationImportRowReceipt | None:
    """item의 composite current pointer가 가리키는 immutable row를 읽는다."""

    row = (
        (
            await session.execute(
                text(_GET_CURRENT_IMPORT_ROW_SQL),
                {"curation_item_id": curation_item_id},
            )
        )
        .mappings()
        .first()
    )
    return _import_row_receipt(row) if row is not None else None


async def _lock_collection_keys(
    session: AsyncSession,
    collection_keys: Sequence[str],
) -> None:
    """아직 생성되지 않은 collection까지 stable key 순서로 직렬화한다."""

    normalized_keys = sorted(set(collection_keys))
    if not normalized_keys:
        return
    await session.execute(
        text(
            """
            SELECT pg_advisory_xact_lock(
                hashtextextended(
                    'kortravelmap:curation-collection:' || collection_key,
                    0
                )
            )
            FROM unnest(CAST(:collection_keys AS text[]))
                AS requested(collection_key)
            ORDER BY collection_key
            """
        ),
        {"collection_keys": normalized_keys},
    )


async def _lock_curation_write_boundary(session: AsyncSession) -> None:
    """Theme·collection·Feature 순서가 다른 공식/수동 writer를 직렬화한다."""

    await session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended('kortravelmap:curation-import', 0))")
    )


async def _lock_collection(session: AsyncSession, collection_id: str) -> bool:
    row = (
        await session.execute(
            text(
                "SELECT collection_id FROM feature.curation_collections "
                "WHERE collection_id = CAST(:collection_id AS uuid) FOR UPDATE"
            ),
            {"collection_id": collection_id},
        )
    ).first()
    return row is not None


async def _touch_collection(
    session: AsyncSession, *, collection_id: str, actor: str | None
) -> None:
    await session.execute(
        text(
            "UPDATE feature.curation_collections "
            "SET updated_by = :actor, updated_at = now(), "
            "row_revision = row_revision + 1 "
            "WHERE collection_id = CAST(:collection_id AS uuid)"
        ),
        {"collection_id": collection_id, "actor": actor},
    )


async def create_curation_collection(
    session: AsyncSession,
    *,
    collection_key: str,
    theme_id: str,
    source_id: str | None,
    title: str,
    edition_key: str = "",
    description: str | None = None,
    status: str = "draft",
    visibility: str = "admin_only",
    metadata: Mapping[str, Any] | None = None,
    actor: str | None = None,
) -> CurationCollection:
    if status not in _COLLECTION_STATUSES or visibility not in _VISIBILITIES:
        raise ValueError("invalid curation collection state")
    if not collection_key.strip() or not title.strip():
        raise ValueError("collection_key and title are required")
    normalized_collection_key = collection_key.strip()
    await _lock_curation_write_boundary(session)
    await _lock_collection_keys(session, (normalized_collection_key,))
    collection_id = str(
        (
            await session.execute(
                text(_CREATE_COLLECTION_SQL),
                {
                    "collection_key": normalized_collection_key,
                    "theme_id": theme_id,
                    "source_id": source_id,
                    "title": title.strip(),
                    "edition_key": edition_key.strip(),
                    "description": description,
                    "status": status,
                    "visibility": visibility,
                    "metadata": json.dumps(dict(metadata or {})),
                    "actor": actor,
                },
            )
        ).scalar_one()
    )
    result = await get_curation_collection(
        session, collection_id=collection_id, include_archived=True
    )
    assert result is not None
    return result[0]


async def update_curation_collection(
    session: AsyncSession,
    *,
    collection_id: str,
    updates: Mapping[str, Any],
    expected_revision: int | None = None,
) -> CurationCollection | None:
    allowed = {
        "theme_id",
        "source_id",
        "title",
        "edition_key",
        "description",
        "status",
        "visibility",
        "metadata",
        "updated_by",
    }
    clauses: list[str] = []
    params: dict[str, Any] = {"collection_id": collection_id}
    for key, value in updates.items():
        if key not in allowed:
            raise ValueError(f"unsupported curation collection field: {key}")
        if key == "status" and value not in _COLLECTION_STATUSES:
            raise ValueError("invalid curation collection status")
        if key == "visibility" and value not in _VISIBILITIES:
            raise ValueError("invalid curation collection visibility")
        if key in {"theme_id", "source_id"}:
            clauses.append(f"{key} = CAST(:{key} AS uuid)")
        elif key == "metadata":
            clauses.append("metadata = CAST(:metadata AS jsonb)")
            value = json.dumps(dict(value))
        else:
            clauses.append(f"{key} = :{key}")
        params[key] = value
    if not clauses:
        current = await get_curation_collection(
            session, collection_id=collection_id, include_archived=True
        )
        if (
            current is not None
            and expected_revision is not None
            and current[0].row_revision != expected_revision
        ):
            raise CurationRevisionConflictError("curation collection revision이 stale입니다.")
        return current[0] if current else None
    clauses.extend(
        [
            "updated_at = now()",
            "row_revision = row_revision + 1",
            (
                "archived_at = CASE WHEN :archive THEN now() "
                "WHEN :unarchive THEN NULL ELSE archived_at END"
            ),
        ]
    )
    params["archive"] = updates.get("status") == "archived"
    params["unarchive"] = "status" in updates and updates.get("status") != "archived"
    params["expected_revision"] = expected_revision
    sql = f"""
    UPDATE feature.curation_collections
    SET {", ".join(clauses)}
    WHERE collection_id = CAST(:collection_id AS uuid)
      AND (
          CAST(:expected_revision AS bigint) IS NULL
          OR row_revision = CAST(:expected_revision AS bigint)
      )
    RETURNING collection_id::text
    """
    row = (await session.execute(text(sql), params)).first()
    if row is None:
        if expected_revision is not None and await get_curation_collection(
            session, collection_id=collection_id, include_archived=True
        ):
            raise CurationRevisionConflictError("curation collection revision이 stale입니다.")
        return None
    current = await get_curation_collection(
        session, collection_id=collection_id, include_archived=True
    )
    assert current is not None
    return current[0]


async def archive_curation_collection(
    session: AsyncSession,
    *,
    collection_id: str,
    actor: str | None = None,
    expected_revision: int | None = None,
) -> CurationCollection | None:
    return await update_curation_collection(
        session,
        collection_id=collection_id,
        updates={"status": "archived", "updated_by": actor},
        expected_revision=expected_revision,
    )


async def create_curation_collection_command(
    session: AsyncSession,
    *,
    collection_key: str,
    theme_id: str,
    source_id: str | None,
    title: str,
    edition_key: str = "",
    description: str | None = None,
    status: str = "draft",
    visibility: str = "admin_only",
    metadata: Mapping[str, Any] | None = None,
    command_id: int,
    principal: str,
) -> CurationCollection:
    """domain command에 결박된 canonical collection create를 실행한다."""

    if status not in {"draft", "published"} or visibility not in _VISIBILITIES:
        raise ValueError("invalid curation collection state")
    normalized_collection_key = collection_key.strip()
    normalized_title = title.strip()
    normalized_edition_key = edition_key.strip()
    if not normalized_collection_key or not normalized_title:
        raise ValueError("collection_key and title are required")
    result = (
        await session.execute(
            text(
                """
                CALL feature.create_curation_collection_command(
                  :collection_key, CAST(:theme_id AS uuid), CAST(:source_id AS uuid),
                  :title, :edition_key, :description, :status, :visibility,
                  CAST(:metadata_json AS jsonb), :command_id, :principal, NULL, NULL
                )
                """
            ),
            {
                "collection_key": normalized_collection_key,
                "command_id": command_id,
                "description": description,
                "edition_key": normalized_edition_key,
                "metadata_json": json.dumps(dict(metadata or {})),
                "principal": principal,
                "source_id": source_id,
                "status": status,
                "theme_id": theme_id,
                "title": normalized_title,
                "visibility": visibility,
            },
        )
    ).mappings().one()
    created = await get_curation_collection(
        session,
        collection_id=str(result["o_collection_id"]),
        include_archived=True,
    )
    if created is None:
        raise RuntimeError("created curation collection could not be read")
    return created[0]


async def patch_curation_collection_command(
    session: AsyncSession,
    *,
    collection_id: str,
    expected_revision: int,
    updates: Mapping[str, Any],
    command_id: int,
    principal: str,
) -> CurationCollection | None:
    """현재 collection을 full desired input으로 만들어 strong CAS patch한다."""

    allowed = {
        "theme_id",
        "source_id",
        "title",
        "edition_key",
        "description",
        "status",
        "visibility",
        "metadata",
    }
    unknown = set(updates) - allowed
    if unknown:
        raise ValueError(f"unsupported curation collection fields: {sorted(unknown)}")
    current_result = await get_curation_collection(
        session, collection_id=collection_id, include_archived=True
    )
    if current_result is None:
        return None
    current = current_result[0]
    desired: dict[str, Any] = {
        "theme_id": current.theme_id,
        "source_id": current.source_id,
        "title": current.title,
        "edition_key": current.edition_key,
        "description": current.description,
        "status": current.status,
        "visibility": current.visibility,
        "metadata": current.metadata,
    }
    desired.update(updates)
    for field_name in ("theme_id", "title", "edition_key", "status", "visibility", "metadata"):
        if desired[field_name] is None:
            raise ValueError(f"{field_name} must not be null")
    if desired["status"] not in {"draft", "published"}:
        raise ValueError("invalid curation collection status")
    if desired["visibility"] not in _VISIBILITIES:
        raise ValueError("invalid curation collection visibility")
    result = (
        await session.execute(
            text(
                """
                CALL feature.patch_curation_collection_command(
                  CAST(:collection_id AS uuid), :expected_revision,
                  CAST(:theme_id AS uuid), CAST(:source_id AS uuid), :title,
                  :edition_key, :description, :status, :visibility,
                  CAST(:metadata_json AS jsonb), :command_id, :principal,
                  NULL, NULL
                )
                """
            ),
            {
                "collection_id": collection_id,
                "command_id": command_id,
                "description": desired["description"],
                "edition_key": str(desired["edition_key"]).strip(),
                "expected_revision": expected_revision,
                "metadata_json": json.dumps(dict(desired["metadata"])),
                "principal": principal,
                "source_id": desired["source_id"],
                "status": desired["status"],
                "theme_id": desired["theme_id"],
                "title": str(desired["title"]).strip(),
                "visibility": desired["visibility"],
            },
        )
    ).mappings().one()
    updated = await get_curation_collection(
        session,
        collection_id=str(result["o_collection_id"]),
        include_archived=True,
    )
    if updated is None:
        raise RuntimeError("patched curation collection could not be read")
    return updated[0]


async def archive_curation_collection_command(
    session: AsyncSession,
    *,
    collection_id: str,
    expected_revision: int,
    command_id: int,
    principal: str,
) -> CurationCollection | None:
    """canonical collection을 domain command에 결박해 archive한다."""

    if await get_curation_collection(
        session, collection_id=collection_id, include_archived=True
    ) is None:
        return None
    result = (
        await session.execute(
            text(
                """
                CALL feature.archive_curation_collection_command(
                  CAST(:collection_id AS uuid), :expected_revision,
                  :command_id, :principal, NULL, NULL
                )
                """
            ),
            {
                "collection_id": collection_id,
                "command_id": command_id,
                "expected_revision": expected_revision,
                "principal": principal,
            },
        )
    ).mappings().one()
    archived = await get_curation_collection(
        session,
        collection_id=str(result["o_collection_id"]),
        include_archived=True,
    )
    if archived is None:
        raise RuntimeError("archived curation collection could not be read")
    return archived[0]


async def create_curation_item_command(
    session: AsyncSession,
    *,
    collection_id: str,
    feature_id: str | None,
    external_item_id: str,
    external_component_id: str = "primary",
    place_name: str | None = None,
    address_hint: str | None = None,
    source_record_key: str | None = None,
    status: str = "included",
    sort_order: int = 0,
    item_title: str | None = None,
    item_summary: str | None = None,
    curation_relation: str = "nearby_option",
    reuse_policy: str = "manual_review",
    metadata: Mapping[str, Any] | None = None,
    command_id: int,
    principal: str,
) -> CurationItem:
    """domain command에 결박된 canonical item create를 실행한다."""

    normalized_external_item_id = external_item_id.strip()
    normalized_external_component_id = external_component_id.strip()
    normalized_place_name = place_name.strip() if place_name else None
    normalized_address_hint = address_hint.strip() if address_hint else None
    if not normalized_external_item_id or not normalized_external_component_id:
        raise ValueError("invalid curation item identity")
    if feature_id is None and normalized_place_name is None:
        raise ValueError("feature_id or place_name is required")
    if status not in {"candidate", "included", "rejected"}:
        raise ValueError("invalid curation item status")
    if curation_relation not in _RELATIONS or reuse_policy not in _REUSE_POLICIES:
        raise ValueError("invalid curation item policy")
    if not 0 <= sort_order <= _POSTGRES_INTEGER_MAX:
        raise ValueError("invalid curation item sort order")
    result = (
        await session.execute(
            text(
                """
                CALL feature.create_curation_item_command(
                  CAST(:collection_id AS uuid), :feature_id, :source_record_key,
                  :external_item_id, :external_component_id, :place_name,
                  :address_hint, :status, :sort_order, :item_title, :item_summary,
                  :curation_relation, :reuse_policy, CAST(:metadata_json AS jsonb),
                  :command_id, :principal, NULL, NULL, NULL
                )
                """
            ),
            {
                "address_hint": normalized_address_hint,
                "collection_id": collection_id,
                "command_id": command_id,
                "curation_relation": curation_relation,
                "external_component_id": normalized_external_component_id,
                "external_item_id": normalized_external_item_id,
                "feature_id": feature_id,
                "item_summary": item_summary,
                "item_title": item_title,
                "metadata_json": json.dumps(dict(metadata or {})),
                "place_name": normalized_place_name,
                "principal": principal,
                "reuse_policy": reuse_policy,
                "sort_order": sort_order,
                "source_record_key": source_record_key,
                "status": status,
            },
        )
    ).mappings().one()
    created = await get_curation_item(
        session,
        collection_id=collection_id,
        curation_item_id=str(result["o_curation_item_id"]),
        include_archived=True,
    )
    if created is None:
        raise RuntimeError("created curation item could not be read")
    return created


_CREATE_MANUAL_CURATION_ITEM_WITH_FEATURE_SQL: Final[str] = """
CALL feature.create_manual_curation_item_with_feature_command(
  CAST(:feature_payload AS jsonb), CAST(:item_payload AS jsonb),
  CAST(:command_id AS bigint), NULL::text, NULL::text, NULL::uuid,
  NULL::bigint, NULL::uuid, NULL::bigint, NULL::bigint, NULL::uuid
)
"""


async def create_manual_curation_item_with_feature_command(
    session: AsyncSession,
    *,
    collection_id: str,
    manual_feature: Mapping[str, Any],
    external_item_id: str,
    external_component_id: str = "primary",
    place_name: str | None = None,
    address_hint: str | None = None,
    status: str = "included",
    sort_order: int = 0,
    item_title: str | None = None,
    item_summary: str | None = None,
    curation_relation: str = "nearby_option",
    reuse_policy: str = "manual_review",
    metadata: Mapping[str, Any] | None = None,
    command_id: int,
    principal: str,
) -> CurationManualFeatureItem | CurationManualFeatureExactDuplicate:
    """M03 combined procedure로 explicit manual Feature와 item을 함께 만든다.

    caller가 UUID, legacy ID, origin/claim/상태 tuple을 고를 수 없게 이 경계에서
    새 UUIDv7과 opaque bridge를 한 번 발급한다. detail subtype은 같은 outer
    SERIALIZABLE command transaction에서만 뒤이어 materialize된다.
    """

    if command_id < 1 or not principal.strip():
        raise ValueError("manual curation command identity is required")
    kind_value = manual_feature.get("kind")
    kind = str(kind_value) if kind_value is not None else ""
    if kind not in {"place", "event"}:
        raise ValueError("manual_feature.kind must be place or event")
    forbidden = {
        "feature_id",
        "feature_uuid",
        "origin_kind",
        "creator_principal_id",
        "lifecycle_state",
        "publication_state",
        "quality_state",
        "operator",
        "idempotency_key",
    }
    supplied_forbidden = sorted(forbidden.intersection(manual_feature))
    if supplied_forbidden:
        raise ValueError(f"manual_feature.{supplied_forbidden[0]} is server-owned")
    coord = manual_feature.get("coord")
    if not isinstance(coord, Mapping):
        raise ValueError("manual_feature.coord is required")
    lon = coord.get("lon")
    lat = coord.get("lat")
    if lon is None or lat is None:
        raise ValueError("manual_feature.coord is required")
    feature_uuid = candidate_feature_uuid()
    feature_id = make_feature_id(
        bjd_code=None,
        kind=kind,
        category="manual_feature_v1",
        source_type="user_request",
        source_natural_key=f"manual::{feature_uuid}",
        content_hash=None,
    )
    feature_payload = {
        key: value
        for key, value in manual_feature.items()
        if key not in {"detail", "reason", "coord"}
    }
    feature_payload.update(
        {
            "feature_id": feature_id,
            "feature_uuid": feature_uuid,
            "lon": lon,
            "lat": lat,
            "coord_precision_digits": manual_feature.get("coord_precision_digits", 6),
        }
    )
    item_payload: dict[str, Any] = {
        "collection_id": collection_id,
        "external_item_id": external_item_id.strip(),
        "external_component_id": external_component_id.strip(),
        "place_name": place_name.strip() if place_name else None,
        "address_hint": address_hint.strip() if address_hint else None,
        "status": status,
        "sort_order": sort_order,
        "item_title": item_title,
        "item_summary": item_summary,
        "curation_relation": curation_relation,
        "reuse_policy": reuse_policy,
        "metadata": dict(metadata or {}),
        "source_record_key": None,
    }
    result = (
        await session.execute(
            text(_CREATE_MANUAL_CURATION_ITEM_WITH_FEATURE_SQL),
            {
                "command_id": command_id,
                "feature_payload": json.dumps(
                    feature_payload, ensure_ascii=False, default=str
                ),
                "item_payload": json.dumps(
                    item_payload, ensure_ascii=False, default=str
                ),
            },
        )
    ).mappings().one()
    outcome = result.get("o_outcome")
    if outcome == "exact_conflict":
        winner = result.get("o_existing_feature_uuid")
        if not isinstance(winner, (str, UUID)):
            raise RuntimeError("manual curation exact conflict has no winner UUID")
        return CurationManualFeatureExactDuplicate(existing_feature_uuid=str(winner))
    if outcome != "created":
        raise RuntimeError("manual curation writer returned an unknown outcome")
    observed_feature_id = result.get("o_feature_id")
    observed_feature_uuid = result.get("o_feature_uuid")
    item_id = result.get("o_curation_item_id")
    feature_revision = result.get("o_feature_row_revision")
    if (
        observed_feature_id != feature_id
        or str(observed_feature_uuid) != feature_uuid
        or not isinstance(item_id, (str, UUID))
        or type(feature_revision) is not int
        or feature_revision < 1
    ):
        raise RuntimeError("manual curation writer receipt does not match server identity")
    await write_subtype(
        session,
        feature_id=feature_id,
        feature_uuid=feature_uuid,
        kind=kind,
        detail=manual_feature.get("detail"),
    )
    created = await get_curation_item(
        session,
        collection_id=collection_id,
        curation_item_id=str(item_id),
        include_archived=True,
    )
    if created is None:
        raise RuntimeError("manual curation item could not be read")
    return CurationManualFeatureItem(
        feature_id=feature_id,
        feature_uuid=feature_uuid,
        feature_row_revision=feature_revision,
        item=created,
    )


async def patch_curation_item_command(
    session: AsyncSession,
    *,
    collection_id: str,
    curation_item_id: str,
    updates: Mapping[str, Any],
    expected_revision: int,
    command_id: int,
    principal: str,
) -> CurationItem | None:
    """현재 item을 full desired input으로 만들어 strong CAS patch한다."""

    allowed = {
        "feature_id",
        "source_record_key",
        "external_item_id",
        "external_component_id",
        "place_name",
        "address_hint",
        "status",
        "sort_order",
        "item_title",
        "item_summary",
        "curation_relation",
        "reuse_policy",
        "metadata",
    }
    unknown = set(updates) - allowed
    if unknown:
        raise ValueError(f"unsupported curation item fields: {sorted(unknown)}")
    current = await get_curation_item(
        session,
        collection_id=collection_id,
        curation_item_id=curation_item_id,
        include_archived=True,
    )
    if current is None:
        return None
    desired: dict[str, Any] = {
        "feature_id": current.feature_id,
        "source_record_key": current.source_record_key,
        "external_item_id": current.external_item_id,
        "external_component_id": current.external_component_id,
        "place_name": current.place_name,
        "address_hint": current.address_hint,
        "status": current.status,
        "sort_order": current.sort_order,
        "item_title": current.item_title,
        "item_summary": current.item_summary,
        "curation_relation": current.curation_relation,
        "reuse_policy": current.reuse_policy,
        "metadata": current.metadata,
    }
    desired.update(updates)
    for field_name in (
        "external_item_id",
        "external_component_id",
        "place_name",
        "status",
        "sort_order",
        "curation_relation",
        "reuse_policy",
        "metadata",
    ):
        if desired[field_name] is None:
            raise ValueError(f"{field_name} must not be null")
    desired["external_item_id"] = str(desired["external_item_id"]).strip()
    desired["external_component_id"] = str(desired["external_component_id"]).strip()
    desired["place_name"] = str(desired["place_name"]).strip()
    address_hint = desired["address_hint"]
    desired["address_hint"] = (
        str(address_hint).strip() or None if address_hint is not None else None
    )
    if not (
        desired["external_item_id"]
        and desired["external_component_id"]
        and desired["place_name"]
    ):
        raise ValueError("curation item identity and place_name must not be empty")
    if desired["status"] not in {"candidate", "included", "rejected"}:
        raise ValueError("invalid curation item status")
    if desired["curation_relation"] not in _RELATIONS:
        raise ValueError("invalid curation item relation")
    if desired["reuse_policy"] not in _REUSE_POLICIES:
        raise ValueError("invalid curation item reuse policy")
    if (
        not isinstance(desired["sort_order"], int)
        or not 0 <= desired["sort_order"] <= _POSTGRES_INTEGER_MAX
    ):
        raise ValueError("invalid curation item sort order")
    if not isinstance(desired["metadata"], Mapping):
        raise ValueError("curation item metadata must be an object")
    result = (
        await session.execute(
            text(
                """
                CALL feature.patch_curation_item_command(
                  CAST(:collection_id AS uuid), CAST(:curation_item_id AS uuid),
                  :expected_revision, :feature_id, :source_record_key,
                  :external_item_id, :external_component_id, :place_name,
                  :address_hint, :status, :sort_order, :item_title, :item_summary,
                  :curation_relation, :reuse_policy, CAST(:metadata_json AS jsonb),
                  :command_id, :principal, NULL, NULL, NULL
                )
                """
            ),
            {
                "address_hint": desired["address_hint"],
                "collection_id": collection_id,
                "command_id": command_id,
                "curation_item_id": curation_item_id,
                "curation_relation": desired["curation_relation"],
                "expected_revision": expected_revision,
                "external_component_id": desired["external_component_id"],
                "external_item_id": desired["external_item_id"],
                "feature_id": desired["feature_id"],
                "item_summary": desired["item_summary"],
                "item_title": desired["item_title"],
                "metadata_json": json.dumps(dict(desired["metadata"])),
                "place_name": desired["place_name"],
                "principal": principal,
                "reuse_policy": desired["reuse_policy"],
                "sort_order": desired["sort_order"],
                "source_record_key": desired["source_record_key"],
                "status": desired["status"],
            },
        )
    ).mappings().one()
    updated = await get_curation_item(
        session,
        collection_id=collection_id,
        curation_item_id=str(result["o_curation_item_id"]),
        include_archived=True,
    )
    if updated is None:
        raise RuntimeError("patched curation item could not be read")
    return updated


async def archive_curation_item_command(
    session: AsyncSession,
    *,
    collection_id: str,
    curation_item_id: str,
    expected_revision: int,
    command_id: int,
    principal: str,
) -> CurationItem | None:
    """canonical item을 domain command에 결박해 archive한다."""

    if await get_curation_item(
        session,
        collection_id=collection_id,
        curation_item_id=curation_item_id,
        include_archived=True,
    ) is None:
        return None
    result = (
        await session.execute(
            text(
                """
                CALL feature.archive_curation_item_command(
                  CAST(:collection_id AS uuid), CAST(:curation_item_id AS uuid),
                  :expected_revision, :command_id, :principal, NULL, NULL, NULL
                )
                """
            ),
            {
                "collection_id": collection_id,
                "command_id": command_id,
                "curation_item_id": curation_item_id,
                "expected_revision": expected_revision,
                "principal": principal,
            },
        )
    ).mappings().one()
    archived = await get_curation_item(
        session,
        collection_id=collection_id,
        curation_item_id=str(result["o_curation_item_id"]),
        include_archived=True,
    )
    if archived is None:
        raise RuntimeError("archived curation item could not be read")
    return archived


async def add_curation_item(
    session: AsyncSession,
    *,
    collection_id: str,
    feature_id: str | None,
    external_item_id: str,
    external_component_id: str = "primary",
    place_name: str | None = None,
    address_hint: str | None = None,
    source_record_key: str | None = None,
    status: str = "included",
    sort_order: int = 0,
    item_title: str | None = None,
    item_summary: str | None = None,
    curation_relation: str = "nearby_option",
    reuse_policy: str = "manual_review",
    metadata: Mapping[str, Any] | None = None,
    actor: str | None = None,
) -> tuple[CurationItem, bool]:
    if status not in _ITEM_STATUSES:
        raise ValueError("invalid curation item status")
    if curation_relation not in _RELATIONS or reuse_policy not in _REUSE_POLICIES:
        raise ValueError("invalid curation item policy")
    if (
        not 0 <= sort_order <= _POSTGRES_INTEGER_MAX
        or not external_item_id.strip()
        or not external_component_id.strip()
    ):
        raise ValueError("invalid curation item identity")
    resolved_place_name = place_name.strip() if place_name else ""
    if feature_id is not None:
        feature_name = (
            await session.execute(
                text(
                    # legacy `deleted_at IS NULL AND status NOT IN
                    # ('deleted','hidden')`의 3축 등가물 — lifecycle이 삭제 축,
                    # publication이 감춤 축이다(_RESOLVE_FEATURES_BATCH 주석 참조).
                    "SELECT name FROM feature.features "
                    "WHERE feature_id = :id "
                    "AND lifecycle_state = 'active' "
                    "AND publication_state <> 'suppressed' "
                    "FOR KEY SHARE"
                ),
                {"id": feature_id},
            )
        ).scalar_one_or_none()
        if feature_name is None:
            raise ValueError("feature_id must reference an active Feature")
        if not resolved_place_name:
            resolved_place_name = str(feature_name)
    if not await _lock_collection(session, collection_id):
        raise LookupError("curation collection 없음")
    if not resolved_place_name:
        raise ValueError("place_name or an existing feature_id is required")
    archived_identity_exists = (
        await session.execute(
            text(
                "SELECT 1 FROM feature.curation_items "
                "WHERE collection_id = CAST(:collection_id AS uuid) "
                "AND external_item_id = :external_item_id "
                "AND external_component_id = :external_component_id "
                "AND archived_at IS NOT NULL"
            ),
            {
                "collection_id": collection_id,
                "external_item_id": external_item_id.strip(),
                "external_component_id": external_component_id.strip(),
            },
        )
    ).scalar_one_or_none()
    if archived_identity_exists is not None:
        raise ValueError("archive된 curation item identity는 재사용할 수 없습니다.")
    if feature_id is not None:
        duplicate_feature_exists = (
            await session.execute(
                text(
                    "SELECT 1 FROM feature.curation_items "
                    "WHERE collection_id = CAST(:collection_id AS uuid) "
                    "AND external_item_id = :external_item_id "
                    "AND external_component_id <> :external_component_id "
                    "AND feature_id = :feature_id "
                    "AND source_present "
                    "AND archived_at IS NULL"
                ),
                {
                    "collection_id": collection_id,
                    "external_item_id": external_item_id.strip(),
                    "external_component_id": external_component_id.strip(),
                    "feature_id": feature_id,
                },
            )
        ).scalar_one_or_none()
        if duplicate_feature_exists is not None:
            raise ValueError("같은 외부 항목의 다른 component가 이미 이 Feature를 참조합니다.")
    row = (
        (
            await session.execute(
                text(_UPSERT_ITEM_SQL),
                {
                    "collection_id": collection_id,
                    "feature_id": feature_id,
                    "source_record_key": source_record_key,
                    "external_item_id": external_item_id.strip(),
                    "external_component_id": external_component_id.strip(),
                    "place_name": resolved_place_name,
                    "address_hint": address_hint.strip() if address_hint else None,
                    "status": status,
                    "sort_order": sort_order,
                    "item_title": item_title,
                    "item_summary": item_summary,
                    "curation_relation": curation_relation,
                    "reuse_policy": reuse_policy,
                    "metadata": json.dumps(dict(metadata or {})),
                    "actor": actor,
                },
            )
        )
        .mappings()
        .one()
    )
    item_id = str(row["curation_item_id"])
    previous_decision = (
        (
            await session.execute(
                text(
                    """
                    SELECT
                        item.accepted_link_decision_id::text AS decision_id,
                        decision.feature_id
                    FROM feature.curation_items AS item
                    LEFT JOIN feature.curation_link_decisions AS decision
                      ON decision.decision_id =
                         item.accepted_link_decision_id
                    WHERE item.curation_item_id =
                          CAST(:curation_item_id AS uuid)
                    """
                ),
                {"curation_item_id": item_id},
            )
        )
        .mappings()
        .one()
    )
    previous_decision_id = (
        str(previous_decision["decision_id"]) if previous_decision["decision_id"] else None
    )
    if feature_id is not None:
        await _record_manual_link_decision(
            session,
            curation_item_id=item_id,
            feature_id=feature_id,
            decision_kind="accepted",
            actor=actor,
            supersedes_decision_id=previous_decision_id,
            evidence={
                "operation": "add_curation_item",
                "requested_feature_id": feature_id,
            },
        )
    elif previous_decision_id is not None:
        await _record_manual_link_decision(
            session,
            curation_item_id=item_id,
            feature_id=str(previous_decision["feature_id"]),
            decision_kind="revoked",
            actor=actor,
            supersedes_decision_id=previous_decision_id,
            evidence={
                "operation": "add_curation_item",
                "reason": "명시적 feature_id=null",
            },
        )
    item_row = (
        (
            await session.execute(
                text(_ITEM_SELECT + " WHERE i.curation_item_id = CAST(:id AS uuid)"),
                {"id": item_id},
            )
        )
        .mappings()
        .one()
    )
    await _touch_collection(session, collection_id=collection_id, actor=actor)
    return _item(item_row), bool(row["inserted"])


async def update_curation_item(
    session: AsyncSession,
    *,
    collection_id: str,
    curation_item_id: str,
    updates: Mapping[str, Any],
    actor: str | None = None,
    expected_revision: int | None = None,
) -> CurationItem | None:
    """단일 membership을 부분 수정한다. 명시적 ``feature_id=null``도 보존한다."""

    allowed = {
        "feature_id",
        "source_record_key",
        "external_item_id",
        "external_component_id",
        "place_name",
        "address_hint",
        "status",
        "sort_order",
        "item_title",
        "item_summary",
        "curation_relation",
        "reuse_policy",
        "metadata",
    }
    normalized: dict[str, Any] = {}
    for key, value in updates.items():
        if key not in allowed:
            raise ValueError(f"unsupported curation item field: {key}")
        if key == "status" and value not in _ITEM_STATUSES:
            raise ValueError("invalid curation item status")
        if key == "curation_relation" and value not in _RELATIONS:
            raise ValueError("invalid curation item relation")
        if key == "reuse_policy" and value not in _REUSE_POLICIES:
            raise ValueError("invalid curation item reuse policy")
        if key == "sort_order" and (
            not isinstance(value, int) or not 0 <= value <= _POSTGRES_INTEGER_MAX
        ):
            raise ValueError("invalid curation item sort order")
        if key in {"external_item_id", "external_component_id", "place_name"}:
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{key} must not be empty")
            value = value.strip()
        if key == "address_hint" and isinstance(value, str):
            value = value.strip() or None
        if key == "metadata":
            if not isinstance(value, Mapping):
                raise ValueError("curation item metadata must be an object")
            value = json.dumps(dict(value))
        normalized[key] = value

    if not normalized:
        if not await _lock_collection(session, collection_id):
            return None
        current = await get_curation_item(
            session,
            collection_id=collection_id,
            curation_item_id=curation_item_id,
            include_archived=True,
        )
        if (
            current is not None
            and expected_revision is not None
            and current.row_revision != expected_revision
        ):
            raise CurationRevisionConflictError("curation item revision이 stale입니다.")
        return current if current is not None and current.archived_at is None else None

    source_owned_changed = bool(
        {
            "feature_id",
            "source_record_key",
            "external_item_id",
            "external_component_id",
            "place_name",
            "address_hint",
            "sort_order",
            "item_title",
            "item_summary",
            "metadata",
        }
        & normalized.keys()
    )
    target_feature_id = normalized.get("feature_id")
    if target_feature_id is not None:
        target_is_active = (
            await session.execute(
                text(
                    # 위 add 가드와 같은 legacy 술어의 3축 등가물이다.
                    "SELECT 1 FROM feature.features "
                    "WHERE feature_id = :feature_id "
                    "AND lifecycle_state = 'active' "
                    "AND publication_state <> 'suppressed' "
                    "FOR KEY SHARE"
                ),
                {"feature_id": target_feature_id},
            )
        ).scalar_one_or_none()
        if target_is_active is None:
            raise ValueError("feature_id에 해당하는 Feature가 없습니다.")

    if not await _lock_collection(session, collection_id):
        return None
    current = await get_curation_item(
        session,
        collection_id=collection_id,
        curation_item_id=curation_item_id,
        include_archived=True,
    )
    if current is None or current.archived_at is not None:
        return None

    feature_id = normalized.get("feature_id", current.feature_id)
    if {
        "feature_id",
        "external_item_id",
        "external_component_id",
    } & normalized.keys():
        target_external_item_id = str(normalized.get("external_item_id", current.external_item_id))
        target_external_component_id = str(
            normalized.get(
                "external_component_id",
                current.external_component_id,
            )
        )
        archived_identity_exists = (
            await session.execute(
                text(
                    "SELECT 1 FROM feature.curation_items "
                    "WHERE collection_id = CAST(:collection_id AS uuid) "
                    "AND curation_item_id <> CAST(:curation_item_id AS uuid) "
                    "AND external_item_id = :external_item_id "
                    "AND external_component_id = :external_component_id "
                    "AND archived_at IS NOT NULL"
                ),
                {
                    "collection_id": collection_id,
                    "curation_item_id": curation_item_id,
                    "external_item_id": target_external_item_id,
                    "external_component_id": target_external_component_id,
                },
            )
        ).scalar_one_or_none()
        if archived_identity_exists is not None:
            raise ValueError("archive된 curation item identity는 재사용할 수 없습니다.")

        if current.source_present and feature_id is not None:
            duplicate_feature_exists = (
                await session.execute(
                    text(
                        "SELECT 1 FROM feature.curation_items "
                        "WHERE collection_id = CAST(:collection_id AS uuid) "
                        "AND curation_item_id <> CAST(:curation_item_id AS uuid) "
                        "AND external_item_id = :external_item_id "
                        "AND feature_id = :feature_id "
                        "AND source_present "
                        "AND archived_at IS NULL"
                    ),
                    {
                        "collection_id": collection_id,
                        "curation_item_id": curation_item_id,
                        "external_item_id": target_external_item_id,
                        "feature_id": feature_id,
                    },
                )
            ).scalar_one_or_none()
            if duplicate_feature_exists is not None:
                raise ValueError("같은 외부 항목의 다른 component가 이미 이 Feature를 참조합니다.")
    clauses: list[str] = []
    params: dict[str, Any] = {
        "collection_id": collection_id,
        "curation_item_id": curation_item_id,
        "actor": actor,
        "expected_revision": expected_revision,
    }
    for key, value in normalized.items():
        if key == "metadata":
            clauses.append("metadata = CAST(:metadata AS jsonb)")
        else:
            clauses.append(f"{key} = :{key}")
        params[key] = value
    operator_owned_changed = bool(
        {"status", "curation_relation", "reuse_policy"} & normalized.keys()
    )
    if source_owned_changed:
        clauses.append("source_updated_at = clock_timestamp()")
    if operator_owned_changed:
        clauses.extend(
            [
                "operator_updated_by = :actor",
                "operator_updated_at = clock_timestamp()",
            ]
        )
    clauses.extend(
        [
            "updated_by = :actor",
            "updated_at = now()",
            "row_revision = row_revision + 1",
        ]
    )
    if normalized.get("status") == "archived":
        clauses.append("archived_at = now()")
    row = (
        await session.execute(
            text(
                f"""
                UPDATE feature.curation_items
                SET {", ".join(clauses)}
                WHERE collection_id = CAST(:collection_id AS uuid)
                  AND curation_item_id = CAST(:curation_item_id AS uuid)
                  AND archived_at IS NULL
                  AND (
                      CAST(:expected_revision AS bigint) IS NULL
                      OR row_revision = CAST(:expected_revision AS bigint)
                  )
                RETURNING curation_item_id::text
                """
            ),
            params,
        )
    ).first()
    if row is None:
        if expected_revision is not None and await get_curation_item(
            session,
            collection_id=collection_id,
            curation_item_id=curation_item_id,
            include_archived=True,
        ):
            raise CurationRevisionConflictError("curation item revision이 stale입니다.")
        return None
    if "feature_id" in normalized:
        requested_feature_id = normalized["feature_id"]
        if requested_feature_id is not None:
            await _record_manual_link_decision(
                session,
                curation_item_id=curation_item_id,
                feature_id=str(requested_feature_id),
                decision_kind="accepted",
                actor=actor,
                supersedes_decision_id=current.accepted_link_decision_id,
                evidence={
                    "operation": "update_curation_item",
                    "previous_feature_id": current.feature_id,
                    "requested_feature_id": requested_feature_id,
                },
            )
        elif current.feature_id is not None:
            await _record_manual_link_decision(
                session,
                curation_item_id=curation_item_id,
                feature_id=current.feature_id,
                decision_kind="revoked",
                actor=actor,
                supersedes_decision_id=current.accepted_link_decision_id,
                evidence={
                    "operation": "update_curation_item",
                    "previous_feature_id": current.feature_id,
                    "reason": "명시적 feature_id=null",
                },
            )
    await _touch_collection(session, collection_id=collection_id, actor=actor)
    return await get_curation_item(
        session,
        collection_id=collection_id,
        curation_item_id=curation_item_id,
        include_archived=True,
    )


async def archive_curation_item(
    session: AsyncSession,
    *,
    collection_id: str,
    curation_item_id: str,
    actor: str | None = None,
    expected_revision: int | None = None,
) -> CurationItem | None:
    return await update_curation_item(
        session,
        collection_id=collection_id,
        curation_item_id=curation_item_id,
        updates={"status": "archived"},
        actor=actor,
        expected_revision=expected_revision,
    )


async def get_feature_curation_group(
    session: AsyncSession, *, feature_id: str, public_only: bool = True
) -> FeatureCurationGroup | None:
    """feature 1건의 큐레이션 group을 조회한다.

    feature 자체의 공개 여부는 ``public_only``와 무관하게 항상 ADR-067
    ``feature.public_features`` projection을 따른다(공개 표면 전용 read).
    ``public_only``는 collection/item 상태(published·included·public) 필터만
    제어한다.
    """
    feature = (
        (await session.execute(text(_GET_FEATURE_SQL), {"feature_id": feature_id}))
        .mappings()
        .first()
    )
    if feature is None:
        return None
    item_rows = (
        (
            await session.execute(
                text(_LIST_FEATURE_ITEMS_SQL),
                {"feature_id": feature_id, "public_only": public_only},
            )
        )
        .mappings()
        .all()
    )
    if not item_rows:
        return None
    return FeatureCurationGroup(
        feature_id=str(feature["feature_id"]),
        name=str(feature["name"]),
        kind=str(feature["kind"]),
        category=str(feature["category"]),
        lon=float(feature["lon"]) if feature["lon"] is not None else None,
        lat=float(feature["lat"]) if feature["lat"] is not None else None,
        address=_object(feature["address"]),
        lifecycle_state=str(feature["lifecycle_state"]),
        publication_state=str(feature["publication_state"]),
        quality_state=str(feature["quality_state"]),
        curations=tuple(_item(row) for row in item_rows),
        feature_uuid=(str(value) if (value := feature.get("feature_uuid")) else None),
    )


async def list_curation_items_by_feature_ids(
    session: AsyncSession,
    *,
    feature_ids: Sequence[str],
    public_only: bool = True,
) -> dict[str, tuple[CurationItem, ...]]:
    if not feature_ids:
        return {}
    rows = (
        (
            await session.execute(
                text(_LIST_FEATURE_ITEMS_BATCH_SQL),
                {
                    "feature_ids": list(dict.fromkeys(feature_ids)),
                    "public_only": public_only,
                },
            )
        )
        .mappings()
        .all()
    )
    grouped: dict[str, list[CurationItem]] = {}
    for row in rows:
        item = _item(row)
        if item.feature_id is not None:
            grouped.setdefault(item.feature_id, []).append(item)
    return {feature_id: tuple(items) for feature_id, items in grouped.items()}


async def list_unattributed_curation_links(
    session: AsyncSession,
    *,
    limit: int = 500,
) -> tuple[CurationLinkAudit, ...]:
    """첫 audit page만 읽는 기존 내부 호출용 편의 함수."""

    rows, _next_cursor = await list_unattributed_curation_links_page(
        session,
        limit=limit,
    )
    return rows


async def list_unattributed_curation_links_page(
    session: AsyncSession,
    *,
    limit: int = 500,
    cursor: str | None = None,
) -> tuple[tuple[CurationLinkAudit, ...], str | None]:
    """unsafe current link를 stable UUID total order로 전진 조회한다."""

    effective_limit = max(1, min(limit, 10_000))
    decoded_cursor = decode_link_audit_cursor(cursor)
    row_mappings = (
        (
            await session.execute(
                text(_LIST_UNATTRIBUTED_LINKS_SQL),
                {
                    "limit": effective_limit + 1,
                    "cursor_collection_id": (decoded_cursor[0] if decoded_cursor else None),
                    "cursor_curation_item_id": (decoded_cursor[1] if decoded_cursor else None),
                },
            )
        )
        .mappings()
        .all()
    )
    page_rows = row_mappings[:effective_limit]
    next_cursor = None
    if len(row_mappings) > effective_limit and page_rows:
        last = page_rows[-1]
        next_cursor = encode_link_audit_cursor(
            str(last["collection_id"]),
            str(last["curation_item_id"]),
        )
    return tuple(_link_audit(row) for row in page_rows), next_cursor


async def list_curation_quarantine_collections(
    session: AsyncSession,
    *,
    limit: int = 50,
    cursor: str | None = None,
) -> tuple[tuple[CurationQuarantineCollection, ...], str | None]:
    """`0065` 정본 marker 술어로 격리 collection page를 keyset 조회한다 (T-VN-H22A).

    실데이터 격리는 현재 0건이 정상이므로 빈 목록이 정상 경로다.
    """

    effective_limit = max(1, min(limit, 200))
    cursor_collection_id = decode_quarantine_collection_cursor(cursor)
    rows = (
        (
            await session.execute(
                text(_LIST_QUARANTINE_COLLECTIONS_SQL),
                {
                    "cursor_collection_id": cursor_collection_id,
                    "limit": effective_limit + 1,
                },
            )
        )
        .mappings()
        .all()
    )
    page = tuple(_quarantine_collection(row) for row in rows[:effective_limit])
    next_cursor = (
        encode_quarantine_collection_cursor(page[-1].collection_id)
        if len(rows) > effective_limit and page
        else None
    )
    return page, next_cursor


async def _get_quarantine_collection_metadata(
    session: AsyncSession,
    *,
    collection_id: str,
) -> dict[str, Any] | None:
    """정본 marker 술어에 걸리는 격리 collection의 metadata — 아니면 ``None``."""

    row = (
        (
            await session.execute(
                text(_GET_QUARANTINE_COLLECTION_SQL),
                {"collection_id": collection_id},
            )
        )
        .mappings()
        .first()
    )
    return _object(row["metadata"]) if row is not None else None


async def list_curation_quarantine_items(
    session: AsyncSession,
    *,
    collection_id: str,
    target_collection_id: str | None = None,
    limit: int = 50,
    cursor: str | None = None,
) -> tuple[CurationQuarantineItemsPreview, str | None] | None:
    """격리 item page + target 대비 (A)/(B) conflict preview (순수 SELECT, T-VN-H22A).

    target은 명시값이 없으면 marker가 기록한 원본 collection이다. 격리 collection이
    정본 술어에 안 걸리면 ``None``을 반환한다 (router 404).
    """

    normalized_collection_id = str(UUID(collection_id))
    metadata = await _get_quarantine_collection_metadata(
        session, collection_id=normalized_collection_id
    )
    if metadata is None:
        return None
    resolved_target = (
        str(UUID(target_collection_id))
        if target_collection_id is not None
        else _quarantine_original_collection_id(metadata)
    )
    # preview와 command의 판정을 일치시킨다 (적대 리뷰 F2/F3). command가 422로 거부하는
    # 입력을 preview가 "전 item 자기 충돌"이나 정상 preview로 보여주면 운영자를 오도한다.
    if resolved_target == normalized_collection_id:
        raise ValueError("target collection이 격리 collection 자신일 수 없습니다.")
    target_missing = True
    target_archived = False
    target_collection_revision: int | None = None
    if resolved_target is not None:
        target_row = (
            (
                await session.execute(
                    text(
                        "SELECT archived_at, created_by, metadata, row_revision "
                        "FROM feature.curation_collections "
                        "WHERE collection_id = CAST(:collection_id AS uuid)"
                    ),
                    {"collection_id": resolved_target},
                )
            )
            .mappings()
            .first()
        )
        if target_row is not None:
            if _is_quarantine_marker_row(target_row):
                raise ValueError(
                    "target이 또 다른 격리 collection입니다 — 격리 간 이동은 "
                    "0065 모집단을 조용히 섞으므로 허용하지 않습니다."
                )
            target_missing = False
            target_archived = target_row["archived_at"] is not None
            target_collection_revision = int(target_row["row_revision"])
    unresolved_kind: str | None = None
    if resolved_target is None:
        unresolved_kind = QUARANTINE_CONFLICT_NO_TARGET
    elif target_missing:
        unresolved_kind = QUARANTINE_CONFLICT_TARGET_MISSING
    effective_limit = max(1, min(limit, 200))
    cursor_item_id = decode_quarantine_item_cursor(cursor)
    rows = (
        (
            await session.execute(
                text(_LIST_QUARANTINE_ITEMS_SQL),
                {
                    "collection_id": normalized_collection_id,
                    "target_collection_id": (resolved_target if unresolved_kind is None else None),
                    "cursor_curation_item_id": cursor_item_id,
                    "limit": effective_limit + 1,
                },
            )
        )
        .mappings()
        .all()
    )
    items = tuple(
        _quarantine_item(row, unresolved_kind=unresolved_kind) for row in rows[:effective_limit]
    )
    next_cursor = (
        encode_quarantine_item_cursor(items[-1].curation_item_id)
        if len(rows) > effective_limit and items
        else None
    )
    preview = CurationQuarantineItemsPreview(
        target_collection_id=resolved_target,
        target_collection_revision=target_collection_revision,
        target_missing=target_missing,
        target_archived=target_archived,
        items=items,
    )
    return preview, next_cursor


def _is_quarantine_marker_row(row: RowMapping | Mapping[str, Any]) -> bool:
    """FOR UPDATE로 잠근 collection 행에서 정본 marker를 재검증한다."""

    metadata = _object(row["metadata"])
    return row["created_by"] == "migration:0065" and metadata.get("migration_quarantine") == "0065"


async def move_curation_quarantine_items(
    session: AsyncSession,
    *,
    collection_id: str,
    expected_collection_revision: int,
    target_collection_id: str | None = None,
    expected_target_revision: int,
    item_ids: Sequence[str] | None = None,
    command_id: int,
    actor: str,
) -> tuple[tuple[str, ...], bool]:
    """격리 membership을 typed domain command로 원자 이동한다."""

    result = (
        await session.execute(
            text(
                """
                CALL feature.reclassify_curation_quarantine_command(
                  CAST(:collection_id AS uuid), :expected_collection_revision,
                  'move', CAST(:target_collection_id AS uuid),
                  :expected_target_revision, CAST(:item_ids AS uuid[]),
                  NULL, NULL, :command_id, :principal,
                  NULL, NULL, NULL, NULL, NULL, NULL
                )
                """
            ),
            {
                "collection_id": str(UUID(collection_id)),
                "command_id": command_id,
                "expected_collection_revision": expected_collection_revision,
                "expected_target_revision": expected_target_revision,
                "item_ids": (
                    [str(UUID(item_id)) for item_id in item_ids]
                    if item_ids is not None
                    else None
                ),
                "principal": actor,
                "target_collection_id": (
                    str(UUID(target_collection_id))
                    if target_collection_id is not None
                    else None
                ),
            },
        )
    ).mappings().one()
    conflicts = result["o_conflicts"] or []
    if conflicts:
        raise CurationQuarantineMoveConflictError(
            tuple(
                CurationQuarantineMoveConflict(
                    curation_item_id=str(conflict["curation_item_id"]),
                    conflict_kind=str(conflict["conflict_kind"]),
                    conflict_item_id=str(conflict["conflict_item_id"]),
                )
                for conflict in conflicts
            )
        )
    return (
        tuple(str(value) for value in (result["o_moved_item_ids"] or ())),
        bool(result["o_quarantine_deleted"]),
    )


async def confirm_curation_quarantine_standalone(
    session: AsyncSession,
    *,
    collection_id: str,
    expected_collection_revision: int,
    collection_key: str,
    title: str,
    command_id: int,
    actor: str,
) -> tuple[str, str]:
    """격리 collection을 typed domain command로 standalone 확정한다."""

    normalized_key = collection_key.strip()
    normalized_title = title.strip()
    if not normalized_key or not normalized_title:
        raise ValueError("collection_key and title are required")
    result = (
        await session.execute(
            text(
                """
                CALL feature.reclassify_curation_quarantine_command(
                  CAST(:collection_id AS uuid), :expected_collection_revision,
                  'confirm_standalone', NULL, NULL, NULL,
                  :collection_key, :title, :command_id, :principal,
                  NULL, NULL, NULL, NULL, NULL, NULL
                )
                """
            ),
            {
                "collection_id": str(UUID(collection_id)),
                "collection_key": normalized_key,
                "command_id": command_id,
                "expected_collection_revision": expected_collection_revision,
                "principal": actor,
                "title": normalized_title,
            },
        )
    ).mappings().one()
    return str(result["o_collection_id"]), str(result["o_collection_key"])


async def list_feature_curation_groups(
    session: AsyncSession,
    *,
    public_only: bool = True,
    theme_slug: str | None = None,
    edition_key: str | None = None,
    provider_dataset_id: int | None = None,
    q: str | None = None,
    min_lon: float | None = None,
    min_lat: float | None = None,
    max_lon: float | None = None,
    max_lat: float | None = None,
    page_size: int = 100,
    cursor: str | None = None,
) -> tuple[tuple[FeatureCurationGroup, ...], str | None]:
    bbox_values = (min_lon, min_lat, max_lon, max_lat)
    bbox_enabled = all(value is not None for value in bbox_values)
    if any(value is not None for value in bbox_values) and not bbox_enabled:
        raise ValueError("bbox coordinates must be provided together")
    cursor_feature_id = decode_group_cursor(cursor)
    effective_size = max(1, min(page_size, 500))
    key_rows = (
        (
            await session.execute(
                text(_LIST_GROUP_KEYS_SQL),
                {
                    "public_only": public_only,
                    "theme_slug": theme_slug,
                    "edition_key": edition_key,
                    "provider_dataset_id": provider_dataset_id,
                    "q": f"%{q.strip()}%" if q and q.strip() else None,
                    "bbox_enabled": bbox_enabled,
                    "min_lon": min_lon,
                    "min_lat": min_lat,
                    "max_lon": max_lon,
                    "max_lat": max_lat,
                    "cursor_feature_id": cursor_feature_id,
                    "limit": effective_size + 1,
                },
            )
        )
        .mappings()
        .all()
    )
    page_keys = [str(row["feature_id"]) for row in key_rows[:effective_size]]
    feature_rows = (
        (await session.execute(text(_GET_FEATURES_BY_IDS_SQL), {"feature_ids": page_keys}))
        .mappings()
        .all()
        if page_keys
        else []
    )
    features = {str(row["feature_id"]): row for row in feature_rows}
    grouped_items = await list_curation_items_by_feature_ids(
        session, feature_ids=page_keys, public_only=public_only
    )
    groups = []
    for feature_id in page_keys:
        feature = features.get(feature_id)
        if feature is None:
            continue
        groups.append(
            FeatureCurationGroup(
                feature_id=feature_id,
                name=str(feature["name"]),
                kind=str(feature["kind"]),
                category=str(feature["category"]),
                lon=float(feature["lon"]) if feature["lon"] is not None else None,
                lat=float(feature["lat"]) if feature["lat"] is not None else None,
                address=_object(feature["address"]),
                lifecycle_state=str(feature["lifecycle_state"]),
                publication_state=str(feature["publication_state"]),
                quality_state=str(feature["quality_state"]),
                curations=grouped_items.get(feature_id, ()),
                feature_uuid=(str(value) if (value := feature.get("feature_uuid")) else None),
            )
        )
    next_cursor = (
        encode_group_cursor(page_keys[-1]) if len(key_rows) > effective_size and page_keys else None
    )
    return tuple(groups), next_cursor


async def resolve_feature_match(
    session: AsyncSession,
    *,
    feature_id: str | None,
    place_name: str | None,
    address_hint: str | None,
) -> tuple[FeatureMatch, ...]:
    matches = await resolve_feature_matches(
        session,
        requests=(
            FeatureMatchRequest(
                row_number=0,
                feature_id=feature_id,
                place_name=place_name,
                address_hint=address_hint,
            ),
        ),
    )
    return matches.get(0, ())


async def resolve_feature_matches(
    session: AsyncSession,
    *,
    requests: Sequence[FeatureMatchRequest],
    frozen_h35_schema: bool = False,
) -> dict[int, tuple[FeatureMatch, ...]]:
    """CSV 전체의 exact Feature/name 후보를 한 번의 parameterized query로 찾는다.

    DB는 ``lower(name)`` index로 후보만 좁힌다. 주소는 JSON serialization/SQL pattern을
    전혀 사용하지 않고 Python의 구조화 literal matcher로 판정한다.

    ``frozen_h35_schema``: h35 cutover CLI 전용 — 0063~0079 고정 세대에서
    matcher를 돌릴 때 True. 그 세대엔 ``feature_uuid`` column(0080)도
    ``feature.feature_notices``(0085)도 없다. 후보의 ``feature_uuid``는
    None으로 채워진다.
    """

    if not requests:
        return {}
    payload = [
        {
            "row_number": request.row_number,
            "feature_id": request.feature_id.strip() if request.feature_id else None,
            "place_name": normalize_korean_text(request.place_name),
            "address_hint": normalize_korean_text(request.address_hint),
        }
        for request in requests
    ]
    rows = (
        (
            await session.execute(
                text(
                    _RESOLVE_FEATURES_BATCH_PRE_UUID_SQL
                    if frozen_h35_schema
                    else _RESOLVE_FEATURES_BATCH_SQL
                ),
                {"requests": json.dumps(payload, ensure_ascii=False)},
            )
        )
        .mappings()
        .all()
    )
    requests_by_row = {request.row_number: request for request in requests}
    grouped: dict[int, list[FeatureMatch]] = {request.row_number: [] for request in requests}
    for row in rows:
        row_number = int(row["row_number"])
        request = requests_by_row[row_number]
        if (
            request.feature_id is None
            and int(row["name_candidate_count"]) > _FEATURE_MATCH_NAME_CANDIDATE_LIMIT
        ):
            # 상한 밖 후보를 보지 않고 "유일"로 오판하지 않는다.
            grouped[row_number].clear()
            continue
        match = _feature_match(row)
        normalized_hint = normalize_korean_text(request.address_hint)
        if (
            request.feature_id is None
            and normalized_hint is not None
            and not address_hint_matches(match.address, normalized_hint)
        ):
            continue
        grouped[row_number].append(match)
    return {row_number: tuple(items) for row_number, items in grouped.items()}


async def upsert_curation_theme(
    session: AsyncSession,
    *,
    theme_slug: str,
    theme_name: str,
    theme_group: str,
) -> str:
    """수동 입력/CSV가 참조하는 기존 retained theme을 exact match로 해소한다."""

    if not theme_slug.strip() or not theme_name.strip() or not theme_group.strip():
        raise ValueError("theme_slug, theme_name and theme_group are required")
    await _lock_curation_write_boundary(session)
    params = {
        "theme_slug": theme_slug.strip(),
        "theme_name": theme_name.strip(),
        "theme_group": theme_group.strip(),
    }
    value = (await session.execute(text(_RESOLVE_THEME_SQL), params)).scalar_one_or_none()
    if value is None:
        raise ValueError(
            "theme은 retained catalog에서 먼저 생성해야 하며 "
            "slug/name/group이 정확히 일치해야 합니다."
        )
    return str(value)


def validate_resolved_curation_identities(
    rows: Sequence[ResolvedCurationImportRow],
) -> tuple[ResolvedCurationIdentityIssue, ...]:
    """실제 Feature 해소 결과의 component·target identity 충돌을 찾는다."""

    by_component: dict[tuple[str, str, str], list[ResolvedCurationImportRow]] = {}
    by_feature: dict[tuple[str, str, str], list[ResolvedCurationImportRow]] = {}
    for row in rows:
        by_component.setdefault(
            (row.collection_key, row.source_item_key, row.source_component_key),
            [],
        ).append(row)
        if row.feature_id is not None:
            by_feature.setdefault(
                (row.collection_key, row.source_item_key, row.feature_id),
                [],
            ).append(row)

    issues: dict[tuple[int, str], ResolvedCurationIdentityIssue] = {}
    for grouped_rows in by_component.values():
        if len(grouped_rows) > 1:
            for row in grouped_rows:
                issue = ResolvedCurationIdentityIssue(
                    row_number=row.row_number,
                    code="duplicate_component_identity",
                    message=(
                        "Feature 해소 후 collection/source_item_key/"
                        "source_component_key identity가 중복됩니다."
                    ),
                )
                issues[(issue.row_number, issue.code)] = issue
    for grouped_rows in by_feature.values():
        if len(grouped_rows) > 1:
            for row in grouped_rows:
                issue = ResolvedCurationIdentityIssue(
                    row_number=row.row_number,
                    code="duplicate_resolved_feature",
                    message=(
                        "같은 collection/source_item_key의 component가 "
                        "동일 Feature를 중복 참조합니다."
                    ),
                )
                issues[(issue.row_number, issue.code)] = issue
    return tuple(issues[key] for key in sorted(issues, key=lambda value: (value[0], value[1])))


def _ensure_resolved_curation_identities(
    rows: Sequence[ResolvedCurationImportRow],
) -> None:
    if any(not 0 <= row.sort_order <= _POSTGRES_INTEGER_MAX for row in rows):
        raise ValueError("curation item sort_order is outside the PostgreSQL integer range")
    issues = validate_resolved_curation_identities(rows)
    if issues:
        raise ValueError(issues[0].message)


def _ensure_curation_dataset_identity(
    rows: Sequence[ResolvedCurationImportRow],
    *,
    frozen_h35_schema: bool,
) -> None:
    """행이 든 dataset identity가 실행 대상 스키마 세대와 일치하는지 확인한다.

    ``provider_dataset_id``를 ``int | None``으로 푼 것은 고정 세대에 그 열이
    없기 때문일 뿐이다. 그 완화가 현행 스키마의 NOT NULL identity를 무르게
    만들지 않도록, write 경계에서 정확히 한 쪽만 채워졌음을 강제한다.
    """

    for row in rows:
        if frozen_h35_schema:
            if row.frozen_h35_dataset is None or row.provider_dataset_id is not None:
                raise ValueError(
                    "0063~0079 고정 세대 import는 (provider, dataset_key) 자연키만 "
                    f"들어야 합니다: row_number={row.row_number}"
                )
        elif row.provider_dataset_id is None or row.frozen_h35_dataset is not None:
            raise ValueError(
                "현행 스키마 import는 provider_dataset_id surrogate만 들어야 합니다: "
                f"row_number={row.row_number}"
            )


def _canonical_import_row_payload(
    row: ResolvedCurationImportRow,
) -> dict[str, Any]:
    # 영속되는 provenance payload는 그 세대가 실제로 갖는 dataset identity를
    # 적는다. 고정 세대에 surrogate를 적으면 가리키는 대상이 없는 값이 남고,
    # 현행 스키마에 자연키를 적으면 삭제된 사본이 되살아난다.
    dataset_identity: dict[str, Any] = (
        {"provider": row.frozen_h35_dataset[0], "dataset_key": row.frozen_h35_dataset[1]}
        if row.frozen_h35_dataset is not None
        else {"provider_dataset_id": row.provider_dataset_id}
    )
    return {
        "row_number": row.row_number,
        "collection_key": row.collection_key,
        "theme_slug": row.theme_slug,
        "theme_name": row.theme_name,
        "theme_group": row.theme_group,
        "title": row.title,
        "edition_key": row.edition_key,
        **dataset_identity,
        "source_name": row.source_name,
        "source_url": row.source_url,
        "source_item_key": row.source_item_key,
        "source_component_key": row.source_component_key,
        "feature_id": row.feature_id,
        "place_name": row.place_name,
        "address_hint": row.address_hint,
        "sort_order": row.sort_order,
        "item_title": row.item_title,
        "item_summary": row.item_summary,
        "metadata": row.metadata,
        "manual_feature": row.manual_feature,
        "manual_feature_sha256": row.manual_feature_sha256,
    }


def _canonical_json_sha256(value: object) -> str:
    serialized = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(serialized).hexdigest()


def _validated_sha256(value: str) -> str:
    normalized = value.strip().lower()
    if len(normalized) != 64 or any(
        character not in "0123456789abcdef" for character in normalized
    ):
        raise ValueError("content_sha256는 lowercase SHA-256 hex여야 합니다.")
    return normalized


async def _record_import_provenance(
    session: AsyncSession,
    *,
    rows: Sequence[ResolvedCurationImportRow],
    actor: str | None,
    source_content_sha256: str | None,
    batch_kind: str | None,
    command_id: int | None,
) -> tuple[str, tuple[ImportRowReceipt, ...]]:
    """current item을 exact immutable import row/decision으로 전진시킨다.

    ``import_batch_id``와 함께 **행별 좌표**를 돌려준다. `301` linkage가 그 셋을
    결박하므로, caller가 나중에 DB를 되짚어 추론하지 않게 한다.
    """

    effective_actor = (actor or "system:curation-import").strip()
    if not effective_actor:
        raise ValueError("curation import actor는 비어 있을 수 없습니다.")
    canonical_rows = [_canonical_import_row_payload(row) for row in rows]
    effective_content_sha256 = (
        _validated_sha256(source_content_sha256)
        if source_content_sha256 is not None
        else _canonical_json_sha256(canonical_rows)
    )
    effective_kind = batch_kind or (
        "csv_upload" if source_content_sha256 is not None else "normalized_rows"
    )
    if effective_kind not in {
        "csv_upload",
        "normalized_rows",
        "forward_recovery",
    }:
        raise ValueError("지원하지 않는 curation import batch_kind입니다.")
    decision_match_basis = (
        "forward_recovery" if effective_kind == "forward_recovery" else "csv_explicit_feature_id"
    )
    decision_resolver_version = (
        "forward-recovery-v1" if effective_kind == "forward_recovery" else "explicit-feature-id-v1"
    )

    import_batch_id = str(
        (
            await session.execute(
                text(_INSERT_IMPORT_BATCH_SQL),
                {
                    "content_sha256": effective_content_sha256,
                    "batch_kind": effective_kind,
                    "row_count": len(rows),
                    "actor": effective_actor,
                    "command_id": command_id,
                    "metadata": json.dumps(
                        {
                            "schema_version": 1,
                            "address_resolver": CURATION_ADDRESS_RESOLVER_VERSION,
                        },
                        ensure_ascii=False,
                    ),
                },
            )
        ).scalar_one()
    )
    if not rows:
        # 반환형을 tuple로 바꾸면서 이 조기 반환을 놓쳤다. 빈 CSV면 호출부의
        # `import_batch_id, row_receipts = await …` 언패킹이 ValueError로 죽는다.
        return import_batch_id, ()

    identity_payload = json.dumps(
        [
            {
                "row_number": row.row_number,
                "collection_key": row.collection_key,
                "external_item_id": row.source_item_key,
                "external_component_id": row.source_component_key,
            }
            for row in rows
        ],
        ensure_ascii=False,
    )
    identity_rows = (
        (
            await session.execute(
                text(_IMPORT_ITEM_IDENTITIES_SQL),
                {"items": identity_payload},
            )
        )
        .mappings()
        .all()
    )
    identities = {int(row["row_number"]): row for row in identity_rows}
    if set(identities) != {row.row_number for row in rows}:
        raise RuntimeError("import row를 current curation item에 exact 결박하지 못했습니다.")

    import_rows: list[dict[str, Any]] = []
    decisions: list[dict[str, Any]] = []
    pointers: list[dict[str, Any]] = []
    receipts: list[ImportRowReceipt] = []
    for row, row_payload in zip(rows, canonical_rows, strict=True):
        identity = identities[row.row_number]
        item_is_archived = identity["archived_at"] is not None
        current_feature_id = str(identity["feature_id"]) if identity["feature_id"] else None
        if not item_is_archived and current_feature_id != row.feature_id:
            raise RuntimeError("import 직후 item Feature가 normalized row와 다릅니다.")
        import_row_id = str(uuid4())
        source_row_sha256 = _canonical_json_sha256(row_payload)
        import_rows.append(
            {
                "import_row_id": import_row_id,
                "curation_item_id": str(identity["curation_item_id"]),
                "row_number": row.row_number,
                "source_row_sha256": source_row_sha256,
                "row_payload": row_payload,
                "provenance": row.provenance or {},
            }
        )
        if item_is_archived:
            continue
        previous_decision_id = (
            str(identity["accepted_link_decision_id"])
            if identity["accepted_link_decision_id"]
            else None
        )
        accepted_decision_id: str | None = None
        if row.feature_id is not None:
            accepted_decision_id = str(uuid4())
            decisions.append(
                {
                    "decision_id": accepted_decision_id,
                    "curation_item_id": str(identity["curation_item_id"]),
                    "feature_id": row.feature_id,
                    "import_row_id": import_row_id,
                    "decision_kind": "accepted",
                    "match_basis": decision_match_basis,
                    "resolver_version": decision_resolver_version,
                    "evidence": {
                        "source_row_sha256": source_row_sha256,
                        "requested_feature_id": row.feature_id,
                        "normalized_place_name": normalize_korean_text(row.place_name),
                        "normalized_address_hint": normalize_korean_text(row.address_hint),
                    },
                    "supersedes_decision_id": previous_decision_id,
                }
            )
        elif previous_decision_id is not None:
            previous_feature_id = str(identity["previous_decision_feature_id"])
            decisions.append(
                {
                    "decision_id": str(uuid4()),
                    "curation_item_id": str(identity["curation_item_id"]),
                    "feature_id": previous_feature_id,
                    "import_row_id": import_row_id,
                    "decision_kind": "revoked",
                    "match_basis": decision_match_basis,
                    "resolver_version": decision_resolver_version,
                    "evidence": {
                        "source_row_sha256": source_row_sha256,
                        "previous_feature_id": previous_feature_id,
                        "reason": "authoritative import row에 feature_id가 없음",
                    },
                    "supersedes_decision_id": previous_decision_id,
                }
            )
        pointers.append(
            {
                "curation_item_id": str(identity["curation_item_id"]),
                "import_row_id": import_row_id,
                "accepted_link_decision_id": accepted_decision_id,
            }
        )
        receipts.append(
            ImportRowReceipt(
                row_number=row.row_number,
                import_row_id=import_row_id,
                curation_item_id=str(identity["curation_item_id"]),
                accepted_link_decision_id=accepted_decision_id,
            )
        )

    await session.execute(
        text(_INSERT_IMPORT_ROWS_SQL),
        {
            "import_batch_id": import_batch_id,
            "rows": json.dumps(import_rows, ensure_ascii=False),
        },
    )
    if decisions:
        await session.execute(
            text(_INSERT_LINK_DECISIONS_SQL),
            {
                "actor": effective_actor,
                "decisions": json.dumps(decisions, ensure_ascii=False),
            },
        )
    await session.execute(
        text(_ADVANCE_IMPORT_POINTERS_SQL),
        {"pointers": json.dumps(pointers, ensure_ascii=False)},
    )
    return import_batch_id, tuple(receipts)


async def _record_manual_link_decision(
    session: AsyncSession,
    *,
    curation_item_id: str,
    feature_id: str,
    decision_kind: Literal["accepted", "revoked"],
    actor: str | None,
    supersedes_decision_id: str | None,
    evidence: Mapping[str, Any],
) -> str:
    effective_actor = (actor or "system:curation-admin").strip()
    if not effective_actor:
        raise ValueError("curation link decision actor는 비어 있을 수 없습니다.")
    decision_id = str(
        (
            await session.execute(
                text(_INSERT_MANUAL_LINK_DECISION_SQL),
                {
                    "curation_item_id": curation_item_id,
                    "feature_id": feature_id,
                    "decision_kind": decision_kind,
                    "match_basis": "admin_review",
                    "resolver_version": "manual-admin-v1",
                    "evidence": json.dumps(dict(evidence), ensure_ascii=False),
                    "actor": effective_actor,
                    "supersedes_decision_id": supersedes_decision_id,
                },
            )
        ).scalar_one()
    )
    await session.execute(
        text(
            """
            UPDATE feature.curation_items
            SET accepted_link_decision_id =
                    CASE
                        WHEN :decision_kind = 'accepted'
                        THEN CAST(:decision_id AS uuid)
                        ELSE NULL
                    END
            WHERE curation_item_id = CAST(:curation_item_id AS uuid)
            """
        ),
        {
            "curation_item_id": curation_item_id,
            "decision_id": decision_id,
            "decision_kind": decision_kind,
        },
    )
    return decision_id


async def _ensure_unambiguous_legacy_import_adoptions(
    session: AsyncSession,
    *,
    payload: str,
) -> None:
    conflict = (
        (
            await session.execute(
                text(_LEGACY_IMPORT_ADOPTION_CONFLICTS_SQL),
                {"items": payload},
            )
        )
        .mappings()
        .first()
    )
    if conflict is not None:
        raise ValueError(
            "legacy component identity 승계 후보가 모호합니다: "
            f"collection={conflict['collection_key']}, "
            f"item={conflict['external_item_id']}, "
            f"component={conflict['external_component_id']}, "
            f"feature={conflict['feature_id']}, "
            f"candidates={list(conflict['candidates'])!r}"
        )


async def preview_curation_import(
    session: AsyncSession,
    *,
    rows: Sequence[ResolvedCurationImportRow],
) -> CurationImportPlan:
    """write 없이 CSV 항목 upsert와 authoritative removal을 정확히 예측한다."""

    _ensure_resolved_curation_identities(rows)
    if not rows:
        return CurationImportPlan(collections=0, inserted=0, updated=0, removals=())
    values = [
        {
            "collection_key": row.collection_key,
            "feature_id": row.feature_id,
            "external_item_id": row.source_item_key,
            "external_component_id": row.source_component_key,
            "place_name": row.place_name,
            "address_hint": row.address_hint,
            "sort_order": row.sort_order,
            "item_title": row.item_title,
            "item_summary": row.item_summary,
            "metadata": row.metadata,
        }
        for row in rows
    ]
    payload = json.dumps(values, ensure_ascii=False)
    await _ensure_unambiguous_legacy_import_adoptions(session, payload=payload)
    counts = (
        (await session.execute(text(_PREVIEW_IMPORT_COUNTS_SQL), {"items": payload}))
        .mappings()
        .one()
    )
    removal_rows = (
        (await session.execute(text(_PREVIEW_IMPORT_REMOVALS_SQL), {"items": payload}))
        .mappings()
        .all()
    )
    return CurationImportPlan(
        collections=len({row.collection_key for row in rows}),
        inserted=int(counts["inserted"] or 0),
        updated=int(counts["updated"] or 0),
        removals=tuple(_item(row) for row in removal_rows),
    )


async def build_curation_import_revision_vector(
    session: AsyncSession,
    *,
    rows: Sequence[ResolvedCurationImportRow],
) -> tuple[CurationImportRevisionExpectation, ...]:
    """resolved import set이 읽은 retained catalog와 membership revision을 닫는다."""

    _ensure_resolved_curation_identities(rows)
    _ensure_curation_dataset_identity(rows, frozen_h35_schema=False)
    expectations: dict[tuple[str, str], int | None] = {}
    representatives: dict[str, ResolvedCurationImportRow] = {}
    for row in rows:
        representatives.setdefault(row.collection_key, row)

    for collection_key in sorted(representatives):
        row = representatives[collection_key]
        theme = (
            (
                await session.execute(
                    text(
                        "SELECT theme_id::text, row_revision "
                        "FROM feature.curated_themes "
                        "WHERE theme_slug = :slug AND theme_name = :name "
                        "AND theme_group = :group AND archived_at IS NULL"
                    ),
                    {
                        "slug": row.theme_slug,
                        "name": row.theme_name,
                        "group": row.theme_group,
                    },
                )
            )
            .mappings()
            .one_or_none()
        )
        if theme is None:
            raise ValueError(
                "theme은 retained catalog에서 먼저 생성해야 하며 "
                "slug/name/group이 정확히 일치해야 합니다."
            )
        theme_id = str(theme["theme_id"])
        expectations[("theme", theme_id)] = int(theme["row_revision"])

        source = (
            (
                await session.execute(
                    text(
                        "SELECT source_id::text, row_revision "
                        "FROM feature.curated_sources "
                        "WHERE provider_dataset_id = :dataset_id "
                        "AND source_name = :name "
                        "AND source_url IS NOT DISTINCT FROM :url "
                        "AND archived_at IS NULL"
                    ),
                    {
                        "dataset_id": row.provider_dataset_id,
                        "name": row.source_name,
                        "url": row.source_url,
                    },
                )
            )
            .mappings()
            .one_or_none()
        )
        if source is None:
            raise ValueError(
                "source는 retained catalog에서 먼저 생성해야 하며 "
                "dataset/name/url이 정확히 일치해야 합니다."
            )
        source_id = str(source["source_id"])
        expectations[("source", source_id)] = int(source["row_revision"])

        collection = (
            (
                await session.execute(
                    text(
                        "SELECT collection_id::text, theme_id::text, source_id::text, "
                        "title, edition_key, status, visibility, archived_at, row_revision "
                        "FROM feature.curation_collections "
                        "WHERE collection_key = :collection_key"
                    ),
                    {"collection_key": collection_key},
                )
            )
            .mappings()
            .one_or_none()
        )
        if collection is None:
            expectations[("collection", collection_key)] = None
        else:
            if (
                str(collection["theme_id"]),
                str(collection["source_id"]) if collection["source_id"] else None,
                str(collection["title"]),
                str(collection["edition_key"]),
                str(collection["status"]),
                str(collection["visibility"]),
                collection["archived_at"] is None,
            ) != (
                theme_id,
                source_id,
                row.title,
                row.edition_key,
                "published",
                "public",
                True,
            ):
                raise ValueError(
                    "기존 collection이 preview의 retained catalog 입력과 다릅니다."
                )
            expectations[("collection", collection_key)] = int(
                collection["row_revision"]
            )

    for row in rows:
        item_key = json.dumps(
            [row.collection_key, row.source_item_key, row.source_component_key],
            ensure_ascii=False,
            separators=(",", ":"),
        )
        item_revision = await session.scalar(
            text(
                "SELECT item.row_revision FROM feature.curation_items AS item "
                "JOIN feature.curation_collections AS collection "
                "ON collection.collection_id = item.collection_id "
                "WHERE collection.collection_key = :collection_key "
                "AND item.external_item_id = :item_id "
                "AND item.external_component_id = :component_id"
            ),
            {
                "collection_key": row.collection_key,
                "item_id": row.source_item_key,
                "component_id": row.source_component_key,
            },
        )
        expectations[("item", item_key)] = (
            int(item_revision) if item_revision is not None else None
        )
        if row.feature_id is not None:
            feature_revision = await session.scalar(
                text(
                    "SELECT row_revision FROM feature.features "
                    "WHERE feature_id = :feature_id"
                ),
                {"feature_id": row.feature_id},
            )
            if feature_revision is None:
                raise ValueError("preview 대상 Feature가 더 이상 존재하지 않습니다.")
            expectations[("feature", row.feature_id)] = int(feature_revision)

    return tuple(
        CurationImportRevisionExpectation(
            resource_kind=resource_kind,  # type: ignore[arg-type]
            resource_key=resource_key,
            expected_revision=revision,
        )
        for (resource_kind, resource_key), revision in sorted(expectations.items())
    )


def _stored_import_row_payload(row: ResolvedCurationImportRow) -> dict[str, Any]:
    payload = _canonical_import_row_payload(row)
    payload["provenance"] = row.provenance
    return payload


def _resolved_import_row_from_payload(payload: Mapping[str, Any]) -> ResolvedCurationImportRow:
    return ResolvedCurationImportRow(
        row_number=int(payload["row_number"]),
        collection_key=str(payload["collection_key"]),
        theme_slug=str(payload["theme_slug"]),
        theme_name=str(payload["theme_name"]),
        theme_group=str(payload["theme_group"]),
        title=str(payload["title"]),
        edition_key=str(payload["edition_key"]),
        provider_dataset_id=int(payload["provider_dataset_id"]),
        source_name=str(payload["source_name"]),
        source_url=str(payload["source_url"]) if payload.get("source_url") is not None else None,
        source_item_key=str(payload["source_item_key"]),
        source_component_key=str(payload["source_component_key"]),
        feature_id=str(payload["feature_id"]) if payload.get("feature_id") is not None else None,
        place_name=str(payload["place_name"]),
        address_hint=(
            str(payload["address_hint"])
            if payload.get("address_hint") is not None
            else None
        ),
        sort_order=int(payload["sort_order"]),
        item_title=str(payload["item_title"]) if payload.get("item_title") is not None else None,
        item_summary=(
            str(payload["item_summary"])
            if payload.get("item_summary") is not None
            else None
        ),
        metadata=dict(payload["metadata"]),
        provenance=(dict(payload["provenance"]) if payload.get("provenance") is not None else None),
        manual_feature=(
            dict(payload["manual_feature"])
            if payload.get("manual_feature") is not None
            else None
        ),
        manual_feature_sha256=(
            str(payload["manual_feature_sha256"])
            if payload.get("manual_feature_sha256") is not None
            else None
        ),
    )


async def create_curation_import_plan_command(
    session: AsyncSession,
    *,
    import_plan_id: str,
    content_sha256: str,
    provenance_sha256: str | None,
    plan_sha256: str,
    summary: Mapping[str, Any],
    rows: Sequence[ResolvedCurationImportRow],
    response_rows: Sequence[Mapping[str, Any]],
    revisions: Sequence[CurationImportRevisionExpectation],
    expires_at: datetime,
    command_id: int,
    principal: str,
) -> None:
    """closed preview plan을 command-owned append-only relations에 저장한다."""

    normalized_by_row = {row.row_number: _stored_import_row_payload(row) for row in rows}
    stored_rows = [
        {
            "row_number": int(response_row["row_number"]),
            "normalized_payload": normalized_by_row.get(int(response_row["row_number"])),
            "response_payload": dict(response_row),
        }
        for response_row in response_rows
    ]
    await session.execute(
        text(
            "CALL feature.create_curation_import_plan_command("
            "CAST(:plan_id AS uuid), :content_sha256, :provenance_sha256, "
            ":plan_sha256, CAST(:summary AS jsonb), CAST(:rows AS jsonb), "
            "CAST(:revisions AS jsonb), :expires_at, :command_id, :principal)"
        ),
        {
            "plan_id": import_plan_id,
            "content_sha256": content_sha256,
            "provenance_sha256": provenance_sha256,
            "plan_sha256": plan_sha256,
            "summary": json.dumps(dict(summary), ensure_ascii=False),
            "rows": json.dumps(stored_rows, ensure_ascii=False),
            "revisions": json.dumps(
                [
                    {
                        "resource_kind": revision.resource_kind,
                        "resource_key": revision.resource_key,
                        "expected_revision": revision.expected_revision,
                    }
                    for revision in revisions
                ],
                ensure_ascii=False,
            ),
            "expires_at": expires_at,
            "command_id": command_id,
            "principal": principal,
        },
    )


async def claim_curation_import_plan_command(
    session: AsyncSession,
    *,
    import_plan_id: str,
    plan_sha256: str,
    command_id: int,
    principal: str,
) -> tuple[
    str,
    tuple[ResolvedCurationImportRow, ...],
    dict[str, Any],
    tuple[dict[str, Any], ...],
    datetime,
]:
    """plan ETag/expiry/revision vector를 잠그고 stored normalized rows만 반환한다."""

    result = (
        await session.execute(
            text(
                "CALL feature.claim_curation_import_plan_command("
                "CAST(:plan_id AS uuid), :plan_sha256, :command_id, :principal, "
                "NULL, NULL, NULL, NULL, NULL)"
            ),
            {
                "plan_id": import_plan_id,
                "plan_sha256": plan_sha256,
                "command_id": command_id,
                "principal": principal,
            },
        )
    ).mappings().one()
    payloads = result["o_rows"]
    return (
        str(result["o_content_sha256"]),
        tuple(_resolved_import_row_from_payload(payload) for payload in payloads),
        dict(result["o_summary"]),
        tuple(dict(payload) for payload in result["o_response_rows"]),
        result["o_expires_at"],
    )


async def complete_curation_import_plan_command(
    session: AsyncSession,
    *,
    import_plan_id: str,
    command_id: int,
    import_batch_id: str,
    result_payload: Mapping[str, Any],
    principal: str,
) -> None:
    """import batch와 immutable terminal plan receipt를 같은 transaction에 결박한다."""

    await session.execute(
        text(
            "CALL feature.complete_curation_import_plan_command("
            "CAST(:plan_id AS uuid), :command_id, CAST(:batch_id AS uuid), "
            "CAST(:result AS jsonb), :principal)"
        ),
        {
            "plan_id": import_plan_id,
            "command_id": command_id,
            "batch_id": import_batch_id,
            "result": json.dumps(dict(result_payload), ensure_ascii=False),
            "principal": principal,
        },
    )


async def _resolve_curation_import_collection_command(
    session: AsyncSession,
    *,
    collection_key: str,
    theme_id: str,
    source_id: str | None,
    title: str,
    edition_key: str,
    command_id: int,
    principal: str,
) -> tuple[str, bool]:
    """현재 import command에 collection create/reuse effect를 결박한다."""

    result = (
        await session.execute(
            text(
                """
                CALL feature.resolve_curation_import_collection_command(
                  :collection_key, CAST(:theme_id AS uuid), CAST(:source_id AS uuid),
                  :title, :edition_key, :command_id, :principal,
                  NULL, NULL, NULL
                )
                """
            ),
            {
                "collection_key": collection_key,
                "command_id": command_id,
                "edition_key": edition_key,
                "principal": principal,
                "source_id": source_id,
                "theme_id": theme_id,
                "title": title,
            },
        )
    ).mappings().one()
    return str(result["o_collection_id"]), bool(result["o_created"])


async def _curation_collection_item_state_hash(
    session: AsyncSession,
    *,
    collection_id: str,
) -> str:
    """collection child representation의 deterministic semantic digest."""

    value = (
        await session.execute(
            text(
                """
                SELECT COALESCE(jsonb_agg(jsonb_build_array(
                  item.curation_item_id::text, item.feature_id,
                  item.source_record_key, item.external_item_id,
                  item.external_component_id, item.place_name, item.address_hint,
                  item.source_present, item.status, item.sort_order,
                  item.item_title, item.item_summary, item.curation_relation,
                  item.reuse_policy, item.metadata, item.archived_at,
                  item.row_revision
                ) ORDER BY item.sort_order, item.curation_item_id), '[]'::jsonb)
                FROM feature.curation_items AS item
                WHERE item.collection_id = CAST(:collection_id AS uuid)
                """
            ),
            {"collection_id": collection_id},
        )
    ).scalar_one()
    return _canonical_json_sha256(value)


async def _touch_curation_import_collection_command(
    session: AsyncSession,
    *,
    collection_id: str,
    command_id: int,
    principal: str,
) -> int:
    result = (
        await session.execute(
            text(
                """
                CALL feature.touch_curation_import_collection_command(
                  CAST(:collection_id AS uuid), :command_id, :principal, NULL
                )
                """
            ),
            {
                "collection_id": collection_id,
                "command_id": command_id,
                "principal": principal,
            },
        )
    ).mappings().one()
    return int(result["o_collection_revision"])


def _manual_import_rows(
    rows: Sequence[ResolvedCurationImportRow],
) -> tuple[ResolvedCurationImportRow, ...]:
    """typed manual payload가 실린 행만, 행 번호 순서로."""

    return tuple(
        sorted(
            (row for row in rows if row.manual_feature is not None),
            key=lambda row: row.row_number,
        )
    )


async def _issue_manual_feature_children(
    session: AsyncSession,
    *,
    manual_rows: Sequence[ResolvedCurationImportRow],
    collections: Mapping[str, str],
    actor: str,
    parent: ParentCommandIdentity,
    import_plan_id: str,
    plan_sha256: str,
) -> tuple[ManualImportChild, ...]:
    """manual 행마다 결정적 identity의 child command를 발급하고 writer를 돌린다.

    child 하나가 claim → Feature → origin → subtype → item → accepted decision을
    소유한다(설계 §6.3). 하나라도 실패하면 예외로 전체 batch가 rollback된다(§6.4).
    exact conflict(같은 identity의 manual Feature 존재)도 실패다 — 부분 성공한
    import는 존재하지 않는다.
    """

    issued: list[ManualImportChild] = []
    for row in manual_rows:
        payload = row.manual_feature or {}
        sha = row.manual_feature_sha256
        if not sha:
            raise ValueError(
                f"manual 행 {row.row_number}: typed payload SHA가 없다 — "
                "plan이 §6.1 이전 세대다. 다시 preview할 것."
            )
        # ── 재수렴 판정(H2/F3): 같은 item identity가 이미 있으면 이번 batch는
        # 새 child를 만들 수 없다(writer의 item 선검사가 23505로 죽는다). 이전
        # child linkage가 같은 typed payload를 결박했으면 그 child를 재사용하고,
        # 아니면 원인을 정확히 말하는 오류로 fail-close한다.
        prior = (
            await session.execute(
                text(
                    "SELECT item.curation_item_id, item.feature_id, "
                    "feature_row.feature_uuid, linkage.child_command_id, "
                    "linkage.manual_payload_sha256 "
                    "FROM feature.curation_items AS item "
                    "LEFT JOIN feature.features AS feature_row "
                    "  ON feature_row.feature_id = item.feature_id "
                    "LEFT JOIN ops.curation_import_manual_feature_children AS linkage "
                    "  ON linkage.curation_item_id = item.curation_item_id "
                    "WHERE item.collection_id = CAST(:collection_id AS uuid) "
                    "  AND item.external_item_id = :external_item_id "
                    "  AND item.external_component_id = :external_component_id "
                    "ORDER BY linkage.recorded_at ASC NULLS LAST LIMIT 1"
                ),
                {
                    "collection_id": collections[row.collection_key],
                    "external_item_id": row.source_item_key,
                    "external_component_id": row.source_component_key,
                },
            )
        ).mappings().one_or_none()
        if prior is not None:
            if prior["child_command_id"] is None:
                raise ValueError(
                    f"manual 행 {row.row_number}: 같은 item identity가 manual 생성이 "
                    "아닌 경로로 이미 존재한다 — 이 행을 feature_id 참조로 바꿀 것."
                )
            if prior["manual_payload_sha256"] != sha:
                raise ValueError(
                    f"manual 행 {row.row_number}: 이전 반영과 typed payload가 다르다 "
                    "(좌표/category 변경은 재수렴할 수 없다) — 이 행을 feature_id "
                    "참조로 바꾸고 변경은 admin PATCH로 수행할 것."
                )
            if prior["feature_uuid"] is None or prior["feature_id"] is None:
                raise ValueError(
                    f"manual 행 {row.row_number}: 이전 child의 item이 feature 결박을 "
                    "잃었다 — 계보가 손상됐으므로 수동 확인이 필요하다."
                )
            issued.append(
                ManualImportChild(
                    row_number=row.row_number,
                    child_command_id=int(prior["child_command_id"]),
                    feature_id=str(prior["feature_id"]),
                    feature_uuid=str(prior["feature_uuid"]),
                    curation_item_id=str(prior["curation_item_id"]),
                    reused=True,
                )
            )
            continue
        identity = derive_child_command_identity(
            parent=parent,
            import_plan_id=import_plan_id,
            plan_sha256=plan_sha256,
            plan_row_number=row.row_number,
            manual_payload_sha256=sha,
        )
        await lock_domain_command(
            session,
            actor=actor,
            operation=identity.operation,
            idempotency_key=str(identity.idempotency_key),
        )
        claim = await create_domain_command_claim(
            session,
            actor=actor,
            operation=identity.operation,
            idempotency_key=str(identity.idempotency_key),
            request_fingerprint=identity.request_fingerprint,
        )
        coord = payload.get("coord") or {}
        manual_feature = {
            "kind": payload.get("kind"),
            "category": payload.get("category"),
            # Feature 이름은 place_name이 소유한다(§6.1). preview가 비어 있는
            # place_name을 이미 거절했다.
            "name": row.place_name,
            # canonical SHA는 문자열 자릿수를 보존하지만, writer는 JSON number를
            # 요구한다. float 왕복은 최단 표현으로 같은 십진값을 유지한다.
            "coord": {
                "lon": float(str(coord.get("lon"))),
                "lat": float(str(coord.get("lat"))),
            },
        }
        created = await create_manual_curation_item_with_feature_command(
            session,
            collection_id=collections[row.collection_key],
            manual_feature=manual_feature,
            external_item_id=row.source_item_key,
            external_component_id=row.source_component_key,
            place_name=row.place_name,
            address_hint=row.address_hint,
            sort_order=row.sort_order,
            item_title=row.item_title,
            item_summary=row.item_summary,
            metadata=row.metadata,
            command_id=claim.command_id,
            principal=actor,
        )
        if isinstance(created, CurationManualFeatureExactDuplicate):
            raise ValueError(
                f"manual 행 {row.row_number}: 같은 identity의 manual Feature가 이미 "
                f"있다(feature_uuid={created.existing_feature_uuid}). import는 부분 "
                "성공하지 않는다 — 행을 feature_id 참조로 바꾸거나 좌표를 확인할 것."
            )
        issued.append(
            ManualImportChild(
                row_number=row.row_number,
                child_command_id=claim.command_id,
                feature_id=created.feature_id,
                feature_uuid=created.feature_uuid,
                curation_item_id=created.item.curation_item_id,
            )
        )
    return tuple(issued)


_RECORD_MANUAL_CHILD_SQL: Final = (
    "CALL ops.record_curation_import_manual_feature_child("
    "CAST(:import_plan_id AS uuid), :plan_row_number, :plan_sha256, "
    ":manual_payload_sha256, :child_command_id, CAST(:feature_uuid AS uuid), "
    "CAST(:import_row_id AS uuid), CAST(:curation_item_id AS uuid), "
    "CAST(:link_decision_id AS uuid))"
)


async def _record_manual_children_linkage(
    session: AsyncSession,
    *,
    issued: Sequence[ManualImportChild],
    receipts: Mapping[int, ImportRowReceipt],
    manual_rows: Mapping[int, ResolvedCurationImportRow],
    import_plan_id: str,
    plan_sha256: str,
) -> None:
    """child ↔ import receipt ↔ decision을 `301` linkage 표에 결박하고 child를 닫는다.

    좌표는 이 transaction이 방금 확정해 돌려준 값(o_row_receipts)이다 — DB를 되짚어
    추론하지 않는다. 존재 결박(FK)은 표가, 인자 사이 정합은 recorder가 강제한다.

    **coverage 가드(적대 리뷰 H1)**: 이 batch의 모든 manual 행은 fresh 발급 또는
    재수렴 중 하나여야 한다. 발급 단계가 무력화(no-op)돼도 여기서 fail-close한다 —
    child 없는 `manual_feature_child` decision이 조용히 남는 경로를 막는다.
    """

    covered = {child.row_number for child in issued}
    uncovered = sorted(set(manual_rows) - covered)
    if uncovered:
        raise ValueError(
            f"manual 행 {uncovered}: child 발급도 재수렴도 되지 않았다 — "
            "발급 단계가 건너뛰어졌다. batch를 중단한다."
        )

    for child in issued:
        if child.reused:
            # 재수렴: linkage는 생성 시점의 것 하나뿐이다(UNIQUE(child_command_id)).
            # 이번 import row의 decision은 apply가 이미 accepted/manual_feature_child로
            # 남겼고, receipt 존재만 확인한다.
            reused_receipt = receipts.get(child.row_number)
            if reused_receipt is None:
                raise ValueError(
                    f"manual 행 {child.row_number}: 재수렴인데 apply가 행 좌표를 "
                    "돌려주지 않았다."
                )
            if reused_receipt.curation_item_id != child.curation_item_id:
                raise ValueError(
                    f"manual 행 {child.row_number}: 재수렴 item과 import receipt의 "
                    "item이 다르다."
                )
            continue
        receipt = receipts.get(child.row_number)
        if receipt is None:
            raise ValueError(
                f"manual 행 {child.row_number}: apply가 행 좌표를 돌려주지 않았다 — "
                "linkage를 결박할 수 없다(302 이전 procedure?)"
            )
        if receipt.curation_item_id != child.curation_item_id:
            raise ValueError(
                f"manual 행 {child.row_number}: writer가 만든 item과 import receipt의 "
                "item이 다르다 — 같은 행이 두 item에 걸쳐 있다."
            )
        if receipt.accepted_link_decision_id is None:
            raise ValueError(
                f"manual 행 {child.row_number}: import decision이 accepted가 아니다 — "
                "linkage evidence를 결박할 수 없다."
            )
        row = manual_rows[child.row_number]
        await session.execute(
            text(_RECORD_MANUAL_CHILD_SQL),
            {
                "import_plan_id": import_plan_id,
                "plan_row_number": child.row_number,
                "plan_sha256": plan_sha256,
                "manual_payload_sha256": row.manual_feature_sha256,
                "child_command_id": child.child_command_id,
                "feature_uuid": child.feature_uuid,
                "import_row_id": receipt.import_row_id,
                "curation_item_id": receipt.curation_item_id,
                "link_decision_id": receipt.accepted_link_decision_id,
            },
        )
        # child terminal result — §6.3의 마지막 소유물. 외부 HTTP replay route는
        # 없지만, immutable claim/result 짝은 다른 command와 같은 원장에 남긴다.
        await create_domain_command_record(
            session,
            command_id=child.child_command_id,
            response_status=201,
            response_body={
                "feature_id": child.feature_id,
                "feature_uuid": child.feature_uuid,
                "curation_item_id": child.curation_item_id,
                "import_plan_id": import_plan_id,
                "plan_row_number": child.row_number,
                "plan_sha256": plan_sha256,
            },
            response_headers={},
        )


async def _apply_curation_import_items_command(
    session: AsyncSession,
    *,
    items: Sequence[Mapping[str, Any]],
    actor: str,
    source_content_sha256: str,
    batch_kind: str,
    command_id: int,
) -> CurationImportResult:
    """normalized item/provenance set을 한 named DB command로 반영한다."""

    result = (
        await session.execute(
            text(
                "CALL feature.apply_curation_import_items_command("
                "CAST(:items AS jsonb), :content_sha256, :batch_kind, "
                ":command_id, :principal, NULL, NULL, NULL, NULL, NULL)"
            ),
            {
                "items": json.dumps(list(items), ensure_ascii=False),
                "content_sha256": source_content_sha256,
                "batch_kind": batch_kind,
                "command_id": command_id,
                "principal": actor,
            },
        )
    ).mappings().one()
    removed_ids = [str(value) for value in (result["o_removed_item_ids"] or [])]
    removals: tuple[CurationItem, ...] = ()
    if removed_ids:
        removal_rows = (
            (
                await session.execute(
                    text(
                        _ITEM_SELECT
                        + " WHERE i.curation_item_id = ANY(CAST(:item_ids AS uuid[])) "
                        "ORDER BY c.collection_key, i.sort_order, i.curation_item_id"
                    ),
                    {"item_ids": removed_ids},
                )
            )
            .mappings()
            .all()
        )
        removals = tuple(_item(row) for row in removal_rows)
    raw_receipts = result["o_row_receipts"]
    if isinstance(raw_receipts, str):
        raw_receipts = json.loads(raw_receipts)
    row_receipts = tuple(
        ImportRowReceipt(
            row_number=int(entry["row_number"]),
            import_row_id=str(entry["import_row_id"]),
            curation_item_id=str(entry["curation_item_id"]),
            accepted_link_decision_id=(
                str(entry["accepted_link_decision_id"])
                if entry.get("accepted_link_decision_id") is not None
                else None
            ),
        )
        for entry in (raw_receipts or [])
    )
    return {
        "rows": len(items),
        "collections": len({str(item["collection_id"]) for item in items}),
        "inserted": int(result["o_inserted"] or 0),
        "updated": int(result["o_updated"] or 0),
        "removed": len(removed_ids),
        "removals": removals,
        "import_batch_id": str(result["o_import_batch_id"]),
        # `302`부터 procedure가 행별 immutable 좌표를 직접 돌려준다 — caller는 DB를
        # 되짚어 추론하지 않는다. `301` linkage가 이 셋을 결박한다.
        "row_receipts": row_receipts,
        "manual_children": (),
    }


async def import_curation_rows(
    session: AsyncSession,
    *,
    rows: Sequence[ResolvedCurationImportRow],
    actor: str | None = None,
    source_content_sha256: str | None = None,
    batch_kind: str | None = None,
    frozen_h35_schema: bool = False,
    command_id: int | None = None,
    parent_identity: ParentCommandIdentity | None = None,
    import_plan_id: str | None = None,
    plan_sha256: str | None = None,
) -> CurationImportResult:
    """검증·Feature 해소가 끝난 CSV 행을 한 transaction에서 멱등 upsert한다.

    ``frozen_h35_schema``: h35 cutover CLI 전용 — 0063~0079 고정 세대에서
    removal projection의 ``feature_uuid``를 NULL로 채우고, public 판정을
    typed ``feature_notices`` 대신 당시의 detail 문자열 술어로 되돌리며,
    curated source를 surrogate가 아닌 ``(provider, dataset_key)`` 자연키로
    upsert한다(그 세대엔 ``provider_sync.provider_datasets``가 없다).
    """
    _ensure_resolved_curation_identities(rows)
    _ensure_curation_dataset_identity(rows, frozen_h35_schema=frozen_h35_schema)
    manual_rows = _manual_import_rows(rows)
    if manual_rows and (command_id is None or frozen_h35_schema):
        # manual Feature 생성은 child command·writer·linkage가 한 transaction에서
        # 함께 확정돼야 한다(설계 §6). command 없는 경로로 보내면 item이 feature
        # 없이 만들어져 계보가 조용히 끊긴다.
        raise ValueError("manual Feature 행은 command 경로에서만 반영할 수 있습니다.")
    collections: dict[str, str] = {}
    created_collections: set[str] = set()
    before_item_hashes: dict[str, str] = {}
    item_values: list[dict[str, Any]] = []
    if rows:
        # 서로 다른 CSV가 theme/source/collection lock을 역순으로 잡는 deadlock과
        # 같은 collection의 authoritative replace 경합을 하나의 write 경계로 직렬화한다.
        await _lock_curation_write_boundary(session)
        collection_keys = sorted({row.collection_key for row in rows})
        await _lock_collection_keys(session, collection_keys)
        feature_ids = sorted({str(row.feature_id) for row in rows if row.feature_id is not None})
        if feature_ids:
            # import row가 참조할 수 있는 feature 집합도 add 가드와 같은 legacy 술어를
            # 따른다 — 감춰진 것만 배제하고 draft·quarantined는 그대로 후보다. h35
            # replay는 3축이 아직 없는 세대에서 이 경로를 그대로 도므로 matcher와 같은
            # 세대별 표기를 쓴다(둘이 갈리면 matcher가 고른 행을 이 가드가 되돌려
            # import 전체가 죽는다).
            active_state_sql = _active_feature_state_sql(
                "f", frozen_h35_schema=frozen_h35_schema
            )
            active_feature_ids = set(
                (
                    await session.execute(
                        text(
                            "SELECT feature_id FROM feature.features AS f "
                            "WHERE f.feature_id = ANY(CAST(:feature_ids AS text[])) "
                            f"AND {active_state_sql} "
                            "ORDER BY f.feature_id FOR UPDATE"
                        ),
                        {"feature_ids": feature_ids},
                    )
                )
                .scalars()
                .all()
            )
            if active_feature_ids != set(feature_ids):
                raise ValueError(
                    "큐레이션 반영 중 Feature lifecycle이 변경되었습니다. 다시 preview하세요."
                )
        if command_id is None or frozen_h35_schema:
            await session.execute(
                text(
                    "SELECT collection_id FROM feature.curation_collections "
                    "WHERE collection_key = ANY(CAST(:collection_keys AS text[])) "
                    "ORDER BY collection_id FOR UPDATE"
                ),
                {"collection_keys": collection_keys},
            )
        legacy_adoption_payload = json.dumps(
            [
                {
                    "collection_key": row.collection_key,
                    "feature_id": row.feature_id,
                    "external_item_id": row.source_item_key,
                    "external_component_id": row.source_component_key,
                }
                for row in rows
            ],
            ensure_ascii=False,
        )
        await _ensure_unambiguous_legacy_import_adoptions(
            session,
            payload=legacy_adoption_payload,
        )

    representatives: dict[str, ResolvedCurationImportRow] = {}
    for row in rows:
        representatives.setdefault(row.collection_key, row)
    for collection_key in sorted(representatives):
        row = representatives[collection_key]
        if frozen_h35_schema:
            theme_id = await upsert_curation_theme(
                session,
                theme_slug=row.theme_slug,
                theme_name=row.theme_name,
                theme_group=row.theme_group,
            )
        else:
            theme_value = (
                await session.execute(
                    text(_RESOLVE_THEME_SQL),
                    {
                        "theme_group": row.theme_group,
                        "theme_name": row.theme_name,
                        "theme_slug": row.theme_slug,
                    },
                )
            ).scalar_one_or_none()
            if theme_value is None:
                raise ValueError(
                    "theme은 retained catalog에서 먼저 생성해야 하며 "
                    "slug/name/group이 정확히 일치해야 합니다."
                )
            theme_id = str(theme_value)
        source_params: dict[str, Any] = {
            "source_name": row.source_name,
            "source_url": row.source_url,
        }
        if row.frozen_h35_dataset is not None:
            source_params["provider"] = row.frozen_h35_dataset[0]
            source_params["dataset_key"] = row.frozen_h35_dataset[1]
        else:
            source_params["provider_dataset_id"] = row.provider_dataset_id
        if frozen_h35_schema:
            source_id = await _upsert_id_with_fallback(
                session,
                upsert_sql=_FROZEN_H35_UPSERT_SOURCE_SQL,
                lookup_sql=_FROZEN_H35_GET_SOURCE_ID_BY_KEY_SQL,
                params=source_params,
                entity="curation source",
            )
        else:
            source_value = (
                await session.execute(text(_RESOLVE_SOURCE_SQL), source_params)
            ).scalar_one_or_none()
            if source_value is None:
                raise ValueError(
                    "source는 retained catalog에서 먼저 생성해야 하며 "
                    "dataset/name/url이 정확히 일치해야 합니다."
                )
            source_id = str(source_value)
        collection_params = {
            "collection_key": collection_key,
            "theme_id": theme_id,
            "source_id": source_id,
            "title": row.title,
            "edition_key": row.edition_key,
            "actor": actor,
        }
        if command_id is not None and not frozen_h35_schema:
            principal = (actor or "").strip()
            if not principal:
                raise ValueError("curation import command actor is required")
            collection_id, created = await _resolve_curation_import_collection_command(
                session,
                collection_key=collection_key,
                theme_id=theme_id,
                source_id=source_id,
                title=row.title,
                edition_key=row.edition_key,
                command_id=command_id,
                principal=principal,
            )
            collections[collection_key] = collection_id
            if created:
                created_collections.add(collection_id)
            else:
                before_item_hashes[collection_id] = (
                    await _curation_collection_item_state_hash(
                        session,
                        collection_id=collection_id,
                    )
                )
        else:
            collections[collection_key] = await _upsert_id_with_fallback(
                session,
                upsert_sql=_UPSERT_COLLECTION_SQL,
                lookup_sql=_GET_COLLECTION_ID_BY_KEY_SQL,
                params=collection_params,
                entity="curation collection",
            )
    for row in rows:
        item_values.append(
            {
                "row_number": row.row_number,
                "collection_id": collections[row.collection_key],
                "collection_key": row.collection_key,
                "feature_id": row.feature_id,
                "external_item_id": row.source_item_key,
                "external_component_id": row.source_component_key,
                "place_name": row.place_name,
                "address_hint": row.address_hint,
                "sort_order": row.sort_order,
                "item_title": row.item_title,
                "item_summary": row.item_summary,
                "metadata": row.metadata,
                "provenance": row.provenance or {},
                "row_payload": _canonical_import_row_payload(row),
            }
        )
    if command_id is not None and not frozen_h35_schema:
        principal = (actor or "").strip()
        if not principal:
            raise ValueError("curation import command actor is required")
        content_sha256 = (
            _validated_sha256(source_content_sha256)
            if source_content_sha256 is not None
            else _canonical_json_sha256(
                [_canonical_import_row_payload(row) for row in rows]
            )
        )
        issued: tuple[ManualImportChild, ...] = ()
        if manual_rows:
            if parent_identity is None or import_plan_id is None or plan_sha256 is None:
                raise ValueError(
                    "manual 행은 부모 command identity와 plan 결박(import_plan_id·"
                    "plan_sha256)이 있어야 child를 발급할 수 있습니다 — plan commit "
                    "경로로만 import할 것."
                )
            # child writer가 item을 먼저 만들어야 apply의 provenance가 그 item을
            # 관측한다. apply는 manual 행의 item upsert를 건너뛴다(302).
            issued = await _issue_manual_feature_children(
                session,
                manual_rows=manual_rows,
                collections=collections,
                actor=principal,
                parent=parent_identity,
                import_plan_id=import_plan_id,
                plan_sha256=plan_sha256,
            )
        result = await _apply_curation_import_items_command(
            session,
            items=item_values,
            actor=principal,
            source_content_sha256=content_sha256,
            batch_kind=batch_kind or "normalized_rows",
            command_id=command_id,
        )
        if manual_rows:
            assert import_plan_id is not None
            assert plan_sha256 is not None
            await _record_manual_children_linkage(
                session,
                issued=issued,
                receipts={
                    receipt.row_number: receipt
                    for receipt in result["row_receipts"]
                },
                manual_rows={row.row_number: row for row in manual_rows},
                import_plan_id=import_plan_id,
                plan_sha256=plan_sha256,
            )
            # 적대 리뷰 H4: apply는 manual 행의 item upsert를 건너뛰므로 fresh
            # 생성이 `updated`(provenance_only)로 계상된다. writer가 이 transaction
            # 에서 만든 item은 의미상 insert다 — preview 집계와도 이 보정이 맞다.
            fresh = sum(1 for child in issued if not child.reused)
            result["inserted"] += fresh
            result["updated"] = max(0, result["updated"] - fresh)
        result["manual_children"] = issued
        return result
    counts = {"inserted": 0, "updated": 0, "removed": 0}
    removals: tuple[CurationItem, ...] = ()
    if item_values:
        collection_ids = sorted(collections.values())
        if command_id is None or frozen_h35_schema:
            await session.execute(
                text(
                    "SELECT collection_id FROM feature.curation_collections "
                    "WHERE collection_id = ANY(CAST(:collection_ids AS uuid[])) "
                    "ORDER BY collection_id FOR UPDATE"
                ),
                {"collection_ids": collection_ids},
            )
        items_payload = json.dumps(item_values, ensure_ascii=False)
        removed_rows = (
            (
                await session.execute(
                    text(
                        _MARK_IMPORT_REMOVALS_PRE_UUID_NO_REVISION_SQL
                        if frozen_h35_schema
                        else _MARK_IMPORT_REMOVALS_SQL
                    ),
                    {"items": items_payload, "actor": actor},
                )
            )
            .mappings()
            .all()
        )
        removals = tuple(_item(row) for row in removed_rows)
        adopted = int(
            (
                await session.execute(
                text(
                    _ADOPT_LEGACY_IMPORT_IDENTITIES_PRE_REVISION_SQL
                    if frozen_h35_schema
                    else _ADOPT_LEGACY_IMPORT_IDENTITIES_SQL
                ),
                    {"items": items_payload, "actor": actor},
                )
            ).scalar_one()
        )
        count_row = (
            (
                await session.execute(
                text(
                    _BULK_UPSERT_ITEMS_PRE_REVISION_SQL
                    if frozen_h35_schema
                    else _BULK_UPSERT_ITEMS_SQL
                ),
                    {
                        "items": items_payload,
                        "actor": actor,
                    },
                )
            )
            .mappings()
            .one()
        )
        counts = {
            "inserted": int(count_row["inserted"] or 0),
            "updated": adopted + int(count_row["updated"] or 0),
            "removed": len(removals),
        }
        if any(counts.values()) and command_id is not None and not frozen_h35_schema:
            principal = (actor or "").strip()
            for collection_id in collection_ids:
                if collection_id in created_collections:
                    continue
                before_hash = before_item_hashes[collection_id]
                after_hash = await _curation_collection_item_state_hash(
                    session,
                    collection_id=collection_id,
                )
                if after_hash != before_hash:
                    await _touch_curation_import_collection_command(
                        session,
                        collection_id=collection_id,
                        command_id=command_id,
                        principal=principal,
                    )
        elif any(counts.values()):
            await session.execute(
                text(
                    "UPDATE feature.curation_collections "
                    "SET updated_by = :actor, updated_at = now() "
                    "WHERE collection_id = ANY(CAST(:collection_ids AS uuid[]))"
                ),
                {"collection_ids": collection_ids, "actor": actor},
            )
    import_batch_id, row_receipts = await _record_import_provenance(
        session,
        rows=rows,
        actor=actor,
        source_content_sha256=source_content_sha256,
        batch_kind=batch_kind,
        command_id=command_id,
    )
    return {
        "rows": len(rows),
        "collections": len(collections),
        "inserted": counts["inserted"],
        "updated": counts["updated"],
        "removed": counts["removed"],
        "removals": removals,
        "import_batch_id": import_batch_id,
        "row_receipts": row_receipts,
        "manual_children": (),
    }
