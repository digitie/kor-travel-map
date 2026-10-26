"""저장된 휴게소 전체 입력의 SH 적용 조각. 새 원천 호출이나 TX 소유권은 없다.

준비 RR snapshot은 권위가 아니다. 원 kernel 잠금 뒤 DB evidence를 다시 비교하고
같은 TX에서 counter/capture와 원 결과를 저장한다. collector의 불변 입력만 쓰며 TX를 소유하지 않는다.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from typing import Any, cast
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from kortravelmap.infra import scoped_provider_batch as batch
from kortravelmap.infra.feature_repo import FeatureLoadResult, _make_source_entity_key
from kortravelmap.infra.integrity_violation_repo import ensure_integrity_observation_run
from kortravelmap.infra.provider_field_candidates import lock_provider_field_policy_epoch
from kortravelmap.infra.provider_snapshot_artifact import (
    DecodedSnapshotArtifact,
    SnapshotArtifactPins,
)
from kortravelmap.infra.provider_snapshot_result import (
    SnapshotApplyResult,
    encode_snapshot_apply_result,
)
from kortravelmap.infra.rest_area_snapshot_artifact import decode_rest_area_snapshot_artifact
from kortravelmap.infra.scoped_feature_writes import lock_scoped_feature_write_protocol
from kortravelmap.infra.transaction_limits import apply_bounded_transaction_limits
from kortravelmap.infra.transport_rest_evidence_reader import decode_transport_rest_evidence
from kortravelmap.providers.kor_travel_rest_evidence import (
    RestReobservationPreparation,
    assess_transport_rest_area_reobservation_evidence,
)
from kortravelmap.providers.kor_travel_transport_apply import _counter_state


def _inputs(
    artifact: DecodedSnapshotArtifact, preparation: RestReobservationPreparation
) -> tuple[tuple[batch.ProviderScalarRefreshItem, ...], str, int, str]:
    if (
        type(artifact) is not DecodedSnapshotArtifact
        or type(preparation) is not RestReobservationPreparation
        or preparation.eligible is not True
        or preparation.reason != "unchanged_reobservation"
        or preparation.input_eof is not True
        or preparation.evidence.evidence_complete is not True
        or preparation.evidence.db_scope_eof is not True
    ):
        raise ValueError("complete unchanged rest-area preparation required")
    incoming = {
        _make_source_entity_key(
            provider=b.source_record.provider,
            dataset_key=b.source_record.dataset_key,
            source_entity_type=b.source_record.source_entity_type,
            source_entity_id=b.source_record.source_entity_id,
        ): b
        for b in artifact.bundles
    }
    items, rows, revisions = [], [], set()
    for raw in preparation.evidence.items:
        item = cast("dict[str, Any]", raw)
        entity = item["source_entity"]["source_entity_key"]
        bundle = incoming.pop(entity)
        fid = UUID(item["feature"]["feature_id"])
        revisions.add(item["policy"]["policy_revision"])
        items.append(batch.ProviderScalarRefreshItem(fid, bundle))
        rows.append(
            {
                "feature_id": str(fid),
                "source_entity_key": entity,
                "raw_payload_hash": bundle.source_record.raw_payload_hash,
            }
        )
    if incoming or len(revisions) != 1:
        raise ValueError("rest-area input scope or policy changed")
    revision = revisions.pop()
    ordered, digest = batch._prepare_batch(
        items, dataset_id=preparation.evidence.dataset_id, policy_revision=revision
    )
    return ordered, digest, revision, json.dumps(rows, sort_keys=True, separators=(",", ":"))


async def _read_locked_evidence(session: AsyncSession, dataset: int) -> object:
    """이 조회만 서버3초/lock1초·JIT OFF로 실행하고 성공 뒤 caller 설정을 복원한다.

    SQL 오류/취소 뒤에는 복원 SQL을 보내 원오류를 덮지 않는다. caller는 전체 TX를
    rollback해야 하며 SET LOCAL 설정도 그 rollback에 따라 복원된다. decoder/assessment는
    조회 성공 후 원래 설정으로 돌아온 구간에서 별도로 실행한다.
    """
    prior = {
        str(name): str(value)
        for name, value in (
            await session.execute(
                text(
                    "SELECT name,setting FROM pg_settings WHERE name IN "
                    "('statement_timeout','lock_timeout','jit')"
                )
            )
        ).all()
    }
    if set(prior) != {"statement_timeout", "lock_timeout", "jit"} or prior["jit"] not in {
        "on", "off"
    }:
        raise RuntimeError("rest-area reader settings are missing or invalid")
    await apply_bounded_transaction_limits(session, statement_timeout_ms=3000, lock_timeout_ms=1000)
    # 작은 검증 집합은 JIT 컴파일 비용을 피한다. 전체 TX/DB 설정은 바꾸지 않는다.
    await session.execute(
        text("SELECT set_config(:name,:value,true)"), {"name": "jit", "value": "off"}
    )
    raw: object = await session.scalar(
        text("SELECT feature.read_transport_rest_snapshot_evidence(:dataset)"),
        {"dataset": dataset},
    )
    for name, value in prior.items():
        await session.execute(
            text("SELECT set_config(:name,:value,true)"), {"name": name, "value": value}
        )
    return raw


async def apply_stored_rest_area_reobservation(
    session: AsyncSession,
    artifact_payload: bytes,
    preparation: RestReobservationPreparation,
    *,
    pins: SnapshotArtifactPins,
    snapshot_id: UUID,
    generation: int,
    fence: UUID,
    attempt_id: UUID,
    owner: UUID,
    manifest_digest: str,
) -> SnapshotApplyResult:
    """SH 원 적용만 수행한다. commit 불명 후 재호출 대신 SDK0 member read로 원 결과를 읽는다.

    입력 DTO/준비 evidence는 전체 await 동안 caller가 독점 소유한다. 실패·취소 시 caller는
    반드시 TX 전체를 rollback한다. 이미 적용된 상태를 새 counter/성공으로 바꾸지 않는다.
    """
    if not session.in_transaction():
        raise ValueError("explicit caller transaction required")
    if any(type(value) is not UUID for value in (snapshot_id, fence, attempt_id, owner)):
        raise ValueError("canonical snapshot and kernel UUIDs required")
    if type(generation) is not int or not 1 <= generation < 2**63:
        raise ValueError("positive executor generation required")
    artifact = decode_rest_area_snapshot_artifact(artifact_payload, expected_pins=pins)
    ordered, digest, revision, counter_payload = _inputs(artifact, preparation)
    dataset = preparation.evidence.dataset_id
    params = {"snapshot": snapshot_id, "generation": generation, "fence": fence}
    async with asyncio.timeout(30):
        await lock_scoped_feature_write_protocol(session, exclusive=False)
        await lock_provider_field_policy_epoch(session)
        binding = await session.scalar(
            text("""SELECT ops.begin_provider_snapshot_apply(
                :snapshot,:generation,:fence,:attempt,:owner,:manifest,:artifact_sha)"""),
            {
                **params,
                "attempt": attempt_id,
                "owner": owner,
                "manifest": manifest_digest,
                "artifact_sha": hashlib.sha256(artifact_payload).hexdigest(),
            },
        )
        attempt = await batch._begin_batch(
            session,
            ordered,
            expected_digest=digest,
            dataset_id=dataset,
            attempt_id=attempt_id,
            owner=owner,
            manifest_digest=manifest_digest,
            exclusive_protocol=False,
        )
        fresh = decode_transport_rest_evidence(
            dataset, await _read_locked_evidence(session, dataset)
        )
        if fresh != preparation.evidence:
            raise ValueError("rest-area evidence changed after locking; replan")
        assessed = await assess_transport_rest_area_reobservation_evidence(
            artifact.bundles, fresh, pins=pins, geo=artifact.geo
        )
        if assessed.eligible is not True:
            raise ValueError("stored rest-area input requires EX: " + assessed.reason)
        await batch._validate_batch_manifest(
            session,
            ordered,
            attempt=attempt,
            dataset_id=dataset,
            policy_revision=revision,
            attempt_id=attempt_id,
        )
        if (
            type(binding) is not dict
            or type(binding.get("snapshot_observation_generation")) is not str
        ):
            raise ValueError("original observation generation is missing from apply binding")
        await ensure_integrity_observation_run(
            session,
            provider_dataset_id=dataset,
            external_run_id=binding["snapshot_observation_generation"],
        )
        expected = {item.feature_id for item in ordered}
        before = await _counter_state(session, params, counter_payload, expected)
        heads = await batch._apply_batch_items(
            session, ordered, dataset_id=dataset, policy_revision=revision, attempt_id=attempt_id
        )
        after = await _counter_state(session, params, counter_payload, expected)
        if any(after[fid][0] < before[fid][0] or not after[fid][1] for fid in expected):
            raise ValueError("scalar apply result lacks original source record or revision")
        await batch._finish_batch(
            session, heads, expected_digest=digest, attempt_id=attempt_id, owner=owner
        )
        capture = (
            (
                await session.execute(
                    text(
                        "SELECT * FROM ops.capture_provider_snapshot_apply_input_set("
                        ":snapshot,:generation,:fence)"
                    ),
                    params,
                )
            )
            .mappings()
            .one()
        )
        load = FeatureLoadResult(
            bundles_total=len(ordered),
            features_updated=sum(after[fid][0] != before[fid][0] for fid in expected),
            source_records_inserted=sum(not before[fid][1] and after[fid][1] for fid in expected),
            curation_input_member_count=capture["input_member_count"],
            curation_input_set_hash=capture["source_input_set_hash"],
        )
        result = encode_snapshot_apply_result(load, retired=0)
        await session.execute(
            text("SELECT ops.finish_provider_snapshot_apply(:snapshot,:generation,:fence,:result)"),
            {**params, "result": result},
        )
    return SnapshotApplyResult(load, retired=0)
