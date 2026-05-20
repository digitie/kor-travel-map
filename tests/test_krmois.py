from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from zoneinfo import ZoneInfo

from sqlalchemy import func, select

from krtour_map.dagster import DagsterEtlExecution
from krtour_map.db import (
    feature_place_details,
    features,
    initialize_feature_db,
    load_feature_rows,
    source_records,
)
from krtour_map.enums import FeatureKind
from krtour_map.krmois import (
    KRMOIS_LICENSE_FEATURE_DATASET_KEY,
    KRMOIS_LICENSE_FULL_UPDATE_INTERVAL_DAYS,
    KRMOIS_PROVIDER,
    collect_krmois_license_features,
    delete_krmois_license_features_for_records,
    krmois_license_feature_full_update_identity,
    krmois_license_feature_full_update_job_spec,
    load_krmois_license_feature_result,
)
from krtour_map.models import Address, Feature, PlaceDetail


@dataclass(frozen=True)
class FakePlaceRecord:
    service_slug: str
    mng_no: str
    place_name: str
    is_open: bool | None = True
    category: str | None = "건강"
    title: str | None = "건강_병원"
    opn_authority_code: str | None = "3000000"
    status_code: str | None = "01"
    status_name: str | None = "영업/정상"
    detail_status_code: str | None = None
    detail_status_name: str | None = None
    license_date: date | None = date(2025, 2, 28)
    license_cancelled_date: date | None = None
    closed_date: date | None = None
    telno: str | None = "02-123-4567"
    road_address: str | None = "서울특별시 종로구 세종대로 209"
    lot_address: str | None = "서울특별시 종로구 세종로 1-91"
    road_zip: str | None = "03171"
    lot_zip: str | None = "03171"
    business_type_name: str | None = None
    subtype_name: str | None = None
    multi_use_business_place_yn: str | None = None
    sanitation_business_status_name: str | None = None
    facility_total_scale: str | None = "1200㎡"
    water_supply_facility_type_name: str | None = None
    culture_sports_business_type_name: str | None = None
    sales_method_name: str | None = None
    designation_date: date | None = None
    building_usage_name: str | None = "의료시설"
    ground_floor_count: int | None = 8
    underground_floor_count: int | None = 2
    total_floor_count: int | None = 10
    facility_area: float | None = 1200.5
    total_area: float | None = 3500.0
    sickbed_count: int | None = 92
    bed_count: int | None = 100
    healthcare_worker_count: int | None = 30
    hospital_room_count: int | None = 20
    medical_institution_type_name: str | None = "병원"
    medical_subject_names: str | None = "내과,정형외과"
    legal_dong_code: str | None = None
    road_name_code: str | None = None
    building_management_number: str | None = None
    road_name_emd_no: str | None = None
    source_x: float | None = 199642.716240024
    source_y: float | None = 452606.614384676
    lon: float | None = 126.9784
    lat: float | None = 37.5666
    data_updated_at: datetime | None = datetime(
        2026,
        5,
        19,
        1,
        0,
        tzinfo=ZoneInfo("Asia/Seoul"),
    )
    source_modified_at: datetime | None = None
    data: dict[str, object] = field(default_factory=dict)
    raw: dict[str, str] = field(default_factory=dict)


def test_collect_krmois_license_features_promotes_open_travel_rows_only() -> None:
    open_hospital = FakePlaceRecord(
        service_slug="hospitals",
        mng_no="PHMA1",
        place_name="포레스트병원",
    )
    closed_hospital = FakePlaceRecord(
        service_slug="hospitals",
        mng_no="PHMA2",
        place_name="닫은병원",
        is_open=False,
        status_code="03",
        status_name="폐업",
    )
    excluded_pc_bang = FakePlaceRecord(
        service_slug="pc_bangs",
        mng_no="PC1",
        place_name="여행자PC",
    )

    result = collect_krmois_license_features(
        (open_hospital, closed_hospital, excluded_pc_bang),
        reverse_geocoder=lambda _coord: {
            "road_address": "서울특별시 종로구 세종대로 209",
            "legal_dong_code": "1111011900",
        },
    )

    assert result.dataset_key == KRMOIS_LICENSE_FEATURE_DATASET_KEY
    assert len(result.features) == 1
    assert result.features[0].detail is not None
    assert result.features[0].detail["selected_source"]["provider"] == KRMOIS_PROVIDER
    assert result.features[0].detail["selected_source"]["mng_no"] == "PHMA1"
    assert result.features[0].detail["selected_coordinate"]["lon"] == 126.9784
    assert result.features[0].detail["category_confidence"] == 90
    assert result.features[0].detail["visible_status"] == "visible"
    assert result.features[0].detail["match_level"] == "coordinate_legal_dong"
    assert result.place_details[0].phones == ["02-123-4567"]
    assert result.place_details[0].facility_info["sickbed_count"] == 92
    assert result.place_details[0].facility_info["medical_subject_names"] == "내과,정형외과"
    assert {item.reason for item in result.skipped_records} == {
        "not open",
        "excluded service_slug",
    }


def test_load_krmois_license_feature_result_prunes_stale_without_source_records() -> None:
    open_hospital = FakePlaceRecord(
        service_slug="hospitals",
        mng_no="PHMA1",
        place_name="포레스트병원",
    )
    collection = collect_krmois_license_features((open_hospital,))
    context = initialize_feature_db("sqlite+pysqlite:///:memory:")
    try:
        with context.session_factory() as session:
            old_feature = Feature(
                feature_id="f_old_krmois",
                kind=FeatureKind.PLACE,
                name="이전 병원",
                category="07010100",
                marker_icon="hospital",
                marker_color="#C53030",
                address=Address(),
                detail={
                    "selected_source": {
                        "provider": KRMOIS_PROVIDER,
                        "service_slug": "hospitals",
                        "mng_no": "OLD",
                    }
                },
            )
            load_feature_rows(
                session,
                feature_items=(old_feature,),
                place_detail_items=(PlaceDetail(feature_id="f_old_krmois"),),
            )
            result = load_krmois_license_feature_result(
                session,
                collection,
                prune_existing=True,
            )
            session.commit()

            feature_count = session.scalar(select(func.count()).select_from(features))
            place_count = session.scalar(select(func.count()).select_from(feature_place_details))
            source_count = session.scalar(select(func.count()).select_from(source_records))
            old_row = session.execute(
                select(features.c.feature_id).where(features.c.feature_id == "f_old_krmois")
            ).first()

        assert result.deleted_features == 1
        assert result.load.features == 1
        assert result.load.source_records == 0
        assert feature_count == 1
        assert place_count == 1
        assert source_count == 0
        assert old_row is None
    finally:
        context.dispose()


def test_delete_krmois_license_features_for_closed_records() -> None:
    open_hospital = FakePlaceRecord(
        service_slug="hospitals",
        mng_no="PHMA1",
        place_name="포레스트병원",
    )
    closed_hospital = FakePlaceRecord(
        service_slug="hospitals",
        mng_no="PHMA1",
        place_name="포레스트병원",
        is_open=False,
        status_code="03",
        status_name="폐업",
    )
    context = initialize_feature_db("sqlite+pysqlite:///:memory:")
    try:
        with context.session_factory() as session:
            collection = collect_krmois_license_features((open_hospital,))
            load_krmois_license_feature_result(session, collection)
            deleted = delete_krmois_license_features_for_records(session, (closed_hospital,))
            session.commit()
            feature_count = session.scalar(select(func.count()).select_from(features))

        assert deleted == 1
        assert feature_count == 0
    finally:
        context.dispose()


def test_krmois_license_feature_job_spec_is_weekly_full_update() -> None:
    execution = DagsterEtlExecution(
        logical_datetime=datetime(2026, 5, 19, 0, 0, tzinfo=ZoneInfo("Asia/Seoul")),
        run_type="scheduled",
        op_config={},
    )
    identity = krmois_license_feature_full_update_identity(
        None,
        KRMOIS_LICENSE_FEATURE_DATASET_KEY,
        execution,
    )

    assert KRMOIS_LICENSE_FULL_UPDATE_INTERVAL_DAYS == 7
    assert krmois_license_feature_full_update_job_spec.dataset_key == (
        KRMOIS_LICENSE_FEATURE_DATASET_KEY
    )
    assert "schedule:weekly" in krmois_license_feature_full_update_job_spec.tags
    assert "closed:delete" in krmois_license_feature_full_update_job_spec.tags
    assert identity.run_key == "20260519-weekly-full-update"
