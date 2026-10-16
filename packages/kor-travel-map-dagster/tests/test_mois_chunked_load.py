"""MOIS 재개형 적재 (ADR-108) — chunk commit·재개·지오코딩 선조회·run 크기.

DB는 대역이지만 **commit 의미는 지킨다**: chunk transaction 안에서 예외가 나면 그 chunk의
쓰기는 하나도 남지 않는다. 변환은 실제 ``license_records_to_bundles``를 쓴다 — 재개 키
(payload hash)와 변환 결과가 같은 값이어야 한다는 계약이 그래야 시험된다.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime
from types import SimpleNamespace
from typing import Any, Final, cast

import pytest
from dagster import DagsterRunStatus, DefaultSensorStatus, Failure, RunRequest, SkipReason
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

pytestmark = [
    # Definitions를 로드하는 검사가 있다 — sensor `owners`의 BetaWarning을 루트 설정
    # (경고=오류)에서도 무시한다. tests/lint의 run completion gate 검사와 같은 필터다.
    pytest.mark.filterwarnings(
        "ignore:Parameter `owners` of initializer `SensorDefinition.__init__`"
        ".*:dagster_shared.utils.warnings.BetaWarning"
    ),
]

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
    conflicts: int = 0
    """다음 N개 chunk transaction을 "확인 뒤 entity가 바뀌었다"로 되돌린다."""
    markers: dict[str, tuple[str, float]] = field(default_factory=dict)
    """역지오코딩 불가 표식: dedupe key → (payload.source_record_key, 마지막 관측 일)."""
    today: float = 0.0
    """표식 나이를 재는 DB 시계(일)."""
    resolved: list[str] = field(default_factory=list)
    marker_write_error: Exception | None = None
    resolve_error: Exception | None = None
    tokens_seen: list[tuple[str, str | None]] = field(default_factory=list)
    """토큰 조건을 받는 세 자리가 받은 토큰: ("unchanged"|"marker"|"load", token)."""


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
        current_data_token: str | None = None,
    ) -> frozenset[str]:
        del provider, dataset_key, source_entity_type
        self.db.tokens_seen.append(("unchanged", current_data_token))
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
        geo: Any = None,
    ) -> FeatureLoadResult:
        del provider, dataset_key, source_entity_type, observed_at
        self.db.tokens_seen.append(("load", geo.effective_token() if geo is not None else None))
        self._transactions += 1
        if self.db.conflicts > 0:
            self.db.conflicts -= 1
            raise ProviderEntityReobservationConflict("dedup moved an entity mid-chunk")
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
        geo: Any = None,
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
        if self.db.marker_write_error is not None and any(
            f.violation_type == chunked.UNRESOLVABLE_MARKER_TYPE for f in findings
        ):
            raise self.db.marker_write_error
        for finding in findings:
            if finding.violation_type == chunked.UNRESOLVABLE_MARKER_TYPE:
                self.db.markers[finding.dedupe_key] = (
                    str(finding.payload["source_record_key"]),
                    self.db.today,
                )
        return IntegrityFindingSyncResult(
            observed_count=len(findings),
            unique_count=len(findings),
            upserted_count=len(findings),
        )


    async def resolve_open_findings_by_key(
        self, *, violation_type: str, dedupe_keys: Sequence[str], reason: str
    ) -> int:
        del reason
        assert violation_type == chunked.UNRESOLVABLE_MARKER_TYPE
        if self.db.resolve_error is not None:
            raise self.db.resolve_error
        closed = [key for key in dedupe_keys if self.db.markers.pop(key, None) is not None]
        self.db.resolved.extend(closed)
        return len(closed)

    async def find_fresh_open_findings(
        self,
        *,
        violation_type: str,
        expected_source_record_keys: Mapping[str, str],
        max_age_days: int,
        expected_payload_fields: Mapping[str, str] | None = None,
    ) -> frozenset[str]:
        assert violation_type == chunked.UNRESOLVABLE_MARKER_TYPE
        self.db.tokens_seen.append(
            ("marker", (expected_payload_fields or {}).get("geo_data_token"))
        )
        return frozenset(
            key
            for key, expected in expected_source_record_keys.items()
            if key in self.db.markers
            and self.db.markers[key][0] == expected
            and self.db.today - self.db.markers[key][1] < max_age_days
        )


class _Geocoder:
    def __init__(
        self,
        *,
        fail_at_lon: float | None = None,
        empty_at_lon: float | None = None,
        always_empty: bool = False,
    ) -> None:
        self.calls: list[Coordinate] = []
        self._fail_at_lon = fail_at_lon
        self._empty_at_lon = empty_at_lon
        self._always_empty = always_empty

    async def __call__(self, coord: Coordinate) -> Address:
        self.calls.append(coord)
        lon = float(coord.lon)
        if self._fail_at_lon is not None and abs(lon - self._fail_at_lon) < 1e-9:
            raise TimeoutError("kor-travel-geo ReadTimeout")
        if self._always_empty or (
            self._empty_at_lon is not None and abs(lon - self._empty_at_lon) < 1e-9
        ):
            return Address()  # geo가 답은 했지만 법정동코드가 없다
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
    strict_address: str = "off",
    context: Any = None,
    current_dataset: Any = None,
) -> chunked.MoisChunkedLoadOutcome:
    kwargs: dict[str, Any] = {}
    if clock is not None:
        kwargs["clock"] = clock
    if current_dataset is not None:
        kwargs["current_dataset"] = current_dataset
    return await load_mois_license_records_chunked(
        context=cast(Any, context or _Context()),
        client=cast(Any, _FakeClient(db)),
        records=records,
        plan=plan or _plan(),
        fetched_at=_FETCHED,
        dataset_key="mois_license_features_bulk",
        strict_address=strict_address,
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


# -- 소실 하한·geo 장애 (적대 리뷰 MED-1) ------------------------------------------


def _slug_records(slug: str, count: int, **overrides: Any) -> list[_Record]:
    return [
        _Record(service_slug=slug, mng_no=f"{slug[:3]}-{i:04d}", **overrides)
        for i in range(count)
    ]


async def test_one_geocode_miss_in_a_tail_chunk_drops_that_row_and_the_run_completes() -> None:
    """꼬리 chunk(1행)의 역지오코딩 실패 한 건이 run을 멈추면 이어 달리기가 영구히 막힌다."""
    records = [
        _Record(service_slug="yacht_marinas", mng_no=f"y-{i}", lon=126.97 + i / 1000, lat=37.56)
        for i in range(4)  # chunk 3 + 꼬리 1
    ]
    db = _FakeDb()

    outcome = await _run(
        records, db, geocoder=_Geocoder(empty_at_lon=126.973), strict_address="drop"
    )

    assert outcome.complete
    assert outcome.dropped_count == 1
    assert set(db.current) == {license_source_entity_id(r) for r in records[:3]}


async def test_geo_returning_empty_answers_is_an_upstream_outage_not_a_data_loss(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """geo가 빈 답만 내면 행을 버리며 진행하지 않는다 — chunk를 적재하기 전에 멈춘다."""
    monkeypatch.setattr(chunked, "MOIS_LOAD_CHUNK_SIZE", 30)
    records = [
        _Record(service_slug="bakeries", mng_no=f"b-{i:03d}", lon=126.9 + i / 1000, lat=37.5)
        for i in range(25)
    ]
    db = _FakeDb()

    with pytest.raises(Failure, match="upstream"):
        await _run(records, db, geocoder=_Geocoder(always_empty=True), strict_address="drop")

    assert db.commits == [], "장애 판정 전에 행을 버린 chunk를 commit했다"


async def test_data_invalid_drops_fail_the_slug_only_past_the_minimum_sample() -> None:
    no_location = {"lon": None, "lat": None, "road_address": None, "lot_address": None}
    small = _slug_records("yacht_marinas", 10, **no_location)
    outcome = await _run(small, _FakeDb(), geocoder=_Geocoder(), strict_address="drop")
    assert outcome.complete, "작은 업종은 표본이 모자라 판정하지 않는다(행 단위 finding만)"
    assert outcome.dropped_count == 10

    large = _slug_records("bakeries", chunked.LOSS_GUARD_MIN_SAMPLE + 10, **no_location)
    db = _FakeDb()
    with pytest.raises(Failure, match="bakeries"):
        await _run(large, db, geocoder=_Geocoder(), strict_address="drop")
    assert db.commits, "표본이 모이기 전 chunk는 정상적으로 commit된다"


def test_geocode_drops_are_counted_apart_from_data_invalid_drops() -> None:
    import asyncio

    bundles = asyncio.run(
        license_records_to_bundles(
            [
                _Record(service_slug="bakeries", mng_no="g", lon=126.9, lat=37.5),
                _Record(service_slug="bakeries", mng_no="m", lon=None, lat=None),
            ],
            fetched_at=_FETCHED,
            dataset_key="mois_license_features_bulk",
            reverse_geocoder=_Geocoder(always_empty=True),
        )
    )
    geocode, invalid = chunked._classify_drops(bundles, mode="drop")  # noqa: SLF001
    assert (len(geocode), invalid) == (1, 1)
    # 빈 답 행은 모드와 무관하게 센다(off 모드도 적재하지 않는다). 데이터 무효는 drop에서만 버린다.
    geocode, invalid = chunked._classify_drops(bundles, mode="off")  # noqa: SLF001
    assert (len(geocode), invalid) == (1, 0)


# -- 재관측 충돌 (적대 리뷰 MED-2) ------------------------------------------------


async def test_reobservation_conflict_redoes_only_that_chunk_in_process() -> None:
    records = _snapshot(per_slug=4)
    db = _FakeDb()
    await _run(records, db, geocoder=_Geocoder())

    db.conflicts = chunked.REOBSERVATION_CONFLICT_RETRIES
    outcome = await _run(records, db, geocoder=_Geocoder())

    assert outcome.complete
    assert set(db.current) == {license_source_entity_id(r) for r in records}
    assert outcome.chunks_committed == 4


async def test_persistent_reobservation_conflict_still_fails_after_bounded_retries() -> None:
    db = _FakeDb(conflicts=chunked.REOBSERVATION_CONFLICT_RETRIES + 1)

    with pytest.raises(ProviderEntityReobservationConflict):
        await _run(_snapshot(per_slug=4), db, geocoder=_Geocoder())
    assert db.commits == []


# -- run 시계 (적대 리뷰 MED-3) ----------------------------------------------------


class _RunContext(_Context):
    """실제 run처럼 run 시작 시각과 run 상한 tag를 갖는 context."""

    def __init__(self, *, started_at: float, max_runtime: int) -> None:
        super().__init__()
        self.run_id = "run-1"
        self.run = SimpleNamespace(tags={"dagster/max_runtime": str(max_runtime)})
        self.instance = SimpleNamespace(
            get_run_record_by_id=lambda _run_id: SimpleNamespace(start_time=started_at),
            add_run_tags=lambda *_a, **_k: None,
        )


async def test_budget_is_measured_from_run_start_not_step_start() -> None:
    """Phase A sync(resource init)와 step 재시도가 쓴 시간은 상한에서 빠진다."""
    now = 1_000_000.0
    clock = _Clock(step=10)
    clock.now = now
    context = _RunContext(started_at=now - 14_390, max_runtime=21_600)

    outcome = await _run(
        _snapshot(per_slug=7), _FakeDb(), geocoder=_Geocoder(), clock=clock, context=context
    )

    assert not outcome.complete
    assert outcome.chunks_committed == 1


def test_effective_budget_is_capped_by_the_run_max_runtime_minus_margin() -> None:
    margin = chunked.RUN_FINAL_MARGIN_SECONDS
    assert chunked.effective_run_budget_seconds(14_400, None) == 14_400
    assert chunked.effective_run_budget_seconds(14_400, 21_600) == 14_400
    assert chunked.effective_run_budget_seconds(19_800, 21_600) == 21_600 - margin
    assert chunked.effective_run_budget_seconds(19_800, 7_200) == 7_200 - margin


def test_settings_budget_ceiling_is_derived_from_the_job_run_cap() -> None:
    """settings 최대값 = 이 job의 run 상한 tag - 여유. 둘이 갈라지면 여기서 빨개진다."""
    from kortravelmap.dagster.definitions import defs

    job = defs.resolve_job_def(chunked.MOIS_LOAD_JOB_NAME)
    run_cap = int(job.tags["dagster/max_runtime"])
    field_info = KorTravelMapSettings.model_fields["mois_load_run_budget_seconds"]
    le = next(m.le for m in field_info.metadata if hasattr(m, "le"))
    assert le == run_cap - chunked.RUN_FINAL_MARGIN_SECONDS


# -- 이어 달리기 sensor LOW ---------------------------------------------------------


def _zero_progress_run(*, budget: int, available: int) -> _Run:
    return _Run(
        DagsterRunStatus.SUCCESS,
        {
            MOIS_LOAD_OUTCOME_TAG: MOIS_LOAD_OUTCOME_BUDGET_EXHAUSTED,
            chunked.MOIS_LOAD_CONVERTED_TAG: "0",
            chunked.MOIS_LOAD_BUDGET_TAG: str(budget),
            chunked.MOIS_LOAD_AVAILABLE_TAG: str(available),
        },
    )


def test_continuation_stops_when_a_full_budget_run_made_no_progress() -> None:
    decision = mois_load_continuation_decision(
        _zero_progress_run(budget=14_400, available=14_000)
    )
    assert isinstance(decision, SkipReason)


@pytest.mark.parametrize(
    "tags",
    [
        {chunked.MOIS_LOAD_BUDGET_TAG: "14400", chunked.MOIS_LOAD_AVAILABLE_TAG: "0"},
        {},
        {chunked.MOIS_LOAD_BUDGET_TAG: "x", chunked.MOIS_LOAD_AVAILABLE_TAG: "y"},
    ],
    ids=["retry-started-past-deadline", "untagged", "garbled"],
)
def test_continuation_relaunches_a_zero_progress_run_that_never_had_its_budget(
    tags: dict[str, str],
) -> None:
    """늦은 실패 뒤 step 재시도는 run 시작 기준 상한을 넘겨 한 chunk(미변경)만 하고 멈춘다 —
    그것을 "전진할 수 없다"로 보면 다음 월간 tick까지 정체된다(적대 리뷰 MED-1)."""
    run = _Run(
        DagsterRunStatus.SUCCESS,
        {
            MOIS_LOAD_OUTCOME_TAG: MOIS_LOAD_OUTCOME_BUDGET_EXHAUSTED,
            chunked.MOIS_LOAD_CONVERTED_TAG: "0",
            **tags,
        },
    )
    assert isinstance(mois_load_continuation_decision(run), RunRequest)


def test_continuation_sensor_waits_while_any_mois_run_is_active() -> None:
    from dagster import build_sensor_context

    budget_stopped = _Run(
        DagsterRunStatus.SUCCESS,
        {MOIS_LOAD_OUTCOME_TAG: MOIS_LOAD_OUTCOME_BUDGET_EXHAUSTED},
    )
    queued = _Run(DagsterRunStatus.QUEUED, run_id="run-2")

    class _Instance:
        def get_runs(self, *, filters: Any, limit: int) -> list[_Run]:
            del limit
            return [queued] if filters.statuses else [budget_stopped]

    from kortravelmap.dagster.mois_chunked_load import mois_load_continuation_sensor

    context = build_sensor_context()
    object.__setattr__(context, "_instance", _Instance())
    result = mois_load_continuation_sensor._raw_fn(context)  # noqa: SLF001
    assert isinstance(result, SkipReason)


# -- HIGH-1: 재개 run에서 빈 답이 정상인 좌표가 조회를 지배해도 막히지 않는다 ------------


async def test_outage_is_still_detected_when_the_probe_also_comes_back_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(chunked, "MOIS_LOAD_CHUNK_SIZE", 30)
    records = [
        _Record(service_slug="bakeries", mng_no=f"b-{i:03d}", lon=126.9 + i / 1000, lat=37.5)
        for i in range(25)
    ]
    geocoder = _Geocoder(always_empty=True)
    db = _FakeDb()

    with pytest.raises(Failure, match="probe"):
        await _run(records, db, geocoder=geocoder, strict_address="drop")
    assert db.commits == []


# -- LOW-d: run 시작 시각이 쓸 수 없는 값이면 step 시계로 물러난다 -----------------


@pytest.mark.parametrize(
    "start_time", [None, "1700000000", float("nan"), float("inf"), -5.0, 0, True, 9e18]
)
def test_run_clock_start_ignores_unusable_start_times(start_time: object) -> None:
    context = SimpleNamespace(
        run_id="run-1",
        instance=SimpleNamespace(
            get_run_record_by_id=lambda _run_id: SimpleNamespace(start_time=start_time)
        ),
    )
    assert chunked._run_clock_start(context, 1_000.0) == 1_000.0  # noqa: SLF001


def test_run_clock_start_uses_a_sane_run_start() -> None:
    context = SimpleNamespace(
        run_id="run-1",
        instance=SimpleNamespace(
            get_run_record_by_id=lambda _run_id: SimpleNamespace(start_time=400.0)
        ),
    )
    assert chunked._run_clock_start(context, 1_000.0) == 400.0  # noqa: SLF001


# -- 최종 델타 리뷰 MED-1: 지역 장애는 조용한 손실이 아니라 degraded run이다 -------------


def _province_records(count: int, *, empty_province: bool) -> list[_Record]:
    """mng_no가 발급 지자체 순이라 한 시·도의 행이 연속으로 온다."""
    good = [
        _Record(service_slug="bakeries", mng_no=f"a-{i:04d}", lon=126.9 + i / 10_000, lat=37.5)
        for i in range(count)
    ]
    bad = [
        _Record(service_slug="bakeries", mng_no=f"b-{i:04d}", lon=128.5 + i / 10_000, lat=35.8)
        for i in range(count if empty_province else 0)
    ]
    return good + bad


class _ProvinceLayerEmpty(_Geocoder):
    """경도 128.4 이상(한 시·도)의 layer만 비었다. 기준점·다른 지역은 답한다."""

    async def __call__(self, coord: Coordinate) -> Address:
        self.calls.append(coord)
        if float(coord.lon) >= 128.4:
            return Address()
        return Address(bjd_code="1111010100", sigungu_code="11110", sido_code="11")


@pytest.mark.parametrize("mode", ["drop", "off"])
async def test_regional_outage_completes_but_is_degraded_not_sealed(
    monkeypatch: pytest.MonkeyPatch, mode: str
) -> None:
    monkeypatch.setattr(chunked, "MOIS_LOAD_CHUNK_SIZE", 50)
    records = _province_records(150, empty_province=True)
    db = _FakeDb()
    context = _Context()

    outcome = await _run(
        records,
        db,
        geocoder=_ProvinceLayerEmpty(),
        plan=_plan(full_coverage=True),
        strict_address=mode,
        context=context,
    )

    assert outcome.complete
    assert "bakeries" in outcome.geocode_degraded_slugs
    assert not outcome.authoritative
    assert db.seals == 0, "지역 장애 run이 봉인됐다"
    assert outcome.geocode_empty == 150
    assert context.metadata["mois_geocode_degraded"] is True
    assert context.metadata["mois_geo_probes"] >= 1
    assert context.metadata["mois_geo_probe_passes"] == context.metadata["mois_geo_probes"]
    # 빈 bjd 행은 어느 모드에서도 적재되지 않았다 — 다음 run이 "그대로"로 건너뛰지 않고 다시 한다.
    assert set(db.current) == {license_source_entity_id(r) for r in records[:150]}


async def test_off_mode_rows_with_an_empty_geocode_are_retried_next_run() -> None:
    """off 모드에서 빈 bjd로 commit하면 같은 payload는 영원히 "그대로"다 — 적재하지 않는다."""
    records = [
        _Record(service_slug="bakeries", mng_no=f"x-{i}", lon=126.9 + i / 1000, lat=37.5)
        for i in range(3)
    ]
    db = _FakeDb()
    first = await _run(
        records, db, geocoder=_Geocoder(empty_at_lon=126.901), strict_address="off"
    )
    assert first.geocode_empty == 1
    assert license_source_entity_id(records[1]) not in db.current

    # geo가 건강할 때 빈 답 → 표식. 다음 run은 30일 동안 그 행을 조회·적재하지 않는다.
    within = await _run(records, db, geocoder=_Geocoder(), strict_address="off")
    assert within.known_unresolvable == 1
    assert within.geocoded_rows == 0
    assert license_source_entity_id(records[1]) not in db.current

    db.today += chunked.UNRESOLVABLE_MARKER_RETRY_DAYS  # 표식이 낡았다 → 다시 확인
    converted = _Converted()
    second = await _run(
        records, db, geocoder=_Geocoder(), converted=converted, strict_address="off"
    )
    assert converted.ids == [license_source_entity_id(records[1])]
    assert second.geocode_empty == 0
    assert set(db.current) == {license_source_entity_id(r) for r in records}
    # 이제 풀린 행의 표식은 닫힌다 — 열린 표식이 끝없이 쌓이지 않는다(L-2).
    assert db.markers == {}
    assert len(db.resolved) == 1


async def test_repeated_trips_with_a_passing_probe_in_one_slug_mark_it_degraded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """비율 판정을 끄고(상한 1.0), K회 연속 "문턱 초과 + probe 통과"만으로 degraded가 된다."""
    monkeypatch.setattr(chunked, "MOIS_LOAD_CHUNK_SIZE", 25)
    records = _province_records(10, empty_province=False) + [
        _Record(service_slug="bakeries", mng_no=f"c-{i:04d}", lon=128.5 + i / 10_000, lat=35.8)
        # 첫 chunk는 좋은 행 10과 섞여 문턱을 넘지 않는다 — 문턱 초과 K회를 보려면 한 chunk 더.
        for i in range(25 * (chunked.GEO_PASSING_TRIPS_DEGRADE + 1))
    ]
    plan = replace(_plan(full_coverage=True), geocode_degraded_ratio=1.0)

    outcome = await _run(
        records, _FakeDb(), geocoder=_ProvinceLayerEmpty(), plan=plan, strict_address="drop"
    )

    assert outcome.geo_probe_passes >= chunked.GEO_PASSING_TRIPS_DEGRADE
    assert "bakeries" in outcome.geocode_degraded_slugs
    assert not outcome.authoritative


async def test_a_healthy_run_with_few_empty_rows_is_still_sealed() -> None:
    """상한(5%) 아래의 행 단위 빈 답은 정상이다 — 봉인을 막지 않는다."""
    records = [
        _Record(service_slug="bakeries", mng_no=f"h-{i:04d}", lon=126.9 + i / 10_000, lat=37.5)
        for i in range(400)
    ]
    db = _FakeDb()
    outcome = await _run(
        records,
        db,
        geocoder=_Geocoder(empty_at_lon=126.9005),
        plan=_plan(full_coverage=True),
        strict_address="drop",
    )
    assert outcome.geocode_empty == 1
    assert outcome.geocode_degraded_slugs == ()
    assert outcome.authoritative
    assert db.seals == 1


# -- 최종 설계: 역지오코딩 불가 표식·조회 행 분모·연속 degraded --------------------------


def _land(count: int, *, prefix: str = "a", slug: str = "bakeries") -> list[_Record]:
    return [
        _Record(service_slug=slug, mng_no=f"{prefix}-{i:05d}", lon=126.9 + i / 100_000, lat=37.5)
        for i in range(count)
    ]


def _sea(count: int, *, prefix: str = "s", slug: str = "bakeries") -> list[_Record]:
    return [
        _Record(service_slug=slug, mng_no=f"{prefix}-{i:05d}", lon=129.6 + i / 100_000, lat=35.0)
        for i in range(count)
    ]


class _SeaIsEmpty(_Geocoder):
    """경도 129.5 이상(해상)은 언제나 빈 답, 나머지(기준점 포함)는 답한다."""

    async def __call__(self, coord: Coordinate) -> Address:
        self.calls.append(coord)
        if float(coord.lon) >= 129.5:
            return Address()
        return Address(bjd_code="1111010100", sigungu_code="11110", sido_code="11")


async def test_persistent_empties_are_marked_once_then_skipped_and_the_run_seals(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """정상 상태: 미변경 행이 대부분이고 해상 좌표 60행이 몰려 있다. 첫 run이 표식을 남기면
    다음 run은 그 행을 조회하지 않고, degraded가 아니며, 봉인한다(최종 델타 리뷰 MED-1)."""
    monkeypatch.setattr(chunked, "MOIS_LOAD_CHUNK_SIZE", 50)
    # 해상 좌표 60행이 2,000행 사이에 흩어져 있다(낮은 밀도) — 문턱을 넘지 않으므로 표식이 남는다.
    # 몰려 있어 문턱을 넘는 빈 답은 지역 장애와 구별할 수 없으므로 표식을 남기지 않는다
    # (아래 테스트).
    land = _land(2000)
    sea = _sea(60)
    records = []
    for index, row in enumerate(land):
        records.append(replace(row, mng_no=f"m-{len(records):05d}"))
        if index % 33 == 0 and sea:
            records.append(replace(sea.pop(), mng_no=f"m-{len(records):05d}"))
    assert not sea
    db = _FakeDb()

    first = await _run(
        records, db, geocoder=_SeaIsEmpty(), plan=_plan(full_coverage=True), strict_address="drop"
    )
    assert first.geocode_empty == 60
    assert first.geo_probes == 0, "낮은 밀도의 해상 좌표가 장애 문턱을 넘었다"
    assert len(db.markers) == 60

    geocoder = _SeaIsEmpty()
    second = await _run(
        records, db, geocoder=geocoder, plan=_plan(full_coverage=True), strict_address="drop"
    )

    assert second.known_unresolvable == 60
    assert second.geocoded_rows == 0
    assert geocoder.calls == [], "표식이 맞는 행을 다시 조회했다"
    assert second.geocode_degraded_slugs == ()
    assert second.authoritative
    assert db.seals >= 1


async def test_a_changed_payload_does_not_match_the_old_marker() -> None:
    records = _sea(3)
    db = _FakeDb()
    await _run(records, db, geocoder=_SeaIsEmpty(), strict_address="drop")

    changed = [replace(records[0], place_name="상호 변경"), *records[1:]]
    geocoder = _SeaIsEmpty()
    outcome = await _run(changed, db, geocoder=geocoder, strict_address="drop")

    assert outcome.known_unresolvable == 2
    assert [float(c.lon) for c in geocoder.calls] == [float(records[0].lon)]


async def test_steady_state_regional_outage_is_judged_on_geocoded_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """미변경 2,000행 + 빈 지역의 새 행 100. 관측 행 분모(100/2,100=4.8%)면 놓치고, 조회 행 분모
    (100/100)면 잡는다(델타 리뷰 LOW-1)."""
    monkeypatch.setattr(chunked, "MOIS_LOAD_CHUNK_SIZE", 50)
    land = _land(2000)
    db = _FakeDb()
    await _run(land, db, geocoder=_SeaIsEmpty(), plan=_plan(full_coverage=True))

    new_region = [
        _Record(service_slug="bakeries", mng_no=f"z-{i:05d}", lon=128.5 + i / 100_000, lat=35.8)
        for i in range(100)
    ]
    outcome = await _run(
        land + new_region,
        db,
        geocoder=_ProvinceLayerEmpty(),
        plan=_plan(full_coverage=True),
        strict_address="drop",
    )

    assert outcome.records_unchanged == 2000
    assert outcome.geocoded_rows == 100
    assert "bakeries" in outcome.geocode_degraded_slugs
    assert not outcome.authoritative


async def test_run_wide_ratio_catches_what_no_single_slug_can(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """업종마다 조회 40행(표본 50 미만)이라 업종 판정은 못 하지만 run 전체 120행 중 12%는 잡는다."""
    monkeypatch.setattr(chunked, "MOIS_LOAD_CHUNK_SIZE", 50)
    records: list[_Record] = []
    for slug in ("bakeries", "general_restaurants", "rest_cafes"):
        records += _land(36, prefix=f"{slug[:2]}a", slug=slug)
        records += _sea(4, prefix=f"{slug[:2]}s", slug=slug)
    plan = replace(
        _plan(full_coverage=True),
        service_slugs=("bakeries", "general_restaurants", "rest_cafes"),
    )

    outcome = await _run(records, _FakeDb(), geocoder=_SeaIsEmpty(), plan=plan)

    assert outcome.geocoded_rows == 120
    assert outcome.geocode_degraded_slugs == ("(run)",)
    assert not outcome.authoritative


class _HistoryContext(_Context):
    """앞선 전체 run들(최신순)을 아는 run context."""

    def __init__(
        self,
        previous_tags: dict[str, str] | None = None,
        *,
        history: list[dict[str, str]] | None = None,
        run_id: str = "run-now",
    ) -> None:
        super().__init__()
        self.run_id = run_id
        self.tagged: dict[str, str] = {}
        runs = history if history is not None else ([previous_tags] if previous_tags else [])
        previous = [
            SimpleNamespace(run_id=f"run-before-{index}", tags=tags)
            for index, tags in enumerate(runs)
        ]

        def _get_runs(*, filters: Any, limit: int) -> list[Any]:
            del limit
            assert filters.tags[chunked.MOIS_LOAD_FULL_COVERAGE_TAG] == "true"
            # 사슬의 budget_exhausted run을 빼면 안 된다 — outcome으로 거르지 않는다.
            assert MOIS_LOAD_OUTCOME_TAG not in filters.tags
            return [SimpleNamespace(run_id=self.run_id, tags=self.tagged), *previous]

        self.instance = SimpleNamespace(
            get_runs=_get_runs,
            add_run_tags=lambda _run_id, tags: self.tagged.update(tags),
            get_run_record_by_id=lambda _run_id: None,
        )


@pytest.mark.parametrize(
    ("previous_tags", "fails"),
    [
        ({chunked.MOIS_LOAD_GEOCODE_DEGRADED_TAG: "bakeries"}, True),
        ({}, False),
        (None, False),
    ],
    ids=["previous-degraded", "previous-healthy", "no-previous"],
)
async def test_a_second_consecutive_degraded_full_run_fails_red(
    monkeypatch: pytest.MonkeyPatch, previous_tags: dict[str, str] | None, fails: bool
) -> None:
    monkeypatch.setattr(chunked, "MOIS_LOAD_CHUNK_SIZE", 50)
    records = _province_records(150, empty_province=True)
    context = _HistoryContext(previous_tags)

    async def _go() -> chunked.MoisChunkedLoadOutcome:
        return await _run(
            records,
            _FakeDb(),
            geocoder=_ProvinceLayerEmpty(),
            plan=_plan(full_coverage=True),
            strict_address="drop",
            context=context,
        )

    if fails:
        with pytest.raises(Failure, match="연속 두 전체 run") as caught:
            await _go()
        assert caught.value.allow_retries is False
    else:
        outcome = await _go()
        assert "bakeries" in outcome.geocode_degraded_slugs
    # 실패해도 이 run은 degraded·complete·전체로 tag된다 — 다음 판정의 근거이고 사슬을 막지 않는다.
    assert context.tagged[MOIS_LOAD_OUTCOME_TAG] == MOIS_LOAD_OUTCOME_COMPLETE
    assert "bakeries" in context.tagged[chunked.MOIS_LOAD_GEOCODE_DEGRADED_TAG].split(",")
    assert context.tagged[chunked.MOIS_LOAD_FULL_COVERAGE_TAG] == "true"


def test_degraded_ratio_setting_must_be_positive() -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        KorTravelMapSettings(mois_geocode_degraded_ratio=0)


# -- 최종 리뷰 MED-1: 지역 장애는 표식이 되지 않고, 사슬 전체를 비교한다 ---------------------


async def test_regional_outage_with_a_passing_probe_leaves_no_markers_and_turns_red(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(chunked, "MOIS_LOAD_CHUNK_SIZE", 50)
    records = _province_records(150, empty_province=True)
    db = _FakeDb()

    first_context = _HistoryContext(run_id="run-1")
    first = await _run(
        records,
        db,
        geocoder=_ProvinceLayerEmpty(),
        plan=_plan(full_coverage=True),
        strict_address="drop",
        context=first_context,
    )
    assert "bakeries" in first.geocode_degraded_slugs
    assert first.geo_probe_passes >= 1
    assert db.markers == {}, "probe를 통과한 지역 장애의 행에 표식을 남겼다"

    # 다음 run은 그 행을 다시 조회한다 — 여전히 degraded이고, 연속 두 번이므로 붉다.
    second_context = _HistoryContext(history=[first_context.tagged], run_id="run-2")
    with pytest.raises(Failure, match="연속 두 전체 run"):
        await _run(
            records,
            db,
            geocoder=_ProvinceLayerEmpty(),
            plan=_plan(full_coverage=True),
            strict_address="drop",
            context=second_context,
        )
    assert "bakeries" in second_context.tagged[chunked.MOIS_LOAD_GEOCODE_DEGRADED_TAG].split(",")
    assert db.markers == {}


@pytest.mark.parametrize(
    ("history", "fails"),
    [
        (
            [
                {MOIS_LOAD_OUTCOME_TAG: MOIS_LOAD_OUTCOME_BUDGET_EXHAUSTED},
                {
                    MOIS_LOAD_OUTCOME_TAG: MOIS_LOAD_OUTCOME_BUDGET_EXHAUSTED,
                    chunked.MOIS_LOAD_GEOCODE_DEGRADED_TAG: "bakeries",
                },
                {MOIS_LOAD_OUTCOME_TAG: MOIS_LOAD_OUTCOME_COMPLETE},
            ],
            True,
        ),
        (
            [
                {MOIS_LOAD_OUTCOME_TAG: MOIS_LOAD_OUTCOME_COMPLETE},
                {
                    MOIS_LOAD_OUTCOME_TAG: MOIS_LOAD_OUTCOME_COMPLETE,
                    chunked.MOIS_LOAD_GEOCODE_DEGRADED_TAG: "bakeries",
                },
            ],
            False,
        ),
    ],
    ids=["degraded-budget-run-in-chain", "older-than-last-complete"],
)
async def test_consecutive_check_spans_the_chain_back_to_the_last_complete_run(
    monkeypatch: pytest.MonkeyPatch, history: list[dict[str, str]], fails: bool
) -> None:
    monkeypatch.setattr(chunked, "MOIS_LOAD_CHUNK_SIZE", 50)
    context = _HistoryContext(history=history)

    async def _go() -> chunked.MoisChunkedLoadOutcome:
        return await _run(
            _province_records(150, empty_province=True),
            _FakeDb(),
            geocoder=_ProvinceLayerEmpty(),
            plan=_plan(full_coverage=True),
            strict_address="drop",
            context=context,
        )

    if fails:
        with pytest.raises(Failure, match="연속 두 전체 run"):
            await _go()
    else:
        assert "bakeries" in (await _go()).geocode_degraded_slugs


@pytest.mark.parametrize("destroyed", [True, False])
async def test_marker_write_failure_is_fatal_only_when_it_destroyed_the_transaction(
    destroyed: bool,
) -> None:
    from kortravelmap.core.exceptions import IntegrityFindingPersistenceError

    db = _FakeDb(
        marker_write_error=IntegrityFindingPersistenceError(
            provider="python-mois-api",
            dataset_key="mois_license_features_bulk",
            observed_count=1,
            unique_count=1,
            error_type="OperationalError",
            transaction_destroyed=destroyed,
        )
    )
    records = _sea(1)

    if destroyed:
        with pytest.raises(IntegrityFindingPersistenceError):
            await _run(records, db, geocoder=_SeaIsEmpty(), strict_address="drop")
    else:
        outcome = await _run(records, db, geocoder=_SeaIsEmpty(), strict_address="drop")
        assert outcome.complete
        assert db.markers == {}


async def test_a_dense_cluster_that_trips_the_detector_is_not_marked_even_when_healthy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """문턱을 넘은(probe 통과) chunk의 빈 답은 지역 장애와 구별할 수 없다 — 업종이 degraded가
    아니어도 표식을 남기지 않는다. 다음 run이 다시 조회할 뿐이다(비율 2%라 봉인은 막지 않는다)."""
    monkeypatch.setattr(chunked, "MOIS_LOAD_CHUNK_SIZE", 50)
    land = _land(2000)
    records = [replace(r, mng_no=f"m-{i:05d}") for i, r in enumerate(land[:1000])]
    records += [replace(r, mng_no=f"m-{1000 + i:05d}") for i, r in enumerate(_sea(40))]
    records += [replace(r, mng_no=f"m-{1040 + i:05d}") for i, r in enumerate(land[1000:])]
    db = _FakeDb()

    outcome = await _run(
        records, db, geocoder=_SeaIsEmpty(), plan=_plan(full_coverage=True), strict_address="drop"
    )

    assert outcome.geo_probe_passes == 1
    assert outcome.geocode_degraded_slugs == ()
    assert outcome.authoritative
    assert db.markers == {}


async def test_a_slug_degraded_by_ratio_alone_leaves_no_markers() -> None:
    """문턱은 넘지 않았지만(낮은 밀도) 조회 대비 빈 답이 10%라 degraded — 표식을 남기지 않는다."""
    records: list[_Record] = []
    land = _land(180)
    sea = _sea(20)
    for index, row in enumerate(land):
        records.append(replace(row, mng_no=f"m-{len(records):05d}"))
        if index % 9 == 0 and sea:
            records.append(replace(sea.pop(), mng_no=f"m-{len(records):05d}"))
    db = _FakeDb()

    outcome = await _run(
        records, db, geocoder=_SeaIsEmpty(), plan=_plan(full_coverage=True), strict_address="drop"
    )

    assert outcome.geo_probes == 0
    assert "bakeries" in outcome.geocode_degraded_slugs
    assert db.markers == {}


# -- narrow 리뷰 MED-1·L-1·L-3 ---------------------------------------------------------


def _interleaved(slug: str, good: int, empty: int) -> list[_Record]:
    """같은 업종 안에 빈 답 행을 낮은 밀도로 흩는다(문턱을 넘지 않게)."""
    rows: list[_Record] = []
    land = _land(good, slug=slug)
    sea = _sea(empty, slug=slug)
    step = max(1, good // max(1, empty))
    for index, row in enumerate(land):
        rows.append(replace(row, mng_no=f"{slug[:3]}-{len(rows):05d}"))
        if index % step == 0 and sea:
            rows.append(replace(sea.pop(), mng_no=f"{slug[:3]}-{len(rows):05d}"))
    rows += [replace(r, mng_no=f"{slug[:3]}-{len(rows) + i:05d}") for i, r in enumerate(sea)]
    return rows


_SMALL_SLUGS: Final = ("lodgings", "rest_cafes", "tourist_restaurants")


def _outage_plan() -> MoisLoadPlan:
    return replace(
        _plan(full_coverage=True),
        service_slugs=tuple(sorted({"bakeries", "general_restaurants", *_SMALL_SLUGS})),
    )


async def test_small_slugs_of_the_same_outage_get_no_markers_when_a_large_slug_degrades(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """큰 업종 하나가 degraded이고 run 전체는 상한 아래 — 표본이 모자라 스스로 판정받지 못한 작은
    업종들의 빈 답은 같은 지역 장애일 수 있으므로 표식을 남기지 않는다(narrow 리뷰 MED-1)."""
    monkeypatch.setattr(chunked, "MOIS_LOAD_CHUNK_SIZE", 50)
    records = _interleaved("bakeries", 50, 10) + _land(2000, prefix="g", slug="general_restaurants")
    for slug in _SMALL_SLUGS:
        records += _interleaved(slug, 9, 1)
    records.sort(key=lambda r: (r.service_slug, r.mng_no))
    db = _FakeDb()

    outcome = await _run(
        records, db, geocoder=_SeaIsEmpty(), plan=_outage_plan(), strict_address="drop"
    )

    assert outcome.geo_probes == 0
    assert outcome.geocode_degraded_slugs == ("bakeries",), "run 전체는 상한 아래여야 한다"
    assert outcome.geocode_empty == 10 + len(_SMALL_SLUGS)
    assert db.markers == {}, "degraded run에서 표본 미달 업종에 표식을 남겼다"


async def test_run_wide_ratio_is_evaluated_even_after_a_slug_degraded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(chunked, "MOIS_LOAD_CHUNK_SIZE", 50)
    records = _interleaved("bakeries", 50, 10)
    for slug in _SMALL_SLUGS:
        records += _interleaved(slug, 6, 4)
    records.sort(key=lambda r: (r.service_slug, r.mng_no))
    plan = replace(_plan(full_coverage=True), service_slugs=("bakeries", *_SMALL_SLUGS))

    outcome = await _run(
        records, _FakeDb(), geocoder=_SeaIsEmpty(), plan=plan, strict_address="drop"
    )

    assert "bakeries" in outcome.geocode_degraded_slugs
    assert "(run)" in outcome.geocode_degraded_slugs


async def test_a_chain_longer_than_the_lookback_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(chunked, "MOIS_LOAD_CHUNK_SIZE", 50)
    monkeypatch.setattr(chunked, "_CHAIN_LOOKBACK_LIMIT", 5)
    context = _HistoryContext(
        history=[{MOIS_LOAD_OUTCOME_TAG: MOIS_LOAD_OUTCOME_BUDGET_EXHAUSTED}] * 10
    )

    with pytest.raises(Failure, match="unknown"):
        await _run(
            _province_records(150, empty_province=True),
            _FakeDb(),
            geocoder=_ProvinceLayerEmpty(),
            plan=_plan(full_coverage=True),
            strict_address="drop",
            context=context,
        )


@pytest.mark.parametrize("destroyed", [True, False])
async def test_resolve_failure_is_fatal_only_when_it_destroyed_the_transaction(
    destroyed: bool,
) -> None:
    from kortravelmap.core.exceptions import IntegrityFindingPersistenceError

    db = _FakeDb(
        resolve_error=IntegrityFindingPersistenceError(
            provider="(resolve)",
            dataset_key="x",
            observed_count=1,
            unique_count=1,
            error_type="OperationalError",
            transaction_destroyed=destroyed,
        )
    )
    records = _land(2)

    if destroyed:
        with pytest.raises(IntegrityFindingPersistenceError):
            await _run(records, db, geocoder=_Geocoder())
    else:
        assert (await _run(records, db, geocoder=_Geocoder())).complete


def test_run_outcome_tag_is_skipped_for_a_direct_asset_context() -> None:
    """``build_asset_context``의 run id(``EPHEMERAL``)는 instance에 없다 — tag 쓰기가 터지지 않는다

    통합 테스트가 asset을 직접 호출하는 경로(test_dagster_feature_etl)를 그대로 흉내낸다.
    """
    from dagster import build_asset_context

    context = build_asset_context(resources={})
    chunked._tag_run_outcome(context, {MOIS_LOAD_OUTCOME_TAG: MOIS_LOAD_OUTCOME_COMPLETE})


# -- geo 토큰(ADR-109 결정 4, T-GR-03) ---------------------------------------------------------

_TOKEN: Final[str] = "dd1-" + "1" * 32
_OTHER_TOKEN: Final[str] = "dd1-" + "2" * 32


class _ObservingGeocoder(_Geocoder):
    """응답마다 ``data_token``을 관측 계수에 남긴다. ``switch_after``번째 호출부터 다른 토큰."""

    def __init__(self, *, switch_after: int | None = None) -> None:
        super().__init__()
        self.stats = SimpleNamespace(observed_data_tokens=set())
        self._switch_after = switch_after

    async def __call__(self, coord: Coordinate) -> Address:
        switched = self._switch_after is not None and len(self.calls) >= self._switch_after
        self.stats.observed_data_tokens.add(_OTHER_TOKEN if switched else _TOKEN)
        return await super().__call__(coord)


def _current() -> Any:
    from kortravelmap.dto.geo_dataset import DatasetRef

    return DatasetRef(version_token="dv1-" + "a" * 32, data_token=_TOKEN)


async def test_every_token_condition_receives_the_run_token() -> None:
    """"그대로" 판정·빈 답 표식·적재 셋 다 run 시작에 읽은 토큰을 받는다(chunk마다)."""
    db = _FakeDb()
    await _run(
        _snapshot(per_slug=4), db, geocoder=_ObservingGeocoder(), current_dataset=_current()
    )

    kinds = {kind for kind, _ in db.tokens_seen}
    assert kinds == {"unchanged", "marker", "load"}
    assert all(token == _TOKEN for _, token in db.tokens_seen), db.tokens_seen


async def test_without_a_current_dataset_no_token_condition_applies() -> None:
    db = _FakeDb()
    await _run(_snapshot(per_slug=4), db, geocoder=_ObservingGeocoder())
    assert db.tokens_seen
    assert all(token is None for _, token in db.tokens_seen)


async def test_a_geocoder_without_observation_stats_fails_closed() -> None:
    """관측 계수가 없는 역지오코더면 전환을 볼 수 없다 — 토큰 조건도 스탬프도 쓰지 않는다."""
    db = _FakeDb()
    await _run(_snapshot(per_slug=4), db, geocoder=_Geocoder(), current_dataset=_current())
    assert all(token is None for _, token in db.tokens_seen)


async def test_mid_run_dataset_switch_stops_using_the_token_from_the_next_chunk_on() -> None:
    """run 도중 geo가 데이터셋을 바꾸면 그 뒤 chunk는 토큰을 쓰지 않는다(옛 토큰으로 봉인 안 함)."""
    db = _FakeDb()
    await _run(
        _snapshot(per_slug=6),
        db,
        geocoder=_ObservingGeocoder(switch_after=2),
        current_dataset=_current(),
    )

    loads = [token for kind, token in db.tokens_seen if kind == "load"]
    assert loads[0] == _TOKEN
    assert None in loads
    # 한 번 전환을 보면 다시 토큰을 쓰지 않는다.
    first_none = loads.index(None)
    assert all(token is None for token in loads[first_none:])
    later = [token for kind, token in db.tokens_seen[db.tokens_seen.index(("load", None)) :]]
    assert all(token is None for token in later)
