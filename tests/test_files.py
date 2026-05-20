from __future__ import annotations

from datetime import datetime
from uuid import UUID
from zoneinfo import ZoneInfo

from krtour_map.files import (
    DownloadedFile,
    FeatureFileSource,
    RustfsFileStore,
    make_feature_file_id,
    make_rustfs_object_key,
    upload_feature_file_sources_to_rustfs,
)
from krtour_map.rustfs import (
    RustfsS3Client,
    RustfsSettings,
    RustfsStorage,
    load_rustfs_settings,
    redacted_rustfs_settings,
    save_rustfs_settings,
)


class FakeRustfsClient:
    def __init__(self) -> None:
        self.objects: list[dict[str, object]] = []

    def put_object(self, *, Bucket: str, Key: str, Body: bytes, ContentType: str) -> None:
        self.objects.append(
            {
                "bucket": Bucket,
                "key": Key,
                "body": Body,
                "content_type": ContentType,
            }
        )


def test_upload_feature_file_source_to_rustfs_builds_metadata() -> None:
    client = FakeRustfsClient()
    store = RustfsFileStore(
        client=client,
        bucket="tripmate-feature-files",
        prefix="feature-files",
        public_base_url="https://media.example.com",
    )
    collected_at = datetime(2026, 5, 18, 12, 0, tzinfo=ZoneInfo("Asia/Seoul"))
    source = FeatureFileSource(
        feature_id="f_event_1",
        source_url="https://cdn.example.com/festival.jpg",
        role="primary",
        display_order=0,
        provider="visitkorea",
        dataset_key="visitkorea_festival_events",
        source_record_key="sr_1",
        payload={"visitkorea_field": "first_image"},
    )

    files = upload_feature_file_sources_to_rustfs(
        store,
        [source],
        fetch_url=lambda _url: DownloadedFile(
            data=b"image-bytes",
            content_type="image/jpeg",
            width=800,
            height=600,
        ),
        collected_at=collected_at,
    )

    feature_file = files[0]
    assert len(client.objects) == 1
    assert client.objects[0]["bucket"] == "tripmate-feature-files"
    assert client.objects[0]["content_type"] == "image/jpeg"
    assert feature_file.storage_backend == "rustfs"
    assert feature_file.bucket == "tripmate-feature-files"
    assert feature_file.object_key.startswith("feature-files/f_event_1/000-primary-")
    assert feature_file.object_key.endswith(".jpg")
    assert feature_file.public_url == f"https://media.example.com/{feature_file.object_key}"
    assert feature_file.byte_size == len(b"image-bytes")
    assert feature_file.width == 800
    assert feature_file.height == 600
    assert feature_file.provider == "python-visitkorea-api"
    assert feature_file.created_at == collected_at


def test_feature_file_ids_are_stable_for_rustfs_objects() -> None:
    object_key = make_rustfs_object_key(
        feature_id="f_event_1",
        source_url="https://cdn.example.com/festival",
        role="thumbnail",
        display_order=1,
        checksum_sha256="a" * 64,
        content_type="image/png",
    )

    first = make_feature_file_id(
        feature_id="f_event_1",
        bucket="tripmate-feature-files",
        object_key=object_key,
    )
    second = make_feature_file_id(
        feature_id="f_event_1",
        bucket="tripmate-feature-files",
        object_key=object_key,
    )

    assert object_key == "feature-files/f_event_1/001-thumbnail-aaaaaaaaaaaaaaaa.png"
    assert first == second
    assert first.startswith("ff_")


def test_rustfs_settings_save_load_and_redact(tmp_path) -> None:
    path = tmp_path / "rustfs.toml"
    settings = RustfsSettings(
        endpoint_url="http://127.0.0.1:19000",
        console_url="http://127.0.0.1:19001",
        bucket="tripmate-media",
        access_key_id="tripmate-dev-access",
        secret_access_key="tripmate-dev-secret",
        allowed_content_types=("image/jpeg", "video/mp4", "application/pdf"),
    )

    saved_path = save_rustfs_settings(settings, path)
    restored = load_rustfs_settings(saved_path)
    redacted = redacted_rustfs_settings(restored)

    assert restored.bucket == "tripmate-media"
    assert restored.allowed_content_types == ("image/jpeg", "video/mp4", "application/pdf")
    assert redacted["access_key_id"] == "<configured>"
    assert redacted["secret_access_key"] == "<configured>"


def test_rustfs_storage_presigns_upload_for_feature_files() -> None:
    storage = RustfsStorage(
        RustfsSettings(
            bucket="tripmate-feature-files",
            access_key_id="access",
            secret_access_key="secret",
            allowed_content_types=("image/jpeg", "video/mp4"),
        )
    )

    upload = storage.create_presigned_upload(
        user_id=UUID("00000000-0000-0000-0000-000000000001"),
        filename="heritage.jpg",
        content_type="image/jpeg",
        content_length=128,
    )

    assert upload.bucket == "tripmate-feature-files"
    assert upload.storage_key.startswith(
        "user-uploads/feature_file/00000000-0000-0000-0000-000000000001/"
    )
    assert upload.storage_key.endswith(".jpg")
    assert "X-Amz-Signature=" in upload.upload_url
    assert upload.headers == {"Content-Type": "image/jpeg"}


def test_rustfs_s3_client_lists_objects_with_signed_request() -> None:
    captured = {}

    def requester(request):
        captured["url"] = request.full_url
        captured["authorization"] = request.headers.get("Authorization")
        return b"""<?xml version="1.0" encoding="UTF-8"?>
<ListBucketResult xmlns="http://s3.amazonaws.com/doc/2006-03-01/">
  <Name>tripmate-feature-files</Name>
  <Prefix>feature-files/</Prefix>
  <IsTruncated>false</IsTruncated>
  <Contents>
    <Key>feature-files/f1/000-primary.jpg</Key>
    <LastModified>2026-05-20T00:00:00.000Z</LastModified>
    <ETag>&quot;etag&quot;</ETag>
    <Size>12</Size>
    <StorageClass>STANDARD</StorageClass>
  </Contents>
</ListBucketResult>"""

    client = RustfsS3Client(
        RustfsSettings(
            bucket="tripmate-feature-files",
            access_key_id="access",
            secret_access_key="secret",
        ),
        requester=requester,
    )

    listing = client.list_objects(prefix="feature-files/", max_keys=10)

    assert "list-type=2" in captured["url"]
    assert captured["authorization"].startswith("AWS4-HMAC-SHA256")
    assert listing.bucket == "tripmate-feature-files"
    assert listing.objects[0].key == "feature-files/f1/000-primary.jpg"
    assert listing.objects[0].size == 12
