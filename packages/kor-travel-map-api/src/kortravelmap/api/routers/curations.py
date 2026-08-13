"""큐레이션 collection/item REST API."""

from __future__ import annotations

import csv
import hashlib
import io
import json
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from time import perf_counter
from typing import Annotated, Any, Literal
from uuid import UUID, uuid4

from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    Query,
    Request,
    UploadFile,
)
from fastapi.responses import Response
from kortravelmap.curation_import import (
    CURATION_CSV_HEADERS,
    CURATION_CSV_MAX_BYTES,
    CURATION_INTEGER_MAX,
    CurationImportIssue,
    CurationImportRow,
    parse_curation_csv,
)
from kortravelmap.curation_provenance import (
    CURATION_PROVENANCE_MAX_BYTES,
    CurationProvenanceError,
    parse_curation_provenance,
    provenance_row_payload,
    requires_lighthouse_provenance,
)
from kortravelmap.infra import curation_candidate_repo, curation_repo, feature_identity
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from kortravelmap.api import domain_command_service
from kortravelmap.api.auth import AdminProxyContext, require_admin_frontend
from kortravelmap.api.db import get_session
from kortravelmap.api.domain_command_service import (
    domain_command_transaction,
    idempotent_domain_command,
)
from kortravelmap.api.feature_ref import resolve_feature_ref_or_error
from kortravelmap.api.http_revision import parse_revision_header, revision_etag
from kortravelmap.api.identity_projection import response_feature_id
from kortravelmap.api.response import Meta, make_meta

__all__ = ["admin_router", "candidate_router", "router"]

router = APIRouter(prefix="/curations", tags=["curations"])
admin_router = APIRouter(prefix="/admin/curations", tags=["admin-curations"])
candidate_router = APIRouter(
    prefix="/admin/theme-feature-candidates",
    tags=["admin-curation-candidates"],
)

CollectionStatus = Literal["draft", "published", "archived"]
ActiveCollectionStatus = Literal["draft", "published"]
CollectionVisibility = Literal["admin_only", "public"]
ItemStatus = Literal["candidate", "included", "rejected", "archived"]
ActiveItemStatus = Literal["candidate", "included", "rejected"]
CurationRelation = Literal[
    "primary_stop",
    "food_stop",
    "cafe_stop",
    "bookstore_stop",
    "nearby_option",
    "accessibility_support",
    "pet_support",
    "family_support",
    "theme_area_anchor",
]
ReusePolicy = Literal["allowed", "blocked", "manual_review"]
CandidateReviewState = Literal["open", "promoted", "rejected"]
_ETAG_RESPONSE_HEADER = {
    "ETag": {
        "description": "현재 응답 representation의 strong entity tag.",
        "schema": {"type": "string"},
    }
}
_IF_MATCH_OPENAPI_PARAMETER = {
    "name": "If-Match",
    "in": "header",
    "required": True,
    "schema": {"type": "string"},
    "description": "직전 command ETag. 누락은 428, stale 값은 412.",
}
_IMPORT_PLAN_IF_MATCH_OPENAPI_PARAMETER = {
    "name": "If-Match",
    "in": "header",
    "required": True,
    "schema": {"type": "string", "pattern": '^"sha256:[0-9a-f]{64}"$'},
    "description": "preview 응답의 immutable import plan strong ETag.",
}


class AdminThemeCandidateView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidate_id: UUID
    rule_id: UUID
    theme_id: UUID
    theme_slug: str
    theme_name: str
    source_id: UUID
    source_name: str
    provider_dataset_id: int
    source_entity_key: str
    feature_id: str
    feature_uuid: UUID
    feature_name: str
    feature_kind: str
    feature_category: str
    feature_detail: dict[str, Any]
    lifecycle_state: str
    publication_state: str
    quality_state: str
    source_record_key: str
    source_record_hash: str
    rule_row_revision: str
    rule_input_hash: str
    candidate_input_hash: str
    review_state: CandidateReviewState
    eligibility_present: bool
    disposition: str
    rank_score: str
    proposal_title: str | None
    proposal_summary: str | None
    match_evidence: dict[str, Any]
    candidate_revision: str
    candidate_etag: str
    feature_row_revision: str
    representation_etag: str
    created_at: datetime
    updated_at: datetime


class AdminThemeCandidatePageData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[AdminThemeCandidateView]


class AdminThemeCandidatePageResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    data: AdminThemeCandidatePageData
    meta: Meta


class AdminThemeCandidateResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    data: AdminThemeCandidateView
    meta: Meta


class AdminThemeCandidateTransitionView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    transition_id: str
    candidate_id: UUID
    transition_kind: str
    from_review_state: str | None
    to_review_state: str
    from_eligibility_present: bool | None
    to_eligibility_present: bool
    candidate_revision: str
    generation_id: UUID | None
    command_id: str | None
    actor: str
    reason_code: str
    causation_ref: dict[str, Any]
    occurred_at: datetime


class AdminThemeCandidateTransitionPageData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[AdminThemeCandidateTransitionView]


class AdminThemeCandidateTransitionPageResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    data: AdminThemeCandidateTransitionPageData
    meta: Meta


class ThemeCandidateRejectRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason_code: str = Field(min_length=1, max_length=128)


class ThemeCandidatePromoteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    collection_id: UUID
    collection_revision: str = Field(pattern=r"^[1-9][0-9]*$")
    item_revision: str | None = Field(default=None, pattern=r"^[1-9][0-9]*$")
    external_item_id: str = Field(min_length=1, max_length=512)
    external_component_id: str = Field(min_length=1, max_length=512)
    place_name: str = Field(min_length=1, max_length=512)
    address_hint: str | None = None
    item_title: str | None = None
    item_summary: str | None = None
    sort_order: int = Field(ge=0)
    curation_relation: CurationRelation
    reuse_policy: ReusePolicy
    item_status: Literal["candidate", "included"]
    reason_code: str = Field(min_length=1, max_length=128)


class ThemeCandidateCommandData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidate_id: UUID
    candidate_revision: str
    transition_id: str
    curation_item_id: UUID | None = None
    curation_item_revision: str | None = None


class ThemeCandidateCommandResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    data: ThemeCandidateCommandData
    meta: Meta


class PublicCurationCollectionView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    collection_id: UUID
    collection_key: str
    theme_id: UUID
    theme_slug: str
    theme_name: str
    theme_group: str
    source_id: UUID | None
    provider_dataset_id: int | None
    provider: str | None
    dataset_key: str | None
    source_name: str | None
    source_url: str | None
    title: str
    edition_key: str
    description: str | None
    status: CollectionStatus
    visibility: CollectionVisibility
    item_count: int
    created_at: datetime
    updated_at: datetime
    archived_at: datetime | None


class AdminCurationCollectionView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    collection_id: UUID
    collection_key: str
    theme_id: UUID
    theme_slug: str
    theme_name: str
    theme_group: str
    source_id: UUID | None
    provider_dataset_id: int | None
    provider: str | None
    dataset_key: str | None
    source_name: str | None
    source_url: str | None
    title: str
    edition_key: str
    description: str | None
    status: CollectionStatus
    visibility: CollectionVisibility
    metadata: dict[str, Any]
    item_count: int
    public_item_count: int
    row_revision: str = Field(pattern=r"^[1-9][0-9]*$")
    command_etag: str
    created_at: datetime
    updated_at: datetime
    archived_at: datetime | None
    created_by: str | None
    updated_by: str | None


class PublicCurationItemView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    curation_item_id: UUID
    collection_id: UUID
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
    external_item_id: str
    external_component_id: str
    place_name: str
    address_hint: str | None
    status: ItemStatus
    sort_order: int
    item_title: str | None
    item_summary: str | None
    curation_relation: CurationRelation
    reuse_policy: ReusePolicy
    created_at: datetime
    updated_at: datetime
    archived_at: datetime | None


class AdminCurationItemView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    curation_item_id: UUID
    collection_id: UUID
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
    status: ItemStatus
    sort_order: int
    item_title: str | None
    item_summary: str | None
    curation_relation: CurationRelation
    reuse_policy: ReusePolicy
    metadata: dict[str, Any]
    current_import_row_id: UUID | None
    accepted_link_decision_id: UUID | None
    link_match_basis: str | None
    link_resolver_version: str | None
    link_evidence: dict[str, Any]
    link_actor: str | None
    link_decided_at: datetime | None
    row_revision: str = Field(pattern=r"^[1-9][0-9]*$")
    command_etag: str
    created_at: datetime
    updated_at: datetime
    archived_at: datetime | None
    created_by: str | None
    updated_by: str | None


class CurationFeatureView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    feature_id: str
    name: str
    kind: str
    category: str
    lon: float | None
    lat: float | None
    address: dict[str, Any]


class FeatureCurationGroupView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    feature: CurationFeatureView
    curations: list[PublicCurationItemView]
    curation_count: int


class CurationCollectionsData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[PublicCurationCollectionView]


class AdminCurationCollectionsData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[AdminCurationCollectionView]


class CurationCollectionData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    collection: PublicCurationCollectionView
    items: list[PublicCurationItemView]


class AdminCurationCollectionData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    collection: AdminCurationCollectionView
    items: list[AdminCurationItemView]


class FeatureCurationGroupsData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[FeatureCurationGroupView]


class CurationCollectionsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    data: CurationCollectionsData
    meta: Meta


class AdminCurationCollectionsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    data: AdminCurationCollectionsData
    meta: Meta


class CurationCollectionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    data: CurationCollectionData
    meta: Meta


class AdminCurationCollectionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    data: AdminCurationCollectionData
    meta: Meta


class FeatureCurationGroupsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    data: FeatureCurationGroupsData
    meta: Meta


class FeatureCurationGroupResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    data: FeatureCurationGroupView
    meta: Meta


class CurationItemResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    data: PublicCurationItemView
    meta: Meta


class AdminCurationItemResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    data: AdminCurationItemView
    meta: Meta


class CurationCollectionCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    collection_key: str = Field(min_length=1, max_length=240)
    theme_id: UUID
    source_id: UUID | None = None
    title: str = Field(min_length=1, max_length=300)
    edition_key: str = Field(default="", max_length=100)
    description: str | None = None
    status: ActiveCollectionStatus = "draft"
    visibility: CollectionVisibility = "admin_only"
    metadata: dict[str, Any] = Field(default_factory=dict)

class CurationCollectionPatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # ``None`` default는 필드 생략 sentinel로만 쓰며 명시적 JSON null은 거절한다.
    theme_id: UUID = None  # type: ignore[assignment]
    source_id: UUID | None = None
    title: str = Field(default=None, min_length=1, max_length=300)  # type: ignore[assignment]
    edition_key: str = Field(default=None, max_length=100)  # type: ignore[assignment]
    description: str | None = None
    status: ActiveCollectionStatus = None  # type: ignore[assignment]
    visibility: CollectionVisibility = None  # type: ignore[assignment]
    metadata: dict[str, Any] = None  # type: ignore[assignment]


class CurationItemCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    feature_id: str | None = Field(default=None, min_length=1)
    external_item_id: str = Field(min_length=1, max_length=300)
    external_component_id: str = Field(
        default="primary", min_length=1, max_length=300
    )
    place_name: str | None = Field(default=None, min_length=1, max_length=500)
    address_hint: str | None = Field(default=None, max_length=1000)
    source_record_key: str | None = None
    status: ActiveItemStatus = "included"
    sort_order: int = Field(default=0, ge=0, le=CURATION_INTEGER_MAX)
    item_title: str | None = None
    item_summary: str | None = None
    curation_relation: CurationRelation = "nearby_option"
    reuse_policy: ReusePolicy = "manual_review"
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _feature_or_place_name(self) -> CurationItemCreateRequest:
        if self.feature_id or self.place_name:
            return self
        raise ValueError("feature_id 또는 place_name이 필요합니다.")


class CurationItemPatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    feature_id: str | None = Field(default=None, min_length=1)
    external_item_id: str = Field(default=None, min_length=1, max_length=300)  # type: ignore[assignment]
    external_component_id: str = Field(  # type: ignore[assignment]
        default=None, min_length=1, max_length=300
    )
    place_name: str = Field(default=None, min_length=1, max_length=500)  # type: ignore[assignment]
    address_hint: str | None = Field(default=None, max_length=1000)
    source_record_key: str | None = None
    status: ActiveItemStatus = None  # type: ignore[assignment]
    sort_order: int = Field(  # type: ignore[assignment]
        default=None, ge=0, le=CURATION_INTEGER_MAX
    )
    item_title: str | None = None
    item_summary: str | None = None
    curation_relation: CurationRelation = None  # type: ignore[assignment]
    reuse_policy: ReusePolicy = None  # type: ignore[assignment]
    metadata: dict[str, Any] = None  # type: ignore[assignment]


ImportRowStatus = Literal[
    "valid",
    "invalid",
    "unmatched",
    "review_required",
    "ambiguous",
    "imported",
]


class CurationImportIssueView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    message: str
    row_number: int | None = None
    column: str | None = None


class CurationImportFeatureCandidateView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    feature_id: str
    name: str
    address: dict[str, Any]
    lon: float | None
    lat: float | None


class CurationImportRowView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    row_number: int
    status: ImportRowStatus
    collection_key: str
    theme_slug: str
    title: str
    edition_key: str
    place_name: str
    address_hint: str
    requested_feature_id: str
    resolved_feature_id: str | None
    source_item_key: str
    source_component_key: str
    candidates: list[CurationImportFeatureCandidateView]
    issues: list[CurationImportIssueView]


class CurationImportData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dry_run: bool
    import_plan_id: UUID
    plan_etag: str
    expires_at: datetime
    rows_total: int
    valid_rows: int
    invalid_rows: int
    unresolved_rows: int
    inserted: int
    updated: int
    removed: int
    collections: int
    import_batch_id: UUID | None
    removals: list[AdminCurationItemView]
    items: list[CurationImportRowView]
    issues: list[CurationImportIssueView]


class CurationImportResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    data: CurationImportData
    meta: Meta


class CurationLinkAuditView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    curation_item_id: UUID
    collection_key: str
    external_item_id: str
    external_component_id: str
    feature_id: str
    place_name: str
    address_hint: str | None
    match_basis: str | None
    resolver_version: str | None
    decided_at: datetime | None


class CurationLinkAuditData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[CurationLinkAuditView]
    count: int
    has_more: bool
    next_cursor: str | None


class CurationLinkAuditResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    data: CurationLinkAuditData
    meta: Meta


class CurationImportRowReceiptView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    import_row_id: UUID
    import_batch_id: UUID
    curation_item_id: UUID
    row_number: int
    source_row_sha256: str
    row_payload: dict[str, Any]
    provenance: dict[str, Any]
    imported_at: datetime


class CurationImportBatchView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    import_batch_id: UUID
    content_sha256: str
    batch_kind: str
    row_count: int
    actor: str
    metadata: dict[str, Any]
    imported_at: datetime
    rows: list[CurationImportRowReceiptView]


class CurationImportBatchResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    data: CurationImportBatchView
    meta: Meta


class CurationImportRowReceiptResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    data: CurationImportRowReceiptView
    meta: Meta


QuarantineConflictKind = Literal[
    "movable",
    "component_identity_conflict",
    "active_source_feature_conflict",
    "no_target",
    "target_missing",
]
QuarantineReclassifyAction = Literal["move", "confirm_standalone"]


class CurationQuarantineThemeView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    theme_id: UUID
    theme_slug: str
    theme_name: str
    theme_group: str
    visibility: CollectionVisibility


class CurationQuarantineSourceView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_id: UUID
    provider_dataset_id: int | None
    provider: str | None
    dataset_key: str | None
    source_name: str | None


class CurationQuarantineOriginalCollectionView(BaseModel):
    """`0065` marker가 기록한 원본 collection의 현재 상태 (병렬 표시 전용)."""

    model_config = ConfigDict(extra="forbid")

    collection_id: UUID
    row_revision: str | None = Field(default=None, pattern=r"^[1-9][0-9]*$")
    command_etag: str | None = None
    title: str | None
    status: CollectionStatus | None
    visibility: CollectionVisibility | None
    exists: bool
    theme: CurationQuarantineThemeView | None
    source: CurationQuarantineSourceView | None


class AdminCurationQuarantineCollectionView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    collection_id: UUID
    row_revision: str = Field(pattern=r"^[1-9][0-9]*$")
    command_etag: str
    collection_key: str
    title: str
    edition_key: str
    status: CollectionStatus
    visibility: CollectionVisibility
    created_by: str | None
    item_count: int
    marker_intact: bool
    quarantine_theme: CurationQuarantineThemeView | None
    quarantine_source: CurationQuarantineSourceView | None
    original_collection: CurationQuarantineOriginalCollectionView | None


class AdminCurationQuarantineItemView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    curation_item_id: UUID
    external_item_id: str
    external_component_id: str
    feature_id: str | None
    place_name: str
    status: ItemStatus
    source_present: bool
    archived_at: datetime | None
    conflict_kind: QuarantineConflictKind
    conflict_item_id: UUID | None


class AdminCurationQuarantineCollectionsData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[AdminCurationQuarantineCollectionView]


class AdminCurationQuarantineCollectionsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    data: AdminCurationQuarantineCollectionsData
    meta: Meta


class AdminCurationQuarantineItemsData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_collection_id: UUID | None
    target_collection_revision: str | None = Field(
        default=None, pattern=r"^[1-9][0-9]*$"
    )
    target_command_etag: str | None = None
    target_missing: bool
    target_archived: bool
    items: list[AdminCurationQuarantineItemView]


class AdminCurationQuarantineItemsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    data: AdminCurationQuarantineItemsData
    meta: Meta


class AdminCurationQuarantineReclassifyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: QuarantineReclassifyAction
    # move 전용 — null target은 원본 collection, null item_ids는 전체.
    target_collection_id: UUID | None = None
    target_collection_revision: str | None = Field(
        default=None, pattern=r"^[1-9][0-9]*$"
    )
    item_ids: list[UUID] | None = Field(default=None, min_length=1)
    # confirm_standalone 전용.
    collection_key: str | None = Field(default=None, min_length=1, max_length=240)
    title: str | None = Field(default=None, min_length=1, max_length=300)

    @model_validator(mode="after")
    def _fields_match_action(self) -> AdminCurationQuarantineReclassifyRequest:
        if self.action == "move":
            if self.collection_key is not None or self.title is not None:
                raise ValueError("move에는 collection_key/title을 쓸 수 없습니다.")
            if self.target_collection_revision is None:
                raise ValueError("move에는 target_collection_revision이 필요합니다.")
            return self
        if (
            self.target_collection_id is not None
            or self.target_collection_revision is not None
            or self.item_ids is not None
        ):
            raise ValueError(
                "confirm_standalone에는 target_collection_id/item_ids를 쓸 수 없습니다."
            )
        if self.collection_key is None or self.title is None:
            raise ValueError("confirm_standalone에는 collection_key와 title이 필요합니다.")
        return self


class AdminCurationQuarantineReclassifyData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: QuarantineReclassifyAction
    # move 결과.
    moved_item_ids: list[UUID] | None = None
    quarantine_collection_deleted: bool | None = None
    # confirm_standalone 결과.
    collection_id: UUID | None = None
    collection_key: str | None = None


class AdminCurationQuarantineReclassifyResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    data: AdminCurationQuarantineReclassifyData
    meta: Meta


def _public_collection_view(
    row: curation_repo.CurationCollection,
) -> PublicCurationCollectionView:
    view = PublicCurationCollectionView.model_validate(row, from_attributes=True)
    return view.model_copy(update={"item_count": row.public_item_count})


def _admin_collection_view(
    row: curation_repo.CurationCollection,
) -> AdminCurationCollectionView:
    payload = dict(row.__dict__)
    payload["row_revision"] = str(row.row_revision)
    payload["command_etag"] = revision_etag(row.row_revision)
    return AdminCurationCollectionView.model_validate(payload)


def curation_item_response_feature_id(row: curation_repo.CurationItem) -> str | None:
    """curation item의 응답 feature 참조 — UUID 정본, 미연결이면 None (T-VN-32C PR-2).

    feature_id가 있는데 feature_uuid가 없으면 projection 결함이므로 fail-close.
    내부 join·dict lookup 키는 치환 전 legacy ``row.feature_id``를 그대로 쓴다.
    """
    if row.feature_id is None:
        return None
    if not row.feature_uuid:
        raise ValueError(
            "curation item row에 feature_uuid가 없습니다 — projection 누락 (T-VN-32C)"
        )
    return row.feature_uuid


def _public_item_view(row: curation_repo.CurationItem) -> PublicCurationItemView:
    view = PublicCurationItemView.model_validate(row, from_attributes=True)
    return view.model_copy(update={"feature_id": curation_item_response_feature_id(row)})


def _admin_item_view(row: curation_repo.CurationItem) -> AdminCurationItemView:
    payload = dict(row.__dict__)
    payload.pop("feature_uuid", None)
    payload["row_revision"] = str(row.row_revision)
    payload["command_etag"] = revision_etag(row.row_revision)
    view = AdminCurationItemView.model_validate(payload)
    return view.model_copy(update={"feature_id": curation_item_response_feature_id(row)})


def _curation_representation_etag(value: BaseModel) -> str:
    payload = json.dumps(
        value.model_dump(mode="json"),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return f'"sha256:{hashlib.sha256(payload).hexdigest()}"'


def _import_row_receipt_view(
    row: curation_repo.CurationImportRowReceipt,
) -> CurationImportRowReceiptView:
    return CurationImportRowReceiptView.model_validate(row, from_attributes=True)


def _quarantine_theme_view(
    ref: curation_repo.CurationQuarantineThemeRef | None,
) -> CurationQuarantineThemeView | None:
    if ref is None:
        return None
    return CurationQuarantineThemeView.model_validate(ref, from_attributes=True)


def _quarantine_source_view(
    ref: curation_repo.CurationQuarantineSourceRef | None,
) -> CurationQuarantineSourceView | None:
    if ref is None:
        return None
    return CurationQuarantineSourceView.model_validate(ref, from_attributes=True)


def _quarantine_collection_view(
    row: curation_repo.CurationQuarantineCollection,
) -> AdminCurationQuarantineCollectionView:
    original = row.original_collection
    original_view = (
        CurationQuarantineOriginalCollectionView.model_validate(
            {
                "collection_id": original.collection_id,
                "row_revision": (
                    str(original.row_revision)
                    if original.row_revision is not None
                    else None
                ),
                "command_etag": (
                    revision_etag(original.row_revision)
                    if original.row_revision is not None
                    else None
                ),
                "title": original.title,
                "status": original.status,
                "visibility": original.visibility,
                "exists": original.exists,
                "theme": _quarantine_theme_view(original.theme),
                "source": _quarantine_source_view(original.source),
            }
        )
        if original is not None
        else None
    )
    return AdminCurationQuarantineCollectionView.model_validate(
        {
            "collection_id": row.collection_id,
            "row_revision": str(row.row_revision),
            "command_etag": revision_etag(row.row_revision),
            "collection_key": row.collection_key,
            "title": row.title,
            "edition_key": row.edition_key,
            "status": row.status,
            "visibility": row.visibility,
            "created_by": row.created_by,
            "item_count": row.item_count,
            "marker_intact": row.marker_intact,
            "quarantine_theme": _quarantine_theme_view(row.quarantine_theme),
            "quarantine_source": _quarantine_source_view(row.quarantine_source),
            "original_collection": original_view,
        }
    )


def _quarantine_item_view(
    row: curation_repo.CurationQuarantineItem,
) -> AdminCurationQuarantineItemView:
    # T-VN-32C 치환 제외 — 격리 item의 feature_id는 저장된 링크 상태 그대로를
    # 보여주는 정합 복구 표면이다 (repo projection도 legacy 단독, 미확장).
    return AdminCurationQuarantineItemView.model_validate(row, from_attributes=True)


def _group_view(
    row: curation_repo.FeatureCurationGroup,
) -> FeatureCurationGroupView:
    # T-VN-32C PR-2 — 응답 feature record의 feature_id는 UUID 정본. group 조립의
    # 내부 키(repo grouped_items lookup)는 치환 전 legacy 축이다.
    return FeatureCurationGroupView(
        feature=CurationFeatureView(
            feature_id=response_feature_id(row),
            name=row.name,
            kind=row.kind,
            category=row.category,
            lon=row.lon,
            lat=row.lat,
            address=row.address,
        ),
        curations=[_public_item_view(item) for item in row.curations],
        curation_count=len(row.curations),
    )


async def _provider_dataset_ids_by_pair(
    session: AsyncSession,
    rows: Sequence[CurationImportRow],
) -> dict[tuple[str, str], int]:
    """CSV 자연키 pair를 이 DB의 ``provider_dataset_id``로 해석한다 (질의 1회)."""

    pairs = sorted({(row.provider, row.dataset_key) for row in rows})
    if not pairs:
        return {}
    result = await session.execute(
        text(
            "SELECT provider, dataset_key, provider_dataset_id "
            "FROM provider_sync.provider_datasets "
            "WHERE (provider, dataset_key) IN ("
            "  SELECT unnest(CAST(:providers AS text[])), "
            "         unnest(CAST(:dataset_keys AS text[]))"
            ")"
        ),
        {
            "providers": [pair[0] for pair in pairs],
            "dataset_keys": [pair[1] for pair in pairs],
        },
    )
    return {
        (str(row.provider), str(row.dataset_key)): int(row.provider_dataset_id)
        for row in result
    }


async def _lighthouse_dataset_pairs(
    session: AsyncSession,
    rows: Sequence[CurationImportRow],
) -> frozenset[tuple[str, str]]:
    """CSV가 가리킨 dataset 중 등대 공식 pair만 반환한다.

    판정 축은 자연키다 — CSV는 저장소에 sha로 고정돼 어느 DB에나 적용되는데
    ``provider_dataset_id``는 DB마다 다른 surrogate라 파일에 담길 수 없다.
    """

    candidates = sorted({row.dataset_key for row in rows})
    if not candidates:
        return frozenset()
    result = await session.execute(
        text(
            "SELECT provider, dataset_key FROM provider_sync.provider_datasets "
            "WHERE dataset_key = ANY(CAST(:dataset_keys AS text[])) "
            "AND dataset_key LIKE 'lighthouse-stamp-tour-season-%'"
        ),
        {"dataset_keys": candidates},
    )
    return frozenset((str(row.provider), str(row.dataset_key)) for row in result)


def _conflict(exc: IntegrityError) -> HTTPException:
    return HTTPException(status_code=409, detail="curation constraint violation")


def _import_plan_sha256(request: Request) -> str:
    values = request.headers.getlist("If-Match")
    if not values:
        raise HTTPException(status_code=428, detail="If-Match header가 필요합니다.")
    if len(values) != 1:
        raise HTTPException(status_code=422, detail="If-Match는 정확히 하나여야 합니다.")
    value = values[0]
    prefix = '"sha256:'
    if not value.startswith(prefix) or not value.endswith('"'):
        raise HTTPException(status_code=422, detail="import plan ETag 형식이 아닙니다.")
    digest = value[len(prefix) : -1]
    if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
        raise HTTPException(status_code=422, detail="import plan ETag 형식이 아닙니다.")
    return digest


def _import_plan_command_error(exc: DBAPIError) -> HTTPException:
    message = str(exc.orig)
    sqlstate = getattr(exc.orig, "sqlstate", None)
    if sqlstate == "40001":
        raise exc
    if sqlstate == "P0002":
        return HTTPException(status_code=404, detail="curation import plan 없음")
    if any(
        marker in message
        for marker in (
            "plan actor or ETag changed",
            "plan expired",
            "revision vector is stale",
        )
    ):
        return HTTPException(status_code=412, detail=message)
    if sqlstate == "23505" or "already committed" in message:
        return HTTPException(status_code=409, detail=message)
    if sqlstate == "42501":
        return HTTPException(
            status_code=403,
            detail="curation import plan command 권한이 없습니다.",
        )
    if sqlstate in {"22P02", "23502", "23503", "23514", "22023"}:
        return HTTPException(status_code=422, detail=message)
    raise exc


def _collection_command_error(exc: DBAPIError) -> HTTPException:
    message = str(exc.orig)
    sqlstate = getattr(exc.orig, "sqlstate", None)
    if sqlstate == "40001":
        raise exc
    if "collection revision mismatch" in message:
        return HTTPException(status_code=412, detail="curation collection revision이 변경됐습니다.")
    if sqlstate == "P0002":
        return HTTPException(status_code=404, detail="curation collection 없음")
    if sqlstate == "23505":
        return HTTPException(status_code=409, detail="curation collection identity conflict")
    if sqlstate == "23514" and "archived collection" in message:
        return HTTPException(status_code=409, detail=message)
    if sqlstate in {"22P02", "23502", "23503", "23514", "22023"}:
        return HTTPException(status_code=422, detail=message)
    if sqlstate == "42501":
        return HTTPException(status_code=403, detail="curation collection command 권한이 없습니다.")
    raise exc


def _item_command_error(exc: DBAPIError) -> HTTPException:
    message = str(exc.orig)
    sqlstate = getattr(exc.orig, "sqlstate", None)
    if sqlstate == "40001":
        raise exc
    if "item identity or revision changed" in message:
        return HTTPException(status_code=412, detail="curation item revision이 변경됐습니다.")
    if sqlstate == "P0002":
        return HTTPException(status_code=404, detail="curation item 또는 collection 없음")
    if sqlstate == "23505":
        return HTTPException(status_code=409, detail="curation item identity conflict")
    if sqlstate == "23514" and "archived" in message:
        return HTTPException(status_code=409, detail=message)
    if sqlstate in {"22P02", "23502", "23503", "23514", "22023"}:
        return HTTPException(status_code=422, detail=message)
    if sqlstate == "42501":
        return HTTPException(status_code=403, detail="curation item command 권한이 없습니다.")
    raise exc


def _theme_candidate_view(
    row: curation_candidate_repo.ThemeCandidateRecord,
) -> AdminThemeCandidateView:
    representation_payload = {
        "candidate_id": row.candidate_id,
        "candidate_revision": str(row.row_revision),
        "rule_row_revision": str(row.rule_row_revision),
        "rule_input_hash": row.rule_input_hash,
        "candidate_input_hash": row.candidate_input_hash,
        "feature_row_revision": str(row.feature_row_revision),
        "feature_detail": row.feature_detail,
    }
    representation_hash = hashlib.sha256(
        json.dumps(
            representation_payload,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
    ).hexdigest()
    return AdminThemeCandidateView(
        candidate_id=UUID(row.candidate_id),
        rule_id=UUID(row.rule_id),
        theme_id=UUID(row.theme_id),
        theme_slug=row.theme_slug,
        theme_name=row.theme_name,
        source_id=UUID(row.source_id),
        source_name=row.source_name,
        provider_dataset_id=row.provider_dataset_id,
        source_entity_key=row.source_entity_key,
        feature_id=response_feature_id(row),
        feature_uuid=UUID(row.feature_uuid),
        feature_name=row.feature_name,
        feature_kind=row.feature_kind,
        feature_category=row.feature_category,
        feature_detail=row.feature_detail,
        lifecycle_state=row.lifecycle_state,
        publication_state=row.publication_state,
        quality_state=row.quality_state,
        source_record_key=row.source_record_key,
        source_record_hash=row.source_record_hash,
        rule_row_revision=str(row.rule_row_revision),
        rule_input_hash=row.rule_input_hash,
        candidate_input_hash=row.candidate_input_hash,
        review_state=row.review_state,
        eligibility_present=row.eligibility_present,
        disposition=row.disposition,
        rank_score=row.rank_score,
        proposal_title=row.proposal_title,
        proposal_summary=row.proposal_summary,
        match_evidence=row.match_evidence,
        candidate_revision=str(row.row_revision),
        candidate_etag=revision_etag(row.row_revision),
        feature_row_revision=str(row.feature_row_revision),
        representation_etag=f'"sha256:{representation_hash}"',
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _theme_candidate_transition_view(
    row: curation_candidate_repo.ThemeCandidateTransitionRecord,
) -> AdminThemeCandidateTransitionView:
    return AdminThemeCandidateTransitionView(
        transition_id=str(row.transition_id),
        candidate_id=UUID(row.candidate_id),
        transition_kind=row.transition_kind,
        from_review_state=row.from_review_state,
        to_review_state=row.to_review_state,
        from_eligibility_present=row.from_eligibility_present,
        to_eligibility_present=row.to_eligibility_present,
        candidate_revision=str(row.candidate_row_revision),
        generation_id=UUID(row.generation_id) if row.generation_id else None,
        command_id=str(row.command_id) if row.command_id is not None else None,
        actor=row.actor,
        reason_code=row.reason_code,
        causation_ref=row.causation_ref,
        occurred_at=row.occurred_at,
    )


def _candidate_command_error(exc: DBAPIError) -> HTTPException:
    message = str(exc.orig)
    sqlstate = getattr(exc.orig, "sqlstate", None)
    if "revision mismatch" in message or "expected candidate revision" in message:
        return HTTPException(status_code=412, detail="candidate revision이 변경됐습니다.")
    if sqlstate == "23505":
        return HTTPException(status_code=409, detail="curation item identity conflict")
    if sqlstate == "P0002":
        return HTTPException(status_code=404, detail="candidate 또는 target resource 없음")
    if sqlstate == "23514" and any(
        token in message
        for token in ("stale", "no longer", "only an active", "does not exist", "archived")
    ):
        return HTTPException(status_code=409, detail=message)
    if sqlstate in {"23514", "22023"}:
        return HTTPException(status_code=422, detail=message)
    if sqlstate == "42501":
        return HTTPException(status_code=403, detail="candidate command 권한이 없습니다.")
    raise exc


def _issue_view(issue: CurationImportIssue) -> CurationImportIssueView:
    return CurationImportIssueView.model_validate(issue, from_attributes=True)


def _candidate_view(
    match: curation_repo.FeatureMatch,
) -> CurationImportFeatureCandidateView:
    # T-VN-32C PR-2 — 후보 표시 feature_id는 UUID 정본. 자동 채택·DB 반영은
    # 치환 전 match.feature_id(legacy)를 쓴다 (write 경로 legacy 축).
    view = CurationImportFeatureCandidateView.model_validate(match, from_attributes=True)
    return view.model_copy(update={"feature_id": response_feature_id(match)})


def _adopted_match(
    row: CurationImportRow,
    matches: Sequence[curation_repo.FeatureMatch],
) -> curation_repo.FeatureMatch | None:
    """CSV가 명시한 exact Feature ID만 자동 채택한다.

    이름과 구조화 주소가 유일해도 ``address_hint``는 preview evidence일 뿐 승인
    decision이 아니다. 운영자는 후보를 검토한 뒤 CSV ``feature_id`` 또는 admin item
    PATCH로 명시적으로 확정한다(#909).
    """
    if not (row.feature_id or "").strip():
        return None
    return matches[0] if len(matches) == 1 else None


def _sido_name(address: Mapping[str, Any] | None) -> str | None:
    value = (address or {}).get("sido_name")
    return str(value) if value else None


def _unlinked_issue(
    row: CurationImportRow,
    matches: Sequence[curation_repo.FeatureMatch],
) -> CurationImportIssueView:
    """미연결 사유를 **구분 가능하게** 만든다 (T-VN-H36).

    운영자가 "후보가 아예 없다"와 "이름은 맞는 후보가 있는데 자동으로 붙이지 않았다"를
    구분할 수 있어야 한다. 전자는 공급원 부재(→ provider 적재 문제)이고 후자는 사람이
    확인해서 붙이면 되는 건이라, 해야 할 일이 다르다.

    ``code``는 openapi에서 자유 문자열이므로(``CurationImportIssueView.code: str``)
    새 코드를 늘려도 스키마·프런트 타입이 바뀌지 않는다. ``ImportRowStatus``(enum)를
    건드리면 openapi drift → 생성 타입 → 프런트 수기 union → 배지 맵까지 연쇄된다.

    후보의 시도명은 ``FeatureMatch.address`` jsonb에 이미 들어 있어(리졸버가 이미 SELECT한다)
    SQL도 DTO도 넓히지 않고 사유 문장에 넣을 수 있다.
    """
    if not matches:
        return CurationImportIssueView(
            code="unmatched",
            message="기존 Feature와 일치하는 후보가 없어 미연결 항목으로 저장합니다.",
            row_number=row.row_number,
        )

    if (row.feature_id or "").strip():
        return CurationImportIssueView(
            code="ambiguous",
            message="명시한 Feature ID 후보가 여러 개여서 미연결 항목으로 저장합니다.",
            row_number=row.row_number,
        )

    if (row.address_hint or "").strip():
        return CurationImportIssueView(
            code="address_candidate_requires_review",
            message=(
                f"정규화 이름+구조화 주소 후보 {len(matches)}건을 찾았으나 address_hint는 "
                "링크 승인 근거가 아닙니다. 후보를 검토한 뒤 CSV feature_id 또는 admin에서 "
                "명시적으로 연결하세요."
            ),
            row_number=row.row_number,
        )

    where = ", ".join(
        sorted({s for s in (_sido_name(m.address) for m in matches[:3]) if s})
    )
    detail = f" 후보 소재: {where}." if where else ""
    row_region = str((row.metadata_json or {}).get("region") or "").strip()
    region_context = f" CSV region: '{row_region}'." if row_region else ""
    return CurationImportIssueView(
        code="name_only_match",
        message=(
            f"이름만 일치하는 후보 {len(matches)}건을 찾았으나 자동 링크하지 않았습니다 — "
            f"동명이 하나뿐이라는 것이 같은 장소라는 뜻은 아닙니다 (T-VN-H36)."
            f"{detail}{region_context}"
            " 확인 후 CSV feature_id에 적거나 admin에서 직접 연결하세요."
        ),
        row_number=row.row_number,
    )


def _import_metadata(row: CurationImportRow) -> dict[str, Any]:
    metadata = dict(row.metadata_json)
    if row.subcourse:
        metadata["subcourse"] = row.subcourse
    if row.official_ordinal is not None:
        metadata["official_ordinal"] = row.official_ordinal
    if row.place_name:
        metadata["official_place_name"] = row.place_name
    if row.address_hint:
        metadata["address_hint"] = row.address_hint
    return metadata


@admin_router.get(
    "/link-audit",
    response_model=CurationLinkAuditResponse,
)
async def audit_unattributed_curation_links(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    _context: Annotated[AdminProxyContext, Depends(require_admin_frontend)],
    limit: Annotated[int, Query(ge=1, le=10_000)] = 500,
    cursor: Annotated[str | None, Query()] = None,
) -> CurationLinkAuditResponse:
    """공개 승인에 쓸 수 없는 legacy/provenance-less current link를 감사한다."""

    started_at = perf_counter()
    try:
        rows, next_cursor = (
            await curation_repo.list_unattributed_curation_links_page(
                session,
                limit=limit,
                cursor=cursor,
            )
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    # T-VN-32C 치환 제외 — legacy/provenance-less link의 저장값 감사 증거 표면이라
    # feature_id는 DB에 기록된 표기 그대로 보여준다 (repo projection legacy 단독).
    items = [
        CurationLinkAuditView.model_validate(row, from_attributes=True)
        for row in rows
    ]
    return CurationLinkAuditResponse(
        data=CurationLinkAuditData(
            items=items,
            count=len(items),
            has_more=next_cursor is not None,
            next_cursor=next_cursor,
        ),
        meta=make_meta(request, started_at=started_at),
    )


# `/quarantine...` 리터럴 경로는 `/{collection_id}` 계열보다 **먼저** 선언해야 한다
# (Starlette는 등록 순서로 매칭한다 — `/link-audit` 등 기존 리터럴 경로와 같은 위치 관용).


@admin_router.get(
    "/quarantine",
    response_model=AdminCurationQuarantineCollectionsResponse,
)
async def list_admin_curation_quarantines(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    _context: Annotated[AdminProxyContext, Depends(require_admin_frontend)],
    page_size: Annotated[int, Query(ge=1, le=200)] = 50,
    cursor: Annotated[str | None, Query()] = None,
) -> AdminCurationQuarantineCollectionsResponse:
    """`0065` 정본 marker 술어로 격리 collection 목록을 조회한다 (T-VN-H22A).

    격리 collection이 보관한 theme/source와 원본 collection의 현재 theme/source를
    병렬로 내려준다 — target 추정·추천은 하지 않는다. 빈 목록이 정상 경로다.
    """

    started_at = perf_counter()
    try:
        rows, next_cursor = await curation_repo.list_curation_quarantine_collections(
            session,
            limit=page_size,
            cursor=cursor,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return AdminCurationQuarantineCollectionsResponse(
        data=AdminCurationQuarantineCollectionsData(
            items=[_quarantine_collection_view(row) for row in rows]
        ),
        meta=make_meta(
            request,
            started_at=started_at,
            page_size=page_size,
            next_cursor=next_cursor,
        ),
    )


@admin_router.get(
    "/quarantine/{collection_id}/items",
    response_model=AdminCurationQuarantineItemsResponse,
)
async def list_admin_curation_quarantine_items(
    request: Request,
    collection_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    _context: Annotated[AdminProxyContext, Depends(require_admin_frontend)],
    target_collection_id: Annotated[UUID | None, Query()] = None,
    page_size: Annotated[int, Query(ge=1, le=200)] = 50,
    cursor: Annotated[str | None, Query()] = None,
) -> AdminCurationQuarantineItemsResponse:
    """격리 item 목록 + target 대비 conflict preview (순수 SELECT, T-VN-H22A)."""

    started_at = perf_counter()
    try:
        result = await curation_repo.list_curation_quarantine_items(
            session,
            collection_id=str(collection_id),
            target_collection_id=(
                str(target_collection_id) if target_collection_id is not None else None
            ),
            limit=page_size,
            cursor=cursor,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if result is None:
        raise HTTPException(status_code=404, detail="curation quarantine collection 없음")
    preview, next_cursor = result
    return AdminCurationQuarantineItemsResponse(
        data=AdminCurationQuarantineItemsData(
            target_collection_id=(
                UUID(preview.target_collection_id)
                if preview.target_collection_id is not None
                else None
            ),
            target_collection_revision=(
                str(preview.target_collection_revision)
                if preview.target_collection_revision is not None
                else None
            ),
            target_command_etag=(
                revision_etag(preview.target_collection_revision)
                if preview.target_collection_revision is not None
                else None
            ),
            target_missing=preview.target_missing,
            target_archived=preview.target_archived,
            items=[_quarantine_item_view(item) for item in preview.items],
        ),
        meta=make_meta(
            request,
            started_at=started_at,
            page_size=page_size,
            next_cursor=next_cursor,
        ),
    )


@admin_router.post(
    "/quarantine/{collection_id}/reclassify",
    response_model=AdminCurationQuarantineReclassifyResponse,
    status_code=200,
    responses={
        200: {"headers": _ETAG_RESPONSE_HEADER},
        412: {"description": "collection revision 불일치"},
        428: {"description": "If-Match 헤더 누락"},
    },
    openapi_extra={"parameters": [_IF_MATCH_OPENAPI_PARAMETER]},
)
@idempotent_domain_command("admin.curation-quarantine.reclassify")
async def reclassify_admin_curation_quarantine(
    request: Request,
    collection_id: UUID,
    body: AdminCurationQuarantineReclassifyRequest,
    response: Response,
    session: Annotated[AsyncSession, Depends(get_session)],
    context: Annotated[AdminProxyContext, Depends(require_admin_frontend)],
) -> AdminCurationQuarantineReclassifyResponse:
    """격리 collection을 move 또는 standalone 확정으로 명시 재분류한다 (T-VN-H22B).

    move는 lock 하 (A)/(B) 재검사 뒤 전체 원자 적용이며 충돌 시 409로 전체를
    거부한다(부분 적용 금지). confirm_standalone은 `0065` marker를 제거하고
    collection_key/title을 확정한다.
    """

    started_at = perf_counter()
    expected_collection_revision = parse_revision_header(
        request, "If-Match", required=True
    )
    data: AdminCurationQuarantineReclassifyData
    try:
        async with domain_command_transaction(session):
            command = domain_command_service.current_domain_command()
            if body.action == "move":
                (
                    moved_item_ids,
                    quarantine_deleted,
                ) = await curation_repo.move_curation_quarantine_items(
                    session,
                    collection_id=str(collection_id),
                    expected_collection_revision=expected_collection_revision,
                    target_collection_id=(
                        str(body.target_collection_id)
                        if body.target_collection_id is not None
                        else None
                    ),
                    expected_target_revision=int(body.target_collection_revision or "0"),
                    item_ids=(
                        [str(item_id) for item_id in body.item_ids]
                        if body.item_ids is not None
                        else None
                    ),
                    command_id=command.command_id,
                    actor=context.actor,
                )
                data = AdminCurationQuarantineReclassifyData(
                    action="move",
                    moved_item_ids=[UUID(value) for value in moved_item_ids],
                    quarantine_collection_deleted=quarantine_deleted,
                )
            else:
                (
                    confirmed_id,
                    confirmed_key,
                ) = await curation_repo.confirm_curation_quarantine_standalone(
                    session,
                    collection_id=str(collection_id),
                    expected_collection_revision=expected_collection_revision,
                    collection_key=body.collection_key or "",
                    title=body.title or "",
                    command_id=command.command_id,
                    actor=context.actor,
                )
                data = AdminCurationQuarantineReclassifyData(
                    action="confirm_standalone",
                    collection_id=UUID(confirmed_id),
                    collection_key=confirmed_key,
                )
    except curation_repo.CurationQuarantineMoveConflictError as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "CURATION_QUARANTINE_MOVE_CONFLICT",
                "message": str(exc),
                "details": {
                    "conflicts": [
                        {
                            "curation_item_id": conflict.curation_item_id,
                            "conflict_kind": conflict.conflict_kind,
                            "conflict_item_id": conflict.conflict_item_id,
                        }
                        for conflict in exc.conflicts
                    ]
                },
            },
        ) from exc
    except curation_repo.CurationQuarantineTargetArchivedError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except DBAPIError as exc:
        message = str(exc.orig)
        if "revision or marker changed" in message or "target collection revision" in message:
            raise HTTPException(
                status_code=412,
                detail="curation quarantine 또는 target collection revision이 변경됐습니다.",
            ) from exc
        mapped = _collection_command_error(exc)
        raise mapped from exc
    except IntegrityError as exc:
        raise _conflict(exc) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    result_response = AdminCurationQuarantineReclassifyResponse(
        data=data,
        meta=make_meta(request, started_at=started_at),
    )
    response.headers["ETag"] = _curation_representation_etag(result_response.data)
    return result_response


@admin_router.get(
    "/import-batches/{import_batch_id}",
    response_model=CurationImportBatchResponse,
)
async def get_admin_curation_import_batch(
    request: Request,
    import_batch_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    _context: Annotated[AdminProxyContext, Depends(require_admin_frontend)],
) -> CurationImportBatchResponse:
    """성공한 import batch와 immutable row payload/provenance를 조회한다."""

    started_at = perf_counter()
    result = await curation_repo.get_curation_import_batch(
        session,
        import_batch_id=str(import_batch_id),
    )
    if result is None:
        raise HTTPException(status_code=404, detail="curation import batch 없음")
    batch, rows = result
    data = CurationImportBatchView(
        import_batch_id=UUID(batch.import_batch_id),
        content_sha256=batch.content_sha256,
        batch_kind=batch.batch_kind,
        row_count=batch.row_count,
        actor=batch.actor,
        metadata=batch.metadata,
        imported_at=batch.imported_at,
        rows=[_import_row_receipt_view(row) for row in rows],
    )
    return CurationImportBatchResponse(
        data=data,
        meta=make_meta(request, started_at=started_at),
    )


@admin_router.get(
    "/items/{curation_item_id}/current-import-row",
    response_model=CurationImportRowReceiptResponse,
)
async def get_admin_curation_item_current_import_row(
    request: Request,
    curation_item_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    _context: Annotated[AdminProxyContext, Depends(require_admin_frontend)],
) -> CurationImportRowReceiptResponse:
    """item current pointer의 exact row payload/provenance를 조회한다."""

    started_at = perf_counter()
    row = await curation_repo.get_current_curation_import_row(
        session,
        curation_item_id=str(curation_item_id),
    )
    if row is None:
        raise HTTPException(status_code=404, detail="curation current import row 없음")
    return CurationImportRowReceiptResponse(
        data=_import_row_receipt_view(row),
        meta=make_meta(request, started_at=started_at),
    )


@admin_router.get(
    "/import-template.csv",
    include_in_schema=True,
    response_class=Response,
    responses={
        200: {
            "description": "UTF-8 BOM 큐레이션 CSV 업로드 양식",
            "content": {"text/csv": {"schema": {"type": "string", "format": "binary"}}},
        }
    },
)
async def download_curation_import_template() -> Response:
    """큐레이션 import용 UTF-8 BOM CSV header를 내려준다."""
    output = io.StringIO(newline="")
    csv.writer(output, lineterminator="\n").writerow(CURATION_CSV_HEADERS)
    content = "\ufeff" + output.getvalue()
    return Response(
        content=content.encode("utf-8"),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": ('attachment; filename="kor-travel-map-curations-template.csv"')
        },
    )


@admin_router.post(
    "/imports/preview",
    response_model=CurationImportResponse,
    status_code=201,
    responses={201: {"headers": _ETAG_RESPONSE_HEADER}},
)
@idempotent_domain_command("admin.curation-import.preview")
async def preview_admin_curation_import(
    request: Request,
    response: Response,
    session: Annotated[AsyncSession, Depends(get_session)],
    context: Annotated[AdminProxyContext, Depends(require_admin_frontend)],
    file: Annotated[UploadFile, File(description="UTF-8 CSV 파일")],
    provenance_file: Annotated[
        UploadFile | None,
        File(description="행별 source provenance JSON sidecar"),
    ] = None,
) -> CurationImportResponse:
    """CSV+sidecar를 한 번 해소해 immutable import plan으로 저장한다."""
    started_at = perf_counter()
    command = domain_command_service.current_domain_command()
    content = await file.read(CURATION_CSV_MAX_BYTES + 1)
    content_sha256 = hashlib.sha256(content).hexdigest()
    provenance_content: bytes | None = None
    provenance_by_row: dict[int, dict[str, Any]] = {}
    if provenance_file is not None:
        provenance_content = await provenance_file.read(
            CURATION_PROVENANCE_MAX_BYTES + 1
        )
    provenance_sha256 = (
        hashlib.sha256(provenance_content).hexdigest()
        if provenance_content is not None
        else None
    )
    preview = parse_curation_csv(content)
    if provenance_content is not None:
        try:
            provenance = parse_curation_provenance(
                csv_content=content,
                provenance_content=provenance_content,
            )
        except CurationProvenanceError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        provenance_by_row = {
            csv_row.row_number: provenance_row_payload(provenance, row)
            for csv_row, row in zip(preview.rows, provenance.rows, strict=True)
        }
    elif requires_lighthouse_provenance(
        preview.rows,
        lighthouse_dataset_pairs=await _lighthouse_dataset_pairs(session, preview.rows),
    ):
        raise HTTPException(
            status_code=422,
            detail=(
                "저장소 공식 등대 dataset import에는 exact CSV와 결박된 "
                "provenance_file이 필요합니다."
            ),
        )
    dry_run = True
    # T-VN-32C PR-2 (W8) — CSV의 UUID 표기 feature 참조를 legacy 정본 키로
    # 일괄 정규화해 매칭한다 (miss는 원문 유지 → 기존 unmatched 흐름,
    # requested_feature_id echo는 CSV 원문 보존).
    csv_refs: list[str] = []
    for preview_row in preview.rows:
        if preview_row.status != "valid" or not preview_row.feature_id:
            continue
        try:
            feature_identity.validate_feature_ref(preview_row.feature_id)
        except feature_identity.FeatureIdentityRefError:
            continue  # 형식 위반 참조는 정규화 없이 기존 unmatched 흐름으로.
        csv_refs.append(preview_row.feature_id)
    resolved_csv_refs = await feature_identity.resolve_feature_identities_bulk(
        session, csv_refs
    )

    def _match_feature_id(raw: str | None) -> str | None:
        if not raw:
            return None
        identity = resolved_csv_refs.get(raw)
        return identity.feature_id if identity is not None else raw

    matches_by_row = await curation_repo.resolve_feature_matches(
        session,
        requests=tuple(
            curation_repo.FeatureMatchRequest(
                row_number=row.row_number,
                feature_id=_match_feature_id(row.feature_id),
                place_name=row.place_name or None,
                address_hint=row.address_hint or None,
            )
            for row in preview.rows
            if row.status == "valid"
        ),
    )
    item_views: list[CurationImportRowView] = []
    # CSV의 자연키를 이 DB의 surrogate로 해석한다(질의 1회). CSV가 자연키를 들고
    # 있으므로 해석은 적재 시점 몫이고, 해석 못 한 pair는 조용히 넘기지 않는다 —
    # 통과시키면 curation이 대상 dataset 없이 적재된다.
    dataset_ids_by_pair = await _provider_dataset_ids_by_pair(session, preview.rows)
    resolved_rows: list[curation_repo.ResolvedCurationImportRow] = []

    for row in preview.rows:
        if row.status == "invalid":
            item_views.append(
                CurationImportRowView(
                    row_number=row.row_number,
                    status="invalid",
                    collection_key=row.collection_key,
                    theme_slug=row.theme_slug,
                    title=row.title,
                    edition_key=row.edition_key,
                    place_name=row.place_name,
                    address_hint=row.address_hint,
                    # echo 예외 — CSV가 적은 표기를 그대로 되돌린다 (치환 금지).
                    requested_feature_id=row.feature_id,
                    resolved_feature_id=None,
                    source_item_key=row.source_item_key,
                    source_component_key=row.source_component_key,
                    candidates=[],
                    issues=[_issue_view(issue) for issue in row.issues],
                )
            )
            continue

        matches = matches_by_row.get(row.row_number, ())
        match = _adopted_match(row, matches)
        row_status: ImportRowStatus
        row_issues: list[CurationImportIssueView]
        if match is not None:
            row_status = "valid" if dry_run else "imported"
            row_issues = []
        else:
            if not matches:
                row_status = "unmatched"
            elif not (row.feature_id or "").strip():
                row_status = "review_required"
            else:
                row_status = "ambiguous"
            row_issues = [_unlinked_issue(row, matches)]
        # catalog에 없는 pair는 여기서 끊는다. 이 fail-close가 parser/catalog
        # drift를 HTTP write까지 전파하지 않는다.
        dataset_id = dataset_ids_by_pair.get((row.provider, row.dataset_key))
        if dataset_id is None:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"catalog에 없는 provider/dataset_key입니다: "
                    f"{row.provider}/{row.dataset_key}"
                ),
            )
        resolved_rows.append(
            curation_repo.ResolvedCurationImportRow(
                row_number=row.row_number,
                collection_key=row.collection_key,
                theme_slug=row.theme_slug,
                theme_name=row.theme_name,
                theme_group=row.theme_group,
                title=row.title,
                edition_key=row.edition_key,
                provider_dataset_id=dataset_id,
                source_name=row.source_name,
                source_url=row.source_url or None,
                source_item_key=row.source_item_key,
                source_component_key=row.source_component_key,
                # 내부 write 경로 — DB FK는 legacy 축이므로 치환하지 않는다 (T-VN-32C).
                feature_id=match.feature_id if match is not None else None,
                place_name=(
                    row.place_name or (match.name if match is not None else row.feature_id)
                ),
                address_hint=row.address_hint or None,
                sort_order=(
                    row.sort_order
                    if row.sort_order is not None
                    else (
                        row.official_ordinal
                        if row.official_ordinal is not None
                        else row.row_number - 1
                    )
                ),
                item_title=row.item_title or None,
                item_summary=row.item_summary or None,
                metadata=_import_metadata(row),
                provenance=provenance_by_row.get(row.row_number),
            )
        )
        item_views.append(
            CurationImportRowView(
                row_number=row.row_number,
                status=row_status,
                collection_key=row.collection_key,
                theme_slug=row.theme_slug,
                title=row.title,
                edition_key=row.edition_key,
                place_name=row.place_name,
                address_hint=row.address_hint,
                # echo 예외 — CSV 표기 보존. resolved는 응답 표시 필드라 UUID 정본.
                requested_feature_id=row.feature_id,
                resolved_feature_id=(
                    response_feature_id(match) if match is not None else None
                ),
                source_item_key=row.source_item_key,
                source_component_key=row.source_component_key,
                candidates=[_candidate_view(candidate) for candidate in matches],
                issues=row_issues,
            )
        )

    resolved_identity_issues = curation_repo.validate_resolved_curation_identities(resolved_rows)
    identity_issues_by_row: dict[int, list[CurationImportIssueView]] = {}
    for issue in resolved_identity_issues:
        identity_issues_by_row.setdefault(issue.row_number, []).append(
            CurationImportIssueView(
                code=issue.code,
                message=issue.message,
                row_number=issue.row_number,
            )
        )
    if identity_issues_by_row:
        item_views = [
            item.model_copy(
                update={
                    "status": "invalid",
                    "issues": item.issues + identity_issues_by_row.get(item.row_number, []),
                }
            )
            if item.row_number in identity_issues_by_row
            else item
            for item in item_views
        ]

    has_errors = preview.has_errors or bool(resolved_identity_issues)
    change_plan = curation_repo.CurationImportPlan(
        collections=0, inserted=0, updated=0, removals=()
    )
    revisions: tuple[curation_repo.CurationImportRevisionExpectation, ...] = ()
    try:
        if not has_errors:
            change_plan = await curation_repo.preview_curation_import(
                session,
                rows=resolved_rows,
            )
            revisions = await curation_repo.build_curation_import_revision_vector(
                session,
                rows=resolved_rows,
            )
        result: curation_repo.CurationImportResult = {
            "rows": len(resolved_rows),
            "inserted": change_plan.inserted,
            "updated": change_plan.updated,
            "removed": len(change_plan.removals),
            "collections": change_plan.collections,
            "removals": change_plan.removals,
            "import_batch_id": None,
        }
    except IntegrityError as exc:
        raise _conflict(exc) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    invalid_rows = sum(item.status == "invalid" for item in item_views)
    valid_rows = sum(item.status != "invalid" for item in item_views)
    unresolved_rows = sum(
        item.status in {"unmatched", "review_required", "ambiguous"}
        for item in item_views
    )
    issues = [_issue_view(issue) for issue in preview.issues] + [
        issue for row_issues in identity_issues_by_row.values() for issue in row_issues
    ]
    import_plan_id = uuid4()
    expires_at = datetime.now(UTC) + timedelta(hours=1)
    summary = {
        "schema_version": 1,
        "rows_total": preview.rows_total,
        "valid_rows": valid_rows,
        "invalid_rows": invalid_rows,
        "unresolved_rows": unresolved_rows,
        "inserted": int(result["inserted"]),
        "updated": int(result["updated"]),
        "removed": int(result["removed"]),
        "collections": int(result["collections"]),
        "has_errors": has_errors,
    }
    plan_hash_input = {
        "schema_version": 1,
        "import_plan_id": str(import_plan_id),
        "actor": context.actor,
        "content_sha256": content_sha256,
        "provenance_sha256": provenance_sha256,
        "summary": summary,
        "rows": [item.model_dump(mode="json") for item in item_views],
        "revisions": [
            {
                "resource_kind": revision.resource_kind,
                "resource_key": revision.resource_key,
                "expected_revision": revision.expected_revision,
            }
            for revision in revisions
        ],
        "expires_at": expires_at.isoformat(),
    }
    plan_sha256 = hashlib.sha256(
        json.dumps(
            plan_hash_input,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
    ).hexdigest()
    try:
        await curation_repo.create_curation_import_plan_command(
            session,
            import_plan_id=str(import_plan_id),
            content_sha256=content_sha256,
            provenance_sha256=provenance_sha256,
            plan_sha256=plan_sha256,
            summary=summary,
            rows=resolved_rows,
            response_rows=[item.model_dump(mode="json") for item in item_views],
            revisions=revisions,
            expires_at=expires_at,
            command_id=command.command_id,
            principal=context.actor,
        )
    except DBAPIError as exc:
        raise _import_plan_command_error(exc) from exc
    plan_etag = f'"sha256:{plan_sha256}"'
    result_response = CurationImportResponse(
        data=CurationImportData(
            dry_run=dry_run,
            import_plan_id=import_plan_id,
            plan_etag=plan_etag,
            expires_at=expires_at,
            rows_total=preview.rows_total,
            valid_rows=valid_rows,
            invalid_rows=invalid_rows,
            unresolved_rows=unresolved_rows,
            inserted=int(result["inserted"]),
            updated=int(result["updated"]),
            removed=int(result["removed"]),
            collections=int(result["collections"]),
            import_batch_id=(
                UUID(str(result["import_batch_id"]))
                if result["import_batch_id"] is not None
                else None
            ),
            removals=[_admin_item_view(item) for item in result["removals"]],
            items=item_views,
            issues=issues,
        ),
        meta=make_meta(request, started_at=started_at),
    )
    response.headers["ETag"] = plan_etag
    return result_response


@admin_router.post(
    "/import-plans/{import_plan_id}/commit",
    response_model=CurationImportResponse,
    responses={
        200: {"headers": _ETAG_RESPONSE_HEADER},
        412: {"description": "plan ETag/expiry/revision vector stale"},
        428: {"description": "If-Match 누락"},
    },
    openapi_extra={"parameters": [_IMPORT_PLAN_IF_MATCH_OPENAPI_PARAMETER]},
)
@idempotent_domain_command("admin.curation.import")
async def commit_admin_curation_import_plan(
    request: Request,
    import_plan_id: UUID,
    response: Response,
    session: Annotated[AsyncSession, Depends(get_session)],
    context: Annotated[AdminProxyContext, Depends(require_admin_frontend)],
) -> CurationImportResponse:
    """stored normalized plan을 재해소 없이 exact revision vector 위에서 반영한다."""

    started_at = perf_counter()
    plan_sha256 = _import_plan_sha256(request)
    command = domain_command_service.current_domain_command()
    try:
        async with domain_command_transaction(session):
            (
                content_sha256,
                resolved_rows,
                summary,
                stored_response_rows,
                expires_at,
            ) = await curation_repo.claim_curation_import_plan_command(
                session,
                import_plan_id=str(import_plan_id),
                plan_sha256=plan_sha256,
                command_id=command.command_id,
                principal=context.actor,
            )
            result = await curation_repo.import_curation_rows(
                session,
                rows=resolved_rows,
                actor=context.actor,
                source_content_sha256=content_sha256,
                batch_kind="csv_upload",
                command_id=command.command_id,
            )
            import_batch_id = result["import_batch_id"]
            if import_batch_id is None:
                raise RuntimeError("curation import commit에 import batch receipt가 없습니다.")
            item_views = [
                CurationImportRowView.model_validate(payload)
                for payload in stored_response_rows
            ]
            item_views = [
                item.model_copy(update={"status": "imported"})
                if item.status == "valid" and item.resolved_feature_id is not None
                else item
                for item in item_views
            ]
            issues = [issue for item in item_views for issue in item.issues]
            plan_etag = f'"sha256:{plan_sha256}"'
            result_response = CurationImportResponse(
                data=CurationImportData(
                    dry_run=False,
                    import_plan_id=import_plan_id,
                    plan_etag=plan_etag,
                    expires_at=expires_at,
                    rows_total=int(summary["rows_total"]),
                    valid_rows=int(summary["valid_rows"]),
                    invalid_rows=int(summary["invalid_rows"]),
                    unresolved_rows=int(summary["unresolved_rows"]),
                    inserted=int(result["inserted"]),
                    updated=int(result["updated"]),
                    removed=int(result["removed"]),
                    collections=int(result["collections"]),
                    import_batch_id=UUID(str(import_batch_id)),
                    removals=[_admin_item_view(item) for item in result["removals"]],
                    items=item_views,
                    issues=issues,
                ),
                meta=make_meta(request, started_at=started_at),
            )
            await curation_repo.complete_curation_import_plan_command(
                session,
                import_plan_id=str(import_plan_id),
                command_id=command.command_id,
                import_batch_id=str(import_batch_id),
                result_payload=result_response.model_dump(mode="json"),
                principal=context.actor,
            )
    except DBAPIError as exc:
        raise _import_plan_command_error(exc) from exc
    except (IntegrityError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    response.headers["ETag"] = plan_etag
    return result_response


@candidate_router.get("", response_model=AdminThemeCandidatePageResponse)
async def list_admin_theme_candidates(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    rule_id: Annotated[UUID | None, Query()] = None,
    theme_id: Annotated[UUID | None, Query()] = None,
    source_id: Annotated[UUID | None, Query()] = None,
    review_state: Annotated[CandidateReviewState | None, Query()] = None,
    eligibility_present: Annotated[bool | None, Query()] = None,
    feature_id: Annotated[str | None, Query()] = None,
    page_size: Annotated[int, Query(ge=1, le=200)] = 100,
    cursor: Annotated[str | None, Query()] = None,
) -> AdminThemeCandidatePageResponse:
    started_at = perf_counter()
    try:
        page = await curation_candidate_repo.list_theme_candidates(
            session,
            rule_id=str(rule_id) if rule_id else None,
            theme_id=str(theme_id) if theme_id else None,
            source_id=str(source_id) if source_id else None,
            review_state=review_state,
            eligibility_present=eligibility_present,
            feature_id=feature_id,
            limit=page_size,
            cursor=cursor,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return AdminThemeCandidatePageResponse(
        data=AdminThemeCandidatePageData(
            items=[_theme_candidate_view(row) for row in page.items]
        ),
        meta=make_meta(
            request,
            started_at=started_at,
            page_size=page_size,
            next_cursor=page.next_cursor,
        ),
    )


@candidate_router.get(
    "/{candidate_id}",
    response_model=AdminThemeCandidateResponse,
    responses={304: {"description": "representation ETag 일치"}},
)
async def get_admin_theme_candidate(
    request: Request,
    candidate_id: UUID,
    response: Response,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AdminThemeCandidateResponse | Response:
    started_at = perf_counter()
    row = await curation_candidate_repo.get_theme_candidate(
        session, candidate_id=str(candidate_id)
    )
    if row is None:
        raise HTTPException(status_code=404, detail="theme candidate 없음")
    view = _theme_candidate_view(row)
    if request.headers.get("if-none-match") == view.representation_etag:
        return Response(status_code=304, headers={"ETag": view.representation_etag})
    response.headers["ETag"] = view.representation_etag
    return AdminThemeCandidateResponse(
        data=view,
        meta=make_meta(request, started_at=started_at),
    )


@candidate_router.get(
    "/{candidate_id}/transitions",
    response_model=AdminThemeCandidateTransitionPageResponse,
)
async def list_admin_theme_candidate_transitions(
    request: Request,
    candidate_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    before_transition_id: Annotated[int | None, Query(gt=0)] = None,
    page_size: Annotated[int, Query(ge=1, le=200)] = 100,
) -> AdminThemeCandidateTransitionPageResponse:
    started_at = perf_counter()
    if await curation_candidate_repo.get_theme_candidate(
        session, candidate_id=str(candidate_id)
    ) is None:
        raise HTTPException(status_code=404, detail="theme candidate 없음")
    page = await curation_candidate_repo.list_theme_candidate_transitions(
        session,
        candidate_id=str(candidate_id),
        before_transition_id=before_transition_id,
        limit=page_size,
    )
    return AdminThemeCandidateTransitionPageResponse(
        data=AdminThemeCandidateTransitionPageData(
            items=[_theme_candidate_transition_view(row) for row in page.items]
        ),
        meta=make_meta(
            request,
            started_at=started_at,
            page_size=page_size,
            next_cursor=str(page.next_cursor) if page.next_cursor else None,
        ),
    )


@candidate_router.post(
    "/{candidate_id}/reject",
    response_model=ThemeCandidateCommandResponse,
    responses={
        200: {"headers": _ETAG_RESPONSE_HEADER},
        412: {"description": "stale candidate If-Match"},
        428: {"description": "If-Match 누락"},
    },
    openapi_extra={"parameters": [_IF_MATCH_OPENAPI_PARAMETER]},
)
@idempotent_domain_command("admin.theme-feature-candidate.reject")
async def reject_admin_theme_candidate(
    request: Request,
    candidate_id: UUID,
    body: ThemeCandidateRejectRequest,
    response: Response,
    session: Annotated[AsyncSession, Depends(get_session)],
    context: Annotated[AdminProxyContext, Depends(require_admin_frontend)],
) -> ThemeCandidateCommandResponse:
    started_at = perf_counter()
    expected_revision = parse_revision_header(request, "If-Match", required=True)
    assert expected_revision is not None
    try:
        async with domain_command_transaction(session):
            result = await curation_candidate_repo.reject_theme_candidate(
                session,
                candidate_id=str(candidate_id),
                expected_revision=expected_revision,
                command_id=domain_command_service.current_domain_command().command_id,
                reason_code=body.reason_code,
                principal=context.actor,
            )
    except DBAPIError as exc:
        raise _candidate_command_error(exc) from exc
    response.headers["ETag"] = revision_etag(result[1])
    return ThemeCandidateCommandResponse(
        data=ThemeCandidateCommandData(
            candidate_id=UUID(result[0]),
            candidate_revision=str(result[1]),
            transition_id=str(result[2]),
        ),
        meta=make_meta(request, started_at=started_at),
    )


@candidate_router.post(
    "/{candidate_id}/promote",
    response_model=ThemeCandidateCommandResponse,
    responses={
        200: {"headers": _ETAG_RESPONSE_HEADER},
        412: {"description": "stale candidate/collection/item revision"},
        428: {"description": "If-Match 누락"},
    },
    openapi_extra={"parameters": [_IF_MATCH_OPENAPI_PARAMETER]},
)
@idempotent_domain_command("admin.theme-feature-candidate.promote")
async def promote_admin_theme_candidate(
    request: Request,
    candidate_id: UUID,
    body: ThemeCandidatePromoteRequest,
    response: Response,
    session: Annotated[AsyncSession, Depends(get_session)],
    context: Annotated[AdminProxyContext, Depends(require_admin_frontend)],
) -> ThemeCandidateCommandResponse:
    started_at = perf_counter()
    expected_revision = parse_revision_header(request, "If-Match", required=True)
    assert expected_revision is not None
    try:
        async with domain_command_transaction(session):
            result = await curation_candidate_repo.promote_theme_candidate(
                session,
                candidate_id=str(candidate_id),
                collection_id=str(body.collection_id),
                external_item_id=body.external_item_id,
                external_component_id=body.external_component_id,
                place_name=body.place_name,
                address_hint=body.address_hint,
                item_title=body.item_title,
                item_summary=body.item_summary,
                sort_order=body.sort_order,
                curation_relation=body.curation_relation,
                reuse_policy=body.reuse_policy,
                item_status=body.item_status,
                expected_candidate_revision=expected_revision,
                expected_collection_revision=int(body.collection_revision),
                expected_item_revision=(
                    int(body.item_revision) if body.item_revision else None
                ),
                command_id=domain_command_service.current_domain_command().command_id,
                reason_code=body.reason_code,
                principal=context.actor,
            )
    except DBAPIError as exc:
        raise _candidate_command_error(exc) from exc
    response.headers["ETag"] = revision_etag(result[1])
    return ThemeCandidateCommandResponse(
        data=ThemeCandidateCommandData(
            candidate_id=UUID(result[0]),
            candidate_revision=str(result[1]),
            curation_item_id=UUID(result[2]),
            curation_item_revision=str(result[3]),
            transition_id=str(result[4]),
        ),
        meta=make_meta(request, started_at=started_at),
    )


@router.get("", response_model=FeatureCurationGroupsResponse)
async def list_public_curation_groups(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    theme_slug: Annotated[str | None, Query()] = None,
    edition_key: Annotated[str | None, Query()] = None,
    provider_dataset_id: Annotated[int | None, Query(gt=0)] = None,
    q: Annotated[str | None, Query()] = None,
    min_lon: Annotated[float | None, Query()] = None,
    min_lat: Annotated[float | None, Query()] = None,
    max_lon: Annotated[float | None, Query()] = None,
    max_lat: Annotated[float | None, Query()] = None,
    page_size: Annotated[int, Query(ge=1, le=500)] = 100,
    cursor: Annotated[str | None, Query()] = None,
) -> FeatureCurationGroupsResponse:
    started_at = perf_counter()
    try:
        rows, next_cursor = await curation_repo.list_feature_curation_groups(
            session,
            public_only=True,
            theme_slug=theme_slug,
            edition_key=edition_key,
            provider_dataset_id=provider_dataset_id,
            q=q,
            min_lon=min_lon,
            min_lat=min_lat,
            max_lon=max_lon,
            max_lat=max_lat,
            page_size=page_size,
            cursor=cursor,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return FeatureCurationGroupsResponse(
        data=FeatureCurationGroupsData(items=[_group_view(row) for row in rows]),
        meta=make_meta(
            request,
            started_at=started_at,
            page_size=page_size,
            next_cursor=next_cursor,
        ),
    )


@router.get("/collections", response_model=CurationCollectionsResponse)
async def list_public_curation_collections(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    theme_slug: Annotated[str | None, Query()] = None,
    edition_key: Annotated[str | None, Query()] = None,
    provider_dataset_id: Annotated[int | None, Query(gt=0)] = None,
    q: Annotated[str | None, Query()] = None,
    page_size: Annotated[int, Query(ge=1, le=500)] = 200,
    cursor: Annotated[str | None, Query()] = None,
) -> CurationCollectionsResponse:
    started_at = perf_counter()
    try:
        rows, next_cursor = await curation_repo.list_curation_collections(
            session,
            status="published",
            visibility="public",
            theme_slug=theme_slug,
            edition_key=edition_key,
            provider_dataset_id=provider_dataset_id,
            q=q,
            public_only=True,
            limit=page_size,
            cursor=cursor,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return CurationCollectionsResponse(
        data=CurationCollectionsData(items=[_public_collection_view(row) for row in rows]),
        meta=make_meta(
            request,
            started_at=started_at,
            page_size=page_size,
            next_cursor=next_cursor,
        ),
    )


@router.get("/collections/{collection_id}", response_model=CurationCollectionResponse)
async def get_public_curation_collection(
    request: Request,
    collection_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> CurationCollectionResponse:
    started_at = perf_counter()
    result = await curation_repo.get_curation_collection(
        session, collection_id=str(collection_id), public_only=True
    )
    if result is None or result[0].status != "published" or result[0].visibility != "public":
        raise HTTPException(status_code=404, detail="curation collection 없음")
    collection, items = result
    public_items = [item for item in items if item.status == "included"]
    return CurationCollectionResponse(
        data=CurationCollectionData(
            collection=_public_collection_view(collection),
            items=[_public_item_view(item) for item in public_items],
        ),
        meta=make_meta(request, started_at=started_at),
    )


@router.get("/features/{feature_id}", response_model=FeatureCurationGroupResponse)
async def get_public_feature_curations(
    request: Request,
    feature_id: str,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> FeatureCurationGroupResponse:
    started_at = perf_counter()
    # T-VN-32C PR-2 (S11) — `/{feature_id}` 계열과 동일한 경계 해석: legacy·UUID
    # 양형식 수용(형식 오류 422, 미존재 404), 내부 조회는 정본 legacy 키.
    identity = await resolve_feature_ref_or_error(session, feature_id)
    row = await curation_repo.get_feature_curation_group(
        session, feature_id=identity.feature_id, public_only=True
    )
    if row is None:
        raise HTTPException(status_code=404, detail="feature 없음")
    return FeatureCurationGroupResponse(
        data=_group_view(row),
        meta=make_meta(request, started_at=started_at),
    )


@admin_router.get("", response_model=AdminCurationCollectionsResponse)
async def list_admin_curation_collections(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    status: Annotated[CollectionStatus | None, Query()] = None,
    visibility: Annotated[CollectionVisibility | None, Query()] = None,
    theme_slug: Annotated[str | None, Query()] = None,
    edition_key: Annotated[str | None, Query()] = None,
    provider_dataset_id: Annotated[int | None, Query(gt=0)] = None,
    q: Annotated[str | None, Query()] = None,
    include_archived: Annotated[bool, Query()] = False,
    page_size: Annotated[int, Query(ge=1, le=500)] = 200,
    cursor: Annotated[str | None, Query()] = None,
) -> AdminCurationCollectionsResponse:
    started_at = perf_counter()
    try:
        rows, next_cursor = await curation_repo.list_curation_collections(
            session,
            status=status,
            visibility=visibility,
            theme_slug=theme_slug,
            edition_key=edition_key,
            provider_dataset_id=provider_dataset_id,
            q=q,
            include_archived=include_archived,
            limit=page_size,
            cursor=cursor,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return AdminCurationCollectionsResponse(
        data=AdminCurationCollectionsData(items=[_admin_collection_view(row) for row in rows]),
        meta=make_meta(
            request,
            started_at=started_at,
            page_size=page_size,
            next_cursor=next_cursor,
        ),
    )


@admin_router.get(
    "/{collection_id}",
    response_model=AdminCurationCollectionResponse,
    responses={
        200: {"headers": _ETAG_RESPONSE_HEADER},
        304: {"description": "representation ETag 일치"},
    },
)
async def get_admin_curation_collection(
    request: Request,
    collection_id: UUID,
    response: Response,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AdminCurationCollectionResponse | Response:
    started_at = perf_counter()
    result = await curation_repo.get_curation_collection(
        session, collection_id=str(collection_id), include_archived=True
    )
    if result is None:
        raise HTTPException(status_code=404, detail="curation collection 없음")
    collection, items = result
    result_response = AdminCurationCollectionResponse(
        data=AdminCurationCollectionData(
            collection=_admin_collection_view(collection),
            items=[_admin_item_view(item) for item in items],
        ),
        meta=make_meta(request, started_at=started_at),
    )
    representation_etag = _curation_representation_etag(result_response.data)
    if request.headers.get("if-none-match") == representation_etag:
        return Response(status_code=304, headers={"ETag": representation_etag})
    response.headers["ETag"] = representation_etag
    return result_response


@admin_router.post(
    "",
    response_model=AdminCurationCollectionResponse,
    status_code=201,
    responses={201: {"headers": _ETAG_RESPONSE_HEADER}},
)
@idempotent_domain_command("admin.curation-collection.create")
async def create_admin_curation_collection(
    request: Request,
    body: CurationCollectionCreateRequest,
    response: Response,
    session: Annotated[AsyncSession, Depends(get_session)],
    context: Annotated[AdminProxyContext, Depends(require_admin_frontend)],
) -> AdminCurationCollectionResponse:
    started_at = perf_counter()
    try:
        async with domain_command_transaction(session):
            command = domain_command_service.current_domain_command()
            collection = await curation_repo.create_curation_collection_command(
                session,
                collection_key=body.collection_key,
                theme_id=str(body.theme_id),
                source_id=(str(body.source_id) if body.source_id is not None else None),
                title=body.title,
                edition_key=body.edition_key,
                description=body.description,
                status=body.status,
                visibility=body.visibility,
                metadata=body.metadata,
                command_id=command.command_id,
                principal=command.actor,
            )
    except DBAPIError as exc:
        raise _collection_command_error(exc) from exc
    except IntegrityError as exc:
        raise _conflict(exc) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    result_response = AdminCurationCollectionResponse(
        data=AdminCurationCollectionData(collection=_admin_collection_view(collection), items=[]),
        meta=make_meta(request, started_at=started_at),
    )
    response.headers["ETag"] = _curation_representation_etag(result_response.data)
    return result_response


@admin_router.patch(
    "/{collection_id}",
    response_model=AdminCurationCollectionResponse,
    responses={
        200: {"headers": _ETAG_RESPONSE_HEADER},
        412: {"description": "stale collection If-Match"},
        428: {"description": "If-Match 누락"},
    },
    openapi_extra={"parameters": [_IF_MATCH_OPENAPI_PARAMETER]},
)
@idempotent_domain_command("admin.curation-collection.patch")
async def patch_admin_curation_collection(
    request: Request,
    collection_id: UUID,
    body: CurationCollectionPatchRequest,
    response: Response,
    session: Annotated[AsyncSession, Depends(get_session)],
    context: Annotated[AdminProxyContext, Depends(require_admin_frontend)],
) -> AdminCurationCollectionResponse:
    started_at = perf_counter()
    expected_revision = parse_revision_header(request, "If-Match", required=True)
    assert expected_revision is not None
    try:
        async with domain_command_transaction(session):
            command = domain_command_service.current_domain_command()
            updates = body.model_dump(exclude_unset=True)
            for field in ("theme_id", "source_id"):
                if updates.get(field) is not None:
                    updates[field] = str(updates[field])
            collection = await curation_repo.patch_curation_collection_command(
                session,
                collection_id=str(collection_id),
                updates=updates,
                expected_revision=expected_revision,
                command_id=command.command_id,
                principal=command.actor,
            )
    except DBAPIError as exc:
        raise _collection_command_error(exc) from exc
    except IntegrityError as exc:
        raise _conflict(exc) from exc
    except curation_repo.CurationRevisionConflictError as exc:
        raise HTTPException(status_code=412, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if collection is None:
        raise HTTPException(status_code=404, detail="curation collection 없음")
    result = await curation_repo.get_curation_collection(
        session, collection_id=str(collection_id), include_archived=True
    )
    assert result is not None
    result_response = AdminCurationCollectionResponse(
        data=AdminCurationCollectionData(
            collection=_admin_collection_view(result[0]),
            items=[_admin_item_view(item) for item in result[1]],
        ),
        meta=make_meta(request, started_at=started_at),
    )
    response.headers["ETag"] = _curation_representation_etag(result_response.data)
    return result_response


@admin_router.delete(
    "/{collection_id}",
    response_model=AdminCurationCollectionResponse,
    responses={
        200: {"headers": _ETAG_RESPONSE_HEADER},
        412: {"description": "stale collection If-Match"},
        428: {"description": "If-Match 누락"},
    },
    openapi_extra={"parameters": [_IF_MATCH_OPENAPI_PARAMETER]},
)
@idempotent_domain_command("admin.curation-collection.archive")
async def archive_admin_curation_collection(
    request: Request,
    collection_id: UUID,
    response: Response,
    session: Annotated[AsyncSession, Depends(get_session)],
    context: Annotated[AdminProxyContext, Depends(require_admin_frontend)],
) -> AdminCurationCollectionResponse:
    started_at = perf_counter()
    expected_revision = parse_revision_header(request, "If-Match", required=True)
    assert expected_revision is not None
    try:
        async with domain_command_transaction(session):
            command = domain_command_service.current_domain_command()
            collection = await curation_repo.archive_curation_collection_command(
                session,
                collection_id=str(collection_id),
                expected_revision=expected_revision,
                command_id=command.command_id,
                principal=command.actor,
            )
    except DBAPIError as exc:
        raise _collection_command_error(exc) from exc
    except curation_repo.CurationRevisionConflictError as exc:
        raise HTTPException(status_code=412, detail=str(exc)) from exc
    if collection is None:
        raise HTTPException(status_code=404, detail="curation collection 없음")
    result = await curation_repo.get_curation_collection(
        session, collection_id=str(collection_id), include_archived=True
    )
    assert result is not None
    result_response = AdminCurationCollectionResponse(
        data=AdminCurationCollectionData(
            collection=_admin_collection_view(result[0]),
            items=[_admin_item_view(item) for item in result[1]],
        ),
        meta=make_meta(request, started_at=started_at),
    )
    response.headers["ETag"] = _curation_representation_etag(result_response.data)
    return result_response


@admin_router.post(
    "/{collection_id}/items",
    response_model=AdminCurationItemResponse,
    status_code=201,
    responses={201: {"headers": _ETAG_RESPONSE_HEADER}},
)
@idempotent_domain_command("admin.curation-item.create")
async def add_admin_curation_item(
    request: Request,
    collection_id: UUID,
    body: CurationItemCreateRequest,
    response: Response,
    session: Annotated[AsyncSession, Depends(get_session)],
    context: Annotated[AdminProxyContext, Depends(require_admin_frontend)],
) -> AdminCurationItemResponse:
    started_at = perf_counter()
    payload = body.model_dump()
    # T-VN-32C PR-2 (W6) — 값 전환 후 admin이 복사한 UUID 참조를 legacy 정본
    # 키로 정규화한다 (miss는 원문 유지 — 기존 "active Feature 아님" 422 계약
    # 이 판정).
    if payload.get("feature_id") is not None:
        payload["feature_id"] = await feature_identity.legacy_id_for_filter(
            session, payload["feature_id"]
        )
    try:
        async with domain_command_transaction(session):
            command = domain_command_service.current_domain_command()
            item = await curation_repo.create_curation_item_command(
                session,
                collection_id=str(collection_id),
                command_id=command.command_id,
                principal=command.actor,
                **payload,
            )
    except DBAPIError as exc:
        raise _item_command_error(exc) from exc
    except IntegrityError as exc:
        raise _conflict(exc) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    result_response = AdminCurationItemResponse(
        data=_admin_item_view(item),
        meta=make_meta(request, started_at=started_at),
    )
    response.headers["ETag"] = _curation_representation_etag(result_response.data)
    return result_response


@admin_router.patch(
    "/{collection_id}/items/{curation_item_id}",
    response_model=AdminCurationItemResponse,
    responses={
        200: {"headers": _ETAG_RESPONSE_HEADER},
        412: {"description": "stale item If-Match"},
        428: {"description": "If-Match 누락"},
    },
    openapi_extra={"parameters": [_IF_MATCH_OPENAPI_PARAMETER]},
)
@idempotent_domain_command("admin.curation-item.patch")
async def patch_admin_curation_item(
    request: Request,
    collection_id: UUID,
    curation_item_id: UUID,
    body: CurationItemPatchRequest,
    response: Response,
    session: Annotated[AsyncSession, Depends(get_session)],
    context: Annotated[AdminProxyContext, Depends(require_admin_frontend)],
) -> AdminCurationItemResponse:
    started_at = perf_counter()
    expected_revision = parse_revision_header(request, "If-Match", required=True)
    assert expected_revision is not None
    updates = body.model_dump(exclude_unset=True)
    # T-VN-32C PR-2 (W7) — W6과 동일한 feature 참조 정규화.
    if updates.get("feature_id") is not None:
        updates["feature_id"] = await feature_identity.legacy_id_for_filter(
            session, updates["feature_id"]
        )
    try:
        async with domain_command_transaction(session):
            command = domain_command_service.current_domain_command()
            item = await curation_repo.patch_curation_item_command(
                session,
                collection_id=str(collection_id),
                curation_item_id=str(curation_item_id),
                updates=updates,
                expected_revision=expected_revision,
                command_id=command.command_id,
                principal=command.actor,
            )
    except DBAPIError as exc:
        raise _item_command_error(exc) from exc
    except IntegrityError as exc:
        raise _conflict(exc) from exc
    except curation_repo.CurationRevisionConflictError as exc:
        raise HTTPException(status_code=412, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if item is None:
        raise HTTPException(status_code=404, detail="curation item 없음")
    result_response = AdminCurationItemResponse(
        data=_admin_item_view(item),
        meta=make_meta(request, started_at=started_at),
    )
    response.headers["ETag"] = _curation_representation_etag(result_response.data)
    return result_response


@admin_router.delete(
    "/{collection_id}/items/{curation_item_id}",
    response_model=AdminCurationItemResponse,
    responses={
        200: {"headers": _ETAG_RESPONSE_HEADER},
        412: {"description": "stale item If-Match"},
        428: {"description": "If-Match 누락"},
    },
    openapi_extra={"parameters": [_IF_MATCH_OPENAPI_PARAMETER]},
)
@idempotent_domain_command("admin.curation-item.archive")
async def archive_admin_curation_item(
    request: Request,
    collection_id: UUID,
    curation_item_id: UUID,
    response: Response,
    session: Annotated[AsyncSession, Depends(get_session)],
    context: Annotated[AdminProxyContext, Depends(require_admin_frontend)],
) -> AdminCurationItemResponse:
    started_at = perf_counter()
    expected_revision = parse_revision_header(request, "If-Match", required=True)
    assert expected_revision is not None
    try:
        async with domain_command_transaction(session):
            command = domain_command_service.current_domain_command()
            item = await curation_repo.archive_curation_item_command(
                session,
                collection_id=str(collection_id),
                curation_item_id=str(curation_item_id),
                expected_revision=expected_revision,
                command_id=command.command_id,
                principal=command.actor,
            )
    except DBAPIError as exc:
        raise _item_command_error(exc) from exc
    except curation_repo.CurationRevisionConflictError as exc:
        raise HTTPException(status_code=412, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if item is None:
        raise HTTPException(status_code=404, detail="curation item 없음")
    result_response = AdminCurationItemResponse(
        data=_admin_item_view(item),
        meta=make_meta(request, started_at=started_at),
    )
    response.headers["ETag"] = _curation_representation_etag(result_response.data)
    return result_response
