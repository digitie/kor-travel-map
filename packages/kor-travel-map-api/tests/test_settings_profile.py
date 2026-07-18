"""production profile fail-closed 기동 검증 (ADR-066 D-1, T-VN-01).

production은 필수 secret 누락·인증 없는 debug surface에서 ``ApiSettings`` 생성
자체가 실패해야 하고(기동 거부), secret 미설정 local-dev fallback은 non-production
profile에서만 유지되어야 한다.
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from kortravelmap.api.app import create_app
from kortravelmap.api.settings import ApiSettings

ADMIN_PROXY_SECRET = "admin-proxy-secret-000000000000000000000000"
OPS_READ_TOKEN = "read-token-00000000000000000000000000000000"
OPS_CANCEL_TOKEN = "cancel-token-000000000000000000000000000000"
SERVICE_TOKEN = "service-token-0000000000000000000000000000"

# 명시하지 않은 필드에 ambient host env가 스며들어 기본값 검증을 오염시키지
# 않도록, 이 파일의 모든 테스트에서 관련 env를 제거한다.
_HERMETIC_ENV_VARS = (
    "KOR_TRAVEL_MAP_API_PROFILE",
    "KOR_TRAVEL_MAP_API_DEBUG_ROUTES_ENABLED",
    "KOR_TRAVEL_MAP_API_FEATURES_ROUTES_ENABLED",
    "KOR_TRAVEL_MAP_API_ADMIN_ROUTES_ENABLED",
    "KOR_TRAVEL_MAP_API_OPS_ROUTES_ENABLED",
    "KOR_TRAVEL_MAP_API_PUBLIC_API_KEY_REQUIRED",
    "KOR_TRAVEL_MAP_ADMIN_PROXY_SECRET",
    "KOR_TRAVEL_MAP_API_ADMIN_PROXY_SECRET",
    "KOR_TRAVEL_MAP_API_OPS_READ_TOKEN",
    "KOR_TRAVEL_MAP_API_OPS_CANCEL_TOKEN",
    "KOR_TRAVEL_MAP_API_OPS_PRINCIPAL_REQUIRED",
    "KOR_TRAVEL_MAP_API_OPS_ACTOR",
    "KOR_TRAVEL_MAP_API_SERVICE_TOKEN",
    "KOR_TRAVEL_MAP_API_VWORLD_API_KEY",
)


@pytest.fixture(autouse=True)
def _hermetic_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in _HERMETIC_ENV_VARS:
        monkeypatch.delenv(name, raising=False)


def _local_settings(**overrides: Any) -> ApiSettings:
    values: dict[str, Any] = {
        "admin_proxy_secret": None,
        "ops_cancel_token": None,
        "ops_read_token": None,
        "public_api_key_required": False,
        "service_token": None,
        "vworld_api_key": None,
    }
    values.update(overrides)
    return ApiSettings(_env_file=None, **values)


def _production_settings(**overrides: Any) -> ApiSettings:
    """n150 Docker 배포와 등가인 최소 production 설정."""

    values: dict[str, Any] = {
        "profile": "production",
        "admin_proxy_secret": ADMIN_PROXY_SECRET,
        "ops_read_token": OPS_READ_TOKEN,
        "ops_cancel_token": OPS_CANCEL_TOKEN,
        "ops_principal_required": True,
        "public_api_key_required": True,
        "debug_routes_enabled": False,
        "service_token": SERVICE_TOKEN,
        "vworld_api_key": None,
    }
    values.update(overrides)
    return ApiSettings(_env_file=None, **values)


# ── profile 자체 ─────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_default_profile_is_local_dev_and_keeps_fallbacks() -> None:
    settings = _local_settings()
    assert settings.profile == "local-dev"
    assert not settings.is_production
    # 하위호환: local-dev는 secret 전무 + fail-open 기본값으로도 생성된다.
    assert settings.admin_proxy_secret is None
    assert not settings.public_api_key_required
    assert settings.debug_routes_enabled


@pytest.mark.unit
@pytest.mark.parametrize("profile", ["", "prod", "PRODUCTION", "dev", "staging"])
def test_profile_rejects_unknown_values(profile: str) -> None:
    with pytest.raises(ValidationError):
        _local_settings(profile=profile)


@pytest.mark.unit
def test_profile_reads_env_name(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KOR_TRAVEL_MAP_API_PROFILE", "production")
    monkeypatch.setenv("KOR_TRAVEL_MAP_ADMIN_PROXY_SECRET", ADMIN_PROXY_SECRET)
    monkeypatch.setenv("KOR_TRAVEL_MAP_API_OPS_READ_TOKEN", OPS_READ_TOKEN)
    monkeypatch.setenv("KOR_TRAVEL_MAP_API_OPS_CANCEL_TOKEN", OPS_CANCEL_TOKEN)
    monkeypatch.setenv("KOR_TRAVEL_MAP_API_PUBLIC_API_KEY_REQUIRED", "true")
    monkeypatch.setenv("KOR_TRAVEL_MAP_API_DEBUG_ROUTES_ENABLED", "false")
    monkeypatch.setenv("KOR_TRAVEL_MAP_API_SERVICE_TOKEN", SERVICE_TOKEN)
    settings = ApiSettings(_env_file=None)
    assert settings.is_production


# ── production 통과 matrix ───────────────────────────────────────────────────


@pytest.mark.unit
def test_production_minimal_valid_configuration_boots() -> None:
    settings = _production_settings()
    assert settings.is_production
    assert settings.resolved_ops_routes_enabled
    assert settings.resolved_admin_routes_enabled


@pytest.mark.unit
def test_production_docker_compose_env_equivalent_boots(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """compose environment + n150 package .env와 등가인 env 조합으로 기동한다.

    docker-compose.yml api service가 주입하는 PROFILE=production ·
    DEBUG_ROUTES_ENABLED=false · PUBLIC_API_KEY_REQUIRED=true 기본값과
    hard-require SERVICE_TOKEN, 그리고 n150이 package .env로 주입하는
    admin secret/ops principal을 재현한다.
    """

    monkeypatch.setenv("KOR_TRAVEL_MAP_API_PROFILE", "production")
    monkeypatch.setenv("KOR_TRAVEL_MAP_API_DEBUG_ROUTES_ENABLED", "false")
    monkeypatch.setenv("KOR_TRAVEL_MAP_API_PUBLIC_API_KEY_REQUIRED", "true")
    monkeypatch.setenv("KOR_TRAVEL_MAP_ADMIN_PROXY_SECRET", ADMIN_PROXY_SECRET)
    monkeypatch.setenv("KOR_TRAVEL_MAP_API_OPS_PRINCIPAL_REQUIRED", "true")
    monkeypatch.setenv("KOR_TRAVEL_MAP_API_OPS_READ_TOKEN", OPS_READ_TOKEN)
    monkeypatch.setenv("KOR_TRAVEL_MAP_API_OPS_CANCEL_TOKEN", OPS_CANCEL_TOKEN)
    monkeypatch.setenv("KOR_TRAVEL_MAP_API_FEATURES_ROUTES_ENABLED", "true")
    monkeypatch.setenv("KOR_TRAVEL_MAP_API_ADMIN_ROUTES_ENABLED", "true")
    monkeypatch.setenv("KOR_TRAVEL_MAP_API_OPS_ROUTES_ENABLED", "true")
    monkeypatch.setenv("KOR_TRAVEL_MAP_API_SERVICE_TOKEN", SERVICE_TOKEN)
    settings = ApiSettings(_env_file=None)
    assert settings.is_production
    assert settings.debug_routes_enabled is False
    assert settings.public_api_key_required is True


@pytest.mark.unit
def test_production_without_any_surface_needs_only_admin_secret() -> None:
    # DB 없는 부팅 검증형 배포: features/admin/ops 전부 off — public key·
    # service token·ops principal 요구는 사라지고 admin/operator secret만 남는다.
    settings = _production_settings(
        features_routes_enabled=False,
        ops_read_token=None,
        ops_cancel_token=None,
        ops_principal_required=False,
        public_api_key_required=False,
        service_token=None,
    )
    assert settings.is_production
    assert not settings.resolved_ops_routes_enabled


@pytest.mark.unit
def test_production_ops_tokens_not_required_when_ops_surface_disabled() -> None:
    settings = _production_settings(
        ops_routes_enabled=False,
        ops_read_token=None,
        ops_cancel_token=None,
        ops_principal_required=False,
    )
    assert settings.is_production
    assert not settings.resolved_ops_routes_enabled


@pytest.mark.unit
def test_production_accepts_service_token_at_32_char_boundary() -> None:
    settings = _production_settings(service_token="s" * 32)
    assert settings.service_token is not None


# ── production 거부 matrix ───────────────────────────────────────────────────


@pytest.mark.unit
@pytest.mark.parametrize(
    "admin_proxy_secret",
    [
        None,
        "",
        "short-secret",
        "a" * 31,
        f" {ADMIN_PROXY_SECRET}",
        f"{ADMIN_PROXY_SECRET} ",
    ],
)
def test_production_requires_deployable_admin_proxy_secret(
    admin_proxy_secret: str | None,
) -> None:
    with pytest.raises(ValidationError) as excinfo:
        _production_settings(admin_proxy_secret=admin_proxy_secret)
    message = str(excinfo.value)
    assert "production profile is fail-closed" in message
    assert "KOR_TRAVEL_MAP_ADMIN_PROXY_SECRET" in message
    # hide_input_in_errors + 고정 메시지 — secret 원문은 에러에 남지 않는다.
    if admin_proxy_secret:
        assert admin_proxy_secret.strip() not in message


@pytest.mark.unit
def test_production_requires_ops_principal_while_ops_surface_enabled() -> None:
    with pytest.raises(ValidationError) as excinfo:
        _production_settings(
            ops_read_token=None,
            ops_cancel_token=None,
            ops_principal_required=False,
        )
    message = str(excinfo.value)
    assert "KOR_TRAVEL_MAP_API_OPS_READ_TOKEN" in message
    assert "ops surface is enabled" in message


@pytest.mark.unit
def test_production_requires_ops_principal_when_ops_follows_features() -> None:
    # ops_routes_enabled=None(기본)은 features flag를 따른다 — features가 켜져
    # 있으면 token 없는 production은 거부된다.
    with pytest.raises(ValidationError):
        _production_settings(
            ops_routes_enabled=None,
            features_routes_enabled=True,
            ops_read_token=None,
            ops_cancel_token=None,
            ops_principal_required=False,
        )


@pytest.mark.unit
def test_production_requires_public_api_key_on_features_surface() -> None:
    with pytest.raises(ValidationError) as excinfo:
        _production_settings(public_api_key_required=False)
    assert "KOR_TRAVEL_MAP_API_PUBLIC_API_KEY_REQUIRED" in str(excinfo.value)


@pytest.mark.unit
def test_production_rejects_unauthenticated_debug_routes() -> None:
    with pytest.raises(ValidationError) as excinfo:
        _production_settings(debug_routes_enabled=True)
    assert "KOR_TRAVEL_MAP_API_DEBUG_ROUTES_ENABLED" in str(excinfo.value)


@pytest.mark.unit
def test_production_rejects_debug_routes_even_without_features_surface() -> None:
    # mount 여부와 무관하게 flag 자체를 거부한다 — mount 조건 변경에 따라 조용히
    # 열리는 회귀를 막는다.
    with pytest.raises(ValidationError):
        _production_settings(
            features_routes_enabled=False,
            debug_routes_enabled=True,
            ops_read_token=None,
            ops_cancel_token=None,
            ops_principal_required=False,
            public_api_key_required=False,
        )


@pytest.mark.unit
def test_production_requires_service_token_while_features_surface_enabled() -> None:
    # D-1-2의 service secret — 미설정이면 /v1/features/batch가 public key만으로
    # 열리는 조용한 격하가 생기므로 features surface에서는 기동을 거부한다.
    with pytest.raises(ValidationError) as excinfo:
        _production_settings(service_token=None)
    message = str(excinfo.value)
    assert "KOR_TRAVEL_MAP_API_SERVICE_TOKEN" in message
    assert "features surface is enabled" in message


@pytest.mark.unit
def test_production_service_token_not_required_without_features_surface() -> None:
    settings = _production_settings(
        features_routes_enabled=False,
        ops_routes_enabled=True,
        public_api_key_required=False,
        service_token=None,
    )
    assert settings.service_token is None


@pytest.mark.unit
@pytest.mark.parametrize(
    "service_token",
    ["", " ", "abc", "s" * 31, f" {SERVICE_TOKEN}", f"{SERVICE_TOKEN} "],
)
def test_production_rejects_blank_padded_or_short_service_token(
    service_token: str,
) -> None:
    with pytest.raises(ValidationError) as excinfo:
        _production_settings(service_token=service_token)
    assert "KOR_TRAVEL_MAP_API_SERVICE_TOKEN" in str(excinfo.value)


@pytest.mark.unit
@pytest.mark.parametrize("service_token", ["abc", "s" * 31, f" {SERVICE_TOKEN}"])
def test_production_rejects_bad_service_token_shape_even_without_features(
    service_token: str,
) -> None:
    # features off라도 설정된 token은 배포 가능한 형태여야 한다.
    with pytest.raises(ValidationError) as excinfo:
        _production_settings(
            features_routes_enabled=False,
            ops_routes_enabled=True,
            public_api_key_required=False,
            service_token=service_token,
        )
    assert "KOR_TRAVEL_MAP_API_SERVICE_TOKEN" in str(excinfo.value)


@pytest.mark.unit
def test_production_error_aggregates_every_missing_requirement() -> None:
    # 전부-기본값(local-dev fallback) 상태로 production을 켜면 한 번의 에러에
    # 모든 거부 사유가 나열되어 운영자가 반복 기동 없이 고칠 수 있다.
    with pytest.raises(ValidationError) as excinfo:
        _local_settings(profile="production")
    message = str(excinfo.value)
    assert "KOR_TRAVEL_MAP_ADMIN_PROXY_SECRET" in message
    assert "KOR_TRAVEL_MAP_API_OPS_READ_TOKEN" in message
    assert "KOR_TRAVEL_MAP_API_PUBLIC_API_KEY_REQUIRED" in message
    assert "KOR_TRAVEL_MAP_API_SERVICE_TOKEN" in message
    assert "KOR_TRAVEL_MAP_API_DEBUG_ROUTES_ENABLED" in message


# ── local-dev 격리 ───────────────────────────────────────────────────────────


@pytest.mark.unit
def test_local_dev_profile_keeps_all_fallbacks() -> None:
    # production 거부 사유의 조합이 non-production에서는 전부 허용된다(하위호환).
    settings = _local_settings(
        profile="local-dev",
        debug_routes_enabled=True,
        public_api_key_required=False,
    )
    assert settings.admin_proxy_secret is None
    assert settings.ops_read_token is None


# ── app 조립 ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_create_app_boots_with_production_settings_and_omits_debug_routes() -> None:
    application = create_app(settings=_production_settings())
    assert application.state.settings.is_production
    # ``application.routes`` 순회는 FastAPI 내부 표현에 묶인다 — 0.136+는 included
    # router를 lazy 객체로 담아 ``route.path``가 없다. 공개 API인 OpenAPI 스키마
    # (ADR-031 drift gate와 같은 소스)로 mount 여부를 검증한다.
    paths = set(application.openapi()["paths"])
    assert not any(path.startswith("/v1/debug") for path in paths)
    # 운영 surface는 그대로 mount된다.
    assert any(path.startswith("/v1/features") for path in paths)
    assert any(path.startswith("/v1/admin") for path in paths)
    assert any(path.startswith("/v1/ops") for path in paths)
