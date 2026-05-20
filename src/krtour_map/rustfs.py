from __future__ import annotations

import hashlib
import hmac
import os
import re
import tomllib
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal
from urllib.parse import quote, urlencode, urlsplit, urlunsplit
from urllib.request import Request, urlopen
from uuid import UUID, uuid4
from xml.etree import ElementTree

StorageUploadPurpose = Literal["feature_file", "media_asset", "avatar", "trip_attachment"]
RustfsRequester = Callable[[Request], bytes]

DEFAULT_RUSTFS_ENDPOINT_URL = "http://127.0.0.1:19000"
DEFAULT_RUSTFS_CONSOLE_URL = "http://127.0.0.1:19001"
DEFAULT_RUSTFS_REGION = "us-east-1"
DEFAULT_RUSTFS_BUCKET = "tripmate-media"
DEFAULT_RUSTFS_CONFIG_PATH = ".krtour-map/rustfs.toml"
DEFAULT_RUSTFS_ALLOWED_CONTENT_TYPES = (
    "image/jpeg",
    "image/png",
    "image/webp",
    "image/gif",
    "video/mp4",
    "audio/mpeg",
    "audio/mp4",
    "application/pdf",
)

_SAFE_BUCKET_RE = re.compile(r"^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$")
_SAFE_EXTENSION_RE = re.compile(r"^[A-Za-z0-9]{1,12}$")
_FALLBACK_EXTENSIONS = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
    "video/mp4": ".mp4",
    "audio/mpeg": ".mp3",
    "audio/mp4": ".m4a",
    "application/pdf": ".pdf",
}


class RustfsError(Exception):
    """Base error for RustFS configuration and S3-compatible operations."""


class RustfsConfigurationError(RustfsError):
    """Raised when RustFS settings are incomplete or invalid."""


class RustfsHttpError(RustfsError):
    """Raised when RustFS returns an unusable HTTP response."""


@dataclass(frozen=True)
class RustfsSettings:
    enabled: bool = True
    endpoint_url: str = DEFAULT_RUSTFS_ENDPOINT_URL
    public_endpoint_url: str | None = DEFAULT_RUSTFS_ENDPOINT_URL
    public_base_url: str | None = None
    console_url: str = DEFAULT_RUSTFS_CONSOLE_URL
    region: str = DEFAULT_RUSTFS_REGION
    bucket: str = DEFAULT_RUSTFS_BUCKET
    access_key_id: str | None = None
    secret_access_key: str | None = None
    upload_url_expires_seconds: int = 900
    max_upload_bytes: int = 10 * 1024 * 1024
    allowed_content_types: tuple[str, ...] = DEFAULT_RUSTFS_ALLOWED_CONTENT_TYPES

    @property
    def is_configured(self) -> bool:
        return bool(self.access_key_id and self.secret_access_key and self.bucket)


@dataclass(frozen=True)
class PresignedUpload:
    bucket: str
    storage_key: str
    upload_url: str
    headers: dict[str, str]
    expires_at: datetime
    public_url: str | None


@dataclass(frozen=True)
class RustfsObject:
    key: str
    size: int | None = None
    last_modified: datetime | None = None
    etag: str | None = None
    storage_class: str | None = None


@dataclass(frozen=True)
class RustfsObjectListing:
    bucket: str
    prefix: str = ""
    objects: tuple[RustfsObject, ...] = ()
    is_truncated: bool = False
    next_continuation_token: str | None = None


class RustfsStorage:
    """Small RustFS/S3 utility owned by python-krtour-map.

    TripMate can keep using the same settings shape while this library owns
    feature-file object key and presigned URL logic.
    """

    def __init__(self, settings: RustfsSettings) -> None:
        self.settings = settings

    @property
    def is_configured(self) -> bool:
        return self.settings.is_configured

    def public_object_url(self, storage_key: str) -> str | None:
        if not self.settings.public_base_url:
            return None
        return f"{self.settings.public_base_url.rstrip('/')}/{quote(storage_key, safe='/')}"

    def create_presigned_upload(
        self,
        *,
        user_id: UUID,
        filename: str,
        content_type: str,
        content_length: int,
        purpose: StorageUploadPurpose = "feature_file",
    ) -> PresignedUpload:
        self._ensure_configured()
        self._validate_bucket()
        self._validate_upload(content_type=content_type, content_length=content_length)

        now = datetime.now(UTC)
        storage_key = self.build_upload_key(
            user_id=user_id,
            purpose=purpose,
            filename=filename,
            content_type=content_type,
            now=now,
        )
        expires_at = now + timedelta(seconds=self.settings.upload_url_expires_seconds)
        headers = {"Content-Type": content_type}
        upload_url = self._presign_url(
            method="PUT",
            storage_key=storage_key,
            headers=headers,
            expires_seconds=self.settings.upload_url_expires_seconds,
            now=now,
        )
        return PresignedUpload(
            bucket=self.settings.bucket,
            storage_key=storage_key,
            upload_url=upload_url,
            headers=headers,
            expires_at=expires_at,
            public_url=self.public_object_url(storage_key),
        )

    def build_upload_key(
        self,
        *,
        user_id: UUID,
        purpose: StorageUploadPurpose,
        filename: str,
        content_type: str,
        now: datetime,
    ) -> str:
        extension = _safe_extension(filename) or _FALLBACK_EXTENSIONS.get(content_type, "")
        return f"user-uploads/{purpose}/{user_id}/{now:%Y/%m}/{uuid4().hex}{extension.lower()}"

    def _ensure_configured(self) -> None:
        if not self.is_configured:
            raise RustfsConfigurationError("RustFS access key and secret key are required.")

    def _validate_bucket(self) -> None:
        if not _SAFE_BUCKET_RE.fullmatch(self.settings.bucket):
            raise RustfsConfigurationError("RustFS bucket name is invalid.")

    def _validate_upload(self, *, content_type: str, content_length: int) -> None:
        if content_type not in self.settings.allowed_content_types:
            raise RustfsConfigurationError(f"Unsupported upload content type: {content_type}")
        if content_length <= 0:
            raise RustfsConfigurationError("Upload content length must be greater than zero.")
        if content_length > self.settings.max_upload_bytes:
            raise RustfsConfigurationError(
                f"Upload content length exceeds {self.settings.max_upload_bytes} bytes."
            )

    def _presign_url(
        self,
        *,
        method: str,
        storage_key: str,
        headers: dict[str, str],
        expires_seconds: int,
        now: datetime,
    ) -> str:
        endpoint = urlsplit(self.settings.public_endpoint_url or self.settings.endpoint_url)
        if not endpoint.scheme or not endpoint.netloc:
            raise RustfsConfigurationError("RustFS endpoint URL must include scheme and host.")

        amz_date = now.strftime("%Y%m%dT%H%M%SZ")
        date_stamp = now.strftime("%Y%m%d")
        credential_scope = f"{date_stamp}/{self.settings.region}/s3/aws4_request"
        signed_header_values = {
            "host": endpoint.netloc,
            **{key.lower(): value for key, value in headers.items()},
        }
        signed_headers = ";".join(sorted(signed_header_values))
        query_parameters = {
            "X-Amz-Algorithm": "AWS4-HMAC-SHA256",
            "X-Amz-Credential": f"{self.settings.access_key_id}/{credential_scope}",
            "X-Amz-Date": amz_date,
            "X-Amz-Expires": str(expires_seconds),
            "X-Amz-SignedHeaders": signed_headers,
        }
        canonical_uri = _canonical_object_path(endpoint.path, self.settings.bucket, storage_key)
        canonical_request = "\n".join(
            [
                method,
                canonical_uri,
                _canonical_query_string(query_parameters),
                "".join(
                    f"{name}:{_normalize_header_value(value)}\n"
                    for name, value in sorted(signed_header_values.items())
                ),
                signed_headers,
                "UNSIGNED-PAYLOAD",
            ]
        )
        signature = _signature(
            canonical_request=canonical_request,
            amz_date=amz_date,
            date_stamp=date_stamp,
            region=self.settings.region,
            secret_access_key=str(self.settings.secret_access_key),
            credential_scope=credential_scope,
        )
        signed_query = _canonical_query_string(
            {**query_parameters, "X-Amz-Signature": signature}
        )
        return urlunsplit((endpoint.scheme, endpoint.netloc, canonical_uri, signed_query, ""))


class RustfsS3Client:
    """Minimal signed S3-compatible client for debug listing and smoke tests."""

    def __init__(
        self,
        settings: RustfsSettings,
        *,
        requester: RustfsRequester | None = None,
        timeout: float = 10.0,
    ) -> None:
        self.settings = settings
        self.requester = requester
        self.timeout = timeout

    def list_objects(
        self,
        *,
        bucket: str | None = None,
        prefix: str = "",
        max_keys: int = 100,
        continuation_token: str | None = None,
    ) -> RustfsObjectListing:
        if max_keys <= 0 or max_keys > 1000:
            raise ValueError("max_keys must be between 1 and 1000")
        target_bucket = bucket or self.settings.bucket
        query: dict[str, str] = {
            "list-type": "2",
            "max-keys": str(max_keys),
        }
        if prefix:
            query["prefix"] = prefix
        if continuation_token:
            query["continuation-token"] = continuation_token
        body = self._request("GET", f"/{quote(target_bucket, safe='')}", query=query)
        return _parse_list_objects(body, bucket=target_bucket, prefix=prefix)

    def _request(
        self,
        method: str,
        path: str,
        *,
        query: Mapping[str, str] | None = None,
    ) -> bytes:
        if not self.settings.is_configured:
            raise RustfsConfigurationError("RustFS access key and secret key are required.")
        endpoint = urlsplit(self.settings.endpoint_url)
        if not endpoint.scheme or not endpoint.netloc:
            raise RustfsConfigurationError("RustFS endpoint URL must include scheme and host.")
        normalized_path = f"{endpoint.path.rstrip('/')}{path}" if endpoint.path else path
        query_string = urlencode(dict(query or {}))
        url = urlunsplit((endpoint.scheme, endpoint.netloc, normalized_path, query_string, ""))
        request = Request(url, method=method)
        for key, value in self._signed_headers(
            method=method,
            endpoint=endpoint,
            path=normalized_path,
            query=dict(query or {}),
        ).items():
            request.add_header(key, value)
        if self.requester is not None:
            return self.requester(request)
        try:
            with urlopen(request, timeout=self.timeout) as response:  # noqa: S310
                return response.read()
        except OSError as exc:
            raise RustfsHttpError(str(exc)) from exc

    def _signed_headers(
        self,
        *,
        method: str,
        endpoint: Any,
        path: str,
        query: Mapping[str, str],
    ) -> dict[str, str]:
        now = datetime.now(UTC)
        amz_date = now.strftime("%Y%m%dT%H%M%SZ")
        date_stamp = now.strftime("%Y%m%d")
        credential_scope = f"{date_stamp}/{self.settings.region}/s3/aws4_request"
        headers = {
            "host": endpoint.netloc,
            "x-amz-content-sha256": "UNSIGNED-PAYLOAD",
            "x-amz-date": amz_date,
        }
        signed_headers = ";".join(sorted(headers))
        canonical_request = "\n".join(
            [
                method,
                quote(path, safe="/"),
                _canonical_query_string(query),
                "".join(f"{name}:{headers[name]}\n" for name in sorted(headers)),
                signed_headers,
                "UNSIGNED-PAYLOAD",
            ]
        )
        signature = _signature(
            canonical_request=canonical_request,
            amz_date=amz_date,
            date_stamp=date_stamp,
            region=self.settings.region,
            secret_access_key=str(self.settings.secret_access_key),
            credential_scope=credential_scope,
        )
        authorization = (
            "AWS4-HMAC-SHA256 "
            f"Credential={self.settings.access_key_id}/{credential_scope}, "
            f"SignedHeaders={signed_headers}, Signature={signature}"
        )
        return {**headers, "authorization": authorization}


def rustfs_settings_from_env() -> RustfsSettings:
    allowed = os.getenv("KRTOUR_MAP_RUSTFS_ALLOWED_CONTENT_TYPES") or os.getenv(
        "TRIPMATE_RUSTFS_ALLOWED_CONTENT_TYPES"
    )
    return RustfsSettings(
        enabled=_bool_env("KRTOUR_MAP_RUSTFS_ENABLED", default=True),
        endpoint_url=_env(
            "KRTOUR_MAP_RUSTFS_ENDPOINT_URL",
            "TRIPMATE_RUSTFS_PUBLIC_ENDPOINT_URL",
            "TRIPMATE_RUSTFS_ENDPOINT_URL",
            default=DEFAULT_RUSTFS_ENDPOINT_URL,
        ),
        public_endpoint_url=_env(
            "KRTOUR_MAP_RUSTFS_PUBLIC_ENDPOINT_URL",
            "TRIPMATE_RUSTFS_PUBLIC_ENDPOINT_URL",
            default=DEFAULT_RUSTFS_ENDPOINT_URL,
        ),
        public_base_url=_env(
            "KRTOUR_MAP_RUSTFS_PUBLIC_BASE_URL",
            "TRIPMATE_RUSTFS_PUBLIC_BASE_URL",
        ),
        console_url=_env(
            "KRTOUR_MAP_RUSTFS_CONSOLE_URL",
            "TRIPMATE_RUSTFS_CONSOLE_URL",
            default=DEFAULT_RUSTFS_CONSOLE_URL,
        ),
        region=_env("KRTOUR_MAP_RUSTFS_REGION", "TRIPMATE_RUSTFS_REGION", default="us-east-1"),
        bucket=_env(
            "KRTOUR_MAP_RUSTFS_BUCKET",
            "TRIPMATE_RUSTFS_BUCKET",
            default=DEFAULT_RUSTFS_BUCKET,
        ),
        access_key_id=_env(
            "KRTOUR_MAP_RUSTFS_ACCESS_KEY_ID",
            "TRIPMATE_RUSTFS_ACCESS_KEY_ID",
            "RUSTFS_ACCESS_KEY",
        ),
        secret_access_key=_env(
            "KRTOUR_MAP_RUSTFS_SECRET_ACCESS_KEY",
            "TRIPMATE_RUSTFS_SECRET_ACCESS_KEY",
            "RUSTFS_SECRET_KEY",
        ),
        upload_url_expires_seconds=_int_env(
            "KRTOUR_MAP_RUSTFS_PRESIGNED_URL_EXPIRES_SECONDS",
            "TRIPMATE_RUSTFS_PRESIGNED_URL_EXPIRES_SECONDS",
            default=900,
        ),
        max_upload_bytes=_int_env(
            "KRTOUR_MAP_RUSTFS_MAX_UPLOAD_BYTES",
            "TRIPMATE_RUSTFS_MAX_UPLOAD_BYTES",
            default=10 * 1024 * 1024,
        ),
        allowed_content_types=tuple(_parse_csv_or_json_list(allowed))
        if allowed
        else DEFAULT_RUSTFS_ALLOWED_CONTENT_TYPES,
    )


def rustfs_config_path(path: str | Path | None = None) -> Path:
    if path is not None:
        return Path(path)
    return Path(os.getenv("KRTOUR_MAP_RUSTFS_CONFIG") or DEFAULT_RUSTFS_CONFIG_PATH)


def load_rustfs_settings(path: str | Path | None = None) -> RustfsSettings:
    config_path = rustfs_config_path(path)
    if not config_path.exists():
        return rustfs_settings_from_env()
    with config_path.open("rb") as file:
        data = tomllib.load(file)
    return rustfs_settings_from_mapping(data)


def save_rustfs_settings(settings: RustfsSettings, path: str | Path | None = None) -> Path:
    config_path = rustfs_config_path(path)
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(_settings_to_toml(settings), encoding="utf-8")
    return config_path


def rustfs_settings_from_mapping(data: Mapping[str, Any]) -> RustfsSettings:
    env_defaults = rustfs_settings_from_env()
    return RustfsSettings(
        enabled=_bool_value(data.get("enabled"), default=env_defaults.enabled),
        endpoint_url=str(data.get("endpoint_url") or env_defaults.endpoint_url),
        public_endpoint_url=_optional_str(
            data.get("public_endpoint_url"), default=env_defaults.public_endpoint_url
        ),
        public_base_url=_optional_str(
            data.get("public_base_url"),
            default=env_defaults.public_base_url,
        ),
        console_url=str(data.get("console_url") or env_defaults.console_url),
        region=str(data.get("region") or env_defaults.region),
        bucket=str(data.get("bucket") or env_defaults.bucket),
        access_key_id=_optional_str(data.get("access_key_id"), default=env_defaults.access_key_id),
        secret_access_key=_optional_str(
            data.get("secret_access_key"), default=env_defaults.secret_access_key
        ),
        upload_url_expires_seconds=int(
            data.get("upload_url_expires_seconds") or env_defaults.upload_url_expires_seconds
        ),
        max_upload_bytes=int(data.get("max_upload_bytes") or env_defaults.max_upload_bytes),
        allowed_content_types=tuple(
            str(item)
            for item in data.get("allowed_content_types", env_defaults.allowed_content_types)
        ),
    )


def redacted_rustfs_settings(settings: RustfsSettings) -> dict[str, Any]:
    result = asdict(settings)
    result["secret_access_key"] = "<configured>" if settings.secret_access_key else None
    result["access_key_id"] = "<configured>" if settings.access_key_id else None
    result["is_configured"] = settings.is_configured
    return result


def _parse_list_objects(body: bytes, *, bucket: str, prefix: str) -> RustfsObjectListing:
    root = ElementTree.fromstring(body)
    objects: list[RustfsObject] = []
    for node in _findall(root, "Contents"):
        objects.append(
            RustfsObject(
                key=_findtext(node, "Key") or "",
                size=_int_or_none(_findtext(node, "Size")),
                last_modified=_datetime_or_none(_findtext(node, "LastModified")),
                etag=(_findtext(node, "ETag") or "").strip('"') or None,
                storage_class=_findtext(node, "StorageClass"),
            )
        )
    return RustfsObjectListing(
        bucket=bucket,
        prefix=prefix,
        objects=tuple(item for item in objects if item.key),
        is_truncated=(_findtext(root, "IsTruncated") or "").lower() == "true",
        next_continuation_token=_findtext(root, "NextContinuationToken"),
    )


def _settings_to_toml(settings: RustfsSettings) -> str:
    values = asdict(settings)
    lines = []
    for key, value in values.items():
        if isinstance(value, bool):
            lines.append(f"{key} = {'true' if value else 'false'}")
        elif isinstance(value, int):
            lines.append(f"{key} = {value}")
        elif isinstance(value, tuple | list):
            items = ", ".join(f'"{_escape_toml(str(item))}"' for item in value)
            lines.append(f"{key} = [{items}]")
        elif value is None:
            lines.append(f"{key} = \"\"")
        else:
            lines.append(f'{key} = "{_escape_toml(str(value))}"')
    return "\n".join(lines) + "\n"


def _escape_toml(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _safe_extension(filename: str) -> str:
    name = filename.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    if "." not in name:
        return ""
    extension = name.rsplit(".", 1)[-1]
    if not _SAFE_EXTENSION_RE.fullmatch(extension):
        return ""
    return f".{extension}"


def _canonical_object_path(endpoint_path: str, bucket: str, storage_key: str) -> str:
    base_path = endpoint_path.rstrip("/")
    encoded_bucket = quote(bucket, safe="")
    encoded_key = quote(storage_key, safe="/")
    return (
        f"{base_path}/{encoded_bucket}/{encoded_key}"
        if base_path
        else f"/{encoded_bucket}/{encoded_key}"
    )


def _canonical_query_string(parameters: Mapping[str, str]) -> str:
    return "&".join(
        f"{quote(str(key), safe='-_.~')}={quote(str(value), safe='-_.~')}"
        for key, value in sorted(parameters.items())
    )


def _normalize_header_value(value: str) -> str:
    return " ".join(value.strip().split())


def _signature(
    *,
    canonical_request: str,
    amz_date: str,
    date_stamp: str,
    region: str,
    secret_access_key: str,
    credential_scope: str,
) -> str:
    string_to_sign = "\n".join(
        [
            "AWS4-HMAC-SHA256",
            amz_date,
            credential_scope,
            hashlib.sha256(canonical_request.encode("utf-8")).hexdigest(),
        ]
    )
    signing_key = _signature_key(
        secret_access_key=secret_access_key,
        date_stamp=date_stamp,
        region=region,
    )
    return hmac.new(signing_key, string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()


def _signature_key(*, secret_access_key: str, date_stamp: str, region: str) -> bytes:
    date_key = _sign(("AWS4" + secret_access_key).encode("utf-8"), date_stamp)
    date_region_key = _sign(date_key, region)
    date_region_service_key = _sign(date_region_key, "s3")
    return _sign(date_region_service_key, "aws4_request")


def _sign(key: bytes, message: str) -> bytes:
    return hmac.new(key, message.encode("utf-8"), hashlib.sha256).digest()


def _findall(root: ElementTree.Element, tag: str) -> list[ElementTree.Element]:
    return root.findall(f".//{{*}}{tag}") or root.findall(f".//{tag}")


def _findtext(root: ElementTree.Element, tag: str) -> str | None:
    value = root.findtext(f".//{{*}}{tag}") or root.findtext(f".//{tag}")
    if value is None:
        return None
    text = value.strip()
    return text or None


def _int_or_none(value: str | None) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(str(value))
    except ValueError:
        return None


def _datetime_or_none(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _env(*names: str, default: str | None = None) -> str | None:
    for name in names:
        value = os.getenv(name)
        if value:
            return value
    return default


def _int_env(*names: str, default: int) -> int:
    for name in names:
        value = os.getenv(name)
        if value:
            try:
                return int(value)
            except ValueError:
                return default
    return default


def _bool_env(name: str, *, default: bool) -> bool:
    return _bool_value(os.getenv(name), default=default)


def _bool_value(value: Any, *, default: bool) -> bool:
    if value in (None, ""):
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _optional_str(value: Any, *, default: str | None = None) -> str | None:
    if value in (None, ""):
        return default
    return str(value)


def _parse_csv_or_json_list(value: str) -> tuple[str, ...]:
    text = value.strip()
    if not text:
        return ()
    if text.startswith("[") and text.endswith("]"):
        import json

        loaded = json.loads(text)
        if isinstance(loaded, list):
            return tuple(str(item) for item in loaded)
    return tuple(item.strip() for item in text.split(",") if item.strip())
