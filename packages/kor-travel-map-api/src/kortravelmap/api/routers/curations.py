"""큐레이션 collection/item REST API."""

from __future__ import annotations

import csv
import io
from collections.abc import Mapping, Sequence
from datetime import datetime
from time import perf_counter
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import Response
from kortravelmap.curation_import import (
    CURATION_CSV_HEADERS,
    CURATION_CSV_MAX_BYTES,
    CURATION_INTEGER_MAX,
    CurationImportIssue,
    CurationImportRow,
    parse_curation_csv,
)
from kortravelmap.infra import curation_repo
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from kortravelmap.api.auth import AdminProxyContext, require_admin_frontend
from kortravelmap.api.db import get_session
from kortravelmap.api.response import Meta, make_meta

__all__ = ["admin_router", "router"]

router = APIRouter(prefix="/curations", tags=["curations"])
admin_router = APIRouter(prefix="/admin/curations", tags=["admin-curations"])

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


class PublicCurationCollectionView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    collection_id: UUID
    collection_key: str
    theme_id: UUID
    theme_slug: str
    theme_name: str
    theme_group: str
    source_id: UUID | None
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
    status: str


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
    theme_id: UUID | None = None
    theme_slug: str | None = Field(default=None, min_length=1, max_length=200)
    theme_name: str | None = Field(default=None, min_length=1, max_length=300)
    theme_group: str | None = Field(default=None, min_length=1, max_length=200)
    source_id: UUID | None = None
    title: str = Field(min_length=1, max_length=300)
    edition_key: str = Field(default="", max_length=100)
    description: str | None = None
    status: ActiveCollectionStatus = "draft"
    visibility: CollectionVisibility = "admin_only"
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _theme_reference_or_definition(self) -> CurationCollectionCreateRequest:
        if self.theme_id:
            return self
        if self.theme_slug and self.theme_name and self.theme_group:
            return self
        raise ValueError("theme_id 또는 theme_slug/theme_name/theme_group 전체가 필요합니다.")


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


ImportRowStatus = Literal["valid", "invalid", "unmatched", "ambiguous", "imported"]


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
    rows_total: int
    valid_rows: int
    invalid_rows: int
    unresolved_rows: int
    inserted: int
    updated: int
    removed: int
    collections: int
    removals: list[AdminCurationItemView]
    items: list[CurationImportRowView]
    issues: list[CurationImportIssueView]


class CurationImportResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    data: CurationImportData
    meta: Meta


def _public_collection_view(
    row: curation_repo.CurationCollection,
) -> PublicCurationCollectionView:
    view = PublicCurationCollectionView.model_validate(row, from_attributes=True)
    return view.model_copy(update={"item_count": row.public_item_count})


def _admin_collection_view(
    row: curation_repo.CurationCollection,
) -> AdminCurationCollectionView:
    return AdminCurationCollectionView.model_validate(row, from_attributes=True)


def _public_item_view(row: curation_repo.CurationItem) -> PublicCurationItemView:
    return PublicCurationItemView.model_validate(row, from_attributes=True)


def _admin_item_view(row: curation_repo.CurationItem) -> AdminCurationItemView:
    return AdminCurationItemView.model_validate(row, from_attributes=True)


def _group_view(
    row: curation_repo.FeatureCurationGroup,
) -> FeatureCurationGroupView:
    return FeatureCurationGroupView(
        feature=CurationFeatureView(
            feature_id=row.feature_id,
            name=row.name,
            kind=row.kind,
            category=row.category,
            lon=row.lon,
            lat=row.lat,
            address=row.address,
            status=row.status,
        ),
        curations=[_public_item_view(item) for item in row.curations],
        curation_count=len(row.curations),
    )


def _conflict(exc: IntegrityError) -> HTTPException:
    return HTTPException(status_code=409, detail="curation constraint violation")


def _issue_view(issue: CurationImportIssue) -> CurationImportIssueView:
    return CurationImportIssueView.model_validate(issue, from_attributes=True)


def _candidate_view(
    match: curation_repo.FeatureMatch,
) -> CurationImportFeatureCandidateView:
    return CurationImportFeatureCandidateView.model_validate(match, from_attributes=True)


def _adopted_match(
    row: CurationImportRow,
    matches: Sequence[curation_repo.FeatureMatch],
) -> curation_repo.FeatureMatch | None:
    """이 행이 실제로 링크할 feature를 고른다. **CSV가 지정한 경우에만 링크한다** (T-VN-H36).

    이전에는 ``matches[0] if len(matches) == 1 else None``이었다. 그 규칙은 CSV
    ``feature_id``가 비었을 때 리졸버가 **이름 단독**으로 찾아온 후보(
    ``_RESOLVE_FEATURES_BATCH_SQL``의 ``lower(f.name) = lower(place_name)`` 브랜치)를
    "유일하니 맞겠지"라며 그대로 채택했다. 유일성은 *동명 feature가 하나뿐*이라는 뜻이지
    *그게 맞는 장소*라는 뜻이 아니다.

    실제로 그 구멍으로 오링크가 들어왔다: 한국관광100선 "남이섬"이 서울 중구의 동명 업소
    feature에, "청남대"가 전남 영암 시설에 붙었다(T-VN-H33이 해제). prod에 그 이름의 live
    feature가 각각 하나뿐이라 항상 "유일 매칭"으로 통과했다. 그리고 T-VN-H33이 끊어 놓아도
    다음 import가 같은 경로로 되살렸다.

    그래서 **CSV ``feature_id``가 빈 행은 후보 수와 무관하게 링크하지 않는다.** 리졸버가
    찾은 후보는 버리지 않고 ``candidates``로 계속 노출하므로, 운영자가 preview에서 보고
    admin에서 직접 링크할 수 있다. 자동으로 붙는 일만 없어진다.

    CSV가 ``feature_id``를 명시한 행은 그대로다 — 그건 사람이 적어 넣은 값이고
    리졸버도 PK 조회 브랜치를 탄다.
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
    row_region = str((row.metadata_json or {}).get("region") or "").strip()

    if not matches:
        return CurationImportIssueView(
            code="unmatched",
            message="기존 Feature와 일치하는 후보가 없어 미연결 항목으로 저장합니다.",
            row_number=row.row_number,
        )

    if (row.feature_id or "").strip():
        # feature_id를 지정했는데도 안 붙었다면 후보가 여럿인 경우뿐이다.
        return CurationImportIssueView(
            code="ambiguous",
            message="기존 Feature 후보가 여러 개여서 미연결 항목으로 저장합니다.",
            row_number=row.row_number,
        )

    where = ", ".join(
        sorted({s for s in (_sido_name(m.address) for m in matches[:3]) if s})
    )
    detail = f" 후보 소재: {where}." if where else ""
    differs = bool(row_region) and bool(where) and row_region not in where
    mismatch = f" CSV의 region은 '{row_region}'입니다." if differs else ""
    return CurationImportIssueView(
        code="name_only_match",
        message=(
            f"이름만 일치하는 후보 {len(matches)}건을 찾았으나 자동 링크하지 않았습니다 — "
            f"동명이 하나뿐이라는 것이 같은 장소라는 뜻은 아닙니다 (T-VN-H36)."
            f"{detail}{mismatch}"
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


@admin_router.post("/import", response_model=CurationImportResponse)
async def import_admin_curations(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    context: Annotated[AdminProxyContext, Depends(require_admin_frontend)],
    file: Annotated[UploadFile, File(description="UTF-8 CSV 파일")],
    dry_run: Annotated[bool, Query()] = True,
) -> CurationImportResponse:
    """CSV를 preview하거나 오류 없는 전체 파일을 원자적으로 멱등 반영한다."""
    started_at = perf_counter()
    content = await file.read(CURATION_CSV_MAX_BYTES + 1)
    preview = parse_curation_csv(content)
    matches_by_row = await curation_repo.resolve_feature_matches(
        session,
        requests=tuple(
            curation_repo.FeatureMatchRequest(
                row_number=row.row_number,
                feature_id=row.feature_id or None,
                place_name=row.place_name or None,
                address_hint=row.address_hint or None,
            )
            for row in preview.rows
            if row.status == "valid"
        ),
    )
    item_views: list[CurationImportRowView] = []
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
            row_status = "unmatched" if not matches else "ambiguous"
            row_issues = [_unlinked_issue(row, matches)]
        resolved_rows.append(
            curation_repo.ResolvedCurationImportRow(
                row_number=row.row_number,
                collection_key=row.collection_key,
                theme_slug=row.theme_slug,
                theme_name=row.theme_name,
                theme_group=row.theme_group,
                title=row.title,
                edition_key=row.edition_key,
                provider=row.provider,
                dataset_key=row.dataset_key,
                source_name=row.source_name,
                source_url=row.source_url or None,
                source_item_key=row.source_item_key,
                source_component_key=row.source_component_key,
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
                requested_feature_id=row.feature_id,
                resolved_feature_id=match.feature_id if match is not None else None,
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
    if not dry_run and has_errors:
        raise HTTPException(
            status_code=422,
            detail="CSV에 형식 또는 해소 후 identity 오류가 있어 전체 반영을 취소했습니다.",
        )

    change_plan = curation_repo.CurationImportPlan(
        collections=0, inserted=0, updated=0, removals=()
    )
    try:
        if not has_errors:
            change_plan = await curation_repo.preview_curation_import(
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
        }
        if not dry_run:
            result = await curation_repo.import_curation_rows(
                session, rows=resolved_rows, actor=context.actor
            )
            await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise _conflict(exc) from exc
    except ValueError as exc:
        await session.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    invalid_rows = sum(item.status == "invalid" for item in item_views)
    valid_rows = sum(item.status != "invalid" for item in item_views)
    unresolved_rows = sum(item.status in {"unmatched", "ambiguous"} for item in item_views)
    return CurationImportResponse(
        data=CurationImportData(
            dry_run=dry_run,
            rows_total=preview.rows_total,
            valid_rows=valid_rows,
            invalid_rows=invalid_rows,
            unresolved_rows=unresolved_rows,
            inserted=int(result["inserted"]),
            updated=int(result["updated"]),
            removed=int(result["removed"]),
            collections=int(result["collections"]),
            removals=[_admin_item_view(item) for item in result["removals"]],
            items=item_views,
            issues=[_issue_view(issue) for issue in preview.issues]
            + [issue for row_issues in identity_issues_by_row.values() for issue in row_issues],
        ),
        meta=make_meta(request, started_at=started_at),
    )


@router.get("", response_model=FeatureCurationGroupsResponse)
async def list_public_curation_groups(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    theme_slug: Annotated[str | None, Query()] = None,
    edition_key: Annotated[str | None, Query()] = None,
    provider: Annotated[str | None, Query()] = None,
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
            provider=provider,
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
    provider: Annotated[str | None, Query()] = None,
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
            provider=provider,
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
    row = await curation_repo.get_feature_curation_group(
        session, feature_id=feature_id, public_only=True
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
    provider: Annotated[str | None, Query()] = None,
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
            provider=provider,
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


@admin_router.get("/{collection_id}", response_model=AdminCurationCollectionResponse)
async def get_admin_curation_collection(
    request: Request,
    collection_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AdminCurationCollectionResponse:
    started_at = perf_counter()
    result = await curation_repo.get_curation_collection(
        session, collection_id=str(collection_id), include_archived=True
    )
    if result is None:
        raise HTTPException(status_code=404, detail="curation collection 없음")
    collection, items = result
    return AdminCurationCollectionResponse(
        data=AdminCurationCollectionData(
            collection=_admin_collection_view(collection),
            items=[_admin_item_view(item) for item in items],
        ),
        meta=make_meta(request, started_at=started_at),
    )


@admin_router.post("", response_model=AdminCurationCollectionResponse, status_code=201)
async def create_admin_curation_collection(
    request: Request,
    body: CurationCollectionCreateRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
    context: Annotated[AdminProxyContext, Depends(require_admin_frontend)],
) -> AdminCurationCollectionResponse:
    started_at = perf_counter()
    try:
        async with session.begin():
            theme_id: str
            if body.theme_id is None:
                assert body.theme_slug is not None
                assert body.theme_name is not None
                assert body.theme_group is not None
                theme_id = await curation_repo.upsert_curation_theme(
                    session,
                    theme_slug=body.theme_slug,
                    theme_name=body.theme_name,
                    theme_group=body.theme_group,
                )
            else:
                theme_id = str(body.theme_id)
            collection = await curation_repo.create_curation_collection(
                session,
                collection_key=body.collection_key,
                theme_id=theme_id,
                source_id=(str(body.source_id) if body.source_id is not None else None),
                title=body.title,
                edition_key=body.edition_key,
                description=body.description,
                status=body.status,
                visibility=body.visibility,
                metadata=body.metadata,
                actor=context.actor,
            )
    except IntegrityError as exc:
        raise _conflict(exc) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return AdminCurationCollectionResponse(
        data=AdminCurationCollectionData(collection=_admin_collection_view(collection), items=[]),
        meta=make_meta(request, started_at=started_at),
    )


@admin_router.patch("/{collection_id}", response_model=AdminCurationCollectionResponse)
async def patch_admin_curation_collection(
    request: Request,
    collection_id: UUID,
    body: CurationCollectionPatchRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
    context: Annotated[AdminProxyContext, Depends(require_admin_frontend)],
) -> AdminCurationCollectionResponse:
    started_at = perf_counter()
    try:
        async with session.begin():
            updates = body.model_dump(exclude_unset=True)
            for field in ("theme_id", "source_id"):
                if updates.get(field) is not None:
                    updates[field] = str(updates[field])
            collection = await curation_repo.update_curation_collection(
                session,
                collection_id=str(collection_id),
                updates={
                    **updates,
                    "updated_by": context.actor,
                },
            )
    except IntegrityError as exc:
        raise _conflict(exc) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if collection is None:
        raise HTTPException(status_code=404, detail="curation collection 없음")
    result = await curation_repo.get_curation_collection(
        session, collection_id=str(collection_id), include_archived=True
    )
    assert result is not None
    return AdminCurationCollectionResponse(
        data=AdminCurationCollectionData(
            collection=_admin_collection_view(result[0]),
            items=[_admin_item_view(item) for item in result[1]],
        ),
        meta=make_meta(request, started_at=started_at),
    )


@admin_router.delete("/{collection_id}", response_model=AdminCurationCollectionResponse)
async def archive_admin_curation_collection(
    request: Request,
    collection_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    context: Annotated[AdminProxyContext, Depends(require_admin_frontend)],
) -> AdminCurationCollectionResponse:
    started_at = perf_counter()
    async with session.begin():
        collection = await curation_repo.archive_curation_collection(
            session, collection_id=str(collection_id), actor=context.actor
        )
    if collection is None:
        raise HTTPException(status_code=404, detail="curation collection 없음")
    result = await curation_repo.get_curation_collection(
        session, collection_id=str(collection_id), include_archived=True
    )
    assert result is not None
    return AdminCurationCollectionResponse(
        data=AdminCurationCollectionData(
            collection=_admin_collection_view(result[0]),
            items=[_admin_item_view(item) for item in result[1]],
        ),
        meta=make_meta(request, started_at=started_at),
    )


@admin_router.post(
    "/{collection_id}/items",
    response_model=AdminCurationItemResponse,
    status_code=201,
)
async def add_admin_curation_item(
    request: Request,
    collection_id: UUID,
    body: CurationItemCreateRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
    context: Annotated[AdminProxyContext, Depends(require_admin_frontend)],
) -> AdminCurationItemResponse:
    started_at = perf_counter()
    try:
        async with session.begin():
            item, inserted = await curation_repo.add_curation_item(
                session,
                collection_id=str(collection_id),
                actor=context.actor,
                **body.model_dump(),
            )
            if not inserted:
                raise HTTPException(
                    status_code=409,
                    detail="같은 identity의 active curation item이 이미 있습니다.",
                )
    except IntegrityError as exc:
        raise _conflict(exc) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return AdminCurationItemResponse(
        data=_admin_item_view(item),
        meta=make_meta(request, started_at=started_at),
    )


@admin_router.patch(
    "/{collection_id}/items/{curation_item_id}",
    response_model=AdminCurationItemResponse,
)
async def patch_admin_curation_item(
    request: Request,
    collection_id: UUID,
    curation_item_id: UUID,
    body: CurationItemPatchRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
    context: Annotated[AdminProxyContext, Depends(require_admin_frontend)],
) -> AdminCurationItemResponse:
    started_at = perf_counter()
    try:
        async with session.begin():
            item = await curation_repo.update_curation_item(
                session,
                collection_id=str(collection_id),
                curation_item_id=str(curation_item_id),
                updates=body.model_dump(exclude_unset=True),
                actor=context.actor,
            )
    except IntegrityError as exc:
        raise _conflict(exc) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if item is None:
        raise HTTPException(status_code=404, detail="curation item 없음")
    return AdminCurationItemResponse(
        data=_admin_item_view(item),
        meta=make_meta(request, started_at=started_at),
    )


@admin_router.delete(
    "/{collection_id}/items/{curation_item_id}",
    response_model=AdminCurationItemResponse,
)
async def archive_admin_curation_item(
    request: Request,
    collection_id: UUID,
    curation_item_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    context: Annotated[AdminProxyContext, Depends(require_admin_frontend)],
) -> AdminCurationItemResponse:
    started_at = perf_counter()
    try:
        async with session.begin():
            item = await curation_repo.archive_curation_item(
                session,
                collection_id=str(collection_id),
                curation_item_id=str(curation_item_id),
                actor=context.actor,
            )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if item is None:
        raise HTTPException(status_code=404, detail="curation item 없음")
    return AdminCurationItemResponse(
        data=_admin_item_view(item),
        meta=make_meta(request, started_at=started_at),
    )
