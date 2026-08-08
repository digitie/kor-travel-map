"""단건/batch weather 라우터 — DB 무관(repo monkeypatch)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient
from kortravelmap.infra.weather_repo import (
    WEATHER_BATCH_MAX_FEATURE_ID_LENGTH,
    WEATHER_BATCH_MAX_PAIRS,
    WeatherBatchCard,
    WeatherBatchItem,
    WeatherBatchMetricLimitExceededError,
    WeatherBatchPayloadLimitExceededError,
    WeatherBatchQueryTimeoutError,
    WeatherBatchSnapshot,
    WeatherBatchTarget,
    WeatherBatchWorkLimitExceededError,
    WeatherCard,
    WeatherMetric,
)
from sqlalchemy.exc import OperationalError

from kortravelmap.api.app import create_app
from kortravelmap.api.settings import ApiSettings


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app(ApiSettings()))


def _fake_session(client: TestClient) -> None:
    from kortravelmap.api.db import get_session

    async def _fs() -> AsyncIterator[Any]:
        yield object()

    client.app.dependency_overrides[get_session] = _fs


def _snapshot(
    target_at: datetime,
    *items: WeatherBatchItem,
    cards: tuple[WeatherBatchCard, ...] = (),
) -> tuple[WeatherBatchSnapshot, ...]:
    return (WeatherBatchSnapshot(target_at=target_at, items=items, cards=cards),)


@pytest.mark.unit
def test_weather_in_openapi(client: TestClient) -> None:
    spec = client.get("/openapi.json").json()
    assert "/v1/features/{feature_id}/weather" in spec["paths"]
    assert "/v1/features/weather/batch" in spec["paths"]
    assert "FeatureWeatherResponse" in spec["components"]["schemas"]
    assert "WeatherBatchResponse" in spec["components"]["schemas"]
    assert "WeatherBatchCardOut" in spec["components"]["schemas"]
    request_schema = spec["components"]["schemas"]["WeatherBatchRequest"]
    targets = request_schema["properties"]["targets"]
    assert targets["maxItems"] == 366
    target_schema = spec["components"]["schemas"]["WeatherBatchTargetRequest"]
    feature_ids = target_schema["properties"]["feature_ids"]
    assert feature_ids["uniqueItems"] is True
    assert feature_ids["maxItems"] == 200
    assert feature_ids["items"]["minLength"] == 1
    assert feature_ids["items"]["maxLength"] == WEATHER_BATCH_MAX_FEATURE_ID_LENGTH
    operation = spec["paths"]["/v1/features/weather/batch"]["post"]
    assert "413" in operation["responses"]
    single_operation = spec["paths"]["/v1/features/{feature_id}/weather"]["get"]
    assert "413" not in single_operation["responses"]
    assert "503" in single_operation["responses"]
    assert "/v1/features/{feature_id}/weather/snapshot" in spec["paths"]
    assert "/v1/features/{feature_id}/price/snapshot" in spec["paths"]
    feature_id_parameter = next(
        parameter
        for parameter in single_operation["parameters"]
        if parameter["in"] == "path" and parameter["name"] == "feature_id"
    )
    assert feature_id_parameter["schema"]["minLength"] == 1
    assert (
        feature_id_parameter["schema"]["maxLength"]
        == WEATHER_BATCH_MAX_FEATURE_ID_LENGTH
    )


@pytest.mark.unit
def test_weather_card_rejects_oversized_feature_id_before_repo(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from kortravelmap.api.routers import features as mod

    _fake_session(client)

    async def _unexpected_batch(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("oversized feature_id reached repository")

    monkeypatch.setattr(mod.weather_repo, "get_weather_batch_snapshots", _unexpected_batch)
    response = client.get(
        f"/v1/features/{'x' * (WEATHER_BATCH_MAX_FEATURE_ID_LENGTH + 1)}/weather"
    )
    assert response.status_code == 422


@pytest.mark.unit
def test_weather_card_response_maps_metrics(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from kortravelmap.api.routers import features as mod

    valid_at = datetime(2026, 6, 6, 3, 0, tzinfo=UTC)
    card = WeatherCard(
        feature_id="f1",
        source_styles=["short"],
        metrics=[
            WeatherMetric(
                forecast_style="short",
                metric_key="TMP",
                provider_dataset_id=17,
                dataset_key="kma_short_forecast",
                dataset_display_name="기상청 단기예보",
                known_at=valid_at,
                metric_name="기온",
                timeline_bucket="short",
                value_number=Decimal("25.0"),
                value_text=None,
                unit="deg_c",
                severity=None,
                issued_at=None,
                valid_at=valid_at,
                observed_at=None,
                provider="python-kma-api",
                weather_domain="kma_short_forecast",
            )
        ],
        latest_at=valid_at,
        is_stale=False,
    )

    async def _current_card(_s: Any, **kw: Any) -> WeatherCard:
        assert kw == {"feature_id": "f1"}
        return card

    async def _public_row(_s: Any, feature_id: str) -> dict[str, Any]:
        assert feature_id == "f1"
        return {"feature_id": "f1", "kind": "weather", "status": "active"}

    monkeypatch.setattr(mod.weather_repo, "build_weather_card", _current_card)
    monkeypatch.setattr(mod.feature_repo, "get_public_feature_row", _public_row)
    _fake_session(client)
    try:
        r = client.get("/v1/features/f1/weather")
        assert r.status_code == 200
        d = r.json()["data"]
        # T-VN-32C 값 전환 — 단건 card 응답의 feature_id는 UUID 정본
        # (경계 해석 identity의 uuid — repo 조회는 위 target assert대로 legacy 축).
        from kortravelmap.core.ids import feature_uuid_from_legacy

        assert d["feature_id"] == str(feature_uuid_from_legacy("f1"))
        assert d["source_styles"] == ["short"]
        assert len(d["metrics"]) == 1
        assert d["is_stale"] is False
        m = d["metrics"][0]
        assert m["forecast_style"] == "short"
        assert m["metric_key"] == "TMP"
        assert m["value_number"] == 25.0  # Decimal → float
        assert m["unit"] == "deg_c"
        assert m["provider"] == "python-kma-api"
        assert m["weather_domain"] == "kma_short_forecast"
    finally:
        client.app.dependency_overrides.clear()


@pytest.mark.unit
def test_weather_snapshot_requires_explicit_business_and_knowledge_time(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from kortravelmap.api.routers import features as mod

    target_at = datetime(2026, 6, 6, 3, 0, tzinfo=UTC)
    known_at = datetime(2026, 6, 6, 4, 0, tzinfo=UTC)

    async def _snapshot_card(_s: Any, **kw: Any) -> WeatherCard:
        assert kw == {
            "feature_id": "f1",
            "target_at": target_at,
            "known_at": known_at,
        }
        return WeatherCard(
            feature_id="f1",
            source_styles=[],
            metrics=[],
            latest_at=None,
            is_stale=True,
        )

    async def _public_row(_s: Any, feature_id: str) -> dict[str, Any]:
        assert feature_id == "f1"
        return {"feature_id": "f1", "kind": "weather", "status": "active"}

    monkeypatch.setattr(mod.weather_repo, "build_weather_snapshot", _snapshot_card)
    monkeypatch.setattr(mod.feature_repo, "get_public_feature_row", _public_row)
    _fake_session(client)
    try:
        response = client.get(
            "/v1/features/f1/weather/snapshot",
            params={"target_at": target_at.isoformat(), "known_at": known_at.isoformat()},
        )
        assert response.status_code == 200
        assert response.json()["data"]["target_at"] == "2026-06-06T03:00:00Z"
        assert response.json()["data"]["known_at"] == "2026-06-06T04:00:00Z"
    finally:
        client.app.dependency_overrides.clear()


@pytest.mark.unit
def test_weather_snapshot_requires_both_time_axes(
    client: TestClient,
) -> None:
    response = client.get("/v1/features/f1/weather/snapshot")
    assert response.status_code == 422


@pytest.mark.unit
def test_weather_card_404_when_feature_not_public(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """비공개(draft/broken/inactive/hidden/삭제) parent feature의 weather payload는
    노출되지 않는다 — ADR-067 단일 공개 projection, F-1 (T-VN-04)."""
    from kortravelmap.api.routers import features as mod

    async def _none(_s: Any, feature_id: str) -> None:
        assert feature_id == "hidden-f"

    monkeypatch.setattr(mod.feature_repo, "get_public_feature_row", _none)
    _fake_session(client)
    try:
        r = client.get("/v1/features/hidden-f/weather")
        assert r.status_code == 404
    finally:
        client.app.dependency_overrides.clear()


@pytest.mark.unit
@pytest.mark.parametrize(
    ("repo_error", "expected_status", "expected_code", "expected_details"),
    [
        pytest.param(
            WeatherBatchMetricLimitExceededError(actual=20_001, limit=20_000),
            413,
            "WEATHER_BATCH_RESULT_LIMIT_EXCEEDED",
            {"actual": 20_001, "limit": 20_000},
            id="metric-limit",
        ),
        pytest.param(
            WeatherBatchWorkLimitExceededError(actual=150_001, limit=150_000),
            413,
            "WEATHER_BATCH_RESULT_LIMIT_EXCEEDED",
            {
                "actual_series_work": 150_001,
                "limit_series_work": 150_000,
            },
            id="series-work-limit",
        ),
        pytest.param(
            WeatherBatchPayloadLimitExceededError(
                actual=8 * 1024 * 1024 + 1,
                limit=8 * 1024 * 1024,
            ),
            413,
            "WEATHER_BATCH_RESULT_LIMIT_EXCEEDED",
            {
                "actual_bytes": 8 * 1024 * 1024 + 1,
                "limit_bytes": 8 * 1024 * 1024,
            },
            id="payload-limit",
        ),
        pytest.param(
            WeatherBatchQueryTimeoutError("weather batch query exceeded budget"),
            503,
            "WEATHER_BATCH_UNAVAILABLE",
            {},
            id="query-timeout",
        ),
        pytest.param(
            OperationalError("weather batch", {}, OSError("database unavailable")),
            503,
            "WEATHER_BATCH_UNAVAILABLE",
            {},
            id="database",
        ),
    ],
)
def test_weather_batch_maps_repository_failures(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    repo_error: Exception,
    expected_status: int,
    expected_code: str,
    expected_details: dict[str, object],
) -> None:
    from kortravelmap.api.routers import features as mod

    async def _failed(_s: Any, **_kw: Any) -> None:
        raise repo_error

    monkeypatch.setattr(mod.weather_repo, "get_weather_batch_snapshots", _failed)
    _fake_session(client)
    try:
        response = client.post(
            "/v1/features/weather/batch",
            json={
                "targets": [
                    {
                        "target_at": "2026-06-06T03:00:00Z",
                        "feature_ids": ["f1"],
                    }
                ],
                "known_at": "2026-06-06T04:00:00Z",
            },
        )
        assert response.status_code == expected_status
        assert response.headers["content-type"].startswith("application/problem+json")
        problem = response.json()
        assert problem["code"] == expected_code
        assert problem.get("details", {}) == expected_details
        assert "data" not in problem
    finally:
        client.app.dependency_overrides.clear()


@pytest.mark.unit
def test_weather_batch_maps_found_no_data_retired_and_bitemporal_fields(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from kortravelmap.api.routers import features as mod

    target_at = datetime(2026, 7, 30, 0, tzinfo=UTC)
    earlier_at = datetime(2026, 7, 29, 0, tzinfo=UTC)
    known_at = datetime(2026, 7, 29, 12, tzinfo=UTC)
    future_at = datetime(2026, 7, 31, 0, tzinfo=UTC)
    current_metric = WeatherMetric(
        forecast_style="observed",
        metric_key="T1H",
        provider_dataset_id=23,
        dataset_key="rest_area_weather",
        dataset_display_name="휴게소 관측",
        known_at=known_at,
        metric_name="기온",
        timeline_bucket="ultra_short",
        value_number=Decimal("24.5"),
        value_text=None,
        unit="deg_c",
        severity=None,
        issued_at=None,
        valid_at=None,
        observed_at=target_at,
        provider="python-krex-api",
        weather_domain="rest_area_weather",
        effective_at=target_at,
    )
    timeline_metric = WeatherMetric(
        forecast_style="short",
        metric_key="TMP",
        provider_dataset_id=24,
        dataset_key="kma_short_forecast",
        dataset_display_name="기상청 단기예보",
        known_at=known_at,
        metric_name="기온",
        timeline_bucket="short",
        value_number=Decimal("27.0"),
        value_text=None,
        unit="deg_c",
        severity=None,
        issued_at=known_at,
        valid_at=future_at,
        observed_at=None,
        provider="python-kma-api",
        weather_domain="kma_short_forecast",
        effective_at=future_at,
    )

    async def _batch(_s: Any, **kw: Any) -> tuple[WeatherBatchSnapshot, ...]:
        assert kw == {
            "targets": (
                WeatherBatchTarget(
                    target_at=earlier_at,
                    feature_ids=("earlier-no-data",),
                ),
                WeatherBatchTarget(
                    target_at=target_at,
                    feature_ids=("found", "found-peer", "no-data", "retired"),
                ),
            ),
            "known_at": known_at,
        }
        return (
            WeatherBatchSnapshot(
                target_at=earlier_at,
                items=(
                    WeatherBatchItem(
                        feature_id="earlier-no-data",
                        state="no_data",
                        card_key=None,
                    ),
                ),
                cards=(),
            ),
            WeatherBatchSnapshot(
                target_at=target_at,
                items=(
                    WeatherBatchItem(
                        feature_id="found",
                        state="found",
                        card_key="c2",
                    ),
                    WeatherBatchItem(
                        feature_id="found-peer",
                        state="found",
                        card_key="c2",
                    ),
                    WeatherBatchItem(
                        feature_id="no-data",
                        state="no_data",
                        card_key=None,
                    ),
                    WeatherBatchItem(
                        feature_id="retired",
                        state="retired",
                        card_key=None,
                    ),
                ),
                cards=(
                    WeatherBatchCard(
                        card_key="c2",
                        source_styles=["observed", "short"],
                        current=[current_metric],
                        timeline=[timeline_metric],
                        latest_at=target_at,
                        is_stale=False,
                    ),
                ),
            ),
        )

    monkeypatch.setattr(mod.weather_repo, "get_weather_batch_snapshots", _batch)

    # T-VN-32B additive — item feature 참조의 UUID 병행 노출. retired parent는
    # 저장소에 없다고 가정해 map에서 빠진다(None 노출).
    uuid_map = {
        "earlier-no-data": "00000000-0000-5000-8000-000000000001",
        "found": "00000000-0000-5000-8000-000000000002",
        "found-peer": "00000000-0000-5000-8000-000000000003",
        "no-data": "00000000-0000-5000-8000-000000000004",
    }

    async def _uuid_map(_session: Any, feature_ids: Any) -> dict[str, str]:
        assert sorted(feature_ids) == [
            "earlier-no-data",
            "found",
            "found-peer",
            "no-data",
            "retired",
        ]
        return uuid_map

    monkeypatch.setattr(mod.feature_identity, "get_feature_uuid_map", _uuid_map)
    _fake_session(client)
    try:
        response = client.post(
            "/v1/features/weather/batch",
            json={
                "targets": [
                    {
                        "target_at": earlier_at.isoformat(),
                        "feature_ids": ["earlier-no-data"],
                    },
                    {
                        "target_at": target_at.isoformat(),
                        "feature_ids": ["found", "found-peer", "no-data", "retired"],
                    },
                ],
                "known_at": known_at.isoformat(),
            },
        )
        assert response.status_code == 200
        data = response.json()["data"]
        assert data["known_at"] == "2026-07-29T12:00:00Z"
        assert [target["target_at"] for target in data["targets"]] == [
            "2026-07-29T00:00:00Z",
            "2026-07-30T00:00:00Z",
        ]
        assert data["targets"][0]["timeline_until"] == "2026-07-30T00:00:00Z"
        assert data["targets"][0]["items"] == [
            {
                "state": "no_data",
                "feature_id": "earlier-no-data",
                "feature_uuid": uuid_map["earlier-no-data"],
            }
        ]
        later = data["targets"][1]
        assert later["timeline_until"] == "2026-07-31T00:00:00Z"
        assert [item["state"] for item in later["items"]] == [
            "found",
            "found",
            "no_data",
            "retired",
        ]
        found = later["items"][0]
        assert found == {
            "state": "found",
            "feature_id": "found",
            "feature_uuid": uuid_map["found"],
            "card_key": "c2",
        }
        assert later["items"][1] == {
            "state": "found",
            "feature_id": "found-peer",
            "feature_uuid": uuid_map["found-peer"],
            "card_key": "c2",
        }
        assert len(later["cards"]) == 1
        assert later["cards"][0]["card_key"] == "c2"
        assert later["cards"][0]["current"][0]["provider"] == "python-krex-api"
        assert later["cards"][0]["timeline"][0]["valid_at"] == "2026-07-31T00:00:00Z"
        assert (
            later["cards"][0]["timeline"][0]["effective_at"]
            == "2026-07-31T00:00:00Z"
        )
        assert later["items"][2] == {
            "state": "no_data",
            "feature_id": "no-data",
            "feature_uuid": uuid_map["no-data"],
        }
        # 저장소에 없는 retired parent — UUID 병행 노출도 None.
        assert later["items"][3] == {
            "state": "retired",
            "feature_id": "retired",
            "feature_uuid": None,
        }
    finally:
        client.app.dependency_overrides.clear()


@pytest.mark.unit
@pytest.mark.parametrize(
    "body",
    [
        {
            "targets": [
                {
                    "target_at": "2026-07-30T00:00:00Z",
                    "feature_ids": ["same", "same"],
                }
            ],
            "known_at": "2026-07-29T00:00:00Z",
        },
        {
            "targets": [
                {
                    "target_at": "2026-07-30T00:00:00Z",
                    "feature_ids": ["x" * (WEATHER_BATCH_MAX_FEATURE_ID_LENGTH + 1)],
                }
            ],
            "known_at": "2026-07-29T00:00:00Z",
        },
        {
            "targets": [
                {
                    "target_at": "2026-07-30T00:00:00",
                    "feature_ids": ["naive"],
                }
            ],
            "known_at": "2026-07-29T00:00:00Z",
        },
        {
            "targets": [
                {
                    "target_at": "2026-07-30T00:00:00Z",
                    "feature_ids": [""],
                }
            ],
            "known_at": "2026-07-29T00:00:00Z",
        },
        {
            "targets": [
                {
                    "target_at": "9999-12-31T23:59:59.999999Z",
                    "feature_ids": ["overflow"],
                }
            ],
            "known_at": "2026-07-29T00:00:00Z",
        },
        {
            "targets": [
                {
                    "target_at": "2026-07-31T00:00:00Z",
                    "feature_ids": ["later"],
                },
                {
                    "target_at": "2026-07-30T00:00:00Z",
                    "feature_ids": ["earlier"],
                },
            ],
            "known_at": "2026-07-29T00:00:00Z",
        },
        {
            "targets": [
                {
                    "target_at": "2026-07-30T00:00:00Z",
                    "feature_ids": ["first"],
                },
                {
                    "target_at": "2026-07-30T09:00:00+09:00",
                    "feature_ids": ["same-instant"],
                },
            ],
            "known_at": "2026-07-29T00:00:00Z",
        },
    ],
)
def test_weather_batch_rejects_ambiguous_request_before_db(
    client: TestClient, body: dict[str, Any]
) -> None:
    response = client.post("/v1/features/weather/batch", json=body)
    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"


@pytest.mark.unit
def test_weather_batch_rejects_total_pair_budget_before_db(
    client: TestClient,
) -> None:
    targets = [
        {
            "target_at": f"2026-08-{day:02d}T00:00:00Z",
            "feature_ids": [f"f-{day:02d}-{feature_index:03d}" for feature_index in range(200)],
        }
        for day in range(1, WEATHER_BATCH_MAX_PAIRS // 200 + 2)
    ]
    response = client.post(
        "/v1/features/weather/batch",
        json={"targets": targets, "known_at": "2026-07-29T00:00:00Z"},
    )
    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"


@pytest.mark.unit
def test_weather_batch_rejects_planning_work_budget_before_db(
    client: TestClient,
) -> None:
    shared_feature_ids = [f"f-{feature_index:03d}" for feature_index in range(200)]
    targets = [
        {
            "target_at": f"2026-08-{day:02d}T00:00:00Z",
            "feature_ids": shared_feature_ids,
        }
        for day in range(1, 11)
    ]
    response = client.post(
        "/v1/features/weather/batch",
        json={"targets": targets, "known_at": "2026-07-29T00:00:00Z"},
    )
    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"


@pytest.mark.unit
def test_weather_batch_maps_database_failure_to_unavailable(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from kortravelmap.api.routers import features as mod

    async def _failed(_s: Any, **_kw: Any) -> None:
        raise OperationalError("weather batch", {}, OSError("database unavailable"))

    monkeypatch.setattr(mod.weather_repo, "get_weather_batch_snapshots", _failed)
    _fake_session(client)
    try:
        response = client.post(
            "/v1/features/weather/batch",
            json={
                "targets": [
                    {
                        "target_at": "2026-07-30T00:00:00Z",
                        "feature_ids": ["f1"],
                    }
                ],
                "known_at": "2026-07-29T00:00:00Z",
            },
        )
        assert response.status_code == 503
        assert response.headers["content-type"].startswith("application/problem+json")
        assert response.json()["code"] == "WEATHER_BATCH_UNAVAILABLE"
    finally:
        client.app.dependency_overrides.clear()


@pytest.mark.unit
def test_weather_batch_maps_query_timeout_to_unavailable(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from kortravelmap.api.routers import features as mod

    async def _timed_out(_s: Any, **_kw: Any) -> None:
        raise WeatherBatchQueryTimeoutError("weather batch query exceeded budget")

    monkeypatch.setattr(mod.weather_repo, "get_weather_batch_snapshots", _timed_out)
    _fake_session(client)
    try:
        response = client.post(
            "/v1/features/weather/batch",
            json={
                "targets": [
                    {
                        "target_at": "2026-07-30T00:00:00Z",
                        "feature_ids": ["f1"],
                    }
                ],
                "known_at": "2026-07-29T00:00:00Z",
            },
        )
        assert response.status_code == 503
        assert response.headers["content-type"].startswith("application/problem+json")
        problem = response.json()
        assert problem["code"] == "WEATHER_BATCH_UNAVAILABLE"
        assert problem.get("details", {}) == {}
    finally:
        client.app.dependency_overrides.clear()


@pytest.mark.unit
def test_weather_batch_rejects_metric_result_over_budget_without_partial_items(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from kortravelmap.api.routers import features as mod

    async def _too_large(_s: Any, **_kw: Any) -> None:
        raise WeatherBatchMetricLimitExceededError(actual=20_001, limit=20_000)

    monkeypatch.setattr(
        mod.weather_repo,
        "get_weather_batch_snapshots",
        _too_large,
    )
    _fake_session(client)
    try:
        response = client.post(
            "/v1/features/weather/batch",
            json={
                "targets": [
                    {
                        "target_at": "2026-07-30T00:00:00Z",
                        "feature_ids": ["f1"],
                    }
                ],
                "known_at": "2026-07-29T00:00:00Z",
            },
        )
        assert response.status_code == 413
        assert response.headers["content-type"].startswith("application/problem+json")
        problem = response.json()
        assert problem["code"] == "WEATHER_BATCH_RESULT_LIMIT_EXCEEDED"
        assert problem["details"] == {"actual": 20_001, "limit": 20_000}
        assert "data" not in problem
    finally:
        client.app.dependency_overrides.clear()


@pytest.mark.unit
def test_weather_batch_rejects_series_work_over_budget_without_querying_facts(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from kortravelmap.api.routers import features as mod

    async def _too_large(_s: Any, **_kw: Any) -> None:
        raise WeatherBatchWorkLimitExceededError(actual=150_001, limit=150_000)

    monkeypatch.setattr(
        mod.weather_repo,
        "get_weather_batch_snapshots",
        _too_large,
    )
    _fake_session(client)
    try:
        response = client.post(
            "/v1/features/weather/batch",
            json={
                "targets": [
                    {
                        "target_at": "2026-07-30T00:00:00Z",
                        "feature_ids": ["f1"],
                    }
                ],
                "known_at": "2026-07-29T00:00:00Z",
            },
        )
        assert response.status_code == 413
        problem = response.json()
        assert problem["code"] == "WEATHER_BATCH_RESULT_LIMIT_EXCEEDED"
        assert problem["details"] == {
            "actual_series_work": 150_001,
            "limit_series_work": 150_000,
        }
    finally:
        client.app.dependency_overrides.clear()


@pytest.mark.unit
def test_weather_batch_rejects_payload_over_budget_without_partial_items(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from kortravelmap.api.routers import features as mod

    async def _too_large(_s: Any, **_kw: Any) -> None:
        raise WeatherBatchPayloadLimitExceededError(
            actual=8 * 1024 * 1024 + 1,
            limit=8 * 1024 * 1024,
        )

    monkeypatch.setattr(
        mod.weather_repo,
        "get_weather_batch_snapshots",
        _too_large,
    )
    _fake_session(client)
    try:
        response = client.post(
            "/v1/features/weather/batch",
            json={
                "targets": [
                    {
                        "target_at": "2026-07-30T00:00:00Z",
                        "feature_ids": ["f1"],
                    }
                ],
                "known_at": "2026-07-29T00:00:00Z",
            },
        )
        assert response.status_code == 413
        assert response.headers["content-type"].startswith("application/problem+json")
        problem = response.json()
        assert problem["code"] == "WEATHER_BATCH_RESULT_LIMIT_EXCEEDED"
        assert problem["details"] == {
            "actual_bytes": 8 * 1024 * 1024 + 1,
            "limit_bytes": 8 * 1024 * 1024,
        }
        assert "data" not in problem
    finally:
        client.app.dependency_overrides.clear()
