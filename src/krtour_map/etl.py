from __future__ import annotations

import inspect
from collections.abc import AsyncIterable, Awaitable, Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, TypeVar

from krtour_map.models import ProviderSyncState
from krtour_map.providers import normalize_provider_name

T = TypeVar("T")


RUN_KIND_METADATA_PROBE = "metadata_probe"
RUN_KIND_FULL_SCAN = "full_scan"
RUN_KIND_DYNAMIC = "dynamic"
RUN_KIND_MANUAL = "manual"


@dataclass(frozen=True)
class EtlRefreshPolicy:
    """Provider dataset refresh policy used to update `provider_sync_state`.

    This is not a scheduler. TripMate/Dagster still owns when a job is attempted;
    this policy gives that thin shell a consistent way to decide whether a run is
    due and how far to advance `next_run_after` after a successful staged load.
    """

    provider: str
    dataset_key: str
    sync_scope: str = "global"
    metadata_probe_interval: timedelta | None = None
    full_scan_interval: timedelta | None = None
    dynamic_interval: timedelta | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "provider", normalize_provider_name(self.provider))

    def interval_for(self, run_kind: str) -> timedelta | None:
        if run_kind == RUN_KIND_METADATA_PROBE:
            return self.metadata_probe_interval
        if run_kind == RUN_KIND_FULL_SCAN:
            return self.full_scan_interval
        if run_kind == RUN_KIND_DYNAMIC:
            return self.dynamic_interval
        if run_kind == RUN_KIND_MANUAL:
            return None
        raise ValueError(f"Unsupported ETL run kind: {run_kind}")

    def next_run_after(self, run_at: datetime, *, run_kind: str) -> datetime | None:
        interval = self.interval_for(run_kind)
        return run_at + interval if interval is not None else None


def is_sync_due(state: ProviderSyncState | None, *, now: datetime) -> bool:
    """Return whether a provider dataset should be attempted at `now`."""

    if state is None:
        return True
    if state.status != "active":
        return False
    return state.next_run_after is None or state.next_run_after <= now


def sync_state_after_success(
    policy: EtlRefreshPolicy,
    *,
    run_at: datetime,
    run_kind: str,
    previous: ProviderSyncState | None = None,
    cursor: dict[str, Any] | None = None,
    metadata_hash: str | None = None,
    source_version: str | None = None,
    item_count: int | None = None,
    extra: dict[str, Any] | None = None,
) -> ProviderSyncState:
    """Build the success checkpoint row for a provider dataset."""

    merged_extra = dict(previous.extra) if previous is not None else {}
    if item_count is not None:
        merged_extra["last_item_count"] = item_count
    merged_extra.update(extra or {})

    return ProviderSyncState(
        provider=policy.provider,
        dataset_key=policy.dataset_key,
        sync_scope=policy.sync_scope,
        status="active",
        cursor=cursor if cursor is not None else (previous.cursor if previous else None),
        metadata_hash=metadata_hash
        if metadata_hash is not None
        else (previous.metadata_hash if previous else None),
        last_observed_source_version=source_version
        if source_version is not None
        else (previous.last_observed_source_version if previous else None),
        last_success_at=run_at,
        last_attempt_at=run_at,
        last_full_scan_at=(
            run_at
            if run_kind == RUN_KIND_FULL_SCAN
            else (previous.last_full_scan_at if previous else None)
        ),
        next_run_after=policy.next_run_after(run_at, run_kind=run_kind),
        last_error=None,
        last_error_at=None,
        extra=merged_extra,
        updated_at=run_at,
    )


def sync_state_after_failure(
    policy: EtlRefreshPolicy,
    *,
    run_at: datetime,
    error: BaseException | str,
    retry_after: timedelta | None = None,
    previous: ProviderSyncState | None = None,
) -> ProviderSyncState:
    """Build the failure checkpoint row while preserving the last good cursor."""

    return ProviderSyncState(
        provider=policy.provider,
        dataset_key=policy.dataset_key,
        sync_scope=policy.sync_scope,
        status=previous.status if previous is not None else "active",
        cursor=previous.cursor if previous is not None else None,
        metadata_hash=previous.metadata_hash if previous is not None else None,
        last_observed_source_version=(
            previous.last_observed_source_version if previous is not None else None
        ),
        last_success_at=previous.last_success_at if previous is not None else None,
        last_attempt_at=run_at,
        last_full_scan_at=previous.last_full_scan_at if previous is not None else None,
        next_run_after=run_at + retry_after if retry_after is not None else None,
        last_error=str(error),
        last_error_at=run_at,
        extra=dict(previous.extra) if previous is not None else {},
        updated_at=run_at,
    )


async def maybe_await(value: T | Awaitable[T]) -> T:
    """Resolve a value that may be returned directly or as an awaitable."""

    if inspect.isawaitable(value):
        return await value
    return value


async def tuple_from_async_iterable(items: AsyncIterable[T] | Iterable[T]) -> tuple[T, ...]:
    """Collect either an async iterable or a sync iterable into a tuple."""

    if hasattr(items, "__aiter__"):
        result: list[T] = []
        async for item in items:  # type: ignore[union-attr]
            result.append(item)
        return tuple(result)
    return tuple(items)  # type: ignore[arg-type]


def page_items(page: Any) -> tuple[Any, ...]:
    """Return a page's item tuple from common provider page shapes."""

    items = getattr(page, "items", None)
    if items is None and isinstance(page, dict):
        items = page.get("items")
    if items is None:
        return ()
    return tuple(items)


def page_collected_at(page: Any) -> Any:
    """Best-effort collected_at extraction from provider page context objects."""

    collected_at = getattr(page, "collected_at", None)
    if collected_at is not None:
        return collected_at
    context = getattr(page, "context", None)
    return getattr(context, "collected_at", None) if context is not None else None
