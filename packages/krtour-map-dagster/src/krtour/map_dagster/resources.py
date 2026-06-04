"""Dagster resource factory.

운영 배포는 이 module의 기본 resource를 그대로 쓰거나, 테스트/특수 배포에서
``Definitions(..., resources={...})``로 교체한다.
"""

from __future__ import annotations

import asyncio
import importlib
import inspect
import threading
from collections.abc import Awaitable, Iterator
from typing import Any, cast

from dagster import InitResourceContext, resource
from krtour.map.client import AsyncKrtourMapClient
from krtour.map.infra.db import make_async_engine
from krtour.map.infra.file_store import S3ObjectStore
from krtour.map.settings import KrtourMapSettings

__all__ = [
    "build_offline_upload_store_from_settings",
    "create_s3_client_from_settings",
    "krtour_map_client_resource",
    "offline_upload_store_resource",
]


def build_offline_upload_store_from_settings(
    settings: KrtourMapSettings,
    *,
    s3_client: Any | None = None,
) -> S3ObjectStore:
    """설정에서 offline upload bucket용 S3 store를 만든다."""
    client = s3_client if s3_client is not None else create_s3_client_from_settings(settings)
    return S3ObjectStore(
        s3_client=client,
        bucket=settings.offline_upload_bucket,
        public_base_url=None,
    )


def create_s3_client_from_settings(settings: KrtourMapSettings) -> Any:
    """boto3 S3 호환 client를 설정에서 생성한다."""
    access_key = settings.object_store_access_key_id
    secret_key = settings.object_store_secret_access_key
    if (access_key is None) != (secret_key is None):
        raise RuntimeError(
            "KRTOUR_MAP_OBJECT_STORE_ACCESS_KEY_ID와 "
            "KRTOUR_MAP_OBJECT_STORE_SECRET_ACCESS_KEY는 함께 설정해야 함."
        )

    boto3 = cast(Any, importlib.import_module("boto3"))
    botocore_config = cast(Any, importlib.import_module("botocore.config"))
    kwargs: dict[str, Any] = {
        "region_name": settings.object_store_region,
        "config": botocore_config.Config(signature_version="s3v4"),
    }
    if settings.object_store_endpoint_url:
        kwargs["endpoint_url"] = settings.object_store_endpoint_url
    if access_key is not None and secret_key is not None:
        kwargs["aws_access_key_id"] = access_key.get_secret_value()
        kwargs["aws_secret_access_key"] = secret_key.get_secret_value()
    return boto3.client("s3", **kwargs)


async def _await_resource_teardown(awaitable: Awaitable[object]) -> None:
    await awaitable


def _run_async_resource_teardown(awaitable: Awaitable[object]) -> None:
    """Dagster sync generator resource teardown에서 async cleanup을 실행한다."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        asyncio.run(_await_resource_teardown(awaitable))
        return

    raised: list[BaseException] = []

    def _runner() -> None:
        try:
            asyncio.run(_await_resource_teardown(awaitable))
        except BaseException as exc:  # pragma: no cover - 아래 re-raise 경로 검증
            raised.append(exc)

    thread = threading.Thread(
        target=_runner,
        name="krtour-map-dagster-resource-teardown",
    )
    thread.start()
    thread.join()
    if raised:
        raise raised[0]


def _dispose_async_engine(engine: Any) -> None:
    dispose_result = engine.dispose()
    if inspect.isawaitable(dispose_result):
        _run_async_resource_teardown(cast("Awaitable[object]", dispose_result))


@resource(description="admin offline upload 원본 파일을 읽는 RustFS/S3 store.")
def offline_upload_store_resource(_context: InitResourceContext) -> S3ObjectStore:
    """Dagster ``offline_upload_store`` 기본 resource."""
    return build_offline_upload_store_from_settings(KrtourMapSettings())


@resource(description="krtour-map app DB에 연결된 AsyncKrtourMapClient.")
def krtour_map_client_resource(
    _context: InitResourceContext,
) -> Iterator[AsyncKrtourMapClient]:
    """Dagster ``krtour_map_client`` 기본 resource."""
    settings = KrtourMapSettings()
    engine = make_async_engine(settings.pg_dsn)
    try:
        yield AsyncKrtourMapClient(engine, settings=settings)
    finally:
        _dispose_async_engine(engine)
