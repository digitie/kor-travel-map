from __future__ import annotations

import hashlib
import mimetypes
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from io import BytesIO
from pathlib import PurePosixPath
from typing import Any
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from krtour_map.ids import make_payload_hash
from krtour_map.models import FeatureFile

DEFAULT_RUSTFS_FEATURE_FILE_PREFIX = "feature-files"
DEFAULT_FILE_DOWNLOAD_TIMEOUT_SECONDS = 15.0
FileFetcher = Callable[[str], "DownloadedFile"]


@dataclass(frozen=True)
class FeatureFileSource:
    feature_id: str
    source_url: str
    file_type: str = "image"
    role: str = "gallery"
    display_order: int = 0
    alt_text: str | None = None
    provider: str | None = None
    dataset_key: str | None = None
    source_record_key: str | None = None
    payload: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class DownloadedFile:
    data: bytes
    content_type: str | None = None
    width: int | None = None
    height: int | None = None
    payload: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RustfsFileStore:
    """Small S3-compatible RustFS file sink.

    The `client` is expected to expose a `put_object` method. Boto3-style keyword
    calls and MinIO-style positional calls are both supported to keep TripMate's
    resource wiring simple.
    """

    client: Any
    bucket: str
    prefix: str = DEFAULT_RUSTFS_FEATURE_FILE_PREFIX
    public_base_url: str | None = None
    storage_backend: str = "rustfs"

    def upload_source(
        self,
        source: FeatureFileSource,
        *,
        fetch_url: FileFetcher | None = None,
        collected_at: datetime | None = None,
    ) -> FeatureFile:
        fetch = fetch_url or download_url_bytes
        downloaded = fetch(source.source_url)
        checksum = hashlib.sha256(downloaded.data).hexdigest()
        content_type = downloaded.content_type or guess_content_type(source.source_url)
        object_key = make_rustfs_object_key(
            feature_id=source.feature_id,
            source_url=source.source_url,
            role=source.role,
            display_order=source.display_order,
            checksum_sha256=checksum,
            content_type=content_type,
            prefix=self.prefix,
        )
        self._put_object(object_key, downloaded.data, content_type)
        created_at = collected_at or _now_kst()
        return FeatureFile(
            file_id=make_feature_file_id(
                feature_id=source.feature_id,
                bucket=self.bucket,
                object_key=object_key,
                storage_backend=self.storage_backend,
            ),
            feature_id=source.feature_id,
            file_type=source.file_type,
            storage_backend=self.storage_backend,
            bucket=self.bucket,
            object_key=object_key,
            source_url=source.source_url,
            public_url=self.public_url_for(object_key),
            content_type=content_type,
            byte_size=len(downloaded.data),
            checksum_sha256=checksum,
            width=downloaded.width,
            height=downloaded.height,
            role=source.role,
            display_order=source.display_order,
            alt_text=source.alt_text,
            provider=source.provider,
            dataset_key=source.dataset_key,
            source_record_key=source.source_record_key,
            payload={**dict(source.payload), **dict(downloaded.payload)},
            created_at=created_at,
            updated_at=created_at,
        )

    def public_url_for(self, object_key: str) -> str | None:
        if self.public_base_url is None:
            return None
        return f"{self.public_base_url.rstrip('/')}/{object_key.lstrip('/')}"

    def _put_object(self, object_key: str, data: bytes, content_type: str | None) -> None:
        put_object = self.client.put_object
        try:
            put_object(
                Bucket=self.bucket,
                Key=object_key,
                Body=data,
                ContentType=content_type or "application/octet-stream",
            )
        except TypeError:
            put_object(
                self.bucket,
                object_key,
                BytesIO(data),
                len(data),
                content_type=content_type or "application/octet-stream",
            )


def upload_feature_file_sources_to_rustfs(
    store: RustfsFileStore,
    sources: Iterable[FeatureFileSource],
    *,
    fetch_url: FileFetcher | None = None,
    collected_at: datetime | None = None,
) -> tuple[FeatureFile, ...]:
    return tuple(
        store.upload_source(source, fetch_url=fetch_url, collected_at=collected_at)
        for source in sources
    )


def download_url_bytes(
    url: str,
    *,
    timeout: float = DEFAULT_FILE_DOWNLOAD_TIMEOUT_SECONDS,
) -> DownloadedFile:
    request = Request(url, headers={"User-Agent": "python-krtour-map/0.1"})
    with urlopen(request, timeout=timeout) as response:
        data = response.read()
        content_type = response.headers.get_content_type() if response.headers else None
    return DownloadedFile(data=data, content_type=content_type)


def make_feature_file_id(
    *,
    feature_id: str,
    bucket: str,
    object_key: str,
    storage_backend: str = "rustfs",
) -> str:
    digest = make_payload_hash(
        {
            "feature_id": feature_id,
            "storage_backend": storage_backend,
            "bucket": bucket,
            "object_key": object_key,
        },
        length=20,
    )
    return f"ff_{digest}"


def make_rustfs_object_key(
    *,
    feature_id: str,
    source_url: str,
    role: str,
    display_order: int,
    checksum_sha256: str,
    content_type: str | None,
    prefix: str = DEFAULT_RUSTFS_FEATURE_FILE_PREFIX,
) -> str:
    extension = extension_for_content(source_url, content_type)
    safe_role = "".join(char if char.isalnum() or char in ("-", "_") else "-" for char in role)
    filename = f"{display_order:03d}-{safe_role}-{checksum_sha256[:16]}{extension}"
    return str(PurePosixPath(prefix.strip("/")) / feature_id / filename)


def extension_for_content(source_url: str, content_type: str | None) -> str:
    if content_type:
        guessed = mimetypes.guess_extension(content_type.split(";", 1)[0].strip())
        if guessed:
            return guessed
    suffix = PurePosixPath(urlparse(source_url).path).suffix
    if suffix and len(suffix) <= 10:
        return suffix
    return ""


def guess_content_type(source_url: str) -> str | None:
    guessed, _encoding = mimetypes.guess_type(source_url)
    return guessed


def _now_kst() -> datetime:
    from zoneinfo import ZoneInfo

    return datetime.now(ZoneInfo("Asia/Seoul"))
