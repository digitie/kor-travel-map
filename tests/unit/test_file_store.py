"""S3ObjectStore 단위 테스트."""

from __future__ import annotations

from io import BytesIO

import pytest

from krtour.map.core.exceptions import FileStoreError
from krtour.map.infra.file_store import S3ObjectStore

pytestmark = pytest.mark.unit


class _FakeS3Client:
    def __init__(self) -> None:
        self.objects: dict[tuple[str, str], bytes] = {}
        self.deleted: list[tuple[str, str]] = []

    def put_object(
        self,
        *,
        Bucket: str,
        Key: str,
        Body: bytes,
        ContentType: str,
        Metadata: dict[str, str],
    ) -> dict[str, str]:
        assert ContentType
        assert Metadata is not None
        self.objects[(Bucket, Key)] = Body
        return {"ETag": '"etag-1"'}

    def get_object(self, *, Bucket: str, Key: str) -> dict[str, BytesIO]:
        return {"Body": BytesIO(self.objects[(Bucket, Key)])}

    def delete_object(self, *, Bucket: str, Key: str) -> dict[str, str]:
        self.deleted.append((Bucket, Key))
        self.objects.pop((Bucket, Key), None)
        return {}


async def test_s3_object_store_write_and_read_bytes() -> None:
    client = _FakeS3Client()
    store = S3ObjectStore(
        s3_client=client,
        bucket="krtour-uploads",
        public_base_url="http://127.0.0.1:9003/krtour-uploads",
    )

    stored = await store.write_bytes(
        "offline-uploads/u1/features.jsonl",
        b'{"ok": true}\n',
        content_type="application/jsonl",
        metadata={"provider": "offline-test"},
    )
    body = await store.read_bytes("offline-uploads/u1/features.jsonl")

    assert body == b'{"ok": true}\n'
    assert stored.bucket == "krtour-uploads"
    assert stored.byte_size == 13
    assert stored.checksum_sha256
    assert stored.public_url == (
        "http://127.0.0.1:9003/krtour-uploads/offline-uploads/u1/features.jsonl"
    )
    assert stored.etag == '"etag-1"'

    await store.delete_object("offline-uploads/u1/features.jsonl")
    assert client.deleted == [("krtour-uploads", "offline-uploads/u1/features.jsonl")]
    with pytest.raises(FileStoreError, match="객체 저장소 읽기 실패"):
        await store.read_bytes("offline-uploads/u1/features.jsonl")


async def test_s3_object_store_wraps_read_errors() -> None:
    store = S3ObjectStore(s3_client=_FakeS3Client(), bucket="krtour-uploads")

    with pytest.raises(FileStoreError, match="객체 저장소 읽기 실패"):
        await store.read_bytes("missing.jsonl")
