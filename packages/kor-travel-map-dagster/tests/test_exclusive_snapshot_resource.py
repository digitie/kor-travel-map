"""국가유산 EX opt-in의 실제 client 연결과 리소스 종료 경계를 검증한다."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import Any, cast

import pytest
from dagster import build_init_resource_context
from kortravelmap.client import AsyncKorTravelMapClient
from kortravelmap.providers.krheritage import DATASET_KEY_HERITAGE, PROVIDER_NAME
from kortravelmap.settings import KorTravelMapSettings
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine

from kortravelmap.dagster import resources

_FLAG = "KOR_TRAVEL_MAP_KRHERITAGE_EXCLUSIVE_SNAPSHOT_ENABLED"


@pytest.mark.parametrize("enabled", [False, True])
@pytest.mark.parametrize("consumer_failed", [False, True])
def test_resource_routes_only_explicit_heritage_option_without_opening_database(
    monkeypatch: pytest.MonkeyPatch, enabled: bool, consumer_failed: bool
) -> None:
    """기본 호출 형태와 pool1을 보존하고 소비자 실패 때도 소유 engine을 정리한다."""
    if enabled:
        monkeypatch.setenv(_FLAG, "true")
    else:
        monkeypatch.delenv(_FLAG, raising=False)
    settings = KorTravelMapSettings(_env_file=None)
    assert settings.krheritage_exclusive_snapshot_enabled is enabled
    monkeypatch.setattr(resources, "KorTravelMapSettings", lambda: settings)
    real_make_engine = resources.make_async_engine
    real_dispose = resources._dispose_async_engine
    engines: list[AsyncEngine] = []
    disposed: list[AsyncEngine] = []
    client_arguments: list[dict[str, Any]] = []

    def forbid_connect(*_args: Any, **_kwargs: Any) -> None:
        pytest.fail("리소스 생성/종료는 DB 연결이나 계획 SQL을 실행하면 안 된다.")

    def make_engine(*args: Any, **kwargs: Any) -> AsyncEngine:
        engine = real_make_engine(*args, **kwargs)
        event.listen(engine.sync_engine, "do_connect", forbid_connect)
        engines.append(engine)
        return engine

    def make_client(engine: AsyncEngine, **kwargs: Any) -> AsyncKorTravelMapClient:
        client_arguments.append(kwargs)
        return AsyncKorTravelMapClient(engine, **kwargs)

    def dispose(engine: AsyncEngine) -> None:
        disposed.append(engine)
        real_dispose(engine)

    monkeypatch.setattr(resources, "make_async_engine", make_engine)
    monkeypatch.setattr(resources, "AsyncKorTravelMapClient", make_client)
    monkeypatch.setattr(resources, "_dispose_async_engine", dispose)
    resource_fn = cast(
        "Callable[[object], Iterator[AsyncKorTravelMapClient]]",
        resources.kor_travel_map_client_resource.resource_fn,
    )
    with build_init_resource_context() as context:
        resource_iter = resource_fn(context)
        try:
            client = next(resource_iter)
            assert isinstance(client, AsyncKorTravelMapClient)
            assert client._engine is engines[0]
            assert engines[0].pool.size() == 1
            assert engines[0].pool._max_overflow == 0
            assert engines[0].pool.checkedout() == 0
            assert disposed == []
            assert len(client_arguments) == 1
            assert client_arguments[0]["settings"] is settings
            if enabled:
                from kortravelmap.infra.exclusive_provider_refresh import (
                    ExclusiveProviderSnapshotOptions,
                )

                assert client_arguments[0]["exclusive_provider_snapshot"] == (
                    ExclusiveProviderSnapshotOptions(
                        provider=PROVIDER_NAME,
                        dataset_key=DATASET_KEY_HERITAGE,
                        source_entity_type="heritage",
                    )
                )
            else:
                assert set(client_arguments[0]) == {"settings"}
            if consumer_failed:
                with pytest.raises(RuntimeError, match="수집 소비자 실패"):
                    resource_iter.throw(RuntimeError("수집 소비자 실패"))
            else:
                with pytest.raises(StopIteration):
                    next(resource_iter)
        finally:
            resource_iter.close()
    assert disposed == engines
    assert len(disposed) == 1
