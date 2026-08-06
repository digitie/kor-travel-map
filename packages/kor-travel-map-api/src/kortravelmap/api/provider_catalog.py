"""DB 정본 provider dataset catalog projection.

T-VN-33부터 provider/dataset identity, 활성 상태, capability, 실행 operation과
scope는 PostgreSQL이 소유한다. 이 모듈은 그 relation을 읽어 API/Dagster가 사용할
불변 projection으로 조립할 뿐 provider 상수나 fixture 목록을 들고 있지 않다.

``operation_key``의 실행 handler는 main package의
``feature_operation_registry``가 소유한다. DB의 활성 refresh operation key 집합과
그 handler key 집합은 배포 전 exact-set으로 대조한다. 따라서 seed에 새 operation을
넣고 handler를 빼먹거나, 제거한 operation의 handler를 남기는 어느 경우도
fail-closed 한다.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Final, cast

from sqlalchemy import text

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

__all__ = [
    "ActiveOperationHandlerDriftError",
    "ProviderDatasetCatalogEntry",
    "ProviderDatasetOperation",
    "ProviderDatasetOperationBinding",
    "assert_active_operation_handler_exact_set",
    "find_provider_dataset_catalog_entry",
    "list_active_refresh_operation_bindings",
    "list_provider_dataset_catalog",
]


_CATALOG_SQL: Final[str] = """
SELECT
    dataset.provider_dataset_id,
    dataset.provider,
    dataset.dataset_key,
    dataset.display_name,
    dataset.source_kind,
    dataset.is_active,
    dataset.capabilities,
    operation.operation_key,
    operation.operation_kind,
    operation.is_enabled AS operation_is_enabled,
    operation.config AS operation_config,
    scope.sync_scope
FROM provider_sync.provider_datasets AS dataset
LEFT JOIN provider_sync.provider_dataset_operations AS operation
  ON operation.provider_dataset_id = dataset.provider_dataset_id
LEFT JOIN provider_sync.provider_dataset_operation_scopes AS scope
  ON scope.provider_dataset_id = operation.provider_dataset_id
 AND scope.operation_key = operation.operation_key
 AND scope.operation_kind = operation.operation_kind
WHERE (CAST(:active_only AS boolean) = false OR dataset.is_active)
ORDER BY
    dataset.provider,
    dataset.dataset_key,
    operation.operation_key,
    operation.operation_kind,
    scope.sync_scope
"""

_ACTIVE_REFRESH_OPERATION_BINDINGS_SQL: Final[str] = """
SELECT
    dataset.provider_dataset_id,
    dataset.provider,
    dataset.dataset_key,
    operation.operation_key
FROM provider_sync.provider_datasets AS dataset
JOIN provider_sync.provider_dataset_operations AS operation
  ON operation.provider_dataset_id = dataset.provider_dataset_id
WHERE dataset.is_active
  AND operation.is_enabled
  AND operation.operation_kind = 'refresh'
ORDER BY dataset.provider, dataset.dataset_key, operation.operation_key
"""


def _freeze_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _freeze_json(item) for key, item in value.items()})
    if isinstance(value, list | tuple):
        return tuple(_freeze_json(item) for item in value)
    return value


def _json_object(value: Any) -> Mapping[str, Any]:
    """PostgreSQL JSONB와 test double 양쪽을 deep immutable object로 정규화한다."""
    decoded = json.loads(value) if isinstance(value, str) else value
    if not isinstance(decoded, Mapping):
        raise ValueError("provider dataset JSON column must be an object")
    frozen = _freeze_json(decoded)
    if not isinstance(frozen, Mapping):
        raise AssertionError("JSON object freeze must preserve mapping shape")
    return cast("Mapping[str, Any]", frozen)


@dataclass(frozen=True, slots=True)
class ProviderDatasetOperation:
    """DB가 소유한 dataset operation 1개와 정규 sync scope."""

    operation_key: str
    operation_kind: str
    is_enabled: bool
    config: Mapping[str, Any]
    sync_scopes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ProviderDatasetCatalogEntry:
    """``provider_datasets``의 API read projection.

    ``produces``는 capabilities metadata에서만 읽는다. operation enable/handler/scope는
    별도 operation relation을 읽으므로 동일 의미가 두 곳에 저장되지 않는다.
    """

    provider_dataset_id: int
    provider: str
    dataset_key: str
    display_name: str
    source_kind: str
    is_active: bool
    capabilities: Mapping[str, Any]
    operations: tuple[ProviderDatasetOperation, ...]

    @property
    def produces(self) -> tuple[str, ...]:
        raw = self.capabilities.get("produces", ())
        if not isinstance(raw, list | tuple) or not all(isinstance(value, str) for value in raw):
            raise ValueError("provider dataset capabilities.produces must be a string array")
        return tuple(raw)

    @property
    def feature_kind(self) -> str:
        """UI가 표시할 대표 산출 종류.

        capability는 복수 산출도 허용하지만 현 seed는 하나만 등록한다. 복수 산출은
        순서로 의미를 만들지 않으며 안정적인 첫 값을 표시용으로만 사용한다.
        """
        return self.produces[0] if self.produces else "unknown"

    @property
    def enabled_refresh_operations(self) -> tuple[ProviderDatasetOperation, ...]:
        return tuple(
            operation
            for operation in self.operations
            if operation.operation_kind == "refresh" and operation.is_enabled
        )

    @property
    def refresh_scopes(self) -> tuple[str, ...]:
        return tuple(
            sorted(
                {
                    scope
                    for operation in self.enabled_refresh_operations
                    for scope in operation.sync_scopes
                }
            )
        )

    @property
    def is_refreshable(self) -> bool:
        return self.is_active and bool(self.enabled_refresh_operations)

    @property
    def default_refresh_scope(self) -> str:
        """DB가 선언한 기본 refresh scope.

        target grid dataset은 전체 dataset 갱신과 별개로 운영자가 target scope를
        선택하는 것이 유용하므로 target_grids를 우선한다. 나머지는 dataset_wide다.
        """
        if "target_grids" in self.refresh_scopes:
            return "target_grids"
        if "dataset_wide" in self.refresh_scopes:
            return "dataset_wide"
        raise ValueError(
            "refresh operation must declare dataset_wide or target_grids default scope"
        )

    @property
    def supports_targeted_refresh(self) -> bool:
        return "target_grids" in self.refresh_scopes

    @property
    def has_fixture_preview(self) -> bool:
        """fixture preview는 DB preview operation의 handler config로만 활성화한다."""
        return any(
            operation.operation_kind == "preview"
            and operation.is_enabled
            and operation.config.get("handler") == "fixture"
            for operation in self.operations
        )


@dataclass(frozen=True, slots=True)
class ProviderDatasetOperationBinding:
    """활성 refresh operation의 DB-owned dataset binding.

    하나의 ``operation_key``는 여러 dataset row에 반복될 수 있다. handler registry는
    여기의 provider/dataset 쌍을 알지 못하며, caller가 DB에서 받은 이 binding으로
    실행 대상을 결정한다.
    """

    provider_dataset_id: int
    provider: str
    dataset_key: str
    operation_key: str


class ActiveOperationHandlerDriftError(RuntimeError):
    """활성 DB operation과 Python handler exact-set이 다르다."""

    def __init__(
        self,
        *,
        missing_handler_operation_keys: frozenset[str],
        stale_handler_operation_keys: frozenset[str],
    ) -> None:
        self.missing_handler_operation_keys = missing_handler_operation_keys
        self.stale_handler_operation_keys = stale_handler_operation_keys
        super().__init__(
            "active provider dataset operations and handler bindings differ: "
            f"missing_handler={sorted(missing_handler_operation_keys)!r}; "
            f"stale_handler={sorted(stale_handler_operation_keys)!r}"
        )


def _catalog_entries(rows: Iterable[Any]) -> tuple[ProviderDatasetCatalogEntry, ...]:
    datasets: dict[int, dict[str, Any]] = {}
    for row in rows:
        dataset_id = int(row["provider_dataset_id"])
        item = datasets.setdefault(
            dataset_id,
            {
                "provider": str(row["provider"]),
                "dataset_key": str(row["dataset_key"]),
                "display_name": str(row["display_name"]),
                "source_kind": str(row["source_kind"]),
                "is_active": bool(row["is_active"]),
                "capabilities": _json_object(row["capabilities"]),
                "operations": {},
            },
        )
        operation_key = row["operation_key"]
        if operation_key is None:
            continue
        operation_kind = str(row["operation_kind"])
        operation_identity = (str(operation_key), operation_kind)
        operation_rows: dict[tuple[str, str], dict[str, Any]] = item["operations"]
        operation = operation_rows.setdefault(
            operation_identity,
            {
                "is_enabled": bool(row["operation_is_enabled"]),
                "config": _json_object(row["operation_config"]),
                "sync_scopes": set(),
            },
        )
        if row["sync_scope"] is not None:
            operation["sync_scopes"].add(str(row["sync_scope"]))

    entries: list[ProviderDatasetCatalogEntry] = []
    for dataset_id, item in datasets.items():
        catalog_operations = tuple(
            ProviderDatasetOperation(
                operation_key=operation_key,
                operation_kind=operation_kind,
                is_enabled=operation["is_enabled"],
                config=operation["config"],
                sync_scopes=tuple(sorted(operation["sync_scopes"])),
            )
            for (operation_key, operation_kind), operation in sorted(item["operations"].items())
        )
        entries.append(
            ProviderDatasetCatalogEntry(
                provider_dataset_id=dataset_id,
                provider=item["provider"],
                dataset_key=item["dataset_key"],
                display_name=item["display_name"],
                source_kind=item["source_kind"],
                is_active=item["is_active"],
                capabilities=item["capabilities"],
                operations=catalog_operations,
            )
        )
    return tuple(sorted(entries, key=lambda item: (item.provider, item.dataset_key)))


async def list_provider_dataset_catalog(
    session: AsyncSession,
    *,
    active_only: bool = False,
) -> tuple[ProviderDatasetCatalogEntry, ...]:
    """DB dataset catalog를 provider/dataset 순서의 immutable projection으로 읽는다."""
    result = await session.execute(text(_CATALOG_SQL), {"active_only": active_only})
    return _catalog_entries(result.mappings().all())


async def find_provider_dataset_catalog_entry(
    session: AsyncSession,
    *,
    provider: str,
    dataset_key: str,
    active_only: bool = False,
) -> ProviderDatasetCatalogEntry | None:
    """DB 정본에서 exact provider/dataset 하나를 찾는다."""
    entries = await list_provider_dataset_catalog(session, active_only=active_only)
    for entry in entries:
        if entry.provider == provider and entry.dataset_key == dataset_key:
            return entry
    return None


async def list_active_refresh_operation_bindings(
    session: AsyncSession,
) -> tuple[ProviderDatasetOperationBinding, ...]:
    """실행 가능한 refresh dataset binding을 DB에서 읽는다."""
    result = await session.execute(text(_ACTIVE_REFRESH_OPERATION_BINDINGS_SQL))
    return tuple(
        ProviderDatasetOperationBinding(
            provider_dataset_id=int(row["provider_dataset_id"]),
            provider=str(row["provider"]),
            dataset_key=str(row["dataset_key"]),
            operation_key=str(row["operation_key"]),
        )
        for row in result.mappings().all()
    )


async def assert_active_operation_handler_exact_set(
    session: AsyncSession,
    *,
    handler_operation_keys: Iterable[str],
) -> frozenset[str]:
    """활성 DB refresh operation key와 Python handler key를 exact 비교한다.

    반환값은 검증된 DB key 집합이다. caller는 이 검증을 통과한 뒤에만 binding을
    launch 대상으로 사용해야 한다.
    """
    bindings = await list_active_refresh_operation_bindings(session)
    active_operation_keys = frozenset(binding.operation_key for binding in bindings)
    handler_keys = frozenset(handler_operation_keys)
    if any(not key or key != key.strip() for key in handler_keys):
        raise ValueError("handler operation_key must be non-empty and trimmed")
    missing_handler_keys = active_operation_keys - handler_keys
    stale_handler_keys = handler_keys - active_operation_keys
    if missing_handler_keys or stale_handler_keys:
        raise ActiveOperationHandlerDriftError(
            missing_handler_operation_keys=missing_handler_keys,
            stale_handler_operation_keys=stale_handler_keys,
        )
    return active_operation_keys
