"""S3 호환 객체 저장소 클라이언트.

ADR-015 기준으로 본 라이브러리는 RustFS 고유 API가 아니라 boto3 S3 호환 client만
요구한다. 이 모듈의 store는 admin offline upload load job에서 원본 bytes를 읽는
resource로 먼저 사용하고, 이후 feature file 업로드와 admin upload API도 같은
계약을 공유한다.
"""

from __future__ import annotations

import asyncio
import hashlib
import importlib
from dataclasses import dataclass
from typing import Any, cast

from kortravelmap.core.exceptions import FileStoreError

__all__ = [
    "S3ObjectStore",
    "StoredObject",
    "build_s3_object_store",
    "create_s3_client",
]


@dataclass(frozen=True)
class StoredObject:
    """객체 저장 결과 metadata."""

    bucket: str
    object_key: str
    byte_size: int
    checksum_sha256: str
    public_url: str | None = None
    etag: str | None = None


@dataclass(frozen=True)
class S3ObjectStore:
    """boto3 S3 호환 client를 감싸는 async store.

    ``s3_client``는 ``boto3.client("s3")``와 같은 ``get_object``/``put_object``
    메서드를 가진 객체다. boto3 호출은 동기 API이므로 ``asyncio.to_thread``로
    감싸 event loop를 막지 않는다.
    """

    s3_client: Any
    bucket: str
    public_base_url: str | None = None

    async def read_bytes(self, storage_key: str) -> bytes:
        """``storage_key`` 객체를 읽어 bytes로 반환한다."""
        try:
            return await asyncio.to_thread(self._read_bytes_sync, storage_key)
        except FileStoreError:
            raise
        except Exception as exc:
            raise FileStoreError(
                f"객체 저장소 읽기 실패: bucket={self.bucket!r}, key={storage_key!r}"
            ) from exc

    async def write_bytes(
        self,
        storage_key: str,
        body: bytes,
        *,
        content_type: str | None = None,
        metadata: dict[str, str] | None = None,
    ) -> StoredObject:
        """``storage_key``에 bytes를 저장하고 metadata를 반환한다."""
        checksum = hashlib.sha256(body).hexdigest()
        try:
            response = await asyncio.to_thread(
                self.s3_client.put_object,
                Bucket=self.bucket,
                Key=storage_key,
                Body=body,
                ContentType=content_type or "application/octet-stream",
                Metadata=metadata or {},
            )
        except Exception as exc:
            raise FileStoreError(
                f"객체 저장소 쓰기 실패: bucket={self.bucket!r}, key={storage_key!r}"
            ) from exc

        etag = response.get("ETag") if isinstance(response, dict) else None
        return StoredObject(
            bucket=self.bucket,
            object_key=storage_key,
            byte_size=len(body),
            checksum_sha256=checksum,
            public_url=self.public_url(storage_key),
            etag=str(etag) if etag is not None else None,
        )

    async def delete_object(self, storage_key: str) -> None:
        """``storage_key`` 객체를 삭제한다."""
        try:
            await asyncio.to_thread(
                self.s3_client.delete_object,
                Bucket=self.bucket,
                Key=storage_key,
            )
        except Exception as exc:
            raise FileStoreError(
                f"객체 저장소 삭제 실패: bucket={self.bucket!r}, key={storage_key!r}"
            ) from exc

    def public_url(self, storage_key: str) -> str | None:
        """공개 base URL이 설정된 경우 객체 접근 URL을 만든다."""
        if not self.public_base_url:
            return None
        return f"{self.public_base_url.rstrip('/')}/{storage_key.lstrip('/')}"

    def _read_bytes_sync(self, storage_key: str) -> bytes:
        response = self.s3_client.get_object(Bucket=self.bucket, Key=storage_key)
        body = response.get("Body") if isinstance(response, dict) else None
        if body is None or not hasattr(body, "read"):
            raise FileStoreError(
                f"S3 get_object 응답에 Body.read()가 없음: key={storage_key!r}"
            )
        data = body.read()
        if isinstance(data, bytes):
            return data
        raise FileStoreError(f"S3 Body.read() 결과가 bytes가 아님: key={storage_key!r}")


def create_s3_client(
    *,
    region_name: str,
    endpoint_url: str | None = None,
    access_key_id: str | None = None,
    secret_access_key: str | None = None,
) -> Any:
    """설정 값으로 boto3 S3 호환 client를 만든다."""
    if (access_key_id is None) != (secret_access_key is None):
        raise RuntimeError(
            "KOR_TRAVEL_MAP_OBJECT_STORE_ACCESS_KEY_ID와 "
            "KOR_TRAVEL_MAP_OBJECT_STORE_SECRET_ACCESS_KEY는 함께 설정해야 함."
        )

    boto3 = cast(Any, importlib.import_module("boto3"))
    botocore_config = cast(Any, importlib.import_module("botocore.config"))
    kwargs: dict[str, Any] = {
        "region_name": region_name,
        "config": botocore_config.Config(signature_version="s3v4"),
    }
    if endpoint_url:
        kwargs["endpoint_url"] = endpoint_url
    if access_key_id is not None and secret_access_key is not None:
        kwargs["aws_access_key_id"] = access_key_id
        kwargs["aws_secret_access_key"] = secret_access_key
    return boto3.client("s3", **kwargs)


def build_s3_object_store(
    *,
    bucket: str,
    region_name: str,
    endpoint_url: str | None = None,
    access_key_id: str | None = None,
    secret_access_key: str | None = None,
    public_base_url: str | None = None,
    s3_client: Any | None = None,
) -> S3ObjectStore:
    """설정 값 또는 주입 client로 ``S3ObjectStore``를 만든다."""
    client = (
        s3_client
        if s3_client is not None
        else create_s3_client(
            region_name=region_name,
            endpoint_url=endpoint_url,
            access_key_id=access_key_id,
            secret_access_key=secret_access_key,
        )
    )
    return S3ObjectStore(
        s3_client=client,
        bucket=bucket,
        public_base_url=public_base_url,
    )
