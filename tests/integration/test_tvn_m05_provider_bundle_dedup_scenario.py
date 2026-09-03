"""T-VN-M05 — 승인 manual Feature × 실적재 provider Feature의 dedup 전 구간 시나리오.

> 파일명이 ``test_tvn_m05_*`` 접두인 이유: 이 테스트는 실제 Feature/claim/origin/
> source_record 행을 남긴다(append-only 계보 — 삭제 불가). 전역 개수를 세는 이웃
> (``test_mois_loader``, ``test_tvn_m01_*``)이 **먼저** 돌아야 오염되지 않으므로,
> 알파벳 정렬로 그 뒤에 서도록 기존 ``test_tvn_m0*`` 파일과 같은 접두를 쓴다
> (``test_tvn_m03_import_child_issuance`` 헤더의 같은 규약).

기존 ``test_tvn_m05_manual_provider_dedup``은 role/evidence 경계를 본다. 다만 그
파일은 provider source proof를 ``repeat('b', 64)``로 **직접 심기 때문에** 실적재
규약(``make_payload_hash`` 기본 32-hex prefix)을 한 번도 통과시키지 않았다. 그래서
``ops.manual_provider_dedup_cases.source_record_raw_payload_hash``의 사본 CHECK만
64-hex를 강제하던 결함이 2026-09-01 isolated one-shot(e2e16)에서야 드러났고
(``303``이 수리), 그때까지 **기본 규약으로 적재된 모든 provider**가 M05 case
기록에서 깨지는 상태였다.

이 모듈은 그 경로를 격리 run 없이 재현한다.

1. M04 승인 경로(``feature_request_repo.submit`` → ``approve``)로 manual Feature.
2. 실 provider 변환 + ``feature_repo.load_bundle``로 provider Feature 적재
   (payload hash는 ``make_payload_hash`` 기본값 — 테스트가 규약을 우회하지 않는다).
3. ``feature.record_manual_provider_dedup_candidate``로 case 기록. **``303``
   이전에는 이 한 줄이 ``ck_manual_provider_dedup_cases_hashes`` 위반으로 죽는다.**
4. M05 admin read/decision repo(``list`` / ``get`` / ``resolve``).
5. reconciliation feed repo(``lease`` / ``preflight`` / ``ack`` —
   ``/v1/service/feature-reference-reconciliations`` 라우터의 백엔드)까지 소비.

식별자 축(2026-09-01 e2e15 클래스)도 같이 못박는다.
``ops.feature_requests.resolved_feature_id``는 **uuid** 컬럼(FK →
``feature.features.feature_uuid``)인데 승인 queue projection은 그 값을
``feature_id``라는 이름으로 노출한다. 그 값을 그대로 dedup detector에 넘기면
``feature.features.feature_id``(text)로 조회되지 않아 23514
``ck_m05_candidate_feature_proof``("Feature proof is not eligible")가 난다 —
NOT FOUND가 **eligibility 위반으로 위장**된다. writer receipt가 주는 text
``feature_id``로만 성립한다는 것을 manual/provider 양축에서 단언한다.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from kortravelmap.core.ids import PAYLOAD_HASH_DEFAULT_LENGTH
from kortravelmap.infra import feature_reference_reconciliation_repo as m05_repo
from kortravelmap.infra import feature_repo, feature_request_repo
from kortravelmap.infra.db import make_async_engine
from kortravelmap.infra.domain_command_repo import (
    canonical_domain_command_fingerprint,
    create_domain_command_claim,
)
from kortravelmap.infra.feature_update_active_repo import (
    _driver_constraint_identity,
)
from kortravelmap.providers.standard_data import (
    DATASET_KEY_TOURIST_ATTRACTIONS,
    STANDARD_DATA_PROVIDER_NAME,
    tourist_attractions_to_bundles,
)

pytestmark = [
    pytest.mark.integration,
    pytest.mark.usefixtures("tvn_m01_m05_role_graph"),
]

_RUNTIME_PASSWORD = "tvn40-test-only-runtime-password"
_SERVICE_PRINCIPAL = "service:feature-reference-reconciliation"
_SCORER_ID = "manual-provider-v1"
_FETCHED_AT = datetime(2026, 9, 1, 3, 0, tzinfo=UTC)

# 좌표는 소수 표기에 후행 0이 없어야 한다 — M04 승인 writer가
# ``p_feature_payload ->> 'lon'``과 request payload의 jsonb 텍스트를 **문자열로**
# 비교하는데, PostgreSQL jsonb numeric은 scale을 보존하고 Python float repr은
# 후행 0을 지운다(예: 126.978410 vs 126.97841).
_MANUAL_LON = 126.978511
_MANUAL_LAT = 37.566611
_PROVIDER_LON = 126.978411
_PROVIDER_LAT = 37.566511

_CAUSATION: dict[str, Any] = {
    "scope": "integration",
    "harness": "tvn-m05-provider-bundle",
}

_RECORD_CANDIDATE_SQL = """
CALL feature.record_manual_provider_dedup_candidate(
    CAST(:manual_feature_id AS text), CAST(:provider_feature_id AS text),
    CAST(:scores AS jsonb), CAST(:causation AS jsonb), NULL::uuid, NULL::text
)
"""

_CURRENT_PRIMARY_HASH_SQL = """
SELECT source.raw_payload_hash
FROM provider_sync.source_links AS link
JOIN provider_sync.source_entity_heads AS head
  ON head.source_entity_key = link.source_entity_key
JOIN provider_sync.source_records AS source
  ON source.source_entity_key = head.source_entity_key
 AND source.source_record_key = head.current_source_record_key
WHERE link.feature_id = :feature_id
  AND link.source_role = 'primary'
"""

_EVENT_SQL = """
SELECT event_sequence, event_sha256, action
FROM ops.feature_reference_reconciliation_events
WHERE event_id = CAST(:event_id AS uuid)
"""

_FEATURE_STATE_SQL = """
SELECT lifecycle_state, publication_state, row_revision
FROM feature.features
WHERE feature_id = :feature_id
"""

_SEED_SUBSCRIPTION_SQL = """
INSERT INTO ops.feature_reference_reconciliation_subscriptions (
    principal_id, initial_event_sequence, read_scope, ack_scope
) VALUES (
    :principal_id, :cursor,
    'feature-reference-reconciliation:read',
    'feature-reference-reconciliation:ack'
)
"""

_SEED_LEASE_SQL = """
INSERT INTO ops.feature_reference_reconciliation_leases (
    principal_id, acked_through_sequence, worker_id, lease_epoch, lease_expires_at
) VALUES (:principal_id, :cursor, NULL, 0, NULL)
"""

_CONSTRAINT_DEF_SQL = """
SELECT pg_get_constraintdef(oid)
FROM pg_catalog.pg_constraint
WHERE conrelid = CAST(:relation AS regclass) AND conname = :constraint_name
"""


def _sqlstate(error: DBAPIError) -> str | None:
    sqlstate, _ = _driver_constraint_identity(error)
    return str(sqlstate) if sqlstate is not None else None


def _constraint_name(error: DBAPIError) -> str | None:
    _, name = _driver_constraint_identity(error)
    return str(name) if name is not None else None


@dataclass(frozen=True)
class _TouristAttraction:
    """``PublicTouristAttractionItem`` Protocol 만족 (provider 실모델 필드명, ADR-044)."""

    trrsrt_nm: str | None
    trrsrt_se: str | None
    rdnmadr: str | None
    lnmadr: str | None
    latitude: float | None
    longitude: float | None
    phone_number: str | None
    instt_code: str | None
    raw: Any = None


@dataclass(frozen=True)
class _DedupScenario:
    """한 dedup episode가 필요로 하는 두 Feature의 실제 identity."""

    actor: str
    manual_feature_id: str
    manual_feature_uuid: str
    #: 승인 queue projection(``resolved_feature_id``)이 ``feature_id``라는 이름으로
    #: 노출하는 값 — 실제로는 UUID 정본이다(e2e15).
    approval_projection_feature_id: str
    provider_feature_id: str
    provider_payload_hash: str


def _runtime_engine(engine: AsyncEngine, *, login: str) -> AsyncEngine:
    dsn = engine.url.set(username=login, password=_RUNTIME_PASSWORD).render_as_string(
        hide_password=False
    )
    return make_async_engine(dsn, pool_size=1)


async def _open_command(
    engine: AsyncEngine, *, actor: str, operation: str, payload: object
) -> int:
    """실제 domain command claim writer로 open command 하나를 만든다."""

    async with AsyncSession(engine, expire_on_commit=False) as session, session.begin():
        claim = await create_domain_command_claim(
            session,
            actor=actor,
            operation=operation,
            idempotency_key=str(uuid4()),
            request_fingerprint=canonical_domain_command_fingerprint(payload),
        )
        return claim.command_id


async def _approve_requested_manual_feature(
    api: AsyncEngine, *, suffix: str
) -> tuple[str, str, str, str]:
    """M04 queue 실경로로 ``manual_request`` origin Feature를 만든다.

    반환은 ``(actor, text feature_id, feature_uuid, 승인 projection feature_id)``.
    마지막 값이 e2e15가 밟은 UUID 정본이다.
    """

    request_id = uuid4()
    actor = f"admin:tvn-m05-bundle-{suffix}"
    request_payload: dict[str, Any] = {
        "kind": "place",
        "name": f"M05 시나리오 요청 장소 {suffix[:8]}",
        "lon": _MANUAL_LON,
        "lat": _MANUAL_LAT,
        "categories": ["external-request"],
        "note": "tvn-m05 provider bundle dedup scenario",
    }
    submit_command = await _open_command(
        api,
        actor="service:feature-request",
        operation="service.feature-request.submit.v1",
        payload=request_payload,
    )
    async with AsyncSession(api, expire_on_commit=False) as session, session.begin():
        await session.execute(text("SET TRANSACTION ISOLATION LEVEL READ COMMITTED"))
        status, _submitted_at = await feature_request_repo.submit_feature_request(
            session,
            request_id=request_id,
            request_payload=request_payload,
            command_id=submit_command,
        )
    assert status == "pending"

    approve_command = await _open_command(
        api,
        actor=actor,
        operation="admin.feature-request.approve.v1",
        payload={"request_id": str(request_id), "category": "01070300"},
    )
    async with AsyncSession(api, expire_on_commit=False) as session, session.begin():
        await session.execute(text("SET TRANSACTION ISOLATION LEVEL READ COMMITTED"))
        pending = await feature_request_repo.get_feature_request(
            session, request_id=request_id
        )
        assert pending is not None
        assert pending.status == "pending"
        created = await feature_request_repo.approve_feature_request(
            session,
            request=pending,
            category="01070300",
            marker_color="P-03",
            marker_icon="marker",
            command_id=approve_command,
        )
    assert isinstance(created, feature_request_repo.FeatureRequestCreated)

    async with AsyncSession(api, expire_on_commit=False) as session:
        approved = await feature_request_repo.get_feature_request(
            session, request_id=request_id
        )
    assert approved is not None
    assert approved.status == "approved"
    assert approved.resolved_feature_id is not None
    return actor, created.feature_id, created.feature_uuid, approved.resolved_feature_id


def _tourist_item(suffix: str) -> _TouristAttraction:
    return _TouristAttraction(
        trrsrt_nm=f"M05 시나리오 관광지 {suffix[:8]}",
        trrsrt_se="관광지",
        rdnmadr="서울특별시 중구 세종대로 110",
        lnmadr="서울특별시 중구 태평로1가 31",
        latitude=_PROVIDER_LAT,
        longitude=_PROVIDER_LON,
        phone_number="02-120",
        instt_code=f"M05-BUNDLE-{suffix[:12]}",
    )


async def _load_provider_feature(engine: AsyncEngine, *, suffix: str) -> tuple[str, str]:
    """실 provider 변환 + 실 loader로 provider Feature를 적재한다.

    payload hash 규약을 테스트가 다시 쓰지 않는 것이 이 harness의 존재 이유다 —
    ``make_payload_hash``의 기본 32-hex prefix가 그대로
    ``provider_sync.source_records``에 들어가야 M05 사본 도메인이 실제로 검증된다.
    """

    bundle = (
        await tourist_attractions_to_bundles(
            [_tourist_item(suffix)],  # type: ignore[list-item]
            fetched_at=_FETCHED_AT,
        )
    )[0]
    assert bundle.source_record.provider == STANDARD_DATA_PROVIDER_NAME
    assert bundle.source_record.dataset_key == DATASET_KEY_TOURIST_ATTRACTIONS
    async with AsyncSession(engine, expire_on_commit=False) as session, session.begin():
        result = await feature_repo.load_bundle(session, bundle)
    assert result.features_inserted == 1
    assert result.source_records_inserted == 1
    assert result.source_links_inserted == 1
    return bundle.feature.feature_id, bundle.source_record.raw_payload_hash


async def _seed_scenario(
    migrated_engine: AsyncEngine, api: AsyncEngine, *, suffix: str
) -> _DedupScenario:
    (
        actor,
        manual_feature_id,
        manual_feature_uuid,
        projection_feature_id,
    ) = await _approve_requested_manual_feature(api, suffix=suffix)
    provider_feature_id, payload_hash = await _load_provider_feature(
        migrated_engine, suffix=suffix
    )
    return _DedupScenario(
        actor=actor,
        manual_feature_id=manual_feature_id,
        manual_feature_uuid=manual_feature_uuid,
        approval_projection_feature_id=projection_feature_id,
        provider_feature_id=provider_feature_id,
        provider_payload_hash=payload_hash,
    )


def _scores(*, manual_feature_id: str, provider_feature_id: str) -> dict[str, Any]:
    canonical = json.dumps(
        {
            "scorer_id": _SCORER_ID,
            "manual_feature_id": manual_feature_id,
            "provider_feature_id": provider_feature_id,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return {
        "name_score": 0.91,
        "spatial_score": 0.99,
        "category_score": 0.75,
        "total_score": 0.93,
        "distance_meters": 13.9,
        "scorer_input_sha256": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
    }


async def _record_candidate(
    dagster: AsyncEngine,
    *,
    manual_feature_id: str,
    provider_feature_id: str,
    scores: Mapping[str, Any],
) -> Mapping[str, Any]:
    """detector executor(Dagster LOGIN)로 case를 기록한다.

    M05 detector는 아직 Python 경로가 없다(SECURITY DEFINER procedure가 정본).
    executor 경계를 우회하지 않도록 실제 Dagster LOGIN으로 호출한다.
    """

    async with dagster.begin() as connection:
        await connection.execute(text("SET TRANSACTION ISOLATION LEVEL READ COMMITTED"))
        return dict(
            (
                await connection.execute(
                    text(_RECORD_CANDIDATE_SQL),
                    {
                        "manual_feature_id": manual_feature_id,
                        "provider_feature_id": provider_feature_id,
                        "scores": json.dumps(dict(scores)),
                        "causation": json.dumps(_CAUSATION),
                    },
                )
            )
            .mappings()
            .one()
        )


async def _ensure_paired_consumer(api: AsyncEngine, *, actor: str) -> None:
    """M05 decision writer의 활성화 게이트(paired consumer 등록)를 보장한다.

    이미 등록돼 있으면 ``already_provisioned``다 — 이 모듈은 등록 순서를 다른
    파일에 의존하지 않는다(단독 실행에서도 성립해야 한다).
    """

    command_id = await _open_command(
        api,
        actor=actor,
        operation="admin.feature-reference-reconciliation-subscription.provision.v1",
        payload={"principal_id": _SERVICE_PRINCIPAL},
    )
    async with AsyncSession(api, expire_on_commit=False) as session, session.begin():
        await session.execute(text("SET TRANSACTION ISOLATION LEVEL READ COMMITTED"))
        receipt = await m05_repo.provision_feature_reference_reconciliation_subscription(
            session,
            principal_id=_SERVICE_PRINCIPAL,
            initial_event_sequence=0,
            actor=actor,
            command_id=command_id,
        )
    assert receipt.outcome in {"provisioned", "already_provisioned"}
    assert receipt.initial_event_sequence == 0


async def _seed_isolated_consumer(
    migrated_engine: AsyncEngine, *, principal_id: str, cursor: int
) -> None:
    """이 시나리오 전용 consumer cursor를 심는다.

    ``provision_feature_reference_reconciliation_subscription``은 정본 principal
    하나만 sequence 0으로 받는다. 다른 모듈이 남긴 event를 먼저 소비하지 않고 이
    시나리오의 event **하나만** lease하려면 cursor를 직접 심어야 한다 — 기존
    ``test_tvn_m05_manual_provider_dedup``과 같은 규약이다.
    """

    async with migrated_engine.begin() as connection:
        await connection.execute(
            text(_SEED_SUBSCRIPTION_SQL),
            {"principal_id": principal_id, "cursor": cursor},
        )
        await connection.execute(
            text(_SEED_LEASE_SQL),
            {"principal_id": principal_id, "cursor": cursor},
        )


async def test_default_payload_hash_provider_bundle_reaches_case_decision_and_feed(
    migrated_engine: AsyncEngine,
) -> None:
    """실적재 32-hex payload hash가 case → 판정 → reconciliation feed까지 살아간다.

    ``303`` 이전에는 candidate 기록 자체가
    ``ck_manual_provider_dedup_cases_hashes``(64-hex 강제) 위반으로 죽었다.
    """

    suffix = uuid4().hex
    api = _runtime_engine(migrated_engine, login="ktm_feature_api_runtime")
    dagster = _runtime_engine(migrated_engine, login="ktm_feature_dagster_runtime")
    try:
        scenario = await _seed_scenario(migrated_engine, api, suffix=suffix)

        # 앵커 ① — 실적재 규약이 32-hex라는 사실 자체를 값으로 고정한다.
        assert len(scenario.provider_payload_hash) == PAYLOAD_HASH_DEFAULT_LENGTH
        assert PAYLOAD_HASH_DEFAULT_LENGTH < 64
        assert set(scenario.provider_payload_hash) <= set("0123456789abcdef")
        async with migrated_engine.connect() as connection:
            stored_hash = await connection.scalar(
                text(_CURRENT_PRIMARY_HASH_SQL),
                {"feature_id": scenario.provider_feature_id},
            )
        assert stored_hash == scenario.provider_payload_hash

        scores = _scores(
            manual_feature_id=scenario.manual_feature_id,
            provider_feature_id=scenario.provider_feature_id,
        )
        # 앵커 ② — 303이 없으면 이 CALL이 CheckViolation으로 죽는다.
        receipt = await _record_candidate(
            dagster,
            manual_feature_id=scenario.manual_feature_id,
            provider_feature_id=scenario.provider_feature_id,
            scores=scores,
        )
        assert receipt["o_outcome"] == "created"
        case_id = UUID(str(receipt["o_case_id"]))

        replayed = await _record_candidate(
            dagster,
            manual_feature_id=scenario.manual_feature_id,
            provider_feature_id=scenario.provider_feature_id,
            scores=scores,
        )
        assert replayed["o_outcome"] == "idempotent"
        assert UUID(str(replayed["o_case_id"])) == case_id

        async with AsyncSession(api, expire_on_commit=False) as session:
            detail = await m05_repo.get_manual_provider_dedup_case(
                session, case_id=case_id
            )
            page = await m05_repo.list_manual_provider_dedup_cases(
                session,
                status="pending",
                after_created_at=None,
                after_case_id=None,
                limit=100,
            )
        assert detail is not None
        data = detail.data
        assert data["status"] == "pending"
        assert data["manual_feature"]["feature_id"] == scenario.manual_feature_id
        assert data["manual_feature"]["feature_uuid"] == scenario.manual_feature_uuid
        assert data["provider_feature"]["feature_id"] == scenario.provider_feature_id
        # 앵커 ③ — 사본이 원본 hash를 **그대로** 옮겼는지(잘라내기·재계산 없음).
        assert (
            data["provider_feature"]["source_record_raw_payload_hash"]
            == scenario.provider_payload_hash
        )
        assert data["scores"]["scorer_id"] == _SCORER_ID
        assert case_id in {case.case_id for case in page}

        fingerprint = str(data["evidence_fingerprint"])
        manual_revision = int(data["manual_feature"]["row_revision"])
        provider_revision = int(data["provider_feature"]["row_revision"])
        provider_feature_uuid = str(data["provider_feature"]["feature_uuid"])

        await _ensure_paired_consumer(api, actor=scenario.actor)

        # 판정 축에서도 survivor는 text feature_id다 — UUID를 넘기면 성립하지 않는다.
        stale_command = await _open_command(
            api,
            actor=scenario.actor,
            operation="admin.manual-provider-dedup-case.resolve.v1",
            payload={"case_id": str(case_id), "survivor": provider_feature_uuid},
        )
        async with AsyncSession(api, expire_on_commit=False) as session, session.begin():
            await session.execute(text("SET TRANSACTION ISOLATION LEVEL READ COMMITTED"))
            stale = await m05_repo.resolve_manual_provider_dedup_case(
                session,
                case_id=case_id,
                decision="merged",
                expected_case_fingerprint=fingerprint,
                expected_manual_row_revision=manual_revision,
                expected_provider_row_revision=provider_revision,
                survivor_feature_id=provider_feature_uuid,
                reason="survivor를 UUID 축으로 넘기면 성립하지 않는다",
                actor=scenario.actor,
                command_id=stale_command,
            )
        assert stale.outcome == "stale"
        assert stale.resolution_id is None
        assert stale.event_id is None

        decision_command = await _open_command(
            api,
            actor=scenario.actor,
            operation="admin.manual-provider-dedup-case.resolve.v1",
            payload={"case_id": str(case_id), "survivor": scenario.provider_feature_id},
        )
        async with AsyncSession(api, expire_on_commit=False) as session, session.begin():
            await session.execute(text("SET TRANSACTION ISOLATION LEVEL READ COMMITTED"))
            resolved = await m05_repo.resolve_manual_provider_dedup_case(
                session,
                case_id=case_id,
                decision="merged",
                expected_case_fingerprint=fingerprint,
                expected_manual_row_revision=manual_revision,
                expected_provider_row_revision=provider_revision,
                survivor_feature_id=scenario.provider_feature_id,
                reason="같은 장소를 provider 정본으로 합친다",
                actor=scenario.actor,
                command_id=decision_command,
            )
        assert resolved.outcome == "merged"
        assert resolved.manual_feature_id == scenario.manual_feature_id
        assert resolved.manual_feature_row_revision == manual_revision + 1
        assert resolved.resolution_id is not None
        event_id = resolved.event_id
        assert event_id is not None

        async with migrated_engine.connect() as connection:
            event = (
                (await connection.execute(text(_EVENT_SQL), {"event_id": str(event_id)}))
                .mappings()
                .one()
            )
            manual_state = (
                (
                    await connection.execute(
                        text(_FEATURE_STATE_SQL),
                        {"feature_id": scenario.manual_feature_id},
                    )
                )
                .mappings()
                .one()
            )
        assert event["action"] == "rebind"
        assert manual_state["lifecycle_state"] == "retired"
        assert manual_state["publication_state"] == "suppressed"
        assert int(manual_state["row_revision"]) == manual_revision + 1
        event_sequence = int(event["event_sequence"])
        event_sha256 = str(event["event_sha256"])

        principal_id = f"service:m05-bundle-{suffix}"
        await _seed_isolated_consumer(
            migrated_engine, principal_id=principal_id, cursor=event_sequence - 1
        )

        worker_id = uuid4()
        async with AsyncSession(api, expire_on_commit=False) as session, session.begin():
            await session.execute(text("SET TRANSACTION ISOLATION LEVEL READ COMMITTED"))
            lease = await m05_repo.lease_feature_reference_reconciliation_event(
                session, principal_id=principal_id, worker_id=worker_id
            )
        assert lease.outcome == "leased"
        assert lease.event_id == event_id
        assert lease.event_sequence == event_sequence
        assert lease.event_sha256 == event_sha256
        assert lease.action == "rebind"
        assert lease.case_id == case_id
        assert lease.resolution_id == resolved.resolution_id
        lease_epoch = lease.lease_epoch
        assert lease_epoch is not None
        payload = lease.event_payload
        assert payload is not None
        assert payload["old_feature"]["feature_id"] == scenario.manual_feature_id
        assert (
            payload["replacement_feature"]["feature_id"] == scenario.provider_feature_id
        )
        assert payload["replacement_feature"]["feature_uuid"] == provider_feature_uuid

        local_receipt_sha256 = hashlib.sha256(
            f"pinvi-local-receipt::{event_id}".encode()
        ).hexdigest()
        async with AsyncSession(api, expire_on_commit=False) as session, session.begin():
            await session.execute(text("SET TRANSACTION ISOLATION LEVEL READ COMMITTED"))
            absent = await m05_repo.preflight_feature_reference_reconciliation_ack(
                session,
                principal_id=principal_id,
                event_id=event_id,
                event_sha256=event_sha256,
                local_receipt_sha256=local_receipt_sha256,
            )
        assert absent.outcome == "absent"

        ack_command = await _open_command(
            api,
            actor=principal_id,
            operation="service.feature-reference-reconciliation.ack.v1",
            payload={"event_id": str(event_id)},
        )
        async with AsyncSession(api, expire_on_commit=False) as session, session.begin():
            await session.execute(text("SET TRANSACTION ISOLATION LEVEL READ COMMITTED"))
            acked = await m05_repo.ack_feature_reference_reconciliation_event(
                session,
                principal_id=principal_id,
                event_id=event_id,
                worker_id=worker_id,
                lease_epoch=lease_epoch,
                event_sha256=event_sha256,
                local_receipt_sha256=local_receipt_sha256,
                command_id=ack_command,
            )
        assert acked.outcome == "acked"
        assert acked.acked_through_sequence == event_sequence

        async with AsyncSession(api, expire_on_commit=False) as session, session.begin():
            await session.execute(text("SET TRANSACTION ISOLATION LEVEL READ COMMITTED"))
            drained = await m05_repo.lease_feature_reference_reconciliation_event(
                session, principal_id=principal_id, worker_id=worker_id
            )
            replayed_ack = await m05_repo.preflight_feature_reference_reconciliation_ack(
                session,
                principal_id=principal_id,
                event_id=event_id,
                event_sha256=event_sha256,
                local_receipt_sha256=local_receipt_sha256,
            )
        assert drained.outcome == "empty"
        assert replayed_ack.outcome == "replayed"
        assert replayed_ack.acked_through_sequence == event_sequence

        async with AsyncSession(api, expire_on_commit=False) as session:
            terminal = await m05_repo.get_manual_provider_dedup_case(
                session, case_id=case_id
            )
        assert terminal is not None
        assert terminal.data["status"] == "terminal"
        assert terminal.data["resolution"]["decision"] == "merged"
    finally:
        await api.dispose()
        await dagster.dispose()


async def test_dedup_candidate_rejects_uuid_identity_and_accepts_text_feature_id(
    migrated_engine: AsyncEngine,
) -> None:
    """승인 응답의 UUID를 detector에 넣으면 eligibility 위반으로 **위장**된다(e2e15)."""

    suffix = uuid4().hex
    api = _runtime_engine(migrated_engine, login="ktm_feature_api_runtime")
    dagster = _runtime_engine(migrated_engine, login="ktm_feature_dagster_runtime")
    try:
        scenario = await _seed_scenario(migrated_engine, api, suffix=suffix)

        # 승인 queue projection의 `feature_id`는 uuid 컬럼(resolved_feature_id)이다.
        assert scenario.approval_projection_feature_id == scenario.manual_feature_uuid
        assert scenario.approval_projection_feature_id != scenario.manual_feature_id
        assert (
            str(UUID(scenario.approval_projection_feature_id))
            == scenario.approval_projection_feature_id
        )
        assert scenario.manual_feature_id.startswith("f_")

        scores = _scores(
            manual_feature_id=scenario.manual_feature_id,
            provider_feature_id=scenario.provider_feature_id,
        )
        with pytest.raises(DBAPIError) as manual_axis:
            await _record_candidate(
                dagster,
                manual_feature_id=scenario.approval_projection_feature_id,
                provider_feature_id=scenario.provider_feature_id,
                scores=scores,
            )
        assert _sqlstate(manual_axis.value) == "23514"
        assert _constraint_name(manual_axis.value) == "ck_m05_candidate_feature_proof"

        created = await _record_candidate(
            dagster,
            manual_feature_id=scenario.manual_feature_id,
            provider_feature_id=scenario.provider_feature_id,
            scores=scores,
        )
        assert created["o_outcome"] == "created"
        case_id = UUID(str(created["o_case_id"]))

        async with AsyncSession(api, expire_on_commit=False) as session:
            detail = await m05_repo.get_manual_provider_dedup_case(
                session, case_id=case_id
            )
        assert detail is not None
        provider_feature_uuid = str(detail.data["provider_feature"]["feature_uuid"])
        assert provider_feature_uuid != scenario.provider_feature_id

        with pytest.raises(DBAPIError) as provider_axis:
            await _record_candidate(
                dagster,
                manual_feature_id=scenario.manual_feature_id,
                provider_feature_id=provider_feature_uuid,
                scores=scores,
            )
        assert _sqlstate(provider_axis.value) == "23514"
        assert _constraint_name(provider_axis.value) == "ck_m05_candidate_feature_proof"
    finally:
        await api.dispose()
        await dagster.dispose()


async def test_dedup_case_payload_hash_domain_matches_source_records_in_catalog(
    migrated_engine: AsyncEngine,
) -> None:
    """사본 CHECK가 원본 도메인을 승계했는지 **live catalog**에서 확인한다(``303``).

    ``tests/lint/test_copied_hash_domain_parity``는 ORM 선언 텍스트를 본다. 이
    단언은 실제로 배포된 제약을 본다 — 둘이 갈라지면(예: migration만 되돌리면)
    여기서 잡힌다.
    """

    async with migrated_engine.connect() as connection:
        case_check = await connection.scalar(
            text(_CONSTRAINT_DEF_SQL),
            {
                "relation": "ops.manual_provider_dedup_cases",
                "constraint_name": "ck_manual_provider_dedup_cases_hashes",
            },
        )
        source_check = await connection.scalar(
            text(_CONSTRAINT_DEF_SQL),
            {
                "relation": "provider_sync.source_records",
                "constraint_name": "ck_source_records_payload_hash_canonical",
            },
        )
    assert isinstance(case_check, str)
    assert isinstance(source_check, str)
    assert "raw_payload_hash" in source_check
    assert "'^[0-9a-f]{1,64}$'" in source_check
    assert "source_record_raw_payload_hash ~ '^[0-9a-f]{1,64}$'" in case_check
    assert "source_record_raw_payload_hash ~ '^[0-9a-f]{64}$'" not in case_check
    # 이 계약이 스스로 full SHA-256을 정의하는 두 필드는 64-hex를 유지한다.
    assert "evidence_fingerprint ~ '^[0-9a-f]{64}$'" in case_check
    assert "scorer_input_sha256 ~ '^[0-9a-f]{64}$'" in case_check
