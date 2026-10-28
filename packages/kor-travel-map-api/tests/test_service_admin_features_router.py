"""PinVi 전용 두 GET의 scope/기존 admin 조회 의미 회귀(DB 없는 ASGI)."""

from __future__ import annotations

import hashlib
from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient
from kortravelmap.infra.admin_feature_repo import AdminFeaturePage
from pydantic import ValidationError
from test_admin_features_router import _feature_detail, _feature_row, _patch_admin_resolved_identity

from kortravelmap.api.app import create_app
from kortravelmap.api.auth import SERVICE_TOKEN_HEADER
from kortravelmap.api.db import get_read_snapshot_session, get_session
from kortravelmap.api.routers import admin_features
from kortravelmap.api.routers.service_admin_features import service_router
from kortravelmap.api.settings import ApiSettings

TOKEN = "pinvi-admin-features-read-test-token"
DIGEST = hashlib.sha256(TOKEN.encode()).hexdigest()
OTHER = "separate-legacy-service-test-token"


async def _session() -> AsyncIterator[Any]:
    yield object()


def _client(**settings: Any) -> TestClient:
    app = create_app(ApiSettings(public_api_key_required=False, vworld_api_key=None, **settings))
    app.dependency_overrides[get_session] = _session
    app.dependency_overrides[get_read_snapshot_session] = _session
    return TestClient(app)


def _headers(token: str = TOKEN) -> dict[str, str]:
    return {SERVICE_TOKEN_HEADER: token}


@pytest.mark.unit
@pytest.mark.parametrize("suffix", ["", "/feature-1"])
def test_exact_read_auth_and_rotation(suffix: str, monkeypatch: pytest.MonkeyPatch) -> None:
    query = AsyncMock()
    monkeypatch.setattr(admin_features, "list_admin_features", query)
    monkeypatch.setattr(admin_features, "get_admin_feature_detail", query)
    path = "/v1/service/admin-features" + suffix
    client = _client(
        pinvi_admin_features_read_token_sha256=DIGEST,
        service_token=OTHER,
        pinvi_curation_snapshot_token_sha256=hashlib.sha256(b"snapshot-token").hexdigest(),
        ops_read_token="ops-read-test-token-00000000000000000000000000000000",
        ops_cancel_token="ops-cancel-test-token-00000000000000000000000000000000",
        ops_fixture_token="ops-fixture-test-token-00000000000000000000000000000000",
    )
    assert client.get(path).status_code == 401
    assert client.get(path, headers=_headers("unknown")).status_code == 401
    for token in (OTHER, "snapshot-token", "ops-read-test-token-00000000000000000000000000000000"):
        assert client.get(path, headers=_headers(token)).status_code == 403
    assert _client().get(path, headers=_headers()).status_code == 401
    replaced = _client(pinvi_admin_features_read_token_sha256=hashlib.sha256(b"new").hexdigest())
    assert replaced.get(path, headers=_headers()).status_code == 401
    query.assert_not_awaited()


@pytest.mark.unit
@pytest.mark.parametrize(
    "setting",
    [
        "admin_feature_create_token_sha256",
        "feature_request_token_sha256",
        "feature_reference_reconciliation_read_token_sha256",
        "feature_reference_reconciliation_ack_token_sha256",
    ],
)
def test_other_scope_digest_token_is_forbidden_not_unauthenticated(
    setting: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """다른 scope의 유효 토큰은 403이다. 판정은 기동 distinctness와 같은 단일 목록을 쓴다.

    수동 생성 digest는 예전 목록에 없어 401(``..._TOKEN_INVALID``)로 떨어졌다.
    """

    query = AsyncMock()
    monkeypatch.setattr(admin_features, "list_admin_features", query)
    other = f"{setting}-test-token"
    settings = {
        "feature_reference_reconciliation_read_token_sha256": hashlib.sha256(b"read").hexdigest(),
        "feature_reference_reconciliation_ack_token_sha256": hashlib.sha256(b"ack").hexdigest(),
        setting: hashlib.sha256(other.encode()).hexdigest(),
    }
    client = _client(pinvi_admin_features_read_token_sha256=DIGEST, **settings)
    response = client.get("/v1/service/admin-features", headers=_headers(other))
    assert response.status_code == 403
    assert response.json()["code"] == "PINVI_ADMIN_FEATURES_READ_SERVICE_SCOPE_FORBIDDEN"
    query.assert_not_awaited()


@pytest.mark.unit
def test_list_reuses_all_admin_filters_and_operational_dto(monkeypatch: pytest.MonkeyPatch) -> None:
    query = AsyncMock(return_value=AdminFeaturePage(items=(_feature_row(),), next_cursor="next"))
    monkeypatch.setattr(admin_features, "list_admin_features", query)
    client = _client(pinvi_admin_features_read_token_sha256=DIGEST)
    response = client.get(
        "/v1/service/admin-features",
        headers=_headers(),
        params=[
            ("q", "광화문"),
            ("kind", "place"),
            ("category", "01070300"),
            ("lifecycle_state", "retired"),
            ("publication_state", "suppressed"),
            ("quality_state", "quarantined"),
            ("provider_dataset_id", "7"),
            ("has_coord", "false"),
            ("has_issue", "true"),
            ("issue_type", "missing_address"),
            ("updated_from", "2026-01-01T00:00:00Z"),
            ("updated_to", "2026-10-25T00:00:00Z"),
            ("include_ended", "true"),
            ("page_size", "25"),
            ("cursor", "before"),
            ("sort", "issue_count"),
            ("order", "asc"),
        ],
    )
    assert response.status_code == 200
    kwargs = query.await_args.kwargs
    assert kwargs["q"] == "광화문"
    assert kwargs["kinds"] == ["place"]
    assert kwargs["categories"] == ["01070300"]
    assert kwargs["lifecycle_states"] == ["retired"]
    assert kwargs["publication_states"] == ["suppressed"]
    assert kwargs["quality_states"] == ["quarantined"]
    assert kwargs["provider_dataset_id"] == 7
    assert kwargs["has_coord"] is False
    assert kwargs["has_issue"] is True
    assert kwargs["issue_types"] == ["missing_address"]
    assert kwargs["updated_from"].isoformat() == "2026-01-01T00:00:00+00:00"
    assert kwargs["updated_to"].isoformat() == "2026-10-25T00:00:00+00:00"
    assert kwargs["include_ended"] is True
    assert (kwargs["page_size"], kwargs["cursor"], kwargs["sort"], kwargs["order"]) == (
        25,
        "before",
        "issue_count",
        "asc",
    )
    body = response.json()
    assert body["data"]["items"][0]["issues"][0]["issue_id"] == "issue-1"
    assert body["meta"]["page"]["next_cursor"] == "next"
    assert (
        client.get("/v1/service/admin-features?page_size=501", headers=_headers()).status_code
        == 422
    )


@pytest.mark.unit
def test_detail_keeps_canonical_resolver_sources_and_nonpublic_curations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_admin_resolved_identity(monkeypatch)
    detail = AsyncMock(return_value=_feature_detail())
    curations = AsyncMock(return_value={"feature-1": ()})
    monkeypatch.setattr(admin_features, "get_admin_feature_detail", detail)
    monkeypatch.setattr(
        admin_features.curation_repo, "list_curation_items_by_feature_ids", curations
    )
    client = _client(pinvi_admin_features_read_token_sha256=DIGEST)
    response = client.get("/v1/service/admin-features/feature-1", headers=_headers())
    assert response.status_code == 200
    assert detail.await_args.args[1] == "feature-1"
    assert curations.await_args.kwargs == {"feature_ids": ["feature-1"], "public_only": False}
    data = response.json()["data"]
    assert data["sources"][0]["raw_data"] == {"id": "sr-feature-1"}
    assert data["issues"][0]["issue_id"] == "issue-1"
    assert data["overrides"]
    detail.return_value = None
    assert client.get("/v1/service/admin-features/feature-1", headers=_headers()).status_code == 404
    assert client.get("/v1/service/admin-features/%20bad", headers=_headers()).status_code == 422


@pytest.mark.unit
@pytest.mark.parametrize(
    "path",
    [
        "/v1/service/admin-features",
        "/v1/service/admin-features/feature-1",
    ],
)
@pytest.mark.parametrize("method", ["post", "patch", "put", "delete"])
def test_service_router_has_no_writes(path: str, method: str) -> None:
    response = _client(pinvi_admin_features_read_token_sha256=DIGEST).request(
        method, path, headers=_headers(), json={}
    )
    assert response.status_code == 405


@pytest.mark.unit
def test_read_token_does_not_authorize_bff_or_other_service_scope() -> None:
    client = _client(
        pinvi_admin_features_read_token_sha256=DIGEST,
        admin_proxy_secret="separate-admin-proxy-secret",
        pinvi_curation_snapshot_token_sha256=hashlib.sha256(b"snapshot").hexdigest(),
    )
    assert client.get("/v1/admin/features", headers=_headers()).status_code == 403
    assert client.post("/v1/admin/features", headers=_headers(), json={}).status_code == 403
    assert (
        client.get(
            "/v1/service/curation-items/22222222-2222-4222-8222-222222222222/detail-snapshot",
            headers=_headers(),
        ).status_code
        == 403
    )


@pytest.mark.unit
@pytest.mark.parametrize(
    "other",
    [
        "pinvi_curation_snapshot_token_sha256",
        "pinvi_curation_cutover_mapping_token_sha256",
        "feature_request_token_sha256",
    ],
)
def test_duplicate_scoped_digest_is_rejected(other: str) -> None:
    with pytest.raises(ValidationError, match="distinct"):
        ApiSettings(pinvi_admin_features_read_token_sha256=DIGEST, **{other: DIGEST})


@pytest.mark.unit
@pytest.mark.parametrize("other", ["service_token", "admin_proxy_secret", "ops_read_token"])
def test_duplicate_raw_credential_is_rejected(other: str) -> None:
    settings = {other: TOKEN}
    if other == "ops_read_token":
        settings.update(
            ops_cancel_token="other-cancel-00000000000000000000000000000000",
            ops_fixture_token="other-fixture-00000000000000000000000000000000",
        )
    with pytest.raises(ValidationError, match="distinct"):
        ApiSettings(pinvi_admin_features_read_token_sha256=DIGEST, **settings)


@pytest.mark.unit
def test_digest_validation_and_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for invalid in ("a" * 63, "A" * 64, "g" * 64):
        with pytest.raises(ValidationError):
            ApiSettings(pinvi_admin_features_read_token_sha256=invalid)
    assert (
        ApiSettings(
            pinvi_admin_features_read_token_sha256=""
        ).pinvi_admin_features_read_token_sha256
        is None
    )
    monkeypatch.setenv("KOR_TRAVEL_MAP_API_PINVI_ADMIN_FEATURES_READ_TOKEN_SHA256", DIGEST)
    assert ApiSettings().pinvi_admin_features_read_token_sha256 == DIGEST


@pytest.mark.unit
def test_only_two_gets_share_original_endpoint_and_spec() -> None:
    assert [(route.path, route.methods, route.endpoint) for route in service_router.routes] == [
        ("/service/admin-features", {"GET"}, admin_features.list_features),
        ("/service/admin-features/{feature_id}", {"GET"}, admin_features.get_feature_detail_route),
    ]
    spec = _client().app.openapi()
    for suffix, original, dto in [
        ("", "/v1/admin/features", "AdminFeaturesListResponse"),
        ("/{feature_id}", "/v1/admin/features/{feature_id}", "AdminFeatureDetailResponse"),
    ]:
        operation = spec["paths"]["/v1/service/admin-features" + suffix]["get"]
        old = spec["paths"][original]["get"]
        assert operation["security"] == [{"ServiceToken": []}]
        assert operation["parameters"] == old["parameters"]
        assert operation["responses"]["200"]["content"]["application/json"]["schema"] == {
            "$ref": "#/components/schemas/" + dto
        }


@pytest.mark.unit
@pytest.mark.parametrize("enabled", [False, True])
@pytest.mark.parametrize("read_first", [False, True])
def test_manual_create_digest_cannot_equal_read_digest(enabled: bool, read_first: bool) -> None:
    digest_settings = [
        ("pinvi_admin_features_read_token_sha256", DIGEST),
        ("admin_feature_create_token_sha256", DIGEST),
    ]
    if not read_first:
        digest_settings.reverse()
    with pytest.raises(ValidationError, match="distinct from PinVi admin features read"):
        ApiSettings(
            admin_manual_feature_create_enabled=enabled,
            admin_proxy_secret="separate-proxy-secret-000000000000000000000",
            **dict(digest_settings),
        )


@pytest.mark.unit
@pytest.mark.parametrize("enabled", [False, True])
def test_runtime_revalidation_rejects_unvalidated_duplicate_copy(enabled: bool) -> None:
    valid = ApiSettings(
        admin_manual_feature_create_enabled=enabled,
        admin_proxy_secret="separate-proxy-secret-000000000000000000000",
        admin_feature_create_token_sha256=hashlib.sha256(b"separate-create-token").hexdigest(),
        pinvi_admin_features_read_token_sha256=DIGEST,
    )
    invalid = valid.model_copy(update={"admin_feature_create_token_sha256": DIGEST})
    with pytest.raises(ValueError, match="distinct from PinVi admin features read"):
        create_app(invalid)


@pytest.mark.unit
def test_read_token_cannot_be_promoted_to_create_with_valid_bff() -> None:
    from test_admin_features_router import _manual_create_payload

    secret = "separate-proxy-secret-000000000000000000000"
    app = create_app(
        ApiSettings(
            public_api_key_required=False,
            vworld_api_key=None,
            admin_manual_feature_create_enabled=True,
            admin_proxy_secret=secret,
            admin_trusted_proxy_cidrs=["127.0.0.1/32"],
            admin_feature_create_token_sha256=hashlib.sha256(b"separate-create-token").hexdigest(),
            pinvi_admin_features_read_token_sha256=DIGEST,
        )
    )
    app.dependency_overrides[get_session] = _session
    app.dependency_overrides[get_read_snapshot_session] = _session
    client = TestClient(app, client=("127.0.0.1", 50000))
    response = client.post(
        "/v1/admin/features",
        json=_manual_create_payload(),
        headers={
            SERVICE_TOKEN_HEADER: TOKEN,
            "X-Kor-Travel-Map-Admin-Feature-Create-Token": TOKEN,
            "X-Kor-Travel-Map-Admin-Proxy-Secret": secret,
            "X-Kor-Travel-Map-Actor": "admin:read-scope-boundary-test",
            "Idempotency-Key": "95000000-0000-4000-8000-000000000001",
        },
    )
    assert response.status_code == 403
    assert response.json()["code"] == "ADMIN_FEATURE_CREATE_SCOPE_REQUIRED"
