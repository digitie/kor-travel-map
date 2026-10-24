"""한 sealed attempt의 여러 기존 primary place scalar를 한 TX로 적용한다.

collector 배선·provider 전체 snapshot seal이 아니다. caller는 지원 외 필드 불변과
artifact 보존을 담당하며 claim/plan TX 뒤 fresh apply TX를 명시적으로 소유한다.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from kortravelmap.dto import FeatureBundle
from kortravelmap.infra import scoped_provider_refresh as native
from kortravelmap.infra.feature_repo import (
    FEATURE_CURATION_WRITE_WAIT_INFO_KEY,
    _make_source_entity_key,
    lock_feature_curation_write,
)
from kortravelmap.infra.provider_field_candidates import lock_provider_field_policy_epoch
from kortravelmap.infra.scoped_feature_writes import (
    _arm_deadline,
    begin_scoped_feature_write,
    finish_scoped_feature_write,
    lock_scoped_feature_write_protocol,
)

# 기존 manifest8192 항목은 Feature/revision·membership·최소 source head의3개가 필요하다.
_MAX_BATCH_ITEMS = 8192 // 3
_BATCH_APPLY_SECONDS = 30.0


@dataclass(frozen=True)
class ProviderScalarRefreshItem:
    """정본 UUID와 재사용할 입력. frozen wrapper가 중첩 DTO 불변성을 보장하지는 않는다."""

    feature_id: UUID
    bundle: FeatureBundle

    def __post_init__(self) -> None:
        if not isinstance(self.feature_id, UUID) or not isinstance(self.bundle, FeatureBundle):
            raise ValueError("canonical Feature UUID and typed bundle required")


def _prepare_batch(
    items: Iterable[ProviderScalarRefreshItem], *, dataset_id: int, policy_revision: int
) -> tuple[tuple[ProviderScalarRefreshItem, ...], str]:
    if any(type(value) is not int or value < 1 for value in (dataset_id, policy_revision)):
        raise ValueError("positive dataset and policy revision required")
    bounded: list[ProviderScalarRefreshItem] = []
    features: set[UUID] = set()
    for item in items:
        if len(bounded) == _MAX_BATCH_ITEMS or not isinstance(item, ProviderScalarRefreshItem):
            raise ValueError("invalid bounded scalar batch")
        if item.feature_id in features:
            raise ValueError("duplicate canonical Feature in scalar batch")
        features.add(item.feature_id)
        bounded.append(item)
    if not bounded:
        raise ValueError("empty scalar batch")
    ordered = tuple(sorted(bounded, key=lambda item: item.feature_id))
    # 전체 예산 검사를 각 bundle의 raw/hash 재검증보다 먼저 완료한다.
    digest = native._artifact_digest(
        [
            "native-scalar-batch-v1",
            dataset_id,
            policy_revision,
            [[str(item.feature_id), item.bundle] for item in ordered],
        ]
    )
    entities: set[str] = set()
    datasets: set[tuple[str, str]] = set()
    for item in ordered:
        native.scoped_provider_refresh_input_digest(
            item.bundle,
            feature_id=item.feature_id,
            dataset_id=dataset_id,
            policy_revision=policy_revision,
        )
        record = item.bundle.source_record
        datasets.add((record.provider, record.dataset_key))
        entity = _make_source_entity_key(
            provider=record.provider,
            dataset_key=record.dataset_key,
            source_entity_type=record.source_entity_type,
            source_entity_id=record.source_entity_id,
        )
        if entity in entities:
            raise ValueError("duplicate source entity in scalar batch")
        entities.add(entity)
    if len(datasets) != 1:
        raise ValueError("scalar batch must share one provider dataset")
    return ordered, digest


def scoped_provider_refresh_batch_input_digest(
    items: Iterable[ProviderScalarRefreshItem], *, dataset_id: int, policy_revision: int
) -> str:
    """전체 정렬 입력의 총1MiB 지문. 기존 single 입력 지문과 다른 domain이다."""
    return _prepare_batch(items, dataset_id=dataset_id, policy_revision=policy_revision)[1]


async def refresh_scoped_provider_scalars_batch(
    session: AsyncSession,
    items: Iterable[ProviderScalarRefreshItem],
    *,
    dataset_id: int,
    policy_revision: int,
    attempt_id: UUID,
    owner: UUID,
    manifest_digest: str,
) -> dict[str, Any]:
    """SH 원자 batch. caller는 digest 준비부터 apply 종료까지 중첩 입력을 독점 소유한다.

    await 중 다른 task에 DTO/raw/list를 공유·변경하지 않는다. 전체 진입은 협력적30s
    timeout이며 caller의 commit/rollback은 포함하지 않는다. 모든 항목 뒤 finish1회다."""
    return await _refresh_batch(
        session,
        items,
        dataset_id=dataset_id,
        policy_revision=policy_revision,
        attempt_id=attempt_id,
        owner=owner,
        manifest_digest=manifest_digest,
        exclusive_protocol=False,
    )


async def refresh_exclusive_provider_scalars_batch(
    session: AsyncSession,
    items: Iterable[ProviderScalarRefreshItem],
    *,
    dataset_id: int,
    policy_revision: int,
    attempt_id: UUID,
    owner: UUID,
    manifest_digest: str,
) -> dict[str, Any]:
    """같은 scalar 의미를 EX+global fence로 적용한다. 자동 fallback이 아니다.

    SH entry와 같은 입력 독점 소유·협력적30s·caller 전체 rollback 계약을 요구한다."""
    return await _refresh_batch(
        session,
        items,
        dataset_id=dataset_id,
        policy_revision=policy_revision,
        attempt_id=attempt_id,
        owner=owner,
        manifest_digest=manifest_digest,
        exclusive_protocol=True,
    )


async def _refresh_batch(
    session: AsyncSession,
    items: Iterable[ProviderScalarRefreshItem],
    *,
    dataset_id: int,
    policy_revision: int,
    attempt_id: UUID,
    owner: UUID,
    manifest_digest: str,
    exclusive_protocol: bool,
) -> dict[str, Any]:
    if not session.in_transaction():
        raise ValueError("explicit caller transaction required")
    async with asyncio.timeout(_BATCH_APPLY_SECONDS):
        ordered, expected_digest = _prepare_batch(
            items, dataset_id=dataset_id, policy_revision=policy_revision
        )
        return await _apply_batch(
            session,
            ordered,
            expected_digest=expected_digest,
            dataset_id=dataset_id,
            policy_revision=policy_revision,
            attempt_id=attempt_id,
            owner=owner,
            manifest_digest=manifest_digest,
            exclusive_protocol=exclusive_protocol,
        )


async def _apply_batch(
    session: AsyncSession,
    ordered: tuple[ProviderScalarRefreshItem, ...],
    *,
    expected_digest: str,
    dataset_id: int,
    policy_revision: int,
    attempt_id: UUID,
    owner: UUID,
    manifest_digest: str,
    exclusive_protocol: bool,
) -> dict[str, Any]:
    await _arm_deadline(session)
    if exclusive_protocol:
        session.info.pop(FEATURE_CURATION_WRITE_WAIT_INFO_KEY, None)
        await lock_feature_curation_write(session)
    else:
        await lock_scoped_feature_write_protocol(session, exclusive=False)
    await lock_provider_field_policy_epoch(session)
    attempt = await begin_scoped_feature_write(
        session, attempt_id=attempt_id, owner=owner, manifest_digest=manifest_digest
    )
    if (
        attempt["input_digest"] != expected_digest
        or attempt["provider_dataset_id"] != dataset_id
        or attempt["exclusive_protocol"] is not exclusive_protocol
        or attempt["regions"]
        or not 3 * len(ordered) <= attempt["expected_members"] <= 8192
    ):
        raise ValueError("sealed scalar batch artifact does not match this input")
    if attempt["status"] == "completed":
        return attempt
    # 필요 dependency의 존재를 전수 검증한 뒤에만 count 등식이 완전성을 증명한다.
    for item in ordered:
        await native._assert_provider_scalar_target(
            session,
            item.bundle,
            feature_id=item.feature_id,
            dataset_id=dataset_id,
            policy_revision=policy_revision,
            attempt_id=attempt_id,
        )
    source_count = await session.scalar(
        text("""SELECT count(*) FROM (
            SELECT DISTINCT source_entity_key FROM provider_sync.source_links
            WHERE feature_id=ANY(CAST(:features AS uuid[])) LIMIT 8193
        ) required_sources"""),
        {"features": [item.feature_id for item in ordered]},
    )
    if type(source_count) is not int:
        raise ValueError("invalid scalar source count")
    required_members = 2 * len(ordered) + source_count
    if required_members > 8192 or attempt["expected_members"] != required_members:
        raise ValueError("scalar batch requires exactly its complete manifest")
    heads = []
    for item in ordered:
        current_key = await native._apply_provider_scalar(
            session,
            item.bundle,
            feature_id=item.feature_id,
            dataset_id=dataset_id,
            policy_revision=policy_revision,
            attempt_id=attempt_id,
            scalar_values=native._provider_scalar_values(item.bundle, feature_id=item.feature_id),
        )
        heads.append([str(item.feature_id), current_key])
    result_digest = hashlib.sha256(
        json.dumps([expected_digest, heads], separators=(",", ":")).encode()
    ).hexdigest()
    return await finish_scoped_feature_write(
        session, attempt_id=attempt_id, owner=owner, result_digest=result_digest
    )
