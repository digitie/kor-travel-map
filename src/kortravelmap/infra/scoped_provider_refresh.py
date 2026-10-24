"""기존 primary membership의 명시 name/phones refresh. 전체 수집 전환용 entry가 아니다.

원천 호출과 manifest 준비는 바깥에서 완료한다. 이 함수는 caller의 READ COMMITTED
transaction 안에서 source/head, 후보, winner, 완료 receipt를 함께 바꾸며 commit하지 않는다.
신규 identity/link, Geo, retire/merge, 파일, 지역 분할은 처리하지 않는다.
기본 수집 경로에는 배선하지 않는다.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from kortravelmap.core.ids import make_payload_hash, make_source_record_key
from kortravelmap.dto import FeatureBundle, SourceRole
from kortravelmap.infra.feature_repo import (
    FEATURE_CURATION_WRITE_WAIT_INFO_KEY,
    _make_source_entity_key,
    _provider_field_patch_payload,
    _upsert_source_record_state,
    lock_feature_curation_write,
)
from kortravelmap.infra.provider_field_candidates import (
    capture_provider_field_candidates,
    lock_provider_field_policy_epoch,
    recompute_provider_field_candidates,
)
from kortravelmap.infra.scoped_feature_writes import (
    _arm_deadline,
    begin_scoped_feature_write,
    finish_scoped_feature_write,
    lock_scoped_feature_write_protocol,
)

_FIELDS = frozenset({"core.name", "place.phones"})
_MAX_INPUT_BYTES = 1_048_576


def _artifact_json_value(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return dict(value)  # raw_data를 재귀 복사하지 않는다.
    if isinstance(value, (set, frozenset)):
        return sorted(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, (UUID, Decimal)):
        return str(value)
    if isinstance(value, Enum):
        return value.value
    raise TypeError("unsupported scalar artifact value")


def _check_artifact_budget(value: Any, budget: list[int], depth: int = 0) -> None:
    # iterencode도 큰 단일 string을 한 번에 만들므로 복사/원천 hash 이전에 크기를 막는다.
    if depth > 64:
        raise ValueError("scalar refresh artifact nesting exceeds budget")
    budget[0] -= 8
    if isinstance(value, str):
        if len(value) > budget[0]:
            raise ValueError("scalar refresh artifact exceeds 1 MiB")
        budget[0] -= len(value.encode())
    elif isinstance(value, BaseModel):
        _check_artifact_budget(dict(value), budget, depth + 1)
    elif isinstance(value, dict):
        for key, child in value.items():
            _check_artifact_budget(key, budget, depth + 1)
            _check_artifact_budget(child, budget, depth + 1)
    elif isinstance(value, (list, tuple, set, frozenset)):
        for child in value:
            _check_artifact_budget(child, budget, depth + 1)
    if budget[0] < 0:
        raise ValueError("scalar refresh artifact exceeds 1 MiB")


def _artifact_digest(value: Any) -> str:
    _check_artifact_budget(value, [_MAX_INPUT_BYTES])
    digest = hashlib.sha256()
    size = 0
    encoder = json.JSONEncoder(
        default=_artifact_json_value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    for chunk in encoder.iterencode(value):
        encoded = chunk.encode()
        size += len(encoded)
        if size > _MAX_INPUT_BYTES:
            raise ValueError("scalar refresh artifact exceeds 1 MiB")
        digest.update(encoded)
    return digest.hexdigest()


def scoped_provider_refresh_input_digest(
    bundle: FeatureBundle, *, feature_id: UUID, dataset_id: int, policy_revision: int
) -> str:
    """claim.input_digest에 넣는 bounded artifact 지문. fetch 재시도를 유발하지 않는다."""
    if not isinstance(feature_id, UUID):
        raise ValueError("canonical Feature UUID required")
    if any(type(value) is not int or value < 1 for value in (dataset_id, policy_revision)):
        raise ValueError("positive dataset and policy revision required")
    presence = bundle.provider_field_presence
    if presence is None or not presence.supplied_fields <= _FIELDS:
        raise ValueError("explicit name/phones presence required")
    if (
        bundle.feature.kind.value != "place"
        or bundle.source_link.source_role != SourceRole.PRIMARY
        or bundle.source_record.expires_at is not None
        or bundle.file_sources
        or bundle.geo_attempt is not None
        or bundle.admin_evidence is not None
    ):
        raise ValueError("only existing unexpired primary place scalar refresh is supported")
    digest = _artifact_digest(
        ["native-scalar-v1", str(feature_id), dataset_id, policy_revision, bundle]
    )
    record = bundle.source_record
    if record.raw_payload_hash != make_payload_hash(
        record.raw_data, length=len(record.raw_payload_hash)
    ):
        raise ValueError("raw payload hash mismatch")
    if record.source_record_key != make_source_record_key(
        provider=record.provider,
        dataset_key=record.dataset_key,
        source_entity_type=record.source_entity_type,
        source_entity_id=record.source_entity_id,
        raw_payload_hash=record.raw_payload_hash,
    ):
        raise ValueError("source record key mismatch")
    return digest


async def refresh_scoped_provider_scalars(
    session: AsyncSession,
    bundle: FeatureBundle,
    *,
    feature_id: UUID,
    dataset_id: int,
    policy_revision: int,
    attempt_id: UUID,
    owner: UUID,
    manifest_digest: str,
) -> dict[str, Any]:
    """검증된 sealed plan의 실제 source→후보→winner 쓰기와 완료를 한 TX로 묶는다.

    40001/55P03/취소 시 caller는 TX 전체를 rollback한다. 같은 공유 TX에서 legacy
    경로로 fallback하지 않는다. 재계획은 새 transaction/attempt로 하며 원천 artifact는
    재사용한다. 완료된 동일 attempt 재호출은 source DML을 다시 실행하지 않는다.
    """
    return await _refresh_provider_scalars(
        session,
        bundle,
        feature_id=feature_id,
        dataset_id=dataset_id,
        policy_revision=policy_revision,
        attempt_id=attempt_id,
        owner=owner,
        manifest_digest=manifest_digest,
        exclusive_protocol=False,
    )


async def refresh_exclusive_provider_scalars(
    session: AsyncSession,
    bundle: FeatureBundle,
    *,
    feature_id: UUID,
    dataset_id: int,
    policy_revision: int,
    attempt_id: UUID,
    owner: UUID,
    manifest_digest: str,
) -> dict[str, Any]:
    """동일 후보/winner 의미를 기존 배타 protocol·전역 fence 아래 적용한다.

    Geo/link/신규 identity 변경 처리를 제공하지 않는다. caller는 지원 외 필드 불변을
    확인하고 같은 의미의 EX manifest를 별도 transaction에서 준비해야 한다. 자동
    fallback이나 collector 배선이 아니다."""
    return await _refresh_provider_scalars(
        session,
        bundle,
        feature_id=feature_id,
        dataset_id=dataset_id,
        policy_revision=policy_revision,
        attempt_id=attempt_id,
        owner=owner,
        manifest_digest=manifest_digest,
        exclusive_protocol=True,
    )


async def _refresh_provider_scalars(
    session: AsyncSession,
    bundle: FeatureBundle,
    *,
    feature_id: UUID,
    dataset_id: int,
    policy_revision: int,
    attempt_id: UUID,
    owner: UUID,
    manifest_digest: str,
    exclusive_protocol: bool,
) -> dict[str, Any]:
    if not session.in_transaction():
        raise ValueError("explicit caller transaction required")
    expected_digest = scoped_provider_refresh_input_digest(
        bundle, feature_id=feature_id, dataset_id=dataset_id, policy_revision=policy_revision
    )
    values, _ = _provider_field_patch_payload(
        bundle.feature, feature_uuid=str(feature_id), parent_feature_id=None
    )
    scalar_values = json.dumps(
        {key: value for key, value in json.loads(values).items() if key in _FIELDS},
        ensure_ascii=False,
        allow_nan=False,
    )
    await _arm_deadline(session)
    if exclusive_protocol:
        # legacy의 첫 fence 장기 대기 힌트가 native deadline을 늘리지 않게 소비한다.
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
    ):
        raise ValueError("sealed scalar refresh artifact does not match this input")
    if attempt["status"] == "completed":
        return attempt
    record = bundle.source_record
    entity = _make_source_entity_key(
        provider=record.provider,
        dataset_key=record.dataset_key,
        source_entity_type=record.source_entity_type,
        source_entity_id=record.source_entity_id,
    )
    # source DML 전에 현재 policy·dataset·기존 primary membership을 DB 권한으로 확인한다.
    await session.execute(
        text("""SELECT feature.assert_scoped_provider_scalar_target(
            :attempt,:feature,:dataset,:entity,:revision)"""),
        {
            "attempt": attempt_id,
            "feature": feature_id,
            "dataset": dataset_id,
            "entity": entity,
            "revision": policy_revision,
        },
    )
    state = await _upsert_source_record_state(session, record)
    current_key = await session.scalar(
        text("""SELECT current_source_record_key FROM provider_sync.source_entity_heads
            WHERE source_entity_key=:entity"""),
        {"entity": entity},
    )
    # became_current=False는 동일 관측과 오래된 artifact 모두 가능하다. 실제 head로 구분한다.
    if current_key == state.source_record_key:
        await capture_provider_field_candidates(
            session,
            feature_id=str(feature_id),
            dataset_id=dataset_id,
            entity_key=entity,
            record_key=state.source_record_key,
            values=scalar_values,
            geometry_wkt="{}",
            presence=bundle.provider_field_presence,
            attempt_id=str(attempt_id),
            policy_revision=policy_revision,
        )
    await recompute_provider_field_candidates(
        session,
        attempt_id=str(attempt_id),
        feature_id=str(feature_id),
        policy_revision=policy_revision,
    )
    result_digest = hashlib.sha256(
        json.dumps([expected_digest, current_key], separators=(",", ":")).encode()
    ).hexdigest()
    return await finish_scoped_feature_write(
        session, attempt_id=attempt_id, owner=owner, result_digest=result_digest
    )
