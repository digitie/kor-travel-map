"""T-VN-32C PR-2 — read 응답 feature_id 값 UUID 전환 통합 검증 (ADR-068).

실 PostGIS(alembic head) 위에서 API 표면을 httpx ASGITransport로 직접 호출해
값 전환의 계약을 고정한다:

① cursor 연속성 (R3 — 최중요) — bbox(``/features``)·search·nearby·public beach
   목록 4계열 모두 2페이지 이상 걸치는 조건에서 누락·중복 0. cursor keyset은
   치환 **전** legacy 축이고 응답 ``feature_id``는 UUID 정본이다 — repo 매퍼
   단계에서 치환하면 keyset이 조용히 깨지는 회귀를 페이지 합집합으로 잡는다.
② 응답 값 == 저장 uuid — 단건 상세·목록의 ``feature_id``가
   ``feature.features.feature_uuid`` 저장값과 문자열로 일치하고 ``feature_uuid``
   병행 필드와도 같다.
③ batch echo 등식 (R2) — service feature batch·weather batch의 item
   ``feature_id``는 **요청 표기 그대로** 돌아온다(legacy in → legacy out,
   UUID in → UUID out). PinVi 클라이언트가 이 등식을 런타임 강제 중이다.
④ write 해석 → legacy FK (R4) — admin create의 UUID ``feature_id`` 거부(422),
   ``parent_feature_id`` UUID 참조의 legacy 해석 기록, update-request
   scope.feature_ids의 UUID→legacy 해석과 미해석 422 fail-close.
⑤ admin 검색 UUID fast-path (R5) — ``list_admin_features(q=<uuid>)``가 해당
   feature 1건을 반환한다 (#639 풀스캔 회귀의 기능 축; EXPLAIN 등가는
   ``test_t212d_perf_explain``).

R6(curated snapshot UUID)은 ``test_curated_repo``의 물질화 테스트가 고정한다.
"""

from __future__ import annotations

import uuid as uuid_module
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any

import httpx
import pytest
from fastapi import HTTPException
from kortravelmap.api import feature_update_service
from kortravelmap.api.app import create_app
from kortravelmap.api.db import get_session
from kortravelmap.api.feature_update_schema import (
    FeatureIdsScope,
    FeatureUpdateRequestCreateRequest,
    FeatureUpdateRequestPreviewRequest,
)
from kortravelmap.api.settings import ApiSettings
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, AsyncSession

from kortravelmap.core.ids import make_payload_hash, make_source_record_key
from kortravelmap.dto import (
    Address,
    Coordinate,
    Feature,
    FeatureBundle,
    FeatureKind,
    SourceLink,
    SourceRecord,
    SourceRole,
)
from kortravelmap.infra import admin_feature_repo, feature_repo
from kortravelmap.providers.khoa import beaches_to_bundles
from kortravelmap.settings import KorTravelMapSettings

if TYPE_CHECKING:
    from collections.abc import Sequence

pytestmark = pytest.mark.integration

_KST = timezone(timedelta(hours=9))
_FETCHED = datetime(2026, 8, 5, 12, 0, tzinfo=_KST)

_PROVIDER = "python-standard-data-api"
_DATASET = "cultural_festivals"
_ENTITY_TYPE = "festival"

# 다른 테스트의 잔존 commit과 절대 겹치지 않을 외해 bbox (제주 남서 해상).
_BBOX = {
    "min_lon": 124.6000,
    "min_lat": 33.1000,
    "max_lon": 124.6100,
    "max_lat": 33.1100,
}
_NEARBY_CENTER = (124.6050, 33.1050)

_MISSING_LEGACY_REF = "f_global_p_t32cmissing00001"
_MISSING_UUID_REF = "00000000-0000-7000-8000-00000000dead"


@dataclass(frozen=True)
class _SeededIdentity:
    """seed된 feature의 legacy 키·UUID 정본 쌍."""

    feature_id: str
    feature_uuid: str


@dataclass(frozen=True)
class _CutoverEnv:
    """API app + 공유 connection + seed 목록."""

    client: httpx.AsyncClient
    connection: AsyncConnection
    places: tuple[_SeededIdentity, ...]
    beaches: tuple[_SeededIdentity, ...]


def _place_bundle(
    feature_id: str,
    *,
    name: str,
    lon: float,
    lat: float,
) -> FeatureBundle:
    raw_data = {"natural_key": feature_id, "name": name}
    raw_payload_hash = make_payload_hash(raw_data)
    source_record_key = make_source_record_key(
        provider=_PROVIDER,
        dataset_key=_DATASET,
        source_entity_type=_ENTITY_TYPE,
        source_entity_id=feature_id,
        raw_payload_hash=raw_payload_hash,
    )
    feature = Feature(
        feature_id=feature_id,
        kind=FeatureKind.PLACE,
        name=name,
        address=Address(),
        category="01070100",
        coord=Coordinate(lon=lon, lat=lat),
        marker_icon="star",
        marker_color="P-03",
        created_at=_FETCHED,
        updated_at=_FETCHED,
    )
    source_record = SourceRecord(
        provider=_PROVIDER,
        dataset_key=_DATASET,
        source_entity_type=_ENTITY_TYPE,
        source_entity_id=feature_id,
        raw_payload_hash=raw_payload_hash,
        raw_name=name,
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
        is_primary_source=True,
        created_at=_FETCHED,
    )
    return FeatureBundle(
        feature=feature,
        source_record=source_record,
        source_link=source_link,
    )


async def _stored_feature_uuid(session: AsyncSession, feature_id: str) -> str:
    """정본(features)에 저장된 ``feature_uuid`` — 모든 read 기대값의 기준."""
    return str(
        (
            await session.execute(
                text(
                    "SELECT CAST(feature_uuid AS text) FROM feature.features "
                    "WHERE feature_id = :fid"
                ),
                {"fid": feature_id},
            )
        ).scalar_one()
    )


async def _seed_place(
    session: AsyncSession,
    feature_id: str,
    *,
    name: str,
    lon: float,
    lat: float,
) -> _SeededIdentity:
    await feature_repo.load_bundle(
        session, _place_bundle(feature_id, name=name, lon=lon, lat=lat)
    )
    await session.flush()
    return _SeededIdentity(
        feature_id=feature_id,
        feature_uuid=await _stored_feature_uuid(session, feature_id),
    )


@dataclass(frozen=True)
class _Beach:
    name: str
    sido_name: str
    gugun_name: str | None
    latitude: float | None
    longitude: float | None
    beach_kind: str | None
    image_url: str | None
    raw: Any = None


async def _seed_beaches(session: AsyncSession) -> tuple[_SeededIdentity, ...]:
    bundles = await beaches_to_bundles(
        [
            _Beach(
                name=f"T32C 전환검증 해수욕장 {index}",
                sido_name="부산광역시",
                gugun_name="수영구",
                latitude=35.1500 + 0.0010 * index,
                longitude=129.1100 + 0.0010 * index,
                beach_kind="일반",
                image_url=None,
            )
            for index in range(1, 4)
        ],
        fetched_at=_FETCHED,
    )
    seeded: list[_SeededIdentity] = []
    for bundle in bundles:
        await feature_repo.load_bundle(session, bundle)
        await session.flush()
        seeded.append(
            _SeededIdentity(
                feature_id=bundle.feature.feature_id,
                feature_uuid=await _stored_feature_uuid(
                    session, bundle.feature.feature_id
                ),
            )
        )
    return tuple(seeded)


def _api_settings() -> ApiSettings:
    return ApiSettings(
        _env_file=None,
        admin_proxy_secret=None,
        ops_cancel_token=None,
        ops_read_token=None,
        public_api_key_required=False,
        service_token=None,
        vworld_api_key=None,
    )


@pytest.fixture
async def cutover_env(migrated_engine: AsyncEngine) -> AsyncIterator[_CutoverEnv]:
    """seed + API client — 전부 outer transaction 안 (테스트 간 격리 rollback)."""
    async with migrated_engine.connect() as connection:
        outer = await connection.begin()
        async with AsyncSession(
            bind=connection,
            join_transaction_mode="create_savepoint",
        ) as setup, setup.begin():
            places = tuple(
                [
                    await _seed_place(
                        setup,
                        f"f_1100000000_p_t32cpage000{index}",
                        name=f"T32C 페이지 표적 {index}",
                        lon=124.6020 + 0.0010 * index,
                        lat=33.1020 + 0.0010 * index,
                    )
                    for index in range(1, 6)
                ]
            )
            beaches = await _seed_beaches(setup)

        app = create_app(_api_settings())

        async def _request_session() -> AsyncIterator[AsyncSession]:
            async with AsyncSession(
                bind=connection,
                expire_on_commit=False,
                join_transaction_mode="create_savepoint",
            ) as session:
                yield session

        app.dependency_overrides[get_session] = _request_session
        transport = httpx.ASGITransport(app=app)
        try:
            async with httpx.AsyncClient(
                transport=transport, base_url="http://test"
            ) as client:
                yield _CutoverEnv(
                    client=client,
                    connection=connection,
                    places=places,
                    beaches=beaches,
                )
        finally:
            await outer.rollback()


# ── ① cursor 연속성 (R3) + ② 응답 값 == 저장 uuid ──────────────────────────


async def _walk_pages(
    client: httpx.AsyncClient,
    path: str,
    params: dict[str, Any],
    *,
    page_size: int,
    max_pages: int = 10,
) -> list[list[dict[str, Any]]]:
    """cursor를 따라 전 페이지를 걷는다 — 종료 보장 실패는 그 자체로 회귀다."""
    pages: list[list[dict[str, Any]]] = []
    cursor: str | None = None
    for _ in range(max_pages):
        query: dict[str, Any] = {**params, "page_size": page_size}
        if cursor is not None:
            query["cursor"] = cursor
        response = await client.get(path, params=query)
        assert response.status_code == 200, response.text
        body = response.json()
        pages.append(body["data"]["items"])
        cursor = body["meta"]["page"]["next_cursor"]
        if cursor is None:
            return pages
    raise AssertionError(f"{path} page walk did not terminate")


def _assert_uuid_page_union(
    pages: list[list[dict[str, Any]]],
    expected: Sequence[_SeededIdentity],
) -> None:
    """전 페이지 합집합 무결 + 각 item feature_id의 UUID 정본성."""
    collected = [item["feature_id"] for page in pages for item in page]
    assert len(collected) == len(set(collected)), "cursor 페이지 사이 중복 발생"
    assert set(collected) == {identity.feature_uuid for identity in expected}
    for page in pages:
        for item in page:
            # canonical hyphenated UUID — legacy `f_*` 표기 잔존은 회귀다.
            parsed = uuid_module.UUID(item["feature_id"])
            assert str(parsed) == item["feature_id"]
            if "feature_uuid" in item:
                assert item["feature_uuid"] == item["feature_id"]


async def test_bbox_list_pages_are_gapless_and_uuid_valued(
    cutover_env: _CutoverEnv,
) -> None:
    pages = await _walk_pages(
        cutover_env.client, "/v1/features", dict(_BBOX), page_size=2
    )
    assert len(pages) >= 2, "2페이지 이상 걸쳐야 cursor 연속성이 검증된다"
    _assert_uuid_page_union(pages, cutover_env.places)


async def test_search_pages_are_gapless_and_uuid_valued(
    cutover_env: _CutoverEnv,
) -> None:
    # bbox-only search — feature_id keyset 축 (트grm 점수 비결정성 배제).
    pages = await _walk_pages(
        cutover_env.client, "/v1/features/search", dict(_BBOX), page_size=2
    )
    assert len(pages) >= 2
    _assert_uuid_page_union(pages, cutover_env.places)


async def test_nearby_pages_are_gapless_and_uuid_valued(
    cutover_env: _CutoverEnv,
) -> None:
    lon, lat = _NEARBY_CENTER
    pages = await _walk_pages(
        cutover_env.client,
        "/v1/features/nearby",
        {"lon": lon, "lat": lat, "radius_m": 2000},
        page_size=2,
    )
    assert len(pages) >= 2
    _assert_uuid_page_union(pages, cutover_env.places)


async def test_public_beach_pages_are_gapless_and_uuid_valued(
    cutover_env: _CutoverEnv,
) -> None:
    pages = await _walk_pages(
        cutover_env.client,
        "/v1/public/beaches",
        {"q": "T32C 전환검증"},
        page_size=1,
    )
    assert len(pages) >= 2
    _assert_uuid_page_union(pages, cutover_env.beaches)


async def test_detail_and_list_feature_id_equal_stored_feature_uuid(
    cutover_env: _CutoverEnv,
) -> None:
    """응답 feature_id == features.feature_uuid 저장값 == feature_uuid 필드."""
    target = cutover_env.places[0]
    by_legacy = await cutover_env.client.get(f"/v1/features/{target.feature_id}")
    assert by_legacy.status_code == 200, by_legacy.text
    data = by_legacy.json()["data"]
    assert data["feature_id"] == target.feature_uuid
    assert data["feature_uuid"] == target.feature_uuid

    # canonical UUID 참조도 같은 정본 값으로 수렴한다 (dual-read + 값 전환).
    by_uuid = await cutover_env.client.get(f"/v1/features/{target.feature_uuid}")
    assert by_uuid.status_code == 200, by_uuid.text
    assert by_uuid.json()["data"]["feature_id"] == target.feature_uuid

    listed = await cutover_env.client.get(
        "/v1/features", params={**_BBOX, "page_size": 100}
    )
    assert listed.status_code == 200, listed.text
    by_id = {item["feature_id"]: item for item in listed.json()["data"]["items"]}
    assert by_id[target.feature_uuid]["feature_uuid"] == target.feature_uuid


# ── ③ batch echo 등식 (R2) ─────────────────────────────────────────────────


async def test_feature_batch_echoes_request_notation(
    cutover_env: _CutoverEnv,
) -> None:
    """legacy·UUID 혼합 요청 — item feature_id는 요청 표기 그대로 (echo 계약)."""
    first, second = cutover_env.places[0], cutover_env.places[1]
    refs = [
        first.feature_id,  # legacy 표기
        first.feature_uuid,  # 같은 feature의 UUID 표기 — 조회 1회, echo 별도
        second.feature_uuid,  # 다른 feature의 UUID 표기
        _MISSING_LEGACY_REF,
        _MISSING_UUID_REF,
    ]
    response = await cutover_env.client.post(
        "/v1/features/batch",
        json={"items": [{"feature_id": ref} for ref in refs]},
    )
    assert response.status_code == 200, response.text
    items = response.json()["data"]["items"]
    assert [item["feature_id"] for item in items] == refs
    assert [item["state"] for item in items] == [
        "found",
        "found",
        "found",
        "missing",
        "missing",
    ]
    # echo는 표기 보존, 정본은 feature_uuid 필드가 밝힌다.
    assert items[0]["feature_uuid"] == first.feature_uuid
    assert items[1]["feature_uuid"] == first.feature_uuid
    assert items[2]["feature_uuid"] == second.feature_uuid
    # trip_card.feature_id는 item echo와 동일 값 — PinVi가
    # `trip_card.feature_id == item.feature_id` 등식을 런타임 강제한다(리뷰 F1).
    for item, ref in zip(items[:3], refs[:3], strict=False):
        assert item["trip_card"]["feature_id"] == ref


async def test_weather_batch_echoes_target_notation(
    cutover_env: _CutoverEnv,
) -> None:
    first, second = cutover_env.places[0], cutover_env.places[1]
    refs = [first.feature_id, first.feature_uuid, second.feature_uuid]
    target_at = datetime(2026, 8, 5, 12, 0, tzinfo=UTC)
    response = await cutover_env.client.post(
        "/v1/features/weather/batch",
        json={
            "targets": [
                {"target_at": target_at.isoformat(), "feature_ids": refs}
            ],
            "known_at": target_at.isoformat(),
        },
    )
    assert response.status_code == 200, response.text
    items = response.json()["data"]["targets"][0]["items"]
    assert [item["feature_id"] for item in items] == refs
    # weather 미적재 공개 parent — 상태는 no_data, echo·uuid 병행은 그대로.
    assert {item["state"] for item in items} == {"no_data"}
    assert items[0]["feature_uuid"] == first.feature_uuid
    assert items[1]["feature_uuid"] == first.feature_uuid
    assert items[2]["feature_uuid"] == second.feature_uuid


# ── ④ write 해석 → legacy FK (R4) ──────────────────────────────────────────


def _admin_create_body(**overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "kind": "place",
        "name": "T32C write 해석 검증 장소",
        "category": "01070100",
        "marker_icon": "star",
        "marker_color": "P-03",
        "reason": "T-VN-32C PR-2 write 경계 검증",
    }
    body.update(overrides)
    return body


def _idempotency_headers() -> dict[str, str]:
    return {"Idempotency-Key": str(uuid_module.uuid4())}


async def test_admin_create_rejects_uuid_feature_id(
    cutover_env: _CutoverEnv,
) -> None:
    """UUID를 신규 legacy PK로 각인하는 유령 행 생성 차단 (W1 — 422)."""
    response = await cutover_env.client.post(
        "/v1/admin/features",
        json=_admin_create_body(feature_id=cutover_env.places[0].feature_uuid),
        headers=_idempotency_headers(),
    )
    assert response.status_code == 422, response.text


async def test_admin_create_resolves_parent_uuid_ref_to_legacy(
    cutover_env: _CutoverEnv,
) -> None:
    """parent_feature_id의 UUID 참조는 legacy 정본 키로 해석되어 기록된다."""
    parent = cutover_env.places[0]
    response = await cutover_env.client.post(
        "/v1/admin/features",
        json=_admin_create_body(parent_feature_id=parent.feature_uuid),
        headers=_idempotency_headers(),
    )
    assert response.status_code == 200, response.text
    record = response.json()["data"]["request"]
    assert record["payload"]["parent_feature_id"] == parent.feature_id

    # 영속된 change request payload도 legacy 정본 키다 (응답만 정규화되는
    # 착시 차단 — FK 오염은 저장 payload가 진실이다).
    async with AsyncSession(
        bind=cutover_env.connection,
        join_transaction_mode="create_savepoint",
    ) as probe:
        stored = (
            await probe.execute(
                text(
                    "SELECT payload FROM ops.feature_change_requests "
                    "WHERE request_id = CAST(:request_id AS uuid)"
                ),
                {"request_id": record["request_id"]},
            )
        ).scalar_one()
    assert stored["parent_feature_id"] == parent.feature_id


async def test_admin_create_rejects_unresolvable_parent_uuid_ref(
    cutover_env: _CutoverEnv,
) -> None:
    response = await cutover_env.client.post(
        "/v1/admin/features",
        json=_admin_create_body(parent_feature_id=_MISSING_UUID_REF),
        headers=_idempotency_headers(),
    )
    assert response.status_code == 422, response.text


async def test_update_request_scope_resolves_uuid_refs_to_legacy(
    migrated_session: AsyncSession,
) -> None:
    """scope.feature_ids의 UUID 표기는 legacy 정본 집합으로 해석된다 (S1)."""
    first = await _seed_place(
        migrated_session,
        "f_1100000000_p_t32cscope0001",
        name="T32C scope 표적 1",
        lon=124.6210,
        lat=33.1210,
    )
    second = await _seed_place(
        migrated_session,
        "f_1100000000_p_t32cscope0002",
        name="T32C scope 표적 2",
        lon=124.6220,
        lat=33.1220,
    )
    body = FeatureUpdateRequestPreviewRequest(
        scope=FeatureIdsScope(
            type="feature_ids",
            feature_ids=[first.feature_uuid, second.feature_id],
        )
    )
    resolved = await feature_update_service.resolve_feature_ids_scope_refs(
        body, migrated_session
    )
    assert isinstance(resolved.scope, FeatureIdsScope)
    assert resolved.scope.feature_ids == [first.feature_id, second.feature_id]

    # 같은 feature의 UUID·legacy 이중 표기는 canonical 1건으로 dedup된다.
    duplicated = FeatureUpdateRequestPreviewRequest(
        scope=FeatureIdsScope(
            type="feature_ids",
            feature_ids=[first.feature_uuid, first.feature_id],
        )
    )
    deduplicated = await feature_update_service.resolve_feature_ids_scope_refs(
        duplicated, migrated_session
    )
    assert isinstance(deduplicated.scope, FeatureIdsScope)
    assert deduplicated.scope.feature_ids == [first.feature_id]


async def test_create_update_request_resolves_scope_inside_service_transaction(
    cutover_env: _CutoverEnv,
) -> None:
    """리뷰 H1 회귀 — create 전 과정이 **실세션**으로 성공해야 한다.

    라우터에서 scope를 먼저 해석하면 SELECT autobegin이 서비스의
    ``session.begin()``과 충돌해 feature_ids scope 요청이 전건 500이 된다.
    해석은 서비스 트랜잭션 안(idempotency lock 직후)에서 수행되고, 저장
    레코드의 scope는 legacy 정본으로 canonical화된다.
    """
    first, second = cutover_env.places[0], cutover_env.places[1]
    body = FeatureUpdateRequestCreateRequest(
        scope=FeatureIdsScope(
            type="feature_ids",
            # UUID·legacy 혼합 + 같은 feature 이중 표기 → 해석·dedup 결과 고정.
            feature_ids=[first.feature_uuid, first.feature_id, second.feature_id],
        ),
        reason="T32C H1 회귀 검증",
    )

    async def _noop_guard(_pairs: frozenset[tuple[str, str]]) -> None:
        return None

    key = uuid_module.UUID("00000000-0000-4000-8000-0000000032c1")
    session = AsyncSession(
        bind=cutover_env.connection, join_transaction_mode="create_savepoint"
    )
    try:
        result = await feature_update_service.create_feature_update_request(
            body,
            session,
            idempotency_key=key,
            operator="t32c-h1-regression",
            status_url_prefix="/v1/ops/pipeline/executions/update_request",
            settings=KorTravelMapSettings(),
            resolved_plan_guard=_noop_guard,
        )
        assert result.idempotent_replay is False
        scope = result.data.scope
        assert isinstance(scope, FeatureIdsScope)
        assert scope.feature_ids == [first.feature_id, second.feature_id]

        # 같은 key 재전송 — 해석 후 fingerprint가 동일하므로 terminal 재생.
        replay_session = AsyncSession(
            bind=cutover_env.connection, join_transaction_mode="create_savepoint"
        )
        try:
            replay = await feature_update_service.create_feature_update_request(
                body,
                replay_session,
                idempotency_key=key,
                operator="t32c-h1-regression",
                status_url_prefix="/v1/ops/pipeline/executions/update_request",
                settings=KorTravelMapSettings(),
                resolved_plan_guard=_noop_guard,
            )
        finally:
            await replay_session.close()
        assert replay.idempotent_replay is True
        assert replay.data.request_id == result.data.request_id
    finally:
        await session.close()


async def test_update_request_scope_rejects_unresolvable_uuid_ref(
    migrated_session: AsyncSession,
) -> None:
    body = FeatureUpdateRequestPreviewRequest(
        scope=FeatureIdsScope(
            type="feature_ids",
            feature_ids=[_MISSING_UUID_REF],
        )
    )
    with pytest.raises(HTTPException) as error:
        await feature_update_service.resolve_feature_ids_scope_refs(
            body, migrated_session
        )
    assert error.value.status_code == 422
    detail = error.value.detail
    assert isinstance(detail, dict)
    assert detail["code"] == "FEATURE_REF_UNRESOLVED"
    assert _MISSING_UUID_REF in detail["details"]["unresolved"]


# ── ⑤ admin 검색 UUID fast-path (R5) ───────────────────────────────────────


async def test_admin_search_uuid_fast_path_returns_single_feature(
    migrated_session: AsyncSession,
) -> None:
    """UUID 검색어가 해당 feature 1건으로 등가 해석된다 (#639 회귀의 기능 축)."""
    seeded = await _seed_place(
        migrated_session,
        "f_1100000000_p_t32cfastpath1",
        name="T32C fast-path 표적",
        lon=124.6310,
        lat=33.1310,
    )
    page = await admin_feature_repo.list_admin_features(
        migrated_session, q=seeded.feature_uuid
    )
    assert [item.feature_id for item in page.items] == [seeded.feature_id]
    assert page.items[0].feature_uuid == seeded.feature_uuid
    assert page.next_cursor is None

    # 대문자 표기도 같은 fast-path에 태운다 — 경계 해석·batch echo와 표면 간
    # 일관(소문자 전용이면 ILIKE 풀스캔 #639 회귀, 리뷰 F2).
    upper = await admin_feature_repo.list_admin_features(
        migrated_session, q=seeded.feature_uuid.upper()
    )
    assert [item.feature_id for item in upper.items] == [seeded.feature_id]

    # 존재하지 않는 UUID 검색어는 존재하지 않는 legacy id와 동일하게 빈 결과다.
    empty = await admin_feature_repo.list_admin_features(
        migrated_session, q=_MISSING_UUID_REF
    )
    assert empty.items == ()
