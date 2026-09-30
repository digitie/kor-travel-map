"""Dagster GraphQL URL 분리: backend가 **호출하는** URL과 **보고하는** 공개 URL.

공유 Dagster plane(Manager ADR-54)에서 공개 URL은 Basic Auth gateway다. backend는
loopback webserver를 호출하고, 공개 URL은 응답의 ``graphql_url``로만 보고한다(C7이 그
sha256을 대조한다). 설정이 하나뿐인 오늘 배포에서는 둘이 같아야 한다.

검사는 효과에 건다 — 실제로 POST된 URL과 응답에 실린 URL을 본다.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from kortravelmap.infra.pipeline_repo import PipelineStatusCounts

from kortravelmap.api import dagster_graphql as dagster_mod
from kortravelmap.api import dagster_schedule_service
from kortravelmap.api.app import create_app
from kortravelmap.api.dagster_graphql import DagsterUrlConfigurationError, dagster_urls
from kortravelmap.api.db import get_session
from kortravelmap.api.routers import ops_pipeline as pipeline_mod
from kortravelmap.api.settings import ApiSettings

pytestmark = pytest.mark.unit

_INTERNAL = "http://127.0.0.1:11002/graphql"
_PUBLIC = "https://dagster.example.org/graphql"
_LOOPBACK = ["127.0.0.1", "localhost", "::1"]


def _split_settings(**overrides: Any) -> ApiSettings:
    values: dict[str, Any] = {
        "admin_proxy_secret": None,
        "dagster_url": "http://127.0.0.1:11002",
        "dagster_graphql_url": _PUBLIC,
        "dagster_internal_graphql_url": _INTERNAL,
        "dagster_allowed_hosts": _LOOPBACK,
    }
    values.update(overrides)
    return ApiSettings(**values)


def test_single_url_config_calls_and_reports_the_same_url() -> None:
    """오늘 prod 모양: 공개 URL 하나, 그 host가 allowlist에 있다 — 호출 = 보고."""

    urls = dagster_urls(
        ApiSettings(
            dagster_url="http://127.0.0.1:12702",
            dagster_graphql_url="https://map-dagster.example.org/graphql",
            dagster_allowed_hosts=[*_LOOPBACK, "map-dagster.example.org"],
        )
    )
    assert urls.graphql_url == "https://map-dagster.example.org/graphql"
    assert urls.public_graphql_url == urls.graphql_url


def test_default_config_derives_both_from_dagster_url() -> None:
    urls = dagster_urls(ApiSettings(dagster_url="http://127.0.0.1:12702"))
    assert urls.graphql_url == "http://127.0.0.1:12702/graphql"
    assert urls.public_graphql_url == urls.graphql_url


def test_split_config_calls_loopback_and_reports_public() -> None:
    urls = dagster_urls(_split_settings())
    assert urls.graphql_url == _INTERNAL
    assert urls.public_graphql_url == _PUBLIC


def test_split_config_keeps_the_allowlist_on_the_called_url() -> None:
    with pytest.raises(DagsterUrlConfigurationError, match="dagster_internal_graphql_url"):
        dagster_urls(_split_settings(dagster_internal_graphql_url="http://evil.example/graphql"))
    # 공개 URL을 allowlist에 넣지 않아도 된다 — 호출하지 않는다.
    assert dagster_urls(_split_settings()).public_graphql_url == _PUBLIC
    # 분리하지 않았다면 공개 URL이 곧 호출 URL이므로 allowlist를 지나야 한다.
    with pytest.raises(DagsterUrlConfigurationError, match="dagster_graphql_url"):
        dagster_urls(_split_settings(dagster_internal_graphql_url=None))


@pytest.mark.parametrize(
    "public",
    [
        "https://user:secret@dagster.example.org/graphql",
        "https://dagster.example.org/graphql?token=x",
        "https://dagster.example.org/",
        "ftp://dagster.example.org/graphql",
    ],
)
def test_split_config_still_validates_the_public_url_shape(public: str) -> None:
    with pytest.raises(DagsterUrlConfigurationError, match="dagster_graphql_url"):
        dagster_urls(_split_settings(dagster_graphql_url=public))


def test_blank_internal_env_is_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    """compose의 ``${X:-}``가 넣는 빈 값은 분리가 아니다 — 오늘처럼 공개 URL을 호출한다."""

    monkeypatch.setenv("KOR_TRAVEL_MAP_API_DAGSTER_INTERNAL_GRAPHQL_URL", "")
    settings = ApiSettings(
        dagster_url="http://127.0.0.1:12702",
        dagster_graphql_url="http://127.0.0.1:12702/graphql",
    )
    assert settings.dagster_internal_graphql_url is None
    assert dagster_urls(settings).graphql_url == "http://127.0.0.1:12702/graphql"


class _FakeSession:
    pass


@pytest.fixture
def split_client(monkeypatch: pytest.MonkeyPatch) -> tuple[TestClient, list[str]]:
    app = create_app(_split_settings())
    called: list[str] = []

    async def _fake_session() -> AsyncIterator[_FakeSession]:
        yield _FakeSession()

    async def _fake_counts(_session: Any) -> PipelineStatusCounts:
        return PipelineStatusCounts(
            operations_by_status={}, active_operations=0, failed_operations_24h=0
        )

    async def _no_overrides(_session: Any) -> dict[str, Any]:
        return {}

    async def _fake_post_graphql(**kwargs: Any) -> dict[str, Any]:
        called.append(kwargs["graphql_url"])
        return {"data": {}}

    app.dependency_overrides[get_session] = _fake_session
    monkeypatch.setattr(pipeline_mod, "get_pipeline_status_counts", _fake_counts)
    monkeypatch.setattr(dagster_schedule_service, "schedule_overrides", _no_overrides)
    monkeypatch.setattr(dagster_mod, "post_graphql", _fake_post_graphql)
    return TestClient(app), called


@pytest.mark.parametrize(
    ("path", "projection"),
    [
        ("/v1/ops/pipeline/overview", "dagster"),
        ("/v1/ops/pipeline/dagster-runs", None),
        # C7이 sha256을 대조하는 응답.
        ("/v1/ops/pipeline/schedules", None),
    ],
)
def test_endpoints_post_to_internal_and_report_public(
    split_client: tuple[TestClient, list[str]], path: str, projection: str | None
) -> None:
    client, called = split_client
    with client:
        response = client.get(path)

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    reported = data[projection] if projection else data
    assert called, path
    assert set(called) == {_INTERNAL}
    assert reported["graphql_url"] == _PUBLIC
    assert _INTERNAL not in response.text
