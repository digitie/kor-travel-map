"""``infra/feature_identity`` 경계 + alias 등록부 (T-VN-32B/32C·T-VN-39, ADR-068/098).

alembic head(309 재키)가 적용된 실 PostGIS에서:

① 경계 alias 해석 — legacy ``f_*`` alias·canonical UUID 양쪽 참조가 같은
   정본 키 쌍으로 해석되고, 미존재는 ``None``, 형식 오류는 fail-fast.
② dual read — raw/공개 단건·bbox 목록·service batch·notice lineage read가
   ``feature_uuid``를 병행(additive)으로 노출한다. 309 뒤 ``features.feature_id``가
   곧 uuid이고 ``feature_uuid``는 같은 값의 text 표기다.
③ 신규 write 원자성 — provider 생성 경로가 **한 transaction에서** 정본 키(uuid)와
   legacy alias를 함께 남긴다. 이 파일이 그 원자성을 관측하는 유일한 자리이고,
   alias INSERT가 core CALL **앞**에 있어 신규 provider Feature마다 23503이 나던
   결함(309 사이드카에서 수정)이 CI에서 걸리는 지점이다.
④ **alias는 "모든 Feature의 두 번째 이름"이 아니라 바깥에서 이 Feature를 가리킨
   적이 있는 주소의 등록부다** (ADR-098 결정 6). 재키 뒤 주소를 발급하는 주체는
   backfill과 ``create_provider_feature_with_initial_state`` 둘뿐이므로,
   **admin 수동·요청 승인·큐레이션·core 경로가 만든 Feature는 alias 0행이고 그것이
   정상 상태다** — 결손이 아니다. 그래서 ``count_features_missing_identity``의 둘째
   축은 features 전수가 아니라 **provider claim 기준**이다.

   근거는 정보량이다. provider ``f_*``는 ``sha1(bjd|kind|category|source_type|
   natural_key)``라 provider 레코드를 가진 제3자가 Map을 본 적 없어도 계산할 수 있고
   재분류로 값이 바뀌어도 옛 주소가 alias로 남아 구 URL이 산다. manual ``f_*``는
   ``sha1(…|manual::{서버가 방금 발급한 UUIDv7})``이라 정본 키의 순수 함수이고,
   밖에서 계산할 수 없으며 드리프트하지 않으므로 발급할 이득이 원리적으로 없다.
"""

from __future__ import annotations

import json
import uuid as uuid_module
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from kortravelmap.core.ids import (
    feature_uuid_from_legacy,
    make_payload_hash,
    make_source_record_key,
)
from kortravelmap.dto import (
    Address,
    Coordinate,
    Feature,
    FeatureBundle,
    FeatureKind,
    NoticeDetail,
    PlaceDetail,
    SourceLink,
    SourceRecord,
    SourceRole,
)
from kortravelmap.infra import (
    admin_feature_repo,
    curation_repo,
    feature_identity,
    feature_repo,
    feature_request_repo,
)
from kortravelmap.infra.domain_command_repo import (
    canonical_domain_command_fingerprint,
    create_domain_command_claim,
)
from tests.integration.conftest import as_api_runtime

pytestmark = pytest.mark.integration

_KST = timezone(timedelta(hours=9))
_FETCHED = datetime(2026, 8, 4, 12, 0, tzinfo=_KST)

_PROVIDER = "data.go.kr-standard"
_DATASET = "datagokr_cultural_festivals"
_ENTITY_TYPE = "festival"

#: 어떤 Feature도 갖지 않는 canonical uuid. 309 뒤 read 표면의 조회 키는 전부
#: ``uuid``/``uuid[]``로 캐스팅되므로 "없는 참조" probe도 legacy 문자열이 아니라
#: uuid여야 한다 — 문자열을 넣으면 관측이 아니라 22P02가 된다.
_ABSENT_UUID = "00000000-0000-7000-8000-00000000dead"


def _place_bundle(
    feature_id: str,
    *,
    name: str = "identity 검증 장소",
    natural_key: str | None = None,
) -> FeatureBundle:
    """provider 경로 seed 하나.

    ``provider_natural_key``는 T-VN-39/ADR-098 identity claim 축
    ``(provider_dataset_id, feature_kind, natural_key)``의 세 번째 성분이고, 이
    값이 없으면 writer가 :class:`FeatureIdentityAnchorError`로 **선다**(fail-close).
    그래서 provider seed는 재키 뒤 이 값을 반드시 실어야 한다.

    기본 자연키는 legacy id 자신이다. 따로 주는 경우는 하나뿐 — "재분류로 같은
    ``f_*``가 다른 Feature를 가리키게 된" 상황을 만들 때다(claim 축이 달라야 새
    Feature가 주조된다).
    """
    key = natural_key or feature_id
    raw_data = {"natural_key": key, "name": name}
    raw_payload_hash = make_payload_hash(raw_data)
    source_record_key = make_source_record_key(
        provider=_PROVIDER,
        dataset_key=_DATASET,
        source_entity_type=_ENTITY_TYPE,
        source_entity_id=key,
        raw_payload_hash=raw_payload_hash,
    )
    feature = Feature(
        feature_id=feature_id,
        provider_natural_key=key,
        kind=FeatureKind.PLACE,
        name=name,
        address=Address(),
        category="01070100",
        coord=Coordinate(lon=126.9239, lat=37.5263),
        marker_icon="star",
        marker_color="P-03",
        # T-VN-35(ADR-086): place subtype의 ``place_kind``는 NOT NULL이고 writer도
        # 결측을 거부한다(sentinel 폐기) — detail 없는 place는 더 이상 유효하지 않다.
        detail=PlaceDetail(feature_id=feature_id, place_kind="attraction"),
        created_at=_FETCHED,
        updated_at=_FETCHED,
    )
    source_record = SourceRecord(
        provider=_PROVIDER,
        dataset_key=_DATASET,
        source_entity_type=_ENTITY_TYPE,
        source_entity_id=key,
        raw_payload_hash=raw_payload_hash,
        raw_data=raw_data,
        fetched_at=_FETCHED,
        imported_at=_FETCHED,
        source_record_key=source_record_key,
    )
    source_link = SourceLink(
        feature_id=feature_id,
        source_record_key=source_record_key,
        source_role=SourceRole.PRIMARY,
        match_method="natural_key",
        confidence=100,
        created_at=_FETCHED,
    )
    return FeatureBundle(
        feature=feature,
        source_record=source_record,
        source_link=source_link,
    )


async def _canonical_uuid_for_alias(session: AsyncSession, feature_id: str) -> str:
    """legacy ``f_*``가 가리키는 정본 키(uuid의 text 표기).

    309 재키가 사본 컬럼 ``features.feature_uuid``를 영구히 없앴다 — 정본 키는
    ``features.feature_id``(uuid) 하나이고, legacy 문자열에서 그 값으로 가는 유일한
    입구가 ``feature_aliases``다. 즉 이 helper 자체가 "alias는 주소 등록부"라는
    ADR-098 결정 6의 실물이다. **provider 경로로 심은 Feature에만 쓸 수 있다** —
    manual 계열은 주소를 발급하지 않으므로 여기서 조회할 것이 없는 것이 정상이다.
    """
    return str(
        (
            await session.execute(
                text(
                    "SELECT CAST(a.feature_id AS text) "
                    "FROM feature.feature_aliases AS a "
                    "WHERE a.alias = :alias AND a.alias_kind = 'legacy_feature_id'"
                ),
                {"alias": feature_id},
            )
        ).scalar_one()
    )


def _sqlstate(error: BaseException) -> str | None:
    """DBAPIError에서 PostgreSQL SQLSTATE를 꺼낸다 (driver 표기 차이 흡수)."""
    for candidate in (getattr(error, "orig", None), error):
        for attribute in ("sqlstate", "pgcode"):
            value = getattr(candidate, attribute, None)
            if value:
                return str(value)
    return None


def _assert_nonderived_uuid_v7(value: str, *, feature_id: str) -> str:
    """0083 신규 행 정본 형태 — canonical UUIDv7이고 legacy 파생값이 아니다."""
    parsed = uuid_module.UUID(value)
    assert str(parsed) == value
    assert parsed.version == 7
    assert parsed.variant == uuid_module.RFC_4122
    assert value != str(feature_uuid_from_legacy(feature_id))
    return value


async def _open_command(session: AsyncSession, *, actor: str, operation: str) -> int:
    """manual writer가 요구하는 open domain command receipt 하나."""
    claim = await create_domain_command_claim(
        session,
        actor=actor,
        operation=operation,
        idempotency_key=str(uuid_module.uuid4()),
        request_fingerprint=canonical_domain_command_fingerprint(
            {"actor": actor, "operation": operation}
        ),
    )
    return claim.command_id


async def _assert_manual_feature_carries_no_alias(
    session: AsyncSession, *, feature_uuid: str
) -> None:
    """manual 계열 Feature의 정상 상태 — 등록부에 주소가 **없고**, 그것이 위반이 아니다.

    두 단언이 한 쌍이어야 뜻이 산다. alias 0행만 보면 "아직 안 넣었다"와 구분되지
    않으므로, 같은 자리에서 4축 관측이 전부 0인지도 본다 — 둘째 축이 provider claim
    기준으로 다시 그어졌기 때문에 alias 없는 manual Feature는 애초에 세지 않는다.
    """
    alias_count = (
        await session.execute(
            text(
                "SELECT count(*) FROM feature.feature_aliases "
                "WHERE feature_id = CAST(:feature_uuid AS uuid)"
            ),
            {"feature_uuid": feature_uuid},
        )
    ).scalar_one()
    assert alias_count == 0
    assert await feature_identity.count_features_missing_identity(session) == (0, 0, 0, 0)


# ── ① 경계 alias 해석 ───────────────────────────────────────────────────────


async def test_resolve_feature_identity_accepts_legacy_and_uuid_refs(
    migrated_session: AsyncSession,
) -> None:
    feature_id = "f_1100000000_p_idboundary0001"
    await feature_repo.load_bundle(migrated_session, _place_bundle(feature_id))
    expected_uuid = _assert_nonderived_uuid_v7(
        await _canonical_uuid_for_alias(migrated_session, feature_id),
        feature_id=feature_id,
    )

    by_legacy = await feature_identity.resolve_feature_identity(
        migrated_session, feature_id
    )
    assert by_legacy is not None
    # 309 뒤 두 슬롯은 같은 정본 키의 uuid/text 표기다 — legacy 문자열은 해석
    # **입력**이지 결과가 아니다(``FeatureIdentity``의 필드 이름만 바깥 계약).
    assert by_legacy.feature_id == expected_uuid
    assert by_legacy.feature_uuid == expected_uuid

    # canonical UUID 참조(대문자 포함)도 같은 정본 키 쌍으로 해석된다.
    by_uuid = await feature_identity.resolve_feature_identity(
        migrated_session, expected_uuid
    )
    assert by_uuid == by_legacy
    by_uuid_upper = await feature_identity.resolve_feature_identity(
        migrated_session, expected_uuid.upper()
    )
    assert by_uuid_upper == by_legacy


async def test_resolve_feature_identity_returns_none_for_unknown_refs(
    migrated_session: AsyncSession,
) -> None:
    assert (
        await feature_identity.resolve_feature_identity(
            migrated_session, "f_global_p_nonexistent00000"
        )
        is None
    )
    assert (
        await feature_identity.resolve_feature_identity(
            migrated_session, "00000000-0000-5000-8000-00000000dead"
        )
        is None
    )


async def test_resolve_feature_identity_fail_fast_on_malformed_ref(
    migrated_session: AsyncSession,
) -> None:
    with pytest.raises(feature_identity.FeatureIdentityRefError):
        await feature_identity.resolve_feature_identity(migrated_session, " f_1")


# ── ② dual read — feature_uuid 병행 노출 ────────────────────────────────────


async def test_reads_expose_feature_uuid_additively(
    migrated_session: AsyncSession,
) -> None:
    feature_id = "f_1100000000_p_idboundary0002"
    await feature_repo.load_bundle(migrated_session, _place_bundle(feature_id))
    expected_uuid = _assert_nonderived_uuid_v7(
        await _canonical_uuid_for_alias(migrated_session, feature_id),
        feature_id=feature_id,
    )

    # 309 ``_VIEW_RECREATE`` — 공개 view는 26열 계약(INV-34C-04)을 유지하며
    # ``feature_uuid`` 슬롯을 ``CAST(feature_id AS text)``로 계속 노출한다.
    view_uuid = (
        await migrated_session.execute(
            text(
                "SELECT CAST(feature_uuid AS text) FROM feature.public_features "
                "WHERE feature_id = CAST(:feature_uuid AS uuid)"
            ),
            {"feature_uuid": expected_uuid},
        )
    ).scalar_one()
    assert view_uuid == expected_uuid

    raw_row = await feature_repo.get_feature_row(migrated_session, expected_uuid)
    assert raw_row is not None
    assert raw_row["feature_uuid"] == expected_uuid

    public_row = await feature_repo.get_public_feature_row(
        migrated_session, expected_uuid
    )
    assert public_row is not None
    assert public_row["feature_uuid"] == expected_uuid

    bbox_rows = await feature_repo.features_in_bbox(
        migrated_session,
        min_lon=126.9,
        min_lat=37.5,
        max_lon=127.0,
        max_lat=37.6,
    )
    bbox_by_id = {str(row["feature_id"]): row for row in bbox_rows}
    assert bbox_by_id[expected_uuid]["feature_uuid"] == expected_uuid

    batch = await feature_repo.get_service_feature_batch_items(
        migrated_session,
        ((expected_uuid, None), (_ABSENT_UUID, None)),
    )
    assert batch[0].state == "found"
    assert batch[0].feature_uuid == expected_uuid
    assert batch[1].state == "missing"
    assert batch[1].feature_uuid is None

    uuid_map = await feature_identity.get_feature_uuid_map(
        migrated_session, [expected_uuid, _ABSENT_UUID]
    )
    assert uuid_map == {expected_uuid: expected_uuid}


async def test_notice_lineage_read_exposes_uuid_pairs(
    migrated_session: AsyncSession,
) -> None:
    feature_id = "f_global_n_idboundary00003"
    bundle = _place_bundle(feature_id, name="identity 검증 공지")
    notice_feature = bundle.feature.model_copy(
        update={
            "kind": FeatureKind.NOTICE,
            "detail": NoticeDetail(feature_id=feature_id, notice_type="safety"),
            "coord": None,
            "coord_precision_digits": None,
        }
    )
    await feature_repo.load_bundle(
        migrated_session,
        FeatureBundle(
            feature=notice_feature,
            source_record=bundle.source_record,
            source_link=bundle.source_link,
        ),
    )
    expected_uuid = _assert_nonderived_uuid_v7(
        await _canonical_uuid_for_alias(migrated_session, feature_id),
        feature_id=feature_id,
    )

    identities = await feature_repo.public_active_notice_feature_identities(
        migrated_session, [expected_uuid, _ABSENT_UUID]
    )
    assert identities == {expected_uuid: expected_uuid}


# ── ③ provider 생성 경로의 정본 키 + alias 원자성 ───────────────────────────


async def test_provider_create_writes_uuid_and_alias_atomically(
    migrated_session: AsyncSession,
) -> None:
    """provider 생성 한 번이 정본 키와 legacy 주소를 **같은 transaction에** 남긴다.

    309가 ``trg_features_legacy_alias``를 영구 제거해 alias 삽입이 DB 트리거가
    아니라 ``create_provider_feature_with_initial_state``의 책임이 됐다. 그 프로시저
    안에서 alias INSERT는 core CALL **뒤에만** 설 수 있다 —
    ``fk_feature_aliases_feature``가 DEFERRABLE 없이 재생성되어 문장 끝에서 즉시
    검사되고, 신규 claim의 uuid는 core가 넣기 전까지 ``feature.features``에 없기
    때문이다. 앞에 두면 신규 provider Feature마다 23503이다. 이 테스트가 그 순서를
    CI에서 붙잡는 자리다.
    """
    feature_id = "f_1100000000_p_idboundary0004"
    await feature_repo.load_bundle(migrated_session, _place_bundle(feature_id))
    expected_uuid = _assert_nonderived_uuid_v7(
        await _canonical_uuid_for_alias(migrated_session, feature_id),
        feature_id=feature_id,
    )

    pair = (
        await migrated_session.execute(
            text(
                "SELECT CAST(f.feature_id AS text) AS feature_uuid, "
                "       a.alias, a.alias_kind "
                "FROM feature.features AS f "
                "JOIN feature.feature_aliases AS a ON a.feature_id = f.feature_id "
                "WHERE f.feature_id = CAST(:feature_uuid AS uuid)"
            ),
            {"feature_uuid": expected_uuid},
        )
    ).one()
    assert pair.feature_uuid == expected_uuid
    assert pair.alias == feature_id
    assert pair.alias_kind == "legacy_feature_id"

    # 재적재는 같은 claim으로 수렴한다 — 새 UUIDv7 후보를 만들어도 claim이 이미
    # 있으면 그 값이 정본으로 남고, alias는 ``ON CONFLICT (alias) DO NOTHING``이
    # 삼킨 뒤 소유자가 같음을 확인하고 통과한다(다르면 23505 — 아래 별도 테스트).
    await feature_repo.load_bundle(migrated_session, _place_bundle(feature_id))
    assert await _canonical_uuid_for_alias(migrated_session, feature_id) == expected_uuid

    assert await feature_identity.count_features_missing_identity(migrated_session) == (
        0,
        0,
        0,
        0,
    )


async def test_admin_manual_create_db_objects_exist_at_m01_head(
    migrated_session: AsyncSession,
) -> None:
    procedure_count = (
        await migrated_session.execute(
            text(
                """
                SELECT count(*)
                FROM pg_catalog.pg_proc AS procedure
                JOIN pg_catalog.pg_namespace AS namespace
                  ON namespace.oid = procedure.pronamespace
                WHERE namespace.nspname = 'feature'
                  AND procedure.proname =
                      'create_admin_manual_feature_with_initial_state'
                """
            )
        )
    ).scalar_one()
    relations = (
        await migrated_session.execute(
            text(
                """
                SELECT
                    to_regclass('feature.manual_feature_identity_claims') AS claims,
                    to_regclass('feature.feature_creation_origins') AS origins
                """
            )
        )
    ).one()

    assert procedure_count == 1
    assert relations.claims is not None
    assert relations.origins is not None


# ── ④ alias = 주소 등록부 (ADR-098 결정 6) ──────────────────────────────────


async def test_provider_alias_loss_is_observed_by_the_claim_axis(
    migrated_session: AsyncSession,
) -> None:
    """**provider claim이 있는데 주소가 없는 것**만 결측이다 (새 INV-068-01).

    종전 관측은 "features 전수 중 alias 없는 행"이었고, 그 보편 명제는 사라진 트리거
    ``trg_features_legacy_alias``와 consumer-rollout 문안의 산물이었다. 재키 뒤
    둘째 축은 ``provider_sync.provider_feature_identities`` claim 중 legacy alias가
    등록부에 없는 것만 센다 — 그리고 그 축의 DB 보장은 없다(writer 보장이다). 그래서
    이 테스트는 **관측이 실제로 작동하는지**를 provider 경로에서 확인한다.

    alias 직접 DELETE는 0081 fence가 거부하므로(그 거부 자체를 먼저 단언한다) 결측
    상태는 fence 일시 해제로 만든다 — transaction rollback으로 원복된다.
    """
    feature_id = "f_1100000000_p_idboundary0006"
    await feature_repo.load_bundle(migrated_session, _place_bundle(feature_id))

    # 등록부 행은 불변이다 — 지우려면 fence를 내려야 한다는 사실 자체가 계약이다.
    with pytest.raises(DBAPIError) as fence_error:
        async with migrated_session.begin_nested():
            await migrated_session.execute(
                text("DELETE FROM feature.feature_aliases WHERE alias = :alias"),
                {"alias": feature_id},
            )
    assert "legacy write fence" in str(fence_error.value)

    await migrated_session.execute(
        text(
            "ALTER TABLE feature.feature_aliases "
            "DISABLE TRIGGER trg_feature_aliases_delete_fence"
        )
    )
    await migrated_session.execute(
        text("DELETE FROM feature.feature_aliases WHERE alias = :alias"),
        {"alias": feature_id},
    )
    await migrated_session.execute(
        text(
            "ALTER TABLE feature.feature_aliases "
            "ENABLE TRIGGER trg_feature_aliases_delete_fence"
        )
    )

    (
        missing_uuid,
        missing_alias,
        pair_mismatch,
        orphan_alias,
    ) = await feature_identity.count_features_missing_identity(migrated_session)
    assert missing_uuid == 0
    # claim은 남아 있고 그 주소가 사라졌다 — 이것이 유일하게 남은 "결측"의 뜻이다.
    assert missing_alias >= 1
    assert pair_mismatch == 0
    assert orphan_alias == 0


async def test_admin_manual_create_issues_no_alias(
    migrated_session: AsyncSession,
) -> None:
    """(a) admin 수동 생성 — alias 0행이 정상이다.

    manual ``f_*``는 ``sha1(…|manual::{서버가 방금 발급한 UUIDv7})``이라 정본 키의
    순수 함수다. 밖에서 계산할 수 없고, 계산할 수 있는 사람은 이미 정본 키를 쥐고
    있으며, uuid는 드리프트하지 않으므로 "재분류마다 alias가 는다"는 이득이
    원리적으로 발생하지 않는다. 그래서 이 경로는 주소를 발급하지 않는다.
    """
    suffix = uuid_module.uuid4().hex[:12]
    actor = f"admin:idboundary-manual-{suffix}"
    command_id = await _open_command(
        migrated_session, actor=actor, operation="admin.feature.create.manual-v1"
    )
    # wrapper는 ``session_user = ktm_feature_api_runtime``만 통과시킨다(42501) —
    # superuser seed transaction 안에서 그 write만 실제 runtime으로 실행한다.
    async with as_api_runtime(migrated_session):
        created = await admin_feature_repo.create_admin_feature_with_field_overrides(
            migrated_session,
            payload={
                "kind": "place",
                "name": f"identity 경계 수동 장소 {suffix}",
                "category": "01070300",
                "coord": {"lon": 127.101234, "lat": 37.501234},
                "marker_icon": "marker",
                "marker_color": "P-02",
                "detail": {"place_kind": "attraction"},
            },
            reason_code="manual_create",
            operator=actor,
            command_id=command_id,
        )
    assert isinstance(created, admin_feature_repo.AdminManualFeatureCreated)
    await _assert_manual_feature_carries_no_alias(
        migrated_session, feature_uuid=created.feature_uuid
    )


async def test_feature_request_approval_issues_no_alias(
    migrated_session: AsyncSession,
) -> None:
    """(b) 요청 승인 — alias 0행이 정상이다."""
    suffix = uuid_module.uuid4().hex[:12]
    actor = f"admin:idboundary-request-{suffix}"
    request_id = uuid_module.uuid4()
    request_payload = {
        "kind": "place",
        "name": f"identity 경계 요청 장소 {suffix}",
        "lon": 127.201234,
        "lat": 37.601234,
        "categories": ["identity-boundary"],
    }
    submit_command = await _open_command(
        migrated_session,
        actor="service:feature-request",
        operation="service.feature-request.submit.v1",
    )
    approve_command = await _open_command(
        migrated_session, actor=actor, operation="admin.feature-request.approve.v1"
    )
    async with as_api_runtime(migrated_session):
        status, _submitted_at = await feature_request_repo.submit_feature_request(
            migrated_session,
            request_id=request_id,
            request_payload=request_payload,
            command_id=submit_command,
        )
        assert status == "pending"
        pending = await feature_request_repo.get_feature_request(
            migrated_session, request_id=request_id
        )
        assert pending is not None
        created = await feature_request_repo.approve_feature_request(
            migrated_session,
            request=pending,
            category="01070300",
            marker_color="P-03",
            marker_icon="marker",
            command_id=approve_command,
        )
    assert isinstance(created, feature_request_repo.FeatureRequestCreated)
    await _assert_manual_feature_carries_no_alias(
        migrated_session, feature_uuid=created.feature_uuid
    )


async def test_manual_curation_create_issues_no_alias(
    migrated_engine: AsyncEngine,
) -> None:
    """(c) 큐레이션 경로 — alias 0행이 정상이다.

    이 경로만 ``migrated_session``을 쓰지 못한다. curation writer 셋이 모두
    SERIALIZABLE을 요구하는데(READ COMMITTED면 25001) 공용 fixture의 transaction은
    이미 READ COMMITTED로 열려 있어 도중에 격리 수준을 바꿀 수 없다. 그래서 같은
    engine 위에 격리 수준을 지정한 transaction을 따로 열고, 끝에서 rollback해 공용
    fixture와 같은 테스트 간 격리를 유지한다.

    ``curation_repo``가 legacy ``f_*``를 **계산은 한다**(``feature_id`` 필드로 돌려
    준다). 그러나 그 값을 등록부에 싣지 않는다 — 그것이 결정 6의 요지이므로 계산된
    값이 실제로 조회되지 않는 것까지 함께 단언한다.
    """
    suffix = uuid_module.uuid4().hex[:12]
    actor = f"admin:idboundary-curation-{suffix}"
    session = AsyncSession(migrated_engine, expire_on_commit=False)
    try:
        await session.begin()
        await session.execute(text("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE"))

        theme_command = await _open_command(
            session, actor=actor, operation="admin.curated-theme.create"
        )
        async with as_api_runtime(session):
            theme_id = str(
                (
                    await session.execute(
                        text(
                            """
                            CALL feature.create_curated_theme_command(
                              :theme_slug, 'identity 경계 theme', '', 'test',
                              'admin_only', '{}'::jsonb, :command_id, :principal,
                              NULL, NULL
                            )
                            """
                        ),
                        {
                            "command_id": theme_command,
                            "principal": actor,
                            "theme_slug": f"idboundary-{suffix}",
                        },
                    )
                )
                .mappings()
                .one()["o_theme_id"]
            )

        collection_command = await _open_command(
            session, actor=actor, operation="admin.curation-collection.create"
        )
        async with as_api_runtime(session):
            collection = await curation_repo.create_curation_collection_command(
                session,
                collection_key=f"idboundary-{suffix}",
                theme_id=theme_id,
                source_id=None,
                title="identity 경계 collection",
                command_id=collection_command,
                principal=actor,
            )

        item_command = await _open_command(
            session,
            actor=actor,
            operation="admin.curation-item.create.manual-feature-v1",
        )
        async with as_api_runtime(session):
            created = await curation_repo.create_manual_curation_item_with_feature_command(
                session,
                collection_id=collection.collection_id,
                manual_feature={
                    "kind": "place",
                    "name": f"identity 경계 큐레이션 장소 {suffix}",
                    "category": "01070300",
                    "coord": {"lon": 127.301234, "lat": 37.701234},
                    "marker_icon": "marker",
                    "marker_color": "P-02",
                    "detail": {"place_kind": "attraction"},
                },
                external_item_id=f"idboundary-{suffix}",
                command_id=item_command,
                principal=actor,
            )
        assert isinstance(created, curation_repo.CurationManualFeatureItem)
        await _assert_manual_feature_carries_no_alias(
            session, feature_uuid=created.feature_uuid
        )
        # 계산된 legacy 문자열은 어디로도 등록되지 않았다 — 해석 입구가 비어 있다.
        assert (
            await feature_identity.resolve_feature_identity(session, created.feature_id)
            is None
        )
    finally:
        await session.rollback()
        await session.close()


async def test_provider_create_rejects_alias_bound_to_another_feature(
    migrated_session: AsyncSession,
) -> None:
    """(d) 같은 ``f_*``가 다른 Feature에 이미 묶여 있으면 provider 생성이 선다.

    재키 전에는 ``ck_feature_aliases_legacy_identity``(alias = feature_id)가 이 상황을
    원리적으로 막았다. uuid = text가 되어 그 CHECK를 되살릴 수 없으므로 프로시저가
    ``ON CONFLICT (alias) DO NOTHING``이 삼킨 경우의 소유자를 직접 확인하고, 주인이
    다르면 ``ck_provider_feature_alias_bound_elsewhere``(23505)로 멈춘다. 그 조용한
    통로가 다시 열리면 identity 손상이 무증상으로 쌓인다.

    두 번째 생성은 loader가 아니라 프로시저를 직접 호출한다 — 관측 대상이 wrapper의
    alias 분기 하나이고, claim 축(자연키)만 다르게 주면 그 분기에 정확히 닿는다.
    """
    feature_id = "f_1100000000_p_idboundary0008"
    await feature_repo.load_bundle(migrated_session, _place_bundle(feature_id))
    bound_uuid = await _canonical_uuid_for_alias(migrated_session, feature_id)
    dataset_id = (
        await migrated_session.execute(
            text(
                "SELECT provider_dataset_id FROM provider_sync.provider_datasets "
                "WHERE provider = :provider AND dataset_key = :dataset_key"
            ),
            {"dataset_key": _DATASET, "provider": _PROVIDER},
        )
    ).scalar_one()

    with pytest.raises(DBAPIError) as bound_elsewhere:
        async with migrated_session.begin_nested():
            await migrated_session.execute(
                text(
                    "CALL feature.create_provider_feature_with_initial_state("
                    " CAST(:feature_payload AS jsonb), CAST(:identity AS jsonb),"
                    " 'active', 'published', 'valid', CAST(:context AS jsonb),"
                    " NULL, NULL, NULL)"
                ),
                {
                    "context": json.dumps(
                        {
                            "transition_kind": "initial",
                            "reason_code": "identity_boundary_probe",
                            "principal": "test:identity-boundary",
                        }
                    ),
                    "feature_payload": json.dumps(
                        {
                            # wrapper가 claim한 uuid로 덮어쓰므로 여기 값은 자리표시다.
                            "feature_id": bound_uuid,
                            "kind": "place",
                            "name": "재분류가 주조한 다른 Feature",
                            "category": "01070100",
                            "lon": 126.9239,
                            "lat": 37.5263,
                            "coord_precision_digits": 6,
                            "marker_icon": "star",
                            "marker_color": "P-03",
                        },
                        ensure_ascii=False,
                    ),
                    "identity": json.dumps(
                        {
                            "provider_dataset_id": str(dataset_id),
                            "feature_kind": "place",
                            "natural_key": f"{feature_id}-reclassified",
                            "legacy_alias": feature_id,
                        }
                    ),
                },
            )
    assert "ck_provider_feature_alias_bound_elsewhere" in str(bound_elsewhere.value)
    assert _sqlstate(bound_elsewhere.value) == "23505"
    # 거부는 원자적이다 — 등록부의 주인은 그대로다.
    assert await _canonical_uuid_for_alias(migrated_session, feature_id) == bound_uuid


async def test_legacy_alias_shape_admits_provider_ids_and_rejects_uuid_strings(
    migrated_session: AsyncSession,
) -> None:
    """(e) ``ck_feature_aliases_legacy_alias_shape`` — 등록부는 ``f_*``만 담는다.

    309가 값 관계 CHECK(alias = feature_id) 자리를 **형태**로 받았다. 목적은 하나다 —
    정본 키를 alias로 되풀이하지 않는다. uuid 표기는 이 형태에 걸리지 않으므로 그
    금지가 DB 층에서 강제된다.

    반대 방향도 함께 고정한다. bjd 자리를 ``.+``로 둔 것은 의도다 —
    ``make_feature_id``가 ``bjd_code``를 검증하지 않아 밑줄 섞인 값이 원리적으로
    가능하고, ``[^_]+``로 조이면 그런 provider가 전량 23514로 멎는다. 형태 검사가
    적재를 막는 것은 이 CHECK의 목적이 아니다.
    """
    feature_id = "f_1100000000_p_idboundary0009"
    await feature_repo.load_bundle(migrated_session, _place_bundle(feature_id))
    bound_uuid = await _canonical_uuid_for_alias(migrated_session, feature_id)

    # 재분류가 만든 두 번째 주소는 같은 Feature에 한 행 더 실린다 — 등록부니까.
    # bjd 자리에 밑줄이 있어도 통과해야 한다.
    await migrated_session.execute(
        text(
            "INSERT INTO feature.feature_aliases (alias, feature_id, alias_kind) "
            "VALUES (:alias, CAST(:feature_uuid AS uuid), 'legacy_feature_id')"
        ),
        {"alias": "f_11_000_00000_p_00112233445566ff", "feature_uuid": bound_uuid},
    )

    with pytest.raises(DBAPIError) as shape_error:
        async with migrated_session.begin_nested():
            await migrated_session.execute(
                text(
                    "INSERT INTO feature.feature_aliases "
                    "(alias, feature_id, alias_kind) "
                    "VALUES (:alias, CAST(:feature_uuid AS uuid), 'legacy_feature_id')"
                ),
                {"alias": bound_uuid, "feature_uuid": bound_uuid},
            )
    assert "ck_feature_aliases_legacy_alias_shape" in str(shape_error.value)
    assert _sqlstate(shape_error.value) == "23514"
    # 파생 CHECK와 값 관계 CHECK는 309에서 사라졌다 — 이름이 다시 등장하면 회귀다.
    assert "ck_feature_aliases_legacy_identity" not in str(shape_error.value)
