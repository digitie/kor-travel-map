"""records resource ``source_mode=replay`` (ADR-109 결정 7, T-GR-08).

- golden: 저장된 ``raw_data``(jsonb 왕복)를 replay 경로(``REPLAY_FROM_RAW``)로 되살려 같은 변환기에
  넣은 bundle이 fetch bundle과 **같다** — resource마다.
- MOIS는 golden이 성립하지 않는다(raw가 record 1:1이 아니다) — 그래서 replay 목록에 없다.
- 효과: replay resource는 provider HTTP를 0회 보낸다(``httpx.AsyncClient.send``를 세는 fake).
  같은 fake가 fetch 모드에서는 호출을 센다 — 세는 장치가 살아 있다는 대조군.
- launchable replay operation의 job은 replay run_config를 Dagster config 검증으로 받는다
  (MOIS는 거부).
- provenance: replay bundle은 저장된 ``fetched_at``·``observed_at``을 되돌려 받고, payload가 다르면
  적재 전에 실패한다.
- asset 배선: replay면 적재 전에 읽고, bundle에 provenance가 붙고, sync state를 쓰지 않는다.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Callable, Sequence
from dataclasses import dataclass, fields
from datetime import UTC, date, datetime
from decimal import Decimal
from types import SimpleNamespace
from typing import Any, cast

import httpx
import pytest
from dagster import validate_run_config
from kortravelmap.core.feature_operation import (
    REPLAY_RECORDS_RESOURCES,
    SENSOR_LAUNCHABLE_REPLAY_OPERATION_KEYS,
)
from kortravelmap.dto import Address, Coordinate, FeatureBundle
from kortravelmap.infra.geo_release_repo import run_config_for_dataset
from kortravelmap.infra.source_replay_repo import CurrentSourceRecord
from kortravelmap.providers.datagokr_file_data import file_data_rows_to_bundles
from kortravelmap.providers.mois import license_record_to_bundle
from kortravelmap.providers.standard_data import (
    cultural_festivals_to_bundles,
    museums_to_bundles,
    parking_lots_to_bundles,
    special_streets_to_bundles,
    tourist_attractions_to_bundles,
)

from kortravelmap.dagster import assets, resources
from kortravelmap.dagster.definitions import defs
from kortravelmap.dagster.feature_operation_tracking import FeatureOperationExecutionGuard
from kortravelmap.dagster.source_replay import (
    ReplayPayloadDrift,
    ReplayRecordStream,
    apply_replay_provenance,
)

pytestmark = pytest.mark.filterwarnings(
    "ignore:Parameter `owners` of initializer `SensorDefinition.__init__`"
    ".*:dagster_shared.utils.warnings.BetaWarning"
)

_FETCHED = datetime(2026, 10, 16, 3, 0, tzinfo=UTC)
_STORED_FETCHED = datetime(2026, 9, 1, 3, 0, tzinfo=UTC)
_STORED_OBSERVED = datetime(2026, 10, 1, 3, 0, tzinfo=UTC)


async def _reverse(coord: Coordinate) -> Address:
    """좌표마다 다른 답(결정적) — fetch와 replay가 같은 답을 받는다."""
    sigungu = "11560" if coord.lat > Decimal("37") else "50110"
    return Address(
        bjd_code=f"{sigungu}10100",
        sigungu_code=sigungu,
        sido_code=sigungu[:2],
        admin="가상동",
        road_name_code=f"{sigungu}3118001",
        zipcode="07237",
    )


@dataclass(frozen=True)
class _Api:
    """provider API JSON(camelCase alias) 한 행 — 테스트 안에서 provider 모델로 만든다.

    provider 라이브러리는 ``providers`` extra라 CI에 없다(``test_provider_protocol_conformance``
    머리말). 실모델 golden은 설치된 환경(Dagster 이미지·n150 providers venv)에서 돈다 — 없으면
    skip하고, CI에서는 ``tests/lint/test_replay_raw_is_a_record_snapshot.py``가 같은 성질을
    구조로 본다. fileData는 원본 row mapping이라 provider 없이도 돈다.
    """

    model: str
    payload: dict[str, Any]


def _datagokr(model: str, payload: dict[str, Any]) -> _Api:
    return _Api(model, payload)


def _materialize(record: Any) -> Any:
    if isinstance(record, _Api):
        datagokr = pytest.importorskip("datagokr")
        return getattr(datagokr, record.model).model_validate(record.payload)
    return record


def _jsonb_round_trip(raw: dict[str, Any]) -> dict[str, Any]:
    """``_source_record_params``의 직렬화(``default=str``) + jsonb 키 재정렬을 흉내 낸다."""
    loaded = json.loads(json.dumps(raw, ensure_ascii=False, default=str, sort_keys=True))
    assert isinstance(loaded, dict)
    return loaded


_Convert = Callable[[list[Any]], Any]


def _standard(convert: Callable[..., Any]) -> _Convert:
    return lambda items: convert(items, fetched_at=_FETCHED, reverse_geocoder=_reverse)


def _file_data(dataset_key: str) -> _Convert:
    return lambda items: file_data_rows_to_bundles(
        items, dataset_key=dataset_key, fetched_at=_FETCHED, reverse_geocoder=_reverse
    )


#: resource → [(변환기, fetch record들)]. fileData는 dataset 넷이 한 resource를 쓴다.
_GOLDEN: dict[str, list[tuple[_Convert, list[Any]]]] = {
    "datagokr_cultural_festivals": [
        (
            _standard(cultural_festivals_to_bundles),
            [
                _datagokr(
                    "PublicCulturalFestival",
                    {
                        "fstvlNm": " 한강 불빛 축제 ",
                        "opar": "여의도 한강공원",
                        "fstvlStartDate": "2026-10-01",
                        "fstvlEndDate": "2026-10-09",
                        "fstvlCo": "불꽃과 음악",
                        "mnnstNm": "서울특별시",
                        "auspcInsttNm": "서울특별시",
                        "suprtInsttNm": "",
                        "phoneNumber": "02-120",
                        "homepageUrl": "https://example.org/festival",
                        "rdnmadr": "서울특별시 영등포구 여의동로 330",
                        "lnmadr": "서울특별시 영등포구 여의도동 85",
                        "latitude": "37.528312345678901",
                        "longitude": "126.932949",
                        "referenceDate": "2026-09-01",
                        "instt_code": "3010000",
                        "instt_nm": "서울특별시 영등포구",
                        "insttCode": "알 수 없는 원천 열(extra)",
                    },
                ),
                _datagokr(
                    "PublicCulturalFestival",
                    {
                        "fstvlNm": "좌표 없는 축제",
                        "rdnmadr": "제주특별자치도 제주시 문연로 6",
                        "fstvlStartDate": "2026-11-01",
                    },
                ),
            ],
        )
    ],
    "standard_museums": [
        (
            _standard(museums_to_bundles),
            [
                _datagokr(
                    "PublicMuseumArtGallery",
                    {
                        "fcltyNm": "가상 미술관",
                        "fcltyType": "미술관",
                        "rdnmadr": "서울특별시 종로구 삼청로 30",
                        "lnmadr": "서울특별시 종로구 소격동 165",
                        "latitude": "37.5786",
                        "longitude": "126.9806",
                        "operPhoneNumber": "02-3701-9500",
                        "homepageUrl": "https://example.org/museum",
                        "weekdayOperOpenHhmm": "10:00",
                        "adultChrge": "2000",
                        "instt_code": "B551000",
                    },
                ),
                _datagokr("PublicMuseumArtGallery", {"fcltyNm": "코드 없는 박물관"}),
            ],
        )
    ],
    "standard_tourist_attractions": [
        (
            _standard(tourist_attractions_to_bundles),
            [
                _datagokr(
                    "PublicTouristAttraction",
                    {
                        "trrsrtNm": "가상 관광지",
                        "trrsrtSe": "관광단지",
                        "rdnmadr": "제주특별자치도 서귀포시 중문관광로 72",
                        "latitude": "33.2490",
                        "longitude": "126.4120",
                        "ar": "12.5",
                        "phoneNumber": "064-1",
                        "instt_code": "6500000",
                    },
                )
            ],
        )
    ],
    "standard_parking_lots": [
        (
            _standard(parking_lots_to_bundles),
            [
                _datagokr(
                    "PublicParkingLot",
                    {
                        "prkplceNo": "123-4-000001",
                        "prkplceNm": "가상 공영주차장",
                        "prkplceSe": "공영",
                        "rdnmadr": "서울특별시 마포구 월드컵로 240",
                        "prkcmprt": "120",
                        "parkingchrgeInfo": "유료",
                        "addUnitTime": "0.5",
                        "addUnitCharge": "200+400",
                        "latitude": "37.5683",
                        "longitude": "126.8975",
                        "phoneNumber": "02-1",
                        "instt_code": "3130000",
                    },
                )
            ],
        )
    ],
    "standard_special_streets": [
        (
            _standard(special_streets_to_bundles),
            [
                _datagokr(
                    "PublicSpecialStreet",
                    {
                        "stretNm": "가상 특화거리",
                        "stretIntrcn": "  골목 소개  ",
                        "rdnmadr": "부산광역시 중구 광복로 1",
                        "latitude": "35.0989",
                        "longitude": "129.0300",
                        "stretLt": "1.2",
                        "storNumber": "35",
                        "appnYear": "2015",
                        "institutionNm": "부산광역시 중구",
                        "referenceDate": "2025-12-31",
                        "instt_code": "3270000",
                        "instt_nm": "부산광역시 중구",
                    },
                )
            ],
        )
    ],
    "datagokr_file_data_records": [
        (
            _file_data("datagokr_seoul_bookstores"),
            [
                {
                    "STORE_SEQ_NO": 2283.0,
                    "STORE_NAME": "가상 책방",
                    "ADRES": "마포구 동교로 194",
                    "XCNTS": 37.5571234,
                    "YDNTS": 126.9221234,
                    "TEL_NO": "02-1",
                    "STORE_TYPE_NAME": "독립서점",
                    "HMPG_URL": None,
                },
                {"책방명": "한글 열 책방", "주소": "서울특별시 종로구 1", "관리번호": "0012"},
            ],
        ),
        (
            _file_data("datagokr_gyeonggi_muslim_friendly_restaurants"),
            [
                {
                    "상호": "가상 할랄식당",
                    "주소": "경기도 안산시 단원구 원곡로 1",
                    "위도": "37.3311",
                    "경도": "126.8001",
                    "연락처": "031-1",
                    "지역": "안산",
                    "종류": "할랄",
                }
            ],
        ),
        (
            _file_data("datagokr_ansan_world_restaurants"),
            [
                {
                    "가게명": "가상 세계맛집",
                    "주소": "경기도 안산시 단원구 다문화길 2",
                    "위도": 37.3312,
                    "경도": 126.8002,
                    "음식종류": "베트남",
                    "조회수": 12,
                    "작성일": "2020-01-01",
                }
            ],
        ),
        (
            _file_data("datagokr_jeju_local_restaurants"),
            [
                {
                    "업소명": "가상 향토음식점",
                    "소재지": "제주특별자치도 제주시 관덕로 1",
                    "위도": "33.5130",
                    "경도": "126.5220",
                    "지정번호": "J-1",
                    "관리기관": "제주시",
                    "데이터기준일자": "2025-01-01",
                }
            ],
        ),
    ],
}


def _fetch_records(resource_key: str, records: list[Any]) -> list[Any]:
    """fetch가 변환기에 넘기는 record. fileData는 원본 row mapping(``PublicFileDataRecord.raw``)."""
    del resource_key
    return [_materialize(record) for record in records]


#: 생성 시각 기본값(``kst_now``) — 내용이 아니라 변환을 부른 순간이다.
_GENERATED_AT = frozenset({"imported_at", "created_at", "updated_at"})


def _content(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _content(v) for k, v in value.items() if k not in _GENERATED_AT}
    if isinstance(value, list):
        return [_content(v) for v in value]
    return value


def _by_key(bundles: Sequence[FeatureBundle]) -> dict[str, dict[str, Any]]:
    return {
        bundle.source_record.source_record_key: _content(bundle.model_dump(mode="json"))
        for bundle in bundles
    }


def test_replay_resources_match_the_core_replay_table() -> None:
    assert set(resources.REPLAY_FROM_RAW) == set(REPLAY_RECORDS_RESOURCES.values())
    assert set(_GOLDEN) == set(resources.REPLAY_FROM_RAW)  # golden 없는 replay resource 금지
    assert frozenset(REPLAY_RECORDS_RESOURCES) == SENSOR_LAUNCHABLE_REPLAY_OPERATION_KEYS


@pytest.mark.parametrize("resource_key", sorted(_GOLDEN))
async def test_replay_bundle_equals_fetch_bundle(resource_key: str) -> None:
    from_raw = resources.REPLAY_FROM_RAW[resource_key]
    for convert, records in _GOLDEN[resource_key]:
        fetched = await convert(_fetch_records(resource_key, records))
        assert fetched, resource_key
        stored = [_jsonb_round_trip(bundle.source_record.raw_data) for bundle in fetched]
        replayed = await convert([from_raw(raw) for raw in reversed(stored)])
        assert _by_key(replayed) == _by_key(fetched)


@dataclass(frozen=True)
class _MoisRecord:
    """``MoisLicensePlaceRecord`` 모사 — 변환기가 읽는 필드 전부."""

    service_slug: str = "general_restaurants"
    mng_no: str | None = "MNG-1"
    category: str | None = "식품"
    title: str | None = "식품_일반음식점"
    opn_authority_code: str | None = "3220000"
    place_name: str | None = "가상 식당"
    status_code: str | None = "01"
    status_name: str | None = "영업/정상"
    detail_status_code: str | None = "01"
    detail_status_name: str | None = "영업"
    is_open: bool | None = True
    license_date: date | None = date(2020, 1, 2)
    telno: str | None = "02-1"
    road_address: str | None = "서울특별시 강남구 테헤란로 1"
    lot_address: str | None = "서울특별시 강남구 역삼동 1"
    road_zip: str | None = "06236"
    lot_zip: str | None = None
    legal_dong_code: str | None = "1168010100"
    road_name_code: str | None = "116803122001"
    building_management_number: str | None = "1168010100100010000000001"
    lon: float | None = 127.03
    lat: float | None = 37.50
    source_x: float | None = 202000.0
    source_y: float | None = 444000.0
    business_type_name: str | None = "한식"
    subtype_name: str | None = "한식"
    multi_use_business_place_yn: str | None = "Y"
    sanitation_business_status_name: str | None = "영업"
    facility_total_scale: str | None = None
    water_supply_facility_type_name: str | None = "상수도"
    culture_sports_business_type_name: str | None = None
    sales_method_name: str | None = None
    designation_date: date | None = None
    building_usage_name: str | None = "근린생활시설"
    ground_floor_count: int | None = 3
    underground_floor_count: int | None = 1
    total_floor_count: int | None = 4
    facility_area: float | None = 85.5
    total_area: float | None = 120.0
    sickbed_count: int | None = None
    bed_count: int | None = None
    healthcare_worker_count: int | None = None
    hospital_room_count: int | None = None
    medical_institution_type_name: str | None = None
    medical_subject_names: str | None = None


async def test_mois_raw_data_is_not_a_record_snapshot() -> None:
    """MOIS를 replay에 넣지 않은 근거 — raw에 없는 필드는 되살릴 수 없어 bundle이 달라진다."""
    record = _MoisRecord()
    fetched = await license_record_to_bundle(record, fetched_at=_FETCHED)
    raw = _jsonb_round_trip(fetched.source_record.raw_data)
    known = {item.name for item in fields(_MoisRecord)}
    restored = _MoisRecord(
        **{key: value for key, value in raw.items() if key in known and key != "license_date"},
        license_date=date.fromisoformat(raw["license_date"]),
        **{name: None for name in known - set(raw) if name != "service_slug"},
    )
    replayed = await license_record_to_bundle(restored, fetched_at=_FETCHED)
    lost = known - set(raw)
    assert "building_management_number" in lost
    assert "facility_area" in lost
    assert replayed.source_record.raw_payload_hash == fetched.source_record.raw_payload_hash
    assert replayed.model_dump(mode="json") != fetched.model_dump(mode="json")
    assert "feature_place_mois_licenses_job" not in REPLAY_RECORDS_RESOURCES


# -- 효과: provider HTTP 0회 ------------------------------------------------------------------


class _Sent(BaseException):
    """요청이 전송 계층에 닿았다(재시도 래퍼가 삼키지 못하게 BaseException)."""


class _ReplayClient:
    def __init__(self, records: list[CurrentSourceRecord]) -> None:
        self.records = records
        self.reads: list[tuple[str, str]] = []

    async def read_current_source_records(
        self, *, provider: str, dataset_key: str, batch_size: int = 1000
    ) -> list[CurrentSourceRecord]:
        self.reads.append((provider, dataset_key))
        return self.records


_INSTANCE = object()


def _context(client: object, config: dict[str, object]) -> Any:
    guard = FeatureOperationExecutionGuard(
        client=cast(Any, client),
        instance=_INSTANCE,
        operation_key=None,
        memberships=(),
        dagster_run_id="replay-test",
        trigger_kind=None,
    )
    return SimpleNamespace(
        resource_config=config,
        resources=SimpleNamespace(feature_operation_guard=guard, kor_travel_map_client=client),
        instance=_INSTANCE,
        run=SimpleNamespace(job_name="panel_only_job", run_id="replay-test"),
    )


async def _drain(value: object) -> list[Any]:
    return [item async for item in cast(AsyncIterator[Any], value)]


@pytest.fixture
def sends(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    seen: list[str] = []

    async def _send(self: httpx.AsyncClient, request: httpx.Request, **_: object) -> Any:
        seen.append(str(request.url.host))
        raise _Sent

    monkeypatch.setattr(httpx.AsyncClient, "send", _send)
    monkeypatch.setenv("KOR_TRAVEL_MAP_DATA_GO_KR_SERVICE_KEY", "test-key")
    monkeypatch.setenv("KOR_TRAVEL_MAP_SEOUL_OPEN_DATA_API_KEY", "test-key")
    return seen


@pytest.mark.parametrize("resource_key", sorted(_GOLDEN))
def test_replay_resource_sends_no_provider_request(resource_key: str, sends: list[str]) -> None:
    convert, records = _GOLDEN[resource_key][0]
    fetched = asyncio.run(convert(_fetch_records(resource_key, records)))
    stored = [
        CurrentSourceRecord(
            source_entity_key=f"se_{index}",
            source_entity_type=bundle.source_record.source_entity_type,
            source_entity_id=bundle.source_record.source_entity_id,
            raw_data=_jsonb_round_trip(bundle.source_record.raw_data),
            raw_payload_hash=bundle.source_record.raw_payload_hash,
            fetched_at=_STORED_FETCHED,
            observed_at=_STORED_OBSERVED,
        )
        for index, bundle in enumerate(fetched)
    ]
    client = _ReplayClient(stored)
    resource_fn = cast(
        "Callable[[object], object]",
        resources.PROVIDER_RECORD_RESOURCE_DEFINITIONS[resource_key].resource_fn,
    )
    config: dict[str, object] = {"source_mode": "replay"}
    if resource_key == "datagokr_file_data_records":
        config["dataset_key"] = "datagokr_seoul_bookstores"

    value = resource_fn(_context(client, config))
    assert isinstance(value, ReplayRecordStream)
    assert len(asyncio.run(_drain(value))) == len(stored)
    assert sends == []  # provider 전송 0회
    assert len(client.reads) == 1

    # 대조군 — 같은 fake가 fetch 모드의 요청은 센다(세는 장치가 살아 있다).
    fetch_config = {key: value for key, value in config.items() if key != "source_mode"}
    fetch_value = resource_fn(_context(client, fetch_config))
    with pytest.raises(_Sent):
        asyncio.run(_drain(fetch_value))
    assert len(sends) == 1


# -- launchable ⇒ job이 replay config를 받는다 -------------------------------------------------


@pytest.mark.parametrize("operation_key", sorted(SENSOR_LAUNCHABLE_REPLAY_OPERATION_KEYS))
def test_launchable_replay_operations_accept_the_replay_run_config(operation_key: str) -> None:
    job = defs.resolve_job_def(operation_key)
    config = run_config_for_dataset(operation_key, "datagokr_seoul_bookstores")
    assert config is not None
    validate_run_config(job, config)


@pytest.mark.parametrize("operation_key", sorted(SENSOR_LAUNCHABLE_REPLAY_OPERATION_KEYS))
def test_the_replay_config_is_checked_not_merely_tolerated(operation_key: str) -> None:
    """대조군 — schema 없는 resource는 아무 config나 받는다(그러면 위 검증은 항진명제). 값이 틀리면
    거부되어야 ``source_mode``가 실제로 선언된 것이다."""
    from dagster import DagsterInvalidConfigError

    job = defs.resolve_job_def(operation_key)
    config = run_config_for_dataset(operation_key, "datagokr_seoul_bookstores")
    assert config is not None
    for resource in config["resources"].values():
        if "source_mode" in resource["config"]:
            resource["config"]["source_mode"] = "bogus"
    with pytest.raises(DagsterInvalidConfigError):
        validate_run_config(job, config)


# -- provenance -------------------------------------------------------------------------------


async def _bookstore_bundles() -> list[FeatureBundle]:
    convert, rows = _GOLDEN["datagokr_file_data_records"][0]
    return cast(list[FeatureBundle], await convert(rows))


def _stream_with(bundles: Sequence[FeatureBundle], *, hash_of: Callable[[str], str]) -> Any:
    stream = ReplayRecordStream(
        cast(Any, None), provider="p", dataset_key="d", from_raw=lambda raw: raw
    )
    stream.provenance = {
        (b.source_record.source_entity_type, b.source_record.source_entity_id): (
            CurrentSourceRecord(
                source_entity_key="se",
                source_entity_type=b.source_record.source_entity_type,
                source_entity_id=b.source_record.source_entity_id,
                raw_data={},
                raw_payload_hash=hash_of(b.source_record.raw_payload_hash),
                fetched_at=_STORED_FETCHED,
                observed_at=_STORED_OBSERVED,
            )
        )
        for b in bundles
    }
    return stream


async def test_provenance_restores_the_stored_times() -> None:
    bundles = await _bookstore_bundles()
    replayed = apply_replay_provenance(_stream_with(bundles, hash_of=lambda h: h), bundles)
    assert [b.source_record.fetched_at for b in replayed] == [_STORED_FETCHED] * len(bundles)
    assert [b.source_record.imported_at for b in replayed] == [_STORED_OBSERVED] * len(bundles)
    assert [b.feature for b in replayed] == [b.feature for b in bundles]
    # fetch 모드 값은 그대로 지나간다.
    assert apply_replay_provenance(object(), bundles) == bundles


async def test_a_payload_that_differs_from_the_stored_one_fails_before_loading() -> None:
    bundles = await _bookstore_bundles()
    with pytest.raises(ReplayPayloadDrift, match="2건"):
        apply_replay_provenance(_stream_with(bundles, hash_of=lambda h: h[::-1]), bundles)
    with pytest.raises(ReplayPayloadDrift, match="1건"):
        apply_replay_provenance(_stream_with(bundles[:1], hash_of=lambda h: h), bundles)


# -- asset 배선 -------------------------------------------------------------------------------


class _Log:
    def info(self, message: str) -> None:
        del message

    def warning(self, message: str) -> None:
        del message


async def test_standard_asset_reads_before_loading_and_skips_sync_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    convert, records = _GOLDEN["standard_museums"][0]
    fetched = await convert(_fetch_records("standard_museums", records))
    stored = [
        CurrentSourceRecord(
            source_entity_key=f"se_{index}",
            source_entity_type=b.source_record.source_entity_type,
            source_entity_id=b.source_record.source_entity_id,
            raw_data=_jsonb_round_trip(b.source_record.raw_data),
            raw_payload_hash=b.source_record.raw_payload_hash,
            fetched_at=_STORED_FETCHED,
            observed_at=_STORED_OBSERVED,
        )
        for index, b in enumerate(fetched)
    ]
    client = _ReplayClient(stored)
    stream = ReplayRecordStream(
        cast(Any, client),
        provider="data.go.kr-standard",
        dataset_key="datagokr_museums",
        from_raw=resources.REPLAY_FROM_RAW["standard_museums"],
    )
    seen: dict[str, Any] = {}

    async def _fake_load(context: object, **kwargs: Any) -> str:
        seen["reads_before_load"] = len(client.reads)
        seen["record_sync_state"] = kwargs["record_sync_state"]
        seen["bundles"] = [b async for batch in kwargs["batches"] for b in batch]
        return "loaded"

    monkeypatch.setattr(assets, "_load_snapshot_batches", _fake_load)
    context = SimpleNamespace(
        resources=SimpleNamespace(
            standard_museums=stream, fetched_at=_FETCHED, reverse_geocoder=_reverse
        ),
        log=_Log(),
    )

    assert await assets.run_feature_place_standard_museums(cast(Any, context)) == "loaded"
    assert seen["reads_before_load"] == 1
    assert seen["record_sync_state"] is False
    assert {b.source_record.imported_at for b in seen["bundles"]} == {_STORED_OBSERVED}
    def features(bundles: Sequence[FeatureBundle]) -> dict[str, Any]:
        return {
            b.source_record.source_record_key: _content(b.feature.model_dump(mode="json"))
            for b in bundles
        }

    assert features(seen["bundles"]) == features(fetched)


async def test_file_data_asset_in_replay_skips_sync_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    convert, rows = _GOLDEN["datagokr_file_data_records"][0]
    fetched = await convert(_fetch_records("datagokr_file_data_records", rows))
    stored = [
        CurrentSourceRecord(
            source_entity_key=f"se_{index}",
            source_entity_type=b.source_record.source_entity_type,
            source_entity_id=b.source_record.source_entity_id,
            raw_data=_jsonb_round_trip(b.source_record.raw_data),
            raw_payload_hash=b.source_record.raw_payload_hash,
            fetched_at=_STORED_FETCHED,
            observed_at=_STORED_OBSERVED,
        )
        for index, b in enumerate(fetched)
    ]
    stream = ReplayRecordStream(
        cast(Any, _ReplayClient(stored)),
        provider="python-datagokr-api",
        dataset_key="datagokr_seoul_bookstores",
        from_raw=resources.REPLAY_FROM_RAW["datagokr_file_data_records"],
    )
    seen: dict[str, Any] = {}

    async def _fake_load(context: object, **kwargs: Any) -> str:
        seen.update(kwargs)
        return "loaded"

    monkeypatch.setattr(assets, "_load", _fake_load)
    context = SimpleNamespace(
        resources=SimpleNamespace(
            datagokr_file_data_records=stream,
            datagokr_file_data_dataset_key="datagokr_seoul_bookstores",
            fetched_at=_FETCHED,
            reverse_geocoder=_reverse,
        ),
        log=_Log(),
    )

    assert await assets.run_feature_place_datagokr_file_data(cast(Any, context)) == "loaded"
    assert seen["record_sync_state"] is False
    assert {b.source_record.fetched_at for b in seen["bundles"]} == {_STORED_FETCHED}
    assert len(seen["bundles"]) == len(fetched)
