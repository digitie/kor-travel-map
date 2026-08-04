"""``kortravelmap.api.route_policy`` — ADR-066 D-1 route policy matrix.

모든 HTTP route와 WebSocket을 ``public-unauthenticated`` / ``public-keyed`` /
``service`` / ``operator`` / ``debug`` / ``metrics`` 중 정확히 하나로 분류하는
**명시적 in-code registry**와, 조립된 FastAPI app을 걸어 다니며 matrix를
데이터로 생성하는 생성기를 둔다 (ADR-066 결정 1).

- 분류 원천은 registry다 — 현재 dependency 배선에서 정책을 **추론하지 않는다**.
  route를 추가하고 registry에 분류를 넣지 않으면 앱 구성 검사(``create_app``)와
  CI(pytest)가 함께 실패한다.
- 배선 검증(``assert_route_policy_wiring``)은 route별로 관측된 enforcing
  dependency가 정책과 일치하는지 확인한다. 다른 task가 소유한 알려진
  배선≠정책 gap은 ``KNOWN_WIRING_EXCEPTIONS`` ledger에 소유 task와 함께
  명시하며, 해당 task가 gap을 닫으면 stale entry가 CI에서 실패해 ledger가
  줄어들도록 강제한다.
- WebSocket ``/v1/ops/live``는 #725의 HMAC ticket dependency
  (``authenticate_ops_live_websocket``)를 enforcing dependency로 기록한다 —
  인증을 중복 구현하지 않는다 (ADR-066 결정 4·ADR-064 유지).

FastAPI 버전 견고성
-------------------
FastAPI 0.136+는 ``include_router`` 결과를 lazy ``_IncludedRouter``로
``app.routes``에 둔다. 본 모듈은 내부 클래스를 직접 순회하지 않고, OpenAPI
생성기가 쓰는 공개 평탄화 helper ``fastapi.routing.iter_route_contexts``로
route를 해석한다(WebSocket은 OpenAPI paths에 나타나지 않으므로 ``openapi()``
기반 열거는 불충분하다). helper가 없는 구버전(<0.136)은 ``app.router.routes``
가 이미 구체 route라 그대로 순회한다.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from fastapi.routing import APIWebSocketRoute
from starlette.routing import WebSocketRoute

from kortravelmap.api.auth import (
    require_admin_frontend,
    require_cache_target_service_principal,
    require_metrics_token,
    require_ops_operator,
    require_public_api_key,
    require_service_token,
)
from kortravelmap.api.ops_live_auth import authenticate_ops_live_websocket

if TYPE_CHECKING:
    from fastapi import FastAPI

__all__ = [
    "KNOWN_WIRING_EXCEPTIONS",
    "ROUTE_POLICIES",
    "RoutePolicy",
    "RoutePolicyError",
    "RoutePolicyMatrixRow",
    "WiringException",
    "assert_route_policy_wiring",
    "assert_routes_classified",
    "build_route_policy_matrix",
]


class RoutePolicy(StrEnum):
    """ADR-066 결정 1의 6개 route 정책."""

    PUBLIC_UNAUTHENTICATED = "public-unauthenticated"
    PUBLIC_KEYED = "public-keyed"
    SERVICE = "service"
    OPERATOR = "operator"
    DEBUG = "debug"
    METRICS = "metrics"


class RoutePolicyError(RuntimeError):
    """미분류 route 또는 정책-배선 불일치 (ADR-066 fail-closed)."""


#: 관측 가능한 enforcing dependency — dependency callable identity로만 판정한다.
_ENFORCEMENT_BY_CALLABLE: dict[Callable[..., Any], str] = {
    require_cache_target_service_principal: "require_cache_target_service_principal",
    require_public_api_key: "require_public_api_key",
    require_service_token: "require_service_token",
    require_admin_frontend: "require_admin_frontend",
    require_ops_operator: "require_ops_operator",
    require_metrics_token: "require_metrics_token",
    # #725 ops-live HMAC ticket — WebSocket의 enforcing dependency (재사용).
    authenticate_ops_live_websocket: "authenticate_ops_live_websocket",
}

_OPERATOR_ENFORCEMENTS = frozenset(
    {
        "require_admin_frontend",
        "require_ops_operator",
        "authenticate_ops_live_websocket",
    }
)


@dataclass(frozen=True, slots=True)
class RoutePolicyMatrixRow:
    """route policy matrix 1행 — route, methods, 정책, 관측된 enforcement."""

    path: str
    schema_path: str
    methods: tuple[str, ...]
    is_websocket: bool
    include_in_schema: bool
    policy: RoutePolicy
    observed_enforcement: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class WiringException:
    """다른 task가 소유한 알려진 배선≠정책 gap (ledger entry).

    소유 task가 gap을 닫으면 이 entry는 stale이 되어
    ``assert_route_policy_wiring``이 제거를 강제한다.
    """

    path: str
    owner: str
    note: str


# ---------------------------------------------------------------------------
# Route policy registry — 분류의 단일 정본 (경로 → 정책).
#
# 경로는 FastAPI route.path 문자열과 정확히 일치해야 한다. 새 route는 여기에
# 분류를 추가하지 않으면 create_app과 CI가 실패한다. `/metrics`는 경로가
# settings(`prometheus_metrics_path`)로 정해지므로 registry가 아니라
# ``build_route_policy_matrix``가 settings에서 동적으로 편입한다.
# ---------------------------------------------------------------------------

ROUTE_POLICIES: dict[str, RoutePolicy] = {
    # -- public-unauthenticated — liveness/version (ADR-066 결정 1)만. D-1의
    #    "public-unauthenticated=(liveness/version)"을 넓히지 않는다.
    #    ``/openapi.json``은 저장소에 export/commit되는 기계 판독 공개 계약
    #    (ADR-031)이라 비밀이 아니고 모든 profile에서 유지한다.
    "/health": RoutePolicy.PUBLIC_UNAUTHENTICATED,
    "/version": RoutePolicy.PUBLIC_UNAUTHENTICATED,
    "/openapi.json": RoutePolicy.PUBLIC_UNAUTHENTICATED,
    # -- debug — 인증 없는 interactive docs UI. production에서 내린다
    #    (app.py의 ``docs_url``/``redoc_url``=None). debug policy의 enforcing
    #    경계는 dependency가 아니라 production-off이며 ``/v1/debug/*``와 같다.
    "/docs": RoutePolicy.DEBUG,
    "/docs/oauth2-redirect": RoutePolicy.DEBUG,
    "/redoc": RoutePolicy.DEBUG,
    # -- public-keyed — 공개 REST read (VWorld 호환 public API key).
    "/v1/categories": RoutePolicy.PUBLIC_KEYED,
    "/v1/curations": RoutePolicy.PUBLIC_KEYED,
    "/v1/curations/collections": RoutePolicy.PUBLIC_KEYED,
    "/v1/curations/collections/{collection_id}": RoutePolicy.PUBLIC_KEYED,
    "/v1/curations/features/{feature_id}": RoutePolicy.PUBLIC_KEYED,
    "/v1/features": RoutePolicy.PUBLIC_KEYED,
    "/v1/features/in-bounds": RoutePolicy.PUBLIC_KEYED,
    "/v1/features/nearby": RoutePolicy.PUBLIC_KEYED,
    "/v1/features/nearby/by-target": RoutePolicy.PUBLIC_KEYED,
    "/v1/features/search": RoutePolicy.PUBLIC_KEYED,
    "/v1/features/weather/alerts": RoutePolicy.PUBLIC_KEYED,
    "/v1/features/weather/forecast": RoutePolicy.PUBLIC_KEYED,
    "/v1/features/{feature_id}": RoutePolicy.PUBLIC_KEYED,
    "/v1/features/{feature_id}/contained-features": RoutePolicy.PUBLIC_KEYED,
    "/v1/features/{feature_id}/price": RoutePolicy.PUBLIC_KEYED,
    "/v1/features/{feature_id}/weather": RoutePolicy.PUBLIC_KEYED,
    "/v1/features/{feature_id}/weather/forecast": RoutePolicy.PUBLIC_KEYED,
    "/v1/providers": RoutePolicy.PUBLIC_KEYED,
    "/v1/providers/{provider}/last-sync": RoutePolicy.PUBLIC_KEYED,
    "/v1/public/beaches": RoutePolicy.PUBLIC_KEYED,
    "/v1/public/beaches/map-markers": RoutePolicy.PUBLIC_KEYED,
    "/v1/public/beaches/{feature_id}": RoutePolicy.PUBLIC_KEYED,
    "/v1/public/festivals/map-markers": RoutePolicy.PUBLIC_KEYED,
    "/v1/public/festivals/monthly": RoutePolicy.PUBLIC_KEYED,
    "/v1/public/festivals/{feature_id}": RoutePolicy.PUBLIC_KEYED,
    # curated 공개 read도 다른 public read와 같은 public-keyed 경계다.
    "/v1/curated-features": RoutePolicy.PUBLIC_KEYED,
    "/v1/curated-features/{curated_feature_id}": RoutePolicy.PUBLIC_KEYED,
    "/v1/curated-sources": RoutePolicy.PUBLIC_KEYED,
    "/v1/curated-themes": RoutePolicy.PUBLIC_KEYED,
    # -- service — service-to-service surface (X-Kor-Travel-Map-Service-Token).
    "/v1/features/batch": RoutePolicy.SERVICE,
    "/v1/features/weather/batch": RoutePolicy.SERVICE,
    "/v1/service/cache-targets/{external_system}/{target_key}": RoutePolicy.SERVICE,
    "/v1/service/cache-target-streams/{external_system}": RoutePolicy.SERVICE,
    "/v1/service/cache-target-streams/{external_system}/restore-fences": (
        RoutePolicy.SERVICE
    ),
    "/v1/service/cache-target-event-claims": RoutePolicy.SERVICE,
    "/v1/service/cache-target-event-acks": RoutePolicy.SERVICE,
    "/v1/service/cache-target-event-nacks": RoutePolicy.SERVICE,
    "/v1/service/cache-target-event-dead-letters/{event_id}": RoutePolicy.SERVICE,
    "/v1/service/cache-target-event-dead-letters/{event_id}/replays": (
        RoutePolicy.SERVICE
    ),
    "/v1/service/cache-target-reconciliations": RoutePolicy.SERVICE,
    "/v1/service/cache-target-reconciliations/{request_id}/seals": (
        RoutePolicy.SERVICE
    ),
    "/v1/service/cache-target-reconciliations/{request_id}/completions": (
        RoutePolicy.SERVICE
    ),
    "/v1/service/cache-target-reconciliations/{request_id}/snapshot": (
        RoutePolicy.SERVICE
    ),
    "/v1/service/cache-target-snapshots/{external_system}": RoutePolicy.SERVICE,
    "/v1/service/refresh-requests": RoutePolicy.SERVICE,
    "/v1/service/refresh-requests/{request_id}": RoutePolicy.SERVICE,
    # -- operator/debug — raw provider payload은 local-dev debug mount에서만
    #    노출하되 mount된 route도 trusted admin BFF를 요구한다. production은
    #    debug_routes_enabled=false로 route 자체를 내린다.
    "/v1/debug/mois-license/{license_id}": RoutePolicy.OPERATOR,
    # -- operator — feature raw lineage(관측/source). T-VN-05(ADR-073/D-9-1):
    #    raw_data/raw_payload_hash/source_record_key는 공개 detail에서 제거하고
    #    admin BFF 인증 표면으로 이동했다.
    "/v1/features/{feature_id}/sources": RoutePolicy.OPERATOR,
    "/v1/features/{feature_id}/observations/{source_entity_key}/history": (
        RoutePolicy.OPERATOR
    ),
    # -- operator — admin BFF(trusted proxy secret+actor) 표면.
    "/v1/admin/auth-events": RoutePolicy.OPERATOR,
    "/v1/admin/backups": RoutePolicy.OPERATOR,
    "/v1/admin/backups/{backup_id}": RoutePolicy.OPERATOR,
    "/v1/admin/curated-features": RoutePolicy.OPERATOR,
    "/v1/admin/curated-features/{curated_feature_id}": RoutePolicy.OPERATOR,
    "/v1/admin/curated-features/{curated_feature_id}/place-search": (
        RoutePolicy.OPERATOR
    ),
    "/v1/admin/curated-features/{curated_feature_id}/select": RoutePolicy.OPERATOR,
    "/v1/admin/curated-features/{curated_feature_id}/unselect": RoutePolicy.OPERATOR,
    "/v1/admin/curated-source-rules": RoutePolicy.OPERATOR,
    "/v1/admin/curated-source-rules/{rule_id}": RoutePolicy.OPERATOR,
    "/v1/admin/curated-source-rules/{rule_id}/apply": RoutePolicy.OPERATOR,
    "/v1/admin/curated-sources": RoutePolicy.OPERATOR,
    "/v1/admin/curated-sources/{source_id}": RoutePolicy.OPERATOR,
    "/v1/admin/curated-themes": RoutePolicy.OPERATOR,
    "/v1/admin/curated-themes/{theme_id}": RoutePolicy.OPERATOR,
    "/v1/admin/curations": RoutePolicy.OPERATOR,
    "/v1/admin/curations/import": RoutePolicy.OPERATOR,
    "/v1/admin/curations/import-batches/{import_batch_id}": RoutePolicy.OPERATOR,
    "/v1/admin/curations/import-template.csv": RoutePolicy.OPERATOR,
    "/v1/admin/curations/items/{curation_item_id}/current-import-row": (
        RoutePolicy.OPERATOR
    ),
    "/v1/admin/curations/link-audit": RoutePolicy.OPERATOR,
    "/v1/admin/curations/quarantine": RoutePolicy.OPERATOR,
    "/v1/admin/curations/quarantine/{collection_id}/items": RoutePolicy.OPERATOR,
    "/v1/admin/curations/quarantine/{collection_id}/reclassify": (
        RoutePolicy.OPERATOR
    ),
    "/v1/admin/curations/{collection_id}": RoutePolicy.OPERATOR,
    "/v1/admin/curations/{collection_id}/items": RoutePolicy.OPERATOR,
    "/v1/admin/curations/{collection_id}/items/{curation_item_id}": (
        RoutePolicy.OPERATOR
    ),
    "/v1/admin/cache-target-event-dead-letters/{event_id}/replays": (
        RoutePolicy.OPERATOR
    ),
    "/v1/admin/cache-target-reconciliations": RoutePolicy.OPERATOR,
    "/v1/admin/dedup-reviews": RoutePolicy.OPERATOR,
    "/v1/admin/dedup-reviews/{review_id}": RoutePolicy.OPERATOR,
    "/v1/admin/enrichment-reviews": RoutePolicy.OPERATOR,
    "/v1/admin/enrichment-reviews/{review_id}": RoutePolicy.OPERATOR,
    "/v1/admin/features": RoutePolicy.OPERATOR,
    "/v1/admin/features/in-bounds": RoutePolicy.OPERATOR,
    "/v1/admin/features/weather/alerts": RoutePolicy.OPERATOR,
    "/v1/admin/features/change-requests": RoutePolicy.OPERATOR,
    "/v1/admin/features/change-requests/{request_id}/approve": RoutePolicy.OPERATOR,
    "/v1/admin/features/change-requests/{request_id}/reject": RoutePolicy.OPERATOR,
    "/v1/admin/features/curated": RoutePolicy.OPERATOR,
    "/v1/admin/features/curated/{curated_feature_id}": RoutePolicy.OPERATOR,
    "/v1/admin/features/curated/{curated_feature_id}/detail-snapshot": (
        RoutePolicy.OPERATOR
    ),
    "/v1/admin/features/curated/{curated_feature_id}/place-search": (
        RoutePolicy.OPERATOR
    ),
    "/v1/admin/features/curated/{curated_feature_id}/select": RoutePolicy.OPERATOR,
    "/v1/admin/features/curated/{curated_feature_id}/unselect": RoutePolicy.OPERATOR,
    "/v1/admin/features/dedup-reviews": RoutePolicy.OPERATOR,
    "/v1/admin/features/dedup-reviews/{review_id}": RoutePolicy.OPERATOR,
    "/v1/admin/features/enrichment-reviews": RoutePolicy.OPERATOR,
    "/v1/admin/features/enrichment-reviews/{review_id}": RoutePolicy.OPERATOR,
    "/v1/admin/features/{feature_id}": RoutePolicy.OPERATOR,
    "/v1/admin/features/{feature_id}/revision": RoutePolicy.OPERATOR,
    "/v1/admin/features/{feature_id}/deactivate": RoutePolicy.OPERATOR,
    "/v1/admin/features/{feature_id}/price": RoutePolicy.OPERATOR,
    "/v1/admin/features/{feature_id}/weather": RoutePolicy.OPERATOR,
    "/v1/admin/files": RoutePolicy.OPERATOR,
    "/v1/admin/files/rescan": RoutePolicy.OPERATOR,
    "/v1/admin/files/summary": RoutePolicy.OPERATOR,
    "/v1/admin/files/{file_id}": RoutePolicy.OPERATOR,
    "/v1/admin/files/{file_id}/events": RoutePolicy.OPERATOR,
    "/v1/admin/files/{file_id}/purge": RoutePolicy.OPERATOR,
    "/v1/admin/issues": RoutePolicy.OPERATOR,
    "/v1/admin/issues/{issue_id}": RoutePolicy.OPERATOR,
    "/v1/admin/offline-uploads": RoutePolicy.OPERATOR,
    "/v1/admin/offline-uploads/{upload_id}": RoutePolicy.OPERATOR,
    "/v1/admin/offline-uploads/{upload_id}/load": RoutePolicy.OPERATOR,
    "/v1/admin/offline-uploads/{upload_id}/preview": RoutePolicy.OPERATOR,
    "/v1/admin/offline-uploads/{upload_id}/validate": RoutePolicy.OPERATOR,
    "/v1/admin/offline-uploads/{upload_id}/validation": RoutePolicy.OPERATOR,
    "/v1/admin/poi-cache-targets": RoutePolicy.OPERATOR,
    "/v1/admin/poi-cache-targets/{external_system}/{target_key}": (
        RoutePolicy.OPERATOR
    ),
    "/v1/admin/public-api-keys": RoutePolicy.OPERATOR,
    "/v1/admin/public-api-keys/{public_api_key_id}/revoke": RoutePolicy.OPERATOR,
    "/v1/admin/restore/{backup_id}": RoutePolicy.OPERATOR,
    "/v1/admin/restore/{backup_id}/swap": RoutePolicy.OPERATOR,
    # -- operator — canonical ops datasets/pipeline (BFF 또는 ops principal).
    "/v1/ops/datasets": RoutePolicy.OPERATOR,
    "/v1/ops/datasets/detail": RoutePolicy.OPERATOR,
    "/v1/ops/datasets/preview": RoutePolicy.OPERATOR,
    "/v1/ops/datasets/refresh-policy": RoutePolicy.OPERATOR,
    "/v1/ops/pipeline/dagster-runs": RoutePolicy.OPERATOR,
    "/v1/ops/pipeline/dagster-runs/{run_id:path}": RoutePolicy.OPERATOR,
    "/v1/ops/pipeline/events": RoutePolicy.OPERATOR,
    "/v1/ops/pipeline/executions": RoutePolicy.OPERATOR,
    "/v1/ops/pipeline/executions/import_job/{execution_id}/cancel": (
        RoutePolicy.OPERATOR
    ),
    "/v1/ops/pipeline/executions/update_request/{execution_id}/cancel": (
        RoutePolicy.OPERATOR
    ),
    "/v1/ops/pipeline/executions/{kind}/{execution_id}": RoutePolicy.OPERATOR,
    "/v1/ops/pipeline/overview": RoutePolicy.OPERATOR,
    "/v1/ops/pipeline/prechecks/mois-source-sync": RoutePolicy.OPERATOR,
    "/v1/ops/pipeline/requests": RoutePolicy.OPERATOR,
    "/v1/ops/pipeline/requests/preview": RoutePolicy.OPERATOR,
    "/v1/ops/pipeline/requests/{request_id}/run-now": RoutePolicy.OPERATOR,
    "/v1/ops/pipeline/schedules": RoutePolicy.OPERATOR,
    "/v1/ops/pipeline/schedules/{schedule_name}": RoutePolicy.OPERATOR,
    "/v1/ops/pipeline/schedules/{schedule_name}/claims/{command_id}/resolve": (
        RoutePolicy.OPERATOR
    ),
    "/v1/ops/pipeline/schedules/{schedule_name}/commands": RoutePolicy.OPERATOR,
    "/v1/ops/cache-target-streams": RoutePolicy.OPERATOR,
    "/v1/ops/cache-target-event-dead-letters": RoutePolicy.OPERATOR,
    "/v1/ops/cache-target-event-dead-letters/{event_id}": RoutePolicy.OPERATOR,
    "/v1/ops/cache-target-operations/{operation_id}": RoutePolicy.OPERATOR,
    # -- operator — ops-live WebSocket (#725 HMAC ticket 재사용, ADR-064).
    "/v1/ops/live": RoutePolicy.OPERATOR,
    # -- operator — 존치 ops 관측 read(BFF 또는 ops:read principal).
    "/v1/ops/metrics": RoutePolicy.OPERATOR,
    "/v1/ops/system-logs": RoutePolicy.OPERATOR,
    "/v1/ops/api-call-logs": RoutePolicy.OPERATOR,
    "/v1/ops/consistency/reports": RoutePolicy.OPERATOR,
    "/v1/ops/consistency/issues": RoutePolicy.OPERATOR,
    "/v1/ops/health-deep": RoutePolicy.OPERATOR,
}


#: 배선≠정책이 허용되는 유일한 목록. T-VN-03 clean-cut 뒤 예외는 0건이다.
KNOWN_WIRING_EXCEPTIONS: tuple[WiringException, ...] = ()


# ---------------------------------------------------------------------------
# FastAPI 버전 견고 route 열거
# ---------------------------------------------------------------------------


def _iter_flattened_routes(app: FastAPI) -> Iterator[Any]:
    """lazy ``_IncludedRouter``를 해석한 route 열거 (버전 견고).

    FastAPI 0.136+에서는 OpenAPI 생성기와 같은 공개 helper
    ``iter_route_contexts``를 사용하고, 구버전은 ``app.router.routes``가 이미
    구체 route라 그대로 낸다.
    """

    try:
        from fastapi.routing import iter_route_contexts
    except ImportError:  # pragma: no cover — fastapi<0.136 하위호환 경로.
        yield from app.router.routes
        return
    yield from iter_route_contexts(app.router.routes)


def _observed_enforcement(dependant: Any) -> tuple[str, ...]:
    """route dependant 트리에서 알려진 enforcing dependency를 수집한다."""

    observed: set[str] = set()
    stack = list(getattr(dependant, "dependencies", []) or [])
    while stack:
        dependency = stack.pop()
        call = getattr(dependency, "call", None)
        if call is not None and call in _ENFORCEMENT_BY_CALLABLE:
            observed.add(_ENFORCEMENT_BY_CALLABLE[call])
        stack.extend(getattr(dependency, "dependencies", []) or [])
    return tuple(sorted(observed))


def _resolve_route(
    entry: Any,
) -> tuple[str | None, str | None, tuple[str, ...], bool, bool, Any]:
    """평탄화 entry를 path/method/schema 포함 여부/dependant로 해석한다.

    FastAPI 0.136+의 ``RouteContext``는 WebSocket/plain route의 해석 결과를
    ``starlette_route``에 담고(``path`` 필드는 비어 있음), APIRoute는 context
    자체가 해석된 path/dependant를 가진다. 구버전의 구체 route는 두 getattr이
    모두 자기 자신으로 떨어진다.
    """

    resolved = getattr(entry, "starlette_route", None) or entry
    original = getattr(entry, "original_route", entry)
    path = getattr(resolved, "path", None) or getattr(original, "path", None)
    schema_path = getattr(resolved, "path_format", None) or path
    is_websocket = isinstance(original, APIWebSocketRoute | WebSocketRoute)
    methods_value = getattr(resolved, "methods", None)
    methods = tuple(sorted(methods_value)) if methods_value else ()
    include_in_schema = bool(getattr(resolved, "include_in_schema", False))
    dependant = getattr(resolved, "dependant", None)
    if dependant is None:
        dependant = getattr(original, "dependant", None)
    return path, schema_path, methods, is_websocket, include_in_schema, dependant


def _registry_for_app(app: FastAPI) -> dict[str, RoutePolicy]:
    """정적 registry + settings 파생 entry(`/metrics` 경로)를 결합한다."""

    registry = dict(ROUTE_POLICIES)
    settings = getattr(app.state, "settings", None)
    if settings is not None and settings.prometheus_metrics_enabled:
        metrics_path = settings.prometheus_metrics_path
        existing = registry.get(metrics_path)
        if existing is not None and existing is not RoutePolicy.METRICS:
            raise RoutePolicyError(
                "prometheus_metrics_path collides with a route already classified "
                f"as {existing.value}: {metrics_path}"
            )
        registry[metrics_path] = RoutePolicy.METRICS
    return registry


def build_route_policy_matrix(app: FastAPI) -> tuple[RoutePolicyMatrixRow, ...]:
    """조립된 app의 전 HTTP/WS route를 분류한 matrix를 데이터로 생성한다.

    registry에 없는 route가 하나라도 있으면 ``RoutePolicyError``를 던진다
    (ADR-066 결정 1 — 미분류 route는 앱 구성 검사와 CI를 실패시킨다).
    """

    registry = _registry_for_app(app)
    rows: list[RoutePolicyMatrixRow] = []
    unclassified: list[str] = []
    for entry in _iter_flattened_routes(app):
        (
            path,
            schema_path,
            methods,
            is_websocket,
            include_in_schema,
            dependant,
        ) = _resolve_route(entry)
        if path is None:
            unclassified.append(f"<no path: {type(entry).__name__}>")
            continue
        policy = registry.get(path)
        if policy is None:
            unclassified.append(path)
            continue
        rows.append(
            RoutePolicyMatrixRow(
                path=path,
                schema_path=schema_path or path,
                methods=methods,
                is_websocket=is_websocket,
                include_in_schema=include_in_schema,
                policy=policy,
                observed_enforcement=_observed_enforcement(dependant),
            )
        )
    if unclassified:
        raise RoutePolicyError(
            "unclassified routes found — add each route to "
            "kortravelmap.api.route_policy.ROUTE_POLICIES with exactly one of "
            "public-unauthenticated/public-keyed/service/operator/debug/metrics "
            "(ADR-066 D-1): " + ", ".join(sorted(set(unclassified)))
        )
    return tuple(sorted(rows, key=lambda row: row.path))


def assert_routes_classified(app: FastAPI) -> None:
    """앱 구성 검사 — 미분류 route가 있으면 조립 시점에 실패한다."""

    build_route_policy_matrix(app)


def _wiring_satisfied(row: RoutePolicyMatrixRow) -> bool:
    """관측된 enforcing dependency가 정책 요구를 충족하는지 판정한다.

    - ``public-unauthenticated``/``debug``: 앱 인증 dependency가 없어야 한다.
      (debug의 enforcing 경계는 ``debug_routes_enabled`` flag + T-VN-01
      production 거부 — dependency가 아니라 mount 여부로 검증한다.)
    - ``public-keyed``: ``require_public_api_key``.
    - ``service``: ``require_service_token``.
    - ``operator``: admin BFF·ops principal·ops-live ticket 중 하나 이상.
    - ``metrics``: ``require_metrics_token``.
    """

    observed = set(row.observed_enforcement)
    if row.policy in (RoutePolicy.PUBLIC_UNAUTHENTICATED, RoutePolicy.DEBUG):
        return not observed
    if row.policy is RoutePolicy.PUBLIC_KEYED:
        return "require_public_api_key" in observed
    if row.policy is RoutePolicy.SERVICE:
        return bool(
            observed
            & {
                "require_service_token",
                "require_cache_target_service_principal",
            }
        )
    if row.policy is RoutePolicy.OPERATOR:
        return bool(observed & _OPERATOR_ENFORCEMENTS)
    if row.policy is RoutePolicy.METRICS:
        return "require_metrics_token" in observed
    raise RoutePolicyError(f"unknown route policy: {row.policy!r}")  # pragma: no cover


def assert_route_policy_wiring(app: FastAPI) -> tuple[RoutePolicyMatrixRow, ...]:
    """정책-배선 일치를 검증하고 matrix를 반환한다 (CI gate).

    ``KNOWN_WIRING_EXCEPTIONS``에 있는 route만 불일치가 허용되며, 소유 task가
    gap을 닫아 배선이 정책을 충족하게 되면 stale entry로 실패해 ledger 제거를
    강제한다.
    """

    matrix = build_route_policy_matrix(app)
    exceptions_by_path = {entry.path: entry for entry in KNOWN_WIRING_EXCEPTIONS}
    problems: list[str] = []
    for row in matrix:
        satisfied = _wiring_satisfied(row)
        exception = exceptions_by_path.get(row.path)
        if exception is not None:
            # ledger는 읽기 전용 gap만 임시 면제한다. ledger된 경로 아래 무인증
            # MUTATION이 T-VN-03 배선 전에 조용히 면제되는 것을 막는다 — 현재
            # ledger 항목은 전부 GET-only ops/curated read다.
            non_get_methods = set(row.methods) - {"GET", "HEAD"}
            if non_get_methods:
                problems.append(
                    f"{row.path}: KNOWN_WIRING_EXCEPTIONS may only exempt read-only "
                    f"routes but this route exposes {sorted(non_get_methods)!r} — "
                    "a non-GET method must not be ledger-exempted; wire the "
                    "enforcing dependency instead"
                )
            if satisfied:
                problems.append(
                    f"{row.path}: KNOWN_WIRING_EXCEPTIONS entry is stale — "
                    f"{exception.owner} closed this gap; remove the ledger entry"
                )
            continue
        if not satisfied:
            problems.append(
                f"{row.path}: policy {row.policy.value} is not enforced by the "
                f"observed dependencies {list(row.observed_enforcement)!r} — "
                "wire the enforcing dependency or add a KNOWN_WIRING_EXCEPTIONS "
                "entry with the owning task"
            )
    if problems:
        raise RoutePolicyError(
            "route policy wiring mismatch (ADR-066 D-1): " + "; ".join(problems)
        )
    return matrix
