"""Managed file registry 상태·분류 상수 (ops.managed_files, PR-D).

``core/offline_upload_states.py``와 같은 위치 — CHECK 제약·repo·API·dagster가
전부 이 튜플을 공유해 값 drift를 막는다.

- kind: 파일 분류. "임시"는 여기(kind='temp')가 담당한다 — lifecycle이 아님.
- status: lifecycle만. ``missing``(등록됐는데 파일이 사라짐)은 ``orphan``
  (파일은 있는데 소유 레코드가 없음)과 정반대 상황이라 분리한다.
- orphan_reason: scan orphan rule의 판정 id — UI 표기·purge 게이트·회귀
  테스트가 이 값을 기준으로 동작한다.
"""

from __future__ import annotations

from typing import Final

MANAGED_FILE_KIND_VALUES: Final[tuple[str, ...]] = (
    "provider_download",
    "backup",
    "upload",
    "feature_file",
    "report",
    "temp",
    "other",
)

MANAGED_FILE_STATUS_VALUES: Final[tuple[str, ...]] = (
    "active",
    "orphan",
    "missing",
    "deleted",
)

MANAGED_FILE_ORPHAN_REASON_VALUES: Final[tuple[str, ...]] = (
    "zombie_object",
    "owner_row_deleted",
    "manifest_missing",
    "e2e_backup_expired",
    "scan_unregistered",
    "temp_expired",
)

MANAGED_FILE_REGISTERED_BY_VALUES: Final[tuple[str, ...]] = (
    "hook",
    "scan",
    "backfill",
)

MANAGED_FILE_EVENT_KIND_VALUES: Final[tuple[str, ...]] = (
    "registered",
    "downloaded",
    "validated",
    "loaded",
    "restored",
    "marked_orphan",
    "marked_missing",
    "reappeared",
    "deleted",
    "delete_failed",
    "purged",
)

MANAGED_FILE_STORAGE_BACKEND_VALUES: Final[tuple[str, ...]] = (
    "filesystem",
    "s3",
)

# 논리 location 키 — 물리 경로/버킷명 대신 registry에 저장되는 값.
# 물리 해석은 scan 시점에 settings로 수행한다(배포별 경로 차이 흡수).
MANAGED_FILE_LOCATION_BACKUP_ROOT: Final[str] = "backup_root"
MANAGED_FILE_LOCATION_MOIS_SOURCE: Final[str] = "mois_source"
MANAGED_FILE_LOCATION_OBJECT_STORE: Final[str] = "object_store"
MANAGED_FILE_LOCATION_OFFLINE_UPLOADS: Final[str] = "offline_uploads"

MANAGED_FILE_LOCATION_VALUES: Final[tuple[str, ...]] = (
    MANAGED_FILE_LOCATION_BACKUP_ROOT,
    MANAGED_FILE_LOCATION_MOIS_SOURCE,
    MANAGED_FILE_LOCATION_OBJECT_STORE,
    MANAGED_FILE_LOCATION_OFFLINE_UPLOADS,
)
