"""PinVi 전용 admin Feature 읽기: 기존 endpoint/DTO/query를 그대로 공유한다."""

from fastapi import APIRouter, Depends

from kortravelmap.api.auth import require_pinvi_admin_features_read_service_principal
from kortravelmap.api.routers.admin_features import (
    AdminFeatureDetailResponse,
    AdminFeaturesListResponse,
    get_feature_detail_route,
    list_features,
)

service_router = APIRouter(
    prefix="/service/admin-features",
    tags=["service-admin-features"],
    dependencies=[Depends(require_pinvi_admin_features_read_service_principal)],
)
service_router.add_api_route(
    "",
    list_features,
    methods=["GET"],
    response_model=AdminFeaturesListResponse,
    operation_id="service_admin_features_list",
    description="pinvi:admin-features:read 전용. 기존 admin Feature 필터와 DTO를 공유한다.",
)
service_router.add_api_route(
    "/{feature_id}",
    get_feature_detail_route,
    methods=["GET"],
    response_model=AdminFeatureDetailResponse,
    operation_id="service_admin_features_detail",
    description="pinvi:admin-features:read 전용. 기존 alias 해석과 전체 admin DTO를 공유한다.",
)
