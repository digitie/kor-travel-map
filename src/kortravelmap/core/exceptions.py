"""``kortravelmap.core.exceptions`` — 라이브러리 공개 예외 계층.

``docs/architecture/backend-package.md §5`` +
``docs/architecture/debug-ui-package.md §6.4 HTTP 매핑``의 원천.
모든 예외는 ``KorTravelMapError``를 상속한다.

호출자(TripMate / debug-ui)는 본 모듈의 예외만 catch해야 한다. 내부 SQLAlchemy /
asyncpg / httpx 예외가 새는 일이 없도록 ``infra/``/``providers/``/``client/``
레이어에서 본 예외로 wrap한다.

ADR 참조
--------
- ADR-001 — 의존 방향 ``core``는 dto만 import (본 모듈은 stdlib만 사용)
- ADR-002 — async-only API (예외 자체는 sync 객체)

HTTP 매핑 (``docs/architecture/debug-ui-package.md §6.4``)
---------------------------------------------
| 예외 | HTTP | error code |
|------|------|-----------|
| ``ValidationError`` | 422 | ``VALIDATION_ERROR`` |
| ``FeatureNotFoundError`` | 404 | ``FEATURE_NOT_FOUND`` |
| ``SourceRecordNotFoundError`` | 404 | ``SOURCE_RECORD_NOT_FOUND`` |
| ``DuplicateFeatureError`` | 409 | ``DUPLICATE_FEATURE`` |
| ``ImportJobConflictError`` | 409 | ``JOB_CONFLICT`` |
| ``ProviderError`` | 502 | ``PROVIDER_ERROR`` |
| ``FileStoreError`` | 502 | ``FILE_STORE_ERROR`` |
"""

from __future__ import annotations

__all__ = [
    "KorTravelMapError",
    "ValidationError",
    "FeatureNotFoundError",
    "SourceRecordNotFoundError",
    "DuplicateFeatureError",
    "ImportJobConflictError",
    "ProviderError",
    "FileStoreError",
]


class KorTravelMapError(Exception):
    """``kortravelmap`` 라이브러리 모든 공개 예외의 베이스.

    호출자는 ``except KorTravelMapError:``로 라이브러리 발 예외 전체를 catch할 수
    있다. 내부 의존(SQLAlchemy / asyncpg / httpx / pyproj)의 raw 예외는
    ``infra``/``providers``/``client`` 레이어에서 본 베이스 또는 적절한 서브클래스로
    wrap해야 한다 (raw 예외 누설 금지, ``docs/architecture/backend-package.md §5``).
    """


class ValidationError(KorTravelMapError):
    """DTO Pydantic validation 실패 또는 도메인 룰 위반.

    ``Feature.detail`` kind mismatch (ADR-018), naive datetime 입력 (ADR-019),
    Korea coordinate bounds 위반, ``NOTICE_TYPES`` 미지원 값 등이 이 예외로
    표준화된다. Pydantic의 ``ValidationError``는 호출자에게 노출하기 전 본
    예외로 래핑한다 (HTTP 422 매핑).
    """


class FeatureNotFoundError(KorTravelMapError):
    """``feature_id``로 조회 시 row 없음.

    ``get_feature(feature_id)`` / ``load_feature_bundles([...])`` 등에서
    요청한 ID가 DB에 존재하지 않거나 ``deleted_at IS NOT NULL`` (soft-deleted)인
    경우 발생. HTTP 404 매핑.
    """


class SourceRecordNotFoundError(KorTravelMapError):
    """``source_record_key``로 조회 시 row 없음.

    provider 적재 결과 추적이나 fixture 회귀 시 raw payload를 다시 끌어올
    때 사용. HTTP 404 매핑.
    """


class DuplicateFeatureError(KorTravelMapError):
    """``feature_id`` 충돌 (다른 source/payload).

    ADR-009 ``make_feature_id``가 결정적이므로 같은 입력은 같은 ID를 낳고
    upsert로 처리된다. 본 예외는 ``content_hash``가 다른데 같은 natural key
    조합으로 ID가 충돌하는 (이론적) 경우, 또는 명시적 upsert가 아닌 insert
    경로에서 race로 ID 중복이 감지될 때 발생.

    HTTP 409 매핑.
    """


class ImportJobConflictError(KorTravelMapError):
    """``import_jobs`` advisory lock 미획득.

    ADR-011 — 같은 ``(provider, dataset_key)`` 조합으로 동시에 다른 워커가
    적재 중이면 PostgreSQL ``pg_try_advisory_xact_lock``이 실패하고 본 예외가
    발생한다. 호출자는 backoff 후 재시도하거나 다음 schedule을 기다린다.

    HTTP 409 매핑.
    """


class ProviderError(KorTravelMapError):
    """provider client 호출 실패 (HTTP 5xx, timeout, rate-limit 등).

    ``python-{provider}-api``의 raw 예외(httpx.HTTPStatusError, asyncio.TimeoutError,
    provider 자체 RateLimitExceeded 등)를 ``providers/``에서 본 예외로 wrap.
    ADR-006 — provider client는 직접 사용하되 예외만 정규화한다.

    HTTP 502 매핑.
    """


class FileStoreError(KorTravelMapError):
    """object store(RustFS / S3 호환) 접근 실패.

    ``upload_feature_files()``의 multipart upload 실패, signed URL 생성 실패,
    bucket 존재하지 않음 등을 wrap한다 (``docs/architecture/feature-files-rustfs.md`` 참조).

    HTTP 502 매핑.
    """
