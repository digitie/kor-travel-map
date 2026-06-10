"""Dagster resource factory 단위 테스트."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from io import BytesIO
from typing import cast

import pytest
from dagster import build_init_resource_context
from krtour.map.settings import KrtourMapSettings
from pydantic import SecretStr

from krtour.map_dagster import resources
from krtour.map_dagster.resources import (
    PROVIDER_RECORD_RESOURCE_SPECS,
    build_offline_upload_store_from_settings,
    build_provider_record_guard_resource,
)

pytestmark = pytest.mark.filterwarnings(
    "ignore:Parameter `owners` of initializer `SensorDefinition.__init__`"
    ".*:dagster_shared.utils.warnings.BetaWarning"
)


class _FakeS3Client:
    def get_object(self, *, Bucket: str, Key: str) -> dict[str, BytesIO]:
        return {"Body": BytesIO(f"{Bucket}:{Key}".encode())}


class _FakeEngine:
    def __init__(self) -> None:
        self.disposed = False

    async def dispose(self) -> None:
        self.disposed = True


class _FakeClient:
    def __init__(self, engine: _FakeEngine, *, settings: KrtourMapSettings) -> None:
        self.engine = engine
        self.settings = settings


async def test_build_offline_upload_store_uses_offline_upload_bucket() -> None:
    settings = KrtourMapSettings(
        object_store_endpoint_url="http://127.0.0.1:9003",
        object_store_region="us-east-1",
        object_store_access_key_id=SecretStr("access"),
        object_store_secret_access_key=SecretStr("secret"),
        offline_upload_bucket="krtour-uploads",
    )

    store = build_offline_upload_store_from_settings(settings, s3_client=_FakeS3Client())
    body = await store.read_bytes("offline-uploads/u1/features.jsonl")

    assert store.bucket == "krtour-uploads"
    assert body == b"krtour-uploads:offline-uploads/u1/features.jsonl"


async def test_krtour_map_client_resource_disposes_engine(monkeypatch: pytest.MonkeyPatch) -> None:
    engine = _FakeEngine()
    monkeypatch.setattr(resources, "make_async_engine", lambda _dsn: engine)
    monkeypatch.setattr(resources, "AsyncKrtourMapClient", _FakeClient)

    resource_fn = cast(
        "Callable[[object], Iterator[_FakeClient]]",
        resources.krtour_map_client_resource.resource_fn,
    )
    resource_iter = resource_fn(build_init_resource_context())
    client = next(resource_iter)

    assert client.engine is engine
    assert engine.disposed is False

    with pytest.raises(StopIteration):
        next(resource_iter)

    assert engine.disposed is True


def test_provider_record_resource_env_mapping() -> None:
    specs = {spec.resource_key: spec for spec in PROVIDER_RECORD_RESOURCE_SPECS}

    assert specs["datagokr_cultural_festivals"].krtour_map_env_names == (
        "KRTOUR_MAP_DATA_GO_KR_SERVICE_KEY",
    )
    assert specs["opinet_stations"].krtour_map_env_names == (
        "KRTOUR_MAP_OPINET_API_KEY",
    )
    assert specs["krex_traffic_notices"].krtour_map_env_names == (
        "KRTOUR_MAP_KREX_EX_API_KEY",
    )
    assert specs["knps_point_records"].source_env_names == ()
    assert specs["tripmate_agent_youtube_features"].krtour_map_env_names == (
        "KRTOUR_MAP_TRIPMATE_AGENT_BASE_URL",
        "KRTOUR_MAP_TRIPMATE_AGENT_API_KEY",
    )
    assert specs["tripmate_agent_youtube_features"].source_env_names == ("API_KEYS",)


def test_provider_record_guard_message_hides_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("KRTOUR_MAP_DATA_GO_KR_SERVICE_KEY", "super-secret-value")
    spec = {
        item.resource_key: item for item in PROVIDER_RECORD_RESOURCE_SPECS
    }["datagokr_cultural_festivals"]
    resource_def = build_provider_record_guard_resource(spec)
    resource_fn = cast("Callable[[object], object]", resource_def.resource_fn)

    with pytest.raises(RuntimeError) as exc_info:
        resource_fn(build_init_resource_context())

    message = str(exc_info.value)
    assert "KRTOUR_MAP_DATA_GO_KR_SERVICE_KEY" in message
    assert "DATA_GO_KR_SERVICE_KEY" in message
    assert "super-secret-value" not in message
    assert "provider public client wiring PR" in message
