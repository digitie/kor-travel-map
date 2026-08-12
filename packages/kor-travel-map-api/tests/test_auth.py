"""앱 레벨 service-token / 파괴적 작업 kill-switch (ADR-045 D-1 B안)."""

from __future__ import annotations

import asyncio

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from pydantic import SecretStr, ValidationError

from kortravelmap.api.app import create_app
from kortravelmap.api.routers.admin_features import (
    require_destructive_enabled_for_retire,
)
from kortravelmap.api.auth import (
    ADMIN_ACTOR_HEADER,
    ADMIN_PROXY_SECRET_HEADER,
    OPS_ACTOR,
    OPS_FIXTURE_ACTOR,
    OPS_SCOPE_HEADER,
    OPS_TOKEN_HEADER,
    PUBLIC_API_KEY_HEADER,
    SERVICE_TOKEN_HEADER,
    require_admin_destructive_enabled,
    require_admin_frontend,
    require_ops_fixture_principal,
    require_ops_operator,
    require_service_token,
    resolve_admin_proxy_context,
)
from kortravelmap.api.db import get_session
from kortravelmap.api.provider_catalog import (
    ProviderDatasetCatalogEntry,
    ProviderDatasetOperation,
)
from kortravelmap.api.settings import ApiSettings

OPS_READ_TOKEN = "read-token-00000000000000000000000000000000"
OPS_CANCEL_TOKEN = "cancel-token-000000000000000000000000000000"
OPS_FIXTURE_TOKEN = "fixture-token-00000000000000000000000000000"


def _api_settings(**overrides: Any) -> ApiSettings:
    values: dict[str, Any] = {
        "admin_proxy_secret": None,
        "ops_cancel_token": None,
        "ops_fixture_token": None,
        "ops_read_token": None,
        "public_api_key_required": False,
        "service_token": None,
        "vworld_api_key": None,
    }
    values.update(overrides)
    if (
        values["ops_read_token"] is not None
        and values["ops_cancel_token"] is not None
        and "ops_fixture_token" not in overrides
    ):
        values["ops_fixture_token"] = OPS_FIXTURE_TOKEN
    return ApiSettings(**values)


def _request(settings: ApiSettings) -> Any:
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(settings=settings)))


def _json_body_request(settings: ApiSettings, payload: dict[str, Any]) -> Any:
    """route-level dependency 검증용 최소 request — body만 읽는다."""

    async def _json() -> dict[str, Any]:
        return payload

    return SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(settings=settings)),
        json=_json,
    )


def _ops_request(
    settings: ApiSettings,
    *,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    peer: str = "198.51.100.10",
    route_path: str = "/v1/ops/datasets",
    request_path: str | None = None,
    kind: str | None = None,
) -> Any:
    return SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(settings=settings)),
        client=SimpleNamespace(host=peer),
        headers=headers or {},
        method=method,
        path_params={} if kind is None else {"kind": kind},
        scope={
            "path": request_path or route_path,
            "route": SimpleNamespace(path=route_path),
        },
    )


# ── dependency 단위 ──────────────────────────────────────────────────────────


@pytest.mark.unit
def test_settings_reads_shared_admin_proxy_secret_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("KOR_TRAVEL_MAP_ADMIN_PROXY_SECRET", "shared-secret")
    monkeypatch.delenv("KOR_TRAVEL_MAP_API_ADMIN_PROXY_SECRET", raising=False)
    settings = ApiSettings(_env_file=None)
    assert settings.admin_proxy_secret is not None
    assert settings.admin_proxy_secret.get_secret_value() == "shared-secret"


@pytest.mark.unit
def test_settings_reads_legacy_api_admin_proxy_secret_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("KOR_TRAVEL_MAP_ADMIN_PROXY_SECRET", raising=False)
    monkeypatch.setenv(
        "KOR_TRAVEL_MAP_API_ADMIN_PROXY_SECRET",
        "legacy-api-secret",
    )
    settings = ApiSettings(_env_file=None)
    assert settings.admin_proxy_secret is not None
    assert settings.admin_proxy_secret.get_secret_value() == "legacy-api-secret"


@pytest.mark.unit
def test_settings_prefers_shared_admin_proxy_secret_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("KOR_TRAVEL_MAP_ADMIN_PROXY_SECRET", "shared-secret")
    monkeypatch.setenv(
        "KOR_TRAVEL_MAP_API_ADMIN_PROXY_SECRET",
        "legacy-api-secret",
    )
    settings = ApiSettings(_env_file=None)
    assert settings.admin_proxy_secret is not None
    assert settings.admin_proxy_secret.get_secret_value() == "shared-secret"


@pytest.mark.unit
def test_settings_keeps_admin_proxy_secret_unset_without_either_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("KOR_TRAVEL_MAP_ADMIN_PROXY_SECRET", raising=False)
    monkeypatch.delenv("KOR_TRAVEL_MAP_API_ADMIN_PROXY_SECRET", raising=False)
    settings = ApiSettings(_env_file=None)
    assert settings.admin_proxy_secret is None


@pytest.mark.unit
def test_shared_admin_proxy_secret_keeps_wrong_header_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("KOR_TRAVEL_MAP_ADMIN_PROXY_SECRET", "shared-secret")
    monkeypatch.delenv("KOR_TRAVEL_MAP_API_ADMIN_PROXY_SECRET", raising=False)
    settings = ApiSettings(_env_file=None)
    request = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(settings=settings)),
        client=SimpleNamespace(host="127.0.0.1"),
        headers={ADMIN_ACTOR_HEADER: "admin"},
    )

    with pytest.raises(HTTPException) as exc:
        require_admin_frontend(request, proxy_secret="wrong")
    assert exc.value.status_code == 403


@pytest.mark.unit
def test_settings_reads_server_only_ops_principal_names(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("KOR_TRAVEL_MAP_API_OPS_READ_TOKEN", OPS_READ_TOKEN)
    monkeypatch.setenv("KOR_TRAVEL_MAP_API_OPS_CANCEL_TOKEN", OPS_CANCEL_TOKEN)
    monkeypatch.setenv("KOR_TRAVEL_MAP_API_OPS_FIXTURE_TOKEN", OPS_FIXTURE_TOKEN)
    settings = ApiSettings(_env_file=None)
    assert settings.ops_read_token is not None
    assert settings.ops_cancel_token is not None
    assert settings.ops_fixture_token is not None
    assert settings.ops_read_token.get_secret_value() == OPS_READ_TOKEN
    assert settings.ops_cancel_token.get_secret_value() == OPS_CANCEL_TOKEN
    assert settings.ops_fixture_token.get_secret_value() == OPS_FIXTURE_TOKEN


@pytest.mark.unit
@pytest.mark.parametrize("actor", ["", "service:pinvi-test"])
def test_settings_rejects_removed_ops_actor_env(
    monkeypatch: pytest.MonkeyPatch,
    actor: str,
) -> None:
    monkeypatch.setenv("KOR_TRAVEL_MAP_API_OPS_ACTOR", actor)
    with pytest.raises(ValidationError):
        ApiSettings(_env_file=None)


@pytest.mark.unit
def test_settings_treats_empty_ops_tokens_as_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("KOR_TRAVEL_MAP_API_OPS_READ_TOKEN", "")
    monkeypatch.setenv("KOR_TRAVEL_MAP_API_OPS_CANCEL_TOKEN", "")
    monkeypatch.setenv("KOR_TRAVEL_MAP_API_OPS_FIXTURE_TOKEN", "")
    settings = ApiSettings(_env_file=None)
    assert settings.ops_read_token is None
    assert settings.ops_cancel_token is None
    assert settings.ops_fixture_token is None


@pytest.mark.unit
def test_settings_allows_absent_ops_pair_only_when_not_required() -> None:
    settings = ApiSettings(
        _env_file=None,
        admin_proxy_secret=None,
        public_api_key_required=False,
        service_token=None,
        vworld_api_key=None,
    )
    assert settings.ops_read_token is None
    assert settings.ops_cancel_token is None
    with pytest.raises(ValidationError):
        _api_settings(ops_principal_required=True)


@pytest.mark.unit
def test_settings_rejects_required_explicit_empty_ops_pair() -> None:
    with pytest.raises(ValidationError):
        _api_settings(
            ops_principal_required=True,
            ops_read_token="",
            ops_cancel_token="",
        )


@pytest.mark.unit
@pytest.mark.parametrize(
    "values",
    [
        {"ops_read_token": ""},
        {"ops_cancel_token": ""},
        {"ops_read_token": None},
        {"ops_cancel_token": None},
        {"ops_read_token": "", "ops_cancel_token": OPS_CANCEL_TOKEN},
        {"ops_read_token": OPS_READ_TOKEN, "ops_cancel_token": ""},
    ],
)
def test_settings_rejects_missing_empty_or_partial_ops_pair(
    values: dict[str, str | None],
) -> None:
    base: dict[str, Any] = {
        "admin_proxy_secret": None,
        "public_api_key_required": False,
        "service_token": None,
        "vworld_api_key": None,
    }
    with pytest.raises(ValidationError):
        ApiSettings(_env_file=None, **base, **values)


@pytest.mark.unit
@pytest.mark.parametrize(
    ("read_token", "cancel_token"),
    [
        ("read token-00000000000000000000000000000000", OPS_CANCEL_TOKEN),
        ("read\ttoken-0000000000000000000000000000000", OPS_CANCEL_TOKEN),
        (OPS_READ_TOKEN, "cancel token-000000000000000000000000000000"),
        (OPS_READ_TOKEN, "cancel\ttoken-00000000000000000000000000000"),
    ],
)
def test_settings_rejects_ops_token_whitespace_anywhere(
    read_token: str,
    cancel_token: str,
) -> None:
    with pytest.raises(ValidationError):
        _api_settings(
            ops_read_token=read_token,
            ops_cancel_token=cancel_token,
        )


@pytest.mark.unit
@pytest.mark.parametrize(
    ("read_token", "cancel_token", "admin_secret", "service_token"),
    [
        (OPS_READ_TOKEN, OPS_CANCEL_TOKEN, OPS_READ_TOKEN, None),
        (OPS_READ_TOKEN, OPS_CANCEL_TOKEN, OPS_CANCEL_TOKEN, None),
        (OPS_READ_TOKEN, OPS_CANCEL_TOKEN, None, OPS_READ_TOKEN),
        (OPS_READ_TOKEN, OPS_CANCEL_TOKEN, None, OPS_CANCEL_TOKEN),
    ],
)
def test_settings_rejects_ops_token_reuse_across_trust_boundaries(
    read_token: str,
    cancel_token: str,
    admin_secret: str | None,
    service_token: str | None,
) -> None:
    with pytest.raises(ValidationError):
        _api_settings(
            ops_read_token=read_token,
            ops_cancel_token=cancel_token,
            admin_proxy_secret=(SecretStr(admin_secret) if admin_secret is not None else None),
            service_token=(SecretStr(service_token) if service_token is not None else None),
        )


@pytest.mark.unit
@pytest.mark.parametrize(
    ("read_token", "cancel_token"),
    [
        ("", OPS_CANCEL_TOKEN),
        ("short", OPS_CANCEL_TOKEN),
        (f" {OPS_READ_TOKEN}", OPS_CANCEL_TOKEN),
        (OPS_READ_TOKEN, None),
        (None, OPS_CANCEL_TOKEN),
        (OPS_READ_TOKEN, OPS_READ_TOKEN),
    ],
)
def test_ops_principal_rejects_empty_short_trimmed_partial_or_shared_tokens(
    read_token: str | None,
    cancel_token: str | None,
) -> None:
    with pytest.raises(ValidationError):
        _api_settings(
            ops_read_token=read_token,
            ops_cancel_token=cancel_token,
        )


@pytest.mark.unit
@pytest.mark.parametrize(
    "values",
    [
        {"ops_read_token": "SENTINEL_RAW_SHORT"},
        {
            "ops_read_token": "SENTINEL RAW TOKEN 0000000000000000000000",
            "ops_cancel_token": OPS_CANCEL_TOKEN,
        },
        {
            "ops_read_token": "SENTINEL_RAW_TOKEN_00000000000000000000",
        },
        {
            "ops_read_token": "SENTINEL_RAW_TOKEN_00000000000000000000",
            "ops_cancel_token": "SENTINEL_RAW_TOKEN_00000000000000000000",
        },
        {
            "ops_read_token": "SENTINEL_RAW_TOKEN_00000000000000000000",
            "ops_cancel_token": OPS_CANCEL_TOKEN,
            "admin_proxy_secret": "SENTINEL_RAW_TOKEN_00000000000000000000",
        },
    ],
)
def test_ops_principal_validation_errors_hide_raw_secret_inputs(
    values: dict[str, str],
) -> None:
    with pytest.raises(ValidationError) as captured:
        _api_settings(**values)

    diagnostic = f"{captured.value!s}\n{captured.value!r}"
    assert "SENTINEL" not in diagnostic


@pytest.mark.unit
async def test_service_token_unset_allows_any() -> None:
    settings = _api_settings(service_token=None)
    # 미설정이면 헤더 유무와 무관하게 통과(raise 없음).
    await require_service_token(_request(settings), token=None)
    await require_service_token(_request(settings), token="anything")


@pytest.mark.unit
async def test_service_token_set_requires_match() -> None:
    settings = _api_settings(service_token=SecretStr("s3cr3t"))
    await require_service_token(_request(settings), token="s3cr3t")  # 일치 → OK
    for bad in (None, "", "wrong"):
        with pytest.raises(HTTPException) as exc:
            await require_service_token(_request(settings), token=bad)
        assert exc.value.status_code == 401


@pytest.mark.unit
def test_admin_destructive_kill_switch() -> None:
    require_admin_destructive_enabled(_request(_api_settings(admin_destructive_enabled=True)))
    with pytest.raises(HTTPException) as exc:
        require_admin_destructive_enabled(_request(_api_settings(admin_destructive_enabled=False)))
    assert exc.value.status_code == 403


def test_admin_frontend_gate_requires_proxy_secret_when_configured() -> None:
    settings = _api_settings(admin_proxy_secret=SecretStr("proxy-secret"))
    request = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(settings=settings)),
        client=SimpleNamespace(host="127.0.0.1"),
        headers={ADMIN_ACTOR_HEADER: "admin"},
    )
    context = require_admin_frontend(request, proxy_secret="proxy-secret")
    assert context.actor == "admin"

    with pytest.raises(HTTPException) as exc:
        require_admin_frontend(request, proxy_secret=None)
    assert exc.value.status_code == 403

    with pytest.raises(HTTPException) as exc:
        require_admin_frontend(request, proxy_secret="wrong")
    assert exc.value.status_code == 403


def test_admin_frontend_gate_keeps_local_dev_compat_when_secret_unset() -> None:
    request = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(settings=_api_settings())),
        client=SimpleNamespace(host="testclient"),
        headers={},
    )
    assert require_admin_frontend(request).actor == "local-dev"


@pytest.mark.unit
def test_admin_frontend_local_dev_fallback_is_closed_in_production() -> None:
    # ADR-066(T-VN-01): production settings는 생성 시점에 secret을 필수화하므로
    # 이 상태는 검증 우회(model_construct)로만 만들 수 있다. 그래도 dependency는
    # local-dev actor를 돌려주지 않고 fail-closed로 닫혀야 한다.
    settings = ApiSettings.model_construct(profile="production")
    assert settings.admin_proxy_secret is None
    request = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(settings=settings)),
        client=SimpleNamespace(host="127.0.0.1"),
        headers={ADMIN_ACTOR_HEADER: "admin"},
    )
    with pytest.raises(HTTPException) as exc:
        require_admin_frontend(request)
    assert exc.value.status_code == 403


@pytest.mark.unit
def test_resolve_admin_proxy_context_returns_none_in_production_without_secret() -> None:
    settings = ApiSettings.model_construct(profile="production")
    request = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(settings=settings)),
        client=SimpleNamespace(host="127.0.0.1"),
        headers={ADMIN_ACTOR_HEADER: "admin"},
    )
    assert resolve_admin_proxy_context(request, settings) is None


@pytest.mark.unit
def test_ops_operator_keeps_trusted_frontend_actor() -> None:
    settings = _api_settings(admin_proxy_secret=SecretStr("proxy-secret"))
    request = _ops_request(
        settings,
        headers={
            ADMIN_ACTOR_HEADER: "admin-actor",
            ADMIN_PROXY_SECRET_HEADER: "proxy-secret",
        },
        peer="127.0.0.1",
    )
    context = require_ops_operator(request)
    assert context.actor == "admin-actor"


@pytest.mark.unit
def test_ops_operator_uses_constant_time_token_and_server_actor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _api_settings(
        admin_proxy_secret=SecretStr("proxy-secret"),
        ops_cancel_token=SecretStr(OPS_CANCEL_TOKEN),
        ops_read_token=SecretStr(OPS_READ_TOKEN),
    )
    compared: list[tuple[str, str]] = []

    def _compare(left: str, right: str) -> bool:
        compared.append((left, right))
        return left == right

    monkeypatch.setattr("kortravelmap.api.auth.hmac.compare_digest", _compare)
    request = _ops_request(
        settings,
        headers={ADMIN_ACTOR_HEADER: "spoofed"},
    )
    context = require_ops_operator(
        request,
        token=OPS_READ_TOKEN,
        scope="ops:read",
    )
    assert context.actor == OPS_ACTOR
    assert compared == [
        (OPS_READ_TOKEN, OPS_READ_TOKEN),
        (OPS_READ_TOKEN, OPS_CANCEL_TOKEN),
    ]


@pytest.mark.unit
def test_ops_principal_disables_local_dev_bypass_when_admin_secret_is_unset() -> None:
    settings = _api_settings(
        admin_proxy_secret=None,
        ops_cancel_token=SecretStr(OPS_CANCEL_TOKEN),
        ops_read_token=SecretStr(OPS_READ_TOKEN),
    )
    with pytest.raises(HTTPException) as exc:
        require_ops_operator(_ops_request(settings))
    assert exc.value.status_code == 401
    assert exc.value.detail["code"] == "OPS_TOKEN_REQUIRED"


@pytest.mark.unit
def test_ops_cancel_token_is_bound_to_exact_import_job_cancel_route() -> None:
    settings = _api_settings(
        admin_proxy_secret=SecretStr("proxy-secret"),
        ops_cancel_token=SecretStr(OPS_CANCEL_TOKEN),
        ops_read_token=SecretStr(OPS_READ_TOKEN),
    )
    exact_cancel = _ops_request(
        settings,
        method="POST",
        # FastAPI/Starlette 조합에 따라 route.path의 include_router prefix 보존
        # 여부가 달라도 실제 ASGI path에 결박된 권한 판정은 같아야 한다.
        route_path="/executions/import_job/{execution_id}/cancel",
        request_path=(
            "/v1/ops/pipeline/executions/import_job/11111111-1111-1111-1111-111111111111/cancel"
        ),
        kind="import_job",
    )
    context = require_ops_operator(
        exact_cancel,
        token=OPS_CANCEL_TOKEN,
        scope="ops:cancel",
    )
    assert context.actor == OPS_ACTOR

    update_request_cancel = _ops_request(
        settings,
        method="POST",
        route_path="/executions/update_request/{execution_id}/cancel",
        request_path=(
            "/v1/ops/pipeline/executions/update_request/11111111-1111-1111-1111-111111111111/cancel"
        ),
        kind="update_request",
    )
    with pytest.raises(HTTPException) as exc:
        require_ops_operator(
            update_request_cancel,
            token=OPS_CANCEL_TOKEN,
            scope="ops:cancel",
        )
    assert exc.value.status_code == 403
    assert exc.value.detail["code"] == "OPS_SCOPE_FORBIDDEN"


@pytest.mark.unit
def test_ops_fixture_token_is_bound_to_exact_fixture_routes() -> None:
    settings = _api_settings(
        admin_proxy_secret=SecretStr("proxy-secret"),
        ops_cancel_token=SecretStr(OPS_CANCEL_TOKEN),
        ops_fixture_token=SecretStr(OPS_FIXTURE_TOKEN),
        ops_read_token=SecretStr(OPS_READ_TOKEN),
    )
    fixture_path = "/v1/ops/contract-fixtures/c6c-cancel-probe/11111111-1111-1111-1111-111111111111"
    for method, path in (
        ("GET", fixture_path),
        ("PUT", fixture_path),
        ("POST", f"{fixture_path}/finalize"),
    ):
        context = require_ops_fixture_principal(
            _ops_request(settings, method=method, request_path=path),
            token=OPS_FIXTURE_TOKEN,
            scope="ops:fixture",
        )
        assert context.actor == OPS_FIXTURE_ACTOR

    for method, token, scope, path, expected_status, expected_code in (
        ("GET", OPS_READ_TOKEN, "ops:fixture", fixture_path, 403, "OPS_TOKEN_INVALID"),
        ("GET", OPS_FIXTURE_TOKEN, "ops:read", fixture_path, 422, "OPS_SCOPE_INVALID"),
        ("DELETE", OPS_FIXTURE_TOKEN, "ops:fixture", fixture_path, 403, "OPS_SCOPE_FORBIDDEN"),
        ("POST", OPS_FIXTURE_TOKEN, "ops:fixture", fixture_path, 403, "OPS_SCOPE_FORBIDDEN"),
        (
            "POST",
            OPS_FIXTURE_TOKEN,
            "ops:fixture",
            "/v1/ops/pipeline/executions/import_job/11111111-1111-1111-1111-111111111111/cancel",
            403,
            "OPS_SCOPE_FORBIDDEN",
        ),
    ):
        with pytest.raises(HTTPException) as exc:
            require_ops_fixture_principal(
                _ops_request(settings, method=method, request_path=path),
                token=token,
                scope=scope,
            )
        assert exc.value.status_code == expected_status
        assert exc.value.detail["code"] == expected_code


@pytest.mark.unit
@pytest.mark.parametrize(
    ("method", "token", "scope", "expected_status", "expected_code"),
    [
        ("GET", None, None, 401, "OPS_TOKEN_REQUIRED"),
        ("GET", "wrong", "ops:read", 403, "OPS_TOKEN_INVALID"),
        ("GET", OPS_READ_TOKEN, None, 422, "OPS_SCOPE_REQUIRED"),
        ("GET", OPS_READ_TOKEN, "unknown", 422, "OPS_SCOPE_INVALID"),
        ("GET", OPS_READ_TOKEN, "ops:cancel", 403, "OPS_SCOPE_FORBIDDEN"),
        ("GET", OPS_CANCEL_TOKEN, "ops:read", 403, "OPS_SCOPE_FORBIDDEN"),
        ("POST", OPS_READ_TOKEN, "ops:read", 403, "OPS_SCOPE_FORBIDDEN"),
        ("POST", OPS_CANCEL_TOKEN, "ops:cancel", 403, "OPS_SCOPE_FORBIDDEN"),
        ("HEAD", OPS_READ_TOKEN, "ops:read", 403, "OPS_SCOPE_FORBIDDEN"),
    ],
)
def test_ops_operator_rejects_missing_invalid_or_excess_scope(
    method: str,
    token: str | None,
    scope: str | None,
    expected_status: int,
    expected_code: str,
) -> None:
    settings = _api_settings(
        admin_proxy_secret=SecretStr("proxy-secret"),
        ops_cancel_token=SecretStr(OPS_CANCEL_TOKEN),
        ops_read_token=SecretStr(OPS_READ_TOKEN),
    )
    with pytest.raises(HTTPException) as exc:
        require_ops_operator(
            _ops_request(settings, method=method),
            token=token,
            scope=scope,
        )
    assert exc.value.status_code == expected_status
    assert exc.value.detail["code"] == expected_code


# ── TestClient 통합 ──────────────────────────────────────────────────────────


class _FakeSession:
    async def execute(self, *_args: Any, **_kwargs: Any) -> Any:
        class _Result:
            def scalars(self) -> Any:
                return self

            def mappings(self) -> Any:
                return self

            def all(self) -> list[Any]:
                return []

        return _Result()

    def begin(self) -> Any:
        class _Tx:
            async def __aenter__(self) -> None:
                return None

            async def __aexit__(self, *_e: object) -> None:
                return None

        return _Tx()


def _client(settings: ApiSettings) -> TestClient:
    app = create_app(settings)

    async def _fake_session() -> AsyncIterator[_FakeSession]:
        yield _FakeSession()

    app.dependency_overrides[get_session] = _fake_session
    return TestClient(app, client=("127.0.0.1", 50000))


def _ops_client() -> TestClient:
    return _client(
        _api_settings(
            admin_proxy_secret=SecretStr("proxy-secret"),
            ops_cancel_token=SecretStr(OPS_CANCEL_TOKEN),
            ops_read_token=SecretStr(OPS_READ_TOKEN),
        )
    )


@pytest.mark.unit
def test_canonical_ops_read_accepts_bff_and_service_principal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kortravelmap.api.ops_dataset_schema import OpsDatasetsGridData
    from kortravelmap.api.routers import ops_datasets as router_module

    async def _grid(*_args: object, **_kwargs: object) -> OpsDatasetsGridData:
        return OpsDatasetsGridData(
            items=[],
            schedule_source_status="unavailable",
            schedule_source_errors=[],
            execution_coverage="db_recorded_canonical_operations",
        )

    monkeypatch.setattr(router_module, "load_datasets_grid", _grid)
    client = _ops_client()

    bff = client.get(
        "/v1/ops/datasets",
        headers={
            ADMIN_ACTOR_HEADER: "frontend-admin",
            ADMIN_PROXY_SECRET_HEADER: "proxy-secret",
        },
    )
    service = client.get(
        "/v1/ops/datasets",
        headers={
            ADMIN_ACTOR_HEADER: "spoofed",
            OPS_SCOPE_HEADER: "ops:read",
            OPS_TOKEN_HEADER: OPS_READ_TOKEN,
        },
    )
    assert bff.status_code == 200
    assert service.status_code == 200


@pytest.mark.unit
def test_c6c_fixture_route_accepts_only_fixture_principal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kortravelmap.infra.c6c_cancel_probe_fixture_repo import (
        C6cCancelProbeFixture,
    )

    from kortravelmap.api.routers import ops_contract_fixtures as router_module

    fixture = C6cCancelProbeFixture(
        transaction_id="11111111-1111-1111-1111-111111111111",
        job_id="22222222-2222-2222-2222-222222222222",
        state="armed",
        cancellation_id=None,
        created_at=datetime(2026, 8, 6, tzinfo=UTC),
        consumed_at=None,
        finalized_at=None,
        canonical_unsafe_outcome=None,
    )

    async def _get(*_args: object, **_kwargs: object) -> C6cCancelProbeFixture:
        return fixture

    monkeypatch.setattr(router_module, "get_c6c_cancel_probe_fixture", _get)
    client = _ops_client()
    path = "/v1/ops/contract-fixtures/c6c-cancel-probe/" + fixture.transaction_id

    fixture_response = client.get(
        path,
        headers={
            OPS_SCOPE_HEADER: "ops:fixture",
            OPS_TOKEN_HEADER: OPS_FIXTURE_TOKEN,
        },
    )
    bff_response = client.get(
        path,
        headers={
            ADMIN_ACTOR_HEADER: "frontend-admin",
            ADMIN_PROXY_SECRET_HEADER: "proxy-secret",
        },
    )
    read_response = client.get(
        path,
        headers={
            OPS_SCOPE_HEADER: "ops:fixture",
            OPS_TOKEN_HEADER: OPS_READ_TOKEN,
        },
    )

    assert fixture_response.status_code == 200
    assert fixture_response.json()["data"]["fixture"] == {
        "transaction_id": fixture.transaction_id,
        "job_id": fixture.job_id,
        "state": "armed",
        "cancellation_id": None,
        "created_at": "2026-08-06T00:00:00Z",
        "consumed_at": None,
        "finalized_at": None,
        "canonical_unsafe_outcome": None,
        "capability_generation": 2,
    }
    assert (bff_response.status_code, bff_response.json()["code"]) == (
        401,
        "OPS_TOKEN_REQUIRED",
    )
    assert (read_response.status_code, read_response.json()["code"]) == (
        403,
        "OPS_TOKEN_INVALID",
    )


@pytest.mark.unit
def test_c6c_fixture_receipt_exposes_only_canonical_unsafe_outcome() -> None:
    from kortravelmap.infra.c6c_cancel_probe_fixture_repo import (
        C6cCancelProbeCanonicalUnsafeOutcome,
        C6cCancelProbeFixture,
    )

    from kortravelmap.api.routers import ops_contract_fixtures as router_module

    fixture = C6cCancelProbeFixture(
        transaction_id="11111111-1111-1111-1111-111111111111",
        job_id="22222222-2222-2222-2222-222222222222",
        state="consumed",
        cancellation_id="33333333-3333-3333-3333-333333333333",
        created_at=datetime(2026, 8, 6, tzinfo=UTC),
        consumed_at=datetime(2026, 8, 6, 0, 1, tzinfo=UTC),
        finalized_at=None,
        canonical_unsafe_outcome=C6cCancelProbeCanonicalUnsafeOutcome(
            http_status=409,
            code="PIPELINE_CANCELLATION_UNSAFE",
            root_job_id="22222222-2222-2222-2222-222222222222",
            cancellation_id="33333333-3333-3333-3333-333333333333",
        ),
    )

    record = router_module._record(fixture)

    assert record.canonical_unsafe_outcome is not None
    assert record.canonical_unsafe_outcome.model_dump(mode="json") == {
        "http_status": 409,
        "code": "PIPELINE_CANCELLATION_UNSAFE",
        "root_job_id": fixture.job_id,
        "cancellation_id": fixture.cancellation_id,
    }


@pytest.mark.unit
def test_canonical_ops_mutation_is_bff_only_except_exact_cancel(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kortravelmap.api.ops_dataset_preview import DatasetPreviewResult
    from kortravelmap.api.routers import ops_datasets as router_module

    async def _catalog(*_args: object) -> tuple[ProviderDatasetCatalogEntry, ...]:
        return (
            ProviderDatasetCatalogEntry(
                provider_dataset_id=42,
                provider="test",
                dataset_key="fixture",
                display_name="fixture",
                source_kind="manual",
                is_active=True,
                capabilities={},
                operations=(
                    ProviderDatasetOperation(
                        operation_key="fixture_preview",
                        operation_kind="preview",
                        is_enabled=True,
                        config={"handler": "fixture"},
                        sync_scopes=(),
                    ),
                    ProviderDatasetOperation(
                        operation_key="fixture_refresh",
                        operation_kind="refresh",
                        is_enabled=True,
                        config={},
                        sync_scopes=("dataset_wide",),
                    ),
                ),
            ),
        )

    monkeypatch.setattr(router_module, "list_provider_dataset_catalog", _catalog)

    async def _preview(
        provider: str,
        dataset_key: str,
        *,
        max_items: int,
    ) -> DatasetPreviewResult:
        return DatasetPreviewResult(
            provider=provider,
            dataset=dataset_key,
            variant="contract",
            description="ops principal contract",
            items=(),
            total_items=0,
            max_items=max_items,
        )

    monkeypatch.setattr(router_module, "run_dataset_fixture_preview", _preview)
    client = _ops_client()
    params = {"sync_scope": "dataset_wide"}
    body = {"source": "fixture", "max_items": 1}
    service = client.post(
        "/v1/ops/datasets/42/preview",
        params=params,
        json=body,
        headers={
            OPS_SCOPE_HEADER: "ops:read",
            OPS_TOKEN_HEADER: OPS_READ_TOKEN,
        },
    )
    bff = client.post(
        "/v1/ops/datasets/42/preview",
        params=params,
        json=body,
        headers={
            ADMIN_ACTOR_HEADER: "frontend-admin",
            ADMIN_PROXY_SECRET_HEADER: "proxy-secret",
        },
    )
    assert service.status_code == 403
    assert service.json()["code"] == "OPS_SCOPE_FORBIDDEN"
    assert bff.status_code == 200


@pytest.mark.unit
@pytest.mark.parametrize(
    ("headers", "expected_status", "expected_code"),
    [
        ({}, 401, "OPS_TOKEN_REQUIRED"),
        (
            {OPS_TOKEN_HEADER: "wrong", OPS_SCOPE_HEADER: "ops:read"},
            403,
            "OPS_TOKEN_INVALID",
        ),
        ({OPS_TOKEN_HEADER: OPS_READ_TOKEN}, 422, "OPS_SCOPE_REQUIRED"),
        (
            {OPS_TOKEN_HEADER: OPS_READ_TOKEN, OPS_SCOPE_HEADER: "unknown"},
            422,
            "OPS_SCOPE_INVALID",
        ),
        (
            {OPS_TOKEN_HEADER: OPS_CANCEL_TOKEN, OPS_SCOPE_HEADER: "ops:read"},
            403,
            "OPS_SCOPE_FORBIDDEN",
        ),
    ],
)
def test_canonical_ops_http_errors_are_typed_problem_details(
    headers: dict[str, str],
    expected_status: int,
    expected_code: str,
) -> None:
    response = _ops_client().get("/v1/ops/datasets", headers=headers)
    assert response.status_code == expected_status
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["code"] == expected_code


@pytest.mark.unit
def test_ops_service_principal_cannot_access_admin_routes() -> None:
    response = _ops_client().get(
        "/v1/admin/auth-events",
        headers={
            ADMIN_ACTOR_HEADER: "spoofed",
            OPS_SCOPE_HEADER: "ops:read",
            OPS_TOKEN_HEADER: OPS_READ_TOKEN,
        },
    )
    assert response.status_code == 403


@pytest.mark.unit
def test_openapi_declares_exact_canonical_ops_security_contract() -> None:
    spec = _ops_client().get("/openapi.json").json()
    schemes = spec["components"]["securitySchemes"]
    assert schemes["AdminBFF"] == {
        "type": "apiKey",
        "description": (
            "trusted admin frontend BFF가 주입하는 server-only secret. 허용된 peer "
            f"CIDR과 {ADMIN_ACTOR_HEADER} actor header도 함께 검증한다."
        ),
        "in": "header",
        "name": ADMIN_PROXY_SECRET_HEADER,
    }
    assert schemes["OpsToken"] == {
        "type": "apiKey",
        "description": (
            "ops server-to-server read/cancel token. scope 문자열만으로는 "
            "권한을 얻지 못하며, token 종류와 method/exact path도 일치해야 한다."
        ),
        "in": "header",
        "name": OPS_TOKEN_HEADER,
    }
    assert schemes["OpsScope"] == {
        "type": "apiKey",
        "in": "header",
        "name": OPS_SCOPE_HEADER,
        "description": (
            "service principal 사용 시 OpsToken과 함께 필수인 scope 헤더. GET은 "
            "`ops:read`, exact import-job cancel POST는 `ops:cancel`이다. scope "
            "문자열만으로는 권한을 얻지 못하며 token 종류와 method/exact path도 "
            "일치해야 한다."
        ),
    }

    canonical_operations = 0
    cancel_path = "/v1/ops/pipeline/executions/import_job/{execution_id}/cancel"
    for path, path_item in spec["paths"].items():
        if not path.startswith(("/v1/ops/datasets", "/v1/ops/pipeline")):
            continue
        for method, operation in path_item.items():
            if method not in {"get", "put", "post", "delete", "patch"}:
                continue
            canonical_operations += 1
            service_capable = method == "get" or (method == "post" and path == cancel_path)
            # service 대안은 OpsToken+OpsScope AND 결합 — 런타임의 scope 헤더 필수
            # 판정(누락 422)과 선언이 일치해야 한다.
            assert operation["security"] == (
                [{"AdminBFF": []}, {"OpsToken": [], "OpsScope": []}]
                if service_capable
                else [{"AdminBFF": []}]
            ), (method, path)
            assert {"401", "403", "422"} <= set(operation["responses"])
            scope_parameters = [
                item
                for item in operation.get("parameters", [])
                if item["in"] == "header" and item["name"] == OPS_SCOPE_HEADER
            ]
            if service_capable:
                assert len(scope_parameters) == 1, (method, path)
                assert scope_parameters[0]["required"] is False
                assert "service principal" in scope_parameters[0]["description"]
            else:
                assert scope_parameters == [], (method, path)
                assert {"ServiceToken": []} not in operation["security"]
    assert canonical_operations > 0

    update_cancel = spec["paths"][
        "/v1/ops/pipeline/executions/update_request/{execution_id}/cancel"
    ]["post"]
    assert update_cancel["security"] == [{"AdminBFF": []}]
    assert not any(
        item["in"] == "header" and item["name"] == OPS_SCOPE_HEADER
        for item in update_cancel.get("parameters", [])
    )

    admin_operation = spec["paths"]["/v1/admin/auth-events"]["get"]
    assert admin_operation["security"] == [{"AdminBFF": []}]
    assert not any(
        item["in"] == "header" and item["name"] == OPS_SCOPE_HEADER
        for item in admin_operation.get("parameters", [])
    )

    observability_paths = {
        "/v1/ops/api-call-logs",
        "/v1/ops/consistency/issues",
        "/v1/ops/consistency/reports",
        "/v1/ops/health-deep",
        "/v1/ops/metrics",
        "/v1/ops/system-logs",
    }
    for path in observability_paths:
        operation = spec["paths"][path]["get"]
        assert operation["security"] == [
            {"AdminBFF": []},
            {"OpsToken": [], "OpsScope": []},
        ]
        assert any(
            item["in"] == "header" and item["name"] == OPS_SCOPE_HEADER
            for item in operation.get("parameters", [])
        )

    public_key = schemes["PublicApiKey"]
    assert public_key == {
        "type": "apiKey",
        "in": "header",
        "name": "X-Kor-Travel-Map-Api-Key",
        "description": (
            "외부/비신뢰 public read용 VWorld 호환 API key를 X-Kor-Travel-Map-Api-Key "
            "헤더로 전달한다. ServiceToken 요청은 같은 runtime dependency에서 별도 "
            "principal로 허용한다. T-VN-H01 — 접근 로그·Referer 유출을 막기 위해 이전 "
            "?key= 쿼리 파라미터는 제거됐다."
        ),
    }
    for path in {
        "/v1/curated-features",
        "/v1/curated-features/{curated_feature_id}",
        "/v1/curated-sources",
        "/v1/curated-themes",
    }:
        assert spec["paths"][path]["get"]["security"] == [
            {"PublicApiKey": []},
            {"ServiceToken": []},
        ]

    mois = spec["paths"]["/v1/debug/mois-license/{license_id}"]["get"]
    assert mois["security"] == [{"AdminBFF": []}]


@pytest.mark.unit
@pytest.mark.parametrize(
    "path",
    [
        "/v1/ops/api-call-logs",
        "/v1/ops/consistency/issues",
        "/v1/ops/consistency/reports",
        "/v1/ops/health-deep",
        "/v1/ops/metrics",
        "/v1/ops/system-logs",
    ],
)
def test_ops_observability_routes_reject_headerless_and_wrong_principals(
    path: str,
) -> None:
    client = _ops_client()
    headerless = client.get(path)
    service_only = client.get(
        path,
        headers={SERVICE_TOKEN_HEADER: "not-an-ops-token"},
    )
    cancel_as_read = client.get(
        path,
        headers={
            OPS_TOKEN_HEADER: OPS_CANCEL_TOKEN,
            OPS_SCOPE_HEADER: "ops:read",
        },
    )
    assert (headerless.status_code, headerless.json()["code"]) == (
        401,
        "OPS_TOKEN_REQUIRED",
    )
    assert (service_only.status_code, service_only.json()["code"]) == (
        401,
        "OPS_TOKEN_REQUIRED",
    )
    assert (cancel_as_read.status_code, cancel_as_read.json()["code"]) == (
        403,
        "OPS_SCOPE_FORBIDDEN",
    )


@pytest.mark.unit
def test_ops_observability_health_accepts_bff_and_read_principal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kortravelmap.api.routers import ops as ops_module

    async def _ok(_session: object) -> ops_module.OpsHealthCheck:
        return ops_module.OpsHealthCheck(component="probe", status="ok")

    monkeypatch.setattr(ops_module, "_check_database", _ok)
    monkeypatch.setattr(ops_module, "_check_postgis", _ok)
    monkeypatch.setattr(ops_module, "_check_prewarm", _ok)
    client = _ops_client()
    bff = client.get(
        "/v1/ops/health-deep",
        headers={
            ADMIN_ACTOR_HEADER: "frontend-admin",
            ADMIN_PROXY_SECRET_HEADER: "proxy-secret",
        },
    )
    service = client.get(
        "/v1/ops/health-deep",
        headers={
            OPS_TOKEN_HEADER: OPS_READ_TOKEN,
            OPS_SCOPE_HEADER: "ops:read",
        },
    )
    assert bff.status_code == 200
    assert service.status_code == 200


@pytest.mark.unit
def test_openapi_declares_service_and_public_key_security_schemes() -> None:
    client = _client(_api_settings(service_token=SecretStr("tok")))
    spec = client.get("/openapi.json").json()
    assert "ServiceToken" in spec["components"]["securitySchemes"]
    scheme = spec["components"]["securitySchemes"]["ServiceToken"]
    assert scheme["in"] == "header"
    assert scheme["name"] == SERVICE_TOKEN_HEADER
    # service operation은 service token만, public-keyed operation은 public key 또는
    # service token 중 하나를 요구한다.
    tri = spec["paths"]["/v1/features/batch"]["post"]
    assert tri["security"] == [{"ServiceToken": []}]
    weather_batch = spec["paths"]["/v1/features/weather/batch"]["post"]
    assert weather_batch["security"] == [{"ServiceToken": []}]
    feat = spec["paths"]["/v1/features"]["get"]
    assert feat["security"] == [
        {"PublicApiKey": []},
        {"ServiceToken": []},
    ]


@pytest.mark.unit
@pytest.mark.parametrize(
    "path",
    ["/v1/features/batch", "/v1/features/weather/batch"],
)
def test_batch_requires_token_when_set(path: str) -> None:
    client = _client(_api_settings(service_token=SecretStr("tok")))
    # 헤더 없음/오류 → 401(핸들러/DB 도달 전 auth 차단).
    assert client.post(path, json={}).status_code == 401
    assert (
        client.post(
            path,
            json={},
            headers={SERVICE_TOKEN_HEADER: "wrong"},
        ).status_code
        == 401
    )


@pytest.mark.unit
@pytest.mark.parametrize(
    "path",
    ["/v1/features/batch", "/v1/features/weather/batch"],
)
def test_batch_token_unset_not_blocked(path: str) -> None:
    client = _client(_api_settings(service_token=None))
    # 미설정이면 auth가 막지 않는다(하위호환). 본문/DB 사유로 401은 아니어야 한다.
    assert client.post(path, json={}).status_code != 401


@pytest.mark.unit
def test_features_not_gated_by_service_token() -> None:
    client = _client(_api_settings(service_token=SecretStr("tok")))
    # 브라우저 admin UI도 쓰는 공용 read surface는 service token으로 막지 않는다.
    assert client.get("/v1/features?limit=1").status_code != 401


@pytest.mark.unit
def test_public_api_key_required_accepts_vworld_fallback() -> None:
    client = _client(
        _api_settings(
            public_api_key_required=True,
            vworld_api_key=SecretStr("vw-test-key"),
        )
    )
    assert (
        client.get(
            "/v1/categories",
            headers={PUBLIC_API_KEY_HEADER: "vw-test-key"},
        ).status_code
        == 200
    )
    assert (
        client.get(
            "/v1/categories",
            headers={PUBLIC_API_KEY_HEADER: "wrong"},
        ).status_code
        == 401
    )
    assert client.get("/v1/categories").status_code == 401
    # T-VN-H01: query 파라미터로는 더 이상 인증되지 않는다(header-only).
    assert client.get("/v1/categories?key=vw-test-key").status_code == 401


@pytest.mark.unit
def test_public_api_key_required_trusts_admin_proxy() -> None:
    client = _client(
        _api_settings(
            admin_proxy_secret=SecretStr("proxy-secret"),
            public_api_key_required=True,
        )
    )
    response = client.get(
        "/v1/categories",
        headers={
            ADMIN_ACTOR_HEADER: "admin",
            ADMIN_PROXY_SECRET_HEADER: "proxy-secret",
        },
    )
    assert response.status_code == 200


@pytest.mark.unit
def test_admin_proxy_secret_deny_and_allow_over_http() -> None:
    client = _client(_api_settings(admin_proxy_secret=SecretStr("proxy-secret")))
    assert client.get("/v1/admin/auth-events").status_code == 403
    assert (
        client.get(
            "/v1/admin/auth-events",
            headers={
                ADMIN_ACTOR_HEADER: "admin",
                ADMIN_PROXY_SECRET_HEADER: "wrong",
            },
        ).status_code
        == 403
    )
    assert (
        client.get(
            "/v1/admin/auth-events",
            headers={
                ADMIN_ACTOR_HEADER: "admin",
                ADMIN_PROXY_SECRET_HEADER: "proxy-secret",
            },
        ).status_code
        == 200
    )


@pytest.mark.unit
def test_auth_event_records_authenticated_principal_not_body_actor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # ADR-066 D-2 (T-VN-07) — 감사 actor는 인증 principal에서만 파생한다. body가
    # 다른 actor를 보내도 저장·응답 actor는 proxy actor header(principal)여야 한다.
    from datetime import UTC, datetime

    from kortravelmap.infra.auth_event_repo import AdminAuthEventRow

    from kortravelmap.api import domain_command_service
    from kortravelmap.api.routers import admin_auth as admin_auth_mod

    captured: dict[str, Any] = {}

    async def _record(_session: Any, **kwargs: Any) -> AdminAuthEventRow:
        captured.update(kwargs)
        return AdminAuthEventRow(
            auth_event_id="ae_1",
            event_type=kwargs["event_type"],
            outcome=kwargs["outcome"],
            attempted_username=kwargs["attempted_username"],
            actor=kwargs["actor"],
            reason=kwargs["reason"],
            next_path=kwargs["next_path"],
            client_ip=kwargs["client_ip"],
            user_agent=kwargs["user_agent"],
            request_id=kwargs["request_id"],
            created_at=datetime(2026, 7, 19, tzinfo=UTC),
        )

    monkeypatch.setattr(admin_auth_mod, "record_admin_auth_event", _record)
    monkeypatch.setattr(
        domain_command_service,
        "begin_domain_command",
        AsyncMock(return_value=object()),
    )
    monkeypatch.setattr(
        domain_command_service,
        "complete_domain_command",
        AsyncMock(),
    )

    class _Transaction:
        async def __aenter__(self) -> None:
            return None

        async def __aexit__(self, *_exc: object) -> None:
            return None

    class _CommitSession:
        def begin(self) -> _Transaction:
            return _Transaction()

        async def commit(self) -> None:
            return None

    async def _session() -> AsyncIterator[Any]:
        yield _CommitSession()

    client = _client(_api_settings(admin_proxy_secret=SecretStr("proxy-secret")))
    client.app.dependency_overrides[get_session] = _session

    response = client.post(
        "/v1/admin/auth-events",
        headers={
            ADMIN_ACTOR_HEADER: "admin:real",
            ADMIN_PROXY_SECRET_HEADER: "proxy-secret",
            "Idempotency-Key": "95000000-0000-4000-8000-000000000001",
        },
        json={
            "event_type": "login",
            "outcome": "succeeded",
        },
    )

    assert response.status_code == 200, response.text
    # 저장·응답 actor 모두 인증 principal이어야 한다.
    assert captured["actor"] == "admin:real"
    assert response.json()["data"]["item"]["actor"] == "admin:real"


@pytest.mark.unit
def test_auth_event_rejects_removed_body_actor_field() -> None:
    # T-VN-20 (ADR-066 D-2): body.actor 필드는 제거됐다 — 보내면 extra="forbid"로 422.
    client = _client(_api_settings(admin_proxy_secret=SecretStr("proxy-secret")))
    response = client.post(
        "/v1/admin/auth-events",
        headers={
            ADMIN_ACTOR_HEADER: "admin:real",
            ADMIN_PROXY_SECRET_HEADER: "proxy-secret",
        },
        json={
            "event_type": "login",
            "outcome": "succeeded",
            "actor": "attacker:forged",
        },
    )
    assert response.status_code == 422


#: ``PATCH /admin/features/{id}/state``가 요구하는 write 헤더.
#: 이 둘이 없으면 body/header 검증이 핸들러보다 먼저 422를 내서, kill-switch가
#: 403을 낼 기회 자체가 없다(= 게이트를 검증하지 못한다).
_STATE_WRITE_HEADERS = {
    "If-Match": '"1"',
    "Idempotency-Key": "00000000-0000-4000-8000-000000000001",
}


@pytest.mark.unit
def test_destructive_admin_blocked_when_disabled() -> None:
    client = _client(_api_settings(admin_destructive_enabled=False))
    # T-VN-34가 ``POST /{id}/deactivate``를 ``PATCH /{id}/state``의 retire action으로
    # 합쳤다. kill-switch도 그 자리로 따라가야 한다 — route-level이 아니라 action
    # 단위로 거는 이유는, 같은 라우트의 publication/quality patch는 파괴적이지 않아
    # 게이트를 꺼도 막히면 안 되기 때문이다(아래 대조군).
    assert (
        client.patch(
            "/v1/admin/features/f_x/state",
            json={"action": "retire", "reason_code": "test"},
            headers=_STATE_WRITE_HEADERS,
        ).status_code
        == 403
    )
    assert (
        client.request("DELETE", "/v1/admin/poi-cache-targets/external-app/key-1").status_code
        == 403
    )


@pytest.mark.unit
def test_destructive_disabled_by_default_returns_403(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # T-VN-H02 — 기본값 fail-closed: env 미설정이면 파괴적 admin 작업은 403.
    monkeypatch.delenv("KOR_TRAVEL_MAP_API_DESTRUCTIVE_ENABLED", raising=False)
    settings = _api_settings()
    assert settings.admin_destructive_enabled is False
    client = _client(settings)
    assert (
        client.patch(
            "/v1/admin/features/f_x/state",
            json={"action": "retire", "reason_code": "test"},
            headers=_STATE_WRITE_HEADERS,
        ).status_code
        == 403
    )
    # 대조군 — 파괴적이지 않은 patch action은 게이트를 통과해야 한다.
    # HTTP로 태우면 게이트를 지난 뒤 DB에 닿으므로, 게이트 축만 직접 검증한다
    # (게이트를 라우트 전체에 걸면 아래가 HTTPException으로 깨진다).
    asyncio.run(
        require_destructive_enabled_for_retire(
            _json_body_request(
                settings,
                {"action": "patch", "publication_state": "draft", "reason_code": "test"},
            )
        )
    )


@pytest.mark.unit
def test_destructive_enabled_via_env_allows_ops(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # 배포 전제: env로 명시 enable하면 파괴적 kill-switch를 통과한다.
    monkeypatch.setenv("KOR_TRAVEL_MAP_API_DESTRUCTIVE_ENABLED", "true")
    settings = _api_settings()
    assert settings.admin_destructive_enabled is True
    require_admin_destructive_enabled(_request(settings))
