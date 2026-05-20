from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import func, select

from krtour_map.dagster import DagsterEtlExecution, DagsterEtlRun
from krtour_map.db import (
    feature_area_details,
    feature_event_details,
    feature_files,
    feature_place_details,
    features,
    initialize_feature_db,
    source_links,
    source_records,
)
from krtour_map.enums import FeatureKind
from krtour_map.files import DownloadedFile, RustfsFileStore
from krtour_map.heritage import (
    KRHERITAGE_EVENT_DATASET_KEY,
    KRHERITAGE_EVENT_FULL_SCAN_INTERVAL_DAYS,
    KRHERITAGE_HERITAGE_DATASET_KEY,
    KRHERITAGE_HERITAGE_FULL_SCAN_INTERVAL_DAYS,
    KRHERITAGE_PROVIDER,
    KrHeritageFeatureBundle,
    KrHeritageFeatureDbEtlResult,
    KrHeritageFeatureLoadResources,
    collect_krheritage_events,
    collect_krheritage_heritage_features,
    krheritage_event_full_scan_identity,
    krheritage_event_full_scan_job_spec,
    krheritage_event_item_to_feature_bundle,
    krheritage_heritage_full_scan_identity,
    krheritage_heritage_full_scan_job_spec,
    krheritage_heritage_item_to_feature_bundle,
    krheritage_natural_key,
    load_krheritage_events,
    load_krheritage_heritage_features,
    load_krheritage_heritage_result,
)
from krtour_map.models import Coordinate


@dataclass(frozen=True)
class FakeHeritageKey:
    ccba_kdcd: str
    ccba_asno: str
    ccba_ctcd: str


@dataclass(frozen=True)
class FakeHeritageItem:
    key: FakeHeritageKey
    name_ko: str
    raw: dict[str, object]
    coordinate: Coordinate | None = None
    address: str | None = None
    heritage_domain: str | None = None
    heritage_type_name: str | None = None
    image_url: str | None = None
    content: str | None = None
    designated_date: str | None = None
    geometry: dict[str, object] | None = None


@dataclass(frozen=True)
class FakeHeritageEvent:
    sn: str | None
    title: str | None
    raw: dict[str, object]
    coordinate: Coordinate | None = None
    address: str | None = None
    site_name: str | None = None
    main_image: str | None = None
    tel_name: str | None = None


class FakeRustfsClient:
    def __init__(self) -> None:
        self.objects: list[dict[str, object]] = []

    def put_object(self, *, Bucket: str, Key: str, Body: bytes, ContentType: str) -> None:
        self.objects.append(
            {
                "bucket": Bucket,
                "key": Key,
                "body": Body,
                "content_type": ContentType,
            }
        )


class FakeKrHeritageSearchService:
    def __init__(self, items: tuple[FakeHeritageItem, ...]) -> None:
        self.items = items
        self.calls: list[dict[str, object]] = []

    def iter_all_details(self, **kwargs: object) -> tuple[FakeHeritageItem, ...]:
        self.calls.append(kwargs)
        return self.items


class FakeKrHeritageEventService:
    def __init__(self, items: tuple[FakeHeritageEvent, ...]) -> None:
        self.items = items
        self.calls: list[dict[str, object]] = []

    def iter_months(self, **kwargs: object) -> tuple[FakeHeritageEvent, ...]:
        self.calls.append(kwargs)
        return self.items


class FakeKrHeritageClient:
    def __init__(
        self,
        *,
        heritage_items: tuple[FakeHeritageItem, ...] = (),
        event_items: tuple[FakeHeritageEvent, ...] = (),
    ) -> None:
        self.search = FakeKrHeritageSearchService(heritage_items)
        self.event = FakeKrHeritageEventService(event_items)


class FakeKrHeritageClientWithHeritageService:
    def __init__(self, items: tuple[FakeHeritageItem, ...]) -> None:
        self.heritage = FakeKrHeritageSearchService(items)


def _heritage_item(
    *,
    type_code: str = "25",
    natural_no: str = "0000001",
    city_code: str = "11",
    name: str = "Historic Heritage",
    domain: str | None = "cultural",
    geometry: dict[str, object] | None = None,
    image_url: str | None = None,
) -> FakeHeritageItem:
    return FakeHeritageItem(
        key=FakeHeritageKey(type_code, natural_no, city_code),
        name_ko=name,
        coordinate=Coordinate(lat=37.5796, lon=126.9769),
        address="Seoul Jongno",
        heritage_domain=domain,
        heritage_type_name="National Heritage",
        image_url=image_url,
        content="Heritage detail text",
        designated_date="20260101",
        geometry=geometry,
        raw={
            "ccbaKdcd": type_code,
            "ccbaAsno": natural_no,
            "ccbaCtcd": city_code,
            "ccbaMnm1": name,
            "ccbaLcad": "Seoul Jongno",
            "ccbaAsdt": "20260101",
            "imageUrl": image_url,
            "geometry": geometry,
        },
    )


def test_krheritage_natural_key_uses_official_composite_key() -> None:
    item = _heritage_item(type_code="25", natural_no="0000001", city_code="11")

    assert krheritage_natural_key(item) == "25-0000001-11"


def test_krheritage_cultural_heritage_becomes_place_feature() -> None:
    collected_at = datetime(2026, 5, 19, 9, 0, tzinfo=ZoneInfo("Asia/Seoul"))
    bundle = krheritage_heritage_item_to_feature_bundle(
        _heritage_item(image_url="https://cdn.example.com/heritage.jpg"),
        collected_at=collected_at,
    )

    assert isinstance(bundle, KrHeritageFeatureBundle)
    assert bundle.feature.kind == FeatureKind.PLACE
    assert bundle.feature.raw_refs[0].provider == KRHERITAGE_PROVIDER
    assert bundle.source_record.provider == KRHERITAGE_PROVIDER
    assert bundle.source_record.dataset_key == KRHERITAGE_HERITAGE_DATASET_KEY
    assert bundle.source_record.source_entity_id == "25-0000001-11"
    assert bundle.place_detail is not None
    assert bundle.place_detail.place_kind == "heritage"
    assert bundle.area_detail is None
    assert bundle.feature_file_sources[0].source_url == "https://cdn.example.com/heritage.jpg"


def test_krheritage_media_models_become_feature_file_sources() -> None:
    base = _heritage_item(image_url="https://cdn.example.com/heritage.jpg")
    item = replace(
        base,
        raw={
            **base.raw,
            "media_images": [
                {
                    "imageUrl": "https://cdn.example.com/gallery.webp",
                    "description": "gallery",
                    "license": "public",
                }
            ],
            "videos": [
                {
                    "video_url": "https://cdn.example.com/intro.mp4",
                    "title": "intro",
                    "duration_sec": 12,
                }
            ],
            "narrations": [
                {
                    "audio_url": "https://cdn.example.com/narration.mp3",
                    "lang": "ko",
                    "transcript": "설명",
                }
            ],
            "documents": [{"fileUrl": "https://cdn.example.com/booklet.pdf"}],
        },
    )
    bundle = krheritage_heritage_item_to_feature_bundle(item)

    assert isinstance(bundle, KrHeritageFeatureBundle)
    assert [source.file_type for source in bundle.feature_file_sources] == [
        "image",
        "image",
        "video",
        "audio",
        "document",
    ]
    assert bundle.feature_file_sources[2].payload["duration_sec"] == 12
    assert bundle.feature_file_sources[3].payload["transcript"] == "설명"


def test_krheritage_historic_site_with_geometry_becomes_area_feature() -> None:
    geometry = {
        "type": "Polygon",
        "coordinates": [
            [
                [126.97, 37.57],
                [126.98, 37.57],
                [126.98, 37.58],
                [126.97, 37.57],
            ]
        ],
    }
    bundle = krheritage_heritage_item_to_feature_bundle(
        _heritage_item(type_code="27", domain="cultural", geometry=geometry)
    )

    assert isinstance(bundle, KrHeritageFeatureBundle)
    assert bundle.feature.kind == FeatureKind.AREA
    assert bundle.place_detail is None
    assert bundle.area_detail is not None
    assert bundle.area_detail.area_kind == "heritage_area"
    assert bundle.area_detail.boundary_source == "gis_3070426"
    assert bundle.area_detail.geometry == geometry


def test_krheritage_natural_monument_without_boundary_becomes_place_feature() -> None:
    bundle = krheritage_heritage_item_to_feature_bundle(
        _heritage_item(type_code="30", domain="natural", name="Natural Monument")
    )

    assert isinstance(bundle, KrHeritageFeatureBundle)
    assert bundle.feature.kind == FeatureKind.PLACE
    assert bundle.place_detail is not None
    assert bundle.place_detail.place_kind == "natural_heritage"


def test_collect_krheritage_events_maps_event_detail_and_images() -> None:
    event = FakeHeritageEvent(
        sn="EVT-1",
        title="Heritage Performance",
        site_name="Heritage Hall",
        tel_name="02-123-4567",
        coordinate=Coordinate(lat=37.5796, lon=126.9769),
        address="Seoul Jongno",
        main_image="https://cdn.example.com/event.jpg",
        raw={
            "sn": "EVT-1",
            "subTitle": "Heritage Performance",
            "startDate": "20260501",
            "endDate": "20260503",
            "siteName": "Heritage Hall",
            "address": "Seoul Jongno",
            "telName": "02-123-4567",
            "mainImage": "https://cdn.example.com/event.jpg",
        },
    )

    result = collect_krheritage_events((event,))

    assert result.dataset_key == KRHERITAGE_EVENT_DATASET_KEY
    assert result.features[0].kind == FeatureKind.EVENT
    assert result.event_details[0].starts_on == date(2026, 5, 1)
    assert result.event_details[0].ends_on == date(2026, 5, 3)
    assert result.event_details[0].venue_name == "Heritage Hall"
    assert result.feature_file_sources[0].source_url == "https://cdn.example.com/event.jpg"


def test_krheritage_job_specs_match_full_scan_cadence() -> None:
    execution = DagsterEtlExecution(
        logical_datetime=datetime(2026, 5, 19, 0, 0, tzinfo=ZoneInfo("Asia/Seoul")),
        run_type="scheduled",
        op_config={},
    )

    heritage_identity = krheritage_heritage_full_scan_identity(
        None,
        KRHERITAGE_HERITAGE_DATASET_KEY,
        execution,
    )
    event_identity = krheritage_event_full_scan_identity(
        None,
        KRHERITAGE_EVENT_DATASET_KEY,
        execution,
    )

    assert KRHERITAGE_HERITAGE_FULL_SCAN_INTERVAL_DAYS == 7
    assert KRHERITAGE_EVENT_FULL_SCAN_INTERVAL_DAYS == 1
    assert "schedule:weekly" in krheritage_heritage_full_scan_job_spec.tags
    assert "schedule:daily" in krheritage_event_full_scan_job_spec.tags
    assert heritage_identity.run_key == "20260519-heritage-full-scan"
    assert event_identity.run_key == "20260519-event-full-scan"


def test_load_krheritage_heritage_result_writes_area_place_source_and_files() -> None:
    collected_at = datetime(2026, 5, 19, 9, 0, tzinfo=ZoneInfo("Asia/Seoul"))
    geometry = {
        "type": "Polygon",
        "coordinates": [
            [
                [126.97, 37.57],
                [126.98, 37.57],
                [126.98, 37.58],
                [126.97, 37.57],
            ]
        ],
    }
    result = collect_krheritage_heritage_features(
        (
            _heritage_item(
                type_code="25",
                natural_no="0000001",
                image_url="https://cdn.example.com/place.jpg",
            ),
            _heritage_item(
                type_code="27",
                natural_no="0000002",
                geometry=geometry,
                image_url="https://cdn.example.com/area.jpg",
            ),
        ),
        collected_at=collected_at,
    )
    rustfs_client = FakeRustfsClient()
    rustfs_store = RustfsFileStore(
        client=rustfs_client,
        bucket="tripmate-feature-files",
        public_base_url="https://media.example.com",
    )
    context = initialize_feature_db("sqlite+pysqlite:///:memory:")
    try:
        with context.session_factory() as session:
            load_result = load_krheritage_heritage_result(
                session,
                result,
                rustfs_store=rustfs_store,
                file_fetcher=lambda _url: DownloadedFile(
                    data=b"image-bytes",
                    content_type="image/jpeg",
                ),
                collected_at=collected_at,
            )
            session.commit()

        with context.session_factory() as session:
            feature_count = session.scalar(select(func.count()).select_from(features))
            source_record_count = session.scalar(select(func.count()).select_from(source_records))
            source_link_count = session.scalar(select(func.count()).select_from(source_links))
            place_count = session.scalar(select(func.count()).select_from(feature_place_details))
            area_count = session.scalar(select(func.count()).select_from(feature_area_details))
            file_count = session.scalar(select(func.count()).select_from(feature_files))

        assert load_result.features == 2
        assert load_result.source_records == 2
        assert load_result.source_links == 2
        assert load_result.place_details == 1
        assert load_result.area_details == 1
        assert load_result.feature_files == 2
        assert len(rustfs_client.objects) == 2
        assert feature_count == 2
        assert source_record_count == 2
        assert source_link_count == 2
        assert place_count == 1
        assert area_count == 1
        assert file_count == 2
    finally:
        context.dispose()


def test_load_krheritage_heritage_features_loads_when_session_resource_is_provided() -> None:
    collected_at = datetime(2026, 5, 19, 9, 0, tzinfo=ZoneInfo("Asia/Seoul"))
    run = DagsterEtlRun(
        dataset_key=KRHERITAGE_HERITAGE_DATASET_KEY,
        run_key="20260519-heritage-full-scan",
        run_type="scheduled",
        trigger_date=date(2026, 5, 19),
        logical_datetime=collected_at,
        op_config={},
    )
    context = initialize_feature_db("sqlite+pysqlite:///:memory:")
    try:
        with context.session_factory() as session:
            resources = KrHeritageFeatureLoadResources(
                heritage_items=(_heritage_item(type_code="25"),),
                session=session,
            )
            result = load_krheritage_heritage_features(resources, run)
            session.commit()

        with context.session_factory() as session:
            feature_count = session.scalar(select(func.count()).select_from(features))

        assert isinstance(result, KrHeritageFeatureDbEtlResult)
        assert result.load.features == 1
        assert feature_count == 1
    finally:
        context.dispose()


def test_load_krheritage_heritage_features_reads_public_provider_client() -> None:
    collected_at = datetime(2026, 5, 19, 9, 0, tzinfo=ZoneInfo("Asia/Seoul"))
    run = DagsterEtlRun(
        dataset_key=KRHERITAGE_HERITAGE_DATASET_KEY,
        run_key="20260519-heritage-full-scan",
        run_type="scheduled",
        trigger_date=date(2026, 5, 19),
        logical_datetime=collected_at,
        op_config={
            "page_size": 7,
            "max_pages": 2,
            "ccbaKdcd": "25",
            "ccbaCtcd": "11",
        },
    )
    client = FakeKrHeritageClient(heritage_items=(_heritage_item(type_code="25"),))

    result = load_krheritage_heritage_features(
        KrHeritageFeatureLoadResources(client=client),
        run,
    )

    assert result.item_count == 1
    assert client.search.calls == [
        {
            "page_size": 7,
            "max_pages": 2,
            "ccba_kdcd": "25",
            "ccba_ctcd": "11",
        }
    ]


def test_load_krheritage_heritage_features_prefers_public_heritage_service() -> None:
    collected_at = datetime(2026, 5, 19, 9, 0, tzinfo=ZoneInfo("Asia/Seoul"))
    run = DagsterEtlRun(
        dataset_key=KRHERITAGE_HERITAGE_DATASET_KEY,
        run_key="20260519-heritage-full-scan",
        run_type="scheduled",
        trigger_date=date(2026, 5, 19),
        logical_datetime=collected_at,
        op_config={"page_size": 10, "max_pages": 1},
    )
    client = FakeKrHeritageClientWithHeritageService(
        (_heritage_item(type_code="25", natural_no="0000003"),)
    )

    result = load_krheritage_heritage_features(
        KrHeritageFeatureLoadResources(client=client),
        run,
    )

    assert result.item_count == 1
    assert client.heritage.calls == [{"page_size": 10, "max_pages": 1}]


def test_krheritage_provider_models_are_consumed_directly_when_installed() -> None:
    kr_models = pytest.importorskip("krheritage.models")
    HeritageDetail = kr_models.HeritageDetail
    HeritageEvent = kr_models.HeritageEvent

    detail = HeritageDetail.model_validate(
        {
            "key": {"ccbaKdcd": "25", "ccbaAsno": "0000004", "ccbaCtcd": "11"},
            "ccbaMnm1": "Provider Heritage",
            "ccmaName": "국보",
            "ccbaCtcdNm": "서울특별시",
            "ccsiName": "종로구",
            "ccbaLcad": "서울특별시 종로구",
            "ccbaAsdt": "20260101",
            "longitude": 126.9769,
            "latitude": 37.5796,
            "imageUrl": "https://cdn.example.com/provider-heritage.jpg",
            "content": "provider content",
        }
    )
    event = HeritageEvent.model_validate(
        {
            "sn": "EVT-PROVIDER-1",
            "subTitle": "Provider Event",
            "subTitle2": "Night",
            "startDate": "20260501",
            "endDate": "20260503",
            "siteName": "Provider Hall",
            "address": "서울특별시 종로구",
            "mainImage": "https://cdn.example.com/provider-event.jpg",
        }
    )

    feature_bundle = krheritage_heritage_item_to_feature_bundle(detail)
    event_bundle = krheritage_event_item_to_feature_bundle(event)

    assert isinstance(feature_bundle, KrHeritageFeatureBundle)
    assert feature_bundle.feature.name == "Provider Heritage"
    assert feature_bundle.source_record.source_entity_id == "25-0000004-11"
    assert feature_bundle.feature_file_sources[0].source_url.endswith("provider-heritage.jpg")
    assert event_bundle.feature.name == "Provider Event Night"
    assert event_bundle.event_detail.starts_on == date(2026, 5, 1)
    assert event_bundle.feature_file_sources[0].source_url.endswith("provider-event.jpg")


def test_load_krheritage_events_loads_event_rows_with_session_resource() -> None:
    collected_at = datetime(2026, 5, 19, 9, 0, tzinfo=ZoneInfo("Asia/Seoul"))
    run = DagsterEtlRun(
        dataset_key=KRHERITAGE_EVENT_DATASET_KEY,
        run_key="20260519-event-full-scan",
        run_type="scheduled",
        trigger_date=date(2026, 5, 19),
        logical_datetime=collected_at,
        op_config={},
    )
    context = initialize_feature_db("sqlite+pysqlite:///:memory:")
    try:
        with context.session_factory() as session:
            resources = KrHeritageFeatureLoadResources(
                event_items=(
                    FakeHeritageEvent(
                        sn="EVT-2",
                        title="Heritage Lecture",
                        raw={
                            "sn": "EVT-2",
                            "subTitle": "Heritage Lecture",
                            "startDate": "20260601",
                        },
                    ),
                ),
                session=session,
            )
            result = load_krheritage_events(resources, run)
            session.commit()

        with context.session_factory() as session:
            event_count = session.scalar(select(func.count()).select_from(feature_event_details))

        assert isinstance(result, KrHeritageFeatureDbEtlResult)
        assert result.load.features == 1
        assert result.load.event_details == 1
        assert event_count == 1
    finally:
        context.dispose()


def test_load_krheritage_events_reads_public_provider_client() -> None:
    collected_at = datetime(2026, 5, 19, 9, 0, tzinfo=ZoneInfo("Asia/Seoul"))
    run = DagsterEtlRun(
        dataset_key=KRHERITAGE_EVENT_DATASET_KEY,
        run_key="20260519-event-full-scan",
        run_type="scheduled",
        trigger_date=date(2026, 5, 19),
        logical_datetime=collected_at,
        op_config={
            "search_year": 2026,
            "search_month": 5,
            "months_ahead": 3,
        },
    )
    client = FakeKrHeritageClient(
        event_items=(
            FakeHeritageEvent(
                sn="EVT-3",
                title="Provider Event",
                raw={"sn": "EVT-3", "subTitle": "Provider Event"},
            ),
        )
    )

    result = load_krheritage_events(
        KrHeritageFeatureLoadResources(client=client),
        run,
    )

    assert result.item_count == 1
    assert client.event.calls == [
        {"search_year": 2026, "search_month": 5, "months_ahead": 3}
    ]


def test_krheritage_event_item_skips_missing_source_id() -> None:
    result = krheritage_event_item_to_feature_bundle(
        FakeHeritageEvent(
            sn=None,
            title="No ID",
            raw={"subTitle": "No ID"},
        )
    )

    assert result.reason == "missing event source id"
