"""잔존 curated **catalog**(theme/source/rule) HTTP 계약.

T-VN-40C가 `tests/unit/test_curated_routes.py`를 legacy `curated_features` 라우트와
함께 지웠는데, 그 파일에는 40C 이후에도 살아 있는 catalog 명령의 계약 검사가 섞여
있었다(strong ETag·CAS·표현 분리·식별자 검증). 그 몫만 여기로 옮긴다.
"""

from __future__ import annotations

import json

from collections.abc import AsyncIterator

from contextlib import asynccontextmanager

from dataclasses import replace

from datetime import UTC, datetime

from typing import Any, NoReturn

from unittest.mock import AsyncMock

import httpx

import pytest

from fastapi.testclient import TestClient

from kortravelmap.api.app import create_app

from kortravelmap.api.curated_public_schema import (
    PublicCuratedAreaFeatureView,
    PublicCuratedEventFeatureView,
    PublicCuratedNoticeFeatureView,
    PublicCuratedPlaceFeatureView,
    PublicCuratedPriceFeatureView,
    PublicCuratedRouteFeatureView,
    PublicCuratedWeatherFeatureView,
)

from kortravelmap.api.db import get_session

from kortravelmap.api.routers import curated

from kortravelmap.api.settings import ApiSettings

from pydantic import SecretStr

from kortravelmap.infra.curated_repo import (
    CuratedFeature,
    CuratedFeaturePage,
    CuratedSource,
    CuratedSourceRule,
    CuratedTheme,
)

from kortravelmap.settings import KorTravelMapSettings

def test_curated_source_rule_view_accepts_detail_selector() -> None:
    now = datetime(2026, 7, 12, tzinfo=UTC)
    row = CuratedSourceRule(
        rule_id="11111111-1111-1111-1111-111111111111",
        theme_id="22222222-2222-2222-2222-222222222222",
        theme_slug="youtube-food",
        source_id="33333333-3333-3333-3333-333333333333",
        provider_dataset_id=101,
        provider="kor-travel-concierge-youtube",
        dataset_key="youtube_place_candidates",
        place_kind="youtube_place_candidate",
        category=None,
        region_scope={},
        detail_selector={"path": ["payload", "channel_id"], "value": "channel-A"},
        default_action="candidate",
        priority=10,
        enabled=True,
        metadata={},
        created_at=now,
        updated_at=now,
    )

    view = curated._rule_view(row)

    assert view.detail_selector == {
        "path": ["payload", "channel_id"],
        "value": "channel-A",
    }
    assert view.row_revision == "1"

class _RuleApiSession:
    @asynccontextmanager
    async def begin(self) -> AsyncIterator[None]:
        yield

    async def execute(self, statement: object) -> None:
        assert str(statement) == "SET TRANSACTION ISOLATION LEVEL SERIALIZABLE"

def _rule_api_row(*, revision: int, archived: bool = False) -> CuratedSourceRule:
    now = datetime(2026, 8, 13, tzinfo=UTC)
    return CuratedSourceRule(
        rule_id="11111111-1111-4111-8111-111111111111",
        theme_id="22222222-2222-4222-8222-222222222222",
        theme_slug="rule-api",
        source_id="33333333-3333-4333-8333-333333333333",
        provider_dataset_id=101,
        provider="rule-api-provider",
        dataset_key="rule-api-dataset",
        place_kind=None,
        category=None,
        region_scope={},
        detail_selector=None,
        default_action="candidate",
        priority=0,
        enabled=not archived,
        metadata={},
        created_at=now,
        updated_at=now,
        row_revision=revision,
        archived_at=now if archived else None,
    )

def _theme_api_row(*, revision: int, archived: bool = False) -> CuratedTheme:
    now = datetime(2026, 8, 13, tzinfo=UTC)
    return CuratedTheme(
        theme_id="22222222-2222-4222-8222-222222222222",
        theme_slug="theme-api",
        theme_name="테마 API",
        theme_description="테마 설명",
        theme_group="test",
        visibility="admin_only",
        metadata={},
        created_at=now,
        updated_at=now,
        row_revision=revision,
        archived_at=now if archived else None,
        owner_kind="operator",
        owner_provider_dataset_id=None,
    )

def _source_api_row(
    *, revision: int, observation_revision: int = 7, archived: bool = False
) -> CuratedSource:
    now = datetime(2026, 8, 13, tzinfo=UTC)
    return CuratedSource(
        source_id="33333333-3333-4333-8333-333333333333",
        provider_dataset_id=101,
        provider="source-api-provider",
        dataset_key="source-api-dataset",
        source_name="source API",
        source_url=None,
        source_kind="internal",
        license=None,
        update_cycle="daily",
        last_source_modified_at=None,
        last_checked_at=now,
        next_expected_at=None,
        row_count=1,
        freshness_note=None,
        provider_status="implemented",
        metadata={},
        created_at=now,
        updated_at=now,
        row_revision=revision,
        observation_revision=observation_revision,
        archived_at=now if archived else None,
    )

def test_retained_source_http_commands_separate_representation_and_cas_etags(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kortravelmap.api import domain_command_service

    rows = {
        3: _source_api_row(revision=3),
        4: _source_api_row(revision=4),
        5: _source_api_row(revision=5, archived=True),
    }
    get_source = AsyncMock(return_value=rows[3])
    create_source = AsyncMock(return_value=rows[3])
    patch_source = AsyncMock(return_value=rows[4])
    archive_source = AsyncMock(return_value=rows[5])
    monkeypatch.setattr(curated.curated_repo, "get_curated_source", get_source)
    monkeypatch.setattr(
        curated.curated_repo, "create_curated_source_command", create_source
    )
    monkeypatch.setattr(
        curated.curated_repo, "patch_curated_source_command", patch_source
    )
    monkeypatch.setattr(
        curated.curated_repo, "archive_curated_source_command", archive_source
    )

    async def _begin_command(
        _session: object,
        *,
        actor: str,
        operation: str,
        idempotency_key: object,
        payload: object,
    ) -> domain_command_service.DomainCommandHandle:
        del payload
        return domain_command_service.DomainCommandHandle(
            command_id=703,
            actor=actor,
            operation=operation,
            idempotency_key=str(idempotency_key),
            request_fingerprint="c" * 64,
        )

    monkeypatch.setattr(domain_command_service, "begin_domain_command", _begin_command)
    monkeypatch.setattr(
        domain_command_service, "complete_domain_command", AsyncMock()
    )
    app = create_app(
        ApiSettings(
            admin_proxy_secret=None,
            public_api_key_required=False,
            vworld_api_key=None,
        )
    )

    async def _session() -> AsyncIterator[_RuleApiSession]:
        yield _RuleApiSession()

    app.dependency_overrides[get_session] = _session
    client = TestClient(app)
    source_id = rows[3].source_id
    key_prefix = "95200000-0000-4000-8000-00000000000"

    fetched = client.get(f"/v1/admin/curated-sources/{source_id}")
    representation_etag = fetched.headers["etag"]
    cached = client.get(
        f"/v1/admin/curated-sources/{source_id}",
        headers={"If-None-Match": representation_etag},
    )
    created = client.post(
        "/v1/admin/curated-sources",
        json={
            "provider_dataset_id": 101,
            "source_name": "source API",
            "source_kind": "internal",
        },
        headers={"Idempotency-Key": f"{key_prefix}1"},
    )
    missing = client.patch(
        f"/v1/admin/curated-sources/{source_id}",
        json={"source_name": "변경"},
        headers={"Idempotency-Key": f"{key_prefix}2"},
    )
    patched = client.patch(
        f"/v1/admin/curated-sources/{source_id}",
        json={"source_name": "변경"},
        headers={
            "Idempotency-Key": f"{key_prefix}3",
            "If-Match": fetched.json()["data"]["command_etag"],
        },
    )
    archived = client.request(
        "DELETE",
        f"/v1/admin/curated-sources/{source_id}",
        json={"reason_code": "operator_retired"},
        headers={"Idempotency-Key": f"{key_prefix}4", "If-Match": '"4"'},
    )

    assert fetched.status_code == 200
    assert representation_etag.startswith('"sha256:')
    assert fetched.json()["data"]["row_revision"] == "3"
    assert fetched.json()["data"]["observation_revision"] == "7"
    assert fetched.json()["data"]["command_etag"] == '"3"'
    assert cached.status_code == 304
    assert (created.status_code, created.headers["etag"]) == (201, '"3"')
    assert missing.status_code == 428
    assert (patched.status_code, patched.headers["etag"]) == (200, '"4"')
    assert (archived.status_code, archived.headers["etag"]) == (200, '"5"')
    assert create_source.await_args.kwargs["command_id"] == 703
    assert "last_checked_at" not in create_source.await_args.kwargs
    assert patch_source.await_args.kwargs["expected_revision"] == 3
    assert patch_source.await_args.kwargs["updates"] == {"source_name": "변경"}
    assert archive_source.await_args.kwargs["expected_revision"] == 4

def test_retained_theme_http_commands_use_strong_etag_and_typed_repo(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kortravelmap.api import domain_command_service

    rows = {
        3: _theme_api_row(revision=3),
        4: _theme_api_row(revision=4),
        5: _theme_api_row(revision=5, archived=True),
    }
    get_theme = AsyncMock(return_value=rows[3])
    create_theme = AsyncMock(return_value=rows[3])
    patch_theme = AsyncMock(return_value=rows[4])
    archive_theme = AsyncMock(return_value=rows[5])
    monkeypatch.setattr(curated.curated_repo, "get_curated_theme", get_theme)
    monkeypatch.setattr(
        curated.curated_repo, "create_curated_theme_command", create_theme
    )
    monkeypatch.setattr(
        curated.curated_repo, "patch_curated_theme_command", patch_theme
    )
    monkeypatch.setattr(
        curated.curated_repo, "archive_curated_theme_command", archive_theme
    )

    async def _begin_command(
        _session: object,
        *,
        actor: str,
        operation: str,
        idempotency_key: object,
        payload: object,
    ) -> domain_command_service.DomainCommandHandle:
        del payload
        return domain_command_service.DomainCommandHandle(
            command_id=702,
            actor=actor,
            operation=operation,
            idempotency_key=str(idempotency_key),
            request_fingerprint="b" * 64,
        )

    monkeypatch.setattr(domain_command_service, "begin_domain_command", _begin_command)
    monkeypatch.setattr(
        domain_command_service, "complete_domain_command", AsyncMock()
    )
    app = create_app(
        ApiSettings(
            admin_proxy_secret=None,
            public_api_key_required=False,
            vworld_api_key=None,
        )
    )

    async def _session() -> AsyncIterator[_RuleApiSession]:
        yield _RuleApiSession()

    app.dependency_overrides[get_session] = _session
    client = TestClient(app)
    theme_id = rows[3].theme_id
    key_prefix = "95100000-0000-4000-8000-00000000000"

    fetched = client.get(f"/v1/admin/curated-themes/{theme_id}")
    created = client.post(
        "/v1/admin/curated-themes",
        json={
            "theme_slug": "theme-api",
            "theme_name": "테마 API",
            "theme_group": "test",
        },
        headers={"Idempotency-Key": f"{key_prefix}1"},
    )
    missing = client.patch(
        f"/v1/admin/curated-themes/{theme_id}",
        json={"theme_name": "변경"},
        headers={"Idempotency-Key": f"{key_prefix}2"},
    )
    patched = client.patch(
        f"/v1/admin/curated-themes/{theme_id}",
        json={"theme_name": "변경"},
        headers={"Idempotency-Key": f"{key_prefix}3", "If-Match": '"3"'},
    )
    archived = client.request(
        "DELETE",
        f"/v1/admin/curated-themes/{theme_id}",
        json={"reason_code": "operator_retired"},
        headers={"Idempotency-Key": f"{key_prefix}4", "If-Match": '"4"'},
    )

    assert (fetched.status_code, fetched.headers["etag"]) == (200, '"3"')
    assert fetched.json()["data"]["row_revision"] == "3"
    assert (created.status_code, created.headers["etag"]) == (201, '"3"')
    assert missing.status_code == 428
    assert (patched.status_code, patched.headers["etag"]) == (200, '"4"')
    assert (archived.status_code, archived.headers["etag"]) == (200, '"5"')
    assert archived.json()["data"]["archived_at"] is not None
    assert create_theme.await_args.kwargs["command_id"] == 702
    assert create_theme.await_args.kwargs["principal"] == "local-dev"
    assert patch_theme.await_args.kwargs["expected_revision"] == 3
    assert patch_theme.await_args.kwargs["updates"] == {"theme_name": "변경"}
    assert archive_theme.await_args.kwargs["expected_revision"] == 4
    assert archive_theme.await_args.kwargs["reason_code"] == "operator_retired"

def test_retained_rule_http_commands_use_strong_etag_and_typed_repo(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kortravelmap.api import domain_command_service

    rows = {
        3: _rule_api_row(revision=3),
        4: _rule_api_row(revision=4),
        5: _rule_api_row(revision=5, archived=True),
    }
    get_rule = AsyncMock(return_value=rows[3])
    create_rule = AsyncMock(return_value=rows[3])
    patch_rule = AsyncMock(return_value=rows[4])
    archive_rule = AsyncMock(return_value=rows[5])
    monkeypatch.setattr(curated.curated_repo, "get_curated_source_rule", get_rule)
    monkeypatch.setattr(
        curated.curated_repo, "create_curated_source_rule_command", create_rule
    )
    monkeypatch.setattr(
        curated.curated_repo, "patch_curated_source_rule_command", patch_rule
    )
    monkeypatch.setattr(
        curated.curated_repo, "archive_curated_source_rule_command", archive_rule
    )

    async def _begin_command(
        _session: object,
        *,
        actor: str,
        operation: str,
        idempotency_key: object,
        payload: object,
    ) -> domain_command_service.DomainCommandHandle:
        del payload
        return domain_command_service.DomainCommandHandle(
            command_id=701,
            actor=actor,
            operation=operation,
            idempotency_key=str(idempotency_key),
            request_fingerprint="a" * 64,
        )

    monkeypatch.setattr(domain_command_service, "begin_domain_command", _begin_command)
    monkeypatch.setattr(
        domain_command_service, "complete_domain_command", AsyncMock()
    )
    app = create_app(
        ApiSettings(
            admin_proxy_secret=None,
            public_api_key_required=False,
            vworld_api_key=None,
        )
    )

    async def _session() -> AsyncIterator[_RuleApiSession]:
        yield _RuleApiSession()

    app.dependency_overrides[get_session] = _session
    client = TestClient(app)
    rule_id = rows[3].rule_id
    key_prefix = "95000000-0000-4000-8000-00000000000"

    fetched = client.get(f"/v1/admin/curated-source-rules/{rule_id}")
    created = client.post(
        "/v1/admin/curated-source-rules",
        json={"theme_id": rows[3].theme_id, "source_id": rows[3].source_id},
        headers={"Idempotency-Key": f"{key_prefix}1"},
    )
    missing = client.patch(
        f"/v1/admin/curated-source-rules/{rule_id}",
        json={"priority": 9},
        headers={"Idempotency-Key": f"{key_prefix}2"},
    )
    patched = client.patch(
        f"/v1/admin/curated-source-rules/{rule_id}",
        json={"priority": 9},
        headers={
            "Idempotency-Key": f"{key_prefix}3",
            "If-Match": '"3"',
        },
    )
    archived = client.request(
        "DELETE",
        f"/v1/admin/curated-source-rules/{rule_id}",
        json={"reason_code": "operator_retired"},
        headers={
            "Idempotency-Key": f"{key_prefix}4",
            "If-Match": '"4"',
        },
    )

    assert (fetched.status_code, fetched.headers["etag"]) == (200, '"3"')
    assert fetched.json()["data"]["row_revision"] == "3"
    assert (created.status_code, created.headers["etag"]) == (201, '"3"')
    assert missing.status_code == 428
    assert (patched.status_code, patched.headers["etag"]) == (200, '"4"')
    assert (archived.status_code, archived.headers["etag"]) == (200, '"5"')
    assert archived.json()["data"]["archived_at"] is not None
    assert create_rule.await_args.kwargs["command_id"] == 701
    assert create_rule.await_args.kwargs["principal"] == "local-dev"
    assert patch_rule.await_args.kwargs["expected_revision"] == 3
    assert patch_rule.await_args.kwargs["updates"] == {"priority": 9}
    assert patch_rule.await_count == 1
    assert archive_rule.await_args.kwargs["expected_revision"] == 4
    assert archive_rule.await_args.kwargs["reason_code"] == "operator_retired"

@pytest.mark.parametrize(
    ("path", "method", "payload"),
    [
        (
            "/v1/admin/curated-themes/11111111-1111-4111-8111-111111111111",
            "PATCH",
            {"theme_name": None},
        ),
        (
            "/v1/admin/curated-sources/11111111-1111-4111-8111-111111111111",
            "PATCH",
            {"provider_status": None},
        ),
        (
            "/v1/admin/curated-source-rules/not-a-uuid",
            "GET",
            None,
        ),
        (
            "/v1/admin/curated-source-rules/11111111-1111-4111-8111-111111111111",
            "PATCH",
            {"priority": None},
        ),
        (
            "/v1/admin/curated-source-rules/11111111-1111-4111-8111-111111111111",
            "PATCH",
            {"enabled": None},
        ),
    ],
)
def test_retained_catalog_http_rejects_malformed_identifiers_and_nulls(
    path: str,
    method: str,
    payload: dict[str, object] | None,
) -> None:
    app = create_app(
        ApiSettings(
            admin_proxy_secret=None,
            public_api_key_required=False,
            vworld_api_key=None,
        )
    )

    async def _session() -> AsyncIterator[object]:
        yield object()

    # FastAPI는 path/body 422를 확정하기 전에 dependency graph를 해소한다. 이 테스트는
    # DB가 아니라 HTTP validation 경계를 보므로 실제 runtime DSN을 열지 않는다.
    app.dependency_overrides[get_session] = _session
    client = TestClient(app)
    headers = {
        "Idempotency-Key": "96000000-0000-4000-8000-000000000001",
        "If-Match": '"1"',
    }
    response = client.request(method, path, json=payload, headers=headers)
    assert response.status_code == 422
