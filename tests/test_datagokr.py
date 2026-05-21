from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from zoneinfo import ZoneInfo

from sqlalchemy import func, select

from krtour_map.dagster import DagsterEtlExecution, DagsterEtlRun
from krtour_map.datagokr import (
    DATAGOKR_AGRI_WEATHER_STATION_DATASET_KEY,
    DATAGOKR_CULTURAL_FESTIVAL_DATASET_KEY,
    DATAGOKR_KWATER_SLUICE_HOUR_DATASET_KEY,
    DATAGOKR_MUSEUM_ART_GALLERY_DATASET_KEY,
    DATAGOKR_PARKING_LOT_DATASET_KEY,
    DATAGOKR_PROVIDER,
    DATAGOKR_TOURIST_ATTRACTION_DATASET_KEY,
    DataGoKrStandardDbEtlResult,
    collect_datagokr_agri_weather_stations,
    collect_datagokr_public_cultural_festivals,
    collect_datagokr_public_museum_art_galleries,
    datagokr_museum_art_gallery_full_scan_job_spec,
    datagokr_standard_full_scan_identity,
    kwater_sluice_record_to_weather_values,
    load_datagokr_standard_features,
)
from krtour_map.db import (
    feature_event_details,
    feature_place_details,
    features,
    initialize_feature_db,
    source_records,
)
from krtour_map.enums import FeatureKind, ForecastStyle, WeatherDomain


@dataclass(frozen=True)
class FakePage:
    items: tuple[object, ...]
    total_count: int = 1
    page_no: int = 1
    num_of_rows: int = 100
    collected_at: datetime = datetime(2026, 5, 20, 9, 0, tzinfo=ZoneInfo("Asia/Seoul"))


class FakeService:
    def __init__(self, pages: tuple[FakePage, ...]) -> None:
        self.pages = pages
        self.calls: list[dict[str, object]] = []

    def iter_pages(self, **kwargs: object) -> tuple[FakePage, ...]:
        self.calls.append(kwargs)
        return self.pages


class FakeAgriWeatherFacade:
    def __init__(self) -> None:
        self.observation_stations = FakeService(
            (
                FakePage(
                    items=(
                        {
                            "Obsr_Spot_Code": "542805A001",
                            "Obsr_Spot_Nm": "구례군 구례읍",
                            "Instl_La": "35.1973055576348",
                            "Instl_Lo": "127.4609219654052",
                            "Instl_Al": "38",
                            "Instl_Adres": "전라남도 구례군 구례읍 동산1길 32",
                            "Obsr_Begin_Datetm": "2016-05-04",
                        },
                    ),
                ),
            )
        )


class FakeDataGoKrClient:
    def __init__(self) -> None:
        self.agri_weather = FakeAgriWeatherFacade()
        self.museum_art = FakeService(
            (
                FakePage(
                    items=(
                        {
                            "fcltyNm": "서울공예박물관",
                            "fcltyType": "공립",
                            "rdnmadr": "서울특별시 종로구 율곡로3길 4",
                            "latitude": "37.5761",
                            "longitude": "126.9836",
                            "operPhoneNumber": "02-6450-7000",
                            "homepageUrl": "https://craftmuseum.seoul.go.kr/",
                            "referenceDate": "2026-05-01",
                        },
                    ),
                ),
            )
        )
        self.parking = FakeService(
            (
                FakePage(
                    items=(
                        {
                            "prkplceNo": "P-1",
                            "prkplceNm": "종로 공영주차장",
                            "rdnmadr": "서울특별시 종로구 세종대로 1",
                            "latitude": "37.5700",
                            "longitude": "126.9760",
                            "prkcmprt": "20",
                            "parkingchrgeInfo": "유료",
                        },
                    ),
                ),
            )
        )
        self.tourist_attraction = FakeService(
            (
                FakePage(
                    items=(
                        {
                            "trrsrtNm": "남산서울타워",
                            "trrsrtSe": "관광지",
                            "rdnmadr": "서울특별시 용산구 남산공원길 105",
                            "latitude": "37.5512",
                            "longitude": "126.9882",
                            "trrsrtIntrcn": "서울 대표 전망 관광지",
                        },
                    ),
                ),
            )
        )
        self.festival = FakeService(
            (
                FakePage(
                    items=(
                        {
                            "fstvlNm": "서울빛축제",
                            "opar": "광화문광장",
                            "fstvlStartDate": "2026-12-01",
                            "fstvlEndDate": "2026-12-31",
                            "fstvlCo": "야간 미디어 축제",
                            "rdnmadr": "서울특별시 종로구 세종대로 172",
                            "latitude": "37.5726",
                            "longitude": "126.9769",
                            "phoneNumber": "02-0000-0000",
                        },
                    ),
                ),
            )
        )


def test_collect_datagokr_museum_maps_place_feature() -> None:
    client = FakeDataGoKrClient()

    result = collect_datagokr_public_museum_art_galleries(
        client,
        page_size=50,
        reverse_geocoder=lambda _coord: {
            "road_address": "서울특별시 종로구 율곡로3길 4",
            "legal_dong_code": "1111014600",
        },
    )

    assert client.museum_art.calls[0]["num_of_rows"] == 50
    assert result.dataset_key == DATAGOKR_MUSEUM_ART_GALLERY_DATASET_KEY
    assert result.scanned_pages == 1
    assert result.features[0].raw_refs[0].provider == DATAGOKR_PROVIDER
    assert result.features[0].kind == FeatureKind.PLACE
    assert result.features[0].address.legal_dong_code == "1111014600"
    assert result.place_details[0].phones == ["02-6450-7000"]
    assert result.source_records[0].raw_name == "서울공예박물관"


def test_collect_datagokr_festival_maps_event_detail() -> None:
    result = collect_datagokr_public_cultural_festivals(FakeDataGoKrClient())

    assert result.dataset_key == DATAGOKR_CULTURAL_FESTIVAL_DATASET_KEY
    assert result.features[0].kind == FeatureKind.EVENT
    assert result.event_details[0].starts_on == date(2026, 12, 1)
    assert result.event_details[0].ends_on == date(2026, 12, 31)
    assert result.event_details[0].venue_name == "광화문광장"


def test_collect_datagokr_agri_weather_station_maps_weather_feature() -> None:
    client = FakeDataGoKrClient()

    result = collect_datagokr_agri_weather_stations(
        client,
        page_size=20,
        reverse_geocoder=lambda _coord: {
            "road_address": "전라남도 구례군 구례읍 동산1길 32",
            "legal_dong_code": "4673025021",
        },
    )

    assert client.agri_weather.observation_stations.calls[0]["num_of_rows"] == 20
    assert result.dataset_key == DATAGOKR_AGRI_WEATHER_STATION_DATASET_KEY
    assert result.features[0].kind == FeatureKind.WEATHER
    assert result.features[0].category == "agri_weather_station"
    assert result.features[0].coord is not None
    assert result.features[0].coord.latitude == 35.1973055576348
    assert result.features[0].address.legal_dong_code == "4673025021"
    assert result.source_records[0].source_entity_id == "542805A001"


def test_kwater_sluice_record_maps_hydro_weather_values() -> None:
    values = kwater_sluice_record_to_weather_values(
        "feature_dam_1",
        {
            "damcode": "2022510",
            "obsrdt": "10-01 01시",
            "lowlevel": "0.74",
            "rf": "0.000",
            "inflowqy": "236.038",
            "totdcwtrqy": "108.649",
            "rsvwtqy": "296.377",
            "rsvwtrt": "96.5",
        },
        observed_year=2018,
    )

    by_metric = {value.metric_key: value for value in values}

    assert len(values) == 6
    assert by_metric["dam_water_level"].provider == DATAGOKR_PROVIDER
    assert by_metric["dam_water_level"].weather_domain == WeatherDomain.HYDRO_WEATHER
    assert by_metric["dam_water_level"].forecast_style == ForecastStyle.OBSERVED
    assert by_metric["dam_water_level"].observed_at is not None
    assert by_metric["dam_water_level"].observed_at.isoformat() == "2018-10-01T01:00:00"
    assert by_metric["dam_water_level"].value_number is not None
    assert str(by_metric["dam_water_level"].value_number) == "0.74"
    assert by_metric["reservoir_rate"].payload["dataset_key"] == (
        DATAGOKR_KWATER_SLUICE_HOUR_DATASET_KEY
    )


def test_datagokr_job_spec_identity_and_dataset_tags() -> None:
    execution = DagsterEtlExecution(
        logical_datetime=datetime(2026, 5, 20, 0, 0, tzinfo=ZoneInfo("Asia/Seoul")),
        run_type="scheduled",
        op_config={},
    )
    identity = datagokr_standard_full_scan_identity(
        None,
        DATAGOKR_MUSEUM_ART_GALLERY_DATASET_KEY,
        execution,
    )

    assert identity.run_key == "20260520-full-scan"
    assert datagokr_museum_art_gallery_full_scan_job_spec.dataset_key == (
        DATAGOKR_MUSEUM_ART_GALLERY_DATASET_KEY
    )
    assert "data_go_kr:15017323" in datagokr_museum_art_gallery_full_scan_job_spec.tags


def test_load_datagokr_standard_features_writes_place_and_event_rows() -> None:
    client = FakeDataGoKrClient()
    context = initialize_feature_db("sqlite+pysqlite:///:memory:")
    try:
        with context.session_factory() as session:
            place_run = DagsterEtlRun(
                dataset_key=DATAGOKR_PARKING_LOT_DATASET_KEY,
                run_key="20260520-full-scan",
                run_type="scheduled",
                trigger_date=date(2026, 5, 20),
                logical_datetime=datetime(2026, 5, 20, 9, 0, tzinfo=ZoneInfo("Asia/Seoul")),
                op_config={"page_size": 10},
            )
            place_result = load_datagokr_standard_features(
                {"datagokr_client": client, "feature_session": session},
                place_run,
            )
            event_run = DagsterEtlRun(
                dataset_key=DATAGOKR_CULTURAL_FESTIVAL_DATASET_KEY,
                run_key="20260520-full-scan",
                run_type="scheduled",
                trigger_date=date(2026, 5, 20),
                logical_datetime=datetime(2026, 5, 20, 9, 0, tzinfo=ZoneInfo("Asia/Seoul")),
                op_config={},
            )
            event_result = load_datagokr_standard_features(
                {"datagokr_client": client, "feature_session": session},
                event_run,
            )
            session.commit()

        assert isinstance(place_result, DataGoKrStandardDbEtlResult)
        assert isinstance(event_result, DataGoKrStandardDbEtlResult)
        assert place_result.load.features == 1
        assert event_result.load.event_details == 1

        with context.session_factory() as session:
            feature_count = session.scalar(select(func.count()).select_from(features))
            source_count = session.scalar(select(func.count()).select_from(source_records))
            place_count = session.scalar(select(func.count()).select_from(feature_place_details))
            event_count = session.scalar(select(func.count()).select_from(feature_event_details))

        assert feature_count == 2
        assert source_count == 2
        assert place_count == 1
        assert event_count == 1
    finally:
        context.dispose()


def test_all_requested_dataset_keys_are_available() -> None:
    assert {
        DATAGOKR_MUSEUM_ART_GALLERY_DATASET_KEY,
        DATAGOKR_PARKING_LOT_DATASET_KEY,
        DATAGOKR_TOURIST_ATTRACTION_DATASET_KEY,
        DATAGOKR_CULTURAL_FESTIVAL_DATASET_KEY,
        DATAGOKR_AGRI_WEATHER_STATION_DATASET_KEY,
        DATAGOKR_KWATER_SLUICE_HOUR_DATASET_KEY,
    }
