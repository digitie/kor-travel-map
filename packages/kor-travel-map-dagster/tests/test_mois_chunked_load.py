"""MOIS 재개형 적재 (ADR-108) — chunk commit·재개·지오코딩 선조회·run 크기.

DB는 대역이지만 **commit 의미는 지킨다**: chunk transaction 안에서 예외가 나면 그 chunk의
쓰기는 하나도 남지 않는다. 변환은 실제 ``license_records_to_bundles``를 쓴다 — 재개 키
(payload hash)와 변환 결과가 같은 값이어야 한다는 계약이 그래야 시험된다.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from types import SimpleNamespace
from typing import Any, cast

import pytest
from kortravelmap.client import IntegrityFindingSyncResult
from kortravelmap.dto import Address, Coordinate, FeatureBundle
from kortravelmap.infra.feature_repo import (
    FeatureLoadResult,
    ProviderEntityReobservationConflict,
)
from kortravelmap.providers.mois import (
    PROMOTED_SERVICE_SLUGS,
    license_records_to_bundles,
    license_source_entity_id,
)
from kortravelmap.settings import KorTravelMapSettings

from dagster import DagsterRunStatus, DefaultSensorStatus, RunRequest, SkipReason

from kortravelmap.dagster import mois_chunked_load as chunked
from kortravelmap.dagster.mois_chunked_load import (
    MOIS_LOAD_OUTCOME_BUDGET_EXHAUSTED,
    MOIS_LOAD_OUTCOME_COMPLETE,
    MOIS_LOAD_OUTCOME_TAG,
    MoisLoadPlan,
    iter_slug_chunks,
    load_mois_license_records_chunked,
    mois_load_continuation_decision,
    resolve_mois_load_plan,
)

_FETCHED = datetime(2026, 10, 12, 4, 35, tzinfo=UTC)


@dataclass(frozen=True)
class _Record:
    """``MoisLicensePlaceRecord`` Protocol (mois.db.PlaceRecord 모사)."""

    service_slug: str
    mng_no: str | None = "MNG-0001"
    is_open: bool | None = True
    place_name: str | None = "테스트 사업장"
    category: str | None = None
    title: str | None = None
    opn_authority_code: str | None = None
    status_code: str | None = "01"
    status_name: str | None = "영업/정상"
    detail_status_code: str | None = None
    detail_status_name: str | None = None
    license_date: date | None = None
    telno: str | None = None
    road_address: str | None = None
    lot_address: str | None = None
    road_zip: str | None = None
    lot_zip: str | None = None
    legal_dong_code: str | None = None
    road_name_code: str | None = None
    building_management_number: str | None = None
    lon: float | None = None
    lat: float | None = None
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


def _snapshot(per_slug: int = 7) -> list[_Record]:
    """두 업종, ``(service_slug, mng_no)`` 순 — provider stream과 같은 순서."""
    records: list[_Record] = []
    for slug in ("bakeries", "general_restaurants"):
        for i in range(per_slug):
            records.append(
                _Record(
                    service_slug=slug,
                    mng_no=f"{slug[:3]}-{i:03d}",
                    # 두 건씩 같은 건물 좌표 — 선조회 중복 제거가 보여야 한다.
                    lon=126.97 + (i // 2) / 1000,
                    lat=37.56,
                )
            )
    return records


@dataclass
class _FakeDb:
    """committed 상태만 보이는 MOIS dataset. 값은 ``source_entity_id → raw_payload_hash``."""

    current: dict[str, str] = field(default_factory=dict)
    commits: list[tuple[str, ...]] = field(default_factory=list)
    reobserved: list[tuple[str, ...]] = field(default_factory=list)
    retired: set[str] = field(default_factory=set)
    crash_on_commit: int | None = None
    """N번째(1부터) chunk transaction에서 절반을 쓴 뒤 죽는다."""
    seals: int = 0


class _FakeClient:
    def __init__(self, db: _FakeDb) -> None:
        self.db = db
        self._transactions = 0

    async def find_unchanged_active_source_entities(
        self,
        *,
        provider: str,
        dataset_key: str,
        source_entity_type: str,
        payload_hashes: Mapping[str, str],
    ) -> frozenset[str]:
        del provider, dataset_key, source_entity_type
        return frozenset(
            key
            for key, value in payload_hashes.items()
            if self.db.current.get(key) == value and key not in self.db.retired
        )

    async def load_feature_bundles_reobserving(
        self,
        bundles: Iterable[FeatureBundle],
        *,
        provider: str,
        dataset_key: str,
        source_entity_type: str,
        reobserved_payload_hashes: Mapping[str, str],
        observed_at: datetime,
    ) -> FeatureLoadResult:
        del provider, dataset_key, source_entity_type, observed_at
        self._transactions += 1
        staged = dict(self.db.current)  # transaction-local
        for key, value in reobserved_payload_hashes.items():
            if staged.get(key) != value:
                raise ProviderEntityReobservationConflict(key)
        written: list[str] = []
        materialized = list(bundles)
        for index, bundle in enumerate(materialized):
            if (
                self.db.crash_on_commit == self._transactions
                and index == len(materialized) // 2
            ):
                raise RuntimeError("DB connection lost mid-chunk")
            staged[bundle.source_record.source_entity_id] = bundle.source_record.raw_payload_hash
            written.append(bundle.source_record.source_entity_id)
        inserted = sum(1 for key in written if key not in self.db.current)
        # commit — 여기까지 와야만 보인다.
        self.db.current = staged
        self.db.commits.append(tuple(written))
        self.db.reobserved.append(tuple(sorted(reobserved_payload_hashes)))
        return FeatureLoadResult(
            bundles_total=len(written),
            features_inserted=inserted,
            source_records_inserted=len(written),
        )

    async def load_feature_bundles(
        self,
        bundles: Iterable[FeatureBundle],
        *,
        curation_dataset: tuple[str, str] | None = None,
    ) -> FeatureLoadResult:
        assert not list(bundles), "봉인 transaction은 아무것도 적재하지 않는다"
        assert curation_dataset is not None
        self.db.seals += 1
        return FeatureLoadResult(
            curation_input_member_count=len(self.db.current),
            curation_input_set_hash="seal-hash",
        )

    async def record_address_validation_findings(
        self, findings: Sequence[Any], *, provider: str, dataset_key: str, run_id: str | None
    ) -> IntegrityFindingSyncResult:
        del provider, dataset_key, run_id
        return IntegrityFindingSyncResult(
            observed_count=len(findings),
            unique_count=len(findings),
            upserted_count=len(findings),
        )


class _Geocoder:
    def __init__(self, *, fail_at_lon: float | None = None) -> None:
        self.calls: list[Coordinate] = []
        self._fail_at_lon = fail_at_lon

    async def __call__(self, coord: Coordinate) -> Address:
        self.calls.append(coord)
        if self._fail_at_lon is not None and abs(float(coord.lon) - self._fail_at_lon) < 1e-9:
            raise TimeoutError("kor-travel-geo ReadTimeout")
        return Address(bjd_code="1111010100", sigungu_code="11110", sido_code="11")


class _Context:
    run_id = None
    retry_number = 0

    def __init__(self) -> None:
        self.metadata: dict[str, object] = {}
        self.log = SimpleNamespace(info=lambda *_a, **_k: None, warning=lambda *_a, **_k: None)

    def add_output_metadata(self, metadata: Mapping[str, object]) -> None:
        self.metadata.update(metadata)


def _plan(*, full_coverage: bool = False, budget: int = 14_400) -> MoisLoadPlan:
    return MoisLoadPlan(
        service_slugs=("bakeries", "general_restaurants"),
        full_coverage=full_coverage,
        source_db_path=None,
        geocode_concurrency=2,
        run_budget_seconds=budget,
    )


class _Converted:
    def __init__(self) -> None:
        self.ids: list[str] = []

    async def __call__(self, records: list[Any], **kwargs: Any) -> list[FeatureBundle]:
        self.ids.extend(license_source_entity_id(record) for record in records)
        return await license_records_to_bundles(records, **kwargs)


async def _run(
    records: list[_Record],
    db: _FakeDb,
    *,
    geocoder: _Geocoder,
    converted: _Converted | None = None,
    plan: MoisLoadPlan | None = None,
    clock: Any = None,
) -> chunked.MoisChunkedLoadOutcome:
    kwargs: dict[str, Any] = {}
    if clock is not None:
        kwargs["clock"] = clock
    return await load_mois_license_records_chunked(
        context=cast(Any, _Context()),
        client=cast(Any, _FakeClient(db)),
        records=records,
        plan=plan or _plan(),
        fetched_at=_FETCHED,
        dataset_key="mois_license_features_bulk",
        strict_address="off",
        reverse_geocoder=geocoder,
        convert=converted or _Converted(),
        **kwargs,
    )


@pytest.fixture(autouse=True)
def _small_chunks(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(chunked, "MOIS_LOAD_CHUNK_SIZE", 3)


# -- chunk 경계 ----------------------------------------------------------------


def test_chunks_never_span_a_service_slug() -> None:
    chunks = list(iter_slug_chunks(_snapshot(per_slug=7), 3))

    assert [len(c) for c in chunks] == [3, 3, 1, 3, 3, 1]
    assert all(len({r.service_slug for r in c}) == 1 for c in chunks)


def test_chunk_size_must_be_positive() -> None:
    with pytest.raises(ValueError, match="positive"):
        list(iter_slug_chunks([], 0))


# -- 크래시 → 재개 --------------------------------------------------------------


async def test_crash_mid_chunk_then_rerun_resumes_without_duplicates() -> None:
    """지오코딩이 3번째 chunk 한가운데서 죽는다 → 앞 두 chunk만 남는다 → 재실행이 이어 간다."""
    records = _snapshot(per_slug=7)
    db = _FakeDb()
    # 3번째 chunk(bakeries index 6, 좌표 index 3)에서만 geo가 죽는다.
    failing = _Geocoder(fail_at_lon=126.97 + 3 / 1000)

    with pytest.raises(TimeoutError):
        await _run(records, db, geocoder=failing)

    first_two = {license_source_entity_id(r) for r in records[:6]}
    assert set(db.current) == first_two, "commit된 chunk만, 그리고 그것 전부가 남아야 한다"

    converted = _Converted()
    healthy = _Geocoder()
    outcome = await _run(records, db, geocoder=healthy, converted=converted)

    every = {license_source_entity_id(r) for r in records}
    assert set(db.current) == every
    assert outcome.complete
    # 재실행은 남은 것만 변환했다 — 이미 commit된 6건은 다시 변환·적재하지 않는다.
    assert sorted(converted.ids) == sorted(every - first_two)
    loaded_twice = [
        key for key in every if sum(key in commit for commit in db.commits) > 1
    ]
    assert loaded_twice == []
    assert outcome.records_unchanged == 6


async def test_crash_inside_the_chunk_transaction_leaves_nothing_of_that_chunk() -> None:
    records = _snapshot(per_slug=4)  # bakeries 3+1, restaurants 3+1
    db = _FakeDb(crash_on_commit=2)

    with pytest.raises(RuntimeError, match="mid-chunk"):
        await _run(records, db, geocoder=_Geocoder())

    assert set(db.current) == {license_source_entity_id(r) for r in records[:3]}, (
        "2번째 chunk가 절반 쓰고 죽었는데 그 절반이 보인다 — 반쯤 쓰인 chunk"
    )

    db.crash_on_commit = None
    outcome = await _run(records, db, geocoder=_Geocoder())

    assert set(db.current) == {license_source_entity_id(r) for r in records}
    assert outcome.records_unchanged == 3
    assert outcome.records_converted == len(records) - 3


async def test_changed_payload_is_reloaded_and_unchanged_rows_are_only_reobserved() -> None:
    """다음 원천 snapshot에서 한 행만 바뀌면 그 한 행만 변환·지오코딩한다."""
    records = _snapshot(per_slug=4)
    db = _FakeDb()
    await _run(records, db, geocoder=_Geocoder())

    changed = list(records)
    changed[5] = _Record(
        service_slug=changed[5].service_slug,
        mng_no=changed[5].mng_no,
        place_name="상호 변경",
        lon=127.5,
        lat=37.4,
    )
    geocoder = _Geocoder()
    converted = _Converted()
    outcome = await _run(changed, db, geocoder=geocoder, converted=converted)

    assert converted.ids == [license_source_entity_id(changed[5])]
    assert [float(c.lon) for c in geocoder.calls] == [127.5]
    assert outcome.records_unchanged == len(records) - 1
    reobserved = {key for batch in db.reobserved for key in batch}
    assert license_source_entity_id(changed[5]) not in reobserved


async def test_retired_feature_is_not_skipped() -> None:
    """active가 아닌 feature는 "그대로"가 아니다 — 평소 적재 경로(재활성화 판단)로 보낸다."""
    records = _snapshot(per_slug=2)
    db = _FakeDb()
    await _run(records, db, geocoder=_Geocoder())
    db.retired.add(license_source_entity_id(records[0]))

    converted = _Converted()
    await _run(records, db, geocoder=_Geocoder(), converted=converted)

    assert converted.ids == [license_source_entity_id(records[0])]


# -- 지오코딩 -------------------------------------------------------------------


async def test_identical_coordinates_are_geocoded_once_and_coded_rows_never() -> None:
    records = _snapshot(per_slug=6)  # 업종마다 좌표 3개(두 건씩 공유) — 업종 사이에도 같다
    records.append(
        _Record(
            service_slug="general_restaurants",
            mng_no="zzz-coded",
            lon=128.0,
            lat=35.0,
            legal_dong_code="2611010100",
        )
    )
    geocoder = _Geocoder()

    outcome = await _run(records, _FakeDb(), geocoder=geocoder)

    lons = sorted(round(float(c.lon), 6) for c in geocoder.calls)
    assert lons == [126.97, 126.971, 126.972], "같은 좌표는 run 전체에서 한 번만 조회한다"
    assert outcome.reverse_geocode_live_calls == 3
    assert outcome.reverse_geocode_cache_hits >= len(records) - 1 - 3


# -- run 크기 -------------------------------------------------------------------


class _Clock:
    """호출마다 ``step``초 흐르는 시계."""

    def __init__(self, step: float) -> None:
        self.now = 0.0
        self.step = step

    def __call__(self) -> float:
        value = self.now
        self.now += self.step
        return value


async def test_budget_stops_between_chunks_and_the_next_run_finishes() -> None:
    records = _snapshot(per_slug=7)  # chunk 6개
    db = _FakeDb()

    first = await _run(
        records, db, geocoder=_Geocoder(), plan=_plan(budget=60), clock=_Clock(step=25)
    )

    assert not first.complete
    assert first.outcome == MOIS_LOAD_OUTCOME_BUDGET_EXHAUSTED
    assert 1 <= first.chunks_committed < 6
    assert first.stopped_in_slug in {"bakeries", "general_restaurants"}
    committed = set(db.current)
    assert committed == {
        license_source_entity_id(r) for r in records[: len(committed)]
    }, "멈춘 run은 앞에서부터 연속된 chunk만 남긴다"

    second = await _run(records, db, geocoder=_Geocoder())
    assert second.complete
    assert second.outcome == MOIS_LOAD_OUTCOME_COMPLETE
    assert set(db.current) == {license_source_entity_id(r) for r in records}


async def test_a_run_always_makes_progress_even_if_the_budget_is_already_spent() -> None:
    db = _FakeDb()
    outcome = await _run(
        _snapshot(per_slug=7), db, geocoder=_Geocoder(), plan=_plan(budget=60),
        clock=_Clock(step=10_000),
    )
    assert outcome.chunks_committed == 1
    assert len(db.current) == 3


async def test_only_a_complete_full_coverage_run_seals_the_snapshot() -> None:
    records = _snapshot(per_slug=4)

    partial_db = _FakeDb()
    stopped = await _run(
        records, partial_db, geocoder=_Geocoder(),
        plan=_plan(full_coverage=True, budget=60), clock=_Clock(step=100),
    )
    assert not stopped.authoritative
    assert partial_db.seals == 0
    assert not stopped.result.observation_receipt.authoritative_snapshot_complete

    subset_db = _FakeDb()
    subset = await _run(records, subset_db, geocoder=_Geocoder(), plan=_plan(full_coverage=False))
    assert subset.complete
    assert not subset.authoritative
    assert subset_db.seals == 0

    full_db = _FakeDb()
    full = await _run(records, full_db, geocoder=_Geocoder(), plan=_plan(full_coverage=True))
    assert full.authoritative
    assert full_db.seals == 1
    assert full.result.observation_receipt.authoritative_snapshot_complete
    assert full.result.load.curation_input_set_hash == "seal-hash"


async def test_an_empty_full_coverage_source_is_not_sealed() -> None:
    db = _FakeDb()
    outcome = await _run([], db, geocoder=_Geocoder(), plan=_plan(full_coverage=True))
    assert outcome.complete
    assert not outcome.authoritative
    assert db.seals == 0


def test_plan_defaults_to_every_promoted_slug() -> None:
    plan = resolve_mois_load_plan(KorTravelMapSettings.model_construct(
        mois_source_db_path="/x/mois.db", mois_geocode_concurrency=2,
        mois_load_run_budget_seconds=14_400,
    ))
    assert plan.full_coverage
    assert plan.service_slugs == tuple(sorted(PROMOTED_SERVICE_SLUGS))


def test_plan_selection_is_a_subset_and_unknown_names_are_rejected() -> None:
    settings = KorTravelMapSettings.model_construct(
        mois_source_db_path=None, mois_geocode_concurrency=2,
        mois_load_run_budget_seconds=14_400,
    )
    plan = resolve_mois_load_plan(settings, ["bakeries", " bakeries "])
    assert plan.service_slugs == ("bakeries",)
    assert not plan.full_coverage

    with pytest.raises(ValueError, match="billiard_halls"):
        resolve_mois_load_plan(settings, ["billiard_halls"])
    with pytest.raises(ValueError, match="bakerys"):
        resolve_mois_load_plan(settings, ["bakerys"])


def test_run_sizing_defaults_stay_under_the_run_cap() -> None:
    """기본 상한이 run 상한(6시간)보다 충분히 작고, 동시성은 보수적이다."""
    from kortravelmap.dagster.schedules import FEATURE_LOAD_SCHEDULE_SPECS

    settings = KorTravelMapSettings()
    assert settings.mois_geocode_concurrency == 2
    assert settings.mois_load_run_budget_seconds == 14_400
    run_cap = 21_600
    assert settings.mois_load_run_budget_seconds <= run_cap - 2 * 3600

    field_info = KorTravelMapSettings.model_fields["mois_load_run_budget_seconds"]
    le = next(m.le for m in field_info.metadata if hasattr(m, "le"))
    assert le < run_cap, "상한을 run cap 이상으로 올릴 수 있으면 마지막 chunk가 run을 넘긴다"

    spec = next(s for s in FEATURE_LOAD_SCHEDULE_SPECS if s.job_name == chunked.MOIS_LOAD_JOB_NAME)
    assert spec.coalesce_active_runs


def test_the_asset_retries_once_and_declares_the_plan() -> None:
    from kortravelmap.dagster.assets import FEATURE_LOAD_RETRY_POLICY, feature_place_mois_licenses

    policy = feature_place_mois_licenses.op.retry_policy
    assert policy is not None
    assert policy.max_retries == 1
    assert policy != FEATURE_LOAD_RETRY_POLICY
    assert "mois_load_plan" in feature_place_mois_licenses.required_resource_keys


# -- 이어 달리기 sensor ---------------------------------------------------------


@dataclass
class _Run:
    status: DagsterRunStatus
    tags: dict[str, str] = field(default_factory=dict)
    run_id: str = "run-1"
    run_config: dict[str, object] = field(default_factory=dict)

    @property
    def is_finished(self) -> bool:
        return self.status in {
            DagsterRunStatus.SUCCESS,
            DagsterRunStatus.FAILURE,
            DagsterRunStatus.CANCELED,
        }


def test_continuation_relaunches_a_budget_stopped_run_with_its_config() -> None:
    config = {"resources": {"mois_load_plan": {"config": {"service_slugs": ["bakeries"]}}}}
    decision = mois_load_continuation_decision(
        _Run(
            DagsterRunStatus.SUCCESS,
            {MOIS_LOAD_OUTCOME_TAG: MOIS_LOAD_OUTCOME_BUDGET_EXHAUSTED},
            run_config=config,
        )
    )
    assert isinstance(decision, RunRequest)
    assert decision.run_key == "mois-continue:run-1"
    assert decision.run_config == config
    assert decision.tags["kor_travel_map.trigger_kind"] == "sensor"
    assert decision.tags["kor_travel_map.operation_key"] == chunked.MOIS_LOAD_JOB_NAME


@pytest.mark.parametrize(
    "run",
    [
        None,
        _Run(DagsterRunStatus.STARTED, {MOIS_LOAD_OUTCOME_TAG: MOIS_LOAD_OUTCOME_BUDGET_EXHAUSTED}),
        _Run(DagsterRunStatus.FAILURE, {MOIS_LOAD_OUTCOME_TAG: MOIS_LOAD_OUTCOME_BUDGET_EXHAUSTED}),
        _Run(DagsterRunStatus.SUCCESS, {MOIS_LOAD_OUTCOME_TAG: MOIS_LOAD_OUTCOME_COMPLETE}),
        _Run(DagsterRunStatus.SUCCESS, {}),
    ],
    ids=["no-run", "in-progress", "failed", "complete", "untagged"],
)
def test_continuation_does_not_relaunch_otherwise(run: _Run | None) -> None:
    assert isinstance(mois_load_continuation_decision(run), SkipReason)


def test_continuation_sensor_is_registered_stopped_against_the_job() -> None:
    from kortravelmap.dagster.definitions import defs

    sensor_def = defs.resolve_sensor_def("feature_place_mois_licenses_continuation_sensor")
    assert sensor_def.default_status == DefaultSensorStatus.STOPPED
    assert sensor_def.job_name == chunked.MOIS_LOAD_JOB_NAME


# -- 큐 경로 --------------------------------------------------------------------


async def test_queue_runner_refuses_mois_for_every_scope_type() -> None:
    from kortravelmap.infra.feature_update_executor import ProviderDatasetRefreshScope

    from kortravelmap.dagster.feature_update_runner import FeatureUpdateAssetRunner

    called: list[str] = []

    def _settings() -> KorTravelMapSettings:
        called.append("settings")
        raise AssertionError("MOIS 큐 요청이 resource 구성까지 갔다")

    runner = FeatureUpdateAssetRunner(
        common_resources={},
        log=SimpleNamespace(info=lambda *_a, **_k: None),
        settings_factory=_settings,
    )
    for scope_type, request_scope in (
        (
            "provider_dataset",
            {"type": "provider_dataset", "provider_dataset_id": 1, "sync_scope": "dataset_wide"},
        ),
        (
            "center_radius",
            {"type": "center_radius", "center": {"lon": 127.0, "lat": 37.0}, "radius_km": 1.0},
        ),
    ):
        scope = ProviderDatasetRefreshScope(
            request_id="11111111-1111-4111-8111-111111111111",
            provider_dataset_id=1,
            operation_key=chunked.MOIS_LOAD_JOB_NAME,
            provider="python-mois-api",
            dataset_key="mois_license_features_bulk",
            scope_type=scope_type,
            request_scope=request_scope,
            update_policy={},
            feature_ids=(),
            feature_count=0,
            prevent_provider_reactivation=False,
            sync_scope="dataset_wide",
        )
        result = await runner(cast(Any, None), scope)
        assert result.status == "skipped"
        assert result.metadata["skip_reason"] == "dedicated_job_only"
    assert called == []
