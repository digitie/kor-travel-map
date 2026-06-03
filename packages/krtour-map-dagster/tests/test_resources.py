"""Dagster resource factory 단위 테스트."""

from __future__ import annotations

from io import BytesIO

import pytest
from krtour.map.settings import KrtourMapSettings
from pydantic import SecretStr

from krtour.map_dagster.resources import build_offline_upload_store_from_settings

pytestmark = pytest.mark.filterwarnings(
    "ignore:Parameter `owners` of initializer `SensorDefinition.__init__`"
    ".*:dagster_shared.utils.warnings.BetaWarning"
)


class _FakeS3Client:
    def get_object(self, *, Bucket: str, Key: str) -> dict[str, BytesIO]:
        return {"Body": BytesIO(f"{Bucket}:{Key}".encode())}


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
