"""오프라인 업로드 파일 적재 오케스트레이션.

T-208g의 첫 구현 범위는 이미 객체 저장소(RustFS 등)에 올라간 파일을
``ops.offline_uploads`` 메타데이터로 찾아 JSON/JSONL ``FeatureBundle`` 묶음 또는
검증된 CSV/TSV tabular 원본으로 파싱하고, ``ops.import_jobs`` 추적 아래 PostGIS에
적재하는 것이다. CSV/TSV는 validation job이 저장한 column mapping payload를 load
job이 재사용한다.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import PurePath
from typing import TYPE_CHECKING, Final, Protocol

from pydantic import BaseModel

from krtour.map.core.ids import (
    make_feature_id,
    make_payload_hash,
    make_source_record_key,
)
from krtour.map.dto import (
    Address,
    AreaDetail,
    Coordinate,
    EventDetail,
    Feature,
    FeatureBundle,
    FeatureKind,
    NoticeDetail,
    PlaceDetail,
    RouteDetail,
    SourceLink,
    SourceRecord,
    SourceRole,
)
from krtour.map.infra.advisory_lock import try_advisory_lock
from krtour.map.infra.feature_repo import FeatureLoadResult, load_bundles
from krtour.map.infra.jobs_repo import (
    ImportJob,
    finish_import_job,
    get_import_job,
    heartbeat_import_job,
    start_import_job,
    update_import_job_payload,
)
from krtour.map.infra.offline_upload_repo import (
    OfflineUpload,
    finish_offline_upload_load,
    finish_offline_upload_validation,
    get_offline_upload,
    mark_offline_upload_loading,
    mark_offline_upload_validating,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from krtour.map.geocoding import AddressResolver, ReverseGeocoder

__all__ = [
    "OfflineUploadColumnMapping",
    "OfflineUploadLoadResult",
    "OfflineUploadObjectStore",
    "OfflineUploadTabularPreview",
    "OfflineUploadValidationIssue",
    "OfflineUploadValidationResult",
    "OFFLINE_UPLOAD_LOAD_JOB_KIND",
    "OFFLINE_UPLOAD_VALIDATE_JOB_KIND",
    "parse_offline_feature_bundles",
    "parse_offline_tabular_feature_bundles_async",
    "preview_offline_tabular_upload",
    "run_offline_upload_validation_job",
    "run_offline_upload_load_job",
    "validate_offline_tabular_upload_async",
    "validate_offline_tabular_upload",
]

OFFLINE_UPLOAD_LOAD_JOB_KIND: Final[str] = "offline_upload_load"
OFFLINE_UPLOAD_VALIDATE_JOB_KIND: Final[str] = "offline_upload_validate"

_LOADABLE_STATES: Final[frozenset[str]] = frozenset(
    {"uploaded", "validated", "load_failed"}
)
_VALIDATABLE_STATES: Final[frozenset[str]] = frozenset(
    {"uploaded", "validated", "validation_failed", "load_failed"}
)
_TABULAR_FORMATS: Final[frozenset[str]] = frozenset({"csv", "tsv"})
_DETAIL_MODELS: Final[dict[str, type[BaseModel]]] = {
    "place": PlaceDetail,
    "event": EventDetail,
    "notice": NoticeDetail,
    "route": RouteDetail,
    "area": AreaDetail,
}
_KST: Final[timezone] = timezone(timedelta(hours=9))


class OfflineUploadObjectStore(Protocol):
    """오프라인 업로드 원본을 읽는 객체 저장소 protocol."""

    async def read_bytes(self, storage_key: str) -> bytes:
        """``storage_key``에 해당하는 원본 파일 bytes를 반환한다."""


@dataclass(frozen=True)
class OfflineUploadColumnMapping:
    """CSV/TSV source column → FeatureBundle field 매핑."""

    name: str
    lon: str
    lat: str
    address: str | None = None
    source_id: str | None = None
    bjd_code: str | None = None
    category: str | None = None
    default_category: str = "02020101"
    default_marker_icon: str = "marker"
    default_marker_color: str = "P-01"
    default_place_kind: str = "offline_upload"

    def as_payload(self) -> dict[str, object]:
        """``import_jobs.payload``/HTTP 응답용 dict."""
        return asdict(self)


@dataclass(frozen=True)
class OfflineUploadValidationIssue:
    """CSV/TSV validation issue."""

    severity: str
    code: str
    message: str
    row_number: int | None = None
    column: str | None = None

    def as_payload(self) -> dict[str, object]:
        """``import_jobs.payload``/HTTP 응답용 dict."""
        return asdict(self)


@dataclass(frozen=True)
class OfflineUploadTabularPreview:
    """CSV/TSV header + sample preview."""

    parsed_format: str
    encoding: str
    delimiter: str
    headers: tuple[str, ...]
    sample_rows: tuple[dict[str, str], ...]
    rows_total: int
    rows_sampled: int

    def as_payload(self) -> dict[str, object]:
        """``import_jobs.payload``/HTTP 응답용 dict."""
        return {
            "parsed_format": self.parsed_format,
            "encoding": self.encoding,
            "delimiter": self.delimiter,
            "headers": list(self.headers),
            "sample_rows": list(self.sample_rows),
            "rows_total": self.rows_total,
            "rows_sampled": self.rows_sampled,
        }


@dataclass(frozen=True)
class OfflineUploadValidationResult:
    """CSV/TSV validation 결과."""

    upload: OfflineUpload
    job: ImportJob | None
    column_mapping: OfflineUploadColumnMapping
    parsed_format: str
    encoding: str
    delimiter: str
    headers: tuple[str, ...]
    sample_rows: tuple[dict[str, str], ...]
    rows_total: int
    rows_sampled: int
    valid_rows: int
    error_rows: int
    issues: tuple[OfflineUploadValidationIssue, ...]
    bytes_read: int
    checksum_sha256: str

    @property
    def has_errors(self) -> bool:
        """ERROR severity issue 존재 여부."""
        return any(issue.severity == "error" for issue in self.issues)

    def as_payload(self) -> dict[str, object]:
        """``import_jobs.payload``/HTTP 응답용 dict."""
        return {
            "upload": self.upload.as_metadata(),
            "job_id": self.job.job_id if self.job is not None else None,
            "job_state": self.job.state if self.job is not None else None,
            "column_mapping": self.column_mapping.as_payload(),
            "parsed_format": self.parsed_format,
            "encoding": self.encoding,
            "delimiter": self.delimiter,
            "headers": list(self.headers),
            "sample_rows": list(self.sample_rows),
            "rows_total": self.rows_total,
            "rows_sampled": self.rows_sampled,
            "valid_rows": self.valid_rows,
            "error_rows": self.error_rows,
            "issues": [issue.as_payload() for issue in self.issues],
            "bytes_read": self.bytes_read,
            "checksum_sha256_actual": self.checksum_sha256,
        }


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


async def run_offline_upload_validation_job(
    session: AsyncSession,
    upload_id: str,
    *,
    store: OfflineUploadObjectStore,
    column_mapping: OfflineUploadColumnMapping | Mapping[str, object],
    sample_size: int = 1000,
    operator: str | None = None,
    address_resolver: AddressResolver | None = None,
    reverse_geocoder: ReverseGeocoder | None = None,
) -> OfflineUploadValidationResult:
    """CSV/TSV 업로드 파일을 검증하고 결과를 ``import_jobs.payload``에 저장한다."""
    upload = await get_offline_upload(session, upload_id)
    if upload is None:
        raise ValueError(f"offline upload 없음: {upload_id!r}")
    if upload.state not in _VALIDATABLE_STATES:
        raise ValueError(
            f"offline upload {upload_id!r}는 validation 가능한 상태가 아님: "
            f"{upload.state!r}"
        )
    mapping = normalize_offline_upload_column_mapping(column_mapping)

    async with try_advisory_lock(
        session, f"offline-upload-validate:{upload.upload_id}"
    ) as acquired:
        if not acquired:
            raise ValueError(f"offline upload validation lock 획득 실패: {upload.upload_id}")

        job = await start_import_job(
            session,
            kind=OFFLINE_UPLOAD_VALIDATE_JOB_KIND,
            payload={
                "upload_id": upload.upload_id,
                "provider": upload.provider,
                "dataset_key": upload.dataset_key,
                "sync_scope": upload.sync_scope,
                "storage_backend": upload.storage_backend,
                "storage_key": upload.storage_key,
                "operator": operator,
                "sample_size": sample_size,
                "column_mapping": mapping.as_payload(),
            },
            source_checksum=upload.checksum_sha256,
        )
        marked_validation = await mark_offline_upload_validating(
            session,
            upload_id=upload.upload_id,
            validation_job_id=job.job_id,
        )
        if marked_validation is None:
            raise ValueError(f"offline upload 없음: {upload.upload_id!r}")
        upload = marked_validation

        body = b""
        checksum_actual: str | None = None
        try:
            await heartbeat_import_job(
                session,
                job.job_id,
                progress=10,
                current_stage="read_object",
            )
            body = await store.read_bytes(upload.storage_key)
            _verify_size(upload, body)
            checksum_actual = hashlib.sha256(body).hexdigest()
            _verify_checksum(upload, checksum_actual)

            await heartbeat_import_job(
                session,
                job.job_id,
                progress=50,
                current_stage="validate_tabular_rows",
            )
            result = await validate_offline_tabular_upload_async(
                upload,
                body,
                column_mapping=mapping,
                sample_size=sample_size,
                checksum_sha256=checksum_actual,
                address_resolver=address_resolver,
                reverse_geocoder=reverse_geocoder,
            )
        except Exception as exc:  # noqa: BLE001 - 실패 결과를 job payload로 보존
            result = _failed_validation_result(
                upload,
                column_mapping=mapping,
                body=body,
                checksum_sha256=checksum_actual,
                message=str(exc),
            )

        await update_import_job_payload(session, job.job_id, payload=result.as_payload())

        if result.has_errors:
            finished = (
                await finish_import_job(
                    session,
                    job.job_id,
                    state="failed",
                    error_message=f"offline upload validation failed: {result.error_rows} rows",
                )
                or job
            )
            failed_upload = await finish_offline_upload_validation(
                session,
                upload_id=upload.upload_id,
                state="validation_failed",
            )
            if failed_upload is None:
                raise ValueError(f"offline upload 없음: {upload.upload_id!r}")
            upload = failed_upload
        else:
            finished = await finish_import_job(session, job.job_id, state="done") or job
            validated_upload = await finish_offline_upload_validation(
                session,
                upload_id=upload.upload_id,
                state="validated",
            )
            if validated_upload is None:
                raise ValueError(f"offline upload 없음: {upload.upload_id!r}")
            upload = validated_upload
        final_result = OfflineUploadValidationResult(
            upload=upload,
            job=finished,
            column_mapping=result.column_mapping,
            parsed_format=result.parsed_format,
            encoding=result.encoding,
            delimiter=result.delimiter,
            headers=result.headers,
            sample_rows=result.sample_rows,
            rows_total=result.rows_total,
            rows_sampled=result.rows_sampled,
            valid_rows=result.valid_rows,
            error_rows=result.error_rows,
            issues=result.issues,
            bytes_read=result.bytes_read,
            checksum_sha256=result.checksum_sha256,
        )
        await update_import_job_payload(
            session,
            job.job_id,
            payload=final_result.as_payload(),
        )
        return final_result


async def run_offline_upload_load_job(
    session: AsyncSession,
    upload_id: str,
    *,
    store: OfflineUploadObjectStore,
    dagster_run_id: str | None = None,
    address_resolver: AddressResolver | None = None,
    reverse_geocoder: ReverseGeocoder | None = None,
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
    upload_format = _detected_format(upload.detected_format, upload.original_filename)
    if upload_format in _TABULAR_FORMATS and upload.validation_job_id is None:
        raise ValueError("CSV/TSV offline upload은 load 전 validation이 필요함.")

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
        marked_load = await mark_offline_upload_loading(
            session,
            upload_id=upload.upload_id,
            load_job_id=job.job_id,
        )
        if marked_load is None:
            raise ValueError(f"offline upload 없음: {upload.upload_id!r}")
        upload = marked_load

        body = b""
        checksum_actual: str | None = None
        parsed_format = upload_format
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
            column_mapping = await _load_column_mapping_for_upload(session, upload)
            if parsed_format in _TABULAR_FORMATS:
                if column_mapping is None:
                    raise ValueError(
                        "CSV/TSV offline upload load에는 validation column mapping이 필요함."
                    )
                bundles = await parse_offline_tabular_feature_bundles_async(
                    body,
                    provider=upload.provider,
                    dataset_key=upload.dataset_key,
                    column_mapping=column_mapping,
                    detected_format=upload.detected_format,
                    detected_encoding=upload.detected_encoding,
                    original_filename=upload.original_filename,
                    address_resolver=address_resolver,
                    reverse_geocoder=reverse_geocoder,
                )
            else:
                bundles = parse_offline_feature_bundles(
                    body,
                    detected_format=upload.detected_format,
                    detected_encoding=upload.detected_encoding,
                    original_filename=upload.original_filename,
                    provider=upload.provider,
                    dataset_key=upload.dataset_key,
                    column_mapping=column_mapping,
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
            failed_upload = await finish_offline_upload_load(
                session,
                upload_id=upload.upload_id,
                state="load_failed",
            )
            if failed_upload is None:
                raise ValueError(f"offline upload 없음: {upload.upload_id!r}") from exc
            upload = failed_upload
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
        loaded_upload = await finish_offline_upload_load(
            session,
            upload_id=upload.upload_id,
            state="loaded",
        )
        if loaded_upload is None:
            raise ValueError(f"offline upload 없음: {upload.upload_id!r}")
        upload = loaded_upload
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
    provider: str | None = None,
    dataset_key: str | None = None,
    column_mapping: OfflineUploadColumnMapping | Mapping[str, object] | None = None,
) -> list[FeatureBundle]:
    """JSON/JSONL 또는 검증된 CSV/TSV 원본을 ``FeatureBundle`` 목록으로 파싱한다."""
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
    elif fmt in _TABULAR_FORMATS:
        if provider is None or dataset_key is None:
            raise ValueError("CSV/TSV offline upload load에는 provider/dataset_key가 필요함.")
        if column_mapping is None:
            raise ValueError("CSV/TSV offline upload load에는 validation column mapping이 필요함.")
        bundles = parse_offline_tabular_feature_bundles(
            data,
            provider=provider,
            dataset_key=dataset_key,
            column_mapping=column_mapping,
            detected_format=fmt,
            detected_encoding=detected_encoding,
            original_filename=original_filename,
        )
    else:
        raise ValueError(
            "offline upload format은 JSON/JSONL FeatureBundle 또는 검증된 CSV/TSV만 지원함 "
            f"(detected={detected_format!r}, filename={original_filename!r})."
        )
    if not bundles:
        raise ValueError("offline upload FeatureBundle 파일이 비어 있음.")
    return bundles


def preview_offline_tabular_upload(
    data: bytes,
    *,
    detected_format: str | None = None,
    detected_encoding: str | None = None,
    original_filename: str | None = None,
    sample_size: int = 20,
) -> OfflineUploadTabularPreview:
    """CSV/TSV header와 sample row를 반환한다."""
    parsed = _parse_tabular(
        data,
        detected_format=detected_format,
        detected_encoding=detected_encoding,
        original_filename=original_filename,
        sample_size=sample_size,
    )
    return OfflineUploadTabularPreview(
        parsed_format=parsed.parsed_format,
        encoding=parsed.encoding,
        delimiter=parsed.delimiter,
        headers=parsed.headers,
        sample_rows=parsed.sample_rows,
        rows_total=parsed.rows_total,
        rows_sampled=parsed.rows_sampled,
    )


def validate_offline_tabular_upload(
    upload: OfflineUpload,
    data: bytes,
    *,
    column_mapping: OfflineUploadColumnMapping | Mapping[str, object],
    sample_size: int = 1000,
    checksum_sha256: str | None = None,
) -> OfflineUploadValidationResult:
    """CSV/TSV sample row를 FeatureBundle로 변환 가능한지 검증한다."""
    mapping = normalize_offline_upload_column_mapping(column_mapping)
    parsed = _parse_tabular(
        data,
        detected_format=upload.detected_format,
        detected_encoding=upload.detected_encoding,
        original_filename=upload.original_filename,
        sample_size=sample_size,
    )
    issues = list(_validate_mapping_headers(parsed.headers, mapping))
    valid_rows = 0
    error_rows = 0
    for offset, row in enumerate(parsed.sample_rows, start=2):
        before = len(issues)
        try:
            _bundle_from_tabular_row(
                row,
                provider=upload.provider,
                dataset_key=upload.dataset_key,
                mapping=mapping,
                row_number=offset,
            )
        except Exception as exc:  # noqa: BLE001 - validation issue로 수집
            issues.append(
                OfflineUploadValidationIssue(
                    severity="error",
                    code="dto_validation_failed",
                    message=str(exc),
                    row_number=offset,
                )
            )
        if len(issues) == before:
            valid_rows += 1
        else:
            error_rows += 1
    return OfflineUploadValidationResult(
        upload=upload,
        job=None,
        column_mapping=mapping,
        parsed_format=parsed.parsed_format,
        encoding=parsed.encoding,
        delimiter=parsed.delimiter,
        headers=parsed.headers,
        sample_rows=parsed.sample_rows,
        rows_total=parsed.rows_total,
        rows_sampled=parsed.rows_sampled,
        valid_rows=valid_rows,
        error_rows=error_rows,
        issues=tuple(issues),
        bytes_read=len(data),
        checksum_sha256=checksum_sha256 or hashlib.sha256(data).hexdigest(),
    )


async def validate_offline_tabular_upload_async(
    upload: OfflineUpload,
    data: bytes,
    *,
    column_mapping: OfflineUploadColumnMapping | Mapping[str, object],
    sample_size: int = 1000,
    checksum_sha256: str | None = None,
    address_resolver: AddressResolver | None = None,
    reverse_geocoder: ReverseGeocoder | None = None,
) -> OfflineUploadValidationResult:
    """CSV/TSV sample row를 async geocoder 보강 포함 검증한다."""
    mapping = normalize_offline_upload_column_mapping(column_mapping)
    parsed = _parse_tabular(
        data,
        detected_format=upload.detected_format,
        detected_encoding=upload.detected_encoding,
        original_filename=upload.original_filename,
        sample_size=sample_size,
    )
    issues = list(_validate_mapping_headers(parsed.headers, mapping))
    valid_rows = 0
    error_rows = 0
    for offset, row in enumerate(parsed.sample_rows, start=2):
        before = len(issues)
        try:
            await _bundle_from_tabular_row_async(
                row,
                provider=upload.provider,
                dataset_key=upload.dataset_key,
                mapping=mapping,
                row_number=offset,
                address_resolver=address_resolver,
                reverse_geocoder=reverse_geocoder,
            )
        except Exception as exc:  # noqa: BLE001 - validation issue로 수집
            issues.append(
                OfflineUploadValidationIssue(
                    severity="error",
                    code="dto_validation_failed",
                    message=str(exc),
                    row_number=offset,
                )
            )
        if len(issues) == before:
            valid_rows += 1
        else:
            error_rows += 1
    return OfflineUploadValidationResult(
        upload=upload,
        job=None,
        column_mapping=mapping,
        parsed_format=parsed.parsed_format,
        encoding=parsed.encoding,
        delimiter=parsed.delimiter,
        headers=parsed.headers,
        sample_rows=parsed.sample_rows,
        rows_total=parsed.rows_total,
        rows_sampled=parsed.rows_sampled,
        valid_rows=valid_rows,
        error_rows=error_rows,
        issues=tuple(issues),
        bytes_read=len(data),
        checksum_sha256=checksum_sha256 or hashlib.sha256(data).hexdigest(),
    )


def parse_offline_tabular_feature_bundles(
    data: bytes,
    *,
    provider: str,
    dataset_key: str,
    column_mapping: OfflineUploadColumnMapping | Mapping[str, object],
    detected_format: str | None = None,
    detected_encoding: str | None = None,
    original_filename: str | None = None,
) -> list[FeatureBundle]:
    """검증된 CSV/TSV 전체 row를 ``FeatureBundle``로 변환한다."""
    mapping = normalize_offline_upload_column_mapping(column_mapping)
    parsed = _parse_tabular(
        data,
        detected_format=detected_format,
        detected_encoding=detected_encoding,
        original_filename=original_filename,
        sample_size=None,
    )
    missing = list(_validate_mapping_headers(parsed.headers, mapping))
    if missing:
        messages = "; ".join(issue.message for issue in missing)
        raise ValueError(messages)
    return [
        _bundle_from_tabular_row(
            row,
            provider=provider,
            dataset_key=dataset_key,
            mapping=mapping,
            row_number=index,
        )
        for index, row in enumerate(parsed.sample_rows, start=2)
    ]


async def parse_offline_tabular_feature_bundles_async(
    data: bytes,
    *,
    provider: str,
    dataset_key: str,
    column_mapping: OfflineUploadColumnMapping | Mapping[str, object],
    detected_format: str | None = None,
    detected_encoding: str | None = None,
    original_filename: str | None = None,
    address_resolver: AddressResolver | None = None,
    reverse_geocoder: ReverseGeocoder | None = None,
) -> list[FeatureBundle]:
    """검증된 CSV/TSV 전체 row를 geocoder 보강 포함 ``FeatureBundle``로 변환한다."""
    mapping = normalize_offline_upload_column_mapping(column_mapping)
    parsed = _parse_tabular(
        data,
        detected_format=detected_format,
        detected_encoding=detected_encoding,
        original_filename=original_filename,
        sample_size=None,
    )
    missing = list(_validate_mapping_headers(parsed.headers, mapping))
    if missing:
        messages = "; ".join(issue.message for issue in missing)
        raise ValueError(messages)
    bundles: list[FeatureBundle] = []
    for index, row in enumerate(parsed.sample_rows, start=2):
        bundles.append(
            await _bundle_from_tabular_row_async(
                row,
                provider=provider,
                dataset_key=dataset_key,
                mapping=mapping,
                row_number=index,
                address_resolver=address_resolver,
                reverse_geocoder=reverse_geocoder,
            )
        )
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


def _failed_validation_result(
    upload: OfflineUpload,
    *,
    column_mapping: OfflineUploadColumnMapping,
    body: bytes,
    checksum_sha256: str | None,
    message: str,
) -> OfflineUploadValidationResult:
    fmt = _detected_format(upload.detected_format, upload.original_filename)
    delimiter = "\t" if fmt == "tsv" else ","
    return OfflineUploadValidationResult(
        upload=upload,
        job=None,
        column_mapping=column_mapping,
        parsed_format=fmt,
        encoding=upload.detected_encoding or "unknown",
        delimiter=delimiter,
        headers=(),
        sample_rows=(),
        rows_total=0,
        rows_sampled=0,
        valid_rows=0,
        error_rows=1,
        issues=(
            OfflineUploadValidationIssue(
                severity="error",
                code="validation_job_failed",
                message=message,
            ),
        ),
        bytes_read=len(body),
        checksum_sha256=checksum_sha256 or (hashlib.sha256(body).hexdigest() if body else ""),
    )


@dataclass(frozen=True)
class _ParsedTabular:
    parsed_format: str
    encoding: str
    delimiter: str
    headers: tuple[str, ...]
    sample_rows: tuple[dict[str, str], ...]
    rows_total: int
    rows_sampled: int


def normalize_offline_upload_column_mapping(
    value: OfflineUploadColumnMapping | Mapping[str, object],
) -> OfflineUploadColumnMapping:
    """dict/Pydantic payload를 ``OfflineUploadColumnMapping``으로 정규화한다."""
    if isinstance(value, OfflineUploadColumnMapping):
        return value
    data = dict(value)
    return OfflineUploadColumnMapping(
        name=str(data.get("name") or ""),
        lon=str(data.get("lon") or ""),
        lat=str(data.get("lat") or ""),
        address=_optional_string(data.get("address")),
        source_id=_optional_string(data.get("source_id")),
        bjd_code=_optional_string(data.get("bjd_code")),
        category=_optional_string(data.get("category")),
        default_category=str(data.get("default_category") or "02020101"),
        default_marker_icon=str(data.get("default_marker_icon") or "marker"),
        default_marker_color=str(data.get("default_marker_color") or "P-01"),
        default_place_kind=str(data.get("default_place_kind") or "offline_upload"),
    )


def _optional_string(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _parse_tabular(
    data: bytes,
    *,
    detected_format: str | None,
    detected_encoding: str | None,
    original_filename: str | None,
    sample_size: int | None,
) -> _ParsedTabular:
    fmt = _detected_format(detected_format, original_filename)
    if fmt not in _TABULAR_FORMATS:
        raise ValueError(
            f"CSV/TSV validation은 csv/tsv만 지원함 "
            f"(detected={detected_format!r}, filename={original_filename!r})."
        )
    text, encoding = _decode_bytes_with_encoding(data, detected_encoding)
    delimiter = "," if fmt == "csv" else "\t"
    reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
    headers = tuple(reader.fieldnames or [])
    if not headers:
        raise ValueError("CSV/TSV header가 비어 있음.")
    rows: list[dict[str, str]] = []
    rows_total = 0
    limit = None if sample_size is None else max(1, sample_size)
    for raw in reader:
        rows_total += 1
        if limit is None or len(rows) < limit:
            rows.append(_clean_tabular_row(raw))
    return _ParsedTabular(
        parsed_format=fmt,
        encoding=encoding,
        delimiter=delimiter,
        headers=headers,
        sample_rows=tuple(rows),
        rows_total=rows_total,
        rows_sampled=len(rows),
    )


def _clean_tabular_row(row: Mapping[str | None, str | None]) -> dict[str, str]:
    clean: dict[str, str] = {}
    extras: list[str] = []
    for key, value in row.items():
        if key is None:
            if value:
                extras.append(str(value))
            continue
        clean[str(key)] = "" if value is None else str(value).strip()
    if extras:
        clean["__extra__"] = "|".join(extras)
    return clean


def _validate_mapping_headers(
    headers: tuple[str, ...],
    mapping: OfflineUploadColumnMapping,
) -> tuple[OfflineUploadValidationIssue, ...]:
    header_set = set(headers)
    issues: list[OfflineUploadValidationIssue] = []
    for target, required_column in {
        "name": mapping.name,
        "lon": mapping.lon,
        "lat": mapping.lat,
    }.items():
        if not required_column:
            issues.append(
                OfflineUploadValidationIssue(
                    severity="error",
                    code="missing_required_mapping",
                    message=f"{target} mapping이 비어 있음.",
                    column=target,
                )
            )
        elif required_column not in header_set:
            issues.append(
                OfflineUploadValidationIssue(
                    severity="error",
                    code="missing_required_column",
                    message=f"{target} column {required_column!r}이 header에 없음.",
                    column=required_column,
                )
            )
    optional_columns: tuple[tuple[str, str | None], ...] = (
        ("address", mapping.address),
        ("source_id", mapping.source_id),
        ("bjd_code", mapping.bjd_code),
        ("category", mapping.category),
    )
    for target, optional_column in optional_columns:
        if optional_column and optional_column not in header_set:
            issues.append(
                OfflineUploadValidationIssue(
                    severity="error",
                    code="missing_optional_column",
                    message=f"{target} column {optional_column!r}이 header에 없음.",
                    column=optional_column,
                )
            )
    return tuple(issues)


def _bundle_from_tabular_row(
    row: Mapping[str, str],
    *,
    provider: str,
    dataset_key: str,
    mapping: OfflineUploadColumnMapping,
    row_number: int,
    resolved_address: Address | None = None,
) -> FeatureBundle:
    name = _required_row_value(row, mapping.name, row_number=row_number)
    lon = _decimal_row_value(row, mapping.lon, row_number=row_number)
    lat = _decimal_row_value(row, mapping.lat, row_number=row_number)
    coord = Coordinate(lon=lon, lat=lat)
    address_text = _mapped_row_value(row, mapping.address)
    bjd_code = _mapped_row_value(row, mapping.bjd_code) or (
        resolved_address.bjd_code if resolved_address is not None else None
    )
    category = _mapped_row_value(row, mapping.category) or mapping.default_category
    source_entity_id = _mapped_row_value(row, mapping.source_id) or make_payload_hash(
        dict(row), length=16
    )
    raw_payload = dict(row)
    payload_hash = make_payload_hash(raw_payload)
    source_record_key = make_source_record_key(
        provider=provider,
        dataset_key=dataset_key,
        source_entity_type="offline_tabular_row",
        source_entity_id=source_entity_id,
        raw_payload_hash=payload_hash,
    )
    feature_id = make_feature_id(
        bjd_code=bjd_code,
        kind=FeatureKind.PLACE,
        category=category,
        source_type="offline_upload_tabular",
        source_natural_key=source_entity_id,
    )
    feature = Feature(
        feature_id=feature_id,
        kind=FeatureKind.PLACE,
        name=name,
        coord=coord,
        address=_tabular_feature_address(
            address_text=address_text,
            bjd_code=bjd_code,
            resolved_address=resolved_address,
        ),
        category=category,
        marker_icon=mapping.default_marker_icon,
        marker_color=mapping.default_marker_color,
        detail=PlaceDetail(
            feature_id=feature_id,
            place_kind=mapping.default_place_kind,
            payload={
                "offline_upload": {
                    "provider": provider,
                    "dataset_key": dataset_key,
                    "row_number": row_number,
                }
            },
        ),
    )
    source_record = SourceRecord(
        provider=provider,
        dataset_key=dataset_key,
        source_entity_type="offline_tabular_row",
        source_entity_id=source_entity_id,
        raw_payload_hash=payload_hash,
        raw_name=name,
        raw_address=address_text,
        raw_longitude=lon,
        raw_latitude=lat,
        raw_data=raw_payload,
        fetched_at=datetime.now(_KST),
        source_record_key=source_record_key,
    )
    source_link = SourceLink(
        feature_id=feature_id,
        source_record_key=source_record_key,
        source_role=SourceRole.PRIMARY,
        match_method="offline_upload_column_mapping",
        confidence=100,
        is_primary_source=True,
    )
    return FeatureBundle(
        feature=feature,
        source_record=source_record,
        source_link=source_link,
    )


async def _bundle_from_tabular_row_async(
    row: Mapping[str, str],
    *,
    provider: str,
    dataset_key: str,
    mapping: OfflineUploadColumnMapping,
    row_number: int,
    address_resolver: AddressResolver | None,
    reverse_geocoder: ReverseGeocoder | None,
) -> FeatureBundle:
    lon = _decimal_row_value(row, mapping.lon, row_number=row_number)
    lat = _decimal_row_value(row, mapping.lat, row_number=row_number)
    coord = Coordinate(lon=lon, lat=lat)
    resolved = await _resolve_missing_tabular_bjd_code(
        row,
        mapping=mapping,
        row_number=row_number,
        coord=coord,
        address_resolver=address_resolver,
        reverse_geocoder=reverse_geocoder,
    )
    return _bundle_from_tabular_row(
        row,
        provider=provider,
        dataset_key=dataset_key,
        mapping=mapping,
        row_number=row_number,
        resolved_address=resolved,
    )


async def _resolve_missing_tabular_bjd_code(
    row: Mapping[str, str],
    *,
    mapping: OfflineUploadColumnMapping,
    row_number: int,
    coord: Coordinate,
    address_resolver: AddressResolver | None,
    reverse_geocoder: ReverseGeocoder | None,
) -> Address | None:
    if _mapped_row_value(row, mapping.bjd_code):
        return None
    address_text = _mapped_row_value(row, mapping.address)
    if address_text and address_resolver is not None:
        resolved = await address_resolver(Address(road=address_text, legal=address_text))
        if resolved is not None and resolved.bjd_code is not None:
            return resolved
    if reverse_geocoder is not None:
        resolved = await reverse_geocoder(coord)
        if resolved is not None and resolved.bjd_code is not None:
            return resolved
    if address_text:
        raise ValueError(
            f"row {row_number}: bjd_code가 없고 kraddr-geo geocode 보강에 실패함"
        )
    raise ValueError(
        f"row {row_number}: bjd_code가 없고 address/reverse geocoder 보강 경로가 없음"
    )


def _tabular_feature_address(
    *,
    address_text: str | None,
    bjd_code: str | None,
    resolved_address: Address | None,
) -> Address:
    if resolved_address is None:
        return Address(road=address_text, bjd_code=bjd_code)
    sigungu_code = (
        resolved_address.sigungu_code
        if bjd_code is None or resolved_address.sigungu_code == bjd_code[:5]
        else None
    )
    sido_code = (
        resolved_address.sido_code
        if bjd_code is None or resolved_address.sido_code == bjd_code[:2]
        else None
    )
    return Address(
        road=address_text or resolved_address.road,
        legal=resolved_address.legal,
        admin=resolved_address.admin,
        bjd_code=bjd_code,
        admin_dong_code=resolved_address.admin_dong_code,
        sigungu_code=sigungu_code,
        sido_code=sido_code,
        road_name_code=resolved_address.road_name_code,
        zipcode=resolved_address.zipcode,
        sido_name=resolved_address.sido_name,
        sigungu_name=resolved_address.sigungu_name,
    )


def _required_row_value(
    row: Mapping[str, str],
    column: str,
    *,
    row_number: int,
) -> str:
    value = row.get(column, "").strip()
    if not value:
        raise ValueError(f"row {row_number}: required column {column!r} is empty")
    return value


def _mapped_row_value(row: Mapping[str, str], column: str | None) -> str | None:
    if column is None:
        return None
    value = row.get(column, "").strip()
    return value or None


def _decimal_row_value(
    row: Mapping[str, str],
    column: str,
    *,
    row_number: int,
) -> Decimal:
    value = _required_row_value(row, column, row_number=row_number)
    try:
        return Decimal(value)
    except InvalidOperation as exc:
        raise ValueError(
            f"row {row_number}: column {column!r} value {value!r} is not decimal"
        ) from exc


async def _load_column_mapping_for_upload(
    session: AsyncSession,
    upload: OfflineUpload,
) -> OfflineUploadColumnMapping | None:
    fmt = _detected_format(upload.detected_format, upload.original_filename)
    if fmt not in _TABULAR_FORMATS:
        return None
    if upload.validation_job_id is None:
        raise ValueError("CSV/TSV offline upload은 load 전 validation이 필요함.")
    job = await get_import_job(session, upload.validation_job_id)
    if job is None:
        raise ValueError(
            f"offline upload validation job 없음: {upload.validation_job_id!r}"
        )
    raw_mapping = job.payload.get("column_mapping")
    if not isinstance(raw_mapping, Mapping):
        raise ValueError("offline upload validation job payload에 column_mapping이 없음.")
    return normalize_offline_upload_column_mapping(raw_mapping)


def _decode_bytes(data: bytes, detected_encoding: str | None) -> str:
    text, _encoding = _decode_bytes_with_encoding(data, detected_encoding)
    return text


def _decode_bytes_with_encoding(
    data: bytes,
    detected_encoding: str | None,
) -> tuple[str, str]:
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
            return data.decode(encoding), encoding
        except UnicodeDecodeError as exc:
            last_error = exc
    if last_error is not None:
        raise ValueError(f"offline upload 파일 인코딩을 해석할 수 없음: {tried}") from (
            last_error
        )
    return data.decode(), "default"


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
