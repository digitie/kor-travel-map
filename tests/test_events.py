from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from zoneinfo import ZoneInfo

from sqlalchemy import func, select

from krtour_map.dagster import DagsterEtlExecution, DagsterEtlRun
from krtour_map.db import (
    feature_event_details,
    feature_files,
    features,
    initialize_feature_db,
    source_links,
    source_records,
)
from krtour_map.enums import FeatureKind
from krtour_map.events import (
    VISITKOREA_FESTIVAL_DATASET_KEY,
    VISITKOREA_FESTIVAL_DEFAULT_PAGE_SIZE,
    VISITKOREA_FESTIVAL_FULL_SCAN_INTERVAL_DAYS,
    VISITKOREA_FESTIVAL_FULL_SCAN_START_DATE,
    VisitKoreaFestivalDbEtlResult,
    VisitKoreaFestivalLoadResources,
    collect_visitkorea_festival_events,
    load_visitkorea_festival_events,
    load_visitkorea_festival_result,
    visitkorea_festival_full_scan_identity,
    visitkorea_festival_full_scan_job_spec,
    visitkorea_festival_item_to_feature_bundle,
)
from krtour_map.files import DownloadedFile, RustfsFileStore
from krtour_map.models import Coordinate, FeatureOpeningHours


@dataclass(frozen=True)
class FakeFestivalItem:
    content_id: str | None
    title: str | None
    raw: dict[str, object]
    coordinate: Coordinate | None = None
    addr1: str | None = None
    addr2: str | None = None
    zipcode: str | None = None
    content_type_id: str | None = "15"
    area_code: str | None = "1"
    sigungu_code: str | None = "1"
    cat1: str | None = "A02"
    cat2: str | None = "A0207"
    cat3: str | None = "A02070200"
    first_image: str | None = None
    first_image2: str | None = None
    tel: str | None = None
    opening_hours: FeatureOpeningHours | dict[str, object] | None = None


@dataclass(frozen=True)
class FakePage:
    items: tuple[FakeFestivalItem, ...]
    total_count: int
    page_no: int
    num_of_rows: int
    collected_at: datetime


class FakeVisitKoreaClient:
    def __init__(self, pages: tuple[FakePage, ...]) -> None:
        self.pages = pages
        self.calls: list[dict[str, object]] = []

    def search_festival(self, *_args: object, **_kwargs: object) -> None:
        raise AssertionError("iter_pages should own pagination")

    def iter_pages(self, fetch_page: object, *args: object, **kwargs: object):
        self.calls.append({"fetch_page": fetch_page, "args": args, **kwargs})
        return iter(self.pages)


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


def test_collect_visitkorea_festival_events_uses_provider_pagination() -> None:
    collected_at = datetime(2026, 5, 18, 9, 0, tzinfo=ZoneInfo("Asia/Seoul"))
    client = FakeVisitKoreaClient(
        (
            FakePage(
                items=(
                    FakeFestivalItem(
                        content_id="100",
                        title="봄 축제",
                        coordinate=Coordinate(lat=37.5796, lon=126.9769),
                        addr1="서울 종로구 세종대로 1",
                        first_image="https://cdn.example.com/festival.jpg",
                        first_image2="https://cdn.example.com/festival-thumb.jpg",
                        raw={"contentid": "100", "eventstartdate": "20260501"},
                    ),
                    FakeFestivalItem(
                        content_id="101",
                        title="좌표 없는 축제",
                        raw={"contentid": "101", "eventstartdate": "20260601"},
                    ),
                ),
                total_count=3,
                page_no=1,
                num_of_rows=2,
                collected_at=collected_at,
            ),
            FakePage(
                items=(
                    FakeFestivalItem(
                        content_id="102",
                        title="여름 축제",
                        coordinate=Coordinate(lat=35.1796, lon=129.0756),
                        raw={
                            "contentid": "102",
                            "eventstartdate": "20260701",
                            "eventenddate": "20260707",
                        },
                    ),
                ),
                total_count=3,
                page_no=2,
                num_of_rows=2,
                collected_at=collected_at,
            ),
        )
    )

    result = collect_visitkorea_festival_events(
        client,
        event_start_date=date(2026, 5, 18),
        page_size=2,
    )

    assert client.calls[0]["fetch_page"] == client.search_festival
    assert client.calls[0]["num_of_rows"] == 2
    assert client.calls[0]["max_pages"] is None
    assert result.dataset_key == VISITKOREA_FESTIVAL_DATASET_KEY
    assert result.scanned_pages == 2
    assert len(result.features) == 3
    assert result.features[0].kind == FeatureKind.EVENT
    assert result.features[1].coord is None
    assert result.event_details[2].starts_on == date(2026, 7, 1)
    assert result.event_details[2].ends_on == date(2026, 7, 7)
    assert result.source_links[0].source_record_key == result.source_records[0].key()
    assert len(result.feature_file_sources) == 2
    assert result.feature_file_sources[0].role == "primary"
    assert result.feature_file_sources[1].role == "thumbnail"


def test_visitkorea_festival_job_spec_is_daily_full_scan() -> None:
    execution = DagsterEtlExecution(
        logical_datetime=datetime(2026, 5, 18, 0, 0, tzinfo=ZoneInfo("Asia/Seoul")),
        run_type="scheduled",
        op_config={},
    )
    identity = visitkorea_festival_full_scan_identity(
        None,
        VISITKOREA_FESTIVAL_DATASET_KEY,
        execution,
    )

    assert VISITKOREA_FESTIVAL_FULL_SCAN_INTERVAL_DAYS == 1
    assert visitkorea_festival_full_scan_job_spec.dataset_key == VISITKOREA_FESTIVAL_DATASET_KEY
    assert "schedule:daily" in visitkorea_festival_full_scan_job_spec.tags
    assert identity.run_key == "20260518-full-scan"


def test_collect_visitkorea_festival_events_enriches_address_from_coordinate() -> None:
    collected_at = datetime(2026, 5, 18, 9, 0, tzinfo=ZoneInfo("Asia/Seoul"))
    client = FakeVisitKoreaClient(
        (
            FakePage(
                items=(
                    FakeFestivalItem(
                        content_id="200",
                        title="주소 보강 축제",
                        coordinate=Coordinate(lat=37.5796, lon=126.9769),
                        addr1="서울 종로구 세종대로 1",
                        opening_hours={
                            "periods": [
                                {
                                    "open": {"day": 1, "time": "0900"},
                                    "close": {"day": 1, "time": "1800"},
                                }
                            ]
                        },
                        raw={"contentid": "200", "eventstartdate": "20260501"},
                    ),
                ),
                total_count=1,
                page_no=1,
                num_of_rows=1,
                collected_at=collected_at,
            ),
        )
    )

    result = collect_visitkorea_festival_events(
        client,
        event_start_date=date(2026, 5, 18),
        page_size=1,
        reverse_geocoder=lambda _coord: {
            "road_address": "서울 종로구 세종대로 1",
            "legal_dong_code": "1111011900",
        },
    )

    assert result.features[0].address.legal_dong_code == "1111011900"
    assert result.address_match_reports[0].match_level == "coordinate_legal_dong"
    assert result.address_match_reports[0].confidence == 90
    assert result.event_details[0].opening_hours is not None
    assert result.event_details[0].opening_hours.periods[0].duration_minutes == 540


def test_load_visitkorea_festival_events_defaults_to_uncapped_full_scan() -> None:
    logical_datetime = datetime(2026, 5, 18, 0, 0, tzinfo=ZoneInfo("Asia/Seoul"))
    client = FakeVisitKoreaClient(())
    run = DagsterEtlRun(
        dataset_key=VISITKOREA_FESTIVAL_DATASET_KEY,
        run_key="20260518-full-scan",
        run_type="scheduled",
        trigger_date=date(2026, 5, 18),
        logical_datetime=logical_datetime,
        op_config={},
    )

    result = load_visitkorea_festival_events(client, run)

    assert result.scanned_pages == 0
    assert client.calls[0]["args"] == (VISITKOREA_FESTIVAL_FULL_SCAN_START_DATE,)
    assert client.calls[0]["num_of_rows"] == VISITKOREA_FESTIVAL_DEFAULT_PAGE_SIZE
    assert client.calls[0]["max_pages"] is None


def test_load_visitkorea_festival_result_writes_feature_rows() -> None:
    collected_at = datetime(2026, 5, 18, 9, 0, tzinfo=ZoneInfo("Asia/Seoul"))
    client = FakeVisitKoreaClient(
        (
            FakePage(
                items=(
                    FakeFestivalItem(
                        content_id="300",
                        title="DB 적재 축제",
                        coordinate=Coordinate(lat=37.5796, lon=126.9769),
                        addr1="서울 종로구 세종대로 1",
                        raw={
                            "contentid": "300",
                            "eventstartdate": "20260501",
                            "eventenddate": "20260505",
                        },
                    ),
                ),
                total_count=1,
                page_no=1,
                num_of_rows=1,
                collected_at=collected_at,
            ),
        )
    )
    result = collect_visitkorea_festival_events(
        client,
        event_start_date=date(2026, 5, 18),
        page_size=1,
    )
    context = initialize_feature_db("sqlite+pysqlite:///:memory:")
    try:
        with context.session_factory() as session:
            load_result = load_visitkorea_festival_result(session, result)
            session.commit()

        with context.session_factory() as session:
            feature_count = session.scalar(select(func.count()).select_from(features))
            source_record_count = session.scalar(select(func.count()).select_from(source_records))
            source_link_count = session.scalar(select(func.count()).select_from(source_links))
            event_detail_count = session.scalar(
                select(func.count()).select_from(feature_event_details)
            )

        assert load_result.features == 1
        assert load_result.source_records == 1
        assert load_result.source_links == 1
        assert load_result.event_details == 1
        assert feature_count == 1
        assert source_record_count == 1
        assert source_link_count == 1
        assert event_detail_count == 1
    finally:
        context.dispose()


def test_load_visitkorea_festival_events_loads_when_session_resource_is_provided() -> None:
    collected_at = datetime(2026, 5, 18, 9, 0, tzinfo=ZoneInfo("Asia/Seoul"))
    client = FakeVisitKoreaClient(
        (
            FakePage(
                items=(
                    FakeFestivalItem(
                        content_id="301",
                        title="리소스 적재 축제",
                        raw={"contentid": "301", "eventstartdate": "20260501"},
                    ),
                ),
                total_count=1,
                page_no=1,
                num_of_rows=1,
                collected_at=collected_at,
            ),
        )
    )
    run = DagsterEtlRun(
        dataset_key=VISITKOREA_FESTIVAL_DATASET_KEY,
        run_key="20260518-full-scan",
        run_type="scheduled",
        trigger_date=date(2026, 5, 18),
        logical_datetime=collected_at,
        op_config={},
    )
    context = initialize_feature_db("sqlite+pysqlite:///:memory:")
    try:
        with context.session_factory() as session:
            resources = VisitKoreaFestivalLoadResources(client=client, session=session)
            result = load_visitkorea_festival_events(resources, run)
            session.commit()

        with context.session_factory() as session:
            feature_count = session.scalar(select(func.count()).select_from(features))

        assert isinstance(result, VisitKoreaFestivalDbEtlResult)
        assert result.collection.scanned_pages == 1
        assert result.load.features == 1
        assert feature_count == 1
    finally:
        context.dispose()


def test_load_visitkorea_festival_events_uploads_images_to_rustfs() -> None:
    collected_at = datetime(2026, 5, 18, 9, 0, tzinfo=ZoneInfo("Asia/Seoul"))
    client = FakeVisitKoreaClient(
        (
            FakePage(
                items=(
                    FakeFestivalItem(
                        content_id="302",
                        title="이미지 축제",
                        raw={"contentid": "302", "eventstartdate": "20260501"},
                        first_image="https://cdn.example.com/festival.jpg",
                        first_image2="https://cdn.example.com/festival-thumb.jpg",
                    ),
                ),
                total_count=1,
                page_no=1,
                num_of_rows=1,
                collected_at=collected_at,
            ),
        )
    )
    rustfs_client = FakeRustfsClient()
    rustfs_store = RustfsFileStore(
        client=rustfs_client,
        bucket="tripmate-feature-files",
        public_base_url="https://media.example.com",
    )
    run = DagsterEtlRun(
        dataset_key=VISITKOREA_FESTIVAL_DATASET_KEY,
        run_key="20260518-full-scan",
        run_type="scheduled",
        trigger_date=date(2026, 5, 18),
        logical_datetime=collected_at,
        op_config={},
    )
    context = initialize_feature_db("sqlite+pysqlite:///:memory:")
    try:
        with context.session_factory() as session:
            resources = VisitKoreaFestivalLoadResources(
                client=client,
                session=session,
                rustfs_store=rustfs_store,
                file_fetcher=lambda _url: DownloadedFile(
                    data=b"image-bytes",
                    content_type="image/jpeg",
                ),
            )
            result = load_visitkorea_festival_events(resources, run)
            session.commit()

        with context.session_factory() as session:
            file_count = session.scalar(select(func.count()).select_from(feature_files))

        assert isinstance(result, VisitKoreaFestivalDbEtlResult)
        assert result.load.feature_files == 2
        assert len(rustfs_client.objects) == 2
        assert file_count == 2
    finally:
        context.dispose()


def test_visitkorea_festival_feature_id_is_stable_across_payload_changes() -> None:
    first = visitkorea_festival_item_to_feature_bundle(
        FakeFestivalItem(
            content_id="200",
            title="First Festival Name",
            raw={"contentid": "200", "eventstartdate": "20260501"},
        )
    )
    second = visitkorea_festival_item_to_feature_bundle(
        FakeFestivalItem(
            content_id="200",
            title="Renamed Festival",
            raw={"contentid": "200", "eventstartdate": "20260501", "tel": "02-123-4567"},
        )
    )

    assert isinstance(first, tuple)
    assert isinstance(second, tuple)
    assert first[0].feature_id == second[0].feature_id
    assert first[2].key() != second[2].key()
