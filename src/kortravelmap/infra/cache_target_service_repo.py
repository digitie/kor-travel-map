"""ServiceToken cache-target source read와 refresh request facade 없는 domain 조합."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Literal, cast

from sqlalchemy import text

from kortravelmap.infra.cache_target_stream_repo import CacheTargetStreamConflict
from kortravelmap.infra.domain_command_repo import canonical_domain_command_fingerprint
from kortravelmap.infra.feature_update_repo import (
    FeatureUpdateRequest,
    create_feature_update_request_idempotency,
    enqueue_feature_update_request,
    get_feature_update_request_idempotency,
    get_update_request,
    lock_feature_update_request_idempotency,
)
from kortravelmap.infra.poi_cache_target_repo import poi_cache_target_entity_tag

if TYPE_CHECKING:
    from collections.abc import Sequence

    from sqlalchemy.ext.asyncio import AsyncSession

__all__ = [
    "CacheTargetRefreshRequestResult",
    "CacheTargetSourceRecord",
    "create_cache_target_refresh_request",
    "get_cache_target_refresh_request",
    "get_cache_target_source",
]

_GET_SOURCE_SQL = """
SELECT head.external_system, head.target_key, head.state, head.restore_epoch,
       head.source_generation, head.source_payload_fingerprint,
       head.target_id, head.target_sequence, head.updated_at,
       source.occurred_at, target.lock_version
FROM ops.poi_cache_target_source_heads AS head
LEFT JOIN ops.poi_cache_target_source_events AS source
  ON source.event_id = head.last_source_event_id
LEFT JOIN ops.poi_cache_targets AS target
  ON target.target_id = head.target_id
WHERE head.external_system = :external_system AND head.target_key = :target_key
"""


@dataclass(frozen=True, slots=True)
class CacheTargetSourceRecord:
    external_system: str
    target_key: str
    state: Literal["active", "deleted"]
    restore_epoch: int
    source_generation: int
    source_payload_fingerprint: str
    entity_tag: str | None
    target_id: str | None
    target_sequence: int
    occurred_at: datetime | None
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class CacheTargetRefreshRequestResult:
    request_id: str
    external_system: str
    status: str
    created_at: datetime
    updated_at: datetime
    idempotent_replay: bool = False

    @property
    def status_url(self) -> str:
        return f"/v1/service/refresh-requests/{self.request_id}"

    @property
    def retry_after_seconds(self) -> int | None:
        return 5 if self.status in ("queued", "running") else None


async def get_cache_target_source(
    session: AsyncSession,
    *,
    external_system: str,
    target_key: str,
    include_deleted: bool = False,
) -> CacheTargetSourceRecord | None:
    row = (
        await session.execute(
            text(_GET_SOURCE_SQL),
            {"external_system": external_system, "target_key": target_key},
        )
    ).one_or_none()
    if row is None:
        return None
    values = row._mapping
    state = str(values["state"])
    if state == "deleted" and not include_deleted:
        return None
    if state not in ("active", "deleted"):
        raise RuntimeError("cache target source head state가 유효하지 않습니다.")
    target_id = str(values["target_id"]) if values["target_id"] is not None else None
    lock_version = (
        int(values["lock_version"]) if values["lock_version"] is not None else None
    )
    return CacheTargetSourceRecord(
        external_system=str(values["external_system"]),
        target_key=str(values["target_key"]),
        state=cast('Literal["active", "deleted"]', state),
        restore_epoch=int(values["restore_epoch"]),
        source_generation=int(values["source_generation"]),
        source_payload_fingerprint=str(values["source_payload_fingerprint"]),
        entity_tag=(
            poi_cache_target_entity_tag(target_id, lock_version)
            if target_id is not None and lock_version is not None
            else None
        ),
        target_id=target_id,
        target_sequence=int(values["target_sequence"]),
        occurred_at=values["occurred_at"],
        updated_at=values["updated_at"],
    )


def _external_system(request: FeatureUpdateRequest) -> str:
    external_system = request.scope.get("external_system")
    if request.scope_type != "cache_target_keys" or not isinstance(external_system, str):
        raise RuntimeError("refresh request의 cache_target_keys scope가 손상됐습니다.")
    return external_system


def _refresh_result(
    request: FeatureUpdateRequest,
    *,
    replay: bool,
) -> CacheTargetRefreshRequestResult:
    return CacheTargetRefreshRequestResult(
        request_id=request.request_id,
        external_system=_external_system(request),
        status=request.status,
        created_at=request.created_at,
        updated_at=request.finished_at or request.started_at or request.created_at,
        idempotent_replay=replay,
    )


async def create_cache_target_refresh_request(
    session: AsyncSession,
    *,
    principal_id: str,
    consumer_id: str,
    idempotency_key: str,
    external_system: str,
    target_keys: Sequence[str],
    reason: str,
) -> CacheTargetRefreshRequestResult:
    """기존 feature-update ledger에 ServiceToken request identity를 결합한다."""

    actor = f"cache-target:{principal_id}:{consumer_id}"
    if len(actor) > 200:
        raise ValueError("principal_id와 consumer_id 결합 길이는 200 이하여야 합니다.")
    if not target_keys or len(target_keys) > 500:
        raise ValueError("target_keys는 1개 이상 500개 이하여야 합니다.")
    request_payload = {
        "consumer_id": consumer_id,
        "external_system": external_system,
        "reason": reason,
        "target_keys": list(target_keys),
        "version": "cache-target-refresh-request-v1",
    }
    fingerprint = canonical_domain_command_fingerprint(request_payload)
    await lock_feature_update_request_idempotency(
        session,
        idempotency_key,
        actor=actor,
    )
    existing = await get_feature_update_request_idempotency(
        session,
        idempotency_key,
        actor=actor,
    )
    if existing is not None:
        if existing.request_fingerprint != fingerprint:
            raise CacheTargetStreamConflict(
                "refresh_idempotency_key_reused",
                "같은 Idempotency-Key가 다른 refresh request에 사용됐습니다.",
            )
        request = await get_update_request(session, existing.request_id)
        if request is None:
            raise RuntimeError("refresh idempotency ledger의 request가 없습니다.")
        return _refresh_result(request, replay=True)

    stream = (
        await session.execute(
            text(
                "SELECT consumer_id FROM ops.poi_cache_target_streams "
                "WHERE external_system = :external_system FOR KEY SHARE"
            ),
            {"external_system": external_system},
        )
    ).one_or_none()
    if stream is None:
        raise CacheTargetStreamConflict("stream_not_found", "cache target stream이 없습니다.")
    if str(stream._mapping["consumer_id"]) != consumer_id:
        raise CacheTargetStreamConflict(
            "consumer_mismatch",
            "service principal consumer_id가 stream binding과 다릅니다.",
        )
    request = await enqueue_feature_update_request(
        session,
        scope={
            "type": "cache_target_keys",
            "external_system": external_system,
            "target_keys": list(target_keys),
        },
        run_mode="queued",
        operator=actor,
        reason=reason,
    )
    await create_feature_update_request_idempotency(
        session,
        idempotency_key=idempotency_key,
        request_fingerprint=fingerprint,
        request_id=request.request_id,
        actor=actor,
        reused_active_request=False,
    )
    return _refresh_result(request, replay=False)


async def get_cache_target_refresh_request(
    session: AsyncSession,
    *,
    request_id: str,
) -> CacheTargetRefreshRequestResult | None:
    request = await get_update_request(session, request_id)
    if request is None or request.scope_type != "cache_target_keys":
        return None
    return _refresh_result(request, replay=False)
