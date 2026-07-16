"""Provider refresh ``sync_scope`` 정규형과 strict parser.

``sync_scope``는 단순 cursor namespace가 아니라 실제 provider 호출 대상의
identity다. 자유 문자열이나 과거 alias를 허용하면 같은 대상을 서로 다른 scope로
동시에 실행할 수 있으므로, 본 모듈의 세 정규형만 허용한다.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, TypeAlias

DATASET_WIDE_SYNC_SCOPE = "dataset_wide"
TARGET_GRIDS_SYNC_SCOPE = "target_grids"
EXTERNAL_SYSTEM_SYNC_SCOPE_PREFIX = "external_system:"
MAX_EXTERNAL_SYSTEM_NAME_LENGTH = 112

SyncScopeKind: TypeAlias = Literal[
    "dataset_wide",
    "target_grids",
    "external_system",
]


@dataclass(frozen=True, slots=True)
class CanonicalSyncScope:
    """검증을 마친 provider refresh scope identity."""

    value: str
    kind: SyncScopeKind
    external_system: str | None = None


def parse_canonical_sync_scope(value: str) -> CanonicalSyncScope:
    """정규 ``sync_scope``를 parse하고 자유 alias/blank를 거부한다.

    ``external_system:<name>``의 ``name``은 trim하거나 case-fold하지 않는다.
    저장된 ``ops.poi_cache_targets.external_system``과 exact equality로 비교해야
    하므로 앞뒤 공백이 있는 값도 비정규 입력으로 거절한다.
    """
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError("sync_scope must be a trimmed, non-empty string")
    if value == DATASET_WIDE_SYNC_SCOPE:
        return CanonicalSyncScope(value=value, kind="dataset_wide")
    if value == TARGET_GRIDS_SYNC_SCOPE:
        return CanonicalSyncScope(value=value, kind="target_grids")
    if value.startswith(EXTERNAL_SYSTEM_SYNC_SCOPE_PREFIX):
        external_system = value.removeprefix(EXTERNAL_SYSTEM_SYNC_SCOPE_PREFIX)
        if not external_system or external_system != external_system.strip():
            raise ValueError("external_system sync_scope requires an exact non-empty system name")
        if len(external_system) > MAX_EXTERNAL_SYSTEM_NAME_LENGTH:
            raise ValueError(
                "external_system sync_scope name must contain at most "
                f"{MAX_EXTERNAL_SYSTEM_NAME_LENGTH} characters"
            )
        return CanonicalSyncScope(
            value=value,
            kind="external_system",
            external_system=external_system,
        )
    raise ValueError(
        "unsupported sync_scope; expected dataset_wide, target_grids, or external_system:<name>"
    )


__all__ = [
    "DATASET_WIDE_SYNC_SCOPE",
    "EXTERNAL_SYSTEM_SYNC_SCOPE_PREFIX",
    "MAX_EXTERNAL_SYSTEM_NAME_LENGTH",
    "TARGET_GRIDS_SYNC_SCOPE",
    "CanonicalSyncScope",
    "SyncScopeKind",
    "parse_canonical_sync_scope",
]
