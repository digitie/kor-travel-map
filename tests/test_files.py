from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from krtour_map.files import (
    DownloadedFile,
    FeatureFileSource,
    RustfsFileStore,
    make_feature_file_id,
    make_rustfs_object_key,
    upload_feature_file_sources_to_rustfs,
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
