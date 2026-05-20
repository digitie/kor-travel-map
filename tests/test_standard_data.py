from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

from sqlalchemy import func, select

from krtour_map.db import (
    feature_event_details,
    feature_place_details,
    feature_route_details,
    features,
    initialize_feature_db,
    source_records,
)
from krtour_map.enums import FeatureKind
from krtour_map.models import ROUTE_TYPE_ACCESSIBLE_WALK, ROUTE_TYPE_TOURISM_ROAD
from krtour_map.standard_data import (
    DATA_GO_KR_STANDARD_PROVIDER,
    STANDARD_CULTURAL_FESTIVALS,
    STANDARD_MUSEUMS,
    STANDARD_PARKING_LOTS,
    STANDARD_TOURISM_ROADS,
    StandardDataClient,
    StandardDataConfig,
    async_collect_and_load_standard_data_features,
    async_collect_standard_data_features,
    collect_standard_data_features,
    load_standard_data_result,
    standard_dataset_spec,
)
from krtour_map.standard_data.client import _parse_json_or_xml, _parse_standard_response


class FakeStandardSession:
    def __init__(self, payloads: tuple[dict[str, object], ...]) -> None:
        self.payloads = list(payloads)
        self.calls: list[dict[str, object]] = []

    async def get(self, url: str, *, params: dict[str, object]) -> dict[str, object]:
        self.calls.append({"url": url, "params": params})
        return self.payloads.pop(0)


def _standard_payload(items: list[dict[str, object]], total_count: int | None = None) -> dict:
    return {
        "response": {
            "body": {
                "items": items,
                "totalCount": total_count if total_count is not None else len(items),
            }
        }
    }


def test_standard_dataset_catalog_contains_bounded_openapi_endpoints() -> None:
    roads = standard_dataset_spec(STANDARD_TOURISM_ROADS)
    museums = standard_dataset_spec(STANDARD_MUSEUMS)
    parking = standard_dataset_spec(STANDARD_PARKING_LOTS)

    assert roads.endpoint_url.endswith("tn_pubr_public_stret_tursm_info_api")
    assert museums.dataset_id == "15017323"
    assert parking.full_scan_interval_days == 180


def test_standard_data_client_matches_datagokr_env_and_xml_shape(monkeypatch) -> None:
    monkeypatch.setenv("DATAGOKR_API_KEY", "env-key")
    raw = _parse_json_or_xml(
        """
        <response>
          <header><resultCode>00</resultCode><resultMsg>NORMAL SERVICE.</resultMsg></header>
          <body>
            <items>
              <item><stretNm>남산길</stretNm><referenceDate>2026-02-09</referenceDate></item>
            </items>
            <totalCount>1</totalCount>
          </body>
        </response>
        """
    )
    items, total_count = _parse_standard_response(raw)

    assert StandardDataConfig.from_env().api_key == "env-key"
    assert total_count == 1
    assert items[0]["stretNm"] == "남산길"


def test_collect_standard_tourism_road_becomes_route_feature() -> None:
    result = collect_standard_data_features(
        STANDARD_TOURISM_ROADS,
        [
            {
                "stretNm": "진해드림로드",
                "stretIntrcn": "숲길 코스",
                "stretLt": "27.4",
                "reqreTime": "11시간 25분",
                "beginSpotNm": "진해 삼밀사 아래",
                "beginLnmadr": "경상남도 창원시 진해구 태백동 52-96",
                "endSpotNm": "기념비",
                "endLatitude": "경상남도 창원시 진해구 남양동 4-18",
                "coursInfo": "시작→쉼터→종점",
                "institutionNm": "창원시청",
                "referenceDate": "2026-02-09",
                "instt_code": "5670000",
            }
        ],
    )

    assert result.features[0].kind == FeatureKind.ROUTE
    assert result.features[0].raw_refs[0].provider == DATA_GO_KR_STANDARD_PROVIDER
    assert result.features[0].detail["route"]["geometry_status"] == "missing_route_geometry"
    assert result.features[0].detail["route"]["type"] == ROUTE_TYPE_TOURISM_ROAD
    assert result.route_details[0].route_type == ROUTE_TYPE_TOURISM_ROAD
    assert result.route_details[0].total_distance_meters == 27400
    assert result.route_details[0].expected_duration_minutes == 685
    assert result.source_records[0].source_version == "2026-02-09"


def test_collect_standard_tourism_road_detects_accessible_walk_route_type() -> None:
    result = collect_standard_data_features(
        STANDARD_TOURISM_ROADS,
        [
            {
                "stretNm": "남산 무장애산책길",
                "stretIntrcn": "휠체어 이용 가능한 무장애 산책로",
                "stretLt": "800m",
                "reqreTime": "40분",
                "beginSpotNm": "입구",
                "beginRdnmadr": "서울특별시 중구",
                "endSpotNm": "전망대",
                "endRdnmadr": "서울특별시 중구",
                "referenceDate": "2026-02-09",
                "instt_code": "6110000",
            }
        ],
    )

    assert result.route_details[0].route_type == ROUTE_TYPE_ACCESSIBLE_WALK
    assert result.route_details[0].total_distance_meters == 800
    assert result.route_details[0].expected_duration_minutes == 40


def test_collect_standard_place_and_event_datasets() -> None:
    museum_result = collect_standard_data_features(
        STANDARD_MUSEUMS,
        [
            {
                "fcltyNm": "대구미술관",
                "fcltyType": "공립 미술관",
                "rdnmadr": "대구광역시 수성구 미술관로 40",
                "latitude": "35.82702862",
                "longitude": "128.6743408",
                "homepageUrl": "https://daeguartmuseum.or.kr",
                "weekdayOperOpenHhmm": "10:00",
                "weekdayOperColseHhmm": "19:00",
                "referenceDate": "2026-03-05",
            }
        ],
    )
    festival_result = collect_standard_data_features(
        STANDARD_CULTURAL_FESTIVALS,
        [
            {
                "fstvlNm": "2026 춘천연극제",
                "opar": "봄내극장",
                "fstvlStartDate": "2026-06-11",
                "fstvlEndDate": "2026-12-26",
                "fstvlCo": "연극제",
                "rdnmadr": "강원특별자치도 춘천시 서부대성로 71",
                "latitude": "37.882374",
                "longitude": "127.731332",
                "homepageUrl": "citf.or.kr",
                "referenceDate": "2026-03-18",
            }
        ],
    )

    assert museum_result.features[0].kind == FeatureKind.PLACE
    assert museum_result.features[0].urls.homepage is not None
    assert museum_result.place_details[0].business_hours is not None
    assert festival_result.features[0].kind == FeatureKind.EVENT
    assert festival_result.event_details[0].starts_on == date(2026, 6, 11)
    assert festival_result.event_details[0].ends_on == date(2026, 12, 26)


async def _collect_from_fake_client() -> tuple[object, FakeStandardSession]:
    session = FakeStandardSession(
        (
            _standard_payload(
                [
                    {
                        "prkplceNo": "258-2-000053",
                        "prkplceNm": "횡성동물병원 인근 공터주차장",
                        "lnmadr": "강원특별자치도 횡성군 횡성읍 읍상리 676-1",
                        "prkcmprt": "4",
                        "parkingchrgeInfo": "무료",
                        "latitude": "37.48723303",
                        "longitude": "127.9854264",
                        "referenceDate": "2026-05-13",
                    }
                ]
            ),
        )
    )
    client = StandardDataClient.aio(api_key="sample-key", session=session)
    result = await async_collect_standard_data_features(
        client,
        STANDARD_PARKING_LOTS,
        page_size=100,
        max_pages=1,
        collected_at=datetime(2026, 5, 20, 9, 0, tzinfo=ZoneInfo("Asia/Seoul")),
    )
    return result, session


def test_async_standard_data_client_collects_pages(anyio_backend_name: str = "asyncio") -> None:
    import asyncio

    result, session = asyncio.run(_collect_from_fake_client())

    assert result.dataset_key == STANDARD_PARKING_LOTS
    assert result.scanned_pages == 1
    assert result.features[0].category.endswith("06010000") or result.features[0].category
    assert session.calls[0]["url"].endswith("tn_pubr_prkplce_info_api")
    assert session.calls[0]["params"]["type"] == "json"


def test_load_standard_data_result_writes_rows() -> None:
    result = collect_standard_data_features(
        STANDARD_TOURISM_ROADS,
        [
            {
                "stretNm": "남산 무장애산책길",
                "stretIntrcn": "휠체어 이용 가능한 무장애 산책로",
                "stretLt": "800m",
                "reqreTime": "40분",
                "beginSpotNm": "입구",
                "beginRdnmadr": "서울특별시 중구",
                "endSpotNm": "전망대",
                "endRdnmadr": "서울특별시 중구",
                "referenceDate": "2026-02-26",
            }
        ],
    )
    context = initialize_feature_db("sqlite+pysqlite:///:memory:")
    try:
        with context.session_factory() as session:
            load = load_standard_data_result(session, result)
            session.commit()

        with context.session_factory() as session:
            feature_count = session.scalar(select(func.count()).select_from(features))
            place_count = session.scalar(select(func.count()).select_from(feature_place_details))
            event_count = session.scalar(select(func.count()).select_from(feature_event_details))
            route_count = session.scalar(select(func.count()).select_from(feature_route_details))
            source_count = session.scalar(select(func.count()).select_from(source_records))

        assert load.features == 1
        assert load.route_details == 1
        assert feature_count == 1
        assert place_count == 0
        assert event_count == 0
        assert route_count == 1
        assert source_count == 1
    finally:
        context.dispose()


def test_async_collect_and_load_standard_data_features() -> None:
    import asyncio

    async def run() -> None:
        session = FakeStandardSession(
            (
                _standard_payload(
                    [
                        {
                            "fstvlNm": "제천청풍호벚꽃축제",
                            "opar": "청풍 문화마을",
                            "fstvlStartDate": "2026-04-04",
                            "fstvlEndDate": "2026-04-19",
                            "latitude": "37.1493417",
                            "longitude": "128.2160865",
                            "referenceDate": "2026-03-23",
                        }
                    ]
                ),
            )
        )
        client = StandardDataClient.aio(api_key="sample-key", session=session)
        context = initialize_feature_db("sqlite+pysqlite:///:memory:")
        try:
            with context.session_factory() as db_session:
                result = await async_collect_and_load_standard_data_features(
                    db_session,
                    client,
                    STANDARD_CULTURAL_FESTIVALS,
                    max_pages=1,
                )
                db_session.commit()
            assert result.load.features == 1
            assert result.load.event_details == 1
        finally:
            context.dispose()

    asyncio.run(run())
