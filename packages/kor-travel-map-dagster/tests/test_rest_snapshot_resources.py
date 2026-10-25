"""새 기본 resource 초기화는 opt-in이 소비할 때까지 원천 HTTP를 수행하지 않는다."""

from unittest.mock import AsyncMock

from dagster import build_resources

from kortravelmap.dagster import provider_fetchers
from kortravelmap.dagster.assets import feature_place_transport_rest_areas
from kortravelmap.dagster.definitions import DEFAULT_RESOURCE_DEFINITIONS


async def test_rest_capture_resource_is_lazy_until_consumed(monkeypatch):
    capture = object()
    fetch = AsyncMock(return_value=capture)
    monkeypatch.setattr(provider_fetchers, "fetch_transport_rest_area_snapshot", fetch)
    resource = DEFAULT_RESOURCE_DEFINITIONS["rest_snapshot_input"]
    with build_resources({"capture": resource}) as resources:
        fetch.assert_not_called()
        assert await resources.capture() is capture
        fetch.assert_awaited_once()
    assert {"rest_snapshot_runtime", "rest_snapshot_input"} <= (
        feature_place_transport_rest_areas.required_resource_keys
    )
