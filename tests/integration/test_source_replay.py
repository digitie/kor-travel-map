"""replay 읽기·적재 — 저장된 원본으로 같은 변환기를 다시 돌린다(ADR-109 결정 7, T-GR-08).

실제 jsonb 왕복을 지난다: fetch 경로로 적재(geo 토큰 A) → ``read_current_source_records``로 읽기 →
``ReplayRecordStream``·``REPLAY_FROM_RAW``로 되살리기 → 같은 변환기(geo 토큰 B의 답) →
``apply_replay_provenance`` → 적재. 확인하는 것:

- 새 source record 0건, head 관측 시각 불변(``became_current`` 거짓 — 관측을 꾸미지 않는다).
- geo 값만 새 답으로 바뀌고 스탬프가 토큰 B로 전진한다(replay가 재지오코딩의 수단이다).
- retired Feature의 entity는 읽지 않는다 — 되살리지 않는다.
- keyset 페이지(``limit=1``)가 빠짐·중복 없이 끝까지 간다.
- MOIS는 replay가 아니지만(golden 실패 — fetch), 릴리스 run의 acceptance 술어는 같다: 스탬프 없는
  payload-bjd 행은 reverse 없이 ``not_called`` 스탬프를 받고 두 번째 run은 변환 0건.

세션은 테스트마다 롤백된다(``migrated_session``).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import TYPE_CHECKING, Any

import pytest
from kortravelmap.dagster.resources import REPLAY_FROM_RAW
from kortravelmap.dagster.source_replay import ReplayRecordStream, apply_replay_provenance
from sqlalchemy import text

from kortravelmap.dto import Address, Coordinate
from kortravelmap.dto.geo_dataset import DatasetRef, GeoApplied, GeoLoadContext
from kortravelmap.infra import feature_identity
from kortravelmap.infra.feature_geocode_stamp_repo import coverage, get_stamp
from kortravelmap.infra.feature_repo import (
    find_unchanged_active_source_entities,
    load_bundles,
    resolve_active_provider_dataset_id,
    retire_features_by_source_entity_ids,
)
from kortravelmap.infra.source_replay_repo import (
    CurrentSourceRecord,
    read_current_source_records,
)
from kortravelmap.providers.datagokr_file_data import (
    DATAGOKR_FILEDATA_PROVIDER_NAME,
    file_data_rows_to_bundles,
)
from kortravelmap.providers.mois import DATASET_KEY_BULK as MOIS_DATASET_KEY_BULK
from kortravelmap.providers.mois import PROVIDER_NAME as MOIS_PROVIDER_NAME
from kortravelmap.providers.mois import (
    license_record_payload_hash,
    license_record_to_bundle,
    license_source_entity_id,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from kortravelmap.dto import FeatureBundle

pytestmark = pytest.mark.integration

_FETCHED = datetime(2026, 9, 1, 3, 0, tzinfo=UTC)
_REPLAY_RUN = datetime(2026, 10, 16, 3, 0, tzinfo=UTC)
TOKEN_A = "dd1-" + "1" * 32
TOKEN_B = "dd1-" + "2" * 32
REF_A = DatasetRef(version_token="dv1-" + "a" * 32, data_token=TOKEN_A)
REF_B = DatasetRef(version_token="dv1-" + "b" * 32, data_token=TOKEN_B)
_REVERSE = GeoApplied(reverse=True, geocode=False)


class _Reverse:
    def __init__(self, admin: str) -> None:
        self.admin = admin
        self.calls = 0

    async def __call__(self, coord: Coordinate) -> Address:
        self.calls += 1
        return Address(
            legal="서울특별시 영등포구 여의도동",
            admin=self.admin,
            bjd_code="1156011000",
            admin_dong_code="1156054000",
            sigungu_code="11560",
            sido_code="11",
            road_name_code="115603118001",
            zipcode="07237",
            sido_name="서울특별시",
            sigungu_name="영등포구",
        )


def _ctx(ref: DatasetRef) -> GeoLoadContext:
    return GeoLoadContext(
        geo_applied=_REVERSE, current_dataset=ref, observed_data_tokens=frozenset()
    )


_BOOKSTORES = "datagokr_seoul_bookstores"


def _bookstore(seq: int) -> dict[str, Any]:
    """서울 열린데이터광장 책방 row(JSON number 식별자·float 좌표 — jsonb 왕복이 다루는 꼴).

    provider 라이브러리(``providers`` extra)가 없는 CI에서도 도는 replay 경로다 — fileData는
    원본 row mapping을 그대로 되살린다. 표준데이터의 실모델 golden은 dagster 패키지 테스트다.
    """
    return {
        "STORE_SEQ_NO": float(seq),
        "STORE_NAME": f"가상 책방 {seq}",
        "ADRES": f"영등포구 여의공원로 {seq}",
        "XCNTS": 37.5263123456789 + (seq % 100) / 100000,
        "YDNTS": 126.923912,
        "TEL_NO": "02-1",
    }


async def _bookstore_bundles(rows: list[dict[str, Any]], reverse: Any) -> list[FeatureBundle]:
    return await file_data_rows_to_bundles(
        rows, dataset_key=_BOOKSTORES, fetched_at=_FETCHED, reverse_geocoder=reverse
    )


class _SessionClient:
    """``AsyncKorTravelMapClient.read_current_source_records``를 테스트 session으로 흉내 낸다."""

    def __init__(self, session: AsyncSession, provider_dataset_id: int) -> None:
        self.session = session
        self.provider_dataset_id = provider_dataset_id

    async def read_current_source_records(
        self, *, provider: str, dataset_key: str, batch_size: int = 1000
    ) -> list[CurrentSourceRecord]:
        return await _read_all(self.session, self.provider_dataset_id, limit=batch_size)


async def _read_all(
    session: AsyncSession, provider_dataset_id: int, *, limit: int
) -> list[CurrentSourceRecord]:
    records: list[CurrentSourceRecord] = []
    after = ""
    while True:
        page = await read_current_source_records(
            session,
            provider_dataset_id=provider_dataset_id,
            after_source_entity_key=after,
            limit=limit,
        )
        records.extend(page)
        if len(page) < limit:
            return records
        after = page[-1].source_entity_key


async def _head(session: AsyncSession, source_entity_key: str) -> tuple[Any, ...]:
    row = (
        await session.execute(
            text(
                "SELECT current_source_record_key, observed_at "
                "FROM provider_sync.source_entity_heads WHERE source_entity_key = :key"
            ),
            {"key": source_entity_key},
        )
    ).one()
    return tuple(row)


async def _admin(session: AsyncSession, feature_id: str) -> str | None:
    value = (
        await session.execute(
            text(
                "SELECT address->>'admin' FROM feature.features "
                "WHERE feature_id = CAST(:id AS uuid)"
            ),
            {"id": feature_id},
        )
    ).scalar_one()
    return None if value is None else str(value)


async def _lifecycle(session: AsyncSession, feature_id: str) -> str:
    return str(
        (
            await session.execute(
                text(
                    "SELECT lifecycle_state FROM feature.features "
                    "WHERE feature_id = CAST(:id AS uuid)"
                ),
                {"id": feature_id},
            )
        ).scalar_one()
    )


async def _feature_id(session: AsyncSession, bundle: FeatureBundle) -> str:
    identity = await feature_identity.resolve_feature_identity(session, bundle.feature.feature_id)
    assert identity is not None
    return identity.feature_id


async def test_replay_regeocodes_without_a_new_observation_and_never_resurrects(
    migrated_session: AsyncSession,
) -> None:
    session = migrated_session
    fetched = await _bookstore_bundles(
        [_bookstore(seq) for seq in (2283, 2284, 2285)], _Reverse("여의동")
    )
    loaded = await load_bundles(session, fetched, geo=_ctx(REF_A))
    assert loaded.source_records_inserted == 3
    feature_ids = [await _feature_id(session, bundle) for bundle in fetched]
    # provider에서 사라진 entity — retired. replay가 이것을 되살리면 안 된다.
    retired = fetched[2].source_record
    assert (
        await retire_features_by_source_entity_ids(
            session,
            provider=retired.provider,
            dataset_key=retired.dataset_key,
            source_entity_type=retired.source_entity_type,
            source_entity_ids={retired.source_entity_id},
        )
        == 1
    )

    dataset_id = await resolve_active_provider_dataset_id(
        session, provider=DATAGOKR_FILEDATA_PROVIDER_NAME, dataset_key=_BOOKSTORES
    )
    paged = await _read_all(session, dataset_id, limit=1)
    assert {r.source_entity_id for r in paged} == {
        b.source_record.source_entity_id for b in fetched[:2]
    }
    assert [r.source_entity_key for r in paged] == sorted(r.source_entity_key for r in paged)
    assert len({r.source_entity_key for r in paged}) == 2  # 중복 없음, retired 제외
    heads_before = {r.source_entity_key: await _head(session, r.source_entity_key) for r in paged}

    stream = ReplayRecordStream(
        _SessionClient(session, dataset_id),  # type: ignore[arg-type]
        provider=DATAGOKR_FILEDATA_PROVIDER_NAME,
        dataset_key=_BOOKSTORES,
        from_raw=REPLAY_FROM_RAW["datagokr_file_data_records"],
    )
    await stream.prefetch()
    records = [record async for record in stream]
    reverse = _Reverse("여의동(새 경계)")
    converted = await file_data_rows_to_bundles(
        records, dataset_key=_BOOKSTORES, fetched_at=_REPLAY_RUN, reverse_geocoder=reverse
    )
    replayed = apply_replay_provenance(stream, converted)
    assert reverse.calls == 2
    assert {b.source_record.fetched_at for b in replayed} == {_FETCHED}

    result = await load_bundles(session, replayed, geo=_ctx(REF_B))

    assert result.source_records_inserted == 0
    for key, before in heads_before.items():
        assert await _head(session, key) == before  # 관측 시각·current record 불변
    for feature_id in feature_ids[:2]:
        assert await _admin(session, feature_id) == "여의동(새 경계)"
        stamp = await get_stamp(session, feature_id)
        assert stamp is not None
        assert stamp.geo_data_token == TOKEN_B
    assert await _lifecycle(session, feature_ids[2]) == "retired"
    assert await _admin(session, feature_ids[2]) == "여의동"


async def test_file_data_rows_survive_the_jsonb_round_trip(migrated_session: AsyncSession) -> None:
    """JSON number 식별자(``2283.0``)·긴 float 좌표가 실제 jsonb를 지나도 같은 bundle이다."""
    session = migrated_session
    reverse = _Reverse("여의동")
    fetched = await _bookstore_bundles([_bookstore(2283)], reverse)
    await load_bundles(session, fetched, geo=_ctx(REF_A))
    dataset_id = await resolve_active_provider_dataset_id(
        session, provider=DATAGOKR_FILEDATA_PROVIDER_NAME, dataset_key=_BOOKSTORES
    )
    stored = await _read_all(session, dataset_id, limit=1000)
    assert len(stored) == 1
    replayed = await _bookstore_bundles(
        [REPLAY_FROM_RAW["datagokr_file_data_records"](stored[0].raw_data)], reverse
    )
    assert replayed[0].source_record.raw_payload_hash == stored[0].raw_payload_hash
    generated = {"imported_at", "created_at", "updated_at"}  # 변환을 부른 순간(kst_now)

    def content(value: Any) -> Any:
        if isinstance(value, dict):
            return {k: content(v) for k, v in value.items() if k not in generated}
        return value

    assert [content(b.model_dump(mode="json")) for b in replayed] == [
        content(b.model_dump(mode="json")) for b in fetched
    ]


# -- MOIS(fetch) — 릴리스 run이 스탬프 없는 payload-bjd 행에 reverse 없이 스탬프를 찍는다 ----------


@dataclass(frozen=True)
class _Mois:
    """``MoisLicensePlaceRecord`` 모사 — payload에 법정동코드가 있는 행."""

    mng_no: str
    service_slug: str = "general_restaurants"
    category: str | None = "식품"
    title: str | None = "식품_일반음식점"
    opn_authority_code: str | None = "3220000"
    place_name: str | None = "가상 식당"
    status_code: str | None = "01"
    status_name: str | None = "영업/정상"
    detail_status_code: str | None = None
    detail_status_name: str | None = None
    is_open: bool | None = True
    license_date: date | None = None
    telno: str | None = None
    road_address: str | None = "서울특별시 강남구 테헤란로 1"
    lot_address: str | None = None
    road_zip: str | None = None
    lot_zip: str | None = None
    legal_dong_code: str | None = "1168010100"
    road_name_code: str | None = None
    building_management_number: str | None = None
    lon: float | None = 127.03
    lat: float | None = 37.50
    source_x: float | None = None
    source_y: float | None = None
    business_type_name: str | None = None
    subtype_name: str | None = None
    multi_use_business_place_yn: str | None = None
    sanitation_business_status_name: str | None = None
    facility_total_scale: str | None = None
    water_supply_facility_type_name: str | None = None
    culture_sports_business_type_name: str | None = None
    sales_method_name: str | None = None
    designation_date: date | None = None
    building_usage_name: str | None = None
    ground_floor_count: int | None = None
    underground_floor_count: int | None = None
    total_floor_count: int | None = None
    facility_area: float | None = None
    total_area: float | None = None
    sickbed_count: int | None = None
    bed_count: int | None = None
    healthcare_worker_count: int | None = None
    hospital_room_count: int | None = None
    medical_institution_type_name: str | None = None
    medical_subject_names: str | None = None


async def test_mois_release_run_stamps_unstamped_payload_bjd_rows_without_reverse(
    migrated_session: AsyncSession,
) -> None:
    """acceptance §T-GR-08의 MOIS 항목 — MOIS는 fetch로 돌지만 같은 술어가 성립한다(N=3)."""
    session = migrated_session
    records = [_Mois(mng_no=f"3220000-101-2026-{index:05d}") for index in range(3)]
    reverse = _Reverse("역삼1동")

    async def convert() -> list[FeatureBundle]:
        return [
            await license_record_to_bundle(record, fetched_at=_FETCHED, reverse_geocoder=reverse)
            for record in records
        ]

    # 스탬프 도입 전에 적재된 행 — geo 문맥 없이 적재하면 스탬프가 없다.
    first = await convert()
    await load_bundles(session, first)
    dataset_id = await resolve_active_provider_dataset_id(
        session, provider=MOIS_PROVIDER_NAME, dataset_key=MOIS_DATASET_KEY_BULK
    )
    before = await coverage(session, TOKEN_B, provider_dataset_ids=[dataset_id])
    assert (before.unstamped, before.not_called_by_kind) == (3, {})

    entity_type = first[0].source_record.source_entity_type
    hashes = {license_source_entity_id(r): license_record_payload_hash(r) for r in records}

    async def unchanged() -> frozenset[str]:
        return await find_unchanged_active_source_entities(
            session,
            provider=MOIS_PROVIDER_NAME,
            dataset_key=MOIS_DATASET_KEY_BULK,
            source_entity_type=entity_type,
            payload_hashes=hashes,
            current_data_token=TOKEN_B,
        )

    # 1 run: 스탬프가 없으니 "그대로"가 아니다 → 변환한다(payload bjd라 reverse 0회).
    assert await unchanged() == frozenset()
    await load_bundles(session, await convert(), geo=_ctx(REF_B))
    assert reverse.calls == 0
    after = await coverage(session, TOKEN_B, provider_dataset_ids=[dataset_id])
    assert (after.unstamped, after.not_called_by_kind) == (0, {"place": 3})
    # 2 run: 전부 `not_called` 스탬프 — 변환 0건.
    assert await unchanged() == frozenset(hashes)
