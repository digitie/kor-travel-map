"""``/admin/issues`` 운영 이슈 검토/조치 라우터 (ADR-046, DA-D-04 / T-212).

``ops.data_integrity_violations`` 큐(정합성/주소 매칭 이슈)를 admin이 조회하고
resolve/ignore/reopen하거나, kraddr-geo REST v2(ADR-046)로 정/역지오코딩을
재시도해 feature 주소·좌표를 덮어쓴다. 목록은 keyset cursor(``ops_repo``),
단건/조치는 ``integrity_violation_repo`` + ``feature_address_repo`` raw SQL을 쓴다.
모든 성공 응답은 ``{data, meta}`` envelope(DA-D-03).

kraddr-geo 호출은 ``_forward_geocode`` / ``_reverse_geocode`` 모듈-레벨 헬퍼 뒤에
둔다 — base URL 미설정 시 503, 단위 테스트는 헬퍼를 monkeypatch한다.
"""

from __future__ import annotations

from datetime import datetime
from time import perf_counter
from typing import Annotated, Any, Literal

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, status
from krtour.map.geocoding import (
    KraddrGeoRestClient,
    geocode_response_to_address,
    geocode_response_to_coordinate,
    reverse_response_to_address,
)
from krtour.map.infra.feature_address_repo import (
    FeatureAddressSnapshot,
    apply_feature_address_override,
    get_feature_address_snapshot,
)
from krtour.map.infra.integrity_violation_repo import (
    DataIntegrityViolation,
    DataIntegrityViolationStateConflict,
    get_data_integrity_violation,
    set_data_integrity_violation_status,
)
from krtour.map.infra.ops_repo import OpsIntegrityIssue, list_ops_integrity_issues
from krtour.map.settings import KrtourMapSettings
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from krtour.map_admin.db import get_session

__all__ = [
    "router",
    "AdminIssueRecord",
    "AdminIssuePatchRequest",
    "AdminIssueListResponse",
    "AdminIssueDetailResponse",
    "AdminIssueActionResponse",
]

router = APIRouter(prefix="/admin/issues", tags=["admin-issues"])

IssueStatus = Literal["open", "acknowledged", "resolved", "ignored"]
IssueSeverity = Literal["info", "warning", "error", "critical"]
IssueAction = Literal[
    "resolve",
    "ignore",
    "reopen",
    "retry_geocode",
    "retry_reverse_geocode",
    "apply_kraddr_geo_address",
    "manual_override",
]

_STATUS_BY_ACTION: dict[str, str] = {
    "resolve": "resolved",
    "ignore": "ignored",
    "reopen": "open",
}


class _KraddrGeoUnavailable(RuntimeError):
    """kraddr-geo base URL이 설정되지 않아 지오코딩을 수행할 수 없을 때."""


# ── envelope 모델 ────────────────────────────────────────────────────────────


class IssueCoordBody(BaseModel):
    """WGS84 좌표. 외부 인터페이스는 lon/lat 순서 (SKILL.md DO NOT #5)."""

    model_config = ConfigDict(extra="forbid")

    lon: float = Field(ge=124.0, le=132.0)
    lat: float = Field(ge=33.0, le=39.5)


class AdminIssueRecord(BaseModel):
    """``ops.data_integrity_violations`` HTTP 표현."""

    model_config = ConfigDict(extra="forbid")

    violation_key: str
    provider: str | None = None
    dataset_key: str | None = None
    source_record_key: str | None = None
    feature_id: str | None = None
    violation_type: str
    severity: str
    message: str
    payload: dict[str, Any]
    status: str
    detected_at: datetime
    resolved_at: datetime | None = None


class AdminIssueFeatureSnapshot(BaseModel):
    """이슈에 연결된 feature 주소/좌표 스냅샷."""

    model_config = ConfigDict(extra="forbid")

    feature_id: str
    lon: float | None = None
    lat: float | None = None
    address: dict[str, Any]
    legal_dong_code: str | None = None
    sido_code: str | None = None
    sigungu_code: str | None = None
    road_address_management_no: str | None = None
    status: str


class AdminIssueListData(BaseModel):
    """이슈 목록 data."""

    model_config = ConfigDict(extra="forbid")

    items: list[AdminIssueRecord]
    next_cursor: str | None = None


class AdminIssueListMeta(BaseModel):
    """이슈 목록 meta."""

    model_config = ConfigDict(extra="forbid")

    count: int
    duration_ms: int


class AdminIssueListResponse(BaseModel):
    """``GET /admin/issues`` 응답 (DA-D-03 envelope)."""

    model_config = ConfigDict(extra="forbid")

    data: AdminIssueListData
    meta: AdminIssueListMeta


class AdminIssueDetailData(BaseModel):
    """이슈 단건 data."""

    model_config = ConfigDict(extra="forbid")

    issue: AdminIssueRecord
    feature: AdminIssueFeatureSnapshot | None = None


class AdminIssueDetailMeta(BaseModel):
    """단건 응답 meta."""

    model_config = ConfigDict(extra="forbid")

    duration_ms: int


class AdminIssueDetailResponse(BaseModel):
    """``GET /admin/issues/{violation_key}`` 응답."""

    model_config = ConfigDict(extra="forbid")

    data: AdminIssueDetailData
    meta: AdminIssueDetailMeta


class AdminIssueActionData(BaseModel):
    """``PATCH /admin/issues/{violation_key}`` data."""

    model_config = ConfigDict(extra="forbid")

    issue: AdminIssueRecord
    feature: AdminIssueFeatureSnapshot | None = None
    geocode_candidate: dict[str, Any] | None = None


class AdminIssueActionResponse(BaseModel):
    """``PATCH /admin/issues/{violation_key}`` 응답."""

    model_config = ConfigDict(extra="forbid")

    data: AdminIssueActionData
    meta: AdminIssueDetailMeta


class AdminIssuePatchRequest(BaseModel):
    """이슈 조치 요청. ``action``에 따라 필요한 필드가 다르다."""

    model_config = ConfigDict(extra="forbid")

    action: IssueAction
    reason: str | None = None
    operator: str | None = None
    address: dict[str, Any] | None = None
    coord: IssueCoordBody | None = None
    legal_dong_code: str | None = None
    sido_code: str | None = None
    sigungu_code: str | None = None
    road_address_management_no: str | None = None
    prevent_provider_reactivation: bool = True


# ── 매퍼 ─────────────────────────────────────────────────────────────────────


def _record(issue: OpsIntegrityIssue | DataIntegrityViolation) -> AdminIssueRecord:
    return AdminIssueRecord(
        violation_key=issue.violation_key,
        provider=issue.provider,
        dataset_key=issue.dataset_key,
        source_record_key=issue.source_record_key,
        feature_id=issue.feature_id,
        violation_type=issue.violation_type,
        severity=issue.severity,
        message=issue.message,
        payload=issue.payload,
        status=issue.status,
        detected_at=issue.detected_at,
        resolved_at=issue.resolved_at,
    )


def _snapshot(row: FeatureAddressSnapshot | None) -> AdminIssueFeatureSnapshot | None:
    if row is None:
        return None
    return AdminIssueFeatureSnapshot(
        feature_id=row.feature_id,
        lon=row.lon,
        lat=row.lat,
        address=row.address,
        legal_dong_code=row.legal_dong_code,
        sido_code=row.sido_code,
        sigungu_code=row.sigungu_code,
        road_address_management_no=row.road_address_management_no,
        status=row.status,
    )


def _elapsed_ms(started_at: float) -> int:
    return max(0, int((perf_counter() - started_at) * 1000))


# ── kraddr-geo 헬퍼 (테스트 monkeypatch 지점) ─────────────────────────────────


def _kraddr_geo_base_url() -> str:
    base_url = KrtourMapSettings().kraddr_geo_base_url
    if base_url is None:
        raise _KraddrGeoUnavailable(
            "kraddr-geo base URL이 설정되지 않아 지오코딩을 수행할 수 없습니다 "
            "(KRTOUR_MAP_KRADDR_GEO_BASE_URL)."
        )
    return base_url


async def _forward_geocode(address: str) -> dict[str, Any] | None:
    """주소 문자열 → kraddr-geo 정지오코딩 candidate dict. 결과 없으면 ``None``."""
    base_url = _kraddr_geo_base_url()
    async with httpx.AsyncClient(base_url=base_url) as http:
        client = KraddrGeoRestClient(http)
        response = await client.geocode(address)
    coordinate = geocode_response_to_coordinate(response)
    addr = geocode_response_to_address(response)
    if coordinate is None and addr is None:
        return None
    return {
        "lon": float(coordinate.lon) if coordinate is not None else None,
        "lat": float(coordinate.lat) if coordinate is not None else None,
        "address": (
            addr.model_dump(mode="json", exclude_none=True)
            if addr is not None
            else None
        ),
        "legal_dong_code": addr.bjd_code if addr is not None else None,
        "sido_code": addr.sido_code if addr is not None else None,
        "sigungu_code": addr.sigungu_code if addr is not None else None,
        "road_address_management_no": (
            addr.road_address_management_no if addr is not None else None
        ),
    }


async def _reverse_geocode(lon: float, lat: float) -> dict[str, Any] | None:
    """좌표 → kraddr-geo 역지오코딩 candidate dict. 결과 없으면 ``None``."""
    base_url = _kraddr_geo_base_url()
    async with httpx.AsyncClient(base_url=base_url) as http:
        client = KraddrGeoRestClient(http)
        response = await client.reverse(x=lon, y=lat)
    addr = reverse_response_to_address(response)
    if addr is None:
        return None
    return {
        "address": addr.model_dump(mode="json", exclude_none=True),
        "legal_dong_code": addr.bjd_code,
        "sido_code": addr.sido_code,
        "sigungu_code": addr.sigungu_code,
        "road_address_management_no": addr.road_address_management_no,
    }


def _geocode_query(
    feature: FeatureAddressSnapshot | None,
    payload: dict[str, Any],
) -> str | None:
    """정지오코딩에 쓸 주소 문자열. feature.address 우선, 없으면 issue.payload."""
    if feature is not None:
        addr = feature.address
        candidate = addr.get("road") or addr.get("legal") or addr.get("admin")
        if isinstance(candidate, str) and candidate.strip():
            return candidate
    for key in (
        "raw_address",
        "road_address",
        "address",
        "parcel_address",
        "jibun_address",
    ):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return None


# ── 엔드포인트 ───────────────────────────────────────────────────────────────


@router.get("", response_model=AdminIssueListResponse)
async def list_admin_issues(
    session: Annotated[AsyncSession, Depends(get_session)],
    issue_status: Annotated[IssueStatus | None, Query(alias="status")] = "open",
    issue_type: Annotated[str | None, Query()] = None,
    provider: Annotated[str | None, Query()] = None,
    dataset_key: Annotated[str | None, Query()] = None,
    severity: Annotated[IssueSeverity | None, Query()] = None,
    feature_id: Annotated[str | None, Query()] = None,
    page_size: Annotated[int, Query(ge=1, le=200)] = 50,
    cursor: Annotated[str | None, Query()] = None,
) -> AdminIssueListResponse:
    """운영 이슈 목록 (keyset cursor).

    ``bbox``/free-text ``q`` 필터는 ``ops_repo``가 지원하지 않아 범위 밖이다
    (deferred — 추후 repo 확장 시 추가).
    """
    started_at = perf_counter()
    try:
        page = await list_ops_integrity_issues(
            session,
            status=issue_status,
            severity=severity,
            violation_type=issue_type,
            provider=provider,
            dataset_key=dataset_key,
            feature_id=feature_id,
            limit=page_size,
            cursor=cursor,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return AdminIssueListResponse(
        data=AdminIssueListData(
            items=[_record(item) for item in page.items],
            next_cursor=page.next_cursor,
        ),
        meta=AdminIssueListMeta(
            count=len(page.items),
            duration_ms=_elapsed_ms(started_at),
        ),
    )


@router.get(
    "/{violation_key}",
    response_model=AdminIssueDetailResponse,
    responses={404: {"description": "이슈 없음"}},
)
async def get_admin_issue(
    violation_key: str,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AdminIssueDetailResponse:
    """운영 이슈 단건 + 연결 feature 주소/좌표 스냅샷."""
    started_at = perf_counter()
    issue = await get_data_integrity_violation(session, violation_key)
    if issue is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"이슈 없음: {violation_key}",
        )
    feature = (
        await get_feature_address_snapshot(session, issue.feature_id)
        if issue.feature_id is not None
        else None
    )
    return AdminIssueDetailResponse(
        data=AdminIssueDetailData(
            issue=_record(issue),
            feature=_snapshot(feature),
        ),
        meta=AdminIssueDetailMeta(duration_ms=_elapsed_ms(started_at)),
    )


def _require_feature_id(issue: DataIntegrityViolation) -> str:
    if issue.feature_id is None:
        raise HTTPException(
            status_code=422,
            detail="issue has no linked feature",
        )
    return issue.feature_id


def _resolution_payload(action: str, body: AdminIssuePatchRequest) -> dict[str, Any]:
    return {"action": action, "operator": body.operator, "reason": body.reason}


@router.patch(
    "/{violation_key}",
    response_model=AdminIssueActionResponse,
    responses={
        404: {"description": "이슈/feature 없음"},
        409: {"description": "상태 전이 충돌"},
        503: {"description": "kraddr-geo 미설정"},
    },
)
async def patch_admin_issue(
    violation_key: str,
    body: AdminIssuePatchRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AdminIssueActionResponse:
    """이슈 상태 전이 + kraddr-geo 재지오코딩/주소 덮어쓰기."""
    started_at = perf_counter()
    issue = await get_data_integrity_violation(session, violation_key)
    if issue is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"이슈 없음: {violation_key}",
        )
    try:
        return await _dispatch_action(
            session,
            violation_key=violation_key,
            issue=issue,
            body=body,
            started_at=started_at,
        )
    except _KraddrGeoUnavailable as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"kraddr-geo 호출 실패: {exc}",
        ) from exc
    except DataIntegrityViolationStateConflict as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


async def _dispatch_action(
    session: AsyncSession,
    *,
    violation_key: str,
    issue: DataIntegrityViolation,
    body: AdminIssuePatchRequest,
    started_at: float,
) -> AdminIssueActionResponse:
    action = body.action

    if action in _STATUS_BY_ACTION:
        target_status = _STATUS_BY_ACTION[action]
        async with session.begin():
            updated = await set_data_integrity_violation_status(
                session,
                violation_key,
                status=target_status,
                resolution_payload=_resolution_payload(action, body),
            )
        if updated is None:
            raise HTTPException(status_code=404, detail=f"이슈 없음: {violation_key}")
        return _action_response(updated, feature=None, candidate=None, started_at=started_at)

    if action == "retry_geocode":
        feature = (
            await get_feature_address_snapshot(session, issue.feature_id)
            if issue.feature_id is not None
            else None
        )
        query = _geocode_query(feature, issue.payload)
        if query is None:
            raise HTTPException(
                status_code=422,
                detail="정지오코딩에 사용할 주소 문자열을 찾을 수 없습니다.",
            )
        candidate = await _forward_geocode(query)
        return _action_response(
            issue, feature=feature, candidate=candidate, started_at=started_at
        )

    if action == "retry_reverse_geocode":
        feature_id = _require_feature_id(issue)
        feature = await get_feature_address_snapshot(session, feature_id)
        if feature is None or feature.lon is None or feature.lat is None:
            raise HTTPException(
                status_code=422,
                detail="feature 좌표가 없어 역지오코딩을 수행할 수 없습니다.",
            )
        candidate = await _reverse_geocode(feature.lon, feature.lat)
        return _action_response(
            issue, feature=feature, candidate=candidate, started_at=started_at
        )

    if action == "apply_kraddr_geo_address":
        feature_id = _require_feature_id(issue)
        feature = await get_feature_address_snapshot(session, feature_id)
        if feature is None or feature.lon is None or feature.lat is None:
            raise HTTPException(
                status_code=422,
                detail="feature 좌표가 없어 역지오코딩을 수행할 수 없습니다.",
            )
        candidate = await _reverse_geocode(feature.lon, feature.lat)
        if candidate is None:
            raise HTTPException(
                status_code=422,
                detail="kraddr-geo 역지오코딩 결과가 없어 적용할 수 없습니다.",
            )
        async with session.begin():
            result = await apply_feature_address_override(
                session,
                feature_id,
                address=candidate.get("address"),
                legal_dong_code=candidate.get("legal_dong_code"),
                sido_code=candidate.get("sido_code"),
                sigungu_code=candidate.get("sigungu_code"),
                road_address_management_no=candidate.get("road_address_management_no"),
                reason=body.reason,
                operator=body.operator,
                prevent_provider_reactivation=body.prevent_provider_reactivation,
            )
            if result is None:
                raise HTTPException(
                    status_code=404, detail=f"feature 없음: {feature_id}"
                )
            updated = await set_data_integrity_violation_status(
                session,
                violation_key,
                status="resolved",
                resolution_payload=_resolution_payload(action, body),
            )
        if updated is None:
            raise HTTPException(status_code=404, detail=f"이슈 없음: {violation_key}")
        return _action_response(
            updated,
            feature=result.snapshot,
            candidate=candidate,
            started_at=started_at,
        )

    # manual_override
    feature_id = _require_feature_id(issue)
    has_fields = (
        body.address is not None
        or body.coord is not None
        or body.legal_dong_code is not None
        or body.sido_code is not None
        or body.sigungu_code is not None
        or body.road_address_management_no is not None
    )
    if not has_fields:
        raise HTTPException(
            status_code=422,
            detail="manual_override는 address/coord/행정코드 중 최소 1개가 필요합니다.",
        )
    async with session.begin():
        result = await apply_feature_address_override(
            session,
            feature_id,
            address=body.address,
            lon=body.coord.lon if body.coord is not None else None,
            lat=body.coord.lat if body.coord is not None else None,
            legal_dong_code=body.legal_dong_code,
            sido_code=body.sido_code,
            sigungu_code=body.sigungu_code,
            road_address_management_no=body.road_address_management_no,
            reason=body.reason,
            operator=body.operator,
            prevent_provider_reactivation=body.prevent_provider_reactivation,
        )
        if result is None:
            raise HTTPException(status_code=404, detail=f"feature 없음: {feature_id}")
        updated = await set_data_integrity_violation_status(
            session,
            violation_key,
            status="resolved",
            resolution_payload=_resolution_payload(action, body),
        )
    if updated is None:
        raise HTTPException(status_code=404, detail=f"이슈 없음: {violation_key}")
    return _action_response(
        updated, feature=result.snapshot, candidate=None, started_at=started_at
    )


def _action_response(
    issue: OpsIntegrityIssue | DataIntegrityViolation,
    *,
    feature: FeatureAddressSnapshot | None,
    candidate: dict[str, Any] | None,
    started_at: float,
) -> AdminIssueActionResponse:
    return AdminIssueActionResponse(
        data=AdminIssueActionData(
            issue=_record(issue),
            feature=_snapshot(feature),
            geocode_candidate=candidate,
        ),
        meta=AdminIssueDetailMeta(duration_ms=_elapsed_ms(started_at)),
    )
