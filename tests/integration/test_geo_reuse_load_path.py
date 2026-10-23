"""저장값 재사용(ADR-116) — payload·좌표·geo 토큰이 그대로인 행은 역지오코딩하지 않는다.

두 부분이다.

1. **조회 술어**(``read_reusable_geo_columns``, 테스트마다 롤백되는 ``migrated_session``) — 그대로인
   행은 저장 주소 열과 함께 나오고, payload·좌표·토큰·override 중 하나라도 다르면 빠진다.
2. **실제 client 경로**(Dagster와 같은 연결 1개 엔진, ADR-113 spool) — 두 번째 적재가 stream 안에서
   조회하고(쓰기 transaction 밖), 바뀌지 않은 행은 geo를 부르지 않으며, 적재
   결과(``row_revision``·스탬프· 주소 열)는 전량 지오코딩한 적재와 같다. 바뀐 payload·옛 토큰 행은
   geo를 부른다. 큐 경로처럼 executor transaction에 결합한 client에서도 같다.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Sequence
from datetime import UTC, date, datetime
from typing import TYPE_CHECKING, Any

import pytest
from kortravelmap.dagster.feature_update_runner import _bind_client_to_session
from kortravelmap.dagster.geo_reuse import transform_reusing_stored_geo
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from kortravelmap.client import AsyncKorTravelMapClient
from kortravelmap.dto import Address, Coordinate
from kortravelmap.dto.geo_dataset import DatasetRef, GeoApplied, GeoLoadContext
from kortravelmap.geocoding import GeoCallStats, ReverseGeocoder
from kortravelmap.infra import feature_identity
from kortravelmap.infra.db import make_async_engine, make_async_session_factory
from kortravelmap.infra.feature_geocode_load import address_column_values
from kortravelmap.infra.feature_geocode_reuse import read_reusable_geo_columns
from kortravelmap.infra.feature_repo import load_bundles
from kortravelmap.providers.standard_data import cultural_festivals_to_bundles
from kortravelmap.settings import KorTravelMapSettings
from tests.integration._db_cleanup import truncate_committed_test_rows
from tests.integration.test_client_orchestration import _Festival

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine

    from kortravelmap.dto import FeatureBundle

pytestmark = pytest.mark.integration

_FETCHED = datetime(2026, 10, 23, tzinfo=UTC)
VERSION = "dv1-" + "a" * 32
TOKEN_A = "dd1-" + "1" * 32
TOKEN_B = "dd1-" + "2" * 32
REF_A = DatasetRef(version_token=VERSION, data_token=TOKEN_A)
REF_B = DatasetRef(version_token=VERSION, data_token=TOKEN_B)
_REVERSE = GeoApplied(reverse=True, geocode=False)
_DAGSTER_SERVER_SETTINGS = {"statement_timeout": "600000", "lock_timeout": "30000"}
_TRUNCATE_SQL = (
    "TRUNCATE feature.features, "
    "provider_sync.source_entities, provider_sync.source_entity_heads, "
    "provider_sync.source_records, "
    "provider_sync.source_links RESTART IDENTITY CASCADE"
)


class _Reverse:
    """좌표의 함수인 결정적 답(같은 토큰이면 같은 좌표에 같은 답).

    ``generation``은 geo 데이터셋이다.
    """

    def __init__(self, generation: str = "A") -> None:
        self.generation = generation
        self.calls: list[tuple[str, str]] = []

    async def __call__(self, coord: Coordinate) -> Address | None:
        self.calls.append((str(coord.lon), str(coord.lat)))
        return Address(
            legal="서울특별시 영등포구 여의도동",
            admin="여의동",
            bjd_code="1156011000",
            admin_dong_code="1156054000",
            sigungu_code="11560",
            sido_code="11",
            road_name_code="115603118001" if self.generation == "A" else "115603118999",
            zipcode="07237",
            sido_name="서울특별시",
            sigungu_name="영등포구",
        )


def _item(seed: str, *, lat: float = 37.5263, description: str = "축제") -> _Festival:
    return _Festival(
        fstvl_nm=f"재사용 축제 {seed}",
        opar="여의도공원",
        fstvl_start_date=date(2026, 10, 1),
        fstvl_end_date=date(2026, 10, 9),
        fstvl_co=description,
        rdnmadr=f"서울특별시 영등포구 여의공원로 120 ({seed})",
        lnmadr="서울특별시 영등포구 여의도동 8",
        latitude=lat,
        longitude=126.9239,
        reference_date=date(2026, 9, 1),
        instt_nm="서울특별시 영등포구",
    )


def _transform(items: Sequence[_Festival]) -> Any:
    async def run(geocoder: ReverseGeocoder) -> list[FeatureBundle]:
        return await cultural_festivals_to_bundles(
            items,  # type: ignore[arg-type]
            fetched_at=_FETCHED,
            reverse_geocoder=geocoder,
        )

    return run


def _comparable(bundles: Sequence[FeatureBundle]) -> list[str]:
    """bundle 비교 키 — ``source_link.created_at``(만들 때의 now)만 뺀다."""
    dumped = []
    for bundle in bundles:
        data = bundle.model_dump(mode="json")
        data["source_link"].pop("created_at")
        dumped.append(json.dumps(data, sort_keys=True, ensure_ascii=False))
    return sorted(dumped)


def _ctx(ref: DatasetRef, token: str) -> GeoLoadContext:
    return GeoLoadContext(
        geo_applied=_REVERSE, current_dataset=ref, observed_data_tokens=frozenset({token})
    )


async def _feature_id(session: AsyncSession, bundle: FeatureBundle) -> str:
    identity = await feature_identity.resolve_feature_identity(session, bundle.feature.feature_id)
    assert identity is not None
    return identity.feature_id


# 
# -- 1. 조회 술어 ------------------------------------------------------------------------------


async def _loaded(session: AsyncSession, seed: str) -> FeatureBundle:
    bundle = (await _transform([_item(seed)])(_Reverse()))[0]
    result = await load_bundles(session, [bundle], geo=_ctx(REF_A, TOKEN_A))
    assert result.geo_stamps_written == 1
    return bundle


async def test_an_unchanged_row_is_reusable_with_its_stored_columns(
    migrated_session: AsyncSession,
) -> None:
    bundle = await _loaded(migrated_session, "same")
    again = (await _transform([_item("same")])(_Reverse()))[0]

    found = await read_reusable_geo_columns(
        migrated_session, [again], current_data_token=TOKEN_A
    )

    key = again.source_record.source_record_key
    assert set(found) == {key}
    expected = address_column_values(bundle.feature.address)
    assert {column: found[key][column] for column in expected if column != "address"} == {
        column: value for column, value in expected.items() if column != "address"
    }
    assert Address.model_validate(found[key]["address"]) == bundle.feature.address


async def test_a_changed_payload_is_not_reusable(migrated_session: AsyncSession) -> None:
    await _loaded(migrated_session, "payload")
    changed = (await _transform([_item("payload", description="바뀐 설명")])(_Reverse()))[0]

    assert await read_reusable_geo_columns(
        migrated_session, [changed], current_data_token=TOKEN_A
    ) == {}


async def test_a_changed_coordinate_is_not_reusable(migrated_session: AsyncSession) -> None:
    bundle = await _loaded(migrated_session, "coord")
    # payload key는 그대로 두고 좌표만 바꾼다 — 좌표 조건이 따로 결박돼 있는지 본다.
    original = bundle.feature.coord
    assert original is not None
    moved = bundle.model_copy(
        update={
            "feature": bundle.feature.model_copy(
                update={"coord": Coordinate(lon=original.lon, lat=37.6)}
            )
        }
    )

    assert await read_reusable_geo_columns(
        migrated_session, [moved], current_data_token=TOKEN_A
    ) == {}
    # 의도적 대조: 좌표가 같으면 나온다.
    assert await read_reusable_geo_columns(
        migrated_session, [bundle], current_data_token=TOKEN_A
    )


async def test_an_old_token_stamp_is_not_reusable(migrated_session: AsyncSession) -> None:
    bundle = await _loaded(migrated_session, "token")

    assert await read_reusable_geo_columns(
        migrated_session, [bundle], current_data_token=TOKEN_B
    ) == {}


async def test_an_address_override_is_not_reusable(migrated_session: AsyncSession) -> None:
    bundle = await _loaded(migrated_session, "override")
    feature_id = await _feature_id(migrated_session, bundle)
    await migrated_session.execute(
        text(
            "INSERT INTO ops.feature_overrides (feature_id, field_path, override_value, status)"
            "VALUES (CAST(:id AS uuid), 'core.road_name_code', CAST(:value AS jsonb), 'active')"
        ),
        {"id": feature_id, "value": json.dumps("115603118777")},
    )

    assert await read_reusable_geo_columns(
        migrated_session, [bundle], current_data_token=TOKEN_A
    ) == {}


async def test_a_row_never_loaded_is_not_reusable(migrated_session: AsyncSession) -> None:
    fresh = (await _transform([_item("never-loaded")])(_Reverse()))[0]

    assert await read_reusable_geo_columns(
        migrated_session, [fresh], current_data_token=TOKEN_A
    ) == {}


# 
# -- 2. 실제 client 경로(ADR-113 spool, 연결 1개) ------------------------------------------------


@pytest.fixture
async def dagster_like_engine(
    dagster_runtime_engine: AsyncEngine,
    migrated_engine: AsyncEngine,
) -> AsyncIterator[AsyncEngine]:
    dsn = dagster_runtime_engine.url.render_as_string(hide_password=False)
    engine = make_async_engine(
        dsn, pool_size=1, max_overflow=0, server_settings=_DAGSTER_SERVER_SETTINGS
    )
    try:
        yield engine
    finally:
        await engine.dispose()
        async with AsyncSession(migrated_engine) as session, session.begin():
            await truncate_committed_test_rows(session, _TRUNCATE_SQL)


async def _state(engine: AsyncEngine, bundles: Sequence[FeatureBundle]) -> dict[str, Any]:
    """Feature별 (row_revision, 주소 유도 열, 스탬프 토큰·outcome·시각)."""
    out: dict[str, Any] = {}
    async with AsyncSession(engine) as session, session.begin():
        for bundle in bundles:
            feature_id = await _feature_id(session, bundle)
            row = (
                await session.execute(
                    text(
                        "SELECT feature.row_revision, feature.address, feature.legal_dong_code, "
                        "feature.road_name_code, stamp.geo_data_token, stamp.reverse_outcome "
                        "FROM feature.features AS feature "
                        "LEFT JOIN feature.feature_geocode_stamps AS stamp USING (feature_id) "
                        "WHERE feature.feature_id = CAST(:id AS uuid)"
                    ),
                    {"id": feature_id},
                )
            ).mappings().one()
            out[bundle.source_record.source_entity_id] = dict(row)
    return out


async def _load_run(
    client: AsyncKorTravelMapClient,
    items: Sequence[_Festival],
    *,
    live: _Reverse,
    ref: DatasetRef,
    stats: GeoCallStats,
) -> list[FeatureBundle]:
    """asset의 snapshot 경로 모양.

    batch마다 stream 안에서 변환(재사용)하고, 쓰기는 spool 뒤 한 번이다.
    """
    token = ref.data_token
    assert token is not None
    produced: list[FeatureBundle] = []

    async def lookup(bundles: Sequence[FeatureBundle]) -> Any:
        return await client.read_reusable_geo_columns(bundles, current_data_token=token)

    async def batches() -> AsyncIterator[Sequence[FeatureBundle]]:
        for start in range(0, len(items), 2):
            batch = await transform_reusing_stored_geo(
                _transform(items[start : start + 2]), live=live, lookup=lookup, stats=stats
            )
            produced.extend(batch)
            yield batch

    await client.load_feature_bundle_batches(batches(), geo=_ctx(ref, token))
    return produced


async def test_unchanged_rows_skip_geo_and_load_exactly_like_a_full_geocode(
    dagster_like_engine: AsyncEngine,
) -> None:
    client = AsyncKorTravelMapClient(
        dagster_like_engine,
        settings=KorTravelMapSettings(feature_load_curation_lock_wait_seconds=120),
    )
    # 좌표는 행마다 다르게 둔다 — 같은 좌표를 나눈 행은 저장값이 갈리면(축제 원문 주소)
    # 재사용하지 않는다.
    items = [_item(f"R{index}", lat=37.52 + index / 1000) for index in range(5)]

    first_live = _Reverse()
    await _load_run(client, items, live=first_live, ref=REF_A, stats=GeoCallStats())
    assert len(first_live.calls) == 5  # 스탬프가 없다 — 전량 지오코딩
    loaded = await _transform(items)(_Reverse())
    before = await _state(dagster_like_engine, loaded)

    # 둘째 run: R0는 payload가 바뀌고 나머지는 그대로.
    second_items = [_item("R0", lat=37.52, description="바뀐 설명"), *items[1:]]
    second_live = _Reverse()
    stats = GeoCallStats()
    produced = await _load_run(client, second_items, live=second_live, ref=REF_A, stats=stats)

    assert len(second_live.calls) == 1, second_live.calls  # 바뀐 R0만
    assert dict(stats.reuse) == {"skipped": 4, "geocoded": 1, "fallback": 0}
    # 전량 지오코딩한 변환과 같은 bundle이다.
    full = await _transform(second_items)(_Reverse())
    assert _comparable(produced) == _comparable(full)
    after = await _state(dagster_like_engine, loaded)
    for key in list(after)[1:]:
        assert after[key] == before[key], key  # row_revision·주소·스탬프 그대로
    assert after[next(iter(after))]["row_revision"] > before[next(iter(before))]["row_revision"]

    # 셋째 run: geo 데이터셋이 B로 바뀌었다 — 옛 토큰 스탬프는 전부 다시 지오코딩한다(ADR-109).
    third_live = _Reverse(generation="B")
    stats_b = GeoCallStats()
    await _load_run(client, second_items, live=third_live, ref=REF_B, stats=stats_b)
    assert len(third_live.calls) == 5
    assert stats_b.reuse["skipped"] == 0
    final = await _state(dagster_like_engine, loaded)
    assert {row["geo_data_token"] for row in final.values()} == {TOKEN_B}
    assert {row["road_name_code"] for row in final.values()} == {"115603118999"}


async def test_queue_bound_client_reuses_inside_the_executor_transaction(
    dagster_like_engine: AsyncEngine,
) -> None:
    """큐 경로: executor transaction에 결합한 client(연결 1개)로 조회해도 막히지 않고 재사용한다."""
    client = AsyncKorTravelMapClient(
        dagster_like_engine,
        settings=KorTravelMapSettings(feature_load_curation_lock_wait_seconds=120),
    )
    items = [_item(f"Q{index}", lat=37.53 + index / 1000) for index in range(3)]
    await _load_run(client, items, live=_Reverse(), ref=REF_A, stats=GeoCallStats())

    live = _Reverse()
    async with make_async_session_factory(dagster_like_engine)() as executor, executor.begin():
        await executor.execute(text("SELECT 1"))
        bound = await _bind_client_to_session(client, executor)
        await _load_run(bound, items, live=live, ref=REF_A, stats=GeoCallStats())

    assert live.calls == []
