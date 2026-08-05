"""production profile fail-closed 기동 검증 (ADR-066 D-1, T-VN-01).

production은 필수 secret 누락·인증 없는 debug surface에서 ``ApiSettings`` 생성
자체가 실패해야 하고(기동 거부), secret 미설정 local-dev fallback은 non-production
profile에서만 유지되어야 한다.
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import SecretStr, ValidationError

from kortravelmap.api.app import create_app
from kortravelmap.api.settings import ApiSettings

ADMIN_PROXY_SECRET = "admin-proxy-secret-000000000000000000000000"
OPS_READ_TOKEN = "read-token-00000000000000000000000000000000"
OPS_CANCEL_TOKEN = "cancel-token-000000000000000000000000000000"
OPS_FIXTURE_TOKEN = "fixture-token-00000000000000000000000000000"
SERVICE_TOKEN = "service-token-0000000000000000000000000000"
METRICS_TOKEN = "metrics-token-0000000000000000000000000000"
CURSOR_SIGNING_SECRET = "cursor-signing-secret-000000000000000000000000"
PUBLIC_API_KEY = "public-api-key-0000000000000000000000000000"

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
    "KOR_TRAVEL_MAP_API_OPS_FIXTURE_TOKEN",
    "KOR_TRAVEL_MAP_API_OPS_PRINCIPAL_REQUIRED",
    "KOR_TRAVEL_MAP_API_OPS_ACTOR",
    "KOR_TRAVEL_MAP_API_SERVICE_TOKEN",
    "KOR_TRAVEL_MAP_API_CURSOR_SIGNING_SECRET",
    "KOR_TRAVEL_MAP_API_VWORLD_API_KEY",
    "KOR_TRAVEL_MAP_API_METRICS_TOKEN",
    "KOR_TRAVEL_MAP_API_PROMETHEUS_METRICS_ENABLED",
)


@pytest.fixture(autouse=True)
def _hermetic_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in _HERMETIC_ENV_VARS:
        monkeypatch.delenv(name, raising=False)


def _local_settings(**overrides: Any) -> ApiSettings:
    values: dict[str, Any] = {
        "admin_proxy_secret": None,
        "ops_cancel_token": None,
        "ops_fixture_token": None,
        "ops_read_token": None,
        "public_api_key_required": False,
        "service_token": None,
        "cursor_signing_secret": None,
        "vworld_api_key": None,
    }
    values.update(overrides)
    if (
        values["ops_read_token"] is not None
        and values["ops_cancel_token"] is not None
        and "ops_fixture_token" not in overrides
    ):
        values["ops_fixture_token"] = OPS_FIXTURE_TOKEN
    return ApiSettings(_env_file=None, **values)


def _production_settings(**overrides: Any) -> ApiSettings:
    """n150 Docker 배포와 등가인 최소 production 설정."""

    values: dict[str, Any] = {
        "profile": "production",
        "admin_proxy_secret": ADMIN_PROXY_SECRET,
        "ops_read_token": OPS_READ_TOKEN,
        "ops_cancel_token": OPS_CANCEL_TOKEN,
        "ops_fixture_token": OPS_FIXTURE_TOKEN,
        "ops_principal_required": True,
        "public_api_key_required": True,
        "debug_routes_enabled": False,
        "service_token": SERVICE_TOKEN,
        "cursor_signing_secret": CURSOR_SIGNING_SECRET,
        "metrics_token": METRICS_TOKEN,
        "vworld_api_key": None,
    }
    values.update(overrides)
    if (
        values["ops_read_token"] is None
        and values["ops_cancel_token"] is None
        and "ops_fixture_token" not in overrides
    ):
        values["ops_fixture_token"] = None
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
    monkeypatch.setenv("KOR_TRAVEL_MAP_API_OPS_FIXTURE_TOKEN", OPS_FIXTURE_TOKEN)
    monkeypatch.setenv("KOR_TRAVEL_MAP_API_PUBLIC_API_KEY_REQUIRED", "true")
    monkeypatch.setenv("KOR_TRAVEL_MAP_API_DEBUG_ROUTES_ENABLED", "false")
    monkeypatch.setenv("KOR_TRAVEL_MAP_API_SERVICE_TOKEN", SERVICE_TOKEN)
    monkeypatch.setenv(
        "KOR_TRAVEL_MAP_API_CURSOR_SIGNING_SECRET",
        CURSOR_SIGNING_SECRET,
    )
    monkeypatch.setenv("KOR_TRAVEL_MAP_API_METRICS_TOKEN", METRICS_TOKEN)
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
    monkeypatch.setenv("KOR_TRAVEL_MAP_API_OPS_FIXTURE_TOKEN", OPS_FIXTURE_TOKEN)
    monkeypatch.setenv("KOR_TRAVEL_MAP_API_FEATURES_ROUTES_ENABLED", "true")
    monkeypatch.setenv("KOR_TRAVEL_MAP_API_ADMIN_ROUTES_ENABLED", "true")
    monkeypatch.setenv("KOR_TRAVEL_MAP_API_OPS_ROUTES_ENABLED", "true")
    monkeypatch.setenv("KOR_TRAVEL_MAP_API_SERVICE_TOKEN", SERVICE_TOKEN)
    monkeypatch.setenv(
        "KOR_TRAVEL_MAP_API_CURSOR_SIGNING_SECRET",
        CURSOR_SIGNING_SECRET,
    )
    monkeypatch.setenv("KOR_TRAVEL_MAP_API_METRICS_TOKEN", METRICS_TOKEN)
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
        cursor_signing_secret=None,
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


@pytest.mark.unit
def test_production_rejects_service_token_reused_as_admin_secret() -> None:
    with pytest.raises(ValidationError) as excinfo:
        _production_settings(service_token=ADMIN_PROXY_SECRET)
    message = str(excinfo.value)
    assert "KOR_TRAVEL_MAP_API_SERVICE_TOKEN" in message
    assert "distinct from KOR_TRAVEL_MAP_ADMIN_PROXY_SECRET" in message


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


# ── feature search cursor signing secret (T-VN-15) ──────────────────────────


@pytest.mark.unit
def test_production_requires_cursor_signing_secret_while_features_enabled() -> None:
    with pytest.raises(ValidationError) as excinfo:
        _production_settings(cursor_signing_secret=None)
    message = str(excinfo.value)
    assert "KOR_TRAVEL_MAP_API_CURSOR_SIGNING_SECRET" in message
    assert "features surface is enabled" in message


@pytest.mark.unit
def test_production_cursor_signing_secret_not_required_without_features() -> None:
    settings = _production_settings(
        features_routes_enabled=False,
        cursor_signing_secret=None,
    )
    assert settings.cursor_signing_secret is None


@pytest.mark.unit
@pytest.mark.parametrize(
    "cursor_signing_secret",
    ["", "short", "c" * 31, "cursor signing secret " + "c" * 32],
)
def test_cursor_signing_secret_rejects_short_or_whitespace(
    cursor_signing_secret: str,
) -> None:
    if cursor_signing_secret == "":
        settings = _local_settings(cursor_signing_secret=cursor_signing_secret)
        assert settings.cursor_signing_secret is None
        return
    with pytest.raises(ValidationError) as excinfo:
        _local_settings(cursor_signing_secret=cursor_signing_secret)
    assert "KOR_TRAVEL_MAP_API_CURSOR_SIGNING_SECRET" in str(excinfo.value)


@pytest.mark.unit
def test_local_dev_cursor_fallback_is_process_local_and_stable() -> None:
    first = _local_settings()
    second = _local_settings()
    assert first.cursor_signing_secret is None
    assert first.cursor_signing_key == second.cursor_signing_key
    assert len(first.cursor_signing_key) >= 32


@pytest.mark.unit
@pytest.mark.parametrize(
    "reused_field",
    [
        "admin_proxy_secret",
        "service_token",
        "metrics_token",
        "vworld_api_key",
    ],
)
def test_cursor_signing_secret_must_be_distinct_from_other_secrets(
    reused_field: str,
) -> None:
    with pytest.raises(ValidationError, match="must be distinct"):
        _local_settings(
            cursor_signing_secret=CURSOR_SIGNING_SECRET,
            **{reused_field: CURSOR_SIGNING_SECRET},
        )


@pytest.mark.unit
def test_cursor_signing_secret_must_be_distinct_from_ops_tokens() -> None:
    with pytest.raises(ValidationError, match="distinct from ops read token"):
        _local_settings(
            cursor_signing_secret=OPS_READ_TOKEN,
            ops_read_token=OPS_READ_TOKEN,
            ops_cancel_token=OPS_CANCEL_TOKEN,
        )


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


# ── metrics scrape token (ADR-066 결정 4, T-VN-02) ───────────────────────────


@pytest.mark.unit
def test_production_requires_metrics_token_while_metrics_endpoint_enabled() -> None:
    with pytest.raises(ValidationError) as excinfo:
        _production_settings(metrics_token=None)
    message = str(excinfo.value)
    assert "KOR_TRAVEL_MAP_API_METRICS_TOKEN" in message
    assert "Prometheus metrics endpoint is enabled" in message


@pytest.mark.unit
def test_production_metrics_token_not_required_when_metrics_disabled() -> None:
    settings = _production_settings(
        prometheus_metrics_enabled=False,
        metrics_token=None,
    )
    assert settings.metrics_token is None


@pytest.mark.unit
@pytest.mark.parametrize(
    "metrics_token",
    ["short", "m" * 31, f" {METRICS_TOKEN}", f"{METRICS_TOKEN} "],
)
def test_production_rejects_blank_padded_or_short_metrics_token(
    metrics_token: str,
) -> None:
    # service token과 같은 배포 가능 형태(앞뒤 공백 없는 32자 이상) 기준.
    with pytest.raises(ValidationError) as excinfo:
        _production_settings(metrics_token=metrics_token)
    assert "KOR_TRAVEL_MAP_API_METRICS_TOKEN" in str(excinfo.value)


@pytest.mark.unit
def test_production_rejects_bad_metrics_token_shape_even_when_disabled() -> None:
    # metrics endpoint off라도 설정된 token은 배포 가능한 형태여야 한다.
    with pytest.raises(ValidationError) as excinfo:
        _production_settings(
            prometheus_metrics_enabled=False,
            metrics_token="short",
        )
    assert "KOR_TRAVEL_MAP_API_METRICS_TOKEN" in str(excinfo.value)


@pytest.mark.unit
def test_local_dev_accepts_placeholder_metrics_token_shape() -> None:
    # root .env.example의 CHANGE_ME placeholder가 local-dev full-stack 검증을
    # 막지 않는다 (T-VN-01 service token과 같은 패턴 — production만 형태 강제).
    settings = _local_settings(metrics_token="CHANGE_ME")
    assert settings.metrics_token is not None


@pytest.mark.unit
@pytest.mark.parametrize(
    "metrics_token",
    ["é" * 32, "metrics token " + "m" * 32, "metrics:token:" + "m" * 32],
)
def test_metrics_token_rejects_non_b64token_characters(
    metrics_token: str,
) -> None:
    with pytest.raises(ValidationError, match="RFC 6750 b64token ASCII"):
        _local_settings(metrics_token=metrics_token)


@pytest.mark.unit
def test_metrics_token_accepts_rfc6750_b64token_padding() -> None:
    settings = _local_settings(metrics_token="metrics-token_0123456789+/abcdef==")
    assert settings.metrics_token is not None


@pytest.mark.unit
def test_metrics_token_empty_string_disables_like_none() -> None:
    settings = _local_settings(metrics_token="")
    assert settings.metrics_token is None


@pytest.mark.unit
@pytest.mark.parametrize(
    ("reused_field", "protected_name"),
    [
        ("admin_proxy_secret", "admin proxy secret"),
        ("service_token", "service token"),
    ],
)
def test_metrics_token_must_be_distinct_from_other_secrets(
    reused_field: str,
    protected_name: str,
) -> None:
    with pytest.raises(ValidationError, match=f"distinct from {protected_name}"):
        _local_settings(metrics_token=METRICS_TOKEN, **{reused_field: METRICS_TOKEN})


@pytest.mark.unit
def test_metrics_token_must_be_distinct_from_ops_tokens() -> None:
    with pytest.raises(ValidationError, match="distinct from ops read token"):
        _local_settings(
            metrics_token=OPS_READ_TOKEN,
            ops_read_token=OPS_READ_TOKEN,
            ops_cancel_token=OPS_CANCEL_TOKEN,
        )


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
    assert "KOR_TRAVEL_MAP_API_CURSOR_SIGNING_SECRET" in message
    assert "KOR_TRAVEL_MAP_API_DEBUG_ROUTES_ENABLED" in message
    assert "KOR_TRAVEL_MAP_API_METRICS_TOKEN" in message


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


@pytest.mark.unit
@pytest.mark.parametrize(
    ("updates", "expected_problem"),
    [
        ({"service_token": None}, "KOR_TRAVEL_MAP_API_SERVICE_TOKEN"),
        ({"public_api_key_required": False}, "KOR_TRAVEL_MAP_API_PUBLIC_API_KEY_REQUIRED"),
        ({"debug_routes_enabled": True}, "KOR_TRAVEL_MAP_API_DEBUG_ROUTES_ENABLED"),
        ({"cursor_signing_secret": None}, "KOR_TRAVEL_MAP_API_CURSOR_SIGNING_SECRET"),
        (
            {"cursor_signing_secret": SecretStr("short")},
            "KOR_TRAVEL_MAP_API_CURSOR_SIGNING_SECRET",
        ),
        (
            {"cursor_signing_secret": SecretStr("cursor signing secret " + "c" * 32)},
            "contain no whitespace",
        ),
        (
            {"cursor_signing_secret": SERVICE_TOKEN},
            "distinct from service token",
        ),
        (
            {"cursor_signing_secret": ADMIN_PROXY_SECRET},
            "distinct from admin proxy secret",
        ),
        (
            {"cursor_signing_secret": OPS_READ_TOKEN},
            "distinct from ops read token",
        ),
        (
            {"cursor_signing_secret": OPS_CANCEL_TOKEN},
            "distinct from ops cancel token",
        ),
        (
            {"cursor_signing_secret": METRICS_TOKEN},
            "distinct from metrics token",
        ),
        (
            {
                "cursor_signing_secret": PUBLIC_API_KEY,
                "vworld_api_key": SecretStr(PUBLIC_API_KEY),
            },
            "distinct from public API key",
        ),
        ({"cursor_signing_secret": 123}, "must be a string when set"),
    ],
)
def test_create_app_revalidates_bypassed_production_settings(
    updates: dict[str, Any],
    expected_problem: str,
) -> None:
    bypassed = _production_settings().model_copy(update=updates)
    with pytest.raises(ValueError, match=expected_problem):
        create_app(settings=bypassed)


@pytest.mark.unit
def test_create_app_accepts_plain_valid_cursor_secret_from_model_copy() -> None:
    bypassed = _production_settings().model_copy(
        update={"cursor_signing_secret": CURSOR_SIGNING_SECRET}
    )
    application = create_app(settings=bypassed)
    assert application.state.settings.cursor_signing_key == CURSOR_SIGNING_SECRET.encode()


@pytest.mark.unit
@pytest.mark.parametrize(
    ("updates", "expected_problem"),
    [
        (
            {"cursor_signing_secret": SecretStr("short")},
            "KOR_TRAVEL_MAP_API_CURSOR_SIGNING_SECRET",
        ),
        (
            {"cursor_signing_secret": SecretStr("cursor signing secret " + "c" * 32)},
            "contain no whitespace",
        ),
        (
            {"cursor_signing_secret": SERVICE_TOKEN},
            "distinct from service token",
        ),
        ({"cursor_signing_secret": 123}, "must be a string when set"),
        ({"cursor_signing_secret": None}, "KOR_TRAVEL_MAP_API_CURSOR_SIGNING_SECRET"),
    ],
)
def test_create_app_revalidates_model_construct_cursor_secret(
    updates: dict[str, Any],
    expected_problem: str,
) -> None:
    values = _production_settings().model_dump()
    values.update(updates)
    bypassed = ApiSettings.model_construct(**values)
    with pytest.raises(ValueError, match=expected_problem):
        create_app(settings=bypassed)


@pytest.mark.unit
@pytest.mark.parametrize(
    "updates",
    [
        {"cursor_signing_secret": SecretStr("short")},
        {
            "cursor_signing_secret": SERVICE_TOKEN,
            "service_token": SecretStr(SERVICE_TOKEN),
        },
    ],
)
def test_create_app_revalidates_local_dev_cursor_secret(
    updates: dict[str, Any],
) -> None:
    bypassed = _local_settings().model_copy(update=updates)
    with pytest.raises(ValueError, match="runtime settings are invalid"):
        create_app(settings=bypassed)
