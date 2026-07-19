"""route policy matrix — 미분류 CI gate + 정책-배선 검증 (ADR-066 D-1, T-VN-02).

대표 구성(전 surface 활성, local-dev + dummy secret)으로 app을 조립해:

1. 모든 HTTP route와 WebSocket이 registry에 정확히 하나의 정책으로 분류돼
   있고(미분류 0건 — §8.2 gate), registry에 죽은 entry도 없음을 검사한다.
2. route별 관측된 enforcing dependency가 정책과 일치함을 검사한다. 다른
   task가 소유한 알려진 gap은 ``KNOWN_WIRING_EXCEPTIONS`` ledger로만 허용되고,
   소유 task가 gap을 닫으면 stale entry가 실패해 ledger 축소를 강제한다.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI

from kortravelmap.api.app import create_app
from kortravelmap.api.route_policy import (
    KNOWN_WIRING_EXCEPTIONS,
    ROUTE_POLICIES,
    RoutePolicy,
    RoutePolicyError,
    assert_route_policy_wiring,
    build_route_policy_matrix,
)
from kortravelmap.api.settings import ApiSettings

ADMIN_PROXY_SECRET = "admin-proxy-secret-000000000000000000000000"
OPS_READ_TOKEN = "read-token-00000000000000000000000000000000"
OPS_CANCEL_TOKEN = "cancel-token-000000000000000000000000000000"
SERVICE_TOKEN = "service-token-0000000000000000000000000000"
METRICS_TOKEN = "metrics-token-0000000000000000000000000000"

_HERMETIC_ENV_VARS = (
    "KOR_TRAVEL_MAP_API_PROFILE",
    "KOR_TRAVEL_MAP_API_DEBUG_ROUTES_ENABLED",
    "KOR_TRAVEL_MAP_API_FEATURES_ROUTES_ENABLED",
    "KOR_TRAVEL_MAP_API_ADMIN_ROUTES_ENABLED",
    "KOR_TRAVEL_MAP_API_OPS_ROUTES_ENABLED",
    "KOR_TRAVEL_MAP_API_PUBLIC_API_KEY_REQUIRED",
    "KOR_TRAVEL_MAP_API_PROMETHEUS_METRICS_ENABLED",
    "KOR_TRAVEL_MAP_API_PROMETHEUS_METRICS_PATH",
    "KOR_TRAVEL_MAP_API_METRICS_TOKEN",
    "KOR_TRAVEL_MAP_ADMIN_PROXY_SECRET",
    "KOR_TRAVEL_MAP_API_OPS_READ_TOKEN",
    "KOR_TRAVEL_MAP_API_OPS_CANCEL_TOKEN",
    "KOR_TRAVEL_MAP_API_OPS_PRINCIPAL_REQUIRED",
    "KOR_TRAVEL_MAP_API_SERVICE_TOKEN",
    "KOR_TRAVEL_MAP_API_VWORLD_API_KEY",
)


@pytest.fixture(autouse=True)
def _hermetic_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in _HERMETIC_ENV_VARS:
        monkeypatch.delenv(name, raising=False)


def _representative_settings(**overrides: object) -> ApiSettings:
    """전 surface 활성 + dummy secret의 대표 구성 (local-dev)."""

    values: dict[str, object] = {
        "profile": "local-dev",
        "debug_routes_enabled": True,
        "features_routes_enabled": True,
        "admin_routes_enabled": True,
        "ops_routes_enabled": True,
        "prometheus_metrics_enabled": True,
        "public_api_key_required": True,
        "admin_proxy_secret": ADMIN_PROXY_SECRET,
        "ops_read_token": OPS_READ_TOKEN,
        "ops_cancel_token": OPS_CANCEL_TOKEN,
        "service_token": SERVICE_TOKEN,
        "metrics_token": METRICS_TOKEN,
        "vworld_api_key": None,
    }
    values.update(overrides)
    return ApiSettings(_env_file=None, **values)


def _representative_app(**overrides: object) -> FastAPI:
    return create_app(_representative_settings(**overrides))


# ── 미분류 CI gate (§8.2 — route policy matrix에 미분류 route 0건) ────────────


@pytest.mark.unit
def test_all_routes_classified_and_registry_has_no_dead_entries() -> None:
    app = _representative_app()
    matrix = build_route_policy_matrix(app)

    mounted_paths = {row.path for row in matrix}
    registry_paths = set(ROUTE_POLICIES) | {
        app.state.settings.prometheus_metrics_path
    }
    # 미분류 route 0건은 build_route_policy_matrix가 이미 강제한다. 역방향:
    # registry에 있으나 전 surface 활성 구성에서도 mount되지 않는 dead entry는
    # route 삭제 시 registry 정리를 강제한다.
    assert registry_paths == mounted_paths

    # 모든 route는 6개 정책 중 정확히 하나다 (registry가 dict라 중복 불가).
    assert {row.policy for row in matrix} <= set(RoutePolicy)


@pytest.mark.unit
def test_adding_unclassified_route_breaks_the_gate_with_clear_message() -> None:
    app = _representative_app()

    @app.get("/v1/unclassified-probe")
    async def probe() -> dict[str, str]:  # pragma: no cover — 등록만 필요.
        return {}

    with pytest.raises(RoutePolicyError) as excinfo:
        build_route_policy_matrix(app)
    message = str(excinfo.value)
    assert "/v1/unclassified-probe" in message
    assert "ROUTE_POLICIES" in message


@pytest.mark.unit
def test_adding_unclassified_websocket_breaks_the_gate() -> None:
    app = _representative_app()

    @app.websocket("/v1/unclassified-ws-probe")
    async def ws_probe() -> None:  # pragma: no cover — 등록만 필요.
        return

    with pytest.raises(RoutePolicyError, match="unclassified-ws-probe"):
        build_route_policy_matrix(app)


@pytest.mark.unit
def test_create_app_rejects_metrics_path_colliding_with_other_policy() -> None:
    # `/metrics` 경로는 settings에서 오므로 registry의 다른 정책 경로와 충돌하면
    # 조립 자체가 실패해야 한다 (한 route = 정확히 한 정책).
    with pytest.raises(RoutePolicyError, match="prometheus_metrics_path"):
        _representative_app(prometheus_metrics_path="/health")


@pytest.mark.unit
def test_custom_metrics_path_is_classified_as_metrics() -> None:
    app = _representative_app(prometheus_metrics_path="/internal-metrics")
    matrix = build_route_policy_matrix(app)
    row = next(row for row in matrix if row.path == "/internal-metrics")
    assert row.policy is RoutePolicy.METRICS
    assert row.observed_enforcement == ("require_metrics_token",)


# ── 정책-배선 검증 + 예외 ledger ─────────────────────────────────────────────


@pytest.mark.unit
def test_route_policy_wiring_matches_with_known_exceptions_only() -> None:
    matrix = assert_route_policy_wiring(_representative_app())
    assert matrix  # 전 route 검증 완료 (불일치는 ledger 외에는 예외 발생).


@pytest.mark.unit
def test_known_exceptions_reference_owner_and_live_routes() -> None:
    app = _representative_app()
    mounted_paths = {row.path for row in build_route_policy_matrix(app)}
    assert KNOWN_WIRING_EXCEPTIONS  # T-VN-03 landing 전까지는 비어 있지 않다.
    for exception in KNOWN_WIRING_EXCEPTIONS:
        # ledger는 소유 task를 참조해야 하며(축소 추적), 실제 mount route와
        # registry 분류를 가리켜야 한다 (dead ledger entry 금지).
        assert "T-VN-" in exception.owner, exception
        assert exception.path in mounted_paths, exception
        assert exception.path in ROUTE_POLICIES, exception


@pytest.mark.unit
def test_stale_exception_entry_fails_when_gap_is_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # 소유 task가 배선을 정책에 맞추면 ledger entry가 stale로 실패해야 한다 —
    # 이미 배선이 일치하는 route를 예외로 등록해 재현한다.
    from kortravelmap.api import route_policy as module
    from kortravelmap.api.route_policy import WiringException

    monkeypatch.setattr(
        module,
        "KNOWN_WIRING_EXCEPTIONS",
        (
            *KNOWN_WIRING_EXCEPTIONS,
            WiringException("/v1/features", "T-VN-99 (probe)", "stale probe"),
        ),
    )
    with pytest.raises(RoutePolicyError, match="stale"):
        assert_route_policy_wiring(_representative_app())


@pytest.mark.unit
def test_unlisted_wiring_gap_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    # ledger에 없는 배선 gap은 실패한다 — 기존 gap 하나를 ledger에서 제거해 재현.
    from kortravelmap.api import route_policy as module

    remaining = tuple(
        entry
        for entry in KNOWN_WIRING_EXCEPTIONS
        if entry.path != "/v1/curated-themes"
    )
    assert len(remaining) == len(KNOWN_WIRING_EXCEPTIONS) - 1
    monkeypatch.setattr(module, "KNOWN_WIRING_EXCEPTIONS", remaining)
    with pytest.raises(RoutePolicyError, match="/v1/curated-themes"):
        assert_route_policy_wiring(_representative_app())


# ── 정책별 대표 검증 ─────────────────────────────────────────────────────────


@pytest.mark.unit
def test_ops_live_websocket_is_operator_with_reused_ticket_auth() -> None:
    matrix = build_route_policy_matrix(_representative_app())
    row = next(row for row in matrix if row.is_websocket)
    # #725 HMAC ticket 인증을 재사용한다 — 중복 인증 구현 금지 (ADR-066 결정 4).
    assert row.path == "/v1/ops/live"
    assert row.policy is RoutePolicy.OPERATOR
    assert row.observed_enforcement == ("authenticate_ops_live_websocket",)
    # WebSocket은 이 1개뿐이어야 한다 — 새 WS는 registry 분류를 강제받는다.
    assert [row.path for row in matrix if row.is_websocket] == ["/v1/ops/live"]


@pytest.mark.unit
def test_metrics_route_is_gated_by_metrics_token_dependency() -> None:
    matrix = build_route_policy_matrix(_representative_app())
    rows = [row for row in matrix if row.policy is RoutePolicy.METRICS]
    assert [row.path for row in rows] == ["/metrics"]
    assert rows[0].observed_enforcement == ("require_metrics_token",)


@pytest.mark.unit
def test_service_policy_covers_features_batch_only() -> None:
    matrix = build_route_policy_matrix(_representative_app())
    service_rows = [row for row in matrix if row.policy is RoutePolicy.SERVICE]
    assert {row.path for row in service_rows} == {"/v1/features/batch"}
    for row in service_rows:
        assert "require_service_token" in row.observed_enforcement


@pytest.mark.unit
def test_debug_policy_routes_disappear_when_debug_flag_is_off() -> None:
    matrix = build_route_policy_matrix(
        _representative_app(debug_routes_enabled=False)
    )
    # debug 정책의 enforcing 경계는 dependency가 아니라 settings flag mount다.
    assert not [row for row in matrix if row.policy is RoutePolicy.DEBUG]


@pytest.mark.unit
def test_public_unauthenticated_is_liveness_version_and_openapi_contract() -> None:
    matrix = build_route_policy_matrix(_representative_app())
    paths = {
        row.path
        for row in matrix
        if row.policy is RoutePolicy.PUBLIC_UNAUTHENTICATED
    }
    assert paths == {
        "/health",
        "/version",
        "/docs",
        "/docs/oauth2-redirect",
        "/redoc",
        "/openapi.json",
    }
    for row in matrix:
        if row.policy is RoutePolicy.PUBLIC_UNAUTHENTICATED:
            assert row.observed_enforcement == ()
