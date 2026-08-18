"""PinVi canonical curation snapshot service 계약."""

from __future__ import annotations

import hashlib
import unicodedata
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from kortravelmap.core.curation_snapshot import curation_snapshot_sha256
from kortravelmap.infra.curation_repo import (
    CurationCutoverIdentityMapping,
    CurationCutoverIdentityMappingExport,
    CurationServiceCollectionSnapshot,
    CurationServiceItemSnapshot,
)
from pydantic import SecretStr, ValidationError

from kortravelmap.api.app import create_app
from kortravelmap.api.auth import (
    OPS_TOKEN_HEADER,
    PUBLIC_API_KEY_HEADER,
    SERVICE_TOKEN_HEADER,
)
from kortravelmap.api.db import get_session
from kortravelmap.api.routers import curation_snapshots as module
from kortravelmap.api.settings import ApiSettings

TOKEN = "pinvi-curation-snapshot-token-000000000000000000000"
TOKEN_DIGEST = hashlib.sha256(TOKEN.encode()).hexdigest()
CUTOVER_TOKEN = "pinvi-curation-cutover-token-0000000000000000000000"
CUTOVER_TOKEN_DIGEST = hashlib.sha256(CUTOVER_TOKEN.encode()).hexdigest()
GENERIC_TOKEN = "generic-service-token-000000000000000000000000000"
OPS_TOKEN = "ops-read-token-000000000000000000000000000000000"
OPS_CANCEL_TOKEN = "ops-cancel-token-000000000000000000000000000000"
OPS_FIXTURE_TOKEN = "ops-fixture-token-00000000000000000000000000000"
COLLECTION_ID = "11111111-1111-4111-8111-111111111111"
ITEM_ID = "22222222-2222-4222-8222-222222222222"
ITEM_ID_2 = "33333333-3333-4333-8333-333333333333"
FEATURE_ID = "44444444-4444-4444-8444-444444444444"


async def _fake_session() -> AsyncIterator[Any]:
    yield object()


@pytest.fixture
def client() -> TestClient:
    app = create_app(
        ApiSettings(
            public_api_key_required=False,
            vworld_api_key=None,
            pinvi_curation_snapshot_token_sha256=TOKEN_DIGEST,
        )
    )
    app.dependency_overrides[get_session] = _fake_session
    return TestClient(app)


def _item(item_id: str = ITEM_ID, *, revision: int = 7) -> CurationServiceItemSnapshot:
    return CurationServiceItemSnapshot(
        curation_item_id=item_id,
        collection_id=COLLECTION_ID,
        row_revision=revision,
        updated_at=datetime(2026, 8, 14, 1, 2, 3, tzinfo=UTC),
        theme_slug="coastal-cafes",
        theme_name="해안 카페",
        collection_title="동해 카페",
        edition_key="2026",
        feature_uuid=FEATURE_ID,
        relation="cafe_stop",
        sort_order=3,
        item_title=None,
        item_summary="바다가 보이는 카페",
        feature_name="파도 카페",
        feature_category="01070100",
        feature_kind="place",
        lon=129.1,
        lat=35.1,
        address={"road": "해안로 1"},
        detail={"place_kind": "cafe"},
        source_record_key=None,
    )


def _collection(
    *items: CurationServiceItemSnapshot,
    revision: int = 5,
    item_count: int | None = None,
    item_set_hash: str = "a" * 64,
) -> CurationServiceCollectionSnapshot:
    return CurationServiceCollectionSnapshot(
        collection_id=COLLECTION_ID,
        row_revision=revision,
        updated_at=datetime(2026, 8, 14, 2, 3, 4, tzinfo=UTC),
        theme_slug="coastal-cafes",
        theme_name="해안 카페",
        title="동해 카페",
        edition_key="2026",
        item_count=len(items) if item_count is None else item_count,
        item_set_hash=item_set_hash,
        items=tuple(items),
    )


def _headers(token: str = TOKEN) -> dict[str, str]:
    return {SERVICE_TOKEN_HEADER: token}


def _cutover_headers(token: str = CUTOVER_TOKEN) -> dict[str, str]:
    return {SERVICE_TOKEN_HEADER: token}


@pytest.fixture
def cutover_client() -> TestClient:
    app = create_app(
        ApiSettings(
            public_api_key_required=False,
            vworld_api_key=None,
            pinvi_curation_snapshot_token_sha256=TOKEN_DIGEST,
            pinvi_curation_cutover_mapping_token_sha256=CUTOVER_TOKEN_DIGEST,
        )
    )
    app.dependency_overrides[get_session] = _fake_session
    return TestClient(app)


@pytest.mark.unit
def test_snapshot_auth_is_fail_closed_and_generic_token_cannot_cross(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kortravelmap.infra.public_api_keys import hash_public_api_key

    path = f"/v1/service/curation-items/{ITEM_ID}/detail-snapshot"
    assert client.get(path).status_code == 401
    assert client.get(path, headers=_headers("generic-service-token")).status_code == 401

    wrong_scope_app = create_app(
        ApiSettings(
            service_token=SecretStr(GENERIC_TOKEN),
            ops_read_token=SecretStr(OPS_TOKEN),
            ops_cancel_token=SecretStr(OPS_CANCEL_TOKEN),
            ops_fixture_token=SecretStr(OPS_FIXTURE_TOKEN),
            pinvi_curation_snapshot_token_sha256=TOKEN_DIGEST,
        )
    )
    wrong_scope_app.dependency_overrides[get_session] = _fake_session
    wrong_scope_client = TestClient(wrong_scope_app)
    monkeypatch.setattr(
        "kortravelmap.api.auth.cached_active_public_api_key_hashes",
        AsyncMock(return_value=frozenset({hash_public_api_key("known-public")})),
    )
    assert (
        wrong_scope_client.get(path, headers=_headers(GENERIC_TOKEN)).status_code
        == 403
    )
    assert wrong_scope_client.get(path, headers=_headers(OPS_TOKEN)).status_code == 403
    assert (
        wrong_scope_client.get(path, headers={OPS_TOKEN_HEADER: OPS_TOKEN}).status_code
        == 403
    )
    assert (
        wrong_scope_client.get(path, headers={PUBLIC_API_KEY_HEADER: "known-public"}).status_code
        == 403
    )
    assert (
        wrong_scope_client.get(path, headers={OPS_TOKEN_HEADER: "unknown-ops"}).status_code
        == 401
    )
    assert (
        wrong_scope_client.get(path, headers={PUBLIC_API_KEY_HEADER: "unknown-public"}).status_code
        == 401
    )
    assert (
        wrong_scope_client.get(path, headers={"Authorization": "Bearer unknown"}).status_code
        == 401
    )


@pytest.mark.unit
def test_item_snapshot_has_exact_shape_etag_and_304(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        module.curation_repo,
        "get_curation_service_item_snapshot",
        AsyncMock(return_value=_item()),
    )
    path = f"/v1/service/curation-items/{ITEM_ID}/detail-snapshot"
    response = client.get(path, headers=_headers())
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {
        "curation_item_id",
        "collection_id",
        "row_revision",
        "etag",
        "updated_at",
        "collection",
        "item",
        "feature",
    }
    assert body["row_revision"] == "7"
    assert body["feature"]["source_record_key"] is None
    assert body["feature"]["feature_id"] == FEATURE_ID
    assert body["item"]["feature_id"] == FEATURE_ID
    assert response.headers["etag"] == f'"{body["etag"]}"'
    payload = dict(body)
    payload.pop("etag")
    assert body["etag"] == f"sha256:{curation_snapshot_sha256(payload)}"

    cached = client.get(
        path,
        headers={**_headers(), "If-None-Match": response.headers["etag"]},
    )
    assert cached.status_code == 304
    assert cached.content == b""


@pytest.mark.unit
def test_collection_snapshot_pages_exact_set_and_rejects_drift(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first_snapshot = _collection(_item(), _item(ITEM_ID_2, revision=8))
    second_snapshot = _collection(
        _item(ITEM_ID_2, revision=8),
        item_count=2,
    )
    stale_snapshot = _collection(
        _item(ITEM_ID_2, revision=8),
        revision=6,
        item_count=2,
    )
    fetch = AsyncMock(side_effect=[first_snapshot, second_snapshot, stale_snapshot])
    monkeypatch.setattr(
        module.curation_repo,
        "get_curation_service_collection_snapshot",
        fetch,
    )
    path = f"/v1/service/curation-collections/{COLLECTION_ID}/detail-snapshot"
    first = client.get(path, headers=_headers(), params={"page_size": 1})
    assert first.status_code == 200
    body = first.json()
    assert body["item_count"] == 2
    assert body["complete"] is False
    assert len(body["items"]) == 1
    assert body["next_cursor"]
    assert first.headers["etag"] == f'"{body["etag"]}"'
    payload = dict(body)
    payload.pop("etag")
    assert body["etag"] == f"sha256:{curation_snapshot_sha256(payload)}"

    second = client.get(
        path,
        headers=_headers(),
        params={"page_size": 1, "cursor": body["next_cursor"]},
    )
    assert second.status_code == 200
    assert second.json()["complete"] is True
    assert second.json()["items"][0]["curation_item_id"] == ITEM_ID_2
    assert second.headers["etag"] == f'"{second.json()["etag"]}"'
    assert fetch.await_args_list[0].kwargs["page_limit"] == 2
    assert fetch.await_args_list[0].kwargs["after_curation_item_id"] is None
    assert fetch.await_args_list[1].kwargs["after_curation_item_id"] == ITEM_ID

    stale = client.get(
        path,
        headers=_headers(),
        params={"page_size": 1, "cursor": body["next_cursor"]},
    )
    assert stale.status_code == 409


@pytest.mark.unit
def test_collection_first_page_supports_exact_304(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        module.curation_repo,
        "get_curation_service_collection_snapshot",
        AsyncMock(return_value=_collection(_item())),
    )
    path = f"/v1/service/curation-collections/{COLLECTION_ID}/detail-snapshot"
    first = client.get(path, headers=_headers())
    cached = client.get(
        path,
        headers={**_headers(), "If-None-Match": first.headers["etag"]},
    )
    assert cached.status_code == 304


@pytest.mark.unit
def test_collection_etag_changes_with_page_representation(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snapshot = _collection(_item(), _item(ITEM_ID_2, revision=8))
    monkeypatch.setattr(
        module.curation_repo,
        "get_curation_service_collection_snapshot",
        AsyncMock(return_value=snapshot),
    )
    path = f"/v1/service/curation-collections/{COLLECTION_ID}/detail-snapshot"
    one = client.get(path, headers=_headers(), params={"page_size": 1})
    two = client.get(
        path,
        headers={**_headers(), "If-None-Match": one.headers["etag"]},
        params={"page_size": 2},
    )

    assert one.status_code == 200
    assert two.status_code == 200
    assert one.headers["etag"] != two.headers["etag"]
    assert one.json()["complete"] is False
    assert two.json()["complete"] is True


@pytest.mark.unit
def test_collection_snapshot_rejects_over_limit_set(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snapshot = _collection(
        item_count=module.curation_repo.CURATION_SERVICE_COLLECTION_MAX_ITEMS + 1,
    )
    monkeypatch.setattr(
        module.curation_repo,
        "get_curation_service_collection_snapshot",
        AsyncMock(return_value=snapshot),
    )
    path = f"/v1/service/curation-collections/{COLLECTION_ID}/detail-snapshot"
    assert client.get(path, headers=_headers()).status_code == 413


@pytest.mark.unit
def test_snapshot_openapi_freezes_scope_and_service_security(client: TestClient) -> None:
    paths = client.get("/openapi.json").json()["paths"]
    for path in (
        "/v1/service/curation-items/{curation_item_id}/detail-snapshot",
        "/v1/service/curation-collections/{collection_id}/detail-snapshot",
    ):
        operation = paths[path]["get"]
        assert operation["x-required-service-scope"] == "pinvi:curation-snapshot:read"
        assert operation["security"] == [{"ServiceToken": []}]
        if_none_match = next(
            parameter
            for parameter in operation["parameters"]
            if parameter["in"] == "header" and parameter["name"] == "If-None-Match"
        )
        assert if_none_match["required"] is False
        non_null_header_schema = next(
            schema
            for schema in if_none_match["schema"]["anyOf"]
            if schema.get("type") != "null"
        )
        assert non_null_header_schema["pattern"] == '^"sha256:[0-9a-f]{64}"$'
        assert operation["responses"]["304"]["headers"]["ETag"]["schema"][
            "pattern"
        ] == '^"sha256:[0-9a-f]{64}"$'

    schemas = client.get("/openapi.json").json()["components"]["schemas"]
    item_schema = schemas["CurationItemDetailSnapshot"]
    snapshot_collection_schema = schemas["CurationSnapshotCollection"]
    collection_schema = schemas["CurationCollectionDetailSnapshot"]
    assert snapshot_collection_schema["properties"]["theme_slug"] == {
        "type": "string",
        "maxLength": 128,
        "minLength": 1,
        "title": "Theme Slug",
    }
    assert snapshot_collection_schema["properties"]["theme_name"] == {
        "type": "string",
        "maxLength": 200,
        "minLength": 1,
        "title": "Theme Name",
    }
    assert snapshot_collection_schema["properties"]["title"] == {
        "type": "string",
        "maxLength": 300,
        "minLength": 1,
        "title": "Title",
    }
    assert snapshot_collection_schema["properties"]["edition_key"] == {
        "type": "string",
        "maxLength": 100,
        "title": "Edition Key",
    }
    assert item_schema["properties"]["row_revision"]["pattern"] == "^[1-9][0-9]*$"
    assert item_schema["properties"]["etag"]["pattern"] == "^sha256:[0-9a-f]{64}$"
    assert collection_schema["properties"]["row_revision"]["pattern"] == "^[1-9][0-9]*$"
    assert collection_schema["properties"]["etag"]["pattern"] == "^sha256:[0-9a-f]{64}$"
    assert collection_schema["properties"]["item_set_hash"]["pattern"] == "^[0-9a-f]{64}$"
    assert collection_schema["properties"]["item_set_hash_version"]["const"] == (
        "ktm-db-item-set-v1"
    )
    assert collection_schema["properties"]["item_count"]["maximum"] == 2000
    assert collection_schema["properties"]["items"]["maxItems"] == 200
    assert "413" in paths[
        "/v1/service/curation-collections/{collection_id}/detail-snapshot"
    ]["get"]["responses"]


@pytest.mark.unit
def test_snapshot_canonicalization_normalizes_nfc() -> None:
    assert curation_snapshot_sha256({"name": "카페"}) == curation_snapshot_sha256(
        {"name": unicodedata.normalize("NFD", "카페")}
    )


@pytest.mark.unit
def test_snapshot_http_representation_normalizes_nfc(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    nfd_item = _item()
    object.__setattr__(nfd_item, "feature_name", unicodedata.normalize("NFD", "카페"))
    monkeypatch.setattr(
        module.curation_repo,
        "get_curation_service_item_snapshot",
        AsyncMock(return_value=nfd_item),
    )
    path = f"/v1/service/curation-items/{ITEM_ID}/detail-snapshot"
    response = client.get(path, headers=_headers())
    assert response.status_code == 200
    assert response.json()["feature"]["name"] == "카페"
    assert unicodedata.is_normalized("NFC", response.json()["feature"]["name"])

    cached = client.get(
        path,
        headers={**_headers(), "If-None-Match": response.headers["etag"]},
    )
    assert cached.status_code == 304


@pytest.mark.unit
def test_pinvi_curation_token_digest_empty_string_disables_like_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """compose의 ``${NAME:-}`` 주입(raw pair 미설정)은 unset과 같아야 한다 — 기동 거부 금지."""

    monkeypatch.setenv("KOR_TRAVEL_MAP_API_PINVI_CURATION_SNAPSHOT_TOKEN_SHA256", "")
    monkeypatch.setenv("KOR_TRAVEL_MAP_API_PINVI_CURATION_CUTOVER_MAPPING_TOKEN_SHA256", "")
    settings = ApiSettings()
    assert settings.pinvi_curation_snapshot_token_sha256 is None
    assert settings.pinvi_curation_cutover_mapping_token_sha256 is None
    direct = ApiSettings(
        pinvi_curation_snapshot_token_sha256="",
        pinvi_curation_cutover_mapping_token_sha256="",
    )
    assert direct.pinvi_curation_snapshot_token_sha256 is None
    assert direct.pinvi_curation_cutover_mapping_token_sha256 is None


@pytest.mark.unit
def test_snapshot_token_digest_must_be_lowercase_and_distinct() -> None:
    with pytest.raises(ValidationError):
        ApiSettings(pinvi_curation_snapshot_token_sha256="A" * 64)
    with pytest.raises(ValidationError):
        ApiSettings(pinvi_curation_snapshot_token_sha256="a" * 63)
    with pytest.raises(ValidationError):
        ApiSettings(pinvi_curation_cutover_mapping_token_sha256=" ")
    with pytest.raises(ValidationError):
        ApiSettings(
            service_token=SecretStr(TOKEN),
            pinvi_curation_snapshot_token_sha256=TOKEN_DIGEST,
        )
    with pytest.raises(ValidationError):
        ApiSettings(
            pinvi_curation_snapshot_token_sha256=TOKEN_DIGEST,
            pinvi_curation_cutover_mapping_token_sha256=TOKEN_DIGEST,
        )


@pytest.mark.unit
def test_cutover_mapping_export_is_scoped_keyset_and_closed(
    cutover_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kortravelmap.core.curation_cutover_mapping import (
        CurationCutoverIdentityMappingDigestInput,
        curation_cutover_identity_mapping_root,
    )

    mappings = (
        CurationCutoverIdentityMapping(
            legacy_curated_feature_id="11111111-1111-4111-8111-111111111111",
            collection_id=COLLECTION_ID,
            curation_item_id=ITEM_ID,
            mapping_kind="legacy_projection",
            source_row_hash="a" * 64,
        ),
        CurationCutoverIdentityMapping(
            legacy_curated_feature_id="33333333-3333-4333-8333-333333333333",
            collection_id=COLLECTION_ID,
            curation_item_id=ITEM_ID_2,
            mapping_kind="official_membership",
            source_row_hash="b" * 64,
        ),
    )
    root = curation_cutover_identity_mapping_root(
        CurationCutoverIdentityMappingDigestInput(
            legacy_curated_feature_id=UUID(mapping.legacy_curated_feature_id),
            collection_id=UUID(mapping.collection_id),
            curation_item_id=UUID(mapping.curation_item_id),
            mapping_kind=mapping.mapping_kind,
            source_row_hash=mapping.source_row_hash,
        )
        for mapping in mappings
    )
    export = CurationCutoverIdentityMappingExport(
        mapping_count=len(mappings),
        mapping_root=root,
        mappings=mappings,
    )
    changed = CurationCutoverIdentityMappingExport(
        mapping_count=len(mappings),
        mapping_root="c" * 64,
        mappings=mappings,
    )
    repository = AsyncMock(side_effect=[export, export, changed])
    monkeypatch.setattr(
        module.curation_repo,
        "get_curation_cutover_identity_mapping_export",
        repository,
    )

    path = "/v1/service/curation-cutover/identity-mappings?page_size=1"
    assert cutover_client.get(path).status_code == 401
    assert cutover_client.get(path, headers=_headers()).status_code == 403

    first = cutover_client.get(path, headers=_cutover_headers())
    assert first.status_code == 200, first.text
    body = first.json()
    assert body["mapping_root_version"] == "ktm-curation-cutover-mapping-v1"
    assert body["mapping_count"] == 2
    assert body["mapping_root"] == root
    assert [entry["curation_item_id"] for entry in body["mappings"]] == [ITEM_ID]
    assert body["complete"] is False
    assert body["next_cursor"]

    second = cutover_client.get(
        f"/v1/service/curation-cutover/identity-mappings?cursor={body['next_cursor']}",
        headers=_cutover_headers(),
    )
    assert second.status_code == 200, second.text
    assert [entry["curation_item_id"] for entry in second.json()["mappings"]] == [ITEM_ID_2]
    assert second.json()["complete"] is True

    restarted = cutover_client.get(
        f"/v1/service/curation-cutover/identity-mappings?cursor={body['next_cursor']}",
        headers=_cutover_headers(),
    )
    assert restarted.status_code == 409
    assert repository.await_count == 3
