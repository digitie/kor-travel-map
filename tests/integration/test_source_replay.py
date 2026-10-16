"""replay 읽기·적재 — 저장된 원본으로 같은 변환기를 다시 돌린다(ADR-109 결정 7, T-GR-08).

실제 jsonb 왕복을 지난다: fetch 경로로 적재(geo 토큰 A) → ``read_current_source_records``로 읽기 →
``ReplayRecordStream``·``REPLAY_FROM_RAW``로 되살리기 → 같은 변환기(geo 토큰 B의 답) →
``apply_replay_provenance`` → 적재. 확인하는 것:

- 새 source record 0건, head 관측 시각 불변(``became_current`` 거짓 — 관측을 꾸미지 않는다).
- geo 값만 새 답으로 바뀌고 스탬프가 토큰 B로 전진한다(replay가 재지오코딩의 수단이다).
- retired Feature의 entity는 읽지 않는다 — 되살리지 않는다.
- keyset 페이지(``limit=1``)가 빠짐·중복 없이 끝까지 간다.

세션은 테스트마다 롤백된다(``migrated_session``).
"""

from __future__ import annotations

import importlib
from datetime import UTC, date, datetime
from typing import TYPE_CHECKING, Any

import pytest
from kortravelmap.dagster.resources import REPLAY_FROM_RAW
from kortravelmap.dagster.source_replay import ReplayRecordStream, apply_replay_provenance
from sqlalchemy import text

from kortravelmap.dto import Address, Coordinate
from kortravelmap.dto.geo_dataset import DatasetRef, GeoApplied, GeoLoadContext
from kortravelmap.infra import feature_identity
from kortravelmap.infra.feature_geocode_stamp_repo import get_stamp
from kortravelmap.infra.feature_repo import (
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
from kortravelmap.providers.standard_data import (
    DATASET_KEY_CULTURAL_FESTIVALS,
    STANDARD_DATA_PROVIDER_NAME,
    cultural_festivals_to_bundles,
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


def _festival(name: str) -> Any:
    return importlib.import_module("datagokr").PublicCulturalFestival.model_validate(
        {
            "fstvlNm": name,
            "opar": "여의도공원",
            "fstvlStartDate": "2026-10-01",
            "fstvlEndDate": "2026-10-09",
            "rdnmadr": f"서울특별시 영등포구 여의공원로 {len(name)}",
            "latitude": "37.526312345678901",
            "longitude": "126.923912",
            "referenceDate": "2026-09-01",
            "instt_nm": "서울특별시 영등포구",
        }
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
    names = ["축제 가", "축제 나나", "축제 다다다"]
    fetched = await cultural_festivals_to_bundles(
        [_festival(name) for name in names],
        fetched_at=_FETCHED,
        reverse_geocoder=_Reverse("여의동"),
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
        session, provider=STANDARD_DATA_PROVIDER_NAME, dataset_key=DATASET_KEY_CULTURAL_FESTIVALS
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
        provider=STANDARD_DATA_PROVIDER_NAME,
        dataset_key=DATASET_KEY_CULTURAL_FESTIVALS,
        from_raw=REPLAY_FROM_RAW["datagokr_cultural_festivals"],
    )
    await stream.prefetch()
    records = [record async for record in stream]
    reverse = _Reverse("여의동(새 경계)")
    converted = await cultural_festivals_to_bundles(
        records, fetched_at=_REPLAY_RUN, reverse_geocoder=reverse
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
    """서울 책방의 JSON number 식별자(``2283.0``)·float 좌표가 jsonb를 지나도 같은 bundle이다."""
    session = migrated_session
    rows = [
        {
            "STORE_SEQ_NO": 2283.0,
            "STORE_NAME": "가상 책방",
            "ADRES": "마포구 동교로 194",
            "XCNTS": 37.5571234567891,
            "YDNTS": 126.9221234567891,
            "TEL_NO": "02-1",
            "기준일": date(2026, 9, 1).isoformat(),
        }
    ]
    reverse = _Reverse("서교동")
    fetched = await file_data_rows_to_bundles(
        rows, dataset_key="datagokr_seoul_bookstores", fetched_at=_FETCHED, reverse_geocoder=reverse
    )
    await load_bundles(session, fetched, geo=_ctx(REF_A))
    dataset_id = await resolve_active_provider_dataset_id(
        session, provider=DATAGOKR_FILEDATA_PROVIDER_NAME, dataset_key="datagokr_seoul_bookstores"
    )
    stored = await _read_all(session, dataset_id, limit=1000)
    assert len(stored) == 1
    replayed = await file_data_rows_to_bundles(
        [REPLAY_FROM_RAW["datagokr_file_data_records"](stored[0].raw_data)],
        dataset_key="datagokr_seoul_bookstores",
        fetched_at=_FETCHED,
        reverse_geocoder=reverse,
    )
    assert replayed[0].source_record.raw_payload_hash == stored[0].raw_payload_hash
    assert [b.model_dump(mode="json") for b in replayed] == [
        b.model_dump(mode="json") for b in fetched
    ]
