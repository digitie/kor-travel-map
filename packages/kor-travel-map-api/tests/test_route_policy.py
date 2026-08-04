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
CURSOR_SIGNING_SECRET = "cursor-signing-secret-000000000000000000000000"

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
    "KOR_TRAVEL_MAP_API_CURSOR_SIGNING_SECRET",
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
        "cursor_signing_secret": CURSOR_SIGNING_SECRET,
        "metrics_token": METRICS_TOKEN,
        "vworld_api_key": None,
    }
    values.update(overrides)
    return ApiSettings(_env_file=None, **values)


def _representative_app(**overrides: object) -> FastAPI:
    return create_app(_representative_settings(**overrides))


def _production_app(**overrides: object) -> FastAPI:
    """전 surface 활성 production 구성 — docs UI off·debug off를 검증한다."""

    return create_app(
        _representative_settings(
            profile="production",
            debug_routes_enabled=False,
            **overrides,
        )
    )


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
    # T-VN-03 clean-cut 뒤 정책과 실제 dependency가 전부 일치한다. 이후 gap은
    # 새 ledger로 숨기지 않고 같은 PR에서 배선을 완결해야 한다.
    assert KNOWN_WIRING_EXCEPTIONS == ()


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
    # registry 정책만 operator로 바꾸고 public dependency를 그대로 두면 예외 없이
    # 즉시 실패한다.
    monkeypatch.setitem(
        ROUTE_POLICIES,
        "/v1/curated-themes",
        RoutePolicy.OPERATOR,
    )
    with pytest.raises(RoutePolicyError, match="/v1/curated-themes"):
        assert_route_policy_wiring(_representative_app())


@pytest.mark.unit
@pytest.mark.parametrize(
    ("path", "wrong_policy"),
    [
        ("/v1/curated-themes", RoutePolicy.OPERATOR),
        ("/v1/ops/metrics", RoutePolicy.PUBLIC_KEYED),
    ],
)
def test_create_app_fails_on_public_operator_wiring_mismatch(
    monkeypatch: pytest.MonkeyPatch,
    path: str,
    wrong_policy: RoutePolicy,
) -> None:
    """PUBLIC_KEYED/OPERATOR 오배선은 test helper 호출 전 startup에서 실패한다."""

    monkeypatch.setitem(ROUTE_POLICIES, path, wrong_policy)

    with pytest.raises(RoutePolicyError, match=path):
        _representative_app()


@pytest.mark.unit
def test_every_ledgered_path_is_get_only() -> None:
    # ledger는 읽기 전용 gap만 면제한다 — 각 예외 경로가 실제로 GET-only인지
    # matrix에서 확인한다(무인증 MUTATION이 ledger 아래 숨는 것 방지).
    matrix = build_route_policy_matrix(_representative_app())
    methods_by_path = {row.path: set(row.methods) for row in matrix}
    for entry in KNOWN_WIRING_EXCEPTIONS:
        methods = methods_by_path[entry.path]
        assert methods - {"GET", "HEAD"} == set(), (entry.path, methods)


@pytest.mark.unit
def test_ledger_exempting_a_mutation_route_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # ledger에 POST 등 비-GET route를 넣으면 wiring gate가 거부해야 한다 —
    # T-VN-03 배선 전 무인증 MUTATION이 조용히 면제되는 것을 막는 가드.
    from kortravelmap.api import route_policy as module
    from kortravelmap.api.route_policy import WiringException

    # `/v1/admin/features`는 GET+POST를 노출한다.
    monkeypatch.setattr(
        module,
        "KNOWN_WIRING_EXCEPTIONS",
        (
            *KNOWN_WIRING_EXCEPTIONS,
            WiringException("/v1/admin/features", "T-VN-99 (probe)", "mutation probe"),
        ),
    )
    with pytest.raises(RoutePolicyError, match="non-GET method must not be"):
        assert_route_policy_wiring(_representative_app())


# ── callable-identity anti-spoof ─────────────────────────────────────────────


@pytest.mark.unit
def test_enforcement_is_identity_not_name_based() -> None:
    # 같은 이름의 impostor dependency는 enforcement로 기록되지 않는다 — 관측은
    # callable identity로만 판정하므로 이름만 흉내낸 경계는 wiring gate를 통과
    # 못 한다(정책 미충족 → 실패). 실제 callable은 정확히 기록됨을 함께 확인한다.
    from types import SimpleNamespace

    from kortravelmap.api import route_policy as module

    def require_public_api_key() -> None:  # noqa: D401 — same __name__ impostor.
        return None

    assert require_public_api_key.__name__ == "require_public_api_key"
    impostor_dep = SimpleNamespace(call=require_public_api_key, dependencies=[])
    impostor_root = SimpleNamespace(dependencies=[impostor_dep])
    assert module._observed_enforcement(impostor_root) == ()

    real_dep = SimpleNamespace(
        call=module.require_public_api_key,
        dependencies=[],
    )
    real_root = SimpleNamespace(dependencies=[real_dep])
    assert module._observed_enforcement(real_root) == ("require_public_api_key",)


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
def test_service_policy_covers_feature_and_weather_batches() -> None:
    matrix = build_route_policy_matrix(_representative_app())
    service_rows = [row for row in matrix if row.policy is RoutePolicy.SERVICE]
    assert {row.path for row in service_rows} == {
        "/v1/features/batch",
        "/v1/features/weather/batch",
        "/v1/service/cache-target-event-acks",
        "/v1/service/cache-target-event-claims",
        "/v1/service/cache-target-event-dead-letters/{event_id}",
        "/v1/service/cache-target-event-dead-letters/{event_id}/replays",
        "/v1/service/cache-target-event-nacks",
        "/v1/service/cache-target-reconciliations",
        "/v1/service/cache-target-reconciliations/{request_id}/completions",
        "/v1/service/cache-target-reconciliations/{request_id}/seals",
        "/v1/service/cache-target-reconciliations/{request_id}/snapshot",
        "/v1/service/cache-target-snapshots/{external_system}",
        "/v1/service/cache-target-streams/{external_system}",
        "/v1/service/cache-target-streams/{external_system}/restore-fences",
        "/v1/service/cache-targets/{external_system}/{target_key}",
        # T-VN-32C alias-map DB-to-DB 이관 표면 (ADR-068 전환·복구 경계 read).
        "/v1/service/feature-alias-maps",
        "/v1/service/feature-alias-maps/checksum",
        "/v1/service/refresh-requests",
        "/v1/service/refresh-requests/{request_id}",
    }
    for row in service_rows:
        assert {
            "require_cache_target_service_principal",
            "require_service_token",
        } & set(row.observed_enforcement)


@pytest.mark.unit
def test_debug_policy_covers_interactive_docs_only() -> None:
    matrix = build_route_policy_matrix(_representative_app())
    debug_paths = {row.path for row in matrix if row.policy is RoutePolicy.DEBUG}
    assert debug_paths == {
        "/docs",
        "/docs/oauth2-redirect",
        "/redoc",
    }
    for row in matrix:
        if row.policy is RoutePolicy.DEBUG:
            assert row.observed_enforcement == ()


@pytest.mark.unit
def test_mois_debug_route_is_operator_gated_and_disappears_with_debug_flag() -> None:
    matrix = build_route_policy_matrix(_representative_app())
    mois = next(
        row
        for row in matrix
        if row.path == "/v1/debug/mois-license/{license_id}"
    )
    assert mois.policy is RoutePolicy.OPERATOR
    assert mois.observed_enforcement == ("require_admin_frontend",)

    # ``debug_routes_enabled=False``는 ``/v1/debug/*``만 내린다. interactive docs
    # UI는 별도로 ``is_production``으로 gate되므로 local-dev에서는 그대로 남는다.
    disabled_matrix = build_route_policy_matrix(
        _representative_app(debug_routes_enabled=False)
    )
    mounted_paths = {row.path for row in disabled_matrix}
    debug_paths = {
        row.path for row in disabled_matrix if row.policy is RoutePolicy.DEBUG
    }
    assert "/v1/debug/mois-license/{license_id}" not in mounted_paths
    assert {"/docs", "/redoc", "/docs/oauth2-redirect"} <= debug_paths


@pytest.mark.unit
def test_t_vn_03_public_and_ops_routes_have_exact_enforcement() -> None:
    matrix = build_route_policy_matrix(_representative_app())
    rows = {row.path: row for row in matrix}
    public_curated = {
        "/v1/curated-features",
        "/v1/curated-features/{curated_feature_id}",
        "/v1/curated-sources",
        "/v1/curated-themes",
    }
    ops_observability = {
        "/v1/ops/api-call-logs",
        "/v1/ops/consistency/issues",
        "/v1/ops/consistency/reports",
        "/v1/ops/health-deep",
        "/v1/ops/metrics",
        "/v1/ops/system-logs",
    }
    for path in public_curated:
        assert rows[path].policy is RoutePolicy.PUBLIC_KEYED
        assert rows[path].observed_enforcement == ("require_public_api_key",)
    for path in ops_observability:
        assert rows[path].policy is RoutePolicy.OPERATOR
        assert rows[path].observed_enforcement == ("require_ops_operator",)


@pytest.mark.unit
def test_docs_uis_absent_in_production_openapi_contract_kept() -> None:
    # ADR-066 D-1 (T-VN-02) — 인증 없는 interactive docs UI는 production에서
    # 사라지고(debug policy = production-off), 기계 판독 계약 /openapi.json은 남는다.
    matrix = build_route_policy_matrix(_production_app())
    paths = {row.path for row in matrix}
    assert not (paths & {"/docs", "/redoc", "/docs/oauth2-redirect"})
    assert "/openapi.json" in paths
    assert "/v1/debug/mois-license/{license_id}" not in paths
    openapi_row = next(row for row in matrix if row.path == "/openapi.json")
    assert openapi_row.policy is RoutePolicy.PUBLIC_UNAUTHENTICATED


@pytest.mark.unit
def test_public_unauthenticated_is_liveness_version_and_openapi_contract() -> None:
    matrix = build_route_policy_matrix(_representative_app())
    paths = {
        row.path
        for row in matrix
        if row.policy is RoutePolicy.PUBLIC_UNAUTHENTICATED
    }
    # D-1: interactive docs UI는 여기 없다(→ debug). 기계 판독 계약만 유지.
    assert paths == {"/health", "/version", "/openapi.json"}
    for row in matrix:
        if row.policy is RoutePolicy.PUBLIC_UNAUTHENTICATED:
            assert row.observed_enforcement == ()
