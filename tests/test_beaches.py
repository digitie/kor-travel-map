from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from zoneinfo import ZoneInfo

from sqlalchemy import func, select

from krtour_map.beaches import (
    KHOA_OCEANS_BEACH_INFO_CATEGORY,
    KHOA_OCEANS_BEACH_INFO_DATASET_KEY,
    KHOA_OCEANS_BEACH_INFO_DEFAULT_PAGE_SIZE,
    KHOA_OCEANS_BEACH_INFO_FULL_SCAN_INTERVAL_DAYS,
    KhoaBeachInfoDbEtlResult,
    collect_khoa_oceans_beach_info,
    khoa_oceans_beach_info_full_scan_identity,
    khoa_oceans_beach_info_full_scan_job_spec,
    load_khoa_oceans_beach_info,
)
from krtour_map.dagster import DagsterEtlExecution, DagsterEtlRun
from krtour_map.db import (
    feature_files,
    feature_place_details,
    features,
    initialize_feature_db,
    source_records,
)
from krtour_map.files import DownloadedFile, RustfsFileStore
from krtour_map.models import Coordinate


@dataclass(frozen=True)
class FakeBeachItem:
    sido_name: str
    gugun_name: str | None
    name: str
    raw: dict[str, object]
    coordinate: Coordinate | None = None
    num: str | None = None
    beach_width_m: float | None = None
    beach_length_m: float | None = None
    beach_kind: str | None = None
    link_url: str | None = None
    link_name: str | None = None
    image_url: str | None = None
    emergency_contact: str | None = None

    @property
    def source_key(self) -> str:
        return "|".join((self.sido_name, self.gugun_name or "", self.name))


@dataclass(frozen=True)
class FakePage:
    items: tuple[FakeBeachItem, ...]
    total_count: int
    page_no: int
    num_of_rows: int
    collected_at: datetime


class FakeKhoaClient:
    def __init__(self, pages: tuple[FakePage, ...]) -> None:
        self.pages = pages
        self.calls: list[dict[str, object]] = []

    def iter_oceans_beach_info_pages(self, **kwargs: object):
        self.calls.append(dict(kwargs))
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


def test_collect_khoa_oceans_beach_info_uses_provider_pagination() -> None:
    collected_at = datetime(2026, 5, 19, 9, 0, tzinfo=ZoneInfo("Asia/Seoul"))
    client = FakeKhoaClient(
        (
            FakePage(
                items=(
                    FakeBeachItem(
                        sido_name="제주",
                        gugun_name="서귀포시",
                        name="신양섭지코지",
                        coordinate=Coordinate(lat=33.434809, lon=126.923021),
                        beach_width_m=80,
                        beach_length_m=300,
                        beach_kind="모래",
                        link_url="https://www.visitjeju.net/",
                        image_url="https://cdn.example.com/beach.jpg",
                        emergency_contact="064-782-2368",
                        raw={"sidoNm": "제주", "gugunNm": "서귀포시", "staNm": "신양섭지코지"},
                    ),
                ),
                total_count=1,
                page_no=1,
                num_of_rows=100,
                collected_at=collected_at,
            ),
        )
    )

    result = collect_khoa_oceans_beach_info(
        client,
        sido_names=("제주",),
        page_size=50,
        reverse_geocoder=lambda _coord: {
            "road_address": "제주 서귀포시 성산읍 섭지코지로 107",
            "legal_dong_code": "5013025924",
        },
    )

    assert client.calls[0]["sido_names"] == ("제주",)
    assert client.calls[0]["num_of_rows"] == 50
    assert result.dataset_key == KHOA_OCEANS_BEACH_INFO_DATASET_KEY
    assert result.scanned_pages == 1
    assert len(result.features) == 1
    assert result.features[0].category == KHOA_OCEANS_BEACH_INFO_CATEGORY
    assert result.features[0].address.legal_dong_code == "5013025924"
    assert result.place_details[0].phones == ["064-782-2368"]
    assert result.place_details[0].facility_info["beach_width_m"] == 80.0
    assert result.source_links[0].source_record_key == result.source_records[0].key()
    assert len(result.feature_file_sources) == 1
    assert result.feature_file_sources[0].source_url == "https://cdn.example.com/beach.jpg"


def test_khoa_oceans_beach_info_job_spec_is_daily_full_scan() -> None:
    execution = DagsterEtlExecution(
        logical_datetime=datetime(2026, 5, 19, 0, 0, tzinfo=ZoneInfo("Asia/Seoul")),
        run_type="scheduled",
        op_config={},
    )
    identity = khoa_oceans_beach_info_full_scan_identity(
        None,
        KHOA_OCEANS_BEACH_INFO_DATASET_KEY,
        execution,
    )

    assert KHOA_OCEANS_BEACH_INFO_FULL_SCAN_INTERVAL_DAYS == 1
    assert khoa_oceans_beach_info_full_scan_job_spec.dataset_key == (
        KHOA_OCEANS_BEACH_INFO_DATASET_KEY
    )
    assert "schedule:daily" in khoa_oceans_beach_info_full_scan_job_spec.tags
    assert "pagination:all-pages" in khoa_oceans_beach_info_full_scan_job_spec.tags
    assert identity.run_key == "20260519-full-scan"


def test_load_khoa_oceans_beach_info_writes_feature_rows_and_files() -> None:
    collected_at = datetime(2026, 5, 19, 9, 0, tzinfo=ZoneInfo("Asia/Seoul"))
    client = FakeKhoaClient(
        (
            FakePage(
                items=(
                    FakeBeachItem(
                        sido_name="부산",
                        gugun_name="해운대구",
                        name="해운대해수욕장",
                        coordinate=Coordinate(lat=35.1587, lon=129.1603),
                        image_url="https://cdn.example.com/haeundae.jpg",
                        raw={"sidoNm": "부산", "gugunNm": "해운대구", "staNm": "해운대해수욕장"},
                    ),
                ),
                total_count=1,
                page_no=1,
                num_of_rows=100,
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
    context = initialize_feature_db("sqlite+pysqlite:///:memory:")
    try:
        with context.session_factory() as session:
            run = DagsterEtlRun(
                dataset_key=KHOA_OCEANS_BEACH_INFO_DATASET_KEY,
                run_key="20260519-full-scan",
                run_type="scheduled",
                trigger_date=date(2026, 5, 19),
                logical_datetime=collected_at,
                op_config={},
            )
            result = load_khoa_oceans_beach_info(
                {
                    "khoa_client": client,
                    "feature_session": session,
                    "rustfs_store": rustfs_store,
                    "file_fetcher": lambda _url: DownloadedFile(
                        data=b"image-bytes",
                        content_type="image/jpeg",
                    ),
                },
                run,
            )
            session.commit()

        assert isinstance(result, KhoaBeachInfoDbEtlResult)
        assert result.load.features == 1
        assert result.load.place_details == 1
        assert result.load.feature_files == 1
        assert rustfs_client.objects[0]["bucket"] == "tripmate-feature-files"

        with context.session_factory() as session:
            feature_count = session.scalar(select(func.count()).select_from(features))
            place_count = session.scalar(select(func.count()).select_from(feature_place_details))
            source_count = session.scalar(select(func.count()).select_from(source_records))
            file_count = session.scalar(select(func.count()).select_from(feature_files))

        assert feature_count == 1
        assert place_count == 1
        assert source_count == 1
        assert file_count == 1
        assert client.calls[0]["num_of_rows"] == KHOA_OCEANS_BEACH_INFO_DEFAULT_PAGE_SIZE
    finally:
        context.dispose()
