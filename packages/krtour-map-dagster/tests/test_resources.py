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
from krtour.map_dagster.resources import build_offline_upload_store_from_settings

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
