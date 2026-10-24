"""제한 active primary place의 명시 EX full refresh. 기본 collector 선택은 바꾸지 않는다.

caller는 planning부터 await 종료까지 입력 DTO/Geo 관측집합을 독점 소유한다. 원천/Geo
호출은 이 경계 밖에서 끝내고 실패/취소 시 caller TX 전체를 rollback한다. whole input
상한1MiB/2730을 유지하며 파일 업로드와 active identity/membership/lifecycle 변경은 없다.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any, Literal
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from kortravelmap.core.ids import make_payload_hash, make_source_record_key
from kortravelmap.dto import FeatureBundle, SourceRole
from kortravelmap.dto.geo_dataset import GeoLoadContext
from kortravelmap.infra import feature_repo as repo
from kortravelmap.infra import scoped_provider_refresh as native
from kortravelmap.infra.feature_identity import resolve_feature_identity
from kortravelmap.infra.provider_field_candidates import lock_provider_field_policy_epoch
from kortravelmap.infra.scoped_feature_writes import (
    ScopedWriteDependency,
    _arm_deadline,
    append_scoped_feature_write_manifest,
    begin_scoped_feature_write,
    claim_scoped_feature_write,
    finish_scoped_feature_write,
    seal_scoped_feature_write_manifest,
)

_MAX_ITEMS = 8192 // 3
_APPLY_SECONDS = 30.0
_PLAN_SECONDS = 30.0
_DOMAIN = "native-full-refresh-v1"


@dataclass(frozen=True)
class ExclusiveProviderSnapshotOptions:
    """constructor의 명시 scope 선택. 미래 입력/clock을 미리 만든 plan이 아니다."""

    provider: str
    dataset_key: str
    source_entity_type: str


@dataclass(frozen=True)
class ExclusiveProviderSnapshotPlan:
    """실제 최종 bundles+Geo에서 만들어진 한 dataset의 sealed attempt."""

    dataset_id: int
    active_targets: Mapping[UUID, int]
    attempt_id: UUID
    owner: UUID
    manifest_digest: str


@dataclass(frozen=True)
class ExclusiveProviderSnapshotResult:
    """replay는 DML0이며 과거 insert/update 카운트를 복원했다고 주장하지 않는다."""

    load: repo.FeatureLoadResult
    attempt: dict[str, Any]
    replayed: bool
    retired: int | None


def _prepare(
    bundles: Iterable[FeatureBundle],
    *,
    dataset_id: int,
    provider: str,
    dataset_key: str,
    source_entity_type: str,
    active_targets: Mapping[UUID, int],
    geo: GeoLoadContext | None,
    retire_geometryless_areas: bool,
) -> tuple[tuple[FeatureBundle, ...], str]:
    ordered: list[FeatureBundle] = []
    for bundle in bundles:
        if len(ordered) == _MAX_ITEMS:
            raise ValueError("full snapshot exceeds2730; no partial commit")
        ordered.append(bundle)
    if not ordered or not active_targets or len(active_targets) > _MAX_ITEMS:
        raise ValueError("bounded nonempty full snapshot and active targets required")
    if type(dataset_id) is not int or dataset_id < 1 or type(retire_geometryless_areas) is not bool:
        raise ValueError("invalid dataset or retirement option")
    if any(
        not isinstance(k, UUID) or type(v) is not int or v < 1 for k, v in active_targets.items()
    ):
        raise ValueError("canonical target UUID and positive revision required")
    geo_input = (
        None if geo is None else [geo.geo_applied, geo.current_dataset, geo.observed_data_tokens]
    )
    # 원입력순서를 보존한다. active 잠금 순서만 별도로 정렬한다. aggregate guard가
    # 개별 raw hash/JSON 복사보다 먼저 실행된다.
    fingerprint = native._artifact_digest(
        [
            _DOMAIN,
            dataset_id,
            provider,
            dataset_key,
            source_entity_type,
            [[str(k), v] for k, v in sorted(active_targets.items())],
            geo_input,
            retire_geometryless_areas,
            ordered,
        ]
    )
    _validate_sources(
        ordered, provider=provider, dataset_key=dataset_key, source_entity_type=source_entity_type
    )
    return tuple(ordered), fingerprint


def _validate_sources(
    ordered: Iterable[FeatureBundle], *, provider: str, dataset_key: str, source_entity_type: str
) -> None:
    identities = set()
    entities = set()
    for bundle in ordered:
        record = bundle.source_record
        entity = repo._make_source_entity_key(
            provider=record.provider,
            dataset_key=record.dataset_key,
            source_entity_type=record.source_entity_type,
            source_entity_id=record.source_entity_id,
        )
        identity = (bundle.feature.kind, bundle.feature.provider_natural_key)
        if (
            (record.provider, record.dataset_key, record.source_entity_type)
            != (provider, dataset_key, source_entity_type)
            or not identity[1]
            or identity in identities
            or entity in entities
        ):
            raise ValueError("mixed dataset or duplicate canonical/source input is unsupported")
        identities.add(identity)
        entities.add(entity)
        if record.expires_at is not None or bundle.source_link.source_role != SourceRole.PRIMARY:
            raise ValueError("only unexpired primary input is supported")
        if record.raw_payload_hash != make_payload_hash(
            record.raw_data, length=len(record.raw_payload_hash)
        ):
            raise ValueError("raw payload hash mismatch")
        if (
            record.source_record_key
            != make_source_record_key(
                provider=record.provider,
                dataset_key=record.dataset_key,
                source_entity_type=record.source_entity_type,
                source_entity_id=record.source_entity_id,
                raw_payload_hash=record.raw_payload_hash,
            )
            or bundle.source_link.source_record_key != record.source_record_key
        ):
            raise ValueError("source/link key mismatch")


def exclusive_provider_snapshot_input_digest(
    bundles: Iterable[FeatureBundle],
    *,
    dataset_id: int,
    provider: str,
    dataset_key: str,
    source_entity_type: str,
    active_targets: Mapping[UUID, int],
    geo: GeoLoadContext | None = None,
    retire_geometryless_areas: bool = False,
) -> str:
    """claim.input_digest. 전용 key는 domain:digest:attempt.hex로 별도 발급한다."""
    return _prepare(
        bundles,
        dataset_id=dataset_id,
        provider=provider,
        dataset_key=dataset_key,
        source_entity_type=source_entity_type,
        active_targets=active_targets,
        geo=geo,
        retire_geometryless_areas=retire_geometryless_areas,
    )[1]


def bounded_full_snapshot(
    bundles: Iterable[FeatureBundle],
    *,
    options: ExclusiveProviderSnapshotOptions,
    geo: GeoLoadContext | None,
    retire_geometryless_areas: bool,
) -> tuple[FeatureBundle, ...]:
    """최종 converter 입력을 MAX+1에서 멈추고 planning 첫 SQL 전에 aggregate 예산 검사."""
    result: list[FeatureBundle] = []
    for bundle in bundles:
        if len(result) == _MAX_ITEMS:
            raise ValueError("full snapshot exceeds2730; no partial commit")
        result.append(bundle)
    if not result:
        raise ValueError("empty full snapshot is unsupported")
    native._artifact_digest(
        [
            _DOMAIN,
            options.provider,
            options.dataset_key,
            options.source_entity_type,
            result,
            None
            if geo is None
            else [geo.geo_applied, geo.current_dataset, geo.observed_data_tokens],
            retire_geometryless_areas,
        ]
    )
    _validate_sources(
        result,
        provider=options.provider,
        dataset_key=options.dataset_key,
        source_entity_type=options.source_entity_type,
    )
    return tuple(result)


async def prepare_exclusive_provider_snapshot(
    session: AsyncSession,
    bundles: tuple[FeatureBundle, ...],
    *,
    options: ExclusiveProviderSnapshotOptions,
    geo: GeoLoadContext | None = None,
    retire_geometryless_areas: bool = False,
) -> ExclusiveProviderSnapshotPlan | None:
    """한 fresh planning TX. 실제 snapshot을 받고 만들며 commit은 caller 소유다."""
    async with asyncio.timeout(_PLAN_SECONDS):
        return await _prepare_exclusive_provider_snapshot(
            session,
            bundles,
            options=options,
            geo=geo,
            retire_geometryless_areas=retire_geometryless_areas,
        )


async def _prepare_exclusive_provider_snapshot(
    session: AsyncSession,
    bundles: tuple[FeatureBundle, ...],
    *,
    options: ExclusiveProviderSnapshotOptions,
    geo: GeoLoadContext | None,
    retire_geometryless_areas: bool,
) -> ExclusiveProviderSnapshotPlan | None:
    if not session.in_transaction():
        raise ValueError("explicit planning transaction required")
    bundles = bounded_full_snapshot(
        bundles, options=options, geo=geo, retire_geometryless_areas=retire_geometryless_areas
    )
    await _arm_deadline(session)
    session.info.pop(repo.FEATURE_CURATION_WRITE_WAIT_INFO_KEY, None)
    await repo.lock_feature_curation_write(session)
    await lock_provider_field_policy_epoch(session)
    dataset = await session.scalar(
        text("""SELECT provider_dataset_id
        FROM provider_sync.provider_datasets WHERE provider=:provider AND dataset_key=:key
        AND is_active"""),
        {"provider": options.provider, "key": options.dataset_key},
    )
    if type(dataset) is not int:
        raise ValueError("full refresh requires a declared active dataset")
    entities = [
        repo._make_source_entity_key(
            provider=b.source_record.provider,
            dataset_key=b.source_record.dataset_key,
            source_entity_type=b.source_record.source_entity_type,
            source_entity_id=b.source_record.source_entity_id,
        )
        for b in bundles
    ]
    policies = await session.scalar(
        text("""SELECT feature.validate_exclusive_provider_snapshot(
        NULL,:dataset,NULL,CAST(:entities AS text[]))"""),
        {"dataset": dataset, "entities": entities},
    )
    if not policies:
        return None
    targets = {UUID(k): int(v[0]) for k, v in policies.items()}
    fingerprint = exclusive_provider_snapshot_input_digest(
        bundles,
        dataset_id=dataset,
        provider=options.provider,
        dataset_key=options.dataset_key,
        source_entity_type=options.source_entity_type,
        active_targets=targets,
        geo=geo,
        retire_geometryless_areas=retire_geometryless_areas,
    )
    dependencies: dict[
        tuple[Literal["feature", "feature_membership", "source_head"], str], str
    ] = {}
    feature_rows = (
        await session.execute(
            text("""SELECT feature_id,row_revision,
        ops.scoped_feature_write_membership_digest(feature_id)
        FROM feature.features WHERE feature_id=ANY(CAST(:features AS uuid[]))
        ORDER BY feature_id"""),
            {"features": list(targets)},
        )
    ).all()
    if len(feature_rows) != len(targets):
        raise ValueError("active Feature disappeared while planning")
    for feature, revision, membership in feature_rows:
        dependencies[("feature", str(feature))] = str(revision)
        dependencies[("feature_membership", str(feature))] = membership
    heads = (
        await session.execute(
            text("""SELECT DISTINCT source_entity_key,current_source_record_key
        FROM provider_sync.source_links
        JOIN provider_sync.source_entity_heads USING(source_entity_key)
        WHERE feature_id=ANY(CAST(:features AS uuid[])) ORDER BY source_entity_key LIMIT 8193"""),
            {"features": list(targets)},
        )
    ).all()
    for entity, key in heads:
        dependencies[("source_head", entity)] = key
    if len(dependencies) > 8192:
        raise ValueError("complete active manifest exceeds8192")
    attempt, owner = uuid4(), uuid4()
    await claim_scoped_feature_write(
        session,
        attempt_id=attempt,
        owner=owner,
        dataset_id=dataset,
        idempotency_key=_DOMAIN + ":" + fingerprint + ":" + attempt.hex,
        regions=(),
        expected_members=len(dependencies),
        input_digest=fingerprint,
        exclusive_protocol=True,
        lease_seconds=60,
    )
    members = [
        ScopedWriteDependency(i, kind, key, value)
        for i, ((kind, key), value) in enumerate(sorted(dependencies.items()))
    ]
    for start in range(0, len(members), 256):
        await append_scoped_feature_write_manifest(
            session, attempt_id=attempt, owner=owner, members=members[start : start + 256]
        )
    manifest = await seal_scoped_feature_write_manifest(session, attempt_id=attempt, owner=owner)
    return ExclusiveProviderSnapshotPlan(dataset, targets, attempt, owner, manifest)


async def refresh_exclusive_provider_snapshot(
    session: AsyncSession,
    bundles: Iterable[FeatureBundle],
    *,
    dataset_id: int,
    provider: str,
    dataset_key: str,
    source_entity_type: str,
    active_targets: Mapping[UUID, int],
    attempt_id: UUID,
    owner: UUID,
    manifest_digest: str,
    geo: GeoLoadContext | None = None,
    retire_geometryless_areas: bool = False,
) -> ExclusiveProviderSnapshotResult:
    """RC load→retire→capture→attempt finish만 수행한다. commit/영속 child seal은 caller 소유."""
    if not session.in_transaction():
        raise ValueError("explicit caller transaction required")
    async with asyncio.timeout(_APPLY_SECONDS):
        ordered, fingerprint = _prepare(
            bundles,
            dataset_id=dataset_id,
            provider=provider,
            dataset_key=dataset_key,
            source_entity_type=source_entity_type,
            active_targets=active_targets,
            geo=geo,
            retire_geometryless_areas=retire_geometryless_areas,
        )
        await _arm_deadline(session)
        session.info.pop(repo.FEATURE_CURATION_WRITE_WAIT_INFO_KEY, None)
        await repo.lock_feature_curation_write(session)
        await lock_provider_field_policy_epoch(session)
        attempt = await begin_scoped_feature_write(
            session,
            attempt_id=attempt_id,
            owner=owner,
            manifest_digest=manifest_digest,
        )
        if (
            attempt["input_digest"] != fingerprint
            or attempt["provider_dataset_id"] != dataset_id
            or attempt["exclusive_protocol"] is not True
            or attempt["regions"]
            or attempt["idempotency_key"] != _DOMAIN + ":" + fingerprint + ":" + attempt_id.hex
        ):
            raise ValueError("sealed full input/mode does not match")
        entities = []
        resolved_ids = set()
        for bundle in ordered:
            identity = await resolve_feature_identity(session, bundle.feature.feature_id)
            assert bundle.feature.provider_natural_key is not None
            resolved = await repo._resolve_provider_feature_id(
                session,
                provider_dataset_id=dataset_id,
                feature_kind=bundle.feature.kind.value,
                natural_key=bundle.feature.provider_natural_key,
            )
            if identity is not None and str(identity.feature_id) != resolved:
                raise ValueError("alias and canonical provider claim disagree")
            if resolved is not None:
                if resolved in resolved_ids:
                    raise ValueError("multiple full inputs resolve to one canonical Feature")
                resolved_ids.add(resolved)
            entity = repo._make_source_entity_key(
                provider=provider,
                dataset_key=dataset_key,
                source_entity_type=source_entity_type,
                source_entity_id=bundle.source_record.source_entity_id,
            )
            entities.append(entity)
            if resolved is not None and UUID(resolved) in active_targets:
                if bundle.feature.kind.value != "place" or bundle.provider_field_presence is None:
                    raise ValueError("active full target requires typed place and presence")
                # 같은 membership이어도 metadata 변경은 숨기지 않는다. 동일 link만 DML을 생략한다.
                link = (
                    await session.execute(
                        text("""SELECT source_role,match_method,confidence
                    FROM provider_sync.source_links WHERE feature_id=CAST(:feature AS uuid)
                    AND source_entity_key=:entity"""),
                        {"feature": resolved, "entity": entity},
                    )
                ).one_or_none()
                if link is None or tuple(link) != (
                    bundle.source_link.source_role.value,
                    bundle.source_link.match_method,
                    bundle.source_link.confidence,
                ):
                    raise ValueError("active primary link metadata changed")
        if not {str(key) for key in active_targets} <= resolved_ids:
            raise ValueError("active target is not a canonical identity of this full input")
        policies = await session.scalar(
            text("""SELECT feature.validate_exclusive_provider_snapshot(
            :attempt,:dataset,CAST(:targets AS jsonb),CAST(:entities AS text[]))"""),
            {
                "attempt": attempt_id,
                "dataset": dataset_id,
                "targets": json.dumps({str(k): v for k, v in active_targets.items()}),
                "entities": entities,
            },
        )
        context = repo._ExclusiveProviderRefresh(
            attempt_id, {key: (value[0], frozenset(value[1])) for key, value in policies.items()}
        )
        if attempt["status"] == "completed":
            capture = await repo.capture_provider_curation_input(
                session, provider=provider, dataset_key=dataset_key
            )
            result = _result_digest(
                fingerprint,
                manifest_digest,
                capture,
                context,
                await _read_target_state(session, entities),
            )
            if result != attempt["result_digest"]:
                raise ValueError("completed full snapshot is stale; replan without DML")
            return ExclusiveProviderSnapshotResult(capture, attempt, True, None)
        load = await repo.load_bundles(session, ordered, geo=geo, _exclusive_refresh=context)
        retired = 0
        if retire_geometryless_areas:
            retired = await repo.retire_geometryless_area_features_by_source(
                session,
                provider=provider,
                dataset_key=dataset_key,
                source_entity_type=source_entity_type,
            )
        capture = await repo.capture_provider_curation_input(
            session, provider=provider, dataset_key=dataset_key
        )
        attempt = await finish_scoped_feature_write(
            session,
            attempt_id=attempt_id,
            owner=owner,
            result_digest=_result_digest(
                fingerprint,
                manifest_digest,
                capture,
                context,
                await _read_target_state(session, entities),
            ),
        )
        return ExclusiveProviderSnapshotResult(load.merge(capture), attempt, False, retired)


async def _read_target_state(session: AsyncSession, entities: list[str]) -> list[list[str]]:
    # capture 원장에는 Geo stamp가 없다. 입력 target을 먼저 bounded DISTINCT한 뒤
    # 모든 core UPDATE는 정본 BEFORE trigger가 row_revision을 올린다.
    # core 전체 JSON 재직렬화 없이 revision과 독립 Geo stamp의 DB hash만 전송한다.
    rows = (
        await session.execute(
            text("""WITH targets AS (
        SELECT DISTINCT feature_id FROM provider_sync.source_links
        WHERE source_entity_key=ANY(CAST(:entities AS text[])) ORDER BY feature_id LIMIT 2731
    ) SELECT core.feature_id::text,encode(x_extension.digest(convert_to(
        jsonb_build_array(core.feature_id,core.row_revision,to_jsonb(stamp))::text,'UTF8'),'sha256'),'hex')
      FROM targets JOIN feature.features core USING(feature_id)
      LEFT JOIN feature.feature_geocode_stamps stamp USING(feature_id)
      ORDER BY core.feature_id"""),
            {"entities": entities},
        )
    ).all()
    if len(rows) > _MAX_ITEMS:
        raise ValueError("full result target set exceeds2730")
    return [[str(feature), str(fingerprint)] for feature, fingerprint in rows]


def _result_digest(
    fingerprint: str,
    manifest: str,
    capture: repo.FeatureLoadResult,
    context: repo._ExclusiveProviderRefresh,
    target_state: list[list[str]],
) -> str:
    return hashlib.sha256(
        json.dumps(
            [
                "native-full-refresh-result-v1",
                fingerprint,
                manifest,
                [
                    [key, rev, sorted(fields)]
                    for key, (rev, fields) in sorted(context.policies.items())
                ],
                capture.curation_input_member_count,
                capture.curation_input_set_hash,
                target_state,
            ],
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
