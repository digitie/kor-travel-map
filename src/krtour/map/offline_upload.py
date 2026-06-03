"""오프라인 업로드 파일 적재 오케스트레이션.

T-208g의 첫 구현 범위는 이미 객체 저장소(RustFS 등)에 올라간 파일을
``ops.offline_uploads`` 메타데이터로 찾아 JSON/JSONL ``FeatureBundle`` 묶음으로
파싱하고, ``ops.import_jobs`` 추적 아래 PostGIS에 적재하는 것이다. CSV/TSV의
provider별 column mapping/validation wizard는 admin API/UI 후속 작업에서 이
동일한 DB 계약과 load job을 사용한다.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import PurePath
from typing import TYPE_CHECKING, Final, Protocol

from pydantic import BaseModel

from krtour.map.dto import (
    AreaDetail,
    EventDetail,
    Feature,
    FeatureBundle,
    NoticeDetail,
    PlaceDetail,
    RouteDetail,
    SourceLink,
    SourceRecord,
)
from krtour.map.infra.advisory_lock import try_advisory_lock
from krtour.map.infra.feature_repo import FeatureLoadResult, load_bundles
from krtour.map.infra.jobs_repo import (
    ImportJob,
    finish_import_job,
    heartbeat_import_job,
    start_import_job,
)
from krtour.map.infra.offline_upload_repo import (
    OfflineUpload,
    finish_offline_upload_load,
    get_offline_upload,
    mark_offline_upload_loading,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

__all__ = [
    "OfflineUploadLoadResult",
    "OfflineUploadObjectStore",
    "OFFLINE_UPLOAD_LOAD_JOB_KIND",
    "parse_offline_feature_bundles",
    "run_offline_upload_load_job",
]

OFFLINE_UPLOAD_LOAD_JOB_KIND: Final[str] = "offline_upload_load"

_LOADABLE_STATES: Final[frozenset[str]] = frozenset(
    {"uploaded", "validated", "loaded", "load_failed"}
)
_DETAIL_MODELS: Final[dict[str, type[BaseModel]]] = {
    "place": PlaceDetail,
    "event": EventDetail,
    "notice": NoticeDetail,
    "route": RouteDetail,
    "area": AreaDetail,
}


class OfflineUploadObjectStore(Protocol):
    """오프라인 업로드 원본을 읽는 객체 저장소 protocol."""

    async def read_bytes(self, storage_key: str) -> bytes:
        """``storage_key``에 해당하는 원본 파일 bytes를 반환한다."""


@dataclass(frozen=True)
class OfflineUploadLoadResult:
    """오프라인 업로드 load job 결과."""

    acquired: bool
    upload: OfflineUpload | None = None
    job: ImportJob | None = None
    load: FeatureLoadResult | None = None
    bytes_read: int = 0
    checksum_sha256: str | None = None
    parsed_format: str | None = None
    error_message: str | None = None

    def as_metadata(self) -> dict[str, object]:
        """Dagster metadata로 기록할 summary."""
        upload_metadata = self.upload.as_metadata() if self.upload is not None else {}
        load = self.load or FeatureLoadResult()
        return {
            **upload_metadata,
            "acquired": self.acquired,
            "job_id": self.job.job_id if self.job is not None else None,
            "job_state": self.job.state if self.job is not None else None,
            "bytes_read": self.bytes_read,
            "checksum_sha256_actual": self.checksum_sha256,
            "parsed_format": self.parsed_format,
            "bundles_total": load.bundles_total,
            "features_inserted": load.features_inserted,
            "features_updated": load.features_updated,
            "source_records_inserted": load.source_records_inserted,
            "source_links_inserted": load.source_links_inserted,
            "source_links_updated": load.source_links_updated,
            "error_message": self.error_message,
        }


async def run_offline_upload_load_job(
    session: AsyncSession,
    upload_id: str,
    *,
    store: OfflineUploadObjectStore,
    dagster_run_id: str | None = None,
) -> OfflineUploadLoadResult:
    """업로드 파일을 읽어 FeatureBundle로 적재한다.

    같은 provider/dataset/scope 단위는 advisory lock으로 직렬화한다. checksum/size
    불일치나 parser 오류는 ``import_jobs.state='failed'``와
    ``offline_uploads.state='load_failed'``로 기록한 뒤 결과의 ``error_message``에
    담아 반환한다. commit/rollback은 호출자 책임이다.
    """
    upload = await get_offline_upload(session, upload_id)
    if upload is None:
        raise ValueError(f"offline upload 없음: {upload_id!r}")
    if upload.state not in _LOADABLE_STATES:
        raise ValueError(
            f"offline upload {upload_id!r}는 load 가능한 상태가 아님: {upload.state!r}"
        )

    async with try_advisory_lock(session, _advisory_key(upload)) as acquired:
        if not acquired:
            return OfflineUploadLoadResult(acquired=False, upload=upload)

        job = await start_import_job(
            session,
            kind=OFFLINE_UPLOAD_LOAD_JOB_KIND,
            payload={
                "upload_id": upload.upload_id,
                "provider": upload.provider,
                "dataset_key": upload.dataset_key,
                "sync_scope": upload.sync_scope,
                "storage_backend": upload.storage_backend,
                "storage_key": upload.storage_key,
                "dagster_run_id": dagster_run_id,
            },
            source_checksum=upload.checksum_sha256,
        )
        upload = (
            await mark_offline_upload_loading(
                session,
                upload_id=upload.upload_id,
                load_job_id=job.job_id,
            )
            or upload
        )

        body = b""
        checksum_actual: str | None = None
        parsed_format = _detected_format(
            upload.detected_format, upload.original_filename
        )
        load_result: FeatureLoadResult | None = None
        error_message: str | None = None

        try:
            await heartbeat_import_job(
                session, job.job_id, progress=10, current_stage="read_object"
            )
            body = await store.read_bytes(upload.storage_key)
            _verify_size(upload, body)
            checksum_actual = hashlib.sha256(body).hexdigest()
            _verify_checksum(upload, checksum_actual)

            await heartbeat_import_job(
                session, job.job_id, progress=30, current_stage="parse_feature_bundles"
            )
            bundles = parse_offline_feature_bundles(
                body,
                detected_format=upload.detected_format,
                detected_encoding=upload.detected_encoding,
                original_filename=upload.original_filename,
            )

            await heartbeat_import_job(
                session, job.job_id, progress=70, current_stage="load_feature_bundles"
            )
            async with session.begin_nested():
                load_result = await load_bundles(session, bundles)
        except Exception as exc:  # noqa: BLE001 - failed job 기록 후 결과로 반환
            error_message = str(exc)
            finished = (
                await finish_import_job(
                    session,
                    job.job_id,
                    state="failed",
                    error_message=error_message,
                )
                or job
            )
            upload = (
                await finish_offline_upload_load(
                    session,
                    upload_id=upload.upload_id,
                    state="load_failed",
                )
                or upload
            )
            return OfflineUploadLoadResult(
                acquired=True,
                upload=upload,
                job=finished,
                load=load_result,
                bytes_read=len(body),
                checksum_sha256=checksum_actual,
                parsed_format=parsed_format,
                error_message=error_message,
            )

        finished = await finish_import_job(session, job.job_id, state="done") or job
        upload = (
            await finish_offline_upload_load(
                session,
                upload_id=upload.upload_id,
                state="loaded",
            )
            or upload
        )
        return OfflineUploadLoadResult(
            acquired=True,
            upload=upload,
            job=finished,
            load=load_result,
            bytes_read=len(body),
            checksum_sha256=checksum_actual,
            parsed_format=parsed_format,
        )


def parse_offline_feature_bundles(
    data: bytes,
    *,
    detected_format: str | None = None,
    detected_encoding: str | None = None,
    original_filename: str | None = None,
) -> list[FeatureBundle]:
    """JSON/JSONL ``FeatureBundle`` 파일을 DTO 목록으로 파싱한다."""
    fmt = _detected_format(detected_format, original_filename)
    text = _decode_bytes(data, detected_encoding)
    if fmt == "jsonl":
        bundles = [
            _bundle_from_payload(json.loads(line))
            for line in text.splitlines()
            if line.strip()
        ]
    elif fmt == "json":
        payload = json.loads(text)
        bundles = _bundles_from_json_payload(payload)
    else:
        raise ValueError(
            "offline upload format은 현재 JSON/JSONL FeatureBundle만 지원함 "
            f"(detected={detected_format!r}, filename={original_filename!r})."
        )
    if not bundles:
        raise ValueError("offline upload FeatureBundle 파일이 비어 있음.")
    return bundles


def _bundles_from_json_payload(payload: object) -> list[FeatureBundle]:
    if isinstance(payload, list):
        return [_bundle_from_payload(item) for item in payload]
    if isinstance(payload, dict):
        items = payload.get("items")
        if items is None:
            items = payload.get("bundles")
        if isinstance(items, list):
            return [_bundle_from_payload(item) for item in items]
        return [_bundle_from_payload(payload)]
    raise TypeError("JSON offline upload payload는 object/list여야 함.")


def _bundle_from_payload(payload: object) -> FeatureBundle:
    if isinstance(payload, FeatureBundle):
        return payload
    if not isinstance(payload, dict):
        return FeatureBundle.model_validate(payload)
    normalized = dict(payload)
    feature_payload = normalized.get("feature")
    if isinstance(feature_payload, dict):
        normalized["feature"] = _feature_from_payload(feature_payload)
    source_record_payload = normalized.get("source_record")
    if isinstance(source_record_payload, dict):
        normalized["source_record"] = SourceRecord.model_validate(source_record_payload)
    source_link_payload = normalized.get("source_link")
    if isinstance(source_link_payload, dict):
        normalized["source_link"] = SourceLink.model_validate(source_link_payload)
    return FeatureBundle.model_validate(normalized)


def _feature_from_payload(payload: dict[str, object]) -> Feature:
    normalized = dict(payload)
    detail_payload = normalized.get("detail")
    kind = normalized.get("kind")
    detail_model = _DETAIL_MODELS.get(str(kind)) if kind is not None else None
    if isinstance(detail_payload, dict) and detail_model is not None:
        normalized["detail"] = detail_model.model_validate(detail_payload)
    return Feature.model_validate(normalized)


def _decode_bytes(data: bytes, detected_encoding: str | None) -> str:
    candidates = [
        value
        for value in (
            detected_encoding,
            "utf-8-sig",
            "utf-8",
            "cp949",
            "euc-kr",
        )
        if value
    ]
    tried: set[str] = set()
    last_error: UnicodeDecodeError | None = None
    for encoding in candidates:
        if encoding in tried:
            continue
        tried.add(encoding)
        try:
            return data.decode(encoding)
        except UnicodeDecodeError as exc:
            last_error = exc
    if last_error is not None:
        raise ValueError(f"offline upload 파일 인코딩을 해석할 수 없음: {tried}") from (
            last_error
        )
    return data.decode()


def _detected_format(
    detected_format: str | None,
    original_filename: str | None,
) -> str:
    raw = (detected_format or "").strip().lower().replace("-", "_")
    if "jsonl" in raw or "ndjson" in raw:
        return "jsonl"
    if raw == "json" or raw.endswith("/json") or "feature_bundle_json" in raw:
        return "json"
    suffix = PurePath(original_filename or "").suffix.lower().lstrip(".")
    if suffix in {"jsonl", "ndjson"}:
        return "jsonl"
    if suffix == "json":
        return "json"
    return raw or suffix or "unknown"


def _verify_size(upload: OfflineUpload, body: bytes) -> None:
    if upload.byte_size != len(body):
        raise ValueError(
            f"offline upload size mismatch: expected={upload.byte_size}, "
            f"actual={len(body)}"
        )


def _verify_checksum(upload: OfflineUpload, checksum_actual: str) -> None:
    if upload.checksum_sha256.lower() != checksum_actual:
        raise ValueError(
            "offline upload checksum mismatch: "
            f"expected={upload.checksum_sha256}, actual={checksum_actual}"
        )


def _advisory_key(upload: OfflineUpload) -> str:
    return f"import:{upload.provider}:{upload.dataset_key}:{upload.sync_scope}"
